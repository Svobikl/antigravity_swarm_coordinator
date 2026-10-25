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

"""Adversarial test suite for Anti-Shortcut, Zero-Heuristic Substitution, and Prompt-to-Code Traceability gates."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestAntiShortcutAndOpusGates(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.script_path = (
            self.repo_root / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"
        )
        self.core_script_path = (
            self.repo_root / "core_framework" / "scripts" / "invoke_opus_reviewer.py"
        )
        self.hook_path = (
            self.repo_root
            / "plugins"
            / "antigravity-swarm"
            / "scripts"
            / "asw-hook.mjs"
        )

    def test_plan_review_rejects_heuristic_approximation_in_model_integration(self):
        """Plan review must reject a plan that proposes heuristic approximation instead of real trained model artifacts."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            bad_plan = (
                "# Implementation Plan: Integrate Trained XGBoost Model\n\n"
                "## Objective\n"
                "Integrate trained XGBoost model into live execution.\n\n"
                "## Governance & Invariants\n"
                "Complies with GLOBAL_DEVELOPMENT_RULES.md.\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Approximate with heuristic sigmoid formula\n"
                "  - Files: `services/market/engine.py`\n"
                "  - RED: test\n"
                "  - GREEN: approximate with heuristic sigmoid instead of loading booster\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: e1.txt\n"
                "  - Cleanup: finally\n"
            )
            plan_file = tmp_path / "bad_heuristic_plan.md"
            plan_file.write_text(bad_plan, encoding="utf-8")
            out_file = tmp_path / "review.md"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "plan-review",
                    "--plan",
                    str(plan_file),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc.returncode, 0)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: PLAN_REVISION_REQUIRED", content)
            self.assertIn("heuristic", content.lower())

    def test_diff_review_rejects_hand_coded_sigmoid_heuristic_substitution(self):
        """Diff review must reject production diffs that replace trained model inference with hand-coded logit/_sigmoid equations."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Task Plan\nFiles: `services/market/engine.py`, `tests/test_engine.py`\n",
                encoding="utf-8",
            )

            diff_file = tmp_path / "heuristic.diff"
            diff_file.write_text(
                "diff --git a/services/market/engine.py b/services/market/engine.py\n"
                "--- a/services/market/engine.py\n"
                "+++ b/services/market/engine.py\n"
                "@@ -10,3 +10,12 @@\n"
                "+def evaluate_model():\n"
                "+    v42_logit = (er12 - 0.25) * 2.2 + (er24 - 0.22) * 1.6\n"
                "+    pred_score = _sigmoid(v42_logit)\n"
                "+    return {'pred': pred_score, 'action': 'SCANNING'}\n"
                "diff --git a/tests/test_engine.py b/tests/test_engine.py\n"
                "--- a/tests/test_engine.py\n"
                "+++ b/tests/test_engine.py\n"
                "@@ -1,3 +1,6 @@\n"
                "+def test_negative_input_rejected():\n"
                "+    assert evaluate_model()['pred'] >= 0.0\n",
                encoding="utf-8",
            )

            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "task-1.txt").write_text(
                "RED PHASE: fail\nGREEN PHASE: ok\nnegative test passed\n",
                encoding="utf-8",
            )
            out_file = tmp_path / "diff_review.md"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
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
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc.returncode, 0)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", content)
            self.assertIn("heuristic", content.lower())

    def test_diff_review_rejects_catch_all_scanning_enter_long_and_naive_stoploss(self):
        """Diff review must reject catch-all SCANNING -> ENTER_LONG fallbacks and naive ternary stop_loss labels."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Task Plan\nFiles: `services/execution/worker.py`, `tests/test_worker.py`\n",
                encoding="utf-8",
            )

            diff_file = tmp_path / "bad_fallback.diff"
            diff_file.write_text(
                "diff --git a/services/execution/worker.py b/services/execution/worker.py\n"
                "--- a/services/execution/worker.py\n"
                "+++ b/services/execution/worker.py\n"
                "@@ -20,3 +20,9 @@\n"
                "+    else:\n"
                "+        pathway = 'SCANNING_6_PATHWAYS'\n"
                "+        action = 'ENTER_LONG' if score >= -0.08 else 'SCANNING'\n"
                "+    st.exit_reason = 'take_profit' if st.pnl_pct >= 0 else 'stop_loss'\n"
                "diff --git a/tests/test_worker.py b/tests/test_worker.py\n"
                "--- a/tests/test_worker.py\n"
                "+++ b/tests/test_worker.py\n"
                "@@ -1,3 +1,6 @@\n"
                "+def test_worker_negative_edge():\n"
                "+    assert 1 != 2\n",
                encoding="utf-8",
            )

            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "task-1.txt").write_text(
                "RED phase failed\nGREEN phase passed\nnegative edge verified\n",
                encoding="utf-8",
            )
            out_file = tmp_path / "diff_review.md"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
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
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc.returncode, 0)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", content)
            self.assertTrue(
                "scanning" in content.lower() or "stop_loss" in content.lower()
            )

    def test_diff_review_rejects_open_plan_checkboxes_and_tautological_tests(self):
        """Diff review must reject when the plan still has open '- [ ]' checkboxes or when tests are purely tautological."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Task Plan\n- [x] Task 1\n- [ ] Task 2 left unfinished\n",
                encoding="utf-8",
            )

            diff_file = tmp_path / "tautology.diff"
            diff_file.write_text(
                "diff --git a/src/mod.py b/src/mod.py\n"
                "--- a/src/mod.py\n"
                "+++ b/src/mod.py\n"
                "@@ -1,2 +1,4 @@\n"
                "+def run():\n"
                "+    return {'status': 'ok'}\n"
                "diff --git a/tests/test_mod.py b/tests/test_mod.py\n"
                "--- a/tests/test_mod.py\n"
                "+++ b/tests/test_mod.py\n"
                "@@ -1,2 +1,5 @@\n"
                "+def test_negative_edge():\n"
                "+    res = run()\n"
                "+    assert res is not None\n",
                encoding="utf-8",
            )

            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "task-1.txt").write_text(
                "RED phase fail\nGREEN phase pass\nnegative check\n",
                encoding="utf-8",
            )
            out_file = tmp_path / "diff_review.md"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
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
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc.returncode, 0)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", content)
            self.assertTrue(
                "unchecked" in content.lower() or "tautolog" in content.lower()
            )

    def test_rules_hooks_and_skills_enforce_zero_heuristic_and_traceability(self):
        """Verify GLOBAL_DEVELOPMENT_RULES.md, GEMINI.md, asw-hook.mjs, and core skills enforce Zero Heuristic Substitution and Prompt-to-Code Traceability."""
        rules_text = (
            self.repo_root / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Zero Heuristic Substitution", rules_text)
        self.assertIn("Prompt-to-Code Traceability", rules_text)

        gemini_text = (
            self.repo_root / "global_entrypoint" / "GEMINI.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Zero Heuristic Substitution", gemini_text)

        hook_text = self.hook_path.read_text(encoding="utf-8")
        self.assertIn("Zero Heuristic Substitution", hook_text)
        self.assertIn("User Intent & Anti-Shortcut Contract", hook_text)

        self.assertEqual(
            self.script_path.read_text(encoding="utf-8"),
            self.core_script_path.read_text(encoding="utf-8"),
            "invoke_opus_reviewer.py must be identical in .antigravity/scripts and core_framework/scripts",
        )


if __name__ == "__main__":
    unittest.main()
