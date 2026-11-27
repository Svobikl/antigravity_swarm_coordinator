#!/usr/bin/env python3
"""System 1 Local Decision Model (Laya) Integration for Autonomous Routing & Triage.

Provides sub-40ms bounded routing decisions (Mode 0-5 classification, Quad-Model tier
routing, UI verification detection, active skill budget selection, and review triage)
using the local NandhaKishorM/laya engine or zero-latency (< 5ms) calibrated bilingual (CZ/EN) fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_DECISION_CONFIG: dict[str, object] = {
    "enabled": True,
    "prefer_gpu": True,
    "min_free_vram_mib": 2048,
    "min_total_vram_mib": 4096,
    "cpu_threads": 12,
    "flush_denormal": True,
    "preferred_checkpoint": "multilingual",
    "compact_question_schema": True,
    "use_local_snapshot_fastload": True,
}


def get_decision_config_path(target_dir: Path | None = None) -> Path:
    """Resolve the path for decision_config.json."""
    if target_dir:
        return target_dir / "decision_config.json"
    workspace_cfg = Path.cwd() / ".antigravity" / "decision_config.json"
    if workspace_cfg.parent.is_dir():
        return workspace_cfg
    global_cfg = Path.home() / ".gemini" / "decision_config.json"
    return global_cfg


def load_decision_config() -> dict[str, object]:
    """Load decision configuration from disk and environment variables."""
    cfg = dict(DEFAULT_DECISION_CONFIG)
    # Layered merge: global defaults first, then workspace overrides.
    candidates = [
        Path.home() / ".gemini" / ".antigravity" / "decision_config.json",
        Path.home() / ".gemini" / "decision_config.json",
        Path(__file__).resolve().parent.parent / "decision_config.json",
        Path.cwd() / ".antigravity" / "decision_config.json",
    ]
    seen: set[Path] = set()
    for c in candidates:
        try:
            resolved = c.resolve()
        except Exception:
            resolved = c
        if resolved in seen:
            continue
        seen.add(resolved)
        if c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception:
                pass

    env_val = os.environ.get("ASW_DECISION_MODEL_ENABLED")
    if env_val is not None:
        s = env_val.strip().lower()
        if s in ("0", "false", "no", "off"):
            cfg["enabled"] = False
        elif s in ("1", "true", "yes", "on"):
            cfg["enabled"] = True

    return cfg


def save_decision_config(updates: dict[str, object], target_path: Path | None = None) -> Path:
    """Save updates to decision_config.json."""
    cfg = load_decision_config()
    cfg.update(updates)
    dest = target_path or get_decision_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    gemini_cfg = Path.home() / ".gemini" / "decision_config.json"
    if dest != gemini_cfg and gemini_cfg.parent.is_dir():
        try:
            gemini_cfg.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass
    return dest


def select_optimal_device(
    *,
    min_free_vram_mib: int = 2048,
    min_total_vram_mib: int = 4096,
    min_compute_cap: float = 7.0,
    nvidia_smi_output: str | None = None,
) -> dict[str, object]:
    """Inspect GPU hardware to select 'cuda' vs 'cpu'.

    Selects 'cuda' ONLY when:
      1. free_vram_mib >= min_free_vram_mib (2048 MiB)
      2. total_vram_mib >= min_total_vram_mib (4096 MiB)
      3. compute_cap >= min_compute_cap (7.0, Volta/Turing/Ampere/Ada/Blackwell)

    On GPUs like GTX 1060 3GB (Pascal compute 6.1, ~600 MiB free, 3072 MiB total),
    automatically selects 'cpu' (max_loaded=1) to prevent CUDA OOM or PCIe thrashing.
    """
    raw_csv = nvidia_smi_output
    if raw_csv is None:
        if platform.system() == "Darwin":
            return {
                "device": "cpu",
                "max_loaded": 1,
                "gpu_name": None,
                "total_vram_mib": None,
                "free_vram_mib": None,
                "compute_cap": None,
                "reason": "darwin_no_nvidia_cuda",
            }
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free,compute_cap",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                raw_csv = res.stdout.strip()
        except Exception:
            raw_csv = None

    if not raw_csv or not raw_csv.strip():
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": None,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "no_cuda_or_smi_failed",
        }

    first_line = raw_csv.strip().splitlines()[0]
    parts = [p.strip() for p in first_line.split(",")]
    if len(parts) < 4:
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": parts[0] if parts else None,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "unrecognized_smi_format",
        }

    gpu_name = parts[0]
    try:
        total_vram = int(float(parts[1]))
        free_vram = int(float(parts[2]))
        compute_cap = float(parts[3])
    except (ValueError, IndexError):
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": gpu_name,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "unrecognized_smi_numbers",
        }

    is_sufficient = (
        free_vram >= min_free_vram_mib
        and total_vram >= min_total_vram_mib
        and compute_cap >= min_compute_cap
    )

    if is_sufficient:
        max_loaded = 2 if total_vram >= 16384 else 1
        return {
            "device": "cuda",
            "max_loaded": max_loaded,
            "gpu_name": gpu_name,
            "total_vram_mib": total_vram,
            "free_vram_mib": free_vram,
            "compute_cap": compute_cap,
            "reason": "sufficient_vram",
        }
    else:
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": gpu_name,
            "total_vram_mib": total_vram,
            "free_vram_mib": free_vram,
            "compute_cap": compute_cap,
            "reason": "insufficient_vram_or_pascal_fp16",
        }


LEGACY_SKILL_CATALOG_KEYWORDS: dict[str, list[str]] = {
    "fastapi-pro": ["fastapi", "uvicorn", "pydantic", "rest api", "endpoint"],
    "playwright-skill": ["playwright", "browser", "e2e", "gui", "web test"],
    "quant-analyst": ["quant", "alpha", "trading", "sharpe", "backtest", "portfolio"],
    "risk-metrics-calculation": ["risk", "var", "cvar", "drawdown", "volatility"],
    "frontend-design": ["frontend", "css", "html", "design", "layout", "vzhled"],
    "react-patterns": ["react", "component", "hook", "jsx", "tsx", "state"],
    "postgres-best-practices": ["postgres", "postgresql", "sql", "migration", "index"],
    "sql-pro": ["sql", "query", "database", "databáze", "schema"],
    "docker-expert": ["docker", "container", "dockerfile", "compose"],
    "odoo-module-developer": ["odoo", "erp", "module", "qweb"],
    "obs-memory": ["obsidian", "vault", "memory", "paměť", "note"],
    "agent-memory": ["agent-memory", "episodic", "recall", "zkušenosti"],
    "ui-ux-designer": ["ui", "ux", "dashboard", "graf", "prohlížeč", "rozhraní"],
    "asw-test-gui": ["asw-test-gui", "gui test", "screen test", "native app"],
    "test-driven-development": ["tdd", "test", "red green", "unit test", "testy"],
    "rtk-token-killer": ["rtk", "token", "cli proxy", "git status", "pytest"],
    "software-architect": ["architect", "architecture", "design", "architektura"],
    "compliance-maintainability-reviewer": ["review", "lint", "compliance", "revize"],
    "opposition-reviewer": ["opus", "opposition", "adversarial", "falsify"],
    "systematic-debugging": ["debug", "crash", "chyba", "hang", "bug", "traceback"],
    "python-pro": ["python", "pytest", "asyncio", "pydantic"],
    "typescript-pro": ["typescript", "ts", "node", "npm"],
    "context-hub": [
        "context-hub", "context hub", "chub", "annotate",
        "stripe", "openai", "anthropic", "supabase", "cloudflare",
        "webhook", "oauth", "graphql", "rest api", "rest client",
        "endpoint", "third-party", "external api", "library docs",
        "api docs", "api", "sdk", "aws",
    ],
}

CORE_SKILL_CATALOG_KEYWORDS: dict[str, list[str]] = {
    "fastapi-pro": ["fastapi", "uvicorn", "pydantic", "rest api", "endpoint", "endpoints"],
    "playwright-skill": ["playwright", "browser", "e2e", "gui", "web test", "web tests", "prohlížeč", "prohlížeči"],
    "quant-analyst": ["quant", "quantitative", "kvantitativní", "alpha", "trading", "sharpe", "backtest", "backtesting", "portfolio"],
    "risk-metrics-calculation": ["risk", "risk metrics", "var", "cvar", "drawdown", "drawdownu", "volatility", "volatilita", "riziko"],
    "frontend-design": ["frontend", "css", "html", "tailwind", "scss", "sass", "layout", "vzhled", "design"],
    "react-patterns": ["react", "jsx", "tsx", "usestate", "useeffect", "redux", "nextjs", "next.js", "component", "components", "hook", "hooks", "komponenta", "komponenty", "state"],
    "postgres-best-practices": ["postgres", "postgresql", "pgvector", "psycopg", "asyncpg", "alembic", "psql", "sql", "migration", "migrations", "migrace", "index", "indexes", "vacuum"],
    "sql-pro": ["sql", "query", "queries", "database", "databáze", "databázi", "schema", "cte", "dotaz", "dotazy"],
    "docker-expert": ["docker", "container", "containers", "kontejner", "kontejnery", "dockerfile", "docker compose", "compose"],
    "odoo-module-developer": ["odoo", "erp", "qweb", "ir.model", "module"],
    "obs-memory": ["obsidian", "vault", "paměť", "paměti", "wikilink", "memory", "note", "notes", "poznámka", "poznámky"],
    "agent-memory": ["agent-memory", "episodic", "recall", "zkušenosti"],
    "ui-ux-designer": ["ui", "ux", "dashboard", "dashboardu", "graf", "grafy", "prohlížeč", "prohlížeči", "rozhraní", "wireframe", "usability"],
    "asw-test-gui": ["asw-test-gui", "gui test", "screen test", "native app"],
    "test-driven-development": ["tdd", "test", "tests", "testing", "red green", "unit test", "unit tests", "testy", "testů", "otestuj"],
    "rtk-token-killer": ["rtk", "rtk-token-killer", "cli proxy", "token reduction", "token killer", "token"],
    "software-architect": ["architect", "architecture", "architektura", "architekturu", "design"],
    "compliance-maintainability-reviewer": ["review", "lint", "linter", "compliance", "revize", "revizi"],
    "opposition-reviewer": ["opus", "opposition", "adversarial", "falsify"],
    "systematic-debugging": ["debug", "debugging", "crash", "pád", "chyba", "chybu", "chyby", "chyb", "hang", "bug", "bugs", "traceback", "ladění"],
    "python-pro": ["python", "pythonu", "pytest", "asyncio", "pydantic"],
    "typescript-pro": ["typescript", "ts", "node", "nodejs", "npm"],
    "context-hub": [
        "context-hub", "context hub", "chub", "annotate",
        "stripe", "openai", "anthropic", "supabase", "cloudflare",
        "webhook", "oauth", "graphql", "rest api", "rest client",
        "endpoint", "third-party", "external api", "library docs",
        "api docs", "sdk docs", "api", "sdk", "aws",
    ],
    "rust-pro": ["rust", "rustu", "cargo", "tokio", "serde", "crate", "crates", "rustc", "clippy", "rustlang", "borrow checker"],
    "golang-pro": ["golang", "go", "goroutine", "goroutines", "go.mod", "go test", "go build", "gopath", "gin-gonic", "go-chi"],
    "cpp-pro": ["c++", "cpp", "cmake", "raii", "std::", "clang", "g++", "msvc", "c++20", "c++23", "c++17", "vcpkg", "conan"],
    "kubernetes-architect": ["kubernetes", "k8s", "helm", "kubectl", "helm chart", "ingress", "argocd", "gitops", "kustomize", "statefulset", "pod", "pods"],
    "terraform-skill": ["terraform", "tfstate", "tfvars", "hcl", "iac", "infrastructure as code", "opentofu", "terraform plan", "terraform apply"],
    "security-auditor": ["security", "vulnerability", "vulnerabilities", "owasp", "cve", "devsecops", "xss", "csrf", "sqli", "sql injection", "penetration", "hardening", "security audit", "bezpečnost", "bezpečnostní", "zranitelnost", "zranitelnosti"],
    "polars": ["polars", "lazyframe", "parquet", "scan_parquet", "pl.dataframe", "dataframe", "dataframes"],
    "pptx-official": ["pptx", "powerpoint", "powerpointu", "pitch deck", "slide deck", "slide", "slides", "prezentace", "prezentaci", "slidy", "slidů"],
    "gdpr-data-handling": ["gdpr", "pii", "anonymization", "anonymize", "anonymizaci", "anonymizace", "osobní údaje", "osobních údajů", "data retention", "dsr", "subject access", "consent", "privacy", "soukromí", "ochrana dat"],
}

SKILL_NEGATIVE_EXAMPLES: dict[str, dict[str, list[str]]] = {
    "react-patterns": {
        "strong_anchors": ["react", "jsx", "tsx", "usestate", "useeffect", "redux", "nextjs", "next.js"],
        "negative_terms": [
            "state machine", "finite state", "stavový automat", "stavový", "automat",
            "state.json", "git", "parser", "parseru", "cli", "daemon", "stop hook",
            "pretooluse", "posttooluse", "webhook", "bash", "python", "pythonu",
        ],
        "ambiguous_only_suppress": ["state", "hook", "hooks", "component", "components", "komponenta", "komponenty"],
    },
    "postgres-best-practices": {
        "strong_anchors": ["postgres", "postgresql", "pgvector", "psycopg", "asyncpg", "alembic", "psql", "sql"],
        "negative_terms": [
            "inverted index", "document search", "full-text search", "bm25",
            "tfidf", "tf-idf", "vector index", "faiss", "hnsw",
            "list index", "array index", "index.html", "index.ts", "index.js", "python",
        ],
        "ambiguous_only_suppress": ["index", "indexes", "migration", "migrations", "migrace"],
    },
    "context-hub": {
        "strong_anchors": [
            "context-hub", "context hub", "chub", "annotate",
            "stripe", "openai", "anthropic", "supabase", "cloudflare",
            "webhook", "oauth", "graphql", "third-party", "external api",
            "library docs", "api docs", "sdk docs",
        ],
        "negative_terms": [
            "local", "src/", "src/api", "routes.py", ".py",
            "refactor", "internal", "fastapi", "terraform", "hcl",
        ],
        "ambiguous_only_suppress": ["api", "sdk", "rest api", "rest client", "endpoint", "aws"],
    },
    "golang-pro": {
        "strong_anchors": ["golang", "goroutine", "goroutines", "go.mod", "go build", "gopath", "gin-gonic", "go-chi"],
        "negative_terms": [
            "go to", "to go", "go back", "go ahead", "go live", "go-live",
            "go through", "go wrong", "go down", "go up", "go on", "go out",
            "go for", "let's go", "lets go", "go check", "goal",
            "go test the", "go test this", "go test it",
        ],
        "ambiguous_only_suppress": ["go", "go test"],
        "require_cue_only_for": ["go"],
        "require_cue_if_only_ambiguous": [
            "cli", "grpc", "microservice", "concurrency", "worker",
            "server", "http", "struct", "channel", "channels",
        ],
    },
    "frontend-design": {
        "strong_anchors": ["frontend", "css", "html", "tailwind", "scss", "sass", "layout", "vzhled"],
        "negative_terms": [
            "system design", "api design", "architecture", "architektura", "architekturu",
            "backend", "backendu", "database", "databáze", "microservice", "cli", "schema",
            "pptx", "powerpoint", "powerpointu", "prezentaci", "prezentace",
        ],
        "ambiguous_only_suppress": ["design"],
    },
    "odoo-module-developer": {
        "strong_anchors": ["odoo", "erp", "qweb", "ir.model"],
        "negative_terms": [
            "python", "typescript", "rust", "golang", "c++", "react",
            "fastapi", "terraform", "hcl", "auth", "node", "npm", "pytest",
        ],
        "ambiguous_only_suppress": ["module"],
    },
    "obs-memory": {
        "strong_anchors": ["obsidian", "vault", "wikilink"],
        "negative_terms": [
            "memory leak", "memory safety", "únik paměti", "alokace paměti", "v paměti",
            "ram", "vram", "heap", "malloc",
            "valgrind", "oom", "out of memory", "buffer", "release note", "release notes",
        ],
        "ambiguous_only_suppress": ["memory", "note", "notes", "paměť", "paměti", "poznámka", "poznámky"],
    },
    "rtk-token-killer": {
        "strong_anchors": ["rtk", "rtk-token-killer", "cli proxy", "token reduction", "token killer"],
        "negative_terms": [
            "jwt", "oauth", "bearer", "csrf", "auth", "authentication",
            "session token", "api key", "refresh token", "access token",
            "commit", "branch",
        ],
        "ambiguous_only_suppress": ["token", "git status"],
    },
    "kubernetes-architect": {
        "strong_anchors": ["kubernetes", "k8s", "helm", "kubectl", "helm chart", "ingress", "argocd", "gitops", "kustomize", "statefulset"],
        "negative_terms": ["pod linux", "pod linuxem", "pod windows", "pod macos", "pod pythonem", "pod tlakem"],
        "ambiguous_only_suppress": ["pod", "pods"],
    },
    "polars": {
        "strong_anchors": ["polars", "lazyframe", "scan_parquet", "pl.dataframe"],
        "negative_terms": ["pandas", "pd.dataframe", "matplotlib", "seaborn"],
        "ambiguous_only_suppress": ["dataframe", "dataframes", "parquet"],
    },
    "pptx-official": {
        "strong_anchors": ["pptx", "powerpoint", "powerpointu", "pitch deck", "slide deck", "prezentace", "prezentaci", "slidy", "slidů"],
        "negative_terms": ["carousel", "slider", "css", "swiper", "frontend"],
        "ambiguous_only_suppress": ["slide", "slides"],
    },
    "gdpr-data-handling": {
        "strong_anchors": ["gdpr", "pii", "anonymization", "anonymize", "anonymizaci", "anonymizace", "osobní údaje", "osobních údajů", "data retention", "dsr", "subject access"],
        "negative_terms": ["private repo", "private key", "private method"],
        "ambiguous_only_suppress": ["consent", "privacy"],
    },
}

_WORD_CHAR_RE = re.compile(r"[a-z0-9_\u00c0-\u024f]")
_COMPILED_TERM_PATTERNS: dict[str, re.Pattern[str]] = {}


def _compile_term_pattern(term: str) -> re.Pattern[str]:
    cached = _COMPILED_TERM_PATTERNS.get(term)
    if cached is not None:
        return cached
    prefix = r"(?<![a-z0-9_\u00c0-\u024f])" if term and _WORD_CHAR_RE.match(term[0]) else ""
    if term.endswith("+"):
        suffix = r"(?![a-z_])"
    elif term.endswith(":"):
        suffix = ""
    elif term and _WORD_CHAR_RE.match(term[-1]):
        suffix = r"(?![a-z0-9_\u00c0-\u024f])"
    else:
        suffix = ""
    pat = re.compile(f"{prefix}{re.escape(term)}{suffix}")
    _COMPILED_TERM_PATTERNS[term] = pat
    return pat


def _matches_term(term: str, lower_text: str) -> bool:
    return _compile_term_pattern(term).search(lower_text) is not None


def _legacy_select_skills(text: str, max_skills: int = 8) -> list[str]:
    """Exact snapshot of the legacy substring skill selector for before-vs-after benchmarking."""
    max_skills = min(max(max_skills, 1), 8)
    if not text or not isinstance(text, str) or not text.strip():
        return CORE_FALLBACK_SKILLS[: min(4, max_skills)]

    lower = text.lower()
    scored: list[tuple[str, int]] = []
    for skill_name, keywords in LEGACY_SKILL_CATALOG_KEYWORDS.items():
        if skill_name == "context-hub":
            matches = sum(
                1
                for kw in keywords
                if (
                    re.search(rf"\b{re.escape(kw)}s?\b", lower)
                    if len(kw) <= 3
                    else kw in lower
                )
            )
        else:
            matches = sum(1 for kw in keywords if kw in lower)
        if matches > 0:
            scored.append((skill_name, matches))

    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [s[0] for s in scored[:max_skills]]
    if not selected:
        return CORE_FALLBACK_SKILLS[: min(4, max_skills)]
    return selected

CORE_FALLBACK_SKILLS = [
    "swarm-coordinator",
    "skill-router",
    "implementation-developer",
    "validator-build-test-agent",
]

_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_DOUBLE_QUOTE_RE = re.compile(r'"(?:\\.|[^"\\\r\n])*"')
_CZ_QUOTE_RE = re.compile(r"\u201e[^\u201c\u201d\r\n]*[\u201c\u201d]")
_CURLY_DOUBLE_QUOTE_RE = re.compile(r"\u201c[^\u201d\r\n]*\u201d")
_SINGLE_QUOTE_RE = re.compile(
    r"(?<![A-Za-z0-9_\u00c0-\u024f])'(?:\\.|(?<=[A-Za-z0-9_\u00c0-\u024f])'(?=[A-Za-z0-9_\u00c0-\u024f])|[^'\\\r\n])*?'(?![A-Za-z0-9_\u00c0-\u024f])"
)
_CURLY_SINGLE_QUOTE_RE = re.compile(
    r"(?<![A-Za-z0-9_\u00c0-\u024f])\u2018(?:\\.|(?<=[A-Za-z0-9_\u00c0-\u024f])\u2019(?=[A-Za-z0-9_\u00c0-\u024f])|[^\u2019\\\r\n])*?\u2019(?![A-Za-z0-9_\u00c0-\u024f])"
)

_PATH_OR_FILE_RE = re.compile(
    r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|\b[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,6}\b)"
)

_LEADING_SLASH_CMD_RE = re.compile(
    r"^\s*/?(asw-plan|asw-clarify|asw-test-gui|asw-start-work|start-work|asw-review|asw-goal|asw-cleanup|asw-loop|asw)(?![A-Za-z0-9_/-])",
    re.IGNORECASE,
)
_ANY_SLASH_CMD_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])/(asw-plan|asw-clarify|asw-test-gui|asw-start-work|start-work|asw-review|asw-goal|asw-cleanup|asw-loop|asw)(?![A-Za-z0-9_/-])",
    re.IGNORECASE,
)
_TEST_GUI_MODIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])/?(?:asw-test-gui|swarmwork-test-gui)(?![A-Za-z0-9_/-])",
    re.IGNORECASE,
)

_QUESTION_START_PATTERNS = (
    r"^\s*co\s+d[eě]l[aá]\b",
    r"^\s*co\s+je\b",
    r"^\s*co\s+znamen[aá]\b",
    r"^\s*jak\s+funguj[eí]\b",
    r"^\s*vysv[eě]tli\b",
    r"^\s*kde\s+je\b",
    r"^\s*pro[cč]\b",
    r"^\s*nen[ií]\s+to\s+[sš]koda\b",
    r"^\s*pou[zž][ií]v[aá]\b",
    r"^\s*m[uů][zž]u\b",
    r"^\s*je\s+lep[sš][ií]\b",
    r"^\s*what\s+is\b",
    r"^\s*what\s+are\b",
    r"^\s*how\s+does\b",
    r"^\s*how\s+do\b",
    r"^\s*explain\b",
    r"^\s*where\s+is\b",
    r"^\s*tell\s+me\b",
    r"^\s*why\b",
    r"^\s*does\b",
    r"^\s*is\s+it\b",
    r"^\s*can\s+i\b",
    r"^\s*should\s+i\b",
)

_STRONG_ACTION_VERBS = (
    "implement", "build", "add", "create", "design", "refactor", "integrate",
    "develop", "write", "fix", "repair", "patch", "modify", "update", "edit",
    "verify", "split", "extract", "rename", "clean", "cleanup", "remove", "delete",
    "improve", "enhance", "polish", "deploy", "setup", "configure", "migrate",
    "port", "solve", "resolve", "generate", "scaffold", "animate", "convert",
    "redraw", "render",
    "uprav", "upravit", "přidej", "pridej", "přidat", "pridat",
    "vytvoř", "vytvor", "vytvořit", "vytvorit", "implementuj", "implementovat",
    "postav", "postavit", "oprav", "opravit", "integruj", "integrovat",
    "změň", "zmen", "změnit", "zmenit", "otestuj", "otestovat",
    "navrhni", "navrhnout", "ověř", "over", "ověřit", "overit",
    "zkontroluj", "zkontrolovat", "vyladit", "vyřeš", "vyres", "vyřešit", "vyresit",
    "rozděl", "rozdel", "rozdělit", "rozdelit", "přejmenuj", "prejmenuj",
    "přejmenovat", "prejmenovat", "refaktoruj", "refaktorovat",
    "vyčisti", "vycisti", "vyčistit", "vycistit", "ukliď", "uklid", "uklidit",
    "smaž", "smaz", "smazat", "odstraň", "odstran", "odstranit",
    "vylepši", "vylepsi", "vylepšit", "vylepsit", "nastav", "nastavit",
    "nakonfiguruj", "migruj", "napiš", "napis", "napsat", "udělej", "udelej",
    "přepiš", "prepis", "vygeneruj", "extrahuj",
)

_SOFT_ACTION_VERBS = ("test", "tests", "make", "change", "check", "debug", "diagnose", "ladit", "laď", "lad")

_LIVE_GUI_KEYWORDS = (
    "ui", "gui", "frontend", "frontendu", "react", "nextjs", "next.js",
    "vue", "svelte", "tailwind", "flutter", "electron", "pyqt", "pyqt5",
    "pyqt6", "pyside", "pyside6", "tkinter", "wpf", "tauri", "swiftui",
    "playwright", "angular", "shadcn", "html", "css",
    "dashboard", "dashboardu", "graf", "grafy", "grafů", "chart", "charts",
    "browser", "prohlížeč", "prohlížeči", "prohlížeče",
    "rozhraní", "obrazovka", "obrazovku", "obrazovky", "obrazovce",
    "aplikace s okny", "aplikaci s okny", "okenní aplikace", "okenní aplikaci",
    "webová aplikace", "webovou aplikaci", "webové aplikace", "webové aplikaci",
    "webových aplikací", "web app", "webapp", "web page", "webpage", "website",
    "webové stránky", "webovou stránku", "stránka", "stránku", "stránky",
    "komponenta", "komponentu", "komponenty", "vzhled", "vzhledu", "screen", "view",
)

_VISUAL_DOC_KEYWORDS = (
    "svg", "mermaid", "architecture diagram", "diagram", "diagramy",
    "ilustrace", "illustration", "banner", "logo", "badge", "badges",
    "infographic", "infografika", "wireframe",
)

_README_VISUAL_CUES = (
    "vylepši", "vylepsi", "improve", "enhance", "polish", "visual", "vizuální",
    "vzhled", "svg", "diagram", "mermaid", "badge", "banner", "logo",
    "grafika", "grafiku", "ikony", "icons",
)

_DEBUG_TRIGGER_TERMS = (
    "crash", "hang", "bug", "bugs", "traceback", "tracebackem", "tracebacku",
    "stacktrace", "stack trace", "segfault", "deadlock", "debug", "debugging", "diagnose",
    "padá", "pada", "spadne", "zamrzá", "zamrza", "zamrzne", "visí",
    "chyba", "chybu", "chyby", "chyb", "pád", "pády", "nefunguje",
    "ladit", "vyladit", "asw-debug",
)

_CRASH_SYMPTOM_TERMS = (
    "crash", "hang", "traceback", "tracebackem", "tracebacku", "stacktrace", "stack trace",
    "segfault", "deadlock", "padá", "pada", "spadne", "zamrzá", "zamrza", "zamrzne",
    "nefunguje", "pád", "pády",
)

_REFACTOR_TRIGGER_TERMS = (
    "refactor", "refaktor", "refaktoruj", "refaktorovat",
    "split", "rozděl", "rozdel", "rozdělit", "rozdelit",
    "rename", "přejmenuj", "prejmenuj", "přejmenovat", "prejmenovat",
    "restructure", "reorganize", "extract helper", "extract function",
    "rozčleň", "rozclen", "asw-refactor",
)

_CLEANUP_TRIGGER_TERMS = (
    "cleanup", "clean up", "clean-up", "dead code", "dead-code",
    "unused code", "unused imports", "ai slop", "slop",
    "vyčisti", "vycisti", "vyčistit", "vycistit", "ukliď", "uklid", "uklidit",
    "mrtvý kód", "mrtvy kod", "zbytečný kód", "zbytecny kod",
    "nepoužívaný kód", "nepoužívané importy", "remove-ai-slops", "asw-cleanup",
)


def _strip_quoted_spans(text: str) -> str:
    """Strip quoted spans (EN/CZ/curly) while preserving contractions (don't, isn't, can't) and backticks."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = _DOUBLE_QUOTE_RE.sub(" ", text)
    cleaned = _CZ_QUOTE_RE.sub(" ", cleaned)
    cleaned = _CURLY_DOUBLE_QUOTE_RE.sub(" ", cleaned)
    cleaned = _SINGLE_QUOTE_RE.sub(" ", cleaned)
    cleaned = _CURLY_SINGLE_QUOTE_RE.sub(" ", cleaned)
    return cleaned


def _strip_ignored_regions(text: str) -> str:
    """Strip fenced code, backticks, and quoted spans while preserving contractions (don't, isn't, can't)."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = _FENCED_CODE_RE.sub(" ", text)
    cleaned = _INLINE_CODE_RE.sub(" ", cleaned)
    return _strip_quoted_spans(cleaned)


_HYPOTHETICAL_CLAUSE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:když|kdyz|pokud|jestliže|jestlize|jestli|kdyby|jakmile|v\s+případě|v\s+pripade|pro\s+případ|pro\s+pripad)"
        r"\s+(?:se\s+)?(?:oprav\w*|lad\w*|(?:řeš\w*|res(?:i[a-z]*|en[a-z]*|uj[a-z]*|te\b))\s+(?:chyb\w*|bug\w*|pád\w*|pad\w*|problém\w*|problem\w*)|debug\w*|bugfix\w*|jde\s+o\s+(?:oprav\w*|chyb\w*|bug\w*|pád\w*))(?:(?!\b(?:tak|pak|potom)\b)[^,;.!?\n])*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:when|whenever|if|while|suppose|assuming|in\s+case(?:\s+of)?)"
        r"\s+(?:(?:we(?:'re|\s+are)?|you(?:'re|\s+are)?|it(?:'s|\s+is))\s+)?"
        r"(?:(?:fix(?:ing)?|debug(?:ging)?|repair(?:ing)?|resolv(?:e|ing)|handl(?:e|ing))\s+(?:a\s+|an\s+|the\s+)?(?:bug\w*|error\w*|crash\w*|issue\w*|traceback\w*|defect\w*|failure\w*)|(?:a\s+)?(?:bugfix\w*|bug\s+fix\w*|debugging|hotfix\w*))[^,;.!?\n]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:nebo|anebo|případně|pripadne|například|naprikad|např\.?|třeba|treba)"
        r"\s+(?:když\s+|pokud\s+)?(?:opravujeme|ladíme|řešíme|oprav\w*\s+chyb\w*|bugfix\w*|chyb\w*\s+v\s+kódu|při\s+oprav\w*)[^,;.!?\n]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:or|for\s+example|e\.g\.|such\s+as)"
        r"\s+(?:(?:when|if)\s+)?(?:fixing|debugging|repairing|solving|bugfix\w*|bug\s+fix\w*)[^,;.!?\n]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:without|instead\s+of|rather\s+than|not\s+for|bypass(?:ing)?|skip(?:ping)?|mask(?:ing)?)"
        r"\s+(?:when\s+)?(?:fixing|debugging|bugfix\w*|bug\s+fix\w*|bugs?|crashes?|tracebacks?)[^,;.!?\n]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:(?<=^)|(?<=[\s,;.(]))"
        r"(?:bez|místo|misto|nikoli|nikoliv|ne\s+pro)"
        r"\s+(?:oprav\w*|lad\w*|bugfix\w*|chyb\w*|pád\w*)[^,;.!?\n]*",
        re.IGNORECASE,
    ),
)

_NO_CLARIFY_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_-])--no[-_]clarify(?![A-Za-z0-9_-])"
    r"|\b(?:skip[- ]clarify|no[- ]clarify|don't clarify|do not clarify|without clarification|decide yourself|your call)\b"
    r"|\b(?:bez\s+dopt[aá]v[aá]n[ií]|bez\s+up[rř]es[nň]ov[aá]n[ií]|bez\s+ot[aá]zek|rozhodni\s+s[aá]m|vyber\s+s[aá]m)\b)",
    re.IGNORECASE,
)
_FORCE_CLARIFY_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_-])--clarify(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_./-])/?asw-clarify(?![A-Za-z0-9_/-])"
    r"|\b(?:grill[- ]me|clarify\s+first|ask\s+me\s+questions|doptat\s+se|doptej\s+se|dopt[aá]vej\s+se)\b)",
    re.IGNORECASE,
)

_SPEC_FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6}"
    r"|\b[A-Za-z0-9_-]+\.(?:py|ts|tsx|js|jsx|mjs|go|rs|cpp|h|cs|java|rb|sql|json|yaml|yml|toml|md|html|css)\b)"
)
_SPEC_SYMBOL_RE = re.compile(
    r"(?:\b[a-z]+_[a-z0-9_]+\b|\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b|\b[A-Za-z_][A-Za-z0-9_]*\(\))"
)
_SPEC_ENDPOINT_SQL_CLI_RE = re.compile(
    r"(?:\b(?:GET|POST|PUT|PATCH|DELETE)\s+/[A-Za-z0-9_./{}-]+"
    r"|\b(?:SELECT|INSERT\s+INTO|ALTER\s+TABLE|CREATE\s+TABLE)\b"
    r"|(?<![A-Za-z0-9_-])--(?!clarify\b|no[-_]clarify\b)[a-z][a-z0-9-]{2,}\b)"
)
_SPEC_STACK_DB_RE = re.compile(
    r"\b(?:postgres|postgresql|mysql|sqlite|redis|mongodb|dynamodb|sqlalchemy|alembic|prisma|"
    r"fastapi|django|flask|express|nextjs|react|vue|svelte|docker|kubernetes|terraform|"
    r"kafka|graphql|grpc|playwright|pytest|pydantic|stripe)\b",
    re.IGNORECASE,
)
_SPEC_AUTH_RE = re.compile(
    r"\b(?:jwt|oauth2?|oidc|saml|rbac|abac|bearer|api[- ]key|hmac|mfa|totp|mtls|webauthn|passkey|csrf)\b",
    re.IGNORECASE,
)
_SPEC_NUMERIC_SLA_RE = re.compile(
    r"(?:\bp(?:50|95|99)\b|\b\d+(?:\.\d+)?\s*(?:ms|sec|min|req/s|req/min|rps|qps|mb|gb|kb|mib|gib|%|rows|retries)\b|[<>]=?\s*\d+)",
    re.IGNORECASE,
)
_SPEC_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\S+", re.MULTILINE)

_BUGFIX_BYPASS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:failing\s+test|traceback|assertionerror|stack\s*trace|http\s*500|status\s*500|error\s*500)\b", re.IGNORECASE),
    re.compile(r"\b(?:chyba\s*500|selh[aá]v[aá]\s+test|pad[aá]\s+(?:test|worker)|oprav\w*\s+chyb\w*|fix\s+(?:a\s+|the\s+)?bug)\b", re.IGNORECASE),
)

_CLARIFY_DIMENSIONS: tuple[tuple[str, float, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "scope_actors",
        5.0,
        re.compile(r"\b(?:portal|port[aá]l|platform|platforma|multi-region|billing|fakturac|p[rř]edplatn|admin|tenant)\w*", re.IGNORECASE),
        re.compile(r"\b(?:roles?|tenant|admin|non-goal|out of scope|single-user|b2b|b2c)\b", re.IGNORECASE),
    ),
    (
        "data_persistence",
        4.2,
        re.compile(r"\b(?:billing|fakturac|p[rř]edplatn|sync|synchroniza|export|cache|database|datab[aá]z|data|storage|portal|port[aá]l)\w*", re.IGNORECASE),
        _SPEC_STACK_DB_RE,
    ),
    (
        "auth_security",
        4.0,
        re.compile(r"\b(?:portal|port[aá]l|billing|fakturac|pay|auth|admin|api|user|customer|z[aá]kazn|multi-region)\w*", re.IGNORECASE),
        _SPEC_AUTH_RE,
    ),
    (
        "external_integration",
        3.5,
        re.compile(r"\b(?:billing|fakturac|p[rř]edplatn|pay|webhook|notif|email|sync|synchroniza|stripe|external|api|integrat)\w*", re.IGNORECASE),
        re.compile(r"\b(?:stripe|twilio|sendgrid|webhook|oauth2?|grpc|graphql)\b", re.IGNORECASE),
    ),
    (
        "ux_state_flow",
        3.2,
        re.compile(r"\b(?:portal|port[aá]l|ui|ux|dashboard|screen|form|flow|notif|react|frontend|page|str[aá]n)\w*", re.IGNORECASE),
        re.compile(r"\b(?:loading|empty state|error state|modal|redirect|state machine|wireframe)\b", re.IGNORECASE),
    ),
)


def _strip_hypothetical_clauses(text: str) -> str:
    """Mask hypothetical, example, or negated bugfix/debug clauses before debug detection."""
    if not text or not isinstance(text, str):
        return ""
    if not text.strip():
        return text
    cleaned = text
    for pat in _HYPOTHETICAL_CLAUSE_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    return cleaned


def _compute_specificity_score(prompt: str) -> int:
    """Compute a deterministic 0..7 technical specificity score for a prompt."""
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        return 0
    body = _LEADING_SLASH_CMD_RE.sub(" ", prompt.strip(), count=1)
    score = 0
    for pat in (
        _SPEC_FILE_PATH_RE,
        _SPEC_SYMBOL_RE,
        _SPEC_ENDPOINT_SQL_CLI_RE,
        _SPEC_STACK_DB_RE,
        _SPEC_AUTH_RE,
        _SPEC_NUMERIC_SLA_RE,
    ):
        if pat.search(body):
            score += 1
    if len(_SPEC_BULLET_LINE_RE.findall(body)) >= 2:
        score += 1
    return score


def _rank_missing_dimensions(prompt: str) -> list[str]:
    """Rank top 1..3 missing specification dimensions by Impact * Uncertainty."""
    scored: list[tuple[float, int, str, float]] = []
    for idx, (dim, base_impact, domain_re, resolved_re) in enumerate(_CLARIFY_DIMENSIONS):
        impact = base_impact + (1.0 if domain_re.search(prompt) else 0.0)
        uncertainty = 0.15 if resolved_re.search(prompt) else 1.0
        scored.append((-(impact * uncertainty), idx, dim, uncertainty))
    scored.sort(key=lambda item: (item[0], item[1]))
    dims = [dim for _, _, dim, unc in scored if unc > 0.2][:3]
    if not dims:
        dims = [dim for _, _, dim, _ in scored[:3]]
    return dims


def assess_clarification_need(
    prompt: str,
    *,
    execution_mode: str = "mode_3",
    recommended_command: str = "asw-loop",
    is_consultation: bool = False,
    auto_subskills: list[str] | None = None,
    enabled: bool = True,
) -> dict[str, object]:
    """Zero-LLM (<5ms) selective Spec-Kit clarify gate with Impact * Uncertainty ranking."""
    if not enabled:
        return {
            "needs_clarification": False,
            "bypass_reason": "disabled",
            "specificity_score": 0,
            "ambiguity_score": 0.0,
            "missing_dimensions": [],
            "max_questions": 0,
        }

    raw = prompt if isinstance(prompt, str) else ""
    trimmed = raw.strip()
    if not trimmed:
        return {
            "needs_clarification": False,
            "bypass_reason": "read_only" if (is_consultation or execution_mode == "mode_1") else "operational_or_restore",
            "specificity_score": 0,
            "ambiguity_score": 0.0,
            "missing_dimensions": [],
            "max_questions": 0,
        }

    stripped = _strip_ignored_regions(trimmed)
    hyp_stripped = _strip_hypothetical_clauses(stripped)
    lower_hyp = hyp_stripped.lower()
    specificity_score = _compute_specificity_score(trimmed)
    ambiguity_score = round(max(0.0, min(1.0, (3 - min(3, specificity_score)) / 3.0)), 4)

    def _bypass(reason: str) -> dict[str, object]:
        return {
            "needs_clarification": False,
            "bypass_reason": reason,
            "specificity_score": specificity_score,
            "ambiguity_score": ambiguity_score,
            "missing_dimensions": [],
            "max_questions": 0,
        }

    if _NO_CLARIFY_RE.search(stripped):
        return _bypass("user_skip")

    if recommended_command == "asw-clarify" or _FORCE_CLARIFY_RE.search(stripped):
        return {
            "needs_clarification": True,
            "bypass_reason": "user_forced",
            "specificity_score": specificity_score,
            "ambiguity_score": round(max(0.2, ambiguity_score), 4),
            "missing_dimensions": _rank_missing_dimensions(trimmed),
            "max_questions": 3,
        }

    if is_consultation or execution_mode == "mode_1":
        return _bypass("read_only")

    if execution_mode in ("mode_0", "mode_4"):
        return _bypass("operational_or_restore")

    if recommended_command == "asw-start-work":
        return _bypass("executing_approved_plan")

    if recommended_command == "asw-review":
        return _bypass("review_only")

    auto_set = set(auto_subskills or [])
    if recommended_command == "asw-cleanup" or "asw-refactor" in auto_set or "asw-cleanup" in auto_set:
        return _bypass("behavior_preserving")

    if "asw-debug" in auto_set or any(pat.search(lower_hyp) for pat in _BUGFIX_BYPASS_PATTERNS):
        return _bypass("bugfix_or_debug")

    if execution_mode == "mode_2":
        return _bypass("small_clear_change")

    if specificity_score >= 3:
        return _bypass("sufficient_detail")

    return {
        "needs_clarification": True,
        "bypass_reason": None,
        "specificity_score": specificity_score,
        "ambiguity_score": ambiguity_score,
        "missing_dimensions": _rank_missing_dimensions(trimmed),
        "max_questions": 3,
    }


def _is_question_framed(stripped_text: str) -> bool:
    lower = stripped_text.strip().lower()
    if not lower:
        return False
    return lower.endswith("?") or any(re.search(pat, lower) for pat in _QUESTION_START_PATTERNS)


def _has_action_verb(stripped_text: str, *, include_soft: bool = True) -> bool:
    masked = _PATH_OR_FILE_RE.sub(" ", stripped_text).lower()
    if any(_matches_term(v, masked) for v in _STRONG_ACTION_VERBS):
        return True
    if include_soft and any(_matches_term(v, masked) for v in _SOFT_ACTION_VERBS):
        return True
    return False


def _is_read_only_question(stripped_text: str) -> bool:
    if not _is_question_framed(stripped_text):
        return False
    return not _has_action_verb(stripped_text, include_soft=False)


def _detect_gui_intent(
    text: str,
    *,
    has_action_verb: bool | None = None,
    is_question_only: bool | None = None,
    force_action_context: bool = False,
) -> dict[str, object]:
    """Detect bilingual UI/GUI app intent vs non-live visual docs (README/SVG), gated on action intent."""
    stripped = _strip_ignored_regions(text)
    lower = stripped.lower()
    if is_question_only is None:
        is_question_only = _is_read_only_question(stripped)
    if has_action_verb is None:
        has_action_verb = _has_action_verb(stripped, include_soft=not _is_question_framed(stripped))

    has_test_gui_mod = _TEST_GUI_MODIFIER_RE.search(stripped) is not None
    has_live_kw = any(_matches_term(kw, lower) for kw in _LIVE_GUI_KEYWORDS)
    has_visual_kw = any(_matches_term(kw, lower) for kw in _VISUAL_DOC_KEYWORDS) or (
        _matches_term("readme", lower) and any(_matches_term(cue, lower) for cue in _README_VISUAL_CUES)
    )

    if is_question_only and not has_test_gui_mod:
        return {
            "has_gui_keywords": has_live_kw,
            "is_live_gui_app": False,
            "is_visual_doc": False,
            "requires_gui_verification": False,
        }

    can_trigger = bool(has_action_verb or force_action_context or has_test_gui_mod)
    is_live_gui_app = bool((has_live_kw and can_trigger) or has_test_gui_mod)
    is_visual_doc = bool(has_visual_kw and can_trigger and not is_live_gui_app)
    return {
        "has_gui_keywords": has_live_kw,
        "is_live_gui_app": is_live_gui_app,
        "is_visual_doc": is_visual_doc,
        "requires_gui_verification": is_live_gui_app,
    }


def select_auto_subskills(prompt: str, *, force_action_context: bool = False) -> list[str]:
    """Zero-LLM sub-skill selector for asw-ui-ux, asw-test-gui, asw-debug, asw-refactor, asw-cleanup."""
    if not prompt or not isinstance(prompt, str):
        return []
    stripped = _strip_ignored_regions(prompt)
    lower = stripped.lower()
    is_q_framed = _is_question_framed(stripped)
    is_q_only = _is_read_only_question(stripped)
    has_action = _has_action_verb(stripped, include_soft=not is_q_framed)
    has_test_gui_mod = _TEST_GUI_MODIFIER_RE.search(stripped) is not None

    if is_q_only and not has_test_gui_mod:
        return []

    subskills: list[str] = []
    gui_info = _detect_gui_intent(
        stripped,
        has_action_verb=has_action,
        is_question_only=is_q_only,
        force_action_context=force_action_context,
    )
    if gui_info["is_live_gui_app"]:
        subskills.extend(["asw-ui-ux", "asw-test-gui"])
    elif gui_info["is_visual_doc"]:
        subskills.append("asw-ui-ux")

    debug_stripped = _strip_hypothetical_clauses(stripped)
    debug_lower = debug_stripped.lower()
    debug_is_q_framed = _is_question_framed(debug_stripped)
    has_crash_symptom = (not debug_is_q_framed) and any(_matches_term(t, debug_lower) for t in _CRASH_SYMPTOM_TERMS)
    has_debug_term = any(_matches_term(t, debug_lower) for t in _DEBUG_TRIGGER_TERMS)
    if has_debug_term and (has_action or force_action_context or has_crash_symptom):
        subskills.append("asw-debug")

    if any(_matches_term(t, lower) for t in _REFACTOR_TRIGGER_TERMS) and (
        has_action or force_action_context or not is_q_framed
    ):
        subskills.append("asw-refactor")

    if any(_matches_term(t, lower) for t in _CLEANUP_TRIGGER_TERMS) and (
        has_action or force_action_context or not is_q_framed
    ):
        subskills.append("asw-cleanup")

    deduped: list[str] = []
    for s in subskills:
        if s not in deduped:
            deduped.append(s)
    return deduped[:8]


class DecisionRouter:
    """System 1 decision router evaluating developer prompts, diffs, and findings."""

    def __init__(
        self,
        server_url: str | None = None,
        enable_inproc: bool | None = None,
        config: dict[str, object] | None = None,
    ):
        self.config = config if config is not None else load_decision_config()
        self.enabled = bool(self.config.get("enabled", True))
        self._daemon_configured = bool(
            server_url
            or os.environ.get("LAYA_SERVER_URL")
            or self.config.get("use_daemon", False)
        )
        self.server_url = (
            server_url
            or os.environ.get("LAYA_SERVER_URL")
            or str(self.config.get("server_url") or "http://127.0.0.1:8765")
        )
        if enable_inproc is None:
            self.enable_inproc = os.environ.get("LAYA_ENABLE_INPROC", "0").lower() in ("1", "true")
        else:
            self.enable_inproc = enable_inproc

        self._laya_router = None
        if not self.enabled:
            self.device_info: dict[str, object] = {
                "device": "disabled",
                "max_loaded": 0,
                "gpu_name": None,
                "total_vram_mib": None,
                "free_vram_mib": None,
                "compute_cap": None,
                "reason": "decision_model_disabled",
            }
        else:
            self.device_info = select_optimal_device()
            self._init_inproc_if_enabled()

    @staticmethod
    def _resolve_local_laya_snapshot(preferred: str = "multilingual") -> tuple[str | None, str | None]:
        """Find cached HuggingFace snapshot on disk to bypass HTTP Hub check (12.4s -> 2.48s)."""
        hub_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--convaiinnovations--laya" / "snapshots"
        if not hub_dir.is_dir():
            return None, None
        snaps = list(hub_dir.iterdir())
        if preferred == "multilingual":
            for s in snaps:
                if (s / "multilingual" / "model.safetensors").is_file():
                    return str(s), "multilingual"
        for s in snaps:
            if (s / "model.safetensors").is_file():
                return str(s), None
        return None, None

    def _init_inproc_if_enabled(self) -> None:
        if not self.enabled or not self.enable_inproc:
            return
        try:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            import torch  # type: ignore
            import laya  # type: ignore

            dev = str(self.device_info.get("device", "cpu"))
            if dev == "cpu":
                if bool(self.config.get("flush_denormal", True)):
                    torch.set_flush_denormal(True)
                threads = int(self.config.get("cpu_threads", os.cpu_count() or 12))
                if threads > 0:
                    torch.set_num_threads(threads)

            if bool(self.config.get("use_local_snapshot_fastload", True)):
                pref = str(self.config.get("preferred_checkpoint", "multilingual"))
                snap_path, sub = self._resolve_local_laya_snapshot(pref)
                if snap_path is not None:
                    self._laya_router = laya.Agent(snap_path, subfolder=sub, device=dev)
                    return

            max_l = int(self.device_info.get("max_loaded", 1))
            self._laya_router = laya.Router(device=dev, max_loaded=max_l)
        except Exception:
            self._laya_router = None

    def preflight(self) -> dict[str, object]:
        """Check availability of GPU device, Laya SDK, and local Laya HTTP daemon."""
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "backend": "disabled",
                "laya_sdk_installed": False,
                "laya_server_reachable": False,
                "device_info": self.device_info,
            }
        sdk_installed = False
        try:
            import laya  # noqa: F401

            sdk_installed = True
        except ImportError:
            sdk_installed = False

        server_reachable = False
        try:
            timeout = float(self.config.get("daemon_timeout_sec", 0.65))
            req = urllib.request.Request(f"{self.server_url.rstrip('/')}/health", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    server_reachable = True
        except Exception:
            server_reachable = False

        if server_reachable:
            backend = "laya_daemon"
        elif self._laya_router is not None:
            backend = "laya_inproc"
        else:
            backend = "system1_calibrated_fallback"

        return {
            "device_info": self.device_info,
            "laya_sdk_installed": sdk_installed,
            "laya_server_reachable": server_reachable,
            "active_backend": backend,
        }

    def select_auto_subskills(self, prompt: str, *, force_action_context: bool = False) -> list[str]:
        """Select zero-LLM auto sub-skills (asw-ui-ux, asw-test-gui, asw-debug, asw-refactor, asw-cleanup)."""
        if not self.enabled:
            return []
        return select_auto_subskills(prompt, force_action_context=force_action_context)

    def assess_clarification_need(
        self,
        prompt: str,
        *,
        execution_mode: str = "mode_3",
        recommended_command: str = "asw-loop",
        is_consultation: bool = False,
        auto_subskills: list[str] | None = None,
    ) -> dict[str, object]:
        """Assess whether a prompt requires a selective Spec-Kit clarification gate."""
        return assess_clarification_need(
            prompt,
            execution_mode=execution_mode,
            recommended_command=recommended_command,
            is_consultation=is_consultation,
            auto_subskills=auto_subskills,
            enabled=self.enabled,
        )

    def route_prompt(self, prompt: str) -> dict[str, object]:
        """Route a user prompt into Mode 0-5, Quad-Model Tier, GUI gate, and subagent requirements."""
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "backend": "disabled",
                "requires_gui_verification": False,
                "requires_subagent_plan_wave": False,
                "auto_subskills": [],
                "selected_skills": [],
                "opt_tokens": 0.0,
                "choice": "disabled",
                "score": 0.0,
                "noul": 0.0,
                "probabilities": {},
                "answer_confidence": 0.0,
                "execution_mode": "disabled",
                "recommended_mode": "disabled",
                "recommended_command": "disabled",
                "is_consultation": False,
                "recommended_tier": "disabled",
                "clarification_gate": assess_clarification_need(prompt, enabled=False),
                "device_info": self.device_info,
            }

        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return self._build_decision(
                choice="mode_1",
                execution_mode="mode_1",
                recommended_command="asw-consultation",
                is_consultation=True,
                recommended_tier="carbon_plan_research",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.5,
                noul=0.1,
                auto_subskills=[],
                prompt_for_skills="",
            )

        trimmed = prompt.strip()
        stripped = _strip_ignored_regions(trimmed)

        # M1: Leading command priority + quoted command immunity (ignoring path substrings like foo/asw/bar)
        leading_match = _LEADING_SLASH_CMD_RE.match(stripped)
        slash_match = leading_match or _ANY_SLASH_CMD_RE.search(stripped)
        if slash_match:
            cmd = slash_match.group(1).lower()
            body = stripped[slash_match.end():].strip() if leading_match else stripped
            eval_text = body if body else stripped
            has_test_gui_mod = _TEST_GUI_MODIFIER_RE.search(stripped) is not None
            is_q_only = _is_read_only_question(eval_text)

            if "plan" in cmd:
                gui_info = _detect_gui_intent(eval_text, force_action_context=not is_q_only)
                auto_subskills = select_auto_subskills(eval_text, force_action_context=not is_q_only)
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_command="asw-plan",
                    is_consultation=False,
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification=bool(gui_info["requires_gui_verification"]) or has_test_gui_mod,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.2,
                    auto_subskills=auto_subskills,
                    prompt_for_skills=trimmed,
                )
            elif "clarify" in cmd:
                gui_info = _detect_gui_intent(eval_text, force_action_context=not is_q_only)
                auto_subskills = select_auto_subskills(eval_text, force_action_context=not is_q_only)
                req_gui = bool(gui_info["requires_gui_verification"]) or has_test_gui_mod
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_command="asw-clarify",
                    is_consultation=False,
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification=req_gui,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.85 if req_gui else 0.2,
                    auto_subskills=auto_subskills,
                    prompt_for_skills=trimmed,
                )
            elif "test-gui" in cmd:
                auto_subskills = select_auto_subskills(eval_text, force_action_context=True)
                for req_skill in ("asw-ui-ux", "asw-test-gui"):
                    if req_skill not in auto_subskills:
                        auto_subskills.append(req_skill)
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_command="asw-test-gui",
                    is_consultation=False,
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification=True,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.9,
                    auto_subskills=auto_subskills[:8],
                    prompt_for_skills=trimmed,
                )
            elif "start-work" in cmd:
                gui_info = _detect_gui_intent(eval_text, force_action_context=True)
                auto_subskills = select_auto_subskills(eval_text, force_action_context=True)
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_command="asw-start-work",
                    is_consultation=False,
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification=bool(gui_info["requires_gui_verification"]) or has_test_gui_mod,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.2,
                    auto_subskills=auto_subskills,
                    prompt_for_skills=trimmed,
                )
            elif "review" in cmd:
                return self._build_decision(
                    choice="mode_2",
                    execution_mode="mode_2",
                    recommended_command="asw-review",
                    is_consultation=False,
                    recommended_tier="neon_qa_review",
                    requires_gui_verification=False,
                    requires_subagent_plan_wave=False,
                    answer_confidence=1.0,
                    noul=0.1,
                    auto_subskills=[],
                    prompt_for_skills=trimmed,
                )
            elif "goal" in cmd:
                gui_info = _detect_gui_intent(eval_text, force_action_context=not is_q_only)
                auto_subskills = select_auto_subskills(eval_text, force_action_context=not is_q_only)
                return self._build_decision(
                    choice="mode_5",
                    execution_mode="mode_5",
                    recommended_command="asw-goal",
                    is_consultation=False,
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification=bool(gui_info["requires_gui_verification"]) or has_test_gui_mod,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.1,
                    auto_subskills=auto_subskills,
                    prompt_for_skills=trimmed,
                )
            elif "cleanup" in cmd:
                auto_subskills = select_auto_subskills(eval_text, force_action_context=True)
                if "asw-cleanup" not in auto_subskills:
                    auto_subskills = ["asw-cleanup", *auto_subskills]
                return self._build_decision(
                    choice="mode_2",
                    execution_mode="mode_2",
                    recommended_command="asw-cleanup",
                    is_consultation=False,
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification=False,
                    requires_subagent_plan_wave=False,
                    answer_confidence=1.0,
                    noul=0.1,
                    auto_subskills=auto_subskills[:8],
                    prompt_for_skills=trimmed,
                )
            else:  # asw / asw-loop
                if cmd == "asw" and is_q_only and not has_test_gui_mod:
                    return self._build_decision(
                        choice="mode_1",
                        execution_mode="mode_1",
                        recommended_command="asw-consultation",
                        is_consultation=True,
                        recommended_tier="carbon_plan_research",
                        requires_gui_verification=False,
                        requires_subagent_plan_wave=False,
                        answer_confidence=1.0,
                        noul=0.15,
                        auto_subskills=[],
                        prompt_for_skills=trimmed,
                    )

                gui_info = _detect_gui_intent(eval_text)
                auto_subskills = select_auto_subskills(eval_text)
                req_gui = bool(gui_info["requires_gui_verification"]) or has_test_gui_mod
                if req_gui and "asw-test-gui" not in auto_subskills:
                    auto_subskills = [*auto_subskills, "asw-test-gui"]
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_command="asw-loop",
                    is_consultation=False,
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification=req_gui,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.85 if req_gui else 0.3,
                    auto_subskills=auto_subskills[:8],
                    prompt_for_skills=trimmed,
                )

        # M2: Implicit multi-step / UI feature prompts & Mode 1 consultation (Bilingual CZ / EN)
        lower = stripped.lower()
        is_q_framed = _is_question_framed(stripped)
        is_q_only = _is_read_only_question(stripped)
        has_action = _has_action_verb(stripped, include_soft=not is_q_framed)
        has_test_gui_mod = _TEST_GUI_MODIFIER_RE.search(stripped) is not None

        gui_info = _detect_gui_intent(
            stripped,
            has_action_verb=has_action,
            is_question_only=is_q_only,
        )
        has_gui = bool(gui_info["requires_gui_verification"])
        auto_subskills = select_auto_subskills(stripped)

        if is_q_only and not has_test_gui_mod:
            return self._build_decision(
                choice="mode_1",
                execution_mode="mode_1",
                recommended_command="asw-consultation",
                is_consultation=True,
                recommended_tier="carbon_plan_research",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.90,
                noul=0.15,
                auto_subskills=[],
                prompt_for_skills=trimmed,
            )

        # Mode 4: Emergency rollback / restore / revert prompts (unless paired with engineering/feature creation verbs)
        engineering_feature_verbs = [
            "implement", "build", "add", "create", "design", "refactor", "integrate", "develop", "test", "write",
            "vytvoř", "přidej", "implementuj", "navrhni", "postav", "integruj", "uprav", "otestuj",
        ]
        has_engineering_verb = any(_matches_term(v, lower) for v in engineering_feature_verbs)
        mode4_patterns = [
            r"\brollback\b",
            r"\bemergency\s+restore\b",
            r"\brevert\s+production\b",
            r"\bnouzová\s+obnova\b",
        ]
        if any(re.search(pat, lower) for pat in mode4_patterns) and not has_engineering_verb:
            base_decision = self._build_decision(
                choice="mode_4",
                execution_mode="mode_4",
                recommended_command="asw-loop",
                is_consultation=False,
                recommended_tier="hydrogen_implement_tdd",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.95,
                noul=0.15,
                auto_subskills=auto_subskills,
                prompt_for_skills=trimmed,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        # Mode 0: Fast operational build / test / run / lint commands (without code-change/fix/creation verbs or GUI design)
        code_change_verbs = [
            "fix", "repair", "patch", "modify", "update", "refactor",
            "add", "implement", "create", "integrate", "develop", "design", "verify",
            "oprav", "uprav", "změň", "přidej", "vytvoř", "implementuj", "postav", "integruj", "navrhni", "ověř",
        ]
        has_code_change_verb = any(_matches_term(v, lower) for v in code_change_verbs)
        mode0_patterns = [
            r"\brun\s+(?:pytest|unit\s+tests|tests?|lint(?:er)?|build)\b",
            r"\bbuild\s+(?:debug|release|project|app)\b",
            r"\bcmake\s+--build\b",
            r"\bnpm\s+(?:test|run\s+(?:build|lint|test))\b",
            r"\bpytest\b",
            r"\bspusť\s+testy\b",
            r"\bzkompiluj\b",
        ]
        if any(re.search(pat, lower) for pat in mode0_patterns) and not has_code_change_verb and not has_gui:
            base_decision = self._build_decision(
                choice="mode_0",
                execution_mode="mode_0",
                recommended_command="asw-loop",
                is_consultation=False,
                recommended_tier="hydrogen_implement_tdd",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.92,
                noul=0.1,
                auto_subskills=[],
                prompt_for_skills=trimmed,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        # Feature / action verbs (CZ & EN)
        has_feature_verb = _has_action_verb(stripped, include_soft=False)

        is_multi_step = has_feature_verb and (
            "," in lower or " a " in lower or " and " in lower or has_gui or len(lower.split()) > 7
        )

        if is_multi_step or (has_gui and has_feature_verb):
            noul = 0.85 if has_gui else 0.70
            base_decision = self._build_decision(
                choice="mode_3",
                execution_mode="mode_3",
                recommended_command="asw-loop",
                is_consultation=False,
                recommended_tier="carbon_plan_research",
                requires_gui_verification=has_gui,
                requires_subagent_plan_wave=True,
                answer_confidence=0.92,
                noul=noul,
                auto_subskills=auto_subskills,
                prompt_for_skills=trimmed,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        # Default fallback
        if has_feature_verb or bool(auto_subskills):
            base_decision = self._build_decision(
                choice="mode_2",
                execution_mode="mode_2",
                recommended_command="asw-loop",
                is_consultation=False,
                recommended_tier="hydrogen_implement_tdd",
                requires_gui_verification=has_gui,
                requires_subagent_plan_wave=False,
                answer_confidence=0.80,
                noul=0.4,
                auto_subskills=auto_subskills,
                prompt_for_skills=trimmed,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        base_decision = self._build_decision(
            choice="mode_1",
            execution_mode="mode_1",
            recommended_command="asw-consultation",
            is_consultation=True,
            recommended_tier="carbon_plan_research",
            requires_gui_verification=False,
            requires_subagent_plan_wave=False,
            answer_confidence=0.75,
            noul=0.2,
            auto_subskills=[],
            prompt_for_skills=trimmed,
        )
        return self._enrich_with_laya(trimmed, base_decision)

    def _laya_questions_schema(self) -> dict[str, dict[str, object]]:
        if bool(self.config.get("compact_question_schema", True)):
            return {
                "execution_mode": {
                    "type": "choice",
                    "instructions": "Mode:",
                    "criteria": {
                        "mode_0": "build/run",
                        "mode_1": "explain/research",
                        "mode_2": "small fix",
                        "mode_3": "multi-step feature/UI",
                        "mode_4": "rollback",
                        "mode_5": "long program",
                    },
                },
            }
        return {
            "execution_mode": {
                "type": "choice",
                "instructions": "Select the development execution mode for this software engineering request.",
                "criteria": {
                    "mode_0": "Fast operational build, test, or run command",
                    "mode_1": "Read-only investigation, explanation, or research analysis",
                    "mode_2": "Small single-file bugfix or minor change",
                    "mode_3": "Complex multi-step feature delivery requiring plan and subagents",
                    "mode_4": "Emergency production rollback or restore",
                    "mode_5": "Long-horizon autonomous research program",
                },
            },
            "requires_gui_verification": {
                "type": "noul",
                "instructions": "Does this request touch UI, frontend, dashboard, or browser rendering?",
            },
            "requires_subagent_plan_wave": {
                "type": "noul",
                "instructions": "Is this a multi-step engineering change that requires a plan and subagent waves?",
            },
        }

    def _enrich_with_laya(self, prompt: str, base_decision: dict[str, object]) -> dict[str, object]:
        """Enrich or score via live Laya daemon or in-proc Laya Router when active."""
        raw: dict[str, object] | None = None
        backend_name = ""
        schema = self._laya_questions_schema()

        if self._laya_router is not None:
            try:
                res = self._laya_router.predict(prompt, schema)
                if isinstance(res, dict):
                    raw = res
                    backend_name = "laya_inproc"
            except Exception:
                raw = None
        elif self._daemon_configured:
            try:
                timeout = float(self.config.get("daemon_timeout_sec", 0.65))
                payload = json.dumps({"text": prompt, "state": prompt, "questions": schema}).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.server_url.rstrip('/')}/predict",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        parsed = json.loads(resp.read().decode("utf-8"))
                        if isinstance(parsed, dict):
                            raw = parsed
                            backend_name = "laya_daemon"
            except Exception:
                raw = None

        if not raw:
            return base_decision

        try:
            answers = raw.get("answers", {})
            mode_ans = answers.get("execution_mode", {}) if isinstance(answers, dict) else {}
            gui_ans = answers.get("requires_gui_verification", {}) if isinstance(answers, dict) else {}
            if isinstance(mode_ans, dict) and "choice" in mode_ans:
                choice = str(mode_ans["choice"])
                conf = float(mode_ans.get("answer_confidence", base_decision["answer_confidence"]))
                probs = mode_ans.get("probabilities", base_decision["probabilities"])
                has_gui_noul = isinstance(gui_ans, dict) and "noul" in gui_ans and gui_ans["noul"] is not None
                gui_noul = float(gui_ans["noul"]) if has_gui_noul else None
                base_decision["backend"] = backend_name
                base_decision["laya_routing"] = raw.get("routing")
                override_threshold = 0.96 if base_decision["choice"] in ("mode_0", "mode_4") else 0.70
                if conf >= override_threshold:
                    base_decision["choice"] = choice
                    base_decision["execution_mode"] = choice
                    base_decision["recommended_mode"] = choice
                    base_decision["is_consultation"] = choice == "mode_1"
                    if choice == "mode_1":
                        base_decision["recommended_command"] = "asw-consultation"
                        if isinstance(base_decision.get("selected_skills"), list):
                            base_decision["selected_skills"] = [
                                s
                                for s in base_decision["selected_skills"]
                                if s not in ("implementation-developer", "validator-build-test-agent")
                            ]
                    base_decision["recommended_tier"] = (
                        "carbon_plan_research"
                        if choice in ("mode_1", "mode_3", "mode_5")
                        else "hydrogen_implement_tdd"
                    )
                    base_decision["score"] = round(conf, 4)
                    base_decision["answer_confidence"] = round(conf, 4)
                    base_decision["probabilities"] = probs
                    if gui_noul is not None:
                        base_decision["noul"] = round(gui_noul, 4)
                        if not base_decision.get("is_consultation") and gui_noul >= 0.75:
                            base_decision["requires_gui_verification"] = True
                    base_decision["requires_subagent_plan_wave"] = choice in ("mode_3", "mode_5")
                    base_decision["clarification_gate"] = self.assess_clarification_need(
                        prompt,
                        execution_mode=choice,
                        recommended_command=str(base_decision.get("recommended_command", "asw-loop")),
                        is_consultation=bool(base_decision.get("is_consultation", False)),
                        auto_subskills=base_decision.get("auto_subskills") if isinstance(base_decision.get("auto_subskills"), list) else [],
                    )
        except Exception:
            pass
        return base_decision

    def select_skills(self, prompt: str, max_skills: int = 8) -> list[str]:
        """Select up to max_skills (capped at 8) relevant skills using word-boundary + negative-example disambiguation."""
        if not self.enabled:
            return []
        max_skills = min(max(max_skills, 1), 8)
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return CORE_FALLBACK_SKILLS[: min(4, max_skills)]

        lower = _strip_quoted_spans(prompt).lower()
        scored: list[tuple[str, int]] = []

        for skill_name, keywords in CORE_SKILL_CATALOG_KEYWORDS.items():
            matched = [kw for kw in keywords if _matches_term(kw, lower)]
            if not matched:
                continue

            score = len(matched)
            neg_rule = SKILL_NEGATIVE_EXAMPLES.get(skill_name)
            has_strong = False
            if neg_rule:
                strong_anchors = set(neg_rule.get("strong_anchors", []))
                ambiguous_set = set(neg_rule.get("ambiguous_only_suppress", []))
                negative_terms = neg_rule.get("negative_terms", [])
                cue_terms = neg_rule.get("require_cue_if_only_ambiguous", [])

                has_strong = any(kw in strong_anchors for kw in matched)
                only_ambiguous = bool(ambiguous_set) and all(kw in ambiguous_set for kw in matched)

                if not has_strong:
                    neg_hits = sum(1 for neg in negative_terms if _matches_term(neg, lower))
                    if neg_hits > 0 and (only_ambiguous or not strong_anchors):
                        continue
                    cue_targets = set(neg_rule.get("require_cue_only_for", ambiguous_set))
                    only_cue_target = bool(cue_targets) and all(kw in cue_targets for kw in matched)
                    if only_cue_target and cue_terms and not any(_matches_term(c, lower) for c in cue_terms):
                        continue
                else:
                    # Strong domain anchors earn an extra disambiguation weight above generic hits
                    score += sum(1 for kw in matched if kw in strong_anchors)

            scored.append((skill_name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [s[0] for s in scored[:max_skills]]

        if not selected:
            return CORE_FALLBACK_SKILLS[: min(4, max_skills)]

        return selected

    def triage_finding(self, finding_text: str) -> dict[str, object]:
        """Triage a review finding into [patch], [bad_plan], or [defer] with severity."""
        if not self.enabled:
            return {
                "route": "[defer]",
                "severity_score": 0,
                "enabled": False,
                "status": "disabled",
                "explanation": "Decision router disabled",
            }

        if not finding_text or not isinstance(finding_text, str):
            return {
                "route": "[defer]",
                "severity_score": 1,
                "explanation": "Empty or invalid finding text",
            }

        lower = finding_text.lower()

        # Defect keywords indicating broken caller, contracts, or severe regressions
        defect_keywords = [
            "still called", "attributeerror", "deleted function", "missing adoption",
            "caller hop", "broken verification", "contract violation", "syntaxerror",
            "crash", "regression", "unresolved import", "chyba", "pád",
        ]
        is_defect = any(kw in lower for kw in defect_keywords)

        # Defer keywords indicating minor docs, formatting, or future ideas
        defer_keywords = [
            "out-of-scope", "typo", "formatting", "cosmetic", "future", "polish",
            "minor suggestion", "documentation only", "footer", "překlep", "kosmetick",
        ]
        is_defer = any(kw in lower for kw in defer_keywords)

        if is_defect:
            route = "[bad_plan]" if "contract violation" in lower or "frozen" in lower else "[patch]"
            return {
                "route": route,
                "severity_score": 5 if route == "[bad_plan]" else 4,
                "explanation": "Critical runtime or reference defect requiring code patch",
            }
        elif is_defer:
            return {
                "route": "[defer]",
                "severity_score": 1,
                "explanation": "Non-blocking documentation or cosmetic enhancement routed to deferred work",
            }
        else:
            return {
                "route": "[patch]",
                "severity_score": 3,
                "explanation": "Standard review item routed for verification and patch",
            }

    def classify_lesson_scope(self, cue: str, rule: str, project: str | None = None) -> dict[str, object]:
        """Classify whether an engineering lesson is project-scoped or global.

        Uses Laya noul/choice if active, or calibrated universal-vs-project heuristics.
        """
        if not project or not project.strip():
            return {"scope": "global", "confidence": 1.0, "reason": "no_project_specified"}

        p_norm = project.strip().lower()
        combined = f"{cue} {rule}".lower()

        if self._laya_router is not None:
            try:
                schema = {
                    "is_project_specific": {
                        "type": "noul",
                        "instructions": f"Does this lesson apply exclusively to project '{project}' rather than universal software engineering?",
                    }
                }
                res = self._laya_router.predict(f"Project: {project}\nCue: {cue}\nRule: {rule}", schema)
                noul = float(res.get("answers", {}).get("is_project_specific", {}).get("noul", 0.5))
                scope = "project" if noul >= 0.5 else "global"
                return {
                    "scope": scope,
                    "confidence": round(noul if scope == "project" else (1.0 - noul), 4),
                    "reason": "laya_noul_classification",
                }
            except Exception:
                pass

        has_proj_name = p_norm in combined
        has_proj_paths = bool(re.search(
            r"(?:services/|components/|models/|src/|api/|database/|migrations/|\.py|\.ts|\.tsx|\.sql|alembic|fastapi|docker-compose|endpoint)",
            combined,
        ))

        universal_keywords = [
            "utf-8", "bom", "encoding", "subprocess", "timeout", "tempfile",
            "json.loads", "yaml frontmatter", "try-except", "jaccard",
            "mock.patch", "pytest tmp_path", "windows and linux", "cross-platform",
        ]
        has_universal = any(kw in combined for kw in universal_keywords)

        if has_proj_name or (has_proj_paths and not has_universal):
            return {
                "scope": "project",
                "confidence": 0.90,
                "reason": f"project_specific_references_to_{p_norm}",
            }

        if has_universal and not has_proj_name:
            return {
                "scope": "global",
                "confidence": 0.85,
                "reason": "universal_engineering_rule",
            }

        return {
            "scope": "project",
            "confidence": 0.75,
            "reason": "scoped_to_active_project_by_default",
        }

    def _query_laya_loop_head(self, digest: str) -> tuple[str, float | None]:
        """Query local Laya in-proc or daemon head for unproductive loop score."""
        schema = {
            "is_trajectory_stuck_in_unproductive_loop": {
                "type": "noul",
                "instructions": "Is the trajectory stuck in an unproductive repeated-failure loop?",
            }
        }
        if self._laya_router is not None:
            try:
                raw = self._laya_router.predict(digest, schema)
                if isinstance(raw, dict):
                    ans = raw.get("answers", {}).get("is_trajectory_stuck_in_unproductive_loop", {})
                    if isinstance(ans, dict) and "noul" in ans:
                        return "laya_inproc", float(ans["noul"])
            except Exception:
                pass
        if self._daemon_configured:
            try:
                timeout = float(self.config.get("daemon_timeout_sec", 0.65))
                payload = json.dumps({"text": digest, "questions": schema}).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.server_url.rstrip('/')}/predict",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        raw = json.loads(resp.read().decode("utf-8"))
                        ans = raw.get("answers", {}).get("is_trajectory_stuck_in_unproductive_loop", {})
                        if isinstance(ans, dict) and "noul" in ans:
                            return "laya_daemon", float(ans["noul"])
            except Exception:
                pass
        return "system1_calibrated_fallback", None

    def judge_loop_digest(self, digest: str) -> dict[str, object]:
        """Local System 1 stuck-loop judge (M3) evaluating trajectory telemetry digests."""
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "backend": "disabled",
                "stuck": None,
                "confidence": 0.0,
                "reason": "decision_model_disabled",
            }

        raw = digest if isinstance(digest, str) else ""

        def _parse_int(key: str) -> tuple[int, bool]:
            m = re.search(rf"\b{key}\s*[:=]\s*(\d+)", raw, re.IGNORECASE)
            return (int(m.group(1)), True) if m else (0, False)

        def _parse_float(key: str) -> tuple[float | None, bool]:
            m = re.search(rf"\b{key}\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", raw, re.IGNORECASE)
            return (float(m.group(1)), True) if m else (None, False)

        turns, _ = _parse_int("turns")
        edit_churn, _ = _parse_int("edit_churn")
        distinct_edit_files, _ = _parse_int("distinct_edit_files")
        error_outputs, _ = _parse_int("error_outputs")
        test_runs, _ = _parse_int("test_runs")
        repeated_identical_failures, has_rep_hdr = _parse_int("repeated_identical_failures")
        stagnation_val, has_stag_hdr = _parse_float("stagnation")
        repo_context, _ = _parse_float("repo_context")

        err_hashes = re.findall(r"\[err#([A-Za-z0-9_.-]+)\]", raw)
        if not has_rep_hdr and err_hashes:
            counts: dict[str, int] = {}
            for h in err_hashes:
                counts[h] = counts.get(h, 0) + 1
            repeated_identical_failures = sum(c - 1 for c in counts.values())
        if not has_stag_hdr:
            if err_hashes:
                counts_s: dict[str, int] = {}
                for h in err_hashes:
                    counts_s[h] = counts_s.get(h, 0) + 1
                stagnation = sum(c - 1 for c in counts_s.values()) / len(err_hashes)
            else:
                stagnation = 0.0
        else:
            stagnation = float(stagnation_val or 0.0)
        stagnation = max(0.0, min(1.0, stagnation))

        telemetry: dict[str, object] = {
            "turns": turns,
            "edit_churn": edit_churn,
            "distinct_edit_files": distinct_edit_files,
            "error_outputs": error_outputs,
            "test_runs": test_runs,
            "repeated_identical_failures": repeated_identical_failures,
            "stagnation": round(stagnation, 4),
            "err_marker_count": len(err_hashes),
            "unique_err_hashes": len(set(err_hashes)),
        }
        if repo_context is not None:
            telemetry["repo_context"] = round(repo_context, 4)

        backend, laya_noul = self._query_laya_loop_head(raw)

        stuck: bool | None
        if not raw.strip() or (turns == 0 and error_outputs == 0 and not err_hashes):
            stuck = None
            confidence = 0.25
            reason = "ambiguous_early_or_mixed"
        elif (stagnation == 0.0 or repeated_identical_failures == 0) and (
            error_outputs >= 2 or turns >= 12 or len(err_hashes) >= 2
        ):
            stuck = False
            prod_conf = 0.82 + 0.02 * min(distinct_edit_files, 5) + (
                0.03 if stagnation == 0.0 and repeated_identical_failures == 0 else 0.0
            )
            if laya_noul is not None:
                prod_conf = 0.80 * prod_conf + 0.20 * max(0.80, 1.0 - laya_noul)
            confidence = round(min(0.95, max(0.80, prod_conf)), 4)
            reason = "productive_changing_failures"
        elif (
            turns >= 12
            and (edit_churn >= 4 or distinct_edit_files >= 3)
            and error_outputs >= 5
            and repeated_identical_failures >= 2
            and stagnation >= 0.20
        ):
            stag_term = min(1.0, max(0.0, (stagnation - 0.20) / 0.65))
            rep_term = min(1.0, max(0.0, (repeated_identical_failures - 2) / 5.0))
            churn_term = min(1.0, max(0.0, (max(edit_churn, distinct_edit_files) - 3) / 6.0))
            ctx_bonus = 0.02 if (repo_context is not None and repo_context >= 1.0) else 0.0
            raw_conf = 0.72 + 0.24 * (0.50 * stag_term + 0.30 * rep_term + 0.20 * churn_term) + ctx_bonus
            if laya_noul is not None:
                raw_conf = 0.80 * raw_conf + 0.20 * max(0.72, min(0.96, laya_noul))
            stuck = True
            confidence = round(min(0.96, max(0.72, raw_conf)), 4)
            reason = "stagnant_repeated_failure_loop"
        else:
            borderline = 0.35 + 0.15 * min(1.0, stagnation) + 0.10 * min(1.0, repeated_identical_failures / 3.0)
            stuck = None
            confidence = round(min(0.65, max(0.25, borderline)), 4)
            reason = "ambiguous_early_or_mixed"

        out: dict[str, object] = {
            "enabled": True,
            "status": "enabled",
            "backend": backend,
            "stuck": stuck,
            "confidence": confidence,
            "reason": reason,
            "telemetry": telemetry,
            "device_info": self.device_info,
        }
        if laya_noul is not None:
            out["laya_noul"] = round(laya_noul, 4)
        return out

    def predict(self, text: str, context: dict | None = None) -> dict[str, object]:
        """Unified entrypoint matching Laya's predict contract."""
        return self.route_prompt(text)

    def _build_decision(
        self,
        *,
        choice: str,
        execution_mode: str,
        recommended_tier: str,
        requires_gui_verification: bool,
        requires_subagent_plan_wave: bool,
        answer_confidence: float,
        noul: float,
        recommended_command: str = "asw-loop",
        is_consultation: bool = False,
        auto_subskills: list[str] | None = None,
        prompt_for_skills: str | None = None,
    ) -> dict[str, object]:
        all_modes = ["mode_0", "mode_1", "mode_2", "mode_3", "mode_4", "mode_5"]
        probs = {m: 0.05 for m in all_modes}
        probs[execution_mode] = round(answer_confidence, 2)
        remaining = max(0.0, 1.0 - answer_confidence)
        for m in all_modes:
            if m != execution_mode:
                probs[m] = round(remaining / 5.0, 3)

        deduped_auto: list[str] = []
        for s in auto_subskills or []:
            if s and s not in deduped_auto:
                deduped_auto.append(s)
        deduped_auto = deduped_auto[:8]

        remaining_slots = max(0, 8 - len(deduped_auto))
        if remaining_slots > 0 and prompt_for_skills is not None:
            domain_candidates = self.select_skills(prompt_for_skills, max_skills=8)
            excluded = (
                {"implementation-developer", "validator-build-test-agent"}
                if (is_consultation or execution_mode == "mode_1")
                else set()
            )
            selected_skills = [
                s for s in domain_candidates if s not in deduped_auto and s not in excluded
            ][:remaining_slots]
        else:
            selected_skills = []

        clarification_gate = self.assess_clarification_need(
            prompt_for_skills or "",
            execution_mode=execution_mode,
            recommended_command=recommended_command,
            is_consultation=is_consultation,
            auto_subskills=deduped_auto,
        )

        return {
            "enabled": True,
            "status": "enabled",
            "choice": choice,
            "score": answer_confidence,
            "noul": noul,
            "probabilities": probs,
            "answer_confidence": answer_confidence,
            "execution_mode": execution_mode,
            "recommended_mode": execution_mode,
            "recommended_command": recommended_command,
            "is_consultation": is_consultation,
            "recommended_tier": recommended_tier,
            "requires_gui_verification": requires_gui_verification,
            "requires_subagent_plan_wave": requires_subagent_plan_wave,
            "auto_subskills": deduped_auto,
            "selected_skills": selected_skills,
            "clarification_gate": clarification_gate,
            "opt_tokens": 0.0,
            "device_info": self.device_info,
            "backend": "system1_calibrated_fallback",
        }


BENCHMARK_ROUTING_PROMPTS: list[dict[str, object]] = [
    # 18 English engineering/quant/ops/docs prompts
    {
        "id": "EN-01",
        "lang": "en",
        "prompt": "Build Python backend and run unit tests suite quickly with invariant checks",
        "expected_skills": ["python-pro", "test-driven-development"],
        "forbidden_skills": ["ui-ux-designer", "typescript-pro", "risk-metrics-calculation"],
    },
    {
        "id": "EN-02",
        "lang": "en",
        "prompt": "Write Python state machine for git log parser",
        "expected_skills": ["python-pro"],
        "forbidden_skills": ["react-patterns"],
    },
    {
        "id": "EN-03",
        "lang": "en",
        "prompt": "Build Python inverted index for document search",
        "expected_skills": ["python-pro"],
        "forbidden_skills": ["postgres-best-practices"],
    },
    {
        "id": "EN-04",
        "lang": "en",
        "prompt": "Refactor local Python src/api/routes.py validation handler",
        "expected_skills": ["python-pro"],
        "forbidden_skills": ["context-hub"],
    },
    {
        "id": "EN-05",
        "lang": "en",
        "prompt": "Fetch Stripe SDK API docs with chub",
        "expected_skills": ["context-hub"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "EN-06",
        "lang": "en",
        "prompt": "Implement Rust async Tokio TCP server with serde",
        "expected_skills": ["rust-pro"],
        "forbidden_skills": ["typescript-pro", "ui-ux-designer"],
    },
    {
        "id": "EN-07",
        "lang": "en",
        "prompt": "Write Go concurrency worker with goroutines",
        "expected_skills": ["golang-pro"],
        "forbidden_skills": ["react-patterns"],
    },
    {
        "id": "EN-08",
        "lang": "en",
        "prompt": "We want to go to production after goal check and run Python pytest",
        "expected_skills": ["python-pro"],
        "forbidden_skills": ["golang-pro", "rtk-token-killer"],
    },
    {
        "id": "EN-09",
        "lang": "en",
        "prompt": "Optimize C++20 CMake build with RAII memory safety",
        "expected_skills": ["cpp-pro"],
        "forbidden_skills": ["obs-memory", "ui-ux-designer"],
    },
    {
        "id": "EN-10",
        "lang": "en",
        "prompt": "Configure Kubernetes Helm chart and Ingress pods",
        "expected_skills": ["kubernetes-architect"],
        "forbidden_skills": ["typescript-pro"],
    },
    {
        "id": "EN-11",
        "lang": "en",
        "prompt": "Provision enterprise cloud VPC using Terraform HCL modules",
        "expected_skills": ["terraform-skill"],
        "forbidden_skills": ["odoo-module-developer"],
    },
    {
        "id": "EN-12",
        "lang": "en",
        "prompt": "Perform OWASP security vulnerability audit for XSS and CSRF",
        "expected_skills": ["security-auditor"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "EN-13",
        "lang": "en",
        "prompt": "Build fast Parquet ETL pipeline using Polars LazyFrame",
        "expected_skills": ["polars"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "EN-14",
        "lang": "en",
        "prompt": "Create executive PowerPoint pitch deck slides in pptx",
        "expected_skills": ["pptx-official"],
        "forbidden_skills": ["react-patterns", "frontend-design"],
    },
    {
        "id": "EN-15",
        "lang": "en",
        "prompt": "Implement GDPR PII anonymization and data retention policy",
        "expected_skills": ["gdpr-data-handling"],
        "forbidden_skills": ["typescript-pro"],
    },
    {
        "id": "EN-16",
        "lang": "en",
        "prompt": "Tune Postgres SQL migration and composite index for query performance",
        "expected_skills": ["postgres-best-practices", "sql-pro"],
        "forbidden_skills": ["react-patterns"],
    },
    {
        "id": "EN-17",
        "lang": "en",
        "prompt": "Calculate portfolio Sharpe ratio, CVaR drawdown and volatility backtest",
        "expected_skills": ["quant-analyst", "risk-metrics-calculation"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "EN-18",
        "lang": "en",
        "prompt": "Fix JWT token validation and debug traceback crash in FastAPI",
        "expected_skills": ["fastapi-pro", "systematic-debugging"],
        "forbidden_skills": ["rtk-token-killer", "typescript-pro"],
    },
    # 12 Czech engineering/quant/ops/docs prompts
    {
        "id": "CZ-01",
        "lang": "cz",
        "prompt": "Uprav výpočet marže, přidej graf na dashboard a otestuj UI v prohlížeči",
        "expected_skills": ["ui-ux-designer", "playwright-skill", "test-driven-development"],
        "forbidden_skills": ["typescript-pro"],
    },
    {
        "id": "CZ-02",
        "lang": "cz",
        "prompt": "Optimalizuj SQL dotaz v PostgreSQL databázi a vytvoř migrace",
        "expected_skills": ["postgres-best-practices", "sql-pro"],
        "forbidden_skills": ["react-patterns"],
    },
    {
        "id": "CZ-03",
        "lang": "cz",
        "prompt": "Napiš Python asyncio skript a přidej unit testy s pytest",
        "expected_skills": ["python-pro", "test-driven-development"],
        "forbidden_skills": ["rtk-token-killer", "typescript-pro"],
    },
    {
        "id": "CZ-04",
        "lang": "cz",
        "prompt": "Vytvoř Docker container a Dockerfile pro nasazení aplikace",
        "expected_skills": ["docker-expert"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "CZ-05",
        "lang": "cz",
        "prompt": "Navrhni architekturu backendu a udělej revizi kódu",
        "expected_skills": ["software-architect", "compliance-maintainability-reviewer"],
        "forbidden_skills": ["frontend-design", "ui-ux-designer"],
    },
    {
        "id": "CZ-06",
        "lang": "cz",
        "prompt": "Ulož poznámky do Obsidian vault paměti",
        "expected_skills": ["obs-memory"],
        "forbidden_skills": ["typescript-pro"],
    },
    {
        "id": "CZ-07",
        "lang": "cz",
        "prompt": "Otestuj aplikaci pod Linuxem pomocí Python testů",
        "expected_skills": ["python-pro", "test-driven-development"],
        "forbidden_skills": ["kubernetes-architect", "typescript-pro"],
    },
    {
        "id": "CZ-08",
        "lang": "cz",
        "prompt": "Oprav chybu a pád v Rust Tokio službě",
        "expected_skills": ["systematic-debugging", "rust-pro"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "CZ-09",
        "lang": "cz",
        "prompt": "Připrav firemní prezentaci a slidy v PowerPointu (pptx)",
        "expected_skills": ["pptx-official"],
        "forbidden_skills": ["frontend-design"],
    },
    {
        "id": "CZ-10",
        "lang": "cz",
        "prompt": "Implementuj anonymizaci osobních údajů podle GDPR",
        "expected_skills": ["gdpr-data-handling"],
        "forbidden_skills": ["typescript-pro"],
    },
    {
        "id": "CZ-11",
        "lang": "cz",
        "prompt": "Proveď bezpečnostní audit zranitelností OWASP a CSRF",
        "expected_skills": ["security-auditor"],
        "forbidden_skills": ["ui-ux-designer"],
    },
    {
        "id": "CZ-12",
        "lang": "cz",
        "prompt": "Spočítej kvantitativní portfolio backtest a riziko drawdownu",
        "expected_skills": ["quant-analyst", "risk-metrics-calculation"],
        "forbidden_skills": ["ui-ux-designer"],
    },
]


def _evaluate_router_predictions(
    cases: list[dict[str, object]],
    predictor: object,
) -> dict[str, object]:
    """Compute genuine precision, recall, F1, and false-positive metrics from live predictions."""
    total_precision = 0.0
    total_recall = 0.0
    total_matched = 0
    total_predicted = 0
    total_expected = 0
    total_unexpected = 0
    polluted_prompts = 0
    forbidden_hits = 0
    forbidden_prompts = 0

    for case in cases:
        prompt = str(case["prompt"])
        expected = set(case["expected_skills"])  # type: ignore[arg-type]
        forbidden = set(case["forbidden_skills"])  # type: ignore[arg-type]
        predicted = list(predictor(prompt))  # type: ignore[operator]
        pred_set = set(predicted)

        matched = len(pred_set & expected)
        unexpected = len(pred_set - expected)
        forb_hit = len(pred_set & forbidden)

        p = (matched / len(pred_set)) if pred_set else (1.0 if not expected else 0.0)
        r = (matched / len(expected)) if expected else 1.0

        total_precision += p
        total_recall += r
        total_matched += matched
        total_predicted += len(pred_set)
        total_expected += len(expected)
        total_unexpected += unexpected
        if unexpected > 0:
            polluted_prompts += 1
        if forb_hit > 0:
            forbidden_hits += forb_hit
            forbidden_prompts += 1

    n = len(cases) or 1
    precision_at_k = round(total_precision / n, 4)
    recall_at_k = round(total_recall / n, 4)
    f1 = (
        round((2.0 * precision_at_k * recall_at_k) / (precision_at_k + recall_at_k), 4)
        if (precision_at_k + recall_at_k) > 0
        else 0.0
    )
    unexpected_prediction_rate = round(total_unexpected / total_predicted, 4) if total_predicted > 0 else 0.0
    prompt_pollution_rate = round(polluted_prompts / n, 4)
    forbidden_leak_rate = round(forbidden_prompts / n, 4)

    return {
        "precision_at_k": precision_at_k,
        "recall_at_k": recall_at_k,
        "f1": f1,
        "false_positive_rate": unexpected_prediction_rate,
        "unexpected_prediction_rate": unexpected_prediction_rate,
        "prompt_pollution_rate": prompt_pollution_rate,
        "forbidden_hits": forbidden_hits,
        "forbidden_leak_rate": forbidden_leak_rate,
        "matched_expected": total_matched,
        "total_predicted": total_predicted,
        "total_expected": total_expected,
    }


def benchmark_skill_routing(router: DecisionRouter | None = None, max_skills: int = 8) -> dict[str, object]:
    """Run live before-vs-after skill routing benchmark across 30 bilingual (18 EN + 12 CZ) prompts."""
    active_router = (
        router
        if (router is not None and router.enabled)
        else DecisionRouter(config={"enabled": True, "use_daemon": False}, enable_inproc=False)
    )

    legacy_metrics = _evaluate_router_predictions(
        BENCHMARK_ROUTING_PROMPTS,
        lambda txt: _legacy_select_skills(txt, max_skills=max_skills),
    )
    upgraded_metrics = _evaluate_router_predictions(
        BENCHMARK_ROUTING_PROMPTS,
        lambda txt: active_router.select_skills(txt, max_skills=max_skills),
    )

    per_prompt: list[dict[str, object]] = []
    for case in BENCHMARK_ROUTING_PROMPTS:
        prompt_text = str(case["prompt"])
        leg_pred = _legacy_select_skills(prompt_text, max_skills=max_skills)
        upg_pred = active_router.select_skills(prompt_text, max_skills=max_skills)
        forbidden = set(case["forbidden_skills"])  # type: ignore[arg-type]
        per_prompt.append(
            {
                "id": case["id"],
                "lang": case["lang"],
                "prompt": prompt_text,
                "expected_skills": case["expected_skills"],
                "forbidden_skills": case["forbidden_skills"],
                "legacy_predicted": leg_pred,
                "upgraded_predicted": upg_pred,
                "legacy_forbidden_leaks": sorted(set(leg_pred) & forbidden),
                "upgraded_forbidden_leaks": sorted(set(upg_pred) & forbidden),
            }
        )

    en_count = sum(1 for c in BENCHMARK_ROUTING_PROMPTS if c["lang"] == "en")
    cz_count = sum(1 for c in BENCHMARK_ROUTING_PROMPTS if c["lang"] == "cz")

    legacy_vocab = set(LEGACY_SKILL_CATALOG_KEYWORDS.keys())
    shared_cases = [
        c for c in BENCHMARK_ROUTING_PROMPTS
        if set(c["expected_skills"]).issubset(legacy_vocab)  # type: ignore[arg-type]
    ]
    shared_legacy = _evaluate_router_predictions(
        shared_cases,
        lambda txt: _legacy_select_skills(txt, max_skills=max_skills),
    )
    shared_upgraded = _evaluate_router_predictions(
        shared_cases,
        lambda txt: active_router.select_skills(txt, max_skills=max_skills),
    )

    return {
        "prompt_count": len(BENCHMARK_ROUTING_PROMPTS),
        "en_count": en_count,
        "cz_count": cz_count,
        "max_skills": max_skills,
        "opt_tokens": 0.0,
        "legacy": legacy_metrics,
        "upgraded": upgraded_metrics,
        "delta": {
            "precision_at_k": round(upgraded_metrics["precision_at_k"] - legacy_metrics["precision_at_k"], 4),  # type: ignore[operator]
            "recall_at_k": round(upgraded_metrics["recall_at_k"] - legacy_metrics["recall_at_k"], 4),  # type: ignore[operator]
            "f1": round(upgraded_metrics["f1"] - legacy_metrics["f1"], 4),  # type: ignore[operator]
            "false_positive_rate": round(upgraded_metrics["false_positive_rate"] - legacy_metrics["false_positive_rate"], 4),  # type: ignore[operator]
            "prompt_pollution_rate": round(upgraded_metrics["prompt_pollution_rate"] - legacy_metrics["prompt_pollution_rate"], 4),  # type: ignore[operator]
            "forbidden_hits": int(upgraded_metrics["forbidden_hits"]) - int(legacy_metrics["forbidden_hits"]),  # type: ignore[arg-type]
        },
        "shared_legacy_domain_subset": {
            "prompt_count": len(shared_cases),
            "legacy": shared_legacy,
            "upgraded": shared_upgraded,
            "delta": {
                "precision_at_k": round(shared_upgraded["precision_at_k"] - shared_legacy["precision_at_k"], 4),  # type: ignore[operator]
                "recall_at_k": round(shared_upgraded["recall_at_k"] - shared_legacy["recall_at_k"], 4),  # type: ignore[operator]
                "f1": round(shared_upgraded["f1"] - shared_legacy["f1"], 4),  # type: ignore[operator]
                "false_positive_rate": round(shared_upgraded["false_positive_rate"] - shared_legacy["false_positive_rate"], 4),  # type: ignore[operator]
                "prompt_pollution_rate": round(shared_upgraded["prompt_pollution_rate"] - shared_legacy["prompt_pollution_rate"], 4),  # type: ignore[operator]
                "forbidden_hits": int(shared_upgraded["forbidden_hits"]) - int(shared_legacy["forbidden_hits"]),  # type: ignore[arg-type]
            },
        },
        "per_prompt": per_prompt,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="System 1 Decision Router (Laya + Calibrated Fallback)")
    parser.add_argument(
        "--mode",
        choices=["preflight", "predict", "route-prompt", "select-skills", "triage-finding", "classify-scope", "judge-loop"],
        default="route-prompt",
    )
    parser.add_argument("--text", "--prompt", dest="text", type=str, default="", help="Input prompt or finding text")
    parser.add_argument("--json", type=str, default=None, help="JSON input payload")
    parser.add_argument("--max-skills", type=int, default=8, help="Maximum skills to return")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--compact", action="store_true", help="Output single-line deterministic JSON omitting volatile metrics for KV-cache stability")
    parser.add_argument("--enable", action="store_true", help="Enable System 1 Decision Router in config")
    parser.add_argument("--disable", action="store_true", help="Disable System 1 Decision Router in config")
    parser.add_argument("--status", action="store_true", help="Show current Decision Router status and configuration")
    parser.add_argument("--device-info", action="store_true", help="Print GPU/CPU device selection analysis")
    parser.add_argument("--preflight", action="store_true", help="Shorthand for --mode preflight")
    parser.add_argument("--benchmark-routing", action="store_true", help="Run 30-prompt bilingual skill routing benchmark (legacy vs upgraded)")
    parser.add_argument("--cue", type=str, default="", help="Lesson cue for scope classification")
    parser.add_argument("--rule", type=str, default="", help="Lesson rule for scope classification")
    parser.add_argument("--project", type=str, default=None, help="Project name for scope classification")
    args = parser.parse_args(argv)
    if args.preflight:
        args.mode = "preflight"

    if args.benchmark_routing:
        bench = benchmark_skill_routing(max_skills=args.max_skills)
        if args.compact:
            print(json.dumps(bench, separators=(",", ":"), sort_keys=True, ensure_ascii=False))
        else:
            print(json.dumps(bench, indent=2, ensure_ascii=False))
        return 0

    if args.disable:
        p = save_decision_config({"enabled": False})
        res = {
            "enabled": False,
            "status": "disabled",
            "config_path": str(p),
            "message": "Decision model disabled successfully",
        }
        if args.compact:
            print(json.dumps(res, separators=(",", ":"), sort_keys=True))
        else:
            print(json.dumps(res, indent=2))
        return 0

    if args.enable:
        p = save_decision_config({"enabled": True})
        res = {
            "enabled": True,
            "status": "enabled",
            "config_path": str(p),
            "message": "Decision model enabled successfully",
        }
        if args.compact:
            print(json.dumps(res, separators=(",", ":"), sort_keys=True))
        else:
            print(json.dumps(res, indent=2))
        return 0

    if args.status:
        cfg = load_decision_config()
        if args.compact:
            print(json.dumps(cfg, separators=(",", ":"), sort_keys=True))
        else:
            print(json.dumps(cfg, indent=2))
        return 0

    if args.device_info:
        dev_info = select_optimal_device()
        if args.compact and isinstance(dev_info, dict):
            dev_info = {k: v for k, v in dev_info.items() if k != "free_vram_mib"}
            print(json.dumps(dev_info, separators=(",", ":"), sort_keys=True))
        else:
            print(json.dumps(dev_info, indent=2))
        return 0

    raw_input_text = args.text
    if args.json:
        try:
            parsed = json.loads(args.json)
            if isinstance(parsed, dict):
                raw_input_text = parsed.get("text", parsed.get("prompt", parsed.get("finding", raw_input_text)))
            elif isinstance(parsed, str):
                raw_input_text = parsed
        except Exception as e:
            err = {"error": f"Malformed JSON input: {e}", "exit_code": 1}
            print(json.dumps(err))
            return 1

    router = DecisionRouter()

    if args.mode == "preflight":
        out = router.preflight()
    elif args.mode == "route-prompt":
        out = router.route_prompt(raw_input_text)
    elif args.mode == "select-skills":
        out = {"selected_skills": router.select_skills(raw_input_text, max_skills=args.max_skills)}
    elif args.mode == "triage-finding":
        out = router.triage_finding(raw_input_text)
    elif args.mode == "classify-scope":
        out = router.classify_lesson_scope(args.cue or raw_input_text, args.rule or "", project=args.project)
    elif args.mode == "judge-loop":
        out = router.judge_loop_digest(raw_input_text)
    else:  # predict
        out = router.predict(raw_input_text)

    # Stabilize device_info if compact requested (omit volatile free_vram_mib)
    if args.compact and isinstance(out, dict):
        out = dict(out)
        if isinstance(out.get("device_info"), dict):
            out["device_info"] = {
                k: v for k, v in out["device_info"].items() if k != "free_vram_mib"
            }
        print(json.dumps(out, separators=(",", ":"), sort_keys=True, ensure_ascii=False))
    elif args.format == "json":
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
