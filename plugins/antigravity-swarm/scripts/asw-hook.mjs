#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { redactSecrets, safeMode } from "./asw-redact.mjs";

const WORD = "(?<![A-Za-z0-9_/-])";
const END = "(?![A-Za-z0-9_/-])";
const PLAN_RE = new RegExp(`${WORD}(?:asw-plan|swarmwork-plan|asw\\s+plan)${END}`);
const GOAL_RE = new RegExp(`${WORD}(?:asw-goal|swarmwork-goal|asw\\s+goal)${END}`);
const START_WORK_RE = new RegExp(`${WORD}(?:start-work|asw-start-work|swarmwork-start|asw\\s+start\\s+work)${END}`);
const CLEANUP_RE = new RegExp(`${WORD}(?:asw-cleanup|asw-remove-ai-slops|swarmwork-cleanup|asw\\s+cleanup)${END}`);
const LOOP_RE = new RegExp(`${WORD}(?:asw-loop|asw|swarmwork)${END}`);
const REVIEW_RE = new RegExp(`${WORD}(?:asw-review|swarmwork-review|asw\\s+review)${END}`);
const TEST_GUI_RE = new RegExp(`${WORD}(?:asw-test-gui|swarmwork-test-gui|asw\\s+test[-\\s]+gui)${END}`, "i");

function readPayload() {
  try {
    const raw = readFileSync(0, "utf8");
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function promptFrom(payload) {
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
        const role = record.role ?? record.type ?? record.kind ?? "";
        if (typeof role === "string" && /assistant|system|tool/i.test(role)) continue;
        const joined = stringsFrom(record).join("\n");
        if (directiveFor(joined)) return joined;
      } catch {
        if (directiveFor(line)) return line;
      }
    }
  } catch {
    return "";
  }
  return "";
}

const PLAN_DIRECTIVE = `ASW PLAN MODE ENABLED! (Model Tier: Gemini 4 Argon High)

You are Antigravity Swarm's planning specialist running on Gemini 4 Argon (High) (Model="pro"). Convert the user request into a decision-complete implementation plan for Antigravity CLI.

Required behavior:
- Ground the plan in the current repository before asking questions.
- Start the plan with a mandatory ## User Intent & Anti-Shortcut Contract section declaring:
  * Verbatim User Requirements (REQ-1..N)
  * Authoritative Source of Truth (exact model artifacts, datasets, or API endpoints)
  * Forbidden Shortcuts & Heuristics (explicitly enforcing Zero Heuristic Substitution — never replace trained models, mathematical specs, or real APIs with hand-coded _sigmoid/logit heuristics, catch-all SCANNING -> ENTER_LONG fallbacks, or synthetic fallbacks).
- Enforce Dual-Model Cognitive Routing in every plan wave:
  * Research, problem analysis, architecture, and final review lanes MUST use Gemini 4 Argon (High) (Model="pro").
  * Implementation coding, TDD RED-to-GREEN, and test runner lanes MUST use Gemini 3.8 Flash (High) (Model="flash").
- Write the plan to .asw/plans/<slug>.md with ## TL;DR, ## User Intent & Anti-Shortcut Contract, ## TODOs (using - [ ] top-level checkboxes), exact files, tests, hook surfaces, and 3-layer QA commands.
- Make every TODO atomic: assigned model tier (Flash High vs Argon High), lane, files, Layer 1 (Static/Build check), Layer 2 (RED-to-GREEN happy + negative domain + artifact parity test), Layer 3 (real-surface runtime QA command), artifact path, and cleanup receipt.
- Include happy-path, edge-case/negative, and adjacent-surface regression QA scenarios; mocked unit tests never substitute for Layer 3 real-surface runtime proof.
- Include privacy/package safeguards and cleanup receipts for any spawned QA state.
- End with Next: start-work <plan-name>; do not end with a passive "let me know" handoff.
- Do not implement code while in plan mode unless the user explicitly asks to execute.`;

