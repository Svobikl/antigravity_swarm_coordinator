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

"""Input-Only TOON (Token-Oriented Object Notation) codec and STE-100 linter.

Implements:
- Lossless, 100% type-preserving TOON tabular & object encoding/decoding
- Smart format routing (`encode_smart`, `dumps_smart`) per arXiv:2603.03306
- ASD-STE100 directive & prose linter (`lint_ste100_text`)
- CLI `--benchmark` (10 payloads) and `--lint-ste100`
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable


def _load_estimate_tokens() -> Callable[[str], int]:
    """Dynamically load estimate_tokens from sibling token_economizer.py with fallback."""
    sibling = Path(__file__).resolve().parent / "token_economizer.py"
    if sibling.exists():
        try:
            spec = importlib.util.spec_from_file_location("_token_economizer_for_toon", sibling)
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                fn = getattr(mod, "estimate_tokens", None)
                if callable(fn):
                    return fn
        except Exception:
            pass

    def _fallback_estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(len(text.split()), (len(text) + 3) // 4)

    return _fallback_estimate_tokens


estimate_tokens = _load_estimate_tokens()

_UNSAFE_CELL_CHARS = frozenset(
    {",", "\n", "\r", '"', "\\", ":", "|", "\t", "[", "]", "{", "}", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"}
)
_UNSAFE_HEADER_CHARS = frozenset(
    {",", "{", "}", "[", "]", ":", '"', "\\", "\n", "\r", "\t", "|", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"}
)
_RESERVED_SCALARS = frozenset({"null", "true", "false"})
_INT_RE = re.compile(r"^-?(?:0|[1-9]\d*)$")
_FLOAT_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")

_BANNED_FILLER_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, re.compile(r"\b" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\b", re.IGNORECASE))
    for phrase in (
        "in order to",
        "please note that",
        "make sure to",
        "it is important to",
        "it might be worth",
        "keep in mind that",
        "be sure to",
        "as a reminder",
        "you may want to",
    )
)

_FENCE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_CLI_FLAG_RE = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=\())--[a-z0-9-]+", re.IGNORECASE)
_PATH_TOKEN_RE = re.compile(r"(?:\.?[A-Za-z0-9_-]+/)+[A-Za-z0-9_.*<>-]+")
_FUNC_CALL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\([^)\n]*\)")
_ALL_CAPS_ID_RE = re.compile(r"\b[A-Z][A-Z0-9_-]{2,}\b")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)[.!?;]+(?:\s+|$)", re.IGNORECASE)
_PROSE_WORD_RE = re.compile(r"\d+(?:\.\d+)?|[A-Za-z0-9\u00c0-\u024f]+(?:['\u2019-][A-Za-z0-9\u00c0-\u024f]+)*")
_MJS_DIRECTIVE_RE = re.compile(r"const\s+([A-Za-z0-9_]+_DIRECTIVE)\s*=\s*`((?:\\.|[^`\\])*)`\s*;")


def _looks_like_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        pass
    try:
        int(value)
        return True
    except ValueError:
        return False


def _is_safe_unquoted_str(value: str) -> bool:
    if not value or value != value.strip():
        return False
    if any(ch in _UNSAFE_CELL_CHARS for ch in value):
        return False
    if value in _RESERVED_SCALARS:
        return False
    if _looks_like_number(value):
        return False
    return True


def _encode_header_token(token: str) -> str:
    if (
        token
        and token == token.strip()
        and not token.startswith(("#", "@"))
        and not any(ch in _UNSAFE_HEADER_CHARS for ch in token)
    ):
        return token
    return json.dumps(token, ensure_ascii=False)


def _encode_cell(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str):
        if _is_safe_unquoted_str(value):
            return value
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_cell(raw: str) -> Any:
    if raw == "":
        raise ValueError("Empty unquoted TOON cell")
    if raw[0] == '"':
        val = json.loads(raw)
        if not isinstance(val, str):
            raise ValueError(f"Expected string cell from quoted token: {raw!r}")
        return val
    if raw[0] in ("[", "{"):
        return json.loads(raw)
    if raw == "null":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _FLOAT_RE.fullmatch(raw):
        return float(raw)
    return raw


def _split_toon_row(line: str) -> list[str]:
    """Split a TOON row by top-level commas while respecting JSON strings and []/{} depth."""
    cells: list[str] = []
    n = len(line)
    i = 0
    start = 0
    mode = "start"
    escape = False
    in_string = False
    depth = 0

    while i < n:
        ch = line[i]
        if mode == "start":
            if ch == '"':
                mode = "string"
                escape = False
            elif ch in ("[", "{"):
                mode = "container"
                depth = 1
                in_string = False
                escape = False
            elif ch == ",":
                cells.append("")
                start = i + 1
            else:
                mode = "scalar"
        elif mode == "string":
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                mode = "after_string"
        elif mode == "after_string":
            if ch == ",":
                cells.append(line[start:i])
                start = i + 1
                mode = "start"
            else:
                raise ValueError(f"Unexpected character {ch!r} after quoted TOON cell")
        elif mode == "container":
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                    escape = False
                elif ch in ("[", "{"):
                    depth += 1
                elif ch in ("]", "}"):
                    depth -= 1
                    if depth == 0:
                        mode = "after_container"
        elif mode == "after_container":
            if ch == ",":
                cells.append(line[start:i])
                start = i + 1
                mode = "start"
            else:
                raise ValueError(f"Unexpected character {ch!r} after container TOON cell")
        elif mode == "scalar":
            if ch == ",":
                cells.append(line[start:i])
                start = i + 1
                mode = "start"
        i += 1

    if mode in ("string", "container"):
        raise ValueError("Unterminated quoted or container cell in TOON row")
    cells.append(line[start:])
    return cells


def _is_uniform_table(data: Any) -> bool:
    if not isinstance(data, list) or len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict) or len(first) == 0:
        return False
    keys = list(first.keys())
    if not all(isinstance(k, str) for k in keys):
        return False
    return all(isinstance(row, dict) and list(row.keys()) == keys for row in data)


def _encode_table_block(name_token: str, rows: list[dict[str, Any]]) -> list[str]:
    keys = list(rows[0].keys())
    header_keys = ",".join(_encode_header_token(k) for k in keys)
    lines = [f"{name_token}[{len(rows)}]{{{header_keys}}}:"]
    for row in rows:
        encoded_cells = ",".join(_encode_cell(row[k]) for k in keys)
        lines.append(f"  {encoded_cells}")
    return lines


def _parse_table_header(header_line: str) -> tuple[str, int, list[str]]:
    if not header_line.endswith("}:"):
        raise ValueError(f"Invalid TOON table header: {header_line!r}")

    if header_line.startswith('"'):
        decoder = json.JSONDecoder()
        name, pos = decoder.raw_decode(header_line)
        if not isinstance(name, str):
            raise ValueError(f"Invalid quoted table name in header: {header_line!r}")
    else:
        pos = header_line.find("[")
        if pos <= 0:
            raise ValueError(f"Missing table name in TOON header: {header_line!r}")
        name = header_line[:pos]

    if pos >= len(header_line) or header_line[pos] != "[":
        raise ValueError(f"Missing row count bracket in TOON header: {header_line!r}")
    close_bracket = header_line.find("]", pos + 1)
    if close_bracket < 0:
        raise ValueError(f"Unterminated row count in TOON header: {header_line!r}")
    count_str = header_line[pos + 1 : close_bracket]
    if not count_str.isdigit():
        raise ValueError(f"Non-numeric row count in TOON header: {header_line!r}")
    row_count = int(count_str)

    if close_bracket + 1 >= len(header_line) or header_line[close_bracket + 1] != "{":
        raise ValueError(f"Missing field list brace in TOON header: {header_line!r}")

    fields_inner = header_line[close_bracket + 2 : -2]
    raw_fields = _split_toon_row(fields_inner)
    fields: list[str] = []
    for raw_field in raw_fields:
        if raw_field.startswith('"'):
            parsed_key = json.loads(raw_field)
            if not isinstance(parsed_key, str):
                raise ValueError(f"Invalid field key in TOON header: {raw_field!r}")
            fields.append(parsed_key)
        else:
            if not raw_field:
                raise ValueError(f"Empty field key in TOON header: {header_line!r}")
            fields.append(raw_field)

    return name, row_count, fields


def _decode_table_rows(lines: list[str], start_idx: int, row_count: int, fields: list[str]) -> tuple[list[dict[str, Any]], int]:
    if start_idx + row_count > len(lines):
        raise ValueError(f"Truncated TOON table: expected {row_count} rows, got {len(lines) - start_idx}")
    rows: list[dict[str, Any]] = []
    for offset in range(row_count):
        raw_line = lines[start_idx + offset]
        row_body = raw_line[2:] if raw_line.startswith("  ") else raw_line
        raw_cells = _split_toon_row(row_body)
        if len(raw_cells) != len(fields):
            raise ValueError(
                f"TOON row column mismatch at line {start_idx + offset + 1}: expected {len(fields)}, got {len(raw_cells)}"
            )
        rows.append({k: _decode_cell(c) for k, c in zip(fields, raw_cells)})
    return rows, start_idx + row_count


def encode_toon(data: Any, name: str = "items") -> str:
    """Encode JSON-compatible data into lossless TOON format."""
    if _is_uniform_table(data):
        return "\n".join(_encode_table_block(_encode_header_token(name), data))

    if isinstance(data, dict) and len(data) >= 1 and all(isinstance(k, str) for k in data.keys()):
        lines = ["# TOON-OBJECT"]
        for k, v in data.items():
            json_key = json.dumps(k, ensure_ascii=False)
            if _is_uniform_table(v):
                table_lines = _encode_table_block(json_key, v)
                table_lines[0] = f"@table {table_lines[0]}"
                lines.extend(table_lines)
            else:
                compact_val = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                lines.append(f"@field {json_key}: {compact_val}")
        return "\n".join(lines)

    return "# JSON\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def decode_toon(text: str) -> Any:
    """Decode TOON text back into exact Python/JSON structures with zero coercion."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty TOON input")

    if text.startswith("# JSON\n"):
        return json.loads(text[len("# JSON\n") :])

    lines = re.split(r"\r\n|\n|\r", text)
    if lines and lines[-1] == "":
        lines.pop()
    if lines[0] == "# TOON-OBJECT":
        result: dict[str, Any] = {}
        decoder = json.JSONDecoder()
        idx = 1
        while idx < len(lines):
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue
            if line.startswith("@field "):
                rest = line[len("@field ") :]
                key, pos = decoder.raw_decode(rest)
                if not isinstance(key, str):
                    raise ValueError(f"Expected string @field key: {line!r}")
                after_key = rest[pos:].lstrip()
                if not after_key.startswith(":"):
                    raise ValueError(f"Missing ':' in @field line: {line!r}")
                result[key] = json.loads(after_key[1:].strip())
                idx += 1
            elif line.startswith("@table "):
                header_part = line[len("@table ") :]
                key, row_count, fields = _parse_table_header(header_part)
                rows, idx = _decode_table_rows(lines, idx + 1, row_count, fields)
                result[key] = rows
            else:
                raise ValueError(f"Unexpected line in # TOON-OBJECT: {line!r}")
        return result

    _, row_count, fields = _parse_table_header(lines[0])
    rows, next_idx = _decode_table_rows(lines, 1, row_count, fields)
    trailing = [ln for ln in lines[next_idx:] if ln.strip()]
    if trailing:
        raise ValueError(f"Unexpected trailing content after TOON table: {trailing[0]!r}")
    return rows


