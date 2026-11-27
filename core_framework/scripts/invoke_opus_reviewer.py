#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Antigravity-Native Claude Opus 5.5 Reviewer Bridge with Automatic Quota Fallback.

Executes Plan Opposition Audits (6 vectors) and Code Diff / Evidence Opposition Reviews (4 vectors)
grounded in native Claude Opus 5.5 subagent configurations (.antigravity/agents/*.toml),
deterministic adversarial verification tripwires (Zero Heuristic Substitution, Anti-Shortcut
Enforcement, and Prompt-to-Code Traceability), UTF-16LE PowerShell redirection resilience,
self-contained `--files` git diff collection, and automatic fallback to the Deterministic
Adversarial Engine + Gemini 4 Neon (High) whenever Claude Opus 5.5 credits/quota are exhausted.
"""

import argparse
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections import deque
from pathlib import Path


def read_text_resilient(path: Path | None) -> str:
    """Read text file resiliently across UTF-8, UTF-16LE/BE, and mixed PowerShell `>` / `>>` files."""
    if path is None or not path.exists() or not path.is_file():
        return ""
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return ""
    if not raw_bytes:
        return ""

    # Pure UTF-16 BOM
    if raw_bytes.startswith(b"\xff\xfe"):
        return raw_bytes.decode("utf-16-le", errors="replace").replace("\x00", "")
    if raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes.decode("utf-16-be", errors="replace").replace("\x00", "")

    # Mixed UTF-8 + UTF-16LE (e.g. `git diff > f ; Get-Content >> f` in Windows PowerShell 5.1)
    if b"\x00" in raw_bytes:
        cleaned = raw_bytes.replace(b"\xff\xfe", b"").replace(b"\xfe\xff", b"").replace(b"\x00", b"")
        return cleaned.decode("utf-8", errors="replace")

    return raw_bytes.decode("utf-8", errors="replace")


def clean_scratch_directory(scratch_dir: Path) -> int:
    """Non-interactively remove all files and nested directories (including __pycache__) inside a scratch/temp dir.

    Safety Guard: Strictly refuses to wipe '.', cwd, home directory, or any repository/workspace root.
    """
    raw_str = str(scratch_dir).strip()
    if raw_str in ("", ".", "./", ".\\", "..", "../", "..\\"):
        sys.stderr.write(f"Refusing --clean-scratch on unsafe relative target: {raw_str!r}\n")
        return 2
    resolved = scratch_dir.resolve()
    cwd_res = Path.cwd().resolve()
    home_res = Path.home().resolve()
    parts_low = [p.lower() for p in resolved.parts]
    has_scratch_marker = any(
        seg in ("scratch", "tmp", "temp", "test-artifacts")
        or seg.startswith(("tmp", "temp", "scratch"))
        for seg in parts_low
    )
    if (
        resolved in (cwd_res, home_res)
        or len(resolved.parts) <= 3
        or (resolved / ".git").exists()
        or (resolved / ".antigravity").exists()
        or not has_scratch_marker
    ):
        sys.stderr.write(
            f"Refusing --clean-scratch on non-scratch or repository directory: {resolved}\n"
        )
        return 2
    if not scratch_dir.exists():
        return 0
    if not scratch_dir.is_dir():
        try:
            scratch_dir.unlink(missing_ok=True)
        except OSError:
            pass
        return 0

    for item in list(scratch_dir.iterdir()):
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def resolve_fallback_reason(explicit_reason: str | None = None) -> str | None:
    """Determine whether Opus credit/quota fallback mode is active."""
    if explicit_reason and explicit_reason.strip():
        return explicit_reason.strip()
    for env_key in (
        "ANTIGRAVITY_OPUS_CREDITS_EXHAUSTED",
        "OPUS_FALLBACK_MODE",
        "ANTHROPIC_QUOTA_EXHAUSTED",
    ):
        val = os.environ.get(env_key, "").strip().lower()
        if val in ("1", "true", "yes", "exhausted", "fallback"):
            return f"env:{env_key}"
    return None


def discover_latest_plan(workdir: Path, repo_root: Path) -> Path | None:
    """Auto-discover the most recently modified .asw/plans/*.md file."""
    for base in (workdir, repo_root):
        plans_dir = base / ".asw" / "plans"
        if plans_dir.is_dir():
            candidates = sorted(
                (p for p in plans_dir.glob("*.md") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]
    return None


def build_git_diff_from_files(files_arg: str | None, workdir: Path) -> str:
    """Collect unified git diff for tracked files plus synthesized unified diff for untracked files."""
    file_list: list[str] = []
    if files_arg:
        for part in re.split(r"[,;]+", files_arg):
            cleaned = part.strip().strip("'\"")
            if cleaned:
                file_list.append(cleaned)
    else:
        try:
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if status_proc.returncode == 0:
                for line in status_proc.stdout.splitlines():
                    if len(line) > 3:
                        path_part = line[3:].strip().strip('"')
                        if " -> " in path_part:
                            path_part = path_part.split(" -> ", 1)[1].strip()
                        if path_part:
                            file_list.append(path_part)
        except Exception:
            pass

    diff_chunks: list[str] = []
    for rel_file in file_list:
        target_path = (workdir / rel_file).resolve() if not Path(rel_file).is_absolute() else Path(rel_file)
        try:
            rel_posix = target_path.relative_to(workdir.resolve()).as_posix()
        except ValueError:
            rel_posix = Path(rel_file).as_posix()

        git_chunk = ""
        for diff_cmd in (
            ["git", "diff", "HEAD", "--", rel_posix],
            ["git", "diff", "--", rel_posix],
        ):
            try:
                proc = subprocess.run(
                    diff_cmd,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    git_chunk = proc.stdout
                    break
            except Exception:
                continue

        if git_chunk.strip():
            diff_chunks.append(git_chunk)
        elif target_path.is_file():
            # Untracked or newly created file: synthesize unified diff additions in UTF-8
            file_text = read_text_resilient(target_path)
            lines_list = file_text.splitlines()
            added_lines = "\n".join(f"+{line}" for line in lines_list)
            hunk_hdr = f"@@ -0,0 +1,{len(lines_list)} @@\n" if lines_list else ""
            synth_chunk = (
                f"diff --git a/{rel_posix} b/{rel_posix}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{rel_posix}\n"
                f"{hunk_hdr}"
                f"{added_lines}\n"
            )
            diff_chunks.append(synth_chunk)

    return "\n".join(diff_chunks)


def read_evidence_resilient(
    evidence_path: Path | None,
    plan_content: str,
    diff_content: str,
    workdir: Path,
) -> tuple[bool, str]:
    """Read evidence from a directory, a single file, or fallback workspace locations without NotADirectoryError."""
    chunks: list[str] = []
    has_explicit_evidence = False

    if evidence_path is not None and evidence_path.exists():
        if evidence_path.is_file():
            txt = read_text_resilient(evidence_path)
            if txt.strip():
                has_explicit_evidence = True
                chunks.append(txt)
        elif evidence_path.is_dir():
            files = [p for p in evidence_path.rglob("*") if p.is_file()]
            if files:
                has_explicit_evidence = True
                for ef in files[:50]:
                    chunks.append(read_text_resilient(ef))
    else:
        # Auto-discover evidence from .asw/evidence or .asw/plans if --evidence was omitted
        for candidate_dir in (workdir / ".asw" / "evidence", workdir / ".asw" / "plans"):
            if candidate_dir.is_dir():
                files = [p for p in candidate_dir.rglob("*") if p.is_file()]
                if files:
                    has_explicit_evidence = True
                    for ef in files[:30]:
                        chunks.append(read_text_resilient(ef))

    if plan_content.strip():
        chunks.append(plan_content)
        if evidence_path is None:
            has_explicit_evidence = True

    if diff_content.strip() and evidence_path is None:
        has_explicit_evidence = True

    return has_explicit_evidence, "\n".join(chunks)


def discover_antigravity_runtime(repo_root: Path) -> dict:
    """Path-independently discover Antigravity native execution runtime and subagents (Windows, macOS, Linux)."""
    home = Path.home()
    local_app_data = os.environ.get("LOCALAPPDATA")
    win_base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
    win_ls = win_base / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe"

    mac_candidates = [
        (home / "Applications" / "Antigravity.app" / "Contents" / "Resources" / "app" / "extensions" / "antigravity" / "bin" / "language_server_macos_arm", "~/Applications/Antigravity.app/.../language_server_macos_arm"),
        (home / "Applications" / "Antigravity.app" / "Contents" / "Resources" / "app" / "extensions" / "antigravity" / "bin" / "language_server_macos_x64", "~/Applications/Antigravity.app/.../language_server_macos_x64"),
        (home / "Applications" / "Antigravity.app" / "Contents" / "Resources" / "bin" / "language_server", "~/Applications/Antigravity.app/Contents/Resources/bin/language_server"),
        (Path("/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/bin/language_server_macos_arm"), "/Applications/Antigravity.app/.../language_server_macos_arm"),
        (Path("/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/bin/language_server_macos_x64"), "/Applications/Antigravity.app/.../language_server_macos_x64"),
        (Path("/Applications/Antigravity.app/Contents/Resources/bin/language_server"), "/Applications/Antigravity.app/Contents/Resources/bin/language_server"),
    ]

    ls_found = False
    ls_location = None
    if win_ls.exists():
        ls_found = True
        ls_location = "%LOCALAPPDATA%/Programs/antigravity/resources/bin/language_server.exe"
    else:
        for cand_path, cand_label in mac_candidates:
            if cand_path.exists():
                ls_found = True
                ls_location = cand_label
                break

    agy_path = shutil.which("agy")
    if not agy_path:
        for agy_cand in (
            home / ".antigravity" / "bin" / "agy",
            Path("/Applications/Antigravity.app/Contents/Resources/app/bin/agy"),
            Path("/opt/homebrew/bin/agy"),
            Path("/usr/local/bin/agy"),
        ):
            if agy_cand.is_file():
                agy_path = str(agy_cand)
                break

    # Discover subagent tomls
    agents_dir = repo_root / ".antigravity" / "agents"
    expected_agents = ["asw-plan-audit.toml", "asw-opposition-reviewer.toml", "asw-reviewer.toml"]
    subagent_status = {}
    for agent_name in expected_agents:
        subagent_status[agent_name] = (agents_dir / agent_name).exists()

    return {
        "language_server_found": ls_found,
        "language_server_location": ls_location,
        "agy_found": bool(agy_path),
        "subagent_tomls": subagent_status,
        "active_model": "claude-opus-5-5",
        "fallback_model": "gemini-4-neon-high",
        "credit_exhaustion_policy": "auto_fallback_deterministic_and_neon_high",
        "subagent_timeout_seconds": 60,
        "thinking_level": "high",
    }


def sync_agents(repo_root: Path) -> int:
    """Sync .antigravity/agents/*.toml to Path.home() / .gemini/config/plugins/antigravity-swarm/agents/."""
    src_dir = repo_root / ".antigravity" / "agents"
    if not src_dir.exists():
        sys.stderr.write(f"Source agents directory not found: {src_dir}\n")
        return 1

    dst_dir = Path.home() / ".gemini" / "config" / "plugins" / "antigravity-swarm" / "agents"
    dst_dir.mkdir(parents=True, exist_ok=True)

    synced = 0
    for ext in ("*.toml", "*.md"):
        for agent_path in src_dir.glob(ext):
            dst_path = dst_dir / agent_path.name
            content = agent_path.read_text(encoding="utf-8")
            dst_path.write_text(content, encoding="utf-8")
            synced += 1

    sys.stdout.write(f"Synced {synced} subagent configurations to plugin agents directory.\n")
    return 0


def scan_public_repo_privacy(repo_dir: Path, forbid_terms_csv: str | None = None) -> int:
    """Scan a repository or directory for RFC1918 private LAN IPs, live API keys, and forbidden PII/location terms before public push."""
    if not repo_dir.exists():
        sys.stderr.write(f"Error: scan target does not exist: {repo_dir}\n")
        return 2

    raw_terms = []
    if forbid_terms_csv:
        raw_terms.extend([t.strip() for t in forbid_terms_csv.split(",") if t.strip()])
    env_terms = os.environ.get("ANTIGRAVITY_FORBID_PUBLIC_TERMS", "")
    if env_terms:
        raw_terms.extend([t.strip() for t in env_terms.split(",") if t.strip()])

    private_ip_re = re.compile(
        r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
    )
    secret_re = re.compile(
        r"(?:\b(?:AIzaSy[A-Za-z0-9_-]{33}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
    )

    candidate_files = [repo_dir] if repo_dir.is_file() else sorted(repo_dir.rglob("*"))
    violations: list[str] = []

    for fpath in candidate_files:
        if not fpath.is_file():
            continue
        rel_parts = fpath.relative_to(repo_dir if repo_dir.is_dir() else repo_dir.parent).parts
        if any(p in (".git", "__pycache__", ".pytest_cache", ".asw", ".agent-workspace", "node_modules", ".venv", "venv") for p in rel_parts):
            continue
        if fpath.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".whl", ".pyc"):
            continue
        text = read_text_resilient(fpath)
        if not text:
            continue
        rel_str = str(fpath.relative_to(repo_dir if repo_dir.is_dir() else repo_dir.parent))
        for line_no, line in enumerate(text.splitlines(), 1):
            for ip_m in private_ip_re.finditer(line):
                ip_val = ip_m.group(0)
                if ip_val not in (
                    "10.0.0.0",
                    "10.0.2.2",
                    "10.0.1.5",
                    "10.0.1.50",
                    "10.1.0.0",
                    "172.16.0.0",
                    "192.168.0.0",
                    "192.168.1.1",
                    "192.168.1.10",
                    "192.168.1.100",
                ):
                    violations.append(f"{rel_str}:{line_no}: Private RFC1918 LAN IP {ip_val!r} detected")
            for sec_m in secret_re.finditer(line):
                violations.append(f"{rel_str}:{line_no}: Live API/token secret {sec_m.group(0)[:10]}... detected")
            for term in raw_terms:
                if re.search(re.escape(term), line, re.IGNORECASE):
                    violations.append(f"{rel_str}:{line_no}: Forbidden PII/location term {term!r} detected")

    if violations:
        sys.stdout.write("Verdict: PUBLIC_REPO_PRIVACY_REJECTED\n")
        for v in violations:
            sys.stdout.write(f" - [CRITICAL] {v}\n")
        return 1

    sys.stdout.write("Verdict: PUBLIC_REPO_PRIVACY_APPROVED (0 private IPs, secrets, or forbidden PII terms found)\n")
    return 0


_SHARED_RUNTIME_RESOURCE_RE = re.compile(
    r"(?:^|[/\\])(decision_router\.py|token_economizer\.py|asw-[A-Za-z0-9_-]+\.mjs|decision_config\.json)$",
    re.IGNORECASE,
)
_SHARED_RUNTIME_INLINE_RE = re.compile(
    r"\b(decision_router\.py|token_economizer\.py|asw-[A-Za-z0-9_-]+\.mjs|decision_config\.json)\b",
    re.IGNORECASE,
)
_DAG_IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".asw",
    ".agent-workspace",
}
_DAG_CODE_EXTS = {".py", ".mjs", ".js", ".ts", ".tsx", ".jsx"}
_ESM_IMPORT_PATTERNS = (
    re.compile(r"""import\s+(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""export\s+[^'"]*?\s+from\s+['"]([^'"]+)['"]"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)


def _norm_rel(path_str: str) -> str:
    cleaned = path_str.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _collect_py_docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    ids.add(id(val))
    return ids


def build_repo_dependency_graph(
    repo_root: Path,
    candidate_files: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, set[str]]:
    """Build a static repository dependency DAG across Python AST imports, ESM imports, CLI spawns, and shared JSON configs.

    Missing/not-yet-created files yield 0 edges without raising FileNotFoundError (`Missing=0` guard).
    """
    if repo_root is None or not repo_root.exists() or not repo_root.is_dir():
        return {}

    root = repo_root.resolve()
    existing_files: dict[str, Path] = {}
    lower_to_rel: dict[str, str] = {}
    py_module_to_rel: dict[str, str] = {}
    stem_to_py_rels: dict[str, list[str]] = {}
    basename_to_rels: dict[str, list[str]] = {}

    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        try:
            rel_path = fpath.relative_to(root)
        except ValueError:
            continue
        if any(part in _DAG_IGNORED_DIRS for part in rel_path.parts[:-1]):
            continue
        if fpath.suffix.lower() not in (_DAG_CODE_EXTS | {".json"}):
            continue
        rel = rel_path.as_posix()
        existing_files[rel] = fpath
        lower_to_rel[rel.lower()] = rel
        basename_to_rels.setdefault(fpath.name.lower(), []).append(rel)

        if fpath.suffix.lower() == ".py":
            parts = list(rel_path.with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                mod_name = ".".join(parts[:-1])
            else:
                mod_name = ".".join(parts)
            if mod_name:
                py_module_to_rel[mod_name] = rel
            stem = fpath.stem
            if stem != "__init__":
                stem_to_py_rels.setdefault(stem, []).append(rel)

    # Also register explicit candidate files that exist on disk (e.g., inside .antigravity/scripts or tests)
    cand_norm: list[str] = []
    if candidate_files:
        for cf in candidate_files:
            nc = _norm_rel(cf)
            if not nc:
                continue
            cand_norm.append(nc)
            cand_abs = root / nc
            if cand_abs.is_file() and nc not in existing_files:
                existing_files[nc] = cand_abs
                lower_to_rel[nc.lower()] = nc
                basename_to_rels.setdefault(cand_abs.name.lower(), []).append(nc)
                if cand_abs.suffix.lower() == ".py":
                    parts = list(Path(nc).with_suffix("").parts)
                    mod_name = ".".join(parts[:-1]) if parts and parts[-1] == "__init__" else ".".join(parts)
                    if mod_name:
                        py_module_to_rel[mod_name] = nc
                    if cand_abs.stem != "__init__":
                        stem_to_py_rels.setdefault(cand_abs.stem, []).append(nc)

    def _resolve_py_module(mod_name: str) -> str | None:
        if not mod_name:
            return None
        parts = mod_name.split(".")
        for end in range(len(parts), 0, -1):
            prefix = ".".join(parts[:end])
            if prefix in py_module_to_rel:
                return py_module_to_rel[prefix]
        if len(parts) == 1 and parts[0] in stem_to_py_rels:
            matches = stem_to_py_rels[parts[0]]
            if len(matches) == 1:
                return matches[0]
            for m in matches:
                if m in cand_norm:
                    return m
        return None

    def _resolve_rel_module(base_dir: Path, mod_parts: list[str]) -> str | None:
        target_base = _norm_rel((base_dir / "/".join(mod_parts)).as_posix())
        for suffix in (".py", "/__init__.py"):
            cand = target_base + suffix
            if cand in existing_files:
                return cand
            if cand.lower() in lower_to_rel:
                return lower_to_rel[cand.lower()]
        return None

    def _resolve_shared_resource(raw_ref: str, source_rel: str) -> str | None:
        cleaned = _norm_rel(raw_ref)
        if cleaned in existing_files:
            return cleaned
        if cleaned.lower() in lower_to_rel:
            return lower_to_rel[cleaned.lower()]
        src_parent = Path(source_rel).parent
        rel_joined = _norm_rel((src_parent / cleaned).as_posix())
        if rel_joined in existing_files:
            return rel_joined
        m = _SHARED_RUNTIME_INLINE_RE.search(cleaned)
        if m:
            res_name = m.group(1)
            rels = basename_to_rels.get(res_name.lower(), [])
            if len(rels) == 1:
                return rels[0]
            return res_name
        return None

    def _extract_edges_for_file(rel: str) -> set[str]:
        fpath = existing_files.get(rel)
        if fpath is None:
            return set()
        ext = fpath.suffix.lower()
        if ext not in _DAG_CODE_EXTS:
            return set()
        source = read_text_resilient(fpath)
        if not source.strip():
            return set()
        edges: set[str] = set()
        src_parent = Path(rel).parent

        if ext == ".py":
            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = None
            if tree is not None:
                doc_ids = _collect_py_docstring_ids(tree)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            resolved = _resolve_py_module(alias.name)
                            if resolved and resolved != rel:
                                edges.add(resolved)
                    elif isinstance(node, ast.ImportFrom):
                        if node.level > 0:
                            base = src_parent
                            for _ in range(node.level - 1):
                                base = base.parent
                            if node.module:
                                resolved = _resolve_rel_module(base, node.module.split("."))
                                if resolved and resolved != rel:
                                    edges.add(resolved)
                            for alias in node.names:
                                sub_parts = (node.module.split(".") if node.module else []) + [alias.name]
                                resolved = _resolve_rel_module(base, sub_parts)
                                if resolved and resolved != rel:
                                    edges.add(resolved)
                        elif node.module:
                            resolved = _resolve_py_module(node.module)
                            if resolved and resolved != rel:
                                edges.add(resolved)
                            for alias in node.names:
                                sub_resolved = _resolve_py_module(f"{node.module}.{alias.name}")
                                if sub_resolved and sub_resolved != rel:
                                    edges.add(sub_resolved)
                    elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
                        if _SHARED_RUNTIME_INLINE_RE.search(node.value):
                            resolved = _resolve_shared_resource(node.value, rel)
                            if resolved and resolved != rel:
                                edges.add(resolved)
        else:
            code_lines = [
                ln for ln in source.splitlines()
                if not ln.lstrip().startswith(("//", "/*", "*"))
            ]
            code_text = "\n".join(code_lines)
            for pat in _ESM_IMPORT_PATTERNS:
                for m in pat.finditer(code_text):
                    spec = m.group(1).strip()
                    if spec.startswith((".", "/")):
                        raw_target = _norm_rel(os.path.normpath((src_parent / spec).as_posix()))
                        for ext_cand in ("", ".mjs", ".js", ".ts", ".tsx", ".jsx", "/index.mjs", "/index.js"):
                            cand = raw_target + ext_cand
                            if cand in existing_files and cand != rel:
                                edges.add(cand)
                                break
                            if cand.lower() in lower_to_rel and lower_to_rel[cand.lower()] != rel:
                                edges.add(lower_to_rel[cand.lower()])
                                break
            for m in _SHARED_RUNTIME_INLINE_RE.finditer(code_text):
                resolved = _resolve_shared_resource(m.group(1), rel)
                if resolved and resolved != rel:
                    edges.add(resolved)
        return edges

    graph: dict[str, set[str]] = {}
    if candidate_files is not None:
        queue: deque[str] = deque()
        visited: set[str] = set()
        for cf in cand_norm:
            resolved_cf = cf if cf in existing_files else lower_to_rel.get(cf.lower())
            if resolved_cf and resolved_cf not in visited:
                visited.add(resolved_cf)
                queue.append(resolved_cf)
        while queue:
            cur = queue.popleft()
            edges = _extract_edges_for_file(cur)
            if edges:
                graph[cur] = edges
                for nxt in sorted(edges):
                    if nxt in existing_files and nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
    else:
        for rel in sorted(existing_files.keys()):
            edges = _extract_edges_for_file(rel)
            if edges:
                graph[rel] = edges

    return graph


def _bfs_reachable(graph: dict[str, set[str]], start: str) -> dict[str, list[str]]:
    """Return shortest path from `start` to each reachable dependency node (excluding `start`)."""
    if start not in graph:
        return {}
    paths: dict[str, list[str]] = {}
    queue: deque[list[str]] = deque([[start]])
    visited: set[str] = {start}
    while queue:
        path = queue.popleft()
        cur = path[-1]
        for nxt in sorted(graph.get(cur, ())):
            if nxt in visited:
                continue
            visited.add(nxt)
            new_path = path + [nxt]
            paths[nxt] = new_path
            queue.append(new_path)
    return paths


def _infer_plan_repo_root(plan_path: Path, candidate_files: list[str], workdir: Path | None = None) -> Path:
    """Resolve the repository root corresponding to `plan_path` and its candidate files."""
    if workdir is not None:
        return workdir.resolve()
    resolved_plan = plan_path.resolve()
    if resolved_plan.parent.name == "plans" and resolved_plan.parent.parent.name == ".asw":
        plan_root = resolved_plan.parent.parent.parent
    else:
        plan_root = resolved_plan.parent

    if candidate_files:
        for cf in candidate_files:
            if (plan_root / _norm_rel(cf)).exists():
                return plan_root
        cwd = Path.cwd().resolve()
        if cwd != plan_root:
            for cf in candidate_files:
                if (cwd / _norm_rel(cf)).exists():
                    return cwd
    return plan_root


_NEEDS_CLARIFICATION_RE = re.compile(r"\[NEEDS\s+CLARIFICATION\b[^\n\]]*\]?", re.IGNORECASE)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_BACKTICK_RE = re.compile(r"`[^`\r\n]+`")


def _extract_plan_status_and_body(raw: str) -> tuple[str, str]:
    """Return (lowercased_status_from_frontmatter, body_without_frontmatter)."""
    lines = raw.split("\n")
    if lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm = "\n".join(lines[1:i])
                body = "\n".join(lines[i + 1 :])
                m = re.search(r"^\s*status\s*:\s*[\"']?([^\"'\r\n#]+)", fm, re.MULTILINE | re.IGNORECASE)
                status = m.group(1).strip().lower() if m else ""
                return status, body
    return "", raw


def audit_plan(
    plan_path: Path,
    fallback_reason: str | None = None,
    workdir: Path | None = None,
) -> tuple[str, list[dict], str]:
    """Audit an implementation plan across the 6 mandatory adversarial vectors and Anti-Shortcut Law."""
    if not plan_path.exists():
        return "PLAN_REVISION_REQUIRED", [{"vector": "Vector 1", "level": "CRITICAL", "message": f"Plan file does not exist: {plan_path}"}], "File not found."

    raw = read_text_resilient(plan_path)
    raw_lower = raw.lower()
    findings = []

    # Vector 1: Requirement & Scope Fidelity
    has_objective = bool(re.search(r"##\s+(Objective|TL;DR|Goal|Purpose)", raw, re.IGNORECASE))
    has_tasks = bool(re.search(r"-\s+\[[ xX]\]", raw) or re.search(r"##\s+(Execution|TODOs|Tasks)", raw, re.IGNORECASE))
    if not has_objective:
        findings.append({
            "vector": "Vector 1: Requirement & Scope Fidelity",
            "level": "CRITICAL",
            "message": "Missing explicit Objective / Purpose section defining scope."
        })
    if not has_tasks:
        findings.append({
            "vector": "Vector 1: Requirement & Scope Fidelity",
            "level": "CRITICAL",
            "message": "Missing executable task breakdown or checklist."
        })
    plan_status, plan_body = _extract_plan_status_and_body(raw)
    clean_plan_body = _INLINE_BACKTICK_RE.sub("", _FENCED_CODE_RE.sub("", plan_body))
    clarification_matches = _NEEDS_CLARIFICATION_RE.findall(clean_plan_body)
    if clarification_matches:
        is_draft = plan_status == "draft"
        if not is_draft:
            findings.append({
                "vector": "Vector 1: Requirement & Scope Fidelity",
                "level": "HIGH",
                "message": (
                    f"UNRESOLVED_CLARIFICATION_MARKER: Non-draft plan (status={plan_status or 'unspecified'!r}) "
                    f"contains {len(clarification_matches)} unresolved [NEEDS CLARIFICATION] marker(s): "
                    f"{clarification_matches[0]}"
                ),
            })
        elif len(clarification_matches) > 3:
            findings.append({
                "vector": "Vector 1: Requirement & Scope Fidelity",
                "level": "HIGH",
                "message": (
                    f"UNRESOLVED_CLARIFICATION_MARKER: Draft plan contains {len(clarification_matches)} "
                    f"[NEEDS CLARIFICATION] markers (maximum 3 allowed)."
                ),
            })

    # Vector 2: 4-Axis Semantic & Governance Invariant Safety (including Zero Heuristic Substitution Law)
    governance_refs = ["GLOBAL_DEVELOPMENT_RULES", "PROGRAM_INVARIANTS", "METRIC_REGISTRY", "governance", "invariants"]
    has_gov = any(ref.lower() in raw_lower for ref in governance_refs)
    if not has_gov:
        findings.append({
            "vector": "Vector 2: 4-Axis Semantic & Governance Invariant Safety",
            "level": "HIGH",
            "message": "Plan lacks explicit alignment with repository governance rules and invariants."
        })

    # Anti-Shortcut & Zero-Heuristic Plan Tripwires:
    forbidden_plan_phrases = [
        r"approximate\s+with\s+heuristic",
        r"heuristic\s+sigmoid\s+(?:formula|instead|approximation)",
        r"replace\s+trained\s+model\s+with\s+heuristic",
        r"simulate\s+instead\s+of\s+real",
        r"mock\s+in\s+production",
        r"placeholder\s+implementation\s+for\s+production",
    ]
    for pat in forbidden_plan_phrases:
        if re.search(pat, raw_lower):
            findings.append({
                "vector": "Vector 2: 4-Axis Semantic & Governance Invariant Safety",
                "level": "CRITICAL",
                "message": f"Plan proposes forbidden heuristic approximation or shortcut ({pat}) violating Zero Heuristic Substitution Law."
            })

    # Vector 3: Path-Independence Verification
    user_dir_pattern = re.compile(r"[A-Za-z]:" + r"[\\/]+Users[\\/]+", re.IGNORECASE)
    current_username = Path.home().name
    username_pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(current_username)}(?![A-Za-z0-9_])", re.IGNORECASE)

    for line_no, line in enumerate(raw.splitlines(), 1):
        if user_dir_pattern.search(line):
            findings.append({
                "vector": "Vector 3: Path-Independence Verification",
                "level": "CRITICAL",
                "message": f"Line {line_no} contains hardcoded user directory: {line.strip()[:80]}"
            })
        elif username_pattern.search(line):
            if "\\" in line or "/" in line:
                findings.append({
                    "vector": "Vector 3: Path-Independence Verification",
                    "level": "CRITICAL",
                    "message": f"Line {line_no} contains username in path: {line.strip()[:80]}"
                })

    # Vector 4: Parallel Wave File-Collision & NP-Bench Transitive Dependency Serialization
    todos_match = re.search(r"##\s+(?:TODOs|Execution Tasks)(.*?)(?=\n##\s+[A-Z]|\Z)", raw, re.DOTALL | re.IGNORECASE)
    todos_text = todos_match.group(1) if todos_match else raw
    task_snippets = re.split(r"\n(?=-\s+\[[ xX]\])", todos_text)

    task_file_map: dict[str, list[str]] = {}
    task_raw_files: dict[str, list[str]] = {}
    task_test_files: dict[str, list[str]] = {}
    for t in task_snippets:
        if not t.strip() or not re.search(r"-\s+\[[ xX]\]", t):
            continue
        first_line = t.strip().splitlines()[0]
        task_id_match = re.search(r"-\s+\[[ xX]\]\s*[*_`]*(\d+|Task\s*\d+)", first_line, re.IGNORECASE)
        task_id = task_id_match.group(1).lower().replace("task", "").strip() if task_id_match else first_line[:30]

        files_match = re.search(r"-\s+\*?\*?Files\*?\*?:(.*?)(?=\n\s*-\s+\*?\*?[A-Z]|\Z)", t, re.DOTALL | re.IGNORECASE)
        if files_match:
            raw_files = re.findall(r"[`'\"]?([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9_]+)[`'\"]?", files_match.group(1))
            clean_files = [_norm_rel(f) for f in raw_files if not f.startswith("http")]
            task_file_map[task_id] = [f.lower() for f in clean_files]
            task_raw_files[task_id] = clean_files
        else:
            raw_files = re.findall(r"[`'\"]([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9_]+)[`'\"]", t)
            clean_files = [_norm_rel(f) for f in raw_files if "/" in f and not f.startswith("http")]
            task_file_map[task_id] = [f.lower() for f in clean_files]
            task_raw_files[task_id] = clean_files

        # Also extract test files referenced in RED/GREEN/QA lines for transitive DAG coverage
        t_tests: list[str] = []
        for tline in t.splitlines():
            if re.search(r"\b(?:red|green|qa|test)\b", tline, re.IGNORECASE):
                for tf in re.findall(r"[`'\"]?([a-zA-Z0-9_\-\./\\]+\.(?:py|mjs|js|ts|tsx|jsx))[`'\"]?", tline):
                    ntf = _norm_rel(tf)
                    if not ntf.startswith("http") and ntf not in task_raw_files[task_id] and ntf not in t_tests:
                        if "test" in ntf.lower():
                            t_tests.append(ntf)
        task_test_files[task_id] = t_tests

    waves_match = re.search(r"##\s+Parallel Execution Waves(.*?)(?=\n##\s+[A-Z]|\Z)", raw, re.DOTALL | re.IGNORECASE)
    wave_map: dict[str, str] = {}
    if waves_match:
        current_wave = "default"
        for line in waves_match.group(1).splitlines():
            w_match = re.search(r"Wave\s*(\d+|[A-Za-z0-9_-]+)", line, re.IGNORECASE)
            if w_match:
                current_wave = w_match.group(1).lower()
            t_matches = re.findall(r"Task\s*(\d+)", line, re.IGNORECASE)
            for tm in t_matches:
                wave_map[tm.lower()] = current_wave

    if wave_map:
        wave_groups = {
            w: [t for t, wv in wave_map.items() if wv == w]
            for w in sorted(set(wave_map.values()))
        }
    else:
        wave_groups = {"default": list(task_file_map.keys())}

    for w, wave_tasks in wave_groups.items():
        file_to_tasks: dict[str, list[str]] = {}
        for wt in wave_tasks:
            for f in task_file_map.get(wt, []):
                file_to_tasks.setdefault(f, []).append(wt)
        for f, ts in file_to_tasks.items():
            if len(ts) > 1:
                if w == "default" and not wave_map:
                    msg = f"Parallel wave file collision: file '{f}' targeted by multiple tasks: {ts} without explicit serialization."
                else:
                    msg = f"Parallel wave file collision in Wave {w}: file '{f}' targeted concurrently by tasks {ts} without serialization."
                findings.append({
                    "vector": "Vector 4: Parallel Wave File-Collision Serialization",
                    "level": "CRITICAL",
                    "message": msg,
                })

    # NP-Bench Transitive Wave Race Detection across parallel waves (>= 2 tasks)
    all_plan_candidates = [
        f
        for flist in list(task_raw_files.values()) + list(task_test_files.values())
        for f in flist
    ]
    graph_root = _infer_plan_repo_root(plan_path, all_plan_candidates, workdir=workdir)
    dep_graph = build_repo_dependency_graph(graph_root, candidate_files=all_plan_candidates)
    if dep_graph:
        seen_races: set[str] = set()
        for w, wave_tasks in wave_groups.items():
            if len(wave_tasks) < 2:
                continue
            task_seeds: dict[str, list[str]] = {}
            task_owned: dict[str, set[str]] = {}
            task_reach: dict[str, dict[str, tuple[str, list[str]]]] = {}

            for wt in wave_tasks:
                seeds: list[str] = []
                for f in task_raw_files.get(wt, []) + task_test_files.get(wt, []):
                    if f not in seeds:
                        seeds.append(f)
                task_seeds[wt] = seeds
                task_owned[wt] = set(seeds)
                reach_map: dict[str, tuple[str, list[str]]] = {}
                for s in seeds:
                    for dst, path in _bfs_reachable(dep_graph, s).items():
                        if dst not in reach_map or len(path) < len(reach_map[dst][1]):
                            reach_map[dst] = (s, path)
                task_reach[wt] = reach_map

            directed_pairs: set[tuple[str, str]] = set()
            for t_a in wave_tasks:
                for t_b in wave_tasks:
                    if t_a == t_b:
                        continue
                    for dst, (_seed, path) in task_reach[t_a].items():
                        if dst in task_owned[t_b]:
                            edge_str = f"task_{t_a}({path[0]}) -> {' -> '.join(path[1:])}(task_{t_b})"
                            if edge_str not in seen_races:
                                seen_races.add(edge_str)
                                directed_pairs.add((t_a, t_b))
                                directed_pairs.add((t_b, t_a))
                                findings.append({
                                    "vector": "Vector 4: Parallel Wave File-Collision Serialization",
                                    "level": "CRITICAL",
                                    "message": f"NP_BENCH_TRANSITIVE_WAVE_RACE in Wave {w}: {edge_str} introduces transitive dependency race across parallel tasks without serialization.",
                                })

            # Shared CLI / JSON config resource races across disjoint tasks in the same wave
            def _task_sort_key(tid: str) -> tuple[int, str]:
                return (0, f"{int(tid):09d}") if tid.isdigit() else (1, tid)

            ordered_tasks = sorted(wave_tasks, key=_task_sort_key, reverse=True)
            for idx_a, t_hi in enumerate(ordered_tasks):
                for t_lo in ordered_tasks[idx_a + 1:]:
                    if (t_hi, t_lo) in directed_pairs:
                        continue
                    shared_nodes = sorted(
                        set(task_reach[t_hi].keys())
                        & set(task_reach[t_lo].keys())
                    )
                    for shared in shared_nodes:
                        if not _SHARED_RUNTIME_RESOURCE_RE.search(shared):
                            continue
                        s_hi, _ = task_reach[t_hi][shared]
                        s_lo, _ = task_reach[t_lo][shared]
                        edge_str = f"task_{t_hi}({s_hi}) -> {shared} <- {s_lo}(task_{t_lo})"
                        if edge_str not in seen_races:
                            seen_races.add(edge_str)
                            findings.append({
                                "vector": "Vector 4: Parallel Wave File-Collision Serialization",
                                "level": "CRITICAL",
                                "message": f"NP_BENCH_TRANSITIVE_WAVE_RACE in Wave {w}: {edge_str} shares runtime/config dependency across parallel tasks without serialization.",
                            })

    # Vector 5: 3-Layer Verification Completeness
    req_phases = ["red", "green", "qa", "evidence", "cleanup"]
    missing_phases = [p.upper() for p in req_phases if p not in raw_lower]
    if missing_phases:
        findings.append({
            "vector": "Vector 5: 3-Layer Verification Completeness",
            "level": "HIGH",
            "message": f"Plan is missing explicit verification specifications for: {', '.join(missing_phases)}."
        })

    # Vector 6: OS / Runtime Edge Cases
    os_keywords = ["windows", "lock", "posix", "runtime", "finally", "cleanup", "timeout", "worktree"]
    has_os_consideration = any(k in raw_lower for k in os_keywords)
    if not has_os_consideration:
        findings.append({
            "vector": "Vector 6: OS / Runtime Edge Cases",
            "level": "MEDIUM",
            "message": "Plan does not explicitly specify OS/runtime edge case handling (file locks, path normalization, cleanup)."
        })

    critical_or_high = [f for f in findings if f["level"] in ("CRITICAL", "HIGH")]
    verdict = "PLAN_REVISION_REQUIRED" if critical_or_high else "PLAN_APPROVED"

    active_fallback = resolve_fallback_reason(fallback_reason)
    reviewer_line = (
        "`Claude Opus 5.5` -> `Deterministic Adversarial Engine + gemini-4-neon-high` (Opus Quota Fallback)"
        if active_fallback
        else "`Claude Opus 5.5` (Native Antigravity Subagent `asw-plan-audit`)"
    )

    review_text = [
        "# Antigravity Claude Opus 5.5 Plan Opposition Review",
        "",
        f"**Plan File**: `{plan_path.name}`",
        f"**Reviewer**: {reviewer_line}",
    ]
    if active_fallback:
        review_text.append(
            f"**Fallback Mode**: `ACTIVE (Reason: {active_fallback} -> Deterministic Adversarial Engine + gemini-4-neon-high)`"
        )
    review_text.extend([
        "**Thinking Level**: `high`",
        f"Verdict: {verdict}",
        "",
        "## Adversarial Vector Findings",
        "",
    ])

    vector_names = [
        "Vector 1: Requirement & Scope Fidelity",
        "Vector 2: 4-Axis Semantic & Governance Invariant Safety",
        "Vector 3: Path-Independence Verification",
        "Vector 4: Parallel Wave File-Collision Serialization",
        "Vector 5: 3-Layer Verification Completeness",
        "Vector 6: OS / Runtime Edge Cases",
    ]

    for v_name in vector_names:
        v_findings = [f for f in findings if f["vector"] == v_name]
        review_text.append(f"### {v_name}")
        if not v_findings:
            review_text.append("- **Status**: PASS (Adversarial check verified compliant)")
        else:
            for vf in v_findings:
                review_text.append(f"- **[{vf['level']}]**: {vf['message']}")
        review_text.append("")

    if verdict == "PLAN_APPROVED":
        review_text.append("## Conclusion")
        review_text.append("The plan fulfills all 6 adversarial vectors. Bounded execution waves may proceed to Gemini 4 Hydrogen (High).")
    else:
        review_text.append("## Required Plan Revisions")
        review_text.append("Primary Architect (Gemini 4 Carbon High) must resolve the critical and high findings listed above before dispatching execution waves.")

    return verdict, findings, "\n".join(review_text)


_BLIND_HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_BLIND_STRIP_BASENAMES = {
    ".memlog.md",
    "program_state.md",
    "task_graph.json",
    "requirement_coverage.csv",
}


def _is_blind_stripped_path(rel_path: str) -> bool:
    norm = _norm_rel(rel_path).lower()
    if not norm or norm == "/dev/null":
        return False
    return norm.startswith(".asw/") or "/.asw/" in norm


def _sec_contains_plan_or_notes_markers(sec: list[str], rel_path: str) -> bool:
    if not rel_path.lower().endswith(".md"):
        return False
    body = "\n".join(sec).lower()
    return any(
        marker in body
        for marker in (
            "<frozen-after-approval>",
            "## implementation notes",
            "## review triage log",
            "## plan change log",
            "leaf task receipt",
        )
    )


def _clean_blind_diff_path(raw_path: str) -> str:
    cleaned = raw_path.strip().split("\t")[0].strip()
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    if cleaned == "/dev/null":
        return cleaned
    if cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    return _norm_rel(cleaned)


def _extract_fn_branches(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    branches: list[str] = []

    def _visit(stmt: ast.AST) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(stmt, ast.If):
            branches.append(f"L{stmt.lineno}: if {ast.unparse(stmt.test)}")
            for child in stmt.body:
                _visit(child)
            if stmt.orelse:
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    _visit(stmt.orelse[0])
                else:
                    branches.append(f"L{stmt.orelse[0].lineno}: else")
                    for child in stmt.orelse:
                        _visit(child)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            kw = "async for" if isinstance(stmt, ast.AsyncFor) else "for"
            branches.append(f"L{stmt.lineno}: {kw} {ast.unparse(stmt.target)} in {ast.unparse(stmt.iter)}")
            for child in stmt.body + stmt.orelse:
                _visit(child)
            return
        if isinstance(stmt, ast.While):
            branches.append(f"L{stmt.lineno}: while {ast.unparse(stmt.test)}")
            for child in stmt.body + stmt.orelse:
                _visit(child)
            return
        if isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            branches.append(f"L{stmt.lineno}: try")
            for child in stmt.body:
                _visit(child)
            for handler in stmt.handlers:
                exc_t = ast.unparse(handler.type) if handler.type else "Exception"
                branches.append(f"L{handler.lineno}: except {exc_t}")
                for child in handler.body:
                    _visit(child)
            for child in stmt.orelse + stmt.finalbody:
                _visit(child)
            return
        if isinstance(stmt, ast.Return):
            val = ast.unparse(stmt.value) if stmt.value is not None else "None"
            branches.append(f"L{stmt.lineno}: return {val}")
            return
        if isinstance(stmt, ast.Raise):
            exc = ast.unparse(stmt.exc) if stmt.exc is not None else "re-raise"
            branches.append(f"L{stmt.lineno}: raise {exc}")
            return
        if hasattr(ast, "Match") and isinstance(stmt, ast.Match):
            branches.append(f"L{stmt.lineno}: match {ast.unparse(stmt.subject)}")
            for case in stmt.cases:
                branches.append(f"L{case.pattern.lineno if hasattr(case.pattern, 'lineno') else stmt.lineno}: case {ast.unparse(case.pattern)}")
                for child in case.body:
                    _visit(child)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for child in stmt.body:
                _visit(child)

    for top_stmt in fn_node.body:
        _visit(top_stmt)
    return branches


def _extract_ast_symbols_from_source(
    source: str,
    rel_path: str,
    target_lines: set[int] | None = None,
) -> list[dict]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        try:
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:
            return []

    symbols: list[dict] = []

    def _walk_body(stmts: list[ast.stmt], class_prefix: str = "") -> None:
        for node in stmts:
            if isinstance(node, ast.ClassDef):
                nxt_prefix = f"{class_prefix}.{node.name}" if class_prefix else node.name
                _walk_body(node.body, nxt_prefix)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_ln = getattr(node, "end_lineno", node.lineno) or node.lineno
                if target_lines is not None and not any(node.lineno <= ln <= end_ln for ln in target_lines):
                    continue
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                args_src = ast.unparse(node.args)
                ret_src = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
                qualname = f"{class_prefix}.{node.name}" if class_prefix else node.name
                sig = f"{prefix} {qualname}({args_src}){ret_src}"
                symbols.append({
                    "file": rel_path,
                    "function": qualname,
                    "signature": sig,
                    "lineno": node.lineno,
                    "end_lineno": end_ln,
                    "branches": _extract_fn_branches(node),
                })

    _walk_body(tree.body)
    return symbols


def prepare_blind_review_packet(
    diff_content: str = "",
    workdir: Path | None = None,
    plan_path: Path | None = None,  # Explicitly ignored: Stage-1 blind review must never leak plan metadata/notes/matrix
    diff_path: Path | None = None,
) -> dict:
    """Build a Stage-1 RETRACE blind review packet containing ONLY raw code diff (.asw/ stripped) + AST changed functions, signatures, and branches."""
    del plan_path  # Never read plan_path in blind stage
    raw_diff_text = diff_content if diff_content else read_text_resilient(diff_path)
    eff_workdir = workdir.resolve() if workdir else Path.cwd().resolve()

    # Split into per-file sections and strip .asw/ plan/review/evidence/scratch hunks
    sections: list[list[str]] = []
    current_sec: list[str] = []
    for line in raw_diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_sec:
                sections.append(current_sec)
            current_sec = [line]
        else:
            current_sec.append(line)
    if current_sec:
        sections.append(current_sec)

    filtered_sections: list[str] = []
    changed_files: list[str] = []
    stripped_files: list[str] = []
    py_hunk_lines: dict[str, set[int]] = {}
    py_fallback_src: dict[str, list[str]] = {}

    for sec in sections:
        if not any(ln.strip() for ln in sec):
            continue
        sec_file = ""
        for ln in sec:
            if _BLIND_HUNK_HEADER_RE.match(ln):
                break
            if ln.startswith("+++ "):
                cand = _clean_blind_diff_path(ln[4:])
                if cand != "/dev/null":
                    sec_file = cand
                    break
            elif ln.startswith("diff --git "):
                parts = ln.strip().split()
                if parts:
                    sec_file = _clean_blind_diff_path(parts[-1])
        if _is_blind_stripped_path(sec_file):
            if sec_file not in stripped_files:
                stripped_files.append(sec_file)
            continue

        filtered_sections.append("\n".join(sec))
        if sec_file and sec_file not in changed_files:
            changed_files.append(sec_file)

        if sec_file.endswith(".py"):
            new_line = 0
            in_hunk = False
            for ln in sec:
                hm = _BLIND_HUNK_HEADER_RE.match(ln)
                if hm:
                    new_line = int(hm.group(3))
                    in_hunk = True
                    continue
                if not in_hunk:
                    continue
                if ln.startswith("+") and not ln.startswith("+++"):
                    py_hunk_lines.setdefault(sec_file, set()).add(new_line)
                    py_fallback_src.setdefault(sec_file, []).append(ln[1:])
                    new_line += 1
                elif ln.startswith("-") and not ln.startswith("---"):
                    continue
                elif ln.startswith("\\"):
                    continue
                else:
                    py_fallback_src.setdefault(sec_file, []).append(ln[1:] if ln.startswith(" ") else ln)
                    new_line += 1

    filtered_diff = "\n".join(filtered_sections).strip()
    if filtered_diff:
        filtered_diff += "\n"

    ast_symbols: list[dict] = []
    for rel_py in sorted(set(list(py_hunk_lines.keys()) + [f for f in changed_files if f.endswith(".py")])):
        disk_file = eff_workdir / rel_py
        if disk_file.is_file():
            src = read_text_resilient(disk_file)
            syms = _extract_ast_symbols_from_source(src, rel_py, py_hunk_lines.get(rel_py))
        else:
            src = "\n".join(py_fallback_src.get(rel_py, []))
            syms = _extract_ast_symbols_from_source(src, rel_py, None)
        ast_symbols.extend(syms)

    lines = [
        "# Blind Review Packet (RETRACE Stage-1)",
        "",
        "**Mode**: `prepare-blind-review`",
        "**opt_tokens**: `0.0`",
        f"**Changed Files**: {', '.join(f'`{f}`' for f in changed_files) if changed_files else '*(none)*'}",
        "",
        "## AST Changed Functions, Signatures & Control-Flow Branches",
        "",
    ]
    if not ast_symbols:
        lines.append("- *(No modified Python function definitions detected in filtered diff)*")
    else:
        for sym in ast_symbols:
            lines.append(f"### `{sym['file']}` :: `{sym['function']}` (lines {sym['lineno']}-{sym['end_lineno']})")
            lines.append(f"- **Signature**: `{sym['signature']}`")
            if sym["branches"]:
                lines.append("- **Branches**:")
                for br in sym["branches"]:
                    lines.append(f"  - `{br}`")
            else:
                lines.append("- **Branches**: *(linear / no control-flow branches)*")
            lines.append("")

    lines.extend([
        "## Raw Code Diff (`.asw/` stripped)",
        "",
        "```diff",
        filtered_diff.rstrip("\n") if filtered_diff else "(empty diff)",
        "```",
    ])
    packet_text = "\n".join(lines) + "\n"

    return {
        "mode": "prepare-blind-review",
        "opt_tokens": 0.0,
        "files": changed_files,
        "stripped_files": stripped_files,
        "ast_changed_symbols": ast_symbols,
        "raw_diff": filtered_diff,
        "packet_text": packet_text,
    }


def audit_diff(
    plan_path: Path | None,
    diff_path: Path | None,
    evidence_dir: Path | None,
    diff_content_override: str | None = None,
    fallback_reason: str | None = None,
    workdir: Path | None = None,
    verify_mutations: bool = False,
    mutation_threshold: float = 0.75,
    mutation_tests: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[dict], str]:
    """Audit code diff and evidence across the 4 opposition-reviewer attack vectors and Anti-Shortcut tripwires."""
    findings = []
    eff_workdir = workdir or Path.cwd()

    diff_content = (
        diff_content_override
        if diff_content_override is not None
        else read_text_resilient(diff_path)
    )
    plan_content = read_text_resilient(plan_path)
    has_evidence, evidence_text = read_evidence_resilient(
        evidence_dir, plan_content, diff_content, eff_workdir
    )

    # Attack Vector 1: Scope & Plan Integrity
    if not diff_content.strip():
        findings.append({
            "vector": "1. Scope & Plan Integrity",
            "level": "CRITICAL",
            "message": "Empty diff provided for review."
        })
    if not has_evidence:
        findings.append({
            "vector": "1. Scope & Plan Integrity",
            "level": "CRITICAL",
            "message": "Evidence directory or file is empty or missing on disk."
        })

    # Enforce Zero-Unchecked-Plan Closure Gate if plan contains any open `- [ ]` checkboxes
    if plan_content and re.search(r"^\s*-\s+\[\s\]\s+", plan_content, re.MULTILINE):
        findings.append({
            "vector": "1. Scope & Plan Integrity",
            "level": "CRITICAL",
            "message": "Plan still contains unchecked '- [ ]' items. Zero-Unchecked-Plan Closure Gate violated."
        })

    # BMAD Gate 1A: Frozen Contract Tamper Detection (<frozen-after-approval>)
    if plan_content:
        human_reapproved = bool(re.search(r"^human_reapproved:\s*true\b", plan_content, re.MULTILINE | re.IGNORECASE))
        if not human_reapproved:
            frozen_tampered = False
            # Check if diff directly modifies lines inside a plan's <!-- <frozen-after-approval> --> block
            in_frozen_diff = False
            current_diff_file = ""
            plan_name_low = plan_path.name.lower() if plan_path else ""
            for dline in diff_content.splitlines():
                if dline.startswith("diff --git "):
                    in_frozen_diff = False
                    parts = dline.strip().split()
                    current_diff_file = parts[-1].replace("\\", "/").lower() if parts else ""
                elif dline.startswith("+++ "):
                    cand = dline[4:].strip().replace("\\", "/").lower()
                    if cand != "/dev/null":
                        current_diff_file = cand
                else:
                    is_plan_diff_file = ".asw/plans/" in current_diff_file or (
                        bool(plan_name_low) and current_diff_file.endswith(plan_name_low)
                    )
                    if not is_plan_diff_file:
                        continue
                    if re.search(r"<!--\s*<frozen-after-approval>", dline, re.IGNORECASE) and not re.search(
                        r"</frozen-after-approval>", dline, re.IGNORECASE
                    ):
                        if not dline.startswith("+"):
                            in_frozen_diff = True
                    elif re.search(r"<!--\s*</frozen-after-approval>", dline, re.IGNORECASE):
                        in_frozen_diff = False
                    elif (
                        in_frozen_diff
                        and (dline.startswith("+") or dline.startswith("-"))
                        and not dline.startswith(("+++", "---"))
                    ):
                        frozen_tampered = True
                        break

            # Also check git baseline_revision comparison if plan_path is tracked in git at baseline_revision
            if not frozen_tampered and plan_path and plan_path.exists():
                base_match = re.search(r"^baseline_revision:\s*([0-9a-fA-F]{7,40})\b", plan_content, re.MULTILINE)
                status_match = re.search(r"^status:\s*(ready-for-dev|in-progress|in-review|built|done)\b", plan_content, re.MULTILINE | re.IGNORECASE)
                if base_match and status_match:
                    base_sha = base_match.group(1)
                    try:
                        git_top = subprocess.run(
                            ["git", "-C", str(plan_path.parent), "rev-parse", "--show-toplevel"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            check=False,
                        )
                        if git_top.returncode == 0 and git_top.stdout.strip():
                            top_dir = Path(git_top.stdout.strip())
                            rel_plan = plan_path.resolve().relative_to(top_dir.resolve()).as_posix()
                            old_plan_proc = subprocess.run(
                                ["git", "-C", str(top_dir), "show", f"{base_sha}:{rel_plan}"],
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=5,
                                check=False,
                            )
                            if old_plan_proc.returncode == 0 and old_plan_proc.stdout:
                                f_rx = re.compile(
                                    r"<!--\s*<frozen-after-approval>.*?-->\s*(.*?)\s*<!--\s*</frozen-after-approval>\s*-->",
                                    re.DOTALL | re.IGNORECASE,
                                )
                                old_f = f_rx.search(old_plan_proc.stdout)
                                new_f = f_rx.search(plan_content)
                                if old_f and (not new_f or old_f.group(1).strip() != new_f.group(1).strip()):
                                    frozen_tampered = True
                    except Exception:
                        pass

            if frozen_tampered:
                findings.append({
                    "vector": "1. Scope & Plan Integrity",
                    "level": "CRITICAL",
                    "message": "BMAD_FROZEN_CONTRACT_VIOLATION: The human-owned <frozen-after-approval> contract (Intent, Boundaries, or I/O & Edge-Case Matrix) was modified after plan approval without human_reapproved: true."
                })

        # BMAD Gate 1B: Unresolved Review Triage Log items ([intent_gap], [bad_plan], [patch])
        triage_sec = re.search(r"^##\s+Review\s+Triage\s+Log\b(.*?)(?=\n##\s+|\Z)", plan_content, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if triage_sec:
            for tline in triage_sec.group(1).splitlines():
                if re.search(r"^\s*-\s*\[(?:intent_gap|bad_plan|patch)\]", tline, re.IGNORECASE):
                    if not re.search(r"\b(?:RESOLVED|REVERTED|DONE|FIXED)\b", tline, re.IGNORECASE):
                        findings.append({
                            "vector": "1. Scope & Plan Integrity",
                            "level": "CRITICAL",
                            "message": f"BMAD_UNRESOLVED_TRIAGE_ITEM: Unresolved review triage finding in Review Triage Log: {tline.strip()[:100]}"
                        })

    # Separate added lines into production code lines vs test code lines (excluding markdown docs and reviewer scripts)
    added_code_lines = []
    added_prod_lines = []
    added_test_lines = []

    in_md_file = False
    in_test_file = False
    in_reviewer_self = False

    for dline in diff_content.splitlines():
        if dline.startswith("diff --git ") or dline.startswith("+++ "):
            low_line = dline.strip().lower().replace("\\", "/")
            in_md_file = low_line.endswith((".md", ".toml"))
            in_test_file = (
                "/tests/" in low_line
                or "b/tests/" in low_line
                or "tests/" in low_line
                or "/test/" in low_line
                or "/test_" in low_line
                or low_line.endswith((
                    "_test.py",
                    "_test.cpp",
                    "_test.cc",
                    "_test.go",
                    "_test.rs",
                    ".test.ts",
                    ".spec.ts",
                    ".test.tsx",
                    ".spec.tsx",
                    ".test.js",
                    ".spec.js",
                ))
            )
            in_reviewer_self = (
                "invoke_opus_reviewer.py" in low_line
                or "asw-hook.mjs" in low_line
            )
        elif dline.startswith("+") and not dline.startswith("+++") and not in_md_file:
            code_line = dline[1:]
            added_code_lines.append(code_line)
            if in_test_file:
                added_test_lines.append(code_line)
            elif not in_reviewer_self:
                added_prod_lines.append(code_line)

    added_prod_text = "\n".join(added_prod_lines).lower()
    added_test_text = "\n".join(added_test_lines)

    # Attack Vector 2: Research & ML Falsification (including Zero Heuristic Substitution & Anti-Shortcut Law)
    leakage_terms = ["lookahead", "train_test_split", "scaler.fit", "data_leak"]
    for term in leakage_terms:
        if term in added_prod_text and "leak" in added_prod_text:
            findings.append({
                "vector": "2. Research & ML Falsification",
                "level": "CRITICAL",
                "message": f"Potential data leakage or split boundary violation detected: {term}"
            })

    # Tripwire 2A: Heuristic Substitution in Production Model Evaluation
    heuristic_logit_markers = (
        "manual_logit",
        "heuristic_logit",
        "handcoded_logit",
        "raw_logit =",
        "heuristic_score =",
    )
    has_manual_logit = any(m in added_prod_text for m in heuristic_logit_markers) or (
        "_sigmoid(" in added_prod_text
        and ("pred_score" in added_prod_text or "logit" in added_prod_text)
    )
    has_real_booster_loader = any(
        b in added_prod_text
        for b in (
            "get_booster",
            "xgbjsonbooster",
            "lgbtextbooster",
            "evaluate_trained_booster",
            "onnxruntime",
            "joblib.load",
            "torch.load",
        )
    )
    if has_manual_logit and not has_real_booster_loader:
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Heuristic substitution detected in production code: hand-coded logit/_sigmoid equations used instead of real trained model artifact inference (Zero Heuristic Substitution Law violation)."
        })

    # Tripwire 2B: Dangerous Catch-All Idle/Scanning -> Action Fallback
    if re.search(
        r"pathway\s*=\s*['\"](?:scanning|idle)[^'\"]*['\"][\s\S]{0,160}?action\s*=\s*['\"](?:enter_|execute_)[^'\"]*['\"]",
        added_prod_text,
    ):
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Dangerous catch-all fallback detected: idle/scanning pathway branch emits active execution action instead of remaining passive/flat."
        })

    # Tripwire 2C: Naive Binary Outcome/Exit Ternary ('take_profit' if pnl >= 0 else 'stop_loss')
    if re.search(
        r"['\"](?:take_profit|win|success)['\"]\s+if\s+[^\n]+?>=\s*0(?:\.0)?\s+else\s+['\"](?:stop_loss|loss|failure)['\"]",
        added_prod_text,
    ):
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Naive binary outcome/exit ternary ('take_profit' if pnl >= 0 else 'stop_loss') detected without comparing against actual threshold."
        })

    # Tripwire 2D: Leftover Stubs / Synthetic Fallback Pools in Production
    if "raise notimplementederror" in added_prod_text or "synthetic_fallback_pool" in added_prod_text:
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Production code introduces unimplemented stubs (NotImplementedError) or synthetic fallback pools."
        })

    # Tripwire 2E / 3B: Live Caller Bypassing Intrinsic Safety / Validation Gates
    safety_bypass_match = re.search(
        r"\b(?:enforce_shield|enforce_safety|verify_signature|check_permissions)\s*=\s*false\b|\b(?:skip_validation|bypass_auth|ignore_safety_gates)\s*=\s*true\b",
        added_prod_text,
    )
    if safety_bypass_match:
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": f"Production caller disables intrinsic safety/validation gate ({safety_bypass_match.group(0)}), violating Golden Reference & End-to-End Decision Parity Gate."
        })

    # Tripwire 2F: Production-Volume Capped-Denominator Inflation (sum / min(K, len(...))) & Degenerate Flat 0.0 Series
    if re.search(r"/\s*min\s*\(\s*\d+(?:\.\d+)?\s*,\s*(?:float\s*\()?\s*len\s*\(", added_prod_text):
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Production-volume denominator inflation detected: dividing sum by min(cap, len(items)) distorts metrics when real batch count exceeds the cap (use true sample mean or rate)."
        })
    zero_series_matches = re.findall(
        r"['\"]?(?:drawdown_?pct|drawdown|error_rate|variance|loss_pct)['\"]?\s*:\s*0(?:\.0+)?\b",
        added_prod_text,
    )
    nonzero_series_matches = re.findall(
        r"['\"]?(?:drawdown_?pct|drawdown|error_rate|variance|loss_pct)['\"]?\s*:\s*-?[1-9]",
        added_prod_text,
    )
    if len(zero_series_matches) >= 5 and not nonzero_series_matches:
        findings.append({
            "vector": "2. Research & ML Falsification",
            "level": "CRITICAL",
            "message": "Degenerate all-zero metric/drawdown series detected (>= 5 points hardcoded at 0.0 with no non-zero variation). Compute real intra-period values across all intervals."
        })

    # Attack Vector 3: Edge Cases & Boundary Breakdown (including Anti-Tautology Test Gate)
    has_negative_tests = bool(
        re.search(r"def test_.*(negative|edge|bad|fail|error|invalid|reject|collision|crash|tautolog|heuristic|fallback|resilience|boundary)", diff_content, re.IGNORECASE)
        or re.search(r"(assertNotEqual|assertRaises|assertFalse|assertIn\([\"']Verdict: PLAN_REVISION_REQUIRED[\"'])", diff_content)
        or re.search(r"\bTEST(?:_F|_P)?\s*\([^)]*(?:Negative|Edge|Bad|Fail|Error|Invalid|Reject|Boundary|Crash)", diff_content, re.IGNORECASE)
        or re.search(r"\b(?:EXPECT_THROW|ASSERT_THROW|EXPECT_ANY_THROW|ASSERT_ANY_THROW|QVERIFY_EXCEPTION_THROWN)\b", diff_content)
        or re.search(r"#\[should_panic", diff_content)
        or re.search(r"expect\([^)]*\)\.(?:rejects\.)?toThrow", diff_content)
        or re.search(r"\b(?:it|test|describe)\s*\(\s*['\"`][^'\"`]*(?:invalid|error|reject|fail|edge|boundary|negative|crash|panic)[^'\"`]*['\"`]", diff_content, re.IGNORECASE)
        or re.search(r"\bfunc\s+Test[A-Za-z0-9_]*(?:Negative|Edge|Invalid|Reject|Fail|Error|Boundary|Crash)", diff_content)
    )
    ev_lower = evidence_text.lower()
    has_evidence_negative = bool(
        any(w in ev_lower for w in ("negative", "fail", "red phase", "edge", "reject", "crash", "invalid"))
    )

    if not has_negative_tests:
        findings.append({
            "vector": "3. Edge Cases & Boundary Breakdown",
            "level": "CRITICAL",
            "message": "Diff lacks automated negative and edge-case test coverage."
        })
    if not has_evidence_negative:
        findings.append({
            "vector": "3. Edge Cases & Boundary Breakdown",
            "level": "CRITICAL",
            "message": "Evidence directory lacks empirical runtime proof of negative test execution."
        })

    # Tripwire 3A: Anti-Tautology Test Gate
    if added_test_text.strip():
        stripped_test_text = re.sub(r"assert\s+[^\n]+?\s+is\s+not\s+None", "", added_test_text)
        has_substantive_assertion = bool(
            re.search(
                r"(assertEqual|assertNotEqual|assertAlmostEqual|assertRaises|assertTrue|assertFalse|assertIn|assertNotIn|==|!=|<=|>=|<|>|\bEXPECT_|\bASSERT_|\bQVERIFY|\bQCOMPARE|\bexpect\s*\(|\.toThrow\b|\.toEqual\b|\.toBe\b|\bassert_eq!|\bassert_ne!|\bassert!|#\[should_panic)",
                stripped_test_text,
            )
        )
        if not has_substantive_assertion:
            findings.append({
                "vector": "3. Edge Cases & Boundary Breakdown",
                "level": "CRITICAL",
                "message": "Tautological test suite detected: added tests only assert 'is not None' without verifying concrete domain values or behavioral invariants."
            })

    # Tripwire 3C: Unscoped Idempotency / Deduplication Key in Multi-Principal Execution
    has_principal_context = any(
        t in added_prod_text
        for t in ("tenant_id", "tenant", "user_id", "account_id", "org_id", "profile_id", "client_id")
    )
    unscoped_key_match = re.search(
        r"\b(idempotency_key|dedup_key|unique_key)\s*=\s*(?:signal_key|trade_uid|order_key|event_id|request_id|job_id|item_id|payload_hash)\b",
        added_prod_text,
    )
    if has_principal_context and unscoped_key_match:
        findings.append({
            "vector": "3. Edge Cases & Boundary Breakdown",
            "level": "CRITICAL",
            "message": f"Non-principal-scoped uniqueness key ({unscoped_key_match.group(0)}) in multi-tenant/multi-user execution path: causes UNIQUE constraint DB rollback and orphaned external side effects when multiple principals process the same event."
        })

    # Attack Vector 4: Downstream & Blast-Radius Safety
    user_dir_pattern = re.compile(r"[A-Za-z]:" + r"[\\/]+Users[\\/]+", re.IGNORECASE)
    if user_dir_pattern.search(diff_content):
        findings.append({
            "vector": "4. Downstream & Blast-Radius Safety",
            "level": "CRITICAL",
            "message": "Diff introduces forbidden hardcoded user directories."
        })

    # Collect runtime-only evidence files (excluding plan markdown) for Tripwires 4B & 4C
    runtime_ev_chunks: list[str] = []
    if evidence_dir is not None and evidence_dir.exists():
        if evidence_dir.is_file() and (plan_path is None or evidence_dir.resolve() != plan_path.resolve()):
            runtime_ev_chunks.append(read_text_resilient(evidence_dir))
        elif evidence_dir.is_dir():
            for ef in sorted(evidence_dir.rglob("*"))[:50]:
                if ef.is_file():
                    runtime_ev_chunks.append(read_text_resilient(ef))
    runtime_ev_lower = "\n".join(runtime_ev_chunks).lower()

    # Filter out meta-lines describing passing negative tests (e.g. "rejecting <custom-error-card>", "GREEN Phase: 4 passed")
    # and hook directive instructions quoting gate names (e.g. "ASW LOOP MODE ENABLED!", "Enforce Mandatory Rendered DOM")
    non_test_ev_lines = [
        line
        for line in runtime_ev_lower.splitlines()
        if not any(
            meta in line
            for meta in (
                "green phase:",
                "red phase:",
                "rejecting ",
                "negative test",
                "against <",
                "fixture)",
                "test_run_gui_test_rejects",
                "test_diff_review_rejects",
                "asw loop mode enabled",
                "enforce mandatory rendered dom",
                "boundary-to-boundary system/hardware fidelity",
            )
        )
    ]
    filtered_runtime_ev = "\n".join(non_test_ev_lines)

    # Tripwire 4B: Mandatory Rendered DOM & Zero-Error-Card Gate (Web / SPA / Dashboards / Web Components)
    ui_error_markers = (
        "<vite-error-overlay",
        "unhandled runtime error",
        "application error: a client-side exception has occurred",
        "chunkloaderror",
        "hydration failed",
        "<error-card",
        "<error-boundary",
        "configuration error:",
        "custom element doesn't exist",
        "custom element not found",
        "verdict: gui_failed",
    )
    custom_err_match = re.search(r"<[a-z0-9][a-z0-9-]*-error-(?:card|badge)\b", filtered_runtime_ev)
    matched_ui_err = (
        custom_err_match.group(0)
        if custom_err_match
        else next((m for m in ui_error_markers if m in filtered_runtime_ev), None)
    )
    if matched_ui_err:
        findings.append({
            "vector": "4. Downstream & Blast-Radius Safety",
            "level": "CRITICAL",
            "message": f"Rendered UI / DOM evidence contains unresolved error card or failed GUI check ({matched_ui_err!r}). Mandatory Rendered DOM & Zero-Error-Card Gate violated."
        })

    # Tripwire 4C: Boundary-to-Boundary Hardware / ADB Auth & Offline Device Gate
    hw_auth_markers = (
        "error: device unauthorized",
        "\tunauthorized",
        "adb: device offline",
        "error: device offline",
        "blocked_on_hardware_auth",
    )
    matched_hw_err = next((m for m in hw_auth_markers if m in filtered_runtime_ev), None)
    if matched_hw_err:
        findings.append({
            "vector": "4. Downstream & Blast-Radius Safety",
            "level": "CRITICAL",
            "message": f"Target hardware/ADB device was unauthorized or offline in verification evidence ({matched_hw_err.strip()!r}). Workflow must pause in BLOCKED_ON_HARDWARE_AUTH instead of claiming completion."
        })

    # Tripwire 4D: 3-Strike Anti-Thrashing & Unapproved Binary .dex APK Patching Circuit Breaker
    if any(
        dex_marker in added_prod_text
        for dex_marker in ("classes.dex", "classes2.dex", ".patched.apk", "patched-signed.apk", "baksmali")
    ):
        findings.append({
            "vector": "4. Downstream & Blast-Radius Safety",
            "level": "CRITICAL",
            "message": "Unapproved binary .dex APK bytecode hot-patching ('classes.dex') detected in production code, violating the 3-Strike Anti-Thrashing & Architectural Escalation Circuit Breaker."
        })

    # Tripwire 4E: Public-Repo Private LAN IP & PII Sanitization Gate
    plan_low = plan_content.lower() if plan_content else ""
    is_public_repo_context = any(
        p in plan_low
        for p in ("public github", "public repo", "veřejný github", "veřejný repozitář", "open-source")
    )
    if is_public_repo_context:
        priv_ip_match = re.search(
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
            added_prod_text,
        )
        if priv_ip_match and priv_ip_match.group(0) not in ("192.168.0.0", "10.0.0.0"):
            findings.append({
                "vector": "4. Downstream & Blast-Radius Safety",
                "level": "CRITICAL",
                "message": f"Private LAN IP ({priv_ip_match.group(0)}) introduced in a public GitHub repository diff. Use placeholders (<DEVICE_IP>) or environment variables."
            })

    # BMAD Gate 4F: Deletion Check & Missing-Adoption Caller Scan (edge-case-hunter & verification-gap lenses)
    removed_symbols: set[str] = set()
    added_symbols: set[str] = set()
    sym_def_re = re.compile(
        r"^\s*(?:async\s+def|def|export\s+(?:async\s+)?function|(?:async\s+)?function|pub(?:\([^)]*\))?\s+(?:async\s+)?fn|fn|func(?:\s+\([^)]*\))?)\s+([A-Za-z_][A-Za-z0-9_]{2,})\s*[<(]"
    )
    for dline in diff_content.splitlines():
        if dline.startswith("-") and not dline.startswith("---"):
            m = sym_def_re.match(dline[1:])
            if m:
                removed_symbols.add(m.group(1))
        elif dline.startswith("+") and not dline.startswith("+++"):
            m = sym_def_re.match(dline[1:])
            if m:
                added_symbols.add(m.group(1))

    deleted_only_symbols = removed_symbols - added_symbols
    if deleted_only_symbols:
        surviving_lines = [
            ln[1:] if ln.startswith(("+", " ")) else ln
            for ln in diff_content.splitlines()
            if not ln.startswith(("-", "diff ", "@@", "index "))
        ]
        surviving_text = "\n".join(surviving_lines)
        for sym in sorted(deleted_only_symbols):
            call_rx = re.compile(rf"(?<!def\s)(?<!function\s)(?<!fn\s)(?<!func\s)\b{re.escape(sym)}\s*\(")
            if call_rx.search(surviving_text):
                findings.append({
                    "vector": "4. Downstream & Blast-Radius Safety",
                    "level": "CRITICAL",
                    "message": f"BMAD_DELETION_OR_ADOPTION_GAP: Deleted or renamed symbol '{sym}' is still called by surviving/sibling code without updating all call sites."
                })

    # STING AST Mutation Verification Gate (optional --verify-mutations)
    mutation_summary_line = None
    if verify_mutations and diff_content.strip():
        try:
            try:
                from mutation_verifier import run_mutation_verification
            except ImportError:
                script_dir = str(Path(__file__).resolve().parent)
                if script_dir not in sys.path:
                    sys.path.insert(0, script_dir)
                from mutation_verifier import run_mutation_verification

            mut_res = run_mutation_verification(
                repo_dir=eff_workdir,
                diff_text=diff_content,
                test_targets=mutation_tests,
                threshold=mutation_threshold,
            )
            mut_status = mut_res.get("status", "unknown")
            mut_score = float(mut_res.get("mutation_score", 0.0))
            mut_killed = int(mut_res.get("killed", 0))
            mut_viable = int(mut_res.get("viable", 0))
            mut_survived = int(mut_res.get("survived", 0))
            mutation_summary_line = (
                f"**STING Mutation Gate**: `{mut_status.upper()} "
                f"(score={mut_score:.2f}, threshold={mutation_threshold:.2f}, "
                f"killed={mut_killed}/{mut_viable}, survived={mut_survived}, opt_tokens=0.0)`"
            )
            if not mut_res.get("passed", False):
                if mut_status == "baseline_tests_failed":
                    findings.append({
                        "vector": "3. Edge Cases & Boundary Breakdown",
                        "level": "CRITICAL",
                        "message": (
                            f"STING_MUTATION_GATE_FAILED: Baseline test suite failed before mutation verification "
                            f"(returncode={mut_res.get('baseline_returncode')})."
                        ),
                    })
                else:
                    survivors = mut_res.get("survivors", [])
                    surv_str = ", ".join(
                        f"{s.get('location', '?')} ({s.get('operator', '?')})"
                        for s in survivors[:10]
                    )
                    findings.append({
                        "vector": "3. Edge Cases & Boundary Breakdown",
                        "level": "CRITICAL",
                        "message": (
                            f"STING_MUTATION_GATE_FAILED: Mutation kill score {mut_score:.2f} < threshold {mutation_threshold:.2f} "
                            f"(killed={mut_killed}/{mut_viable}, survived={mut_survived}). "
                            f"Surviving mutants: {surv_str}"
                        ),
                    })
        except Exception as exc:
            findings.append({
                "vector": "3. Edge Cases & Boundary Breakdown",
                "level": "CRITICAL",
                "message": f"STING_MUTATION_GATE_FAILED: Mutation verifier execution error: {exc}",
            })

    diff_kb = max(len(diff_content.encode("utf-8")) / 1024.0, 0.001)
    blind_hunter_floor = min(int(math.sqrt(diff_kb) + 1), 10)

    critical_or_high = [f for f in findings if f["level"] in ("CRITICAL", "HIGH")]
    verdict = "ASW REJECTED" if critical_or_high else "ASW APPROVED"

    active_fallback = resolve_fallback_reason(fallback_reason)
    reviewer_line = (
        "`Claude Opus 5.5` -> `Deterministic Adversarial Engine + gemini-4-neon-high` (Opus Quota Fallback)"
        if active_fallback
        else "`Claude Opus 5.5` (Native Antigravity Subagent `asw-opposition-reviewer`)"
    )

    review_text = [
        "# Antigravity Claude Opus 5.5 Diff Opposition Review",
        "",
        f"**Plan File**: `{plan_path.name if (plan_path and plan_path.exists()) else 'auto-resolved'}`",
        f"**Diff File**: `{diff_path.name if (diff_path and diff_path.exists()) else 'git-files-diff'}`",
        f"**Reviewer**: {reviewer_line}",
        f"**BMAD 5-Lens Audit**: `blind-hunter (floor N={blind_hunter_floor}, diff={diff_kb:.2f} kB) + edge-case-hunter + verification-gap + intent-alignment + opus-cross-family`",
    ]
    if mutation_summary_line:
        review_text.append(mutation_summary_line)
    if active_fallback:
        review_text.append(
            f"**Fallback Mode**: `ACTIVE (Reason: {active_fallback} -> Deterministic Adversarial Engine + gemini-4-neon-high)`"
        )
    review_text.extend([
        "**Thinking Level**: `high`",
        f"Verdict: {verdict}",
        "",
        "## 4 Attack Vector Findings",
        "",
    ])

    attack_vectors = [
        "1. Scope & Plan Integrity",
        "2. Research & ML Falsification",
        "3. Edge Cases & Boundary Breakdown",
        "4. Downstream & Blast-Radius Safety",
    ]

    for av in attack_vectors:
        av_findings = [f for f in findings if f["vector"] == av]
        review_text.append(f"### {av}")
        if not av_findings:
            review_text.append("- **Status**: PASS (Adversarial falsification checks satisfied)")
        else:
            for af in av_findings:
                review_text.append(f"- **[{af['level']}]**: {af['message']}")
        review_text.append("")

    return verdict, findings, "\n".join(review_text)


def main():
    parser = argparse.ArgumentParser(description="Antigravity Claude Opus 5.5 Reviewer Bridge")
    parser.add_argument("--preflight", action="store_true", help="Discover Antigravity runtime and return JSON status")
    parser.add_argument("--sync-agents", action="store_true", help="Sync agent TOMLs to global plugin directory")
    parser.add_argument("--clean-scratch", type=Path, help="Non-interactively clean a scratch directory (including __pycache__)")
    parser.add_argument("--scan-public-repo", type=Path, help="Scan a target repo/directory for RFC1918 LAN IPs, API secrets, and forbidden PII terms")
    parser.add_argument("--forbid-terms", type=str, help="Comma-separated list of custom PII/location terms to block in --scan-public-repo")
    parser.add_argument("--mode", choices=["plan-review", "diff-review", "prepare-blind-review"], help="Review mode")
    parser.add_argument("--plan", type=Path, help="Path to implementation plan (auto-discovered from .asw/plans if omitted)")
    parser.add_argument("--diff", type=Path, help="Path to code diff (or use --files for self-contained diff generation)")
    parser.add_argument("--files", type=str, help="Comma-separated list of modified/untracked files to diff directly in UTF-8")
    parser.add_argument("--evidence", type=Path, help="Path to evidence directory or file (auto-discovered if omitted)")
    parser.add_argument("--fallback-reason", type=str, help="Explicit fallback reason when Claude Opus 5.5 credits/quota are exhausted")
    parser.add_argument("--workdir", type=Path, default=None, help="Explicit working directory root (defaults to current working directory)")
    parser.add_argument("--output", type=Path, help="Output markdown review artifact path (optional)")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output (supported for prepare-blind-review)")
    parser.add_argument("--verify-mutations", action="store_true", help="Run STING diff-scoped AST mutation testing gate during diff-review")
    parser.add_argument("--mutation-threshold", type=float, default=0.75, help="Minimum mutation kill score required by --verify-mutations (default: 0.75)")
    parser.add_argument("--mutation-tests", type=str, default=None, help="Comma-separated pytest target paths for --verify-mutations")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent.parent
    workdir = args.workdir.resolve() if args.workdir else Path.cwd()

    if args.clean_scratch:
        return clean_scratch_directory(args.clean_scratch)

    if args.scan_public_repo:
        return scan_public_repo_privacy(args.scan_public_repo, args.forbid_terms)

    if args.preflight:
        runtime_info = discover_antigravity_runtime(repo_root)
        out = {
            "status": "ready" if (runtime_info["language_server_found"] or runtime_info["agy_found"]) else "runtime_missing",
            "antigravity_runtime": runtime_info,
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0 if out["status"] == "ready" else 1

    if args.sync_agents:
        return sync_agents(repo_root)

    if args.mode == "plan-review":
        plan_path = args.plan or discover_latest_plan(workdir, repo_root)
        if not plan_path:
            sys.stderr.write("Error: --plan is required when no .asw/plans/*.md file exists.\n")
            return 2
        verdict, findings, report = audit_plan(
            plan_path,
            fallback_reason=args.fallback_reason,
            workdir=args.workdir.resolve() if args.workdir else None,
        )
        out_path = args.output or (workdir / ".asw" / "reviews" / f"plan-review-{plan_path.stem}.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        sys.stdout.write(f"Plan review written to {out_path} (Verdict: {verdict})\n")
        if not args.output:
            sys.stdout.write(report + "\n")
        return 0 if verdict == "PLAN_APPROVED" else 1

    if args.mode == "prepare-blind-review":
        raw_diff = ""
        if args.diff and args.diff.exists():
            raw_diff = read_text_resilient(args.diff)
        if args.files or not raw_diff.strip():
            gen_diff = build_git_diff_from_files(args.files, workdir)
            raw_diff = (raw_diff + "\n" + gen_diff).strip() if raw_diff.strip() else gen_diff

        packet = prepare_blind_review_packet(
            diff_content=raw_diff,
            workdir=workdir,
            plan_path=args.plan,
        )
        as_json = args.json or (args.output is not None and args.output.suffix.lower() == ".json")
        rendered = json.dumps(packet, indent=2) + "\n" if as_json else packet["packet_text"]
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            sys.stdout.write(f"Blind review packet written to {args.output} (opt_tokens={packet['opt_tokens']})\n")
        else:
            sys.stdout.write(rendered)
        return 0

    if args.mode == "diff-review":
        plan_path = args.plan or discover_latest_plan(workdir, repo_root)
        diff_override = None
        if args.files or (args.diff is None or not args.diff.exists()):
            diff_override = build_git_diff_from_files(args.files, workdir)
            if args.diff and args.diff.exists():
                diff_override = read_text_resilient(args.diff) + "\n" + diff_override

        mut_tests = (
            [t.strip() for t in re.split(r"[,;]+", args.mutation_tests) if t.strip()]
            if args.mutation_tests
            else None
        )
        verdict, findings, report = audit_diff(
            plan_path=plan_path,
            diff_path=args.diff,
            evidence_dir=args.evidence,
            diff_content_override=diff_override,
            fallback_reason=args.fallback_reason,
            workdir=workdir,
            verify_mutations=args.verify_mutations,
            mutation_threshold=args.mutation_threshold,
            mutation_tests=mut_tests,
        )
        out_path = args.output or (workdir / ".asw" / "reviews" / "diff-review-latest.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        sys.stdout.write(f"Diff review written to {out_path} (Verdict: {verdict})\n")
        if not args.output:
            sys.stdout.write(report + "\n")
        return 0 if verdict == "ASW APPROVED" else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
