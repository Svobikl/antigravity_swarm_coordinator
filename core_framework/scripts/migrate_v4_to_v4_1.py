#!/usr/bin/env python3
"""CLI Script to Migrate a V4 workspace to Antigravity V4.1 Semantic Integrity.

Usage:
    python .antigravity/scripts/migrate_v4_to_v4_1.py [--program-dir research_v3/mode5] [--program-id FREQAI_V3_5_MODE5]
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

from semantic.migration import upgrade_v4_workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate V4 workspace to V4.1 Semantic Integrity")
    parser.add_argument("--program-dir", type=str, default="research_v3/mode5", help="Path to program directory")
    parser.add_argument("--program-id", type=str, default="FREQAI_V3_5_MODE5", help="Program identifier")
    args = parser.parse_args()

    p_dir = Path(args.program_dir).resolve()
    res = upgrade_v4_workspace(p_dir, root_dir=REPO_ROOT, program_id=args.program_id)
    print(f"\nUpgraded {len(res['upgraded_files'])} artifacts successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
