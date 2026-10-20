# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for SwarmTaskAdapter, Tri-Model channel routing, and runtime discovery."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
antigravity_path = str(REPO_ROOT / ".antigravity")
if antigravity_path not in sys.path:
    sys.path.insert(0, antigravity_path)

from harness2 import config
from harness2.core import proposer, spec
from harness2.core.spec import BenchmarkAdapter, BenchPrompts, BenchSpec, ChannelSpec


class TestSwarmAdapterAndChannels(unittest.TestCase):
    def test_channels_and_install_modes(self):
        """1) CHANNELS includes antigravity channels and INSTALL_MODES includes antigravity_root."""
        self.assertIn("antigravity", spec.CHANNELS)
        self.assertIn("antigravity_opus", spec.CHANNELS)
        self.assertIn("antigravity_root", spec.INSTALL_MODES)
        self.assertIn("antigravity", config.PROPOSER_MODEL_BY_CHANNEL)
        self.assertIn("antigravity_opus", config.PROPOSER_MODEL_BY_CHANNEL)

    def test_benchspec_asymmetric_tri_model(self):
        """2) Asymmetric Tri-Model BenchSpec.channels configuration validates cleanly."""
        channels = {
            "proposer": ChannelSpec("antigravity", "gemini-4-argon"),
            "selector": ChannelSpec("antigravity_opus", "claude-opus-5-5"),
        }
        prompts = BenchPrompts(work="Codebase feature delivery")
        b_spec = BenchSpec(
            name="swarm",
            runs_root=Path("runs"),
            install_mode="antigravity_root",
            prompts=prompts,
            channels=channels,
        )
        self.assertEqual(b_spec.channels["proposer"].kind, "antigravity")
        self.assertEqual(b_spec.channels["proposer"].model, "gemini-4-argon")
        self.assertEqual(b_spec.channels["selector"].kind, "antigravity_opus")
        self.assertEqual(b_spec.channels["selector"].model, "claude-opus-5-5")

        # Test resolve_channel_model
        cs_prop = spec.resolve_channel_model("antigravity", "gemini-4-argon")
        self.assertEqual(cs_prop.kind, "antigravity")
        self.assertEqual(cs_prop.model, "gemini-4-argon")

        cs_sel = spec.resolve_channel_model("antigravity_opus", "claude-opus-5-5")
        self.assertEqual(cs_sel.kind, "antigravity_opus")
        self.assertEqual(cs_sel.model, "claude-opus-5-5")

    def test_discover_antigravity_runtime_priority(self):
        """3) discover_antigravity_runtime resolves in priority order path-independently."""
        # Check function exists
        self.assertTrue(
            hasattr(proposer, "discover_antigravity_runtime"),
            "proposer.discover_antigravity_runtime must be defined",
        )

        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            fake_agy = temp_root / "bin" / ("agy.exe" if os.name == "nt" else "agy")
            fake_agy.parent.mkdir(parents=True, exist_ok=True)
            fake_agy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            fake_ls = temp_root / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe"
            fake_ls.parent.mkdir(parents=True, exist_ok=True)
            fake_ls.write_text("binary", encoding="utf-8")

            fake_claude = temp_root / "claude_bin" / ("claude.cmd" if os.name == "nt" else "claude")
            fake_claude.parent.mkdir(parents=True, exist_ok=True)
            fake_claude.write_text("echo claude", encoding="utf-8")

            # Priority 1: HARNESS2_ANTIGRAVITY_CMD env override
            with mock.patch.dict(
                os.environ,
                {"HARNESS2_ANTIGRAVITY_CMD": "custom_antigravity_cmd --flag"},
                clear=False,
            ):
                res = proposer.discover_antigravity_runtime()
                self.assertEqual(res.get("kind"), "env")
                self.assertIn("custom_antigravity_cmd", str(res.get("cmd")))

            # Priority 2: shutil.which("agy")
            with mock.patch.dict(os.environ, {"HARNESS2_ANTIGRAVITY_CMD": ""}, clear=False):
                with mock.patch("shutil.which", side_effect=lambda x: str(fake_agy) if "agy" in x else None):
                    res = proposer.discover_antigravity_runtime()
                    self.assertEqual(res.get("kind"), "agy")
                    self.assertEqual(Path(res.get("path")), fake_agy)

            # Priority 3: LocalAppData language_server.exe
            with mock.patch.dict(
                os.environ,
                {"HARNESS2_ANTIGRAVITY_CMD": "", "LOCALAPPDATA": str(temp_root)},
                clear=False,
            ):
                with mock.patch("shutil.which", return_value=None):
                    res = proposer.discover_antigravity_runtime()
                    self.assertEqual(res.get("kind"), "language_server")
                    self.assertEqual(Path(res.get("path")), fake_ls)

            # Priority 4: Fallback to shutil.which("claude")
            with mock.patch.dict(
                os.environ,
                {"HARNESS2_ANTIGRAVITY_CMD": "", "LOCALAPPDATA": str(temp_root / "nonexistent")},
                clear=False,
            ):
                with mock.patch("shutil.which", side_effect=lambda x: str(fake_claude) if "claude" in x else None):
                    res = proposer.discover_antigravity_runtime()
                    self.assertEqual(res.get("kind"), "claude")
                    self.assertEqual(Path(res.get("path")), fake_claude)

    def test_proposer_env_and_claude_cli_model_flag(self):
        """4) proposer.py:env() preserves native auth when project is empty, and passes --model."""
        cs = ChannelSpec("claude_cli", "claude-opus-5-5")

        # When project is empty: auth variables must be preserved and CLAUDE_CODE_USE_VERTEX must not be 1
        with mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-ant-test-key-12345",
                "ANTHROPIC_AUTH_TOKEN": "token-xyz",
            },
            clear=False,
        ):
            prop_no_project = proposer.Proposer(spec=cs, project="")
            env_out = prop_no_project.env()
            self.assertEqual(env_out.get("ANTHROPIC_API_KEY"), "sk-ant-test-key-12345")
            self.assertEqual(env_out.get("ANTHROPIC_AUTH_TOKEN"), "token-xyz")
            self.assertNotEqual(env_out.get("CLAUDE_CODE_USE_VERTEX"), "1")

        # When project is set: Vertex mode is activated
        prop_with_project = proposer.Proposer(spec=cs, project="my-vertex-project")
        env_vertex = prop_with_project.env()
        self.assertEqual(env_vertex.get("CLAUDE_CODE_USE_VERTEX"), "1")
        self.assertEqual(env_vertex.get("ANTHROPIC_VERTEX_PROJECT_ID"), "my-vertex-project")
        self.assertNotIn("ANTHROPIC_API_KEY", env_vertex)

        # Test _claude_cli passes --model
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout='{"result": "mock answer", "total_cost_usd": 0.01}'
                )
                text, cost, err = prop_no_project._claude_cli(cwd, "test mission", "", 60)
                self.assertEqual(text, "mock answer")
                # Assert --model claude-opus-5-5 was passed in args
                call_args = mock_run.call_args[0][0]
                self.assertIn("--model", call_args)
                model_idx = call_args.index("--model")
                self.assertEqual(call_args[model_idx + 1], "claude-opus-5-5")

    def test_antigravity_call_invocations(self):
        """5) proposer.py:_antigravity_call supports gemini-4-argon and claude-opus-5-5."""
        cs_argon = ChannelSpec("antigravity", "gemini-4-argon")
        prop_argon = proposer.Proposer(spec=cs_argon, project="")

        cs_opus = ChannelSpec("antigravity_opus", "claude-opus-5-5")
        prop_opus = proposer.Proposer(spec=cs_opus, project="")

        # Both route through call()
        with tempfile.TemporaryDirectory() as td:
            audit_dir = Path(td) / "audit"
            prop_argon.audit_dir = audit_dir
            prop_opus.audit_dir = audit_dir

            # Mock _antigravity_call returning answer
            with mock.patch.object(
                prop_argon,
                "_antigravity_call",
                return_value=("Argon improvement proposal", 0.005, ""),
            ) as mock_ag:
                reply = prop_argon.call("Propose improvement", None, "label_inv1")
                self.assertTrue(reply.ok)
                self.assertEqual(reply.text, "Argon improvement proposal")
                self.assertEqual(reply.channel, "antigravity")
                mock_ag.assert_called_once()

            with mock.patch.object(
                prop_opus,
                "_antigravity_call",
                return_value=("Opus selection verdict: A", 0.02, ""),
            ) as mock_op:
                reply = prop_opus.call("Select candidate", None, "label_sel")
                self.assertTrue(reply.ok)
                self.assertEqual(reply.text, "Opus selection verdict: A")
                self.assertEqual(reply.channel, "antigravity_opus")
                mock_op.assert_called_once()

        # Test actual _antigravity_call execution with output/answer.md file
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            out_dir = cwd / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "answer.md").write_text("Detailed Antigravity Answer", encoding="utf-8")

            # Mock subprocess to do nothing since answer.md already exists
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )
                text, cost, err = prop_argon._antigravity_call(cwd, "Mission", "System", 30)
                self.assertEqual(text, "Detailed Antigravity Answer")
                self.assertEqual(err, "")
                # MISSION.md must have been created in cwd
                self.assertTrue((cwd / "MISSION.md").is_file())

    def test_swarm_task_adapter_protocol_worktree_and_reuse_base(self):
        """6) SwarmTaskAdapter implements BenchmarkAdapter with git worktree isolation and reuse_base."""
        from harness2.adapter_swarm import SwarmTaskAdapter

        with tempfile.TemporaryDirectory() as td:
            repo_dir = Path(td) / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            runs_root = Path(td) / "runs"
            runs_root.mkdir(parents=True, exist_ok=True)

            # Initialize a git repo with a commit
            subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )
            (repo_dir / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
            )

            # Create adapter
            adapter = SwarmTaskAdapter(
                repo_dir=repo_dir,
                runs_root=runs_root,
                task_id="task_1",
                task_prompt="Implement feature X",
            )

            # Protocol conformance
            self.assertTrue(isinstance(adapter, BenchmarkAdapter))
            self.assertEqual(adapter.tasks(), ["task_1"])
            self.assertEqual(adapter.task_prompt("task_1"), "Implement feature X")

            # Test worktree execution and cleanup
            # We track worktree lifecycle
            created_worktrees = []
            cleaned_up = []

            def mock_executor(worktree_path: Path, run_dir: Path, task_id: str):
                created_worktrees.append(worktree_path)
                self.assertTrue(worktree_path.is_dir())
                # Deliverable created in run_dir
                deliv_dir = run_dir / "deliverables"
                deliv_dir.mkdir(parents=True, exist_ok=True)
                (deliv_dir / "output.txt").write_text("Feature X delivered", encoding="utf-8")
                (run_dir / "trajectory.txt").write_text(
                    "[ACTION] edit file\n[OBSERVATION] OK\n", encoding="utf-8"
                )

            adapter.executor_fn = mock_executor
            run_dir = adapter.execute("task_1", None, "run_wt_001")
            self.assertTrue(run_dir.is_dir())
            self.assertTrue(adapter.delivered(run_dir))
            self.assertIn("Feature X delivered", adapter.deliverable_text(run_dir))
            self.assertIn("[ACTION]", adapter.trajectory(run_dir, obs_trunc=50000))

            # Verify the temporary git worktree was cleaned up
            self.assertEqual(len(created_worktrees), 1)
            self.assertFalse(created_worktrees[0].exists(), "Worktree directory must be cleaned up in finally:")

            # Test reuse_base=True
            failed_run_dir = Path(td) / "failed_base_run"
            failed_run_dir.mkdir(parents=True, exist_ok=True)
            (failed_run_dir / "trajectory.txt").write_text(
                "[ACTION] edit file\n[ERROR] test failure\n", encoding="utf-8"
            )

            adapter_reuse = SwarmTaskAdapter(
                repo_dir=repo_dir,
                runs_root=runs_root,
                task_id="task_1",
                task_prompt="Implement feature X",
                reuse_base=True,
                captured_base_dir=failed_run_dir,
            )

            execution_called = []
            adapter_reuse.executor_fn = lambda w, r, t: execution_called.append(True)

            reused_dir = adapter_reuse.execute("task_1", None, "base1")
            self.assertEqual(reused_dir.resolve(), failed_run_dir.resolve())
            self.assertEqual(len(execution_called), 0, "execute() must reuse captured base without re-running")
            self.assertIn("[ERROR] test failure", adapter_reuse.trajectory(reused_dir, obs_trunc=50000))


if __name__ == "__main__":
    unittest.main()
