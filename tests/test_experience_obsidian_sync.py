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

"""Tests for Harness2 Continual Experience Sync and asw-harness-adapt skill."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root and .antigravity are in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
ANTIGRAVITY_DIR = REPO_ROOT / ".antigravity"
SCRIPTS_DIR = ANTIGRAVITY_DIR / "scripts"
for d in (REPO_ROOT, ANTIGRAVITY_DIR, SCRIPTS_DIR):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))


class TestSyncHarnessExperience(unittest.TestCase):
    """Test path-independent Obsidian Vault experience synchronization."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name).resolve()
        self.vault_dir = self.temp_path / "AgentMemory"
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.lib_root = self.temp_path / "library"
        self.lib_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_obsidian_vault_path_independence(self):
        """Test vault resolution honors overrides and defaults without hardcoded paths."""
        try:
            import sync_harness_experience
        except ImportError:
            self.fail("sync_harness_experience.py must exist in .antigravity/scripts")

        # 1. Explicit vault argument
        resolved = sync_harness_experience.resolve_obsidian_vault(self.vault_dir)
        self.assertEqual(resolved, self.vault_dir)

        # 2. Environment variable override
        old_env = os.environ.get("OBSIDIAN_VAULT_PATH")
        try:
            os.environ["OBSIDIAN_VAULT_PATH"] = str(self.vault_dir)
            resolved_env = sync_harness_experience.resolve_obsidian_vault()
            self.assertEqual(resolved_env, self.vault_dir)
        finally:
            if old_env is not None:
                os.environ["OBSIDIAN_VAULT_PATH"] = old_env
            else:
                os.environ.pop("OBSIDIAN_VAULT_PATH", None)

        # 3. Default fallback
        resolved_default = sync_harness_experience.resolve_obsidian_vault()
        expected_default = (Path.home() / "Documents" / "AgentMemory").expanduser().resolve()
        self.assertEqual(resolved_default, expected_default)

    def test_sync_verified_experience_to_obsidian(self):
        """Syncs verified EXPERIENCE.md into <vault>/projects/<project>/experiences/<domain>.md."""
        try:
            import sync_harness_experience
            from harness2.core import library
        except ImportError:
            self.fail("Required modules sync_harness_experience and harness2 must be importable")

        # Construct a valid library entry: <library>/<mode>/<domain>/harnesses/<task_id>/EXPERIENCE.md
        task_dir = self.lib_root / "agg" / "accounting" / "harnesses" / "ledger-1"
        task_dir.mkdir(parents=True, exist_ok=True)
        valid_exp = (
            "# ledger-1\n\n"
            "- adopted: `agg1` (run `run-1`)\n"
            "- components: scripts: 1\n\n"
            "## Why this was chosen\n"
            "The signed total matches the source ledger.\n\n"
            "## What each edit did\n"
            "component: scripts/summarize.py\n"
            "change: dropped positive-only filter\n"
            "verdict: helped\n\n"
            "## Transferable lesson\n"
            "- **cue**: When a ledger includes credits and debits\n"
            "- **lesson**: Include both signs when summing in scripts/summarize.py.\n"
            "- **evidence**: The scripts/summarize.py row -- removing positive-only filter.\n"
            "- **confidence**: high for this observed arithmetic contrast\n"
        )
        (task_dir / "EXPERIENCE.md").write_text(valid_exp, encoding="utf-8")

        # Verify has_experience detects valid text
        self.assertTrue(library.has_experience(valid_exp))
        self.assertTrue(sync_harness_experience.has_experience(valid_exp))

        # Perform sync
        project_name = "test-project"
        synced_notes = sync_harness_experience.sync_library_to_obsidian(
            self.lib_root, project=project_name, vault_dir=self.vault_dir
        )
        self.assertTrue(len(synced_notes) > 0)

        target_note = self.vault_dir / "projects" / project_name / "experiences" / "accounting.md"
        self.assertTrue(target_note.is_file(), f"Expected note {target_note} was not created")

        content = target_note.read_text(encoding="utf-8")
        self.assertIn("type: harness-experience", content)
        self.assertIn(f"project: {project_name}", content)
        self.assertIn("domain: accounting", content)
        self.assertIn("### ledger-1", content)
        self.assertIn("When a ledger includes credits and debits", content)
        self.assertIn("Include both signs when summing", content)

    def test_negative_rejects_unverified_or_empty_experience(self):
        """Negative Test 1: Rejects/skips unverified or empty EXPERIENCE.md (missing cue/lesson)."""
        try:
            import sync_harness_experience
            from harness2.core import library
        except ImportError:
            self.fail("sync_harness_experience and harness2 must be importable")

        # 1. Completely empty text
        empty_text = ""
        self.assertFalse(library.has_experience(empty_text))
        self.assertFalse(sync_harness_experience.has_experience(empty_text))

        # 2. Missing cue
        no_cue = (
            "# task-x\n\n"
            "## Transferable lesson\n"
            "- **lesson**: Do something useful.\n"
            "- **evidence**: Some evidence.\n"
        )
        self.assertFalse(library.has_experience(no_cue))
        self.assertFalse(sync_harness_experience.has_experience(no_cue))

        # 3. Missing lesson
        no_lesson = (
            "# task-x\n\n"
            "## Transferable lesson\n"
            "- **cue**: When something happens.\n"
            "- **evidence**: Some evidence.\n"
        )
        self.assertFalse(library.has_experience(no_lesson))
        self.assertFalse(sync_harness_experience.has_experience(no_lesson))

        # 4. In a library directory, unverified file is skipped during sync
        unverified_dir = self.lib_root / "seq" / "accounting" / "harnesses" / "unverified-task"
        unverified_dir.mkdir(parents=True, exist_ok=True)
        (unverified_dir / "EXPERIENCE.md").write_text(no_cue, encoding="utf-8")

        synced = sync_harness_experience.sync_library_to_obsidian(
            self.lib_root, project="test-project", vault_dir=self.vault_dir
        )
        target_note = self.vault_dir / "projects" / "test-project" / "experiences" / "accounting.md"
        if target_note.exists():
            content = target_note.read_text(encoding="utf-8")
            self.assertNotIn("unverified-task", content)

    def test_negative_rejects_grader_verdict_leaks(self):
        """Negative Test 2: Rejects EXPERIENCE.md files that leak grader verdicts."""
        try:
            import sync_harness_experience
            from harness2.core import context
        except ImportError:
            self.fail("sync_harness_experience and harness2 must be importable")

        leaked_samples = [
            "Verdict: PASS - test score: 100",
            "Verdict: FAIL - all assertions passed",
            "Score: 100 on unit tests",
            "- **lesson**: Keep the score at test_pass_rate 1.0",
            "- **cue**: When deterministic_eval_summary is present",
        ]

        for sample in leaked_samples:
            # Both direct helper and context.assert_no_grader_verdicts must reject leaks
            with self.assertRaises(ValueError, msg=f"Should reject: {sample}"):
                sync_harness_experience.assert_no_grader_verdicts(sample)

            with self.assertRaises(ValueError, msg=f"context tripwire should reject: {sample}"):
                context.assert_no_grader_verdicts(sample)

        # In library file sync, leaking file must raise ValueError
        leaked_dir = self.lib_root / "agg" / "accounting" / "harnesses" / "leaked-task"
        leaked_dir.mkdir(parents=True, exist_ok=True)
        leaked_content = (
            "# leaked-task\n\n"
            "Verdict: PASS\n"
            "## Transferable lesson\n"
            "- **cue**: When running tests\n"
            "- **lesson**: Check Verdict: PASS\n"
            "- **evidence**: Score: 100\n"
        )
        (leaked_dir / "EXPERIENCE.md").write_text(leaked_content, encoding="utf-8")

        with self.assertRaises(ValueError):
            sync_harness_experience.sync_library_to_obsidian(
                self.lib_root, project="test-project", vault_dir=self.vault_dir
            )


