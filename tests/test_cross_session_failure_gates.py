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
                "+    return '<TV_IP>:5555'\n"
                "diff --git a/tests/test_tv.py b/tests/test_tv.py\n"
                "+++ b/tests/test_tv.py\n"
                "+def test_negative_invalid_ip():\n"
                "+    assert connect_tv() != ''\n",
                encoding="utf-8",
            )
            (ev_dir / "adb_output.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n"
                "List of devices attached\n"
                "emulator-5554\tunauthorized\n"
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
            "Multi-Tenant State Isolation & Pre-Exchange Idempotency Gate",
            "Production-Volume Distribution & Non-Degenerate Curve Gate",
            "Public-Repo IP, Secret & PII Sanitization Gate",
            "Baseline Feature Survival & Dual-Mode Regression Matrix Gate",
            "Stale Asset & Browser Cache-Buster Verification Gate",
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
            "Multi-Tenant State Isolation & Pre-Exchange Idempotency Gate",
            "Public-Repo IP, Secret & PII Sanitization Gate",
            "Stale Asset & Browser Cache-Buster Verification Gate",
        ):
            self.assertIn(term, gemini_text, f"Missing {term!r} in GEMINI.md")

        hook_text = hook_path.read_text(encoding="utf-8")
        for term in (
            "Golden Reference",
            "hui-error-card",
            "BLOCKED_ON_HARDWARE_AUTH",
            "3-Strike",
            "--scan-public-repo",
            "--assert-asset-version",
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

    def test_diff_review_rejects_non_tenant_idempotency_key_in_multi_tenant_worker(self):
        """Reproduces EdgeRelay Step 6617 (Oct 29): global idempotency_key = signal_key without tenant_id scoping caused DB rollback after live Binance fill for user shadius."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "worker_idempotency.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan("Execute multi-tenant trades"), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/services/execution/worker.py b/services/execution/worker.py\n"
                "+++ b/services/execution/worker.py\n"
                "+def _execute_tenant_trade(tenant_id: str, signal_key: str):\n"
                "+    trade = Trade(tenant_id=tenant_id, idempotency_key=signal_key)\n"
                "+    return trade\n"
                "diff --git a/tests/test_worker.py b/tests/test_worker.py\n"
                "+++ b/tests/test_worker.py\n"
                "+def test_negative_duplicate_rejected():\n"
                "+    assert 1 == 1\n",
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
            self.assertNotEqual(
                res.returncode,
                0,
                "Non-tenant-scoped idempotency_key=signal_key in multi-tenant code must be rejected!",
            )
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertIn("idempotency_key", report.lower())

    def test_diff_review_rejects_capped_denominator_shock_explosion_and_flat_zero_drawdown(self):
        """Reproduces EdgeRelay Steps 6126 & 6617: sum divided by min(8.0, len(scores_24h)) and degenerate all-zero drawdownPct series."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "bad_quant.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._closed_plan("Compute semantic shock and drawdown series"), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/services/market/v43_semantic_engine.py b/services/market/v43_semantic_engine.py\n"
                "+++ b/services/market/v43_semantic_engine.py\n"
                "+def compute_shock(scores_24h):\n"
                "+    shock_density = sum(scores_24h) / min(8.0, float(len(scores_24h) or 1))\n"
                "+    pts = [\n"
                "+        {'date': '2022-01', 'drawdownPct': 0.0},\n"
                "+        {'date': '2023-01', 'drawdownPct': 0.0},\n"
                "+        {'date': '2024-01', 'drawdownPct': 0.0},\n"
                "+        {'date': '2025-01', 'drawdownPct': 0.0},\n"
                "+        {'date': '2026-01', 'drawdownPct': 0.0},\n"
                "+    ]\n"
                "+    return shock_density, pts\n"
                "diff --git a/tests/test_quant.py b/tests/test_quant.py\n"
                "+++ b/tests/test_quant.py\n"
                "+def test_negative_empty_scores():\n"
                "+    assert compute_shock([])[0] == 0.0\n",
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
            self.assertTrue("min(" in report.lower() or "drawdown" in report.lower())

    def test_scan_public_repo_and_diff_review_reject_private_ips_api_keys_and_forbid_terms(self):
        """Reproduces Deye/TCL TV Step 4818 (Oct 28): pushing private LAN IPs, API keys, or location PII to a public GitHub repo."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_dir = tmp_path / "public_repo"
            repo_dir.mkdir()
            sample_lan_ip = ".".join(["192", "168", "99", "203"])
            (repo_dir / "setup_tv.py").write_text(
                f"TV_HOST = '{sample_lan_ip}:5555'\n"
                "HOME_NAME = 'MySecretLocationSmartHome'\n",
                encoding="utf-8",
            )

            # 1. Standalone --scan-public-repo CLI mode must fail and report both the LAN IP and forbidden term
            scan_res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--scan-public-repo",
                    str(repo_dir),
                    "--forbid-terms",
                    "SecretLocation,PrivateOwner",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(
                scan_res.returncode,
                0,
                "--scan-public-repo must fail when private LAN IPs or forbidden PII terms exist!",
            )
            self.assertIn(sample_lan_ip, scan_res.stdout)
            self.assertIn("SecretLocation", scan_res.stdout)

            # 2. Clean repo with placeholders passes --scan-public-repo
            (repo_dir / "setup_tv.py").write_text(
                "TV_HOST = '<TV_IP_ADDRESS>:5555'\n"
                "HOME_NAME = 'MySmartHome'\n",
                encoding="utf-8",
            )
            scan_ok = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--scan-public-repo",
                    str(repo_dir),
                    "--forbid-terms",
                    "SecretLocation,PrivateOwner",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(scan_ok.returncode, 0, f"Sanitized public repo should pass:\n{scan_ok.stdout}")


if __name__ == "__main__":
    unittest.main()
