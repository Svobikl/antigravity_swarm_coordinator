---
name: asw
description: Antigravity Swarm execution loop for evidence-driven TDD, subagents, and real-surface QA.
---

# Antigravity Swarm Coordinator & Autonomous Execution Loop (`/asw`)

Use this skill when the user invokes `/asw`, `asw`, `asw-loop`, or `swarmwork` to complete a non-trivial coding, architecture, debugging, documentation, packaging, or automation task.

## MANDATORY SWARM COORDINATOR & `invoke_subagent` DISPATCH GATE (CRITICAL)

**Never execute a multi-step or code-changing `/asw` task entirely inline in a single `Gemini 4 Hydrogen` (`flash`) thread!**

In Antigravity, the UI model selector only sets the model of the **main conversation thread**. Reading a skill does **NOT** automatically switch the main thread's model. Therefore, to enforce the **Quad-Model Cross-Family Architecture (`Gemini 4 Carbon High` + `Claude Opus 5.5` + `Gemini 4 Neon High` + `Gemini 4 Hydrogen High`)**, the main agent MUST act as the **Swarm Coordinator** and actively dispatch subagents via `invoke_subagent` with explicit `Model` overrides:

1. **Step 1 — Recall & Mode Classification (`step-01-clarify-and-route`):**
   - Run `python .antigravity/scripts/memory_manager.py --recall --project-path . --task-type code` to load project memory and lessons.
   - Classify the request into Mode 0-5 (`GLOBAL_DEVELOPMENT_RULES.md`). (Only Mode 0 operational commands or Mode 1 read-only diagnostic questions may run without an implementation subagent wave.)
2. **Step 2 — Plan, `<frozen-after-approval>` Contract & `Code Map` (`step-02-plan` -> `Gemini 4 Carbon High` + `Claude Opus 5.5`):**
   - **If the main conversation is running on `Gemini 4 Hydrogen` (`flash`), you are FORBIDDEN from authoring the architectural plan inline on Hydrogen.** You MUST call:
     `invoke_subagent(TypeName="asw-planner", Role="ASW Architect & Planner (Carbon High)", Model="pro", Prompt="Draft .asw/plans/<slug>.md with <frozen-after-approval> (Intent, Boundaries, I/O & Edge-Case Matrix M1..Mn) and ## Code Map, then validate with bmad_lint_spine.py --mode plan-contract and invoke_opus_reviewer.py --mode plan-review.")`
   - (If the main conversation is already running on `Pro` / `Carbon High`, you may author `.asw/plans/<slug>.md` directly or via `asw-planner`, and audit it via `bmad_lint_spine.py --mode plan-contract` + `invoke_opus_reviewer.py --mode plan-review` until `Verdict: PLAN_APPROVED`.)
3. **Step 3 — Context-Free Leaf Implementation & TDD (`step-03-implement` -> `Gemini 4 Hydrogen High`):**
   - Record `baseline_revision` (Git HEAD short SHA) in `.asw/plans/<slug>.md`.
   - Dispatch bounded leaf implementation subagent(s) on **`Model="flash"` (`Gemini 4 Hydrogen High`)**:
     `invoke_subagent(TypeName="asw-implementer", Role="ASW Leaf Implementer (Hydrogen High)", Model="flash", Prompt="Execute Wave <N> from .asw/plans/<slug>.md using its ## Code Map. Run RED -> GREEN -> Layer 3 Real-Surface QA, verify every row M1..Mn in I/O & Edge-Case Matrix, never modify <frozen-after-approval>, and record results in ## Implementation Notes.")`
   - Retain the subagent `conversationId` for targeted `[patch]` fixes in Step 4. When multiple tasks have zero file overlap, dispatch up to 4 parallel `asw-implementer` subagents (`Model="flash"`).
4. **Step 4 — 5-Lens BMAD + Opus Opposition Review (`step-04-review` -> `Gemini 4 Neon High` + `Claude Opus 5.5`):**
   - **Never let `Gemini 4 Hydrogen` grade or approve its own implementation diff!**
   - Dispatch the review subagent on **`Model="pro"` (`Gemini 4 Neon High`)** paired with `invoke_opus_reviewer.py`:
     `invoke_subagent(TypeName="asw-reviewer", Role="ASW 5-Lens & Opus Reviewer (Neon High)", Model="pro", Prompt="Execute the 5 orthogonal review lenses (blind-hunter, edge-case-hunter with deletion-check & claims-check, verification-gap with caller hop trace, intent-alignment, and opus-cross-family via invoke_opus_reviewer.py --mode diff-review) on .asw/plans/<slug>.md and record findings in ## Review Triage Log.")`
   - Route any verified findings in `## Review Triage Log` (`[intent_gap]`, `[bad_plan]`, `[patch]` via `send_message` to the `asw-implementer` `conversationId`, or `[defer]`) until `Verdict: ASW APPROVED` and 100% of `- [x]` checkboxes are closed.
5. **Step 5 — Clean Handoff & Memory Sync (`step-05-present`):**
   - Present the `ASW REPORT` and `Prompt-to-Code Traceability Matrix` after all 3 verification layers and cleanup receipts are complete.

## Operating Contract

1. Define the observable outcome before editing.
2. Read repository guidance and the files that own the behavior.
3. Write a failing automated test for each production behavior change.
4. Implement the smallest change that makes the test pass.
5. Run the real user-facing surface through tmux, HTTP, browser, or computer-use QA.
6. Capture the artifact path or transcript and clean up spawned state.
7. Use Antigravity subagents (`asw-planner`, `asw-implementer`, `asw-reviewer`, `asw-explorer`, `asw-librarian`) across the Quad-Model architecture.
8. Default developer commands (git status/diff/log, pytest, find, read -l aggressive, json) to `rtk` CLI proxy (`rtk-token-killer`) for 50-98% token reduction, bypassing `rtk tree` on Windows.

