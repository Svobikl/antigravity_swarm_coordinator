import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
REA_BRIDGE_SCRIPT = REPO_ROOT / ".antigravity" / "scripts" / "rea_bridge.py"
MIRROR_REA_BRIDGE_SCRIPT = REPO_ROOT / "core_framework" / "scripts" / "rea_bridge.py"


def _load_rea_bridge():
    spec = importlib.util.spec_from_file_location("rea_bridge", REA_BRIDGE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {REA_BRIDGE_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_realistic_electron_payload(module_count: int = 20) -> dict:
    modules = []
    for idx in range(module_count):
        if idx == 0:
            name = "main.js"
            kind = "electron_main"
        elif idx == 1:
            name = "preload.js"
            kind = "electron_preload"
        elif idx == 2:
            name = "renderer.js"
            kind = "electron_renderer"
        else:
            name = f"src/feature_{idx:02d}/controller.js"
            kind = "cjs_module"

        row = {
            "id": f"mod-{idx:03d}",
            "path": name,
            "kind": kind,
            "exports_count": (idx % 5) + 1,
            "size_bytes": 1024 + idx * 128,
            # Simulate bulky raw source/AST metadata present in full REA JSON evidence
            "raw_ast_excerpt": (
                f"function init_{idx}(ipcMain, contextBridge) {{ "
                + ("/* node_ast_padding */ " * 12)
                + "return true; }"
            ),
        }
        if idx == 1:
            row["uses_context_bridge"] = True
        modules.append(row)

    ipc_boundaries = [
        {
            "channel": "app:get-version",
            "direction": "renderer->main",
            "api": "contextBridge.exposeInMainWorld('electronAPI', ...)",
            "file": "preload.js",
            "handler": "ipcMain.handle",
        },
        {
            "channel": "workspace:open-project",
            "direction": "renderer->main",
            "api": "contextBridge.exposeInMainWorld('electronAPI', ...)",
            "file": "preload.js",
            "handler": "ipcMain.handle",
        },
        {
            "channel": "sync:status-updated",
            "direction": "main->renderer",
            "api": "webContents.send",
            "file": "main.js",
            "handler": "ipcRenderer.on",
        },
        {
            "channel": "settings:save-preferences",
            "direction": "renderer->main",
            "api": "contextBridge.exposeInMainWorld('electronAPI', ...)",
            "file": "preload.js",
            "handler": "ipcMain.handle",
        },
        {
            "channel": "auth:session-state",
            "direction": "renderer->main",
            "api": "contextBridge.exposeInMainWorld('authBridge', ...)",
            "file": "preload.js",
            "handler": "ipcMain.handle",
        },
    ]

    imports = [
        {"source": "main.js", "target": "electron", "symbol": "app,BrowserWindow,ipcMain"},
        {"source": "preload.js", "target": "electron", "symbol": "contextBridge,ipcRenderer"},
        {"source": "renderer.js", "target": "./store", "symbol": "createStore"},
        {"source": "main.js", "target": "path", "symbol": "join"},
        {"source": "main.js", "target": "fs", "symbol": "readFileSync"},
    ]

    checks = [
        {"check": "contextIsolation", "status": "pass", "detail": "contextIsolation=true in BrowserWindow"},
        {"check": "nodeIntegration", "status": "pass", "detail": "nodeIntegration=false in BrowserWindow"},
        {"check": "sandbox", "status": "warn", "detail": "sandbox not explicitly pinned in secondary window"},
        {"check": "preload_bridge", "status": "pass", "detail": "contextBridge exposes 4 typed methods"},
    ]

    return {
        "schema_version": "1.0",
        "command": "analyze-javascript-application",
        "artifact": "/tmp/mock-electron-app",
        "normalized_result": {
            "modules": modules,
            "imports": imports,
            "electron": {
                "boundaries": ipc_boundaries,
                "context_isolation": True,
                "node_integration": False,
            },
            "checks": checks,
            "exports": [
                {"module": "preload.js", "symbol": "electronAPI.getVersion", "kind": "contextBridge"},
                {"module": "preload.js", "symbol": "electronAPI.openProject", "kind": "contextBridge"},
                {"module": "preload.js", "symbol": "electronAPI.savePreferences", "kind": "contextBridge"},
            ],
            "limitations": [
                "Dynamic eval expressions are summarized statically without runtime execution."
            ],
        },
    }


class TestReaBridge(unittest.TestCase):
    """RED-to-GREEN unit, boundary, negative, and subprocess tests for rea_bridge.py (M1..M3)."""

    def test_m1_satisfies_rea_node_range_exact_boundaries(self):
        rb = _load_rea_bridge()
        self.assertEqual(rb.REA_NODE_ENGINE_RANGE, "^22.23.4 || ^24.22.1 || >=26.12.1")

        # Exact M1 matrix
        self.assertFalse(rb.satisfies_rea_node_range("26.12.0"))
        self.assertTrue(rb.satisfies_rea_node_range("26.12.1"))
        self.assertTrue(rb.satisfies_rea_node_range("24.22.3"))
        self.assertFalse(rb.satisfies_rea_node_range("24.22.0"))
        self.assertTrue(rb.satisfies_rea_node_range("22.23.4"))
        self.assertFalse(rb.satisfies_rea_node_range("23.5.0"))
        self.assertFalse(rb.satisfies_rea_node_range("24.22.3-rc.1"))

        # Leading v, whitespace, boundaries, and negative/malformed cases
        self.assertTrue(rb.satisfies_rea_node_range("v24.22.1"))
        self.assertTrue(rb.satisfies_rea_node_range("  v26.12.1  "))
        self.assertTrue(rb.satisfies_rea_node_range("v27.0.0"))
        self.assertTrue(rb.satisfies_rea_node_range("22.24.0"))
        self.assertFalse(rb.satisfies_rea_node_range("v22.23.3"))
        self.assertFalse(rb.satisfies_rea_node_range("25.0.0"))
        self.assertFalse(rb.satisfies_rea_node_range("24.22"))
        self.assertFalse(rb.satisfies_rea_node_range("24.22.1+build.1"))
        self.assertFalse(rb.satisfies_rea_node_range("vv24.22.3"))
        self.assertFalse(rb.satisfies_rea_node_range(""))
        self.assertFalse(rb.satisfies_rea_node_range("not-a-version"))
        self.assertFalse(rb.satisfies_rea_node_range(None))

    def test_discover_rea_runtime_isolated_and_precedence(self):
        rb = _load_rea_bridge()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_home = Path(tmp).resolve()

            # 1. Empty isolated home_dir -> must not pick up system PATH 'rea'
            empty_res = rb.discover_rea_runtime(home_dir=tmp_home)
            self.assertFalse(empty_res["available"])
            self.assertIsNone(empty_res["command"])
            self.assertIsNone(empty_res["rea_version"])
            self.assertEqual(empty_res["source"], "unavailable")

            # 2. Local bin wrapper under isolated home_dir
            local_bin = tmp_home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            is_win = os.name == "nt"
            local_wrapper = local_bin / ("rea.cmd" if is_win else "rea")
            if is_win:
                local_wrapper.write_text("@echo off\r\necho 0.9.1\r\n", encoding="utf-8", newline="")
            else:
                local_wrapper.write_text("#!/bin/sh\necho 0.9.1\n", encoding="utf-8", newline="\n")
                local_wrapper.chmod(local_wrapper.stat().st_mode | stat.S_IEXEC)

            res_local = rb.discover_rea_runtime(home_dir=tmp_home)
            self.assertTrue(res_local["available"])
            self.assertEqual(res_local["rea_version"], "0.9.1")
            self.assertEqual(res_local["source"], "local_bin")

            # 3. Managed runtime launcher takes precedence over local_bin
            managed_bin = tmp_home / ".gemini" / "rea-runtime" / "bin"
            managed_bin.mkdir(parents=True)
            managed_wrapper = managed_bin / ("rea.cmd" if is_win else "rea")
            if is_win:
                managed_wrapper.write_text("@echo off\r\necho 1.2.0\r\n", encoding="utf-8", newline="")
            else:
                managed_wrapper.write_text("#!/bin/sh\necho 1.2.0\n", encoding="utf-8", newline="\n")
                managed_wrapper.chmod(managed_wrapper.stat().st_mode | stat.S_IEXEC)

            res_managed = rb.discover_rea_runtime(home_dir=tmp_home)
            self.assertTrue(res_managed["available"])
            self.assertEqual(res_managed["rea_version"], "1.2.0")
            self.assertEqual(res_managed["source"], "managed_runtime")
            self.assertEqual(res_managed["command"], [str(managed_wrapper)])

            # 4. Managed node_exe + rea.mjs fallback when launcher is removed
            managed_wrapper.unlink()
            node_exe = (
                tmp_home / ".gemini" / "rea-runtime" / "node" / "node.exe"
                if is_win
                else tmp_home / ".gemini" / "rea-runtime" / "node" / "bin" / "node"
            )
            rea_mjs = (
                tmp_home
                / ".gemini"
                / "rea-runtime"
                / "pkg"
                / "node_modules"
                / "rea-agents"
                / "scripts"
                / "rea.mjs"
            )
            node_exe.parent.mkdir(parents=True, exist_ok=True)
            rea_mjs.parent.mkdir(parents=True, exist_ok=True)
            rea_mjs.write_text("// mock rea.mjs\n", encoding="utf-8", newline="\n")
            if is_win:
                node_exe.write_text("@echo off\r\necho 1.3.5\r\n", encoding="utf-8", newline="")
            else:
                node_exe.write_text("#!/bin/sh\necho 1.3.5\n", encoding="utf-8", newline="\n")
                node_exe.chmod(node_exe.stat().st_mode | stat.S_IEXEC)

            res_node_mjs = rb.discover_rea_runtime(home_dir=tmp_home)
            self.assertTrue(res_node_mjs["available"])
            self.assertEqual(res_node_mjs["rea_version"], "1.3.5")
            self.assertEqual(res_node_mjs["source"], "managed_runtime")
            self.assertEqual(res_node_mjs["command"], [str(node_exe), str(rea_mjs)])

    def test_discover_rea_runtime_blocks_incompatible_host_node_npx(self):
        rb = _load_rea_bridge()

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)

            def fake_which(cmd_name: str):
                if cmd_name == "node":
                    return "/usr/local/bin/node"
                if cmd_name == "npx":
                    return "/usr/local/bin/npx"
                return None

            def fake_run(cmd, **kwargs):
                cp = mock.Mock()
                if cmd[0] == "/usr/local/bin/node" and "--version" not in cmd and "-v" in cmd:
                    cp.returncode = 0
                    cp.stdout = "v26.12.0\n"
                    cp.stderr = ""
                    return cp
                cp.returncode = 0
                cp.stdout = "1.4.0\n"
                cp.stderr = ""
                return cp

            with (
                mock.patch.object(rb.Path, "home", return_value=fake_home),
                mock.patch.object(rb.shutil, "which", side_effect=fake_which),
                mock.patch.object(rb.subprocess, "run", side_effect=fake_run),
            ):
                res_bad = rb.discover_rea_runtime()
                self.assertFalse(res_bad["available"])
                self.assertEqual(res_bad["host_node_version"], "v26.12.0")
                self.assertFalse(res_bad["host_node_compatible"])
                self.assertEqual(res_bad["source"], "unavailable")

            def fake_run_good(cmd, **kwargs):
                cp = mock.Mock()
                if cmd[0] == "/usr/local/bin/node" and "-v" in cmd:
                    cp.returncode = 0
                    cp.stdout = "v24.22.3\n"
                    cp.stderr = ""
                    return cp
                cp.returncode = 0
                cp.stdout = "1.4.2\n"
                cp.stderr = ""
                return cp

            with (
                mock.patch.object(rb.Path, "home", return_value=fake_home),
                mock.patch.object(rb.shutil, "which", side_effect=fake_which),
                mock.patch.object(rb.subprocess, "run", side_effect=fake_run_good),
            ):
                res_good = rb.discover_rea_runtime()
                self.assertTrue(res_good["available"])
                self.assertEqual(res_good["host_node_version"], "v24.22.3")
                self.assertTrue(res_good["host_node_compatible"])
                self.assertEqual(res_good["rea_version"], "1.4.2")
                self.assertEqual(res_good["source"], "system_npx")

    def test_resolve_reference_targets_tracks_and_app_discovery(self):
        rb = _load_rea_bridge()

        # Web URL
        url_res = rb.resolve_reference_targets("https://linear.app/features")
        self.assertEqual(url_res["track"], "web_url")
        self.assertEqual(url_res["artifact_kind"], "url")
        self.assertIsNone(url_res["rea_subcommand"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # JS app directory
            js_dir = root / "electron_sample"
            js_dir.mkdir()
            (js_dir / "package.json").write_text('{"name":"sample"}', encoding="utf-8")
            (js_dir / "main.js").write_text("console.log('hi');", encoding="utf-8")
            js_res = rb.resolve_reference_targets("electron_sample", workdir=root)
            self.assertEqual(js_res["track"], "local_artifact")
            self.assertEqual(js_res["artifact_kind"], "javascript_app")
            self.assertEqual(js_res["rea_subcommand"], "analyze-javascript-application")

            # SQLite DB
            db_file = root / "notes.sqlite3"
            db_file.write_bytes(b"SQLite format 3\x00")
            db_res = rb.resolve_reference_targets(str(db_file))
            self.assertEqual(db_res["track"], "local_artifact")
            self.assertEqual(db_res["artifact_kind"], "sqlite_db")
            self.assertEqual(db_res["rea_subcommand"], "inspect-sqlite-database")

            # Managed .dll
            dll_file = root / "Plugin.dll"
            dll_file.write_bytes(b"MZ")
            dll_res = rb.resolve_reference_targets(str(dll_file))
            self.assertEqual(dll_res["track"], "local_artifact")
            self.assertEqual(dll_res["artifact_kind"], "managed_assembly")
            self.assertEqual(dll_res["rea_subcommand"], "inspect-managed-artifact")

            # macOS .app with Contents/Resources/app.asar discovery
            apps_dir = root / "Applications"
            asar_path = apps_dir / "MockSlack.app" / "Contents" / "Resources" / "app.asar"
            asar_path.parent.mkdir(parents=True)
            asar_path.write_bytes(b"asar-mock")
            slack_res = rb.resolve_reference_targets("MockSlack", app_search_dirs=[apps_dir])
            self.assertEqual(slack_res["track"], "local_artifact")
            self.assertEqual(slack_res["artifact_path"], str(asar_path))
            self.assertEqual(slack_res["artifact_kind"], "javascript_app")
            self.assertEqual(slack_res["rea_subcommand"], "analyze-javascript-application")

            # macOS .app without app.asar -> shipped_bundle
            native_app = apps_dir / "NativeNotes.app"
            native_app.mkdir()
            notes_res = rb.resolve_reference_targets("NativeNotes", app_search_dirs=[apps_dir])
            self.assertEqual(notes_res["track"], "local_artifact")
            self.assertEqual(notes_res["artifact_path"], str(native_app))
            self.assertEqual(notes_res["artifact_kind"], "shipped_bundle")
            self.assertEqual(notes_res["rea_subcommand"], "audit-release-exposure")

            # Unknown SaaS product -> remote_saas_fallback
            linear_res = rb.resolve_reference_targets("Linear", app_search_dirs=[apps_dir])
            self.assertEqual(linear_res["track"], "remote_saas_fallback")
            self.assertIsNone(linear_res["artifact_path"])
            self.assertEqual(linear_res["artifact_kind"], "remote_saas")
            self.assertTrue(len(linear_res["checked_paths"]) >= 1)

    def test_m2_project_rea_evidence_to_markdown_electron_ipc_and_toon_cut(self):
        rb = _load_rea_bridge()
        payload = _build_realistic_electron_payload(module_count=20)
        raw_path = Path(".asw/evidence/rea-raw-mock-electron.json")

        proj = rb.project_rea_evidence_to_markdown(
            target="MockElectron",
            artifact_path="/tmp/mock-electron-app",
            artifact_kind="javascript_app",
            raw_payload=payload,
            raw_json_path=raw_path,
        )

        md = proj["markdown"]
        self.assertTrue(md.startswith("# Reference Product Recon: MockElectron"))
        self.assertIn("main.js", md)
        self.assertIn("preload.js", md)
        self.assertIn("contextBridge", md)
        self.assertIn("app:get-version", md)
        self.assertIn("Clean-Room Reference Product Parity Checklist", md)
        self.assertIn("rea-raw-mock-electron.json", md)
        # Verify TOON tabular block header is emitted
        self.assertRegex(md, r"modules\[20\]\{")
        self.assertRegex(md, r"electron_boundaries\[5\]\{|boundaries\[5\]\{|ipc\[5\]\{")
        self.assertGreater(proj["raw_bytes"], 0)
        self.assertGreater(proj["raw_tokens"], 0)
        self.assertLessEqual(proj["projected_tokens"], 2500)
        self.assertGreaterEqual(proj["saved_pct"], 50.0)

        # Verify large list (>60 modules) is capped cleanly
        huge_payload = _build_realistic_electron_payload(module_count=95)
        huge_proj = rb.project_rea_evidence_to_markdown(
            target="HugeElectron",
            artifact_path="/tmp/huge-electron-app",
            artifact_kind="javascript_app",
            raw_payload=huge_payload,
        )
        self.assertIn("95", huge_proj["markdown"])
        self.assertLessEqual(huge_proj["projected_tokens"], 2500)

    def test_m2_run_rea_recon_local_electron_mock_cli_subprocess(self):
        rb = _load_rea_bridge()
        payload = _build_realistic_electron_payload(module_count=18)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "electron_app"
            app_dir.mkdir()
            (app_dir / "package.json").write_text('{"name":"electron-sample"}', encoding="utf-8")
            (app_dir / "main.js").write_text("const {app, ipcMain} = require('electron');", encoding="utf-8")
            (app_dir / "preload.js").write_text(
                "const {contextBridge} = require('electron'); contextBridge.exposeInMainWorld('api', {});",
                encoding="utf-8",
            )
            (app_dir / "renderer.js").write_text("window.api.ping();", encoding="utf-8")

            mock_cli = root / "mock_rea.py"
            payload_file = root / "mock_payload.json"
            payload_file.write_text(json.dumps(payload), encoding="utf-8")
            mock_cli.write_text(
                "import sys, pathlib\n"
                f"data = pathlib.Path({str(payload_file)!r}).read_text(encoding='utf-8')\n"
                "assert sys.argv[1] == 'analyze-javascript-application'\n"
                "assert '--json' in sys.argv\n"
                "sys.stdout.write(data)\n",
                encoding="utf-8",
            )

            out_md = root / ".asw" / "evidence" / "reference-electron-app.md"
            raw_json = root / ".asw" / "evidence" / "rea-raw-electron-app.json"
            res = rb.run_rea_recon(
                str(app_dir),
                output_path=out_md,
                raw_output_path=raw_json,
                workdir=root,
                runner_override=[sys.executable, str(mock_cli)],
            )

            self.assertEqual(res["status"], "RECON_COMPLETED")
            self.assertEqual(res["track"], "local_artifact")
            self.assertEqual(res["artifact_kind"], "javascript_app")
            self.assertEqual(res["opt_tokens"], 0.0)
            self.assertGreaterEqual(res["saved_tokens_pct"], 50.0)
            self.assertTrue(raw_json.is_file())
            self.assertTrue(out_md.is_file())
            md_text = out_md.read_text(encoding="utf-8")
            self.assertIn("contextBridge", md_text)
            self.assertIn("preload.js", md_text)

    def test_m3_run_rea_recon_linear_fallback_required_and_cli(self):
        rb = _load_rea_bridge()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_apps = root / "Apps"
            empty_apps.mkdir()
            out_md = root / "reference-linear.md"

            res = rb.run_rea_recon(
                "Linear",
                output_path=out_md,
                app_search_dirs=[empty_apps],
                home_dir=root,
            )
            self.assertEqual(res["status"], "FALLBACK_REQUIRED")
            self.assertEqual(res["track"], "remote_saas_fallback")
            self.assertEqual(res["delegate_to"], ["asw-librarian", "browser"])
            self.assertEqual(res["opt_tokens"], 0.0)
            self.assertEqual(res["output_path"], str(out_md))
            self.assertTrue(out_md.is_file())
            md_text = out_md.read_text(encoding="utf-8")
            self.assertIn("### Reference Product Parity", md_text)
            self.assertIn("Linear", md_text)

            # Real CLI subprocess tests
            cli_preflight = subprocess.run(
                [sys.executable, str(REA_BRIDGE_SCRIPT), "--preflight", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            preflight_data = json.loads(cli_preflight.stdout)
            self.assertIn("available", preflight_data)
            self.assertIn("host_node_compatible", preflight_data)

            cli_resolve = subprocess.run(
                [sys.executable, str(REA_BRIDGE_SCRIPT), "--resolve", "https://linear.app", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            resolve_data = json.loads(cli_resolve.stdout)
            self.assertEqual(resolve_data["track"], "web_url")

            cli_out = root / "cli-linear.md"
            cli_recon = subprocess.run(
                [
                    sys.executable,
                    str(REA_BRIDGE_SCRIPT),
                    "--recon",
                    "Linear",
                    "--output",
                    str(cli_out),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            recon_data = json.loads(cli_recon.stdout)
            self.assertEqual(recon_data["status"], "FALLBACK_REQUIRED")
            self.assertEqual(recon_data["track"], "remote_saas_fallback")
            self.assertTrue(cli_out.is_file())

    def test_m2_project_real_rea_6_10_1_graph_nodes_and_dedup_limitations(self):
        rb = _load_rea_bridge()
        sha = "a" * 64
        shared_limitations = [
            "JavaScript and HTML were parsed as inert text; bundle bootstrap code was never executed.",
            "Electron relationships are derived from inert syntax; runtime registration remains unproven.",
        ]
        real_schema_payload = {
            "evidence_id": "ev-rea-6101",
            "operation": "analyze-javascript-application",
            "limitations": list(shared_limitations),
            "normalized_result": {
                "summary": {
                    "browser_windows": 1,
                    "preload_entrypoints": 1,
                    "context_bridge_apis": 1,
                    "exposed_api_members": 3,
                    "ipc": {"operations": 5, "literal_channels": 3},
                    "electron_semantics": "recovered",
                },
                "route_inventory": {
                    "sources": [
                        {"key": "src/main.js", "path": "src/main.js", "status": "complete"},
                        {"key": "src/preload.js", "path": "src/preload.js", "status": "complete"},
                        {"key": "src/services/fuzzy_index.js", "path": "src/services/fuzzy_index.js", "status": "complete"},
                    ]
                },
                "limitations": list(shared_limitations),
                "graph": {
                    "limitations": list(shared_limitations),
                    "nodes": [
                        {
                            "node_id": "jag_node_main",
                            "kind": "electron-main",
                            "identity": {"namespace": "electron-role", "key": "electron-main:src/main.js"},
                            "observations": [{"label": "src/main.js", "properties": {"resolved_path": "src/main.js"}}],
                        },
                        {
                            "node_id": "jag_node_preload",
                            "kind": "electron-preload",
                            "identity": {"namespace": "electron-role", "key": "electron-preload:src/preload.js"},
                            "observations": [{"label": "src/preload.js", "properties": {"resolved_path": "src/preload.js"}}],
                        },
                        {
                            "node_id": "jag_node_bw",
                            "kind": "browser-window",
                            "identity": {"namespace": "electron-browser-window", "key": "16:15-28:4"},
                            "observations": [{"label": "BrowserWindow@16:15-28:4", "properties": {"source_path": "src/main.js", "contextIsolation": True}}],
                        },
                        {
                            "node_id": "jag_node_cb",
                            "kind": "context-bridge-api",
                            "identity": {"namespace": "electron-context-bridge", "key": "main:launcherBridge:3:0-11:2"},
                            "observations": [{"label": "launcherBridge", "properties": {"api_key": "launcherBridge", "members": ["search", "execute", "onToggle"]}}],
                        },
                        {
                            "node_id": "jag_node_ipc_search",
                            "kind": "ipc-channel",
                            "identity": {"scope": "electron-ipc-channel"},
                            "observations": [{"label": "palette:search", "properties": {"side": "renderer", "channel": "palette:search"}}],
                        },
                        {
                            "node_id": "jag_node_ipc_exec",
                            "kind": "ipc-handler",
                            "identity": {"namespace": "electron-ipc-handler", "key": "main:handle:palette:execute"},
                            "observations": [{"label": "palette:execute", "properties": {"side": "main", "operation": "handle", "channel": "palette:execute"}}],
                        },
                        {
                            "node_id": "jag_node_mod_fuzzy",
                            "kind": "javascript-module",
                            "identity": {"namespace": "source-module", "key": f"{sha}:src/services/fuzzy_index.js"},
                            "observations": [{"label": "src/services/fuzzy_index.js", "properties": {"semantic_role": "source-module", "ast_dump": "x" * 600}}],
                        },
                        {
                            "node_id": "jag_node_mod_preload",
                            "kind": "javascript-module",
                            "identity": {"namespace": "source-module", "key": f"{sha}:src/preload.js"},
                            "observations": [{"label": "src/preload.js", "properties": {"semantic_role": "source-module", "ast_dump": "y" * 600}}],
                        },
                        {
                            "node_id": "jag_node_mod_preload_dup",
                            "kind": "javascript-module",
                            "identity": {"namespace": "source-module", "key": f"{sha}:src/preload.js"},
                            "observations": [{"label": "src/preload.js", "properties": {"semantic_role": "source-module"}}],
                        },
                        {
                            "node_id": "jag_node_pkg",
                            "kind": "package",
                            "identity": {"namespace": "package-json", "key": "package.json"},
                            "observations": [{"label": "command-launcher-ref", "properties": {"name": "command-launcher-ref", "version": "2.4.0"}}],
                        },
                    ],
                },
            },
        }

        proj = rb.project_rea_evidence_to_markdown(
            target="RaycastPalette",
            artifact_path="/tmp/raycast-like-electron",
            artifact_kind="javascript_app",
            raw_payload=real_schema_payload,
            raw_json_path=Path(".asw/evidence/rea-raw-raycast.json"),
        )

        md = proj["markdown"]
        self.assertIn("## Summary", md)
        self.assertIn("browser_windows", md)
        self.assertIn("electron_semantics", md)
        self.assertIn("launcherBridge", md)
        self.assertIn("palette:search", md)
        self.assertIn("palette:execute", md)
        self.assertIn("src/preload.js", md)
        self.assertIn("src/services/fuzzy_index.js", md)
        self.assertRegex(md, r"electron_boundaries\[6\]\{")
        self.assertRegex(md, r"modules\[4\]\{")
        # Deduplicated limitations: 2 unique lines instead of 6!
        self.assertIn("## Limitations (2)", md)
        self.assertEqual(md.count("JavaScript and HTML were parsed as inert text"), 1)
        self.assertLessEqual(proj["projected_tokens"], 2500)
        self.assertGreaterEqual(proj["saved_pct"], 50.0)

    def test_patch4_resolve_dot_app_no_double_suffix(self):
        rb = _load_rea_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            apps_dir = Path(tmp).resolve() / "Applications"
            asar_path = apps_dir / "MockSlack.app" / "Contents" / "Resources" / "app.asar"
            asar_path.parent.mkdir(parents=True)
            asar_path.write_bytes(b"asar-mock")

            res = rb.resolve_reference_targets("MockSlack.app", app_search_dirs=[apps_dir])
            self.assertEqual(res["track"], "local_artifact")
            self.assertEqual(res["artifact_path"], str(asar_path))
            self.assertFalse(any(".app.app" in p for p in res["checked_paths"]))

            missing = rb.resolve_reference_targets("Slack.app", app_search_dirs=[apps_dir])
            self.assertEqual(missing["track"], "remote_saas_fallback")
            self.assertTrue(any(p.endswith("Slack.app") for p in missing["checked_paths"]))
            self.assertFalse(any(".app.app" in p for p in missing["checked_paths"]))

    def test_patch5_home_sanitization_and_short_raw_slug(self):
        rb = _load_rea_bridge()
        home_str = str(Path.home())
        fake_target = f"{home_str}/workspace/raycast-like-electron"
        raw_p = Path.home() / "workspace" / ".asw" / "evidence" / "rea-raw.json"

        proj = rb.project_rea_evidence_to_markdown(
            target=fake_target,
            artifact_path=fake_target,
            artifact_kind="javascript_app",
            raw_payload={"modules": [{"path": f"{home_str}/workspace/main.js", "kind": "main"}]},
            raw_json_path=raw_p,
        )
        md = proj["markdown"]
        self.assertNotIn(home_str, md)
        self.assertIn("~/workspace/raycast-like-electron", md)
        self.assertIn("~/workspace/.asw/evidence/rea-raw.json", md)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app_dir = root / "raycast-like-electron"
            app_dir.mkdir()
            (app_dir / "package.json").write_text('{"name":"rc"}', encoding="utf-8")
            (app_dir / "main.js").write_text("console.log(1);", encoding="utf-8")

            mock_cli = root / "mock_rea.py"
            mock_cli.write_text(
                "import sys, json\n"
                "sys.stdout.write(json.dumps({'modules': [{'path': 'main.js'}]}))\n",
                encoding="utf-8",
            )
            res = rb.run_rea_recon(
                str(app_dir),
                workdir=root,
                runner_override=[sys.executable, str(mock_cli)],
            )
            self.assertEqual(res["status"], "RECON_COMPLETED")
            raw_name = Path(res["raw_evidence_path"]).name
            self.assertRegex(raw_name, r"^rea-raw-raycast-like-electron-[0-9a-f]{8}\.json$")
            self.assertNotIn(Path.home().name.lower(), raw_name.lower())

    def test_mirror_parity(self):
        self.assertTrue(REA_BRIDGE_SCRIPT.is_file())
        self.assertTrue(MIRROR_REA_BRIDGE_SCRIPT.is_file())
        self.assertEqual(
            REA_BRIDGE_SCRIPT.read_bytes().replace(b"\r\n", b"\n"),
            MIRROR_REA_BRIDGE_SCRIPT.read_bytes().replace(b"\r\n", b"\n"),
            "core_framework/scripts/rea_bridge.py must match .antigravity/scripts/rea_bridge.py",
        )


if __name__ == "__main__":
    unittest.main()
