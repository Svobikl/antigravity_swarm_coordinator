---
name: asw-loop
description: Executes strict RED-to-GREEN-to-Real-Surface QA implementation waves with cleanup receipts.
---

# Antigravity Swarm Loop

Use this skill when a plan exists or the work is clear enough to execute.

## Loop

1. Pick one criterion.
2. Write the failing test and capture RED output.
3. Implement the smallest production change.
4. Capture GREEN output.
5. Run the real Antigravity or application surface.
6. Record cleanup.
7. Re-run the full relevant suite.

Never claim completion from tests alone.

## Subagent Use & Mandatory Model-Tier Escalation Gate

- **Never execute planning, coding, and review all inline in a single `Gemini 4 Hydrogen` (`flash`) thread!** Because the UI dropdown only sets the main thread's model, you MUST call `invoke_subagent` with explicit `Model` overrides so each cognitive tier runs on its designated model:
  - **Planner lane (`asw-planner`, `Model="pro"`):** Author `.asw/plans/<slug>.md` with `<frozen-after-approval>` (`I/O & Edge-Case Matrix`) and `## Code Map` whenever the main thread is on `Hydrogen` (or for any multi-step Mode 2/3/5 task).
  - **Explorer lane (`asw-explorer`, `Model="flash"`):** Locate owners, callers, tests, configs, and prior art.
  - **Librarian lane (`asw-librarian`, `Model="pro"`):** Check current official docs for libraries or external CLIs.
  - **Implementer lane (`asw-implementer`, `Model="flash"`):** Execute context-free RED -> GREEN -> Layer 3 QA waves from `{plan_file}` and `## Code Map`.
  - **Reviewer lane (`asw-reviewer`, `Model="pro"` + `invoke_opus_reviewer.py`):** Inspect the diff across the 5 BMAD + Opus review lenses after implementation.

## Evidence Ledger

For each criterion, keep a terse ledger:

```text
Criterion:
RED:
Change:
GREEN:
Real surface:
Cleanup:
```

If any row is empty, the loop is still running.

## Criterion Loop

Run one criterion at a time:

```text
Criterion:
Automated test:
Manual QA channel:
Expected observable:
Cleanup target:
```

If the criterion is too broad, split it before editing. A criterion should be small enough that one failing test and one real-surface scenario can prove it.

## RED to GREEN

For behavior changes:

1. Write the automated test first.
2. Run it and capture the failing assertion.
3. Make the smallest production change.
4. Run the same test and capture the passing output.
5. Run adjacent regression tests.

For refactors:

1. Identify characterization coverage.
2. Run it green before the refactor.
3. Change structure only.
4. Run it green again.

Do not write production code first and backfill a test later.

## Surface Scenario

After GREEN, run the real surface:

- CLI and installer: tmux transcript.
- Hook: installed or script-level payload smoke with exact input.
- HUD/status line: status payload through the real script.
- Package: dry-run file list and bad-pattern scan.
- Browser: action log and screenshot.
- Desktop/IDE: visible action log and screenshot.

Record:

```text
Scenario:
Tool/channel:
Input:
Expected:
Artifact:
PASS/FAIL:
```

## Cleanup Pairing

Pair every scenario with cleanup:

- close tmux session,
- remove temp config,
- remove temp package output,
- stop servers,
- close browser context,
- remove generated scratch files.

Record cleanup beside the scenario. Do not leave cleanup for the end when multiple scenarios run.

## Reviewer Gate

Run review when:

- 3 or more files changed,
- package contents changed,
- hooks changed,
- public docs changed,
- refactor/migration work occurred,
- the user requested deep or final review.

Reviewer input:

- criteria ledger,
- RED/GREEN evidence,
- surface artifacts,
- diff,
- package/private scan,
- cleanup receipts.

Approval requires no blockers and no missing evidence.

## Stop Rules

Stop and report instead of guessing when:

- a green baseline cannot be established,
- a criterion cannot be tied to a real surface,
- cleanup cannot be verified,
- the same failure repeats after two targeted fixes,
- the user-visible contract is ambiguous.

## Final Output

```text
Criterion ledger:
Tests:
Surface QA:
Cleanup:
Reviewer:
Final status:
```

## User Intent & Anti-Shortcut Contract (Zero Heuristic Substitution Law)
- Start every loop by locking `Verbatim User Requirements`, `Authoritative Source of Truth`, and `Forbidden Shortcuts & Heuristics`.
- Never replace trained ML/quant models, formulas, or external APIs with hand-coded `_sigmoid` / linear heuristics, catch-all idle-to-action fallbacks, or synthetic fallback pools.
- Verify a **Prompt-to-Code Traceability Matrix** and numerical artifact parity (`max_abs_diff < 1e-6`) before closing the loop.

## BMAD-METHOD V7 5-Step Just-In-Time (JIT) Loop & Matrix Test Audit

Follow `references/bmad-steps.md` across every execution wave:
1. **`step-01-clarify-and-route` -> `step-02-plan`:** Bound to a single goal, freeze `<frozen-after-approval>` (`Intent`, `Boundaries`, `I/O & Edge-Case Matrix`), and map `## Code Map`.
2. **`step-03-implement` (Matrix Test Audit):** Capture `baseline_revision`, dispatch context-free `Gemini 4 Hydrogen (High)` subagents with `{plan_file}`, and verify every row `M1..Mn` in `I/O & Edge-Case Matrix` has a passing test. Never edit `<frozen-after-approval>` to make a failing test pass.
3. **`step-04-review` -> `step-05-present`:** Run the 5 orthogonal review lenses and resolve all `[intent_gap]`, `[bad_plan]`, and `[patch]` items in `## Review Triage Log` before completion.
