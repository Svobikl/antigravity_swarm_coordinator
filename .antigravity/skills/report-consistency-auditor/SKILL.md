# Report Consistency Auditor

## Purpose
Adversarially detect and prevent internal and cross-report contradictions, arithmetic discrepancies, and post-hoc criteria redefinitions across long-horizon research reports (Antigravity V4.1 §26).

## Mandatory Audit Responsibilities

### 1. Cross-Document Contradiction Detection (§27)
- Detect conflicting metrics across documents (e.g. DSR = 0.865 in table vs "DSR > 0.95" in text).
- Detect transaction cost discrepancies (e.g. 38 bps vs 34 bps).
- Detect deployment claims contradicting program ceiling (e.g. "PRODUCTION READY" vs `PAPER_TRADING_ONLY`).

### 2. Post-Hoc Criteria Redefinition (§13)
- Catch attempts to move goalposts (e.g. lowering pre-registered threshold from 0.95 to 0.80 after observing 0.86).
- Results failing pre-registered criteria must be labeled `FAILED_PRE_REGISTERED_CRITERION`.

### 3. Machine-Checkable Arithmetic Verification (§28)
- Verify trade frequencies: `trades_per_year == total_trades / calendar_years` within tolerance.
- Verify percentages, win rates, and drawdowns.

### 4. Factorial Ablation Verification (§37)
- Any claim that an interaction between factors adds value must present complete factorial ablation: Base, Base+X, Base+Y, Base+X+Y, Base+interaction.
