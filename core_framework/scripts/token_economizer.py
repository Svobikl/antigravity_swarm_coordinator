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

"""Zero-API-overhead TokenEconomizer engine for Antigravity Swarm Coordinator.

Implements:
- Feature-flag isolation (ASW_TOKEN_ECONOMIZER_ENABLED / decision_config.json)
- Incremental Antigravity JSONL transcript reader (antigravity_read)
- Cache-aware effective token accounting (effective_tokens, antigravity_session_usage)
- Zero-LLM 6-family EnvFactsDistiller + Lifecycle + Forgetting (AD-1 envfacts.json)
- Live per-turn SpiralState + linear-interpolated p90 EnvelopeTracker + TurnGuard
- Deterministic 6-session A/B benchmark (--benchmark)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Constants & Feature Flag Isolation
# ---------------------------------------------------------------------------

DISABLED_RESULT: dict[str, Any] = {"enabled": False, "status": "disabled"}

K_PROMOTE = 3
GAMMA = 0.8
LAMBDA = 5.0
SCORE_FLOOR = 0.0
FIRE_GATE = 0.40
FIRE_MIN_N = 4
CONTRADICT_STREAK = 2

MAX_FACTS = 4
MAX_TOKENS = 150
MAX_RENDERED_CHARS = 600
MAX_NUDGE_TOKENS = 95

ENVFACTS_HEADER = "# environment facts learned from earlier sessions in this repository"

_LINT_RE = re.compile(
    r"\b(?:"
    r"skip(?:ping|ped|s)?|"
    r"no\s+need|"
    r"don'?t|"
    r"do\s+not|"
    r"stop(?:ping|ped|s)?|"
    r"done|"
    r"complete(?:d|ly|s)?|"
    r"finish(?:ed|es|ing)?|"
    r"verif(?:y|ied|ies|ying|ication)|"
    r"instead\s+of\s+(?:running|testing)"
    r")\b",
    re.IGNORECASE,
)

MODEL_WEIGHTS: dict[str, dict[str, float]] = {
    "gemini-4-carbon": {"input": 1.0, "cache_read": 0.05, "cache_write": 0.0, "output": 5.0},
    "gemini-4-neon": {"input": 1.0, "cache_read": 0.05, "cache_write": 0.0, "output": 5.0},
    "gemini-4-hydrogen": {"input": 1.0, "cache_read": 0.05, "cache_write": 0.0, "output": 5.0},
    "claude-opus-5-5": {"input": 1.0, "cache_read": 0.05, "cache_write": 1.25, "output": 5.0},
    "gemini-3.8-flash": {"input": 1.0, "cache_read": 0.10, "cache_write": 0.0, "output": 5.0},
}

_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-5.5": "claude-opus-5-5",
    "opus-5-5": "claude-opus-5-5",
    "gemini-4-carbon-high": "gemini-4-carbon",
    "gemini-4-neon-high": "gemini-4-neon",
    "gemini-4-hydrogen-high": "gemini-4-hydrogen",
}

_TOOL_NAME_MAP: dict[str, str] = {
    "run_command": "Bash",
    "bash": "Bash",
    "read_file": "Read",
    "view_file": "Read",
    "write_file": "Write",
    "write_to_file": "Write",
    "edit_file": "Edit",
    "replace_file_content": "Edit",
    "multi_replace_file_content": "Edit",
    "grep_search": "Grep",
    "find_by_name": "Glob",
    "list_dir": "Glob",
}

_FALSEY_STRS = {"0", "false", "no", "off"}
_TRUTHY_STRS = {"1", "true", "yes", "on"}

_RETRY_BACKOFF_DELAYS = (0.01, 0.02, 0.05, 0.1, 0.2)


def _disabled_copy() -> dict[str, Any]:
    return dict(DISABLED_RESULT)


def is_enabled(repo: str | Path | None = None) -> bool:
    """Return False when disabled via ASW_TOKEN_ECONOMIZER_ENABLED or decision_config.json."""
    env_val = os.environ.get("ASW_TOKEN_ECONOMIZER_ENABLED")
    if env_val is not None:
        norm = env_val.strip().lower()
        if norm in _FALSEY_STRS:
            return False
        if norm in _TRUTHY_STRS:
            return True

    candidates: list[Path] = []
    if repo is not None:
        candidates.append(Path(repo).resolve() / ".antigravity" / "decision_config.json")
    candidates.extend(
        [
            Path.cwd() / ".antigravity" / "decision_config.json",
            Path(__file__).resolve().parent.parent / "decision_config.json",
            Path.home() / ".gemini" / "decision_config.json",
            Path.home() / ".gemini" / ".antigravity" / "decision_config.json",
        ]
    )
    seen: set[Path] = set()
    for cfg_path in candidates:
        if cfg_path in seen:
            continue
        seen.add(cfg_path)
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and "token_economizer_enabled" in data:
                val = data["token_economizer_enabled"]
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    low = val.strip().lower()
                    if low in _FALSEY_STRS:
                        return False
                    if low in _TRUTHY_STRS:
                        return True
    return True


def estimate_tokens(text: str) -> int:
    """Conservative deterministic token count estimator (zero external deps)."""
    if not text:
        return 0
    return max(len(text.split()), (len(text) + 3) // 4)


def is_claim_safe(claim: str) -> bool:
    """Reject any claim or nudge containing verification-skipping or stop phrases."""
    if not claim or not isinstance(claim, str):
        return False
    return _LINT_RE.search(claim) is None


# ---------------------------------------------------------------------------
# Path & Atomic Persistence Utilities (AD-1)
# ---------------------------------------------------------------------------


def repo_slug(repo: str | Path) -> str:
    """Compute filesystem-safe slug from resolved repository directory name."""
    name = Path(repo).resolve().name or "root"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def default_state_root(repo: str | Path) -> Path:
    """Return default AD-1 state root inside repository."""
    return Path(repo).resolve() / ".antigravity" / "token_economizer_state"


def resolve_envfacts_path(
    repo: str | Path | None = None,
    state_root: str | Path | None = None,
) -> Path:
    """Resolve <state_root>/<repo_slug>/envfacts.json."""
    repo_path = Path(repo).resolve() if repo is not None else Path.cwd().resolve()
    root = Path(state_root).resolve() if state_root is not None else default_state_root(repo_path)
    return root / repo_slug(repo_path) / "envfacts.json"


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write JSON atomically using same-dir temp file + Windows PermissionError backoff."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        for idx in range(len(_RETRY_BACKOFF_DELAYS) + 1):
            try:
                os.replace(tmp_path, target)
                break
            except PermissionError:
                if idx >= len(_RETRY_BACKOFF_DELAYS):
                    raise
                time.sleep(_RETRY_BACKOFF_DELAYS[idx])
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
    return target


# ---------------------------------------------------------------------------
# Antigravity Transcript Reader & Cache-Aware Effective Cost
# ---------------------------------------------------------------------------

_USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
_TIMESTAMP_LINE_RE = re.compile(r"(?m)^(?:Created At|Completed At):\s*[^\r\n]*(?:\r?\n|$)")
_EXIT_CODE_RE = re.compile(r"Command exited with code\s+(-?\d+)")


def _strip_user_request(text: str) -> str:
    m = _USER_REQ_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _clean_tool_output(text: str) -> tuple[str, int | None]:
    cleaned = _TIMESTAMP_LINE_RE.sub("", text).strip()
    m = _EXIT_CODE_RE.search(cleaned)
    exit_code = int(m.group(1)) if m else None
    return cleaned, exit_code


def _extract_text_field(row: dict[str, Any]) -> str:
    for key in ("text", "content", "output", "result", "message", "prompt"):
        val = row.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            parts = []
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
    for nested_key in ("userInput", "plannerResponse", "modelResponse", "generic"):
        nested = row.get(nested_key)
        if isinstance(nested, dict):
            txt = _extract_text_field(nested)
            if txt:
                return txt
    return ""


def _parse_tool_args(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {"raw": raw_args}
    return {}


def _map_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    fn_block = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    raw_name = str(tc.get("name") or tc.get("tool") or fn_block.get("name") or "unknown")
    mapped = _TOOL_NAME_MAP.get(raw_name, raw_name)
    args = _parse_tool_args(
        tc.get("arguments")
        if tc.get("arguments") is not None
        else tc.get("args")
        if tc.get("args") is not None
        else tc.get("input")
        if tc.get("input") is not None
        else fn_block.get("arguments")
    )
    command = ""
    file_path = ""
    if mapped == "Bash":
        command = str(args.get("CommandLine") or args.get("command") or args.get("cmd") or "").strip()
        summary = f"Bash {command}".strip()
    elif mapped in ("Read", "Write", "Edit"):
        file_path = str(
            args.get("AbsolutePath")
            or args.get("TargetFile")
            or args.get("file_path")
            or args.get("path")
            or args.get("Path")
            or ""
        ).strip()
        summary = f"{mapped} {file_path}".strip()
    elif mapped == "Grep":
        query = str(args.get("Query") or args.get("query") or args.get("pattern") or "").strip()
        summary = f"Grep {query}".strip()
    elif mapped == "Glob":
        target = str(args.get("SearchDirectory") or args.get("Pattern") or args.get("path") or "").strip()
        summary = f"Glob {target}".strip()
    else:
        summary = mapped

    return {
        "call_id": tc.get("id") or tc.get("call_id") or tc.get("tool_call_id"),
        "tool": mapped,
        "raw_tool": raw_name,
        "summary": summary,
        "command": command,
        "file_path": file_path,
        "args": args,
    }


def _extract_usage_from_row(row: dict[str, Any]) -> dict[str, int] | None:
    src = None
    for key in ("usage", "token_usage", "tokenUsage"):
        if isinstance(row.get(key), dict):
            src = row[key]
            break
    if src is None and isinstance(row.get("plannerResponse"), dict):
        pr = row["plannerResponse"]
        if isinstance(pr.get("usage"), dict):
            src = pr["usage"]
    if src is None:
        if any(k in row for k in ("input_tokens", "cache_read_tokens", "cache_read_input_tokens", "output_tokens")):
            src = row
    if src is None:
        return None
    inp = int(src.get("input_tokens", 0) or 0)
    cr = int(src.get("cache_read_input_tokens", src.get("cache_read_tokens", 0)) or 0)
    cw = int(src.get("cache_creation_input_tokens", src.get("cache_write_tokens", 0)) or 0)
    out = int(src.get("output_tokens", 0) or 0)
    return {
        "input_tokens": inp,
        "cache_read_tokens": cr,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw,
        "output_tokens": out,
    }


def _is_result_row(row: dict[str, Any]) -> bool:
    rtype = str(row.get("type") or row.get("step_type") or "").upper()
    subtype = str(row.get("subtype") or row.get("kind") or "").upper()
    role = str(row.get("role") or "").lower()
    if rtype == "MODEL" and subtype in ("GENERIC", "", "TOOL_RESULT", "COMMAND_STATUS"):
        return True
    if rtype in ("TOOL_RESULT", "TOOL_RESPONSE", "GENERIC", "RUN_COMMAND_RESPONSE", "VIEW_FILE_RESPONSE"):
        return True
    if role == "tool":
        return True
    return False


def antigravity_read(
    path: str | Path,
    offset: int = 0,
    after: int = -1,
    final: bool = True,
) -> tuple[list[dict[str, Any]], int, int]:
    """Incrementally read Antigravity transcript.jsonl / transcript_full.jsonl.

    Returns (items, next_offset, last_step_index).
    """
    p = Path(path)
    if not p.is_file():
        return [], offset, after

    try:
        total_len = p.stat().st_size
    except OSError:
        return [], offset, after
    if offset < 0 or offset > total_len:
        offset = 0
    if offset == total_len:
        return [], offset, after

    try:
        with p.open("rb") as fh:
            fh.seek(offset)
            slice_bytes = fh.read()
    except OSError:
        return [], offset, after
    if not final and slice_bytes and not slice_bytes.endswith(b"\n"):
        last_nl = slice_bytes.rfind(b"\n")
        if last_nl == -1:
            return [], offset, after
        slice_bytes = slice_bytes[: last_nl + 1]

    consumed_end = offset + len(slice_bytes)
    text_chunk = slice_bytes.decode("utf-8", errors="replace")

    parsed_rows: list[tuple[int, dict[str, Any]]] = []
    running_step = after
    for raw_line in text_chunk.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        explicit_step = row.get("step_index", row.get("stepIndex"))
        if explicit_step is not None:
            step_idx = int(explicit_step)
        else:
            running_step += 1
            step_idx = running_step
        if step_idx <= after:
            running_step = max(running_step, step_idx)
            continue
        running_step = max(running_step, step_idx)
        parsed_rows.append((step_idx, row))

    items: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []
    last_step_index = after

    def _flush_pending() -> None:
        while pending_calls:
            call = pending_calls.pop(0)
            items.append(
                {
                    "kind": "tool_use",
                    "step_index": call["planner_step"],
                    "tool": call["tool"],
                    "raw_tool": call["raw_tool"],
                    "summary": call["summary"],
                    "command": call["command"],
                    "file_path": call["file_path"],
                    "args": call["args"],
                    "output": "",
                    "exit_code": None,
                    "is_error": False,
                    "usage": call.get("usage"),
                }
            )

    for step_idx, row in parsed_rows:
        last_step_index = max(last_step_index, step_idx)
        rtype = str(row.get("type") or row.get("step_type") or "").upper()
        role = str(row.get("role") or "").lower()

        if rtype == "USER_INPUT" or role == "user":
            _flush_pending()
            items.append(
                {
                    "kind": "user",
                    "step_index": step_idx,
                    "text": _strip_user_request(_extract_text_field(row)),
                }
            )
            continue

        if rtype == "PLANNER_RESPONSE" or role == "assistant" or "tool_calls" in row or "toolCalls" in row:
            _flush_pending()
            pr_block = row.get("plannerResponse") if isinstance(row.get("plannerResponse"), dict) else row
            tcs = pr_block.get("tool_calls") or pr_block.get("toolCalls") or []
            usage = _extract_usage_from_row(row)
            if tcs:
                for tc in tcs:
                    if isinstance(tc, dict):
                        mapped = _map_tool_call(tc)
                        mapped["planner_step"] = step_idx
                        mapped["usage"] = usage
                        pending_calls.append(mapped)
            else:
                items.append(
                    {
                        "kind": "assistant",
                        "step_index": step_idx,
                        "text": _extract_text_field(row),
                        "usage": usage,
                    }
                )
            continue

        if _is_result_row(row):
            raw_out = _extract_text_field(row)
            cleaned_out, exit_code = _clean_tool_output(raw_out)
            if exit_code is None and "exit_code" in row and row["exit_code"] is not None:
                exit_code = int(row["exit_code"])
            is_err = bool(
                row.get("is_error")
                or row.get("error")
                or (exit_code is not None and exit_code != 0)
            )
            call_id = row.get("call_id") or row.get("tool_call_id")
            matched_idx = None
            if pending_calls:
                if call_id is not None:
                    for i, pc in enumerate(pending_calls):
                        if pc.get("call_id") == call_id:
                            matched_idx = i
                            break
                if matched_idx is None:
                    matched_idx = 0
                call = pending_calls.pop(matched_idx)
                items.append(
                    {
                        "kind": "tool_use",
                        "step_index": step_idx,
                        "tool": call["tool"],
                        "raw_tool": call["raw_tool"],
                        "summary": call["summary"],
                        "command": call["command"],
                        "file_path": call["file_path"],
                        "args": call["args"],
                        "output": cleaned_out,
                        "exit_code": exit_code,
                        "is_error": is_err,
                        "usage": call.get("usage"),
                    }
                )
            else:
                items.append(
                    {
                        "kind": "tool_result",
                        "step_index": step_idx,
                        "output": cleaned_out,
                        "exit_code": exit_code,
                        "is_error": is_err,
                    }
                )
            continue

    if final:
        _flush_pending()

    return items, consumed_end, last_step_index


def effective_tokens(usage_dict: dict[str, Any], model: str | None = None) -> float:
    """Compute cache-weighted effective token cost for Antigravity / Opus models."""
    raw_model = str(model or usage_dict.get("model") or "gemini-4-carbon").strip().lower()
    norm_model = _MODEL_ALIASES.get(raw_model, raw_model)
    weights = MODEL_WEIGHTS.get(norm_model, MODEL_WEIGHTS["gemini-4-carbon"])

    inp = float(usage_dict.get("input_tokens", 0) or 0)
    cr = float(
        usage_dict.get("cache_read_input_tokens", usage_dict.get("cache_read_tokens", 0)) or 0
    )
    cw = float(
        usage_dict.get("cache_creation_input_tokens", usage_dict.get("cache_write_tokens", 0)) or 0
    )
    out = float(usage_dict.get("output_tokens", 0) or 0)

    return (
        weights["input"] * inp
        + weights["cache_read"] * cr
        + weights["cache_write"] * cw
        + weights["output"] * out
    )


def antigravity_session_usage(
    path: str | Path,
    model: str = "gemini-4-carbon",
) -> dict[str, Any]:
    """Sum token usage across an Antigravity transcript JSONL file."""
    p = Path(path)
    totals: dict[str, int] = {
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "requests": 0,
    }
    if p.is_file():
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                try:
                    row = json.loads(s)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                u = _extract_usage_from_row(row)
                if u is None:
                    continue
                totals["input_tokens"] += u["input_tokens"]
                totals["cache_read_tokens"] += u["cache_read_tokens"]
                totals["cache_read_input_tokens"] += u["cache_read_input_tokens"]
                totals["cache_creation_input_tokens"] += u["cache_creation_input_tokens"]
                totals["output_tokens"] += u["output_tokens"]
                totals["requests"] += 1

    raw_total = (
        totals["input_tokens"]
        + totals["cache_read_tokens"]
        + totals["cache_creation_input_tokens"]
        + totals["output_tokens"]
    )
    eff = effective_tokens(totals, model=model)
    return {
        **totals,
        "model": model,
        "raw_tokens": raw_total,
        "effective_tokens": round(eff, 4),
    }


# ---------------------------------------------------------------------------
# Zero-LLM EnvFactsDistiller + Lifecycle + Forgetting (M2, AD-1)
# ---------------------------------------------------------------------------

_CMD_MISSING_RE = re.compile(
    r"(?:is not recognized as an internal or external command|"
    r"command not found|"
    r"executable file not found|"
    r"No module named\s+['\"]?([A-Za-z0-9_.-]+)['\"]?|"
    r"TermNotFound|"
    r"not recognized as the name of a cmdlet)",
    re.IGNORECASE,
)
_PS_SEP_RE = re.compile(r"not a valid statement separator", re.IGNORECASE)
_WIN_FIND_TREE_ERR_RE = re.compile(
    r"(?:FIND:\s*Parameter format not correct|"
    r"System32\\find\.exe|"
    r"Invalid switch\s*-|"
    r"Too many parameters.*tree)",
    re.IGNORECASE,
)
_ARG_ERR_RE = re.compile(
    r"(?:unrecognized arguments?:|"
    r"unknown option|"
    r"unknown flag|"
    r"invalid option|"
    r"no such option|"
    r"unexpected argument|"
    r"invalid argument)",
    re.IGNORECASE,
)
_ENV_ERR_RE = re.compile(
    r"(?:KeyError:\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]|"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+(?:environment variable\s+)?(?:is\s+)?not set|"
    r"missing\s+env(?:ironment)?\s+var(?:iable)?\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?)",
    re.IGNORECASE,
)
_BOUNDARY_ERR_RE = re.compile(
    r"(?:UnicodeEncodeError|"
    r"codec can't encode|"
    r"PermissionError|"
    r"Read-only file system|"
    r"cannot find the path specified|"
    r"No such file or directory|"
    r"outside workspace)",
    re.IGNORECASE,
)


def _strip_env_prefix(cmd: str) -> tuple[dict[str, str], str]:
    tokens = cmd.strip().split()
    envs: dict[str, str] = {}
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        k, v = tokens[i].split("=", 1)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            envs[k] = v
            i += 1
        else:
            break
    return envs, " ".join(tokens[i:])


def _base_exec(cmd: str) -> str:
    _, rest = _strip_env_prefix(cmd)
    parts = rest.split()
    if not parts:
        return ""
    if len(parts) >= 3 and Path(parts[0]).name.lower().startswith("python") and parts[1] == "-m":
        return parts[2]
    if parts[0] in ("npx", "uv", "poetry") and len(parts) >= 2:
        return parts[1]
    return Path(parts[0]).name


def _command_signature(cmd: str) -> str:
    _, rest = _strip_env_prefix(cmd)
    parts = rest.split()
    if not parts:
        return ""
    if len(parts) >= 3 and Path(parts[0]).name.lower().startswith("python") and parts[1] == "-m":
        return f"{Path(parts[0]).name} -m {parts[2]}"
    return parts[0]


def _make_fact_id(family: str, key: str) -> str:
    digest = hashlib.md5(f"{family}:{key}".encode("utf-8")).hexdigest()[:10]
    return f"{family}_{digest}"


class Lifecycle:
    """Zero-LLM recency-decayed score, promotion, exercise gate, and contradiction logic."""

    @staticmethod
    def new_life(now: int, session_id: str) -> dict[str, Any]:
        return {
            "status": "CANDIDATE",
            "k": 1,
            "score": 1.0,
            "last_seen": now,
            "n_fired": 0,
            "n_helpful": 0,
            "n_harmful": 0,
            "contradict_streak": 0,
            "sessions": [session_id],
        }

    @staticmethod
    def observe_support(life: dict[str, Any], now: int, session_id: str) -> dict[str, Any]:
        age = max(0, now - int(life.get("last_seen", now)))
        decayed = float(life.get("score", 0.0)) * (GAMMA ** age)
        sessions = list(life.get("sessions") or [])
        if session_id not in sessions:
            sessions.append(session_id)
            life["k"] = int(life.get("k", 0)) + 1
        life["sessions"] = sessions[-32:]
        life["score"] = round(decayed + 1.0, 6)
        life["last_seen"] = now
        life["contradict_streak"] = 0
        if life.get("status") == "CANDIDATE" and int(life.get("k", 0)) >= K_PROMOTE:
            life["status"] = "ACTIVE"
        return life

    @staticmethod
    def record_exercise(life: dict[str, Any], helpful: bool, now: int) -> dict[str, Any]:
        age = max(0, now - int(life.get("last_seen", now)))
        decayed = float(life.get("score", 0.0)) * (GAMMA ** age)
        life["n_fired"] = int(life.get("n_fired", 0)) + 1
        if helpful:
            life["n_helpful"] = int(life.get("n_helpful", 0)) + 1
            life["score"] = round(decayed + 0.5, 6)
            life["contradict_streak"] = 0
        else:
            life["n_harmful"] = int(life.get("n_harmful", 0)) + 1
            life["score"] = round(max(SCORE_FLOOR, decayed - LAMBDA), 6)
        life["last_seen"] = now

        n_fired = int(life["n_fired"])
        fire_rate = float(life["n_helpful"]) / n_fired if n_fired > 0 else 1.0
        if n_fired >= FIRE_MIN_N and (fire_rate < FIRE_GATE or life["score"] <= SCORE_FLOOR):
            life["status"] = "RETIRED"
        return life

    @staticmethod
    def record_contradiction(life: dict[str, Any], now: int) -> dict[str, Any]:
        age = max(0, now - int(life.get("last_seen", now)))
        decayed = float(life.get("score", 0.0)) * (GAMMA ** age)
        life["contradict_streak"] = int(life.get("contradict_streak", 0)) + 1
        life["score"] = round(max(SCORE_FLOOR, decayed - LAMBDA), 6)
        life["last_seen"] = now
        if life["contradict_streak"] >= CONTRADICT_STREAK:
            life["status"] = "RETIRED"
        return life


class EnvFactsDistiller:
    """Zero-LLM repository environment micro-skill distiller (AD-1 compliant)."""

    def __init__(
        self,
        repo: str | Path | None = None,
        state_root: str | Path | None = None,
    ) -> None:
        self.repo_path = Path(repo).resolve() if repo is not None else Path.cwd().resolve()
        self.state_root = (
            Path(state_root).resolve() if state_root is not None else default_state_root(self.repo_path)
        )
        self.state_path = resolve_envfacts_path(self.repo_path, self.state_root)
        self.slug = repo_slug(self.repo_path)

    def _default_state(self) -> dict[str, Any]:
        return {
            "repo": self.repo_path.name or self.slug,
            "now": 0,
            "rendered": "",
            "opt_tokens": 0.0,
            "facts": {},
            "forgotten": {},
        }

    def load_state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("repo", self.repo_path.name or self.slug)
                    data.setdefault("now", 0)
                    data.setdefault("rendered", "")
                    data["opt_tokens"] = 0.0
                    data.setdefault("facts", {})
                    data.setdefault("forgotten", {})
                    return data
            except Exception:
                pass
        return self._default_state()

    def save_state(self, state: dict[str, Any]) -> Path:
        state["opt_tokens"] = 0.0
        state["rendered"] = self.render_block(state)
        return write_json_atomic(self.state_path, state)

    def active_facts(self, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        st = state if state is not None else self.load_state()
        candidates = [
            f
            for f in st.get("facts", {}).values()
            if isinstance(f, dict)
            and f.get("life", {}).get("status") == "ACTIVE"
            and is_claim_safe(str(f.get("claim", "")))
        ]
        candidates.sort(
            key=lambda f: (
                float(f["life"].get("score", 0.0)),
                int(f["life"].get("k", 0)),
                int(f["life"].get("last_seen", 0)),
            ),
            reverse=True,
        )
        return candidates[:MAX_FACTS]

    def render_block(self, state: dict[str, Any] | None = None) -> str:
        active = self.active_facts(state)
        if not active:
            return ""
        lines = [ENVFACTS_HEADER]
        for fact in active:
            bullet = f"- {fact['claim'].strip()}"
            candidate_text = "\n".join(lines + [bullet])
            if len(candidate_text) <= MAX_RENDERED_CHARS and estimate_tokens(candidate_text) <= MAX_TOKENS:
                lines.append(bullet)
            else:
                break
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    @staticmethod
    def _extract_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bash_events = [it for it in items if it.get("kind") == "tool_use" and it.get("tool") == "Bash"]
        extracted: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _add(family: str, key: str, claim: str, params: dict[str, Any]) -> None:
            if not is_claim_safe(claim):
                return
            fid = _make_fact_id(family, key)
            if fid in seen_ids:
                return
            seen_ids.add(fid)
            extracted.append({"id": fid, "family": family, "claim": claim, "params": params})

        for idx, ev in enumerate(bash_events):
            cmd = str(ev.get("command") or "").strip()
            out = str(ev.get("output") or "")
            is_err = bool(ev.get("is_error"))
            exit_code = ev.get("exit_code")
            if not cmd or not is_err:
                continue

            # 1. Windows shell repairs (PowerShell && -> ; or rtk find / tree on win32)
            if "&&" in cmd and _PS_SEP_RE.search(out):
                repaired_found = any(
                    not b2.get("is_error") and ";" in str(b2.get("command") or "")
                    for b2 in bash_events[idx + 1 :]
                )
                if repaired_found:
                    _add(
                        "win_shell_repair",
                        "ps_semicolon",
                        "PowerShell `&&` fails (`not a valid statement separator`); chain commands with `;`.",
                        {"broken_sep": "&&", "repaired_sep": ";"},
                    )
                    continue

            if ("rtk find" in cmd or "rtk tree" in cmd) and _WIN_FIND_TREE_ERR_RE.search(out):
                tool_tok = "rtk find" if "rtk find" in cmd else "rtk tree"
                repaired_found = any(
                    not b2.get("is_error") and not str(b2.get("command") or "").startswith(tool_tok)
                    for b2 in bash_events[idx + 1 :]
                )
                if repaired_found:
                    _add(
                        "win_shell_repair",
                        f"win_{tool_tok.replace(' ', '_')}",
                        f"`{tool_tok}` fails on Windows (`System32` conflict); use native shell commands.",
                        {"broken_cmd": tool_tok},
                    )
                    continue

            # 2. Boundary repairs (encoding / path / permission)
            if _BOUNDARY_ERR_RE.search(out):
                for b2 in bash_events[idx + 1 :]:
                    if b2.get("is_error"):
                        continue
                    c2 = str(b2.get("command") or "").strip()
                    envs2, rest2 = _strip_env_prefix(c2)
                    if "PYTHONIOENCODING" in envs2 or _base_exec(c2) == _base_exec(cmd):
                        fix_hint = (
                            f"Set `PYTHONIOENCODING={envs2['PYTHONIOENCODING']}`"
                            if "PYTHONIOENCODING" in envs2
                            else f"Run `{c2}` with valid workspace path"
                        )
                        _add(
                            "boundary",
                            f"{_base_exec(cmd)}:boundary",
                            f"`{cmd}` hit a boundary error; {fix_hint}.",
                            {"broken_cmd": cmd, "repaired_cmd": c2, "env": envs2},
                        )
                        break

            # 3. Env value repairs
            m_env = _ENV_ERR_RE.search(out)
            if m_env:
                var_name = next((g for g in m_env.groups() if g), "")
                for b2 in bash_events[idx + 1 :]:
                    if b2.get("is_error"):
                        continue
                    c2 = str(b2.get("command") or "").strip()
                    envs2, _ = _strip_env_prefix(c2)
                    if var_name and (var_name in envs2 or f"{var_name}=" in c2):
                        val = envs2.get(var_name, "configured")
                        _add(
                            "env_value",
                            var_name,
                            f"Environment variable `{var_name}={val}` is required for `{_base_exec(cmd)}`.",
                            {"key": var_name, "value": val},
                        )
                        break

            # 4. FormRepair (missing bare executable -> repaired wrapper e.g. python -m pytest)
            if _CMD_MISSING_RE.search(out) or exit_code in (127, 9009):
                broken_sig = _command_signature(cmd)
                broken_base = _base_exec(cmd)
                repaired_match: str | None = None
                for b2 in bash_events[idx + 1 :]:
                    if b2.get("is_error"):
                        continue
                    c2 = str(b2.get("command") or "").strip()
                    sig2 = _command_signature(c2)
                    if broken_base and broken_base in sig2 and sig2 != broken_sig:
                        repaired_match = sig2
                        break
                if repaired_match:
                    _add(
                        "form_repair",
                        f"{broken_sig}->{repaired_match}",
                        f"`{broken_sig}` fails (`command_missing`); use `{repaired_match}` instead.",
                        {"broken_cmd": broken_sig, "repaired_cmd": repaired_match, "error_kind": "command_missing"},
                    )
                else:
                    # 5. AbsentTool
                    _add(
                        "absent_tool",
                        broken_sig,
                        f"Tool `{broken_sig}` is unavailable in this environment (`command_missing`).",
                        {"tool": broken_sig},
                    )
                continue

            # 6. ArgRepair (invalid flag/option -> corrected flag on same executable)
            if _ARG_ERR_RE.search(out):
                base1 = _base_exec(cmd)
                for b2 in bash_events[idx + 1 :]:
                    if b2.get("is_error"):
                        continue
                    c2 = str(b2.get("command") or "").strip()
                    if base1 and _base_exec(c2) == base1 and c2 != cmd:
                        _add(
                            "arg_repair",
                            f"{base1}:{cmd}->{c2}",
                            f"`{cmd}` fails with an invalid flag; use `{c2}`.",
                            {"tool": base1, "bad_cmd": cmd, "good_cmd": c2},
                        )
                        break

        return extracted

    def fold_transcript(
        self,
        transcript_path: str | Path,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Fold an Antigravity JSONL transcript into AD-1 envfacts.json (opt_tokens == 0.0)."""
        if not is_enabled(self.repo_path):
            return _disabled_copy()

        items, _, _ = antigravity_read(transcript_path, offset=0, after=-1, final=True)
        state = self.load_state()
        now = int(state.get("now", 0)) + 1
        state["now"] = now
        sess = session_id or f"sess_{now}_{Path(transcript_path).stem}"

        facts: dict[str, Any] = state.setdefault("facts", {})
        forgotten: dict[str, Any] = state.setdefault("forgotten", {})
        bash_events = [it for it in items if it.get("kind") == "tool_use" and it.get("tool") == "Bash"]

        # First evaluate existing ACTIVE/CANDIDATE facts against observed Bash runs
        for fid, fact in list(facts.items()):
            if not is_claim_safe(str(fact.get("claim", ""))):
                facts.pop(fid, None)
                continue
            life = fact.get("life", {})
            family = fact.get("family")
            params = fact.get("params", {})

            if family == "form_repair":
                broken = str(params.get("broken_cmd", ""))
                repaired = str(params.get("repaired_cmd", ""))
                for ev in bash_events:
                    cmd = str(ev.get("command") or "").strip()
                    sig = _command_signature(cmd)
                    is_err = bool(ev.get("is_error"))
                    if repaired and sig == repaired:
                        Lifecycle.record_exercise(life, helpful=not is_err, now=now)
                    elif broken and sig == broken and not is_err:
                        # Bare broken command succeeded -> contradiction!
                        Lifecycle.record_contradiction(life, now=now)

        # Now extract candidate facts from this session
        for cand in self._extract_candidates(items):
            fid = cand["id"]
            if fid in forgotten:
                continue
            if fid in facts:
                Lifecycle.observe_support(facts[fid]["life"], now=now, session_id=sess)
            else:
                facts[fid] = {
                    "id": fid,
                    "family": cand["family"],
                    "claim": cand["claim"],
                    "params": cand["params"],
                    "life": Lifecycle.new_life(now=now, session_id=sess),
                }

        self.save_state(state)
        return state

    def forget(self, fid: str) -> dict[str, Any]:
        if not is_enabled(self.repo_path):
            return _disabled_copy()
        state = self.load_state()
        facts = state.setdefault("facts", {})
        forgotten = state.setdefault("forgotten", {})
        if fid in facts:
            forgotten[fid] = facts.pop(fid)
        elif fid not in forgotten:
            forgotten[fid] = {"id": fid, "forgotten_at": state.get("now", 0)}
        self.save_state(state)
        return {"status": "forgotten", "id": fid, "rendered": state["rendered"], "opt_tokens": 0.0}

    def unforget(self, fid: str) -> dict[str, Any]:
        if not is_enabled(self.repo_path):
            return _disabled_copy()
        state = self.load_state()
        facts = state.setdefault("facts", {})
        forgotten = state.setdefault("forgotten", {})
        if fid in forgotten:
            rec = forgotten.pop(fid)
            if isinstance(rec, dict) and "claim" in rec and is_claim_safe(rec["claim"]):
                life = rec.setdefault("life", {})
                if int(life.get("k", 0)) >= K_PROMOTE and life.get("status") != "RETIRED":
                    life["status"] = "ACTIVE"
                facts[fid] = rec
        self.save_state(state)
        return {"status": "unforgotten", "id": fid, "rendered": state["rendered"], "opt_tokens": 0.0}


