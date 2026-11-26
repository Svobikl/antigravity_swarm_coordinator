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

"""Zero-LLM Diff-Scoped AST Mutation Verifier (STING / ExecCritic / PyTation).

Parses unified diffs to locate changed production Python lines, generates up to
`max_mutants` stratified mutants across 7 fault-driven AST operators, prunes
equivalent/duplicate mutants via canonical `ast.dump(tree, include_attributes=False)`,
and executes `pytest -x -q` inside an isolated temporary copy of the repository
with strict `finally` cleanup (Windows read-only + POSIX safe) and `opt_tokens = 0.0`.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IGNORE_COPY_DIRS = frozenset({
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".asw",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
})

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Mutant:
    """Represents a single diff-scoped AST mutant."""

    file_path: str
    lineno: int
    operator: str
    description: str
    mutated_source: str
    ast_dump: str


def read_text_resilient(path: Path | None) -> str:
    """Read text file resiliently across UTF-8 and UTF-16LE/BE encodings."""
    if path is None or not path.exists() or not path.is_file():
        return ""
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return ""
    if not raw_bytes:
        return ""
    if raw_bytes.startswith(b"\xff\xfe"):
        return raw_bytes.decode("utf-16-le", errors="replace").replace("\x00", "")
    if raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes.decode("utf-16-be", errors="replace").replace("\x00", "")
    if b"\x00" in raw_bytes:
        cleaned = raw_bytes.replace(b"\xff\xfe", b"").replace(b"\xfe\xff", b"").replace(b"\x00", b"")
        return cleaned.decode("utf-8", errors="replace")
    return raw_bytes.decode("utf-8", errors="replace")


def _is_production_python_path(rel_path: str) -> bool:
    """Return True if `rel_path` is a non-test Python source file."""
    normalized = rel_path.replace("\\", "/").strip()
    if not normalized or normalized == "/dev/null":
        return False
    if not normalized.endswith(".py"):
        return False
    parts = [p for p in normalized.split("/") if p]
    if any(part.lower() == "tests" for part in parts[:-1]):
        return False
    filename = parts[-1]
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return False
    return True


def _clean_diff_path(raw_path: str) -> str:
    """Strip diff prefixes (`a/`, `b/`) and surrounding quotes."""
    cleaned = raw_path.strip().split("\t")[0].strip()
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    if cleaned == "/dev/null":
        return cleaned
    if cleaned.startswith("b/") or cleaned.startswith("a/"):
        cleaned = cleaned[2:]
    return cleaned.replace("\\", "/")


def parse_diff_hunks(diff_text: str) -> dict[str, set[int]]:
    """Extract target line numbers for modified production `.py` files from a unified diff."""
    if not diff_text:
        return {}

    changed_lines: dict[str, set[int]] = {}
    current_file: str | None = None
    new_line = 0
    old_rem = 0
    new_rem = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current_file = None
            in_hunk = False
            continue

        if line.startswith("+++ ") and not in_hunk:
            candidate = _clean_diff_path(line[4:])
            current_file = candidate if _is_production_python_path(candidate) else None
            in_hunk = False
            continue

        if line.startswith("--- ") and not in_hunk:
            continue

        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            old_rem = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_line = int(hunk_match.group(3))
            new_rem = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
            in_hunk = old_rem > 0 or new_rem > 0
            continue

        if not in_hunk or current_file is None:
            continue

        if line.startswith("+"):
            changed_lines.setdefault(current_file, set()).add(new_line)
            new_line += 1
            new_rem = max(0, new_rem - 1)
        elif line.startswith("-"):
            old_rem = max(0, old_rem - 1)
        elif line.startswith("\\"):
            continue
        else:
            new_line += 1
            old_rem = max(0, old_rem - 1)
            new_rem = max(0, new_rem - 1)

        if old_rem == 0 and new_rem == 0:
            in_hunk = False

    return {path: lines for path, lines in changed_lines.items() if lines}


def _iter_nodes_with_paths(node: ast.AST, path: tuple[tuple[str, int | None], ...] = ()):
    """Yield `(structural_path, node)` pairs deterministically across an AST."""
    yield path, node
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield from _iter_nodes_with_paths(value, path + ((field_name, None),))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _iter_nodes_with_paths(item, path + ((field_name, idx),))


def _resolve_parent_and_node(
    root: ast.AST, path: tuple[tuple[str, int | None], ...]
) -> tuple[ast.AST | None, str | None, int | None, ast.AST]:
    """Resolve `(parent, field_name, index, node)` along `path` on a cloned AST."""
    if not path:
        return None, None, None, root
    cur: Any = root
    for field_name, idx in path[:-1]:
        cur = getattr(cur, field_name)
        if idx is not None:
            cur = cur[idx]
    last_field, last_idx = path[-1]
    target = getattr(cur, last_field)
    if last_idx is not None:
        target = target[last_idx]
    return cur, last_field, last_idx, target


def _replace_at_path(
    root: ast.AST,
    path: tuple[tuple[str, int | None], ...],
    replacement: ast.AST,
) -> None:
    """Replace the AST node at `path` with `replacement`."""
    parent, field_name, idx, _ = _resolve_parent_and_node(root, path)
    if parent is None or field_name is None:
        return
    if idx is None:
        setattr(parent, field_name, replacement)
    else:
        getattr(parent, field_name)[idx] = replacement


class DiffScopedMutator:
    """Generates fault-driven Python AST mutants restricted to changed diff lines."""

    RELATIONAL_MAP: dict[type[ast.cmpop], tuple[type[ast.cmpop], str]] = {
        ast.Lt: (ast.LtE, "< -> <="),
        ast.LtE: (ast.Lt, "<= -> <"),
        ast.Gt: (ast.GtE, "> -> >="),
        ast.GtE: (ast.Gt, ">= -> >"),
    }
    EQUALITY_MAP: dict[type[ast.cmpop], tuple[type[ast.cmpop], str]] = {
        ast.Eq: (ast.NotEq, "== -> !="),
        ast.NotEq: (ast.Eq, "!= -> =="),
        ast.Is: (ast.IsNot, "is -> is not"),
        ast.IsNot: (ast.Is, "is not -> is"),
    }
    MEMBERSHIP_MAP: dict[type[ast.cmpop], tuple[type[ast.cmpop], str]] = {
        ast.In: (ast.NotIn, "in -> not in"),
        ast.NotIn: (ast.In, "not in -> in"),
    }

    def __init__(self, source: str, target_lines: set[int] | None = None, file_path: str = "<string>"):
        self.source = source
        self.target_lines = set(target_lines) if target_lines else set()
        self.file_path = file_path
        self.pruned_equivalent = 0
        self._tree: ast.AST | None = None
        self._seen_dumps: set[str] = set()

    def _ensure_parsed(self) -> ast.AST | None:
        if self._tree is not None:
            return self._tree
        if not self.target_lines:
            return None
        try:
            tree = ast.parse(self.source)
        except SyntaxError:
            return None
        self._tree = tree
        self._seen_dumps = {ast.dump(tree, include_attributes=False)}
        return tree

    def collect_candidates(self) -> list[tuple[Any, ...]]:
        """Collect lightweight `(path, kind, extra, lineno, operator, description)` specs."""
        original_tree = self._ensure_parsed()
        if original_tree is None:
            return []

        specs: list[tuple[Any, ...]] = []
        for path, node in _iter_nodes_with_paths(original_tree):
            lineno = getattr(node, "lineno", None)
            if lineno not in self.target_lines:
                continue

            if isinstance(node, ast.Compare):
                for op_idx, op in enumerate(node.ops):
                    op_type = type(op)
                    for operator_name, mapping in (
                        ("relational_boundary", self.RELATIONAL_MAP),
                        ("equality_flip", self.EQUALITY_MAP),
                        ("membership_flip", self.MEMBERSHIP_MAP),
                    ):
                        if op_type in mapping:
                            new_op_cls, desc = mapping[op_type]
                            specs.append((path, "compare_op", (op_idx, new_op_cls), lineno, operator_name, desc))

            elif isinstance(node, ast.BoolOp):
                if isinstance(node.op, ast.And):
                    specs.append((path, "bool_op", ast.Or, lineno, "boolean_op_flip", "and -> or"))
                elif isinstance(node.op, ast.Or):
                    specs.append((path, "bool_op", ast.And, lineno, "boolean_op_flip", "or -> and"))

            elif isinstance(node, ast.UnaryOp):
                if isinstance(node.op, (ast.Not, ast.USub)):
                    desc = "not x -> x" if isinstance(node.op, ast.Not) else "-x -> x"
                    specs.append((path, "unary_strip", None, lineno, "unary_negation", desc))

            elif isinstance(node, ast.Return) and node.value is not None:
                if isinstance(node.value, ast.Constant):
                    val = node.value.value
                    if isinstance(val, bool):
                        new_val = not val
                        desc = f"return {val} -> return {new_val}"
                    elif isinstance(val, int) and val == 0:
                        new_val = 1
                        desc = "return 0 -> return 1"
                    else:
                        new_val = None
                        desc = "return <expr> -> return None"
                else:
                    new_val = None
                    desc = "return <expr> -> return None"
                specs.append((path, "return_const", new_val, lineno, "return_constant_flip", desc))

            elif isinstance(node, ast.If):
                if isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
                    desc = "if not cond -> if cond"
                else:
                    desc = "if cond -> if not (cond)"
                specs.append((path, "if_flip", None, lineno, "guard_flip", desc))

            elif isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Add):
                    specs.append((path, "bin_op", ast.Sub, lineno, "guard_flip", "+ -> -"))
                elif isinstance(node.op, ast.Sub):
                    specs.append((path, "bin_op", ast.Add, lineno, "guard_flip", "- -> +"))

        return specs

    def materialize_candidate(self, spec: tuple[Any, ...]) -> Mutant | None:
        """Apply one candidate spec in-place, verify uniqueness/syntax, and restore AST."""
        original_tree = self._ensure_parsed()
        if original_tree is None:
            return None
        path, kind, extra, lineno, operator, description = spec
        _, _, _, node = _resolve_parent_and_node(original_tree, path)

        def _record() -> Mutant | None:
            dump = ast.dump(original_tree, include_attributes=False)
            if dump in self._seen_dumps:
                self.pruned_equivalent += 1
                return None
            try:
                mutated_source = ast.unparse(original_tree)
                compile(mutated_source, "<string>", "exec")
            except Exception:
                return None
            self._seen_dumps.add(dump)
            return Mutant(
                file_path=self.file_path,
                lineno=lineno,
                operator=operator,
                description=description,
                mutated_source=mutated_source + "\n",
                ast_dump=dump,
            )

        if kind == "compare_op":
            assert isinstance(node, ast.Compare)
            op_idx, new_op_cls = extra
            orig_op = node.ops[op_idx]
            node.ops[op_idx] = new_op_cls()
            try:
                return _record()
            finally:
                node.ops[op_idx] = orig_op

        if kind == "bool_op":
            assert isinstance(node, ast.BoolOp)
            orig_op = node.op
            node.op = extra()
            try:
                return _record()
            finally:
                node.op = orig_op

        if kind == "unary_strip":
            assert isinstance(node, ast.UnaryOp)
            _replace_at_path(original_tree, path, node.operand)
            try:
                return _record()
            finally:
                _replace_at_path(original_tree, path, node)

        if kind == "return_const":
            assert isinstance(node, ast.Return)
            orig_val = node.value
            node.value = ast.Constant(value=extra)
            try:
                return _record()
            finally:
                node.value = orig_val

        if kind == "if_flip":
            assert isinstance(node, ast.If)
            orig_test = node.test
            if isinstance(orig_test, ast.UnaryOp) and isinstance(orig_test.op, ast.Not):
                node.test = orig_test.operand
            else:
                node.test = ast.UnaryOp(op=ast.Not(), operand=orig_test)
            try:
                return _record()
            finally:
                node.test = orig_test

        if kind == "bin_op":
            assert isinstance(node, ast.BinOp)
            orig_op = node.op
            node.op = extra()
            try:
                return _record()
            finally:
                node.op = orig_op

        return None

    def generate_mutants(self, max_mutants: int | None = None) -> list[Mutant]:
        """Generate deduplicated AST mutants strictly for nodes on `target_lines`."""
        self.pruned_equivalent = 0
        self._tree = None
        specs = self.collect_candidates()
        if not specs:
            return []

        mutants: list[Mutant] = []
        if max_mutants is None:
            for spec in specs:
                m = self.materialize_candidate(spec)
                if m is not None:
                    mutants.append(m)
            return mutants

        if max_mutants <= 0:
            return []

        buckets: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
        for spec in specs:
            buckets[spec[4]].append(spec)
        keys = list(buckets.keys())
        idx_map = {k: 0 for k in keys}
        while len(mutants) < max_mutants:
            progressed = False
            for k in keys:
                pos = idx_map[k]
                while pos < len(buckets[k]):
                    progressed = True
                    m = self.materialize_candidate(buckets[k][pos])
                    pos += 1
                    if m is not None:
                        mutants.append(m)
                        break
                idx_map[k] = pos
                if len(mutants) >= max_mutants:
                    break
            if not progressed:
                break
        return mutants


def _stratify_mutants(mutants: list[Mutant], max_mutants: int) -> list[Mutant]:
    """Select up to `max_mutants` mutants stratified across `(file_path, operator)`."""
    if max_mutants <= 0 or not mutants:
        return []
    if len(mutants) <= max_mutants:
        return list(mutants)

    buckets: dict[tuple[str, str], list[Mutant]] = defaultdict(list)
    for mutant in mutants:
        buckets[(mutant.file_path, mutant.operator)].append(mutant)

    keys = list(buckets.keys())
    selected: list[Mutant] = []
    idx_map = {k: 0 for k in keys}
    while len(selected) < max_mutants:
        progressed = False
        for key in keys:
            pos = idx_map[key]
            if pos < len(buckets[key]):
                selected.append(buckets[key][pos])
                idx_map[key] = pos + 1
                progressed = True
                if len(selected) >= max_mutants:
                    break
        if not progressed:
            break
    return selected


def _handle_remove_readonly(func: Any, path: str, _exc: Any) -> None:
    """Clear read-only attributes on Windows/POSIX before retrying removal."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    func(path)


