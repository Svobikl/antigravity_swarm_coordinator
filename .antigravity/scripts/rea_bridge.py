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

"""CLI bridge for morluto/rea (`rea-agents`) reference-product reconnaissance.

Implements:
- Strict Node.js engine range admission (`satisfies_rea_node_range`)
- Isolated managed/local/system runtime discovery (`discover_rea_runtime`)
- Dual-Track target resolution (`resolve_reference_targets`)
- TOON-projected Markdown evidence generation (`project_rea_evidence_to_markdown`)
- End-to-end recon runner (`run_rea_recon`) and CLI (`--preflight`, `--resolve`, `--recon`)
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

REA_NODE_ENGINE_RANGE = "^22.23.4 || ^24.22.1 || >=26.12.1"

_SEMVER_EXACT_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_RANGE_CLAUSE_RE = re.compile(r"^\s*(>=|\^)?\s*(\d+)\.(\d+)\.(\d+)\s*$")
_VERSION_EXTRACT_RE = re.compile(r"\b\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?\b")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_JS_EXTENSIONS = frozenset({".js", ".mjs", ".cjs"})
_SQLITE_EXTENSIONS = frozenset({".db", ".sqlite", ".sqlite3"})
_SHIPPED_EXTENSIONS = frozenset({".exe", ".apk", ".ipa", ".vsix"})
_BULKY_RAW_KEYS = frozenset(
    {
        "raw_ast_excerpt",
        "source_code",
        "ast",
        "bytecode",
        "raw_source",
        "raw_content",
        "content",
    }
)
_MAX_SECTION_ITEMS = 60
_MAX_PROJECTED_TOKENS = 2500
_SHA256_PREFIX_RE = re.compile(r"^[0-9a-f]{64}:")
_SHA256_INLINE_RE = re.compile(r"[0-9a-f]{64}")

_GRAPH_ELECTRON_BOUNDARY_KINDS = frozenset(
    {
        "electron-main",
        "electron-preload",
        "browser-window",
        "context-bridge-api",
        "ipc-channel",
        "ipc-handler",
        "utility-process",
        "protocol-registration",
        "native-addon",
    }
)
_GRAPH_MODULE_KINDS = frozenset({"javascript-module", "package"})
_NOISY_NODE_PROP_KEYS = frozenset(
    {
        "limitations",
        "evidence",
        "source_map_reference",
        "container_sha256",
        "artifact_sha256",
        "channel_expression",
        "api_key_expression",
        "world_id",
        "ast_dump",
        "file_occurrence",
    }
)

_SECTION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("modules", ("modules", "files", "bundles", "entry_points", "assemblies", "types")),
    (
        "electron_boundaries",
        (
            "boundaries",
            "ipc",
            "ipc_channels",
            "ipchandlers",
            "contextbridge",
            "context_bridge",
            "preload",
            "preload_apis",
            "bridges",
            "channels",
        ),
    ),
    ("imports", ("imports", "dependencies", "packages", "references")),
    ("exports", ("exports", "endpoints", "routes", "commands", "methods")),
    ("tables", ("tables", "columns", "views", "indexes", "triggers")),
    ("rows", ("rows", "sample_rows")),
    ("checks", ("checks", "findings", "exposures", "vulnerabilities", "security_checks", "warnings")),
    ("limitations", ("limitations", "unknowns", "gaps", "caveats")),
)


def _load_toon_helpers() -> tuple[Callable[..., str], Callable[[str], int]]:
    """Dynamically load dumps_smart and estimate_tokens from sibling toon_codec.py."""
    sibling = Path(__file__).resolve().parent / "toon_codec.py"
    if sibling.exists():
        try:
            spec = importlib.util.spec_from_file_location("_toon_codec_for_rea", sibling)
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                dumps_fn = getattr(mod, "dumps_smart", None)
                tokens_fn = getattr(mod, "estimate_tokens", None)
                if callable(dumps_fn) and callable(tokens_fn):
                    return dumps_fn, tokens_fn
        except Exception:
            pass

    def _fallback_dumps_smart(data: Any, name: str = "items", min_rows: int = 3) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def _fallback_estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(len(text.split()), (len(text) + 3) // 4)

    return _fallback_dumps_smart, _fallback_estimate_tokens


dumps_smart, estimate_tokens = _load_toon_helpers()


def satisfies_rea_node_range(
    version_str: str,
    engine_range: str = REA_NODE_ENGINE_RANGE,
) -> bool:
    """Return True iff version_str is a strict X.Y.Z release matching engine_range."""
    if not isinstance(version_str, str):
        return False
    cleaned = version_str.strip()
    if cleaned.startswith(("v", "V")):
        cleaned = cleaned[1:].strip()

    match = _SEMVER_EXACT_RE.fullmatch(cleaned)
    if match is None:
        return False

    version_tuple = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    major, minor, patch = version_tuple

    for raw_clause in engine_range.split("||"):
        clause_match = _RANGE_CLAUSE_RE.fullmatch(raw_clause)
        if clause_match is None:
            continue
        op = clause_match.group(1)
        floor = (int(clause_match.group(2)), int(clause_match.group(3)), int(clause_match.group(4)))
        if op == "^":
            if major == floor[0] and (minor, patch) >= (floor[1], floor[2]):
                return True
        elif op == ">=":
            if version_tuple >= floor:
                return True
        else:
            if version_tuple == floor:
                return True
    return False


def _run_version_probe(cmd: list[str], timeout_sec: int = 10) -> str | None:
    """Execute a CLI version probe and return extracted version text on exit 0."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or proc.stderr or "").strip()
    if not raw:
        return None
    first_line = raw.splitlines()[0].strip()
    ver_match = _VERSION_EXTRACT_RE.search(first_line)
    if ver_match:
        return ver_match.group(0)
    return first_line


