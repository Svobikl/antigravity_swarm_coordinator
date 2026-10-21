#!/usr/bin/env python3
"""Curate and synchronize the Antigravity Multi-Domain Golden Skill Catalog (200 skills).

Eliminates duplicate, overlapping, placeholder, and foreign-language bloat across:
  - ~/.gemini/config/skills
  - ~/.gemini/antigravity-ide/skills
  - ~/.agents/skills

Normalizes YAML frontmatter (strips UTF-8 BOM and enforces single-line descriptions <= 120 chars)
so Antigravity IDE loads 100% of the catalog without context-budget truncation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

GOLDEN_CATALOG: dict[str, str] = {
    # === 1. Swarm Coordinator, ASW & Obsidian Memory Core (43 skills) ===
    "swarm-coordinator": "Global orchestration lead enforcing Mode 0-5 routing, Tri-Model gates, and verification.",
    "skill-router": "Selects a bounded active skill set (max 8 skills) from the catalog per leaf task.",
    "program-state-controller": "Manages Mode 5 control-plane files, task graphs, requirement ledgers, and state transitions.",
    "spec-product-analyst": "Translates user goals into precise, testable requirements, acceptance criteria, and non-goals.",
    "software-architect": "Designs system architecture, component boundaries, interfaces, and implementation plans.",
    "ui-ux-designer": "Specifies user workflows, layout hierarchy, and complete interactive UI state spaces.",
    "implementation-developer": "Executes bounded production code diffs under a decision-complete task contract.",
    "interaction-e2e-tester": "Verifies realistic end-to-end user and system workflows across real runtime surfaces.",
    "validator-build-test-agent": "Discovers repository-native commands and runs static, unit, and build verification gates.",
    "compliance-maintainability-reviewer": "Audits code conventions, maintainability, blast radius, and architectural boundaries.",
    "opposition-reviewer": "Adversarial Claude Opus 5.5 reviewer falsifying plans, diffs, edge cases, and test proofs.",
    "acceptance-reviewer-product-qa": "Verifies delivered behavior against every user requirement with direct runtime evidence.",
    "security-reliability-reviewer": "Audits trust boundaries, authentication, secrets, and runtime failure resilience.",
    "research-experiment-auditor": "Enforces out-of-sample evaluation, fold safety, and anti-leakage in quant/ML research.",
    "memory-state-curator": "Synchronizes verified architectural knowledge and recaps with the Obsidian vault.",
    "completion-auditor": "Performs final mechanical closure, stub scans, and 3-layer evidence audits before sign-off.",
    "documentation-handoff-agent": "Audits READMEs, ADRs, and handoff documentation against verified runtime behavior.",
    "invariant-auditor": "Verifies Mode 5 semantic invariants (PROGRAM_INVARIANTS.json) and blocks silent overrides.",
    "report-consistency-auditor": "Audits final reports and metrics against METRIC_REGISTRY.json and raw disk evidence.",
    "research-validity-auditor": "Audits experimental methodology, baseline fairness, and statistical validity in research.",
    "semantic-completion-auditor": "Verifies semantic goal achievement without post-hoc threshold relaxation or scope drift.",
    "asw": "Antigravity Swarm execution loop for evidence-driven TDD, subagents, and real-surface QA.",
    "asw-cleanup": "Removes AI clutter and temporary QA artifacts without altering runtime behavior.",
    "asw-comment-check": "Enforces high-signal comment and docstring hygiene across modified files.",
    "asw-debug": "Hypothesis-driven debugging workflow for crashes, hangs, wrong output, and runtime drift.",
    "asw-goal": "Runs persistent goal-driven execution loops until all verifiable stop criteria pass.",
    "asw-harness-adapt": "Executes Harness2 recursive Propose-Probe-Compose-Select-Reflect adaptation sweeps.",
    "asw-loop": "Executes strict RED-to-GREEN-to-Real-Surface QA implementation waves with cleanup receipts.",
    "asw-lsp": "Runs language-server diagnostics and symbol-safety checks before and after code edits.",
    "asw-plan": "Generates decision-complete implementation plans audited by the Claude Opus 5.5 gate.",
    "asw-programming": "Enforces strict engineering discipline across Python, TypeScript, Go, Rust, and C/C++.",
    "asw-refactor": "Performs behavior-preserving structural refactoring backed by regression tests.",
    "asw-remove-ai-slops": "Detects and strips AI-generated boilerplate and redundant defensive code smells.",
    "asw-review": "Reviews diffs, test evidence, hooks, packaging, and real-surface QA transcripts.",
    "asw-rules": "Loads and enforces project-level rules and instruction precedence hierarchies.",
    "asw-start-work": "Executes approved .asw/plans checklists wave-by-wave with persistent state tracking.",
    "asw-test-gui": "On-demand physical GUI and localhost Playwright verification for web, native, and mobile apps.",
    "asw-ui-ux": "Product-grade frontend UI/UX and README visual presentation workflow for ASW deliveries.",
    "obs-memory": "Orients sessions, queries project notes, and records recaps in the Obsidian Knowledge Vault.",
    "agent-memory": "Persistent hybrid knowledge and episodic memory patterns for autonomous agents.",
    "agent-memory-mcp": "Integrates Model Context Protocol memory tools with persistent agent knowledge graphs.",
    "obsidian-markdown": "Creates and edits Obsidian Flavored Markdown with wikilinks, callouts, and frontmatter.",
    "obsidian-cli": "Executes Obsidian vault queries, note operations, and index maintenance from the CLI.",
    "obsidian-bases": "Creates and manages Obsidian Bases (.base files) with structured views and formulas.",

    # === 2. Legal, Contracts, GDPR, Compliance & Regulatory (9 skills) ===
    "lex": "Cross-jurisdictional legal analysis (EU, US, CA) and commercial contract scaffolding.",
    "legal-advisor": "Drafts and reviews legal agreements, terms of service, NDAs, and liability clauses.",
    "employment-contract-templates": "Scaffolds employment, contractor, IP assignment, and confidentiality agreements.",
    "gdpr-data-handling": "Audits and designs EU GDPR data processing, consent, retention, and DSR workflows.",
    "privacy-by-design": "Embeds data minimization, anonymization, and PII protection into system architecture.",
    "pci-compliance": "Enforces PCI-DSS security controls for payment processing and cardholder data.",
    "fda-medtech-compliance-auditor": "Audits medical device and hardware/software systems against FDA and ISO 13485 rules.",
    "customs-trade-compliance": "Manages international trade, HS tariff classification, customs, and export compliance.",
    "security-compliance-compliance-check": "Audits systems against SOC 2, ISO 27001, HIPAA, and CIS compliance frameworks.",

    # === 3. Presentations, Slides, Office Documents & Diagrams (13 skills) ===
    "pptx-official": "Creates, edits, and formats professional PowerPoint (.pptx) presentations and slide decks.",
    "pptx-deck-creation": "Structures executive pitch decks, board presentations, and persuasive slide narratives.",
    "frontend-slides": "Builds animation-rich HTML/web presentations and converts PowerPoint decks to web slides.",
    "docx-official": "Creates, reads, edits, and styles Microsoft Word (.docx) documents and reports.",
    "xlsx-official": "Builds, edits, and audits Excel (.xlsx) spreadsheets, formulas, and financial models.",
    "pdf-official": "Extracts, merges, splits, fills forms, and generates production PDF documents.",
    "document-extraction": "Extracts structured tables, text, and metadata from complex PDFs, scans, and Office files.",
    "writer": "Automates document creation, mail merge, and ODT/DOCX/PDF conversion with LibreOffice Writer.",
    "calc": "Automates spreadsheet formulas and ODS/XLSX/CSV conversion with LibreOffice Calc.",
    "mermaid-expert": "Creates valid Mermaid flowcharts, sequence, state, class, and ER architecture diagrams.",
    "c4-container": "Documents software systems using C4 Context, Container, and Component architecture diagrams.",
    "data-storytelling": "Transforms analytical data into clear executive narratives, charts, and decision memos.",
    "professional-proofreader": "Polishes technical, business, and legal prose for grammar, clarity, and executive tone.",

    # === 4. Project, Product, Strategy, Business & Hardware Sourcing (17 skills) ===
    "product-manager-toolkit": "End-to-end product management toolkit for PRDs, discovery, prioritization, and roadmaps.",
    "concise-planning": "Breaks complex initiatives into clear, atomic, dependency-ordered action checklists.",
    "planning-with-files": "Maintains persistent on-disk working plans, progress logs, and decision checkpoints.",
    "brain-to-docs": "Interviews stakeholders to turn project vision into structured READMEs and ADR docs.",
    "architecture-decision-records": "Authors and maintains formal Architecture Decision Records (ADRs) for technical trade-offs.",
    "osterwalder-canvas-architect": "Designs Business Model Canvases and Value Proposition Canvases using Osterwalder's framework.",
    "kotler-macro-analyzer": "Conducts strategic PESTEL, SWOT, and Five Forces market audits using Kotler's methodology.",
    "moatmri": "Analyzes competitive moat exposure, AI disruption risk, and 90-day defensive action plans.",
    "market-sizing-analysis": "Calculates top-down and bottom-up TAM, SAM, and SOM market sizing models.",
    "startup-financial-modeling": "Builds P&L projections, cash-flow models, unit economics (LTV/CAC), and runway scenarios.",
    "kpi-dashboard-design": "Designs executive KPI hierarchies, North Star metrics, and operational dashboards.",
    "pricing-strategy": "Designs tiered SaaS, hardware, usage-based, and enterprise B2B pricing models.",
    "launch-strategy": "Plans go-to-market product launches, positioning, channels, and rollout milestones.",
    "linear-claude-skill": "Manages Linear issues, cycles, projects, and roadmaps for engineering and product teams.",
    "github": "Operates GitHub issues, pull requests, releases, and Actions workflows via the gh CLI.",
    "inventory-demand-planning": "Forecasts inventory demand, safety stock, reorder points, and supply-chain lead times.",
    "electronics-sourcing": "Sources electronic components, compares distributor stock/pricing, and audits hardware BOMs.",

    # === 5. Marketing, SEO, GEO, Copywriting, CRO & Growth (14 skills) ===
    "marketing-plan": "Builds full-funnel B2B and B2C marketing plans, positioning, messaging, and channel budgets.",
    "content-creator": "Develops brand voice guidelines, editorial calendars, and multi-platform marketing content.",
    "copywriting": "Writes high-converting headlines, landing pages, value propositions, and product copy.",
    "page-cro": "Audits and optimizes landing pages and web funnels to maximize conversion rates.",
    "signup-flow-cro": "Optimizes user onboarding, registration forms, and activation funnels to reduce drop-off.",
    "seo-audit": "Diagnoses technical SEO, crawlability, indexation, Core Web Vitals, and ranking bottlenecks.",
    "seo-fundamentals": "Applies core on-page SEO, keyword architecture, internal linking, and content structure.",
    "geo-fundamentals": "Optimizes content for AI search engines (ChatGPT, Perplexity, Claude, Google AI Overviews).",
    "schema-markup": "Designs and validates Schema.org JSON-LD structured data for rich search results.",
    "competitor-analysis": "Maps competitor positioning, feature matrices, pricing, and differentiation gaps.",
    "customer-research": "Synthesizes user interviews, ICP profiles, jobs-to-be-done, and buyer pain points.",
    "email-sequence": "Designs lifecycle onboarding, nurture, retention, and B2B outbound email sequences.",
    "analytics-tracking": "Designs reliable product and marketing event taxonomies across GA4, PostHog, and Segment.",

    # === 6. UI/UX, Frontend, Web, 3D & Mobile Design (18 skills) ===
    "frontend-design": "Designs distinctive, production-grade web interfaces with strong typography and layout.",
    "ui-ux-pro-max": "Comprehensive UI/UX design system patterns for modern web and mobile applications.",
    "web-design-guidelines": "Audits web interfaces against usability, layout, responsive, and interaction best practices.",
    "ux-audit": "Evaluates screens against Nielsen usability heuristics and modern UX patterns.",
    "ux-flow": "Designs intuitive multi-step user journeys, navigation trees, and state transitions.",
    "ui-a11y": "Audits and fixes WCAG 2.1 AA accessibility, keyboard navigation, ARIA, and contrast issues.",
    "design-system": "Architects scalable design tokens, theming, and reusable UI component primitives.",
    "tailwind-design-system": "Builds maintainable design systems and responsive layouts with Tailwind CSS v4.",
    "shadcn": "Implements accessible React UI components using shadcn/ui and Radix primitives.",
    "react-patterns": "Applies modern React 18/19 hooks, composition, state management, and performance patterns.",
    "nextjs-best-practices": "Builds Next.js App Router applications with Server Components, caching, and streaming.",
    "3d-ui": "Implements spatial 3D web interfaces, perspective effects, and interactive 3D scenes.",
    "threejs-skills": "Builds Three.js 3D scenes, shaders, lighting, materials, loaders, and post-processing.",
    "animejs-animation": "Creates smooth, high-performance JavaScript and SVG motion animations with Anime.js.",
    "remotion-best-practices": "Generates programmatic walkthrough and marketing videos in React using Remotion.",
    "claude-d3js-skill": "Builds bespoke, interactive data visualizations and charts using D3.js.",
    "mobile-design": "Applies mobile-first, touch-ergonomic UI patterns for iOS and Android applications.",
    "hig-foundations": "Applies Apple Human Interface Guidelines for layout, typography, color, and navigation.",

    # === 7. Software Engineering, Languages, Frameworks, Embedded & Odoo ERP (39 skills) ===
    "odoo-module-developer": "Develops custom Odoo 17/18 modules with clean manifests, models, views, and controllers.",
    "odoo-orm-expert": "Masters Odoo ORM models, domains, computed fields, constraints, and recordset performance.",
    "odoo-xml-views-builder": "Builds Odoo form, list, kanban, search, calendar, and pivot XML views and actions.",
    "odoo-qweb-templates": "Creates Odoo QWeb PDF reports, portal pages, and website templates.",
    "odoo-security-rules": "Configures Odoo security groups, ir.model.access.csv permissions, and record rules.",
    "odoo-rpc-api": "Integrates external systems with Odoo via XML-RPC, JSON-RPC, and REST controllers.",
    "odoo-accounting-setup": "Configures Odoo chart of accounts, journals, taxes, fiscal positions, and invoicing.",
    "odoo-docker-deployment": "Deploys and tunes production Odoo instances with Docker, PostgreSQL, and Nginx.",
    "odoo-upgrade-advisor": "Plans and executes Odoo version migrations, schema upgrades, and module compatibility fixes.",
    "firmware-analyst": "Analyzes embedded systems firmware, RTOS behavior, IoT security, and hardware interfaces.",
    "arm-cortex-expert": "Programs bare-metal and RTOS firmware for ARM Cortex-M/A microcontrollers and peripherals.",
    "c-pro": "Writes safe, deterministic C code with strict memory management and embedded discipline.",
    "cpp-pro": "Writes modern C++20/23 systems code with RAII, templates, concurrency, and zero-overhead design.",
    "rust-pro": "Masters Rust 1.75+ ownership, async/Tokio, type safety, and systems/embedded programming.",
    "protocol-reverse-engineering": "Analyzes and decodes binary, serial, network, and hardware communication protocols.",
    "python-pro": "Writes idiomatic Python 3.12+ with strict typing, async concurrency, and clean packaging.",
    "fastapi-pro": "Builds high-performance async REST APIs with FastAPI, Pydantic v2, and SQLAlchemy 2.0.",
    "django-pro": "Builds scalable Django and Django REST Framework backends with optimized ORM queries.",
    "pydantic-models-py": "Designs strict Pydantic v2 validation schemas and multi-model API contracts.",
    "typescript-pro": "Masters advanced TypeScript types, generics, discriminated unions, and full-stack safety.",
    "nodejs-backend-patterns": "Architects resilient Node.js backend services, middleware, queues, and error handling.",
    "golang-pro": "Writes concurrent, production-ready Go services, CLIs, and gRPC/HTTP microservices.",
    "csharp-pro": "Builds modern .NET 8+ and C# backends, EF Core data layers, and desktop services.",
    "java-pro": "Builds modern Java 21+ and Spring Boot applications with virtual threads and clean DDD.",
    "php-pro": "Writes modern PHP 8.3+ applications with strict typing, Laravel/Symfony, and PSR standards.",
    "sql-pro": "Writes optimized SQL queries, CTEs, window functions, and indexing strategies.",
    "postgres-best-practices": "Optimizes PostgreSQL schemas, query plans, indexing, partitioning, and connection pooling.",
    "drizzle-orm-expert": "Designs type-safe SQL schemas, relational queries, and migrations with Drizzle ORM.",
    "prisma-expert": "Manages Prisma ORM schemas, migrations, relations, and query performance in TypeScript.",
    "graphql-architect": "Designs GraphQL schemas, resolvers, DataLoader batching, and federated APIs.",
    "zustand-store-ts": "Implements typed, modular React state stores and middleware using Zustand.",
    "flutter-expert": "Builds multi-platform mobile and desktop apps with Flutter and Dart 3.",
    "react-native-architecture": "Architects production React Native and Expo mobile apps with native performance.",
    "swiftui-expert-skill": "Builds modern iOS and macOS apps using SwiftUI, Swift Concurrency, and Observation.",
    "electron-development": "Builds secure, cross-platform desktop applications with Electron and IPC isolation.",
    "senior-architect": "Designs scalable distributed systems, service boundaries, caching, and event architectures.",
    "domain-driven-design": "Applies strategic and tactical Domain-Driven Design (bounded contexts, aggregates, events).",
    "code-reviewer": "Performs deep technical code reviews for correctness, maintainability, and edge cases.",
    "simplify-code": "Simplifies complex code paths and removes duplication while preserving exact behavior.",

    # === 8. Data Science, AI/LLM Engineering, Quant & Scientific Research (20 skills) ===
    "quant-analyst": "Develops quantitative finance models, alpha signals, factor analysis, and portfolio optimization.",
    "backtesting-frameworks": "Builds leakage-free vectorized and event-driven quantitative trading backtests.",
    "risk-metrics-calculation": "Calculates portfolio VaR, CVaR, Sharpe, Sortino, drawdown, and tail-risk metrics.",
    "data-scientist": "Conducts statistical analysis, hypothesis testing, feature engineering, and modeling.",
    "data-engineer": "Builds reliable batch and streaming ETL/ELT data pipelines and warehouse schemas.",
    "polars": "Processes large tabular datasets at high speed using Polars lazy and eager DataFrames.",
    "scikit-learn": "Builds fold-safe classical machine learning pipelines, cross-validation, and ensembles.",
    "statsmodels": "Fits econometric regressions, ARIMA/GARCH time-series models, and statistical tests.",
    "matplotlib": "Creates publication-quality static and multi-panel scientific plots in Python.",
    "plotly": "Builds interactive financial, scientific, and dashboard visualizations with Plotly.",
    "ml-pipeline-workflow": "Orchestrates end-to-end MLOps data preparation, training, evaluation, and deployment.",
    "ai-agents-architect": "Designs tool-using autonomous AI agents, memory hierarchies, and orchestration loops.",
    "rag-engineer": "Builds hybrid retrieval-augmented generation pipelines with chunking and reranking.",
    "embedding-strategies": "Selects, tunes, and evaluates vector embedding models and similarity search indices.",
    "prompt-engineer": "Designs structured system prompts, few-shot schemas, and deterministic LLM evaluations.",
    "gemini-api-dev": "Builds multimodal and agentic applications using the official Google GenAI SDK.",
    "claude-api": "Builds tool-using and streaming applications with the Anthropic Claude API and SDK.",
    "mcp-builder": "Designs and implements Model Context Protocol (MCP) servers and typed tool interfaces.",
    "deep-research": "Executes multi-step autonomous web and literature research with cited synthesis reports.",
    "ii-commons": "Searches arXiv, PubMed, and policy corpora with deterministic freshness cutoffs.",

    # === 9. Testing, Debugging, DevOps, Cloud, Security & Shell Tooling (27 skills) ===
    "systematic-debugging": "Isolates root causes systematically before proposing fixes for bugs or test failures.",
    "test-driven-development": "Enforces strict RED-GREEN-REFACTOR test-driven development for features and bugfixes.",
    "test-guard": "Audits test suites for tautologies, brittle mocks, missing negative cases, and flakiness.",
    "playwright-skill": "Writes reliable end-to-end browser tests and web automation scripts with Playwright.",
    "browser-harness": "Drives live Chrome sessions via CDP for authenticated and visual web verification.",
    "pytest-skill": "Authors clean Python pytest suites with fixtures, parametrization, and coverage checks.",
    "vitest-skill": "Authors fast TypeScript and React unit/integration tests using Vitest.",
    "api-security-best-practices": "Hardens REST and GraphQL APIs against OWASP Top 10, auth bypass, and injection flaws.",
    "security-auditor": "Performs comprehensive DevSecOps, dependency, and application security vulnerability audits.",
    "differential-review": "Performs security-focused differential review of commits, PRs, and attack surfaces.",
    "secrets-management": "Implements secure credential storage, env-var hygiene, and secret rotation workflows.",
    "docker-expert": "Authors optimized multi-stage Dockerfiles, Compose stacks, and hardened containers.",
    "kubernetes-architect": "Designs production Kubernetes manifests, Helm charts, ingress, and GitOps deployments.",
    "terraform-skill": "Writes modular, state-safe Terraform Infrastructure as Code across cloud providers.",
    "aws-skills": "Architects and operates AWS cloud infrastructure, IAM policies, and serverless services.",
    "cloudflare": "Develops and deploys on Cloudflare Workers, Pages, D1, R2, and Zero Trust.",
    "vercel-deployment": "Configures, optimizes, and deploys Next.js and web applications on Vercel.",
    "supabase": "Builds full-stack apps with Supabase Postgres, Row-Level Security, Auth, and Edge Functions.",
    "github-actions-templates": "Builds fast, cached GitHub Actions CI/CD test, build, and release pipelines.",
    "grafana-dashboards": "Designs Prometheus metrics and production Grafana observability dashboards.",
    "vps-server-management": "Manages Linux VPS servers, SSH hardening, systemd services, and reverse proxies.",
    "powershell-windows": "Writes reliable Windows PowerShell scripts avoiding operator, quoting, and encoding pitfalls.",
    "windows-shell-reliability": "Handles Windows path normalization, UTF-8 encoding, and binary execution safely.",
    "bash-pro": "Writes defensive POSIX and Bash scripts with strict error handling and quoting.",
    "jq": "Filters, transforms, and queries JSON streams and config files from the command line.",
    "git-advanced-workflows": "Executes safe Git rebases, worktrees, bisect debugging, and clean branch workflows.",
    "resolving-merge-conflicts": "Resolves complex Git merge and rebase conflicts while preserving both sides' intent.",
}


def _remove_readonly(func, path, _excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def normalize_skill_frontmatter(skill_md: Path, skill_name: str, concise_desc: str) -> None:
    """Strip UTF-8 BOM and enforce clean single-line YAML frontmatter with description <= 120 chars."""
    raw = skill_md.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    txt = raw.decode("utf-8", errors="replace")
    m = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$", txt, re.S)
    if m:
        body = m.group(2).lstrip("\r\n")
    else:
        body = txt.lstrip("\r\n")

    clean_frontmatter = (
        f"---\n"
        f"name: {skill_name}\n"
        f"description: {concise_desc}\n"
        f"---\n\n"
    )
    skill_md.write_text(clean_frontmatter + body, encoding="utf-8", newline="\n")


def curate_catalog(*, dry_run: bool = False) -> dict[str, object]:
    if len(GOLDEN_CATALOG) != 200:
        raise ValueError(f"GOLDEN_CATALOG must have exactly 200 skills, got {len(GOLDEN_CATALOG)}")

    home = Path.home()
    cfg_dir = home / ".gemini" / "config" / "skills"
    ide_dir = home / ".gemini" / "antigravity-ide" / "skills"
    ag_dir = home / ".agents" / "skills"
    repo_root = Path(__file__).resolve().parents[2]
    local_dir = repo_root / "core_framework" / "skills"
    repo_skill_roots = (
        local_dir,
        repo_root / ".antigravity" / "skills",
        repo_root / "plugins" / "antigravity-swarm" / "skills",
    )

    # Step 1: Promote any Golden skills that currently live only in ide_dir or ag_dir into cfg_dir
    promoted: list[str] = []
    for name in sorted(GOLDEN_CATALOG):
        target = cfg_dir / name
        if not (target / "SKILL.md").exists():
            for donor_root in (ide_dir, ag_dir, local_dir):
                donor = donor_root / name
                if (donor / "SKILL.md").exists():
                    if not dry_run:
                        if target.exists():
                            shutil.rmtree(target, onerror=_remove_readonly)
                        shutil.copytree(donor, target)
                    promoted.append(f"{name} (from {donor_root.name})")
                    break

    # Step 2: Delete all non-Golden skill directories from cfg_dir, ide_dir, and ag_dir
    removed_counts = {"cfg": 0, "ide": 0, "ag": 0}
    for label, root in (("cfg", cfg_dir), ("ide", ide_dir), ("ag", ag_dir)):
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            if d.name not in GOLDEN_CATALOG:
                if not dry_run:
                    shutil.rmtree(d, onerror=_remove_readonly)
                removed_counts[label] += 1

    # Step 3: Normalize YAML frontmatter (no BOM + concise single-line description) in cfg_dir and local_dir
    if not dry_run:
        for name, desc in sorted(GOLDEN_CATALOG.items()):
            skill_md = cfg_dir / name / "SKILL.md"
            if not skill_md.exists():
                raise FileNotFoundError(f"Golden skill missing SKILL.md: {skill_md}")
            normalize_skill_frontmatter(skill_md, name, desc)
            for r_root in repo_skill_roots:
                local_md = r_root / name / "SKILL.md"
                if local_md.exists():
                    normalize_skill_frontmatter(local_md, name, desc)

        # Step 4: Synchronize all 200 normalized skills from cfg_dir into ide_dir and ag_dir
        for mirror_root in (ide_dir, ag_dir):
            mirror_root.mkdir(parents=True, exist_ok=True)
            for name in sorted(GOLDEN_CATALOG):
                src = cfg_dir / name
                dst = mirror_root / name
                if dst.exists():
                    shutil.rmtree(dst, onerror=_remove_readonly)
                shutil.copytree(src, dst)

    return {
        "golden_target": len(GOLDEN_CATALOG),
        "promoted": promoted,
        "removed_counts": removed_counts,
        "remaining_cfg": len([d for d in cfg_dir.iterdir() if d.is_dir()]) if cfg_dir.exists() else 0,
        "remaining_ide": len([d for d in ide_dir.iterdir() if d.is_dir()]) if ide_dir.exists() else 0,
        "remaining_ag": len([d for d in ag_dir.iterdir() if d.is_dir()]) if ag_dir.exists() else 0,
    }


def verify_catalog() -> dict[str, object]:
    home = Path.home()
    cfg_dir = home / ".gemini" / "config" / "skills"
    ide_dir = home / ".gemini" / "antigravity-ide" / "skills"
    ag_dir = home / ".agents" / "skills"

    cfg_names = {d.name for d in cfg_dir.iterdir() if d.is_dir()}
    ide_names = {d.name for d in ide_dir.iterdir() if d.is_dir()}
    ag_names = {d.name for d in ag_dir.iterdir() if d.is_dir()}

    bom_count = 0
    max_desc_len = 0
    total_header_chars = 0
    for name in sorted(cfg_names):
        f = cfg_dir / name / "SKILL.md"
        raw = f.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            bom_count += 1
        txt = raw.decode("utf-8", errors="replace")
        m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
        desc = ""
        if m:
            for line in m.group(1).splitlines():
                if line.strip().startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
        max_desc_len = max(max_desc_len, len(desc))
        total_header_chars += len(f"- {name} ({f}): {desc}\n")

    ok = (
        cfg_names == set(GOLDEN_CATALOG)
        and ide_names == set(GOLDEN_CATALOG)
        and ag_names == set(GOLDEN_CATALOG)
        and bom_count == 0
        and max_desc_len <= 120
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "cfg_count": len(cfg_names),
        "ide_count": len(ide_names),
        "ag_count": len(ag_names),
        "bom_count": bom_count,
        "max_desc_len": max_desc_len,
        "estimated_header_chars": total_header_chars,
        "estimated_header_tokens": total_header_chars // 4,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Curate and verify the Antigravity 200-skill Golden Catalog.")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without modifying files.")
    parser.add_argument("--verify", action="store_true", help="Verify the curated catalog state.")
    args = parser.parse_args()

    if args.verify:
        res = verify_catalog()
        print(json.dumps(res, indent=2))
        return 0 if res["status"] == "PASS" else 1

    res = curate_catalog(dry_run=args.dry_run)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
