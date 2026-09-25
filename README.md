# Antigravity Swarm Coordinator (Long-Horizon V4.1)

Complete backup, distribution, and setup package for the default **Swarm Coordinator** and multi-agent governance framework for **Google Antigravity** and **Gemini CLI**.

This repository contains the complete coordinator architecture, including the global configuration entry point prompt, governance rules, validation scripts, a suite of 21 specialized skills, the ASW engine plugin (`antigravity-swarm`), and standardized control-plane templates for managing complex engineering and quantitative research programs.

---

## 🏗️ Architecture & Operating Principles

In Antigravity, the swarm coordinator functions under the **Single Orchestrator Rule**, acting as the sole authority for global scope, program state transitions, task breakdown, agent lifecycles, and dual-axis completion verification.

```
                    ┌────────────────────────────────────────┐
                    │       ~/.gemini/GEMINI.md              │
                    │   (Global Entry Point & Governance)    │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │           swarm-coordinator            │
                    │      (Sole Global Orchestration Lead)  │
                    └───────┬────────────────────────┬───────┘
                            │                        │
            ┌───────────────┴────────┐       ┌───────┴───────────────┐
            │   Multi-Agent Roles    │       │   ASW Engine Plugin   │
            │   (Max 8 skills budget)│       │  (antigravity-swarm)  │
            ├────────────────────────┤       ├───────────────────────┤
            │ spec-product-analyst   │       │ asw-planner           │
            │ software-architect     │       │ asw-loop              │
            │ implementation-dev     │       │ asw-reviewer          │
            │ interaction-e2e-tester │       │ asw-plan-auditor      │
            │ validator-build-test   │       │ asw-librarian         │
            │ opposition-reviewer    │       │ asw-explorer          │
            └───────────────┬────────┘       └───────┬───────────────┘
                            │                        │
                            └───────────┬────────────┘
                                        │
                                        ▼
             ┌─────────────────────────────────────────────────────┐
             │       Multi-Auditor Completion & Verification       │
             ├──────────────────────────┬──────────────────────────┤
             │   completion-auditor     │ semantic-completion-     │
             │ (Mechanical task graph   │         auditor          │
             │  closure & artifact QA)  │ (Semantic integrity,     │
             │                          │  invariants & hypotheses)│
             └──────────────────────────┴──────────────────────────┘
```

### Core Rules
1. **Single Orchestrator:** `swarm-coordinator` is the SOLE authority for global scope and state. Helper orchestration tools (ASW, Conductor) act strictly as localized sub-workflows under coordinator control.
2. **Active Skill Budget:** Enforces a strict budget of **maximum 8 active skills** loaded in context per leaf task, preventing context-window degradation.
3. **Bounded Subagents:** Maximum **4 parallel independent subagents** active concurrently. Subagents receive strict task contracts and are strictly forbidden from declaring global completion or editing global control-plane state.
4. **State Serialization:** Parallel subagents must never edit overlapping files or state. The coordinator serializes all shared state updates.
5. **Dual Control Plane (V4.1 Semantic Integrity):**
   - **Mechanical Completion:** Were all tasks executed and all required evidence artifacts generated on disk?
   - **Semantic Integrity:** Did the program solve the original problem under the specified rules without post-hoc threshold relaxation, metric tampering, or goalpost moving?

---

## ⚡ Execution Modes (Modes 0 to 5)

| Mode | Name | Purpose & Governance |
| :--- | :--- | :--- |
| **Mode 0** | Operational Fast Path | Direct build, test, run, and lint operations. Coordinator + Validator only; zero design bureaucracy. |
| **Mode 1** | Investigation Only | Analysis, bug reproduction, and diagnostics without source code mutation. No state changes. |
| **Mode 2** | Small Controlled Change | Focused modifications with concise change records, existing-reference audits, and targeted tests. |
| **Mode 3** | Complex Delivery | Complex features: specification & design ➔ explicit user approval ➔ autonomous execution ➔ QA ➔ handoff. |
| **Mode 4** | Emergency Restore | Minimal restoration of working state only; no opportunistic refactoring or feature additions. |
| **Mode 5** | Long-Horizon Program / Research | Multi-campaign programs: immutable `SOURCE_PLAN.md` freeze, `REQUIREMENT_COVERAGE.csv`, `TASK_GRAPH.json`, multi-auditor independent sign-off. |

---

## 📁 Repository Structure

