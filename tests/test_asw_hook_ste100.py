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

"""RED-to-GREEN verification suite for ASD-STE100 compressed directives in asw-hook.mjs (M7)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AG_SCRIPTS = REPO_ROOT / ".antigravity" / "scripts"
TOON_SCRIPT = AG_SCRIPTS / "toon_codec.py"
HOOK_SCRIPT = REPO_ROOT / "plugins" / "antigravity-swarm" / "scripts" / "asw-hook.mjs"
BASELINE_PATH = REPO_ROOT / ".asw" / "evidence" / "token-compression-baseline.json"

if str(AG_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AG_SCRIPTS))

import toon_codec as tc  # noqa: E402

EXPECTED_DIRECTIVE_HEADERS = {
    "PLAN_DIRECTIVE": "ASW PLAN MODE ENABLED!",
    "GOAL_DIRECTIVE": "ASW GOAL MODE ENABLED!",
    "START_WORK_DIRECTIVE": "ASW START-WORK MODE ENABLED!",
    "CLEANUP_DIRECTIVE": "ASW CLEANUP MODE ENABLED!",
    "LOOP_DIRECTIVE": "ASW LOOP MODE ENABLED!",
    "REVIEW_DIRECTIVE": "ASW REVIEW MODE ENABLED!",
    "CONSULTATION_DIRECTIVE": "ASW CONSULTATION / MODE 1 ENABLED!",
    "TEST_GUI_DIRECTIVE": "ASW TEST-GUI MODE ENABLED!",
}

MANDATORY_TERMS = (
    "Zero Heuristic Substitution",
    "User Intent & Anti-Shortcut Contract",
    "Golden Reference",
    "Enforce Mandatory Rendered DOM",
    "Shadow-Root",
    "BLOCKED_ON_HARDWARE_AUTH",
    "3-Strike",
    "--scan-public-repo",
    "--assert-asset-version",
    "MANDATORY SUBAGENT & MODEL-TIER ESCALATION GATE",
    "invoke_subagent",
    "asw-planner",
    "asw-implementer",
    "asw-reviewer",
    "Gemini 4 Carbon",
    "Gemini 4 Neon",
    "Gemini 4 Hydrogen",
    "Claude Opus 5.5",
    "rtk",
    "rtk-token-killer",
    "RED-to-GREEN",
    "<= 250",
    "<frozen-after-approval>",
    "I/O & Edge-Case Matrix",
    "## Review Triage Log",
    "blind-hunter",
    "edge-case-hunter",
    "verification-gap",
    "intent-alignment",
    "opus-cross-family",
)

FORBIDDEN_TERMS_GLOBAL = (
    "Argon",
    "Custom element doesn't exist",
    "Unhandled Runtime Error",
    "Verdict: GUI_FAILED",
)


class TestAswHookSte100(unittest.TestCase):
    def test_negative_ste100_linter_rejects_fillers_and_long_sentences(self):
        """Negative check: lint_ste100_text rejects filler phrases and >22 prose-word sentences."""
        for filler in ("In order to finish, run tests.", "Please note that rules apply.", "Make sure to check logs."):
            res = tc.lint_ste100_text(filler, max_words_per_bullet=22)
            self.assertFalse(res["ok"], f"Expected filler rejection for: {filler}")
            self.assertTrue(any(v["category"] == "banned_filler" for v in res["violations"]))

        long_line = "- " + " ".join(f"token{i}" for i in range(23)) + "."
        res_long = tc.lint_ste100_text(long_line, max_words_per_bullet=22)
        self.assertFalse(res_long["ok"])
        self.assertEqual(res_long["violations"][0]["category"], "sentence_too_long")
        self.assertEqual(res_long["max_prose_words_seen"], 23)

    def test_hook_directives_pass_ste100_cli_with_zero_violations(self):
        """CLI --lint-ste100 must exit 0 with ok=True and 0 violations across all 8 directives."""
        proc = subprocess.run(
            [sys.executable, str(TOON_SCRIPT), "--lint-ste100", str(HOOK_SCRIPT), "--max-words", "22", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, f"STE-100 lint failed:\n{proc.stdout}\n{proc.stderr}")
        report = json.loads(proc.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["total_violations"], 0)
        self.assertEqual(report["directive_count"], 8)
        self.assertLessEqual(report["max_prose_words_seen"], 22)
        for name in EXPECTED_DIRECTIVE_HEADERS:
            self.assertIn(name, report["directives"])
            self.assertTrue(report["directives"][name]["ok"], f"{name} failed STE-100: {report['directives'][name]}")

    def test_hook_directives_achieve_at_least_30_percent_token_reduction(self):
        """Sum of estimate_tokens across the 8 static directives must cut >= 30.0% vs 3548 baseline."""
        baseline_tokens = 3548
        if BASELINE_PATH.is_file():
            baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
            self.assertEqual(int(baseline["hook_directives_before"]["total_est_tokens"]), baseline_tokens)

        source = HOOK_SCRIPT.read_text(encoding="utf-8")
        directives = tc._extract_mjs_directives(source)
        self.assertEqual(set(directives.keys()), set(EXPECTED_DIRECTIVE_HEADERS.keys()))

        after_tokens = sum(tc.estimate_tokens(text) for text in directives.values())
        saved_pct = ((baseline_tokens - after_tokens) / baseline_tokens) * 100.0
        self.assertGreaterEqual(
            saved_pct,
            30.0,
            f"Expected >= 30.0% token reduction vs {baseline_tokens}, got {after_tokens} ({saved_pct:.2f}%)",
        )
        self.assertLessEqual(after_tokens, 2480)

    def test_all_headers_mandatory_terms_and_forbidden_terms_enforced(self):
        """100% gate/header preservation and forbidden-term exclusion across asw-hook.mjs."""
        source = HOOK_SCRIPT.read_text(encoding="utf-8")
        directives = tc._extract_mjs_directives(source)
        self.assertEqual(set(directives.keys()), set(EXPECTED_DIRECTIVE_HEADERS.keys()))

        for name, header in EXPECTED_DIRECTIVE_HEADERS.items():
            self.assertIn(header, directives[name], f"{name} missing exact header {header!r}")

        for term in MANDATORY_TERMS:
            self.assertIn(term, source, f"asw-hook.mjs missing mandatory term {term!r}")

        for forbidden in FORBIDDEN_TERMS_GLOBAL:
            self.assertNotIn(forbidden, source, f"asw-hook.mjs must not contain forbidden term {forbidden!r}")

        self.assertNotIn("RED-to-GREEN", directives["CONSULTATION_DIRECTIVE"])

    def test_node_syntax_and_routing_behavior_preserved(self):
        """node --check passes and all 8 command routes emit their expected directive headers."""
        chk = subprocess.run(["node", "--check", str(HOOK_SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertEqual(chk.returncode, 0, chk.stderr)

        prompts = [
            ("/asw-plan Build API", "ASW PLAN MODE ENABLED!"),
            ("/asw-goal Ship feature", "ASW GOAL MODE ENABLED!"),
            ("/asw-start-work my-plan", "ASW START-WORK MODE ENABLED!"),
            ("/asw-cleanup src/app.py", "ASW CLEANUP MODE ENABLED!"),
            ("/asw-loop Fix parser", "ASW LOOP MODE ENABLED!"),
            ("/asw-review", "ASW REVIEW MODE ENABLED!"),
            ("/asw How does caching work?", "ASW CONSULTATION / MODE 1 ENABLED!"),
            ("asw-test-gui verify localhost", "ASW TEST-GUI MODE ENABLED!"),
        ]
        for prompt, expected_header in prompts:
            proc = subprocess.run(
                ["node", str(HOOK_SCRIPT)],
                input=json.dumps({"invocationNum": 1, "lastUserInput": prompt, "cwd": str(REPO_ROOT)}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            msg = json.loads(proc.stdout)["injectSteps"][0]["userMessage"]
            self.assertIn(expected_header, msg)


if __name__ == "__main__":
    unittest.main()
