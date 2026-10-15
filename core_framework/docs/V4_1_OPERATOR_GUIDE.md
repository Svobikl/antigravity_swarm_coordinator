# Antigravity V4.1 Semantic Integrity Operator Guide

## 1. Overview & Motivation

Antigravity V4 established rigorous mechanical completion controls (task graphs, requirement coverage maps, evidence ledgers, state machines, and independent completion audits). However, long-horizon programs can experience **semantic drift**:
- The plan finishes mechanically, but the meaning of original rules drifts during execution.
- Metrics are silently redefined or acceptance thresholds are relaxed post-hoc after observing lower results.
- Evaluation constraints or environment parameters are silently altered mid-program.
- Reports contradict each other while all files technically exist.

**Antigravity V4.1 introduces the Semantic Integrity Control Plane** to guarantee that the program solved the problem under the original rules without moving the goalposts.

---

## 2. The 4-Axis Completion Model (§2)

Any single `PROGRAM_COMPLETE = TRUE` is replaced with four independent axes:

```text
MECHANICAL_COMPLETION:  PASS | IN_PROGRESS | FAIL | BLOCKED | NOT_APPLICABLE
SEMANTIC_INTEGRITY:     PASS | IN_PROGRESS | FAIL | BLOCKED | NOT_APPLICABLE
SCIENTIFIC_VALIDITY:    PASS | PASS_WITH_FINDINGS | FAIL | BLOCKED | NOT_APPLICABLE
FORWARD_VALIDATION:     NOT_STARTED | IN_PROGRESS | PASS | FAIL | NOT_APPLICABLE
DEPLOYMENT_STATUS:      RESEARCH | STAGING_ONLY | FORWARD_SHADOW | HUMAN_APPROVED_PRODUCTION
```

### Prohibited Summaries (§2, §33)
- Never summarize a program with `FORWARD_VALIDATION = IN_PROGRESS` as "100% Validated" or "Production Ready".
- A program may legitimately conclude with:
  ```text
  MECHANICAL_COMPLETION: PASS
  SEMANTIC_INTEGRITY:    PASS
  SCIENTIFIC_VALIDITY:   PASS_WITH_FINDINGS
  FORWARD_VALIDATION:    IN_PROGRESS
  DEPLOYMENT_STATUS:     STAGING_ONLY
  ```

---

## 3. Core Control Plane Files (§3, §6, §14, §16, §17, §29)

1. `PROGRAM_INVARIANTS.json`:
   - Non-negotiable program contracts (safety, scientific, statistical, quality, data, agentic, completion).
   - Immutable except via formal governed override.
2. `PROGRAM_SOURCE_SNAPSHOT.md` & `PROGRAM_SOURCE_HASH`:
   - Verbatim preservation of original user prompt and Master Plan with SHA256 integrity hash.
3. `INVARIANT_OVERRIDES.json`:
   - Append-only register for governed parameter adjustments.
   - `USER_LOCKED` invariants require explicit human approval (`user_approved: true`).
4. `METRIC_REGISTRY.json`:
   - Versioned metric definitions, formulas, units, frequency, and scaling factors.
   - In-place formula modification is prohibited; formula changes require version bumps (e.g. `metric_v2`).
5. `EXECUTION_CONTRACTS.json`:
   - Versioned environment and evaluation assumption contracts.
6. `DATA_CONTRACTS.json`:
   - Dataset boundary definitions with causal availability and hashes.
7. `CLAIM_REGISTRY.json`:
   - Machine-readable registry of high-impact claims with arithmetic verification and supersession lineage.
8. `PROGRAM_MANIFEST.json`:
   - Comprehensive program seal recording SHA256 hashes of all control plane files.

---

## 4. Multi-Auditor Governance Architecture (§20–25)

A Mode 5 program requires multi-auditor independent closure:

1. **`completion-auditor` (Mechanical):**
   - Verifies 100% of leaf tasks in `TASK_GRAPH.json` are COMPLETED.
   - Verifies all evidence paths in `REQUIREMENT_COVERAGE.csv` exist and are non-empty.
2. **`semantic-completion-auditor` (Semantic):**
   - Verifies invariants were preserved; verifies source snapshot hash.
   - Scans reports for contradictions, post-hoc criteria changes, and arithmetic errors.
3. **`research-validity-auditor` (Scientific):**
   - Verifies zero outer OOS data leakage.
   - Verifies factorial ablation for interaction claims.
   - Verifies absence of sample duplication or evaluation bugs.

Both `completion-auditor` and `semantic-completion-auditor` must sign `COMPLETION_LEDGER.md` with `PASS` before `VERIFIED_COMPLETE` can be declared.

---

## 5. How to Debug a Blocked Completion

If `validate_program_state.py` or `run_semantic_audit.py` fails:

### Case 1: Invariant Drift (`INVARIANT_DRIFT_BLOCKING`)
- **Cause:** Code, config, or report modified a locked parameter defined in `PROGRAM_INVARIANTS.json`.
- **Fix:** Either revert the execution to the canonical invariant value, OR register a governed override in `INVARIANT_OVERRIDES.json` with documented evidence, affected tasks, and actor. If the invariant is `USER_LOCKED`, obtain human approval.

### Case 2: Post-Hoc Criteria Relaxation (`POST_HOC_CRITERIA_CHANGE`)
- **Cause:** A pre-registered acceptance threshold was lowered in the final report to claim PASS.
- **Fix:** Report must state the truth: the pre-registered criterion was NOT met (`FAILED_PRE_REGISTERED_CRITERION`). It may be reported as `PASS_WITH_FINDINGS` under exploratory criteria, but cannot claim clean PASS.

### Case 3: Arithmetic Contradiction (`ARITHMETIC_ERROR`)
- **Cause:** Event count and duration do not match the reported rate (`events / duration != reported_rate`).
- **Fix:** Recalculate and synchronize exact figures across tables and narrative text.

### Case 4: Deployment Mismatch (`DEPLOYMENT_MISMATCH`)
- **Cause:** Document claims "PRODUCTION READY" or "100% VALIDATED" while lifecycle ceiling is `RESEARCH` or `STAGING_ONLY`.
- **Fix:** Remove premature production claims; accurately state maturity level and remaining validation requirements.
