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


if __name__ == "__main__":
    unittest.main()
