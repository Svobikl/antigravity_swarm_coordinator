#!/usr/bin/env python3
"""Run Semantic Completion Audit for a Mode 5 program.

Usage:
    python .antigravity/scripts/run_semantic_audit.py [--program-dir research_v3/mode5] [--strict-scientific]
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

from semantic.auditor import SemanticCompletionAuditor


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Semantic Completion Audit (Antigravity V4.1)")
    parser.add_argument("--program-dir", type=str, default="research_v3/mode5", help="Path to program directory")
    parser.add_argument("--root", type=str, default=".", help="Root repository directory")
    parser.add_argument("--strict-scientific", action="store_true", help="Enforce 3-auditor research governance")
    args = parser.parse_args()

    p_dir = Path(args.program_dir).resolve()
    r_dir = Path(args.root).resolve()

    auditor = SemanticCompletionAuditor(p_dir, root_dir=r_dir)
    res = auditor.run_semantic_audit(check_research_validity=args.strict_scientific)

    print("=" * 70)
    print(f"SEMANTIC COMPLETION AUDIT: {res.program_id}")
    print("=" * 70)
    print(res.four_axis_header.format_markdown())
    print("\nFindings:")
    for f in res.findings:
        print(f"  - {f}")

    if res.blocking_errors:
        print("\nBlocking Errors:")
        for err in res.blocking_errors:
            print(f"  [BLOCKING] {err}")
        print("\nAudit Verdict: FAIL")
        return 1

    print(f"\nAudit Report emitted: {res.audit_report_path}")
    print("\nAudit Verdict: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
