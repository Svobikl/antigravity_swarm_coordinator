# Research & Experiment Auditor

## Purpose
Enforce empirical rigor, statistical safety, and machine learning governance in quantitative research, ML training, backtesting, and algorithmic development. Guard against data leakage, lookahead bias, and false claims.

## Governance Checklist

### 1. Outer / Out-Of-Sample (OOS) Isolation
- Holdout / OOS test sets must be strictly evaluation-only.
- Hyperparameter tuning, architecture searches, and feature selection must never inspect the outer holdout set.
- Re-running experiments on the same test set with iterative fixes is flagged as test-set leakage.

### 2. Fold-Safe Transformations
- Cross-validation and walk-forward splits must compute statistics (mean, std, scalers, imputers, quantile cuts) strictly on the train folds.
- Target variables or future bar data must never leak into feature pipelines (lookahead bias).

### 3. Runtime & Checkpoint Proof
- Every experiment claim must include:
  - Exact execution timestamps and duration.
  - Git commit hash or code version.
  - Hardware/environment specifications.
  - Fixed, documented random seeds.
  - Verification logs and verifiable saved artifact/checkpoint paths on disk.

### 4. Missing & Constant Data Semantics
- Missing values, NaN handling, zero-trade windows, and constant features must have explicit protocol definitions.
- Converting missing data or empty periods silently into `NO_VALUE` or artificial zeros without audit is prohibited.
- Flatlines, constant predictions, or all-cash backtests must be flagged as unverified/degraded.

### 5. Complete Trial Accounting
- All attempted trials, failed hypotheses, and discarded variations must be logged in the research ledger.
- Selective reporting of only winning configurations without accounting for the search space (p-hacking / backtest overfitting) is rejected.
