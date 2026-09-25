# Antigravity / Gemini Agent Framework Audit — Long-Horizon V4

## Scope

Audit based on the uploaded `generic_dev_agentic_combined` package and the user's described large installed skill catalog. The actual external ASW/Graphify/Obsidian skill/config contents were not present in the archive, so their internal implementation was not inspected; the V4 changes define how they should interact with the core framework.

## Root cause of large-plan failure

The prior package was strong for bounded software delivery but lacked a true long-horizon program controller. It had evidence-based testing and independent review, yet no machine-verifiable persistent task graph, no source-plan coverage map, no research experiment governance, no skill-budget/router, no memory source-of-truth protocol, and no independent program-completion audit.

This allows a long plan to fail in a characteristic way: individual agents complete local work, executive summaries compress or omit unfinished branches, and the final agent declares the whole plan complete from narrative reports rather than leaf-level evidence.

## High-priority findings

1. No long-horizon execution mode.
2. Mode 3 assumed a bounded design→implementation→QA→handoff lifecycle, not dozens of campaigns/experiments.
3. Requirement IDs existed, but there was no persistent hierarchical task graph.
4. Parent completion was not mechanically derived from child completion.
5. No immutable source-plan / requirement-coverage map, so large plans could silently shrink.
6. No dedicated research/ML protocol for OOS selection, trial accounting, runtime proof, or missing-data semantics.
7. No single-orchestrator rule despite many possible orchestration/planning skills.
8. No active-skill budget; thousands of installed skills can create routing/context entropy.
9. Subagents had no strict task contracts and no prohibition against global completion claims.
10. Memory/knowledge graph had no explicit secondary-vs-authoritative state policy.
11. Final acceptance was primarily narrative/software-test based.
12. Setup validator checked only workspace hygiene.
13. The package contained lowercase `gemini.md` while README referred to `GEMINI.md`; V4 provides both.

## V4 corrections

- Added Mode 5 Long-Horizon Program / Research.
- Added immutable source-plan preservation and `REQUIREMENT_COVERAGE.csv`.
- Added `TASK_GRAPH.json` + authoritative `PROGRAM_STATE.md`.
- Added evidence, runtime, decision, blocker and completion ledgers.
- Added single-orchestrator rule: `swarm-coordinator` owns global scope/state.
- Added default skill budget of 8 per leaf task.
- Added bounded subagent task contracts and default max 4 parallel independent agents.
- Added `skill-router`, `program-state-controller`, `research-experiment-auditor`, `memory-state-curator`, `completion-auditor`.
- Strengthened acceptance, opposition, validation, and swarm-coordinator skills.
- Added research rules: outer/OOS evaluation-only, fold-safe selection, runtime/checkpoint proof, missing/constant data != NO_VALUE.
- Added program-state validator that rejects false completion.
- Added hard rule: no `100% complete` without graph closure + independent completion audit.
- Added context-pressure rule: checkpoint partial state rather than converting unfinished work into a completion summary.
- Added concurrency rule: no parallel agents editing the same files/state; coordinator serializes shared state.

## Recommended usage with thousands of skills

Do not uninstall the large skill catalog. Treat it as a searchable library. For each leaf task select one primary domain skill plus only necessary implementation/validation/review skills. Do not preload whole categories. ASW orchestration-like skills are helper tools, not peer coordinators.

## Memory / Graphify / Obsidian

Use them for discovery, durable decisions, failed hypotheses, and artifact pointers. Never use a memory node as proof that a task is complete. On conflicts, current repository artifacts and program control-plane state win.

## Expected effect

The V4 design specifically targets the observed failure mode in the quant research work: branches such as Laya or sentiment can no longer disappear from a completion report if they remain unmapped/unverified, and a report cannot claim 100% completion unless the source-plan coverage and task graph both close with direct evidence.
