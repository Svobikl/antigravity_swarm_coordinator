# Antigravity Swarm Coordinator (Long-Horizon V4.1 + Harness² + Claude Opus 5.5 + 200 Multi-Domain Skills)

Complete backup, distribution, and cross-platform setup package (**Apple macOS**, **Windows**, and **Linux**) for the default **Swarm Coordinator**, **Google Research `Harness²` recursive adaptation engine**, **Tri-Model Cross-Family Governance Framework** (`Gemini 4 Argon High` + `Claude Opus 5.5` + `Gemini 3.8 Flash High`), and **200 Curated Multi-Domain Golden Catalog Skills** for **Google Antigravity** and **Gemini CLI**.

This repository contains the complete coordinator architecture—100% **path-independent** across users and operating systems—including the global configuration entry point prompt, immutable governance rules, the `Harness²` self-improving harness engine, native `Claude Opus 5.5` adversarial plan & diff review gates, validation scripts, **all 200 curated multi-domain skills**, the ASW engine plugin (`antigravity-swarm`), and 35 automated verification tests.

---

## 🏗️ Architecture & Operating Principles

In Antigravity, the Swarm Coordinator functions under the **Single Orchestrator Rule**, acting as the sole authority for global scope, program state transitions, task breakdown, agent lifecycles, recursive harness adaptation, and multi-auditor completion verification.

```text
                    ┌────────────────────────────────────────────────────────┐
                    │       ~/.gemini/GEMINI.md & ~/.agents/AGENTS.md        │
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

This coordinator integrates Google Research's **Harness²** (*Recursive Agent Harnessing for an Open World*, `.antigravity/harness2/`), hardened for cross-platform **macOS + Windows 11 + Linux** and **Python 3.12–3.14** execution.

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

```bash
# 1. Verify Antigravity-native Claude Opus 5.5 runtime & subagent TOMLs (macOS / Windows / Linux)
python3 .antigravity/scripts/invoke_opus_reviewer.py --preflight

# 2. Run Pre-Execution Plan Opposition Audit (Claude Opus 5.5 reviews Gemini 4 Argon plan)
python3 .antigravity/scripts/invoke_opus_reviewer.py --mode plan-review \
  --plan .asw/plans/<slug>.md \
  --output .asw/reviews/<slug>-opus-plan-review.md

# 3. Run Runtime Diff & QA Opposition Audit (Claude Opus 5.5 audits diff & 3-layer evidence)
python3 .antigravity/scripts/invoke_opus_reviewer.py --mode diff-review \
  --plan .asw/plans/<slug>.md \
  --diff <path-to-diff> \
  --evidence .asw/evidence \
  --output .asw/reviews/<slug>-opus-diff-review.md

