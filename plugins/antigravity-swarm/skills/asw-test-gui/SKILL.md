---
name: asw-test-gui
description: On-demand physical GUI and localhost Playwright verification for web, native, and mobile apps.
---

# Antigravity Swarm Physical GUI Tester (`asw-test-gui`)

Use this skill **on-demand when explicitly requested by the user** (either standalone as `asw-test-gui` to physically test the latest implementation, or chained at the end of `asw-loop` / `asw-start-work` / `asw-goal` when the user specifies `asw-test-gui`).

Do NOT invoke `asw-test-gui` automatically on every backend or non-GUI task unless the user specifies `asw-test-gui` in their prompt.

## Purpose

Unit tests and mocked component tests frequently miss real rendering crashes, broken localhost routing, hydration mismatches, uncaught browser `console.error` / `pageerror` exceptions, broken CSS/layout states, and native window startup crashes. `asw-test-gui` enforces **physical execution and inspection of the live GUI surface**.

## Execution Protocol

### 1. Identify the GUI Surface
Determine the application type in the active repository:
- **Web / Full-Stack Application (React, Next.js, Vite, Vue, FastAPI/Django/Flask templates, Odoo):**
  - Discover the dev/preview server startup command (e.g., `npm run dev`, `pnpm dev`, `uvicorn ...`, `start.ps1`) and target localhost URL (e.g., `http://127.0.0.1:3000`, `http://127.0.0.1:8000`).
- **Native Desktop Application (Electron, PyQt/PySide, Tkinter, WPF/.NET, Rust/Tauri, C++):**
  - Discover the application launch command (`--app-cmd`).
- **Mobile Application (Flutter, React Native / Expo, Android):**
  - Discover the web/emulator/device runner (`flutter run`, `npx expo start --web`, `android` CLI, or integration test target).

### 2. Run Physical GUI Verification (`run_gui_test.py` + Playwright)
Execute `.antigravity/scripts/run_gui_test.py` (or `~/.gemini/scripts/run_gui_test.py`) AND/OR project Playwright E2E specs:

#### Web / Localhost Surface:
```bash
python .antigravity/scripts/run_gui_test.py \
  --mode web \
  --start-cmd "<server-start-command>" \
  --url "http://127.0.0.1:<port>" \
  --assert-text "<expected-visible-heading-or-state>" \
  --assert-selector "<expected-button-or-component>" \
  --screenshot ".asw/evidence/gui-screenshot.png" \
  --output ".asw/evidence/gui-test-report.md"
```
If the repository also has Playwright specs (`playwright.config.ts` / `tests/e2e/`), execute `npx playwright test` against the live localhost server and capture the transcript.

#### Native Desktop Surface:
```bash
python .antigravity/scripts/run_gui_test.py \
  --mode native \
  --app-cmd "<native-app-launch-command>" \
  --wait-seconds 3.0 \
  --output ".asw/evidence/gui-test-report.md"
```

### 3. Mandatory Physical GUI Checks
1. **Liveness & HTTP/Window Readiness:** Server binds and responds with HTTP 200..399 (or native window initializes without exiting non-zero).
2. **Zero Runtime / Console Exceptions:** Zero uncaught `pageerror`, zero `console.error`, zero HTTP 500 responses, and zero `Traceback` / `Segmentation fault` outputs.
3. **Interactive DOM & State Verification:** Expected headings, views, buttons, forms, and newly implemented UI features are physically present and interactive in the rendered DOM.
4. **Self-Correction Loop:** If `Verdict: GUI_FAILED` is returned, fix the underlying UI/runtime bug and re-run `asw-test-gui` until `Verdict: GUI_VERIFIED` is achieved.
5. **Guaranteed Teardown & Cleanup:** Always terminate any spawned localhost dev servers, browser contexts, or native GUI processes before finishing the turn.
