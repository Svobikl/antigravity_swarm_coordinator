# Program State Controller

## Purpose
Maintain the machine-verifiable persistent control plane for long-horizon programs (Mode 5). Derive parent task status mechanically from child tasks, govern program state files, and enforce ledger integrity.

## Authoritative Control Plane Artifacts
1. `SOURCE_PLAN.md` — Immutable, verbatim copy of the user's original plan. Never edited or truncated.
2. `REQUIREMENT_COVERAGE.csv` — Full requirement and branch index. Zero dropped rows permitted.
3. `TASK_GRAPH.json` — Persistent hierarchical DAG (Program -> Campaign -> Epic -> Leaf Task).
4. `PROGRAM_STATE.md` — Authoritative operational control plane (active campaign, current leaf, blockers, next actions).
5. Operational Ledgers:
   - `EVIDENCE_LEDGER.md`
   - `RUNTIME_LEDGER.md`
   - `DECISION_LEDGER.md`
   - `BLOCKER_LEDGER.md`
   - `COMPLETION_LEDGER.md`

## Mechanical Status Derivation Rules
- **Parent status is strictly calculated from children**:
  - `COMPLETED`: only when 100% of child tasks are `COMPLETED` (or ledger-approved `ABANDONED`).
  - `IN_PROGRESS`: if any child task is `IN_PROGRESS` or partially done.
  - `BLOCKED`: if any critical path child task is `BLOCKED`.
  - `NOT_STARTED`: if all children are `NOT_STARTED`.
- **Manual override of parent status is forbidden**.
- No requirement in `REQUIREMENT_COVERAGE.csv` may transition to `VERIFIED_PASS` without a valid, existing `evidence_path`.

## State Checkpointing & Concurrency
- **Context pressure handling**: When approaching context limits, serialize and checkpoint partial state to `PROGRAM_STATE.md` and `TASK_GRAPH.json`. Never compress unfinished tasks into a premature "done" summary.
- **Single-writer serialization**: Subagents never modify state files directly. All state transitions must be serialized and committed through the Coordinator / Program State Controller.
- **Validation hook**: Run `validate_program_state.py` before and after state transitions.
