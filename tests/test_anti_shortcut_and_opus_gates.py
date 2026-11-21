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
                "+    manual_logit = (er12 - 0.25) * 2.2 + (er24 - 0.22) * 1.6\n"
                "+    pred_score = _sigmoid(manual_logit)\n"
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

    def test_diff_review_accepts_cpp_and_typescript_negative_tests(self):
        """Attack Vector 3 and Tripwire 3A must recognize C++ (GTest) and TypeScript (Vitest/Jest) negative/edge tests."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Implementation Plan\n\n"
                "## Objective\nHarden frame parser and token validator.\n\n"
                "## Governance & Invariants\nComplies with GLOBAL_DEVELOPMENT_RULES and PROGRAM_INVARIANTS.\n"
                "Includes RED, GREEN, QA, EVIDENCE, and CLEANUP with Windows/POSIX timeout handling.\n\n"
                "## Execution Tasks\n- [x] Task 1: Parse and validate\n",
                encoding="utf-8",
            )
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "test.log").write_text(
                "RED phase fail -> GREEN phase passed, negative cases verified\n",
                encoding="utf-8",
            )

            # 1. C++ / GTest negative test diff
            cpp_diff = tmp_path / "cpp.diff"
            cpp_diff.write_text(
                "diff --git a/src/parser.cpp b/src/parser.cpp\n"
                "+++ b/src/parser.cpp\n"
                "+int parse_frame(int len) {\n"
                "+    if (len <= 0) throw std::invalid_argument(\"bad len\");\n"
                "+    return len;\n"
                "+}\n"
                "diff --git a/tests/parser_test.cpp b/tests/parser_test.cpp\n"
                "+++ b/tests/parser_test.cpp\n"
                "+TEST_F(ParserTest, RejectsInvalidFrame) {\n"
                "+    EXPECT_THROW(parse_frame(-1), std::invalid_argument);\n"
                "+}\n",
                encoding="utf-8",
            )
            out_cpp = tmp_path / "cpp_review.md"
            res_cpp = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(cpp_diff),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_cpp),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(
                res_cpp.returncode,
                0,
                f"C++ TEST_F + EXPECT_THROW negative test should pass:\n{out_cpp.read_text(encoding='utf-8') if out_cpp.exists() else res_cpp.stderr}",
            )
            self.assertIn("Verdict: ASW APPROVED", out_cpp.read_text(encoding="utf-8"))

            # 2. TypeScript / Vitest negative test diff
            ts_diff = tmp_path / "ts.diff"
            ts_diff.write_text(
                "diff --git a/src/token.ts b/src/token.ts\n"
                "+++ b/src/token.ts\n"
                "+export function parseToken(raw: string): string {\n"
                "+    if (!raw) throw new Error('empty token');\n"
                "+    return raw.trim();\n"
                "+}\n"
                "diff --git a/tests/token.test.ts b/tests/token.test.ts\n"
                "+++ b/tests/token.test.ts\n"
                "+it('rejects invalid token', () => {\n"
                "+    expect(() => parseToken('')).toThrow('empty token');\n"
                "+});\n",
                encoding="utf-8",
            )
            out_ts = tmp_path / "ts_review.md"
            res_ts = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(ts_diff),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_ts),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(
                res_ts.returncode,
                0,
                f"TypeScript it() + expect().toThrow() negative test should pass:\n{out_ts.read_text(encoding='utf-8') if out_ts.exists() else res_ts.stderr}",
            )
            self.assertIn("Verdict: ASW APPROVED", out_ts.read_text(encoding="utf-8"))

    def test_gate_1a_allows_non_plan_frozen_tag_mentions_but_blocks_plan_contract_tampering(self):
        """BMAD Gate 1A must ignore prose/code mentions of <frozen-after-approval> in non-plan files, while catching tampering inside .asw/plans/<slug>.md."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "feature-plan.md"
            plan_file.write_text(
                "# Feature Plan\n\n"
                "## Objective\nDocument contract rules.\n\n"
                "## Governance & Invariants\nGLOBAL_DEVELOPMENT_RULES\nWindows/POSIX timeout.\n\n"
                "## Execution Tasks\n- [x] Task 1: Update docs\n",
                encoding="utf-8",
            )
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "test.log").write_text(
                "RED phase fail -> GREEN phase passed, negative test verified\n",
                encoding="utf-8",
            )

            # 1. Non-plan diff mentioning <frozen-after-approval> in context/deleted/added lines of README.md must PASS
            non_plan_diff = tmp_path / "docs.diff"
            non_plan_diff.write_text(
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -10,3 +10,3 @@\n"
                " Docs explain <frozen-after-approval> blocks.\n"
                "-Old text mentioning Argon.\n"
                "+New text mentioning Neon.\n"
                "diff --git a/tests/test_docs.py b/tests/test_docs.py\n"
                "+++ b/tests/test_docs.py\n"
                "+def test_negative_doc_guard():\n"
                "+    assert 'frozen' != ''\n",
                encoding="utf-8",
            )
            out_ok = tmp_path / "non_plan_review.md"
            res_ok = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(non_plan_diff),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_ok),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(
                res_ok.returncode,
                0,
                f"Non-plan diff mentioning <frozen-after-approval> must pass:\n{out_ok.read_text(encoding='utf-8') if out_ok.exists() else res_ok.stderr}",
            )
            self.assertIn("Verdict: ASW APPROVED", out_ok.read_text(encoding="utf-8"))

            # 2. Tampering inside .asw/plans/feature-plan.md <!-- <frozen-after-approval> --> MUST FAIL
            tamper_diff = tmp_path / "tamper.diff"
            tamper_diff.write_text(
                "diff --git a/.asw/plans/feature-plan.md b/.asw/plans/feature-plan.md\n"
                "--- a/.asw/plans/feature-plan.md\n"
                "+++ b/.asw/plans/feature-plan.md\n"
                "@@ -5,3 +5,3 @@\n"
                " <!-- <frozen-after-approval> -->\n"
                "-| M1 | Input | Must reject |\n"
                "+| M1 | Input | Weakened expectation |\n"
                " <!-- </frozen-after-approval> -->\n"
                "diff --git a/tests/test_docs.py b/tests/test_docs.py\n"
                "+++ b/tests/test_docs.py\n"
                "+def test_negative_doc_guard():\n"
                "+    assert 'frozen' != ''\n",
                encoding="utf-8",
            )
            out_bad = tmp_path / "tamper_review.md"
            res_bad = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "diff-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(tamper_diff),
                    "--evidence",
                    str(ev_dir),
                    "--output",
                    str(out_bad),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(res_bad.returncode, 0)
            bad_text = out_bad.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", bad_text)
            self.assertIn("BMAD_FROZEN_CONTRACT_VIOLATION", bad_text)

    def test_tripwire_4b_catches_multi_hyphen_custom_error_card(self):
        """Tripwire 4B must catch multi-hyphen custom error cards like <my-custom-widget-error-card>."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# UI Plan\n\n## Objective\nRender dashboard.\n\n## Governance\nGLOBAL_DEVELOPMENT_RULES\n\n## Tasks\n- [x] Task 1\n",
                encoding="utf-8",
            )
            diff_file = tmp_path / "ui.diff"
            diff_file.write_text(
                "diff --git a/src/ui.ts b/src/ui.ts\n"
                "+++ b/src/ui.ts\n"
                "+export const renderCard = () => 'ok';\n"
                "diff --git a/tests/ui.test.ts b/tests/ui.test.ts\n"
                "+++ b/tests/ui.test.ts\n"
                "+it('rejects invalid props', () => { expect(() => renderCard()).not.toThrow(); });\n",
                encoding="utf-8",
            )
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "gui.log").write_text(
                "RED phase fail -> GREEN phase pass, negative edge verified\n"
                "DOM dump: <my-custom-widget-error-card>Broken render</my-custom-widget-error-card>\n",
                encoding="utf-8",
            )
            out_file = tmp_path / "review.md"
            res = subprocess.run(
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
            self.assertNotEqual(res.returncode, 0)
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", report)
            self.assertIn("my-custom-widget-error-card", report.lower())


if __name__ == "__main__":
    unittest.main()
