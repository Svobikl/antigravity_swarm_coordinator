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

"""End-to-end tests for Task 4: workspace-local SKILL.md, pipeline integration, A/B benchmark, and flag isolation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AG_SCRIPTS = REPO_ROOT / ".antigravity" / "scripts"
HOOK_SCRIPT = REPO_ROOT / "plugins" / "antigravity-swarm" / "scripts" / "asw-hook.mjs"
RTK_REWRITE_SCRIPT = REPO_ROOT / "plugins" / "antigravity-swarm" / "scripts" / "asw-rtk-rewrite.mjs"
TE_SCRIPT = AG_SCRIPTS / "token_economizer.py"
MEM_SCRIPT = AG_SCRIPTS / "memory_manager.py"
LOCAL_SKILL_MD = REPO_ROOT / ".antigravity" / "skills" / "token-economizer" / "SKILL.md"

if str(AG_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AG_SCRIPTS))

import token_economizer as te  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _isolated_env(home_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    env["USERPROFILE"] = str(home_dir)
    env["APPDATA"] = str(home_dir / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(home_dir / "AppData" / "Local")
    env.pop("OBSIDIAN_VAULT_PATH", None)
    env.pop("ASW_TOKEN_ECONOMIZER_ENABLED", None)
    if extra:
        env.update(extra)
    return env


def _run_hook(args: list[str], payload: dict, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(
        ["node", str(HOOK_SCRIPT), *args],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(f"asw-hook.mjs failed ({proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout)


def _warmup_session_rows(idx: int) -> list[dict]:
    return [
        {
            "type": "USER_INPUT",
            "step_index": 0,
            "text": f"<USER_REQUEST>/asw-loop warmup session {idx}</USER_REQUEST>",
        },
        {
            "type": "PLANNER_RESPONSE",
            "step_index": 1,
            "tool_calls": [{"id": "c1", "name": "run_command", "arguments": {"CommandLine": "pytest -q"}}],
            "usage": {"input_tokens": 1400, "cache_read_tokens": 4200, "output_tokens": 90},
        },
        {
            "type": "MODEL",
            "subtype": "GENERIC",
            "step_index": 2,
            "call_id": "c1",
            "text": "Command exited with code 127\n'pytest' is not recognized as an internal or external command",
        },
        {
            "type": "PLANNER_RESPONSE",
            "step_index": 3,
            "tool_calls": [{"id": "c2", "name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
            "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
        },
        {
            "type": "MODEL",
            "subtype": "GENERIC",
            "step_index": 4,
            "call_id": "c2",
            "text": "Command exited with code 0\n12 passed in 0.41s",
        },
    ]


def _spiral_rows(step_start: int = 1, count: int = 6, error_text: str = "AssertionError: invariant M3 mismatch") -> list[dict]:
    rows: list[dict] = []
    idx = step_start
    for _ in range(count):
        rows.extend(
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": idx,
                    "tool_calls": [{"name": "replace_file_content", "arguments": {"TargetFile": "src/engine.py"}}],
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": idx + 1, "text": "Edited src/engine.py"},
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": idx + 2,
                    "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": idx + 3, "text": f"Command exited with code 1\n{error_text}"},
            ]
        )
        idx += 4
    return rows


class TestTokenEconomizerSkillContract(unittest.TestCase):
    def test_local_skill_exists_valid_frontmatter_no_bom_and_not_global(self):
        self.assertTrue(LOCAL_SKILL_MD.is_file(), f"Missing workspace-local skill: {LOCAL_SKILL_MD}")

        # Must NOT be pushed into global ~/.gemini/config/skills/ (keeps 200-skill catalog invariant intact)
        home = Path.home()
        for global_dir in (
            home / ".gemini" / "config" / "skills" / "token-economizer",
            home / ".gemini" / "antigravity-ide" / "skills" / "token-economizer",
            home / ".agents" / "skills" / "token-economizer",
        ):
            self.assertFalse(global_dir.exists(), f"token-economizer must stay workspace-local, not in {global_dir}")

        raw = LOCAL_SKILL_MD.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "SKILL.md must not have UTF-8 BOM")

        text = raw.decode("utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
        self.assertIsNotNone(m, "SKILL.md must contain valid YAML frontmatter")

        fm_lines = m.group(1).splitlines()
        name = None
        desc = None
        for line in fm_lines:
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip().strip("\"'")
            elif stripped.startswith("description:"):
                desc = stripped.split(":", 1)[1].strip().strip("\"'")

        self.assertEqual(name, "token-economizer")
        self.assertIsNotNone(desc)
        self.assertNotIn(desc, (">", "|", ">-", "|-"), "description must be single-line")
        self.assertGreaterEqual(len(desc), 15, f"description too short: {desc!r}")
        self.assertLessEqual(len(desc), 120, f"description exceeds 120 chars: {desc!r}")

        for required_doc in (
            "--status",
            "--fold",
            "--microskills",
            "--forget",
            "--unforget",
            "--benchmark",
            "ASW_TOKEN_ECONOMIZER_ENABLED=0",
        ):
            self.assertIn(required_doc, text, f"SKILL.md must document {required_doc}")

        # Zero hardcoded user-home paths or current username
        user_dir_pattern = re.compile(r"[A-Za-z]:" + r"[\\/]+Users[\\/]+", re.IGNORECASE)
        self.assertIsNone(user_dir_pattern.search(text), "SKILL.md must not contain hardcoded user paths")
        username = home.name
        if len(username) >= 3:
            username_pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(username)}(?![A-Za-z0-9_])", re.IGNORECASE)
            self.assertIsNone(username_pattern.search(text), "SKILL.md must not contain username")


class TestTokenEconomizerEndToEndPipeline(unittest.TestCase):
    def test_multi_session_pipeline_m1_through_m5_and_turn_guard_scoping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo_dir = root / "e2e_demo_repo"
            (repo_dir / "src").mkdir(parents=True, exist_ok=True)
            (repo_dir / "README.md").write_text("# Demo Repo\n", encoding="utf-8")
            (repo_dir / "src" / "engine.py").write_text("def step():\n    return 1\n", encoding="utf-8")

            vault_dir = root / "obsidian_vault"
            home_dir = root / "isolated_home"
            home_dir.mkdir(parents=True, exist_ok=True)
            env = _isolated_env(home_dir)

            # M4: Verify Windows vs POSIX rtk find guard in asw-rtk-rewrite.mjs
            rtk_probe = (
                f"import {{ rewriteCommandToRtk }} from {json.dumps(RTK_REWRITE_SCRIPT.resolve().as_uri())};"
                "console.log(JSON.stringify({"
                "win_find: rewriteCommandToRtk(\"find . -name '*.py'\", true),"
                "posix_find: rewriteCommandToRtk(\"find . -name '*.py'\", false),"
                "win_compound: rewriteCommandToRtk(\"git status; find . -name '*.py'\", true)"
                "}));"
            )
            rtk_proc = subprocess.run(
                ["node", "--input-type=module", "-e", rtk_probe],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(rtk_proc.returncode, 0, rtk_proc.stderr)
            rtk_res = json.loads(rtk_proc.stdout)
            self.assertEqual(rtk_res["win_find"], "find . -name '*.py'")
            self.assertEqual(rtk_res["posix_find"], "rtk find . -name '*.py'")
            self.assertEqual(rtk_res["win_compound"], "rtk git status; find . -name '*.py'")

            # M2: Fold 4 realistic Antigravity JSONL sessions (K_PROMOTE=3 promotes, session 4 exercises)
            sessions_dir = root / "sessions"
            for s_idx in range(1, 4):
                s_path = sessions_dir / f"session_{s_idx}.jsonl"
                _write_jsonl(s_path, _warmup_session_rows(s_idx))
                fold_proc = subprocess.run(
                    [sys.executable, str(TE_SCRIPT), "--fold", str(s_path), "--repo", str(repo_dir), "--json"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    timeout=15,
                )
                self.assertEqual(fold_proc.returncode, 0, fold_proc.stderr)
                fold_data = json.loads(fold_proc.stdout)
                self.assertEqual(fold_data["opt_tokens"], 0.0)
                if s_idx < 3:
                    self.assertEqual(fold_data["active_facts"], 0)
                else:
                    self.assertEqual(fold_data["active_facts"], 1)

            # Session 4: post-warmup session using learned python -m pytest cleanly
            s4_path = sessions_dir / "session_4.jsonl"
            _write_jsonl(
                s4_path,
                [
                    {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop post-warmup</USER_REQUEST>"},
                    {
                        "type": "PLANNER_RESPONSE",
                        "step_index": 1,
                        "tool_calls": [{"id": "c4", "name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                        "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
                    },
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 2, "call_id": "c4", "text": "Command exited with code 0\n14 passed"},
                ],
            )
            s4_proc = subprocess.run(
                [sys.executable, str(TE_SCRIPT), "--fold", str(s4_path), "--repo", str(repo_dir), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=15,
            )
            self.assertEqual(s4_proc.returncode, 0, s4_proc.stderr)
            s4_data = json.loads(s4_proc.stdout)
            self.assertEqual(s4_data["active_facts"], 1)
            self.assertIn("python -m pytest", s4_data["rendered"])
            self.assertLessEqual(te.estimate_tokens(s4_data["rendered"]), 150)

            # M1 + M2: SessionStart hook emits KV-cached systemMessage <= 150 tokens with learned EnvFacts
            ss_out = _run_hook(["--event", "SessionStart"], {"cwd": str(repo_dir)}, env=env)
            sys_msg = ss_out["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("python -m pytest", sys_msg)
            self.assertLessEqual(te.estimate_tokens(sys_msg), 150)

            # M2 + Obsidian Vault: memory_manager --recall & --sync-envfacts
            recall_proc = subprocess.run(
                [
                    sys.executable,
                    str(MEM_SCRIPT),
                    "--recall",
                    "--project-path",
                    str(repo_dir),
                    "--vault-dir",
                    str(vault_dir),
                    "--task-type",
                    "code",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=20,
            )
            self.assertEqual(recall_proc.returncode, 0, recall_proc.stderr)
            self.assertIn("## 5. Learned Environment Micro-Skills", recall_proc.stdout)
            self.assertIn("python -m pytest", recall_proc.stdout)

            sync_proc = subprocess.run(
                [
                    sys.executable,
                    str(MEM_SCRIPT),
                    "--sync-envfacts",
                    "--project-path",
                    str(repo_dir),
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=20,
            )
            self.assertEqual(sync_proc.returncode, 0, sync_proc.stderr)
            sync_data = json.loads(sync_proc.stdout)
            self.assertEqual(sync_data["status"], "synced")
            self.assertGreaterEqual(sync_data["synced"], 1)
            micro_vault_file = vault_dir / "projects" / repo_dir.name / "Environment Micro-Skills.md"
            self.assertTrue(micro_vault_file.is_file(), f"Missing synced vault note: {micro_vault_file}")
            self.assertIn("python -m pytest", micro_vault_file.read_text(encoding="utf-8"))

            # M1: Cascading PreInvocation hook guard
            fresh_out = _run_hook(
                [],
                {"invocationNum": 1, "lastUserInput": "/asw-plan implement feature", "cwd": str(repo_dir)},
                env=env,
            )
            self.assertIn("ASW PLAN MODE ENABLED!", fresh_out["injectSteps"][0]["userMessage"])
            cascade_out = _run_hook(
                [],
                {"invocationNum": 1, "lastUserInput": "ASW PLAN MODE ENABLED! synthetic payload", "cwd": str(repo_dir)},
                env=env,
            )
            self.assertEqual(cascade_out, {})

            # M3: PreInvocation TurnGuard on stagnant edit-test spiral turn -> 1 ephemeralMessage, then suppressed
            spiral_path = sessions_dir / "spiral_turn.jsonl"
            _write_jsonl(
                spiral_path,
                [
                    {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>fix engine invariant</USER_REQUEST>"},
                    *_spiral_rows(step_start=1, count=6),
                ],
            )
            nudge_out_1 = _run_hook(
                [],
                {
                    "invocationNum": 1,
                    "lastUserInput": "keep fixing engine",
                    "transcriptPath": str(spiral_path),
                    "cwd": str(repo_dir),
                },
                env=env,
            )
            self.assertIn("injectSteps", nudge_out_1)
            eph_msg = nudge_out_1["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("Loop notice:", eph_msg)
            self.assertLessEqual(te.estimate_tokens(eph_msg), 95)

            # Second invocation on the same prompt-turn must NOT re-emit ephemeralMessage
            nudge_out_2 = _run_hook(
                [],
                {
                    "invocationNum": 1,
                    "lastUserInput": "keep fixing engine",
                    "transcriptPath": str(spiral_path),
                    "cwd": str(repo_dir),
                },
                env=env,
            )
            self.assertEqual(nudge_out_2, {})

            # Historical multi-turn transcript after a NEW USER_INPUT prompt must NOT trigger a redirect
            multi_turn_path = sessions_dir / "historical_multi_turn.jsonl"
            _write_jsonl(
                multi_turn_path,
                [
                    {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>historical spiral turn</USER_REQUEST>"},
                    *_spiral_rows(step_start=1, count=6, error_text="AssertionError: historical failure"),
                    {"type": "USER_INPUT", "step_index": 30, "text": "<USER_REQUEST>start fresh unrelated task</USER_REQUEST>"},
                    {
                        "type": "PLANNER_RESPONSE",
                        "step_index": 31,
                        "tool_calls": [{"id": "c31", "name": "view_file", "arguments": {"AbsolutePath": "src/engine.py"}}],
                    },
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 32, "call_id": "c31", "text": "def step(): return 1"},
                ],
            )
            multi_out = _run_hook(
                [],
                {
                    "invocationNum": 1,
                    "lastUserInput": "start fresh unrelated task",
                    "transcriptPath": str(multi_turn_path),
                    "cwd": str(repo_dir),
                },
                env=env,
            )
            self.assertEqual(
                multi_out,
                {},
                f"Historical spiral before a new USER_INPUT prompt must not trigger TurnGuard: {multi_out}",
            )

    def test_real_surface_ab_benchmark_m5(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "ab.json"
            proc = subprocess.run(
                [sys.executable, str(TE_SCRIPT), "--benchmark", "--output", str(out_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out_path.is_file())
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["duplicate_hook_tokens_saved_pct"], 100.0)
            self.assertGreaterEqual(report["post_warmup_effective_token_reduction_pct"], 20.0)
            self.assertGreater(report["raw_token_reduction_pct"], 0.0)
            self.assertEqual(report["productive_false_nudges"], 0)
            self.assertEqual(report["opt_tokens"], 0.0)

    def test_negative_flag_isolation_when_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo_dir = root / "disabled_repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "README.md").write_text("# Disabled Test\n", encoding="utf-8")
            vault_dir = root / "vault"
            home_dir = root / "home"
            home_dir.mkdir(parents=True, exist_ok=True)

            enabled_env = _isolated_env(home_dir)
            # Populate active envfacts while enabled
            for s_idx in range(1, 4):
                s_path = root / f"w_{s_idx}.jsonl"
                _write_jsonl(s_path, _warmup_session_rows(s_idx))
                subprocess.run(
                    [sys.executable, str(TE_SCRIPT), "--fold", str(s_path), "--repo", str(repo_dir)],
                    check=True,
                    capture_output=True,
                    env=enabled_env,
                    timeout=15,
                )

            spiral_path = root / "spiral.jsonl"
            _write_jsonl(
                spiral_path,
                [
                    {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>debug</USER_REQUEST>"},
                    *_spiral_rows(step_start=1, count=6),
                ],
            )

            disabled_env = _isolated_env(home_dir, {"ASW_TOKEN_ECONOMIZER_ENABLED": "0"})

            # 1. SessionStart hook short-circuits cleanly
            ss_disabled = _run_hook(["--event", "SessionStart"], {"cwd": str(repo_dir)}, env=disabled_env)
            self.assertEqual(ss_disabled, {})

            # 2. PreInvocation TurnGuard short-circuits cleanly
            tg_disabled = _run_hook(
                [],
                {
                    "invocationNum": 1,
                    "lastUserInput": "continue",
                    "transcriptPath": str(spiral_path),
                    "cwd": str(repo_dir),
                },
                env=disabled_env,
            )
            self.assertEqual(tg_disabled, {})

            # 3. token_economizer.py --benchmark returns disabled with zero output file writes
            ab_disabled_path = root / "should_not_exist.json"
            bench_proc = subprocess.run(
                [sys.executable, str(TE_SCRIPT), "--benchmark", "--output", str(ab_disabled_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=disabled_env,
                timeout=15,
            )
            self.assertEqual(bench_proc.returncode, 0, bench_proc.stderr)
            self.assertEqual(json.loads(bench_proc.stdout), {"enabled": False, "status": "disabled"})
            self.assertFalse(ab_disabled_path.exists())

            # 4. memory_manager.py recall omits EnvFacts & sync-envfacts short-circuits
            recall_proc = subprocess.run(
                [
                    sys.executable,
                    str(MEM_SCRIPT),
                    "--recall",
                    "--project-path",
                    str(repo_dir),
                    "--vault-dir",
                    str(vault_dir),
                    "--task-type",
                    "code",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=disabled_env,
                timeout=20,
            )
            self.assertEqual(recall_proc.returncode, 0, recall_proc.stderr)
            self.assertNotIn("Learned Environment Micro-Skills", recall_proc.stdout)
            self.assertNotIn("environment facts learned from earlier sessions", recall_proc.stdout)

            sync_proc = subprocess.run(
                [
                    sys.executable,
                    str(MEM_SCRIPT),
                    "--sync-envfacts",
                    "--project-path",
                    str(repo_dir),
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=disabled_env,
                timeout=20,
            )
            self.assertEqual(sync_proc.returncode, 0, sync_proc.stderr)
            self.assertEqual(json.loads(sync_proc.stdout), {"enabled": False, "status": "disabled", "synced": 0, "file": None})

    def test_readme_and_interactive_token_savings_widget_parity(self) -> None:
        """Verify SVG telemetry widget, HTML5 interactive calculator, and README.md match live benchmark figures."""
        import xml.etree.ElementTree as ET

        proc = subprocess.run(
            [sys.executable, str(TE_SCRIPT), "--benchmark", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        post_pct = f"-{report['post_warmup_effective_token_reduction_pct']:.2f}%"
        raw_pct = f"-{report['raw_token_reduction_pct']:.2f}%"
        overall_pct = f"-{report['effective_token_reduction_pct']:.2f}%"

        svg_path = REPO_ROOT / "assets" / "token-efficiency-dashboard.svg"
        self.assertTrue(svg_path.is_file(), f"Missing SVG telemetry widget at {svg_path}")
        svg_text = svg_path.read_text(encoding="utf-8")
        # Must parse as valid XML so GitHub SVG rendering never breaks
        ET.fromstring(svg_text)
        self.assertIn(post_pct, svg_text)
        self.assertIn(raw_pct, svg_text)
        self.assertIn("-87.8%", svg_text)
        self.assertIn("0.0 tok", svg_text)

        calc_path = REPO_ROOT / "docs" / "token-calculator.html"
        self.assertTrue(calc_path.is_file(), f"Missing interactive calculator at {calc_path}")
        calc_text = calc_path.read_text(encoding="utf-8")
        for s_entry in report["sessions"]:
            eff_int = str(int(s_entry["token_economizer"]["effective_tokens"]))
            self.assertIn(eff_int, calc_text)

        readme_path = REPO_ROOT / "README.md"
        if readme_path.is_file():
            readme_txt = readme_path.read_text(encoding="utf-8")
            self.assertIn("./assets/token-efficiency-dashboard.svg", readme_txt)
            self.assertIn("./docs/token-calculator.html", readme_txt)
            self.assertIn("xychart-beta", readme_txt)
            self.assertIn("<details", readme_txt)
            self.assertIn(post_pct, readme_txt)
            self.assertIn(overall_pct, readme_txt)


if __name__ == "__main__":
    unittest.main()
