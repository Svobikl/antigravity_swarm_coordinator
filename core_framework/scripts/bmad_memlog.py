#!/usr/bin/env python3
"""bmad_memlog — Append-only LLM working memory log (.memlog.md) for Antigravity Swarm Coordinator.

Adapted from BMAD-METHOD V7 memlog + recon_kit tally (zero external dependencies, Python 3.11+).

Invariants:
  1. Append-only, chronological: entries land at the end in the order they happen.
     History is never edited or deleted.
  2. Atomic & concurrency-safe: `init` and `set` write a temp file, flush + fsync, and
     atomically rename (`os.replace`). `append` writes at EOF in a single OS append
     operation (`O_APPEND` on POSIX, `FILE_APPEND_DATA` Win32 handle on Windows).
  3. Built-in `tally` command: counts entries by tag/type and summarizes verified,
     unverified, and overturned claims for `deep-research` and `software-architect`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True

MEMLOG_FILENAME = ".memlog.md"
TAG_RE = re.compile(r"^- \(([^)]+)\)\s+(.*)$")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def resolve_memlog_path(args: argparse.Namespace) -> Path:
    if getattr(args, "path", None):
        return Path(args.path)
    return Path(args.workspace) / MEMLOG_FILENAME


def split_memlog(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict in source order, body str)."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(".memlog.md has no frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        raise ValueError(".memlog.md frontmatter is not terminated")
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, "\n".join(lines[end + 1 :]).lstrip("\n")


def render_memlog(meta: dict[str, str], body: str) -> str:
    fm = "\n".join(f"{k}: {' '.join(str(v).splitlines())}" for k, v in meta.items())
    return "---\n" + fm + "\n---\n\n" + body.rstrip("\n") + "\n"


def touch_meta(meta: dict[str, str]) -> None:
    meta.pop("updated", None)
    meta["updated"] = now_iso()


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_line(path: Path, text: str) -> None:
    """Append text at EOF in a single OS append write and sync to disk."""
    data = text.replace("\n", os.linesep).encode("utf-8")
    if sys.platform != "win32":
        fd = os.open(path, os.O_WRONLY | os.O_APPEND)
        try:
            if os.write(fd, data) != len(data):
                raise OSError(f"short write appending to {path}")
            os.fsync(fd)
        finally:
            os.close(fd)
        return

    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_char_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    k32.WriteFile.restype = wintypes.BOOL
    k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    k32.FlushFileBuffers.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    file_append_data, share_all, open_existing, normal = 0x4, 0x7, 3, 0x80
    handle = k32.CreateFileW(str(path), file_append_data, share_all, None, open_existing, normal, None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        written = wintypes.DWORD()
        if not k32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(data):
            raise OSError(f"short write appending to {path}")
        if not k32.FlushFileBuffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k32.CloseHandle(handle)


def entry_count(body: str) -> int:
    return sum(1 for ln in body.splitlines() if ln.startswith("- "))


def print_ack(path: Path, body: str, extra: dict | None = None) -> None:
    payload: dict[str, object] = {
        "ok": True,
        "memlog": str(path),
        "entries": entry_count(body),
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload))


def cmd_init(args: argparse.Namespace) -> int:
    path = resolve_memlog_path(args)
    if path.exists():
        print(f"error: {path} already exists; use append/set to update it", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    meta: dict[str, str] = {}
    for pair in args.field or []:
        if "=" not in pair:
            print(f"error: --field expects key=value, got {pair!r}", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        meta[k.strip()] = v.strip()
    touch_meta(meta)
    write_atomic(path, render_memlog(meta, ""))
    print_ack(path, "")
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    path = resolve_memlog_path(args)
    raw = path.read_text(encoding="utf-8")
    split_memlog(raw)
    text = " ".join(args.text.split())
    label = args.type or ""
    if args.by:
        label = f"{label} by {args.by}".strip()
    tag = f"({label}) " if label else ""
    entry = f"- {tag}{text}"
    append_line(path, ("" if raw.endswith("\n") else "\n") + entry + "\n")
    print_ack(path, split_memlog(path.read_text(encoding="utf-8"))[1])
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    path = resolve_memlog_path(args)
    meta, body = split_memlog(path.read_text(encoding="utf-8"))
    meta[args.key] = args.value
    touch_meta(meta)
    write_atomic(path, render_memlog(meta, body))
    print_ack(path, body)
    return 0


def tally_entries(body: str) -> dict[str, object]:
    by_type: dict[str, int] = {}
    claims = {"verified": 0, "unverified": 0, "overturned": 0}
    for ln in body.splitlines():
        if not ln.startswith("- "):
            continue
        m = TAG_RE.match(ln)
        if not m:
            by_type["note"] = by_type.get("note", 0) + 1
            continue
        raw_tag, content = m.group(1).strip(), m.group(2).strip()
        kind = raw_tag.split(" by ", 1)[0].strip().lower() or "note"
        by_type[kind] = by_type.get(kind, 0) + 1
        low_content = content.lower()
        if kind in ("claim", "verified", "unverified", "overturned"):
            if kind == "overturned" or "[overturned]" in low_content or "status: overturned" in low_content:
                claims["overturned"] += 1
            elif kind == "unverified" or "[unverified]" in low_content or "status: unverified" in low_content:
                claims["unverified"] += 1
            else:
                claims["verified"] += 1
    return {"by_type": by_type, "claims": claims}


def cmd_tally(args: argparse.Namespace) -> int:
    path = resolve_memlog_path(args)
    _, body = split_memlog(path.read_text(encoding="utf-8"))
    stats = tally_entries(body)
    print_ack(path, body, extra=stats)
    return 0


def _add_target(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace", help=f"run folder ({MEMLOG_FILENAME} inside it)")
    g.add_argument("--path", help="explicit path to .memlog.md")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Append-only LLM working memory log (.memlog.md).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create .memlog.md with initial frontmatter")
    _add_target(p)
    p.add_argument("--field", action="append", metavar="K=V", help="frontmatter field (repeatable)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("append", help="append one chronological entry at the end")
    _add_target(p)
    p.add_argument("--type", help="entry kind (decision, constraint, claim, assumption, question, event, ...)")
    p.add_argument("--by", help="who it came from (user, architect, reviewer, ...)")
    p.add_argument("--text", required=True, help="entry text (collapsed to one line)")
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("set", help="set/replace a descriptive frontmatter field")
    _add_target(p)
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("tally", help="tally entries by type and claim verification status")
    _add_target(p)
    p.set_defaults(func=cmd_tally)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
