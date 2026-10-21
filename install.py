#!/usr/bin/env python3
"""Universal Cross-Platform Installer for Antigravity Swarm Coordinator (macOS, Windows, Linux).

Installs:
  1. Global entry point prompt (~/.gemini/GEMINI.md and ~/.agents/AGENTS.md)
  2. All 200 curated Multi-Domain Golden Catalog skills (~/.gemini/config/skills,
     ~/.gemini/antigravity-ide/skills, and ~/.agents/skills)
  3. Antigravity Swarm (ASW) plugin and Claude Opus 5.5 subagent TOMLs
     (~/.gemini/config/plugins/antigravity-swarm)
  4. Enforced local Obsidian Self-Learning Knowledge Vault (~/Documents/AgentMemory or $OBSIDIAN_VAULT_PATH),
     registered in Obsidian's obsidian.json config, with automatic project indexing.
  5. Optional: Deploys .antigravity framework into a target project repository (--target-repo).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import stat
import sys
from pathlib import Path


def _remove_readonly(func, path, _excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def copy_tree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, onerror=_remove_readonly)
    shutil.copytree(src, dst)


def _load_memory_manager(repo_root: Path):
    script_path = repo_root / ".antigravity" / "scripts" / "memory_manager.py"
    if not script_path.is_file():
        script_path = repo_root / "core_framework" / "scripts" / "memory_manager.py"
    if not script_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("memory_manager", script_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_install(
    *,
    repo_root: Path,
    home_dir: Path,
    target_repo: Path | None = None,
    vault_dir: Path | None = None,
    skip_prompt: bool = False,
    skip_skills: bool = False,
    skip_plugin: bool = False,
    skip_vault: bool = False,
    clean_skills: bool = False,
    install_obsidian_app: bool = False,
) -> dict[str, object]:
    gemini_dir = home_dir / ".gemini"
    config_dir = gemini_dir / "config"
    agents_home_dir = home_dir / ".agents"

    summary: dict[str, object] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "prompt_installed": False,
        "skills_installed": 0,
        "skills_cleaned": 0,
        "plugin_installed": False,
        "agents_synced": 0,
        "target_repo_deployed": False,
        "obsidian_vault_initialized": False,
        "obsidian_vault_dir": None,
        "obsidian_projects_indexed": [],
        "obsidian_app_installed": False,
    }

    # 1. Global Entry Point Prompt (~/.gemini/GEMINI.md & ~/.agents/AGENTS.md)
    if not skip_prompt:
        gemini_dir.mkdir(parents=True, exist_ok=True)
        agents_home_dir.mkdir(parents=True, exist_ok=True)
        src_prompt = repo_root / "global_entrypoint" / "GEMINI.md"
        if not src_prompt.is_file():
            src_prompt = repo_root / "GEMINI.md"

        if src_prompt.is_file():
            dest_gemini = gemini_dir / "GEMINI.md"
            if dest_gemini.is_file():
                shutil.copy2(dest_gemini, gemini_dir / "GEMINI.md.bak")
            shutil.copy2(src_prompt, dest_gemini)
            shutil.copy2(src_prompt, agents_home_dir / "AGENTS.md")
            summary["prompt_installed"] = True

    # 2. Global Skills Catalog (200 curated skills)
    if not skip_skills:
        skills_src = repo_root / "core_framework" / "skills"
        if not skills_src.is_dir():
            skills_src = repo_root / "skills"

        if skills_src.is_dir():
            skill_dirs = sorted([d for d in skills_src.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()])
            skill_names = {d.name for d in skill_dirs}

            dest_roots = (
                config_dir / "skills",
                gemini_dir / "antigravity-ide" / "skills",
                agents_home_dir / "skills",
            )
            cleaned = 0
            for d_root in dest_roots:
                d_root.mkdir(parents=True, exist_ok=True)
                if clean_skills and len(skill_names) >= 50:
                    for existing in list(d_root.iterdir()):
                        if existing.is_dir() and existing.name not in skill_names:
                            shutil.rmtree(existing, onerror=_remove_readonly)
                            cleaned += 1
                for s_dir in skill_dirs:
                    copy_tree_clean(s_dir, d_root / s_dir.name)

            summary["skills_installed"] = len(skill_dirs)
            summary["skills_cleaned"] = cleaned

    # 3. Antigravity Swarm (ASW) Plugin + Claude Opus 5.5 Subagent TOMLs
    if not skip_plugin:
        plugin_dst = config_dir / "plugins" / "antigravity-swarm"
        plugin_dst.mkdir(parents=True, exist_ok=True)
        plugin_src = repo_root / "plugins" / "antigravity-swarm"
        if plugin_src.is_dir():
            for item in plugin_src.iterdir():
                target = plugin_dst / item.name
                if item.is_dir():
                    copy_tree_clean(item, target)
                else:
                    shutil.copy2(item, target)
            summary["plugin_installed"] = True

        # Ensure Claude Opus 5.5 subagent TOMLs from .antigravity/agents are synced
        agents_src = repo_root / ".antigravity" / "agents"
        if not agents_src.is_dir():
            agents_src = repo_root / "core_framework" / "agents"
        if agents_src.is_dir():
            agents_dst = plugin_dst / "agents"
            agents_dst.mkdir(parents=True, exist_ok=True)
            count = 0
            for toml_file in agents_src.glob("*.toml"):
                shutil.copy2(toml_file, agents_dst / toml_file.name)
                count += 1
            summary["agents_synced"] = count
            summary["plugin_installed"] = True

    # 4. Optional Target Repository Deployment
    resolved_target: Path | None = None
    if target_repo is not None:
        resolved_target = target_repo.expanduser().resolve()
        resolved_target.mkdir(parents=True, exist_ok=True)
        src_ag = repo_root / ".antigravity"
        if src_ag.is_dir():
            copy_tree_clean(src_ag, resolved_target / ".antigravity")
            summary["target_repo_deployed"] = True

    # 5. Enforced Local Obsidian Self-Learning Knowledge Vault & Project Indexing
    if not skip_vault:
        mm = _load_memory_manager(repo_root)
        if mm is not None:
            resolved_vault = mm.resolve_vault_dir(vault_dir, home_dir=home_dir)
            mm.init_vault(vault_dir=resolved_vault, home_dir=home_dir)
            summary["obsidian_vault_initialized"] = True
            summary["obsidian_vault_dir"] = str(resolved_vault)

            indexed_projects: list[str] = []
            # Index coordinator repository
            if repo_root.is_dir():
                mm.index_project(repo_root, vault_dir=resolved_vault, home_dir=home_dir)
                indexed_projects.append(repo_root.name)

            # Index target_repo and any child git repositories inside target_repo
            if resolved_target is not None and resolved_target.is_dir():
                if resolved_target != repo_root:
                    mm.index_project(resolved_target, vault_dir=resolved_vault, home_dir=home_dir)
                    if resolved_target.name not in indexed_projects:
                        indexed_projects.append(resolved_target.name)
                for child in sorted(resolved_target.iterdir()):
                    if child.is_dir() and (child / ".git").exists() and child.name not in indexed_projects:
                        mm.index_project(child, vault_dir=resolved_vault, home_dir=home_dir)
                        indexed_projects.append(child.name)

            summary["obsidian_projects_indexed"] = indexed_projects
            obs_status = mm.ensure_obsidian_installed(
                home_dir=home_dir,
                attempt_install=install_obsidian_app,
            )
            summary["obsidian_app_installed"] = bool(obs_status.get("installed"))

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-Platform Installer for Antigravity Swarm Coordinator (macOS, Windows, Linux)."
    )
    parser.add_argument("--target-repo", type=Path, default=None, help="Optional target repository to receive .antigravity")
    parser.add_argument("--home-dir", type=Path, default=None, help="Override home directory (for isolated testing)")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Override Obsidian Knowledge Vault directory")
    parser.add_argument("--skip-prompt", action="store_true", help="Skip installing ~/.gemini/GEMINI.md and ~/.agents/AGENTS.md")
    parser.add_argument("--skip-skills", action="store_true", help="Skip installing the 200 curated skills")
    parser.add_argument("--skip-plugin", action="store_true", help="Skip installing the antigravity-swarm plugin")
    parser.add_argument("--skip-vault", action="store_true", help="Skip initializing the local Obsidian Knowledge Vault")
    parser.add_argument("--clean-skills", action="store_true", help="Remove uncurated/duplicate skills from global skill folders")
    parser.add_argument("--install-obsidian-app", action="store_true", help="Attempt to install Obsidian desktop app if missing")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    home_dir = args.home_dir.expanduser().resolve() if args.home_dir else Path.home()

    res = run_install(
        repo_root=repo_root,
        home_dir=home_dir,
        target_repo=args.target_repo,
        vault_dir=args.vault_dir,
        skip_prompt=args.skip_prompt,
        skip_skills=args.skip_skills,
        skip_plugin=args.skip_plugin,
        skip_vault=args.skip_vault,
        clean_skills=args.clean_skills,
        install_obsidian_app=args.install_obsidian_app,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
