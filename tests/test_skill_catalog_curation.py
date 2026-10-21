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
    "asw-start-work", "asw-test-gui", "asw-ui-ux", "obs-memory", "agent-memory", "agent-memory-mcp",
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


if __name__ == "__main__":
    unittest.main()
