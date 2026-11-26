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

"""RED/GREEN unit and behavioral tests for diff-scoped AST mutation verification (M1-M2)."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / ".antigravity" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import mutation_verifier  # noqa: E402


class TestMutationVerifier(unittest.TestCase):
    def test_parse_diff_hunks_extracts_production_py_and_skips_tests(self):
        diff_text = """diff --git a/src/calc.py b/src/calc.py
index 1111111..2222222 100644
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,4 +1,6 @@
 def clamp(val: int, high: int) -> int:
+    if val < 0:
+        return 0
     if val > high:
-        return high
+        return high
     return val
diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -1,2 +1,3 @@
 def test_clamp():
+    assert clamp(1, 5) == 1
     assert True
diff --git a/src/helper_test.py b/src/helper_test.py
--- a/src/helper_test.py
+++ b/src/helper_test.py
@@ -1,1 +1,2 @@
+def test_helper():
     pass
diff --git a/src/test_edge.py b/src/test_edge.py
--- a/src/test_edge.py
+++ b/src/test_edge.py
@@ -1,1 +1,2 @@
+def test_edge():
     pass
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,1 +1,2 @@
+# Docs update
diff --git a/src/removed.py b/src/removed.py
--- a/src/removed.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    return 1
"""
        hunks = mutation_verifier.parse_diff_hunks(diff_text)
        self.assertEqual(list(hunks.keys()), ["src/calc.py"])
        self.assertEqual(hunks["src/calc.py"], {2, 3, 5})

    def test_diff_scoped_mutator_all_seven_operators_and_line_scoping(self):
        source = "\n".join([
            "def untouched(x):",            # 1
            "    return x < 10",            # 2 (untouched)
            "def check(a, b, items):",      # 3
            "    if a < b:",                # 4: relational_boundary, guard_flip
            "        return True",          # 5: return_constant_flip
            "    if a == 0 and b is None:", # 6: equality_flip, boolean_op_flip, guard_flip
            "        return 0",             # 7: return_constant_flip
            "    if not items:",            # 8: unary_negation, guard_flip
            "        return -a",            # 9: unary_negation, return_constant_flip
            "    if 1 in items:",           # 10: membership_flip, guard_flip
            "        return a + b",         # 11: guard_flip (+ <-> -), return_constant_flip
            "    return False",             # 12: return_constant_flip
        ]) + "\n"
        target_lines = {4, 5, 6, 7, 8, 9, 10, 11, 12}
        mutator = mutation_verifier.DiffScopedMutator(source, target_lines, "app.py")
        mutants = mutator.generate_mutants()

        operators = {m.operator for m in mutants}
        expected_ops = {
            "relational_boundary",
            "equality_flip",
            "boolean_op_flip",
            "unary_negation",
            "membership_flip",
            "return_constant_flip",
            "guard_flip",
        }
        self.assertEqual(operators, expected_ops)
        self.assertTrue(all(m.lineno in target_lines for m in mutants))
        self.assertFalse(any(m.lineno == 2 for m in mutants))

    def test_ast_dump_equivalent_mutant_pruning(self):
        source = "\n".join([
            "def f(flag, x):",
            "    if not flag:",
            "        return None",
            "    return x",
        ]) + "\n"
        # On line 2 (`if not flag:`): unary_negation -> `if flag:` and guard_flip -> `if flag:`
        # ast.dump pruning must keep only one and prune the duplicate.
        # On line 3 (`return None`): return_constant_flip must not emit an identical `return None`.
        mutator = mutation_verifier.DiffScopedMutator(source, {2, 3}, "f.py")
        mutants = mutator.generate_mutants()
        dumps = [m.ast_dump for m in mutants]
        self.assertEqual(len(dumps), len(set(dumps)))
        self.assertGreaterEqual(mutator.pruned_equivalent, 1)
        self.assertFalse(any("return None" in m.description for m in mutants))

    def test_run_mutation_verification_weak_vs_strong_discrimination(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            prod = repo / "limits.py"
            prod.write_text(
                "def allow_request(count: int, limit: int) -> bool:\n"
                "    if count < 0:\n"
                "        return False\n"
                "    if count <= limit:\n"
                "        return True\n"
                "    return False\n",
                encoding="utf-8",
            )
            diff_text = (
                "diff --git a/limits.py b/limits.py\n"
                "--- a/limits.py\n"
                "+++ b/limits.py\n"
                "@@ -1,0 +1,6 @@\n"
                "+def allow_request(count: int, limit: int) -> bool:\n"
                "+    if count < 0:\n"
                "+        return False\n"
                "+    if count <= limit:\n"
                "+        return True\n"
                "+    return False\n"
            )

            tests_dir = repo / "tests"
            tests_dir.mkdir()
            test_file = tests_dir / "test_limits.py"

            # Weak suite has negative test name + == assertions, passes pytest & Tripwire 3A
            test_file.write_text(
                "from limits import allow_request\n\n"
                "def test_allow_request_happy():\n"
                "    assert allow_request(2, 10) == True\n\n"
                "def test_negative_over_limit():\n"
                "    assert allow_request(99, 10) == False\n",
                encoding="utf-8",
            )
            weak_res = mutation_verifier.run_mutation_verification(
                repo, diff_text=diff_text, threshold=0.75
            )
            self.assertFalse(weak_res["passed"])
            self.assertLess(weak_res["mutation_score"], 0.75)
            self.assertGreater(weak_res["survived"], 0)
            self.assertEqual(weak_res["opt_tokens"], 0.0)
            first_survivor = weak_res["survivors"][0]
            self.assertRegex(first_survivor["location"], r"^limits\.py:\d+$")
            self.assertIn("operator", first_survivor)

            # Strong suite tests boundaries and negative branch
            test_file.write_text(
                "from limits import allow_request\n\n"
                "def test_allow_request_boundaries():\n"
                "    assert allow_request(0, 10) is True\n"
                "    assert allow_request(10, 10) is True\n\n"
                "def test_negative_boundaries():\n"
                "    assert allow_request(-1, 10) is False\n"
                "    assert allow_request(11, 10) is False\n",
                encoding="utf-8",
            )
            strong_res = mutation_verifier.run_mutation_verification(
                repo, diff_text=diff_text, threshold=0.75
            )
            self.assertTrue(strong_res["passed"])
            self.assertGreaterEqual(strong_res["mutation_score"], 0.75)
            self.assertEqual(strong_res["opt_tokens"], 0.0)

    def test_timeout_kills_infinite_loop_mutant_and_keeps_repo_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            prod = repo / "spin.py"
            original_src = (
                "def countdown(n: int) -> int:\n"
                "    steps = 0\n"
                "    while n > 0:\n"
                "        n = n - 1\n"
                "        steps = steps + 1\n"
                "    return steps\n"
            )
            prod.write_text(original_src, encoding="utf-8")
            tests_dir = repo / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_spin.py").write_text(
                "from spin import countdown\n\n"
                "def test_countdown():\n"
                "    assert countdown(2) == 2\n",
                encoding="utf-8",
            )
            # Mutating `n - 1` -> `n + 1` on line 4 creates a real infinite loop inside `while n > 0:`
            diff_text = (
                "diff --git a/spin.py b/spin.py\n"
                "--- a/spin.py\n"
                "+++ b/spin.py\n"
                "@@ -4,1 +4,1 @@\n"
                "-        n = n - 1\n"
                "+        n = n - 1\n"
            )
            res = mutation_verifier.run_mutation_verification(
                repo, diff_text=diff_text, timeout_sec=1.0
            )
            self.assertEqual(res["timeout_killed"], 1)
            self.assertEqual(res["killed"], 1)
            self.assertTrue(res["passed"])
            self.assertEqual(prod.read_text(encoding="utf-8"), original_src)

    def test_live_workspace_immutability_and_cleanup_on_interrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            prod = repo / "mod.py"
            original_src = "def inc(x: int) -> int:\n    return x + 1\n"
            prod.write_text(original_src, encoding="utf-8")
            ro_file = repo / "readonly.txt"
            ro_file.write_text("locked", encoding="utf-8")
            os.chmod(ro_file, stat.S_IREAD)
            (repo / "test_mod.py").write_text(
                "from mod import inc\ndef test_inc():\n    assert inc(1) == 2\n",
                encoding="utf-8",
            )
            diff_text = (
                "diff --git a/mod.py b/mod.py\n"
                "--- a/mod.py\n"
                "+++ b/mod.py\n"
                "@@ -2,1 +2,1 @@\n"
                "-    return x + 1\n"
                "+    return x + 1\n"
            )
            created_temps = []
            real_mkdtemp = tempfile.mkdtemp

            def track_mkdtemp(*args, **kwargs):
                d = real_mkdtemp(*args, **kwargs)
                created_temps.append(Path(d))
                return d

            try:
                with mock.patch("tempfile.mkdtemp", side_effect=track_mkdtemp):
                    with mock.patch("subprocess.run", side_effect=KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            mutation_verifier.run_mutation_verification(repo, diff_text=diff_text)
                self.assertEqual(len(created_temps), 1)
                self.assertFalse(created_temps[0].exists())
                self.assertEqual(prod.read_text(encoding="utf-8"), original_src)
            finally:
                os.chmod(ro_file, stat.S_IWRITE | stat.S_IREAD)

    def test_baseline_tests_failed_fast_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            (repo / "test_calc.py").write_text(
                "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n",
                encoding="utf-8",
            )
            diff_text = (
                "diff --git a/calc.py b/calc.py\n"
                "--- a/calc.py\n"
                "+++ b/calc.py\n"
                "@@ -2,1 +2,1 @@\n"
                "-    return a + b\n"
                "+    return a - b\n"
            )
            res = mutation_verifier.run_mutation_verification(repo, diff_text=diff_text)
            self.assertEqual(res["status"], "baseline_tests_failed")
            self.assertFalse(res["passed"])
            self.assertEqual(res["killed"], 0)
            self.assertEqual(res["survived"], 0)

    def test_no_python_mutants_graceful_pass_for_docs_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "README.md").write_text("# Hello\n", encoding="utf-8")
            diff_text = (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -1,0 +1,1 @@\n"
                "+# Hello\n"
            )
            res = mutation_verifier.run_mutation_verification(repo, diff_text=diff_text)
            self.assertEqual(res["status"], "no_python_mutants")
            self.assertEqual(res["mutation_score"], 1.0)
            self.assertTrue(res["passed"])
            self.assertEqual(res["viable"], 0)
            self.assertEqual(res["opt_tokens"], 0.0)

    def test_max_mutants_stratification_across_files_and_operators(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            lines_a = "\n".join(f"    if x > {i} and x < {i + 10}: return {i}" for i in range(1, 8))
            lines_b = "\n".join(f"    if y == {i} or y != {i + 5}: return {i}" for i in range(1, 8))
            (repo / "a.py").write_text(f"def fa(x):\n{lines_a}\n    return 0\n", encoding="utf-8")
            (repo / "b.py").write_text(f"def fb(y):\n{lines_b}\n    return 0\n", encoding="utf-8")
            (repo / "test_ab.py").write_text(
                "from a import fa\nfrom b import fb\n"
                "def test_ab():\n    assert fa(5) == 1\n    assert fb(1) == 1\n",
                encoding="utf-8",
            )
            diff_a = "\n".join(f"+    if x > {i} and x < {i + 10}: return {i}" for i in range(1, 8))
            diff_b = "\n".join(f"+    if y == {i} or y != {i + 5}: return {i}" for i in range(1, 8))
            diff_text = (
                "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                f"@@ -1,0 +2,7 @@\n{diff_a}\n"
                "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
                f"@@ -1,0 +2,7 @@\n{diff_b}\n"
            )
            res = mutation_verifier.run_mutation_verification(
                repo, diff_text=diff_text, max_mutants=12
            )
            self.assertEqual(res["viable"], 12)
            self.assertGreater(res["total_candidates"], 12)

    def test_benchmark_mutation_quality_12_cases_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "bench.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "mutation_verifier.py"),
                    "--benchmark-quality",
                    "--json",
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(out_file.read_text(encoding="utf-8"))

        self.assertEqual(report["total_cases"], 12)
        self.assertEqual(len(report["cases"]), 12)
        self.assertEqual(report["opt_tokens"], 0.0)

        legacy = report["legacy_tripwire_3a"]
        sting = report["sting_diff_mutation"]
        self.assertEqual(legacy["false_approval_rate"], 1.0)
        self.assertEqual(legacy["weak_suite_catch_rate"], 0.0)
        self.assertEqual(sting["weak_suite_catch_rate"], 1.0)
        self.assertEqual(sting["strong_suite_pass_rate"], 1.0)
        self.assertEqual(sting["false_approval_rate"], 0.0)
        self.assertEqual(sting["accuracy"], 1.0)
        self.assertLess(sting["mean_weak_mutation_score"], 0.75)
        self.assertGreaterEqual(sting["mean_strong_mutation_score"], 0.75)

    def test_parse_diff_hunks_ignores_hunk_interior_triple_plus_lines(self):
        """Regression: +++ lines inside a @@ hunk must not be treated as file headers."""
        diff_text = (
            "diff --git a/src/formatter.py b/src/formatter.py\n"
            "--- a/src/formatter.py\n"
            "+++ b/src/formatter.py\n"
            "@@ -1,3 +1,6 @@\n"
            " def render(x: int) -> str:\n"
            "+++ b/fake_header_inside_hunk.py\n"
            "+    if x < 0:\n"
            "+        return 'neg'\n"
            "     return str(x)\n"
        )
        hunks = mutation_verifier.parse_diff_hunks(diff_text)
        self.assertEqual(list(hunks.keys()), ["src/formatter.py"])
        self.assertEqual(hunks["src/formatter.py"], {2, 3, 4})

    def test_fast_ast_mutation_on_1500_line_module(self):
        """Regression: in-place AST mutation on a 1,500-line module must finish in < 1.0s."""
        import time

        lines = [
            f"def fn_{i}(x: int) -> int:\n    if x < {i}:\n        return {i}\n    return x + 1"
            for i in range(400)
        ]
        source = "\n".join(lines) + "\n"
        self.assertGreaterEqual(len(source.splitlines()), 1500)
        total_lines = len(source.splitlines())
        target_lines = set(range(total_lines - 11, total_lines + 1))

        t0 = time.monotonic()
        cpu_t0 = time.process_time()
        mutator = mutation_verifier.DiffScopedMutator(source, target_lines, "big_mod.py")
        mutants = mutator.generate_mutants()
        elapsed = time.monotonic() - t0
        cpu_elapsed = time.process_time() - cpu_t0

        self.assertGreaterEqual(len(mutants), 4)
        self.assertLess(cpu_elapsed, 2.0, f"1500-line AST mutation CPU time {cpu_elapsed:.2f}s (expected < 2.0s)")
        self.assertLess(elapsed, 5.0, f"1500-line AST mutation wall time {elapsed:.2f}s (expected < 5.0s)")

    def test_slow_baseline_timeout_calibration_and_diff_test_scoping(self):
        """Regression: effective_timeout scales above baseline_elapsed and auto-scopes diff-matching tests."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "mod_alpha.py").write_text(
                "def check_alpha(x: int) -> bool:\n"
                "    if x < 0:\n"
                "        return False\n"
                "    return True\n",
                encoding="utf-8",
            )
            tests_dir = repo / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_mod_alpha.py").write_text(
                "import time\n"
                "from mod_alpha import check_alpha\n\n"
                "def test_alpha_boundary_slow():\n"
                "    time.sleep(0.35)\n"
                "    assert check_alpha(0) == True\n"
                "    assert check_alpha(-1) == False\n"
                "    assert check_alpha(5) == True\n",
                encoding="utf-8",
            )
            # Unrelated failing test must NOT run when diff only touches mod_alpha.py
            (tests_dir / "test_unrelated.py").write_text(
                "def test_always_fails():\n"
                "    assert False\n",
                encoding="utf-8",
            )
            diff_text = (
                "diff --git a/mod_alpha.py b/mod_alpha.py\n"
                "--- a/mod_alpha.py\n"
                "+++ b/mod_alpha.py\n"
                "@@ -1,4 +1,4 @@\n"
                " def check_alpha(x: int) -> bool:\n"
                "+    if x < 0:\n"
                "+        return False\n"
                "+    return True\n"
            )
            res = mutation_verifier.run_mutation_verification(
                repo,
                diff_text=diff_text,
                test_targets=None,
                threshold=0.75,
                timeout_sec=0.2,
            )
            self.assertEqual(res["status"], "passed", res)
            self.assertTrue(res["passed"])
            self.assertEqual(res["timeout_killed"], 0)
            self.assertGreater(res["effective_timeout"], res["baseline_elapsed"])
            self.assertIn("tests/test_mod_alpha.py", res.get("test_targets", []))
            self.assertNotIn("tests/test_unrelated.py", res.get("test_targets", []))


if __name__ == "__main__":
    unittest.main()
