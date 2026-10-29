#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""On-Demand Physical GUI & Localhost Verification Harness (asw-test-gui).

Executes real-surface GUI verification for:
  1. Web / Localhost applications (--mode web):
     - Starts the local dev server (--start-cmd) or connects to a live localhost/LAN URL (--url).
     - Drives Playwright (headless/headed Chromium) when available, with automatic fallback to
       deterministic HTTP + DOM structural inspection.
     - Recursively traverses both Light DOM and open Shadow DOM roots (`shadowRoot`) to detect
       Home Assistant / Web Component error cards (`<hui-error-card>`, `<hui-error-badge>`,
       `"Configuration error"`, `"Custom element doesn't exist"`), console.error, uncaught
       page exceptions, HTTP 4xx/5xx failures, missing UI text (--assert-text), missing
       interactive selectors (--assert-selector), and forbidden states (--forbid-text,
       --forbid-selector).
     - Captures screenshots (--screenshot) and writes a structured evidence report (--output).
     - Guarantees clean teardown of spawned server processes in `finally`.
  2. Native Desktop / Mobile GUI applications (--mode native):
     - Launches the native GUI binary/command (--app-cmd), monitors startup stability over
       --wait-seconds, detects fatal crash tracebacks on stderr, verifies readiness output,
       and cleanly terminates the GUI process tree.