class TestRunHarnessAdapt(unittest.TestCase):
    """Test run_harness_adapt.py CLI and adaptation execution."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name).resolve()
        self.script_path = SCRIPTS_DIR / "run_harness_adapt.py"
        self.vault_dir = self.temp_path / "AgentMemory"
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_harness_adapt_demo_mode(self):
        """Verify run_harness_adapt.py --demo executes and generates summary.json and library."""
        self.assertTrue(self.script_path.is_file(), f"{self.script_path} must exist")
        output_dir = self.temp_path / "demo_run"

        cmd = [
            sys.executable,
            str(self.script_path),
            "--demo",
            "--k",
            "1",
            "--mode",
            "parallel",
            "--output",
            str(output_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(
            result.returncode,
            0,
            f"run_harness_adapt.py failed with code {result.returncode}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

        # Check summary.json is generated
        summary_file = output_dir / "summary.json"
        self.assertTrue(summary_file.is_file(), f"summary.json not found in {output_dir}")

        # Check EXPERIENCE.md was created in library
        exp_files = list(output_dir.rglob("EXPERIENCE.md"))
        self.assertTrue(len(exp_files) > 0, "No EXPERIENCE.md found in demo output library")

    def test_run_harness_adapt_with_sync_obsidian(self):
        """Verify run_harness_adapt.py --demo --sync-obsidian syncs experiences to vault."""
        self.assertTrue(self.script_path.is_file(), f"{self.script_path} must exist")
        output_dir = self.temp_path / "sync_run"
        project_name = "test-sync-project"

        cmd = [
            sys.executable,
            str(self.script_path),
            "--demo",
            "--k",
            "1",
            "--mode",
            "parallel",
            "--project",
            project_name,
            "--output",
            str(output_dir),
            "--sync-obsidian",
            "--vault-dir",
            str(self.vault_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(
            result.returncode,
            0,
            f"run_harness_adapt.py failed with code {result.returncode}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

        # Verify synced note in custom vault
        expected_note = self.vault_dir / "projects" / project_name / "experiences" / "accounting.md"
        self.assertTrue(expected_note.is_file(), f"Obsidian note was not synced to {expected_note}")
        note_content = expected_note.read_text(encoding="utf-8")
        self.assertIn("type: harness-experience", note_content)
        self.assertIn(f"project: {project_name}", note_content)
        self.assertIn("accounting", note_content)


class TestSkillsAndRouting(unittest.TestCase):
    """Test SKILL.md files for frontmatter, Tri-Model routing, and home sync."""

    def test_skills_frontmatter_and_tri_model(self):
        """Verify skills exist, have valid frontmatter, document Tri-Model routing, and are synced."""
        skills_base = REPO_ROOT / "skills" if (REPO_ROOT / "skills").is_dir() else REPO_ROOT / ".antigravity" / "skills"
        skill_adapt = skills_base / "asw-harness-adapt" / "SKILL.md"
        skill_router = skills_base / "skill-router" / "SKILL.md"

        self.assertTrue(skill_adapt.is_file(), f"{skill_adapt} must exist")
        self.assertTrue(skill_router.is_file(), f"{skill_router} must exist")

        for skill_path, expected_name in [
            (skill_adapt, "asw-harness-adapt"),
            (skill_router, "skill-router"),
        ]:
            content = skill_path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"), f"{skill_path} missing frontmatter start")
            self.assertIn(f"name: {expected_name}", content)
            self.assertIn("description:", content)
            # Tri-Model references
            self.assertIn("Gemini 4 Argon", content)
            self.assertIn("Claude Opus 5.5", content)
            self.assertIn("Gemini 3.8 Flash", content)

        # Check skill-router mentions asw-harness-adapt
        router_content = skill_router.read_text(encoding="utf-8")
        self.assertIn("asw-harness-adapt", router_content)

        # Check synced copies exist in Path.home() directories
        home = Path.home()
        target_dirs = [
            home / ".gemini" / "config" / "skills",
            home / ".gemini" / "antigravity-ide" / "skills",
            home / ".agents" / "skills",
        ]
        for td in target_dirs:
            adapt_copy = td / "asw-harness-adapt" / "SKILL.md"
            router_copy = td / "skill-router" / "SKILL.md"
            self.assertTrue(adapt_copy.is_file(), f"Missing synced skill at {adapt_copy}")
            self.assertTrue(router_copy.is_file(), f"Missing synced skill at {router_copy}")


if __name__ == "__main__":
    unittest.main()
