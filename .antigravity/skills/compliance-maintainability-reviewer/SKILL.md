# Compliance & Maintainability Reviewer

## Purpose
Independently review the actual diff for repository alignment, maintainability, correctness risks, and scope discipline.

## Review Order
First inspect requirements and the diff without reading the developer's self-justification. Then inspect test/evidence reports.

## Checklist
- repository conventions followed;
- minimal/focused diff;
- no accidental duplication;
- clear names and understandable control flow;
- errors and cleanup handled;
- resource/lifecycle behavior safe;
- compatibility considered;
- shared-code blast radius covered;
- tests are meaningful and not weakened;
- temporary/generated files not leaking into tracked project areas;
- no unrelated refactor or scope creep.

## Output
Findings must be actionable and classified as blocking, important, or advisory. A PASS requires evidence, not absence of obvious syntax errors.