def _probe_host_node() -> tuple[str | None, bool]:
    """Check system `node -v` and evaluate REA engine compatibility."""
    node_bin = shutil.which("node")
    if not node_bin:
        return None, False
    try:
        proc = subprocess.run(
            [node_bin, "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, False
    if proc.returncode != 0:
        return None, False
    node_ver = (proc.stdout or "").strip().splitlines()[0].strip() if proc.stdout else ""
    if not node_ver:
        return None, False
    return node_ver, satisfies_rea_node_range(node_ver)


def discover_rea_runtime(home_dir: Path | None = None) -> dict[str, Any]:
    """Discover an executable REA CLI runtime in managed, local, or compatible system paths."""
    system_home = Path.home().resolve()
    active_home = home_dir.resolve() if home_dir is not None else system_home
    is_isolated = home_dir is not None and active_home != system_home
    is_win = os.name == "nt"

    host_node_version, host_node_compatible = _probe_host_node()

    # 1. Managed isolated runtime under active_home / ".gemini" / "rea-runtime"
    runtime_root = active_home / ".gemini" / "rea-runtime"
    managed_launcher = runtime_root / "bin" / ("rea.cmd" if is_win else "rea")
    managed_candidates: list[list[str]] = []
    if managed_launcher.is_file():
        managed_candidates.append([str(managed_launcher)])

    node_exe = runtime_root / ("node/node.exe" if is_win else "node/bin/node")
    rea_mjs = runtime_root / "pkg" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
    if node_exe.is_file() and rea_mjs.is_file():
        managed_candidates.append([str(node_exe), str(rea_mjs)])

    for cmd in managed_candidates:
        rea_ver = _run_version_probe([*cmd, "--version"], timeout_sec=10)
        if rea_ver is not None:
            return {
                "available": True,
                "command": cmd,
                "rea_version": rea_ver,
                "host_node_version": host_node_version,
                "host_node_compatible": host_node_compatible,
                "source": "managed_runtime",
            }

    # 2. User local wrapper within active_home
    local_wrapper = active_home / ".local" / "bin" / ("rea.cmd" if is_win else "rea")
    if local_wrapper.is_file():
        rea_ver = _run_version_probe([str(local_wrapper), "--version"], timeout_sec=10)
        if rea_ver is not None:
            return {
                "available": True,
                "command": [str(local_wrapper)],
                "rea_version": rea_ver,
                "host_node_version": host_node_version,
                "host_node_compatible": host_node_compatible,
                "source": "local_bin",
            }

    # 3 & 4. System PATH binaries and node+npx only when not isolated
    if not is_isolated:
        for bin_name in ("rea", "rea-agents"):
            found = shutil.which(bin_name)
            if found:
                rea_ver = _run_version_probe([found, "--version"], timeout_sec=10)
                if rea_ver is not None:
                    return {
                        "available": True,
                        "command": [found],
                        "rea_version": rea_ver,
                        "host_node_version": host_node_version,
                        "host_node_compatible": host_node_compatible,
                        "source": "system_path",
                    }

        if host_node_compatible:
            npx_bin = shutil.which("npx")
            if npx_bin:
                cmd = [npx_bin, "--no-install", "rea-agents"]
                rea_ver = _run_version_probe([*cmd, "--version"], timeout_sec=10)
                if rea_ver is not None:
                    return {
                        "available": True,
                        "command": cmd,
                        "rea_version": rea_ver,
                        "host_node_version": host_node_version,
                        "host_node_compatible": host_node_compatible,
                        "source": "system_npx",
                    }

    return {
        "available": False,
        "command": None,
        "rea_version": None,
        "host_node_version": host_node_version,
        "host_node_compatible": host_node_compatible,
        "source": "unavailable",
    }


def _default_app_search_dirs() -> list[Path]:
    if sys.platform == "darwin":
        return [Path("/Applications"), Path.home() / "Applications"]
    if os.name == "nt":
        dirs: list[Path] = []
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        prog_files = os.environ.get("ProgramFiles", "").strip()
        if local_app:
            dirs.append(Path(local_app) / "Programs")
        if prog_files:
            dirs.append(Path(prog_files))
        return dirs
    return [Path("/opt"), Path("/usr/share")]


def _dir_contains_js_app(directory: Path) -> bool:
    if (directory / "package.json").is_file():
        return True
    try:
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in _JS_EXTENSIONS:
                return True
            if entry.is_dir() and entry.name != "node_modules":
                for sub in entry.iterdir():
                    if sub.is_file() and sub.suffix.lower() in _JS_EXTENSIONS:
                        return True
    except OSError:
        return False
    return False


def _classify_existing_artifact(path: Path) -> tuple[Path, str, str]:
    suffix = path.suffix.lower()
    if path.is_dir():
        if suffix == ".app":
            asar = path / "Contents" / "Resources" / "app.asar"
            if asar.is_file():
                return asar, "javascript_app", "analyze-javascript-application"
            return path, "shipped_bundle", "audit-release-exposure"
        win_asar = path / "resources" / "app.asar"
        if win_asar.is_file():
            return win_asar, "javascript_app", "analyze-javascript-application"
        if _dir_contains_js_app(path):
            return path, "javascript_app", "analyze-javascript-application"
        return path, "shipped_bundle", "audit-release-exposure"

    if suffix == ".asar" or suffix in _JS_EXTENSIONS:
        return path, "javascript_app", "analyze-javascript-application"
    if suffix in _SQLITE_EXTENSIONS:
        return path, "sqlite_db", "inspect-sqlite-database"
    if suffix == ".dll":
        return path, "managed_assembly", "inspect-managed-artifact"
    if suffix in _SHIPPED_EXTENSIONS:
        return path, "shipped_bundle", "audit-release-exposure"
    return path, "shipped_bundle", "audit-release-exposure"


def resolve_reference_targets(
    target_hint: str,
    *,
    workdir: Path | None = None,
    app_search_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """Resolve a target hint to a local artifact, web URL, or remote SaaS fallback."""
    cleaned = (target_hint or "").strip().strip('"').strip("'")
    if cleaned.lower().startswith(("http://", "https://")):
        return {
            "track": "web_url",
            "target": cleaned,
            "artifact_path": None,
            "artifact_kind": "url",
            "rea_subcommand": None,
            "checked_paths": [],
        }

    checked: list[Path] = []
    if cleaned:
        base_dir = workdir.resolve() if workdir is not None else Path.cwd().resolve()
        raw_path = Path(cleaned).expanduser()
        explicit_cand = raw_path if raw_path.is_absolute() else (base_dir / raw_path)
        checked.append(explicit_cand)
        if explicit_cand.exists():
            artifact_path, artifact_kind, subcommand = _classify_existing_artifact(explicit_cand)
            return {
                "track": "local_artifact",
                "target": cleaned,
                "artifact_path": str(artifact_path),
                "artifact_kind": artifact_kind,
                "rea_subcommand": subcommand,
                "checked_paths": [str(p) for p in checked],
            }

        app_stem = cleaned[:-4] if cleaned.lower().endswith(".app") else cleaned
        search_dirs = app_search_dirs if app_search_dirs is not None else _default_app_search_dirs()
        for sdir in search_dirs:
            bundle = sdir / f"{app_stem}.app"
            bundle_asar = bundle / "Contents" / "Resources" / "app.asar"
            win_asar_exact = sdir / app_stem / "resources" / "app.asar"
            win_asar_lower = sdir / app_stem.lower() / "resources" / "app.asar"

            for cand in (bundle_asar, bundle, win_asar_exact, win_asar_lower):
                if cand not in checked:
                    checked.append(cand)

            if bundle_asar.is_file():
                return {
                    "track": "local_artifact",
                    "target": cleaned,
                    "artifact_path": str(bundle_asar),
                    "artifact_kind": "javascript_app",
                    "rea_subcommand": "analyze-javascript-application",
                    "checked_paths": [str(p) for p in checked],
                }
            if bundle.exists():
                return {
                    "track": "local_artifact",
                    "target": cleaned,
                    "artifact_path": str(bundle),
                    "artifact_kind": "shipped_bundle",
                    "rea_subcommand": "audit-release-exposure",
                    "checked_paths": [str(p) for p in checked],
                }
            for asar_cand in (win_asar_exact, win_asar_lower):
                if asar_cand.is_file():
                    return {
                        "track": "local_artifact",
                        "target": cleaned,
                        "artifact_path": str(asar_cand),
                        "artifact_kind": "javascript_app",
                        "rea_subcommand": "analyze-javascript-application",
                        "checked_paths": [str(p) for p in checked],
                    }

    return {
        "track": "remote_saas_fallback",
        "target": cleaned,
        "artifact_path": None,
        "artifact_kind": "remote_saas",
        "rea_subcommand": None,
        "checked_paths": [str(p) for p in checked],
    }


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", (text or "target").strip().lower()).strip("-")
    return slug or "target"


def _target_slug(target: str) -> str:
    cleaned = (target or "target").strip()
    has_sep = "/" in cleaned or "\\" in cleaned
    base = Path(cleaned).name if has_sep else cleaned
    stem = _slugify(base or cleaned)
    if has_sep:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
        return f"{stem}-{digest}"
    return stem


def _sanitize_home_path(text: str) -> str:
    if not text:
        return text
    out = text
    candidates: list[str] = []
    for hp in (str(Path.home()), str(Path.home().resolve())):
        if hp and hp not in candidates:
            candidates.append(hp)
    for hp in sorted(candidates, key=len, reverse=True):
        out = re.sub(
            re.escape(hp) + r'(?=$|[\\/\s"\'`,\]\})])',
            "~",
            out,
        )
    return out


def _compact_scalar(value: Any, max_len: int = 120) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = _sanitize_home_path(" ".join(value.split()))
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text
    if isinstance(value, (list, dict)):
        dumped = _sanitize_home_path(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        if len(dumped) > max_len:
            return dumped[: max_len - 3] + "..."
        return dumped
    return _sanitize_home_path(str(value))


def _normalize_dict_rows(items: list[Any], limit: int) -> list[dict[str, Any]]:
    capped = items[:limit]
    dict_rows = [row for row in capped if isinstance(row, dict)]
    if not dict_rows:
        return []

    ordered_keys: list[str] = []
    seen_keys: set[str] = set()
    for row in dict_rows:
        for k in row.keys():
            ks = str(k)
            k_lower = ks.lower()
            val = row[k]
            if k_lower in _BULKY_RAW_KEYS and (isinstance(val, (dict, list)) or len(str(val)) > 120):
                continue
            if ks not in seen_keys:
                seen_keys.add(ks)
                ordered_keys.append(ks)

    if not ordered_keys:
        return []

    normalized: list[dict[str, Any]] = []
    for row in dict_rows:
        norm_row: dict[str, Any] = {}
        for k in ordered_keys:
            norm_row[k] = _compact_scalar(row.get(k))
        normalized.append(norm_row)
    return normalized


def _compact_node_properties(props: Any) -> str:
    if isinstance(props, dict):
        cleaned: dict[str, Any] = {}
        for k, v in props.items():
            ks = str(k)
            if v is None or ks.lower() in _NOISY_NODE_PROP_KEYS or ks.lower() in _BULKY_RAW_KEYS:
                continue
            cleaned[ks] = v
        return str(_compact_scalar(cleaned, max_len=140))
    return str(_compact_scalar(props, max_len=140))


def _shorten_node_key(raw_key: Any) -> str:
    if raw_key is None:
        return ""
    text = _SHA256_PREFIX_RE.sub("", str(raw_key))
    text = _SHA256_INLINE_RE.sub(lambda m: m.group(0)[:8], text)
    return str(_compact_scalar(text, max_len=80))


def _dedup_preserving_order(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in items:
        sig = (
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            if isinstance(item, (dict, list))
            else str(item)
        )
        if sig not in seen:
            seen.add(sig)
            unique.append(item)
    return unique


def _extract_graph_and_routes(
    mapping: dict[str, Any],
    collected: dict[str, list[Any]],
    seen_modules: set[tuple[str, str]],
) -> None:
    graph = mapping.get("graph")
    if isinstance(graph, dict) and isinstance(graph.get("nodes"), list):
        for node in graph["nodes"]:
            if not isinstance(node, dict):
                continue
            kind = str(node.get("kind") or "")
            identity = node.get("identity") if isinstance(node.get("identity"), dict) else {}
            observations = node.get("observations") if isinstance(node.get("observations"), list) else []
            obs = observations[0] if observations and isinstance(observations[0], dict) else {}
            obs_label = str(obs.get("label") or identity.get("key") or node.get("node_id") or "")

            if kind in _GRAPH_ELECTRON_BOUNDARY_KINDS:
                collected.setdefault("electron_boundaries", []).append(
                    {
                        "kind": kind,
                        "label": obs_label,
                        "namespace": identity.get("namespace") or identity.get("scope"),
                        "properties": _compact_node_properties(obs.get("properties")),
                    }
                )
            elif kind in _GRAPH_MODULE_KINDS:
                mod_id = (kind, obs_label)
                if mod_id not in seen_modules:
                    seen_modules.add(mod_id)
                    collected.setdefault("modules", []).append(
                        {
                            "kind": kind,
                            "label": obs_label,
                            "key": _shorten_node_key(identity.get("key")),
                        }
                    )

    route_inv = mapping.get("route_inventory")
    if isinstance(route_inv, dict) and isinstance(route_inv.get("sources"), list):
        for src in route_inv["sources"]:
            if not isinstance(src, dict):
                continue
            src_label = str(src.get("path") or src.get("key") or "")
            mod_id = ("javascript-module", src_label)
            if src_label and mod_id not in seen_modules:
                seen_modules.add(mod_id)
                collected.setdefault("modules", []).append(
                    {
                        "kind": "javascript-module",
                        "label": src_label,
                        "key": _shorten_node_key(src.get("key") or src.get("path")),
                    }
                )


def _collect_section_items(
    raw_payload: Any,
) -> tuple[dict[str, list[Any]], dict[str, Any], dict[str, Any]]:
    """Collect structural sections, scalar metadata, and summary from REA JSON payloads."""
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in _SECTION_ALIASES:
        for alias in aliases:
            alias_to_canonical[alias.lower()] = canonical

    collected: dict[str, list[Any]] = {}
    scalars: dict[str, Any] = {}
    summary_dict: dict[str, Any] = {}

    if not isinstance(raw_payload, dict):
        if isinstance(raw_payload, list):
            collected["modules"] = raw_payload
        return collected, scalars, summary_dict

    containers: list[dict[str, Any]] = [raw_payload]
    for nested_key in ("normalized_result", "result", "evidence", "summary", "analysis"):
        nested = raw_payload.get(nested_key)
        if isinstance(nested, dict):
            containers.append(nested)

    expanded: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for container in containers:
        if id(container) not in seen_ids:
            seen_ids.add(id(container))
            expanded.append(container)
        for sub_key in ("electron", "ipc", "preload", "database", "schema", "release", "exposure", "graph"):
            sub_val = container.get(sub_key)
            if isinstance(sub_val, dict) and id(sub_val) not in seen_ids:
                seen_ids.add(id(sub_val))
                expanded.append(sub_val)

    seen_modules: set[tuple[str, str]] = set()
    for mapping in expanded:
        _extract_graph_and_routes(mapping, collected, seen_modules)
        if not summary_dict and isinstance(mapping.get("summary"), dict) and mapping["summary"]:
            summary_dict = mapping["summary"]
        for key, val in mapping.items():
            key_lower = str(key).lower()
            canonical = alias_to_canonical.get(key_lower)
            if canonical and isinstance(val, list) and val:
                bucket = collected.setdefault(canonical, [])
                bucket.extend(val)
            elif canonical and isinstance(val, dict) and val:
                dict_entries: list[dict[str, Any]] = []
                for entry_name, entry_val in val.items():
                    if isinstance(entry_val, dict):
                        dict_entries.append({"name": entry_name, **entry_val})
                    elif not isinstance(entry_val, list):
                        scalars[f"{key}.{entry_name}"] = entry_val
                if dict_entries:
                    collected.setdefault(canonical, []).extend(dict_entries)
            elif isinstance(val, (str, int, float, bool)) and key_lower not in _BULKY_RAW_KEYS:
                if key in ("context_isolation", "node_integration", "sandbox", "schema_version", "command"):
                    scalars[str(key)] = val

    if "limitations" in collected:
        collected["limitations"] = _dedup_preserving_order(collected["limitations"])

    return collected, scalars, summary_dict


def _render_projected_markdown(
    target: str,
    artifact_path: str,
    artifact_kind: str,
    sections: dict[str, list[Any]],
    scalars: dict[str, Any],
    summary_dict: dict[str, Any],
    raw_json_path: Path | None,
    row_limit: int,
) -> str:
    lines: list[str] = [
        f"# Reference Product Recon: {_sanitize_home_path(target)}",
        "",
        f"- **Artifact**: `{_sanitize_home_path(artifact_path)}` (`{artifact_kind}`)",
    ]
    if raw_json_path is not None:
        lines.append(f"- **Raw Evidence**: `{_sanitize_home_path(str(raw_json_path))}`")
    if scalars:
        scalar_summary = ", ".join(f"`{k}={v}`" for k, v in list(scalars.items())[:8])
        lines.append(f"- **Runtime Flags**: {scalar_summary}")
    lines.append("")

    if summary_dict:
        lines.append("## Summary")
        lines.append("")
        for k, v in summary_dict.items():
            if isinstance(v, (dict, list)):
                lines.append(f"- `{k}`: `{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}`")
            else:
                lines.append(f"- `{k}`: `{v}`")
        lines.append("")

    ordered_names = [name for name in sections if name != "limitations"]
    if "limitations" in sections:
        ordered_names.append("limitations")

    for section_name in ordered_names:
        items = sections[section_name]
        total_count = len(items)
        shown_count = min(total_count, row_limit)
        title = section_name.replace("_", " ").title()
        if total_count > row_limit:
            lines.append(f"## {title} ({shown_count}/{total_count} shown)")
        else:
            lines.append(f"## {title} ({total_count})")
        lines.append("")

        norm_rows = _normalize_dict_rows(items, limit=row_limit)
        if norm_rows:
            encoded = dumps_smart(norm_rows, name=section_name, min_rows=3)
            lines.append("```toon")
            lines.append(encoded)
            lines.append("```")
        else:
            for entry in items[:row_limit]:
                lines.append(f"- {_compact_scalar(entry, max_len=160)}")
        lines.append("")

    lines.extend(
        [
            "## Clean-Room Reference Product Parity Checklist",
            "",
            "### Reference Product Parity",
            "",
            "- [ ] Verify core architecture, process boundaries, and IPC contracts cleanly.",
            "- [ ] Implement original clean-room UX and state workflows without proprietary assets.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def project_rea_evidence_to_markdown(
    target: str,
    artifact_path: str,
    artifact_kind: str,
    raw_payload: Any,
    raw_json_path: Path | None = None,
) -> dict[str, Any]:
    """Project REA JSON evidence into token-frugal TOON Markdown (<= 2,500 tokens)."""
    raw_json_str = json.dumps(raw_payload, ensure_ascii=False, indent=2)
    raw_bytes = len(raw_json_str.encode("utf-8"))
    raw_tokens = estimate_tokens(raw_json_str)

    sections, scalars, summary_dict = _collect_section_items(raw_payload)

    markdown = ""
    projected_tokens = 0
    for limit in (_MAX_SECTION_ITEMS, 35, 20, 10):
        markdown = _render_projected_markdown(
            target=target,
            artifact_path=artifact_path,
            artifact_kind=artifact_kind,
            sections=sections,
            scalars=scalars,
            summary_dict=summary_dict,
            raw_json_path=raw_json_path,
            row_limit=limit,
        )
        projected_tokens = estimate_tokens(markdown)
        if projected_tokens <= _MAX_PROJECTED_TOKENS:
            break

    saved_pct = (
        round((raw_tokens - projected_tokens) * 100.0 / raw_tokens, 2) if raw_tokens > 0 else 0.0
    )
    return {
        "markdown": markdown,
        "raw_bytes": raw_bytes,
        "raw_tokens": raw_tokens,
        "projected_tokens": projected_tokens,
        "saved_pct": saved_pct,
    }


def _build_fallback_scaffold_markdown(
    target: str,
    resolution: dict[str, Any],
    runtime: dict[str, Any] | None,
) -> str:
    checked = [_sanitize_home_path(p) for p in resolution.get("checked_paths", [])]
    safe_target = _sanitize_home_path(target)
    reason = (
        "No local artifact matched target on this host."
        if resolution.get("track") != "local_artifact"
        else "Local artifact found, but REA CLI runtime is unavailable."
    )
    lines = [
        f"# Reference Product Recon: {safe_target}",
        "",
        "- **Status**: `FALLBACK_REQUIRED` (Dual-Track Clean-Room Recon)",
        f"- **Track**: `{resolution.get('track')}`",
        f"- **Reason**: {reason}",
        "- **Delegate To**: `asw-librarian`, `browser`",
    ]
    if runtime is not None:
        lines.append(
            f"- **Host Node**: `{runtime.get('host_node_version')}` "
            f"(compatible={runtime.get('host_node_compatible')}, rea_source={runtime.get('source')})"
        )
    if checked:
        lines.append("")
        lines.append("## Checked Local Paths")
        lines.append("")
        for p in checked:
            lines.append(f"- `{p}`")

    lines.extend(
        [
            "",
            "## Clean-Room Reference Product Parity Checklist",
            "",
            "### Reference Product Parity",
            "",
            f"- [ ] Research `{target}` public documentation, workflows, and UX patterns via `asw-librarian` / `browser`.",
            "- [ ] Extract clean-room interaction flows, keyboard shortcuts, and visual tokens without copying proprietary assets.",
            "- [ ] Record observed parity criteria before implementation.",
            "",
        ]
    )
    return "\n".join(lines)


def run_rea_recon(
    target: str,
    *,
    output_path: Path | None = None,
    raw_output_path: Path | None = None,
    home_dir: Path | None = None,
    workdir: Path | None = None,
    app_search_dirs: list[Path] | None = None,
    runner_override: list[str] | None = None,
    timeout_sec: int = 90,
) -> dict[str, Any]:
    """Execute Dual-Track reference-product recon via REA CLI or SaaS fallback scaffold."""
    base_workdir = workdir.resolve() if workdir is not None else Path.cwd().resolve()
    resolution = resolve_reference_targets(
        target,
        workdir=base_workdir,
        app_search_dirs=app_search_dirs,
    )

    runtime: dict[str, Any] | None = None
    rea_cmd: list[str] | None = list(runner_override) if runner_override is not None else None
    if resolution["track"] == "local_artifact" and rea_cmd is None:
        runtime = discover_rea_runtime(home_dir=home_dir)
        if runtime["available"]:
            rea_cmd = runtime["command"]

    if resolution["track"] != "local_artifact" or not rea_cmd:
        scaffold_md = _build_fallback_scaffold_markdown(target, resolution, runtime)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(scaffold_md, encoding="utf-8", newline="\n")
        return {
            "status": "FALLBACK_REQUIRED",
            "track": resolution["track"],
            "target": target,
            "checked_paths": resolution["checked_paths"],
            "delegate_to": ["asw-librarian", "browser"],
            "output_path": str(output_path) if output_path is not None else None,
            "markdown": scaffold_md,
            "opt_tokens": 0.0,
        }

    slug = _target_slug(target)
    raw_path = raw_output_path or (base_workdir / ".asw" / "evidence" / f"rea-raw-{slug}.json")
    out_path = output_path or (base_workdir / ".asw" / "evidence" / f"reference-{slug}.md")

    cmd = [*rea_cmd, str(resolution["rea_subcommand"]), str(resolution["artifact_path"]), "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "ERROR",
            "track": "local_artifact",
            "target": target,
            "artifact_path": str(resolution["artifact_path"]),
            "artifact_kind": resolution["artifact_kind"],
            "error": f"Failed to execute REA CLI: {exc}",
            "opt_tokens": 0.0,
        }

    if proc.returncode != 0:
        return {
            "status": "ERROR",
            "track": "local_artifact",
            "target": target,
            "artifact_path": str(resolution["artifact_path"]),
            "artifact_kind": resolution["artifact_kind"],
            "error": (proc.stderr or proc.stdout or f"REA exited with code {proc.returncode}").strip(),
            "opt_tokens": 0.0,
        }

    try:
        raw_payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "ERROR",
            "track": "local_artifact",
            "target": target,
            "artifact_path": str(resolution["artifact_path"]),
            "artifact_kind": resolution["artifact_kind"],
            "error": f"Invalid JSON output from REA CLI: {exc}",
            "opt_tokens": 0.0,
        }

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    projected = project_rea_evidence_to_markdown(
        target=target,
        artifact_path=str(resolution["artifact_path"]),
        artifact_kind=str(resolution["artifact_kind"]),
        raw_payload=raw_payload,
        raw_json_path=raw_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(projected["markdown"], encoding="utf-8", newline="\n")

    return {
        "status": "RECON_COMPLETED",
        "track": "local_artifact",
        "target": target,
        "artifact_path": str(resolution["artifact_path"]),
        "artifact_kind": resolution["artifact_kind"],
        "raw_evidence_path": str(raw_path),
        "output_path": str(out_path),
        "raw_tokens": projected["raw_tokens"],
        "projected_tokens": projected["projected_tokens"],
        "saved_tokens_pct": projected["saved_pct"],
        "opt_tokens": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="CLI bridge for morluto/rea reference-product reconnaissance."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Inspect REA runtime and Node compatibility.")
    group.add_argument("--resolve", metavar="TARGET", help="Resolve a reference target to a recon track.")
    group.add_argument("--recon", metavar="TARGET", help="Run Dual-Track reference-product recon.")
    parser.add_argument("--output", type=Path, help="Output Markdown path for --recon.")
    parser.add_argument("--workdir", type=Path, help="Working directory for target resolution.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    if args.preflight:
        result = discover_rea_runtime()
        if args.json:
            sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"REA available={result['available']} source={result['source']} "
                f"rea_version={result['rea_version']} host_node={result['host_node_version']} "
                f"compatible={result['host_node_compatible']}\n"
            )
        return 0

    if args.resolve is not None:
        result = resolve_reference_targets(args.resolve, workdir=args.workdir)
        if args.json:
            sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"track={result['track']} kind={result['artifact_kind']} "
                f"artifact={result['artifact_path']}\n"
            )
        return 0

    base_workdir = args.workdir.resolve() if args.workdir is not None else Path.cwd().resolve()
    out_path = args.output or (base_workdir / ".asw" / "evidence" / f"reference-{_target_slug(args.recon)}.md")
    result = run_rea_recon(args.recon, output_path=out_path, workdir=base_workdir)
    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"status={result['status']} track={result['track']} output={result.get('output_path')}\n"
        )
    return 1 if result["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