# ---------------------------------------------------------------------------
# Live SpiralState + p90 EnvelopeTracker + TurnGuard (M3)
# ---------------------------------------------------------------------------

_TEST_CMD_RE = re.compile(
    r"\b(?:pytest|unittest|vitest|jest|cargo\s+test|go\s+test|npm\s+test|node\s+--test)\b",
    re.IGNORECASE,
)
_PASS_VERDICT_RE = re.compile(r"(?:\b\d+\s+passed\b|\bOK\b|Tests:\s+\d+\s+passed)", re.IGNORECASE)
_FAIL_VERDICT_RE = re.compile(r"(?:\b\d+\s+failed\b|\bFAILED\b|\bERROR\b|AssertionError|Traceback)", re.IGNORECASE)

_NORM_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
_NORM_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_NORM_LINE_RE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_NORM_PATH_PREFIX_RE = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\\/\s]+)+[\\/]")
_NORM_WS_RE = re.compile(r"\s+")


class SpiralState:
    """Tracks per-segment edit churn, failure signature repetition, and runner verdicts."""

    def __init__(self) -> None:
        self.turns: int = 0
        self.edit_counts: dict[str, int] = {}
        self.error_outputs: int = 0
        self.test_runs: int = 0
        self.fail_sigs: list[str] = []
        self.history: list[str] = []
        self.last_verdict: str = "unknown"

    @property
    def distinct_edit_files(self) -> int:
        return len(self.edit_counts)

    @property
    def edit_churn(self) -> int:
        return sum(self.edit_counts.values())

    @property
    def repeated_fail_sigs(self) -> int:
        if not self.fail_sigs:
            return 0
        return len(self.fail_sigs) - len(set(self.fail_sigs))

    @property
    def stagnation(self) -> float:
        if self.error_outputs <= 0:
            return 0.0
        return round(self.repeated_fail_sigs / float(self.error_outputs), 4)

    @staticmethod
    def _failure_sig(text: str) -> str:
        norm = _NORM_TS_RE.sub("", text or "")
        norm = _NORM_HEX_RE.sub("0xADDR", norm)
        norm = _NORM_LINE_RE.sub("line N", norm)
        norm = _NORM_PATH_PREFIX_RE.sub("", norm)
        norm = _NORM_WS_RE.sub(" ", norm).strip().lower()
        return hashlib.md5(norm.encode("utf-8")).hexdigest()

    @staticmethod
    def runner_verdict(text: str) -> str:
        if not text:
            return "unknown"
        if _FAIL_VERDICT_RE.search(text):
            return "red"
        if _PASS_VERDICT_RE.search(text) or "Command exited with code 0" in text:
            return "green"
        return "unknown"

    def observe(self, item: dict[str, Any]) -> None:
        kind = item.get("kind")
        if kind == "user":
            return
        self.turns += 1
        tool = str(item.get("tool") or "")
        summary = str(item.get("summary") or tool or kind or "step")

        if tool in ("Edit", "Write"):
            fp = str(item.get("file_path") or summary)
            self.edit_counts[fp] = self.edit_counts.get(fp, 0) + 1

        if tool == "Bash":
            cmd = str(item.get("command") or "")
            if _TEST_CMD_RE.search(cmd):
                self.test_runs += 1

        out = str(item.get("output") or "")
        is_err = bool(item.get("is_error"))
        if is_err:
            self.error_outputs += 1
            self.fail_sigs.append(self._failure_sig(out or summary))
            self.last_verdict = "red"
        elif tool == "Bash":
            verdict = self.runner_verdict(out)
            if verdict != "unknown":
                self.last_verdict = verdict

        self.history.append(f"{summary} ({'ERR' if is_err else 'OK'})")

    def reset_segment(self) -> None:
        self.turns = 0
        self.edit_counts.clear()
        self.error_outputs = 0
        self.test_runs = 0
        self.fail_sigs.clear()
        self.history.clear()
        self.last_verdict = "unknown"

    def recent_digest(self, n: int = 24, envelope: float | None = None) -> str:
        header = (
            f"turns={self.turns} edit_churn={self.edit_churn} "
            f"distinct_edit_files={self.distinct_edit_files} "
            f"error_outputs={self.error_outputs} test_runs={self.test_runs} "
            f"repeated_identical_failures={self.repeated_fail_sigs} "
            f"stagnation={self.stagnation:.2f}"
        )
        if envelope is not None:
            header += f" envelope={envelope:.2f}"
        tail = self.history[-n:] if n > 0 else []
        if not tail:
            return header
        return header + "\n" + "\n".join(tail)


