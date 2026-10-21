# Antigravity Swarm Coordinator (Long-Horizon V4.1 + Harness² + Claude Opus 5.5)

Complete backup, distribution, and setup package for the default **Swarm Coordinator**, **Google Research `Harness²` recursive adaptation engine**, and **Tri-Model Cross-Family Governance Framework** (`Gemini 4 Argon High` + `Claude Opus 5.5` + `Gemini 3.8 Flash High`) for **Google Antigravity** and **Gemini CLI**.

This repository contains the complete coordinator architecture—100% **path-independent** across users and machines—including the global configuration entry point prompt, immutable governance rules, the `Harness²` self-improving harness engine, native `Claude Opus 5.5` adversarial plan & diff review gates, validation scripts, 22 specialized skills, the ASW engine plugin (`antigravity-swarm`), and 29 automated verification tests.

---

## 🏗️ Architecture & Operating Principles

In Antigravity, the Swarm Coordinator functions under the **Single Orchestrator Rule**, acting as the sole authority for global scope, program state transitions, task breakdown, agent lifecycles, recursive harness adaptation, and multi-auditor completion verification.

```text
                    ┌────────────────────────────────────────────────────────┐
                    │                  ~/.gemini/GEMINI.md                   │
                    │     (Global Entry Point & Path-Independent Rules)      │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │                   swarm-coordinator                    │
                    │   (Sole Global Orchestration Lead — Gemini 4 Argon)    │
                    └───────┬───────────────────┼────────────────────┬───────┘
                            │                   │                    │
       ┌────────────────────┴───┐   ┌───────────┴───────────┐   ┌────┴───────────────────────┐
       │  Tier 1B: Opposition   │   │  Tier 2: Execution    │   │   Harness² Adaptation      │
       │   (Claude Opus 5.5)    │   │  (Gemini 3.8 Flash)   │   │  (Propose–Probe–Compose)   │
       ├────────────────────────┤   ├───────────────────────┤   ├────────────────────────────┤
       │ • asw-plan-audit       │   │ • implementation-dev  │   │ • INV Proposer (Argon)     │
       │   (6-Vector Plan Gate) │   │ • asw-loop / TDD      │   │ • DOM Proposer (Argon)     │
       │ • asw-opposition-rev   │   │ • validator-build-test│   │ • Git Worktree Probes      │
       │   (4-Vector Diff Gate) │   │ • interaction-e2e     │   │ • Blind Selector (Opus 5.5)│
       │ • Blind Selector       │   │ • asw-explorer        │   │ • Obsidian Experience Sync │
       └────────────┬───────────┘   └───────────┬───────────┘   └────────────┬───────────────┘
                    │                           │                            │
                    └───────────────────────────┼────────────────────────────┘
                                                │
                                                ▼
             ┌──────────────────────────────────────────────────────────────────┐
             │            Multi-Auditor Completion & Verification               │
             ├────────────────────────────────┬─────────────────────────────────┤
             │       completion-auditor       │   semantic-completion-auditor   │
             │  (Mechanical task-graph/plan   │  (4-Axis semantic integrity,    │
             │   closure & 3-layer QA proof)  │   invariants & zero leakage)    │
             └────────────────────────────────┴─────────────────────────────────┘
```