"""

from __future__ import annotations

import argparse
import datetime
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_FORBIDDEN_ERROR_SELECTORS: tuple[str, ...] = (
    "hui-error-card",
    "hui-error-badge",
    "error-card",
)

DEFAULT_FORBIDDEN_ERROR_TEXTS: tuple[str, ...] = (
    "Configuration error",
    "Custom element doesn't exist",
    "Custom element not found",
    "Traceback (most recent call last)",
    "Internal Server Error",
    "ReferenceError:",
    "SyntaxError:",
    "TypeError: Cannot read",
)


class _DOMInspector(HTMLParser):
    """Lightweight HTML DOM inspector for verifying tags, IDs, classes, and visible text."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.text_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag.lower())
        for k, v in attrs:
            if k == "id" and v:
                self.ids.add(v.strip())
            elif k == "class" and v:
                for cls in v.split():
                    self.classes.add(cls.strip())

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.text_chunks.append(data.strip())

    def matches_selector(self, selector: str) -> bool:
        sel = selector.strip()
        if not sel:
            return True
        if sel.startswith("#"):
            return sel[1:] in self.ids
        if sel.startswith("."):
            return sel[1:] in self.classes
        return sel.lower() in self.tags


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Safely terminate a spawned server or GUI process tree across Windows, macOS, and Linux."""
    if proc.poll() is not None:
        return
    try:
        if platform.system().lower() == "windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _wait_for_http_ready(url: str, timeout_seconds: float) -> tuple[bool, int, str, str]:
    """Poll a localhost URL with uncached headers until it responds or timeout expires."""
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_err = "No response"
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Antigravity-ASW-Test-GUI/1.0",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                status = int(resp.status)
                body = resp.read().decode("utf-8", errors="replace")
                return (200 <= status < 400), status, body, ""
        except urllib.error.HTTPError as he:
            body = ""
            try:
                body = he.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            return False, int(he.code), body, f"HTTP {he.code}: {he.reason}"
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.25)
    return False, 0, "", last_err


_SHADOW_DOM_WALKER_JS = """
() => {
  const tags = new Set();
  const ids = new Set();
  const classes = new Set();
  const texts = [];
  const visit = (root) => {
    if (!root) return;
    const elements = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of elements) {
      if (el.tagName) tags.add(el.tagName.toLowerCase());
      if (el.id) ids.add(el.id);
      if (el.classList) {
        for (const c of el.classList) classes.add(c);
      }
      if (el.shadowRoot) {
        if (el.shadowRoot.innerHTML) {
          texts.push(el.shadowRoot.textContent || '');
        }
        visit(el.shadowRoot);
      }
    }
  };
  visit(document);
  return {
    tags: Array.from(tags),
    ids: Array.from(ids),
    classes: Array.from(classes),
    shadowText: texts.join('\\n'),
    bodyText: document.body ? (document.body.innerText || document.body.textContent || '') : ''
  };
}
"""


def _try_playwright_verification(
    url: str,
    assert_texts: list[str],
    assert_selectors: list[str],
    assert_asset_versions: list[str],
    forbid_texts: list[str],
    forbid_selectors: list[str],
    click_selectors: list[str],
    screenshot_path: Path | None,
) -> dict[str, object] | None:
    """Attempt physical browser verification via Playwright Python API (including Shadow DOM scanning)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    findings: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
            page = context.new_page()

            page.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "response",
                lambda resp: failed_requests.append(f"{resp.status} {resp.url}")
                if resp.status >= 400
                else None,
            )

            resp = page.goto(url, wait_until="domcontentloaded", timeout=15000)
            status = resp.status if resp else 0
            if status < 200 or status >= 400:
                findings.append(f"HTTP status {status} outside 200..399 range")

            for click_sel in click_selectors:
                page.locator(click_sel).first.click(timeout=5000)

            dom_snapshot = page.evaluate(_SHADOW_DOM_WALKER_JS)
            all_tags = set(dom_snapshot.get("tags") or [])
            all_ids = set(dom_snapshot.get("ids") or [])
            all_classes = set(dom_snapshot.get("classes") or [])
            combined_text = (
                (dom_snapshot.get("bodyText") or "")
                + "\n"
                + (dom_snapshot.get("shadowText") or "")
                + "\n"
                + page.content()
            )

            def _selector_present(sel: str) -> bool:
                s = sel.strip()
                if not s:
                    return False
                if s.startswith("#") and s[1:] in all_ids:
                    return True
                if s.startswith(".") and s[1:] in all_classes:
                    return True
                if s.lower() in all_tags:
                    return True
                try:
                    return page.locator(s).count() > 0
                except Exception:
                    return False

            for expected_text in assert_texts:
                if expected_text not in combined_text:
                    findings.append(f"Missing expected UI text: {expected_text!r}")

            for sel in assert_selectors:
                if not _selector_present(sel):
                    findings.append(f"Missing expected UI selector: {sel!r}")

            raw_html = page.content()
            for ver_token in assert_asset_versions:
                if ver_token and ver_token not in raw_html and ver_token not in combined_text:
                    findings.append(
                        f"Missing expected asset/module version token in served HTML (stale cache or un-restarted container): {ver_token!r}"
                    )

            for err_sel in list(DEFAULT_FORBIDDEN_ERROR_SELECTORS) + list(forbid_selectors):
                if _selector_present(err_sel):
                    findings.append(f"Forbidden error/UI element detected in rendered DOM/Shadow DOM: <{err_sel}>")

            for err_txt in list(DEFAULT_FORBIDDEN_ERROR_TEXTS) + list(forbid_texts):
                if err_txt and err_txt.lower() in combined_text.lower():
                    findings.append(f"Forbidden error/broken-state text detected in rendered DOM/Shadow DOM: {err_txt!r}")

            if page_errors:
                findings.append(f"Uncaught page errors: {page_errors[:3]}")
            if console_errors:
                findings.append(f"Browser console.error: {console_errors[:3]}")
            if failed_requests:
                findings.append(f"Failed HTTP responses: {failed_requests[:3]}")

            if screenshot_path is not None:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_path), full_page=True)

            browser.close()
            return {
                "engine": "playwright-chromium",
                "http_status": status,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "failed_requests": failed_requests,
                "findings": findings,
                "passed": len(findings) == 0,
            }
    except Exception:
        # Fall back to deterministic HTTP+DOM inspector if Playwright browser binaries are not installed
        return None