def _rmtree_force(path: Path) -> None:
    """Recursively remove a directory tree safely on both Windows and POSIX."""
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_handle_remove_readonly)
    else:
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def _copy_ignore(_directory: str, entries: list[str]) -> set[str]:
    """Ignore VCS, cache, and virtualenv directories during isolated repo copy."""
    return {entry for entry in entries if entry in IGNORE_COPY_DIRS}


def _collect_git_diff(repo_path: Path, base_ref: str | None) -> str:
    """Obtain unified diff text from git in `repo_path`."""
    if base_ref:
        cmd = ["git", "diff", base_ref, "--unified=3"]
        proc = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=30)
        return proc.stdout if proc.returncode == 0 else ""

    for cmd in (
        ["git", "diff", "HEAD", "--unified=3"],
        ["git", "diff", "--unified=3"],
        ["git", "diff", "--cached", "--unified=3"],
    ):
        proc = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    return ""


def _build_pytest_env(temp_dir: Path) -> dict[str, str]:
    """Build an isolated subprocess environment pointing `PYTHONPATH` to `temp_dir` first."""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{temp_dir}{os.pathsep}{existing_pp}" if existing_pp else str(temp_dir)
    return env


def _is_test_python_path(rel_path: str) -> bool:
    """Return True if `rel_path` is a Python test file (`tests/test_*.py`, `test_*.py`, `*_test.py`)."""
    normalized = rel_path.replace("\\", "/").strip()
    if not normalized or normalized == "/dev/null" or not normalized.endswith(".py"):
        return False
    name = Path(normalized).name
    return name.startswith("test_") or name.endswith("_test.py")