### Core Rules
1. **Single Orchestrator:** `swarm-coordinator` is the SOLE authority for global scope and state. Helper orchestration tools (ASW, Conductor) act strictly as localized sub-workflows under coordinator control.
2. **Tri-Model Cross-Family Cognitive Routing (`Gemini 4 Argon High` + `Claude Opus 5.5` + `Gemini 3.8 Flash High`):**
   - **Tier 1A — Primary Architect, Planner, Synthesizer & Harness² Proposer (`Gemini 4 Argon (High)` / `Model="pro"`):** Mandatory for research, root-cause isolation, architecture design, implementation planning (`.asw/plans/<slug>.md`, `SOURCE_PLAN.md`, `TASK_GRAPH.json`), `INV`/`DOM`/`COMPOSE` harness proposals, and final mechanical completion auditing (`completion-auditor`).
   - **Tier 1B — Independent Cross-Family Opposition Reviewer, Plan Auditor & Blind Selector (`Claude Opus 5.5` natively in Antigravity / `model = "claude-opus-5-5"`):** Eliminates single-model blind spots and self-preference bias across two mandatory gates:
     - **Pre-Execution Plan Opposition Gate (`asw-plan-audit.toml` / `invoke_opus_reviewer.py --mode plan-review`):** Every implementation plan drafted by `Gemini 4 Argon (High)` is audited by `Claude Opus 5.5` across 6 adversarial vectors before execution waves are dispatched to `Gemini 3.8 Flash (High)`.
     - **Execution & Diff Opposition Gate (`asw-opposition-reviewer.toml` / `invoke_opus_reviewer.py --mode diff-review`):** Falsifies code diffs, boundary cases, and negative test proofs before task closure, and acts as `channels["selector"]` in Harness² adaptation sweeps so `Gemini 4 Argon` never grades its own proposals.
   - **Tier 2 — High-Velocity Bounded Executor (`Gemini 3.8 Flash (High)` / `Model="flash"`):** Mandatory for leaf code implementation, TDD RED-to-GREEN cycles, test suite execution, and isolated git-worktree candidate rollouts (`implementation-developer`, `asw-loop`, `validator-build-test-agent`, `interaction-e2e-tester`, `asw-explorer`).
3. **3-Layer Functional Verification Gate:** Syntax checks or mocked unit tests alone never prove completion. Every behavior-changing task requires: (1) Static/Build/Type integrity, (2) Automated happy-path + negative/edge-case tests, and (3) **Real-Surface End-to-End Runtime Proof** (invoking the actual CLI, API, UI, or data pipeline entrypoint with observable output).
4. **Zero-Unchecked-Plan Closure Gate:** Multi-step tasks (Modes 2, 3, and 5) maintain an on-disk checklist (`.asw/plans/<slug>.md` or `TASK_GRAPH.json`) enforced by `asw-stop-check.mjs` and `completion-auditor`. Stopping while any `- [ ]` checkbox remains open is strictly prohibited.
5. **Active Skill Budget:** Enforces a strict budget of **maximum 8 active skills** loaded in context per leaf task, preventing context-window bloat.
6. **Bounded Subagents & Concurrency Serialization:** Maximum **4 parallel independent subagents** active concurrently. Subagents receive strict task contracts and never edit overlapping files or global control-plane state.
7. **100% Path-Independence Invariant:** Zero hardcoded user directory paths or literal usernames anywhere in the coordinator, skills, plugins, or scripts. All paths resolve dynamically at runtime via `Path.home()`, `$OBSIDIAN_VAULT_PATH`, `%LOCALAPPDATA%`, or workspace-relative paths, enforced mechanically by `tests/test_path_independence.py`.
8. **Dual Control Plane (V4.1 Semantic Integrity):**
   - **Mechanical Completion:** Were all tasks executed and all required 3-layer evidence artifacts generated on disk?
   - **Semantic Integrity:** Did the program solve the original problem under the specified rules without post-hoc threshold relaxation, metric tampering, or goalpost moving?

---

## 🧬 Harness² Recursive Adaptation Engine: What It Is & What It Does in Your Harness

This coordinator integrates Google Research's **Harness²** (*Recursive Agent Harnessing for an Open World*, `.antigravity/harness2/`), hardened for cross-platform **Windows 11 + POSIX** and **Python 3.12–3.14** execution.

### Why Harness² Is Needed
While foundation model weights are fixed at inference time, an agent's real-world reliability depends heavily on its **harness**—the surrounding system of standing instructions, tool guidance, on-demand skills, deterministic helper scripts, subagent roles, and tool-loop lifecycle hooks. When an agent fails repeatedly on a complex engineering or quantitative research task, retrying the same task with the exact same harness repeats the same failure mode.

### What Harness² Actually Does in the Swarm Coordinator
When triggered (either automatically after repeated leaf-task failures in `asw-loop`, on explicit `/asw-harness-adapt` invocation, or during Mode 5 continual domain sweeps), **Harness²** executes a closed-loop **5-stage recursive adaptation cycle (`Propose ➔ Probe ➔ Compose ➔ Select ➔ Reflect`)**:

