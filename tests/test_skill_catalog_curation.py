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


if __name__ == "__main__":
    unittest.main()
