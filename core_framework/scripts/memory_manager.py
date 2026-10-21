#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Obsidian Self-Learning Memory & Project Knowledge Engine for Antigravity Swarm Coordinator.

Manages the persistent local Obsidian Knowledge Vault (~/Documents/AgentMemory or $OBSIDIAN_VAULT_PATH):
  - Initializes the vault with Obsidian Flavored Markdown, wikilinks, and .obsidian graph configuration.
  - Registers the vault in Obsidian's desktop configuration (obsidian.json) across Windows, macOS, and Linux.
  - Automatically indexes project repositories (tech stack, architecture, components, entrypoints) into projects/<name>/.
  - Continuously records self-learning engineering lessons (--record-lesson) from user corrections and bug fixes.
  - Continuously records personal, company, presentation, and coding preferences (--record-preference).
  - Updates project-specific architecture/decision notes (--update-project-note).
  - Performs fast pre-task context recall (--recall) across profile, domain preferences, global lessons, and project notes.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

IGNORE_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    "coverage",
    ".agent-workspace",
    ".asw",
})


def resolve_vault_dir(vault_dir: Path | str | None = None, home_dir: Path | None = None) -> Path:
    """Resolve the Obsidian Knowledge Vault path without hardcoded user paths."""
    if vault_dir is not None and str(vault_dir).strip():
        return Path(vault_dir).expanduser().resolve()
    env_vault = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_vault and env_vault.strip():
        return Path(env_vault).expanduser().resolve()
    base_home = home_dir.expanduser().resolve() if home_dir else Path.home()
    return (base_home / "Documents" / "AgentMemory").resolve()


def resolve_obsidian_config_path(
    obsidian_config: Path | str | None = None, home_dir: Path | None = None
) -> Path:
    """Resolve the platform-specific Obsidian global configuration file (obsidian.json)."""
    if obsidian_config is not None and str(obsidian_config).strip():
        return Path(obsidian_config).expanduser().resolve()
    base_home = home_dir.expanduser().resolve() if home_dir else Path.home()
    sys_name = platform.system().lower()
    if sys_name == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata and home_dir is None:
            return Path(appdata) / "obsidian" / "obsidian.json"
        return base_home / "AppData" / "Roaming" / "obsidian" / "obsidian.json"
    if sys_name == "darwin":
        return base_home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    return base_home / ".config" / "obsidian" / "obsidian.json"