1. **Stage 1 — Orthogonal Diagnosis & Proposal (`Propose` via `Gemini 4 Argon High`):**
   Instead of making ad-hoc prompt edits, `Gemini 4 Argon (High)` inspects the full, untruncated execution trajectories (`context/rollouts/`) and produced deliverables (`context/deliverables/`) across two strictly separated axes:
   - **`INV` (Invariant Axis — *How the Agent Works*):** Diagnoses procedural failures, tool-use errors, timeout loops, or fragile hand-rolled calculations. It proposes deterministic helper scripts (`scripts/<name>.py`), tool guidance (`.antigravity/tool_guidance.md`), bounded subagent definitions (`.antigravity/sub_agents/<name>/AGENT.md`), or tool-loop hooks (`.antigravity/hooks.json`) that cannot be skipped by the model.
   - **`DOM` (Domain Axis — *What a Practitioner Knows*):** Diagnoses missing domain knowledge, accounting/quant reconciliation rules, or domain-specific edge cases. It encodes checkable practitioner rules into on-demand skills (`.agents/skills/<name>/SKILL.md`) paired with narrow verbatim trigger lines in `.antigravity/harness_triggers.md`—so domain knowledge costs zero tokens until triggered.
2. **Stage 2 — Isolated Git-Worktree Candidate Probing (`Probe` via `Gemini 3.8 Flash High`):**
   Each proposed `INV` and `DOM` candidate harness is validated pre-rollout (`py_compile` on scripts, YAML frontmatter checks on skills, trigger-line verification, and budget checks) and then executed by `Gemini 3.8 Flash (High)` inside an **isolated Git worktree** (`SwarmTaskAdapter`). In `k=1` failure-repair mode (`reuse_base=True`), the failed rollout is reused directly as `base1` without re-running it.
3. **Stage 3 — Evidence-Grounded Synthesis (`Compose` via `Gemini 4 Argon High`):**
   `Gemini 4 Argon (High)` compares the base trajectory and deliverables against the `INV` and `DOM` probe outputs, merging only the components that demonstrably fixed the observed failure (or emitting `KEEP_BASE` if adaptation did not improve over the base harness, preventing prompt bloat).
4. **Stage 4 — Cross-Family Blind Candidate Selection (`Select` via `Claude Opus 5.5`):**
   Candidate deliverables (`base`, `composed`) are anonymized and shuffled (`Candidate A, B, ...`). **Antigravity-native `Claude Opus 5.5`** (`channels["selector"]`) performs blind selection without knowing which output came from which harness and with strict anti-leakage tripwires (`assert_no_grader_verdicts()`).
5. **Stage 5 — Continual Experience Distillation & Obsidian Vault Sync (`Reflect` via `Claude Opus 5.5`):**
   Once the winning harness is selected, `Claude Opus 5.5` extracts a structured transferable lesson (`cue`, `lesson`, `evidence`, `confidence`) into `EXPERIENCE.md`. The bridge script `sync_harness_experience.py` verifies the lesson and automatically syncs it into your Obsidian Knowledge Vault (`~/Documents/AgentMemory/projects/<project>/experiences/<domain>.md`), warm-starting future tasks in the same domain!

### Immutable Governance Boundary (`ANTIGRAVITY_SURFACE`)
To guarantee that recursive self-improvement can **never** weaken safety rules, falsify metrics, or bypass audit gates, `AntigravitySubstrate` (`ANTIGRAVITY_SURFACE`) enforces a strict wall between editable harness components and immutable governance files:

| Component Path | Surface Role | Mutability in Harness² |
| :--- | :--- | :--- |
| `.antigravity/harness_triggers.md` | Always-on skill trigger lines (`c1`/`c6`) | **Editable** (hard-capped at `<= 6,000` chars & `<= 8` active skills) |
| `.antigravity/tool_guidance.md` | Always-on tool usage notes (`c4`) | **Editable** (shares the `6,000`-char always-on cap) |
| `.agents/skills/<name>/SKILL.md` | On-demand domain/workflow skills (`c6`) | **Editable** (requires YAML frontmatter + trigger line) |
| `scripts/<name>.py` | Deterministic Python helper scripts (`c7`) | **Editable** (must pass `py_compile` + reference integrity) |
| `.antigravity/sub_agents/<name>/AGENT.md` | Bounded subagent definitions (`c5`) | **Editable** (runs in isolated subagent context) |
| `.antigravity/hooks.json` | Tool-loop lifecycle hooks (`c8`) | **Editable** (`PreToolUse`, `PostToolUse`, `Stop` hooks) |
| `GLOBAL_DEVELOPMENT_RULES.md`, `GEMINI.md`, `AGENTS.md` | Core Coordinator & Safety Rules | **IMMUTABLE (Strictly Rejected + Symlink-Blocked)** |
| `PROGRAM_INVARIANTS.json`, `METRIC_REGISTRY.json`, `SOURCE_PLAN.md` | Mode 5 Semantic & Evaluation Registries | **IMMUTABLE (Strictly Rejected + SHA-256 Protected)** |

### Key CLI Commands for Harness² & Claude Opus 5.5 Review Gates

```powershell
# 1. Verify Antigravity-native Claude Opus 5.5 runtime & subagent TOMLs
python .antigravity/scripts/invoke_opus_reviewer.py --preflight

# 2. Run Pre-Execution Plan Opposition Audit (Claude Opus 5.5 reviews Gemini 4 Argon plan)
python .antigravity/scripts/invoke_opus_reviewer.py --mode plan-review `
  --plan .asw/plans/<slug>.md `
  --output .asw/reviews/<slug>-opus-plan-review.md

# 3. Run Runtime Diff & QA Opposition Audit (Claude Opus 5.5 audits diff & 3-layer evidence)
python .antigravity/scripts/invoke_opus_reviewer.py --mode diff-review `
  --plan .asw/plans/<slug>.md `
  --diff <path-to-diff> `
  --evidence .asw/evidence `
  --output .asw/reviews/<slug>-opus-diff-review.md

# 4. Run Harness² Recursive Adaptation Loop + Automatic Obsidian Vault Experience Sync
python .antigravity/scripts/run_harness_adapt.py --demo `
  --project <project-name> `
  --output .asw/evidence/adapt_run `
  --sync-obsidian