const GOAL_DIRECTIVE = `ASW GOAL MODE ENABLED! (Orchestrator: Gemini 4 Argon High -> Execution: Gemini 3.8 Flash High)

You are Antigravity Swarm's durable goal orchestrator. Convert the request into explicit goals, success criteria, User Intent & Anti-Shortcut Contract, and 3-layer evidence requirements.

Required behavior:
- Preserve the user's full objective across turns and sessions with Zero Heuristic Substitution.
- Use Gemini 4 Argon (High) (Model="pro") for research, problem analysis, planning, and adversarial review.
- Dispatch Gemini 3.8 Flash (High) (Model="flash") subagents for bounded leaf implementation and TDD execution.
- Define concrete success criteria and Forbidden Shortcuts before implementation begins.
- Assign each criterion to 3-Layer Verification: (1) Static/Build, (2) Automated happy + negative domain + parity tests, and (3) Real-surface runtime execution (CLI, HTTP/API, browser/UI, or data pipeline).
- Track blockers, retries, cleanup receipts, Prompt-to-Code Traceability Matrix, and completion audits.
- Do not mark completion until 100% of plan checkboxes are checked (- [x]) and proven by current runtime evidence.`;

const START_WORK_DIRECTIVE = `ASW START-WORK MODE ENABLED! (Orchestrator: Gemini 4 Argon High -> Leaf Workers: Gemini 3.8 Flash High)

You are Antigravity Swarm's plan executor. Execute an existing ASW plan until 100% of top-level checkboxes (- [x]) are complete.

Required behavior:
- Select the named plan, or the only active plan under .asw/plans when the user did not name one.
- Re-read the plan from disk before each step and execute the first unchecked top-level checkbox (- [ ]).
- Strictly obey the User Intent & Anti-Shortcut Contract and Zero Heuristic Substitution Law: never substitute trained models, formulas, or external APIs with hand-coded heuristics, catch-all ENTER_LONG fallbacks, or synthetic data.
- Dispatch Gemini 3.8 Flash (High) (Model="flash") subagents for independent implementation & TDD subtasks; use Gemini 4 Argon (High) (Model="pro") for root-cause analysis and adversarial QA verification.
- For every checkbox, capture 3-Layer Verification (Layer 1 Static/Build, Layer 2 RED-to-GREEN happy + negative domain + parity tests, Layer 3 real-surface runtime proof) and cleanup receipts before marking it - [x].
- Keep local continuation state in .asw/start-work/ and update the plan only after verification passes.
- Never stop or summarize partial progress while unchecked - [ ] items remain unless blocked by an unresolvable external dependency.
- When all top-level checkboxes are complete (- [x]), print ORCHESTRATION COMPLETE with the plan path, Prompt-to-Code Traceability Matrix, 3-layer verification commands, artifacts, and cleanup receipts.`;

const CLEANUP_DIRECTIVE = `ASW CLEANUP MODE ENABLED! (Model Tier: Gemini 3.8 Flash High)

You are Antigravity Swarm's cleanup specialist. Remove AI-looking clutter while preserving behavior.

Required behavior:
- Bound the scope to the named files or changed branch diff.
- Preserve behavior with existing tests or a narrow characterization test before cleanup edits.
- Remove obvious comments, dead code, needless defensive code, stale compatibility shims, duplicate branches, and oversized structure only when the behavior is proven safe.
- Keep validation at real boundaries and preserve comments that explain why.
- Run relevant 3-layer verification and real-surface QA when cleanup affects user-visible behavior.`;

const LOOP_DIRECTIVE = `ASW LOOP MODE ENABLED! (Analysis/Review: Gemini 4 Argon High -> Implementation/TDD: Gemini 3.8 Flash High)

You are Antigravity Swarm's evidence-driven execution loop. Ship the requested outcome end-to-end through Antigravity CLI surfaces.

Required behavior:
- Start with a concrete User Intent & Anti-Shortcut Contract (Verbatim User Requirements, Authoritative Source of Truth, and Forbidden Shortcuts) and problem analysis on Gemini 4 Argon (High) (Model="pro").
- Enforce Zero Heuristic Substitution: never replace trained ML/quant models, mathematical specs, or real APIs with hand-coded _sigmoid/logit heuristics, catch-all SCANNING -> ENTER_LONG fallbacks, naive binary stop_loss labels, or synthetic fallbacks.
- Write failing RED tests (covering happy path, artifact parity, and negative domain/edge cases, never tautological 'is not None' checks) before production changes.
- Run the smallest genuine implementation on Gemini 3.8 Flash (High) (Model="flash") that flips RED to GREEN.
- Drive the real surface (Layer 3) through CLI, tmux, HTTP, browser, or computer-use QA — never rely on mocks alone.
- Capture artifacts, cleanup receipts, and a Prompt-to-Code Traceability Matrix verifying every user requirement.
- Use subagents when work can proceed in parallel without shared-state conflicts.`;

