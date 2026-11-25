import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_SCRIPTS = (REPO_ROOT / "core_framework" / "scripts") if (REPO_ROOT / "core_framework" / "scripts").exists() else (REPO_ROOT / ".antigravity" / "scripts")
AG_SCRIPTS = REPO_ROOT / ".antigravity" / "scripts"

for p in (str(CORE_SCRIPTS), str(AG_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import decision_router


class TestDecisionRouter(unittest.TestCase):
    def setUp(self):
        self.router = decision_router.DecisionRouter()

    # --- M6: VRAM-Aware GPU vs CPU Hardware Selection ---
    def test_m6_select_optimal_device_gtx1060_and_rtx4090(self):
        # 1. NVIDIA GeForce GTX 1060 3GB (Pascal compute 6.1, ~607 MiB free, 3072 total)
        gtx1060_csv = "NVIDIA GeForce GTX 1060 3GB, 3072, 607, 6.1\n"
        dev_gtx = decision_router.select_optimal_device(nvidia_smi_output=gtx1060_csv)
        self.assertEqual(dev_gtx["device"], "cpu")
        self.assertEqual(dev_gtx["max_loaded"], 1)
        self.assertIn("insufficient_vram_or_pascal_fp16", dev_gtx["reason"])
        self.assertEqual(dev_gtx["total_vram_mib"], 3072)
        self.assertEqual(dev_gtx["free_vram_mib"], 607)
        self.assertEqual(dev_gtx["compute_cap"], 6.1)

        # 2. NVIDIA GeForce RTX 4090 24GB (Ada Lovelace compute 8.9, 21800 free, 24564 total)
        rtx4090_csv = "NVIDIA GeForce RTX 4090, 24564, 21800, 8.9\n"
        dev_rtx = decision_router.select_optimal_device(nvidia_smi_output=rtx4090_csv)
        self.assertEqual(dev_rtx["device"], "cuda")
        self.assertEqual(dev_rtx["reason"], "sufficient_vram")
        self.assertEqual(dev_rtx["total_vram_mib"], 24564)
        self.assertEqual(dev_rtx["free_vram_mib"], 21800)
        self.assertEqual(dev_rtx["compute_cap"], 8.9)

        # 3. Live host test (on current machine with GTX 1060 3GB)
        live_dev = decision_router.select_optimal_device()
        self.assertIn(live_dev["device"], ("cpu", "cuda"))
        if live_dev.get("gpu_name") and "1060" in str(live_dev.get("gpu_name")):
            self.assertEqual(live_dev["device"], "cpu", "GTX 1060 3GB must be routed to CPU")

        # 4. Error/missing nvidia-smi fallback (non-Darwin host)
        with mock.patch("platform.system", return_value="Linux"), mock.patch("subprocess.run", side_effect=FileNotFoundError):
            fallback_dev = decision_router.select_optimal_device()
            self.assertEqual(fallback_dev["device"], "cpu")
            self.assertEqual(fallback_dev["max_loaded"], 1)
            self.assertIn("no_cuda_or_smi_failed", fallback_dev["reason"])

    # --- M1: Explicit Slash Command Overrides ---
    def test_m1_explicit_slash_command_override(self):
        # /asw-plan
        res_plan = self.router.route_prompt("/asw-plan implement new feature")
        self.assertEqual(res_plan["answer_confidence"], 1.0)
        self.assertEqual(res_plan["execution_mode"], "mode_3")
        self.assertEqual(res_plan["recommended_tier"], "carbon_plan_research")
        self.assertTrue(res_plan["requires_subagent_plan_wave"])

        # /asw-test-gui
        res_gui = self.router.route_prompt("/asw-test-gui verify dashboard in browser")
        self.assertEqual(res_gui["answer_confidence"], 1.0)
        self.assertTrue(res_gui["requires_gui_verification"])

        # /asw-start-work
        res_start = self.router.route_prompt("/asw-start-work laya_decision_model_integration_plan")
        self.assertEqual(res_start["answer_confidence"], 1.0)
        self.assertTrue(res_start["requires_subagent_plan_wave"])

        # /asw-review
        res_rev = self.router.route_prompt("/asw-review audit diff")
        self.assertEqual(res_rev["answer_confidence"], 1.0)
        self.assertEqual(res_rev["recommended_tier"], "neon_qa_review")

        # Negative case: file path containing /asw/ must NOT trigger slash command override
        res_path = self.router.route_prompt("inspect file plugins/asw/test.py and tell me what it does")
        self.assertNotEqual(res_path["answer_confidence"], 1.0)
        self.assertEqual(res_path["execution_mode"], "mode_1")

    # --- M2: Implicit Multi-Step / UI Feature Prompts (CZ/EN) ---
    def test_m2_implicit_multi_step_and_ui_cz_en(self):
        # Czech complex UI prompt
        cz_prompt = "Uprav výpočet marže v acme_analytics, přidej graf na dashboard a otestuj UI"
        cz_res = self.router.route_prompt(cz_prompt)
        self.assertEqual(cz_res["execution_mode"], "mode_3")
        self.assertEqual(cz_res["recommended_tier"], "carbon_plan_research")
        self.assertTrue(cz_res["requires_gui_verification"])
        self.assertTrue(cz_res["requires_subagent_plan_wave"])
        self.assertGreaterEqual(cz_res["noul"], 0.75)

        # English complex UI prompt
        en_prompt = "Build an analytics dashboard with interactive charts and verify UI with Playwright"
        en_res = self.router.route_prompt(en_prompt)
        self.assertEqual(en_res["execution_mode"], "mode_3")
        self.assertEqual(en_res["recommended_tier"], "carbon_plan_research")
        self.assertTrue(en_res["requires_gui_verification"])
        self.assertTrue(en_res["requires_subagent_plan_wave"])
        self.assertGreaterEqual(en_res["noul"], 0.75)

        # Read-only question (Czech)
        cz_q = "Co dělá tato funkce?"
        cz_q_res = self.router.route_prompt(cz_q)
        self.assertEqual(cz_q_res["execution_mode"], "mode_1")
        self.assertFalse(cz_q_res["requires_subagent_plan_wave"])
        self.assertFalse(cz_q_res["requires_gui_verification"])
        self.assertLess(cz_q_res["noul"], 0.40)

        # Read-only question (English)
        en_q = "Explain how the memory manager indexes projects"
        en_q_res = self.router.route_prompt(en_q)
        self.assertEqual(en_q_res["execution_mode"], "mode_1")
        self.assertFalse(en_q_res["requires_subagent_plan_wave"])

    # --- M3: Bounded Skill Routing (<= 8 skills) ---
    def test_m3_bounded_skill_routing(self):
        prompt = "Create a FastAPI backend with Playwright browser testing and quantitative risk metrics"
        skills = self.router.select_skills(prompt, max_skills=8)
        self.assertIsInstance(skills, list)
        self.assertGreaterEqual(len(skills), 1)
        self.assertLessEqual(len(skills), 8)
        self.assertTrue(any("fastapi" in s or "playwright" in s or "quant" in s for s in skills))

        # Edge case: empty or gibberish input returns core fallback skills (<= 4 items)
        empty_skills = self.router.select_skills("", max_skills=8)
        self.assertIsInstance(empty_skills, list)
        self.assertGreaterEqual(len(empty_skills), 1)
        self.assertLessEqual(len(empty_skills), 4)
        self.assertIn("swarm-coordinator", empty_skills)

    # --- M4: Review Finding Triage & Malformed Input Handling ---
    def test_m4_review_finding_triage_and_malformed_cli(self):
        # Broken caller / missing symbol finding -> [patch] or [bad_plan] with score >= 4
        defect = "Deleted function calculate_hash is still called in worker.py, causing AttributeError"
        triage_defect = self.router.triage_finding(defect)
        self.assertIn(triage_defect["route"], ("[patch]", "[bad_plan]"))
        self.assertGreaterEqual(triage_defect["severity_score"], 4)

        # Minor out-of-scope note -> [defer]
        minor = "Minor typography inconsistency in README.md footer; consider fixing in future docs pass"
        triage_minor = self.router.triage_finding(minor)
        self.assertEqual(triage_minor["route"], "[defer]")
        self.assertLessEqual(triage_minor["severity_score"], 2)

        # CLI Malformed JSON test (exit code 1 with structured JSON error)
        script_path = CORE_SCRIPTS / "decision_router.py"
        proc = subprocess.run(
            [sys.executable, str(script_path), "--mode", "predict", "--json", "{invalid_json_here"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        err_data = json.loads(proc.stdout or proc.stderr)
        self.assertIn("error", err_data)
        self.assertEqual(err_data.get("exit_code"), 1)

    # --- M5: Preflight Discovery & Resilience ---
    def test_m5_preflight_discovery_and_resilience(self):
        info = self.router.preflight()
        self.assertIn("device_info", info)
        self.assertIn("laya_sdk_installed", info)
        self.assertIn("laya_server_reachable", info)
        self.assertIn("active_backend", info)
        self.assertIn(info["active_backend"], ("laya_daemon", "laya_inproc", "system1_calibrated_fallback"))

    # --- M7: Configurable Enable/Disable Toggle for Low-RAM / Slow PCs & Negative Isolation ---
    def test_m7_configurable_enable_disable_toggle_and_isolation(self):
        # 1. Config loading with env override ASW_DECISION_MODEL_ENABLED=0
        with mock.patch.dict("os.environ", {"ASW_DECISION_MODEL_ENABLED": "0"}):
            cfg = decision_router.load_decision_config()
            self.assertFalse(cfg["enabled"])
            disabled_router = decision_router.DecisionRouter()
            self.assertFalse(disabled_router.enabled)
            self.assertEqual(disabled_router.device_info["device"], "disabled")

            # Route prompt returns disabled short-circuit
            route_res = disabled_router.route_prompt("Uprav marži na dashboardu a otestuj UI")
            self.assertFalse(route_res["enabled"])
            self.assertEqual(route_res["status"], "disabled")
            self.assertEqual(route_res["backend"], "disabled")
            self.assertFalse(route_res["requires_gui_verification"])
            self.assertFalse(route_res["requires_subagent_plan_wave"])
            self.assertEqual(route_res["selected_skills"], [])

            # select_skills returns empty list
            self.assertEqual(disabled_router.select_skills("fastapi playwright quant"), [])

            # triage_finding returns disabled
            triage_res = disabled_router.triage_finding("Critical crash in worker")
            self.assertFalse(triage_res["enabled"])
            self.assertEqual(triage_res["status"], "disabled")

            # preflight returns disabled
            pre_res = disabled_router.preflight()
            self.assertFalse(pre_res["enabled"])
            self.assertEqual(pre_res["status"], "disabled")

        # 2. CLI --disable and --enable flags (restore original configs in finally)
        script_path = CORE_SCRIPTS / "decision_router.py"
        cfg_targets = [
            REPO_ROOT / ".antigravity" / "decision_config.json",
            Path.home() / ".gemini" / "decision_config.json",
        ]
        saved_cfgs = {cp: cp.read_text(encoding="utf-8") for cp in cfg_targets if cp.is_file()}
        try:
            proc_disable = subprocess.run(
                [sys.executable, str(script_path), "--disable"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_disable.returncode, 0)
            data_disable = json.loads(proc_disable.stdout)
            self.assertFalse(data_disable["enabled"])
            self.assertEqual(data_disable["status"], "disabled")

            # Re-enable via CLI --enable
            proc_enable = subprocess.run(
                [sys.executable, str(script_path), "--enable"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_enable.returncode, 0)
            data_enable = json.loads(proc_enable.stdout)
            self.assertTrue(data_enable["enabled"])
            self.assertEqual(data_enable["status"], "enabled")
        finally:
            for cp, orig_txt in saved_cfgs.items():
                cp.write_text(orig_txt, encoding="utf-8")

    # --- Task 2: Deterministic Compact Prefix Serialization (M5) ---
    def test_compact_deterministic_serialization_hash_parity(self):
        """M5: --compact outputs single-line deterministic JSON omitting volatile free_vram_mib for KV-cache stability."""
        import hashlib
        script_path = CORE_SCRIPTS / "decision_router.py"
        prompt = "Uprav výpočet marže v acme_analytics a otestuj dashboard v prohlížeči"

        # Run 1
        p1 = subprocess.run(
            [sys.executable, str(script_path), "--mode", "route-prompt", "--compact", "--text", prompt],
            capture_output=True,
            text=True,
            check=True,
        )
        out1 = p1.stdout.strip()

        # Run 2
        p2 = subprocess.run(
            [sys.executable, str(script_path), "--mode", "route-prompt", "--compact", "--text", prompt],
            capture_output=True,
            text=True,
            check=True,
        )
        out2 = p2.stdout.strip()

        # 1. Single-line check
        self.assertNotIn("\n", out1, "--compact must produce single-line JSON")

        # 2. free_vram_mib must be omitted from device_info in compact mode
        data1 = json.loads(out1)
        self.assertNotIn("free_vram_mib", data1.get("device_info", {}), "Volatile free_vram_mib must be omitted in compact mode")

        # 3. Exact deterministic hash parity
        hash1 = hashlib.sha256(out1.encode("utf-8")).hexdigest()
        hash2 = hashlib.sha256(out2.encode("utf-8")).hexdigest()
        self.assertEqual(hash1, hash2, "Repeated compact calls must produce identical SHA-256 string for KV-cache stability")

    # --- Task 2: Lesson Scope Classification ---
    def test_classify_lesson_scope_router_and_cli(self):
        """classify_lesson_scope accurately distinguishes project-scoped vs universal lessons."""
        # 1. Method test
        project_cue = "When updating services/control_plane/api_admin_v1.py in acme_analytics"
        project_rule = "Never blindly replace .timestamp in acme_analytics admin events"
        res_proj = self.router.classify_lesson_scope(project_cue, project_rule, project="acme_analytics")
        self.assertEqual(res_proj["scope"], "project")

        universal_cue = "When reading text files across platforms in Python"
        universal_rule = "Always pass encoding='utf-8' and errors='replace' to read_text"
        res_univ = self.router.classify_lesson_scope(universal_cue, universal_rule, project=None)
        self.assertEqual(res_univ["scope"], "global")

        # 2. CLI --mode classify-scope
        script_path = CORE_SCRIPTS / "decision_router.py"
        p_cli = subprocess.run(
            [
                sys.executable, str(script_path), "--mode", "classify-scope",
                "--cue", project_cue, "--rule", project_rule, "--project", "acme_analytics",
                "--compact",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data_cli = json.loads(p_cli.stdout)
        self.assertEqual(data_cli["scope"], "project")

    # --- Task 2: Mode-Sliced Rules (M4) ---
    def test_slice_rules_mode_and_gui_triggers(self):
        """M4: slice_rules extracts < 6,500 bytes (>85% reduction) of targeted rules."""
        import memory_manager
        rules_path = (REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md") if (REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md").exists() else (REPO_ROOT / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md")
        full_size = rules_path.stat().st_size

        # 1. Mode 2 slice
        sliced_mode2 = memory_manager.slice_rules(mode="mode_2", rules_path=rules_path)
        sliced_bytes = len(sliced_mode2.encode("utf-8"))

        self.assertLess(sliced_bytes, 6500, f"Sliced rules size {sliced_bytes} exceeds 6,500 B target")
        self.assertIn("Mode 2 — Small Controlled Change", sliced_mode2)
        self.assertNotIn("Mode 5 — Long-Horizon Program", sliced_mode2)
        reduction = (1.0 - sliced_bytes / full_size) * 100.0
        self.assertGreater(reduction, 85.0, f"Reduction {reduction:.1f}% must be > 85%")

        # 2. UI / GUI prompt trigger
        sliced_gui = memory_manager.slice_rules(prompt="Fix dashboard UI chart with Playwright", rules_path=rules_path)
        self.assertIn("UI / UX Validation Trigger", sliced_gui)

    # --- Task 2: Negative & Boundary Tests for Slicing and Compact Router ---
    def test_slice_rules_and_compact_negative_and_boundary_cases(self):
        """Negative and boundary coverage: invalid mode, empty cues, and unroutable inputs."""
        import memory_manager
        rules_path = (REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md") if (REPO_ROOT / "core_framework" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md").exists() else (REPO_ROOT / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md")

        # Boundary: unknown/invalid mode falls back safely to general rules without crashing
        fallback_slice = memory_manager.slice_rules(mode="invalid_mode_99", rules_path=rules_path)
        self.assertNotEqual(len(fallback_slice), 0, "Fallback slice for invalid mode must not be empty")
        self.assertIn("Core Operating Principles", fallback_slice, "Fallback slice must retain core operating invariants")
        self.assertFalse("Mode 99" in fallback_slice, "Non-existent mode must not appear in output")

        # Boundary: empty cue and rule defaults to global scope
        empty_res = self.router.classify_lesson_scope("", "")
        self.assertEqual(empty_res["scope"], "global")
        self.assertFalse(empty_res["scope"] == "project", "Empty cue/rule must not be project specific")

        # Negative: CLI with missing required fields in classify-scope exits non-zero or handles gracefully
        script_path = CORE_SCRIPTS / "decision_router.py"
        p_err = subprocess.run(
            [sys.executable, str(script_path), "--mode", "classify-scope", "--cue", ""],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p_err.returncode, 0)
        out_err = json.loads(p_err.stdout)
        self.assertEqual(out_err["scope"], "global")

    # --- Task 2 (TokenEconomizer M3): Local Laya Stuck-Loop Judge ---
    def test_judge_loop_stagnant_vs_productive_and_ambiguous(self):
        """M3: judge_loop_digest catches stagnant recurring-hash loops, spares productive changing failures, and returns None on early/mixed traces."""
        stagnant_digest = (
            "turns=22 edit_churn=5 distinct_edit_files=1 error_outputs=7 "
            "test_runs=6 repeated_identical_failures=5 stagnation=0.71 "
            "repo_context=1.18\n[err#deadbeef] AssertionError\n[err#deadbeef] AssertionError"
        )
        res_stuck = self.router.judge_loop_digest(stagnant_digest)
        self.assertTrue(res_stuck["enabled"])
        self.assertIs(res_stuck["stuck"], True)
        self.assertGreaterEqual(res_stuck["confidence"], 0.72)
        self.assertLessEqual(res_stuck["confidence"], 0.96)
        self.assertEqual(res_stuck["reason"], "stagnant_repeated_failure_loop")
        self.assertIn("device_info", res_stuck)

        # Productive multi-file grind (stagnation == 0.0 / repeated_identical_failures == 0)
        productive_digest = (
            "turns=18 edit_churn=6 distinct_edit_files=5 error_outputs=6 "
            "test_runs=5 repeated_identical_failures=0 stagnation=0.0 "
            "[err#1111aaaa] [err#2222bbbb] [err#3333cccc]"
        )
        res_prod = self.router.judge_loop_digest(productive_digest)
        self.assertIs(res_prod["stuck"], False)
        self.assertGreaterEqual(res_prod["confidence"], 0.80)
        self.assertEqual(res_prod["reason"], "productive_changing_failures")

        # Early / borderline trace -> stuck is None, confidence < 0.70
        early_digest = (
            "turns=5 edit_churn=2 distinct_edit_files=1 error_outputs=2 "
            "repeated_identical_failures=1 stagnation=0.25"
        )
        res_early = self.router.judge_loop_digest(early_digest)
        self.assertIsNone(res_early["stuck"])
        self.assertLess(res_early["confidence"], 0.70)
        self.assertEqual(res_early["reason"], "ambiguous_early_or_mixed")

    def test_judge_loop_cli_compact_parity_and_disabled_isolation(self):
        """M3 + Negative Isolation: --mode judge-loop --compact is SHA-256 deterministic and ASW_DECISION_MODEL_ENABLED=0 short-circuits."""
        import hashlib
        import os

        script_path = CORE_SCRIPTS / "decision_router.py"
        digest = "turns=22 edit_churn=5 distinct_edit_files=1 error_outputs=7 repeated_identical_failures=5 stagnation=0.71"

        p1 = subprocess.run(
            [sys.executable, str(script_path), "--mode", "judge-loop", "--compact", "--text", digest],
            capture_output=True,
            text=True,
            check=True,
        )
        p2 = subprocess.run(
            [sys.executable, str(script_path), "--mode", "judge-loop", "--compact", "--text", digest],
            capture_output=True,
            text=True,
            check=True,
        )
        out1 = p1.stdout.strip()
        out2 = p2.stdout.strip()
        self.assertNotIn("\n", out1)
        data1 = json.loads(out1)
        self.assertIs(data1["stuck"], True)
        self.assertGreaterEqual(data1["confidence"], 0.70)
        self.assertNotIn("free_vram_mib", data1.get("device_info", {}))
        self.assertEqual(
            hashlib.sha256(out1.encode("utf-8")).hexdigest(),
            hashlib.sha256(out2.encode("utf-8")).hexdigest(),
        )

        # Negative isolation: ASW_DECISION_MODEL_ENABLED=0
        with mock.patch.dict(os.environ, {"ASW_DECISION_MODEL_ENABLED": "0"}):
            disabled_router = decision_router.DecisionRouter()
            res_dis = disabled_router.judge_loop_digest(digest)
            self.assertEqual(
                res_dis,
                {
                    "enabled": False,
                    "status": "disabled",
                    "backend": "disabled",
                    "stuck": None,
                    "confidence": 0.0,
                    "reason": "decision_model_disabled",
                },
            )

        env_off = os.environ.copy()
        env_off["ASW_DECISION_MODEL_ENABLED"] = "0"
        p_off = subprocess.run(
            [sys.executable, str(script_path), "--mode", "judge-loop", "--compact", "--text", digest],
            capture_output=True,
            text=True,
            env=env_off,
            check=True,
        )
        data_off = json.loads(p_off.stdout.strip())
        self.assertFalse(data_off["enabled"])
        self.assertEqual(data_off["status"], "disabled")
        self.assertIsNone(data_off["stuck"])
        self.assertEqual(data_off["confidence"], 0.0)

    def test_judge_loop_envfacts_recall_sync_and_flag_isolation(self):
        """AD-1: memory_manager.recall_context() and --sync-envfacts read envfacts.json and respect ASW_TOKEN_ECONOMIZER_ENABLED=0."""
        import os
        import re
        import tempfile
        import memory_manager

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            vault_dir = tmp_path / "AgentMemory"
            proj_dir = tmp_path / "sample app@1"
            proj_dir.mkdir(parents=True)
            (proj_dir / "README.md").write_text("# Sample App\n\nTest repo.\n", encoding="utf-8")

            repo_slug = re.sub(r"[^a-zA-Z0-9._-]", "_", proj_dir.resolve().name)
            state_dir = proj_dir / ".antigravity" / "token_economizer_state" / repo_slug
            state_dir.mkdir(parents=True)
            envfacts_payload = {
                "repo": str(proj_dir.resolve()),
                "now": 4,
                "rendered": "- [FormRepair] Use `python -m pytest` instead of bare `pytest`.",
                "facts": {
                    "fact-1": {
                        "id": "fact-1",
                        "family": "FormRepair",
                        "claim": "Use `python -m pytest` instead of bare `pytest`.",
                        "params": {"old": "pytest", "new": "python -m pytest"},
                        "life": {"status": "ACTIVE", "fires": 4, "exposures": 5},
                    },
                    "fact-2": {
                        "id": "fact-2",
                        "family": "AbsentTool",
                        "claim": "Old retired fact should not sync.",
                        "params": {"tool": "flake8"},
                        "life": {"status": "RETIRED", "fires": 1, "exposures": 6},
                    },
                },
                "forgotten": {},
            }
            (state_dir / "envfacts.json").write_text(json.dumps(envfacts_payload, indent=2), encoding="utf-8")

            # 1. recall_context includes Section 5 within < 10,000 byte budget
            recalled = memory_manager.recall_context(
                vault_dir=vault_dir,
                project_path=proj_dir,
                task_type="code",
            )
            self.assertLess(len(recalled.encode("utf-8")), 10000)
            self.assertIn("## 5. Learned Environment Micro-Skills", recalled)
            self.assertIn("python -m pytest", recalled)

            # 2. --sync-envfacts CLI writes Environment Micro-Skills.md and links from <project>.md
            mm_script = CORE_SCRIPTS / "memory_manager.py"
            p_sync = subprocess.run(
                [
                    sys.executable,
                    str(mm_script),
                    "--sync-envfacts",
                    "--project-path",
                    str(proj_dir),
                    "--vault-dir",
                    str(vault_dir),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            sync_out = json.loads(p_sync.stdout)
            self.assertEqual(sync_out["synced"], 1)

            proj_name = proj_dir.resolve().name
            micro_md = vault_dir / "projects" / proj_name / "Environment Micro-Skills.md"
            overview_md = vault_dir / "projects" / proj_name / f"{proj_name}.md"
            self.assertTrue(micro_md.is_file())
            micro_txt = micro_md.read_text(encoding="utf-8")
            self.assertIn(f"tags: [microskills, envfacts, project/{proj_name}]", micro_txt)
            self.assertIn("python -m pytest", micro_txt)
            self.assertNotIn("Old retired fact should not sync.", micro_txt)
            self.assertIn("Environment Micro-Skills", overview_md.read_text(encoding="utf-8"))

            # 3. Negative isolation: ASW_TOKEN_ECONOMIZER_ENABLED=0 disables recall injection & sync writes
            micro_md.unlink()
            with mock.patch.dict(os.environ, {"ASW_TOKEN_ECONOMIZER_ENABLED": "0"}):
                recalled_off = memory_manager.recall_context(
                    vault_dir=vault_dir,
                    project_path=proj_dir,
                    task_type="code",
                )
                self.assertNotIn("## 5. Learned Environment Micro-Skills", recalled_off)
                self.assertNotIn("python -m pytest", recalled_off)

                sync_off = memory_manager.sync_envfacts_to_vault(proj_dir, vault_dir=vault_dir)
                self.assertFalse(sync_off["enabled"])
                self.assertEqual(sync_off["status"], "disabled")
                self.assertFalse(micro_md.exists())

    # --- M6 Hardening: mode_0 / mode_4 routing, Darwin nvidia-smi skip, HTTP daemon _enrich_with_laya ---
    def test_m6_mode0_mode4_routing_and_negative_guards(self):
        """M6: Operational commands route to mode_0 (unless paired with creation/GUI); emergency rollback routes to mode_4."""
        for op_prompt in (
            "run pytest",
            "run unit tests",
            "build debug",
            "cmake --build build_dir",
            "npm test",
            "spusť testy",
            "zkompiluj projekt",
        ):
            res = self.router.route_prompt(op_prompt)
            self.assertEqual(res["execution_mode"], "mode_0", f"Expected mode_0 for {op_prompt!r}, got {res}")
            self.assertEqual(res["choice"], "mode_0")
            self.assertEqual(res["recommended_tier"], "hydrogen_implement_tdd")
            self.assertFalse(res["requires_subagent_plan_wave"])

        # Negative cases: creation verb or GUI keyword suppresses mode_0
        res_feat = self.router.route_prompt("implement new auth module and run pytest")
        self.assertEqual(res_feat["execution_mode"], "mode_3")
        res_gui = self.router.route_prompt("run pytest and verify dashboard UI")
        self.assertNotEqual(res_gui["execution_mode"], "mode_0")

        # Emergency rollback / restore -> mode_4
        for rb_prompt in (
            "rollback latest deployment",
            "emergency restore database",
            "revert production release",
            "nouzová obnova služby",
        ):
            res_rb = self.router.route_prompt(rb_prompt)
            self.assertEqual(res_rb["execution_mode"], "mode_4", f"Expected mode_4 for {rb_prompt!r}, got {res_rb}")
            self.assertEqual(res_rb["choice"], "mode_4")
            self.assertEqual(res_rb["recommended_tier"], "hydrogen_implement_tdd")

        # Negative case: question about rollback stays mode_1
        res_q = self.router.route_prompt("What is a rollback strategy?")
        self.assertEqual(res_q["execution_mode"], "mode_1")

        # Negative cases: engineering/code-change verbs suppress mode_4 and mode_0
        res_impl_rb = self.router.route_prompt("Implement a rollback mechanism for database migrations")
        self.assertIn(res_impl_rb["execution_mode"], ("mode_2", "mode_3"))

        res_rb_now = self.router.route_prompt("Rollback latest production deployment immediately")
        self.assertEqual(res_rb_now["execution_mode"], "mode_4")

        res_fix_py = self.router.route_prompt("Fix pytest teardown failure in auth")
        self.assertIn(res_fix_py["execution_mode"], ("mode_2", "mode_3"))

        for op_ok in ("Run pytest tests/ -q", "Build Debug preset and run unit tests"):
            res_op = self.router.route_prompt(op_ok)
            self.assertEqual(res_op["execution_mode"], "mode_0", f"Expected mode_0 for {op_ok!r}, got {res_op}")

    def test_m6_darwin_skips_nvidia_smi_and_http_daemon_enrich(self):
        """M6: Darwin skips spawning nvidia-smi; _enrich_with_laya queries HTTP /predict and falls back cleanly when offline."""
        with mock.patch("platform.system", return_value="Darwin"), mock.patch(
            "subprocess.run", side_effect=AssertionError("nvidia-smi must not be spawned on Darwin")
        ):
            dev = decision_router.select_optimal_device()
            self.assertEqual(dev["device"], "cpu")
            self.assertEqual(dev["reason"], "darwin_no_nvidia_cuda")

        # HTTP daemon enrichment
        daemon_router = decision_router.DecisionRouter(
            server_url="http://127.0.0.1:18765",
            enable_inproc=False,
            config={"enabled": True, "use_daemon": True, "compact_question_schema": True},
        )
        fake_resp_body = json.dumps({
            "answers": {
                "execution_mode": {
                    "choice": "mode_3",
                    "answer_confidence": 0.97,
                    "probabilities": {"mode_3": 0.97, "mode_2": 0.03},
                },
                "requires_gui_verification": {"noul": 0.88},
            },
            "routing": {"source": "daemon"},
        }).encode("utf-8")

        class _FakeHTTPResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return fake_resp_body

        captured_reqs = []
        def _fake_urlopen(req, timeout=None):
            captured_reqs.append((req.full_url, json.loads(req.data.decode("utf-8")), timeout))
            return _FakeHTTPResp()

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            res_daemon = daemon_router.route_prompt("implement new caching layer")
            self.assertEqual(res_daemon["backend"], "laya_daemon")
            self.assertEqual(res_daemon["choice"], "mode_3")
            self.assertEqual(res_daemon["execution_mode"], "mode_3")
            self.assertTrue(res_daemon["requires_gui_verification"])
            self.assertTrue(res_daemon["requires_subagent_plan_wave"])
            self.assertEqual(len(captured_reqs), 1)
            self.assertTrue(captured_reqs[0][0].endswith("/predict"))
            self.assertIn("state", captured_reqs[0][1])
            self.assertIn("questions", captured_reqs[0][1])
            self.assertAlmostEqual(captured_reqs[0][2], 0.65, places=2)

        # Unreachable daemon fallback -> calibrated fallback
        with mock.patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            res_offline = daemon_router.route_prompt("implement new caching layer")
            self.assertEqual(res_offline["backend"], "system1_calibrated_fallback")
            self.assertEqual(res_offline["execution_mode"], "mode_2")

    def test_m6_loopback_http_daemon_timeout_tier_sync_and_layered_config(self):
        """M6 Patch #3 & #4: layered config merge, config['server_url'], 200ms loopback HTTP /predict, and tier/plan-wave sync."""
        import http.server
        import tempfile
        import threading
        import time

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_cwd = tmp_path / "repo"
            (fake_home / ".gemini").mkdir(parents=True)
            (fake_cwd / ".antigravity").mkdir(parents=True)

            (fake_home / ".gemini" / "decision_config.json").write_text(
                json.dumps({"enabled": True, "use_daemon": True, "server_url": "http://127.0.0.1:19999"}),
                encoding="utf-8",
            )
            # Workspace config does NOT set use_daemon or server_url
            (fake_cwd / ".antigravity" / "decision_config.json").write_text(
                json.dumps({"enabled": True, "prefer_gpu": False}),
                encoding="utf-8",
            )
            fake_script_dir = fake_cwd / ".antigravity" / "scripts" / "decision_router.py"
            with mock.patch("pathlib.Path.home", return_value=fake_home), mock.patch(
                "pathlib.Path.cwd", return_value=fake_cwd
            ), mock.patch.object(decision_router, "__file__", str(fake_script_dir)):
                merged = decision_router.load_decision_config()
                self.assertTrue(merged.get("use_daemon"))
                self.assertEqual(merged.get("server_url"), "http://127.0.0.1:19999")
                self.assertFalse(merged.get("prefer_gpu"))

                r_cfg = decision_router.DecisionRouter(enable_inproc=False, config=merged)
                self.assertEqual(r_cfg.server_url, "http://127.0.0.1:19999")
                self.assertTrue(r_cfg._daemon_configured)

        # Real loopback HTTP server with simulated 200ms CPU inference latency
        next_choice = {"choice": "mode_3", "conf": 0.94}

        class _SlowLayaHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                _ = self.rfile.read(length)
                time.sleep(0.20)
                body = json.dumps({
                    "answers": {
                        "execution_mode": {
                            "choice": next_choice["choice"],
                            "answer_confidence": next_choice["conf"],
                            "probabilities": {next_choice["choice"]: next_choice["conf"]},
                        }
                    },
                    "routing": {"engine": "loopback_test"},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowLayaHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            loop_router = decision_router.DecisionRouter(
                enable_inproc=False,
                config={"enabled": True, "use_daemon": True, "server_url": f"http://127.0.0.1:{port}", "compact_question_schema": True},
            )
            self.assertEqual(loop_router.server_url, f"http://127.0.0.1:{port}")

            # 1. Base heuristic is mode_2, daemon promotes to mode_3 -> recommended_tier & plan_wave must sync!
            res_up = loop_router.route_prompt("Fix bug in auth")
            self.assertEqual(res_up["backend"], "laya_daemon")
            self.assertEqual(res_up["choice"], "mode_3")
            self.assertEqual(res_up["recommended_tier"], "carbon_plan_research")
            self.assertTrue(res_up["requires_subagent_plan_wave"])

            # 2. Base heuristic is mode_3, daemon demotes to mode_0 -> tier & plan_wave must sync down!
            next_choice["choice"] = "mode_0"
            next_choice["conf"] = 0.91
            res_down = loop_router.route_prompt("Implement auth, add tests, and update docs")
            self.assertEqual(res_down["backend"], "laya_daemon")
            self.assertEqual(res_down["choice"], "mode_0")
            self.assertEqual(res_down["recommended_tier"], "hydrogen_implement_tdd")
            self.assertFalse(res_down["requires_subagent_plan_wave"])
        finally:
            server.shutdown()
            server.server_close()

    # --- H1 (Task 1): Word-Boundary + Negative-Example Skill Router & 30-Prompt Benchmark ---
    def test_h1_m1_word_boundary_no_substring_leaks(self):
        """M1: Word-boundary matching prevents 'ui'/'ts'/'var' substring leaks while matching python-pro & TDD."""
        prompt = "Build Python backend and run unit tests suite quickly with invariant checks"
        skills = self.router.select_skills(prompt, max_skills=8)
        self.assertLessEqual(len(skills), 8)
        self.assertIn("python-pro", skills)
        self.assertIn("test-driven-development", skills)
        self.assertNotIn("ui-ux-designer", skills, "'ui' in build/suite must not trigger ui-ux-designer")
        self.assertNotIn("typescript-pro", skills, "'ts' in tests must not trigger typescript-pro")
        self.assertNotIn("risk-metrics-calculation", skills, "'var' in invariant must not trigger risk-metrics-calculation")

    def test_h1_m2_negative_examples_and_domain_expansion(self):
        """M2: SKILL_NEGATIVE_EXAMPLES suppresses false triggers and expanded domain catalog routes accurately."""
        self.assertTrue(hasattr(decision_router, "SKILL_NEGATIVE_EXAMPLES"))
        self.assertIsInstance(decision_router.SKILL_NEGATIVE_EXAMPLES, dict)
        self.assertGreaterEqual(len(decision_router.SKILL_NEGATIVE_EXAMPLES), 4)

        # Negative disambiguation cases
        s_state = self.router.select_skills("Write Python state machine for git log parser", max_skills=8)
        self.assertIn("python-pro", s_state)
        self.assertNotIn("react-patterns", s_state, "'state' without React cues must not select react-patterns")

        s_index = self.router.select_skills("Build Python inverted index for document search", max_skills=8)
        self.assertIn("python-pro", s_index)
        self.assertNotIn("postgres-best-practices", s_index, "'index' without SQL/DB cues must not select postgres-best-practices")

        s_local_api = self.router.select_skills("Refactor local src/api/routes.py validation handler", max_skills=8)
        self.assertNotIn("context-hub", s_local_api, "Local src/api/ path must not trigger context-hub")

        s_ext_api = self.router.select_skills("Fetch Stripe SDK API docs with chub", max_skills=8)
        self.assertIn("context-hub", s_ext_api)

        s_go_verb = self.router.select_skills("We want to go to production after goal check", max_skills=8)
        self.assertNotIn("golang-pro", s_go_verb, "'go to'/'goal' must not trigger golang-pro")

        s_golang = self.router.select_skills("Build Golang gRPC microservice", max_skills=8)
        self.assertIn("golang-pro", s_golang)

        s_go_conc = self.router.select_skills("Write Go concurrency worker with goroutines", max_skills=8)
        self.assertIn("golang-pro", s_go_conc)

        # Domain expansion coverage
        domain_cases = [
            ("Implement Rust async Tokio TCP server with serde", "rust-pro"),
            ("Write Go concurrency worker with goroutines", "golang-pro"),
            ("Optimize C++20 CMake build with RAII memory safety", "cpp-pro"),
            ("Configure Kubernetes Helm chart and Ingress pods", "kubernetes-architect"),
            ("Provision AWS VPC using Terraform HCL modules", "terraform-skill"),
            ("Perform OWASP security vulnerability audit for SQL injection and XSS", "security-auditor"),
            ("Build fast Parquet ETL pipeline using Polars LazyFrame", "polars"),
            ("Create executive PowerPoint pitch deck slides in pptx", "pptx-official"),
            ("Implement GDPR PII anonymization and data retention policy", "gdpr-data-handling"),
        ]
        for prompt_text, expected_skill in domain_cases:
            with self.subTest(expected_skill=expected_skill):
                selected = self.router.select_skills(prompt_text, max_skills=8)
                self.assertLessEqual(len(selected), 8)
                self.assertIn(expected_skill, selected)

        # Flag isolation check on domain prompt
        with mock.patch.dict("os.environ", {"ASW_DECISION_MODEL_ENABLED": "0"}):
            disabled = decision_router.DecisionRouter()
            self.assertEqual(disabled.select_skills("Implement Rust async Tokio TCP server with serde", max_skills=8), [])

    def test_h1_benchmark_skill_routing_30_bilingual_prompts_and_cli(self):
        """M1-M2 Benchmark: 30 bilingual (18 EN + 12 CZ) prompts prove >= +0.20 P@k, higher F1, and lower FPR."""
        self.assertTrue(hasattr(decision_router, "LEGACY_SKILL_CATALOG_KEYWORDS"))
        self.assertTrue(hasattr(decision_router, "benchmark_skill_routing"))

        report = decision_router.benchmark_skill_routing()
        self.assertEqual(report["prompt_count"], 30)
        self.assertEqual(report["en_count"], 18)
        self.assertEqual(report["cz_count"], 12)
        self.assertEqual(report["opt_tokens"], 0.0)
        self.assertEqual(len(report["per_prompt"]), 30)

        legacy = report["legacy"]
        upgraded = report["upgraded"]
        for side in (legacy, upgraded):
            for key in ("precision_at_k", "recall_at_k", "f1", "false_positive_rate", "unexpected_prediction_rate", "prompt_pollution_rate"):
                self.assertIn(key, side)

        self.assertGreaterEqual(
            upgraded["precision_at_k"] - legacy["precision_at_k"],
            0.20,
            f"Expected >= +0.20 precision lift; legacy={legacy}, upgraded={upgraded}",
        )
        self.assertGreater(upgraded["f1"], legacy["f1"])
        self.assertLess(upgraded["false_positive_rate"], legacy["false_positive_rate"])
        self.assertEqual(upgraded["forbidden_hits"], 0)

        # CLI --benchmark-routing check
        script_path = CORE_SCRIPTS / "decision_router.py"
        proc = subprocess.run(
            [sys.executable, str(script_path), "--benchmark-routing"],
            capture_output=True,
            text=True,
            check=True,
        )
        cli_report = json.loads(proc.stdout)
        self.assertEqual(cli_report["prompt_count"], 30)
        self.assertGreaterEqual(cli_report["upgraded"]["precision_at_k"] - cli_report["legacy"]["precision_at_k"], 0.20)
        self.assertIn("shared_legacy_domain_subset", cli_report)
        subset = cli_report["shared_legacy_domain_subset"]
        self.assertGreater(subset["prompt_count"], 0)
        self.assertLess(subset["prompt_count"], 30)
        self.assertGreater(subset["upgraded"]["precision_at_k"], subset["legacy"]["precision_at_k"])

    def test_h1_patch3_czech_memory_leak_and_lets_go_ui_negative_cases(self):
        """Patch 3: Czech memory leak excludes obs-memory; 'Let's go test the UI dashboard' excludes golang-pro."""
        s_mem = self.router.select_skills("Oprav únik paměti v C++ parseru", max_skills=8)
        self.assertIn("cpp-pro", s_mem)
        self.assertNotIn("obs-memory", s_mem, "Czech memory-leak prompt must not select obs-memory")
        self.assertNotIn("react-patterns", s_mem, "Czech parseru prompt must not select react-patterns")

        s_ui = self.router.select_skills("Let's go test the UI dashboard", max_skills=8)
        self.assertIn("ui-ux-designer", s_ui)
        self.assertNotIn("golang-pro", s_ui, "'Let's go test the UI' must not select golang-pro")

        s_go_test = self.router.select_skills("Run go test ./... in golang service", max_skills=8)
        self.assertIn("golang-pro", s_go_test)


if __name__ == "__main__":
    unittest.main()
