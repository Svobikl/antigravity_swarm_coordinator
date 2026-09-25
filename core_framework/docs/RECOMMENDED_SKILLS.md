# Recommended Companion Skills Catalog

While **Swarm Coordinator** provides the global orchestration, state machine, and multi-auditor closure (Mode 0 through Mode 5), complex software engineering and quantitative research benefit from specialized companion skills.

Under the **Strict Active Skill Budget Rule**, no more than **8 active skills** are loaded into context per leaf task. The installed catalog is treated as an on-demand searchable library routed dynamically by `skill-router`.

Below is the curated catalog of recommended skills tested and verified in this Antigravity environment.

---

## 1. Antigravity Swarm (ASW) Execution Suite
*Packaged inside `plugins/antigravity-swarm` and `~/.gemini/config/skills/`.*  
These skills serve as the localized execution engine under coordinator supervision:

| Skill | Role / Function | When to Activate |
| :--- | :--- | :--- |
| **`asw`** | Main ASW execution loop with subagents, tests, and evidence. | Mode 2 & Mode 3 localized implementation sprints. |
| **`asw-plan`** | Decision-complete plan generator with verification steps. | Breaking down sub-epics before implementation. |
| **`asw-loop`** | RED ➔ GREEN ➔ real-surface QA cycle with cleanup receipts. | Strict code change implementation loops. |
| **`asw-goal`** | Deconstructs ambiguous user briefs into concrete evidence criteria. | Requirements crystallization phase. |
| **`asw-review`** | Behavioral integrity inspection of working diffs. | Pre-commit/pre-audit sanity checks. |
| **`asw-debug`** | Hypothesis-driven debugging for crashes, hangs, and drift. | When build or runtime regressions occur. |
| **`asw-remove-ai-slops`** | Removes AI-generated clutter, comments, and unneeded abstractions. | Code hygiene pass before acceptance review. |
| **`asw-lsp`** | Language server diagnostics and symbol-safety auditing. | Typed language refactoring and symbol rename verification. |

---

## 2. Planning, Task Decomposition & Disk State Memory

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`planning-with-files`** | Uses persistent markdown files as working memory on disk. | Complements `PROGRAM_STATE.md` and protects against context loss across session restarts. |
| **`subagent-driven-development`**| Dispatches and tracks independent subagents with atomic scope. | Enforces bounded task contracts (max 4 parallel subagents). |
| **`executing-plans`** | Executes structured implementation plans with gated checkpoints. | Prevents agents from skipping ahead or claiming false progress. |
| **`writing-plans`** | Generates detailed, atomic step-by-step checklists. | Pre-implementation decomposition for Mode 3 and Mode 5 programs. |

---

## 3. Test-Driven Development (TDD) & Evidence Verification

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`test-driven-development`** | Enforces strict Red-Green-Refactor cycles before writing code. | Ensures no production code is written without failing test proof. |
| **`tdd-workflow`** | Standardized TDD cycle execution patterns. | Guides leaf task developers through clean test-driven phases. |
| **`verification-before-completion`** | Prohibits declaring done without empirical proof on disk. | Essential alignment with `completion-auditor` requirements. |
| **`lint-and-validate`** | Runs canonical workspace validation tools after edits. | Mode 0 fast path and pre-review clean gate. |

---

## 4. Debugging & Code Quality Auditing

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`systematic-debugging`** | 4-phase root-cause investigation before proposing fixes. | Mandated for Mode 1 investigations and Mode 0/2 build breaks. |
| **`debugger`** | Specialist for unexpected exceptions, test failures, and hangs. | Deep-dive troubleshooting on complex failure stacks. |
| **`code-reviewer`** | Elite code reviewer checking quality, idioms, and edge cases. | Pairs with `compliance-maintainability-reviewer`. |
| **`vibe-code-auditor`** | Audits rapidly generated AI code for structural flaws. | Detects hallucinated APIs, shallow mocks, and brittle logic. |
| **`simplify-code`** | Safely simplifies diffs and removes unnecessary complexity. | Enforces minimal blast-radius and anti-bloat rules. |

---

## 5. Architecture & Security Governance

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`architect-review`** | Evaluates software design, scalability, and modularity. | Mode 3 technical design phase. |
| **`senior-architect`** | End-to-end system design and technology tradeoffs. | Component boundary specification before leaf dispatch. |
| **`security-auditor`** | DevSecOps, secret leakage, and trust boundary auditing. | Pairs with `security-reliability-reviewer` for auth & API changes. |
| **`database-design`** | Schema design, indexing strategies, and migration safety. | Database-backed feature implementations. |

---

## 6. Environment & Operating System Reliability

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`windows-shell-reliability`** | Handles Windows paths, escaping, CRLF, and binary pitfalls. | Critical for Windows/PowerShell environments to prevent silent command failures. |
| **`powershell-windows`** | Modern PowerShell syntax, operator pitfalls, and error traps. | Ensures background tasks and script executions terminate reliably. |
| **`posix-shell-pro`** | Defensive POSIX shell scripting and piping standards. | Multi-platform CI/CD and container scripts. |

---

## 7. Research, Quantitative & Data Analysis (Mode 5)

| Skill | Role / Function | Value to Swarm Coordinator |
| :--- | :--- | :--- |
| **`quant-analyst`** | Financial/statistical model evaluation and backtesting sanity. | Essential for quant programs (e.g. Freqtrade, Sharpe/DSR verification). |
| **`scikit-learn`** | ML pipelines, fold evaluation, and leak-free cross-validation. | Pairs with `research-experiment-auditor` for fold safety. |
| **`polars`** / **`networkx`** | High-performance dataframe and graph analysis. | Large-scale dataset and execution graph processing. |

---

## Summary: How to Assemble the 8-Skill Budget

For any given task, select:
1. **`swarm-coordinator`** (Always active orchestration lead)
2. **`skill-router`** (Budget gatekeeper)
3. **1 Task-Specific Lead** (e.g., `implementation-developer`, `software-architect`, or `asw-loop`)
4. **1-2 Domain Skills** (e.g., `test-driven-development`, `windows-shell-reliability`, or `quant-analyst`)
5. **1 Validator/Auditor** (e.g., `validator-build-test-agent` or `systematic-debugging`)
6. **1 Reviewer** (e.g., `acceptance-reviewer-product-qa` or `opposition-reviewer`)
7. **1 Closer** (e.g., `completion-auditor` or `documentation-handoff-agent`)

*Total context load: ≤ 8 skills.*
