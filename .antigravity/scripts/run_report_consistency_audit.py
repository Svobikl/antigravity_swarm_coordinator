#!/usr/bin/env python3
"""Run Report Consistency & Contradiction Audit.

Usage:
    python .antigravity/scripts/run_report_consistency_audit.py [--program-dir research_v3/mode5]
"""
import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ANTIGRAVITY_DIR = SCRIPT_DIR.parent
REPO_ROOT = ANTIGRAVITY_DIR.parent
if str(ANTIGRAVITY_DIR) not in sys.path:
    sys.path.insert(0, str(ANTIGRAVITY_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from semantic.consistency import ReportConsistencyAuditor


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Report Consistency Audit (Antigravity V4.1)")
    parser.add_argument("--program-dir", type=str, default="research_v3/mode5", help="Path to program directory")
    parser.add_argument("--report", type=str, default=None, help="Specific report file to check")
    args = parser.parse_args()

    p_dir = Path(args.program_dir).resolve()
    auditor = ReportConsistencyAuditor(p_dir)

    print("=" * 70)
    print("REPORT CONSISTENCY & CONTRADICTION AUDIT (V4.1)")
    print("=" * 70)

    if args.report:
        reports = [Path(args.report).resolve()]
    else:
        reports = list(p_dir.glob("*.md"))
        rep_dir = REPO_ROOT / "research_v3/reports"
        if rep_dir.exists():
            reports.extend(rep_dir.glob("*.md"))

    print(f"Scanning {len(reports)} markdown report files...\n")
    has_blocking = False
    for rep in reports:
        findings = auditor.audit_report_file(rep)
        if findings:
            print(f"Report: {rep.name}")
            for f in findings:
                tag = "[BLOCKING FAIL]" if f.severity == "BLOCKING_FAIL" else "[WARNING]"
                if f.severity == "BLOCKING_FAIL":
                    has_blocking = True
                print(f"  {tag} [{f.finding_type}] {f.message}")
                if f.context_snippet:
                    print(f"    Snippet: {f.context_snippet}")
            print()

    if has_blocking:
        print("REPORT CONSISTENCY AUDIT: FAIL (Blocking contradictions detected)")
        return 1

    print("REPORT CONSISTENCY AUDIT: PASS (0 blocking contradictions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
