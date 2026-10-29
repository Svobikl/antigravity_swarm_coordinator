import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestAswTestGui(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent
        self.script_path = self.repo_root / ".antigravity" / "scripts" / "run_gui_test.py"
        self.hook_path = self.repo_root / "plugins" / "antigravity-swarm" / "scripts" / "asw-hook.mjs"

    def test_asw_test_gui_skill_and_hook_standalone_and_combined(self):
        """asw-test-gui skill exists and asw-hook.mjs triggers it standalone or combined with asw-loop, never automatically."""
        for skill_root in (
            self.repo_root / "core_framework" / "skills",
            self.repo_root / ".antigravity" / "skills",
            self.repo_root / "plugins" / "antigravity-swarm" / "skills",
        ):
            skill_md = skill_root / "asw-test-gui" / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"Missing {skill_md}")
            txt = skill_md.read_text(encoding="utf-8")
            self.assertTrue(txt.startswith("---\nname: asw-test-gui\ndescription: "))

        # 1. Standalone asw-test-gui prompt
        p_standalone = subprocess.run(
            ["node", str(self.hook_path)],
            input=json.dumps({"prompt": "asw-test-gui otestuj poslední implementaci na localhostu"}),
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
        )
        self.assertEqual(p_standalone.returncode, 0, p_standalone.stderr)
        data_standalone = json.loads(p_standalone.stdout)
        msg_standalone = data_standalone["injectSteps"][0]["userMessage"]
        self.assertIn("ASW TEST-GUI MODE ENABLED", msg_standalone)

        # 2. Combined asw-loop + asw-test-gui prompt
        p_combined = subprocess.run(
            ["node", str(self.hook_path)],
            input=json.dumps({"prompt": "asw-loop implementuj dashboard a asw-test-gui na závěr"}),
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
        )
        self.assertEqual(p_combined.returncode, 0, p_combined.stderr)
        data_combined = json.loads(p_combined.stdout)
        msg_combined = data_combined["injectSteps"][0]["userMessage"]
        self.assertIn("ASW LOOP MODE ENABLED", msg_combined)
        self.assertIn("ASW TEST-GUI MODE ENABLED", msg_combined)

        # 3. Standard asw-loop WITHOUT asw-test-gui must NOT inject ASW TEST-GUI MODE ENABLED
        p_loop_only = subprocess.run(
            ["node", str(self.hook_path)],
            input=json.dumps({"prompt": "asw-loop implementuj backend endpoint"}),
            capture_output=True,
            text=True,
            cwd=str(self.repo_root),
        )
        self.assertEqual(p_loop_only.returncode, 0, p_loop_only.stderr)
        data_loop_only = json.loads(p_loop_only.stdout)
        msg_loop_only = data_loop_only["injectSteps"][0]["userMessage"]
        self.assertIn("ASW LOOP MODE ENABLED", msg_loop_only)
        self.assertNotIn("ASW TEST-GUI MODE ENABLED", msg_loop_only)

    def test_run_gui_test_web_localhost_happy_and_negative_edge(self):
        """run_gui_test.py starts a localhost web server, verifies DOM/text/selectors, and rejects missing UI elements."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            web_dir = tmp_path / "web_root"
            web_dir.mkdir(parents=True)
            (web_dir / "index.html").write_text(
                "<!DOCTYPE html><html><head><title>EdgeRelay Admin</title></head>"
                "<body><h1>EdgeRelay Live GUI</h1><button id='btn-sync'>Sync Nodes</button></body></html>",
                encoding="utf-8",
            )
            port = _find_free_port()
            report_good = tmp_path / "gui-report-good.md"
            start_cmd = f'"{sys.executable}" -m http.server {port} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'

            # Happy path
            proc_ok = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd,
                    "--url",
                    f"http://127.0.0.1:{port}/index.html",
                    "--assert-text",
                    "EdgeRelay Live GUI",
                    "--assert-selector",
                    "button",
                    "--output",
                    str(report_good),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertEqual(proc_ok.returncode, 0, f"Web GUI test failed: {proc_ok.stderr}\n{proc_ok.stdout}")
            self.assertTrue(report_good.is_file())
            self.assertIn("Verdict: GUI_VERIFIED", report_good.read_text(encoding="utf-8"))

            # Negative path: assert text that does NOT exist in the rendered GUI
            port2 = _find_free_port()
            start_cmd2 = f'"{sys.executable}" -m http.server {port2} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'
            report_bad = tmp_path / "gui-report-bad.md"
            proc_bad = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd2,
                    "--url",
                    f"http://127.0.0.1:{port2}/index.html",
                    "--assert-text",
                    "NonExistentComponent_999",
                    "--output",
                    str(report_bad),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertNotEqual(proc_bad.returncode, 0)
            self.assertTrue(report_bad.is_file())
            self.assertIn("Verdict: GUI_FAILED", report_bad.read_text(encoding="utf-8"))

    def test_run_gui_test_native_app_happy_and_crash_reject(self):
        """run_gui_test.py --mode native verifies healthy native GUI startup and rejects crashing GUI processes."""
        self.assertTrue(self.script_path.is_file(), f"Missing {self.script_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            healthy_app = tmp_path / "healthy_gui.py"
            healthy_app.write_text(
                "import time, sys\nsys.stdout.write('WINDOW_INITIALIZED_OK\\n')\nsys.stdout.flush()\ntime.sleep(3)\n",
                encoding="utf-8",
            )
            crashing_app = tmp_path / "crashing_gui.py"
            crashing_app.write_text(
                "import sys\nsys.stderr.write('Traceback: Segmentation fault in GUI renderer\\n')\nsys.exit(1)\n",
                encoding="utf-8",
            )

            report_native_ok = tmp_path / "native-ok.md"
            p_ok = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "native",
                    "--app-cmd",
                    f'"{sys.executable}" "{healthy_app.as_posix()}"',
                    "--wait-seconds",
                    "1.0",
                    "--assert-text",
                    "WINDOW_INITIALIZED_OK",
                    "--output",
                    str(report_native_ok),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertEqual(p_ok.returncode, 0, f"Healthy native GUI test failed: {p_ok.stderr}\n{p_ok.stdout}")
            self.assertIn("Verdict: GUI_VERIFIED", report_native_ok.read_text(encoding="utf-8"))

            report_native_bad = tmp_path / "native-bad.md"
            p_bad = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "native",
                    "--app-cmd",
                    f'"{sys.executable}" "{crashing_app.as_posix()}"',
                    "--wait-seconds",
                    "1.0",
                    "--output",
                    str(report_native_bad),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertNotEqual(p_bad.returncode, 0)
            self.assertIn("Verdict: GUI_FAILED", report_native_bad.read_text(encoding="utf-8"))

    def test_run_gui_test_rejects_hui_error_card_and_configuration_error_and_forbid_flags(self):
        """Reproduces Home Assistant Step 853: run_gui_test.py must automatically reject <hui-error-card>, 'Configuration error', and custom --forbid-text / --forbid-selector."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            web_dir = tmp_path / "ha_web"
            web_dir.mkdir(parents=True)

            # Page 1: Contains <hui-error-card> and 'Configuration error' (even though HTTP is 200 and heading exists)
            (web_dir / "lovelace.html").write_text(
                "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
                "<h1>Chytrý dům Klabava</h1>"
                "<hui-error-card>Configuration error: Custom element doesn't exist: klabava-cockpit-card</hui-error-card>"
                "</body></html>",
                encoding="utf-8",
            )
            # Page 2: Healthy HTML but contains a forbidden placeholder ('0 USD' / '.stale-banner') tested via --forbid-text / --forbid-selector
            (web_dir / "dashboard.html").write_text(
                "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
                "<h1>StrataRelay Dashboard</h1>"
                "<div class='stale-banner'>Balance: 0 USD</div>"
                "</body></html>",
                encoding="utf-8",
            )

            port1 = _find_free_port()
            start_cmd1 = f'"{sys.executable}" -m http.server {port1} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'
            report_ha = tmp_path / "ha-error-report.md"

            proc_ha = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd1,
                    "--url",
                    f"http://127.0.0.1:{port1}/lovelace.html",
                    "--assert-text",
                    "Chytrý dům Klabava",
                    "--output",
                    str(report_ha),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertNotEqual(
                proc_ha.returncode,
                0,
                "Page containing <hui-error-card> / 'Configuration error' must fail GUI verification automatically!",
            )
            ha_report_text = report_ha.read_text(encoding="utf-8")
            self.assertIn("Verdict: GUI_FAILED", ha_report_text)
            self.assertTrue(
                "hui-error-card" in ha_report_text.lower() or "configuration error" in ha_report_text.lower()
            )

            port2 = _find_free_port()
            start_cmd2 = f'"{sys.executable}" -m http.server {port2} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'
            report_forbid = tmp_path / "forbid-report.md"
            proc_forbid = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd2,
                    "--url",
                    f"http://127.0.0.1:{port2}/dashboard.html",
                    "--assert-text",
                    "StrataRelay Dashboard",
                    "--forbid-text",
                    "Balance: 0 USD",
                    "--forbid-selector",
                    ".stale-banner",
                    "--output",
                    str(report_forbid),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertNotEqual(proc_forbid.returncode, 0)
            forbid_text = report_forbid.read_text(encoding="utf-8")
            self.assertIn("Verdict: GUI_FAILED", forbid_text)

    def test_run_gui_test_assert_asset_version_detects_stale_cached_module_url(self):
        """Reproduces Home Assistant Step 896 (Oct 28): container served stale extra_module_url '?v=20261026_fixed' instead of '?v=20261028_hist_v2'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            web_dir = tmp_path / "ha_cache_web"
            (web_dir / "local").mkdir(parents=True)
            (web_dir / "local" / "energy-cockpit-card.js").write_text(
                "window.__cockpit_loaded = true;\n",
                encoding="utf-8",
            )
            (web_dir / "index.html").write_text(
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<script type='module' src='/local/energy-cockpit-card.js?v=20261026_fixed'></script>"
                "</head><body><h1>Chytrý dům</h1></body></html>",
                encoding="utf-8",
            )

            port = _find_free_port()
            start_cmd = f'"{sys.executable}" -m http.server {port} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'
            report_stale = tmp_path / "stale-asset-report.md"

            # Negative case: expecting new version 20261028_hist_v2, but server still serves 20261026_fixed
            proc_stale = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd,
                    "--url",
                    f"http://127.0.0.1:{port}/index.html",
                    "--assert-asset-version",
                    "20261028_hist_v2",
                    "--output",
                    str(report_stale),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertNotEqual(
                proc_stale.returncode,
                0,
                "--assert-asset-version must fail when live HTML serves stale module URL!",
            )
            self.assertIn("Verdict: GUI_FAILED", report_stale.read_text(encoding="utf-8"))

            # Positive case: matching asset version 20261026_fixed passes
            port_ok = _find_free_port()
            start_cmd_ok = f'"{sys.executable}" -m http.server {port_ok} --bind 127.0.0.1 --directory "{web_dir.as_posix()}"'
            report_ok = tmp_path / "fresh-asset-report.md"
            proc_ok = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    "--mode",
                    "web",
                    "--start-cmd",
                    start_cmd_ok,
                    "--url",
                    f"http://127.0.0.1:{port_ok}/index.html",
                    "--assert-asset-version",
                    "20261026_fixed",
                    "--output",
                    str(report_ok),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            self.assertEqual(proc_ok.returncode, 0)
            self.assertIn("Verdict: GUI_VERIFIED", report_ok.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