def _discover_diff_test_targets(
    work_repo: Path,
    diff_text: str,
    prod_files: list[str],
) -> list[str]:
    """Discover diff-modified test files and existing test files matching modified module stems."""
    discovered: set[str] = set()
    in_hunk = False
    old_rem = 0
    new_rem = 0

    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        if line.startswith("+++ ") and not in_hunk:
            cand = _clean_diff_path(line[4:])
            if _is_test_python_path(cand) and (work_repo / cand).is_file():
                discovered.add(cand)
            in_hunk = False
            continue
        if line.startswith("--- ") and not in_hunk:
            continue
        hm = HUNK_HEADER_RE.match(line)
        if hm:
            old_rem = int(hm.group(2)) if hm.group(2) is not None else 1
            new_rem = int(hm.group(4)) if hm.group(4) is not None else 1
            in_hunk = old_rem > 0 or new_rem > 0
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            new_rem = max(0, new_rem - 1)
        elif line.startswith("-"):
            old_rem = max(0, old_rem - 1)
        elif not line.startswith("\\"):
            old_rem = max(0, old_rem - 1)
            new_rem = max(0, new_rem - 1)
        if old_rem == 0 and new_rem == 0:
            in_hunk = False

    tests_dir = work_repo / "tests"
    for prod_rel in prod_files:
        stem = Path(prod_rel).stem
        if not stem:
            continue
        if tests_dir.is_dir():
            exact = tests_dir / f"test_{stem}.py"
            if exact.is_file():
                discovered.add(exact.relative_to(work_repo).as_posix())
            for match in tests_dir.rglob(f"*{stem}*.py"):
                if match.is_file() and _is_test_python_path(match.name):
                    discovered.add(match.relative_to(work_repo).as_posix())
        for pat in (f"test_{stem}.py", f"test_*{stem}*.py", f"*{stem}*_test.py"):
            for match in work_repo.glob(pat):
                if match.is_file() and _is_test_python_path(match.name):
                    discovered.add(match.relative_to(work_repo).as_posix())

    return sorted(discovered)


