import re
import unittest
from pathlib import Path


CORE_COORDINATOR_SKILLS = frozenset({
    "swarm-coordinator", "skill-router", "program-state-controller",
    "spec-product-analyst", "software-architect", "ui-ux-designer",
    "implementation-developer", "interaction-e2e-tester", "validator-build-test-agent",
    "compliance-maintainability-reviewer", "opposition-reviewer",
    "acceptance-reviewer-product-qa", "security-reliability-reviewer",
    "research-experiment-auditor", "memory-state-curator",
    "completion-auditor", "documentation-handoff-agent",
    "invariant-auditor", "report-consistency-auditor",
    "research-validity-auditor", "semantic-completion-auditor",
    "asw", "asw-cleanup", "asw-comment-check", "asw-debug", "asw-goal",
    "asw-harness-adapt", "asw-loop", "asw-lsp", "asw-plan", "asw-programming",
    "asw-refactor", "asw-remove-ai-slops", "asw-review", "asw-rules",
    "asw-start-work", "asw-test-gui", "asw-ui-ux", "rtk-token-killer", "obs-memory", "agent-memory", "agent-memory-mcp",
    "obsidian-markdown", "obsidian-cli", "obsidian-bases",
})

REQUIRED_DOMAIN_REPRESENTATIVES = frozenset({
    # Legal & Compliance
    "lex", "legal-advisor", "gdpr-data-handling", "employment-contract-templates",
    # Presentations & Office
    "pptx-official", "docx-official", "xlsx-official", "pdf-official", "frontend-slides", "document-extraction",
    # Project, Strategy & Hardware Sourcing
    "product-manager-toolkit", "concise-planning", "electronics-sourcing", "kotler-macro-analyzer",
    # Marketing & SEO
    "marketing-plan", "seo-audit", "geo-fundamentals", "copywriting",
    # UI/UX & 3D
    "frontend-design", "ui-ux-pro-max", "3d-ui", "threejs-skills",
    # Engineering, Embedded & Odoo
    "odoo-module-developer", "odoo-orm-expert", "firmware-analyst", "python-pro", "typescript-pro", "rust-pro",
    # Data, Quant & AI
    "quant-analyst", "data-scientist", "rag-engineer", "deep-research",
    # Testing, DevOps & Security
    "systematic-debugging", "test-driven-development", "playwright-skill", "docker-expert", "cloudflare",
})


