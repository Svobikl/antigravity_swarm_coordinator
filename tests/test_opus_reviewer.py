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

    def test_np_bench_transitive_wave_race_and_serialized_pass(self):
        """M3: Vector 4 detects transitive DAG races across imports/tests/CLI/JSON in parallel waves, passes when serialized or files missing."""
        scripts_dir = str(self.repo_root / ".antigravity" / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import invoke_opus_reviewer as reviewer

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # 1) Py AST import race: mod_b.py imports mod_a, disjoint Files in Wave 1
            (tmp_path / "mod_a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (tmp_path / "mod_b.py").write_text("import mod_a\n\ndef get_val():\n    return mod_a.VALUE\n", encoding="utf-8")

            parallel_plan_template = (
                "# Plan: Parallel DAG Test\n\n"
                "## Objective\nVerify transitive wave race detection.\n\n"
                "## Governance & Invariants\nComplies with GLOBAL_DEVELOPMENT_RULES and PROGRAM_INVARIANTS.\n\n"
                "## Parallel Execution Waves\n"
                "{waves}\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Update A\n"
                "  - **Files**: `mod_a.py`\n"
                "  - RED/GREEN: pytest tests/test_a.py\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: `.asw/evidence/t1.txt`\n"
                "  - Cleanup: finally cleanup\n"
                "- [ ] Task 2: Update B\n"
                "  - **Files**: `mod_b.py`\n"
                "  - RED/GREEN: pytest tests/test_b.py\n"
                "  - Real-surface QA: run\n"
                "  - Evidence: `.asw/evidence/t2.txt`\n"
                "  - Cleanup: finally cleanup\n"
            )
            plan_parallel = tmp_path / "plan_parallel.md"
            plan_parallel.write_text(
                parallel_plan_template.format(waves="- Wave 1: Task 1, Task 2"),
                encoding="utf-8",
            )
            verdict, findings, report = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict, "PLAN_REVISION_REQUIRED", report)
            crit_msgs = [f["message"] for f in findings if f["level"] == "CRITICAL"]
            self.assertTrue(
                any("NP_BENCH_TRANSITIVE_WAVE_RACE" in m and "task_2(mod_b.py) -> mod_a.py(task_1)" in m for m in crit_msgs),
                f"Expected NP_BENCH_TRANSITIVE_WAVE_RACE edge in {crit_msgs}",
            )

            # 2) Serialized waves (Wave 1: Task 1, Wave 2: Task 2) on exact same files -> PLAN_APPROVED
            plan_serial = tmp_path / "plan_serial.md"
            plan_serial.write_text(
                parallel_plan_template.format(waves="- Wave 1: Task 1\n- Wave 2: Task 2"),
                encoding="utf-8",
            )
            verdict_s, findings_s, report_s = reviewer.audit_plan(plan_serial)
            self.assertEqual(verdict_s, "PLAN_APPROVED", report_s)
            self.assertFalse(any("NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"] for f in findings_s))

            # 3) Test file transitive race: mod_b.py does NOT import mod_a, but tests/test_b.py imports mod_a
            (tmp_path / "mod_b.py").write_text("def pure_b():\n    return 2\n", encoding="utf-8")
            (tmp_path / "tests").mkdir()
            (tmp_path / "tests" / "test_b.py").write_text("from mod_a import VALUE\n\ndef test_b():\n    assert VALUE == 1\n", encoding="utf-8")
            verdict_t, findings_t, report_t = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict_t, "PLAN_REVISION_REQUIRED", report_t)
            self.assertTrue(
                any(
                    f["level"] == "CRITICAL"
                    and "NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"]
                    and "task_2(tests/test_b.py) -> mod_a.py(task_1)" in f["message"]
                    for f in findings_t
                ),
                f"Expected test transitive race in {findings_t}",
            )
            (tmp_path / "tests" / "test_b.py").unlink()

            # 4) Shared CLI spawn (decision_router.py / token_economizer.py / asw-stop-check.mjs) & shared decision_config.json
            (tmp_path / "mod_a.py").write_text("import subprocess\nsubprocess.run(['python', 'decision_router.py'])\n", encoding="utf-8")
            (tmp_path / "mod_b.py").write_text("import subprocess\nsubprocess.run(['python', 'decision_router.py'])\n", encoding="utf-8")
            verdict_cli, findings_cli, _ = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict_cli, "PLAN_REVISION_REQUIRED")
            self.assertTrue(
                any(
                    "NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"]
                    and "task_2(mod_b.py) -> decision_router.py" in f["message"]
                    and "(task_1)" in f["message"]
                    for f in findings_cli
                ),
                f"Expected shared CLI race in {findings_cli}",
            )

            (tmp_path / "mod_a.py").write_text("import subprocess\nsubprocess.run(['node', 'asw-stop-check.mjs'])\n", encoding="utf-8")
            (tmp_path / "mod_b.py").write_text("import subprocess\nsubprocess.run(['node', 'asw-stop-check.mjs'])\n", encoding="utf-8")
            verdict_mjs_cli, findings_mjs_cli, _ = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict_mjs_cli, "PLAN_REVISION_REQUIRED")
            self.assertTrue(
                any("NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"] and "asw-stop-check.mjs" in f["message"] for f in findings_mjs_cli),
                f"Expected shared asw-stop-check.mjs race in {findings_mjs_cli}",
            )

            # Multi-hop transitive Py import: mod_b.py -> helper.py -> mod_a.py
            (tmp_path / "mod_a.py").write_text("VALUE = 42\n", encoding="utf-8")
            (tmp_path / "helper.py").write_text("import mod_a\n\ndef h():\n    return mod_a.VALUE\n", encoding="utf-8")
            (tmp_path / "mod_b.py").write_text("import helper\n\ndef b():\n    return helper.h()\n", encoding="utf-8")
            verdict_hop, findings_hop, _ = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict_hop, "PLAN_REVISION_REQUIRED")
            self.assertTrue(
                any("NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"] and "task_2(mod_b.py) -> helper.py -> mod_a.py(task_1)" in f["message"] for f in findings_hop),
                f"Expected multi-hop race in {findings_hop}",
            )

            (tmp_path / "mod_a.py").write_text("CFG = 'decision_config.json'\n", encoding="utf-8")
            (tmp_path / "mod_b.py").write_text("CFG = 'decision_config.json'\n", encoding="utf-8")
            verdict_json, findings_json, _ = reviewer.audit_plan(plan_parallel)
            self.assertEqual(verdict_json, "PLAN_REVISION_REQUIRED")
            self.assertTrue(
                any(
                    "NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"]
                    and "task_2(mod_b.py) -> decision_config.json" in f["message"]
                    and "(task_1)" in f["message"]
                    for f in findings_json
                ),
                f"Expected shared JSON config race in {findings_json}",
            )

            # 5) ESM import race (.mjs)
            (tmp_path / "a.mjs").write_text("export const x = 1;\n", encoding="utf-8")
            (tmp_path / "b.mjs").write_text("import { x } from './a.mjs';\nexport const y = x + 1;\n", encoding="utf-8")
            esm_plan = tmp_path / "esm_plan.md"
            esm_plan.write_text(
                "# Plan: ESM DAG\n\n## Objective\nESM check.\n\n## Governance & Invariants\nGLOBAL_DEVELOPMENT_RULES\n\n"
                "## Parallel Execution Waves\n- Wave 1: Task 1, Task 2\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Edit a.mjs\n  - **Files**: `a.mjs`\n  - RED/GREEN/QA/Evidence/Cleanup: all covered on POSIX\n"
                "- [ ] Task 2: Edit b.mjs\n  - **Files**: `b.mjs`\n  - RED/GREEN/QA/Evidence/Cleanup: all covered on POSIX\n",
                encoding="utf-8",
            )
            verdict_esm, findings_esm, _ = reviewer.audit_plan(esm_plan)
            self.assertEqual(verdict_esm, "PLAN_REVISION_REQUIRED")
            self.assertTrue(
                any("NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"] and "task_2(b.mjs) -> a.mjs(task_1)" in f["message"] for f in findings_esm),
                f"Expected ESM race in {findings_esm}",
            )

            # 6) Missing=0 guard: non-existent files yield 0 edges and no FileNotFoundError
            missing_graph = reviewer.build_repo_dependency_graph(
                tmp_path,
                candidate_files=["does_not_exist_a.py", "does_not_exist_b.py"],
            )
            self.assertEqual(sum(len(v) for v in missing_graph.values()), 0)
            missing_plan = tmp_path / "missing_plan.md"
            missing_plan.write_text(
                "# Plan: Missing Files\n\n## Objective\nMissing=0.\n\n## Governance & Invariants\nGLOBAL_DEVELOPMENT_RULES\n\n"
                "## Parallel Execution Waves\n- Wave 1: Task 1, Task 2\n\n"
                "## Execution Tasks\n"
                "- [ ] Task 1: Create new_a\n  - **Files**: `new_a.py`\n  - RED/GREEN/QA/Evidence/Cleanup: POSIX\n"
                "- [ ] Task 2: Create new_b\n  - **Files**: `new_b.py`\n  - RED/GREEN/QA/Evidence/Cleanup: POSIX\n",
                encoding="utf-8",
            )
            verdict_m, findings_m, report_m = reviewer.audit_plan(missing_plan)
            self.assertEqual(verdict_m, "PLAN_APPROVED", report_m)
            self.assertFalse(any("NP_BENCH_TRANSITIVE_WAVE_RACE" in f["message"] for f in findings_m))

    def test_prepare_blind_review_packet_ast_and_zero_leak(self):
        """M4: RETRACE prepare-blind-review emits raw diff + AST funcs/sigs/branches with zero Notes/frozen matrix leak."""
        scripts_dir = str(self.repo_root / ".antigravity" / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import invoke_opus_reviewer as reviewer

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plan_file = tmp_path / "plan.md"
            plan_file.write_text(
                "# Plan\n\n"
                "<!-- <frozen-after-approval> -->\n"
                "Matrix expectation M99\n"
                "<!-- </frozen-after-approval> -->\n\n"
                "## Implementation Notes\n"
                "Secret rationale claim XYZ\n",
                encoding="utf-8",
            )
            src_file = tmp_path / "threshold.py"
            src_file.write_text(
                "def evaluate_threshold(value: int, limit: int = 10) -> bool:\n"
                "    if value < 0:\n"
                "        raise ValueError('negative')\n"
                "    if value <= limit:\n"
                "        return True\n"
                "    return False\n",
                encoding="utf-8",
            )
            diff_file = tmp_path / "changes.diff"
            diff_file.write_text(
                "diff --git a/.asw/plans/plan.md b/.asw/plans/plan.md\n"
                "--- a/.asw/plans/plan.md\n"
                "+++ b/.asw/plans/plan.md\n"
                "@@ -1,2 +1,4 @@\n"
                "+Secret rationale claim XYZ\n"
                "+Matrix expectation M99\n"
                "diff --git a/threshold.py b/threshold.py\n"
                "--- a/threshold.py\n"
                "+++ b/threshold.py\n"
                "@@ -1,6 +1,6 @@\n"
                " def evaluate_threshold(value: int, limit: int = 10) -> bool:\n"
                "+    if value < 0:\n"
                "+        raise ValueError('negative')\n"
                "     if value <= limit:\n"
                "         return True\n"
                "     return False\n",
                encoding="utf-8",
            )

            packet = reviewer.prepare_blind_review_packet(
                diff_content=diff_file.read_text(encoding="utf-8"),
                workdir=tmp_path,
                plan_path=plan_file,
            )
            self.assertEqual(packet["opt_tokens"], 0.0)
            serialized = json.dumps(packet) + "\n" + packet.get("packet_text", "")
            self.assertNotIn("Secret rationale claim XYZ", serialized)
            self.assertNotIn("Matrix expectation M99", serialized)
            self.assertNotIn(".asw/plans/plan.md", packet["raw_diff"])
            self.assertIn("evaluate_threshold", serialized)
            self.assertIn("value: int", serialized)
            self.assertIn("if value < 0", serialized)
            self.assertIn("raise ValueError", serialized)

            # CLI --mode prepare-blind-review
            out_file = tmp_path / "blind_packet.md"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "prepare-blind-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--workdir",
                    str(tmp_path),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out_text = out_file.read_text(encoding="utf-8")
            self.assertNotIn("Secret rationale claim XYZ", out_text)
            self.assertNotIn("Matrix expectation M99", out_text)
            self.assertIn("evaluate_threshold", out_text)
            self.assertIn("opt_tokens", out_text)

            # CLI --mode prepare-blind-review --json
            proc_json = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "prepare-blind-review",
                    "--plan",
                    str(plan_file),
                    "--diff",
                    str(diff_file),
                    "--workdir",
                    str(tmp_path),
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc_json.returncode, 0, proc_json.stderr)
            parsed_json = json.loads(proc_json.stdout)
            self.assertEqual(parsed_json["opt_tokens"], 0.0)
            self.assertNotIn("Secret rationale claim XYZ", proc_json.stdout)
            self.assertNotIn("Matrix expectation M99", proc_json.stdout)
            self.assertEqual(parsed_json["files"], ["threshold.py"])

    def test_prepare_blind_review_preserves_readme_and_agent_md_strips_only_asw(self):
        """Regression: prepare-blind-review preserves README.md & agent MDs even when they mention plan markers, stripping only .asw/."""
        scripts_dir = str(self.repo_root / ".antigravity" / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import invoke_opus_reviewer as reviewer

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            diff_text = (
                "diff --git a/.asw/plans/foo.md b/.asw/plans/foo.md\n"
                "--- a/.asw/plans/foo.md\n"
                "+++ b/.asw/plans/foo.md\n"
                "@@ -1,2 +1,4 @@\n"
                "+<!-- <frozen-after-approval> -->\n"
                "+## Implementation Notes\n"
                "+Secret plan note AAA\n"
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -1,2 +1,4 @@\n"
                "+Documenting `<frozen-after-approval>` and `## Implementation Notes`.\n"
                "diff --git a/plugins/antigravity-swarm/agents/asw-reviewer.md b/plugins/antigravity-swarm/agents/asw-reviewer.md\n"
                "--- a/plugins/antigravity-swarm/agents/asw-reviewer.md\n"
                "+++ b/plugins/antigravity-swarm/agents/asw-reviewer.md\n"
                "@@ -1,2 +1,4 @@\n"
                "+Stage 2 reads `<frozen-after-approval>` and `## Review Triage Log`.\n"
                "diff --git a/.antigravity/agents/asw-opposition-reviewer.md b/.antigravity/agents/asw-opposition-reviewer.md\n"
                "--- a/.antigravity/agents/asw-opposition-reviewer.md\n"
                "+++ b/.antigravity/agents/asw-opposition-reviewer.md\n"
                "@@ -1,2 +1,4 @@\n"
                "+Stage 2 verifies `## Implementation Notes`.\n"
            )
            packet = reviewer.prepare_blind_review_packet(diff_content=diff_text, workdir=tmp_path)
            self.assertEqual(packet["stripped_files"], [".asw/plans/foo.md"])
            self.assertNotIn(".asw/plans/foo.md", packet["raw_diff"])
            self.assertNotIn("Secret plan note AAA", packet["raw_diff"])
            self.assertEqual(
                packet["files"],
                [
                    "README.md",
                    "plugins/antigravity-swarm/agents/asw-reviewer.md",
                    ".antigravity/agents/asw-opposition-reviewer.md",
                ],
            )
            self.assertIn("README.md", packet["raw_diff"])
            self.assertIn("plugins/antigravity-swarm/agents/asw-reviewer.md", packet["raw_diff"])
            self.assertIn(".antigravity/agents/asw-opposition-reviewer.md", packet["raw_diff"])

    def test_diff_review_verify_mutations_weak_vs_strong_and_compat(self):
        """M6: --verify-mutations rejects weak tests (<0.75) with STING_MUTATION_GATE_FAILED + file:line, passes strong (>=0.75)."""
        scripts_dir = str(self.repo_root / ".antigravity" / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import invoke_opus_reviewer as reviewer

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_repo = Path(tmp_dir)
            (tmp_repo / "rate_limit.py").write_text(
                "def is_within_limit(count: int, max_allowed: int) -> bool:\n"
                "    if count < 0:\n"
                "        return False\n"
                "    if count <= max_allowed:\n"
                "        return True\n"
                "    return False\n",
                encoding="utf-8",
            )
            (tmp_repo / "tests").mkdir()
            test_file = tmp_repo / "tests" / "test_rate_limit.py"
            # Weak test: has def test_negative_... and ==, so passes legacy Tripwire 3A, but kills < 0.75 mutants
            test_file.write_text(
                "from rate_limit import is_within_limit\n\n"
                "def test_within_limit_happy():\n"
                "    assert is_within_limit(5, 10) == True\n\n"
                "def test_negative_over_limit():\n"
                "    assert is_within_limit(50, 10) == False\n",
                encoding="utf-8",
            )
            plan_file = tmp_repo / "plan.md"
            plan_file.write_text(
                "# Plan\n## Execution Tasks\n- [x] Task 1: rate_limit\n  - Files: `rate_limit.py`, `tests/test_rate_limit.py`\n",
                encoding="utf-8",
            )
            ev_dir = tmp_repo / "evidence"
            ev_dir.mkdir()
            (ev_dir / "run.txt").write_text("RED phase fail -> GREEN passed negative edge\n", encoding="utf-8")
            diff_file = tmp_repo / "patch.diff"
            diff_file.write_text(
                "diff --git a/rate_limit.py b/rate_limit.py\n"
                "--- a/rate_limit.py\n"
                "+++ b/rate_limit.py\n"
                "@@ -1,6 +1,6 @@\n"
                "+def is_within_limit(count: int, max_allowed: int) -> bool:\n"
                "+    if count < 0:\n"
                "+        return False\n"
                "+    if count <= max_allowed:\n"
                "+        return True\n"
                "+    return False\n"
                "diff --git a/tests/test_rate_limit.py b/tests/test_rate_limit.py\n"
                "--- a/tests/test_rate_limit.py\n"
                "+++ b/tests/test_rate_limit.py\n"
                "@@ -1,6 +1,6 @@\n"
                "+def test_within_limit_happy():\n"
                "+    assert is_within_limit(5, 10) == True\n"
                "+def test_negative_over_limit():\n"
                "+    assert is_within_limit(50, 10) == False\n",
                encoding="utf-8",
            )

            # Default verify_mutations=False preserves backward compatibility -> ASW APPROVED
            v_compat, _, r_compat = reviewer.audit_diff(
                plan_path=plan_file,
                diff_path=diff_file,
                evidence_dir=ev_dir,
                workdir=tmp_repo,
            )
            self.assertEqual(v_compat, "ASW APPROVED", r_compat)

            # Weak suite + verify_mutations=True -> ASW REJECTED with STING_MUTATION_GATE_FAILED & file:line
            v_weak, f_weak, r_weak = reviewer.audit_diff(
                plan_path=plan_file,
                diff_path=diff_file,
                evidence_dir=ev_dir,
                workdir=tmp_repo,
                verify_mutations=True,
            )
            self.assertEqual(v_weak, "ASW REJECTED", r_weak)
            self.assertTrue(
                any(
                    "STING_MUTATION_GATE_FAILED" in f["message"] and "rate_limit.py:" in f["message"]
                    for f in f_weak
                ),
                f"Expected STING_MUTATION_GATE_FAILED with file:line in {f_weak}",
            )

            # Strong test suite (>= 0.75) -> CLI --mode diff-review --verify-mutations returns ASW APPROVED
            test_file.write_text(
                "from rate_limit import is_within_limit\n\n"
                "def test_within_limit_boundary():\n"
                "    assert is_within_limit(0, 10) is True\n"
                "    assert is_within_limit(10, 10) is True\n"
                "    assert is_within_limit(11, 10) is False\n\n"
                "def test_negative_count_rejected():\n"
                "    assert is_within_limit(-1, 10) is False\n"
                "    assert is_within_limit(50, 10) is False\n",
                encoding="utf-8",
            )
            out_strong = tmp_repo / "review_strong.md"
            proc_strong = subprocess.run(
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
                    "--workdir",
                    str(tmp_repo),
                    "--verify-mutations",
                    "--output",
                    str(out_strong),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc_strong.returncode, 0, proc_strong.stdout + proc_strong.stderr)
            self.assertIn("Verdict: ASW APPROVED", out_strong.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