const REVIEW_DIRECTIVE = `ASW REVIEW MODE ENABLED! (Model Tier: Gemini 4 Argon High)

You are Antigravity Swarm's adversarial reviewer running on Gemini 4 Argon (High) (Model="pro"). Inspect the diff for behavioral regressions, heuristic shortcut substitutions (Zero Heuristic Substitution Law), catch-all execution fallbacks, unchecked plan items (- [ ]), tautological or mock-only test illusions, missing negative domain tests, unsafe packaging, stale docs, and hook/LSP failures.

Lead with findings ordered by severity and include a Prompt-to-Code Traceability Matrix. Treat any heuristic substitution, unchecked plan item, or missing Layer 3 real-surface QA evidence as a blocking issue.`;

const TEST_GUI_DIRECTIVE = `ASW TEST-GUI MODE ENABLED! (Physical GUI & Localhost Verification: Gemini 3.8 Flash High -> Audit: Claude Opus 5.5 / Argon High)

You MUST perform physical GUI and runtime verification of the implemented application surface (never rely on unit tests or mocks alone):
- For Web / Full-Stack apps: Start the localhost dev/preview server (if not already running), run Playwright and/or \`python .antigravity/scripts/run_gui_test.py --mode web --start-cmd "<cmd>" --url "http://127.0.0.1:<port>" --assert-text "<expected>" --assert-selector "<selector>" --screenshot ".asw/evidence/gui-screenshot.png" --output ".asw/evidence/gui-test-report.md"\`, verify HTTP 200, inspect live DOM elements, confirm zero browser console.error / uncaught pageerror exceptions, and capture screenshot + report.
- For Native Desktop / Mobile apps: Launch the actual application binary/window via \`python .antigravity/scripts/run_gui_test.py --mode native --app-cmd "<cmd>" --wait-seconds 3.0 --output ".asw/evidence/gui-test-report.md"\` (or emulator/device runner), verify startup stability with zero crash tracebacks, and inspect rendered UI state.
- If Verdict: GUI_FAILED occurs, fix the underlying UI/runtime defect and re-run physical GUI verification until Verdict: GUI_VERIFIED passes.
- Always terminate spawned dev servers, browsers, and GUI processes in cleanup before finishing.`;

function directiveFor(prompt) {
  prompt = redactSecrets(stripIgnoredPromptRegions(prompt));
  let base = "";
  if (PLAN_RE.test(prompt)) base = PLAN_DIRECTIVE;
  else if (GOAL_RE.test(prompt)) base = GOAL_DIRECTIVE;
  else if (START_WORK_RE.test(prompt)) base = START_WORK_DIRECTIVE;
  else if (CLEANUP_RE.test(prompt)) base = CLEANUP_DIRECTIVE;
  else if (REVIEW_RE.test(prompt)) base = REVIEW_DIRECTIVE;
  else if (LOOP_RE.test(prompt)) base = LOOP_DIRECTIVE;

  if (TEST_GUI_RE.test(prompt)) {
    return base ? `${base}\n\n${TEST_GUI_DIRECTIVE}` : TEST_GUI_DIRECTIVE;
  }
  return base;
}

function stripIgnoredPromptRegions(prompt) {
  return String(prompt ?? "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ");
}

const payload = readPayload();
const directive = safeMode(payload) ? "" : directiveFor(promptFrom(payload));
if (!directive) {
  process.stdout.write("{}");
} else {
  process.stdout.write(JSON.stringify({ injectSteps: [{ userMessage: directive }] }));
}