def run_mutation_verification(
    repo_dir: str | Path,
    diff_text: str | None = None,
    base_ref: str | None = None,
    test_targets: list[str] | tuple[str, ...] | None = None,
    threshold: float = 0.75,
    max_mutants: int = 12,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    """Run diff-scoped AST mutation verification in an isolated temp copy of `repo_dir`."""
    repo_path = Path(repo_dir).resolve()
    effective_diff = _collect_git_diff(repo_path, base_ref) if diff_text is None else diff_text
    hunks = parse_diff_hunks(effective_diff)

    mutators_and_specs: list[tuple[DiffScopedMutator, list[tuple[Any, ...]]]] = []
    total_candidates = 0
    for rel_path, target_lines in hunks.items():
        abs_file = repo_path / rel_path
        if not abs_file.exists() or not abs_file.is_file():
            continue
        source = read_text_resilient(abs_file)
        if not source.strip():
            continue
        mutator = DiffScopedMutator(source, target_lines, file_path=rel_path)
        specs = mutator.collect_candidates()
        if specs:
            mutators_and_specs.append((mutator, specs))
            total_candidates += len(specs)

    selected: list[Mutant] = []
    pruned_equivalent = 0
    if max_mutants > 0 and mutators_and_specs:
        spec_buckets: dict[tuple[str, str], list[tuple[DiffScopedMutator, tuple[Any, ...]]]] = defaultdict(list)
        for mutator, specs in mutators_and_specs:
            for spec in specs:
                spec_buckets[(mutator.file_path, spec[4])].append((mutator, spec))
        keys = list(spec_buckets.keys())
        idx_map = {k: 0 for k in keys}
        while len(selected) < max_mutants:
            progressed = False
            for key in keys:
                pos = idx_map[key]
                while pos < len(spec_buckets[key]):
                    progressed = True
                    mutator, spec = spec_buckets[key][pos]
                    pos += 1
                    m = mutator.materialize_candidate(spec)
                    if m is not None:
                        selected.append(m)
                        break
                idx_map[key] = pos
                if len(selected) >= max_mutants:
                    break
            if not progressed:
                break
        pruned_equivalent = sum(m.pruned_equivalent for m, _ in mutators_and_specs)

    if not selected:
        return {
            "status": "no_python_mutants",
            "passed": True,
            "mutation_score": 1.0,
            "threshold": threshold,
            "total_candidates": total_candidates,
            "pruned_equivalent": pruned_equivalent,
            "viable": 0,
            "killed": 0,
            "survived": 0,
            "timeout_killed": 0,
            "survivors": [],
            "opt_tokens": 0.0,
        }

    temp_dir = Path(tempfile.mkdtemp(prefix="sting_mut_"))
    try:
        work_repo = temp_dir / "repo"
        shutil.copytree(
            repo_path,
            work_repo,
            symlinks=True,
            ignore=_copy_ignore,
            ignore_dangling_symlinks=True,
        )
        env = _build_pytest_env(work_repo)

        resolved_targets: list[str]
        if test_targets is not None:
            resolved_targets = [str(t) for t in test_targets]
        else:
            resolved_targets = _discover_diff_test_targets(
                work_repo, effective_diff, list(hunks.keys())
            )

        pytest_args = [sys.executable, "-m", "pytest", "-x", "-q"]
        if resolved_targets:
            pytest_args.extend(resolved_targets)

        baseline_timeout = max(timeout_sec * 6.0, 90.0)
        t_base = time.monotonic()
        try:
            baseline = subprocess.run(
                pytest_args,
                cwd=str(work_repo),
                env=env,
                capture_output=True,
                text=True,
                timeout=baseline_timeout,
            )
            baseline_elapsed = time.monotonic() - t_base
            baseline_rc = baseline.returncode
            baseline_out = ((baseline.stdout or "") + "\n" + (baseline.stderr or "")).strip()[-1000:]
        except subprocess.TimeoutExpired:
            baseline_elapsed = time.monotonic() - t_base
            baseline_rc = -1
            baseline_out = "Baseline pytest run timed out."

        effective_timeout = max(timeout_sec, baseline_elapsed * 2.5 + 2.0)

        if baseline_rc != 0:
            return {
                "status": "baseline_tests_failed",
                "passed": False,
                "mutation_score": 0.0,
                "threshold": threshold,
                "total_candidates": total_candidates,
                "pruned_equivalent": pruned_equivalent,
                "viable": len(selected),
                "killed": 0,
                "survived": 0,
                "timeout_killed": 0,
                "survivors": [],
                "test_targets": resolved_targets,
                "baseline_elapsed": round(baseline_elapsed, 4),
                "effective_timeout": round(effective_timeout, 4),
                "baseline_returncode": baseline_rc,
                "baseline_output": baseline_out,
                "opt_tokens": 0.0,
            }

        killed = 0
        survived = 0
        timeout_killed = 0
        survivors: list[dict[str, Any]] = []

        def _run_one_mutant(work_root: Path, mutant: Mutant) -> tuple[str, dict[str, Any] | None]:
            mut_env = _build_pytest_env(work_root)
            target_file = work_root / mutant.file_path
            original_content = target_file.read_text(encoding="utf-8")
            try:
                os.chmod(target_file, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            try:
                target_file.write_text(mutant.mutated_source, encoding="utf-8")
                try:
                    proc = subprocess.run(
                        pytest_args,
                        cwd=str(work_root),
                        env=mut_env,
                        capture_output=True,
                        text=True,
                        timeout=effective_timeout,
                    )
                    if proc.returncode == 0:
                        return (
                            "survived",
                            {
                                "location": f"{mutant.file_path}:{mutant.lineno}",
                                "file": mutant.file_path,
                                "line": mutant.lineno,
                                "operator": mutant.operator,
                                "description": mutant.description,
                            },
                        )
                    return ("killed", None)
                except subprocess.TimeoutExpired:
                    return ("timeout_killed", None)
            finally:
                target_file.write_text(original_content, encoding="utf-8")

        if baseline_elapsed >= 2.0 and len(selected) > 1:
            workers = min(4, len(selected))
            worker_repos: list[Path] = [work_repo]
            for w_idx in range(1, workers):
                w_repo = temp_dir / f"repo_w{w_idx}"
                shutil.copytree(
                    work_repo,
                    w_repo,
                    symlinks=True,
                    ignore=_copy_ignore,
                    ignore_dangling_symlinks=True,
                )
                worker_repos.append(w_repo)
            buckets_m: list[list[Mutant]] = [[] for _ in range(workers)]
            for idx, m in enumerate(selected):
                buckets_m[idx % workers].append(m)

            def _run_bucket(w_repo: Path, items: list[Mutant]) -> list[tuple[str, dict[str, Any] | None]]:
                return [_run_one_mutant(w_repo, m) for m in items]

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run_bucket, worker_repos[i], buckets_m[i]) for i in range(workers)]
                outcomes = [item for fut in futures for item in fut.result()]
        else:
            outcomes = [_run_one_mutant(work_repo, m) for m in selected]

        for outcome, survivor_info in outcomes:
            if outcome == "survived":
                survived += 1
                if survivor_info is not None:
                    survivors.append(survivor_info)
            elif outcome == "timeout_killed":
                killed += 1
                timeout_killed += 1
            else:
                killed += 1

        viable = len(selected)
        mutation_score = round(killed / viable, 4) if viable else 1.0
        passed = mutation_score >= threshold
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "mutation_score": mutation_score,
            "threshold": threshold,
            "total_candidates": total_candidates,
            "pruned_equivalent": pruned_equivalent,
            "viable": viable,
            "killed": killed,
            "survived": survived,
            "timeout_killed": timeout_killed,
            "survivors": survivors,
            "test_targets": resolved_targets,
            "baseline_elapsed": round(baseline_elapsed, 4),
            "effective_timeout": round(effective_timeout, 4),
            "opt_tokens": 0.0,
        }
    finally:
        _rmtree_force(temp_dir)


