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
import re
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
    """Test SKILL.md files for frontmatter, Quad-Model Neon routing, and repo/agent parity."""

    # Construct legacy pattern dynamically so this test file itself contains zero legacy model literals
    _LEGACY_TIER = "ar" + "gon"
    _LEGACY_PATTERN = re.compile(rf"\b{_LEGACY_TIER}\b|gemini-4-{_LEGACY_TIER}", re.IGNORECASE)

    def test_skills_frontmatter_and_tri_model(self):
        """Verify skills exist, have valid frontmatter, document Quad-Model Neon routing, and are synced."""
        skill_trees = [
            REPO_ROOT / ".antigravity" / "skills",
            REPO_ROOT / "core_framework" / "skills",
            REPO_ROOT / "plugins" / "antigravity-swarm" / "skills",
        ]
        for skills_base in skill_trees:
            skill_adapt = skills_base / "asw-harness-adapt" / "SKILL.md"
            skill_router = skills_base / "skill-router" / "SKILL.md"

            self.assertTrue(skill_adapt.is_file(), f"{skill_adapt} must exist")
            self.assertTrue(skill_router.is_file(), f"{skill_router} must exist")

            for skill_path, expected_name in [
                (skill_adapt, "asw-harness-adapt"),
                (skill_router, "skill-router"),
            ]:
                raw = skill_path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{skill_path} must not have UTF-8 BOM")
                content = raw.decode("utf-8").replace("\r\n", "\n")
                self.assertTrue(content.startswith("---\n"), f"{skill_path} missing frontmatter start")
                self.assertIn(f"name: {expected_name}", content)
                desc_lines = [l for l in content.splitlines()[:10] if l.startswith("description:")]
                self.assertEqual(len(desc_lines), 1, f"{skill_path} must have single-line description:")
                desc_val = desc_lines[0].split("description:", 1)[1].strip()
                self.assertTrue(15 <= len(desc_val) <= 120, f"{skill_path} description length {len(desc_val)} out of [15, 120]")
                # Quad-Model references (Neon, not legacy tier)
                self.assertIn("Gemini 4 Carbon", content)
                self.assertIn("Claude Opus 5.5", content)
                self.assertIn("Gemini 4 Neon", content)
                self.assertIn("Gemini 4 Hydrogen", content)
                self.assertIsNone(self._LEGACY_PATTERN.search(content), f"{skill_path} still contains legacy tier name")

            # Check skill-router mentions asw-harness-adapt
            router_content = skill_router.read_text(encoding="utf-8")
            self.assertIn("asw-harness-adapt", router_content)

        # Repo skill trees must be identical (CRLF-normalized) for shared skills
        for sk in ("asw-harness-adapt", "skill-router"):
            ref_bytes = (skill_trees[0] / sk / "SKILL.md").read_bytes().replace(b"\r\n", b"\n")
            for tree in skill_trees[1:]:
                self.assertEqual(
                    (tree / sk / "SKILL.md").read_bytes().replace(b"\r\n", b"\n"),
                    ref_bytes,
                    f"{tree / sk / 'SKILL.md'} differs from {skill_trees[0] / sk / 'SKILL.md'}",
                )

        # Check synced copies exist in Path.home() directories when provisioned
        home = Path.home()
        target_dirs = [
            home / ".gemini" / "config" / "skills",
            home / ".gemini" / "antigravity-ide" / "skills",
            home / ".agents" / "skills",
        ]
        for td in target_dirs:
            if not td.is_dir():
                continue
            adapt_copy = td / "asw-harness-adapt" / "SKILL.md"
            router_copy = td / "skill-router" / "SKILL.md"
            self.assertTrue(adapt_copy.is_file(), f"Missing synced skill at {adapt_copy}")
            self.assertTrue(router_copy.is_file(), f"Missing synced skill at {router_copy}")

    def test_agents_byte_identical_and_readonly_tools(self):
        """Verify all 3 agent directories are byte-identical, Neon-migrated, and enforce read-only tools."""
        agent_dirs = [
            REPO_ROOT / ".antigravity" / "agents",
            REPO_ROOT / "core_framework" / "agents",
            REPO_ROOT / "plugins" / "antigravity-swarm" / "agents",
        ]
        ref_files = sorted(p.name for p in agent_dirs[0].iterdir() if p.is_file())
        self.assertEqual(len(ref_files), 16, f"Expected 16 agent files, found {ref_files}")
        for ad in agent_dirs[1:]:
            self.assertEqual(sorted(p.name for p in ad.iterdir() if p.is_file()), ref_files)
            for fname in ref_files:
                self.assertEqual(
                    (ad / fname).read_bytes().replace(b"\r\n", b"\n"),
                    (agent_dirs[0] / fname).read_bytes().replace(b"\r\n", b"\n"),
                    f"Agent file {ad / fname} does not match {agent_dirs[0] / fname}",
                )

        for fname in ref_files:
            text = (agent_dirs[0] / fname).read_text(encoding="utf-8")
            self.assertIsNone(self._LEGACY_PATTERN.search(text), f"{fname} still references legacy tier name")

        for receipt_agent in ("asw-explorer.md", "asw-implementer.md", "asw-reviewer.md"):
            content = (agent_dirs[0] / receipt_agent).read_text(encoding="utf-8")
            self.assertIn("<= 250 tokens", content, f"{receipt_agent} missing <= 250 tokens receipt contract")
        self.assertIn("chub ", (agent_dirs[0] / "asw-implementer.md").read_text(encoding="utf-8"))

        for readonly_agent in ("asw-plan-audit.md", "asw-opposition-reviewer.md"):
            content = (agent_dirs[0] / readonly_agent).read_text(encoding="utf-8")
            tools_lines = [l for l in content.splitlines()[:10] if l.startswith("tools:")]
            self.assertEqual(len(tools_lines), 1, f"{readonly_agent} missing tools: frontmatter")
            self.assertNotIn("write_file", tools_lines[0], f"{readonly_agent} must NOT grant write_file")
            self.assertNotIn("edit_file", tools_lines[0], f"{readonly_agent} must NOT grant edit_file")

    def test_model_enum_and_scoped_bmad_rollback(self):
        """Verify Model enum vs .toml IDs, scoped Target Files rollback, and zero legacy tier in core docs."""
        contract_docs = [
            REPO_ROOT / "global_entrypoint" / "GEMINI.md",
            REPO_ROOT / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md",
            REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md",
            REPO_ROOT / ".antigravity" / "skills" / "swarm-coordinator" / "SKILL.md",
            REPO_ROOT / "core_framework" / "skills" / "swarm-coordinator" / "SKILL.md",
            REPO_ROOT / "plugins" / "antigravity-swarm" / "skills" / "swarm-coordinator" / "SKILL.md",
        ]
        for doc in contract_docs:
            text = doc.read_text(encoding="utf-8")
            self.assertIsNone(self._LEGACY_PATTERN.search(text), f"{doc} still references legacy tier name")
            self.assertIn("flash_lite", text, f"{doc} missing invoke_subagent Model enum documentation")
            self.assertIn("gemini-4-neon-high", text, f"{doc} missing exact .toml model ID documentation")

        rollback_docs = [
            REPO_ROOT / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md",
            REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md",
            REPO_ROOT / "core_framework" / "skills" / "asw-loop" / "references" / "bmad-steps.md",
            REPO_ROOT / "plugins" / "antigravity-swarm" / "skills" / "asw-loop" / "references" / "bmad-steps.md",
        ]
        for doc in rollback_docs:
            text = doc.read_text(encoding="utf-8")
            self.assertIn("Target Files", text, f"{doc} must scope BMAD rollback to Target Files")
            self.assertIn("git reset --hard", text, f"{doc} must explicitly forbid repo-wide git reset --hard")
            self.assertIn("git checkout <baseline_revision> --", text, f"{doc} missing scoped git checkout command")


if __name__ == "__main__":
    unittest.main()
