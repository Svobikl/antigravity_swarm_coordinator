# Invariant Auditor

## Purpose
Enforce non-negotiable program invariants and prevent silent contract drift across long-horizon programs (Antigravity V4.1).

## Mandatory Audit Responsibilities

### 1. Canonical Invariant Verification
- Ingest `PROGRAM_INVARIANTS.json` and compare against active code, configurations, execution parameters, and reported metrics.
- Verify that every parameter (economic costs, statistical thresholds, safety constraints, data causality, skill limits) matches canonical values.

### 2. Drift Classification
- **Hard Drift:** Unauthorized modification of canonical parameters (e.g. 38 bps -> 34 bps, DSR 0.95 -> 0.80). Automatically blocks completion (`INVARIANT_DRIFT_BLOCKING`).
- **Soft Drift:** Legitimate empirical exploration. Allowed only if explicitly designated as an experimental alternative, while the canonical baseline remains reported and evaluated.

### 3. Governed Override Governance
- Verify that every parameter change references a formal entry in `INVARIANT_OVERRIDES.json`.
- Reject any autonomous change to `USER_LOCKED` invariants (e.g. live capital permission, human-locked significance thresholds) unless `user_approved: true` is verified.

### 4. Continuous Invariant Gating
- Execute before major campaign transitions, candidate promotions, and final reports.
- Fails immediately if unauthorized drift is detected.
