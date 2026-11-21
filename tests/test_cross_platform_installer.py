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
            (fake_target / "acme_analytics_child" / ".git").mkdir(parents=True, exist_ok=True)
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
            self.assertTrue((fake_target / "acme_analytics_child" / ".antigravity" / "scripts" / "memory_manager.py").is_file(), "install.py must deploy .antigravity/scripts into child git repos")
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
                "lastUserInput": "Uprav výpočet marže v acme_analytics, přidej graf na dashboard a otestuj UI",
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
                    "lastUserInput": "Uprav výpočet marže v acme_analytics, přidej graf na dashboard a otestuj UI",
                }),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(hook_proc_disabled.returncode, 0)
            out_data_dis = json.loads(hook_proc_disabled.stdout)
            self.assertNotIn("injectSteps", out_data_dis)

    def test_rtk_macos_tarball_fallback_and_isolation(self):
        """M1: ensure_rtk_installed isolates host paths and falls back to macOS GitHub tarball when brew fails."""
        import importlib.util
        import io
        import tarfile

        install_py = self.repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_mod_m1", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            payload = b"#!/bin/sh\necho rtk 0.23.0\n"
            ti = tarfile.TarInfo("rtk")
            ti.size = len(payload)
            ti.mode = 0o755
            tf.addfile(ti, io.BytesIO(payload))
        tar_bytes = buf.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            fake_home.mkdir(parents=True)
            expected_bin = fake_home / ".local" / "bin" / "rtk"

            seen_cmds: list[tuple[list[str], int | None]] = []

            def fake_run(cmd, *args, **kwargs):
                seen_cmds.append((list(cmd), kwargs.get("timeout")))
                if cmd and cmd[0] == "brew":
                    return subprocess.CompletedProcess(cmd, 1, "", "brew unavailable")
                if cmd and Path(cmd[0]) == expected_bin:
                    return subprocess.CompletedProcess(cmd, 0, "rtk 0.23.0\n", "")
                return subprocess.CompletedProcess(cmd, 1, "", "")

            class _FakeResp:
                def __init__(self, data: bytes):
                    self._data = data

                def read(self) -> bytes:
                    return self._data

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            with (
                mock.patch("platform.system", return_value="Darwin"),
                mock.patch("platform.machine", return_value="arm64"),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("urllib.request.urlopen", return_value=_FakeResp(tar_bytes)) as mock_url,
            ):
                res = mod.ensure_rtk_installed(home_dir=fake_home, attempt_install=True)

            self.assertTrue(res["installed"])
            self.assertEqual(res["version"], "0.23.0")
            self.assertEqual(Path(str(res["path"])), expected_bin)
            self.assertTrue(expected_bin.is_file())
            mock_url.assert_called_once()
            self.assertIn("rtk-aarch64-apple-darwin.tar.gz", str(mock_url.call_args[0][0]))
            brew_calls = [t for c, t in seen_cmds if c and c[0] == "brew"]
            self.assertEqual(brew_calls, [120])

            # Negative case: tarball download fails when binary still missing
            expected_bin.unlink()
            with (
                mock.patch("platform.system", return_value="Darwin"),
                mock.patch("platform.machine", return_value="x86_64"),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("urllib.request.urlopen", side_effect=OSError("offline")),
            ):
                fail_res = mod.ensure_rtk_installed(home_dir=fake_home, attempt_install=True)
            self.assertFalse(fail_res["installed"])
            self.assertIsNone(fail_res["path"])

    def test_clean_skills_backs_up_custom_skills(self):
        """M3: --clean-skills backs up pruned non-catalog skills into .gemini/antigravity-backup/skills-backup/."""
        import importlib.util

        install_py = self.repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_mod_m3", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            custom_skill = fake_home / ".gemini" / "config" / "skills" / "custom-user-skill"
            custom_skill.mkdir(parents=True, exist_ok=True)
            (custom_skill / "SKILL.md").write_text("# Custom User Skill\n", encoding="utf-8")

            summary = mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home,
                skip_prompt=True,
                skip_plugin=True,
                skip_vault=True,
                skip_rtk=True,
                skip_chub=True,
                clean_skills=True,
            )

            self.assertGreaterEqual(summary["skills_cleaned"], 1)
            self.assertFalse(custom_skill.exists(), "Non-catalog skill must be pruned from active skills dir")
            backup_file = (
                fake_home
                / ".gemini"
                / "antigravity-backup"
                / "skills-backup"
                / "config"
                / "custom-user-skill"
                / "SKILL.md"
            )
            self.assertTrue(backup_file.is_file(), f"Pruned skill must be backed up to {backup_file}")
            self.assertIn("Custom User Skill", backup_file.read_text(encoding="utf-8"))

    def test_ensure_laya_installed_and_no_repo_config_mutation(self):
        """M2: ensure_laya_installed provisions Py3.12 venv, sitecustomize, laya_daemon.py, Darwin plist, without mutating repo decision_config.json."""
        import importlib.util
        import json

        install_py = self.repo_root / "install.py"
        spec = importlib.util.spec_from_file_location("installer_mod_m2", install_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        self.assertTrue(hasattr(mod, "ensure_laya_installed"), "install.py must define ensure_laya_installed")

        repo_cfg = self.repo_root / ".antigravity" / "decision_config.json"
        repo_cfg_before = repo_cfg.read_bytes()

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "fake_home"
            fake_home.mkdir(parents=True)
            venv_dir = fake_home / ".gemini" / "laya-venv"
            venv_py = venv_dir / "bin" / "python"
            site_pkgs = venv_dir / "lib" / "python3.12" / "site-packages"

            recorded_cmds: list[list[str]] = []

            def fake_run(cmd, *args, **kwargs):
                cmd_list = [str(c) for c in cmd]
                recorded_cmds.append(cmd_list)
                if len(cmd_list) >= 3 and cmd_list[0].endswith("uv") and cmd_list[1] == "venv":
                    venv_py.parent.mkdir(parents=True, exist_ok=True)
                    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
                    site_pkgs.mkdir(parents=True, exist_ok=True)
                    return subprocess.CompletedProcess(cmd_list, 0, "", "")
                if cmd_list[0] == str(venv_py) and "-c" in cmd_list:
                    code_arg = cmd_list[cmd_list.index("-c") + 1]
                    if "sysconfig" in code_arg:
                        return subprocess.CompletedProcess(cmd_list, 0, str(site_pkgs) + "\n", "")
                    if "import laya" in code_arg:
                        return subprocess.CompletedProcess(cmd_list, 0, "", "")
                return subprocess.CompletedProcess(cmd_list, 0, "", "")

            with (
                mock.patch("platform.system", return_value="Darwin"),
                mock.patch("shutil.which", side_effect=lambda x: "/usr/local/bin/uv" if x == "uv" else None),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                laya_res = mod.ensure_laya_installed(
                    home_dir=fake_home,
                    attempt_install=True,
                    disable_decision_model=False,
                )

            self.assertTrue(laya_res["installed"])
            self.assertTrue(laya_res["venv_installed"])
            self.assertTrue(
                any(c[0].endswith("uv") and c[1] == "venv" and "--python" in c and "3.12" in c for c in recorded_cmds),
                f"Expected uv venv --python 3.12 call, got: {recorded_cmds}",
            )
            self.assertTrue(
                any("pip" in c and "install" in c and "laya" in c and "fastapi" in c for c in recorded_cmds),
                f"Expected pip install laya/fastapi call, got: {recorded_cmds}",
            )
            self.assertFalse(
                any(c[0] == "launchctl" for c in recorded_cmds),
                "launchctl must NOT run when home_dir != Path.home()",
            )

            daemon_py = venv_dir / "laya_daemon.py"
            self.assertTrue(daemon_py.is_file(), f"Missing {daemon_py}")
            daemon_text = daemon_py.read_text(encoding="utf-8")
            self.assertIn("create_app", daemon_text)
            self.assertIn('"/predict"', daemon_text)
            self.assertIn("router.predict", daemon_text)
            self.assertIn("8765", daemon_text)

            sitecust = site_pkgs / "sitecustomize.py"
            self.assertTrue(sitecust.is_file(), f"Missing {sitecust}")
            sitecust_text = sitecust.read_text(encoding="utf-8")
            self.assertIn("torch.compile", sitecust_text)
            self.assertIn("(3, 12)", sitecust_text)
            self.assertIn("2.2.", sitecust_text)

            plist = fake_home / "Library" / "LaunchAgents" / "com.antigravity.laya-daemon.plist"
            self.assertTrue(plist.is_file(), f"Missing {plist}")
            plist_text = plist.read_text(encoding="utf-8")
            self.assertIn("com.antigravity.laya-daemon", plist_text)
            self.assertIn(str(daemon_py), plist_text)

            # Verify run_install sets use_daemon=True and detects venv laya_sdk_installed even if sys.executable lacks laya
            orig_import = __import__

            def mock_import(name, *args, **kwargs):
                if name == "laya":
                    raise ImportError("no laya in host py 3.14")
                return orig_import(name, *args, **kwargs)

            with (
                mock.patch("platform.system", return_value="Darwin"),
                mock.patch("shutil.which", return_value=None),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("builtins.__import__", side_effect=mock_import),
                mock.patch("pathlib.Path.home", return_value=fake_home),
            ):
                summary = mod.run_install(
                    repo_root=self.repo_root,
                    home_dir=fake_home,
                    skip_prompt=True,
                    skip_skills=True,
                    skip_plugin=True,
                    skip_vault=True,
                    skip_rtk=True,
                    skip_chub=True,
                    install_laya=False,
                )

            self.assertTrue(summary["laya_sdk_installed"])
            home_cfg = json.loads((fake_home / ".gemini" / "decision_config.json").read_text(encoding="utf-8"))
            self.assertTrue(home_cfg.get("use_daemon"))
            self.assertEqual(home_cfg.get("server_url"), "http://127.0.0.1:8765")
            self.assertEqual(repo_cfg.read_bytes(), repo_cfg_before, "run_install must never mutate repo decision_config.json")

            # Negative test: disable_decision_model=True skips Laya install and disables config
            fake_home_dis = Path(tmp) / "fake_home_dis"
            fake_home_dis.mkdir(parents=True)
            dis_res = mod.ensure_laya_installed(
                home_dir=fake_home_dis,
                attempt_install=True,
                disable_decision_model=True,
            )
            self.assertFalse(dis_res["installed"])
            self.assertFalse((fake_home_dis / ".gemini" / "laya-venv" / "laya_daemon.py").exists())

            # Negative test: when laya-venv pip/import fails (venv_laya_ok=False), use_daemon=False and no plist created
            fake_home_fail = Path(tmp) / "fake_home_fail"
            fake_home_fail.mkdir(parents=True)
            fail_venv_py = fake_home_fail / ".gemini" / "laya-venv" / "bin" / "python"
            fail_site_pkgs = fake_home_fail / ".gemini" / "laya-venv" / "lib" / "python3.12" / "site-packages"

            def fake_run_fail(cmd, *args, **kwargs):
                cmd_list = [str(c) for c in cmd]
                if len(cmd_list) >= 3 and cmd_list[0].endswith("uv") and cmd_list[1] == "venv":
                    fail_venv_py.parent.mkdir(parents=True, exist_ok=True)
                    fail_venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
                    fail_site_pkgs.mkdir(parents=True, exist_ok=True)
                    return subprocess.CompletedProcess(cmd_list, 0, "", "")
                if cmd_list[0] == str(fail_venv_py) and "-c" in cmd_list:
                    code_arg = cmd_list[cmd_list.index("-c") + 1]
                    if "sysconfig" in code_arg:
                        return subprocess.CompletedProcess(cmd_list, 0, str(fail_site_pkgs) + "\n", "")
                    if "import laya" in code_arg:
                        return subprocess.CompletedProcess(cmd_list, 1, "", "ModuleNotFoundError: No module named 'laya'")
                return subprocess.CompletedProcess(cmd_list, 1, "", "pip install failed offline")

            with (
                mock.patch("platform.system", return_value="Darwin"),
                mock.patch("shutil.which", side_effect=lambda x: "/usr/local/bin/uv" if x == "uv" else None),
                mock.patch("subprocess.run", side_effect=fake_run_fail),
            ):
                fail_res = mod.ensure_laya_installed(
                    home_dir=fake_home_fail,
                    attempt_install=True,
                    disable_decision_model=False,
                )

            self.assertFalse(fail_res["venv_installed"])
            self.assertFalse(fail_res["use_daemon"])
            self.assertIsNone(fail_res["plist_path"])
            self.assertFalse(
                (fake_home_fail / "Library" / "LaunchAgents" / "com.antigravity.laya-daemon.plist").exists(),
                "Darwin LaunchAgent plist must NOT be created when venv import laya fails",
            )

            # Config preservation test: existing custom keys in ~/.gemini/decision_config.json survive run_install()
            fake_home_cfg = Path(tmp) / "fake_home_cfg"
            (fake_home_cfg / ".gemini").mkdir(parents=True, exist_ok=True)
            user_cfg_path = fake_home_cfg / ".gemini" / "decision_config.json"
            user_cfg_path.write_text(
                json.dumps(
                    {
                        "use_daemon": True,
                        "cpu_threads": 4,
                        "server_url": "http://127.0.0.1:8765",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            mod.run_install(
                repo_root=self.repo_root,
                home_dir=fake_home_cfg,
                skip_prompt=True,
                skip_skills=True,
                skip_plugin=True,
                skip_vault=True,
                skip_rtk=True,
                skip_chub=True,
                install_laya=False,
            )
            preserved_cfg = json.loads(user_cfg_path.read_text(encoding="utf-8"))
            self.assertTrue(preserved_cfg.get("use_daemon"))
            self.assertEqual(preserved_cfg.get("cpu_threads"), 4)
            self.assertEqual(preserved_cfg.get("server_url"), "http://127.0.0.1:8765")


if __name__ == "__main__":
    unittest.main()
