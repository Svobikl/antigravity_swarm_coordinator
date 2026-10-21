---
name: completion-auditor
description: Performs final mechanical closure, stub scans, and 3-layer evidence audits before sign-off.
---

# Completion Auditor

## Purpose
Perform an independent, adversarial mechanical audit on **`Gemini 4 Argon (High)` (`Model="pro"`)** before any long-horizon program (Mode 5), complex delivery (Mode 3), or multi-step change (Mode 2) can be declared 100% complete. Reject optimistic narrative summaries, catch unfinished plan checkboxes, and enforce strict leaf-level 3-layer evidence closure.

## Mandatory Audit Gates (`Gemini 4 Argon High`)

### Gate 1: Source-Plan & Checklist Reconciliation (Zero Dropped Steps)
- **Mode 5**: Compare `REQUIREMENT_COVERAGE.csv` row-by-row against `SOURCE_PLAN.md`.
- **Mode 2 / Mode 3**: Compare the delivered diff and verification outputs line-by-line against `.asw/plans/<slug>.md` and the user's original prompt.
- Verify **zero `- [ ]` unchecked items**, zero dropped requirements, zero omitted branches, and zero silent reductions in plan scope.
- Scan modified files for left-behind placeholder stubs (`TODO`, `FIXME`, `NotImplementedError`, hardcoded mock returns in production paths).

### Gate 2: Mechanical Task Graph & Plan Closure
- Inspect `TASK_GRAPH.json` (Mode 5) or `.asw/plans/<slug>.md` (Modes 2/3).
- Verify that 100% of leaf tasks / checkboxes are strictly in `COMPLETED` (`- [x]`) or explicitly governed `ABANDONED` state.
- Verify that no parent node or milestone was marked `COMPLETED` while any child node was pending, blocked, or in-progress.

### Gate 3: 3-Layer Evidence Existence & Real-Surface Proof
- For every completed requirement or task, inspect the linked `evidence_path`.
- Confirm the file exists on disk, is non-empty (>0 bytes), and contains genuine empirical proof across all 3 layers:
  1. Static/build check pass;
  2. Automated unit + negative/edge test pass;
  3. **Real-surface runtime proof** (actual CLI, API, UI, or pipeline execution output — never just mocked unit tests).
- Reject mock-only evidence, empty log files, or circular references.

### Gate 4: Program State Tool Execution
- In Mode 5 (or whenever `TASK_GRAPH.json` exists), execute `python .antigravity/scripts/validate_program_state.py --strict-completion`.
- The audit fails if the validator returns non-zero.

## Sign-Off Policy
- If ANY requirement lacks 3-layer direct evidence or any plan checkbox/task remains open, the audit result is **FAIL** or **PARTIAL**, and the coordinator MUST resume implementation waves via `Gemini 3.8 Flash (High)`.
- Only when all gates pass does the auditor log a signed approval in `COMPLETION_LEDGER.md` (or the final Mode 3 handoff).
- No agent may declare "100% complete" without this formal `Gemini 4 Argon (High)` auditor sign-off.


