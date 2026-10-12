# Skill Router

## Purpose
Analyze incoming task requirements and select an optimal, bounded active skill set (maximum 8 skills per leaf task) from the installed skill catalog. Prevent context pollution, skill collisions, and routing entropy.

## Core Operational Model
Treat the installed skill catalog (hundreds/thousands of skills) as a searchable on-disk reference library, NEVER as a monolithic preloaded bundle.

## Active Skill Budget Rules
For any single task or subagent invocation, strictly enforce:
- **Maximum 8 active skills** in context simultaneously.
- **Composition pattern**:
  1. **Primary Domain Specialist** (1 skill: e.g., `python-pro`, `scikit-learn`, `database`, `api-patterns`).
  2. **Orchestration Authority** (1 skill: `swarm-coordinator` or `skill-router`).
  3. **Implementation** (1 skill: `implementation-developer`).
  4. **Validation** (1 skill: `validator-build-test-agent`).
  5. **Independent Review** (1–2 skills: `compliance-maintainability-reviewer`, `opposition-reviewer`, `acceptance-reviewer-product-qa`, or `research-experiment-auditor`).
  6. **Task-Specific Utility** (0–2 skills: e.g., `performance-profiling`, `systematic-debugging`).

## Routing Responsibilities
- Classify task technical domain before proposing skill activation.
- Reject requests to preload broad multi-skill bundles or unused toolsets.
- Detect conflicting orchestration skills (e.g. ASW, Conductor, CrewAI helper skills) and ensure they operate strictly as task-scoped tools subordinated to `swarm-coordinator`.
- Under context pressure, prune completed or inactive skills immediately.
