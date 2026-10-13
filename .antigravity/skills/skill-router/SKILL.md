# Skill Router

## Purpose
Analyze incoming task requirements, select an optimal, bounded active skill set (maximum 8 skills per leaf task) from the installed skill catalog, and assign the mandatory **Cognitive Model Tier (`Gemini 4 Argon High` vs. `Gemini 3.8 Flash High`)** to each dispatched role. Prevent context pollution, skill collisions, and routing entropy.

## Core Operational Model
Treat the installed skill catalog (hundreds/thousands of skills) as a searchable on-disk reference library, NEVER as a monolithic preloaded bundle.

## Dual-Model Role Assignment Matrix
When routing skills to subagents (`invoke_subagent`), enforce this strict model pairing:
- **`Gemini 4 Argon (High)` (`Model="pro"`) — Research, Analysis, Architecture, Planning & Independent Audit:**
  - `swarm-coordinator`, `skill-router`, `program-state-controller`
  - `spec-product-analyst`, `software-architect`, `ui-ux-designer`, `asw-planner`, `asw-planning-analysis`, `asw-plan-audit`, `asw-librarian`
  - `systematic-debugging`, `asw-debug` (root-cause isolation & hypothesis falsification)
  - `opposition-reviewer`, `acceptance-reviewer-product-qa`, `compliance-maintainability-reviewer`, `security-reliability-reviewer`, `research-experiment-auditor`, `completion-auditor`, `semantic-completion-auditor`, `research-validity-auditor`, `asw-reviewer`
- **`Gemini 3.8 Flash (High)` (`Model="flash"`) — High-Velocity Implementation, Testing & Scouting:**
  - `implementation-developer`, `asw-loop`, `asw-start-work`, `asw-programming`
  - `validator-build-test-agent`, `interaction-e2e-tester`
  - `asw-explorer`, `asw-cleanup`, `memory-state-curator`, `documentation-handoff-agent`

## Active Skill Budget Rules
For any single task or subagent invocation, strictly enforce:
- **Maximum 8 active skills** in context simultaneously.
- **Composition pattern**:
  1. **Primary Domain Specialist** (1 skill: e.g., `python-pro`, `scikit-learn`, `database`, `api-patterns`).
  2. **Orchestration Authority** (1 skill: `swarm-coordinator` or `skill-router` — **Argon High**).
  3. **Implementation** (1 skill: `implementation-developer` — **3.8 Flash High**).
  4. **Validation** (1 skill: `validator-build-test-agent` or `interaction-e2e-tester` — **3.8 Flash High**).
  5. **Independent Review** (1–2 skills: `compliance-maintainability-reviewer`, `opposition-reviewer`, `acceptance-reviewer-product-qa`, or `research-experiment-auditor` — **Argon High**).
  6. **Task-Specific Utility** (0–2 skills: e.g., `performance-profiling`, `systematic-debugging`).

## Routing Responsibilities
- Classify task technical domain and cognitive tier (`Argon High` for planning/analysis/audit vs. `3.8 Flash High` for coding/testing) before proposing skill activation.
- Reject requests to preload broad multi-skill bundles or unused toolsets.
- Detect conflicting orchestration skills (e.g. ASW, Conductor, CrewAI helper skills) and ensure they operate strictly as task-scoped tools subordinated to `swarm-coordinator`.
- Under context pressure, prune completed or inactive skills immediately.

