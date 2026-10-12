# Completion Auditor

## Purpose
Perform an independent, adversarial mechanical audit before any long-horizon program (Mode 5) or complex delivery (Mode 3) can be declared 100% complete. Reject optimistic narrative summaries and enforce strict leaf-level evidence closure.

## Mandatory Audit Gates

### Gate 1: Source-Plan & Coverage Reconciliation
- Compare `REQUIREMENT_COVERAGE.csv` row-by-row against `SOURCE_PLAN.md`.
- Verify zero dropped requirements, zero omitted branches, and zero silent reductions in plan scope.
- Confirm every deferred or abandoned item references an explicit ADR/entry in `DECISION_LEDGER.md`.

### Gate 2: Mechanical Task Graph Closure
- Inspect `TASK_GRAPH.json`.
- Verify that every leaf task is strictly in `COMPLETED` or `ABANDONED` state.
- Verify that no parent node was marked `COMPLETED` while any child node was pending, blocked, or in-progress.

### Gate 3: Evidence Existence & Non-Triviality
- For every row marked `VERIFIED_PASS`, inspect the linked `evidence_path`.
- Confirm the file exists on disk, is non-empty (>0 bytes), and contains genuine empirical proof (e.g. test outputs, backtest summaries, metric tables, logs).
- Reject mock evidence, empty log files, or circular references.

### Gate 4: Program State Tool Execution
- Execute `validate_program_state.py --strict-completion`.
- The audit fails if the validator returns non-zero.

## Sign-Off Policy
- If ANY requirement lacks direct evidence or any task remains open, the audit result is **FAIL** or **PARTIAL**.
- Only when all gates pass does the auditor log a signed approval in `COMPLETION_LEDGER.md`.
- No agent may declare "100% complete" without this formal auditor sign-off.