def register_vault_in_obsidian(
    vault_dir: Path,
    obsidian_config: Path | str | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Register the AgentMemory vault in Obsidian's obsidian.json so it opens automatically."""
    cfg_path = resolve_obsidian_config_path(obsidian_config, home_dir=home_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {"vaults": {}}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
                if not isinstance(data.get("vaults"), dict):
                    data["vaults"] = {}
        except Exception:
            data = {"vaults": {}}

    resolved_vault = str(vault_dir.resolve())
    vault_id = hashlib.sha256(resolved_vault.encode("utf-8")).hexdigest()[:16]

    # Check if path is already registered under any key
    existing_id = None
    for k, v in data["vaults"].items():
        if isinstance(v, dict) and v.get("path") == resolved_vault:
            existing_id = k
            break

    target_key = existing_id or vault_id
    data["vaults"][target_key] = {
        "path": resolved_vault,
        "ts": int(time.time() * 1000),
        "open": True,
    }
    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    return cfg_path


def discover_obsidian_binary(home_dir: Path | None = None) -> str | None:
    """Check whether the Obsidian desktop application is installed on the host."""
    base_home = home_dir.expanduser().resolve() if home_dir else Path.home()
    sys_name = platform.system().lower()

    candidates: list[Path] = []
    if sys_name == "windows":
        local_app = os.environ.get("LOCALAPPDATA")
        prog_files = os.environ.get("PROGRAMFILES")
        if local_app and home_dir is None:
            candidates.append(Path(local_app) / "Programs" / "Obsidian" / "Obsidian.exe")
            candidates.append(Path(local_app) / "Obsidian" / "Obsidian.exe")
        candidates.append(base_home / "AppData" / "Local" / "Programs" / "Obsidian" / "Obsidian.exe")
        if prog_files:
            candidates.append(Path(prog_files) / "Obsidian" / "Obsidian.exe")
    elif sys_name == "darwin":
        candidates.append(Path("/Applications/Obsidian.app/Contents/MacOS/Obsidian"))
        candidates.append(base_home / "Applications" / "Obsidian.app" / "Contents" / "MacOS" / "Obsidian")
    else:
        for p in ("/usr/bin/obsidian", "/usr/local/bin/obsidian", "/snap/bin/obsidian"):
            candidates.append(Path(p))

    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def ensure_obsidian_installed(home_dir: Path | None = None, attempt_install: bool = False) -> dict[str, object]:
    """Check for Obsidian binary and optionally install via native package manager (winget/brew)."""
    binary = discover_obsidian_binary(home_dir=home_dir)
    if binary:
        return {"installed": True, "binary": binary, "installed_now": False}

    if not attempt_install:
        return {"installed": False, "binary": None, "installed_now": False}

    sys_name = platform.system().lower()
    try:
        if sys_name == "windows":
            subprocess.run(
                [
                    "winget",
                    "install",
                    "--id",
                    "Obsidian.Obsidian",
                    "-e",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--silent",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        elif sys_name == "darwin":
            subprocess.run(
                ["brew", "install", "--cask", "obsidian"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
    except Exception:
        pass

    binary_after = discover_obsidian_binary(home_dir=home_dir)
    return {
        "installed": bool(binary_after),
        "binary": binary_after,
        "installed_now": bool(binary_after),
    }


def init_vault(
    vault_dir: Path | str | None = None,
    obsidian_config: Path | str | None = None,
    home_dir: Path | None = None,
) -> dict[str, object]:
    """Idempotently initialize the local Obsidian Knowledge Vault structure and .obsidian config."""
    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    today = datetime.date.today().isoformat()

    for sub in (".obsidian", "todos", "profile", "domains", "lessons", "projects", "sessions", "patterns"):
        (v_dir / sub).mkdir(parents=True, exist_ok=True)

    # .obsidian configuration files for immediate rich graph view
    obs_dir = v_dir / ".obsidian"
    app_json = obs_dir / "app.json"
    if not app_json.is_file():
        app_json.write_text(
            json.dumps(
                {
                    "alwaysUpdateLinks": True,
                    "showFrontmatter": True,
                    "strictLineBreaks": False,
                    "useMarkdownLinks": False,
                },
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )

    appearance_json = obs_dir / "appearance.json"
    if not appearance_json.is_file():
        appearance_json.write_text(
            json.dumps({"theme": "obsidian", " accentColor": "#7c3aed"}, indent=2),
            encoding="utf-8",
            newline="\n",
        )

    core_plugins_json = obs_dir / "core-plugins.json"
    if not core_plugins_json.is_file():
        core_plugins_json.write_text(
            json.dumps(
                [
                    "file-explorer",
                    "global-search",
                    "switcher",
                    "graph",
                    "backlink",
                    "outgoing-link",
                    "tag-pane",
                    "page-preview",
                    "command-palette",
                    "outline",
                ],
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )

    graph_json = obs_dir / "graph.json"
    if not graph_json.is_file():
        graph_json.write_text(
            json.dumps(
                {
                    "collapse-filter": False,
                    "search": "",
                    "showTags": True,
                    "showAttachments": False,
                    "hideUnresolved": False,
                    "showOrphans": True,
                    "colorGroups": [
                        {"query": "tag:#profile", "color": {"a": 1, "rgb": 16761095}},
                        {"query": "tag:#domain", "color": {"a": 1, "rgb": 3715806}},
                        {"query": "tag:#lesson", "color": {"a": 1, "rgb": 15684432}},
                        {"query": "tag:#project", "color": {"a": 1, "rgb": 5025616}},
                        {"query": "tag:#architecture", "color": {"a": 1, "rgb": 10181046}},
                        {"query": "tag:#adr", "color": {"a": 1, "rgb": 16750848}},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )

    templates: dict[Path, str] = {
        v_dir / "Home.md": (
            f"---\n"
            f"tags: [home, index, memory]\n"
            f"type: index\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# Antigravity Swarm Knowledge Vault\n\n"
            f"Central self-learning memory and cross-project knowledge graph for **Antigravity Swarm Coordinator**.\n\n"
            f"## Core Memory Pillars\n"
            f"- [[profile/User and Company Profile|User & Company Profile]]\n"
            f"- [[domains/Presentations and Visual Style|Presentations & Visual Style Preferences]]\n"
            f"- [[domains/Coding and Architecture Preferences|Coding & Architecture Preferences]]\n"
            f"- [[lessons/Engineering Lessons and Anti-Patterns|Self-Learning Engineering Lessons & Anti-Patterns]]\n"
            f"- [[todos/Active TODOs|Active TODOs]]\n\n"
            f"## Indexed Projects\n"
        ),
        v_dir / "todos" / "Active TODOs.md": (
            f"---\n"
            f"tags: [todos, active]\n"
            f"type: todos\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# Active TODOs\n\n"
            f"## Global & Cross-Project Tasks\n"
            f"- [x] Initialize Obsidian Self-Learning Knowledge Vault (`AgentMemory`)\n"
        ),
        v_dir / "profile" / "User and Company Profile.md": (
            f"---\n"
            f"tags: [profile, identity, company]\n"
            f"type: profile\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# User and Company Profile\n\n"
            f"Persistent context about the user, company, brand positioning, and communication preferences.\n"
            f"Linked from [[Home|Vault Home]].\n\n"
            f"## Communication & Workflow Preferences\n"
            f"- **Primary Conversation Language**: Czech (with technical identifiers and repository artifacts in English unless requested otherwise).\n"
            f"- **Orchestration Standard**: Tri-Model Cross-Family Routing (`Gemini 4 Argon High` for research/planning, `Claude Opus 5.5` for adversarial plan & diff audit, `Gemini 3.8 Flash High` for bounded implementation).\n\n"
            f"## Recorded Profile & Company Facts\n"
        ),
        v_dir / "domains" / "Presentations and Visual Style.md": (
            f"---\n"
            f"tags: [domain, presentations, design, slides]\n"
            f"type: domain\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# Presentations and Visual Style\n\n"
            f"Persistent preferences for slide decks (`pptx-official`, `frontend-slides`), executive presentations, visual hierarchy, and branding.\n"
            f"Linked from [[Home|Vault Home]] and [[profile/User and Company Profile|User Profile]].\n\n"
            f"## Recorded Presentation & Style Rules\n"
        ),
        v_dir / "domains" / "Coding and Architecture Preferences.md": (
            f"---\n"
            f"tags: [domain, coding, architecture, standards]\n"
            f"type: domain\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# Coding and Architecture Preferences\n\n"
            f"Cross-project software engineering conventions, preferred libraries, and architectural standards.\n"
            f"Linked from [[Home|Vault Home]].\n\n"
            f"## Core Engineering Standards\n"
            f"- **Path Independence**: Never hardcode user-specific home paths in scripts, configs, or tests; always resolve dynamically via `Path.home()` or environment variables.\n"
            f"- **3-Layer Functional Verification**: Every behavior-changing task requires static/type pass, automated happy + negative/edge tests, and real-surface execution proof.\n\n"
            f"## Recorded Coding Preferences\n"
        ),
        v_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md": (
            f"---\n"
            f"tags: [lesson, self-learning, anti-patterns]\n"
            f"type: lessons\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# Engineering Lessons and Anti-Patterns\n\n"
            f"Self-learning ledger of mistakes, user corrections, and regression traps across all projects. The Swarm Coordinator (`Gemini 4 Argon High`) and Opposition Reviewer (`Claude Opus 5.5`) inspect this ledger before planning and reviewing work so no mistake is ever repeated.\n"
            f"Linked from [[Home|Vault Home]].\n\n"
            f"## Active Lessons\n\n"
            f"### [{today}] Skill YAML Frontmatter & BOM Hygiene\n"
            f"- **Cue (When)**: Creating, importing, or updating any `SKILL.md` file in `.antigravity/skills`, `core_framework/skills`, `plugins/`, or global skill folders.\n"
            f"- **Mistake / User Correction**: Leaving `SKILL.md` files without a `--- name / description ---` YAML frontmatter block or with UTF-8 BOM causes Antigravity to fail loading customizations.\n"
            f"- **Mandatory Rule**: Every `SKILL.md` must start with a valid `---\\nname: <slug>\\ndescription: <15..120 char single-line summary>\\n---` header encoded in UTF-8 without BOM.\n\n"
            f"### [{today}] Cross-Platform Path Independence\n"
            f"- **Cue (When)**: Writing Python, PowerShell, Bash, or configuration files intended for Git repositories.\n"
            f"- **Mistake / User Correction**: Hardcoding user home paths breaks portability for other users and across Windows/macOS/Linux.\n"
            f"- **Mandatory Rule**: Always use `Path.home()`, `$HOME`, `$env:USERPROFILE`, or repository-relative paths (`Path(__file__).resolve().parent`).\n"
        ),
    }

    created_files: list[str] = []
    for file_path, content in templates.items():
        if not file_path.is_file():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8", newline="\n")
            created_files.append(str(file_path.relative_to(v_dir)))

    obs_cfg_path = register_vault_in_obsidian(v_dir, obsidian_config=obsidian_config, home_dir=home_dir)

    return {
        "vault_dir": str(v_dir),
        "obsidian_config": str(obs_cfg_path),
        "created_files": created_files,
    }


def _detect_project_metadata(project_path: Path) -> dict[str, object]:
    """Scan a project directory to extract summary, tech stack, key directories, and components."""
    name = project_path.resolve().name
    readme_summary = "No README summary extracted."
    for r_name in ("README.md", "readme.md", "README.rst", "README.txt"):
        r_file = project_path / r_name
        if r_file.is_file():
            try:
                raw = r_file.read_text(encoding="utf-8", errors="replace")
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("![")]
                if lines:
                    readme_summary = lines[0][:300]
            except Exception:
                pass
            break

    tech_stack: list[str] = []
    req_txt = ""
    for dep_file in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
        p = project_path / dep_file
        if p.is_file():
            if "Python" not in tech_stack:
                tech_stack.append("Python")
            try:
                req_txt += "\n" + p.read_text(encoding="utf-8", errors="replace").lower()
            except Exception:
                pass

    py_frameworks = [
        ("fastapi", "FastAPI"),
        ("pydantic", "Pydantic"),
        ("sqlalchemy", "SQLAlchemy"),
        ("uvicorn", "Uvicorn"),
        ("pytest", "Pytest"),
        ("django", "Django"),
        ("flask", "Flask"),
        ("polars", "Polars"),
        ("pandas", "Pandas"),
        ("scikit-learn", "Scikit-Learn"),
        ("torch", "PyTorch"),
    ]
    for marker, label in py_frameworks:
        if marker in req_txt and label not in tech_stack:
            tech_stack.append(label)

    pkg_json = project_path / "package.json"
    if pkg_json.is_file() or (project_path / "frontend" / "package.json").is_file():
        tech_stack.append("Node.js / TypeScript")
        for pj in (pkg_json, project_path / "frontend" / "package.json"):
            if pj.is_file():
                try:
                    ptxt = pj.read_text(encoding="utf-8", errors="replace").lower()
                    for marker, label in (
                        ("react", "React"),
                        ("next", "Next.js"),
                        ("vite", "Vite"),
                        ("tailwind", "Tailwind CSS"),
                        ("playwright", "Playwright"),
                        ("vitest", "Vitest"),
                    ):
                        if marker in ptxt and label not in tech_stack:
                            tech_stack.append(label)
                except Exception:
                    pass

    if (project_path / "docker-compose.yml").is_file() or (project_path / "Dockerfile").is_file() or list(project_path.glob("Dockerfile*")):
        tech_stack.append("Docker")
    if (project_path / "Cargo.toml").is_file():
        tech_stack.append("Rust")
    if (project_path / "go.mod").is_file():
        tech_stack.append("Go")
    if (project_path / ".antigravity").is_dir():
        tech_stack.append("Antigravity Swarm Governance")

    if not tech_stack:
        # Infer from file extensions
        exts = {f.suffix.lower() for f in project_path.glob("*/*") if f.is_file()}
        if ".py" in exts:
            tech_stack.append("Python")
        if ".ts" in exts or ".tsx" in exts:
            tech_stack.append("TypeScript")

    top_dirs: list[str] = []
    entrypoints: list[str] = []
    components: list[dict[str, str]] = []

    for item in sorted(project_path.iterdir()):
        if item.name in IGNORE_DIRS or item.name.startswith(".git"):
            continue
        if item.is_dir():
            file_count = sum(1 for _ in item.rglob("*") if _.is_file() and not any(p in IGNORE_DIRS for p in _.parts))
            top_dirs.append(f"`{item.name}/` ({file_count} files)")
            # Collect top-level modules inside key directories
            for sub in sorted(item.iterdir()):
                if sub.is_file() and sub.suffix in (".py", ".ts", ".tsx", ".rs", ".go", ".sh", ".ps1") and sub.name != "__init__.py":
                    if len(components) < 30:
                        components.append({
                            "path": f"{item.name}/{sub.name}",
                            "role": f"Module in `{item.name}/`",
                        })
        elif item.is_file():
            if item.name in (
                "install.py",
                "install.ps1",
                "install.sh",
                "main.py",
                "app.py",
                "manage.py",
                "start.ps1",
                "start.bat",
                "docker-compose.yml",
                "Makefile",
                "pyproject.toml",
                "package.json",
            ):
                entrypoints.append(f"`{item.name}`")

    return {
        "name": name,
        "summary": readme_summary,
        "tech_stack": tech_stack or ["General Software Repository"],
        "top_dirs": top_dirs,
        "entrypoints": entrypoints,
        "components": components,
    }


def index_project(
    project_path: Path | str,
    vault_dir: Path | str | None = None,
    project_name: str | None = None,
    home_dir: Path | None = None,
) -> dict[str, object]:
    """Scan a project repository and create/update its structured notes in the Obsidian Vault."""
    proj_dir = Path(project_path).expanduser().resolve()
    if not proj_dir.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {proj_dir}")

    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    init_vault(v_dir, home_dir=home_dir)

    meta = _detect_project_metadata(proj_dir)
    p_name = (project_name.strip() if project_name and project_name.strip() else str(meta["name"]))
    today = datetime.date.today().isoformat()

    proj_vault_dir = v_dir / "projects" / p_name
    proj_vault_dir.mkdir(parents=True, exist_ok=True)

    overview_file = proj_vault_dir / f"{p_name}.md"
    arch_file = proj_vault_dir / "Architecture and Components.md"
    decisions_file = proj_vault_dir / "Decision Ledger.md"
    lessons_file = proj_vault_dir / "Project Lessons.md"

    # Preserve custom notes section if overview already exists
    custom_notes = ""
    if overview_file.is_file():
        old_txt = overview_file.read_text(encoding="utf-8", errors="replace")
        m_custom = re.search(r"(## Custom Notes & Context\s*\n.*)", old_txt, re.DOTALL)
        if m_custom:
            custom_notes = m_custom.group(1).strip() + "\n"

    if not custom_notes:
        custom_notes = "## Custom Notes & Context\n- Project indexed automatically by Antigravity Swarm Coordinator.\n"

    stack_bullets = "\n".join(f"- {s}" for s in meta["tech_stack"])
    dir_bullets = "\n".join(f"- {d}" for d in meta["top_dirs"]) if meta["top_dirs"] else "- Root-level files"
    entry_bullets = "\n".join(f"- {e}" for e in meta["entrypoints"]) if meta["entrypoints"] else "- Standard repository scripts"

    overview_content = (
        f"---\n"
        f"tags: [project, project/{p_name}]\n"
        f"type: project\n"
        f"project: \"[[projects/{p_name}/{p_name}|{p_name}]]\"\n"
        f"updated: {today}\n"
        f"---\n\n"
        f"# Project: {p_name}\n\n"
        f"**Summary**: {meta['summary']}\n\n"
        f"## Knowledge Graph Links\n"
        f"- [[Home|Vault Home]]\n"
        f"- [[projects/{p_name}/Architecture and Components|{p_name} — Architecture & Components]]\n"
        f"- [[projects/{p_name}/Decision Ledger|{p_name} — Decision Ledger (ADRs)]]\n"
        f"- [[projects/{p_name}/Project Lessons|{p_name} — Project Lessons & Gotchas]]\n"
        f"- [[lessons/Engineering Lessons and Anti-Patterns|Global Engineering Lessons]]\n\n"
        f"## Tech Stack & Frameworks\n"
        f"{stack_bullets}\n\n"
        f"## Key Directories\n"
        f"{dir_bullets}\n\n"
        f"## Canonical Entrypoints & Configs\n"
        f"{entry_bullets}\n\n"
        f"{custom_notes}"
    )
    overview_file.write_text(overview_content, encoding="utf-8", newline="\n")

    # Architecture and Components note
    comp_lines = [f"- `{c['path']}` — {c['role']}" for c in meta["components"]]
    if not comp_lines:
        comp_lines = ["- Top-level repository scripts and modules."]

    existing_arch_notes = ""
    if arch_file.is_file():
        old_arch = arch_file.read_text(encoding="utf-8", errors="replace")
        m_arch = re.search(r"(## Recorded Component Notes\s*\n.*)", old_arch, re.DOTALL)
        if m_arch:
            existing_arch_notes = m_arch.group(1).strip() + "\n"
    if not existing_arch_notes:
        existing_arch_notes = "## Recorded Component Notes\n"

    arch_content = (
        f"---\n"
        f"tags: [architecture, components, project/{p_name}]\n"
        f"type: architecture\n"
        f"project: \"[[projects/{p_name}/{p_name}|{p_name}]]\"\n"
        f"updated: {today}\n"
        f"---\n\n"
        f"# {p_name} — Architecture and Components\n\n"
        f"Parent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n"
        f"## Discovered Modules & Boundaries\n"
        + "\n".join(comp_lines)
        + f"\n\n{existing_arch_notes}"
    )
    arch_file.write_text(arch_content, encoding="utf-8", newline="\n")

    # Decision Ledger (preserve if exists)
    if not decisions_file.is_file():
        decisions_file.write_text(
            f"---\n"
            f"tags: [adr, decisions, project/{p_name}]\n"
            f"type: adr\n"
            f"project: \"[[projects/{p_name}/{p_name}|{p_name}]]\"\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# {p_name} — Decision Ledger (ADRs)\n\n"
            f"Parent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n"
            f"## Architectural Decisions\n",
            encoding="utf-8",
            newline="\n",
        )

    # Project Lessons (preserve if exists)
    if not lessons_file.is_file():
        lessons_file.write_text(
            f"---\n"
            f"tags: [lesson, gotchas, project/{p_name}]\n"
            f"type: lessons\n"
            f"project: \"[[projects/{p_name}/{p_name}|{p_name}]]\"\n"
            f"created: {today}\n"
            f"---\n\n"
            f"# {p_name} — Project Lessons & Regression Traps\n\n"
            f"Parent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n"
            f"Global Ledger: [[lessons/Engineering Lessons and Anti-Patterns|Global Engineering Lessons]]\n\n"
            f"## Project-Specific Lessons\n",
            encoding="utf-8",
            newline="\n",
        )

    # Link project in Home.md if not already linked
    home_file = v_dir / "Home.md"
    if home_file.is_file():
        home_txt = home_file.read_text(encoding="utf-8", errors="replace")
        link_line = f"- [[projects/{p_name}/{p_name}|{p_name}]] — {meta['summary']}"
        if f"[[projects/{p_name}/{p_name}" not in home_txt:
            home_txt = home_txt.rstrip() + f"\n{link_line}\n"
            home_file.write_text(home_txt, encoding="utf-8", newline="\n")

    return {
        "project": p_name,
        "vault_project_dir": str(proj_vault_dir),
        "tech_stack": meta["tech_stack"],
        "files_written": [
            str(overview_file),
            str(arch_file),
            str(decisions_file),
            str(lessons_file),
        ],
    }


def record_preference(
    *,
    vault_dir: Path | str | None = None,
    category: str,
    topic: str,
    preference: str,
    home_dir: Path | None = None,
) -> Path:
    """Record a persistent user, company, presentation, or coding preference in the Obsidian Vault."""
    cat = (category or "").strip().lower()
    top = (topic or "").strip()
    pref = (preference or "").strip()
    if not top or not pref:
        raise ValueError("Both --topic and --preference must be non-empty.")

    category_map = {
        "profile": ("profile", "User and Company Profile.md"),
        "company": ("profile", "User and Company Profile.md"),
        "presentations": ("domains", "Presentations and Visual Style.md"),
        "slides": ("domains", "Presentations and Visual Style.md"),
        "coding": ("domains", "Coding and Architecture Preferences.md"),
        "architecture": ("domains", "Coding and Architecture Preferences.md"),
        "domain": ("domains", "Coding and Architecture Preferences.md"),
    }
    if cat not in category_map:
        raise ValueError(f"Unsupported category '{category}'. Choose from: {sorted(category_map.keys())}")

    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    init_vault(v_dir, home_dir=home_dir)

    subdir, fname = category_map[cat]
    target_file = v_dir / subdir / fname
    today = datetime.date.today().isoformat()
    entry = f"\n### [{today}] {top}\n- {pref}\n"

    existing = target_file.read_text(encoding="utf-8", errors="replace") if target_file.is_file() else ""
    if pref not in existing:
        target_file.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8", newline="\n")
    return target_file


def record_lesson(
    *,
    vault_dir: Path | str | None = None,
    cue: str,
    mistake: str,
    rule: str,
    project: str | None = None,
    home_dir: Path | None = None,
) -> list[Path]:
    """Record a self-learning engineering lesson from a user correction or bug fix."""
    c_str = (cue or "").strip()
    m_str = (mistake or "").strip()
    r_str = (rule or "").strip()
    if not c_str or not m_str or not r_str:
        raise ValueError("--cue, --mistake, and --rule must all be non-empty.")

    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    init_vault(v_dir, home_dir=home_dir)

    today = datetime.date.today().isoformat()
    proj_tag = f" (Project: [[projects/{project.strip()}/{project.strip()}|{project.strip()}]])" if project and project.strip() else ""
    block = (
        f"\n### [{today}] {c_str[:80]}\n"
        f"- **Cue (When)**: {c_str}{proj_tag}\n"
        f"- **Mistake / User Correction**: {m_str}\n"
        f"- **Mandatory Rule**: {r_str}\n"
    )

    updated_files: list[Path] = []
    global_lessons = v_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md"
    g_txt = global_lessons.read_text(encoding="utf-8", errors="replace")
    if r_str not in g_txt:
        global_lessons.write_text(g_txt.rstrip() + "\n" + block, encoding="utf-8", newline="\n")
    updated_files.append(global_lessons)

    if project and project.strip():
        p_name = project.strip()
        proj_lessons = v_dir / "projects" / p_name / "Project Lessons.md"
        if not proj_lessons.is_file():
            proj_lessons.parent.mkdir(parents=True, exist_ok=True)
            proj_lessons.write_text(
                f"---\n"
                f"tags: [lesson, gotchas, project/{p_name}]\n"
                f"type: lessons\n"
                f"project: \"[[projects/{p_name}/{p_name}|{p_name}]]\"\n"
                f"created: {today}\n"
                f"---\n\n"
                f"# {p_name} — Project Lessons & Regression Traps\n\n"
                f"Parent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n"
                f"## Project-Specific Lessons\n",
                encoding="utf-8",
                newline="\n",
            )
        p_txt = proj_lessons.read_text(encoding="utf-8", errors="replace")
        if r_str not in p_txt:
            proj_lessons.write_text(p_txt.rstrip() + "\n" + block, encoding="utf-8", newline="\n")
        updated_files.append(proj_lessons)

    return updated_files


def update_project_note(
    *,
    vault_dir: Path | str | None = None,
    project: str,
    section: str,
    title: str,
    content: str,
    home_dir: Path | None = None,
) -> Path:
    """Append an architectural update, ADR decision, or component note to a project's Obsidian folder."""
    p_name = (project or "").strip()
    sec = (section or "").strip().lower()
    t_str = (title or "").strip()
    c_str = (content or "").strip()
    if not p_name or not t_str or not c_str:
        raise ValueError("--project, --title, and --content must be non-empty.")

    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    init_vault(v_dir, home_dir=home_dir)

    proj_dir = v_dir / "projects" / p_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    if sec in ("decision", "adr"):
        target = proj_dir / "Decision Ledger.md"
        header = f"# {p_name} — Decision Ledger (ADRs)\n\nParent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n## Architectural Decisions\n"
    elif sec in ("lesson", "gotcha"):
        target = proj_dir / "Project Lessons.md"
        header = f"# {p_name} — Project Lessons & Regression Traps\n\nParent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n## Project-Specific Lessons\n"
    elif sec in ("architecture", "component"):
        target = proj_dir / "Architecture and Components.md"
        header = f"# {p_name} — Architecture and Components\n\nParent Project: [[projects/{p_name}/{p_name}|{p_name}]]\n\n## Recorded Component Notes\n"
    else:
        target = proj_dir / f"{p_name}.md"
        header = f"# Project: {p_name}\n\n## Custom Notes & Context\n"

    if not target.is_file():
        target.write_text(
            f"---\ntags: [project, project/{p_name}]\ntype: {sec}\ncreated: {today}\n---\n\n{header}",
            encoding="utf-8",
            newline="\n",
        )

    existing = target.read_text(encoding="utf-8", errors="replace")
    entry = f"\n### [{today}] {t_str}\n{c_str}\n"
    if c_str not in existing:
        target.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8", newline="\n")
    return target


def recall_context(
    *,
    vault_dir: Path | str | None = None,
    project: str | None = None,
    project_path: Path | str | None = None,
    task_type: str = "general",
    home_dir: Path | None = None,
) -> str:
    """Assemble a compact, high-signal pre-task memory bundle from the Obsidian Vault."""
    v_dir = resolve_vault_dir(vault_dir, home_dir=home_dir)
    init_vault(v_dir, home_dir=home_dir)

    resolved_project_name = project.strip() if project and project.strip() else None
    if project_path is not None and str(project_path).strip():
        p_path = Path(project_path).expanduser().resolve()
        if p_path.is_dir():
            resolved_project_name = resolved_project_name or p_path.name
            if not (v_dir / "projects" / resolved_project_name / f"{resolved_project_name}.md").is_file():
                index_project(p_path, vault_dir=v_dir, project_name=resolved_project_name, home_dir=home_dir)

    sections: list[str] = [
        f"# Antigravity Swarm Memory Recall (`{v_dir}`)",
    ]

    # 1. User & Company Profile
    profile_f = v_dir / "profile" / "User and Company Profile.md"
    if profile_f.is_file():
        sections.append("## 1. User & Company Profile\n" + profile_f.read_text(encoding="utf-8", errors="replace").strip())

    # 2. Domain Preferences
    t_type = (task_type or "general").strip().lower()
    if t_type in ("presentation", "slides", "general", "all", "ui"):
        pres_f = v_dir / "domains" / "Presentations and Visual Style.md"
        if pres_f.is_file():
            sections.append("## 2A. Presentations & Visual Style\n" + pres_f.read_text(encoding="utf-8", errors="replace").strip())
    if t_type in ("code", "general", "all", "research", "presentation"):
        code_f = v_dir / "domains" / "Coding and Architecture Preferences.md"
        if code_f.is_file():
            sections.append("## 2B. Coding & Architecture Preferences\n" + code_f.read_text(encoding="utf-8", errors="replace").strip())

    # 3. Global Engineering Lessons
    lessons_f = v_dir / "lessons" / "Engineering Lessons and Anti-Patterns.md"
    if lessons_f.is_file():
        sections.append("## 3. Global Engineering Lessons & Anti-Patterns\n" + lessons_f.read_text(encoding="utf-8", errors="replace").strip())

    # 4. Project Context
    if resolved_project_name:
        p_dir = v_dir / "projects" / resolved_project_name
        if p_dir.is_dir():
            for fname in (
                f"{resolved_project_name}.md",
                "Architecture and Components.md",
                "Decision Ledger.md",
                "Project Lessons.md",
            ):
                pf = p_dir / fname
                if pf.is_file():
                    sections.append(f"## 4. Project Memory — `{fname}`\n" + pf.read_text(encoding="utf-8", errors="replace").strip())

    return "\n\n---\n\n".join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Obsidian Self-Learning Memory & Project Knowledge Engine")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Override Obsidian Vault directory")
    parser.add_argument("--obsidian-config", type=Path, default=None, help="Override obsidian.json path")
    parser.add_argument("--init-vault", action="store_true", help="Initialize the local Obsidian Knowledge Vault")
    parser.add_argument("--ensure-obsidian", action="store_true", help="Check/install Obsidian desktop binary")
    parser.add_argument("--index-project", type=Path, default=None, help="Scan and index a project repository into the vault")
    parser.add_argument("--project-name", type=str, default=None, help="Explicit project name override")
    parser.add_argument("--record-preference", action="store_true", help="Record a user/company/domain preference")
    parser.add_argument("--category", type=str, default="profile", help="Preference category: profile, presentations, coding")
    parser.add_argument("--topic", type=str, default="", help="Preference topic heading")
    parser.add_argument("--preference", type=str, default="", help="Preference rule or fact to store")
    parser.add_argument("--record-lesson", action="store_true", help="Record a self-learning lesson from a correction or bug fix")
    parser.add_argument("--cue", type=str, default="", help="Trigger condition / when this lesson applies")
    parser.add_argument("--mistake", type=str, default="", help="What went wrong or what the user corrected")
    parser.add_argument("--rule", type=str, default="", help="Mandatory rule to follow in the future")
    parser.add_argument("--project", type=str, default=None, help="Project name associated with the lesson or recall")
    parser.add_argument("--update-project-note", action="store_true", help="Update a project's architecture, decision, or lesson note")
    parser.add_argument("--section", type=str, default="decision", help="Target section: decision, architecture, lesson, summary")
    parser.add_argument("--title", type=str, default="", help="Entry title")
    parser.add_argument("--content", type=str, default="", help="Entry markdown content")
    parser.add_argument("--recall", action="store_true", help="Output assembled pre-task memory context")
    parser.add_argument("--project-path", type=Path, default=None, help="Project path to auto-index and recall")
    parser.add_argument("--task-type", type=str, default="general", help="Task type: code, presentation, research, general")

    args = parser.parse_args()

    try:
        if args.init_vault:
            res = init_vault(vault_dir=args.vault_dir, obsidian_config=args.obsidian_config)
            print(json.dumps(res, indent=2))
            return 0

        if args.ensure_obsidian:
            res = ensure_obsidian_installed(attempt_install=True)
            print(json.dumps(res, indent=2))
            return 0

        if args.index_project is not None:
            res = index_project(
                args.index_project,
                vault_dir=args.vault_dir,
                project_name=args.project_name,
            )
            print(json.dumps(res, indent=2))
            return 0

        if args.record_preference:
            out_path = record_preference(
                vault_dir=args.vault_dir,
                category=args.category,
                topic=args.topic,
                preference=args.preference,
            )
            print(json.dumps({"status": "recorded", "file": str(out_path)}, indent=2))
            return 0

        if args.record_lesson:
            out_paths = record_lesson(
                vault_dir=args.vault_dir,
                cue=args.cue,
                mistake=args.mistake,
                rule=args.rule,
                project=args.project,
            )
            print(json.dumps({"status": "recorded", "files": [str(p) for p in out_paths]}, indent=2))
            return 0

        if args.update_project_note:
            out_path = update_project_note(
                vault_dir=args.vault_dir,
                project=args.project or "",
                section=args.section,
                title=args.title,
                content=args.content,
            )
            print(json.dumps({"status": "updated", "file": str(out_path)}, indent=2))
            return 0

        if args.recall:
            out_md = recall_context(
                vault_dir=args.vault_dir,
                project=args.project,
                project_path=args.project_path,
                task_type=args.task_type,
            )
            sys.stdout.write(out_md)
            return 0

        parser.print_help()
        return 0
    except (ValueError, FileNotFoundError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
