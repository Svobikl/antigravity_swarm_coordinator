# BMAD-METHOD V7 + Antigravity Swarm Plan Template (`<frozen-after-approval>`)

Use this canonical template when creating `.asw/plans/<slug>.md`.

## Structural Rules
1. **Single-Goal Scope & Token Ceiling (`900–1600` tokens):** Each plan targets one single coherent goal. If the user's request spans multiple independent goals, split secondary goals into `.asw/plans/deferred-work.md`.
2. **Human-Owned `<frozen-after-approval>` Contract:** Everything inside `<!-- <frozen-after-approval> --> ... <!-- </frozen-after-approval> -->` (`Intent`, `Boundaries & Constraints`, and `I/O & Edge-Case Matrix`) is frozen once the plan reaches `status: ready-for-dev` or `in-progress`. Agents must NEVER edit `<frozen-after-approval>` during implementation or review without setting `human_reapproved: true` after explicit human sign-off.
3. **`baseline_revision` Git SHA:** Record the Git HEAD commit SHA (`git rev-parse --short HEAD`) in frontmatter before the first code edit in `step-03-implement`.
4. **Context-Free `## Code Map`:** List the exact files, classes/functions, and caller-to-callee relationships so `Gemini 3.8 Flash (High)` implementation subagents can execute with zero prior conversation context and zero blind repository searching.

---

```markdown
---
title: "<Concise Single-Goal Title>"
status: ready-for-dev
baseline_revision: "<git-short-sha>"
slug: "<plan_slug>"
---

# <Concise Single-Goal Title>

## TL;DR
<2-4 sentences summarizing the problem, solution, and verification approach.>

## Objective
<Clear statement of what will be delivered.>

## Non-Goals
- <Explicitly out-of-scope items deferred to `.asw/plans/deferred-work.md`.>

## Governance & Invariants
- **Mode:** Mode 2 / Mode 3 / Mode 5 (`GLOBAL_DEVELOPMENT_RULES.md`)
- **Tri-Model Routing:** `Gemini 4 Argon (High)` (Architect/Planner) -> `Claude Opus 5.5` (Opposition Gate) -> `Gemini 3.8 Flash (High)` (Implementation/TDD)

<!-- <frozen-after-approval> — Human-owned contract; do not modify after approval -->

## User Intent & Anti-Shortcut Contract

### Intent
<Verbatim user intent and authoritative source of truth.>

### Boundaries & Constraints
- **Always:**
  - <Mandatory invariants, e.g., Zero Heuristic Substitution, 3-Layer Verification>
- **Never:**
  - <Forbidden shortcuts, e.g., never rewrite I/O & Edge-Case Matrix rows to fit broken code>

### I/O & Edge-Case Matrix

| Scenario / Condition | Input / Trigger | Expected Output / Behavior | Boundary / Error Case |
| :--- | :--- | :--- | :--- |
| **M1: <Happy Path>** | `<concrete input>` | `<exact expected output>` | `<boundary/error behavior>` |
| **M2: <Edge/Negative Case>** | `<invalid/extreme input>` | `<expected rejection/error>` | `<zero side effects>` |

<!-- </frozen-after-approval> -->

## Code Map
- `path/to/module.py`: `<functions/classes to modify and their callers/consumers>`
- `tests/test_module.py`: `<unit, negative, and parity test functions covering M1..Mn>`

## Execution Tasks (Serialized Wave Order — Zero File Overlap)

- [ ] **Task 1 (Wave 1 — Serialized): <Task Title>**
  - **Model Tier:** `Gemini 3.8 Flash (High)` (`Model="flash"`)
  - **Target Files:** `path/to/module.py`, `tests/test_module.py`
  - **Action:** <Exact decision-complete implementation instructions.>
  - **RED / GREEN / QA / CLEANUP:**
    - **RED:** `<failing test command before fix>`
    - **GREEN:** `<passing test command covering M1..Mn>`
    - **QA:** `<real-surface CLI/API/GUI execution command>`
    - **CLEANUP:** `<resource/scratch cleanup command>`

## Verification & Stop Criteria (RED -> GREEN -> QA -> CLEANUP)
1. **Layer 1 (Static / Syntax / Build):** `<command>`
2. **Layer 2 (Automated Matrix & Negative Tests):** `<command>`
3. **Layer 3 (Real-Surface Behavioral Proof & Opposition Gate):** `<command>`

## Implementation Notes
*(Populated during `step-03-implement`)*

## Plan Change Log
- `<YYYY-MM-DD>`: Initial plan created and audited.

## Review Triage Log
*(Populated during `step-04-review`)*

Next: start-work <plan_slug>
```