def _is_tabular_eligible(data: Any, min_rows: int) -> bool:
    if _is_uniform_table(data) and len(data) >= min_rows:
        return True
    if isinstance(data, dict):
        return any(_is_uniform_table(v) and len(v) >= min_rows for v in data.values())
    return False


def encode_smart(data: Any, name: str = "items", min_rows: int = 3) -> dict[str, Any]:
    """Select TOON only when tabularly eligible and strictly smaller than compact JSON."""
    compact_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    pretty_json = json.dumps(data, ensure_ascii=False, indent=2)
    compact_tokens = estimate_tokens(compact_json)
    pretty_tokens = estimate_tokens(pretty_json)

    toon_str = encode_toon(data, name=name)
    toon_tokens = estimate_tokens(toon_str)

    eligible = _is_tabular_eligible(data, min_rows=min_rows)
    if eligible and toon_tokens < compact_tokens:
        format_used = "toon"
        chosen_text = toon_str
        chosen_tokens = toon_tokens
    else:
        format_used = "json"
        chosen_text = compact_json
        chosen_tokens = compact_tokens

    saved_vs_pretty_pct = (
        round((pretty_tokens - chosen_tokens) * 100.0 / pretty_tokens, 2) if pretty_tokens > 0 else 0.0
    )
    saved_vs_compact_pct = (
        round((compact_tokens - chosen_tokens) * 100.0 / compact_tokens, 2) if compact_tokens > 0 else 0.0
    )

    return {
        "format_used": format_used,
        "text": chosen_text,
        "toon_tokens": toon_tokens,
        "compact_json_tokens": compact_tokens,
        "pretty_json_tokens": pretty_tokens,
        "saved_vs_pretty_pct": saved_vs_pretty_pct,
        "saved_vs_compact_pct": saved_vs_compact_pct,
    }


