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

"""Unit and behavioural tests for AntigravitySubstrate and ANTIGRAVITY_SURFACE."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
antigravity_path = str(REPO_ROOT / ".antigravity")
if antigravity_path not in sys.path:
    sys.path.insert(0, antigravity_path)

from harness2.core import prompts
from harness2.core import tree as HT
from harness2.substrate.antigravity import (
    ANTIGRAVITY_SURFACE,
    IMMUTABLE_GOVERNANCE_FILES,
    MAX_ACTIVE_SKILLS,
    AntigravitySubstrate,
    validate_antigravity_harness,
)


class TestAntigravitySubstrate(unittest.TestCase):
    def test_imports_and_prompts_registration(self):
        """Verify exports and prompts._st registration for antigravity."""
        self.assertIsNotNone(ANTIGRAVITY_SURFACE)
        self.assertIsNotNone(AntigravitySubstrate)
        self.assertIsNotNone(IMMUTABLE_GOVERNANCE_FILES)
        self.assertTrue(callable(validate_antigravity_harness))

        st = prompts._st("antigravity")
        self.assertIsNotNone(st)
        self.assertIn("antigravity", prompts._SURFACE_TEXTS)
        self.assertIn(".antigravity/harness_triggers.md", st.surface_md)
        self.assertIn(".antigravity/tool_guidance.md", st.surface_md)

    def test_surface_spec_attributes(self):
        """Verify ANTIGRAVITY_SURFACE properties."""
        self.assertEqual(ANTIGRAVITY_SURFACE.name, "antigravity")
        self.assertEqual(
            ANTIGRAVITY_SURFACE.always_on,
            (".antigravity/harness_triggers.md", ".antigravity/tool_guidance.md"),
        )
        self.assertEqual(ANTIGRAVITY_SURFACE.always_on_max, 6000)
        self.assertEqual(ANTIGRAVITY_SURFACE.skill_dir, ".agents/skills")
        self.assertEqual(ANTIGRAVITY_SURFACE.subagent_dir, ".antigravity/sub_agents")
        self.assertEqual(ANTIGRAVITY_SURFACE.hooks_file, ".antigravity/hooks.json")

    def test_valid_tree_acceptance(self):
        """Verify a compliant tree passes HT.validate and validate_antigravity_harness."""
        tree = {
            ".antigravity/harness_triggers.md": (
                "- When testing custom functionality, read .agents/skills/my_skill/SKILL.md and follow it.\n"
            ),
            ".antigravity/tool_guidance.md": "# Tool Guidance\nUse tools carefully.\n",
            ".agents/skills/my_skill/SKILL.md": (
                "---\n"
                "name: my_skill\n"
                "description: Custom skill for testing purposes\n"
                "---\n"
                "Skill body content.\n"
            ),
            "scripts/helper.py": "# helper\nprint('helper ready')\n",
            ".antigravity/sub_agents/scout/AGENT.md": (
                "---\n"
                "description: Autonomous scout agent\n"
                "---\n"
                "Agent instructions.\n"
            ),
        }

        census = HT.validate(ANTIGRAVITY_SURFACE, tree)
        self.assertEqual(census["skills"], 1)
        self.assertEqual(census["scripts"], 1)

        # validate_antigravity_harness should complete without error
        validate_antigravity_harness(tree)

    def test_immutable_governance_protection(self):
        """Verify immutable governance files are rejected by read_tree and validate_antigravity_harness."""
        governance_files = [
            ".antigravity/rules/GLOBAL_DEVELOPMENT_RULES.md",
            "GEMINI.md",
            "AGENTS.md",
            "PROGRAM_INVARIANTS.json",
            "METRIC_REGISTRY.json",
            "SOURCE_PLAN.md",
            "REQUIREMENT_COVERAGE.csv",
        ]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in governance_files:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("governance tampering attempt", encoding="utf-8")

            rejected = []
            read_files = HT.read_tree(ANTIGRAVITY_SURFACE, root, rejected=rejected)
            # All governance files must be in rejected
            self.assertEqual(read_files, {})
            for rel in governance_files:
                self.assertIn(rel, rejected)

        # Direct dictionary rejection
        for rel in governance_files:
            bad_tree = {
                ".antigravity/harness_triggers.md": "standing instruction\n",
                ".antigravity/tool_guidance.md": "tool guidance\n",
                rel: "forbidden modification",
            }
            with self.assertRaises(ValueError) as ctx:
                validate_antigravity_harness(bad_tree)
            self.assertIn("immutable", str(ctx.exception).lower())

    def test_max_active_skills_budget_enforcement(self):
        """Verify active skill budget <= 8 is enforced."""
        trigger_lines = []
        skills_tree = {
            ".antigravity/tool_guidance.md": "tool guidance\n",
        }
        # Create 9 skills
        for i in range(1, 10):
            name = f"skill_{i}"
            trigger_lines.append(
                f"- When situation {i}, read .agents/skills/{name}/SKILL.md and follow it.\n"
            )
            skills_tree[f".agents/skills/{name}/SKILL.md"] = (
                f"---\nname: {name}\ndescription: Description for {name}\n---\nBody"
            )
        skills_tree[".antigravity/harness_triggers.md"] = "".join(trigger_lines)

        with self.assertRaises(ValueError) as ctx:
            validate_antigravity_harness(skills_tree)
        self.assertIn("Active skill budget exceeded: max 8 active skills allowed", str(ctx.exception))

    def test_path_independence_enforcement(self):
        """Verify hardcoded user-home paths are rejected."""
        # Dynamically build forbidden path strings to prevent static check violations
        sep = "\\"
        slash = "/"
        forbidden_samples = [
            "C:" + sep + "Users" + sep + "alice" + sep + "secret.txt",
            slash + "Users" + slash + "bob" + slash + "keys.json",
            slash + "home" + slash + "charlie" + slash + "workspace",
        ]

        for sample in forbidden_samples:
            tree_content_violation = {
                ".antigravity/harness_triggers.md": f"- Standing rule: path is {sample}\n",
                ".antigravity/tool_guidance.md": "tool guidance\n",
            }
            with self.assertRaises(ValueError) as ctx:
                validate_antigravity_harness(tree_content_violation)
            self.assertIn("Hardcoded user path rejected", str(ctx.exception))

            tree_key_violation = {
                ".antigravity/harness_triggers.md": "standing rule\n",
                ".antigravity/tool_guidance.md": "tool guidance\n",
                f"scripts/{sample}": "print('bad')\n",
            }
            with self.assertRaises(ValueError) as ctx:
                validate_antigravity_harness(tree_key_violation)
            self.assertIn("Hardcoded user path rejected", str(ctx.exception))

    def test_substrate_materialise_and_trajectory(self):
        """Verify AntigravitySubstrate.materialise and read_trajectory."""
        substrate = AntigravitySubstrate()
        self.assertEqual(substrate.name, "ag")
        self.assertEqual(substrate.surface(), ANTIGRAVITY_SURFACE)

        with tempfile.TemporaryDirectory() as td:
            src_dir = Path(td) / "src"
            src_dir.mkdir(parents=True)
            (src_dir / ".antigravity").mkdir()
            (src_dir / ".antigravity" / "harness_triggers.md").write_text("- Triggers\n", encoding="utf-8")
            (src_dir / ".antigravity" / "tool_guidance.md").write_text("Tool guidance\n", encoding="utf-8")
            (src_dir / "scripts").mkdir()
            (src_dir / "scripts" / "helper.py").write_text("print('ok')\n", encoding="utf-8")

            # Materialise
            spec = types.SimpleNamespace(install_mode="antigravity_root")
            install = substrate.materialise(src_dir, spec, {"file:extra/config.json": '{"ok": true}'})
            try:
                self.assertTrue(install.staging_dir.is_dir())
                self.assertTrue((install.staging_dir / ".antigravity" / "harness_triggers.md").is_file())
                self.assertTrue((install.staging_dir / "scripts" / "helper.py").is_file())
                self.assertTrue((install.staging_dir / "extra" / "config.json").is_file())
                self.assertEqual(install.extras.get("install_mode"), "antigravity_root")
            finally:
                import shutil
                shutil.rmtree(install.staging_dir, ignore_errors=True)

        # Test read_trajectory on JSONL event stream
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.write(json.dumps({"type": "USER_INPUT", "content": "Fix the issue"}) + "\n")
            tf.write(json.dumps({"type": "PLANNER_RESPONSE", "thinking": "Analyzing root cause"}) + "\n")
            tf.write(json.dumps({"type": "tool_call", "name": "run_command", "args": {"cmd": "pytest"}}) + "\n")
            tf.write(json.dumps({"type": "tool_result", "output": "1 passed"}) + "\n")
            stream_file = Path(tf.name)

        try:
            rendered = substrate.read_trajectory(stream_file, obs_trunc=200, max_chars=1000)
            self.assertIn("[USER] Fix the issue", rendered)
            self.assertIn("[THINKING] Analyzing root cause", rendered)
            self.assertIn("[ACTION] run_command", rendered)
            self.assertIn("[OBSERVATION] 1 passed", rendered)
        finally:
            if stream_file.exists():
                stream_file.unlink()


if __name__ == "__main__":
    unittest.main()
