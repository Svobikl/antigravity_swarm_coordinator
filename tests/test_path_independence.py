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

"""Test repository files for zero hardcoded user-home paths or usernames."""

import re
import unittest
from pathlib import Path


class TestPathIndependence(unittest.TestCase):
    def test_no_hardcoded_user_paths(self):
        repo_root = Path(__file__).resolve().parent.parent

        # Construct patterns dynamically to prevent literal matches within this test itself
        user_dir_pattern = re.compile(r"[A-Za-z]:" + r"[\\/]+Users[\\/]+", re.IGNORECASE)
        username = Path.home().name
        username_pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(username)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )

        targets = ["GEMINI.md", ".antigravity", "skills", ".asw/plans"]
        violations = []

        for target in targets:
            target_path = repo_root / target
            if not target_path.exists():
                continue
            files = (
                [target_path]
                if target_path.is_file()
                else [f for f in target_path.rglob("*") if f.is_file()]
            )
            for f in files:
                if "__pycache__" in f.parts or f.suffix in (".pyc", ".git"):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for line_no, line in enumerate(content.splitlines(), 1):
                    if user_dir_pattern.search(line):
                        rel = f.relative_to(repo_root).as_posix()
                        violations.append(
                            f"{rel}:{line_no} matches user directory: {line.strip()[:100]}"
                        )
                    elif username_pattern.search(line):
                        rel = f.relative_to(repo_root).as_posix()
                        violations.append(
                            f"{rel}:{line_no} matches username: {line.strip()[:100]}"
                        )

        self.assertEqual(
            violations,
            [],
            "Found forbidden hardcoded user paths or username:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
