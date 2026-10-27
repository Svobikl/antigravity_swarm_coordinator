# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Adversarial test suite for the 6 Cross-Session Failure Prevention Gates in Swarm Coordinator:
1. Golden Reference & End-to-End Decision Parity Gate (Tripwire 2E / 3B: enforce_shield=False & partial parity)
2. Mandatory Rendered DOM & Shadow-Root Zero-Error-Card Gate (Tripwire 4B: hui-error-card / Configuration error)
3. Boundary-to-Boundary Hardware / ADB / Voice Fidelity Gate (Tripwire 4C: device unauthorized / BLOCKED_ON_HARDWARE_AUTH)
4. 3-Strike Anti-Thrashing & Unapproved Binary .dex Patching Circuit Breaker (Tripwire 4D: classes.dex patching)
5. Feature-Flag & Negative-State Isolation Gate
6. Synchronized Governance Rules, Hook Directives, and Skills
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCrossSessionFailureGates(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.reviewer_script = (
            self.repo_root / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"
        )
        self.core_reviewer_script = (
            self.repo_root / "core_framework" / "scripts" / "invoke_opus_reviewer.py"
        )
        self.gui_script = (
            self.repo_root / ".antigravity" / "scripts" / "run_gui_test.py"
        )
        self.core_gui_script = (
            self.repo_root / "core_framework" / "scripts" / "run_gui_test.py"
        )

    def _closed_plan(self, objective: str = "Fix model parity and UI rendering") -> str:
        return (
            f"# Implementation Plan\n\n"
            f"## Objective\n{objective}\n\n"
            f"## Governance\nComplies with GLOBAL_DEVELOPMENT_RULES and PROGRAM_INVARIANTS.\n"
            f"Includes RED, GREEN, QA, EVIDENCE, and CLEANUP with Windows timeout handling.\n\n"
            f"## Execution Tasks\n"
            f"- [x] Task 1: Execute and verify\n"
            f"  - **Files**: `services/execution/worker.py`, `tests/test_worker.py`\n"
        )

    def test_diff_review_rejects_live_worker_enforce_shield_false_bypass(self):
        """Reproduces EdgeRelay Step 5304: worker.py calling evaluate_model_live(..., enforce_shield=False) bypassed V4.3/V4.4 sem_safe gates."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "shield_bypass.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan(), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/services/execution/worker.py b/services/execution/worker.py\n"
                "+++ b/services/execution/worker.py\n"
                "+def _evaluate_model_signals():\n"
                "+    live_eval = evaluate_model_live(model_id=mid, candles=c, enforce_shield=False)\n"
                "+    return live_eval\n"
                "diff --git a/tests/test_worker.py b/tests/test_worker.py\n"
                "+++ b/tests/test_worker.py\n"
                "+def test_negative_signal_rejected():\n"
                "+    assert _evaluate_model_signals() != {}\n",
                encoding="utf-8",
            )
            (ev_dir / "pytest.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n",
                encoding="utf-8",
            )

            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(
                res.returncode,
                0,
                "Production code setting enforce_shield=False in evaluate_model_live must be rejected!",
            )
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertIn("enforce_shield=false", report.lower())

    def test_diff_review_rejects_hui_error_card_or_configuration_error_in_evidence(self):
        """Reproduces Home Assistant Step 853: claiming completion while rendered UI or evidence contains hui-error-card / Configuration error."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "lovelace.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan("Update Home Assistant Lovelace overview"), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/config/www/klabava-cockpit-card.js b/config/www/klabava-cockpit-card.js\n"
                "+++ b/config/www/klabava-cockpit-card.js\n"
                "+customElements.define('klabava-cockpit-card', KlabavaCockpitCard);\n"
                "diff --git a/tests/test_cockpit.py b/tests/test_cockpit.py\n"
                "+++ b/tests/test_cockpit.py\n"
                "+def test_negative_missing_entity():\n"
                "+    assert 1 == 1\n",
                encoding="utf-8",
            )
            (ev_dir / "ha_dom_check.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n"
                "DOM dump: <hui-error-card>Configuration error: Custom element doesn't exist: klabava-cockpit-card</hui-error-card>\n",
                encoding="utf-8",
            )

            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(res.returncode, 0)
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertTrue(
                "hui-error-card" in report.lower() or "configuration error" in report.lower()
            )

    def test_diff_review_rejects_unauthorized_or_offline_adb_hardware_in_evidence(self):
        """Reproduces TCL TV Step 1011-1012: claiming completion while ADB target hardware is unauthorized or offline."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "tv_setup.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan("Deploy TCL TV voice assistant via ADB"), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/scripts/setup_tv.py b/scripts/setup_tv.py\n"
                "+++ b/scripts/setup_tv.py\n"
                "+def connect_tv():\n"
                "+    return '192.168.10.203:5555'\n"
                "diff --git a/tests/test_tv.py b/tests/test_tv.py\n"
                "+++ b/tests/test_tv.py\n"
                "+def test_negative_invalid_ip():\n"
                "+    assert connect_tv() != ''\n",
                encoding="utf-8",
            )
            (ev_dir / "adb_output.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n"
                "List of devices attached\n"
                "192.168.10.203:5555\tunauthorized\n"
                "error: device unauthorized.\n",
                encoding="utf-8",
            )

            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(res.returncode, 0)
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertIn("unauthorized", report.lower())

    def test_diff_review_rejects_unapproved_binary_dex_apk_patching_thrashing(self):
        """Reproduces TCL TV Steps 1507-1840: unapproved binary classes.dex patching inside third-party APKs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "patch_apk.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan("Fix Android TV voice assistant"), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/scripts/patch_ha_apk.py b/scripts/patch_ha_apk.py\n"
                "+++ b/scripts/patch_ha_apk.py\n"
                "+def hotpatch_apk():\n"
                "+    raw = open('classes.dex', 'rb').read()\n"
                "+    open('ha-patched-signed.apk', 'wb').write(raw)\n"
                "diff --git a/tests/test_patch.py b/tests/test_patch.py\n"
                "+++ b/tests/test_patch.py\n"
                "+def test_negative_corrupt_dex():\n"
                "+    assert 1 != 0\n",
                encoding="utf-8",
            )
            (ev_dir / "test.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n",
                encoding="utf-8",
            )

            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(res.returncode, 0)
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertIn("classes.dex", report.lower())

    def test_rules_gemini_hook_and_skills_codify_all_six_cross_session_gates(self):
        """Verify GLOBAL_DEVELOPMENT_RULES.md, GEMINI.md, asw-hook.mjs, and core skills codify all 6 Cross-Session Failure Prevention Gates."""
        rules_path = self.repo_root / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md"
        core_rules_path = self.repo_root / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md"
        gemini_path = self.repo_root / "global_entrypoint" / "GEMINI.md"
        hook_path = self.repo_root / "plugins" / "antigravity-swarm" / "scripts" / "asw-hook.mjs"

        rules_text = rules_path.read_text(encoding="utf-8")
        for required_term in (
            "Golden Reference & End-to-End Decision Parity Gate",
            "Mandatory Rendered DOM & Shadow-Root Zero-Error-Card Gate",
            "Boundary-to-Boundary Hardware / IoT / Voice Fidelity Gate",
            "3-Strike Anti-Thrashing & Root-Cause Escalation Circuit Breaker",
            "Feature-Flag & Negative-State Isolation Gate",
            "BLOCKED_ON_HARDWARE_AUTH",
            "hui-error-card",
        ):
            self.assertIn(required_term, rules_text, f"Missing {required_term!r} in GLOBAL_DEVELOPMENT_RULES.md")

        self.assertEqual(
            rules_text,
            core_rules_path.read_text(encoding="utf-8"),
            "GLOBAL_DEVELOPMENT_RULES.md must be identical in .antigravity/rules and core_framework/rules",
        )

        gemini_text = gemini_path.read_text(encoding="utf-8")
        for term in (
            "Golden Reference & End-to-End Decision Parity Gate",
            "Mandatory Rendered DOM & Shadow-Root Zero-Error-Card Gate",
            "3-Strike Anti-Thrashing",
            "BLOCKED_ON_HARDWARE_AUTH",
        ):
            self.assertIn(term, gemini_text, f"Missing {term!r} in GEMINI.md")

        hook_text = hook_path.read_text(encoding="utf-8")
        for term in (
            "Golden Reference",
            "hui-error-card",
            "BLOCKED_ON_HARDWARE_AUTH",
            "3-Strike",
        ):
            self.assertIn(term, hook_text, f"Missing {term!r} in asw-hook.mjs")

        self.assertEqual(
            self.reviewer_script.read_text(encoding="utf-8"),
            self.core_reviewer_script.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            self.gui_script.read_text(encoding="utf-8"),
            self.core_gui_script.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