```

---

## ⚡ Execution Modes (Modes 0 to 5)

| Mode | Name | Purpose & Governance |
| :--- | :--- | :--- |
| **Mode 0** | Operational Fast Path | Direct build, test, run, and lint operations. Coordinator + Validator only; zero design bureaucracy. |
| **Mode 1** | Investigation Only | Analysis, bug reproduction, and diagnostics without source code mutation. No state changes. |
| **Mode 2** | Small Controlled Change | Focused modifications with concise change records, existing-reference audits, and targeted tests. |
| **Mode 3** | Complex Delivery | Complex features: specification & design ➔ Opus 5.5 Plan Review ➔ user approval ➔ autonomous Flash waves ➔ Opus 5.5 Diff Review & Argon QA ➔ handoff. |
| **Mode 4** | Emergency Restore | Minimal restoration of working state only; no opportunistic refactoring or feature additions. |
| **Mode 5** | Long-Horizon Program / Research | Multi-campaign programs: immutable `SOURCE_PLAN.md` freeze, `REQUIREMENT_COVERAGE.csv`, `TASK_GRAPH.json`, Harness² domain adaptation, multi-auditor sign-off. |

---

## 📁 Repository Structure

```text
antigravity_swarm_coordinator/
├── README.md                          # This documentation
├── install.ps1                        # Automated PowerShell installation and restore script
├── .gitignore                         # Git ignore rules for caches and temporary artifacts
│
├── global_entrypoint/
│   └── GEMINI.md                      # Global instructions deployed to ~/.gemini/GEMINI.md
│
├── core_framework/                    # Long-Horizon V4.1 + Harness² Governance Framework
│   ├── agents/                        # Native Antigravity Claude Opus 5.5 subagent TOMLs
│   │   ├── asw-plan-audit.toml        # Pre-Execution Plan Opposition Auditor (claude-opus-5-5)
│   │   ├── asw-opposition-reviewer.toml # Adversarial Diff & QA Reviewer (claude-opus-5-5)
│   │   └── asw-reviewer.toml          # Release & Functional Reviewer (claude-opus-5-5)
│   ├── harness2/                      # Vendored & Windows-hardened Google Research Harness² engine
│   │   ├── core/                      # tree, recursion, selection, library, ledger, proposer, spec
│   │   ├── substrate/                 # antigravity.py (ANTIGRAVITY_SURFACE), codex.py, opencode.py
│   │   ├── adapter_swarm.py           # Git-worktree isolated rollout adapter with reuse_base=True
│   │   └── cli/                       # CLI runners (demo.py, run_sweep.py, check.py, report.py)
│   ├── rules/
│   │   └── GLOBAL_DEVELOPMENT_RULES.md # Comprehensive Tri-Model & 4-axis governance rules
│   ├── docs/
│   │   ├── V4_1_OPERATOR_GUIDE.md     # Operator guide for semantic integrity and 4-axis completion
│   │   ├── ANTIGRAVITY_LONG_HORIZON_AUDIT_V4.md # Architecture audit and theoretical foundation
│   │   └── RECOMMENDED_SKILLS.md      # Curated companion skills guide and budget rules
│   ├── scripts/                       # Python validation, audit, and Harness² bridge scripts
│   │   ├── invoke_opus_reviewer.py    # Claude Opus 5.5 Plan & Diff Opposition Review CLI
│   │   ├── run_harness_adapt.py       # Harness² recursive adaptation CLI runner
│   │   ├── sync_harness_experience.py # Path-independent Obsidian Vault experience sync
│   │   ├── validate_program_state.py  # Strict mechanical program state & task graph validator
│   │   ├── validate_agent_setup.py    # Runtime environment setup verification
│   │   ├── run_semantic_audit.py      # Semantic integrity audit runner
│   │   ├── run_invariant_audit.py     # Invariant preservation auditor
│   │   ├── run_report_consistency_audit.py # Cross-report contradiction detection runner
│   │   └── migrate_v4_to_v4_1.py      # Migration script from V4 to V4.1
│   ├── semantic/                      # Python semantic integrity engine (auditor, claims, memory, etc.)
│   ├── skills/                        # All 22 specialized agent, auditor, and adaptation skills
│   └── templates/                     # Project control-plane templates (Modes 2, 3, and 5)
│
├── plugins/
│   └── antigravity-swarm/             # Antigravity Swarm (ASW) Engine Plugin
│       ├── plugin.json                # Plugin manifest (v0.2.4)
│       ├── agents/                    # ASW subagents (including Claude Opus 5.5 reviewers)
│       ├── hooks/                     # ASW task lifecycle hooks
│       ├── scripts/                   # ESM/Node.js diagnostic and status scripts
│       └── skills/                    # ASW utility skills (asw-plan, asw-loop, asw-harness-adapt, ...)
│
├── tests/                             # 29 automated unit, negative, and path-independence tests
│   ├── test_harness2_windows.py       # Windows msvcrt locks, POSIX paths, symlink rejection
│   ├── test_antigravity_substrate.py  # Immutable governance & 8-skill budget enforcement
│   ├── test_swarm_adapter.py          # Tri-Model channel routing & git worktree isolation
│   ├── test_opus_reviewer.py          # Claude Opus 5.5 plan-review & diff-review gates
│   ├── test_experience_obsidian_sync.py # Continual learning & Obsidian Vault sync
│   └── test_path_independence.py      # Zero hardcoded user paths across the repository
│
└── .antigravity/                      # Drop-in framework directory ready for any target repository
```

---

## 🛠️ Specialized Roles & Skills Catalog

This repository includes all **22 specialized skills** directly powering the coordinator, recursive harness adaptation, and cross-family auditors:

1. **`swarm-coordinator`**: Global orchestration lead and state machine authority (`Gemini 4 Argon High`).
2. **`skill-router`**: Catalog routing and strict active skill budget enforcement (max 8) across the Tri-Model tiers.
3. **`asw-harness-adapt`**: Recursive `Harness²` adaptation (`Propose–Probe–Compose–Select–Reflect`) and continual Obsidian experience sync.
4. **`program-state-controller`**: State machine, ledger, and task graph manager (`Gemini 4 Argon High`).
5. **`spec-product-analyst`**: Requirements, acceptance criteria, and non-goals specification (`Gemini 4 Argon High`).
6. **`software-architect`**: Technical architecture, component boundaries, and API design (`Gemini 4 Argon High`).
7. **`ui-ux-designer`**: Interface workflows, design systems, and state-space specifications (`Gemini 4 Argon High`).
8. **`implementation-developer`**: Bounded diff implementation under strict task contracts (`Gemini 3.8 Flash High`).
9. **`interaction-e2e-tester`**: Interaction and end-to-end verification (`Gemini 3.8 Flash High`).
10. **`validator-build-test-agent`**: Repository-native command discovery and state validation (`Gemini 3.8 Flash High`).
11. **`compliance-maintainability-reviewer`**: Coding conventions, code quality, and blast radius auditing (`Gemini 4 Argon High`).
12. **`opposition-reviewer`**: Cross-family adversarial falsification, plan auditing, and leakage detection (`Claude Opus 5.5`).
13. **`acceptance-reviewer-product-qa`**: Empirical product requirements verification with direct evidence (`Gemini 4 Argon High`).
14. **`security-reliability-reviewer`**: Trust boundaries, threat modeling, and security audits (`Gemini 4 Argon High`).
15. **`research-experiment-auditor`**: Quant/ML governance, out-of-sample discipline, and fold safety (`Gemini 4 Argon High`).
16. **`memory-state-curator`**: Secondary advisory memory synchronization (`~/Documents/AgentMemory`, Graphify) (`Gemini 3.8 Flash High`).
17. **`completion-auditor`**: Independent mechanical closure and 100% completion verification (`Gemini 4 Argon High`).
18. **`documentation-handoff-agent`**: Documentation impact and final handoff audit (`Gemini 3.8 Flash High`).
19. **`invariant-auditor`**: Verification of non-negotiable program contracts (`Gemini 4 Argon High`).
20. **`report-consistency-auditor`**: Cross-report claim reconciliation and arithmetic verification (`Gemini 4 Argon High`).
21. **`research-validity-auditor`**: Scientific validity, causal data contracts, and ablation checks (`Gemini 4 Argon High`).
22. **`semantic-completion-auditor`**: Independent semantic sign-off preventing goalpost drift (`Gemini 4 Argon High`).

---

## 🧩 Recommended Companion Skills (Curated Catalog)

The Swarm Coordinator operates with a searchable library of installed skills, dynamically activating up to **8 active skills** per leaf task. Based on what is proven and installed in this Antigravity environment, the following companion skills are strongly recommended:

### 1. Antigravity Swarm (ASW) Execution Suite
*Included in this repository under `plugins/antigravity-swarm` and registered in Antigravity.*
- **`asw`**: Main Antigravity Swarm execution loop with automated tests, subagents, and manual QA receipts.
- **`asw-plan`**: Pre-implementation decision-complete planning paired with the mandatory `Claude Opus 5.5` Plan Opposition Gate.
- **`asw-loop`**: Autonomous RED ➔ GREEN ➔ real-surface QA loop.
- **`asw-harness-adapt`**: Triggers `Harness²` recursive harness self-improvement when tasks fail repeatedly or require domain adaptation.
- **`asw-goal`**: Converts ambiguous briefs into concrete, measurable evidence criteria.
- **`asw-review`**: Post-change behavioral diff audit powered by `Claude Opus 5.5` (`asw-reviewer.toml`).
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
.\install.ps1 -TargetRepoPath "~/Projects/YourProject"
```

The script will:
1. Back up any existing `~/.gemini/GEMINI.md` to `GEMINI.md.bak` and deploy the coordinator prompt.
2. Install all 22 skills to `~/.gemini/config/skills/`.
3. Deploy the ASW plugin (including native `Claude Opus 5.5` reviewer agents) to `~/.gemini/config/plugins/antigravity-swarm/`.
4. (Optional) Copy `.antigravity/` (including `harness2/`) directly into your target repository root.

### Running the Verification Suite

```powershell
python -m unittest discover -s tests -v
```

---

## 📄 License

This distribution contains open-source components under the MIT License and Apache 2.0 License (`harness2`) and coordinator configurations intended for managing Google Antigravity and Gemini CLI environments.
