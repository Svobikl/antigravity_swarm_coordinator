#!/usr/bin/env python3
"""bmad_lint_spine — Deterministic Architecture Spine & Plan Contract linter for Antigravity Swarm Coordinator.

Adapted from BMAD-METHOD V7 lint-spine + plan-template contract rules (zero external dependencies, Python 3.11+).

Checks:
  1. Spine mode (`--mode spine`, default when scanning architecture docs):
     - `placeholder`: literal TBD / TODO / FIXME / XXX / "similar to AD-n" / unfilled {template-token}
     - `ad_id`: duplicate or non-monotonic AD-n identifiers (`### AD-1`, `### AD-2`, ...)
     - `ad_fields`: an AD-n block missing `Binds`, `Prevents`, or `Rule`
     - `version_pin`: a `## Stack` table row with no version
  2. Plan-contract mode (`--mode plan-contract` or auto-detected for `.asw/plans/*.md`):
     - `frozen_contract`: verifies presence of `<!-- <frozen-after-approval>` ... `<!-- </frozen-after-approval> -->`
     - `io_matrix`: verifies presence of a non-empty `I/O & Edge-Case Matrix` table with zero TBD/TODO cells
     - `code_map`: verifies presence of `## Code Map` section
     - `baseline_revision`: verifies `baseline_revision` in frontmatter when status is ready-for-dev / in-progress / in-review / built / done
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

AD_HEADING = re.compile(r"^#{2,4}\s*AD-(\d+)\b(.*)$", re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]+`")
PLACEHOLDER_WORD = re.compile(r"\b(TBD|TODO|FIXME|XXX)\b")
SIMILAR_TO = re.compile(r"similar to AD-\d+", re.IGNORECASE)
TEMPLATE_TOKEN = re.compile(r"\{[a-z_][a-z0-9_ /.-]*\}")
FROZEN_BLOCK_RE = re.compile(
    r"<!--\s*<frozen-after-approval>.*?-->\s*(.*?)\s*<!--\s*</frozen-after-approval>\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def split_frontmatter(text: str) -> tuple[str, str, int]:
    """Return (frontmatter, body, body_line_offset)."""
    lines = text.split("\n")
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                fm = "\n".join(lines[1:i])
                body = "\n".join(lines[i + 1 :])
                return fm, body, i + 1
    return "", text, 0


def parse_frontmatter_dict(frontmatter: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta


def blank_fences(text: str, *, include_inline_code: bool = False) -> str:
    """Replace each fenced code block with the same number of newlines so line numbers stay exact."""
    cleaned = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    if include_inline_code:
        cleaned = INLINE_CODE.sub(lambda m: " " * len(m.group(0)), cleaned)
    return cleaned


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def find_placeholders(body: str, offset: int, name: str) -> list[dict]:
    findings: list[dict] = []
    scan = blank_fences(body, include_inline_code=True)
    for rx, label, severity in (
        (PLACEHOLDER_WORD, "placeholder marker", "high"),
        (SIMILAR_TO, "unresolved cross-reference", "high"),
        (TEMPLATE_TOKEN, "possible unfilled template token (verify)", "low"),
    ):
        for m in rx.finditer(scan):
            findings.append(
                {
                    "category": "placeholder",
                    "severity": severity,
                    "detail": f"{label}: {m.group(0)!r}",
                    "location": f"{name} (line {offset + line_of(scan, m.start())})",
                }
            )
    return findings


def find_frontmatter_placeholders(frontmatter: str, name: str) -> list[dict]:
    findings: list[dict] = []
    for rx, label, severity in (
        (PLACEHOLDER_WORD, "placeholder marker", "high"),
        (TEMPLATE_TOKEN, "possible unfilled template token (verify)", "low"),
    ):
        for m in rx.finditer(frontmatter):
            findings.append(
                {
                    "category": "placeholder",
                    "severity": severity,
                    "detail": f"frontmatter {label}: {m.group(0)!r}",
                    "location": f"{name} frontmatter (line {1 + line_of(frontmatter, m.start())})",
                }
            )
    return findings


def find_ad_issues(body: str, offset: int, name: str) -> list[dict]:
    findings: list[dict] = []
    scan = blank_fences(body)
    matches = list(AD_HEADING.finditer(scan))
    seen: dict[int, int] = {}
    prev: int | None = None
    for m in matches:
        num = int(m.group(1))
        file_line = offset + line_of(scan, m.start())
        loc = f"{name} AD-{num} (line {file_line})"
        if num in seen:
            findings.append(
                {
                    "category": "ad_id",
                    "severity": "high",
                    "detail": f"AD-{num} id reused (also at line {seen[num]})",
                    "location": loc,
                }
            )
        else:
            seen[num] = file_line
        if prev is not None and num <= prev:
            findings.append(
                {
                    "category": "ad_id",
                    "severity": "high",
                    "detail": f"AD-{num} is non-monotonic (follows AD-{prev}); ids must ascend and never renumber",
                    "location": loc,
                }
            )
        prev = num if prev is None else max(prev, num)

        start = m.end()
        nxt = HEADING.search(scan, start)
        block = scan[start : nxt.start()] if nxt else scan[start:]
        low = block.lower()
        missing = [f for f in ("binds", "prevents", "rule") if f not in low]
        if missing:
            findings.append(
                {
                    "category": "ad_fields",
                    "severity": "high",
                    "detail": f"AD-{num} missing required field(s): {', '.join(missing)}",
                    "location": loc,
                }
            )
    return findings


def _table_cells(row: str) -> list[str]:
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def find_unpinned_stack(body: str, offset: int, name: str) -> list[dict]:
    findings: list[dict] = []
    in_stack = False
    header_seen = False
    name_idx, ver_idx = 0, 1
    scan = blank_fences(body)
    for i, raw in enumerate(scan.splitlines()):
        if HEADING.match(raw):
            in_stack = re.match(r"^##\s+Stack\b", raw) is not None
            header_seen = False
            name_idx, ver_idx = 0, 1
            continue
        if not in_stack or not raw.lstrip().startswith("|"):
            continue
        if set(raw.strip()) <= set("|-: "):
            continue
        cells = _table_cells(raw)
        if not header_seen:
            header_seen = True
            for j, c in enumerate(cells):
                if c.lower() == "name":
                    name_idx = j
                elif c.lower() == "version":
                    ver_idx = j
            continue
        dep = cells[name_idx] if len(cells) > name_idx else ""
        version = cells[ver_idx] if len(cells) > ver_idx else ""
        if not dep or TEMPLATE_TOKEN.search(dep):
            continue
        if not version or TEMPLATE_TOKEN.search(version) or PLACEHOLDER_WORD.search(version):
            findings.append(
                {
                    "category": "version_pin",
                    "severity": "medium",
                    "detail": f"Stack entry {dep!r} has no pinned version",
                    "location": f"{name} (line {offset + i + 1})",
                }
            )
    return findings


def lint_spine(text: str, name: str = "spine") -> dict:
    frontmatter, body, offset = split_frontmatter(text)
    findings: list[dict] = []
    findings += find_frontmatter_placeholders(frontmatter, name)
    findings += find_placeholders(body, offset, name)
    findings += find_ad_issues(body, offset, name)
    findings += find_unpinned_stack(body, offset, name)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "ok": len(findings) == 0,
        "mode": "spine",
        "spine": name,
        "total_findings": len(findings),
        "by_severity": counts,
        "findings": findings,
    }


def extract_frozen_block(text: str) -> str | None:
    m = FROZEN_BLOCK_RE.search(text)
    return m.group(1).strip() if m else None


def lint_plan_contract(text: str, name: str = "plan") -> dict:
    frontmatter, body, offset = split_frontmatter(text)
    meta = parse_frontmatter_dict(frontmatter)
    findings: list[dict] = []

    frozen = extract_frozen_block(text)
    if frozen is None:
        findings.append(
            {
                "category": "frozen_contract",
                "severity": "high",
                "detail": "Missing <!-- <frozen-after-approval> --> ... <!-- </frozen-after-approval> --> block",
                "location": f"{name} (line 1)",
            }
        )
    else:
        for m in PLACEHOLDER_WORD.finditer(blank_fences(frozen, include_inline_code=True)):
            findings.append(
                {
                    "category": "frozen_contract",
                    "severity": "high",
                    "detail": f"Unresolved placeholder {m.group(0)!r} inside <frozen-after-approval> block",
                    "location": f"{name} (<frozen-after-approval>)",
                }
            )

    # Check I/O & Edge-Case Matrix
    matrix_match = re.search(r"^#{2,3}\s+I/O\s*&\s*Edge-Case\s+Matrix\b", body, re.MULTILINE | re.IGNORECASE)
    if not matrix_match:
        findings.append(
            {
                "category": "io_matrix",
                "severity": "high",
                "detail": "Missing `## I/O & Edge-Case Matrix` section",
                "location": f"{name}",
            }
        )
    else:
        start = matrix_match.end()
        nxt = HEADING.search(body, start)
        matrix_section = body[start : nxt.start()] if nxt else body[start:]
        data_rows = []
        header_seen = False
        for raw in matrix_section.splitlines():
            if not raw.lstrip().startswith("|"):
                continue
            if set(raw.strip()) <= set("|-: "):
                continue
            if not header_seen:
                header_seen = True
                continue
            cells = _table_cells(raw)
            if any(cells):
                data_rows.append(cells)
        if not data_rows:
            findings.append(
                {
                    "category": "io_matrix",
                    "severity": "high",
                    "detail": "`I/O & Edge-Case Matrix` table has zero data rows",
                    "location": f"{name} (line {offset + line_of(body, matrix_match.start())})",
                }
            )

    # Check Code Map
    if not re.search(r"^#{2,3}\s+Code\s+Map\b", body, re.MULTILINE | re.IGNORECASE):
        findings.append(
            {
                "category": "code_map",
                "severity": "medium",
                "detail": "Missing `## Code Map` section for context-free subagent handoff",
                "location": f"{name}",
            }
        )

    # Check baseline_revision when plan is approved/active
    status = meta.get("status", "").lower()
    if status in ("ready-for-dev", "in-progress", "in-review", "built", "done"):
        baseline = meta.get("baseline_revision", "").strip()
        if not baseline or baseline.lower() in ("tbd", "todo", "none"):
            findings.append(
                {
                    "category": "baseline_revision",
                    "severity": "medium",
                    "detail": f"Plan with status={status!r} is missing valid `baseline_revision` in frontmatter",
                    "location": f"{name} frontmatter",
                }
            )

    # Also lint any AD-n blocks present in the plan
    findings += find_ad_issues(body, offset, name)

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "ok": len(findings) == 0,
        "mode": "plan-contract",
        "plan": name,
        "total_findings": len(findings),
        "by_severity": counts,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint an Architecture Spine or BMAD/ASW Plan Contract.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace", help="run folder containing `<folder_name>.md`")
    g.add_argument("--file", help="explicit path to markdown file to lint")
    ap.add_argument(
        "--mode",
        choices=("spine", "plan-contract", "auto"),
        default="auto",
        help="lint mode: spine, plan-contract, or auto (default)",
    )
    ap.add_argument("-o", "--output", help="write JSON output to file instead of stdout")
    args = ap.parse_args(argv)

    if args.file:
        target_path = Path(args.file).resolve()
    else:
        ws = Path(args.workspace).resolve()
        target_path = ws / f"{ws.name}.md"

    if not target_path.is_file():
        result = {"ok": False, "error": f"{target_path} not found", "findings": [], "total_findings": 0}
        out = json.dumps(result, indent=2)
        if args.output:
            Path(args.output).write_text(out + "\n", encoding="utf-8")
        else:
            print(out)
        return 1

    text = target_path.read_text(encoding="utf-8-sig")
    mode = args.mode
    if mode == "auto":
        if "<frozen-after-approval>" in text or "I/O & Edge-Case Matrix" in text or ".asw/plans" in target_path.as_posix():
            mode = "plan-contract"
        else:
            mode = "spine"

    if mode == "plan-contract":
        result = lint_plan_contract(text, name=target_path.name)
    else:
        result = lint_spine(text, name=target_path.name)

    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
