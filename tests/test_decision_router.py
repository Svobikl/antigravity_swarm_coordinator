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

        # 4. Error/missing nvidia-smi fallback
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
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
        self.assertEqual(res_rev["recommended_tier"], "argon_qa_review")

        # Negative case: file path containing /asw/ must NOT trigger slash command override
        res_path = self.router.route_prompt("inspect file plugins/asw/test.py and tell me what it does")
        self.assertNotEqual(res_path["answer_confidence"], 1.0)
        self.assertEqual(res_path["execution_mode"], "mode_1")

    # --- M2: Implicit Multi-Step / UI Feature Prompts (CZ/EN) ---
    def test_m2_implicit_multi_step_and_ui_cz_en(self):
        # Czech complex UI prompt
        cz_prompt = "Uprav výpočet marže v edgerelay, přidej graf na dashboard a otestuj UI"
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
        prompt = "Uprav výpočet marže v edgerelay a otestuj dashboard v prohlížeči"

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
        project_cue = "When updating services/control_plane/api_admin_v1.py in edgerelay"
        project_rule = "Never blindly replace .timestamp in edgerelay admin events"
        res_proj = self.router.classify_lesson_scope(project_cue, project_rule, project="edgerelay")
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
                "--cue", project_cue, "--rule", project_rule, "--project", "edgerelay",
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


if __name__ == "__main__":
    unittest.main()
