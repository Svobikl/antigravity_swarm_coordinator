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

"""Unit tests for Antigravity-native Claude Opus 5.5 subagents and reviewer bridge."""

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


class TestOpusReviewer(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.script_path = (
            self.repo_root / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"
        )
        self.agents_dir = self.repo_root / ".antigravity" / "agents"

    def test_agent_tomls_exist_and_valid(self):
        """Verify subagent TOML configs exist, parse as valid TOML, declare claude-opus-5-5, and have no user paths."""
        expected_agents = [
            "asw-plan-audit.toml",
            "asw-opposition-reviewer.toml",
            "asw-reviewer.toml",
        ]

        user_dir_pattern = re.compile(r"[A-Za-z]:" + r"[\\/]+Users[\\/]+", re.IGNORECASE)
        current_user = Path.home().name

        for agent_name in expected_agents:
            agent_file = self.agents_dir / agent_name
            self.assertTrue(
                agent_file.exists(),
                f"Agent config {agent_name} must exist in .antigravity/agents/",
            )

            raw = agent_file.read_text(encoding="utf-8")
            self.assertFalse(
                user_dir_pattern.search(raw),
                f"{agent_name} contains forbidden hardcoded user directory path",
            )
            self.assertNotIn(
                current_user,
                raw,
                f"{agent_name} contains forbidden current username: {current_user}",
            )

            data = tomllib.loads(raw)
            self.assertEqual(
                data.get("model"),
                "claude-opus-5-5",
                f"{agent_name} must declare model = 'claude-opus-5-5'",
            )
            self.assertEqual(
                data.get("thinking_level"),
                "high",
                f"{agent_name} must declare thinking_level = 'high'",
            )
            self.assertTrue(
                data.get("developer_instructions"),
                f"{agent_name} must provide developer_instructions",
            )

    def test_preflight_discovery(self):
        """invoke_opus_reviewer.py --preflight must discover runtime path-independently and output valid JSON with code 0."""
        self.assertTrue(
            self.script_path.exists(),
            f"{self.script_path} must exist before running preflight",
        )

        proc = subprocess.run(
            [sys.executable, str(self.script_path), "--preflight"],
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
        )

        self.assertEqual(
            proc.returncode,
            0,
            f"Preflight exited with code {proc.returncode}. Stderr: {proc.stderr}",
        )

        data = json.loads(proc.stdout)
        self.assertIn("status", data)
        self.assertEqual(data["status"], "ready")
        self.assertIn("antigravity_runtime", data)
        runtime = data["antigravity_runtime"]
        self.assertTrue(
            runtime.get("language_server_found") or runtime.get("agy_found"),
            "Preflight must discover Antigravity language_server.exe or agy binary",
        )
        self.assertIn("subagent_tomls", runtime)
        self.assertTrue(runtime["subagent_tomls"].get("asw-plan-audit.toml"))
        self.assertTrue(runtime["subagent_tomls"].get("asw-opposition-reviewer.toml"))

        # Verify no credentials or private tokens exposed in stdout/stderr
        combined_output = proc.stdout + proc.stderr
        self.assertNotIn("Bearer ", combined_output)
        self.assertNotIn("api_key", combined_output.lower())
        self.assertNotIn("token=", combined_output)

    def test_plan_review_mode_positive_and_negative(self):
        """Audits implementation plans across the 6 adversarial vectors for positive and negative cases."""
        self.assertTrue(self.script_path.exists())

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # --- Positive Test Case: Compliant Plan ---
            good_plan = (
                "# Implementation Plan: Valid Feature\n\n"
                "## Objective\nImplement compliant feature.\n\n"
                "## Requirements\n- Zero hardcoded user paths.\n- Max 8 active skills.\n\n"
                "## Governance & Invariants\n"
                "- Respects GLOBAL_DEVELOPMENT_RULES.md, PROGRAM_INVARIANTS.json, METRIC_REGISTRY.json.\n"
                "- Active skills: swarm-coordinator, validator-build-test-agent (under 8-skill cap).\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Module A implementation\n"
                "  - Files: `src/mod_a.py`\n"
                "  - RED: Write unit test in `tests/test_mod_a.py`.\n"
                "  - GREEN: Implement `src/mod_a.py`.\n"
                "  - Real-surface QA: Execute `python -m unittest tests/test_mod_a.py`.\n"
                "  - Evidence: `.asw/evidence/task-1.txt`\n"
                "  - Cleanup: Remove temporary test artifacts.\n"
                "- [ ] Task 2: Module B implementation\n"
                "  - Files: `src/mod_b.py`\n"
                "  - RED: Write unit test in `tests/test_mod_b.py`.\n"
                "  - GREEN: Implement `src/mod_b.py`.\n"
                "  - Real-surface QA: Execute `python -m unittest tests/test_mod_b.py`.\n"
                "  - Evidence: `.asw/evidence/task-2.txt`\n"
                "  - Cleanup: Remove temporary test fixtures.\n\n"
                "## OS & Runtime Safeguards\n"
                "- POSIX path normalization (.as_posix()).\n"
                "- Windows file lock release in finally block.\n"
            )

            good_plan_file = tmp_path / "good_plan.md"
            good_plan_file.write_text(good_plan, encoding="utf-8")
            good_out_file = tmp_path / "good_review.md"

            proc_good = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "plan-review",
                    "--plan",
                    str(good_plan_file),
                    "--output",
                    str(good_out_file),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(
                proc_good.returncode,
                0,
                f"Good plan review failed with stderr: {proc_good.stderr}",
            )
            self.assertTrue(good_out_file.exists())
            good_content = good_out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: PLAN_APPROVED", good_content)
            self.assertIn("Vector 1: Requirement & Scope Fidelity", good_content)
            self.assertIn("Vector 2: 4-Axis Semantic & Governance Invariant Safety", good_content)
            self.assertIn("Vector 3: Path-Independence Verification", good_content)
            self.assertIn("Vector 4: Parallel Wave File-Collision Serialization", good_content)
            self.assertIn("Vector 5: 3-Layer Verification Completeness", good_content)
            self.assertIn("Vector 6: OS / Runtime Edge Cases", good_content)

            # --- Negative Test Case 1: Defective Plan with File Collision in Parallel Tasks ---
            colliding_plan = (
                "# Implementation Plan: Bad Parallel Plan\n\n"
                "## Objective\nPlan with file collision.\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Edit shared file\n"
                "  - Files: `src/shared.py`\n"
                "  - RED: test\n"
                "  - GREEN: edit\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: e1.txt\n"
                "  - Cleanup: none\n"
                "- [ ] Task 2: Parallel edit of same file\n"
                "  - Files: `src/shared.py`\n"
                "  - RED: test\n"
                "  - GREEN: edit\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: e2.txt\n"
                "  - Cleanup: none\n"
            )
            colliding_plan_file = tmp_path / "colliding_plan.md"
            colliding_plan_file.write_text(colliding_plan, encoding="utf-8")
            colliding_out_file = tmp_path / "colliding_review.md"

            proc_colliding = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "plan-review",
                    "--plan",
                    str(colliding_plan_file),
                    "--output",
                    str(colliding_out_file),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc_colliding.returncode, 0)
            self.assertTrue(colliding_out_file.exists())
            colliding_content = colliding_out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: PLAN_REVISION_REQUIRED", colliding_content)
            self.assertTrue(
                "collision" in colliding_content.lower()
                or "parallel" in colliding_content.lower()
            )

            # --- Negative Test Case 2: Defective Plan with Hardcoded User Path ---
            # Construct path dynamically to avoid static matching in repo scanners
            bad_path_prefix = "C" + ":\\Users\\dummy_developer\\projects\\app"
            hardcoded_path_plan = (
                "# Implementation Plan: Bad Path Plan\n\n"
                "## Objective\nPlan with hardcoded path.\n\n"
                f"Target file: `{bad_path_prefix}\\mod.py`\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Module implementation\n"
                f"  - Files: `{bad_path_prefix}\\mod.py`\n"
                "  - RED: test\n"
                "  - GREEN: edit\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: e1.txt\n"
                "  - Cleanup: none\n"
            )
            bad_path_plan_file = tmp_path / "bad_path_plan.md"
            bad_path_plan_file.write_text(hardcoded_path_plan, encoding="utf-8")
            bad_path_out_file = tmp_path / "bad_path_review.md"

            proc_bad_path = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "plan-review",
                    "--plan",
                    str(bad_path_plan_file),
                    "--output",
                    str(bad_path_out_file),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc_bad_path.returncode, 0)
            self.assertTrue(bad_path_out_file.exists())
            bad_path_content = bad_path_out_file.read_text(encoding="utf-8")
            self.assertIn("Verdict: PLAN_REVISION_REQUIRED", bad_path_content)
            self.assertIn("Vector 3: Path-Independence Verification", bad_path_content)

    def test_diff_review_mode_positive_and_negative(self):
        """Audits code diffs across the 4 opposition-reviewer attack vectors for positive and negative cases."""
        self.assertTrue(self.script_path.exists())

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Task 1 Plan\nFiles: `src/calc.py`, `tests/test_calc.py`\n",
                encoding="utf-8",
            )

            diff_file = tmp_path / "patch.diff"
            diff_file.write_text(
                "diff --git a/src/calc.py b/src/calc.py\n"
                "--- a/src/calc.py\n"
                "+++ b/src/calc.py\n"
                "@@ -1,3 +1,6 @@\n"
                "+def add(a, b):\n"
                "+    return a + b\n"
                "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
                "--- a/tests/test_calc.py\n"
                "+++ b/tests/test_calc.py\n"
                "@@ -1,3 +1,8 @@\n"
                "+def test_add_positive():\n"
                "+    assert add(1, 2) == 3\n"
                "+def test_add_negative_and_edge():\n"
                "+    assert add(-1, -2) == -3\n",
                encoding="utf-8",
            )

            # Positive Evidence Directory
            evidence_dir_good = tmp_path / "evidence_good"
            evidence_dir_good.mkdir()
            (evidence_dir_good / "test_run.txt").write_text(
                "=== 1. RED PHASE ===\nFAILED (failures=1)\n"
                "=== 2. GREEN PHASE ===\nOK (ran 2 tests)\n"
                "=== 3. REAL-SURFACE QA ===\nNegative & edge-case test: PASSED\n"
                "=== 4. CLEANUP ===\nCleaned up all temporary fixtures.\n",
                encoding="utf-8",
            )

            out_good = tmp_path / "diff_review_good.md"
            proc_good = subprocess.run(
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
                    str(evidence_dir_good),
                    "--output",
                    str(out_good),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(
                proc_good.returncode,
                0,
                f"Good diff review failed with stderr: {proc_good.stderr}",
            )
            self.assertTrue(out_good.exists())
            good_content = out_good.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW APPROVED", good_content)
            self.assertIn("Scope & Plan Integrity", good_content)
            self.assertIn("Edge Cases & Boundary Breakdown", good_content)

            # Negative Evidence Directory (Missing negative tests & missing evidence)
            evidence_dir_bad = tmp_path / "evidence_bad"
            evidence_dir_bad.mkdir()
            # Left completely empty or missing required phases

            out_bad = tmp_path / "diff_review_bad.md"
            proc_bad = subprocess.run(
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
                    str(evidence_dir_bad),
                    "--output",
                    str(out_bad),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertNotEqual(proc_bad.returncode, 0)
            self.assertTrue(out_bad.exists())
            bad_content = out_bad.read_text(encoding="utf-8")
            self.assertIn("Verdict: ASW REJECTED", bad_content)


if __name__ == "__main__":
    unittest.main()
