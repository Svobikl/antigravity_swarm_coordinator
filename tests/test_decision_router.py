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

    # --- Auto Sub-Skill Orchestration (Task 1: M1-M5) ---
    def test_aso_m1_strip_ignored_regions_and_contractions(self):
        """M1: _strip_ignored_regions strips backticks/quotes (EN/CZ/curly) while preserving contractions."""
        strip_fn = decision_router._strip_ignored_regions
        self.assertEqual(
            strip_fn('I don\'t use "asw-plan" or `asw-review` and it isn\'t needed'),
            "I don't use   or   and it isn't needed",
        )
        self.assertEqual(
            strip_fn("I can't run 'asw-plan' and Let's test 'don't stop'"),
            "I can't run   and Let's test  ",
        )
        self.assertEqual(
            strip_fn("používám „asw-plan“ a “asw-review” a ‘asw-goal’ ale don’t panic"),
            "používám   a   a   ale don’t panic",
        )
        self.assertEqual(
            strip_fn("Check ```/asw-plan\nfoo``` now"),
            "Check   now",
        )

    def test_aso_m1_leading_command_priority_and_quoted_immunity(self):
        """M1: Leading /asw wins over quoted or trailing /asw-plan; modifiers like asw-test-gui remain active."""
        q_meta = self.router.route_prompt('/asw ja prakticky pouzivam pouze "asw" a obcas "asw-plan", neni to skoda?')
        self.assertEqual(q_meta["recommended_mode"], "mode_1")
        self.assertEqual(q_meta["execution_mode"], "mode_1")
        self.assertEqual(q_meta["recommended_command"], "asw-consultation")
        self.assertTrue(q_meta["is_consultation"])
        self.assertFalse(q_meta["requires_gui_verification"])
        self.assertEqual(q_meta["auto_subskills"], [])

        act_quoted = self.router.route_prompt('/asw implementuj funkci a ne "asw-plan"')
        self.assertEqual(act_quoted["recommended_command"], "asw-loop")
        self.assertIn(act_quoted["recommended_mode"], ("mode_2", "mode_3"))
        self.assertFalse(act_quoted["is_consultation"])

        act_trailing = self.router.route_prompt("/asw oprav funkci a nepouzivej /asw-plan")
        self.assertEqual(act_trailing["recommended_command"], "asw-loop")
        self.assertFalse(act_trailing["is_consultation"])

        mod_gui = self.router.route_prompt("/asw asw-test-gui verify dashboard")
        self.assertTrue(mod_gui["requires_gui_verification"])
        self.assertIn("asw-test-gui", mod_gui["auto_subskills"])

    def test_aso_m2_pure_readonly_mode1_consultation(self):
        """M2: Pure read-only /asw <question>? routes to mode_1 consultation without GUI/TDD."""
        for prompt in (
            "/asw Jak funguje caching?",
            "/asw how does the router work?",
            "Co dělá tato funkce?",
        ):
            with self.subTest(prompt=prompt):
                res = self.router.route_prompt(prompt)
                self.assertEqual(res["recommended_mode"], "mode_1")
                self.assertEqual(res["execution_mode"], "mode_1")
                self.assertEqual(res["recommended_command"], "asw-consultation")
                self.assertTrue(res["is_consultation"])
                self.assertFalse(res["requires_gui_verification"])
                self.assertFalse(res["requires_subagent_plan_wave"])
                self.assertEqual(res["auto_subskills"], [])
                self.assertEqual(res["opt_tokens"], 0.0)

    def test_aso_m3_m4_bilingual_gui_gate_and_visual_docs(self):
        """M3/M4: Action GUI prompts activate asw-ui-ux + asw-test-gui; read-only skips; SVG/README activates only asw-ui-ux."""
        gui_action_prompts = (
            "/asw vytvoř moderní React dashboard s grafy",
            "/asw build a Flutter mobile UI",
            "/asw oprav chybu ve webové aplikaci",
            "/asw-plan navrhni Electron rozhraní",
        )
        for prompt in gui_action_prompts:
            with self.subTest(prompt=prompt):
                res = self.router.route_prompt(prompt)
                self.assertTrue(res["requires_gui_verification"], f"Expected GUI verification for {prompt!r}")
                self.assertIn("asw-ui-ux", res["auto_subskills"])
                self.assertIn("asw-test-gui", res["auto_subskills"])

        res_bug_gui = self.router.route_prompt("/asw oprav chybu ve webové aplikaci")
        self.assertIn("asw-debug", res_bug_gui["auto_subskills"])

        for ro_prompt in ("/asw jak funguje React state?", "/asw používá to asw-ui-ux?"):
            with self.subTest(ro_prompt=ro_prompt):
                res = self.router.route_prompt(ro_prompt)
                self.assertFalse(res["requires_gui_verification"])
                self.assertEqual(res["auto_subskills"], [])
                self.assertEqual(res["recommended_mode"], "mode_1")
                self.assertTrue(res["is_consultation"])

        res_svg = self.router.route_prompt("/asw Vylepši README a přidej SVG architekturu")
        self.assertFalse(res_svg["requires_gui_verification"])
        self.assertIn("asw-ui-ux", res_svg["auto_subskills"])
        self.assertNotIn("asw-test-gui", res_svg["auto_subskills"])

        for backend_prompt in ("asw-loop implementuj backend endpoint", "/asw implementuj FastAPI endpoint"):
            with self.subTest(backend_prompt=backend_prompt):
                res = self.router.route_prompt(backend_prompt)
                self.assertFalse(res["requires_gui_verification"])
                self.assertNotIn("asw-ui-ux", res["auto_subskills"])
                self.assertNotIn("asw-test-gui", res["auto_subskills"])

    def test_aso_m5_zero_llm_auto_subskills_and_budget(self):
        """M5: Zero-LLM auto_subskills trigger debug/refactor/cleanup, respect <=8 combined budget, and preserve 1.0 P@k."""
        for dbg_prompt in ("/asw padá Traceback", "/asw aplikace zamrzá při startu", "/asw debug crash in worker"):
            res = self.router.route_prompt(dbg_prompt)
            self.assertIn("asw-debug", res["auto_subskills"])
            self.assertEqual(res["opt_tokens"], 0.0)

        res_quoted_dbg = self.router.route_prompt('/asw jak funguje "padá" v logu?')
        self.assertEqual(res_quoted_dbg["auto_subskills"], [])

        for ref_prompt in ("/asw rozděl soubor utils.py a přejmenuj funkce", "/asw refactor and split module"):
            res = self.router.route_prompt(ref_prompt)
            self.assertIn("asw-refactor", res["auto_subskills"])

        for cln_prompt in ("/asw vyčisti kód a odstraň mrtvý kód", "/asw cleanup dead code and ai slop"):
            res = self.router.route_prompt(cln_prompt)
            self.assertIn("asw-cleanup", res["auto_subskills"])

        heavy_prompt = (
            "/asw oprav chybu a padá React dashboard, rozděl soubor a přejmenuj komponenty, "
            "vyčisti mrtvý kód, přidej FastAPI Postgres Docker Kubernetes Playwright Python"
        )
        res_heavy = self.router.route_prompt(heavy_prompt)
        auto = res_heavy["auto_subskills"]
        dom = res_heavy["selected_skills"]
        self.assertGreaterEqual(len(auto), 4)
        self.assertEqual(len(set(auto) & set(dom)), 0)
        self.assertLessEqual(len(auto) + len(dom), 8)
        self.assertEqual(res_heavy["opt_tokens"], 0.0)

        pred_heavy = self.router.predict(heavy_prompt)
        self.assertLessEqual(len(pred_heavy["auto_subskills"]) + len(pred_heavy["selected_skills"]), 8)

        bench = decision_router.benchmark_skill_routing(self.router)
        self.assertEqual(bench["upgraded"]["precision_at_k"], 1.0)

    def test_aso_feature_flag_negative_isolation_and_cli_compact(self):
        """Negative isolation: flag 0 / enabled=false returns empty skills; CLI --mode route-prompt --compact --prompt emits full contract."""
        import os

        with mock.patch.dict(os.environ, {"ASW_DECISION_MODEL_ENABLED": "0"}):
            dis = decision_router.DecisionRouter()
            r_dis = dis.route_prompt("/asw vytvoř React dashboard a oprav chybu")
            self.assertFalse(r_dis["enabled"])
            self.assertEqual(r_dis["auto_subskills"], [])
            self.assertEqual(r_dis["selected_skills"], [])
            self.assertFalse(r_dis["requires_gui_verification"])
            self.assertEqual(r_dis["opt_tokens"], 0.0)

        dis_cfg = decision_router.DecisionRouter(config={"enabled": False})
        r_cfg = dis_cfg.predict("/asw padá Traceback")
        self.assertFalse(r_cfg["enabled"])
        self.assertEqual(r_cfg["auto_subskills"], [])
        self.assertEqual(r_cfg["selected_skills"], [])
        self.assertFalse(r_cfg["requires_gui_verification"])

        script_path = CORE_SCRIPTS / "decision_router.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--mode",
                "route-prompt",
                "--compact",
                "--prompt",
                "/asw vytvoř moderní React dashboard s grafy",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        cli_data = json.loads(proc.stdout.strip())
        for key in (
            "auto_subskills",
            "selected_skills",
            "requires_gui_verification",
            "recommended_mode",
            "recommended_command",
            "is_consultation",
            "opt_tokens",
        ):
            self.assertIn(key, cli_data)
        self.assertTrue(cli_data["requires_gui_verification"])
        self.assertIn("asw-ui-ux", cli_data["auto_subskills"])
        self.assertIn("asw-test-gui", cli_data["auto_subskills"])
        self.assertEqual(cli_data["opt_tokens"], 0.0)
        self.assertLessEqual(len(cli_data["auto_subskills"]) + len(cli_data["selected_skills"]), 8)

    def test_aso_mutation_boundary_guards(self):
        """Boundary guards killing AST mutants in both .antigravity and core_framework decision_router mirrors."""
        import importlib.util

        modules = [decision_router]
        core_path = CORE_SCRIPTS / "decision_router.py"
        if core_path.is_file() and core_path.resolve() != Path(decision_router.__file__).resolve():
            spec = importlib.util.spec_from_file_location("core_decision_router", str(core_path))
            if spec is not None and spec.loader is not None:
                core_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(core_mod)
                modules.append(core_mod)

        for mod in modules:
            strip_fn = mod._strip_ignored_regions
            self.assertEqual(strip_fn(""), "")
            self.assertEqual(strip_fn(None), "")  # type: ignore[arg-type]
            self.assertEqual(strip_fn(123), "")  # type: ignore[arg-type]

            strip_q_fn = mod._strip_quoted_spans
            self.assertEqual(strip_q_fn(""), "")
            self.assertEqual(strip_q_fn(None), "")  # type: ignore[arg-type]
            self.assertEqual(strip_q_fn(123), "")  # type: ignore[arg-type]

            gui_fn = mod._detect_gui_intent
            self.assertFalse(gui_fn("/asw jak funguje React UI?")["requires_gui_verification"])
            self.assertTrue(gui_fn("/asw vytvoř React UI")["requires_gui_verification"])
            self.assertFalse(gui_fn("/asw vytvoř React UI", is_question_only=True)["requires_gui_verification"])
            self.assertTrue(
                gui_fn("/asw jak funguje React UI?", is_question_only=False, has_action_verb=True)[
                    "requires_gui_verification"
                ]
            )

            router_inst = mod.DecisionRouter()
            with mock.patch.object(router_inst, "select_skills", side_effect=AssertionError("must not call select_skills when budget is full")):
                full_dec = router_inst._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification=False,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.3,
                    auto_subskills=[f"s{i}" for i in range(8)],
                    prompt_for_skills="python fastapi",
                )
            self.assertEqual(full_dec["selected_skills"], [])

            # Patch-1 & Patch-2 regression assertions across both mirrors
            bare_loop = router_inst.route_prompt("asw-loop Implement auth, add tests, and update docs")
            self.assertEqual(bare_loop["recommended_command"], "asw-loop")
            self.assertEqual(bare_loop["execution_mode"], "mode_3")
            self.assertFalse(bare_loop["requires_gui_verification"])

            bare_loop_q = router_inst.route_prompt("asw-loop Jak funguje caching?")
            self.assertEqual(bare_loop_q["recommended_command"], "asw-loop")
            self.assertFalse(bare_loop_q["is_consultation"])

            bare_asw = router_inst.route_prompt("asw implement parser and ignore /asw-plan")
            self.assertEqual(bare_asw["recommended_command"], "asw-loop")
            self.assertFalse(bare_asw["is_consultation"])

            consult_res = router_inst.route_prompt("/asw Jak funguje caching?")
            self.assertTrue(consult_res["is_consultation"])
            self.assertNotIn("implementation-developer", consult_res["selected_skills"])
            self.assertNotIn("validator-build-test-agent", consult_res["selected_skills"])

            quoted_skills = router_inst.select_skills(
                "/asw don't use “asw-review” here, implement the parser", max_skills=8
            )
            self.assertNotIn("compliance-maintainability-reviewer", quoted_skills)

            # _enrich_with_laya must NOT flip requires_gui_verification when gui_ans is {} or mode_1 consultation
            daemon_inst = mod.DecisionRouter(
                server_url="http://127.0.0.1:18765",
                enable_inproc=False,
                config={"enabled": True, "use_daemon": True, "compact_question_schema": True},
            )
            fake_no_gui = json.dumps({
                "answers": {
                    "execution_mode": {"choice": "mode_3", "answer_confidence": 0.9, "probabilities": {"mode_3": 0.9}},
                },
                "routing": {"source": "daemon"},
            }).encode("utf-8")

            class _FakeRespNoGui:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return fake_no_gui

            base_non_gui = router_inst._build_decision(
                choice="mode_3",
                execution_mode="mode_3",
                recommended_tier="carbon_plan_research",
                requires_gui_verification=False,
                requires_subagent_plan_wave=True,
                answer_confidence=0.92,
                noul=0.70,
                recommended_command="asw-loop",
                is_consultation=False,
                auto_subskills=[],
                prompt_for_skills="asw-loop Implement auth, add tests, and update docs",
            )
            with mock.patch("urllib.request.urlopen", return_value=_FakeRespNoGui()):
                enriched = daemon_inst._enrich_with_laya(
                    "asw-loop Implement auth, add tests, and update docs", dict(base_non_gui)
                )
            self.assertFalse(enriched["requires_gui_verification"])
            self.assertEqual(enriched["noul"], 0.70)

            # Laya override to mode_1 strips implementation/validator skills and ignores high gui_noul
            fake_mode1 = json.dumps({
                "answers": {
                    "execution_mode": {"choice": "mode_1", "answer_confidence": 0.95, "probabilities": {"mode_1": 0.95}},
                    "requires_gui_verification": {"noul": 0.90},
                },
            }).encode("utf-8")

            class _FakeRespMode1:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return fake_mode1

            with mock.patch("urllib.request.urlopen", return_value=_FakeRespMode1()):
                enriched_m1 = daemon_inst._enrich_with_laya("Jak funguje auth?", dict(base_non_gui))
            self.assertTrue(enriched_m1["is_consultation"])
            self.assertEqual(enriched_m1["recommended_command"], "asw-consultation")
            self.assertFalse(enriched_m1["requires_gui_verification"])
            self.assertNotIn("implementation-developer", enriched_m1["selected_skills"])
            self.assertNotIn("validator-build-test-agent", enriched_m1["selected_skills"])

            # Exact gui_noul == 0.75 boundary kills >= -> > mutant
            for boundary_val, expected_gui in ((0.75, True), (0.74, False)):
                fake_b = json.dumps({
                    "answers": {
                        "execution_mode": {"choice": "mode_3", "answer_confidence": 0.9},
                        "requires_gui_verification": {"noul": boundary_val},
                    },
                }).encode("utf-8")

                class _FakeRespBoundary:
                    status = 200
                    def __enter__(self_r): return self_r
                    def __exit__(self_r, *args): return False
                    def read(self_r): return fake_b

                with mock.patch("urllib.request.urlopen", return_value=_FakeRespBoundary()):
                    res_b = daemon_inst._enrich_with_laya("implement auth", dict(base_non_gui))
                self.assertEqual(res_b["requires_gui_verification"], expected_gui)

    # --- Adaptive Spec-Kit Clarify Gate (M1-M5, M7) ---
    def test_clarify_m1_underspecified_complex_prompts(self):
        """M1: Underspecified Mode 3/5 prompts trigger clarify gate with 1..3 missing dimensions and opt_tokens == 0.0."""
        allowed_dims = {
            "scope_actors",
            "data_persistence",
            "auth_security",
            "external_integration",
            "ux_state_flow",
        }
        prompts = (
            ("/asw-plan Build customer billing portal", "mode_3"),
            ("/asw vytvoř zákaznický portál s předplatným a fakturací", "mode_3"),
            ("/asw-goal vybuduj multi-region synchronizační platformu", "mode_5"),
        )
        for prompt, expected_mode in prompts:
            with self.subTest(prompt=prompt):
                res = self.router.route_prompt(prompt)
                self.assertEqual(res["execution_mode"], expected_mode)
                self.assertEqual(res["opt_tokens"], 0.0)
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], True)
                self.assertIsNone(gate["bypass_reason"])
                self.assertLess(gate["specificity_score"], 3)
                self.assertGreater(gate["ambiguity_score"], 0.0)
                self.assertLessEqual(gate["ambiguity_score"], 1.0)
                dims = gate["missing_dimensions"]
                self.assertGreaterEqual(len(dims), 1)
                self.assertLessEqual(len(dims), 3)
                self.assertEqual(len(set(dims)), len(dims))
                self.assertTrue(set(dims).issubset(allowed_dims))
                self.assertEqual(gate["max_questions"], 3)

    def test_clarify_m2_well_specified_complex_prompts(self):
        """M2: Well-specified Mode 3 prompts bypass with 'sufficient_detail' and specificity_score >= 3."""
        prompts = (
            "/asw-plan Add POST /v1/pay in api.py with JWT, Postgres, p95 < 40ms",
            "/asw Přidej endpoint POST /api/v1/exports v routers/exports.py s PostgreSQL, JWT auth a limitem 10 req/min",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                res = self.router.route_prompt(prompt)
                self.assertEqual(res["execution_mode"], "mode_3")
                self.assertEqual(res["opt_tokens"], 0.0)
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], False)
                self.assertEqual(gate["bypass_reason"], "sufficient_detail")
                self.assertGreaterEqual(gate["specificity_score"], 3)
                self.assertEqual(gate["missing_dimensions"], [])
                self.assertEqual(gate["max_questions"], 0)

    def test_clarify_m3_hard_bypasses(self):
        """M3: Bugfix, refactor/cleanup, Mode 1, start-work, review, Mode 0, Mode 4, and small Mode 2 bypass."""
        for bug_prompt in ("/asw oprav chybu 500 v /api/orders", "/asw padá worker s Tracebackem"):
            with self.subTest(bug_prompt=bug_prompt):
                res = self.router.route_prompt(bug_prompt)
                self.assertIn("asw-debug", res["auto_subskills"])
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], False)
                self.assertEqual(gate["bypass_reason"], "bugfix_or_debug")
                self.assertEqual(gate["missing_dimensions"], [])
                self.assertEqual(gate["max_questions"], 0)

        for beh_prompt in ("/asw-refactor rozděl modul", "/asw vyčisti mrtvý kód"):
            with self.subTest(beh_prompt=beh_prompt):
                res = self.router.route_prompt(beh_prompt)
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], False)
                self.assertEqual(gate["bypass_reason"], "behavior_preserving")
                self.assertEqual(gate["missing_dimensions"], [])
                self.assertEqual(gate["max_questions"], 0)

        res_ro = self.router.route_prompt("/asw jak funguje caching?")
        self.assertEqual(res_ro["execution_mode"], "mode_1")
        self.assertIs(res_ro["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_ro["clarification_gate"]["bypass_reason"], "read_only")

        res_sw = self.router.route_prompt("/asw-start-work my-plan")
        self.assertIs(res_sw["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_sw["clarification_gate"]["bypass_reason"], "executing_approved_plan")

        res_rev = self.router.route_prompt("/asw-review")
        self.assertIs(res_rev["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_rev["clarification_gate"]["bypass_reason"], "review_only")

        res_m0 = self.router.route_prompt("spusť testy")
        self.assertEqual(res_m0["execution_mode"], "mode_0")
        self.assertIs(res_m0["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_m0["clarification_gate"]["bypass_reason"], "operational_or_restore")

        res_m4 = self.router.route_prompt("emergency restore production")
        self.assertEqual(res_m4["execution_mode"], "mode_4")
        self.assertIs(res_m4["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_m4["clarification_gate"]["bypass_reason"], "operational_or_restore")

        offline_router = decision_router.DecisionRouter(
            config={"enabled": True, "use_daemon": False},
            enable_inproc=False,
        )
        res_m2 = offline_router.route_prompt("Update timeout constant in config.py")
        self.assertEqual(res_m2["execution_mode"], "mode_2")
        self.assertIs(res_m2["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_m2["clarification_gate"]["bypass_reason"], "small_clear_change")

    def test_clarify_m4_hypothetical_clause_masking(self):
        """M4: Hypothetical/example bugfix clauses never trigger asw-debug or bugfix bypass; direct bugfix still does."""
        hypothetical_prompts = (
            "/asw-plan Navrhni clarify gate nebo opravujeme chybu v kódu",
            "/asw-plan Design clarify gate or when fixing a bug in code",
            "/asw-plan Když opravujeme chybu, neptej se, ale u složitých věcí se doptej",
        )
        for prompt in hypothetical_prompts:
            with self.subTest(prompt=prompt):
                res = self.router.route_prompt(prompt)
                self.assertNotIn("asw-debug", res["auto_subskills"])
                self.assertNotIn("asw-debug", self.router.select_auto_subskills(prompt))
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], True)
                self.assertIsNone(gate["bypass_reason"])

        direct_bug = self.router.route_prompt("/asw oprav chybu v kódu")
        self.assertIn("asw-debug", direct_bug["auto_subskills"])
        self.assertIs(direct_bug["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(direct_bug["clarification_gate"]["bypass_reason"], "bugfix_or_debug")

        # Regression: 'response' / 'restartujeme' after 'když' must NOT be swallowed by hypothetical res- masking
        for real_cz_bug in (
            "/asw když response vrací HTTP 500 tak padá worker",
            "/asw když restartujeme službu padá s Tracebackem",
        ):
            with self.subTest(real_cz_bug=real_cz_bug):
                res_bug = self.router.route_prompt(real_cz_bug)
                self.assertIn("asw-debug", res_bug["auto_subskills"])
                self.assertIs(res_bug["clarification_gate"]["needs_clarification"], False)
                self.assertEqual(res_bug["clarification_gate"]["bypass_reason"], "bugfix_or_debug")

        res_hyp_unaccented = self.router.route_prompt("/asw-plan Když resime chybu nebo opravujeme chybu, neptej se")
        self.assertNotIn("asw-debug", res_hyp_unaccented["auto_subskills"])

    def test_clarify_m5_explicit_skip_vs_force_overrides(self):
        """M5: --no-clarify/bez doptávání/rozhodni sám bypass; /asw-clarify/--clarify/grill-me force; --no-clarify wins."""
        for skip_prompt in (
            "/asw-plan Build customer billing portal --no-clarify",
            "/asw vytvoř portál bez doptávání",
            "/asw vytvoř portál, rozhodni sám",
        ):
            with self.subTest(skip_prompt=skip_prompt):
                res = self.router.route_prompt(skip_prompt)
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], False)
                self.assertEqual(gate["bypass_reason"], "user_skip")
                self.assertEqual(gate["missing_dimensions"], [])
                self.assertEqual(gate["max_questions"], 0)

        res_cmd = self.router.route_prompt("/asw-clarify přidej notifikace")
        self.assertEqual(res_cmd["recommended_command"], "asw-clarify")
        self.assertEqual(res_cmd["execution_mode"], "mode_3")
        self.assertIs(res_cmd["clarification_gate"]["needs_clarification"], True)
        self.assertEqual(res_cmd["clarification_gate"]["bypass_reason"], "user_forced")
        self.assertEqual(res_cmd["clarification_gate"]["max_questions"], 3)
        self.assertGreaterEqual(len(res_cmd["clarification_gate"]["missing_dimensions"]), 1)
        self.assertLessEqual(len(res_cmd["clarification_gate"]["missing_dimensions"]), 3)

        for force_prompt in (
            "/asw --clarify přidej pole",
            "/asw grill-me navrhni cache",
            "/asw-clarify Add POST /v1/pay in api.py with JWT, Postgres, p95 < 40ms",
        ):
            with self.subTest(force_prompt=force_prompt):
                res = self.router.route_prompt(force_prompt)
                gate = res["clarification_gate"]
                self.assertIs(gate["needs_clarification"], True)
                self.assertEqual(gate["bypass_reason"], "user_forced")
                self.assertEqual(gate["max_questions"], 3)
                self.assertGreaterEqual(len(gate["missing_dimensions"]), 1)
                self.assertLessEqual(len(gate["missing_dimensions"]), 3)

        # Precedence guard: --no-clarify beats /asw-clarify
        res_prec = self.router.route_prompt("/asw-clarify přidej notifikace --no-clarify")
        self.assertEqual(res_prec["recommended_command"], "asw-clarify")
        self.assertIs(res_prec["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(res_prec["clarification_gate"]["bypass_reason"], "user_skip")
        self.assertEqual(res_prec["clarification_gate"]["missing_dimensions"], [])
        self.assertEqual(res_prec["clarification_gate"]["max_questions"], 0)

    def test_clarify_m7_disabled_and_laya_override_refresh_and_cli(self):
        """M7: Disabled router emits zeroed clarification_gate; _enrich_with_laya refreshes gate; CLI & benchmark intact."""
        import hashlib
        import os

        expected_disabled = {
            "needs_clarification": False,
            "bypass_reason": "disabled",
            "specificity_score": 0,
            "ambiguity_score": 0.0,
            "missing_dimensions": [],
            "max_questions": 0,
        }
        with mock.patch.dict(os.environ, {"ASW_DECISION_MODEL_ENABLED": "0"}):
            dis_env = decision_router.DecisionRouter()
            r_env = dis_env.route_prompt("/asw-plan Build customer billing portal")
            self.assertEqual(r_env["clarification_gate"], expected_disabled)
            self.assertEqual(dis_env.assess_clarification_need("Build portal"), expected_disabled)

        dis_cfg = decision_router.DecisionRouter(config={"enabled": False})
        r_cfg = dis_cfg.route_prompt("/asw-clarify přidej notifikace")
        self.assertEqual(r_cfg["clarification_gate"], expected_disabled)

        # _enrich_with_laya mode override refresh (mode_3 -> mode_1 and mode_2 -> mode_3)
        daemon_inst = decision_router.DecisionRouter(
            server_url="http://127.0.0.1:18765",
            enable_inproc=False,
            config={"enabled": True, "use_daemon": True, "compact_question_schema": True},
        )
        base_m3 = self.router.route_prompt("/asw-plan Build customer billing portal")
        self.assertIs(base_m3["clarification_gate"]["needs_clarification"], True)

        fake_m1_body = json.dumps({
            "answers": {
                "execution_mode": {"choice": "mode_1", "answer_confidence": 0.95, "probabilities": {"mode_1": 0.95}},
            },
        }).encode("utf-8")

        class _FakeRespM1:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return fake_m1_body

        with mock.patch("urllib.request.urlopen", return_value=_FakeRespM1()):
            refreshed_m1 = daemon_inst._enrich_with_laya("Build customer billing portal", dict(base_m3))
        self.assertEqual(refreshed_m1["execution_mode"], "mode_1")
        self.assertIs(refreshed_m1["clarification_gate"]["needs_clarification"], False)
        self.assertEqual(refreshed_m1["clarification_gate"]["bypass_reason"], "read_only")
        self.assertEqual(refreshed_m1["clarification_gate"]["missing_dimensions"], [])

        base_m2 = self.router.route_prompt("implement caching layer")
        fake_m3_body = json.dumps({
            "answers": {
                "execution_mode": {"choice": "mode_3", "answer_confidence": 0.95, "probabilities": {"mode_3": 0.95}},
            },
        }).encode("utf-8")

        class _FakeRespM3:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return fake_m3_body

        with mock.patch("urllib.request.urlopen", return_value=_FakeRespM3()):
            refreshed_m3 = daemon_inst._enrich_with_laya("implement caching layer", dict(base_m2))
        self.assertEqual(refreshed_m3["execution_mode"], "mode_3")
        self.assertIs(refreshed_m3["clarification_gate"]["needs_clarification"], True)
        self.assertIsNone(refreshed_m3["clarification_gate"]["bypass_reason"])
        self.assertEqual(refreshed_m3["clarification_gate"]["max_questions"], 3)

        # CLI --compact SHA-256 parity + opt_tokens == 0.0
        script_path = CORE_SCRIPTS / "decision_router.py"
        cli_args = [sys.executable, str(script_path), "--mode", "route-prompt", "--compact", "--text", "/asw-plan Build customer billing portal"]
        p1 = subprocess.run(cli_args, capture_output=True, text=True, check=True)
        p2 = subprocess.run(cli_args, capture_output=True, text=True, check=True)
        self.assertEqual(
            hashlib.sha256(p1.stdout.strip().encode("utf-8")).hexdigest(),
            hashlib.sha256(p2.stdout.strip().encode("utf-8")).hexdigest(),
        )
        cli_json = json.loads(p1.stdout.strip())
        self.assertIs(cli_json["clarification_gate"]["needs_clarification"], True)
        self.assertEqual(cli_json["opt_tokens"], 0.0)

        bench = decision_router.benchmark_skill_routing(self.router)
        self.assertEqual(bench["upgraded"]["precision_at_k"], 1.0)
        self.assertEqual(bench["upgraded"]["recall_at_k"], 1.0)
        self.assertEqual(bench["opt_tokens"], 0.0)

    def test_clarify_dual_mirror_ast_mutation_boundaries(self):
        """Boundary and mirror parity tests across .antigravity and core_framework decision_router.py."""
        import importlib.util

        modules = []
        for idx, path in enumerate((AG_SCRIPTS / "decision_router.py", CORE_SCRIPTS / "decision_router.py")):
            spec = importlib.util.spec_from_file_location(f"mirror_decision_router_{idx}", str(path))
            self.assertIsNotNone(spec)
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            modules.append(mod)

        for mod in modules:
            self.assertEqual(mod._strip_hypothetical_clauses(""), "")
            self.assertEqual(mod._strip_hypothetical_clauses("   "), "   ")
            self.assertEqual(mod._strip_hypothetical_clauses(None), "")  # type: ignore[arg-type]
            self.assertEqual(mod._strip_hypothetical_clauses(123), "")  # type: ignore[arg-type]
            self.assertIn("oprav chybu", mod._strip_hypothetical_clauses("oprav chybu v kódu").lower())
            self.assertNotIn("opravujeme", mod._strip_hypothetical_clauses("Navrhni gate nebo opravujeme chybu v kódu").lower())

            self.assertEqual(mod._compute_specificity_score(""), 0)
            self.assertEqual(mod._compute_specificity_score(None), 0)  # type: ignore[arg-type]
            self.assertEqual(mod._compute_specificity_score("- one bullet item"), 0)
            self.assertEqual(mod._compute_specificity_score("- first item\n- second item"), 1)

            score2_prompt = "/asw-plan Add billing endpoint in api.py using Postgres"
            score3_prompt = "/asw-plan Add POST /v1/pay in api.py using Postgres"
            self.assertEqual(mod._compute_specificity_score(score2_prompt), 2)
            self.assertEqual(mod._compute_specificity_score(score3_prompt), 3)

            g_s2 = mod.assess_clarification_need(score2_prompt, execution_mode="mode_3")
            self.assertIs(g_s2["needs_clarification"], True)
            self.assertIsNone(g_s2["bypass_reason"])
            self.assertEqual(g_s2["specificity_score"], 2)
            self.assertGreater(g_s2["ambiguity_score"], 0.0)

            g_s3 = mod.assess_clarification_need(score3_prompt, execution_mode="mode_3")
            self.assertIs(g_s3["needs_clarification"], False)
            self.assertEqual(g_s3["bypass_reason"], "sufficient_detail")
            self.assertEqual(g_s3["specificity_score"], 3)
            self.assertEqual(g_s3["missing_dimensions"], [])
            self.assertEqual(g_s3["max_questions"], 0)

            # Empty / None prompt
            g_empty = mod.assess_clarification_need("", execution_mode="mode_1", is_consultation=False)
            self.assertIs(g_empty["needs_clarification"], False)
            self.assertEqual(g_empty["bypass_reason"], "read_only")

            g_none = mod.assess_clarification_need(None, execution_mode="mode_2", is_consultation=False)  # type: ignore[arg-type]
            self.assertIs(g_none["needs_clarification"], False)
            self.assertEqual(g_none["bypass_reason"], "operational_or_restore")

            # Mode 5 underspecified vs Mode 2 vs Mode 0 vs Mode 4
            g_m5 = mod.assess_clarification_need("/asw-goal build platform", execution_mode="mode_5")
            self.assertIs(g_m5["needs_clarification"], True)
            self.assertEqual(g_m5["max_questions"], 3)

            g_m2 = mod.assess_clarification_need("update helper", execution_mode="mode_2")
            self.assertIs(g_m2["needs_clarification"], False)
            self.assertEqual(g_m2["bypass_reason"], "small_clear_change")

            g_m0 = mod.assess_clarification_need("run pytest", execution_mode="mode_0")
            self.assertIs(g_m0["needs_clarification"], False)
            self.assertEqual(g_m0["bypass_reason"], "operational_or_restore")

            g_m4 = mod.assess_clarification_need("rollback", execution_mode="mode_4")
            self.assertIs(g_m4["needs_clarification"], False)
            self.assertEqual(g_m4["bypass_reason"], "operational_or_restore")

            # Forced detailed prompt still has 1..3 missing_dimensions
            g_forced = mod.assess_clarification_need(
                "/asw-clarify Add POST /v1/pay in api.py with JWT, Postgres, p95 < 40ms",
                execution_mode="mode_3",
                recommended_command="asw-clarify",
            )
            self.assertIs(g_forced["needs_clarification"], True)
            self.assertEqual(g_forced["bypass_reason"], "user_forced")
            self.assertGreaterEqual(len(g_forced["missing_dimensions"]), 1)
            self.assertLessEqual(len(g_forced["missing_dimensions"]), 3)
            self.assertEqual(g_forced["max_questions"], 3)


if __name__ == "__main__":
    unittest.main()
