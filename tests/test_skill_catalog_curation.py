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
    "asw-start-work", "asw-test-gui", "asw-ui-ux", "rtk-token-killer", "context-hub", "obs-memory", "agent-memory", "agent-memory-mcp",
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
        """Global skill catalog must contain exactly 201 curated skills (strictly <= 215 budget)."""
        cfg_skills = {d.name for d in self.cfg_dir.iterdir() if d.is_dir()}
        self.assertEqual(
            len(cfg_skills),
            201,
            f"Expected exactly 201 curated skills in .gemini/config/skills, found {len(cfg_skills)}",
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
                "lastUserInput": "/asw implement new feature in acme_analytics",
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
                "lastUserInput": "/asw implement new feature in acme_analytics",
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

    def test_m1_cascading_hook_guard_session_start_and_ephemeral_channel_split(self):
        """Verifies M1: SessionStart systemMessage, synthetic ASW MODE cascade skip, TurnGuard & LSP ephemeralMessage, no PreToolUse, and malformed stdin fail-open."""
        import json
        import os
        import subprocess
        import sys
        import tempfile

        repo_root = Path(__file__).resolve().parent.parent
        plugin_src = repo_root / "plugins" / "antigravity-swarm"
        hook_script = plugin_src / "scripts" / "asw-hook.mjs"
        lsp_script = plugin_src / "scripts" / "asw-lsp-check.mjs"

        # 1. Both hooks.json files register SessionStart, PreInvocation, PostToolUse, Stop and NEVER PreToolUse
        for hooks_path in (plugin_src / "hooks.json", plugin_src / "hooks" / "hooks.json"):
            self.assertTrue(hooks_path.is_file(), f"Missing {hooks_path}")
            hooks_data = json.loads(hooks_path.read_text(encoding="utf-8"))
            swarm_hooks = hooks_data.get("antigravity-swarm", {})
            for required_event in ("SessionStart", "PreInvocation", "PostToolUse", "Stop"):
                self.assertIn(required_event, swarm_hooks, f"{hooks_path} missing {required_event}")
            self.assertNotIn("PreToolUse", swarm_hooks, f"{hooks_path} must NEVER register PreToolUse")
            self.assertIn("--event SessionStart", json.dumps(swarm_hooks["SessionStart"]))

        # 2. Fresh /asw-plan with omitted invocationNum and invocationNum=1 emits userMessage
        for inv in (None, 1):
            payload = {"lastUserInput": "/asw-plan integrate token economizer"}
            if inv is not None:
                payload["invocationNum"] = inv
            res = subprocess.run(
                ["node", str(hook_script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res.returncode, 0)
            out = json.loads(res.stdout)
            msg = out.get("injectSteps", [{}])[0].get("userMessage", "")
            self.assertIn("ASW PLAN MODE ENABLED!", msg)

        # 3. Cascading synthetic hook-injected prompt at invocationNum=1 must return {} (M1)
        for marker in (
            "ASW PLAN MODE ENABLED! (Model Tier: Gemini 4 Carbon High)",
            "ASW LOOP MODE ENABLED! /asw-plan follow-up",
            "ASW START-WORK MODE ENABLED!",
        ):
            res_dup = subprocess.run(
                ["node", str(hook_script)],
                input=json.dumps({
                    "invocationNum": 1,
                    "lastUserInput": marker,
                }),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res_dup.returncode, 0)
            self.assertEqual(json.loads(res_dup.stdout), {}, f"Synthetic marker must not re-inject: {marker}")

        # 4. Malformed / empty stdin JSON fails open with {} and exit code 0
        for bad_in in ("", "   ", "{not valid json"):
            res_bad = subprocess.run(
                ["node", str(hook_script)],
                input=bad_in,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(res_bad.returncode, 0)
            self.assertEqual(json.loads(res_bad.stdout), {})

        # 5. SessionStart emits KV-cached systemMessage from EnvFacts and honors ASW_TOKEN_ECONOMIZER_ENABLED=0
        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = Path(tmp) / "sample_ws"
            ws_dir.mkdir(parents=True)
            te_script = repo_root / ".antigravity" / "scripts" / "token_economizer.py"
            for idx in range(1, 4):
                tp = Path(tmp) / f"s{idx}.jsonl"
                rows = [
                    {"type": "PLANNER_RESPONSE", "step_index": 0, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 1, "text": "Command exited with code 127\n'pytest' is not recognized"},
                    {"type": "PLANNER_RESPONSE", "step_index": 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": 3, "text": "Command exited with code 0\n5 passed"},
                ]
                tp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
                fold_proc = subprocess.run(
                    [sys.executable, str(te_script), "--fold", str(tp), "--repo", str(ws_dir), "--json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(fold_proc.returncode, 0, fold_proc.stderr)

            ss_res = subprocess.run(
                ["node", str(hook_script), "--event", "SessionStart"],
                cwd=str(repo_root),
                input=json.dumps({"hookEventName": "SessionStart", "workspacePaths": [ws_dir.as_uri()]}),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(ss_res.returncode, 0, ss_res.stderr)
            ss_out = json.loads(ss_res.stdout)
            sys_step = ss_out.get("injectSteps", [{}])[0].get("systemMessage", {})
            sys_msg = sys_step.get("systemMessage", "") if isinstance(sys_step, dict) else sys_step
            self.assertIn("python -m pytest", sys_msg)

            env_off = dict(os.environ)
            env_off["ASW_TOKEN_ECONOMIZER_ENABLED"] = "0"
            ss_off = subprocess.run(
                ["node", str(hook_script), "--event", "SessionStart"],
                cwd=str(repo_root),
                input=json.dumps({"hookEventName": "SessionStart", "workspacePaths": [ws_dir.as_uri()]}),
                env=env_off,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(ss_off.returncode, 0)
            self.assertEqual(json.loads(ss_off.stdout), {})

            # 6. PreInvocation mid-turn TurnGuard emits ephemeralMessage on stagnant edit/test spiral
            spiral_path = Path(tmp) / "spiral.jsonl"
            spiral_rows = []
            step = 0
            for _ in range(7):
                spiral_rows.extend([
                    {"type": "PLANNER_RESPONSE", "step_index": step, "tool_calls": [{"name": "edit_file", "arguments": {"TargetFile": "app.py"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": step + 1, "text": "Edited app.py"},
                    {"type": "PLANNER_RESPONSE", "step_index": step + 2, "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}]},
                    {"type": "MODEL", "subtype": "GENERIC", "step_index": step + 3, "text": "Command exited with code 1\nAssertionError: invariant M3 failed"},
                ])
                step += 4
            spiral_path.write_text("\n".join(json.dumps(r) for r in spiral_rows) + "\n", encoding="utf-8")
            tg_res = subprocess.run(
                ["node", str(hook_script)],
                cwd=str(repo_root),
                input=json.dumps({
                    "invocationNum": 2,
                    "transcriptPath": str(spiral_path),
                    "workspacePaths": [ws_dir.as_uri()],
                }),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(tg_res.returncode, 0, tg_res.stderr)
            tg_out = json.loads(tg_res.stdout)
            eph_msg = tg_out.get("injectSteps", [{}])[0].get("ephemeralMessage", "")
            self.assertTrue(bool(eph_msg.strip()), f"Expected TurnGuard ephemeralMessage, got: {tg_out}")
            self.assertNotIn("userMessage", tg_out.get("injectSteps", [{}])[0])

            # 7. asw-lsp-check.mjs must emit ephemeralMessage (never userMessage) on syntax error
            bad_js = Path(tmp) / "broken.mjs"
            bad_js.write_text("const x = (;\n", encoding="utf-8")
            lsp_res = subprocess.run(
                ["node", str(lsp_script)],
                input=json.dumps({"toolCall": {"args": {"TargetFile": str(bad_js)}}}),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(lsp_res.returncode, 0)
            lsp_out = json.loads(lsp_res.stdout)
            lsp_step = lsp_out.get("injectSteps", [{}])[0]
            self.assertIn("ephemeralMessage", lsp_step, f"LSP check must emit ephemeralMessage, got: {lsp_out}")
            self.assertNotIn("userMessage", lsp_step)
            self.assertIn("Layer-1 Static Check FAILED", lsp_step["ephemeralMessage"])

    def test_m4_windows_rtk_find_guard_and_rules_docs(self):
        """Verifies M4: Windows win32 preserves native find while POSIX rewrites to rtk find, and rules/skill document it."""
        import json
        import subprocess

        repo_root = Path(__file__).resolve().parent.parent
        rewrite_script = repo_root / "plugins" / "antigravity-swarm" / "scripts" / "asw-rtk-rewrite.mjs"
        self.assertTrue(rewrite_script.is_file(), f"Missing {rewrite_script}")

        def run_rewrite(cmd: str, is_win: bool) -> str:
            js = f"""
            import {{ rewriteCommandToRtk }} from {json.dumps(rewrite_script.as_uri())};
            process.stdout.write(rewriteCommandToRtk({json.dumps(cmd)}, {str(is_win).lower()}));
            """
            proc = subprocess.run(
                ["node", "--input-type=module", "-e", js],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout

        # Windows preserves find and find.exe; POSIX rewrites find -> rtk find
        self.assertEqual(run_rewrite("find . -name '*.py'", True), "find . -name '*.py'")
        self.assertEqual(run_rewrite("find.exe . -name '*.py'", True), "find.exe . -name '*.py'")
        self.assertEqual(run_rewrite("find . -name '*.py'", False), "rtk find . -name '*.py'")
        self.assertEqual(run_rewrite("git status; find .", True), "rtk git status; find .")
        self.assertEqual(run_rewrite("git status; find .", False), "rtk git status; rtk find .")

        # Documentation & skill frontmatter check (supports both fresh git clone and deployed target repo)
        required_docs = [
            repo_root / ".antigravity" / "rules" / "antigravity-rtk-rules.md",
            repo_root / ".antigravity" / "skills" / "rtk-token-killer" / "SKILL.md",
        ]
        for optional_mirror in (
            repo_root / "core_framework" / "rules" / "antigravity-rtk-rules.md",
            repo_root / ".agents" / "rules" / "antigravity-rtk-rules.md",
            repo_root / "plugins" / "antigravity-swarm" / "skills" / "rtk-token-killer" / "SKILL.md",
        ):
            if optional_mirror.is_file():
                required_docs.append(optional_mirror)

        for doc_path in required_docs:
            raw = doc_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM found in {doc_path}")
            txt = raw.decode("utf-8")
            self.assertIn("rtk find", txt)
            self.assertIn("System32", txt)

    def test_context_hub_skill_and_chub_installer_contract(self):
        """Verifies M1, M2, M5: context-hub SKILL.md across all roots, BOM/length bounds, install.py --skip-chub & ~/.chub/config.yaml seeding, and workflow wiring."""
        import importlib.util
        import tempfile
        from unittest import mock

        repo_root = Path(__file__).resolve().parent.parent
        skill_paths = [
            repo_root / ".antigravity" / "skills" / "context-hub" / "SKILL.md",
            self.cfg_dir / "context-hub" / "SKILL.md",
            self.ide_dir / "context-hub" / "SKILL.md",
            self.ag_dir / "context-hub" / "SKILL.md",
        ]
        for sp in skill_paths:
            self.assertTrue(sp.is_file(), f"Missing context-hub SKILL.md at {sp}")
            raw = sp.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM found in {sp}")
            txt = raw.decode("utf-8")
            m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
            self.assertIsNotNone(m, f"Missing frontmatter in {sp}")
            desc = ""
            for line in m.group(1).splitlines():
                if line.strip().startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip("\"'")
                    break
            self.assertTrue(15 <= len(desc) <= 97, f"Invalid description length {len(desc)} in {sp}: {desc!r}")
            for marker in ("chub search", "chub get", "chub annotate", "CHUB_TELEMETRY=0", "CHUB_FEEDBACK=0", "--sync-chub-annotations", "untrusted"):
                self.assertIn(marker, txt, f"{sp} missing {marker}")

        # Zero duplicate in plugin skills
        plugin_chub = self.home / ".gemini" / "config" / "plugins" / "antigravity-swarm" / "skills" / "context-hub"
        self.assertFalse(plugin_chub.exists(), "context-hub must not duplicate into deployed plugin skills/")

        # Installer contract: ensure_chub_installed, --skip-chub, ~/.chub/config.yaml seeding & preservation
        install_py = repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_chub_mod", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "ensure_chub_installed"))

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            fake_home.mkdir(parents=True)

            # Seed ~/.chub/config.yaml when missing
            res = mod.run_install(
                repo_root=repo_root,
                home_dir=fake_home,
                skip_prompt=True,
                skip_plugin=True,
                skip_vault=True,
                skip_rtk=True,
                skip_chub=True,
            )
            self.assertIn("chub_installed", res)
            self.assertFalse(res["chub_installed"])
            self.assertTrue((fake_home / ".gemini" / "config" / "skills" / "context-hub" / "SKILL.md").is_file())
            self.assertTrue((fake_home / ".gemini" / "antigravity-ide" / "skills" / "context-hub" / "SKILL.md").is_file())
            self.assertTrue((fake_home / ".agents" / "skills" / "context-hub" / "SKILL.md").is_file())

            chub_cfg = fake_home / ".chub" / "config.yaml"
            self.assertTrue(chub_cfg.is_file(), "install.py must seed ~/.chub/config.yaml")
            cfg_txt = chub_cfg.read_text(encoding="utf-8")
            self.assertIn("telemetry: false", cfg_txt)
            self.assertIn("feedback: false", cfg_txt)

            # Preserve existing custom config.yaml
            custom_yaml = "telemetry: false\nfeedback: false\nsources:\n  - name: custom\n    path: /tmp/docs\n"
            chub_cfg.write_text(custom_yaml, encoding="utf-8")
            with mock.patch("shutil.which", return_value=None):
                missing_res = mod.ensure_chub_installed(home_dir=fake_home, attempt_install=False)
                self.assertFalse(missing_res["installed"])
            self.assertEqual(chub_cfg.read_text(encoding="utf-8"), custom_yaml)

        # M5 workflow adoption across skills, agents, and rules (supports both upstream clone and deployed repo)
        wiring_groups = [
            (
                repo_root / ".antigravity" / "skills" / "implementation-developer" / "SKILL.md",
                repo_root / "core_framework" / "skills" / "implementation-developer" / "SKILL.md",
                self.cfg_dir / "implementation-developer" / "SKILL.md",
            ),
            (
                repo_root / "skills" / "asw-loop" / "SKILL.md",
                repo_root / "core_framework" / "skills" / "asw-loop" / "SKILL.md",
                repo_root / "plugins" / "antigravity-swarm" / "skills" / "asw-loop" / "SKILL.md",
            ),
            (
                repo_root / ".antigravity" / "skills" / "swarm-coordinator" / "SKILL.md",
                repo_root / "core_framework" / "skills" / "swarm-coordinator" / "SKILL.md",
                repo_root / "skills" / "swarm-coordinator" / "SKILL.md",
            ),
            (
                repo_root / "core_framework" / "skills" / "obs-memory" / "SKILL.md",
                self.cfg_dir / "obs-memory" / "SKILL.md",
            ),
            (repo_root / ".antigravity" / "agents" / "asw-implementer.md",),
            (repo_root / "plugins" / "antigravity-swarm" / "agents" / "asw-implementer.md",),
            (repo_root / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md",),
            (
                repo_root / "GEMINI.md",
                repo_root / "global_entrypoint" / "GEMINI.md",
            ),
        ]
        for group in wiring_groups:
            existing = [p for p in group if p.is_file()]
            self.assertTrue(existing, f"Missing M5 wiring target among: {group}")
            for wt in existing:
                w_raw = wt.read_bytes()
                self.assertFalse(w_raw.startswith(b"\xef\xbb\xbf"), f"BOM found in {wt}")
                w_txt = w_raw.decode("utf-8")
                self.assertIn("chub search", w_txt, f"Missing chub search in {wt}")
                self.assertIn("chub get", w_txt, f"Missing chub get in {wt}")
                self.assertIn("chub annotate", w_txt, f"Missing chub annotate in {wt}")
                self.assertIn("--sync-chub-annotations", w_txt, f"Missing --sync-chub-annotations in {wt}")

    def test_m5_hooks_stop_guard_posttooluse_lsp_rtk_and_neon_statusline(self):
        """Verifies M5 & M4: hooks.json matcher/event, Stop cancel guard, PostToolUse .py staging->{} + PreInvocation consume, repoDir config, RTK 2>&1/PreToolUse/fail-open, and Neon G-N statusline."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        repo_root = Path(__file__).resolve().parent.parent
        plugin_src = repo_root / "plugins" / "antigravity-swarm"
        hook_script = plugin_src / "scripts" / "asw-hook.mjs"
        lsp_script = plugin_src / "scripts" / "asw-lsp-check.mjs"
        stop_script = plugin_src / "scripts" / "asw-stop-check.mjs"
        rtk_script = plugin_src / "scripts" / "asw-rtk-rewrite.mjs"
        status_script = plugin_src / "scripts" / "asw-statusline.mjs"

        # 1. hooks.json & hooks/hooks.json: no run_command in PostToolUse matcher, --event PostToolUse present, no PreToolUse
        for hooks_path in (plugin_src / "hooks.json", plugin_src / "hooks" / "hooks.json"):
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            swarm = data["antigravity-swarm"]
            self.assertNotIn("PreToolUse", swarm)
            post_entry = swarm["PostToolUse"][0]
            self.assertNotIn("run_command", post_entry["matcher"])
            self.assertIn("edit_file", post_entry["matcher"])
            self.assertIn("--event PostToolUse", post_entry["hooks"][0]["command"])

        # 2. asw-stop-check.mjs honors USER_CANCELED, ERROR, MAX_INVOCATIONS, and continuationActive=true
        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = Path(tmp)
            plans_dir = ws_dir / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "active.md").write_text("# Plan\n- [x] Step 1\n- [ ] Step 2\n", encoding="utf-8")

            for stop_payload in (
                {"cwd": str(ws_dir), "fullyIdle": True, "terminationReason": "USER_CANCELED"},
                {"cwd": str(ws_dir), "fullyIdle": True, "terminationReason": "ERROR"},
                {"cwd": str(ws_dir), "fullyIdle": True, "terminationReason": "MAX_INVOCATIONS"},
                {"cwd": str(ws_dir), "fullyIdle": True, "continuationActive": True},
            ):
                res = subprocess.run(
                    ["node", str(stop_script)],
                    input=json.dumps(stop_payload),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
                self.assertEqual(json.loads(res.stdout), {"decision": ""}, f"Failed guard for {stop_payload}")

            # 3. PostToolUse relative .py check stages .pending-lsp-diagnostic.json & outputs {}, then PreInvocation consumes & unlinks it
            bad_py = ws_dir / "broken_mod.py"
            bad_py.write_text("def broken(:\n    pass\n", encoding="utf-8")
            lsp_post = subprocess.run(
                ["node", str(lsp_script), "--event", "PostToolUse"],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws_dir.as_uri()],
                    "toolCall": {"args": {"TargetFile": "broken_mod.py"}},
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertEqual(json.loads(lsp_post.stdout), {})
            pending_file = ws_dir / ".asw" / ".pending-lsp-diagnostic.json"
            self.assertTrue(pending_file.is_file(), "PostToolUse must stage .pending-lsp-diagnostic.json")

            pre_res = subprocess.run(
                ["node", str(hook_script)],
                cwd=str(plugin_src),
                input=json.dumps({
                    "invocationNum": 2,
                    "workspacePaths": [ws_dir.as_uri()],
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            pre_out = json.loads(pre_res.stdout)
            eph = pre_out.get("injectSteps", [{}])[0].get("ephemeralMessage", "")
            self.assertIn("ASW POST-EDIT DIAGNOSTIC", eph)
            self.assertIn("broken_mod.py", eph)
            self.assertFalse(pending_file.exists(), "PreInvocation must unlink consumed diagnostic")

            # 4. asw-hook.mjs checks <repoDir>/.antigravity/decision_config.json before process.cwd() and uses Neon branding
            ag_dir = ws_dir / ".antigravity"
            ag_dir.mkdir(parents=True)
            (ag_dir / "decision_config.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
            hook_cfg_res = subprocess.run(
                ["node", str(hook_script)],
                cwd=str(repo_root),
                input=json.dumps({
                    "invocationNum": 1,
                    "autoDecisionRouter": True,
                    "workspacePaths": [ws_dir.as_uri()],
                    "lastUserInput": "Create a new dashboard widget and verify it",
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            # Because repoDir has decision_config.json enabled=false, autoDecisionRouter must NOT inject LOOP_DIRECTIVE
            self.assertEqual(json.loads(hook_cfg_res.stdout), {})

            hook_neon = subprocess.run(
                ["node", str(hook_script)],
                input=json.dumps({"invocationNum": 1, "lastUserInput": "/asw-review audit"}),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            review_msg = hook_neon.stdout
            self.assertIn("Gemini 4 Neon", review_msg)
            self.assertNotIn("Argon", review_msg)

        # 5. asw-rtk-rewrite.mjs preserves 2>&1 / &>, handles PreToolUse overwrite, and fails open without rtk
        cli_redir = subprocess.run(
            ["node", str(rtk_script), "pytest tests/ 2>&1 && git status"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(cli_redir.stdout.strip(), "rtk pytest tests/ 2>&1 && rtk git status")

        env_force = dict(os.environ, FORCE_RTK_REWRITE="1")
        pre_tool_ok = subprocess.run(
            ["node", str(rtk_script)],
            env=env_force,
            input=json.dumps({"toolCall": {"args": {"CommandLine": "git diff 2>&1"}}}),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(
            json.loads(pre_tool_ok.stdout),
            {"decision": "allow", "overwrite": {"CommandLine": "rtk git diff 2>&1"}},
        )

        node_bin = shutil.which("node") or "node"
        env_no_rtk = {k: v for k, v in os.environ.items() if k != "FORCE_RTK_REWRITE"}
        env_no_rtk["PATH"] = ""
        pre_tool_missing = subprocess.run(
            [node_bin, str(rtk_script)],
            env=env_no_rtk,
            input=json.dumps({"toolCall": {"args": {"CommandLine": "git status"}}}),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(json.loads(pre_tool_missing.stdout), {"decision": "allow"})

        fail_open_cmd = subprocess.run(
            [node_bin, str(rtk_script)],
            env=env_no_rtk,
            input=json.dumps({"command": "git status"}),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(json.loads(fail_open_cmd.stdout), {"command": "git status"})

        # 6. asw-statusline.mjs renders Neon -> G-N and compactQuotaModelName G-N(H)
        sl_res = subprocess.run(
            ["node", str(status_script)],
            env=dict(os.environ, FORCE_COLOR="0", NO_COLOR="1"),
            input=json.dumps({
                "model": {"display_name": "Gemini 4 Neon (High)"},
                "context_window": {"used_percentage": 25, "context_window_size": 1000000},
                "model_quota": [{"display_name": "Gemini 4 Neon (High)", "remaining_percentage": 80}],
            }),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        self.assertIn("G-N (High) 4", sl_res.stdout)
        self.assertIn("G-N(H)", sl_res.stdout)
        self.assertNotIn("G-A", sl_res.stdout)

    def test_m3_m4_stale_checkpoint_ttl_and_zero_artifact_lsp_sensor(self):
        """Verifies M3 (stale/completed/mismatched checkpoint & deferred-work/status filtering) and M4 (ast.parse zero-pycache + pending diagnostic unlink)."""
        import json
        import os
        import subprocess
        import tempfile
        import time

        repo_root = Path(__file__).resolve().parent.parent
        plugin_src = repo_root / "plugins" / "antigravity-swarm"
        stop_script = plugin_src / "scripts" / "asw-stop-check.mjs"
        lsp_script = plugin_src / "scripts" / "asw-lsp-check.mjs"
        hook_script = plugin_src / "scripts" / "asw-hook.mjs"

        def run_stop(ws_dir: Path) -> dict:
            res = subprocess.run(
                ["node", str(stop_script)],
                cwd=str(plugin_src),
                input=json.dumps({
                    "fullyIdle": True,
                    "workspacePaths": [ws_dir.as_uri()],
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return json.loads(res.stdout)

        # --- M3: Stale Checkpoint & Unapproved Plan Safety ---
        # Case A: Completed state.json + .stop-guard.json + new unapproved plan (0 [x], 2 [ ]) -> {"decision": ""}
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            sw_dir = ws / ".asw" / "start-work"
            plans_dir.mkdir(parents=True)
            sw_dir.mkdir(parents=True)
            (sw_dir / "state.json").write_text(
                json.dumps({"status": "ORCHESTRATION COMPLETE", "plan": ".asw/plans/old-plan.md"}),
                encoding="utf-8",
            )
            (sw_dir / ".stop-guard.json").write_text(
                json.dumps({"signature": "old-plan.md:1:1:0", "count": 1}),
                encoding="utf-8",
            )
            (plans_dir / "new-unapproved.md").write_text(
                "---\nstatus: ready-for-dev\n---\n# New Plan\n- [ ] Task A\n- [ ] Task B\n",
                encoding="utf-8",
            )
            out_a = run_stop(ws)
            self.assertEqual(out_a.get("decision"), "", f"Case A must not continue unapproved plan: {out_a}")

        # Case B: Expired (> 6h) state.json + 0 [x] plan -> {"decision": ""} and expired .stop-guard.json unlinked
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            sw_dir = ws / ".asw" / "start-work"
            plans_dir.mkdir(parents=True)
            sw_dir.mkdir(parents=True)
            state_file = sw_dir / "state.json"
            state_file.write_text(
                json.dumps({"status": "IN_PROGRESS", "plan": ".asw/plans/stale.md"}),
                encoding="utf-8",
            )
            guard_file = sw_dir / ".stop-guard.json"
            guard_file.write_text(
                json.dumps({"signature": "stale.md:0:2:0", "count": 1}),
                encoding="utf-8",
            )
            seven_hours_ago = time.time() - (7 * 60 * 60)
            os.utime(state_file, (seven_hours_ago, seven_hours_ago))
            os.utime(guard_file, (seven_hours_ago, seven_hours_ago))
            (plans_dir / "stale.md").write_text(
                "# Stale Plan\n- [ ] Step 1\n- [ ] Step 2\n",
                encoding="utf-8",
            )
            out_b = run_stop(ws)
            self.assertEqual(out_b.get("decision"), "", f"Case B expired state.json must not continue: {out_b}")
            self.assertFalse(guard_file.exists(), "Expired .stop-guard.json should be unlinked")

        # Case C: deferred-work.md and status: done / status: deferred plans ignored
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "deferred-work.md").write_text(
                "# Deferred Work\n- [x] Old\n- [ ] Future item\n",
                encoding="utf-8",
            )
            out_c1 = run_stop(ws)
            self.assertEqual(out_c1.get("decision"), "", f"Case C1 deferred-work.md must be ignored: {out_c1}")

            (plans_dir / "finished.md").write_text(
                "---\nstatus: done\n---\n# Finished\n- [x] Done step\n- [ ] Leftover checkbox\n",
                encoding="utf-8",
            )
            out_c2 = run_stop(ws)
            self.assertEqual(out_c2.get("decision"), "", f"Case C2 status: done must be ignored: {out_c2}")

            (plans_dir / "postponed.md").write_text(
                "---\nstatus: deferred\n---\n# Postponed\n- [x] Done step\n- [ ] Later item\n",
                encoding="utf-8",
            )
            out_c3 = run_stop(ws)
            self.assertEqual(out_c3.get("decision"), "", f"Case C3 status: deferred must be ignored: {out_c3}")

        # Case D: Positive active in-progress plan (via fresh state.json and via 1 [x] / 1 [ ] without state.json)
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            sw_dir = ws / ".asw" / "start-work"
            plans_dir.mkdir(parents=True)
            sw_dir.mkdir(parents=True)
            (sw_dir / "state.json").write_text(
                json.dumps({"status": "IN_PROGRESS", "plan": ".asw/plans/active.md"}),
                encoding="utf-8",
            )
            (plans_dir / "active.md").write_text(
                "# Active Plan\n- [ ] Task 1\n- [ ] Task 2\n",
                encoding="utf-8",
            )
            out_d1 = run_stop(ws)
            self.assertEqual(out_d1.get("decision"), "continue", f"Case D1 active state.json must continue: {out_d1}")

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "in_flight.md").write_text(
                "# In Flight\n- [x] Step 1\n- [ ] Step 2\n",
                encoding="utf-8",
            )
            out_d2 = run_stop(ws)
            self.assertEqual(out_d2.get("decision"), "continue", f"Case D2 checked-item plan must continue: {out_d2}")

        # --- M4: Zero-Artifact ast.parse & Pending Diagnostic Unlink ---
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            target_py = ws / "sensor_mod.py"
            pending_file = ws / ".asw" / ".pending-lsp-diagnostic.json"

            # 1. Broken .py edit (PostToolUse) -> stages .pending-lsp-diagnostic.json, creates ZERO __pycache__ or .pyc
            target_py.write_text("def broken_fn(:\n    return 1\n", encoding="utf-8")
            post_bad = subprocess.run(
                ["node", str(lsp_script), "--event", "PostToolUse"],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws.as_uri()],
                    "toolCall": {"args": {"TargetFile": "sensor_mod.py"}},
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertEqual(json.loads(post_bad.stdout), {})
            self.assertTrue(pending_file.is_file(), "Broken .py edit must stage .pending-lsp-diagnostic.json")
            self.assertEqual(list(ws.rglob("__pycache__")), [], "ast.parse must create zero __pycache__ dirs")
            self.assertEqual(list(ws.rglob("*.pyc")), [], "ast.parse must create zero .pyc files")

            # 2. Valid .py edit (PostToolUse) on same file -> zero __pycache__/.pyc AND immediately unlinks .pending-lsp-diagnostic.json
            target_py.write_text("def fixed_fn():\n    return 42\n", encoding="utf-8")
            post_good = subprocess.run(
                ["node", str(lsp_script), "--event", "PostToolUse"],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws.as_uri()],
                    "toolCall": {"args": {"TargetFile": "sensor_mod.py"}},
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertEqual(json.loads(post_good.stdout), {})
            self.assertFalse(pending_file.exists(), "Valid .py edit must unlink .pending-lsp-diagnostic.json")
            self.assertEqual(list(ws.rglob("__pycache__")), [], "Valid edit must create zero __pycache__ dirs")
            self.assertEqual(list(ws.rglob("*.pyc")), [], "Valid edit must create zero .pyc files")

            # Confirm asw-hook.mjs does not inject stale error on next turn
            hook_res = subprocess.run(
                ["node", str(hook_script)],
                cwd=str(plugin_src),
                input=json.dumps({"invocationNum": 2, "workspacePaths": [ws.as_uri()]}),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertEqual(json.loads(hook_res.stdout), {})

            # 3. Standalone CLI mode (without --event PostToolUse) on broken .py file still returns injectSteps
            target_py.write_text("def cli_broken(:\n    pass\n", encoding="utf-8")
            cli_bad = subprocess.run(
                ["node", str(lsp_script)],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws.as_uri()],
                    "toolCall": {"args": {"TargetFile": "sensor_mod.py"}},
                }),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            cli_out = json.loads(cli_bad.stdout)
            eph = cli_out.get("injectSteps", [{}])[0].get("ephemeralMessage", "")
            self.assertIn("ASW POST-EDIT DIAGNOSTIC", eph)
            self.assertEqual(list(ws.rglob("__pycache__")), [])
            self.assertEqual(list(ws.rglob("*.pyc")), [])

        # --- Patch 2: Expired terminal state.json, BOM + YAML comment status, non-canonical LSP path ---
        # 2a. Expired (>6h) terminal state.json must NOT block freshly edited active plan
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            sw_dir = ws / ".asw" / "start-work"
            plans_dir.mkdir(parents=True)
            sw_dir.mkdir(parents=True)
            state_file = sw_dir / "state.json"
            state_file.write_text(
                json.dumps({"status": "ORCHESTRATION COMPLETE", "plan": ".asw/plans/fresh-plan.md"}),
                encoding="utf-8",
            )
            seven_hours_ago = time.time() - (7 * 60 * 60)
            os.utime(state_file, (seven_hours_ago, seven_hours_ago))
            (plans_dir / "fresh-plan.md").write_text(
                "---\nstatus: in-progress\n---\n# Fresh Plan\n- [x] Step 1\n- [ ] Step 2\n",
                encoding="utf-8",
            )
            out_exp_term = run_stop(ws)
            self.assertEqual(out_exp_term.get("decision"), "continue", f"Expired terminal state.json must not block active plan: {out_exp_term}")

        # 2b. UTF-8 BOM + inline YAML comment on status: done # finished must be ignored
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plans_dir = ws / ".asw" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "bom-comment-done.md").write_bytes(
                b"\xef\xbb\xbf---\nstatus: done # finished\n---\n# Done Plan\n- [x] Step 1\n- [ ] Leftover\n"
            )
            out_bom = run_stop(ws)
            self.assertEqual(out_bom.get("decision"), "", f"BOM + commented status: done must be ignored: {out_bom}")

        # 2c. Non-canonical absolute path (/.../sub/../sub/a.py) unlinks .pending-lsp-diagnostic.json cleanly
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            sub_dir = ws / "sub"
            sub_dir.mkdir(parents=True)
            real_py = sub_dir / "a.py"
            non_canonical_path = f"{ws}/sub/../sub/a.py"
            pending_file = ws / ".asw" / ".pending-lsp-diagnostic.json"

            real_py.write_text("def broken(:\n    pass\n", encoding="utf-8")
            subprocess.run(
                ["node", str(lsp_script), "--event", "PostToolUse"],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws.as_uri()],
                    "toolCall": {"args": {"TargetFile": str(real_py)}},
                }),
                capture_output=True, text=True, timeout=10, check=True,
            )
            self.assertTrue(pending_file.is_file())

            real_py.write_text("def ok():\n    return 1\n", encoding="utf-8")
            subprocess.run(
                ["node", str(lsp_script), "--event", "PostToolUse"],
                cwd=str(plugin_src),
                input=json.dumps({
                    "workspacePaths": [ws.as_uri()],
                    "toolCall": {"args": {"TargetFile": non_canonical_path}},
                }),
                capture_output=True, text=True, timeout=10, check=True,
            )
            self.assertFalse(pending_file.exists(), "Non-canonical absolute path must still unlink .pending-lsp-diagnostic.json")


if __name__ == "__main__":
    unittest.main()
