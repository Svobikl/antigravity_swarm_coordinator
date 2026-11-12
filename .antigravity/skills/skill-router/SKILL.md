---
name: skill-router
description: Selects a bounded active skill set (max 8 skills) from the catalog per leaf task.
---

# Skill Router

## Purpose
Analyze incoming task requirements, select an optimal, bounded active skill set (maximum 8 skills per leaf task) from the installed skill catalog, and assign the mandatory **Cognitive Model Tier across the Quad-Model Cross-Family Architecture (`Gemini 4 Carbon High` + `Claude Opus 5.5` + `Gemini 4 Argon High` + `Gemini 4 Hydrogen High`)** to each dispatched role. Prevent context pollution, skill collisions, and routing entropy.

## Core Operational Model
Treat the installed skill catalog (hundreds/thousands of skills) as a searchable on-disk reference library, NEVER as a monolithic preloaded bundle.

## Quad-Model Role Assignment Matrix
When routing skills to subagents (`invoke_subagent`), enforce this strict model pairing:

- **Tier 1A — `Gemini 4 Carbon (High)` (`Model="pro"`) — Primary Planner, Architect & Deep Researcher:**
  - `program-state-controller` (Mode 5 plan freeze & task graph decomposition)
  - `spec-product-analyst`, `software-architect`, `asw-planner`, `asw-planning-analysis`, `asw-librarian`
  - `asw-harness-adapt` (proposing invariant, domain, and composition harness mutations)

- **Tier 1B — `Claude Opus 5.5` (Native Antigravity Runtime) — Independent Cross-Family Opposition Reviewer, Plan Auditor & Selector:**
  - `opposition-reviewer` (`asw-opposition-reviewer`, `asw-reviewer`) — falsifying code diffs, boundary edge cases, and empirical claims
  - `asw-plan-audit` — pre-execution plan opposition audit gate
  - `asw-harness-adapt` — blind candidate selector (`channels["selector"]`), preventing proposer self-grading bias

- **Tier 1C — `Gemini 4 Argon (High)` (`Model="pro"`) — Reviewer, Auditor & Remaining Non-Routine Coordinator Tasks:**
  - `swarm-coordinator`, `skill-router`, `ui-ux-designer`
  - `systematic-debugging`, `asw-debug` (root-cause isolation & hypothesis falsification)
  - `acceptance-reviewer-product-qa`, `compliance-maintainability-reviewer`, `security-reliability-reviewer`, `research-experiment-auditor`, `completion-auditor`, `semantic-completion-auditor`, `research-validity-auditor`

- **Tier 2 — `Gemini 4 Hydrogen (High)` (`Model="flash"`) — High-Velocity Implementation & Routine Execution:**
  - `implementation-developer`, `asw-loop`, `asw-start-work`, `asw-programming`
  - `validator-build-test-agent`, `interaction-e2e-tester`
  - `asw-explorer`, `asw-cleanup`, `memory-state-curator`, `documentation-handoff-agent`
  - `asw-harness-adapt` (bounded probe rollouts, test verification, and Obsidian experience synchronization)

## Active Skill Budget Rules
For any single task or subagent invocation, strictly enforce:
- **Maximum 8 active skills** in context simultaneously.
- **Composition pattern**:
  1. **Primary Domain Specialist** (1 skill: e.g., `python-pro`, `scikit-learn`, `database`, `api-patterns`).
  2. **Orchestration Authority** (1 skill: `swarm-coordinator` or `skill-router` — **Argon High**, or `asw-planner` — **Carbon High**).
  3. **Implementation** (1 skill: `implementation-developer` — **4 Hydrogen High**).
  4. **Validation** (1 skill: `validator-build-test-agent` or `interaction-e2e-tester` — **4 Hydrogen High**).
  5. **Independent Opposition / Review** (1–2 skills: `opposition-reviewer` [**Claude Opus 5.5**], `compliance-maintainability-reviewer` [**Argon High**], or `research-experiment-auditor` [**Argon High**]).
  6. **Adaptation / Utility** (0–2 skills: e.g., `asw-harness-adapt`, `performance-profiling`, `systematic-debugging`).

## Routing Responsibilities
- Classify task technical domain and cognitive tier before proposing skill activation.
- Ensure primary proposers (`Gemini 4 Carbon High`) are paired with cross-family adversarial opposition reviewers (`Claude Opus 5.5`).
- Reject requests to preload broad multi-skill bundles or unused toolsets.
- Under context pressure, prune completed or inactive skills immediately.
