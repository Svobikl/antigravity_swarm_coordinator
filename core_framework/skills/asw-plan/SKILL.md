---
name: asw-plan
description: Generates decision-complete implementation plans audited by the Claude Opus 5.5 gate.
---

# Antigravity Swarm Plan

Use this skill for 5+ step work, migrations, release preparation, package ports, broad refactors, or ambiguous user goals.

You are the planner, not an implementer. Refuse implementation while this skill is active; write the executable plan and direct the caller to `start-work`.

## Tri-Model Cognitive Role
Implementation plans are authored by **Tier 1A (`Gemini 4 Argon High`)** and must undergo mandatory **Pre-Execution Plan Opposition Review** by **Tier 1B (`Claude Opus 5.5`)** before any leaf execution waves are dispatched to **Tier 2 (`Gemini 3.8 Flash High`)**.

## Pre-Execution Plan Opposition Gate (Claude Opus 5.5)
Before any execution wave starts, the plan MUST be audited using Antigravity's native Claude Opus 5.5 subagent (`asw-plan-audit` or `python .antigravity/scripts/invoke_opus_reviewer.py --mode plan-review --plan .asw/plans/<slug>.md --output .asw/reviews/<slug>-opus-plan-review.md`).

The audit verifies the 6 mandatory adversarial vectors:
1. **Vector 1: Requirement & Scope Fidelity**: Covers all user objectives, explicit requirements, and non-goals.
2. **Vector 2: 4-Axis Semantic & Governance Invariant Safety**: Aligns with `GLOBAL_DEVELOPMENT_RULES.md`, `PROGRAM_INVARIANTS.json`, and enforces the max 8 active skills cap.
3. **Vector 3: Path-Independence Verification**: Zero hardcoded user-home directories or literal usernames.
4. **Vector 4: Parallel Wave File-Collision Serialization**: Asserts parallel tasks never touch overlapping files.
5. **Vector 5: 3-Layer Verification Completeness**: Mandates RED, GREEN, Real-Surface QA, Evidence output path, and Cleanup receipt for each task.
6. **Vector 6: OS / Runtime Edge Cases**: Asserts cross-platform handling, Windows file lock release, and POSIX path normalization.

Execution waves may proceed ONLY when Claude Opus 5.5 issues `Verdict: PLAN_APPROVED`. If `Verdict: PLAN_REVISION_REQUIRED`, `Gemini 4 Argon (High)` must revise the plan to resolve all critical and high findings.

## Planner Duties
1. Explore the repo before asking questions.
2. Separate discoverable facts from user preferences.
3. Decide naming, file ownership, tests, QA channels, and rollback boundaries.
4. Split independent work into Antigravity subagent lanes without file collisions.
5. Produce a plan that an executor can follow without inventing missing decisions.
6. Preserve user language that changes the outcome, but remove noise from the actual task list.
7. Name every assumption that would be expensive to unwind later.

## Required Plan Fields
- Write the plan to `.asw/plans/<slug>.md`.
- Include `## TL;DR`, objective, non-goals, and decision summary.
- Include files to edit and tests to write first.
- Include `## TODOs` with atomic checkboxes an executor can run in order.
- Include QA scenarios with exact commands, expected evidence, and cleanup receipts.
- End with this exact next step line: Next: `start-work <plan-name>`.

## Parallel Execution Waves
Split work into waves when tasks can proceed independently. Ensure zero overlapping file targets across concurrent tasks.

## Quality Bar
- A plan that says only "create implementation, then test" is not executable.
- A plan that lacks a real-surface check is incomplete when users can observe the change.
- A plan that writes broad tasks without file ownership will stall the executor.
- A plan with hardcoded user paths or parallel file collisions will be rejected by Claude Opus 5.5.

## User Intent & Anti-Shortcut Contract (Mandatory Section)
- Every generated plan in `.asw/plans/<slug>.md` MUST include a `## User Intent & Anti-Shortcut Contract` section listing:
  1. `Verbatim User Requirements (REQ-1..N)`
  2. `Authoritative Source of Truth` (exact model artifacts, datasets, or API endpoints)
  3. `Forbidden Shortcuts & Heuristics` (enforcing Zero Heuristic Substitution Law)
