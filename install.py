#!/usr/bin/env python3
"""Universal Cross-Platform Installer for Antigravity Swarm Coordinator (macOS, Windows, Linux).

Installs:
  1. Global entry point prompt (~/.gemini/GEMINI.md and ~/.agents/AGENTS.md)
  2. All 201 curated Multi-Domain Golden Catalog skills (~/.gemini/config/skills,
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
import re
import shutil
import stat
import subprocess
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


def ensure_rtk_installed(
    *,
    home_dir: Path | None = None,
    attempt_install: bool = True,
) -> dict[str, object]:
    """Discover or install the rtk (Token Killer) CLI binary across Windows, macOS, and Linux.

    Searches:
      1. System PATH via shutil.which("rtk")
      2. Windows WinGet package directories under %LOCALAPPDATA%/Microsoft/WinGet/Packages/rtk-ai.rtk*
      3. Cargo binary directories (~/.cargo/bin/rtk)
      4. macOS / Linux Homebrew paths (/opt/homebrew/bin/rtk, /usr/local/bin/rtk)
    """
    active_home = home_dir if home_dir is not None else Path.home()
    is_win = platform.system() == "Windows"
    bin_name = "rtk.exe" if is_win else "rtk"

    candidate_paths: list[Path] = []

    which_path = shutil.which("rtk")
    if which_path:
        candidate_paths.append(Path(which_path))

    # Cargo bin
    candidate_paths.append(active_home / ".cargo" / "bin" / bin_name)
    candidate_paths.append(Path.home() / ".cargo" / "bin" / bin_name)

    # Windows WinGet packages
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_root = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            try:
                for pkg_dir in winget_root.glob("rtk-ai.rtk*"):
                    if pkg_dir.is_dir():
                        for exe in pkg_dir.rglob("rtk.exe"):
                            if exe.is_file():
                                candidate_paths.append(exe)
            except Exception:
                pass

    # macOS / Linux Homebrew and standard bins
    candidate_paths.append(Path("/opt/homebrew/bin/rtk"))
    candidate_paths.append(Path("/usr/local/bin/rtk"))
    candidate_paths.append(active_home / ".local" / "bin" / "rtk")

    def _verify_bin(p: Path) -> str | None:
        if not p.is_file():
            return None
        try:
            res = subprocess.run([str(p), "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                txt = (res.stdout or res.stderr).strip()
                m = re.search(r"rtk\s+([0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9._-]*)", txt)
                if m:
                    return m.group(1)
                return txt or "unknown"
        except Exception:
            pass
        return None

    # Check candidates
    for cand in candidate_paths:
        v = _verify_bin(cand)
        if v:
            return {"installed": True, "version": v, "path": str(cand)}

    # If missing and attempt_install=True, try platform package manager with 15s timeout
    if attempt_install:
        try:
            if is_win:
                subprocess.run(
                    ["winget", "install", "--id", "rtk-ai.rtk", "--exact", "--accept-package-agreements", "--accept-source-agreements", "--silent"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            elif platform.system() == "Darwin":
                subprocess.run(["brew", "install", "rtk"], capture_output=True, text=True, timeout=15)
            else:
                subprocess.run(["cargo", "install", "rtk-ai"], capture_output=True, text=True, timeout=15)
        except Exception:
            pass

        # Check again after install attempt
        which_path = shutil.which("rtk")
        if which_path:
            v = _verify_bin(Path(which_path))
            if v:
                return {"installed": True, "version": v, "path": str(which_path)}

        for cand in candidate_paths:
            v = _verify_bin(cand)
            if v:
                return {"installed": True, "version": v, "path": str(cand)}

    return {"installed": False, "version": None, "path": None}


def _seed_chub_config(active_home: Path) -> bool:
    """Seed ~/.chub/config.yaml with telemetry/feedback disabled only if missing."""
    chub_cfg = active_home / ".chub" / "config.yaml"
    if chub_cfg.exists():
        return False
    chub_cfg.parent.mkdir(parents=True, exist_ok=True)
    chub_cfg.write_text("telemetry: false\nfeedback: false\n", encoding="utf-8")
    return True


def ensure_chub_installed(
    home_dir: Path | None = None,
    attempt_install: bool = True,
) -> dict[str, object]:
    """Discover or install the @aisuite/chub CLI and seed privacy-first ~/.chub/config.yaml."""
    active_home = home_dir if home_dir is not None else Path.home()
    seeded = _seed_chub_config(active_home)

    env = dict(os.environ)
    env["CHUB_TELEMETRY"] = "0"
    env["CHUB_FEEDBACK"] = "0"

    def _probe_chub() -> tuple[str | None, str | None]:
        chub_bin = shutil.which("chub")
        if not chub_bin:
            return None, None
        try:
            res = subprocess.run([chub_bin, "-V"], capture_output=True, text=True, env=env, timeout=10)
            if res.returncode == 0:
                ver = (res.stdout or res.stderr).strip() or "unknown"
                return ver, chub_bin
        except Exception:
            pass
        return None, None

    ver, chub_bin = _probe_chub()
    if ver:
        return {"installed": True, "version": ver, "path": chub_bin, "config_seeded": seeded}

    if attempt_install:
        npm_bin = shutil.which("npm")
        if npm_bin:
            try:
                subprocess.run(
                    [npm_bin, "install", "-g", "@aisuite/chub"],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=60,
                )
            except Exception:
                pass
            ver, chub_bin = _probe_chub()
            if ver:
                return {"installed": True, "version": ver, "path": chub_bin, "config_seeded": seeded}

    return {"installed": False, "version": None, "path": None, "config_seeded": seeded}


def _load_golden_skill_names(repo_root: Path) -> set[str]:
    curate_script = repo_root / ".antigravity" / "scripts" / "curate_skill_catalog.py"
    if not curate_script.is_file():
        return {"context-hub"}
    try:
        spec = importlib.util.spec_from_file_location("curate_skill_catalog_inst", curate_script)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return set(getattr(mod, "GOLDEN_CATALOG", {}).keys()) | {"context-hub"}
    except Exception:
        pass
    return {"context-hub"}


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
    skip_rtk: bool = False,
    skip_chub: bool = False,
    install_laya: bool = False,
    disable_decision_model: bool = False,
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
        "rtk_installed": False,
        "rtk_version": None,
        "rtk_skill_mandatory": True,
        "chub_installed": False,
        "chub_version": None,
        "chub_config_seeded": False,
        "decision_router_installed": False,
        "decision_router_device": None,
        "decision_model_enabled": not disable_decision_model,
        "token_economizer_installed": False,
        "laya_sdk_installed": False,
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

    # 2. Global Skills Catalog (201 curated skills)
    if not skip_skills:
        skills_src = repo_root / "core_framework" / "skills"
        using_core_framework = skills_src.is_dir()
        if not using_core_framework:
            skills_src = repo_root / "skills"

        skill_dirs_by_name: dict[str, Path] = {}
        if skills_src.is_dir():
            for d in sorted(skills_src.iterdir()):
                if d.is_dir() and (d / "SKILL.md").is_file():
                    skill_dirs_by_name[d.name] = d

        ag_skills_src = repo_root / ".antigravity" / "skills"
        if not using_core_framework and ag_skills_src.is_dir():
            allowed_golden = _load_golden_skill_names(repo_root)
            for d in sorted(ag_skills_src.iterdir()):
                if d.is_dir() and (d / "SKILL.md").is_file() and d.name in allowed_golden:
                    skill_dirs_by_name.setdefault(d.name, d)

        if skill_dirs_by_name:
            skill_dirs = [skill_dirs_by_name[k] for k in sorted(skill_dirs_by_name)]
            skill_names = set(skill_dirs_by_name.keys())

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
                # Avoid 2x duplicate slash-command registration in Antigravity UI:
                # When global skills are installed into ~/.gemini/config/skills, do NOT install a
                # second copy into ~/.gemini/config/plugins/antigravity-swarm/skills (Antigravity
                # deduplicates skills by file path, not by skill name).
                if item.name == "skills" and (not skip_skills or (config_dir / "skills").is_dir()):
                    stale_plugin_skills = plugin_dst / "skills"
                    if stale_plugin_skills.exists():
                        shutil.rmtree(stale_plugin_skills, onerror=_remove_readonly)
                    continue
                target = plugin_dst / item.name
                if item.is_dir():
                    copy_tree_clean(item, target)
                else:
                    shutil.copy2(item, target)
            if not skip_skills or (config_dir / "skills").is_dir():
                deployed_manifest = plugin_dst / "plugin.json"
                if deployed_manifest.is_file():
                    try:
                        manifest_data = json.loads(deployed_manifest.read_text(encoding="utf-8"))
                        manifest_data.pop("skills", None)
                        deployed_manifest.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
                    except Exception:
                        pass
            summary["plugin_installed"] = True

        # Ensure Claude Opus 5.5 & Quad-Model subagent TOMLs and Antigravity .md definitions are synced
        agents_src = repo_root / ".antigravity" / "agents"
        if not agents_src.is_dir():
            agents_src = repo_root / "core_framework" / "agents"
        if agents_src.is_dir():
            agents_dst = plugin_dst / "agents"
            agents_dst.mkdir(parents=True, exist_ok=True)
            count = 0
            for ext in ("*.toml", "*.md"):
                for agent_file in agents_src.glob(ext):
                    shutil.copy2(agent_file, agents_dst / agent_file.name)
                    count += 1
            summary["agents_synced"] = count
            summary["plugin_installed"] = True

    # 3B. Global .antigravity & ~/.gemini/scripts installation (so scripts work in any directory)
    src_ag_global = repo_root / ".antigravity"
    if src_ag_global.is_dir():
        copy_tree_clean(src_ag_global, gemini_dir / ".antigravity")
        global_scripts_dst = gemini_dir / "scripts"
        global_scripts_dst.mkdir(parents=True, exist_ok=True)
        src_scripts = src_ag_global / "scripts"
        if src_scripts.is_dir():
            for script_file in src_scripts.iterdir():
                if script_file.is_file():
                    shutil.copy2(script_file, global_scripts_dst / script_file.name)

    # 4. Optional Target Repository Deployment (including child git repositories)
    resolved_target: Path | None = None
    if target_repo is not None:
        resolved_target = target_repo.expanduser().resolve()
        resolved_target.mkdir(parents=True, exist_ok=True)
        src_ag = repo_root / ".antigravity"
        if src_ag.is_dir():
            if resolved_target != repo_root:
                copy_tree_clean(src_ag, resolved_target / ".antigravity")
            for child in sorted(resolved_target.iterdir()):
                if child.is_dir() and (child / ".git").exists() and child.resolve() != repo_root.resolve():
                    child_ag = child / ".antigravity"
                    for sub_name in ("scripts", "rules", "agents"):
                        src_sub = src_ag / sub_name
                        dst_sub = child_ag / sub_name
                        if src_sub.is_dir():
                            dst_sub.mkdir(parents=True, exist_ok=True)
                            for item in src_sub.iterdir():
                                if item.is_file():
                                    shutil.copy2(item, dst_sub / item.name)
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

    # 6. RTK (Token Killer) CLI Discovery & Rule Provisioning
    if not skip_rtk:
        rtk_status = ensure_rtk_installed(home_dir=home_dir, attempt_install=True)
        summary["rtk_installed"] = bool(rtk_status.get("installed"))
        summary["rtk_version"] = rtk_status.get("version")

    # Always provision RTK rules in ~/.agents/rules and target_repo/.agents/rules
    rtk_rules_src = repo_root / "core_framework" / "rules" / "antigravity-rtk-rules.md"
    if not rtk_rules_src.is_file():
        rtk_rules_src = repo_root / ".antigravity" / "rules" / "antigravity-rtk-rules.md"

    rules_content = (
        rtk_rules_src.read_text(encoding="utf-8")
        if rtk_rules_src.is_file()
        else (
            "# Antigravity RTK (Token Killer) Rules\n\n"
            "Mandatory pre-filtering directives for developer CLI commands:\n\n"
            "1. **Mandatory RTK CLI Proxy (`rtk-token-killer`):**\n"
            "   - Route `git status`, `git log`, and `git diff` through `rtk git ...` (50% to 90% token reduction).\n"
            "   - Route `pytest` and `python -m pytest` through `rtk pytest ...` (90% to 98% token reduction).\n"
            "   - Route file discovery and inspection through `rtk find <pattern>`, `rtk read -l aggressive <path>`, and `rtk json <path>`.\n"
            "2. **Windows Platform Tree & Find Guards:**\n"
            "   - NEVER execute `rtk tree` on Windows (`win32`). Windows `tree.com` parameter conflicts trigger errors. Preserve native `tree`.\n"
            "   - NEVER execute `rtk find` on Windows (`win32`). `C:\\Windows\\System32\\find.exe` conflicts trigger `FIND: Parameter format not correct`. Preserve native `find` on Windows.\n"
            "3. **Compound Operator Resilience:**\n"
            "   - Multi-segment commands (`;`, `&&`, `||`, `|`) must apply `rtk` per supported subcommand while preserving quotes and shell logic.\n"
        )
    )

    home_rules_dir = agents_home_dir / "rules"
    home_rules_dir.mkdir(parents=True, exist_ok=True)
    (home_rules_dir / "antigravity-rtk-rules.md").write_text(rules_content, encoding="utf-8")

    if resolved_target is not None:
        target_rules_dir = resolved_target / ".agents" / "rules"
        target_rules_dir.mkdir(parents=True, exist_ok=True)
        (target_rules_dir / "antigravity-rtk-rules.md").write_text(rules_content, encoding="utf-8")

    # 6B. Context Hub (@aisuite/chub) CLI Discovery & Privacy Config Seeding
    if not skip_chub:
        chub_status = ensure_chub_installed(home_dir=home_dir, attempt_install=True)
        summary["chub_installed"] = bool(chub_status.get("installed"))
        summary["chub_version"] = chub_status.get("version")
        summary["chub_config_seeded"] = bool(chub_status.get("config_seeded"))
    else:
        summary["chub_config_seeded"] = _seed_chub_config(home_dir)

    # 7. System 1 Decision Router & Laya Status (preserve existing tuned keys)
    base_decision_cfg: dict[str, object] = {
        "enabled": not disable_decision_model,
        "prefer_gpu": True,
        "min_free_vram_mib": 2048,
        "min_total_vram_mib": 4096,
        "cpu_threads": 12,
        "flush_denormal": True,
        "preferred_checkpoint": "multilingual",
        "compact_question_schema": True,
        "use_local_snapshot_fastload": True,
    }
    for src_cfg_cand in (
        repo_root / ".antigravity" / "decision_config.json",
        repo_root / "core_framework" / "decision_config.json",
        gemini_dir / "decision_config.json",
    ):
        if src_cfg_cand.is_file():
            try:
                loaded_cfg = json.loads(src_cfg_cand.read_text(encoding="utf-8"))
                if isinstance(loaded_cfg, dict):
                    base_decision_cfg.update(loaded_cfg)
                    break
            except Exception:
                pass
    base_decision_cfg["enabled"] = not disable_decision_model
    cfg_json = json.dumps(base_decision_cfg, indent=2) + "\n"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    (gemini_dir / "decision_config.json").write_text(cfg_json, encoding="utf-8")
    if resolved_target is not None:
        (resolved_target / ".antigravity").mkdir(parents=True, exist_ok=True)
        (resolved_target / ".antigravity" / "decision_config.json").write_text(cfg_json, encoding="utf-8")
    elif home_dir == Path.home() and (repo_root / ".antigravity").is_dir():
        (repo_root / ".antigravity" / "decision_config.json").write_text(cfg_json, encoding="utf-8")
    summary["decision_model_enabled"] = not disable_decision_model

    dr_dest = gemini_dir / "scripts" / "decision_router.py"
    dr_src = repo_root / ".antigravity" / "scripts" / "decision_router.py"
    if not dr_src.is_file():
        dr_src = repo_root / "core_framework" / "scripts" / "decision_router.py"

    if dr_src.is_file():
        (gemini_dir / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(dr_src, dr_dest)
        summary["decision_router_installed"] = True
    elif dr_dest.is_file():
        summary["decision_router_installed"] = True

    te_dest = gemini_dir / "scripts" / "token_economizer.py"
    te_src = repo_root / ".antigravity" / "scripts" / "token_economizer.py"
    if not te_src.is_file():
        te_src = repo_root / "core_framework" / "scripts" / "token_economizer.py"
    if te_src.is_file():
        (gemini_dir / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(te_src, te_dest)
        summary["token_economizer_installed"] = True
    elif te_dest.is_file():
        summary["token_economizer_installed"] = True

    try:
        dr_spec = importlib.util.spec_from_file_location(
            "decision_router_inst", dr_src if dr_src.is_file() else dr_dest
        )
        if dr_spec and dr_spec.loader:
            dr_mod = importlib.util.module_from_spec(dr_spec)
            dr_spec.loader.exec_module(dr_mod)
            dev_info = dr_mod.select_optimal_device()
            summary["decision_router_device"] = dev_info.get("device", "cpu")
    except Exception:
        summary["decision_router_device"] = "cpu"

    if install_laya:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "laya"], capture_output=True, timeout=60)
        except Exception:
            pass

    try:
        import laya  # noqa: F401

        summary["laya_sdk_installed"] = True
    except ImportError:
        summary["laya_sdk_installed"] = False

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-Platform Installer for Antigravity Swarm Coordinator (macOS, Windows, Linux)."
    )
    parser.add_argument("--target-repo", type=Path, default=None, help="Optional target repository to receive .antigravity")
    parser.add_argument("--home-dir", type=Path, default=None, help="Override home directory (for isolated testing)")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Override Obsidian Knowledge Vault directory")
    parser.add_argument("--skip-prompt", action="store_true", help="Skip installing ~/.gemini/GEMINI.md and ~/.agents/AGENTS.md")
    parser.add_argument("--skip-skills", action="store_true", help="Skip installing the 201 curated skills")
    parser.add_argument("--skip-plugin", action="store_true", help="Skip installing the antigravity-swarm plugin")
    parser.add_argument("--skip-vault", action="store_true", help="Skip initializing the local Obsidian Knowledge Vault")
    parser.add_argument("--clean-skills", action="store_true", help="Remove uncurated/duplicate skills from global skill folders")
    parser.add_argument("--install-obsidian-app", action="store_true", help="Attempt to install Obsidian desktop app if missing")
    parser.add_argument("--skip-rtk", action="store_true", help="Skip discovering or installing the rtk CLI binary")
    parser.add_argument("--skip-chub", action="store_true", help="Skip discovering or installing the @aisuite/chub CLI")
    parser.add_argument("--install-laya", action="store_true", help="Install NandhaKishorM/laya package for neural System 1 routing")
    parser.add_argument(
        "--disable-decision-model",
        action="store_true",
        help="Disable System 1 Decision Router (for low-RAM or constrained PCs)",
    )
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
        skip_rtk=args.skip_rtk,
        skip_chub=args.skip_chub,
        install_laya=args.install_laya,
        disable_decision_model=args.disable_decision_model,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