## Hook Aliases

The installed PreInvocation hook (`hooks.json` -> `asw-hook.mjs`) wakes this mode from `asw`, `asw-loop`, and `swarmwork`.

## Automatic Sub-Skill Orchestration & Mode-1 Routing

- **Automatic Sub-Skill & Domain Routing (`<= 8` Active Cap, `0.0` LLM Tokens):** `asw-hook.mjs` + `decision_router.py` automatically activate `asw-ui-ux` + `asw-test-gui` on action GUI tasks (`requires_gui_verification: true`), `asw-ui-ux` on visual README/SVG tasks, `asw-debug` on crashes/bugs/tracebacks, `asw-refactor` on structural refactoring, and `asw-cleanup` on dead-code/slop cleanup alongside top domain skills within the `<= 8` budget (`opt_tokens: 0.0`). Whenever `AUTO-ACTIVATED SUB-SKILLS & DOMAIN SKILLS` is injected, read and enforce those `SKILL.md` contracts.
- **Mode-1 Read-Only Consultation & Quote-Safe Command Resolution:** Pure read-only `/asw <question>?` prompts (without action/fix/verify verbs) route to `ASW CONSULTATION / MODE 1` (read-only analysis, zero code edits or Playwright runs). Quoted or backticked mentions (`"asw-plan"`, `„...“`, `'...'`, keeping contractions like `don't`) never hijack the leading slash command.

## Loop Discipline

- Keep a visible success contract near the top of the working notes.
- Prefer one thin vertical slice over many half-edited files.
- Spawn `asw-explorer` (`Model="flash"`) for read-only mapping, `asw-librarian` (`Model="pro"`) for current external docs, `asw-planner` (`Model="pro"`) for planning, `asw-implementer` (`Model="flash"`) for bounded coding, and `asw-reviewer` (`Model="pro"`) for final verification.
- Serialize dependent waves across `asw-implementer` subagent invocations so file ownership stays clear.
- When the task touches install, hooks, package contents, README, or screenshots, verify the shipped surface instead of only unit tests.
- Stop and surface a blocker only after local discovery and at least one fallback path fail.

## Completion Gate

Before saying the work is done, confirm:

- requested behavior is present,
- relevant tests or diagnostics passed,
- real user-facing surface was exercised,
- temporary state was cleaned up,
- git/npm/package boundaries do not include private or generated material,
- docs describe what was actually verified.

## Binding Success Criteria

For non-trivial work, write a compact success contract before editing:

```text
Deliverable:
Criteria:
- happy path:
- edge case:
- regression:
Tests:
- file + test id:
Manual QA:
- channel:
- command or action:
- expected observable:
Cleanup:
```

Each criterion needs automated evidence and real-surface evidence when users can observe the behavior. Tests are necessary; they are not the whole completion proof.

## Manual QA Channels

Pick the channel that matches the surface:

- HTTP call: API endpoints and service contracts.
- tmux: terminal applications, installers, hooks, CLIs, and status lines.
- Browser use: web pages and browser-visible flows.
- Computer use: desktop or IDE surfaces.

Auxiliary checks such as parsed config dumps, package file lists, and stdout inspection are valid supporting evidence for data-shaped work. They do not replace a channel scenario when the user interacts with the surface.

Every scenario must name:

- exact command or action,
- concrete input,
- expected binary pass/fail observable,
- artifact path or transcript,
- cleanup receipt.

## Durable Notepad

Keep a durable working note for complex work. Prefer `.asw/` runtime state when it belongs to the workflow, or a temp note when the work should not create repo files.

Suggested sections:

```text
Plan:
Success criteria + QA scenarios:
Now:
Todo:
Findings:
Learnings:
Evidence:
Cleanup:
```

Append updates as work progresses. Do not rewrite history in the note; add a correction when assumptions change.

## Todo Discipline

Use small todos:

- one observable criterion at a time,
- one production edit wave at a time,
- one active item at a time,
- mark completion only after evidence exists.

Good todo shape:

```text
path: action for criterion — verify by command/artifact
```

## Verification Gate

Trigger a reviewer pass when the work is broad, risky, release-related, package-related, refactor-heavy, or explicitly requested as rigorous.

The reviewer must receive:

- user goal,
- success criteria,
- diff,
- tests run,
- manual QA artifacts,
- package/private scans,
- residual risks.

Treat reviewer concerns as blockers until fixed or explicitly handed back to the user as a product decision.

## Cleanup Receipts

Every spawned resource needs a receipt:

- tmux session closed,
- temp directory removed,
- browser context closed,
- server stopped,
- generated preview deleted,
- config restored or intentionally kept,
- package tarball removed if produced.

Leftover QA state means the loop is not complete.

## Final Report

Return:

```text
ASW REPORT
Outcome:
Criteria:
Tests:
Manual QA:
Cleanup:
Package/private surface:
Reviewer:
Commit:
Residual risk:
```

## User Intent & Anti-Shortcut Contract (Zero Heuristic Substitution Law)
- Every ASW execution must begin by declaring `Verbatim User Requirements`, `Authoritative Source of Truth`, and `Forbidden Shortcuts & Heuristics`.
- Never replace trained ML/quant models, mathematical specifications, or external APIs with hand-coded `_sigmoid` / linear heuristics, catch-all idle-to-action fallbacks, naive binary threshold labels, or synthetic fallback pools.
- Include a **Prompt-to-Code Traceability Matrix** in the final ASW REPORT.
