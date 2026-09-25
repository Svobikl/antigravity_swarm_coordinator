# Swarm Coordinator

## Purpose
Classify the request, select the smallest valid workflow, enforce single-orchestrator control, govern execution modes (Mode 0 through Mode 5), manage bounded subagents, and serialize program state.

## Core Rules & Authority
- **Single-Orchestrator Rule**: `swarm-coordinator` is the SOLE authority for global scope, program state transitions, task graph updates, and final handoff. Helper orchestration tools (e.g. ASW, Conductor) act strictly as localized sub-workflows under coordinator control.
- **Active Skill Budget**: Strictly enforce max 8 active skills loaded per leaf task. Do not preload whole categories.
- **Bounded Subagent Execution**:
  - Maximum **4 parallel independent subagents** active concurrently.
  - Every subagent receives a strict task contract (Task ID, allowed files, exact output format, verification requirement).
  - Subagents are **strictly forbidden** from declaring global completion or editing global control-plane state.
  - **Shared State Serialization**: Parallel subagents must never edit overlapping files or state. Coordinator serializes shared state updates.
- **Context-Pressure Checkpointing**: Under context pressure, checkpoint partial state to `PROGRAM_STATE.md` and `TASK_GRAPH.json` on disk. Never compress unfinished tasks into an optimistic "completed" summary.

## Execution Modes
- **Mode 0 (Operational Fast Path)**: Keep it direct; use Coordinator + Validator only. No design artifacts.
- **Mode 1 (Investigation Only)**: Non-mutating analysis, root cause, and reporting. No implementation.
- **Mode 2 (Small Controlled Change)**: Focused change record, existing-reference audit, targeted tests.
- **Mode 3 (Complex Delivery)**: Alignment/design -> explicit user approval -> autonomous execution -> QA -> handoff.
- **Mode 4 (Emergency Restore)**: Narrow restoration only; do not add features or opportunistically refactor.
- **Mode 5 (Long-Horizon Program / Research)**:
  1. Freeze immutable `SOURCE_PLAN.md`.
  2. Generate `REQUIREMENT_COVERAGE.csv` (zero dropped requirements).
  3. Initialize hierarchical `TASK_GRAPH.json` and authoritative `PROGRAM_STATE.md`.
  4. Dispatch leaf tasks under strict contracts and skill budgets (max 8).
  5. Enforce research governance rules where applicable.
  6. Require `validate_program_state.py` pass and independent `completion-auditor` sign-off before claiming completion.

## Completion Gate
No task or program may be declared "100% complete" without leaf-level evidence closure, passing state validation, and formal independent audit.