class TestSkillCatalogCuration(unittest.TestCase):
    def setUp(self):
        self.home = Path.home()
        self.cfg_dir = self.home / ".gemini" / "config" / "skills"
        self.ide_dir = self.home / ".gemini" / "antigravity-ide" / "skills"
        self.ag_dir = self.home / ".agents" / "skills"

    def test_catalog_size_under_antigravity_budget(self):
        """Global skill catalog must contain exactly 200 curated skills (strictly <= 215 budget)."""
        cfg_skills = {d.name for d in self.cfg_dir.iterdir() if d.is_dir()}
        self.assertEqual(
            len(cfg_skills),
            200,
            f"Expected exactly 200 curated skills in .gemini/config/skills, found {len(cfg_skills)}",
        )
        ide_skills = {d.name for d in self.ide_dir.iterdir() if d.is_dir()}
        ag_skills = {d.name for d in self.ag_dir.iterdir() if d.is_dir()}
        self.assertEqual(cfg_skills, ide_skills, "antigravity-ide/skills must match curated config/skills")
        self.assertEqual(cfg_skills, ag_skills, ".agents/skills must match curated config/skills")

    def test_no_duplicate_skills_between_config_skills_and_installed_plugin(self):
        """Installed antigravity-swarm plugin must not duplicate skills already present in .gemini/config/skills (which causes 2x slash commands in Antigravity UI)."""
        import json

        cfg_skills = {d.name for d in self.cfg_dir.iterdir() if d.is_dir()}
        plugin_dir = self.home / ".gemini" / "config" / "plugins" / "antigravity-swarm"
        plugin_skills_dir = plugin_dir / "skills"
        plugin_skills = (
            {d.name for d in plugin_skills_dir.iterdir() if d.is_dir()}
            if plugin_skills_dir.is_dir()
            else set()
        )
        overlap = sorted(cfg_skills & plugin_skills)
        self.assertEqual(
            overlap,
            [],
            f"Duplicate skills found in both .gemini/config/skills and .gemini/config/plugins/antigravity-swarm/skills (causes 2x slash commands): {overlap}",
        )
        deployed_manifest = plugin_dir / "plugin.json"
        if deployed_manifest.is_file():
            manifest_data = json.loads(deployed_manifest.read_text(encoding="utf-8"))
            self.assertNotIn(
                "skills",
                manifest_data,
                "Deployed antigravity-swarm/plugin.json must not mount duplicate './skills' when global .gemini/config/skills is installed",
            )

    def test_core_and_multi_domain_coverage_preserved(self):
        """All 39 Swarm Coordinator/ASW/Obsidian skills and all 9 domain representatives must exist."""
        cfg_skills = {d.name for d in self.cfg_dir.iterdir() if d.is_dir()}
        missing_core = CORE_COORDINATOR_SKILLS - cfg_skills
        self.assertFalse(missing_core, f"Missing protected core skills: {missing_core}")
        missing_domains = REQUIRED_DOMAIN_REPRESENTATIVES - cfg_skills
        self.assertFalse(missing_domains, f"Missing multi-domain representatives: {missing_domains}")

    def test_frontmatter_no_bom_and_concise_descriptions(self):
        """Every curated SKILL.md must have zero UTF-8 BOM and a single-line description of 15..120 chars."""
        bom_files = []
        bad_desc = []
        for d in sorted(self.cfg_dir.iterdir()):
            if not d.is_dir():
                continue
            f = d / "SKILL.md"
            if not f.exists():
                bad_desc.append((d.name, "MISSING SKILL.md"))
                continue
            raw = f.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                bom_files.append(d.name)
            txt = raw.decode("utf-8", errors="replace")
            m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
            if not m:
                bad_desc.append((d.name, "NO_FRONTMATTER"))
                continue
            desc = None
            for line in m.group(1).splitlines():
                if line.strip().startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip("\"'")
                    break
            if not desc or desc in (">", "|", ">-", "|-") or not (15 <= len(desc) <= 120):
                bad_desc.append((d.name, f"len={len(desc) if desc else 0}: {desc!r}"))

        self.assertEqual(bom_files, [], f"Skills with UTF-8 BOM: {bom_files[:10]}")
        self.assertEqual(bad_desc, [], f"Skills with invalid/long descriptions: {bad_desc[:10]}")

    def test_repo_and_plugin_skills_frontmatter_rejects_invalid_and_edge(self):
        """Every SKILL.md in .antigravity/skills, plugins/antigravity-swarm/skills, and deployed plugin skills must have valid YAML frontmatter, and normalize_skill_frontmatter repairs missing/BOM frontmatter."""
        import importlib.util
        import tempfile

        repo_root = Path(__file__).resolve().parent.parent
        roots = [
            repo_root / "core_framework" / "skills",
            repo_root / ".antigravity" / "skills",
            repo_root / "plugins" / "antigravity-swarm" / "skills",
            self.home / ".gemini" / "config" / "plugins" / "antigravity-swarm" / "skills",
        ]
        invalid = []
        for root in roots:
            if not root.is_dir():
                continue
            for d in sorted(root.iterdir()):
                if not d.is_dir():
                    continue
                f = d / "SKILL.md"
                if not f.is_file():
                    continue
                raw = f.read_bytes()
                if raw.startswith(b"\xef\xbb\xbf"):
                    invalid.append(f"{f}: UTF-8 BOM")
                    continue
                txt = raw.decode("utf-8", errors="replace")
                m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
                if not m:
                    invalid.append(f"{f.relative_to(repo_root) if f.is_relative_to(repo_root) else f}: MISSING_FRONTMATTER")
                    continue
                fm_text = m.group(1)
                if f"name: {d.name}" not in fm_text:
                    invalid.append(f"{d.name}: missing name: {d.name}")
                desc = None
                for line in fm_text.splitlines():
                    if line.strip().startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip("\"'")
                        break
                if not desc or not (15 <= len(desc) <= 120):
                    invalid.append(f"{d.name}: invalid description ({desc!r})")
        self.assertEqual(invalid, [], "Found skills with invalid frontmatter:\n" + "\n".join(invalid[:25]))

        # Negative & edge-case verification: normalize_skill_frontmatter repairs missing frontmatter & BOM
        script_path = repo_root / ".antigravity" / "scripts" / "curate_skill_catalog.py"
        spec = importlib.util.spec_from_file_location("curate_skill_catalog", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            bad_skill_dir = Path(tmp) / "edge-broken-skill"
            bad_skill_dir.mkdir(parents=True, exist_ok=True)
            bad_md = bad_skill_dir / "SKILL.md"
            bad_md.write_bytes(b"\xef\xbb\xbf# Edge Broken Skill\n\nProvides specialized verification for edge-case skills.\n")
            self.assertFalse(bad_md.read_text(encoding="utf-8-sig").startswith("---"))
            mod.normalize_skill_frontmatter(
                bad_md,
                "edge-broken-skill",
                "Provides specialized verification for edge-case skills.",
            )
            repaired_raw = bad_md.read_bytes()
            self.assertFalse(repaired_raw.startswith(b"\xef\xbb\xbf"))
            repaired_txt = repaired_raw.decode("utf-8")
            self.assertTrue(repaired_txt.startswith("---\nname: edge-broken-skill\ndescription: "))

    def test_antigravity_plugin_root_hooks_md_agents_and_hydrogen_escalation_gate(self):
        """Verifies Antigravity native plugin root hooks.json, 8 subagent .md files, lastUserInput/workspacePaths hook parsing, and mandatory invoke_subagent escalation gate in /asw."""
        import json
        import subprocess
        import tempfile

        repo_root = Path(__file__).resolve().parent.parent
        plugin_src = repo_root / "plugins" / "antigravity-swarm"
        plugin_dst = self.home / ".gemini" / "config" / "plugins" / "antigravity-swarm"

        # 1. Root hooks.json must exist in both repo and installed plugin dir
        for p_dir in (plugin_src, plugin_dst):
            root_hooks = p_dir / "hooks.json"
            self.assertTrue(root_hooks.is_file(), f"Missing plugin root hooks.json at {root_hooks}")
            hooks_data = json.loads(root_hooks.read_text(encoding="utf-8"))
            self.assertIn("antigravity-swarm", hooks_data)
            self.assertIn("./scripts/asw-hook.mjs", json.dumps(hooks_data))
            self.assertIn("edit_file", json.dumps(hooks_data))

        # 2. All 8 native Antigravity subagent .md definitions must exist with subagent: true & mainAgent: false
        expected_agents = {
            "asw-planner.md",
            "asw-implementer.md",
            "asw-reviewer.md",
            "asw-opposition-reviewer.md",
            "asw-plan-audit.md",
            "asw-explorer.md",
            "asw-librarian.md",
            "asw-planning-analysis.md",
        }
        for p_dir in (plugin_src, plugin_dst):
            agents_dir = p_dir / "agents"
            present_md = {f.name for f in agents_dir.glob("*.md")}
            self.assertTrue(
                expected_agents.issubset(present_md),
                f"Missing Antigravity subagent .md files in {agents_dir}: {expected_agents - present_md}",
            )
            for md_name in expected_agents:
                md_txt = (agents_dir / md_name).read_text(encoding="utf-8")
                self.assertIn("subagent: true", md_txt, f"{md_name} missing subagent: true")
                self.assertIn("mainAgent: false", md_txt, f"{md_name} missing mainAgent: false")

        # 3. asw/SKILL.md must enforce mandatory invoke_subagent dispatch gate and forbid inline-only Hydrogen execution
        for asw_md in (
            plugin_src / "skills" / "asw" / "SKILL.md",
            self.cfg_dir / "asw" / "SKILL.md",
        ):
            txt = asw_md.read_text(encoding="utf-8")
            self.assertIn("invoke_subagent", txt)
            self.assertIn("asw-planner", txt)
            self.assertIn("asw-implementer", txt)
            self.assertIn("asw-reviewer", txt)
            self.assertNotIn("Keep dependent edits in the main thread", txt)

        # 4. asw-hook.mjs must parse Antigravity's native lastUserInput and skip invocationNum > 1
        hook_script = plugin_src / "scripts" / "asw-hook.mjs"
        res_turn1 = subprocess.run(
            ["node", str(hook_script)],
            input=json.dumps({
                "invocationNum": 1,
                "modelName": "gemini-4-hydrogen",
                "lastUserInput": "/asw implement new feature in edgerelay",
            }),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_turn1.returncode, 0)
        out_turn1 = json.loads(res_turn1.stdout)
        injected = out_turn1.get("injectSteps", [{}])[0].get("userMessage", "")
        self.assertIn("ASW LOOP MODE ENABLED!", injected)
        self.assertIn("MANDATORY SUBAGENT & MODEL-TIER ESCALATION GATE", injected)
        self.assertIn("invoke_subagent", injected)

        # Negative test: invocationNum > 1 within the same turn must return {} (no repeated spam)
        res_turn2 = subprocess.run(
            ["node", str(hook_script)],
            input=json.dumps({
                "invocationNum": 2,
                "modelName": "gemini-4-hydrogen",
                "lastUserInput": "/asw implement new feature in edgerelay",
            }),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_turn2.returncode, 0)
        self.assertEqual(json.loads(res_turn2.stdout), {})

        # 5. asw-stop-check.mjs must resolve workspacePaths[0] when cwd is the plugin directory
        stop_script = plugin_src / "scripts" / "asw-stop-check.mjs"
        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = Path(tmp)
            plans_dir = ws_dir / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "active.md").write_text(
                "# Plan\n- [x] Done step\n- [ ] Remaining task\n",
                encoding="utf-8",
            )
            res_stop = subprocess.run(
                ["node", str(stop_script)],
                cwd=str(plugin_src),
                input=json.dumps({
                    "fullyIdle": True,
                    "workspacePaths": [ws_dir.as_uri()],
                }),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res_stop.returncode, 0)
            stop_data = json.loads(res_stop.stdout)
            self.assertEqual(stop_data.get("decision"), "continue")
            self.assertIn("Remaining task", stop_data.get("reason", ""))

    def test_asw_rtk_rewrite_matrix_m1_to_m4(self):
        """Verifies asw-rtk-rewrite.mjs fulfills Matrix M1..M4 (git, pytest, Windows tree guard, compound commands)."""
        import json
        import subprocess

        repo_root = Path(__file__).resolve().parent.parent
        rewrite_script = repo_root / "plugins" / "antigravity-swarm" / "scripts" / "asw-rtk-rewrite.mjs"
        self.assertTrue(rewrite_script.is_file(), f"Missing {rewrite_script}")

        # Helper to invoke rewriteCommandToRtk via node eval
        def run_rewrite(cmd: str, is_win: bool) -> str:
            js = f"""
            import {{ rewriteCommandToRtk }} from "./plugins/antigravity-swarm/scripts/asw-rtk-rewrite.mjs";
            process.stdout.write(rewriteCommandToRtk({json.dumps(cmd)}, {str(is_win).lower()}));
            """
            proc = subprocess.run(
                ["node", "--input-type=module", "-e", js],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, f"Node error: {proc.stderr}")
            return proc.stdout

        # M1: git commands -> rtk git
        self.assertEqual(run_rewrite("git status", True), "rtk git status")
        self.assertEqual(run_rewrite("git log -n 30", True), "rtk git log -n 30")
        self.assertEqual(run_rewrite("git diff HEAD~2 HEAD", True), "rtk git diff HEAD~2 HEAD")
        # Idempotence: already rtk prefixed
        self.assertEqual(run_rewrite("rtk git status", True), "rtk git status")

        # M2: pytest commands -> rtk pytest
        self.assertEqual(run_rewrite("pytest tests/test_curation.py", True), "rtk pytest tests/test_curation.py")
        self.assertEqual(run_rewrite("python -m pytest tests/", True), "rtk pytest tests/")
        self.assertEqual(run_rewrite("python3 -m pytest tests/ -v", True), "rtk pytest tests/ -v")

        # M3: Windows tree guard (win32 must bypass rtk tree; POSIX rewrites)
        self.assertEqual(run_rewrite("tree", True), "tree")
        self.assertEqual(run_rewrite("tree /F", True), "tree /F")
        self.assertEqual(run_rewrite("tree", False), "rtk tree")
        self.assertEqual(run_rewrite("tree -L 2", False), "rtk tree -L 2")

        # M4: PowerShell compound commands with operators (;, &&, ||, |)
        self.assertEqual(
            run_rewrite("git status; pytest tests/ -v", True),
            "rtk git status; rtk pytest tests/ -v",
        )
        self.assertEqual(
            run_rewrite("git diff HEAD~1 && python -m pytest tests/", True),
            "rtk git diff HEAD~1 && rtk pytest tests/",
        )
        # Quoted operator preservation
        self.assertEqual(
            run_rewrite('git commit -m "fix; bug" && pytest', True),
            'rtk git commit -m "fix; bug" && rtk pytest',
        )

        # CLI invocation with argument
        cli_proc = subprocess.run(
            ["node", str(rewrite_script), "git status; pytest tests/ -v"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(cli_proc.returncode, 0)
        self.assertEqual(cli_proc.stdout.strip(), "rtk git status; rtk pytest tests/ -v")


if __name__ == "__main__":
    unittest.main()
