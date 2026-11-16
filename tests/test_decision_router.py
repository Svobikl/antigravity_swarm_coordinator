import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_SCRIPTS = REPO_ROOT / "core_framework" / "scripts"
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

        # 2. CLI --disable and --enable flags
        script_path = CORE_SCRIPTS / "decision_router.py"
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


if __name__ == "__main__":
    unittest.main()
