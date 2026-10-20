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

"""Cross-platform Windows & Python 3.14 tests for harness2.core."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

if os.environ.get("HARNESS2_TEST_UPSTREAM") == "1":
    upstream_path = str(REPO_ROOT / ".agent-workspace" / "scratch" / "harness2_upstream")
    if upstream_path not in sys.path:
        sys.path.insert(0, upstream_path)
else:
    antigravity_path = str(REPO_ROOT / ".antigravity")
    if antigravity_path not in sys.path:
        sys.path.insert(0, antigravity_path)

from harness2.core import runmark, schedule, tree
from harness2.substrate.codex import CODEX_SURFACE


class TestHarness2Windows(unittest.TestCase):
    def test_tree_windows_paths_and_validate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Create files
            agents_md = root / "AGENTS.md"
            agents_md.write_text(
                "- When foo description, read .agents/skills/foo/SKILL.md and follow it.\n",
                encoding="utf-8",
            )

            skill_dir = root / ".agents" / "skills" / "foo"
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(
                "---\nname: foo\ndescription: foo description\n---\n# Foo Skill\n",
                encoding="utf-8",
            )

            scripts_dir = root / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            helper_file = scripts_dir / "helper.py"
            helper_file.write_text("print('helper')\n", encoding="utf-8")

            # Read tree
            res = tree.read_tree(CODEX_SURFACE, root)

            # Verify POSIX keys on Windows
            for k in res.keys():
                self.assertNotIn("\\", k, f"Path key contains backslash on Windows: {k}")

            self.assertIn(".agents/skills/foo/SKILL.md", res)
            self.assertIn("scripts/helper.py", res)
            self.assertIn("AGENTS.md", res)

            # Validate tree
            census = tree.validate(CODEX_SURFACE, res)
            self.assertEqual(census.get("skills"), 1)
            self.assertEqual(census.get("scripts"), 1)

            # Write tree and re-read
            out_dir = root / "output"
            tree.write_tree(CODEX_SURFACE, res, out_dir, stubs=False)
            re_read = tree.read_tree(CODEX_SURFACE, out_dir)
            for k in re_read.keys():
                self.assertNotIn("\\", k, f"Path key in re-read tree contains backslash: {k}")
            self.assertEqual(set(res.keys()), set(re_read.keys()))

    def test_tree_symlink_and_junction_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            root.mkdir()
            (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

            outside = Path(td) / "outside"
            outside.mkdir()
            (outside / "external.txt").write_text("external content\n", encoding="utf-8")

            # Create a real directory junction if on Windows
            junc_path = root / "junc_dir"
            junc_created = False
            try:
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junc_path), str(outside)],
                    capture_output=True,
                    text=True,
                )
                if junc_path.exists():
                    junc_created = True
            except Exception:
                pass

            if junc_created:
                try:
                    rejected = []
                    res = tree.read_tree(CODEX_SURFACE, root, rejected=rejected)
                    self.assertNotIn("junc_dir/external.txt", res)
                    self.assertNotIn("junc_dir\\external.txt", res)
                    rejected_paths = [r[0] if isinstance(r, tuple) else r for r in rejected]
                    rejected_reasons = [r[1] if isinstance(r, tuple) else "" for r in rejected]
                    self.assertTrue(
                        any("junc_dir" in p for p in rejected_paths),
                        f"Expected junc_dir in rejected paths, got: {rejected}",
                    )
                    self.assertTrue(
                        any("symlink or junction rejected" in reason for reason in rejected_reasons),
                        f"Expected 'symlink or junction rejected' in rejected reasons, got: {rejected}",
                    )
                finally:
                    subprocess.run(["cmd", "/c", "rmdir", str(junc_path)], capture_output=True)

            # Mocked symlink test to test file-level symlink and mock path
            mock_target = root / "scripts" / "mocked_symlink.py"
            mock_target.parent.mkdir(parents=True, exist_ok=True)
            mock_target.write_text("print('sym')\n", encoding="utf-8")

            orig_is_symlink = Path.is_symlink

            def mock_is_symlink(self):
                if self.name == "mocked_symlink.py":
                    return True
                return orig_is_symlink(self)

            with mock.patch.object(Path, "is_symlink", mock_is_symlink):
                rejected = []
                res = tree.read_tree(CODEX_SURFACE, root, rejected=rejected)
                self.assertNotIn("scripts/mocked_symlink.py", res)
                self.assertIn(("scripts/mocked_symlink.py", "symlink or junction rejected"), rejected)

    def test_runmark_fingerprint_and_mark_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "harness"
            subdir = root / "sub"
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / "file1.txt").write_bytes(b"content 1\n")
            (root / "file2.txt").write_bytes(b"content 2\n")

            # Canonical digest computed with POSIX forward slashes
            h = hashlib.sha1()
            for rel, content in [("file2.txt", b"content 2\n"), ("sub/file1.txt", b"content 1\n")]:
                h.update(rel.encode())
                h.update(b"\0")
                h.update(content)
                h.update(b"\0")
            expected_fp = h.hexdigest()[:16]

            actual_fp = runmark.fingerprint(root)
            self.assertEqual(
                actual_fp,
                expected_fp,
                f"Fingerprint mismatch due to path separators: got {actual_fp}, expected {expected_fp}",
            )

            # Test mark / verify aliases and functions
            run_dest = Path(td) / "run_out"
            self.assertTrue(hasattr(runmark, "mark"), "runmark module should have 'mark' alias")
            self.assertTrue(hasattr(runmark, "verify"), "runmark module should have 'verify' alias")

            marker = runmark.mark(run_dest, run_id="run-001", harness_dir=root)
            self.assertTrue(marker.is_file())
            self.assertTrue(runmark.verify(run_dest, harness_dir=root))

            other_dir = Path(td) / "other"
            other_dir.mkdir()
            self.assertFalse(runmark.verify(run_dest, harness_dir=other_dir))

    def test_schedule_write_summary_windows_concurrency(self):
        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "summary.json"

            r0 = schedule.TaskResult(
                task_id="task-0",
                domain="accounting",
                k=2,
                status="ok",
                modes={"seq": {"ok": True}},
                selections={"seq": {"ok": True, "chosen_label": "l0"}},
            )
            # Must not raise ModuleNotFoundError: No module named 'fcntl' on Windows
            schedule._write_summary(summary_path, r0)
            self.assertTrue(summary_path.is_file())

            data = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(data["task_id"], "task-0")
            self.assertIn("seq", data["modes"])

            errors = []

            def worker(i):
                try:
                    res = schedule.TaskResult(
                        task_id=f"task-{i}",
                        domain="accounting",
                        k=2,
                        status="ok",
                        modes={f"mode-{i}": {"ok": True}},
                        selections={f"mode-{i}": {"ok": True, "chosen_label": f"label-{i}"}},
                    )
                    schedule._write_summary(summary_path, res)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 11)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [], f"Errors occurred during concurrent _write_summary: {errors}")

            final_data = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertIn("modes", final_data)
            self.assertGreaterEqual(len(final_data["modes"]), 5)


if __name__ == "__main__":
    unittest.main()
