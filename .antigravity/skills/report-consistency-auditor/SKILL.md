---
name: report-consistency-auditor
description: Audits final reports and metrics against METRIC_REGISTRY.json and raw disk evidence.
---

# Report Consistency Auditor

## Purpose
Adversarially detect and prevent internal and cross-report contradictions, arithmetic discrepancies, and post-hoc criteria redefinitions across long-horizon research reports (Antigravity V4.1 §26).

## Mandatory Audit Responsibilities

### 1. Cross-Document Contradiction Detection (§27)
- Detect conflicting metrics across documents (e.g. a metric reported in a table contradicting the narrative text).
- Detect configuration or constraint discrepancies across reports and `PROGRAM_INVARIANTS.json`.
- Detect deployment claims contradicting program ceiling (e.g. "PRODUCTION READY" vs `RESEARCH` / `STAGING_ONLY`).

### 2. Post-Hoc Criteria Redefinition (§13)
- Catch attempts to move goalposts (e.g. lowering a pre-registered acceptance threshold after observing a lower empirical result).
- Results failing pre-registered criteria must be labeled `FAILED_PRE_REGISTERED_CRITERION`.

### 3. Machine-Checkable Arithmetic Verification (§28)
- Verify rate and frequency calculations: `events_per_unit == total_events / total_units` within tolerance.
- Verify percentages, pass rates, and aggregated totals.

### 4. Factorial Ablation Verification (§37)
- Any claim that an interaction between factors adds value must present complete factorial ablation: Base, Base+X, Base+Y, Base+X+Y, Base+interaction.

