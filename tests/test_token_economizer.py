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

"""Unit and integration tests for .antigravity/scripts/token_economizer.py (M2, M3, M5)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
AG_SCRIPTS = REPO_ROOT / ".antigravity" / "scripts"
if str(AG_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AG_SCRIPTS))

import token_economizer as te  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class TestFeatureFlagIsolation(unittest.TestCase):
    def test_env_flag_disabled_short_circuits_with_zero_writes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "demo_repo"
            repo.mkdir()
            state_root = Path(td) / "state"
            transcript = Path(td) / "t.jsonl"
            _write_jsonl(
                transcript,
                [
                    {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>run tests</USER_REQUEST>"},
                    {
                        "type": "PLANNER_RESPONSE",
                        "step_index": 1,
                        "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest"}}],
                        "usage": {"input_tokens": 500, "cache_read_tokens": 1000, "output_tokens": 100},
                    },
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 2, "text": "Command exited with code 127"},
                ],
            )
            with mock.patch.dict(os.environ, {"ASW_TOKEN_ECONOMIZER_ENABLED": "0"}):
                self.assertFalse(te.is_enabled(repo))
                self.assertEqual(te.status(repo=repo, state_root=state_root), {"enabled": False, "status": "disabled"})
                self.assertEqual(
                    te.fold_transcript(transcript, repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.session_start(repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.check_turn(transcript, repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.get_microskills(repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.forget_fact("any", repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.unforget_fact("any", repo=repo, state_root=state_root),
                    {"enabled": False, "status": "disabled"},
                )
                self.assertEqual(
                    te.run_benchmark(),
                    {"enabled": False, "status": "disabled"},
                )
            self.assertFalse(state_root.exists(), "Disabled mode must perform zero disk writes")

    def test_decision_config_disabled_and_cli_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "cfg_repo"
            ag_dir = repo / ".antigravity"
            ag_dir.mkdir(parents=True)
            (ag_dir / "decision_config.json").write_text(
                json.dumps({"enabled": True, "token_economizer_enabled": False}),
                encoding="utf-8",
            )
            state_root = Path(td) / "state"
            self.assertFalse(te.is_enabled(repo))

            env = dict(os.environ)
            env.pop("ASW_TOKEN_ECONOMIZER_ENABLED", None)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(AG_SCRIPTS / "token_economizer.py"),
                    "--status",
                    "--json",
                    "--repo",
                    str(repo),
                    "--state-root",
                    str(state_root),
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload, {"enabled": False, "status": "disabled"})
            self.assertFalse(state_root.exists())


class TestTranscriptReaderAndEffectiveTokens(unittest.TestCase):
    def test_antigravity_read_incremental_and_tool_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "transcript.jsonl"
            rows = [
                {
                    "type": "USER_INPUT",
                    "step_index": 0,
                    "text": "<USER_REQUEST>\nFix failing suite\n</USER_REQUEST>",
                },
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 1,
                    "tool_calls": [
                        {"id": "c1", "name": "view_file", "arguments": {"AbsolutePath": "src/app.py"}},
                        {"id": "c2", "name": "replace_file_content", "arguments": {"TargetFile": "src/app.py"}},
                        {"id": "c3", "name": "write_to_file", "arguments": {"TargetFile": "src/new.py"}},
                        {"id": "c4", "name": "grep_search", "arguments": {"Query": "main"}},
                        {"id": "c5", "name": "find_by_name", "arguments": {"SearchDirectory": "src"}},
                        {"id": "c6", "name": "run_command", "arguments": {"CommandLine": "pytest -q"}},
                    ],
                    "usage": {
                        "input_tokens": 1000,
                        "cache_read_tokens": 4000,
                        "cache_creation_input_tokens": 200,
                        "output_tokens": 150,
                    },
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 2, "call_id": "c1", "text": "Created At: 2026-11-18T10:00:00Z\nCompleted At: 2026-11-18T10:00:01Z\nfile content"},
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 3, "call_id": "c2", "text": "updated"},
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 4, "call_id": "c3", "text": "written"},
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 5, "call_id": "c4", "text": "matches"},
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 6, "call_id": "c5", "text": "src/app.py"},
                {
                    "type": "MODEL",
                    "subtype": "GENERIC",
                    "step_index": 7,
                    "call_id": "c6",
                    "text": "Created At: 2026-11-18T10:00:02Z\nCompleted At: 2026-11-18T10:00:03Z\nCommand exited with code 127\n'pytest' is not recognized",
                },
            ]
            _write_jsonl(p, rows)

            items, next_off, last_step = te.antigravity_read(p, offset=0, after=-1, final=True)
            self.assertEqual(last_step, 7)
            self.assertGreater(next_off, 0)
            self.assertEqual(items[0]["kind"], "user")
            self.assertEqual(items[0]["text"], "Fix failing suite")

            tools = [it for it in items if it["kind"] == "tool_use"]
            self.assertEqual(len(tools), 6)
            self.assertEqual(tools[0]["summary"], "Read src/app.py")
            self.assertNotIn("Created At:", tools[0]["output"])
            self.assertNotIn("Completed At:", tools[0]["output"])
            self.assertEqual(tools[1]["summary"], "Edit src/app.py")
            self.assertEqual(tools[2]["summary"], "Write src/new.py")
            self.assertEqual(tools[3]["tool"], "Grep")
            self.assertEqual(tools[4]["tool"], "Glob")
            self.assertEqual(tools[5]["summary"], "Bash pytest -q")
            self.assertEqual(tools[5]["exit_code"], 127)
            self.assertTrue(tools[5]["is_error"])

            # Incremental append
            with p.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "type": "PLANNER_RESPONSE",
                            "step_index": 8,
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                            "usage": {"input_tokens": 500, "cache_read_tokens": 2000, "output_tokens": 50},
                        }
                    )
                    + "\n"
                )
                f.write(
                    json.dumps(
                        {
                            "type": "MODEL",
                            "subtype": "GENERIC",
                            "step_index": 9,
                            "text": "Command exited with code 0\n3 passed",
                        }
                    )
                    + "\n"
                )
            inc_items, next_off2, last_step2 = te.antigravity_read(p, offset=next_off, after=last_step, final=True)
            self.assertEqual(last_step2, 9)
            self.assertGreater(next_off2, next_off)
            self.assertEqual(len(inc_items), 1)
            self.assertEqual(inc_items[0]["exit_code"], 0)
            self.assertFalse(inc_items[0]["is_error"])

            usage = te.antigravity_session_usage(p, model="gemini-4-carbon")
            self.assertEqual(usage["input_tokens"], 1500)
            self.assertEqual(usage["cache_read_tokens"], 6000)
            self.assertEqual(usage["cache_creation_input_tokens"], 200)
            self.assertEqual(usage["output_tokens"], 200)
            self.assertEqual(usage["requests"], 2)

    def test_effective_tokens_model_weights(self):
        sample = {
            "input_tokens": 1000,
            "cache_read_input_tokens": 2000,
            "cache_creation_input_tokens": 400,
            "output_tokens": 100,
        }
        # gemini-4-carbon / neon / hydrogen: 1.0*1000 + 0.05*2000 + 0.0*400 + 5.0*100 = 1600.0
        for m in ("gemini-4-carbon", "gemini-4-neon", "gemini-4-hydrogen"):
            self.assertAlmostEqual(te.effective_tokens(sample, model=m), 1600.0, places=6)
        # claude-opus-5-5: 1.0*1000 + 0.05*2000 + 1.25*400 + 5.0*100 = 2100.0
        self.assertAlmostEqual(te.effective_tokens(sample, model="claude-opus-5-5"), 2100.0, places=6)
        # gemini-3.8-flash: 1.0*1000 + 0.10*2000 + 0.0*400 + 5.0*100 = 1700.0
        self.assertAlmostEqual(te.effective_tokens(sample, model="gemini-3.8-flash"), 1700.0, places=6)


class TestEnvFactsAndLifecycle(unittest.TestCase):
    def test_m2_form_repair_promotion_exercise_and_contradiction_retirement(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "my repo!"
            repo.mkdir()
            state_root = Path(td) / "state"
            self.assertEqual(te.repo_slug(repo), "my_repo_")

            distiller = te.EnvFactsDistiller(repo=repo, state_root=state_root)
            for idx in range(1, 4):
                tp = Path(td) / f"s{idx}.jsonl"
                _write_jsonl(
                    tp,
                    [
                        {
                            "type": "PLANNER_RESPONSE",
                            "step_index": 0,
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}],
                        },
                        {
                            "type": "MODEL",
                            "subtype": "GENERIC",
                            "step_index": 1,
                            "text": "Command exited with code 127\n'pytest' is not recognized as an internal or external command",
                        },
                        {
                            "type": "PLANNER_RESPONSE",
                            "step_index": 2,
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                        },
                        {
                            "type": "MODEL",
                            "subtype": "GENERIC",
                            "step_index": 3,
                            "text": "Command exited with code 0\n5 passed in 0.12s",
                        },
                    ],
                )
                res = distiller.fold_transcript(tp, session_id=f"s{idx}")
                self.assertEqual(res["opt_tokens"], 0.0)

            envfacts_path = state_root / "my_repo_" / "envfacts.json"
            self.assertTrue(envfacts_path.is_file())
            data = json.loads(envfacts_path.read_text(encoding="utf-8"))
            self.assertEqual(data["opt_tokens"], 0.0)
            active = [f for f in data["facts"].values() if f["life"]["status"] == "ACTIVE"]
            self.assertEqual(len(active), 1)
            fid = active[0]["id"]
            self.assertEqual(active[0]["family"], "form_repair")
            self.assertIn("python -m pytest", active[0]["claim"])
            self.assertIn("# environment facts learned from earlier sessions in this repository", data["rendered"])
            self.assertLessEqual(te.estimate_tokens(data["rendered"]), te.MAX_TOKENS)

            # Session 4: exercise >= 4 times -> fire_rate >= 0.40 keeps ACTIVE
            s4 = Path(td) / "s4.jsonl"
            _write_jsonl(
                s4,
                [
                    {"type": "PLANNER_RESPONSE", "step_index": i * 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}]}
                    if j == 0
                    else {"type": "MODEL", "subtype": "GENERIC", "step_index": i * 2 + 1, "text": "Command exited with code 0\n5 passed"}
                    for i in range(4)
                    for j in range(2)
                ],
            )
            distiller.fold_transcript(s4, session_id="s4")
            data = json.loads(envfacts_path.read_text(encoding="utf-8"))
            self.assertEqual(data["facts"][fid]["life"]["status"], "ACTIVE")
            self.assertGreaterEqual(data["facts"][fid]["life"]["n_fired"], 4)

            # Contradiction: 1 bare pytest success does NOT retire; 2nd consecutive retires!
            s5 = Path(td) / "s5.jsonl"
            _write_jsonl(
                s5,
                [
                    {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 0\n5 passed"},
                ],
            )
            distiller.fold_transcript(s5, session_id="s5")
            data = json.loads(envfacts_path.read_text(encoding="utf-8"))
            self.assertEqual(data["facts"][fid]["life"]["status"], "ACTIVE")
            self.assertEqual(data["facts"][fid]["life"]["contradict_streak"], 1)

            s6 = Path(td) / "s6.jsonl"
            _write_jsonl(
                s6,
                [
                    {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 0\n5 passed"},
                ],
            )
            distiller.fold_transcript(s6, session_id="s6")
            data = json.loads(envfacts_path.read_text(encoding="utf-8"))
            self.assertEqual(data["facts"][fid]["life"]["status"], "RETIRED")
            self.assertEqual(data["rendered"], "")

    def test_lint_re_rejects_unsafe_claims_and_forget_unforget(self):
        unsafe = [
            "You can skip running tests on small edits.",
            "No need to run pytest after formatting.",
            "Don't run the verification suite here.",
            "Do not execute tests on Windows.",
            "Stop early once files are written.",
            "Mark task done without running checks.",
            "Task is complete after editing.",
            "Finish immediately after compile.",
            "Verify manually instead of running tests.",
            "Skip verification when busy.",
            "Use echo instead of testing.",
        ]
        for claim in unsafe:
            self.assertFalse(te.is_claim_safe(claim), f"Expected _LINT_RE rejection for: {claim}")
        self.assertTrue(te.is_claim_safe("`pytest` fails (`command_missing`); use `python -m pytest`."))

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo_fg"
            repo.mkdir()
            state_root = Path(td) / "state"
            distiller = te.EnvFactsDistiller(repo=repo, state_root=state_root)
            for idx in range(1, 4):
                tp = Path(td) / f"w{idx}.jsonl"
                _write_jsonl(
                    tp,
                    [
                        {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "git status && pytest"}}]},
                        {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 1\nThe token '&&' is not a valid statement separator in this version."},
                        {"type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "git status ; pytest"}}]},
                        {"type": "MODEL", "subtype": "GENERIC", "step_index": 3, "text": "Command exited with code 0\nok"},
                    ],
                )
                distiller.fold_transcript(tp, session_id=f"w{idx}")

            active = distiller.active_facts()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["family"], "win_shell_repair")
            fid = active[0]["id"]

            te.forget_fact(fid, repo=repo, state_root=state_root)
            self.assertEqual(te.session_start(repo=repo, state_root=state_root)["systemMessage"], "")
            # Re-folding same transcript while forgotten must not re-promote
            distiller.fold_transcript(Path(td) / "w1.jsonl", session_id="w4")
            self.assertEqual(te.session_start(repo=repo, state_root=state_root)["systemMessage"], "")

            te.unforget_fact(fid, repo=repo, state_root=state_root)
            self.assertIn(";", te.session_start(repo=repo, state_root=state_root)["systemMessage"])

    def test_remaining_llm_free_families_and_atomic_write_backoff(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "fam_repo"
            repo.mkdir()
            state_root = Path(td) / "state"
            distiller = te.EnvFactsDistiller(repo=repo, state_root=state_root)
            tp = Path(td) / "families.jsonl"
            _write_jsonl(
                tp,
                [
                    # arg_repair
                    {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest --bad-flag"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 2\nunrecognized arguments: --bad-flag"},
                    {"type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 3, "text": "Command exited with code 0\n1 passed"},
                    # env_value
                    {"type": "PLANNER_RESPONSE", "step_index": 4, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python app.py"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 5, "text": "Command exited with code 1\nKeyError: 'APP_MODE' environment variable not set"},
                    {"type": "PLANNER_RESPONSE", "step_index": 6, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "APP_MODE=test python app.py"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 7, "text": "Command exited with code 0\nready"},
                    # absent_tool
                    {"type": "PLANNER_RESPONSE", "step_index": 8, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "ripgrep_missing foo"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 9, "text": "Command exited with code 127\nripgrep_missing: command not found"},
                    # boundary
                    {"type": "PLANNER_RESPONSE", "step_index": 10, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python dump.py"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 11, "text": "Command exited with code 1\nUnicodeEncodeError: 'cp1252' codec can't encode character"},
                    {"type": "PLANNER_RESPONSE", "step_index": 12, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "PYTHONIOENCODING=utf-8 python dump.py"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 13, "text": "Command exited with code 0\ndumped"},
                ],
            )
            res = distiller.fold_transcript(tp, session_id="fam1")
            families = {f["family"] for f in res["facts"].values()}
            self.assertTrue({"arg_repair", "env_value", "absent_tool", "boundary"}.issubset(families), families)

            # Windows PermissionError backoff in write_json_atomic
            target = Path(td) / "atomic.json"
            real_replace = os.replace
            calls = {"n": 0}

            def flaky_replace(src, dst):
                calls["n"] += 1
                if calls["n"] <= 3:
                    raise PermissionError("WinError 5 mock")
                return real_replace(src, dst)

            with mock.patch("os.replace", side_effect=flaky_replace), mock.patch("time.sleep") as m_sleep:
                te.write_json_atomic(target, {"ok": True})
            self.assertEqual(calls["n"], 4)
            self.assertEqual(m_sleep.call_count, 3)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})

    def test_win_rtk_find_repair_and_fire_gate_retirement(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "rtk_repo"
            repo.mkdir()
            state_root = Path(td) / "state"
            distiller = te.EnvFactsDistiller(repo=repo, state_root=state_root)
            for idx in range(1, 4):
                tp = Path(td) / f"rtk_{idx}.jsonl"
                _write_jsonl(
                    tp,
                    [
                        {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "rtk find . -name '*.py'"}}]},
                        {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 2\nFIND: Parameter format not correct (System32\\find.exe)"},
                        {"type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "Get-ChildItem -Filter *.py"}}]},
                        {"type": "MODEL", "subtype": "GENERIC", "step_index": 3, "text": "Command exited with code 0\na.py"},
                    ],
                )
                distiller.fold_transcript(tp, session_id=f"r{idx}")

            active = distiller.active_facts()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["family"], "win_shell_repair")
            self.assertIn("rtk find", active[0]["claim"])

            # Verify FIRE_GATE (0.40) retirement at FIRE_MIN_N (4)
            life = dict(active[0]["life"])
            te.Lifecycle.record_exercise(life, helpful=True, now=10)
            for step_n in range(11, 14):
                te.Lifecycle.record_exercise(life, helpful=False, now=step_n)
            # 1 helpful / 4 fired = 0.25 < 0.40 -> RETIRED
            self.assertEqual(life["n_fired"], 4)
            self.assertEqual(life["status"], "RETIRED")


class TestSpiralStateEnvelopeAndTurnGuard(unittest.TestCase):
    def test_envelope_tracker_p90_only_resolved_turns(self):
        tracker = te.EnvelopeTracker(pct=90, margin=1.25, min_samples=5)
        for v in (4, 6, 8, 10):
            tracker.record(v, resolved=True)
        self.assertIsNone(tracker.envelope(), "Below min_samples must return None")
        # Unresolved turn must NOT be added
        tracker.record(999, resolved=False)
        self.assertIsNone(tracker.envelope())
        # 5th resolved sample: [4, 6, 8, 10, 12], pos = 0.9 * 4 = 3.6 -> 10 + 0.6*2 = 11.2, * 1.25 = 14.0
        tracker.record(12, resolved=True)
        self.assertAlmostEqual(tracker.p90(), 11.2, places=6)
        self.assertAlmostEqual(tracker.envelope(), 14.0, places=6)

    def test_m3_spiral_triggers_single_nudge_and_productive_grind_zero_nudges(self):
        # 1. Spiral trajectory with identical MD5 failure signature
        state = te.SpiralState()
        for i in range(6):
            state.observe({"kind": "tool_use", "tool": "Edit", "file_path": "src/a.py", "summary": "Edit src/a.py"})
            state.observe(
                {
                    "kind": "tool_use",
                    "tool": "Bash",
                    "command": "python -m pytest -q",
                    "summary": "Bash python -m pytest -q",
                    "output": f"2026-11-18T10:00:0{i}Z AssertionError: expected 2 got 1 at line 42",
                    "exit_code": 1,
                    "is_error": True,
                }
            )
        self.assertGreaterEqual(state.edit_churn, 4)
        self.assertGreaterEqual(state.error_outputs, 6)
        self.assertGreaterEqual(state.stagnation, 0.20)
        self.assertEqual(state.distinct_edit_files, 1)

        guard = te.TurnGuard(
            judge_fn=lambda d: {"stuck": "stagnation=0." in d and "stagnation=0.00" not in d, "confidence": 0.88},
            max_nudges=1,
        )
        res1 = guard.step(state)
        self.assertTrue(res1["nudge"])
        self.assertEqual(res1["r"], 1)
        self.assertIn("ephemeralMessage", res1)
        self.assertLessEqual(te.estimate_tokens(res1["ephemeralMessage"]), 95)
        self.assertTrue(te.is_claim_safe(res1["ephemeralMessage"]))
        # Segment reset after redirect
        self.assertEqual(state.turns, 0)
        # max_nudges=1 prevents a second nudge in the same turn
        res2 = guard.step(state)
        self.assertFalse(res2["nudge"])

        # 2. Productive grind with changing failure hashes (stagnation == 0.0) -> 0 redirects
        prod_state = te.SpiralState()
        for i in range(7):
            prod_state.observe({"kind": "tool_use", "tool": "Edit", "file_path": f"src/m{i}.py", "summary": f"Edit src/m{i}.py"})
            prod_state.observe(
                {
                    "kind": "tool_use",
                    "tool": "Bash",
                    "command": "python -m pytest -q",
                    "summary": "Bash python -m pytest -q",
                    "output": f"DistinctFailureModule{i}: missing symbol alpha_{i}_token",
                    "exit_code": 1,
                    "is_error": True,
                }
            )
        self.assertEqual(prod_state.stagnation, 0.0)
        prod_guard = te.TurnGuard(max_nudges=1)
        prod_res = prod_guard.step(prod_state)
        self.assertFalse(prod_res["nudge"])
        self.assertEqual(prod_res["r"], 0)

    def test_hard_backstop_at_2_5x_envelope(self):
        tracker = te.EnvelopeTracker(pct=90, margin=1.25, min_samples=5)
        for v in (4, 4, 4, 4, 4):
            tracker.record(v, resolved=True)
        # envelope = 5.0, 2.5x = 12.5
        state = te.SpiralState()
        for i in range(13):
            state.observe(
                {
                    "kind": "tool_use",
                    "tool": "Bash",
                    "command": "python -m pytest",
                    "output": "AssertionError: stuck on invariant X",
                    "exit_code": 1,
                    "is_error": True,
                }
            )
        # Even if judge_fn claims stuck=False, 2.5x envelope hard backstop triggers!
        guard = te.TurnGuard(
            envelope_tracker=tracker,
            judge_fn=lambda _d: {"stuck": False, "confidence": 0.1},
            max_nudges=1,
        )
        res = guard.step(state)
        self.assertTrue(res["nudge"])
        self.assertTrue(res["backstop_triggered"])


class TestCLISurfaceAndBenchmark(unittest.TestCase):
    def test_cli_status_and_benchmark_ab_report(self):
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / "ab_report.json"
            proc_status = subprocess.run(
                [sys.executable, str(AG_SCRIPTS / "token_economizer.py"), "--status", "--json", "--repo", str(REPO_ROOT)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc_status.returncode, 0, proc_status.stderr)
            st = json.loads(proc_status.stdout)
            self.assertTrue(st["enabled"])
            self.assertEqual(st["opt_tokens"], 0.0)

            proc_bench = subprocess.run(
                [
                    sys.executable,
                    str(AG_SCRIPTS / "token_economizer.py"),
                    "--benchmark",
                    "--output",
                    str(out_file),
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc_bench.returncode, 0, proc_bench.stderr)
            report = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(report["duplicate_hook_tokens_saved_pct"], 100.0)
            self.assertGreaterEqual(report["post_warmup_effective_token_reduction_pct"], 20.0)
            self.assertEqual(report["productive_false_nudges"], 0)
            self.assertEqual(report["opt_tokens"], 0.0)
            self.assertGreaterEqual(report["spiral_nudges_emitted"], 1)
            self.assertEqual(len(report["sessions"]), 6)


if __name__ == "__main__":
    unittest.main()
