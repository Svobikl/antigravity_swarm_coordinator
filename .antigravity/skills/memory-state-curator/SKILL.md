# Memory & State Curator

## Purpose
Govern interactions with persistent memory systems, knowledge graphs (e.g. Graphify, Obsidian, MCP memory), and cross-session knowledge bases. Ensure memory serves as an effective advisory cache without corrupting the authoritative project control plane.

## Authoritative vs. Secondary Hierarchy
1. **Authoritative Primary Truth**:
   - Repository code, committed tests, execution outputs, and git state.
   - `TASK_GRAPH.json`, `REQUIREMENT_COVERAGE.csv`, `PROGRAM_STATE.md`, and project ledgers.
2. **Secondary Advisory Cache**:
   - Memory MCP nodes, Obsidian markdown vaults, vector stores, and knowledge graphs.

## Core Rules
- **Memory is never proof of completion**: A note or graph entry stating "Task X is done" has zero evidential value for task acceptance. Only executable test results, logs, and committed artifacts on disk constitute proof.
- **Conflict resolution**: If memory and repository state conflict, repository state and active task ledgers win unconditionally.
- **Durable synchronization**:
  - Record architectural decisions (`DECISION_LEDGER.md`), failed hypotheses, and major milestones into the memory system for future session discovery.
  - Store pointers to artifacts rather than duplicating volatile, evolving source code.
  - Prune obsolete or invalidated assumptions from memory when refuted by empirical tests.
