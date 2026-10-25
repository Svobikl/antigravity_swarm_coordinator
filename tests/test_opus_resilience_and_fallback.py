import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestOpusResilienceAndFallback(unittest.TestCase):
    """Adversarial test suite for Opus Cross-Review Quota Resilience, UTF-16LE Diff Decoding & PowerShell Anti-Hang."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.reviewer_script = self.repo_root / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"

    def _valid_closed_plan_text(self) -> str:
        return """# Implementation Plan

## Objective
Fix model discrepancies and cache with full governance compliance.

## Governance
Complies with GLOBAL_DEVELOPMENT_RULES and PROGRAM_INVARIANTS.
Includes RED, GREEN, QA, EVIDENCE, and CLEANUP phases with Windows lock and timeout handling.
Negative test failure and edge cases verified.

## Execution Tasks
- [x] Task 1: Implement and verify with negative and edge-case tests
  - **Files**: `services/market/model_inference.py`, `tests/test_model_discrepancies.py`
"""

    def test_utf16le_and_mixed_powershell_diff_decoding_passes_audit_diff(self):
        """Reproduces StrataRelay Steps 5014-5023: PowerShell `>` / `>>` writes UTF-16LE null bytes into diff files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "mixed_powershell.diff"
            ev_dir = tmp_path / "evidence"
            ev_dir.mkdir()
            (ev_dir / "pytest.log").write_text(
                "RED phase negative test fail verified -> GREEN 6 passed\n",
                encoding="utf-8",
            )
            plan_file.write_text(self._valid_closed_plan_text(), encoding="utf-8")

            # Part 1 written as UTF-8 (e.g. git diff), Part 2 appended as UTF-16LE (PowerShell Get-Content >>)
            part1_utf8 = (
                "diff --git a/services/market/model_inference.py b/services/market/model_inference.py\n"
                "+++ b/services/market/model_inference.py\n"
                "+def compute_panel():\n"
                "+    return XGBJsonBooster('model.json').predict([1.0, 2.0])\n"
            ).encode("utf-8")
            part2_utf16le = (
                "\ndiff --git a/tests/test_model_discrepancies.py b/tests/test_model_discrepancies.py\n"
                "+++ b/tests/test_model_discrepancies.py\n"
                "+def test_negative_and_edge_cases_vbp_cache():\n"
                "+    assert compute_panel() == 0.75\n"
                "+    assertRaises(ValueError)\n"
            ).encode("utf-16-le")
            diff_file.write_bytes(part1_utf8 + b"\xff\xfe" + part2_utf16le)

            out_file = tmp_path / "review.md"
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
            report = out_file.read_text(encoding="utf-8") if out_file.exists() else res.stdout + res.stderr
            self.assertEqual(res.returncode, 0, f"Mixed UTF-8/UTF-16LE diff should pass review, got:\n{report}")
            self.assertIn("Verdict: ASW APPROVED", report)

    def test_evidence_file_path_does_not_raise_not_a_directory_error(self):
        """Reproduces StrataRelay Step 5010: passing a file path to --evidence crashed with NotADirectoryError."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "changes.diff"
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._valid_closed_plan_text(), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/services/app.py b/services/app.py\n"
                "+++ b/services/app.py\n"
                "+def calc(x):\n"
                "+    return x + 1\n"
                "diff --git a/tests/test_app.py b/tests/test_app.py\n"
                "+++ b/tests/test_app.py\n"
                "+def test_negative_invalid_input():\n"
                "+    assert calc(1) == 2\n",
                encoding="utf-8",
            )

            # Pass plan_file (a FILE, not a directory) to --evidence
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
                    str(plan_file),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotIn("NotADirectoryError", res.stderr)
            self.assertEqual(res.returncode, 0, f"Single file --evidence should succeed, got:\n{res.stderr}\n{res.stdout}")
            self.assertIn("Verdict: ASW APPROVED", out_file.read_text(encoding="utf-8"))

    def test_self_contained_files_argument_collects_tracked_and_untracked_files(self):
        """Reproduces StrataRelay Step 5006 & 5014: --files collects tracked git diff + untracked test files directly."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)

            src_dir = tmp_path / "services"
            src_dir.mkdir()
            src_file = src_dir / "engine.py"
            src_file.write_text("def run():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "services/engine.py"], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

            # Modify tracked file
            src_file.write_text("def run(x):\n    return x * 2\n", encoding="utf-8")

            # Create UNTRACKED test file (not git-added!)
            tests_dir = tmp_path / "tests"
            tests_dir.mkdir()
            test_file = tests_dir / "test_engine.py"
            test_file.write_text(
                "def test_negative_and_edge_cases():\n"
                "    assert run(3) == 6\n"
                "    assert run(-1) == -2\n",
                encoding="utf-8",
            )

            # Create closed plan inside .asw/plans/ so auto-discovery also works
            plans_dir = tmp_path / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            plan_file = plans_dir / "my-plan.md"
            plan_file.write_text(self._valid_closed_plan_text(), encoding="utf-8")

            out_file = tmp_path / "out_review.md"
            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--mode",
                    "diff-review",
                    "--files",
                    "services/engine.py,tests/test_engine.py",
                    "--output",
                    str(out_file),
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"--files should auto-collect tracked + untracked files and auto-discover plan/evidence:\n{res.stdout}\n{res.stderr}",
            )
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW APPROVED", report)

    def test_opus_credit_exhaustion_automatic_fallback_never_blocks(self):
        """Verifies that exhausted Opus credits trigger automatic deterministic + Gemini 4 Argon High fallback without hanging."""
        # 1. Check --preflight metadata includes fallback_model and credit_exhaustion_policy
        pre = subprocess.run(
            [sys.executable, str(self.reviewer_script), "--preflight"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(pre.returncode, 0)
        pre_data = json.loads(pre.stdout)
        rt = pre_data.get("antigravity_runtime", {})
        self.assertEqual(rt.get("fallback_model"), "gemini-4-argon-high")
        self.assertEqual(rt.get("credit_exhaustion_policy"), "auto_fallback_deterministic_and_argon_high")

        # 2. Run diff-review with ANTIGRAVITY_OPUS_CREDITS_EXHAUSTED=1 and --fallback-reason
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_file = tmp_path / "plan.md"
            diff_file = tmp_path / "changes.diff"
            out_file = tmp_path / "review.md"

            plan_file.write_text(self._valid_closed_plan_text(), encoding="utf-8")
            diff_file.write_text(
                "diff --git a/services/app.py b/services/app.py\n"
                "+++ b/services/app.py\n"
                "+def compute(x):\n"
                "+    return x + 10\n"
                "diff --git a/tests/test_app.py b/tests/test_app.py\n"
                "+++ b/tests/test_app.py\n"
                "+def test_negative_boundary():\n"
                "+    assert compute(-5) == 5\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["ANTIGRAVITY_OPUS_CREDITS_EXHAUSTED"] = "1"
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
                    str(plan_file),
                    "--fallback-reason",
                    "opus_credits_exhausted",
                    "--output",
                    str(out_file),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(res.returncode, 0)
            report = out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW APPROVED", report)
            self.assertIn("Fallback Mode", report)
            self.assertIn("gemini-4-argon-high", report.lower())

    def test_clean_scratch_removes_nested_pycache_without_interactive_hang(self):
        """Reproduces StrataRelay 16-minute hang: scratch/__pycache__ caused PowerShell Remove-Item without -Recurse to hang."""
        with tempfile.TemporaryDirectory() as tmp:
            scratch_dir = Path(tmp) / "scratch"
            pycache_dir = scratch_dir / "__pycache__"
            pycache_dir.mkdir(parents=True)
            (pycache_dir / "helper.cpython-314.pyc").write_bytes(b"\x00\x01\x02")
            (scratch_dir / "model_fixes.diff").write_text("diff", encoding="utf-8")
            (scratch_dir / "opus_diff_review.json").write_text("{}", encoding="utf-8")

            res = subprocess.run(
                [
                    sys.executable,
                    str(self.reviewer_script),
                    "--clean-scratch",
                    str(scratch_dir),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res.returncode, 0, f"--clean-scratch failed: {res.stderr}")
            self.assertEqual(list(scratch_dir.iterdir()), [], "Scratch directory should be completely empty after --clean-scratch")

    def test_agent_tomls_and_rules_codify_opus_fallback_and_powershell_anti_hang(self):
        """Verifies agent TOMLs and governance rules include Opus quota fallback and PowerShell anti-hang directives."""
        for toml_name in ("asw-plan-audit.toml", "asw-opposition-reviewer.toml", "asw-reviewer.toml"):
            toml_path = self.repo_root / ".antigravity" / "agents" / toml_name
            content = toml_path.read_text(encoding="utf-8")
            self.assertIn('fallback_model = "gemini-4-argon-high"', content, f"{toml_name} missing fallback_model")
            self.assertIn("timeout_seconds =", content, f"{toml_name} missing timeout_seconds")

        rules_text = (self.repo_root / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md").read_text(encoding="utf-8")
        self.assertIn("Opus Credit", rules_text)
        self.assertIn("--files", rules_text)
        self.assertIn("-Recurse -Confirm:$false", rules_text)


if __name__ == "__main__":
    unittest.main()
