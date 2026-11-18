import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestCrossPlatformInstallerAndMacOSRuntime(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_proposer_macos_runtime_discovery(self):
        """proposer.discover_antigravity_runtime() must discover macOS Antigravity.app binaries."""
        ag_dir = str(self.repo_root / ".antigravity")
        if ag_dir not in sys.path:
            sys.path.insert(0, ag_dir)
        from harness2.core import proposer

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            mac_ls = (
                fake_home
                / "Applications"
                / "Antigravity.app"
                / "Contents"
                / "Resources"
                / "app"
                / "extensions"
                / "antigravity"
                / "bin"
                / "language_server_macos_arm"
            )
            mac_ls.parent.mkdir(parents=True, exist_ok=True)
            mac_ls.write_text("#!/bin/sh\n", encoding="utf-8")

            with (
                mock.patch.dict("os.environ", {"HARNESS2_ANTIGRAVITY_CMD": "", "LOCALAPPDATA": str(fake_home / "none")}, clear=False),
                mock.patch("shutil.which", return_value=None),
                mock.patch("pathlib.Path.home", return_value=fake_home),
            ):
                res = proposer.discover_antigravity_runtime()
                self.assertEqual(res["kind"], "language_server")
                self.assertEqual(Path(res["path"]), mac_ls)

    def test_invoke_opus_reviewer_macos_runtime_discovery(self):
        """invoke_opus_reviewer.discover_antigravity_runtime() must detect macOS Antigravity.app."""
        import importlib.util

        script_path = self.repo_root / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"
        spec = importlib.util.spec_from_file_location("invoke_opus_reviewer", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            mac_ls = (
                fake_home
                / "Applications"
                / "Antigravity.app"
                / "Contents"
                / "Resources"
                / "bin"
                / "language_server"
            )
            mac_ls.parent.mkdir(parents=True, exist_ok=True)
            mac_ls.write_text("#!/bin/sh\n", encoding="utf-8")

            with (
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(fake_home / "none")}, clear=False),
                mock.patch("pathlib.Path.home", return_value=fake_home),
            ):
                info = mod.discover_antigravity_runtime(self.repo_root)
                self.assertTrue(info["language_server_found"])
                self.assertIn("Antigravity.app", info["language_server_location"] or "")

    def test_installer_scripts_exist_and_isolated_home_install(self):
        """install.py, install.sh, and install.ps1 must exist and install into an isolated --home-dir."""
        install_py = self.repo_root / "install.py"
        install_sh = self.repo_root / "install.sh"
        install_ps1 = self.repo_root / "install.ps1"

        self.assertTrue(install_py.is_file(), "Missing cross-platform install.py")
        self.assertTrue(install_sh.is_file(), "Missing macOS/Linux install.sh")
        self.assertTrue(install_ps1.is_file(), "Missing Windows install.ps1")

        sh_text = install_sh.read_text(encoding="utf-8")
        self.assertTrue(sh_text.startswith("#!/usr/bin/env bash"), "install.sh must have bash shebang")
        self.assertNotIn("\r\n", sh_text, "install.sh must use LF line endings for macOS/Linux compatibility")

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_target = Path(tmp) / "target_project"
            (fake_target / "edgerelay_child" / ".git").mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(install_py),
                    "--home-dir",
                    str(fake_home),
                    "--target-repo",
                    str(fake_target),
                    "--skip-skills",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, f"install.py failed: {proc.stderr}\n{proc.stdout}")
            self.assertTrue((fake_home / ".gemini" / "GEMINI.md").is_file())
            self.assertTrue((fake_home / ".agents" / "AGENTS.md").is_file())
            self.assertTrue((fake_home / ".gemini" / "config" / "plugins" / "antigravity-swarm" / "agents" / "asw-plan-audit.toml").is_file())
            self.assertTrue((fake_target / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md").is_file())
            self.assertTrue((fake_home / ".gemini" / "scripts" / "memory_manager.py").is_file(), "install.py must install global ~/.gemini/scripts/memory_manager.py")
            self.assertTrue((fake_home / ".gemini" / ".antigravity" / "scripts" / "memory_manager.py").is_file(), "install.py must install global ~/.gemini/.antigravity")
            self.assertTrue((fake_target / "edgerelay_child" / ".antigravity" / "scripts" / "memory_manager.py").is_file(), "install.py must deploy .antigravity/scripts into child git repos")
            # Verify Obsidian Knowledge Vault is automatically enforced & target project indexed
            vault_dir = fake_home / "Documents" / "AgentMemory"
            self.assertTrue((vault_dir / "Home.md").is_file(), "install.py must enforce local Obsidian Vault initialization")
            self.assertTrue((vault_dir / ".obsidian" / "graph.json").is_file(), "install.py must initialize .obsidian/graph.json")
            self.assertTrue((vault_dir / "profile" / "User and Company Profile.md").is_file())
            self.assertTrue((vault_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md").is_file())
            self.assertTrue(
                (vault_dir / "projects" / "target_project" / "target_project.md").is_file(),
                "install.py must index --target-repo into Obsidian Vault projects/",
            )

    def test_rtk_installer_discovery_and_summary(self):
        """Verifies ensure_rtk_installed discovers rtk, reports in summary dict, and provisions .agents/rules."""
        import importlib.util

        install_py = self.repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_mod", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 1. ensure_rtk_installed function exists
        self.assertTrue(hasattr(mod, "ensure_rtk_installed"))

        # 2. Live/mock discovery
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            fake_home.mkdir(parents=True)
            res = mod.ensure_rtk_installed(home_dir=fake_home, attempt_install=False)
            self.assertIn("installed", res)
            self.assertIn("version", res)
            self.assertIn("path", res)

            # Negative test: missing binary when path/env empty
            with (
                mock.patch("shutil.which", return_value=None),
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(fake_home / "nonexistent")}, clear=False),
            ):
                missing_res = mod.ensure_rtk_installed(home_dir=fake_home, attempt_install=False)
                self.assertFalse(missing_res["installed"])
                self.assertIsNone(missing_res["version"])
                self.assertIsNone(missing_res["path"])

            # 3. Test run_install summary and rule provisioning
            fake_target = Path(tmp) / "target"
            fake_target.mkdir(parents=True)
            summary = mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home,
                target_repo=fake_target,
                skip_skills=True,
                skip_vault=True,
                skip_plugin=True,
            )
            self.assertIn("rtk_installed", summary)
            self.assertIn("rtk_version", summary)
            self.assertTrue(summary.get("rtk_skill_mandatory"))

            # Rules must be provisioned
            home_rtk_rule = fake_home / ".agents" / "rules" / "antigravity-rtk-rules.md"
            self.assertTrue(home_rtk_rule.is_file(), f"Missing {home_rtk_rule}")
            self.assertIn("rtk-token-killer", home_rtk_rule.read_text(encoding="utf-8"))

            target_rtk_rule = fake_target / ".agents" / "rules" / "antigravity-rtk-rules.md"
            self.assertTrue(target_rtk_rule.is_file(), f"Missing {target_rtk_rule}")

            # Test --skip-rtk
            skip_summary = mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home,
                skip_skills=True,
                skip_vault=True,
                skip_plugin=True,
                skip_rtk=True,
            )
            self.assertFalse(skip_summary["rtk_installed"])

    def test_decision_router_installer_and_hook_integration(self):
        """Verifies decision_router is installed by install.py and integrated into asw-hook.mjs."""
        import importlib.util
        import json
        import subprocess

        install_py = self.repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_mod", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            fake_home.mkdir(parents=True)
            summary = mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home,
                skip_skills=True,
                skip_vault=True,
                skip_plugin=True,
            )
            # 1. Summary reports decision_router status and hardware device
            self.assertTrue(summary.get("decision_router_installed"), "decision_router_installed must be True")
            self.assertTrue(summary.get("token_economizer_installed"), "token_economizer_installed must be True")
            self.assertTrue(summary.get("decision_model_enabled"), "decision_model_enabled must default to True")
            self.assertIn("decision_router_device", summary)
            self.assertIn(summary["decision_router_device"], ("cpu", "cuda"))

            # 2. Installed script files in ~/.gemini/scripts and decision_config.json
            installed_script = fake_home / ".gemini" / "scripts" / "decision_router.py"
            self.assertTrue(installed_script.is_file(), f"Missing {installed_script}")
            installed_te = fake_home / ".gemini" / "scripts" / "token_economizer.py"
            self.assertTrue(installed_te.is_file(), f"Missing {installed_te}")
            installed_cfg = fake_home / ".gemini" / "decision_config.json"
            self.assertTrue(installed_cfg.is_file(), f"Missing {installed_cfg}")
            cfg_data = json.loads(installed_cfg.read_text(encoding="utf-8"))
            self.assertTrue(cfg_data.get("enabled"))

            # 3. Test disable_decision_model=True (M7)
            dis_summary = mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home,
                skip_skills=True,
                skip_vault=True,
                skip_plugin=True,
                disable_decision_model=True,
            )
            self.assertFalse(dis_summary.get("decision_model_enabled"))
            dis_cfg = json.loads(installed_cfg.read_text(encoding="utf-8"))
            self.assertFalse(dis_cfg.get("enabled"))

        # 4. asw-hook.mjs auto-routing integration when autoDecisionRouter=True
        hook_script = self.repo_root / "plugins" / "antigravity-swarm" / "scripts" / "asw-hook.mjs"
        hook_proc = subprocess.run(
            ["node", str(hook_script)],
            input=json.dumps({
                "invocationNum": 1,
                "autoDecisionRouter": True,
                "lastUserInput": "Uprav výpočet marže v edgerelay, přidej graf na dashboard a otestuj UI",
            }),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(hook_proc.returncode, 0)
        out_data = json.loads(hook_proc.stdout)
        injected = out_data.get("injectSteps", [{}])[0].get("userMessage", "")
        self.assertIn("ASW LOOP MODE ENABLED!", injected)
        self.assertIn("ASW TEST-GUI MODE ENABLED!", injected)

        # 5. Feature-Flag Isolation Gate (M7): when ASW_DECISION_MODEL_ENABLED=0, zero directives emitted
        with mock.patch.dict("os.environ", {"ASW_DECISION_MODEL_ENABLED": "0"}):
            hook_proc_disabled = subprocess.run(
                ["node", str(hook_script)],
                input=json.dumps({
                    "invocationNum": 1,
                    "autoDecisionRouter": True,
                    "lastUserInput": "Uprav výpočet marže v edgerelay, přidej graf na dashboard a otestuj UI",
                }),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(hook_proc_disabled.returncode, 0)
            out_data_dis = json.loads(hook_proc_disabled.stdout)
            self.assertNotIn("injectSteps", out_data_dis)


if __name__ == "__main__":
    unittest.main()