def dumps_smart(data: Any, name: str = "items", min_rows: int = 3) -> str:
    """Return the chosen compact TOON or compact JSON text from encode_smart."""
    return encode_smart(data, name=name, min_rows=min_rows)["text"]


def lint_ste100_text(text: str, max_words_per_bullet: int = 22) -> dict[str, Any]:
    """Lint prose against ASD-STE100 filler and sentence-length constraints."""
    no_fence = _FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    no_inline = _INLINE_CODE_RE.sub(" ", no_fence)

    violations: list[dict[str, Any]] = []
    max_seen = 0
    skipped_banner = False

    for lineno, raw_line in enumerate(no_inline.splitlines(), start=1):
        for phrase, rx in _BANNED_FILLER_PHRASES:
            match = rx.search(raw_line)
            if match:
                violations.append(
                    {
                        "category": "banned_filler",
                        "line": lineno,
                        "phrase": phrase,
                        "detail": f"Banned conversational filler {match.group(0)!r} on line {lineno}",
                    }
                )

        if not raw_line.strip():
            continue
        if _HEADING_RE.match(raw_line):
            continue
        if not skipped_banner and "ENABLED!" in raw_line:
            skipped_banner = True
            continue

        cleaned = _BULLET_PREFIX_RE.sub("", raw_line)
        cleaned = _FUNC_CALL_RE.sub(" ", cleaned)
        cleaned = _PATH_TOKEN_RE.sub(" ", cleaned)
        cleaned = _CLI_FLAG_RE.sub(" ", cleaned)
        cleaned = _ALL_CAPS_ID_RE.sub(" ", cleaned)

        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
        for sentence in sentences:
            words = _PROSE_WORD_RE.findall(sentence)
            word_count = len(words)
            if word_count > max_seen:
                max_seen = word_count
            if word_count > max_words_per_bullet:
                violations.append(
                    {
                        "category": "sentence_too_long",
                        "line": lineno,
                        "word_count": word_count,
                        "max_words": max_words_per_bullet,
                        "sentence": sentence,
                        "detail": f"Sentence has {word_count} prose words (> {max_words_per_bullet}) on line {lineno}",
                    }
                )

    return {
        "ok": len(violations) == 0,
        "total_violations": len(violations),
        "max_prose_words_seen": max_seen,
        "violations": violations,
    }


