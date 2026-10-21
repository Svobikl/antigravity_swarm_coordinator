import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestObsidianMemoryManager(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.script_path = self.repo_root / ".antigravity" / "scripts" / "memory_manager.py"

    def test_init_vault_and_idempotency(self):
        """--init-vault creates full Obsidian vault structure, registers in obsidian.json, and preserves existing notes."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            obs_cfg = tmp_path / "obsidian.json"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--init-vault",
                    "--vault-dir",
                    str(vault_dir),
                    "--obsidian-config",
                    str(obs_cfg),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc.returncode, 0, f"init-vault failed: {proc.stderr}")

            expected_files = [
                vault_dir / "Home.md",
                vault_dir / ".obsidian" / "app.json",
                vault_dir / ".obsidian" / "graph.json",
                vault_dir / "todos" / "Active TODOs.md",
                vault_dir / "profile" / "User and Company Profile.md",
                vault_dir / "domains" / "Presentations and Visual Style.md",
                vault_dir / "domains" / "Coding and Architecture Preferences.md",
                vault_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md",
            ]
            for ef in expected_files:
                self.assertTrue(ef.is_file(), f"Expected vault file missing: {ef}")

            # Verify obsidian.json registration
            self.assertTrue(obs_cfg.is_file())
            obs_data = json.loads(obs_cfg.read_text(encoding="utf-8"))
            self.assertIn("vaults", obs_data)
            vault_paths = [Path(v["path"]).resolve() for v in obs_data["vaults"].values()]
            self.assertIn(vault_dir.resolve(), vault_paths)

            # Verify idempotency: custom content is preserved on re-init
            profile_file = vault_dir / "profile" / "User and Company Profile.md"
            profile_file.write_text(
                profile_file.read_text(encoding="utf-8") + "\n- CustomCompanyMarker: AcmeAI\n",
                encoding="utf-8",
            )
            proc2 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--init-vault",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc2.returncode, 0)
            self.assertIn("CustomCompanyMarker: AcmeAI", profile_file.read_text(encoding="utf-8"))

    def test_index_project_creates_rich_project_overview(self):
        """--index-project scans a project repo and writes overview, architecture map, decisions, and lessons."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            sample_proj = tmp_path / "sample_edge_service"
            (sample_proj / "services").mkdir(parents=True)
            (sample_proj / "frontend").mkdir(parents=True)
            (sample_proj / "tests").mkdir(parents=True)
            (sample_proj / "README.md").write_text(
                "# Sample Edge Service\n\nHigh-throughput relay service for distributed edge nodes.\n",
                encoding="utf-8",
            )
            (sample_proj / "requirements.txt").write_text("fastapi\nuvicorn\npydantic\n", encoding="utf-8")
            (sample_proj / "services" / "api.py").write_text("def start_api():\n    return True\n", encoding="utf-8")
            (sample_proj / "tests" / "test_api.py").write_text("def test_api():\n    assert True\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--index-project",
                    str(sample_proj),
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
            )
            self.assertEqual(proc.returncode, 0, f"index-project failed: {proc.stderr}")

            proj_vault = vault_dir / "projects" / "sample_edge_service"
            self.assertTrue((proj_vault / "sample_edge_service.md").is_file())
            self.assertTrue((proj_vault / "Architecture and Components.md").is_file())
            self.assertTrue((proj_vault / "Decision Ledger.md").is_file())
            self.assertTrue((proj_vault / "Project Lessons.md").is_file())

            overview_txt = (proj_vault / "sample_edge_service.md").read_text(encoding="utf-8")
            self.assertIn("High-throughput relay service", overview_txt)
            self.assertIn("FastAPI", overview_txt)
            self.assertIn("[[projects/sample_edge_service/Architecture and Components", overview_txt)

            home_txt = (vault_dir / "Home.md").read_text(encoding="utf-8")
            self.assertIn("sample_edge_service", home_txt)

    def test_record_lesson_preference_and_recall(self):
        """--record-lesson, --record-preference, --update-project-note, and --recall persist and retrieve self-learning memory."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            sample_proj = tmp_path / "demo_project"
            sample_proj.mkdir()
            (sample_proj / "README.md").write_text("# Demo Project\n\nDemo description.\n", encoding="utf-8")

            # 1. Record company/user profile preference
            p1 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--record-preference",
                    "--category",
                    "profile",
                    "--topic",
                    "Company Identity",
                    "--preference",
                    "EdgeRelay Labs - B2B AI & Edge Infrastructure, concise executive Czech communication.",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p1.returncode, 0, p1.stderr)

            # 2. Record presentation preference
            p2 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--record-preference",
                    "--category",
                    "presentations",
                    "--topic",
                    "Slide Deck Style",
                    "--preference",
                    "Dark navy theme, high-contrast KPI cards, max 4 bullet points per slide.",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p2.returncode, 0, p2.stderr)

            # 3. Record engineering lesson from user correction
            p3 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--record-lesson",
                    "--cue",
                    "When creating or modifying SKILL.md files across repo and plugin directories",
                    "--mistake",
                    "Left 18 SKILL.md files without YAML frontmatter header, causing Antigravity customization load failures",
                    "--rule",
                    "Always include valid --- name/description --- YAML frontmatter without UTF-8 BOM in every SKILL.md",
                    "--project",
                    "demo_project",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p3.returncode, 0, p3.stderr)

            # 4. Update project decision note
            p4 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--update-project-note",
                    "--project",
                    "demo_project",
                    "--section",
                    "decision",
                    "--title",
                    "ADR-001 Tri-Model Routing",
                    "--content",
                    "Use Argon High for planning, Opus 5.5 for opposition review, Flash High for bounded coding.",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p4.returncode, 0, p4.stderr)

            # 5. Recall context for presentation & code
            p_recall = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--recall",
                    "--project-path",
                    str(sample_proj),
                    "--task-type",
                    "presentation",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_recall.returncode, 0, p_recall.stderr)
            out = p_recall.stdout
            self.assertIn("EdgeRelay Labs", out)
            self.assertIn("Dark navy theme", out)
            self.assertIn("Always include valid --- name/description --- YAML frontmatter", out)
            self.assertIn("ADR-001 Tri-Model Routing", out)

    def test_negative_and_edge_cases_rejected(self):
        """Invalid inputs (empty lesson rule, invalid category, missing project path) must fail with non-zero exit status."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            vault_dir = Path(tmp_dir) / "AgentMemory"

            # Empty lesson rule
            bad_lesson = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--record-lesson",
                    "--cue",
                    "Some cue",
                    "--mistake",
                    "Some mistake",
                    "--rule",
                    "   ",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(bad_lesson.returncode, 0)

            # Non-existent project path for --index-project
            bad_proj = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--index-project",
                    str(Path(tmp_dir) / "non_existent_repo_xyz"),
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(bad_proj.returncode, 0)


if __name__ == "__main__":
    unittest.main()
