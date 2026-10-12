# Semantic Completion Auditor

## Purpose
Perform independent semantic verification before program closure (Antigravity V4.1). Answers: "Did the completed work still satisfy the original scientific, economic, and business intent under the original rules?"

## Mandatory Audit Responsibilities

### 1. Dual-Auditor Completion Gate (§20, §23)
- Operates independently from `completion-auditor`.
- Mechanical closure alone is insufficient: `VERIFIED_COMPLETE` requires PASS from both mechanical and semantic auditors.

### 2. 4-Axis Completion Evaluation (§2)
- Evaluates:
  * `MECHANICAL_COMPLETION`: Were all tasks and files completed?
  * `SEMANTIC_INTEGRITY`: Were program invariants and original intent preserved?
  * `SCIENTIFIC_VALIDITY`: Do conclusions follow from valid, uncompromised empirical evidence?
  * `FORWARD_VALIDATION`: Has the system survived untouched forward paper data?

### 3. Registry Auditing
- Verify `PROGRAM_SOURCE_SNAPSHOT.md` matches `PROGRAM_SOURCE_HASH`.
- Verify `METRIC_REGISTRY.json` formulas and versioning.
- Verify `EXECUTION_CONTRACTS.json` and `DATA_CONTRACTS.json`.
- Verify `CLAIM_REGISTRY.json` immutability, arithmetic, and supersession.

### 4. Semantic Reporting Standard (§34)
- Enforce the mandatory 4-axis markdown header on all final reports.
- Ban ambiguous summaries like "100% Validated" or "Production Ready".
- Emit `SEMANTIC_AUDIT_REPORT.md` and sign `COMPLETION_LEDGER.md`.
