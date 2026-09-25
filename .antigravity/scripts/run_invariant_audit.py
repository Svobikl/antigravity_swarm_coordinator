#!/usr/bin/env python3
"""Run Invariant Audit for a Mode 5 program.

Usage:
    python .antigravity/scripts/run_invariant_audit.py [--program-dir research_v3/mode5]
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

from semantic.invariants import InvariantManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Invariant Audit (Antigravity V4.1)")
    parser.add_argument("--program-dir", type=str, default="research_v3/mode5", help="Path to program directory")
    args = parser.parse_args()

    p_dir = Path(args.program_dir).resolve()
    mgr = InvariantManager(p_dir)
    if not mgr.invariants_path.exists():
        print(f"Error: {mgr.invariants_path} does not exist.")
        return 1

    invs = mgr.load_invariants()
    print("=" * 60)
    print(f"INVARIANT AUDIT: {invs.program_id} (V4.1 Semantic Integrity)")
    print("=" * 60)
    print(f"Version:      {invs.version}")
    print(f"Created At:   {invs.created_at}")
    print(f"Source Hash:  {invs.source_hash[:16]}...")
    print(f"Active Overrides: {len(mgr.overrides)}")

    has_error = False
    for cat, items in invs.invariants.items():
        print(f"\n[{cat.upper()}]")
        for k, inv_def in items.items():
            eff_val, active_ov = mgr.get_effective_value(f"{cat}.{k}")
            ov_str = f" (OVERRIDE: {active_ov.override_id})" if active_ov else ""
            lock_str = " [USER_LOCKED]" if inv_def.user_locked else ""
            print(f"  - {k:<36}: {eff_val}{ov_str}{lock_str}")

            if active_ov and inv_def.user_locked and not active_ov.user_approved:
                print(f"    [FAIL] User-locked invariant was overridden without human approval!")
                has_error = True

    if has_error:
        print("\nINVARIANT AUDIT: FAIL")
        return 1
    print("\nINVARIANT AUDIT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
