#!/usr/bin/env python3
"""Long-Horizon Program State, Task Graph, and Semantic Integrity Validator (V4.1).

Validates:
1. TASK_GRAPH.json: structural validity, DAG integrity, parent-child status mechanics.
2. REQUIREMENT_COVERAGE.csv: full coverage, no dropped rows, valid evidence links, intent & invariant mapping.
3. Mechanical Completion: rejects any 100% / COMPLETED claim unless all leaves
   are closed, evidence files exist, and completion audit is recorded.
4. Semantic Integrity (V4.1):
   - Invariant preservation & governed override verification (PROGRAM_INVARIANTS.json, INVARIANT_OVERRIDES.json).
   - Source snapshot SHA256 integrity (PROGRAM_SOURCE_SNAPSHOT.md, PROGRAM_SOURCE_HASH).
   - Metric, execution, and data contract registries.
   - Claim registry immutability and arithmetic verification.
   - Cross-report consistency and contradiction detection.
   - Dual/Three-auditor completion sign-off (completion-auditor + semantic-completion-auditor).
   - 4-Axis Completion Model reporting.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set

# Ensure .antigravity is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from .antigravity.semantic.schema import FourAxisReportHeader, FourAxisStatus, DeploymentStatus
    from .antigravity.semantic.invariants import InvariantManager
    from .antigravity.semantic.snapshot import SourceSnapshotManager
    from .antigravity.semantic.claims import ClaimRegistryManager
    from .antigravity.semantic.consistency import ReportConsistencyAuditor
    from .antigravity.semantic.auditor import SemanticCompletionAuditor
except (ImportError, ValueError):
    # Direct import fallback if running inside repository root
    sys.path.insert(0, str(SCRIPT_DIR.parent))
    from semantic.schema import FourAxisReportHeader, FourAxisStatus, DeploymentStatus
    from semantic.invariants import InvariantManager
    from semantic.snapshot import SourceSnapshotManager
    from semantic.claims import ClaimRegistryManager
    from semantic.consistency import ReportConsistencyAuditor
    from semantic.auditor import SemanticCompletionAuditor

VALID_TASK_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETED", "ABANDONED"}
VALID_COVERAGE_STATUSES = {"PLANNED", "IN_PROGRESS", "VERIFIED_PASS", "VERIFIED_FAIL", "DEFERRED", "ABANDONED"}
REQUIRED_CSV_COLUMNS = {
    "req_id", "parent_id", "category", "description",
    "source_reference", "status", "verification_type",
    "evidence_path", "completion_date", "notes"
}


def validate_task_graph(graph_path: Path, root_dir: Path) -> list[str]:
    errors = []
    if not graph_path.exists():
        return [f"Task graph file not found: {graph_path}"]

    try:
        with graph_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [f"Malformed JSON in task graph {graph_path}: {e}"]

    if not isinstance(data, dict):
        return [f"Task graph root must be a JSON object: {graph_path}"]

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return [f"Task graph must contain a 'tasks' list: {graph_path}"]

    task_map: Dict[str, Dict[str, Any]] = {}
    child_map: Dict[str, List[str]] = {}

    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task index {idx} is not a JSON object")
            continue
        task_id = task.get("id")
        if not task_id:
            errors.append(f"Task index {idx} missing required 'id'")
            continue
        if task_id in task_map:
            errors.append(f"Duplicate task id: '{task_id}'")
        task_map[task_id] = task

        status = task.get("status")
        if status not in VALID_TASK_STATUSES:
            errors.append(f"Task '{task_id}' has invalid status: '{status}'. Must be one of {VALID_TASK_STATUSES}")

        parent_id = task.get("parent_id")
        if parent_id:
            child_map.setdefault(parent_id, []).append(task_id)

    # Validate parent-child status mechanics
    for parent_id, children_ids in child_map.items():
        if parent_id not in task_map:
            errors.append(f"Child tasks reference non-existent parent_id: '{parent_id}'")
            continue

        parent = task_map[parent_id]
        parent_status = parent.get("status")
        children = [task_map[cid] for cid in children_ids if cid in task_map]
        child_statuses = {c.get("status") for c in children}

        # Parent cannot be COMPLETED unless ALL children are COMPLETED or ABANDONED
        if parent_status == "COMPLETED":
            unfinished = [c.get("id") for c in children if c.get("status") not in {"COMPLETED", "ABANDONED"}]
            if unfinished:
                errors.append(
                    f"Parent task '{parent_id}' is marked COMPLETED, but children are unfinished: {unfinished}"
                )

        # If any child is IN_PROGRESS, parent cannot be NOT_STARTED
        if "IN_PROGRESS" in child_statuses and parent_status == "NOT_STARTED":
            errors.append(f"Parent task '{parent_id}' is marked NOT_STARTED while child tasks are IN_PROGRESS")

    # Cycle detection
    visited: Set[str] = set()
    visiting: Set[str] = set()

    def check_cycle(node_id: str) -> bool:
        visiting.add(node_id)
        task = task_map.get(node_id, {})
        deps = task.get("dependencies", [])
        for dep in deps:
            if dep in visiting:
                errors.append(f"Cyclic dependency detected: '{node_id}' -> '{dep}'")
                return False
            if dep not in visited and dep in task_map:
                if not check_cycle(dep):
                    return False
        visiting.remove(node_id)
        visited.add(node_id)
        return True

    for tid in task_map:
        if tid not in visited:
            check_cycle(tid)

    # Check overall program completion consistency
    prog_status = data.get("status")
    if prog_status == "COMPLETED":
        uncompleted_tasks = [
            t.get("id") for t in tasks
            if t.get("status") not in {"COMPLETED", "ABANDONED"}
        ]
        if uncompleted_tasks:
            errors.append(
                f"Program status is 'COMPLETED', but task graph has unclosed tasks: {uncompleted_tasks}"
            )

    return errors


def validate_requirement_coverage(csv_path: Path, root_dir: Path, check_evidence: bool = True) -> list[str]:
    errors = []
    if not csv_path.exists():
        return [f"Requirement coverage file not found: {csv_path}"]

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            missing_cols = REQUIRED_CSV_COLUMNS - headers
            if missing_cols:
                return [f"Coverage CSV {csv_path} missing required columns: {sorted(missing_cols)}"]

            rows = list(reader)
    except Exception as e:
        return [f"Error reading coverage CSV {csv_path}: {e}"]

    if not rows:
        return [f"Coverage CSV {csv_path} contains no requirement rows"]

    seen_req_ids: Set[str] = set()
    for row_idx, row in enumerate(rows, start=2):
        req_id = row.get("req_id", "").strip()
        if not req_id:
            errors.append(f"Row {row_idx} missing req_id")
            continue
        if req_id in seen_req_ids:
            errors.append(f"Duplicate req_id in coverage CSV: '{req_id}'")
        seen_req_ids.add(req_id)

        status = row.get("status", "").strip()
        if status not in VALID_COVERAGE_STATUSES:
            errors.append(f"Req '{req_id}' has invalid status '{status}'. Must be one of {VALID_COVERAGE_STATUSES}")

        evidence_path = row.get("evidence_path", "").strip()
        if status == "VERIFIED_PASS":
            if not evidence_path:
                errors.append(f"Req '{req_id}' is marked VERIFIED_PASS but has no evidence_path")
            elif check_evidence:
                ev_full = root_dir / evidence_path if not Path(evidence_path).is_absolute() else Path(evidence_path)
                if not ev_full.exists():
                    errors.append(f"Req '{req_id}' evidence path does not exist on disk: {evidence_path}")
                elif ev_full.is_file() and ev_full.stat().st_size == 0:
                    errors.append(f"Req '{req_id}' evidence file is empty (0 bytes): {evidence_path}")

        if status in {"DEFERRED", "ABANDONED"}:
            notes = row.get("notes", "").strip()
            if "DECISION-" not in notes and "ADR-" not in notes and "DECISION_LEDGER" not in notes:
                errors.append(f"Req '{req_id}' is '{status}' without reference to DECISION_LEDGER in notes")

    return errors


def validate_completion_audit(program_dir: Path) -> list[str]:
    errors = []
    completion_ledger = program_dir / "COMPLETION_LEDGER.md"
    if not completion_ledger.exists():
        alt_ledger = program_dir.parent / "COMPLETION_LEDGER.md"
        if alt_ledger.exists():
            completion_ledger = alt_ledger
        else:
            return [f"COMPLETION_LEDGER.md missing under {program_dir}"]

    content = completion_ledger.read_text(encoding="utf-8")
    if "COMPLETION_AUDITOR" not in content and "completion-auditor" not in content.lower():
        errors.append("COMPLETION_LEDGER.md missing formal sign-off from completion-auditor")
    return errors


def validate_invariants(program_dir: Path) -> list[str]:
    errors = []
    inv_mgr = InvariantManager(program_dir)
    if not inv_mgr.invariants_path.exists():
        return [f"PROGRAM_INVARIANTS.json missing under {program_dir}"]

    try:
        invs = inv_mgr.load_invariants()
    except Exception as e:
        return [f"Malformed PROGRAM_INVARIANTS.json: {e}"]

    # Check user-locked invariants in overrides
    for ov in inv_mgr.overrides:
        inv = invs.get_invariant(ov.invariant_id)
        if inv and inv.user_locked and not ov.user_approved:
            errors.append(
                f"Unauthorized override on USER_LOCKED invariant '{ov.invariant_id}': human approval required."
            )
    return errors


def validate_claims(program_dir: Path) -> list[str]:
    errors = []
    claim_path = program_dir / "CLAIM_REGISTRY.json"
    if not claim_path.exists():
        return [f"CLAIM_REGISTRY.json missing under {program_dir}"]

    claim_mgr = ClaimRegistryManager(program_dir)
    for c in claim_mgr.claims.values():
        if c.duration_years > 0 and c.trade_count > 0:
            exp = c.trade_count / c.duration_years
            if abs(c.trades_per_year - exp) > 1.5:
                errors.append(
                    f"Arithmetic error in claim '{c.claim_id}': {c.trade_count} trades / {c.duration_years:.2f} yrs != {c.trades_per_year} tr/yr"
                )
    return errors


def validate_report_consistency(program_dir: Path, root_dir: Path) -> list[str]:
    errors = []
    auditor = ReportConsistencyAuditor(program_dir)
    discovered: Set[Path] = set(program_dir.glob("*.md"))
    graph_file = program_dir / "TASK_GRAPH.json"
    if graph_file.exists():
        try:
            g_data = json.loads(graph_file.read_text(encoding="utf-8"))
            for t in g_data.get("tasks", []):
                for link in t.get("evidence_links", []):
                    if str(link).endswith(".md"):
                        p = root_dir / str(link)
                        if p.exists() and p.is_file():
                            discovered.add(p)
        except Exception:
            pass
    # Exclude raw immutable source plans and generated meta-audit reports
    discovered.discard(program_dir / "SOURCE_PLAN.md")
    discovered.discard(program_dir / "PROGRAM_SOURCE_SNAPSHOT.md")
    discovered.discard(program_dir / "SEMANTIC_AUDIT_REPORT.md")
    discovered.discard(program_dir / "COMPLETION_AUDIT_REPORT.md")
    discovered.discard(program_dir / "V4_FRAMEWORK_ACCEPTANCE_REPORT.md")
    discovered.discard(program_dir / "V4_1_SEMANTIC_INTEGRITY_ACCEPTANCE_REPORT.md")
    discovered.discard(program_dir / "V4_1_REAL_PROGRAM_ACCEPTANCE_LOG.md")

    reports = sorted(list(discovered))
    for rep in reports:
        findings = auditor.audit_report_file(rep)
        for f in findings:
            if f.severity == "BLOCKING_FAIL":
                errors.append(f"Contradiction in {rep.name}: [{f.finding_type}] {f.message}")
    return errors


def validate_semantic_integrity(program_dir: Path, root_dir: Path, strict_scientific: bool = False) -> tuple[list[str], FourAxisReportHeader]:
    errors = []
    auditor = SemanticCompletionAuditor(program_dir, root_dir=root_dir)
    res = auditor.run_semantic_audit(check_research_validity=strict_scientific)

    if not res.is_fully_clean:
        errors.extend(res.blocking_errors)

    # Check Dual-Auditor Sign-off in COMPLETION_LEDGER.md (§23)
    comp_ledger = program_dir / "COMPLETION_LEDGER.md"
    if comp_ledger.exists():
        content = comp_ledger.read_text(encoding="utf-8")
        if "semantic-completion-auditor" not in content.lower():
            errors.append("COMPLETION_LEDGER.md missing formal sign-off from semantic-completion-auditor (§23)")
        if strict_scientific and "research-validity-auditor" not in content.lower():
            errors.append("COMPLETION_LEDGER.md missing formal sign-off from research-validity-auditor (§25)")

    return errors, res.four_axis_header


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Long-Horizon Program State and Semantic Integrity (V4.1)")
    parser.add_argument("--root", type=str, default=".", help="Root repository directory")
    parser.add_argument("--graph", type=str, default=None, help="Path to TASK_GRAPH.json")
    parser.add_argument("--coverage", type=str, default=None, help="Path to REQUIREMENT_COVERAGE.csv")
    parser.add_argument("--program-dir", type=str, default=None, help="Program directory containing state artifacts")
    parser.add_argument("--strict-completion", action="store_true", help="Enforce 100 percent completion audit checks")
    parser.add_argument("--check-invariants", action="store_true", help="Validate invariants and governed overrides")
    parser.add_argument("--check-claims", action="store_true", help="Validate claim registry and arithmetic consistency")
    parser.add_argument("--check-report-consistency", action="store_true", help="Scan reports for internal contradictions")
    parser.add_argument("--check-semantic-integrity", action="store_true", help="Run full semantic integrity audit")
    parser.add_argument("--strict-scientific-completion", action="store_true", help="Enforce 3-auditor research gate")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    all_errors: list[str] = []

    # Auto-discover if not provided
    graph_path = Path(args.graph).resolve() if args.graph else None
    coverage_path = Path(args.coverage).resolve() if args.coverage else None
    program_dir = Path(args.program_dir).resolve() if args.program_dir else None

    if not graph_path:
        candidates = (
            list(root_dir.glob("research_v3/mode5/TASK_GRAPH.json")) +
            list(root_dir.glob("docs/agentic/**/TASK_GRAPH.json")) +
            list(root_dir.glob(".agent-workspace/**/TASK_GRAPH.json"))
        )
        if candidates:
            graph_path = candidates[0]

    if not coverage_path:
        candidates = (
            list(root_dir.glob("research_v3/mode5/REQUIREMENT_COVERAGE.csv")) +
            list(root_dir.glob("docs/agentic/**/REQUIREMENT_COVERAGE.csv"))
        )
        if candidates:
            coverage_path = candidates[0]

    if not program_dir and graph_path:
        program_dir = graph_path.parent

    # 1. Validate graph if found
    if graph_path and graph_path.exists():
        print(f"Validating task graph: {graph_path.relative_to(root_dir) if graph_path.is_relative_to(root_dir) else graph_path}")
        graph_errs = validate_task_graph(graph_path, root_dir)
        all_errors.extend(graph_errs)
    elif args.graph:
        all_errors.append(f"Specified task graph not found: {args.graph}")

    # 2. Validate coverage if found
    if coverage_path and coverage_path.exists():
        print(f"Validating coverage: {coverage_path.relative_to(root_dir) if coverage_path.is_relative_to(root_dir) else coverage_path}")
        cov_errs = validate_requirement_coverage(coverage_path, root_dir)
        all_errors.extend(cov_errs)
    elif args.coverage:
        all_errors.append(f"Specified coverage CSV not found: {args.coverage}")

    # 3. Validate strict completion if requested
    if args.strict_completion and program_dir:
        print(f"Validating program completion audit in: {program_dir}")
        audit_errs = validate_completion_audit(program_dir)
        all_errors.extend(audit_errs)

    # 4. Validate invariants if requested
    if (args.check_invariants or args.check_semantic_integrity) and program_dir:
        print(f"Validating invariants in: {program_dir}")
        inv_errs = validate_invariants(program_dir)
        all_errors.extend(inv_errs)

    # 5. Validate claims if requested
    if (args.check_claims or args.check_semantic_integrity) and program_dir:
        print(f"Validating claims in: {program_dir}")
        claim_errs = validate_claims(program_dir)
        all_errors.extend(claim_errs)

    # 6. Validate report consistency if requested
    if (args.check_report_consistency or args.check_semantic_integrity) and program_dir:
        print(f"Validating report consistency across reports in: {program_dir}")
        cons_errs = validate_report_consistency(program_dir, root_dir)
        all_errors.extend(cons_errs)

    # 7. Validate full semantic integrity if requested
    four_axis_header = None
    if (args.check_semantic_integrity or args.strict_scientific_completion) and program_dir:
        print(f"Executing Semantic Integrity Audit in: {program_dir}")
        sem_errs, four_axis_header = validate_semantic_integrity(
            program_dir, root_dir, strict_scientific=args.strict_scientific_completion
        )
        all_errors.extend(sem_errs)

    if four_axis_header:
        print("\n" + "=" * 50)
        print("ANTIGRAVITY V4.1 COMPLETION STATUS:")
        print(four_axis_header.format_markdown())
        print("=" * 50)

    if all_errors:
        print("\nProgram State & Semantic Validation: FAIL")
        for err in all_errors:
            print(f"  [ERROR] {err}")
        return 1

    print("\nProgram State & Semantic Validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