# 4. Run Harness² Recursive Adaptation Loop + Automatic Obsidian Vault Experience Sync
python3 .antigravity/scripts/run_harness_adapt.py --demo \
  --project <project-name> \
  --output .asw/evidence/adapt_run \
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
├── install.py                         # Universal cross-platform installer (macOS, Windows, Linux)
├── install.sh                         # POSIX Bash/Zsh installer for Apple macOS & Linux
├── install.ps1                        # PowerShell installer for Windows
├── .gitattributes                     # Enforces LF on *.sh for macOS/Linux compatibility
├── .gitignore                         # Git ignore rules for caches and temporary artifacts
│
├── global_entrypoint/
│   └── GEMINI.md                      # Global instructions deployed to ~/.gemini/GEMINI.md & ~/.agents/AGENTS.md
│
├── core_framework/                    # Long-Horizon V4.1 + Harness² Governance Framework
│   ├── agents/                        # Native Antigravity Claude Opus 5.5 subagent TOMLs
│   │   ├── asw-plan-audit.toml        # Pre-Execution Plan Opposition Auditor (claude-opus-5-5)
│   │   ├── asw-opposition-reviewer.toml # Adversarial Diff & QA Reviewer (claude-opus-5-5)
│   │   └── asw-reviewer.toml          # Release & Functional Reviewer (claude-opus-5-5)
│   ├── harness2/                      # Vendored & cross-platform Google Research Harness² engine
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
│   ├── scripts/                       # Python validation, audit, curation, and Harness² bridge scripts
│   │   ├── invoke_opus_reviewer.py    # Claude Opus 5.5 Plan & Diff Opposition Review CLI
│   │   ├── run_harness_adapt.py       # Harness² recursive adaptation CLI runner
│   │   ├── sync_harness_experience.py # Path-independent Obsidian Vault experience sync
│   │   ├── curate_skill_catalog.py    # Curates & normalizes the 200-skill Golden Catalog
│   │   ├── validate_program_state.py  # Strict mechanical program state & task graph validator
│   │   ├── validate_agent_setup.py    # Runtime environment setup verification
│   │   ├── run_semantic_audit.py      # Semantic integrity audit runner
│   │   ├── run_invariant_audit.py     # Invariant preservation auditor
│   │   ├── run_report_consistency_audit.py # Cross-report contradiction detection runner
│   │   └── migrate_v4_to_v4_1.py      # Migration script from V4 to V4.1
│   ├── semantic/                      # Python semantic integrity engine (auditor, claims, memory, etc.)
│   ├── skills/                        # All 200 curated Multi-Domain Golden Catalog skills (9 domains)
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
├── tests/                             # 35 automated unit, negative, and cross-platform tests
│   ├── test_harness2_windows.py       # Cross-platform locks, POSIX paths, symlink rejection
│   ├── test_antigravity_substrate.py  # Immutable governance & 8-skill budget enforcement
│   ├── test_swarm_adapter.py          # Tri-Model channel routing & git worktree isolation
│   ├── test_opus_reviewer.py          # Claude Opus 5.5 plan-review & diff-review gates
│   ├── test_experience_obsidian_sync.py # Continual learning & Obsidian Vault sync
│   ├── test_skill_catalog_curation.py # 200-skill Golden Catalog & BOM/frontmatter bounds
│   ├── test_cross_platform_installer.py # macOS/Windows/Linux installer & runtime discovery
│   └── test_path_independence.py      # Zero hardcoded user paths across the repository
│
└── .antigravity/                      # Drop-in framework directory ready for any target repository
```

---

## 🛠️ Bundled 200-Skill Multi-Domain Golden Catalog (`core_framework/skills/`)

### Why We Audited & Curated This Complete Skill Pack (Solving the Context-Window Bloat Problem)

The internet and open-source AI repositories are flooded with massive packs of **1,500–2,000+ community skills**. In practice, installing raw community skill dumps creates severe problems for agentic coding environments like **Google Antigravity** and **Gemini CLI**:

1. **Context-Window Pollution & Silent Customization Truncation:** At the start of every session, the IDE builds a system-prompt index (`<skills>`) containing the name, file path, and `description` frontmatter of every installed skill. When 1,500–2,000+ skills are installed on disk, just listing their metadata overflows the IDE's customization token budget (`"If a budget is exceeded, large rules are demoted to path pointers and large customizations are excluded automatically"`). The IDE then silently truncates or excludes ~90% of installed skills—often evicting the most critical architecture and coordinator skills first because their descriptions are longer.
2. **Massive Duplication, Broken Templates & Unusable Wrappers:** Our forensic audit of **2,040+ community skills** (3,765 skill directories across global folders) revealed that over 85% consisted of redundant noise:
   - **119 hyper-fragmented `azure-*` micro-skills** for individual NuGet/Maven/PyPI SDK packages,
   - **91 `*-automation` wrappers** coupled to third-party paid SaaS MCP servers (Composio Rube),
   - **77 duplicate hyphen-prefixed plugin clones** (e.g., `code-documentation-doc-generate` vs. `documentation-generation-doc-generate`),
   - **58 foreign-language-only (Chinese CJK / Brazilian Portuguese) skills**,
   - **25 unfilled boilerplate templates** whose description literally read `"One sentence - what this skill does and when to invoke it"`,
   - **Hundreds of overlapping micro-variants** (e.g., 46 overlapping SEO micro-skills and 184 overlapping UI style stubs), plus **18 files with UTF-8 BOMs (`\xef\xbb\xbf`)** that broke strict YAML frontmatter parsers.

To solve this permanently, we conducted a **full audit, deduplication, and frontmatter normalization**, distilling a **complete, self-contained 200-Skill Multi-Domain Golden Catalog** bundled directly inside `core_framework/skills/`:

- **Zero Context Truncation (100% Indexed):** All 200 skills are UTF-8 BOM-free and normalized to a crisp, high-signal single-line `description` (`<= 97` characters). The entire 200-skill index fits comfortably inside Antigravity IDE's startup customization budget with **0 excluded skills**.
- **On-Demand Loading (Max 8 Active Skills Budget):** Full `SKILL.md` bodies are **never** preloaded into the prompt. Instead, `swarm-coordinator` and `skill-router` load only the **1–8 relevant skills on demand** for the active task, keeping the model's context window clean and sharp.
- **Complete Multi-Domain Coverage Out of the Box:** Because real-world projects span far more than just writing code, this single audited pack equips Antigravity across **all 9 operational domains**—from software engineering, Odoo ERP, and embedded firmware to legal/GDPR compliance, executive presentations/Office docs, product strategy, hardware BOM sourcing, marketing/SEO/GEO, 3D UI/UX, and quantitative research:

| # | Domain | Count | Included Skills (Highlights) |
| :--- | :--- | :---: | :--- |
| **1** | **Swarm Coordinator, ASW & Obsidian Memory (Core)** | **43** | All 21 Coordinator & V4.1 Semantic Auditor skills (`swarm-coordinator`, `skill-router`, `program-state-controller`, `opposition-reviewer`, `completion-auditor`, `invariant-auditor`, `report-consistency-auditor`, `research-validity-auditor`, `semantic-completion-auditor`, etc.), all 16 `asw-*` skills (including `asw-harness-adapt`), and 6 `obs-memory` / `obsidian-*` / `agent-memory` skills |
| **2** | **Legal, Contracts, GDPR, Compliance & Regulatory** | **9** | `lex` (EU/US/CA legal analysis & contracts), `legal-advisor`, `employment-contract-templates`, `gdpr-data-handling`, `privacy-by-design`, `pci-compliance`, `fda-medtech-compliance-auditor`, `customs-trade-compliance`, `security-compliance-compliance-check` |
| **3** | **Presentations, Slides, Office Documents & Diagrams** | **13** | `pptx-official`, `pptx-deck-creation`, `frontend-slides`, `docx-official`, `xlsx-official`, `pdf-official`, `document-extraction`, `writer`, `calc`, `mermaid-expert`, `c4-container`, `data-storytelling`, `professional-proofreader` |
| **4** | **Project, Product, Strategy, Finance & Hardware Sourcing** | **17** | `product-manager-toolkit`, `concise-planning`, `planning-with-files`, `brain-to-docs`, `architecture-decision-records`, `osterwalder-canvas-architect`, `kotler-macro-analyzer`, `moatmri`, `market-sizing-analysis`, `startup-financial-modeling`, `kpi-dashboard-design`, `pricing-strategy`, `launch-strategy`, `linear-claude-skill`, `github`, `inventory-demand-planning`, `electronics-sourcing` |
| **5** | **Marketing, SEO, GEO (AI Search), Copywriting & CRO** | **14** | `marketing-plan`, `content-creator`, `copywriting`, `copy-editing`, `page-cro`, `signup-flow-cro`, `seo-audit`, `seo-fundamentals`, `geo-fundamentals`, `schema-markup`, `competitor-analysis`, `customer-research`, `email-sequence`, `analytics-tracking` |
| **6** | **UI/UX, Frontend, Web, 3D, Motion & Video** | **18** | `frontend-design`, `ui-ux-pro-max`, `web-design-guidelines`, `ux-audit`, `ux-flow`, `ui-a11y`, `design-system`, `tailwind-design-system`, `shadcn`, `react-patterns`, `nextjs-best-practices`, `3d-ui`, `threejs-skills`, `animejs-animation`, `remotion-best-practices`, `claude-d3js-skill`, `mobile-design`, `hig-foundations` |
| **7** | **Software Engineering, Odoo ERP, Embedded & Databases** | **39** | **Odoo (9):** `odoo-module-developer`, `odoo-orm-expert`, `odoo-xml-views-builder`, `odoo-qweb-templates`, `odoo-security-rules`, `odoo-rpc-api`, `odoo-accounting-setup`, `odoo-docker-deployment`, `odoo-upgrade-advisor`<br>**Embedded & Systems (6):** `firmware-analyst`, `arm-cortex-expert`, `c-pro`, `cpp-pro`, `rust-pro`, `protocol-reverse-engineering`<br>**Languages, Backend, DB & Mobile (24):** `python-pro`, `fastapi-pro`, `django-pro`, `pydantic-models-py`, `typescript-pro`, `nodejs-backend-patterns`, `golang-pro`, `csharp-pro`, `java-pro`, `php-pro`, `sql-pro`, `postgres-best-practices`, `drizzle-orm-expert`, `prisma-expert`, `graphql-architect`, `zustand-store-ts`, `flutter-expert`, `react-native-architecture`, `swiftui-expert-skill`, `electron-development`, `senior-architect`, `domain-driven-design`, `code-reviewer`, `simplify-code` |
| **8** | **Data Science, Quantitative Research, AI/LLM & Science** | **20** | `quant-analyst`, `backtesting-frameworks`, `risk-metrics-calculation`, `data-scientist`, `data-engineer`, `polars`, `scikit-learn`, `statsmodels`, `matplotlib`, `plotly`, `ml-pipeline-workflow`, `ai-agents-architect`, `rag-engineer`, `embedding-strategies`, `prompt-engineer`, `gemini-api-dev`, `claude-api`, `mcp-builder`, `deep-research`, `ii-commons` |
| **9** | **Testing, Debugging, DevOps, Cloud, Security & Shell** | **27** | `systematic-debugging`, `test-driven-development`, `test-guard`, `playwright-skill`, `browser-harness`, `pytest-skill`, `vitest-skill`, `api-security-best-practices`, `security-auditor`, `differential-review`, `secrets-management`, `docker-expert`, `kubernetes-architect`, `terraform-skill`, `aws-skills`, `cloudflare`, `vercel-deployment`, `supabase`, `github-actions-templates`, `grafana-dashboards`, `vps-server-management`, `powershell-windows`, `windows-shell-reliability`, `bash-pro`, `jq`, `git-advanced-workflows`, `resolving-merge-conflicts` |

---

## 🚀 Cross-Platform Installation (Apple macOS, Windows & Linux)

Installing the repository automatically deploys the global `GEMINI.md` / `AGENTS.md` prompt, **all 200 curated Multi-Domain Golden Catalog skills**, the `antigravity-swarm` plugin, and the native `Claude Opus 5.5` reviewer subagent configurations.

### 🍎 Apple macOS (Apple Silicon M1/M2/M3/M4 & Intel) / Linux

Run `install.sh` (or `python3 install.py` directly) from Terminal:

```bash
chmod +x install.sh