def _evaluate_legacy_tripwire_3a(test_source: str) -> bool:
    """Mirror Legacy `invoke_opus_reviewer.py` lines 913-955 negative + anti-tautology gate."""
    has_negative_tests = bool(
        re.search(
            r"def test_.*(negative|edge|bad|fail|error|invalid|reject|collision|crash|tautolog|heuristic|fallback|resilience|boundary)",
            test_source,
            re.IGNORECASE,
        )
    )
    stripped = re.sub(r"assert\s+[^\n]+?\s+is\s+not\s+None", "", test_source)
    has_substantive_assertion = bool(
        re.search(
            r"(assertEqual|assertNotEqual|assertAlmostEqual|assertRaises|assertTrue|assertFalse|assertIn|assertNotIn|==|!=|<=|>=|<|>)",
            stripped,
        )
    )
    return has_negative_tests and has_substantive_assertion


def _benchmark_scenarios() -> list[dict[str, str]]:
    """Return 6 realistic Python patch scenarios, each paired with weak vs strong tests."""
    return [
        {
            "name": "rate_limit_check",
            "module": "rate_limit.py",
            "code": (
                "def is_within_limit(count: int, max_allowed: int) -> bool:\n"
                "    if count < 0:\n"
                "        return False\n"
                "    if count <= max_allowed:\n"
                "        return True\n"
                "    return False\n"
            ),
            "weak_test": (
                "from rate_limit import is_within_limit\n\n"
                "def test_within_limit_happy():\n"
                "    assert is_within_limit(5, 10) == True\n\n"
                "def test_negative_over_limit():\n"
                "    assert is_within_limit(50, 10) == False\n"
            ),
            "strong_test": (
                "from rate_limit import is_within_limit\n\n"
                "def test_within_limit_boundaries():\n"
                "    assert is_within_limit(0, 10) == True\n"
                "    assert is_within_limit(10, 10) == True\n\n"
                "def test_negative_boundaries():\n"
                "    assert is_within_limit(-1, 10) == False\n"
                "    assert is_within_limit(11, 10) == False\n"
            ),
        },
        {
            "name": "access_gate",
            "module": "access_gate.py",
            "code": (
                "def can_access(role: str, active: bool, suspended: bool) -> bool:\n"
                "    if role == 'admin' and active and not suspended:\n"
                "        return True\n"
                "    if role == 'editor' and active:\n"
                "        return True\n"
                "    return False\n"
            ),
            "weak_test": (
                "from access_gate import can_access\n\n"
                "def test_admin_access_happy():\n"
                "    assert can_access('admin', True, False) == True\n\n"
                "def test_negative_guest_denied():\n"
                "    assert can_access('guest', False, True) == False\n"
            ),
            "strong_test": (
                "from access_gate import can_access\n\n"
                "def test_admin_and_editor_access():\n"
                "    assert can_access('admin', True, False) == True\n"
                "    assert can_access('editor', True, False) == True\n\n"
                "def test_negative_access_denials():\n"
                "    assert can_access('admin', True, True) == False\n"
                "    assert can_access('admin', False, False) == False\n"
                "    assert can_access('editor', False, False) == False\n"
                "    assert can_access('guest', True, False) == False\n"
            ),
        },
        {
            "name": "discount_calc",
            "module": "discount.py",
            "code": (
                "def final_price(base: int, discount: int, is_vip: bool) -> int:\n"
                "    if base <= 0:\n"
                "        return 0\n"
                "    price = base - discount\n"
                "    if is_vip and price > 10:\n"
                "        price = price - 5\n"
                "    return price\n"
            ),
            "weak_test": (
                "from discount import final_price\n\n"
                "def test_regular_price():\n"
                "    assert final_price(100, 10, False) == 90\n\n"
                "def test_negative_zero_base():\n"
                "    assert final_price(0, 0, False) == 0\n"
            ),
            "strong_test": (
                "from discount import final_price\n\n"
                "def test_regular_and_vip_prices():\n"
                "    assert final_price(100, 10, False) == 90\n"
                "    assert final_price(20, 5, True) == 10\n"
                "    assert final_price(15, 5, True) == 10\n\n"
                "def test_negative_base_values():\n"
                "    assert final_price(0, 5, False) == 0\n"
                "    assert final_price(-5, 10, False) == 0\n"
            ),
        },
        {
            "name": "token_validator",
            "module": "token_validator.py",
            "code": (
                "BLOCKED_ROLES = {'banned', 'revoked'}\n\n"
                "def is_token_allowed(role: str, scopes: list[str], require_mfa: bool) -> bool:\n"
                "    if role in BLOCKED_ROLES:\n"
                "        return False\n"
                "    if 'read' not in scopes:\n"
                "        return False\n"
                "    if require_mfa and 'mfa' not in scopes:\n"
                "        return False\n"
                "    return True\n"
            ),
            "weak_test": (
                "from token_validator import is_token_allowed\n\n"
                "def test_valid_token():\n"
                "    assert is_token_allowed('user', ['read', 'mfa'], False) == True\n\n"
                "def test_negative_missing_read():\n"
                "    assert is_token_allowed('user', [], False) == False\n"
            ),
            "strong_test": (
                "from token_validator import is_token_allowed\n\n"
                "def test_valid_tokens():\n"
                "    assert is_token_allowed('user', ['read'], False) == True\n"
                "    assert is_token_allowed('user', ['read', 'mfa'], True) == True\n\n"
                "def test_negative_token_rejections():\n"
                "    assert is_token_allowed('banned', ['read', 'mfa'], True) == False\n"
                "    assert is_token_allowed('user', ['mfa'], True) == False\n"
                "    assert is_token_allowed('user', ['read'], True) == False\n"
            ),
        },
        {
            "name": "delta_clamp",
            "module": "clamp.py",
            "code": (
                "def signed_clamp(value: int, limit: int, invert: bool) -> int:\n"
                "    if value > limit:\n"
                "        clamped = limit\n"
                "    elif value < -limit:\n"
                "        clamped = -limit\n"
                "    else:\n"
                "        clamped = value\n"
                "    if invert:\n"
                "        return -clamped\n"
                "    return clamped\n"
            ),
            "weak_test": (
                "from clamp import signed_clamp\n\n"
                "def test_clamp_in_range():\n"
                "    assert signed_clamp(3, 10, False) == 3\n\n"
                "def test_negative_over_limit():\n"
                "    assert signed_clamp(20, 10, False) == 10\n"
            ),
            "strong_test": (
                "from clamp import signed_clamp\n\n"
                "def test_clamp_bounds_and_invert():\n"
                "    assert signed_clamp(3, 10, False) == 3\n"
                "    assert signed_clamp(10, 10, False) == 10\n"
                "    assert signed_clamp(10, 10, True) == -10\n\n"
                "def test_negative_clamping_edges():\n"
                "    assert signed_clamp(20, 10, False) == 10\n"
                "    assert signed_clamp(-20, 10, False) == -10\n"
                "    assert signed_clamp(-10, 10, False) == -10\n"
            ),
        },
        {
            "name": "retry_policy",
            "module": "retry_policy.py",
            "code": (
                "def should_retry(status_code: int | None, is_idempotent: bool, attempts: int) -> bool:\n"
                "    if status_code is None:\n"
                "        return False\n"
                "    if attempts >= 3:\n"
                "        return False\n"
                "    if not is_idempotent:\n"
                "        return False\n"
                "    if status_code == 503 or status_code == 429:\n"
                "        return True\n"
                "    return False\n"
            ),
            "weak_test": (
                "from retry_policy import should_retry\n\n"
                "def test_retry_503():\n"
                "    assert should_retry(503, True, 1) == True\n\n"
                "def test_negative_200():\n"
                "    assert should_retry(200, False, 1) == False\n"
            ),
            "strong_test": (
                "from retry_policy import should_retry\n\n"
                "def test_retry_transient_codes():\n"
                "    assert should_retry(503, True, 2) == True\n"
                "    assert should_retry(429, True, 0) == True\n\n"
                "def test_negative_retry_guards():\n"
                "    assert should_retry(None, True, 0) == False\n"
                "    assert should_retry(503, True, 3) == False\n"
                "    assert should_retry(503, False, 1) == False\n"
                "    assert should_retry(200, True, 1) == False\n"
            ),
        },
    ]