def run_web_gui_test(
    *,
    url: str,
    start_cmd: str | None = None,
    assert_texts: list[str] | None = None,
    assert_selectors: list[str] | None = None,
    assert_asset_versions: list[str] | None = None,
    forbid_texts: list[str] | None = None,
    forbid_selectors: list[str] | None = None,
    click_selectors: list[str] | None = None,
    screenshot_path: Path | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    """Execute physical web GUI verification against a localhost/LAN URL."""
    texts = assert_texts or []
    selectors = assert_selectors or []
    asset_versions = assert_asset_versions or []
    bad_texts = forbid_texts or []
    bad_selectors = forbid_selectors or []
    clicks = click_selectors or []

    server_proc: subprocess.Popen | None = None
    try:
        if start_cmd and start_cmd.strip():
            server_proc = subprocess.Popen(
                start_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        ready, status, body, err_msg = _wait_for_http_ready(url, timeout_seconds)
        if not ready:
            return {
                "mode": "web",
                "url": url,
                "engine": "http-dom-probe",
                "http_status": status,
                "findings": [f"Localhost endpoint failed readiness check: {err_msg or f'HTTP {status}'}"],
                "passed": False,
                "cleanup": "Spawned server process terminated" if server_proc else "No spawned server",
            }

        pw_res = _try_playwright_verification(
            url, texts, selectors, asset_versions, bad_texts, bad_selectors, clicks, screenshot_path
        )
        if pw_res is not None:
            pw_res["mode"] = "web"
            pw_res["url"] = url
            pw_res["cleanup"] = "Spawned server process terminated & browser closed" if server_proc else "Browser closed"
            return pw_res

        # Deterministic DOM + HTTP fallback
        inspector = _DOMInspector()
        inspector.feed(body)
        findings: list[str] = []

        if not body.strip():
            findings.append("Empty HTML response body")

        for expected_text in texts:
            if expected_text not in body:
                findings.append(f"Missing expected UI text: {expected_text!r}")

        for sel in selectors:
            if not inspector.matches_selector(sel):
                findings.append(f"Missing expected UI selector: {sel!r}")

        for ver_token in asset_versions:
            if ver_token and ver_token not in body:
                findings.append(
                    f"Missing expected asset/module version token in served HTML (stale cache or un-restarted container): {ver_token!r}"
                )

        for err_sel in list(DEFAULT_FORBIDDEN_ERROR_SELECTORS) + list(bad_selectors):
            if inspector.matches_selector(err_sel):
                findings.append(f"Forbidden error/UI element detected in rendered DOM: <{err_sel}>")

        body_lower = body.lower()
        for err_txt in list(DEFAULT_FORBIDDEN_ERROR_TEXTS) + list(bad_texts):
            if err_txt and err_txt.lower() in body_lower:
                findings.append(f"Forbidden error/broken-state text detected in rendered page: {err_txt!r}")

        return {
            "mode": "web",
            "url": url,
            "engine": "http-dom-inspector",
            "http_status": status,
            "discovered_tags": sorted(inspector.tags),
            "findings": findings,
            "passed": len(findings) == 0,
            "cleanup": "Spawned server process terminated" if server_proc else "No spawned server",
        }
    finally:
        if server_proc is not None:
            _kill_process_tree(server_proc)


def run_native_gui_test(
    *,
    app_cmd: str,
    wait_seconds: float = 2.0,
    assert_texts: list[str] | None = None,
) -> dict[str, object]:
    """Launch a native GUI application, verify startup stability and output, and terminate cleanly."""
    texts = assert_texts or []
    findings: list[str] = []
    proc: subprocess.Popen | None = None
    stdout_data = ""
    stderr_data = ""

    try:
        proc = subprocess.Popen(
            app_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(max(wait_seconds, 0.5))
        exit_code = proc.poll()

        # Terminate after observation window so we can read stdout/stderr cleanly
        _kill_process_tree(proc)
        try:
            stdout_data, stderr_data = proc.communicate(timeout=3)
        except Exception:
            pass

        if exit_code is not None and exit_code != 0:
            findings.append(f"Native GUI process crashed during startup window with exit code {exit_code}")

        for fatal_marker in ("Traceback", "Segmentation fault", "Unhandled exception", "Fatal error", "panic:"):
            if fatal_marker.lower() in stderr_data.lower():
                findings.append(f"Fatal error detected on stderr: {fatal_marker}")

        combined_out = (stdout_data or "") + "\n" + (stderr_data or "")
        for expected_text in texts:
            if expected_text not in combined_out:
                findings.append(f"Missing expected readiness output: {expected_text!r}")

        return {
            "mode": "native",
            "app_cmd": app_cmd,
            "engine": "native-process-probe",
            "exit_code_during_window": exit_code,
            "findings": findings,
            "passed": len(findings) == 0,
            "cleanup": "Native GUI process tree terminated",
        }
    finally:
        if proc is not None:
            _kill_process_tree(proc)


def format_markdown_report(result: dict[str, object]) -> str:
    """Format a structured ASW-TEST-GUI Markdown evidence report."""
    verdict = "GUI_VERIFIED" if result.get("passed") else "GUI_FAILED"
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lines = [
        "# Antigravity Swarm Physical GUI Verification Report (`asw-test-gui`)",
        "",
        f"- **Timestamp**: `{ts}`",
        f"- **Mode**: `{result.get('mode')}`",
        f"- **Engine**: `{result.get('engine')}`",
        f"- **Target**: `{result.get('url') or result.get('app_cmd')}`",
        f"- **Cleanup Receipt**: {result.get('cleanup')}",
        f"Verdict: {verdict}",
        "",
        "## Findings",
    ]
    findings = result.get("findings") or []
    if not findings:
        lines.append("- **PASS**: Physical GUI surface rendered and responded with zero errors.")
    else:
        for f in findings:
            lines.append(f"- **[FAIL]**: {f}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Antigravity Swarm Physical GUI & Localhost Tester (asw-test-gui)")
    parser.add_argument("--mode", choices=["web", "native"], default="web", help="GUI surface mode: web (localhost) or native")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:3000", help="Target localhost URL for web mode")
    parser.add_argument("--start-cmd", type=str, default=None, help="Optional command to launch localhost server before probing")
    parser.add_argument("--app-cmd", type=str, default=None, help="Command to launch native GUI application in native mode")
    parser.add_argument("--assert-text", action="append", default=[], help="Text that must be visible in the GUI (repeatable)")
    parser.add_argument("--assert-selector", action="append", default=[], help="DOM selector/tag that must exist (repeatable)")
    parser.add_argument("--assert-asset-version", action="append", default=[], help="Asset/module version token (e.g. '?v=20261028') that must appear in served HTML (repeatable)")
    parser.add_argument("--forbid-text", action="append", default=[], help="Text that must NOT appear in rendered DOM/Shadow DOM (repeatable)")
    parser.add_argument("--forbid-selector", action="append", default=[], help="DOM selector/tag that must NOT exist (repeatable)")
    parser.add_argument("--click", action="append", default=[], help="Selector to click in Playwright mode (repeatable)")
    parser.add_argument("--screenshot", type=Path, default=None, help="Optional path to save PNG screenshot")
    parser.add_argument("--wait-seconds", type=float, default=2.0, help="Observation window for native GUI startup")
    parser.add_argument("--timeout-seconds", type=float, default=15.0, help="Timeout waiting for localhost HTTP readiness")
    parser.add_argument("--output", type=Path, default=Path(".asw/evidence/gui-test-report.md"), help="Output Markdown evidence path")

    args = parser.parse_args()

    if args.mode == "native":
        if not args.app_cmd:
            sys.stderr.write("Error: --app-cmd is required for --mode native\n")
            return 2
        res = run_native_gui_test(
            app_cmd=args.app_cmd,
            wait_seconds=args.wait_seconds,
            assert_texts=args.assert_text,
        )
    else:
        res = run_web_gui_test(
            url=args.url,
            start_cmd=args.start_cmd,
            assert_texts=args.assert_text,
            assert_selectors=args.assert_selector,
            assert_asset_versions=args.assert_asset_version,
            forbid_texts=args.forbid_text,
            forbid_selectors=args.forbid_selector,
            click_selectors=args.click,
            screenshot_path=args.screenshot,
            timeout_seconds=args.timeout_seconds,
        )

    report = format_markdown_report(res)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0 if res.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