```
antigravity_swarm_coordinator/
├── README.md                          # This documentation
├── install.ps1                        # Automated PowerShell installation and restore script
├── .gitignore                         # Git ignore rules for caches and temporary artifacts
│
├── global_entrypoint/
│   └── GEMINI.md                      # Global instructions deployed to ~/.gemini/GEMINI.md
│
├── core_framework/                    # Long-Horizon V4.1 Governance Framework
│   ├── rules/
│   │   └── GLOBAL_DEVELOPMENT_RULES.md # Comprehensive multi-agent rules & operating principles
│   ├── docs/
│   │   ├── V4_1_OPERATOR_GUIDE.md     # Operator guide for semantic integrity and 4-axis completion
│   │   ├── ANTIGRAVITY_LONG_HORIZON_AUDIT_V4.md # Architecture audit and theoretical foundation
│   │   └── RECOMMENDED_SKILLS.md      # Curated companion skills guide and budget rules
│   ├── scripts/                       # Python state validation and audit execution scripts
│   │   ├── validate_program_state.py  # Strict mechanical program state & task graph validator
│   │   ├── validate_agent_setup.py    # Runtime environment setup verification
│   │   ├── run_semantic_audit.py      # Semantic integrity audit runner
│   │   ├── run_invariant_audit.py     # Invariant preservation auditor
│   │   ├── run_report_consistency_audit.py # Cross-report contradiction detection runner
│   │   └── migrate_v4_to_v4_1.py      # Migration script from V4 to V4.1
│   ├── semantic/                      # Python semantic integrity engine (auditor, claims, memory, etc.)
│   ├── skills/                        # All 21 specialized agent and auditor skills
│   └── templates/                     # Project control-plane templates (Modes 2, 3, and 5)
│
├── plugins/
│   └── antigravity-swarm/             # Antigravity Swarm (ASW) Engine Plugin
│       ├── plugin.json                # Plugin manifest (v0.2.4)
│       ├── agents/                    # ASW subagents (asw-planner, asw-reviewer, etc.)
│       ├── hooks/                     # ASW task lifecycle hooks
│       ├── scripts/                   # ESM/Node.js diagnostic and status scripts
│       └── skills/                    # ASW utility skills (asw-plan, asw-loop, asw-goal, ...)
│
└── .antigravity/                      # Drop-in framework directory ready for any target repository
```

---

## 🛠️ Specialized Roles & Skills Catalog

This repository includes all **21 specialized skills** directly powering the coordinator and auditors:

1. **`swarm-coordinator`**: Global orchestration lead and state machine authority.
2. **`skill-router`**: Catalog routing and strict active skill budget enforcement (max 8).
3. **`program-state-controller`**: State machine, ledger, and task graph manager.
4. **`spec-product-analyst`**: Requirements, acceptance criteria, and non-goals specification.
5. **`software-architect`**: Technical architecture, component boundaries, and API design.
6. **`ui-ux-designer`**: Interface workflows, design systems, and state-space specifications.
7. **`implementation-developer`**: Bounded diff implementation under strict task contracts.
8. **`interaction-e2e-tester`**: Interaction and end-to-end verification.
9. **`validator-build-test-agent`**: Repository-native command discovery and state validation.
10. **`compliance-maintainability-reviewer`**: Coding conventions, code quality, and blast radius auditing.
11. **`opposition-reviewer`**: Adversarial hypothesis falsification and leakage detection.
12. **`acceptance-reviewer-product-qa`**: Empirical product requirements verification with direct evidence.
13. **`security-reliability-reviewer`**: Trust boundaries, threat modeling, and security audits.
14. **`research-experiment-auditor`**: Quant/ML governance, out-of-sample discipline, and fold safety.
15. **`memory-state-curator`**: Secondary advisory memory synchronization (Obsidian, Graphify).
16. **`completion-auditor`**: Independent mechanical closure and 100% completion verification.
17. **`documentation-handoff-agent`**: Documentation impact and final handoff audit.
18. **`invariant-auditor`**: Verification of non-negotiable program contracts.
19. **`report-consistency-auditor`**: Cross-report claim reconciliation and arithmetic verification.
20. **`research-validity-auditor`**: Scientific validity, causal data contracts, and ablation checks.
21. **`semantic-completion-auditor`**: Independent semantic sign-off preventing goalpost drift.

---

## 🧩 Recommended Companion Skills (Curated Catalog)

