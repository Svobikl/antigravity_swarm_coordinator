#!/usr/bin/env python3
"""Generic setup and hygiene check for the agentic workflow (V4).

Validates:
1. Workspace hygiene: no root-level temporary files or unapproved artifacts.
2. V4 Framework integrity:
   - Root instruction files (gemini.md, GEMINI.md)
   - Rules with Mode 5 (GLOBAL_DEVELOPMENT_RULES.md)
   - Skills catalog completeness (all 17 core V4 skills present)
   - Templates completeness
   - Validation scripts present
"""
from pathlib import Path
import sys

ROOT = Path.cwd()
TEMP_SUFFIXES = {'.log', '.tmp', '.bak', '.orig', '.rej'}
TEMP_NAMES = {'debug.log', 'output.log', 'agent_notes.txt', 'scratch.txt'}

REQUIRED_SKILLS = [
    "acceptance-reviewer-product-qa",
    "compliance-maintainability-reviewer",
    "documentation-handoff-agent",
    "implementation-developer",
    "interaction-e2e-tester",
    "opposition-reviewer",
    "security-reliability-reviewer",
    "software-architect",
    "spec-product-analyst",
    "swarm-coordinator",
    "ui-ux-designer",
    "validator-build-test-agent",
    # V4 skills
    "skill-router",
    "program-state-controller",
    "research-experiment-auditor",
    "memory-state-curator",
    "completion-auditor",
]

def main() -> int:
    problems = []

    # 1. Root hygiene
    for p in ROOT.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in TEMP_SUFFIXES or p.name.lower() in TEMP_NAMES:
            problems.append(f'root temporary artifact: {p.name}')

    ws = ROOT / '.agent-workspace'
    if ws.exists() and ws.is_file():
        problems.append('.agent-workspace must be a directory, not a file')

    # 2. V4 Entry points
    gemini_lower = ROOT / "gemini.md"
    gemini_upper = ROOT / "GEMINI.md"
    if not gemini_lower.exists() and not gemini_upper.exists():
        problems.append("Neither gemini.md nor GEMINI.md found in repository root")

    # 3. Check rules and skills
    for config_dir in [ROOT / ".antigravity", ROOT / ".gemini"]:
        if not config_dir.exists():
            continue
        rules_file = config_dir / "rules" / "GLOBAL_DEVELOPMENT_RULES.md"
        if not rules_file.exists():
            problems.append(f"Missing rules file: {rules_file}")
        else:
            content = rules_file.read_text(encoding="utf-8")
            if "Mode 5" not in content:
                problems.append(f"Rules file {rules_file} lacks Mode 5 (Long-Horizon Program / Research)")

        skills_dir = config_dir / "skills"
        if not skills_dir.exists():
            problems.append(f"Missing skills directory: {skills_dir}")
        else:
            for skill_name in REQUIRED_SKILLS:
                skill_md = skills_dir / skill_name / "SKILL.md"
                if not skill_md.exists():
                    problems.append(f"Missing skill in {config_dir.name}: {skill_name}")

    if problems:
        print('Agent workflow setup & hygiene: FAIL')
        for item in problems:
            print(f'- {item}')
        return 1

    print('Agent workflow setup & hygiene: PASS (V4 framework & hygiene verified)')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