def _extract_mjs_directives(source: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for match in _MJS_DIRECTIVE_RE.finditer(source):
        name = match.group(1)
        raw_body = match.group(2)
        body = raw_body.replace("\\`", "`").replace("\\$", "$").replace("\\\\", "\\")
        directives[name] = body
    return directives


def _build_benchmark_payloads() -> list[tuple[str, str, Any]]:
    ast_changed_symbols = [
        {
            "file": f".antigravity/scripts/module_{i:02d}.py",
            "symbol": f"process_batch_item_{i:02d}",
            "kind": "function",
            "line_start": 20 + i * 15,
            "line_end": 32 + i * 15,
            "status": "modified",
        }
        for i in range(16)
    ]
    collapsed_mirrors = [
        {
            "canonical_path": f".antigravity/scripts/tool_{i:02d}.py",
            "mirror_path": f"core_framework/scripts/tool_{i:02d}.py",
            "sha256": f"{i:064x}",
            "bytes": 4096 + i * 128,
            "identical": True,
        }
        for i in range(15)
    ]
    spine_lint_findings = [
        {
            "category": "ad_fields" if i % 2 == 0 else "version_pin",
            "severity": "high" if i % 3 == 0 else "medium",
            "location": f"docs/architecture_spine.md:{10 + i * 7}",
            "detail": f"Architecture decision AD-{i + 1} field verification",
            "rule_id": f"SPINE-{(i % 4) + 1}",
        }
        for i in range(16)
    ]
    subagent_usage_ledger = [
        {
            "agent_id": f"leaf-worker-{i:02d}",
            "model": "gemini-4-hydrogen" if i % 2 == 0 else "gemini-4-neon",
            "input_tokens": 1200 + i * 150,
            "cache_read": 8000 + i * 400,
            "output_tokens": 180 + i * 12,
            "effective_tokens": 1800 + i * 90,
        }
        for i in range(15)
    ]
    requirement_coverage_matrix = [
        {
            "req_id": f"REQ-{(i % 5) + 1}",
            "matrix_id": f"M{(i % 8) + 1}",
            "owner_file": f"tests/test_suite_{i:02d}.py",
            "test_case": f"test_boundary_case_{i:02d}",
            "layer": f"L{(i % 3) + 1}",
            "status": "passed",
        }
        for i in range(15)
    ]
    sting_mutant_report = [
        {
            "mutant_id": f"MUT-{i:03d}",
            "file_path": f".antigravity/scripts/codec_{i % 3}.py",
            "lineno": 40 + i * 6,
            "operator": "boundary_flip" if i % 2 == 0 else "boolean_invert",
            "outcome": "killed",
            "duration_ms": 110 + i * 9,
        }
        for i in range(16)
    ]

    fallback_two_rows = [
        {"id": 1, "name": "alpha", "status": "ok"},
        {"id": 2, "name": "beta", "status": "ok"},
    ]
    fallback_empty_list: list[Any] = []
    fallback_ragged_dicts = [
        {"id": 1, "kind": "alpha"},
        {"id": 2, "kind": "beta", "extra": True},
        {"id": 3, "other": "gamma"},
        {"id": 4, "kind": "delta", "tags": ["a", "b"]},
    ]
    fallback_nested_config = {
        "schema_version": 4,
        "routing": {
            "tiers": {"pro": "gemini-4-neon-high", "flash": "gemini-4-hydrogen"},
            "limits": {"max_subagents": 4, "receipt_tokens": 250},
        },
        "gates": {"sting_threshold": 0.75, "require_frozen_contract": True},
    }

    return [
        ("ast_changed_symbols", "tabular", ast_changed_symbols),
        ("collapsed_mirrors", "tabular", collapsed_mirrors),
        ("spine_lint_findings", "tabular", spine_lint_findings),
        ("subagent_usage_ledger", "tabular", subagent_usage_ledger),
        ("requirement_coverage_matrix", "tabular", requirement_coverage_matrix),
        ("sting_mutant_report", "tabular", sting_mutant_report),
        ("fallback_two_rows", "fallback", fallback_two_rows),
        ("fallback_empty_list", "fallback", fallback_empty_list),
        ("fallback_ragged_dicts", "fallback", fallback_ragged_dicts),
        ("fallback_nested_config", "fallback", fallback_nested_config),
    ]


def run_benchmark() -> dict[str, Any]:
    """Benchmark 10 realistic payloads (6 tabular N>=15 + 4 fallback) and verify M1/M2 invariants."""
    results: list[dict[str, Any]] = []
    all_ok = True

    for name, kind, payload in _build_benchmark_payloads():
        smart = encode_smart(payload, name=name)
        toon_encoded = encode_toon(payload, name=name)
        round_trip_ok = decode_toon(toon_encoded) == payload

        if kind == "tabular":
            passed = (
                round_trip_ok
                and smart["format_used"] == "toon"
                and smart["saved_vs_pretty_pct"] >= 35.0
                and smart["toon_tokens"] < smart["compact_json_tokens"]
            )
        else:
            passed = round_trip_ok and smart["format_used"] == "json" and json.loads(smart["text"]) == payload

        if not passed:
            all_ok = False

        results.append(
            {
                "name": name,
                "kind": kind,
                "passed": passed,
                "round_trip_ok": round_trip_ok,
                "format_used": smart["format_used"],
                "toon_tokens": smart["toon_tokens"],
                "compact_json_tokens": smart["compact_json_tokens"],
                "pretty_json_tokens": smart["pretty_json_tokens"],
                "saved_vs_pretty_pct": smart["saved_vs_pretty_pct"],
                "saved_vs_compact_pct": smart["saved_vs_compact_pct"],
            }
        )

    tabular_items = [r for r in results if r["kind"] == "tabular"]
    avg_saved_pretty = round(
        sum(r["saved_vs_pretty_pct"] for r in tabular_items) / len(tabular_items), 2
    )
    avg_saved_compact = round(
        sum(r["saved_vs_compact_pct"] for r in tabular_items) / len(tabular_items), 2
    )

    return {
        "ok": all_ok,
        "total_payloads": len(results),
        "tabular_count": len(tabular_items),
        "fallback_count": len(results) - len(tabular_items),
        "avg_tabular_saved_vs_pretty_pct": avg_saved_pretty,
        "avg_tabular_saved_vs_compact_pct": avg_saved_compact,
        "payloads": results,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="TOON codec & ASD-STE100 directive linter.")
    parser.add_argument("--benchmark", action="store_true", help="Run 10-payload TOON benchmark.")
    parser.add_argument("--lint-ste100", metavar="FILE", help="Lint a text or .mjs directive file.")
    parser.add_argument("--max-words", type=int, default=22, help="Max prose words per sentence/bullet.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--output", help="Optional path to write output.")
    args = parser.parse_args(argv)

    if args.benchmark:
        report = run_benchmark()
        ok = bool(report["ok"])
    elif args.lint_ste100:
        target = Path(args.lint_ste100)
        if not target.exists():
            err = {"ok": False, "error": f"File not found: {target}"}
            print(json.dumps(err, indent=2) if args.json else err["error"], file=sys.stderr)
            return 2
        content = target.read_text(encoding="utf-8")
        if target.suffix == ".mjs":
            directives = _extract_mjs_directives(content)
            per_directive: dict[str, Any] = {}
            total_violations = 0
            max_words_seen = 0
            for dname, dtext in directives.items():
                res = lint_ste100_text(dtext, max_words_per_bullet=args.max_words)
                per_directive[dname] = res
                total_violations += res["total_violations"]
                if res["max_prose_words_seen"] > max_words_seen:
                    max_words_seen = res["max_prose_words_seen"]
            ok = len(directives) > 0 and all(r["ok"] for r in per_directive.values())
            report = {
                "file": str(target),
                "mode": "mjs_directives",
                "ok": ok,
                "directive_count": len(directives),
                "total_violations": total_violations,
                "max_prose_words_seen": max_words_seen,
                "directives": per_directive,
            }
        else:
            report = lint_ste100_text(content, max_words_per_bullet=args.max_words)
            ok = bool(report["ok"])
    else:
        parser.print_help()
        return 2

    rendered = json.dumps(report, indent=2, ensure_ascii=False) if args.json else json.dumps(report, ensure_ascii=False)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