The Swarm Coordinator operates with a searchable library of installed skills, dynamically activating up to **8 active skills** per leaf task. Based on what is proven and installed in this Antigravity environment, the following companion skills are strongly recommended:

### 1. Antigravity Swarm (ASW) Execution Suite
*Included in this repository under `plugins/antigravity-swarm` and registered in Antigravity.*
- **`asw`**: Main Antigravity Swarm execution loop with automated tests, subagents, and manual QA receipts.
- **`asw-plan`**: Pre-implementation decision-complete planning before large or ambiguous work.
- **`asw-loop`**: Autonomous RED ➔ GREEN ➔ real-surface QA loop.
- **`asw-goal`**: Converts ambiguous briefs into concrete, measurable evidence criteria.
- **`asw-review`**: Post-change behavioral diff audit to prevent regressions.
- **`asw-debug`**: Hypothesis-driven debugging for crashes, hangs, and runtime drift.
- **`asw-remove-ai-slops`**: Cleans AI clutter, unnecessary comments, and dead abstractions.
- **`asw-lsp`**: Symbol safety and compiler diagnostics checking.

### 2. Task Planning & Disk-State Persistence
- **`planning-with-files`**: Uses persistent Markdown files as working memory on disk (matches Manus-style durability).
- **`subagent-driven-development`**: Coordinates bounded, parallel subagent dispatching.
- **`executing-plans`**: Step-by-step plan execution with strict review gates.
- **`writing-plans`**: Creates actionable, atomic implementation checklists.

### 3. Test-Driven Development (TDD) & Evidence Gates
- **`test-driven-development`** / **`tdd-workflow`**: Enforces writing failing tests prior to production code.
- **`verification-before-completion`**: Guarantees tasks are not marked complete without verified disk proof.
- **`lint-and-validate`**: Mandatory post-change validation execution.

### 4. Diagnostics & Code Auditing
- **`systematic-debugging`**: 4-phase root-cause diagnosis before proposing fixes.
- **`debugger`**: Dedicated diagnostic assistant for unexpected test failures and crashes.
- **`vibe-code-auditor`**: Audits rapidly generated AI code for structural flaws, mocks, and fragility.
- **`simplify-code`**: Safe, low-risk code simplification and minimal blast-radius enforcement.
- **`code-reviewer`**: Comprehensive code review checking idiomatic design and security risks.

### 5. Architecture & Security Governance
- **`architect-review`** / **`senior-architect`**: Component boundary and architectural decision evaluation.
- **`security-auditor`**: DevSecOps, privilege boundaries, and dependency vulnerability scanning.
- **`database-design`**: Relational/NoSQL schema modeling and migration safety.

### 6. Shell & Environment Reliability (Windows / Cross-Platform)
- **`windows-shell-reliability`**: Escaping, paths, CRLF, and execution pitfalls for Windows PowerShell/CMD.
- **`powershell-windows`**: Error handling and native syntax for robust automation.
- **`posix-shell-pro`**: Defensive shell scripting for Linux/macOS environments.

### 7. Quantitative Research & Data Science (Mode 5)
- **`quant-analyst`**: Financial metrics, risk evaluation, and backtesting sanity auditing.
- **`scikit-learn`**: Out-of-sample data splitting, pipeline hygiene, and model validation.

> 📖 **Full Details:** See [`core_framework/docs/RECOMMENDED_SKILLS.md`](core_framework/docs/RECOMMENDED_SKILLS.md) for how the `skill-router` manages dynamic activation under the 8-skill budget.

---

## 🚀 Installation & Restoration

### Automatic Installation (Recommended)

Run the included PowerShell script from a PowerShell prompt:

```powershell
# 1. Restore global Antigravity environment (GEMINI.md, skills, plugin)
.\install.ps1

# 2. Or restore globally and deploy .antigravity into a specific project repository:
.\install.ps1 -TargetRepoPath "C:\Path\To\YourProject"
```

The script will:
1. Back up any existing `~/.gemini/GEMINI.md` to `GEMINI.md.bak` and deploy the coordinator prompt.
2. Install all 21 skills to `~/.gemini/config/skills/`.
3. Deploy the ASW plugin to `~/.gemini/config/plugins/antigravity-swarm/`.
4. (Optional) Copy `.antigravity/` directly into your target repository root.

---

## 📄 License

This distribution contains open-source components under the MIT License and coordinator configurations intended for managing Google Antigravity and Gemini CLI environments.