# 1. Install global coordinator, all 200 skills, and ASW plugin (and prune any duplicate old skills):
./install.sh --clean-skills

# 2. Or install globally AND deploy .antigravity into a target project repository:
./install.sh --clean-skills --target-repo ~/Projects/YourProject
```

### 🪟 Windows (PowerShell)

Run `install.ps1` (or `python install.py` directly) from PowerShell:

```powershell
# 1. Install global coordinator, all 200 skills, and ASW plugin (and prune any duplicate old skills):
.\install.ps1 -CleanSkills

# 2. Or install globally AND deploy .antigravity into a target project repository:
.\install.ps1 -CleanSkills -TargetRepoPath "~/Projects/YourProject"
```

### What the Installer Deploys
1. Backs up any existing `~/.gemini/GEMINI.md` to `GEMINI.md.bak` and installs `~/.gemini/GEMINI.md` and `~/.agents/AGENTS.md`.
2. Installs **all 200 curated skills** into `~/.gemini/config/skills/`, `~/.gemini/antigravity-ide/skills/`, and `~/.agents/skills/` (and removes old duplicate bloat when `--clean-skills` / `-CleanSkills` is passed).
3. Deploys the ASW plugin and native `Claude Opus 5.5` reviewer subagent TOMLs to `~/.gemini/config/plugins/antigravity-swarm/`.
4. Automatically resolves Antigravity's native runtime binary on both **macOS** (`/Applications/Antigravity.app/...`, `~/Applications/Antigravity.app/...`, `/opt/homebrew/bin/agy`) and **Windows** (`%LOCALAPPDATA%/Programs/antigravity/...`).
5. (Optional) Copies `.antigravity/` (including `harness2/`) into your target project repository.

### Running the Verification Suite

```bash
python3 -m unittest discover -s tests -v
```

---

## 📄 License

This distribution contains open-source components under the MIT License and Apache 2.0 License (`harness2`) and coordinator configurations intended for managing Google Antigravity and Gemini CLI environments.