def _make_added_file_diff(module_name: str, code: str) -> str:
    """Create a unified diff representing an added/modified Python module."""
    lines = code.splitlines()
    plus_lines = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{module_name} b/{module_name}\n"
        f"--- /dev/null\n"
        f"+++ b/{module_name}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{plus_lines}\n"
    )


def benchmark_mutation_quality(threshold: float = 0.75) -> dict[str, Any]:
    """Execute 12 live mini-repo scenarios comparing Legacy Tripwire 3A vs STING diff mutation."""
    scenarios = _benchmark_scenarios()
    jobs = [
        (scenario, suite_type, test_key)
        for scenario in scenarios
        for suite_type, test_key in (("weak", "weak_test"), ("strong", "strong_test"))
    ]

    with tempfile.TemporaryDirectory(prefix="sting_bench_") as bench_root:
        root = Path(bench_root)

        def _run_case(job: tuple[dict[str, str], str, str]) -> dict[str, Any]:
            scenario, suite_type, test_key = job
            mod_name = scenario["module"]
            diff_text = _make_added_file_diff(mod_name, scenario["code"])
            case_dir = root / f"{scenario['name']}_{suite_type}"
            tests_dir = case_dir / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / mod_name).write_text(scenario["code"], encoding="utf-8")
            test_src = scenario[test_key]
            (tests_dir / f"test_{scenario['name']}.py").write_text(test_src, encoding="utf-8")

            legacy_approved = _evaluate_legacy_tripwire_3a(test_src)
            mut_res = run_mutation_verification(
                case_dir,
                diff_text=diff_text,
                threshold=threshold,
                max_mutants=12,
                timeout_sec=15.0,
            )
            pytest_passed = mut_res["status"] != "baseline_tests_failed"
            return {
                "scenario": scenario["name"],
                "suite_type": suite_type,
                "pytest_passed": pytest_passed,
                "legacy_tripwire_3a_approved": legacy_approved,
                "mutation_score": mut_res["mutation_score"],
                "passed_mutation_gate": mut_res["passed"],
                "viable": mut_res["viable"],
                "killed": mut_res["killed"],
                "survived": mut_res["survived"],
                "survivors": mut_res["survivors"],
            }

        with ThreadPoolExecutor(max_workers=min(12, len(jobs))) as pool:
            cases = list(pool.map(_run_case, jobs))

    weak_cases = [c for c in cases if c["suite_type"] == "weak"]
    strong_cases = [c for c in cases if c["suite_type"] == "strong"]

    legacy_weak_caught = sum(1 for c in weak_cases if not c["legacy_tripwire_3a_approved"])
    legacy_strong_passed = sum(1 for c in strong_cases if c["legacy_tripwire_3a_approved"])
    legacy_false_approvals = sum(1 for c in weak_cases if c["legacy_tripwire_3a_approved"])

    sting_weak_caught = sum(1 for c in weak_cases if not c["passed_mutation_gate"])
    sting_strong_passed = sum(1 for c in strong_cases if c["passed_mutation_gate"])
    sting_false_approvals = sum(1 for c in weak_cases if c["passed_mutation_gate"])

    return {
        "total_cases": len(cases),
        "threshold": threshold,
        "cases": cases,
        "legacy_tripwire_3a": {
            "weak_suite_catch_rate": round(legacy_weak_caught / len(weak_cases), 4),
            "strong_suite_pass_rate": round(legacy_strong_passed / len(strong_cases), 4),
            "false_approval_rate": round(legacy_false_approvals / len(weak_cases), 4),
            "accuracy": round((legacy_weak_caught + legacy_strong_passed) / len(cases), 4),
        },
        "sting_diff_mutation": {
            "weak_suite_catch_rate": round(sting_weak_caught / len(weak_cases), 4),
            "strong_suite_pass_rate": round(sting_strong_passed / len(strong_cases), 4),
            "false_approval_rate": round(sting_false_approvals / len(weak_cases), 4),
            "accuracy": round((sting_weak_caught + sting_strong_passed) / len(cases), 4),
            "mean_weak_mutation_score": round(
                sum(c["mutation_score"] for c in weak_cases) / len(weak_cases), 4
            ),
            "mean_strong_mutation_score": round(
                sum(c["mutation_score"] for c in strong_cases) / len(strong_cases), 4
            ),
            "opt_tokens": 0.0,
        },
        "opt_tokens": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zero-LLM Diff-Scoped AST Mutation Verifier (STING / ExecCritic)."
    )
    parser.add_argument("--repo", default=".", help="Path to target repository.")
    parser.add_argument("--diff-file", help="Path to unified diff file.")
    parser.add_argument("--base-ref", help="Git ref to diff against when --diff-file is omitted.")
    parser.add_argument("--tests", nargs="+", help="Optional pytest target paths.")
    parser.add_argument("--threshold", type=float, default=0.75, help="Minimum mutation score.")
    parser.add_argument("--max-mutants", type=int, default=12, help="Maximum stratified mutants.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-mutant pytest timeout (s).")
    parser.add_argument(
        "--benchmark-quality",
        action="store_true",
        help="Run 12-case weak-vs-strong benchmark against Legacy Tripwire 3A.",
    )
    parser.add_argument("--output", help="Optional path to write verification/benchmark output.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    args = parser.parse_args(argv)

    if args.benchmark_quality:
        report = benchmark_mutation_quality(threshold=args.threshold)
        ok = (
            report["sting_diff_mutation"]["weak_suite_catch_rate"] == 1.0
            and report["sting_diff_mutation"]["strong_suite_pass_rate"] == 1.0
        )
    else:
        diff_text = read_text_resilient(Path(args.diff_file)) if args.diff_file else None
        report = run_mutation_verification(
            repo_dir=args.repo,
            diff_text=diff_text,
            base_ref=args.base_ref,
            test_targets=args.tests,
            threshold=args.threshold,
            max_mutants=args.max_mutants,
            timeout_sec=args.timeout,
        )
        ok = bool(report.get("passed"))

    import json as _json

    if args.json:
        rendered = _json.dumps(report, indent=2)
    else:
        if args.benchmark_quality:
            s = report["sting_diff_mutation"]
            l = report["legacy_tripwire_3a"]
            rendered = (
                f"Benchmark (12 cases) | Legacy Tripwire 3A accuracy={l['accuracy']} "
                f"(false_approval={l['false_approval_rate']}) | STING accuracy={s['accuracy']} "
                f"(weak_catch={s['weak_suite_catch_rate']}, strong_pass={s['strong_suite_pass_rate']}, "
                f"mean_weak={s['mean_weak_mutation_score']}, mean_strong={s['mean_strong_mutation_score']}, "
                f"opt_tokens={s['opt_tokens']})"
            )
        else:
            rendered = (
                f"Status: {report['status']} | Score: {report['mutation_score']} "
                f"(threshold={report['threshold']}, killed={report['killed']}/{report['viable']}, "
                f"survived={report['survived']}, opt_tokens={report['opt_tokens']})"
            )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")

    print(rendered)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
