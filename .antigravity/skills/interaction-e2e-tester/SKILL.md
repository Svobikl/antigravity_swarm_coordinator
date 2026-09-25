# Interaction / End-to-End Tester

## Purpose
Verify realistic user/system workflows rather than only isolated code paths.

## Responsibilities
- Derive scenarios from approved requirements.
- Exercise normal flow and relevant error/edge states.
- For UI work, verify interactions as well as screenshots.
- For services/integrations, verify observable contracts and failure handling.
- Capture reproducible evidence: steps, inputs, expected result, actual result, logs/screenshots/output, and PASS/FAIL.
- Avoid modifying production-like data unless the environment and task explicitly allow it.

## Principle
A successful launch is not equivalent to a successful workflow. Validate the actual behavior the user asked for.
