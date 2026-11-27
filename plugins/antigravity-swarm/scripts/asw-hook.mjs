#!/usr/bin/env node

import { readFileSync, existsSync, unlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { redactSecrets, safeMode } from "./asw-redact.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SYNTHETIC_MODE_RE = /ASW\s+(?:[A-Z0-9_-]+\s+MODE|CONSULTATION\s*\/\s*MODE\s+1)\s+ENABLED!|ASW\s+SPEC-KIT\s+CLARIFY\s+GATE/i;

function pythonBin() {
  return process.platform === "win32" ? "python" : "python3";
}

function resolveWorkspaceDir(payload) {
  const candidates = [
    payload?.cwd,
    Array.isArray(payload?.workspacePaths) ? payload.workspacePaths[0] : undefined,
    Array.isArray(payload?.workspaceUris) ? payload.workspaceUris[0] : undefined,
  ];
  for (const raw of candidates) {
    if (typeof raw === "string" && raw.trim()) {
      try {
        if (raw.startsWith("file://")) {
          return fileURLToPath(raw);
        }
        return raw.trim();
      } catch {
        // continue
      }
    }
  }
  return process.cwd();
}

function isTokenEconomizerEnabled(repoDir) {
  const envVal = process.env.ASW_TOKEN_ECONOMIZER_ENABLED;
  if (envVal !== undefined) {
    const s = String(envVal).trim().toLowerCase();
    if (s === "0" || s === "false" || s === "no" || s === "off") return false;
    if (s === "1" || s === "true" || s === "yes" || s === "on") return true;
  }
  const configPaths = [
    repoDir ? join(repoDir, ".antigravity", "decision_config.json") : "",
    join(process.cwd(), ".antigravity", "decision_config.json"),
    join(homedir(), ".gemini", "decision_config.json"),
    join(homedir(), ".gemini", ".antigravity", "decision_config.json"),
  ].filter(Boolean);
  for (const cp of configPaths) {
    if (existsSync(cp)) {
      try {
        const parsed = JSON.parse(readFileSync(cp, "utf8"));
        if (typeof parsed?.token_economizer_enabled === "boolean") {
          return parsed.token_economizer_enabled;
        }
      } catch {
        // continue
      }
    }
  }
  return true;
}

function resolveTokenEconomizer(repoDir) {
  const candidates = [
    join(__dirname, "..", "..", "..", ".antigravity", "scripts", "token_economizer.py"),
    repoDir ? join(repoDir, ".antigravity", "scripts", "token_economizer.py") : "",
    join(process.cwd(), ".antigravity", "scripts", "token_economizer.py"),
    join(homedir(), ".gemini", "scripts", "token_economizer.py"),
    join(homedir(), ".gemini", ".antigravity", "scripts", "token_economizer.py"),
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return null;
}

function isSessionStartEvent(payload) {
  const idx = process.argv.indexOf("--event");
  const argEvent = idx >= 0 ? String(process.argv[idx + 1] ?? "") : "";
  const ev = argEvent || String(payload?.hookEventName ?? payload?.event ?? "");
  return ev.trim().toLowerCase() === "sessionstart";
}

function querySessionStartEnvFacts(repoDir) {
  if (!isTokenEconomizerEnabled(repoDir)) return "";
  const tePath = resolveTokenEconomizer(repoDir);
  if (!tePath) return "";
  try {
    const res = spawnSync(
      pythonBin(),
      [tePath, "--session-start", "--repo", repoDir, "--json"],
      { timeout: 1500, encoding: "utf8" }
    );
    if (res.status === 0 && res.stdout) {
      const parsed = JSON.parse(res.stdout);
      if (parsed?.enabled === false || parsed?.status === "disabled") return "";
      const rendered = String(parsed?.systemMessage ?? parsed?.rendered ?? "").trim();
      return rendered;
    }
  } catch {
    return "";
  }
  return "";
}

function queryTurnGuardNudge(transcriptPath, repoDir) {
  if (!isTokenEconomizerEnabled(repoDir)) return "";
  if (typeof transcriptPath !== "string" || !transcriptPath.trim() || !existsSync(transcriptPath)) {
    return "";
  }
  const tePath = resolveTokenEconomizer(repoDir);
  if (!tePath) return "";
  try {
    const res = spawnSync(
      pythonBin(),
      [tePath, "--check-turn", transcriptPath, "--repo", repoDir, "--json"],
      { timeout: 1500, encoding: "utf8" }
    );
    if (res.status === 0 && res.stdout) {
      const parsed = JSON.parse(res.stdout);
      if (parsed?.enabled === false || parsed?.status === "disabled") return "";
      const msg = String(
        parsed?.ephemeralMessage ?? (typeof parsed?.nudge === "string" ? parsed.nudge : "")
      ).trim();
      if ((parsed?.nudge === true || parsed?.redirect === true || Boolean(msg)) && msg) {
        return msg;
      }
    }
  } catch {
    return "";
  }
  return "";
}

function resolveDecisionRouter(repoDir) {
  const candidates = [
    repoDir ? join(repoDir, ".antigravity", "scripts", "decision_router.py") : "",
    repoDir ? join(repoDir, "core_framework", "scripts", "decision_router.py") : "",
    join(__dirname, "..", "..", "..", "core_framework", "scripts", "decision_router.py"),
    join(__dirname, "..", "..", "..", ".antigravity", "scripts", "decision_router.py"),
    join(process.cwd(), ".antigravity", "scripts", "decision_router.py"),
    join(process.cwd(), "core_framework", "scripts", "decision_router.py"),
    join(homedir(), ".gemini", "scripts", "decision_router.py"),
    join(homedir(), ".gemini", ".antigravity", "scripts", "decision_router.py"),
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return null;
}

function isDecisionModelEnabled(repoDir) {
  const envVal = process.env.ASW_DECISION_MODEL_ENABLED;
  if (envVal !== undefined) {
    const s = String(envVal).trim().toLowerCase();
    if (s === "0" || s === "false" || s === "no" || s === "off") return false;
    if (s === "1" || s === "true" || s === "yes" || s === "on") return true;
  }
  const configPaths = [
    repoDir ? join(repoDir, ".antigravity", "decision_config.json") : "",
    join(process.cwd(), ".antigravity", "decision_config.json"),
    join(__dirname, "..", "..", "..", ".antigravity", "decision_config.json"),
    join(homedir(), ".gemini", "decision_config.json"),
    join(homedir(), ".gemini", ".antigravity", "decision_config.json"),
  ].filter(Boolean);
  for (const cp of configPaths) {
    if (existsSync(cp)) {
      try {
        const parsed = JSON.parse(readFileSync(cp, "utf8"));
        if (typeof parsed?.enabled === "boolean") return parsed.enabled;
      } catch {
        // continue
      }
    }
  }
  return true;
}

function queryAutoDecisionRouter(prompt, repoDir) {
  if (!isDecisionModelEnabled(repoDir)) return null;
  const routerPath = resolveDecisionRouter(repoDir);
  if (!routerPath) return null;
  try {
    const safeCwd = repoDir && existsSync(repoDir) ? repoDir : undefined;
    const res = spawnSync(
      process.platform === "win32" ? "python" : "python3",
      [routerPath, "--mode", "route-prompt", "--compact", "--text", String(prompt)],
      { timeout: 1500, encoding: "utf8", cwd: safeCwd }
    );
    if (res.status === 0 && res.stdout) {
      const parsed = JSON.parse(res.stdout);
      if (parsed.enabled === false || parsed.status === "disabled") {
        return null;
      }
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

const WORD = "(?<![A-Za-z0-9_./-])/?";
const END = "(?![A-Za-z0-9_/-])";
const CLARIFY_RE = new RegExp(`${WORD}(?:asw-clarify|swarmwork-clarify|asw\\s+clarify)${END}`, "i");
const NO_CLARIFY_RE = /(?:--no-clarify|(?<![A-Za-z0-9_\u00c0-\u024f])(?:no-clarify|bez\s+dopt[aá]v[aá]n[ií]|neptej\s+se|rozhodni\s+s[aá]m|skip\s+clarify)(?![A-Za-z0-9_\u00c0-\u024f]))/i;
const PLAN_RE = new RegExp(`${WORD}(?:asw-plan|swarmwork-plan|asw\\s+plan)${END}`);
const GOAL_RE = new RegExp(`${WORD}(?:asw-goal|swarmwork-goal|asw\\s+goal)${END}`);
const START_WORK_RE = new RegExp(`${WORD}(?:start-work|asw-start-work|swarmwork-start|asw\\s+start\\s+work)${END}`);
const CLEANUP_RE = new RegExp(`${WORD}(?:asw-cleanup|asw-remove-ai-slops|swarmwork-cleanup|asw\\s+cleanup)${END}`);
const EXPLICIT_LOOP_RE = new RegExp(`${WORD}(?:asw-loop|swarmwork)${END}`);
const GENERIC_ASW_RE = new RegExp(`${WORD}asw${END}`);
const REVIEW_RE = new RegExp(`${WORD}(?:asw-review|swarmwork-review|asw\\s+review)${END}`);
const TEST_GUI_RE = new RegExp(`${WORD}(?:asw-test-gui|swarmwork-test-gui|asw\\s+test[-\\s]+gui)${END}`, "i");

export function leadingCommandFor(stripped) {
  const trimmed = String(stripped ?? "").trimStart();
  if (!trimmed) return null;
  const rules = [
    ["CLARIFY", new RegExp(`^/?(?:asw-clarify|swarmwork-clarify|asw\\s+clarify)${END}`, "i")],
    ["PLAN", new RegExp(`^/?(?:asw-plan|swarmwork-plan|asw\\s+plan)${END}`)],
    ["GOAL", new RegExp(`^/?(?:asw-goal|swarmwork-goal|asw\\s+goal)${END}`)],
    ["START_WORK", new RegExp(`^/?(?:start-work|asw-start-work|swarmwork-start|asw\\s+start\\s+work)${END}`)],
    ["CLEANUP", new RegExp(`^/?(?:asw-cleanup|asw-remove-ai-slops|swarmwork-cleanup|asw\\s+cleanup)${END}`)],
    ["REVIEW", new RegExp(`^/?(?:asw-review|swarmwork-review|asw\\s+review)${END}`)],
    ["TEST_GUI", new RegExp(`^/?(?:asw-test-gui|swarmwork-test-gui|asw\\s+test[-\\s]+gui)${END}`, "i")],
    ["LOOP", new RegExp(`^/?(?:asw-loop|swarmwork)${END}`)],
    ["ASW", new RegExp(`^/?asw${END}`)],
  ];
  for (const [cmd, re] of rules) {
    if (re.test(trimmed)) return cmd;
  }
  return null;
}

function detectCommand(stripped) {
  const leading = leadingCommandFor(stripped);
  if (leading) return leading;
  if (CLARIFY_RE.test(stripped)) return "CLARIFY";
  if (PLAN_RE.test(stripped)) return "PLAN";
  if (GOAL_RE.test(stripped)) return "GOAL";
  if (START_WORK_RE.test(stripped)) return "START_WORK";
  if (CLEANUP_RE.test(stripped)) return "CLEANUP";
  if (REVIEW_RE.test(stripped)) return "REVIEW";
  if (EXPLICIT_LOOP_RE.test(stripped)) return "LOOP";
  if (GENERIC_ASW_RE.test(stripped)) return "ASW";
  return null;
}

function readPayload() {
  try {
    const raw = readFileSync(0, "utf8");
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function promptFrom(payload) {
  if (typeof payload.lastUserInput === "string" && payload.lastUserInput.trim()) {
    return payload.lastUserInput;
  }
  if (typeof payload.prompt === "string") return payload.prompt;
  if (typeof payload.userMessage === "string") return payload.userMessage;
  if (Array.isArray(payload.steps)) {
    const lastUser = payload.steps
      .map((step) => step?.userMessage)
      .filter((value) => typeof value === "string")
      .at(-1);
    return lastUser ?? "";
  }
  if (typeof payload.transcriptPath === "string") {
    return promptFromTranscript(payload.transcriptPath);
  }
  return "";
}

function stringsFrom(value, out = []) {
  if (typeof value === "string") {
    out.push(value);
  } else if (Array.isArray(value)) {
    for (const item of value) stringsFrom(item, out);
  } else if (value && typeof value === "object") {
    for (const item of Object.values(value)) stringsFrom(item, out);
  }
  return out;
}

function promptFromTranscript(transcriptPath) {
  try {
    const lines = readFileSync(transcriptPath, "utf8").trim().split(/\r?\n/).slice(-200);
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const line = lines[i];
      if (!line) continue;
      try {
        const record = JSON.parse(line);
        const source = String(record.source ?? "");
        const role = String(record.role ?? record.type ?? record.kind ?? "");
        if (/^(MODEL|SYSTEM)$/i.test(source)) continue;
        if (/assistant|system|tool|PLANNER_RESPONSE|GENERIC/i.test(role)) continue;
        const joined = stringsFrom(record).join("\n");
        if (directiveFor(joined, { skipRouter: true })) return joined;
        if (/USER_INPUT|USER_EXPLICIT|^user$/i.test(role) || /USER_EXPLICIT/i.test(source)) {
          return "";
        }
      } catch {
        if (directiveFor(line, { skipRouter: true })) return line;
      }
    }
  } catch {
    return "";
  }
  return "";
}

const PLAN_DIRECTIVE = `ASW PLAN MODE ENABLED! (Model Tier: Gemini 4 Carbon High)

Convert the user request into a decision-complete plan on Gemini 4 Carbon (High) (Model="pro").
- Ground the plan in this repository before asking questions.
- Start with \`## User Intent & Anti-Shortcut Contract\`: verbatim \`REQ-1..N\`, Authoritative Source of Truth, Forbidden Shortcuts.
- Enforce Zero Heuristic Substitution: never replace trained models, math specs, or real APIs with heuristic or synthetic fallbacks.
- Enforce Quad-Model routing: research/planning on Gemini 4 Carbon (High) (Model="pro"); opposition audits on Claude Opus 5.5.
- Run standard reviews/debugging/coordination on Gemini 4 Neon (High) (Model="pro"); coding/TDD on Gemini 4 Hydrogen (High) (Model="flash").
- Write \`.asw/plans/<slug>.md\` with \`## TL;DR\`, \`<!-- <frozen-after-approval> -->\`, Intent/Boundaries, \`## I/O & Edge-Case Matrix\`, \`<!-- </frozen-after-approval> -->\`.
- Include \`## Code Map\`, \`## Execution Tasks\` (\`- [ ]\`), \`## Plan Change Log\`, and \`## Review Triage Log\`.
- Keep single goal (900-1600 tokens); move secondary work to \`.asw/plans/deferred-work.md\`.
- Make tasks atomic: tier, lane, files, L1 build, L2 RED-to-GREEN + parity, L3 QA, evidence, cleanup.
- Default \`git\`, \`pytest\`, \`find\`, \`read -l aggressive\`, \`json\` to \`rtk\` (rtk-token-killer), skipping \`rtk tree\` on Windows.
- Cover happy, negative/edge, and regression QA; mocks never replace Layer 3 proof.
- End with \`Next: start-work <plan-name>\`; never write code in plan mode unless requested.`;

const GOAL_DIRECTIVE = `ASW GOAL MODE ENABLED! (Plan: Gemini 4 Carbon High | Review: Gemini 4 Neon High | Exec: Gemini 4 Hydrogen High)

- Preserve objective across turns with Zero Heuristic Substitution and \`User Intent & Anti-Shortcut Contract\`.
- Use Gemini 4 Carbon (High) (Model="pro") only for initial research/planning; Claude Opus 5.5 handles opposing reviews.
- Use Gemini 4 Neon (High) (Model="pro") for standard reviews, debugging, and orchestration.
- Dispatch Gemini 4 Hydrogen (High) (Model="flash") for leaf coding, TDD, and routine tasks.
- Define success criteria and Forbidden Shortcuts before coding.
- Verify L1 Static/Build, L2 happy/negative/parity tests, and L3 real-surface execution per criterion.
- Track blockers, retries, cleanup receipts, Prompt-to-Code Traceability Matrix, and completion audits.
- Mark complete only at 100% \`- [x]\` with current runtime evidence.`;

const START_WORK_DIRECTIVE = `ASW START-WORK MODE ENABLED! (QA: Gemini 4 Neon High -> Workers: Gemini 4 Hydrogen High)

Execute an ASW plan until 100% of top-level checkboxes (\`- [x]\`) complete.
- Select the named plan, or the single active plan under \`.asw/plans\`.
- Re-read the plan before each step; execute the first unchecked \`- [ ]\` task.
- Obey \`User Intent & Anti-Shortcut Contract\` and Zero Heuristic Substitution: never substitute heuristics, catch-alls, or synthetic data.
- Default \`git\`, \`pytest\`, and inspection commands to \`rtk\` (rtk-token-killer), skipping \`rtk tree\` on Windows.
- Leaf subagents (asw-implementer, asw-explorer, asw-reviewer) emit external receipts <= 250 tokens; internal \`<thought>\` stays unconstrained.
- Dispatch Gemini 4 Hydrogen (High) (Model="flash") for coding/TDD, Gemini 4 Neon (High) (Model="pro") for debugging/QA, Claude Opus 5.5 for opposition review.
- Capture L1 build, L2 RED-to-GREEN happy/negative/parity tests, L3 real-surface proof, and cleanup before checking \`- [x]\`.
- Store state in \`.asw/start-work/\`; never stop with open \`- [ ]\` items unless externally blocked.
- At 100% \`- [x]\`, print \`ORCHESTRATION COMPLETE\` with plan, Traceability Matrix, L1-L3 commands, artifacts, and cleanup.`;

const CLEANUP_DIRECTIVE = `ASW CLEANUP MODE ENABLED! (Gemini 4 Hydrogen High)

Remove AI clutter while preserving exact behavior.
- Bound scope to named files or branch diff.
- Guard behavior with existing tests or a narrow characterization test first.
- Remove dead code, obvious comments, needless guards, stale shims, and duplicate branches only when safe.
- Keep boundary validation and "why" comments; run 3-layer and real-surface QA when behavior changes.`;

const LOOP_DIRECTIVE = `ASW LOOP MODE ENABLED! (Plan: Gemini 4 Carbon High | Review: Gemini 4 Neon High | Exec: Gemini 4 Hydrogen High)

Ship the outcome end-to-end through Antigravity CLI surfaces.
- Draft \`User Intent & Anti-Shortcut Contract\` and initial plan on Gemini 4 Carbon (High) (Model="pro").
- Enforce Zero Heuristic Substitution & Golden Reference End-to-End Decision Parity: never substitute heuristic logits, catch-alls, or gate bypasses.
- Verify reference-vs-target pipeline parity across normal execution, boundary vetoes, and termination lifecycles.
- Enforce Mandatory Rendered DOM & Shadow-Root Zero-Error-Card Gate: reject error overlays or broken custom-element renders.
- Enforce Hardware Fidelity (halt in BLOCKED_ON_HARDWARE_AUTH if unauthorized/offline), Feature-Flag Negative Isolation, and 3-Strike Circuit Breaker (no binary third-party patching).
- Enforce Multi-Tenant Idempotency (\`{principal_id}:{operation_key}\`, persist PENDING first), Production-Volume Distribution, \`--scan-public-repo\` / \`--forbid-terms\`, Baseline Regression, and \`--assert-asset-version\`.
- Write failing RED tests (happy, parity, negative/edge; never tautological \`is not None\`) before coding.
- Default \`git\`, \`pytest\`, \`read -l aggressive\`, \`find\`, \`json\` to \`rtk\` (rtk-token-killer), skipping \`rtk tree\` on Windows (win32).
- Leaf subagents (asw-implementer, asw-explorer, asw-reviewer) emit external receipts <= 250 tokens; internal \`<thought>\` stays unconstrained.
- Implement minimal GREEN code on Gemini 4 Hydrogen (High) (Model="flash").
- Verify Layer 3 real surface via CLI, tmux, HTTP, browser, or GUI; capture artifacts, cleanup, and Traceability Matrix.
- Run \`python .antigravity/scripts/invoke_opus_reviewer.py --mode diff-review --files "<changed_files>" --plan ".asw/plans/<slug>.md"\`; avoid PowerShell \`>\`/\`>>\` or unconfirmed \`Remove-Item\`.
- If Claude Opus 5.5 credits exhaust, \`invoke_opus_reviewer.py\` + Gemini 4 Neon (High) serve as fallback gate.
- MANDATORY SUBAGENT & MODEL-TIER ESCALATION GATE: never run planning, coding, and review inline in one Gemini 4 Hydrogen thread; call \`invoke_subagent\`:
  1. Call \`invoke_subagent(TypeName="asw-planner", Role="ASW Architect & Planner", Model="pro", ...)\` for \`.asw/plans/<slug>.md\` on Pro.
  2. Call \`invoke_subagent(TypeName="asw-implementer", Role="ASW Leaf Implementer", Model="flash", ...)\` for context-free RED-to-GREEN coding from \`{plan_file}\` and \`## Code Map\`.
  3. Call \`invoke_subagent(TypeName="asw-reviewer", Role="ASW 5-Lens Reviewer", Model="pro", ...)\` with \`invoke_opus_reviewer.py --mode diff-review\` on Neon High + Opus 5.5.`;

const REVIEW_DIRECTIVE = `ASW REVIEW MODE ENABLED! (Gemini 4 Neon High + Claude Opus 5.5 + 5-Lens)

Run adversarial review on Gemini 4 Neon (High) (Model="pro") + Claude Opus 5.5 / \`invoke_opus_reviewer.py\`.
Apply 5 lenses since \`baseline_revision\`:
1. blind-hunter: diff-only, zero plan bias, floor \`N = min(floor(sqrt(kB) + 1), 10)\`.
2. edge-case-hunter: trace branches/resources before claims; run deletion-check and claims-check.
3. verification-gap: trace 1-3 caller hops; reject mock-only proof; run missing-adoption check.
4. intent-alignment: compare verbatim user intent vs diff surface.
5. opus-cross-family: check Zero Heuristic Substitution, open \`- [ ]\`, and 4 attack vectors.
- Log findings in ## Review Triage Log.
- Route to [intent_gap], [bad_plan] (keep notes, revert \`baseline_revision\`, log \`## Plan Change Log\`), [patch], or [defer].
- Never alter <frozen-after-approval> or rewrite I/O & Edge-Case Matrix expectations.`;

const CONSULTATION_DIRECTIVE = `ASW CONSULTATION / MODE 1 ENABLED! (Gemini 4 Carbon High | Read-Only)

- Act as read-only architecture and codebase advisor (Mode 1).
- Answer directly using verified repository context.
- Stay read-only: never edit files, write plans, or trigger coding/browser flows unless asked.`;

const TEST_GUI_DIRECTIVE = `ASW TEST-GUI MODE ENABLED! (Exec: Gemini 4 Hydrogen High -> Audit: Claude Opus 5.5 / Neon High)

Run physical GUI/runtime verification on the live surface; mocks never suffice.
- Web: start server; run Playwright or \`python .antigravity/scripts/run_gui_test.py --mode web --start-cmd "<cmd>" --url "http://127.0.0.1:<port>" --assert-text "<expected>" --assert-selector "<selector>" --screenshot ".asw/evidence/gui-screenshot.png" --output ".asw/evidence/gui-test-report.md"\`.
- Check HTTP 200, live DOM, zero \`console.error\`/\`pageerror\`, plus screenshot and report.
- Native/mobile: run \`python .antigravity/scripts/run_gui_test.py --mode native --app-cmd "<cmd>" --wait-seconds 3.0 --output ".asw/evidence/gui-test-report.md"\`.
- Check startup stability, zero tracebacks, and valid rendered UI.
- Fix defects and re-run until \`Verdict: GUI_VERIFIED\` passes; terminate spawned processes in cleanup.`;

export function buildClarifyGateDirective(route) {
  const gate = route && typeof route === "object" ? route.clarification_gate : null;
  const rawDims = Array.isArray(gate?.missing_dimensions) ? gate.missing_dimensions : [];
  const dims = rawDims
    .map((d) => String(d ?? "").trim())
    .filter(Boolean)
    .slice(0, 3);
  const dimsLabel = dims.length > 0 ? dims.join(", ") : "scope_actors, data_persistence, auth_security";
  const maxQ =
    Number.isFinite(Number(gate?.max_questions)) && Number(gate.max_questions) > 0
      ? Math.min(3, Math.trunc(Number(gate.max_questions)))
      : 3;
  return [
    `ASW SPEC-KIT CLARIFY GATE (Unresolved: ${dimsLabel} | Max ${maxQ}):`,
    `1. Repo/Obsidian First: Check codebase/memory; skip discoverable facts; defaults in \`### Assumptions\`.`,
    `2. Single \`ask_question\` (\`<= ${maxQ}\`, 1 round): Ask forks (\`(Recommended) <Best> — <trade-off>\` first), write \`### Clarifications\` (\`- Q -> A\`) + \`I/O & Edge-Case Matrix\` (0 if resolved).`,
  ].join("\n");
}

export function formatAutoSkillsDirective(route) {
  if (!route || route.enabled === false) return "";
  const autoSkills = Array.isArray(route.auto_subskills) ? route.auto_subskills : [];
  const domainSkills = Array.isArray(route.selected_skills) ? route.selected_skills : [];
  const combined = [];
  for (const s of [...autoSkills, ...domainSkills]) {
    const name = String(s ?? "").trim();
    if (name && !combined.includes(name)) combined.push(name);
    if (combined.length >= 8) break;
  }
  if (combined.length === 0) return "";
  const autoShown = [];
  const domainShown = [];
  for (const name of combined) {
    if (autoSkills.includes(name)) autoShown.push(name);
    else domainShown.push(name);
  }
  const parts = [];
  if (autoShown.length > 0) parts.push(`Sub-skills: ${autoShown.join(", ")}`);
  if (domainShown.length > 0) parts.push(`Domain: ${domainShown.join(", ")}`);
  return `AUTO-ACTIVATED SUB-SKILLS & DOMAIN SKILLS:\n- ${parts.join(" | ")}\n- Load only these <= ${combined.length} relevant skills (strict <= 8 cap).`;
}

export function directiveFor(prompt, payload = {}, repoDir = "") {
  const rawRedacted = redactSecrets(String(prompt ?? ""));
  const stripped = stripIgnoredPromptRegions(rawRedacted);
  const cmd = detectCommand(stripped);
  const hasExplicitTestGui = TEST_GUI_RE.test(stripped);

  let base = "";
  let isGenericAsw = false;
  let shouldQueryRouter = false;

  if (cmd === "CLARIFY") {
    base = PLAN_DIRECTIVE;
    shouldQueryRouter = true;
  } else if (cmd === "PLAN") {
    base = PLAN_DIRECTIVE;
    shouldQueryRouter = true;
  } else if (cmd === "GOAL") {
    base = GOAL_DIRECTIVE;
    shouldQueryRouter = true;
  } else if (cmd === "START_WORK") {
    base = START_WORK_DIRECTIVE;
    shouldQueryRouter = true;
  } else if (cmd === "CLEANUP") {
    base = CLEANUP_DIRECTIVE;
  } else if (cmd === "REVIEW") {
    base = REVIEW_DIRECTIVE;
  } else if (cmd === "LOOP") {
    base = LOOP_DIRECTIVE;
    shouldQueryRouter = true;
  } else if (cmd === "ASW") {
    base = LOOP_DIRECTIVE;
    isGenericAsw = true;
    shouldQueryRouter = true;
  }

  if (payload?.skipRouter === true) {
    if (hasExplicitTestGui) {
      return base ? `${base}\n\n${TEST_GUI_DIRECTIVE}` : TEST_GUI_DIRECTIVE;
    }
    return base;
  }

  const autoRouterOptIn =
    !base && (process.env.ASW_AUTO_DECISION_ROUTER === "1" || payload?.autoDecisionRouter === true);

  let route = null;
  if (shouldQueryRouter || autoRouterOptIn) {
    route = queryAutoDecisionRouter(rawRedacted, repoDir);
  }

  let isConsultation = false;
  if (isGenericAsw && !hasExplicitTestGui && route && route.enabled !== false && route.is_consultation === true) {
    base = CONSULTATION_DIRECTIVE;
    isConsultation = true;
  } else if (autoRouterOptIn && route && route.enabled !== false) {
    if (route.requires_subagent_plan_wave) {
      base = LOOP_DIRECTIVE;
    }
  }

  const wantsAutoGui =
    !isConsultation && Boolean(route && route.enabled !== false && route.requires_gui_verification === true);

  const isClarifyEligibleCmd =
    cmd === "ASW" || cmd === "LOOP" || cmd === "PLAN" || cmd === "GOAL" || cmd === "CLARIFY";
  const wantsClarifyGate =
    !isConsultation &&
    isClarifyEligibleCmd &&
    !NO_CLARIFY_RE.test(stripped) &&
    (cmd === "CLARIFY"
      ? route
        ? route.clarification_gate?.needs_clarification === true
        : isDecisionModelEnabled(repoDir)
      : route?.clarification_gate?.needs_clarification === true);

  const sections = [];
  if (base) sections.push(base);
  if (wantsClarifyGate) sections.push(buildClarifyGateDirective(route));
  if (hasExplicitTestGui || wantsAutoGui) sections.push(TEST_GUI_DIRECTIVE);

  const skillsBlock = formatAutoSkillsDirective(route);
  if (skillsBlock && sections.length > 0) {
    sections.push(skillsBlock);
  }

  return sections.join("\n\n");
}

function consumePendingLspDiagnostic(repoDir) {
  if (!repoDir) return "";
  const diagPath = join(repoDir, ".asw", ".pending-lsp-diagnostic.json");
  if (!existsSync(diagPath)) return "";
  try {
    const parsed = JSON.parse(readFileSync(diagPath, "utf8"));
    unlinkSync(diagPath);
    const ts = Number(parsed?.ts ?? 0);
    const maxAgeMs = 5 * 60 * 1000;
    if (ts > 0 && Date.now() - ts > maxAgeMs) {
      return "";
    }
    const diag = String(parsed?.diagnostic ?? "").trim();
    if (!diag) return "";
    return diag.startsWith("ASW POST-EDIT DIAGNOSTIC:")
      ? diag
      : `ASW POST-EDIT DIAGNOSTIC: ${diag}. Fix the syntax/structural error before proceeding to Layer-2 and Layer-3 verification.`;
  } catch {
    try {
      unlinkSync(diagPath);
    } catch {
      // ignore
    }
    return "";
  }
}

export function stripIgnoredPromptRegions(prompt) {
  return String(prompt ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/"(?:\\.|[^"\\\r\n])*"/g, " ")
    .replace(/\u201e[^\u201c\u201d\r\n]*[\u201c\u201d]/g, " ")
    .replace(/\u201c[^\u201d\r\n]*\u201d/g, " ")
    .replace(
      /(?<![A-Za-z0-9_\u00c0-\u024f])'(?:\\.|(?<=[A-Za-z0-9_\u00c0-\u024f])'(?=[A-Za-z0-9_\u00c0-\u024f])|[^'\\\r\n])*?'(?![A-Za-z0-9_\u00c0-\u024f])/g,
      " "
    )
    .replace(
      /(?<![A-Za-z0-9_\u00c0-\u024f])\u2018(?:\\.|(?<=[A-Za-z0-9_\u00c0-\u024f])\u2019(?=[A-Za-z0-9_\u00c0-\u024f])|[^\u2019\\\r\n])*?\u2019(?![A-Za-z0-9_\u00c0-\u024f])/g,
      " "
    );
}

const isMain =
  Boolean(process.argv[1]) &&
  (resolve(process.argv[1]) === fileURLToPath(import.meta.url) ||
    process.argv[1].endsWith("asw-hook.mjs"));

if (isMain) {
  const payload = readPayload();
  const repoDir = resolveWorkspaceDir(payload);

  if (isSessionStartEvent(payload)) {
    const rendered = safeMode(payload) ? "" : querySessionStartEnvFacts(repoDir);
    if (!rendered) {
      process.stdout.write("{}");
    } else {
      process.stdout.write(JSON.stringify({ injectSteps: [{ systemMessage: { systemMessage: rendered } }] }));
    }
  } else {
    const rawPrompt = promptFrom(payload);
    const isSyntheticCascade = SYNTHETIC_MODE_RE.test(rawPrompt);
    const isSubsequentStep = Number(payload.invocationNum) > 1;
    const directive =
      safeMode(payload) || isSubsequentStep || isSyntheticCascade ? "" : directiveFor(rawPrompt, payload, repoDir);
    const pendingLspMsg = safeMode(payload) ? "" : consumePendingLspDiagnostic(repoDir);

    const injectSteps = [];
    if (directive) {
      injectSteps.push({ userMessage: directive });
    }
    const ephParts = [];
    if (pendingLspMsg) ephParts.push(pendingLspMsg);
    if (!directive && !safeMode(payload) && Number(payload.invocationNum) >= 1 && payload.transcriptPath) {
      const nudge = queryTurnGuardNudge(payload.transcriptPath, repoDir);
      if (nudge) ephParts.push(nudge);
    }
    if (ephParts.length > 0) {
      injectSteps.push({ ephemeralMessage: ephParts.join("\n\n") });
    }
    process.stdout.write(injectSteps.length > 0 ? JSON.stringify({ injectSteps }) : "{}");
  }
}
