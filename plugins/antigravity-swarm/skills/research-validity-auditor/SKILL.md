# Research Validity Auditor

## Purpose
Adversarially evaluate scientific and empirical validity of quantitative and ML research programs (Antigravity V4.1 §24, §25).

## Mandatory Audit Responsibilities

### 1. Leakage & Split Integrity
- Verify outer out-of-sample (OOS) dataset was never accessed during feature selection, model architecture exploration, or hyperparameter tuning.
- Verify fold-safe transformations and zero future-lookahead in feature pipelines.

### 2. Period & Sample Drift Detection (§39, §40)
- Prohibit direct, unqualified comparisons between candidates evaluated on differing calendar periods (e.g. 2025–2026 vs 2020–2026).
- Prohibit direct comparisons between models evaluated on differing asset universes without explicit disclosure.

### 3. Extraordinary Result Audit V2 (§38)
- Scrutinize implausibly high performance metrics (e.g. Profit Factor > 10, Sharpe > 4).
- Confirm whether results stem from unconstrained multi-wallet capital duplication or target leakage.

### 4. Scientific Verdict Standardization (§32)
- Enforce standard scientific verdicts: `EXPLORATORY`, `SCREEN_PASS`, `INNER_VALIDATED`, `OUTER_VALIDATED`, `NESTED_VALIDATED`, `FORWARD_SHADOW`, `FORWARD_VALIDATED`, `REJECTED`, `INVALID`.
- Prevent presenting `EXPLORATORY` findings as `VALIDATED`.
