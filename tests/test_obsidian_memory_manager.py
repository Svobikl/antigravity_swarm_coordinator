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
                    "Acme Systems Labs - B2B AI & Edge Infrastructure, concise executive Czech communication.",
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
                    "Use Carbon High for planning, Opus 5.5 for opposition review, Flash High for bounded coding.",
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
            self.assertIn("Acme Systems Labs", out)
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

    def test_auto_provisions_antigravity_and_handles_cp1252_unicode_edge(self):
        """Recalling or indexing a sub-project auto-provisions .antigravity/scripts/memory_manager.py and handles cp1252 stdout without UnicodeEncodeError."""
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            sub_proj = tmp_path / "acme_subproject"
            sub_proj.mkdir(parents=True)
            (sub_proj / "README.md").write_text(
                "# AcmeAnalytics²\n\nPříliš žluťoučký kůň s podporou Harness² a ℝ³.\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "cp1252"

            # First call via script_path with PYTHONIOENCODING=cp1252
            p1 = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--recall",
                    "--project-path",
                    str(sub_proj),
                    "--task-type",
                    "code",
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                env=env,
            )
            self.assertEqual(p1.returncode, 0, f"Failed under cp1252: {p1.stderr.decode('utf-8', errors='replace')}")

            # Verify .antigravity/scripts/memory_manager.py was auto-provisioned into sub_proj
            local_mm = sub_proj / ".antigravity" / "scripts" / "memory_manager.py"
            self.assertTrue(
                local_mm.is_file(),
                "memory_manager.py must auto-provision .antigravity/scripts/memory_manager.py into target project",
            )

            # Now run the exact command from inside sub_proj using relative path .antigravity/scripts/memory_manager.py
            p2 = subprocess.run(
                [
                    sys.executable,
                    ".antigravity/scripts/memory_manager.py",
                    "--recall",
                    "--project-path",
                    ".",
                    "--task-type",
                    "code",
                    "--vault-dir",
                    str(vault_dir),
                ],
                cwd=str(sub_proj),
                capture_output=True,
                env=env,
            )
            self.assertEqual(p2.returncode, 0, f"Relative invocation inside sub_proj failed: {p2.stderr.decode('utf-8', errors='replace')}")

    def test_pruned_recall_project_scoping_extractive_distillation_and_byte_budget(self):
        """M1..M3: Pruned recall enforces project scoping, extractive When->Rule distillation, byte budget < 10,000 B, and --full restore."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"

            # Init vault
            subprocess.run([sys.executable, str(self.script_path), "--init-vault", "--vault-dir", str(vault_dir)], check=True)

            # Record multiple lessons: 2 global, 2 for alpha_proj, 8 for beta_proj
            # Global 1
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When parsing JSON from untrusted HTTP responses",
                "--mistake", "Direct json.loads without try-except crashed daemon",
                "--rule", "Always wrap json.loads in try-except block with fallback",
                "--global", "--vault-dir", str(vault_dir),
            ], check=True)

            # Global 2
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When creating temporary files on Windows and Linux",
                "--mistake", "Used fixed path in /tmp which collided and failed on Windows",
                "--rule", "Always use tempfile.NamedTemporaryFile or pytest tmp_path fixture",
                "--global", "--vault-dir", str(vault_dir),
            ], check=True)

            # alpha_proj lesson 1
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When configuring alpha_proj database connection pool",
                "--mistake", "Set pool size to 100 crashing local postgres",
                "--rule", "Cap alpha_proj DB pool size to 10 in development",
                "--project", "alpha_proj", "--vault-dir", str(vault_dir),
            ], check=True)

            # alpha_proj lesson 2
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When running alpha_proj websocket relay handler",
                "--mistake", "Forgot ping keepalive timeout closing client sockets",
                "--rule", "Send alpha_proj ping frame every 30 seconds",
                "--project", "alpha_proj", "--vault-dir", str(vault_dir),
            ], check=True)

            # beta_proj lessons (8 cross-project lessons)
            for i in range(8):
                subprocess.run([
                    sys.executable, str(self.script_path), "--record-lesson",
                    "--cue", f"When tuning beta_proj cache layer parameter number {i}",
                    "--mistake", f"Beta mistake description narrative for cache number {i}",
                    "--rule", f"Always set beta_proj cache TTL number {i} to 60 seconds",
                    "--project", "beta_proj", "--vault-dir", str(vault_dir),
                ], check=True)

            # 1. Default recall for alpha_proj
            p_default = subprocess.run(
                [
                    sys.executable, str(self.script_path), "--recall",
                    "--project", "alpha_proj", "--vault-dir", str(vault_dir),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            out_default = p_default.stdout
            out_bytes = len(out_default.encode("utf-8"))

            # Byte size < 10,000 bytes (M1)
            self.assertLess(out_bytes, 10000, f"Recalled output size {out_bytes} exceeds 10,000 B ceiling")

            # Extractive distillation: When -> Rule, omitting Mistake / User Correction (M2)
            self.assertIn("When:**", out_default)
            self.assertIn("-> **Rule:**", out_default)
            self.assertNotIn("Mistake / User Correction", out_default, "Default recall must omit verbose Mistake text")

            # Active project lessons are present and not duplicated
            self.assertIn("Cap alpha_proj DB pool size to 10", out_default)
            count_alpha_rule = out_default.count("Cap alpha_proj DB pool size to 10")
            self.assertEqual(count_alpha_rule, 1, "Active project lesson must be rendered exactly once (no duplicates)")

            # Cross-project lessons from beta_proj capped at Top-K (<= 5)
            beta_matches = [line for line in out_default.splitlines() if "beta_proj cache TTL" in line]
            self.assertLessEqual(len(beta_matches), 5, "Cross-project lessons must be bounded to Top-K (<= 5)")

            # 2. Recall with --full (M3)
            p_full = subprocess.run(
                [
                    sys.executable, str(self.script_path), "--recall",
                    "--project", "alpha_proj", "--full", "--vault-dir", str(vault_dir),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            out_full = p_full.stdout
            self.assertIn("Mistake / User Correction", out_full, "--full must restore Mistake narrative")
            self.assertIn("Set pool size to 100 crashing local postgres", out_full)

    def test_prune_vault_and_deduplication(self):
        """M6: --prune-vault moves project-tagged lessons into project notes, deduplicates near-duplicates (Jaccard >= 0.72), and backs up files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"

            subprocess.run([sys.executable, str(self.script_path), "--init-vault", "--vault-dir", str(vault_dir)], check=True)

            global_file = vault_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md"
            # Add synthetic lessons to global file:
            # 1. Project-tagged lesson for gamma_proj
            # 2. Universal lesson
            # 3. Duplicate of universal lesson (Jaccard >= 0.72)
            synth_content = """# Engineering Lessons & Anti-Patterns

## Universal Anti-Patterns & Invariants

### [2026-11-01] When invoking subprocess.run in child tool calls
- **Cue (When)**: When invoking subprocess.run in child tool calls (Project: [[projects/gamma_proj/gamma_proj|gamma_proj]])
- **Mistake / User Correction**: Left timeout parameter unset leading to hanging processes
- **Mandatory Rule**: Always specify explicit timeout parameter on subprocess.run calls in gamma_proj

### [2026-11-02] When parsing UTF-8 files across platforms
- **Cue (When)**: When parsing UTF-8 files across platforms
- **Mistake / User Correction**: Used platform default encoding which failed on Windows cp1252
- **Mandatory Rule**: Always pass encoding='utf-8' and errors='replace' to open and read_text

### [2026-11-03] When reading text files across platforms
- **Cue (When)**: When reading text files across platforms in Python
- **Mistake / User Correction**: Omitted utf-8 encoding causing Windows cp1252 crash
- **Mandatory Rule**: Always pass encoding='utf-8' and errors='replace' to open or read_text calls
"""
            global_file.write_text(synth_content, encoding="utf-8")

            # Run --prune-vault
            p_prune = subprocess.run(
                [sys.executable, str(self.script_path), "--prune-vault", "--vault-dir", str(vault_dir)],
                capture_output=True,
                text=True,
                check=True,
            )
            prune_res = json.loads(p_prune.stdout)
            self.assertEqual(prune_res.get("status"), "pruned")

            # 1. Backup was created under .obsidian/backups/
            backups_dir = vault_dir / ".obsidian" / "backups"
            self.assertTrue(backups_dir.is_dir())
            backup_subdirs = list(backups_dir.iterdir())
            self.assertGreaterEqual(len(backup_subdirs), 1)

            # 2. Project-tagged lesson was moved to projects/gamma_proj/Project Lessons.md
            gamma_lessons = vault_dir / "projects" / "gamma_proj" / "Project Lessons.md"
            self.assertTrue(gamma_lessons.is_file())
            self.assertIn("Always specify explicit timeout parameter on subprocess.run", gamma_lessons.read_text(encoding="utf-8"))

            # 3. Global file does NOT retain gamma_proj tagged lesson
            cleaned_global = global_file.read_text(encoding="utf-8")
            self.assertNotIn("gamma_proj", cleaned_global)

            # 4. Duplicate universal lesson was merged (Jaccard >= 0.72)
            rule_count = cleaned_global.count("encoding='utf-8'")
            self.assertEqual(rule_count, 1, "Duplicate universal lessons must be merged into 1 entry")

    def test_record_lesson_project_scoping_behavior(self):
        """record_lesson writes only to project file when project-specific, and to global file when --global."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            subprocess.run([sys.executable, str(self.script_path), "--init-vault", "--vault-dir", str(vault_dir)], check=True)

            # Project-specific lesson
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When updating acme_analytics internal api routes in services/control_plane",
                "--mistake", "Modified internal acme_analytics database schema directly",
                "--rule", "Always apply acme_analytics alembic migrations before starting server",
                "--project", "acme_analytics",
                "--vault-dir", str(vault_dir),
            ], check=True)

            global_file = vault_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md"
            proj_file = vault_dir / "projects" / "acme_analytics" / "Project Lessons.md"

            self.assertTrue(proj_file.is_file())
            self.assertIn("acme_analytics alembic migrations", proj_file.read_text(encoding="utf-8"))
            self.assertNotIn("acme_analytics alembic migrations", global_file.read_text(encoding="utf-8"))

            # Global lesson
            subprocess.run([
                sys.executable, str(self.script_path), "--record-lesson",
                "--cue", "When writing unit tests for asynchronous python code",
                "--mistake", "Forgot async keyword causing unawaited coroutine warning",
                "--rule", "Always await async functions in pytest-asyncio tests",
                "--project", "acme_analytics",
                "--global",
                "--vault-dir", str(vault_dir),
            ], check=True)

            self.assertIn("Always await async functions in pytest-asyncio tests", global_file.read_text(encoding="utf-8"))

    def test_session_recall_cache(self):
        """--session-cache caches recall output in .asw/cache/recall_cache.json and serves repeated calls from cache."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            subprocess.run([sys.executable, str(self.script_path), "--init-vault", "--vault-dir", str(vault_dir)], check=True)

            # First recall with --session-cache
            p1 = subprocess.run([
                sys.executable, str(self.script_path), "--recall",
                "--project", "cache_proj",
                "--session-cache",
                "--vault-dir", str(vault_dir),
            ], capture_output=True, text=True, check=True)

            cache_file = vault_dir / ".asw" / "cache" / "recall_cache.json"
            self.assertTrue(cache_file.is_file(), f"Cache file {cache_file} was not created")

            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(cache_data), 1)

            # Second call should match
            p2 = subprocess.run([
                sys.executable, str(self.script_path), "--recall",
                "--project", "cache_proj",
                "--session-cache",
                "--vault-dir", str(vault_dir),
            ], capture_output=True, text=True, check=True)
            self.assertEqual(p1.stdout, p2.stdout)

    def test_prune_vault_and_recall_negative_and_edge_cases(self):
        """Negative & boundary cases: recalling empty vault, pruning empty vault, or invalid cache."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            empty_vault = tmp_path / "EmptyVault"
            empty_vault.mkdir()

            # Recalling empty vault does not crash and returns minimal non-empty string
            p_empty = subprocess.run([
                sys.executable, str(self.script_path), "--recall",
                "--project", "nonexistent_proj",
                "--vault-dir", str(empty_vault),
            ], capture_output=True, text=True)
            self.assertEqual(p_empty.returncode, 0)
            self.assertNotEqual(len(p_empty.stdout), 0)
            self.assertFalse("Error" in p_empty.stderr, "Empty vault recall must not write error to stderr")

            # Pruning empty vault reports clean completion without failure
            prune_empty = subprocess.run([
                sys.executable, str(self.script_path), "--prune-vault",
                "--vault-dir", str(empty_vault),
            ], capture_output=True, text=True)
            self.assertEqual(prune_empty.returncode, 0)
            self.assertFalse("Traceback" in prune_empty.stderr)


if __name__ == "__main__":
    unittest.main()
