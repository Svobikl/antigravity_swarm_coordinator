# BMAD-METHOD V7 5-Step Just-In-Time (JIT) Execution Protocol

To prevent context rot and mid-execution instruction amnesia, `asw-loop`, `asw-start-work`, and `swarm-coordinator` execute complex tasks through 5 sequential micro-steps. **Load and focus on one step at a time.**

---

## Step 1: `step-01-clarify-and-route` (Clarify, Bound & Route)
- **Model Tier:** `Gemini 4 Carbon (High)` (`Model="pro"`)
- **Entry Gate:** Recall project memory (`memory_manager.py --recall`) and classify the request into Mode 0–5.
- **Single-Goal Scope Gate:** If the user request bundles multiple independent goals, keep the primary goal in the active plan and split secondary goals into `.asw/plans/deferred-work.md`.
- **Early Exit:** If Mode 0 (direct build/test/run) or Mode 1 (investigation only), execute directly without generating a multi-wave implementation plan.

---

## Step 2: `step-02-plan` (Author Frozen Contract, Matrix & Code Map)
- **Model Tier:** `Gemini 4 Carbon (High)` (`Model="pro"`) + `Claude Opus 5.5` (`--mode plan-review`)
- **Action:**
  1. Scout the exact files and callers to build `## Code Map`.
  2. Draft `.asw/plans/<slug>.md` (900–1600 tokens) enclosing `### Intent`, `### Boundaries & Constraints` (`Always:` / `Never:`), and `### I/O & Edge-Case Matrix` (`M1..Mn`) inside `<!-- <frozen-after-approval> --> ... <!-- </frozen-after-approval> -->`.
  3. Validate mechanical plan contract via `python .antigravity/scripts/bmad_lint_spine.py --file .asw/plans/<slug>.md --mode plan-contract`.
  4. Run the Pre-Execution Plan Opposition Gate: `python .antigravity/scripts/invoke_opus_reviewer.py --mode plan-review --plan .asw/plans/<slug>.md` until `Verdict: PLAN_APPROVED`.

---

## Step 3: `step-03-implement` (Context-Free Subagent Handoff & Matrix Test Audit)
- **Model Tier:** `Gemini 3.8 Flash (High)` (`Model="flash"`)
- **Action:**
  1. **Record `baseline_revision`:** Capture `git rev-parse --short HEAD` into the plan frontmatter before the first code edit.
  2. **Context-Free Subagent Handoff:** Dispatch the bounded implementation subagent with **zero prior conversation history**, passing only `{plan_file}` and its `## Code Map`. Keep the subagent `conversationId` alive for `step-04-review` patches.
  3. **RED -> GREEN -> Real-Surface QA:** Write failing tests for every row `M1..Mn` in `### I/O & Edge-Case Matrix`, implement the minimal genuine production code to pass, and execute the real CLI/API/GUI surface.
  4. **Matrix Test Audit (Hard Invariant):** Verify every row in `### I/O & Edge-Case Matrix` has a covering test that ran and passed. **Never edit `<frozen-after-approval>` or rewrite matrix expectations to match broken code.**
  5. Record claims, deviations, and evidence in `## Implementation Notes`.

---

## Step 4: `step-04-review` (5 Orthogonal Review Lenses & 4-Route Cascading Triage)
- **Model Tier:** `Claude Opus 5.5` + `Gemini 4 Carbon (High)`
- **Action:**
  1. Evaluate the diff since `baseline_revision` across all 5 orthogonal lenses (`blind-hunter`, `edge-case-hunter` with `deletion-check` & `claims-check`, `verification-gap` with caller hop trace & `missing-adoption` check, `intent-alignment`, and `opus-cross-family` via `invoke_opus_reviewer.py --mode diff-review`).
  2. Verify every finding against the actual source code, log it in `## Review Triage Log`, and route by highest blast radius:
     - **`[intent_gap]`:** Revert code to `baseline_revision`, clarify with the user, and return to `step-02-plan`.
     - **`[bad_plan]`:** Extract `KEEP` notes (what worked), revert code to `baseline_revision`, append the dead-end to `## Plan Change Log` (so it is never repeated), update the non-frozen plan, and re-run `step-03-implement`.
     - **`[patch]`:** Send minimal localized fix back to the existing `step-03` subagent `conversationId`, re-run full verification, and mark `RESOLVED` in `## Review Triage Log`.
     - **`[defer]`:** Append out-of-scope follow-ups to `.asw/plans/deferred-work.md`.

---

## Step 5: `step-05-present` (Clean Handoff, Pitfall Capture & Memory Sync)
- **Model Tier:** `Gemini 4 Carbon (High)` / `Gemini 3.8 Flash (High)`
- **Action:**
  1. Verify all `- [x]` checkboxes are closed, `## Review Triage Log` has zero unresolved `[intent_gap]`/`[bad_plan]`/`[patch]` items, and `Verdict: ASW APPROVED` is on disk.
  2. If review uncovered a recurring repo pitfall, either automate it into a check or record it in `<!-- bmad:context -->` in `AGENTS.md` and via `memory_manager.py --record-lesson`.
  3. Present the concise verification summary, `Prompt-to-Code Traceability Matrix`, and cleanup receipts to the user.