class EnvelopeTracker:
    """Linear-interpolated p90 step envelope calibrated strictly from resolved turns."""

    def __init__(
        self,
        pct: float = 90.0,
        margin: float = 1.25,
        min_samples: int = 5,
        frozen_envelope: float | None = None,
    ) -> None:
        self.pct = float(pct)
        self.margin = float(margin)
        self.min_samples = int(min_samples)
        self.frozen_envelope = frozen_envelope
        self.samples: list[int] = []

    def record(self, turn_count: int, resolved: bool = True) -> None:
        if not resolved:
            return
        if turn_count > 0:
            self.samples.append(int(turn_count))

    def p90(self) -> float | None:
        if len(self.samples) < self.min_samples:
            return None
        ordered = sorted(self.samples)
        pos = (self.pct / 100.0) * (len(ordered) - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        frac = pos - lo
        return ordered[lo] + frac * (ordered[hi] - ordered[lo])

    def envelope(self) -> float | None:
        if self.frozen_envelope is not None:
            return float(self.frozen_envelope)
        q = self.p90()
        if q is None:
            return None
        return q * self.margin

    @classmethod
    def load(cls, path: Path) -> "EnvelopeTracker":
        tracker = cls()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    samples = data.get("samples") or []
                    tracker.samples = [int(x) for x in samples if isinstance(x, (int, float)) and int(x) > 0][-500:]
            except Exception:
                pass
        return tracker

    def save(self, path: Path) -> Path:
        return write_json_atomic(path, {"pct": self.pct, "margin": self.margin, "min_samples": self.min_samples, "samples": self.samples[-500:]})


class TurnGuard:
    """Mid-turn edit-test loop detector backed by p90 EnvelopeTracker & local judge."""

    def __init__(
        self,
        envelope_tracker: EnvelopeTracker | None = None,
        judge_fn: Callable[[str], dict[str, Any]] | None = None,
        max_nudges: int = 1,
        repo: str | Path | None = None,
    ) -> None:
        self.envelope_tracker = envelope_tracker or EnvelopeTracker()
        self.judge_fn = judge_fn
        self.max_nudges = int(max_nudges)
        self.repo = repo
        self.nudges_this_turn = 0
        self.total_nudges = 0

    def reset_turn_budget(self) -> None:
        self.nudges_this_turn = 0

    def gate_for_judge(self, state: SpiralState) -> bool:
        if self.nudges_this_turn >= self.max_nudges:
            return False
        if state.stagnation < 0.20:
            return False
        env = self.envelope_tracker.envelope()
        if env is not None and state.turns >= 2.5 * env and state.error_outputs >= 2:
            return True
        if state.edit_churn >= 4 and state.error_outputs >= 6 and state.stagnation >= 0.20:
            return True
        if env is not None and state.turns >= env and state.error_outputs >= 3 and state.stagnation >= 0.20:
            return True
        return False

    def _default_judge(self, digest: str, state: SpiralState) -> dict[str, Any]:
        # Try invoking local Laya decision_router.py --mode judge-loop if available
        dr_path = Path(__file__).resolve().parent / "decision_router.py"
        if dr_path.is_file() and os.environ.get("ASW_DECISION_MODEL_ENABLED", "1").strip().lower() not in _FALSEY_STRS:
            try:
                proc = subprocess.run(
                    [sys.executable, str(dr_path), "--mode", "judge-loop", "--compact", "--text", digest],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    parsed = json.loads(proc.stdout.strip().splitlines()[-1])
                    if isinstance(parsed, dict) and "stuck" in parsed:
                        return parsed
            except Exception:
                pass

        stuck = state.edit_churn >= 4 and state.error_outputs >= 6 and state.stagnation >= 0.20
        conf = min(0.95, 0.55 + 0.40 * state.stagnation) if stuck else 0.15
        return {"stuck": stuck, "confidence": round(conf, 4), "source": "local_spiral_fallback"}

    @staticmethod
    def nudge_text(state: SpiralState) -> str:
        msg = (
            f"Loop notice: {state.turns} steps, {state.edit_churn} edits across "
            f"{state.distinct_edit_files} file(s), {state.error_outputs} errors "
            f"({state.repeated_fail_sigs} repeated identical failures). "
            "Pause edits, inspect the underlying root cause, and adopt a different diagnostic hypothesis."
        )
        # Guarantee <= 95 tokens
        words = msg.split()
        if estimate_tokens(msg) > MAX_NUDGE_TOKENS:
            msg = " ".join(words[:MAX_NUDGE_TOKENS])
        return msg

    def step(self, state: SpiralState) -> dict[str, Any]:
        if not is_enabled(self.repo):
            return _disabled_copy()

        env = self.envelope_tracker.envelope()
        if self.nudges_this_turn >= self.max_nudges:
            return {
                "nudge": False,
                "r": self.total_nudges,
                "stuck": False,
                "backstop_triggered": False,
                "stagnation": state.stagnation,
                "envelope": env,
            }

        backstop = bool(
            env is not None
            and state.turns >= 2.5 * env
            and state.error_outputs >= 2
            and state.stagnation >= 0.20
        )
        gated = self.gate_for_judge(state)
        if not gated and not backstop:
            return {
                "nudge": False,
                "r": self.total_nudges,
                "stuck": False,
                "backstop_triggered": False,
                "stagnation": state.stagnation,
                "envelope": env,
            }

        digest = state.recent_digest(n=24, envelope=env)
        if self.judge_fn is not None:
            verdict = self.judge_fn(digest)
        else:
            verdict = self._default_judge(digest, state)

        stuck = bool(verdict.get("stuck")) or backstop
        if not stuck:
            return {
                "nudge": False,
                "r": self.total_nudges,
                "stuck": False,
                "backstop_triggered": False,
                "confidence": verdict.get("confidence", 0.0),
                "stagnation": state.stagnation,
                "envelope": env,
            }

        msg = self.nudge_text(state)
        self.nudges_this_turn += 1
        self.total_nudges += 1
        snapshot = {
            "nudge": True,
            "ephemeralMessage": msg,
            "r": self.total_nudges,
            "stuck": True,
            "backstop_triggered": backstop,
            "confidence": verdict.get("confidence", 1.0 if backstop else 0.75),
            "stagnation": state.stagnation,
            "envelope": env,
        }
        state.reset_segment()
        return snapshot


# ---------------------------------------------------------------------------
# Public High-Level API & Deterministic 6-Session A/B Benchmark (M5)
# ---------------------------------------------------------------------------


def status(repo: str | Path | None = None, state_root: str | Path | None = None) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    distiller = EnvFactsDistiller(repo=repo, state_root=state_root)
    st = distiller.load_state()
    active = distiller.active_facts(st)
    return {
        "enabled": True,
        "status": "ready",
        "repo": st["repo"],
        "repo_slug": distiller.slug,
        "state_path": str(distiller.state_path),
        "fact_count": len(st.get("facts", {})),
        "active_facts": len(active),
        "forgotten_count": len(st.get("forgotten", {})),
        "opt_tokens": 0.0,
        "rendered_tokens": estimate_tokens(st.get("rendered", "")),
    }


def _find_latest_user_prompt_offset(tp: Path) -> int:
    """Scan backwards in 64 KB chunks to find exact byte offset of latest non-synthetic USER_INPUT."""
    try:
        sz = tp.stat().st_size
    except OSError:
        return 0
    if sz <= 65_536:
        return 0
    chunk_size = 65_536
    pos = sz
    carry = b""
    try:
        with tp.open("rb") as fh:
            while pos > 0:
                read_start = max(0, pos - chunk_size)
                fh.seek(read_start)
                buf = fh.read(pos - read_start) + carry
                lines = buf.splitlines(keepends=True)
                if read_start > 0 and lines:
                    carry = lines.pop(0)
                    base_off = read_start + len(carry)
                else:
                    carry = b""
                    base_off = read_start
                running = base_off
                line_offsets: list[tuple[int, bytes]] = []
                for ln in lines:
                    line_offsets.append((running, ln))
                    running += len(ln)
                for line_off, raw_ln in reversed(line_offsets):
                    if b"USER_INPUT" not in raw_ln and b'"role"' not in raw_ln:
                        continue
                    try:
                        row = json.loads(raw_ln.decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    rtype = str(row.get("type") or row.get("step_type") or "").upper()
                    role = str(row.get("role") or "").lower()
                    if rtype == "USER_INPUT" or role == "user":
                        txt = _strip_user_request(_extract_text_field(row))
                        if not re.search(r"ASW [A-Z0-9_-]+ MODE ENABLED!", txt, re.IGNORECASE):
                            return line_off
                pos = read_start
    except OSError:
        return 0
    return 0


def fold_transcript(
    transcript_path: str | Path,
    repo: str | Path | None = None,
    state_root: str | Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    distiller = EnvFactsDistiller(repo=repo, state_root=state_root)
    st = distiller.fold_transcript(transcript_path, session_id=session_id)

    # Also fold ended-green prompt-turns into per-repo EnvelopeTracker (envelope.json)
    env_path = distiller.state_path.parent / "envelope.json"
    tracker = EnvelopeTracker.load(env_path)
    items, _, _ = antigravity_read(transcript_path, offset=0, after=-1, final=True)
    seg_state = SpiralState()
    last_verdict_failed: bool | None = None
    for it in items:
        if it.get("kind") in ("user", "prompt"):
            txt = str(it.get("text") or "")
            if not re.search(r"ASW [A-Z0-9_-]+ MODE ENABLED!", txt, re.IGNORECASE):
                if seg_state.turns > 0 and last_verdict_failed is not True:
                    tracker.record(seg_state.turns, resolved=True)
                seg_state = SpiralState()
                last_verdict_failed = None
            continue
        seg_state.observe(it)
        if it.get("kind") == "tool_use" and it.get("tool") == "Bash":
            rv = SpiralState.runner_verdict(str(it.get("output") or ""))
            if rv == "red" or it.get("is_error"):
                last_verdict_failed = True
            elif rv == "green":
                last_verdict_failed = False
    if seg_state.turns > 0 and last_verdict_failed is not True:
        tracker.record(seg_state.turns, resolved=True)
    if tracker.samples:
        tracker.save(env_path)

    return {
        "enabled": True,
        "status": "folded",
        "state_path": str(distiller.state_path),
        "envelope_path": str(env_path),
        "envelope_samples": len(tracker.samples),
        "fact_count": len(st.get("facts", {})),
        "active_facts": len(distiller.active_facts(st)),
        "opt_tokens": 0.0,
        "rendered": st.get("rendered", ""),
    }


def session_start(repo: str | Path | None = None, state_root: str | Path | None = None) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    distiller = EnvFactsDistiller(repo=repo, state_root=state_root)
    st = distiller.load_state()
    rendered = distiller.render_block(st)
    return {
        "enabled": True,
        "systemMessage": rendered,
        "active_facts": len(distiller.active_facts(st)),
        "rendered_tokens": estimate_tokens(rendered),
        "opt_tokens": 0.0,
    }


def check_turn(
    transcript_path: str | Path,
    repo: str | Path | None = None,
    state_root: str | Path | None = None,
) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    tp = Path(transcript_path)
    start_off = _find_latest_user_prompt_offset(tp)
    items, _, _ = antigravity_read(tp, offset=start_off, after=-1, final=True)

    # Scope strictly to the active prompt-turn (keyed by immutable step_index + prompt hash)
    last_prompt_idx = -1
    last_prompt_sig = "turn_0"
    for idx, it in enumerate(items):
        if it.get("kind") in ("user", "prompt"):
            txt = str(it.get("text") or "")
            if not re.search(r"ASW [A-Z0-9_-]+ MODE ENABLED!", txt, re.IGNORECASE):
                last_prompt_idx = idx
                step_no = it.get("step_index", idx)
                p_hash = hashlib.md5(txt[:160].encode("utf-8", "replace")).hexdigest()[:10]
                last_prompt_sig = f"step_{step_no}_{p_hash}"

    turn_items = items[last_prompt_idx + 1 :] if last_prompt_idx >= 0 else items

    # Enforce r=1 max_nudges persistence and load per-repo EnvelopeTracker
    repo_p = Path(repo).resolve() if repo is not None else Path.cwd().resolve()
    s_root = Path(state_root).resolve() if state_root is not None else default_state_root(repo_p)
    slug_dir = s_root / repo_slug(repo_p)
    guard_state_path = slug_dir / "turn_guard.json"
    env_tracker = EnvelopeTracker.load(slug_dir / "envelope.json")
    turn_key = f"{tp.name}:{last_prompt_sig}"
    prior_nudges = 0
    if guard_state_path.is_file():
        try:
            gd = json.loads(guard_state_path.read_text(encoding="utf-8"))
            if isinstance(gd, dict) and gd.get("turn_key") == turn_key:
                prior_nudges = int(gd.get("nudges", 0))
        except Exception:
            prior_nudges = 0

    state = SpiralState()
    for it in turn_items:
        state.observe(it)
    guard = TurnGuard(envelope_tracker=env_tracker, repo=repo_p)
    guard.nudges_this_turn = prior_nudges
    guard.total_nudges = prior_nudges
    res = guard.step(state)
    if res.get("nudge"):
        try:
            write_json_atomic(guard_state_path, {"turn_key": turn_key, "nudges": guard.nudges_this_turn})
        except Exception:
            pass
    res["enabled"] = True
    res["turns"] = state.turns
    res["edit_churn"] = state.edit_churn
    res["error_outputs"] = state.error_outputs
    return res


def get_microskills(repo: str | Path | None = None, state_root: str | Path | None = None) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    distiller = EnvFactsDistiller(repo=repo, state_root=state_root)
    st = distiller.load_state()
    return {
        "enabled": True,
        "repo_slug": distiller.slug,
        "opt_tokens": 0.0,
        "rendered": distiller.render_block(st),
        "facts": st.get("facts", {}),
        "forgotten": st.get("forgotten", {}),
    }


def forget_fact(fid: str, repo: str | Path | None = None, state_root: str | Path | None = None) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    return EnvFactsDistiller(repo=repo, state_root=state_root).forget(fid)


def unforget_fact(fid: str, repo: str | Path | None = None, state_root: str | Path | None = None) -> dict[str, Any]:
    if not is_enabled(repo):
        return _disabled_copy()
    return EnvFactsDistiller(repo=repo, state_root=state_root).unforget(fid)


def _dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _build_hook_duplicate_rows(step_start: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "USER_INPUT",
            "step_index": step_start,
            "is_duplicate_hook": True,
            "text": "<USER_REQUEST>ASW PLAN MODE ENABLED! Re-injected cascading hook payload</USER_REQUEST>",
        },
        {
            "type": "PLANNER_RESPONSE",
            "step_index": step_start + 1,
            "is_duplicate_hook": True,
            "tool_calls": [],
            "text": "Acknowledging duplicate mode injection.",
            "usage": {"input_tokens": 1800, "cache_read_tokens": 3000, "output_tokens": 120},
        },
    ]


def _build_discovery_waste_rows(step_start: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "PLANNER_RESPONSE",
            "step_index": step_start,
            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest -q"}}],
            "usage": {"input_tokens": 1400, "cache_read_tokens": 4200, "output_tokens": 90},
        },
        {
            "type": "MODEL",
            "subtype": "GENERIC",
            "step_index": step_start + 1,
            "text": "Command exited with code 127\n'pytest' is not recognized",
        },
        {
            "type": "PLANNER_RESPONSE",
            "step_index": step_start + 2,
            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest --version"}}],
            "usage": {"input_tokens": 1450, "cache_read_tokens": 4400, "output_tokens": 85},
        },
        {
            "type": "MODEL",
            "subtype": "GENERIC",
            "step_index": step_start + 3,
            "text": "Command exited with code 127\n'pytest' is not recognized",
        },
    ]


def _build_spiral_step_rows(step_start: int, count: int, identical: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    idx = step_start
    for i in range(count):
        target = "src/engine.py" if identical else f"src/module_{i}.py"
        err_msg = (
            "AssertionError: invariant M3 mismatch on state transition"
            if identical
            else f"UniqueModuleError_{i}: symbol missing in module_{i}"
        )
        rows.extend(
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": idx,
                    "tool_calls": [{"name": "replace_file_content", "arguments": {"TargetFile": target}}],
                    "usage": {"input_tokens": 1600, "cache_read_tokens": 5000, "output_tokens": 140},
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": idx + 1, "text": f"Edited {target}"},
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": idx + 2,
                    "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                    "usage": {"input_tokens": 1650, "cache_read_tokens": 5200, "output_tokens": 110},
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": idx + 3, "text": f"Command exited with code 1\n{err_msg}"},
            ]
        )
        idx += 4
    return rows


def run_benchmark(
    model: str = "gemini-4-carbon",
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run deterministic 6-session Antigravity JSONL A/B benchmark in an isolated temp dir."""
    if not is_enabled():
        return _disabled_copy()

    tmp_dir = Path(tempfile.mkdtemp(prefix="te_ab_bench_"))
    try:
        repo_dir = tmp_dir / "bench_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        state_root = tmp_dir / "state"
        base_dir = tmp_dir / "baseline"
        te_dir = tmp_dir / "te"
        distiller = EnvFactsDistiller(repo=repo_dir, state_root=state_root)

        baseline_dup_eff = 0.0
        te_dup_eff = 0.0
        spiral_nudges = 0
        productive_false_nudges = 0
        session_reports: list[dict[str, Any]] = []

        # Sessions 1-3: Warmup (hook duplication + pytest -> python -m pytest discovery)
        for s_idx in range(1, 4):
            base_rows = [
                {"type": "USER_INPUT", "step_index": 0, "text": f"<USER_REQUEST>/asw-plan warmup session {s_idx}</USER_REQUEST>"},
                *_build_hook_duplicate_rows(1),
                *_build_discovery_waste_rows(3),
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 7,
                    "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                    "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
                },
                {"type": "MODEL", "subtype": "GENERIC", "step_index": 8, "text": "Command exited with code 0\n12 passed"},
            ]
            # TE arm drops cascading duplicate hook rows
            te_rows = [r for r in base_rows if not r.get("is_duplicate_hook")]
            bp = base_dir / f"session_{s_idx}.jsonl"
            tp = te_dir / f"session_{s_idx}.jsonl"
            _dump_jsonl(bp, base_rows)
            _dump_jsonl(tp, te_rows)
            distiller.fold_transcript(tp, session_id=f"bench_s{s_idx}")

            bu = antigravity_session_usage(bp, model=model)
            tu = antigravity_session_usage(tp, model=model)
            for r in base_rows:
                if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                    baseline_dup_eff += effective_tokens(r["usage"], model=model)
            for r in te_rows:
                if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                    te_dup_eff += effective_tokens(r["usage"], model=model)
            session_reports.append({"session": s_idx, "phase": "warmup", "baseline": bu, "token_economizer": tu})

        # Session 4: Post-warmup EnvFacts payoff (avoids pytest discovery retries)
        s4_base = [
            {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop implement feature</USER_REQUEST>"},
            *_build_hook_duplicate_rows(1),
            *_build_discovery_waste_rows(3),
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 7,
                "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
            },
            {"type": "MODEL", "subtype": "GENERIC", "step_index": 8, "text": "Command exited with code 0\n14 passed"},
        ]
        s4_te = [
            {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop implement feature</USER_REQUEST>"},
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
            },
            {"type": "MODEL", "subtype": "GENERIC", "step_index": 2, "text": "Command exited with code 0\n14 passed"},
        ]
        _dump_jsonl(base_dir / "session_4.jsonl", s4_base)
        _dump_jsonl(te_dir / "session_4.jsonl", s4_te)
        for r in s4_base:
            if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                baseline_dup_eff += effective_tokens(r["usage"], model=model)
        for r in s4_te:
            if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                te_dup_eff += effective_tokens(r["usage"], model=model)
        session_reports.append(
            {
                "session": 4,
                "phase": "post_warmup",
                "baseline": antigravity_session_usage(base_dir / "session_4.jsonl", model=model),
                "token_economizer": antigravity_session_usage(te_dir / "session_4.jsonl", model=model),
            }
        )

        # Session 5: Post-warmup edit-test spiral truncated by TurnGuard
        s5_spiral = _build_spiral_step_rows(3, count=14, identical=True)
        s5_base = [
            {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop fix state bug</USER_REQUEST>"},
            *_build_hook_duplicate_rows(1),
            *s5_spiral,
        ]
        # Stream through SpiralState + TurnGuard to find exact truncation turn
        te_s5_candidate_path = tmp_dir / "s5_stream.jsonl"
        _dump_jsonl(te_s5_candidate_path, s5_spiral)
        stream_items, _, _ = antigravity_read(te_s5_candidate_path, offset=0, after=-1, final=True)
        spiral_state = SpiralState()
        env_tracker = EnvelopeTracker.load(distiller.state_path.parent / "envelope.json")
        guard = TurnGuard(
            envelope_tracker=env_tracker,
            max_nudges=1,
            repo=repo_dir,
        )
        truncated_row_limit = len(s5_spiral)
        for idx_item, it in enumerate(stream_items):
            spiral_state.observe(it)
            verdict = guard.step(spiral_state)
            if verdict.get("nudge"):
                spiral_nudges += 1
                truncated_row_limit = min(len(s5_spiral), (idx_item + 1) * 2)
                break

        s5_te = [
            {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop fix state bug</USER_REQUEST>"},
            *s5_spiral[:truncated_row_limit],
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 200,
                "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
            },
            {"type": "MODEL", "subtype": "GENERIC", "step_index": 201, "text": "Command exited with code 0\n15 passed"},
        ]
        _dump_jsonl(base_dir / "session_5.jsonl", s5_base)
        _dump_jsonl(te_dir / "session_5.jsonl", s5_te)
        for r in s5_base:
            if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                baseline_dup_eff += effective_tokens(r["usage"], model=model)
        for r in s5_te:
            if r.get("is_duplicate_hook") and isinstance(r.get("usage"), dict):
                te_dup_eff += effective_tokens(r["usage"], model=model)
        session_reports.append(
            {
                "session": 5,
                "phase": "post_warmup",
                "baseline": antigravity_session_usage(base_dir / "session_5.jsonl", model=model),
                "token_economizer": antigravity_session_usage(te_dir / "session_5.jsonl", model=model),
            }
        )

        # Session 6: Post-warmup productive changing-error multi-file grind (0 false nudges)
        s6_prod = _build_spiral_step_rows(1, count=7, identical=False)
        s6_base = [
            {"type": "USER_INPUT", "step_index": 0, "text": "<USER_REQUEST>/asw-loop refactor modules</USER_REQUEST>"},
            *s6_prod,
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 100,
                "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "python -m pytest -q"}}],
                "usage": {"input_tokens": 1500, "cache_read_tokens": 4600, "output_tokens": 100},
            },
            {"type": "MODEL", "subtype": "GENERIC", "step_index": 101, "text": "Command exited with code 0\n20 passed"},
        ]
        _dump_jsonl(base_dir / "session_6.jsonl", s6_base)
        _dump_jsonl(te_dir / "session_6.jsonl", s6_base)
        prod_items, _, _ = antigravity_read(te_dir / "session_6.jsonl", offset=0, after=-1, final=True)
        prod_state = SpiralState()
        prod_guard = TurnGuard(max_nudges=1, repo=repo_dir)
        for it in prod_items:
            prod_state.observe(it)
            res = prod_guard.step(prod_state)
            if res.get("nudge"):
                productive_false_nudges += 1
        session_reports.append(
            {
                "session": 6,
                "phase": "post_warmup",
                "baseline": antigravity_session_usage(base_dir / "session_6.jsonl", model=model),
                "token_economizer": antigravity_session_usage(te_dir / "session_6.jsonl", model=model),
            }
        )

        base_raw = sum(s["baseline"]["raw_tokens"] for s in session_reports)
        te_raw = sum(s["token_economizer"]["raw_tokens"] for s in session_reports)
        base_eff = sum(s["baseline"]["effective_tokens"] for s in session_reports)
        te_eff = sum(s["token_economizer"]["effective_tokens"] for s in session_reports)

        post_base_eff = sum(s["baseline"]["effective_tokens"] for s in session_reports if s["phase"] == "post_warmup")
        post_te_eff = sum(s["token_economizer"]["effective_tokens"] for s in session_reports if s["phase"] == "post_warmup")

        dup_saved_pct = (
            ((baseline_dup_eff - te_dup_eff) / baseline_dup_eff) * 100.0
            if baseline_dup_eff > 0
            else 0.0
        )
        post_red_pct = (
            ((post_base_eff - post_te_eff) / post_base_eff) * 100.0
            if post_base_eff > 0
            else 0.0
        )
        raw_red_pct = ((base_raw - te_raw) / base_raw) * 100.0 if base_raw > 0 else 0.0
        eff_red_pct = ((base_eff - te_eff) / base_eff) * 100.0 if base_eff > 0 else 0.0

        st = distiller.load_state()
        report = {
            "enabled": True,
            "model": model,
            "opt_tokens": 0.0,
            "envfacts_active_count": len(distiller.active_facts(st)),
            "envfacts_rendered_tokens": estimate_tokens(st.get("rendered", "")),
            "baseline_total_raw_tokens": base_raw,
            "te_total_raw_tokens": te_raw,
            "raw_token_reduction_pct": round(raw_red_pct, 2),
            "baseline_total_effective_tokens": round(base_eff, 4),
            "te_total_effective_tokens": round(te_eff, 4),
            "effective_token_reduction_pct": round(eff_red_pct, 2),
            "baseline_post_warmup_effective_tokens": round(post_base_eff, 4),
            "te_post_warmup_effective_tokens": round(post_te_eff, 4),
            "post_warmup_effective_token_reduction_pct": round(post_red_pct, 2),
            "duplicate_hook_tokens_saved_pct": round(dup_saved_pct, 2),
            "spiral_nudges_emitted": spiral_nudges,
            "productive_false_nudges": productive_false_nudges,
            "sessions": session_reports,
        }
        if output_path is not None:
            write_json_atomic(output_path, report)
        return report
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity TokenEconomizer Engine (Zero-API Overhead)")
    parser.add_argument("--status", action="store_true", help="Show TokenEconomizer state and status")
    parser.add_argument("--fold", type=str, default=None, help="Fold Antigravity JSONL transcript into envfacts.json")
    parser.add_argument("--session-start", action="store_true", help="Emit SessionStart KV-cached systemMessage")
    parser.add_argument("--check-turn", type=str, default=None, help="Evaluate SpiralState + TurnGuard on transcript")
    parser.add_argument("--microskills", action="store_true", help="List learned EnvFacts micro-skills")
    parser.add_argument("--forget", type=str, default=None, help="Forget a learned micro-skill by ID")
    parser.add_argument("--unforget", type=str, default=None, help="Restore a forgotten micro-skill by ID")
    parser.add_argument("--benchmark", action="store_true", help="Run deterministic 6-session A/B benchmark")
    parser.add_argument("--repo", type=str, default=None, help="Target repository directory")
    parser.add_argument("--state-root", type=str, default=None, help="Override state root directory")
    parser.add_argument("--output", type=str, default=None, help="Optional JSON output file path")
    parser.add_argument("--model", type=str, default="gemini-4-carbon", help="Model weights key for effective_tokens")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()

    if not is_enabled(repo):
        out = _disabled_copy()
        print(json.dumps(out, indent=2))
        return 0

    if args.benchmark:
        result = run_benchmark(model=args.model, output_path=args.output)
    elif args.fold:
        result = fold_transcript(args.fold, repo=repo, state_root=args.state_root)
    elif args.session_start:
        result = session_start(repo=repo, state_root=args.state_root)
    elif args.check_turn:
        result = check_turn(args.check_turn, repo=repo, state_root=args.state_root)
    elif args.microskills:
        result = get_microskills(repo=repo, state_root=args.state_root)
    elif args.forget:
        result = forget_fact(args.forget, repo=repo, state_root=args.state_root)
    elif args.unforget:
        result = unforget_fact(args.unforget, repo=repo, state_root=args.state_root)
    else:
        result = status(repo=repo, state_root=args.state_root)

    if args.output and not args.benchmark:
        write_json_atomic(args.output, result)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
