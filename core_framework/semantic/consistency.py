"""Antigravity V4.1 Report Consistency Auditor & Contradiction Detector.

Implements domain-agnostic consistency checks across project reports and ledgers:
- Cross-report invariant & metric contradiction detection
- Numeric & rate arithmetic validation
- Post-hoc criteria redefinition detection (relaxing pre-registered thresholds after observing results)
- Factorial ablation verification (multi-factor interaction claims require full ablation breakdown)
- Evaluation window / sample scope drift detection between compared candidates
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .invariants import InvariantManager
from .claims import ClaimRegistryManager


@dataclass
class ConsistencyFinding:
    check_id: str
    finding_type: str  # 'CONTRADICTION', 'POST_HOC_CRITERIA_CHANGE', 'ARITHMETIC_ERROR', 'MISSING_FACTORIAL_ABLATION', 'PERIOD_DRIFT', 'SAMPLE_DRIFT', 'DEPLOYMENT_MISMATCH'
    severity: str      # 'BLOCKING_FAIL', 'WARNING'
    target_file: str
    message: str
    context_snippet: str = ""


class ReportConsistencyAuditor:
    """Scans reports, metrics, and ledgers for internal and cross-document contradictions."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.inv_manager = InvariantManager(self.program_dir)
        self.claim_manager = ClaimRegistryManager(self.program_dir)

    def audit_text_content(self, text: str, file_path: str = "") -> List[ConsistencyFinding]:
        findings: List[ConsistencyFinding] = []

        # 1. Check for Deployment / Readiness Contradictions
        # If text claims 'PRODUCTION READY' or '100% VALIDATED' while autonomous production release is locked/disabled
        eff_prod_allowed, _ = self.inv_manager.get_effective_value("safety.autonomous_production_deploy_allowed")
        is_restricted = (eff_prod_allowed is False)

        if is_restricted:
            if re.search(r"\b(production[\s_-]ready|100%\s+validated)\b", text, re.IGNORECASE):
                findings.append(ConsistencyFinding(
                    check_id="CONSISTENCY_DEPLOYMENT_MISMATCH",
                    finding_type="DEPLOYMENT_MISMATCH",
                    severity="BLOCKING_FAIL",
                    target_file=file_path,
                    message="Report claims 'PRODUCTION READY' or '100% VALIDATED' while program safety invariant restricts autonomous production release.",
                    context_snippet="Matched prohibited readiness phrase in document."
                ))

        # 2. Dynamic Numeric Invariant Drift & Post-Hoc Threshold Relaxation Check
        # Iterates over all numeric invariants registered in PROGRAM_INVARIANTS.json
        if self.inv_manager.invariants:
            for cat, cat_dict in self.inv_manager.invariants.invariants.items():
                for inv_key, inv_def in cat_dict.items():
                    if inv_def.type not in ("int", "float"):
                        continue
                    dotted_id = f"{cat}.{inv_key}"
                    eff_val, active_ov = self.inv_manager.get_effective_value(dotted_id)
                    if eff_val is None:
                        continue
                    target_num = float(eff_val)
                    allowed_values = {target_num}
                    if active_ov and isinstance(inv_def.value, (int, float)):
                        allowed_values.add(float(inv_def.value))

                    # Look for explicit mentions of the invariant key with a numeric assignment in text
                    key_pattern = re.escape(inv_key).replace(r"\_", r"[\s_-]+")
                    pat = rf"\b{key_pattern}\s*(?:=|:|is|of|>=|<=)\s*(-?\d+(?:\.\d+)?)"
                    for m in re.finditer(pat, text, re.IGNORECASE):
                        observed_num = float(m.group(1))
                        surrounding = text[max(0, m.start() - 35):min(len(text), m.end() + 35)].lower()
                        if any(tok in surrounding for tok in ("alt", "alternative", "observed", "exploratory")):
                            continue
                        if not any(abs(observed_num - allowed) <= 1e-6 for allowed in allowed_values):
                            findings.append(ConsistencyFinding(
                                check_id="CONSISTENCY_INVARIANT_MISMATCH",
                                finding_type="CONTRADICTION",
                                severity="BLOCKING_FAIL",
                                target_file=file_path,
                                message=(
                                    f"Invariant contradiction for '{dotted_id}': report states {observed_num}, "
                                    f"which does not match authorized value(s) {sorted(allowed_values)}."
                                ),
                                context_snippet=m.group(0).strip()
                            ))

        # 3. Generic Internal Metric Contradictions in Text
        # Detects when the same document states both `METRIC = X` and asserts `METRIC >= Y` (or `> Y`) where X < Y
        assign_matches = re.findall(r"\b([A-Za-z][A-Za-z0-9_-]{2,30})\s*(?:=|is)\s*(-?\d+\.\d+)", text)
        bound_matches = re.findall(r"\b([A-Za-z][A-Za-z0-9_-]{2,30})\s*(>|>=)\s*(-?\d+\.\d+)", text)
        if assign_matches and bound_matches:
            observed_map: Dict[str, float] = {}
            for name, val_str in assign_matches:
                observed_map[name.lower()] = float(val_str)
            for name, op, bound_str in bound_matches:
                key = name.lower()
                if key in observed_map:
                    obs_val = observed_map[key]
                    bound_val = float(bound_str)
                    if (op == ">" and obs_val <= bound_val) or (op == ">=" and obs_val < bound_val):
                        findings.append(ConsistencyFinding(
                            check_id="CONSISTENCY_METRIC_CONTRADICTION",
                            finding_type="CONTRADICTION",
                            severity="BLOCKING_FAIL",
                            target_file=file_path,
                            message=(
                                f"Internal metric contradiction for '{name}': observed value is {obs_val}, "
                                f"but text asserts {name} {op} {bound_val}."
                            ),
                            context_snippet=f"Observed: {name}={obs_val}, Asserted: {name} {op} {bound_val}"
                        ))

        # 4. Generic Rate / Frequency Arithmetic Validation
        # Pattern: "X <items> over Y <units>" vs "Z <items>/<unit>"
        freq_matches = re.finditer(
            r"(\d+)\s+([a-zA-Z]+)\s+over\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]+?)(?:s)?\b",
            text,
            re.IGNORECASE
        )
        for m in freq_matches:
            count_val = int(m.group(1))
            item_unit = m.group(2).lower()
            period_val = float(m.group(3))
            period_unit = m.group(4).lower()
            if period_val <= 0:
                continue
            expected_rate = count_val / period_val
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 100)
            surrounding = text[start:end]
            rate_pat = rf"(\d+(?:\.\d+)?)\s*{re.escape(item_unit)}\s*/\s*{re.escape(period_unit)}"
            rate_match = re.search(rate_pat, surrounding, re.IGNORECASE)
            if rate_match:
                claimed_rate = float(rate_match.group(1))
                tolerance = max(1.0, expected_rate * 0.05)
                if abs(claimed_rate - expected_rate) > tolerance:
                    findings.append(ConsistencyFinding(
                        check_id="CONSISTENCY_ARITHMETIC_RATE",
                        finding_type="ARITHMETIC_ERROR",
                        severity="BLOCKING_FAIL",
                        target_file=file_path,
                        message=(
                            f"Arithmetic contradiction: {count_val} {item_unit} over {period_val} {period_unit}(s) "
                            f"implies {expected_rate:.2f} {item_unit}/{period_unit}, "
                            f"but text states {claimed_rate} {item_unit}/{period_unit}."
                        ),
                        context_snippet=surrounding.strip()
                    ))

        # 5. Factorial Ablation Check
        # If text claims interaction between factors adds value, verify ablation breakdown is present
        if re.search(r"\b(interaction|synergy|jointly|multiplicative)\b.*adds\s+value", text, re.IGNORECASE):
            missing_terms = [t for t in ["base", "interaction"] if t not in text.lower()]
            if missing_terms:
                findings.append(ConsistencyFinding(
                    check_id="CONSISTENCY_FACTORIAL_ABLATION",
                    finding_type="MISSING_FACTORIAL_ABLATION",
                    severity="WARNING",
                    target_file=file_path,
                    message="Interaction value claim made without full factorial ablation decomposition (Base, individual factors, joint factors, interaction).",
                    context_snippet="Interaction claim found without full ablation breakdown."
                ))

        return findings

    def audit_period_and_sample_drift(
        self,
        candidate_a_meta: Dict[str, Any],
        candidate_b_meta: Dict[str, Any]
    ) -> List[ConsistencyFinding]:
        """Detects evaluation window drift and sample/scope drift between compared candidates."""
        findings = []

        # Evaluation window / period drift
        p_a = (candidate_a_meta.get("start"), candidate_a_meta.get("end"))
        p_b = (candidate_b_meta.get("start"), candidate_b_meta.get("end"))
        if p_a != p_b and None not in (p_a[0], p_a[1], p_b[0], p_b[1]):
            findings.append(ConsistencyFinding(
                check_id="DRIFT_PERIOD_MISMATCH",
                finding_type="PERIOD_DRIFT",
                severity="BLOCKING_FAIL",
                target_file=str(candidate_a_meta.get("source", "candidate")),
                message=(
                    f"Direct comparison invalid due to evaluation window drift: Candidate A evaluated on "
                    f"{p_a[0]}..{p_a[1]}, while Candidate B evaluated on {p_b[0]}..{p_b[1]}. "
                    "Unqualified direct comparison is prohibited without explicit disclosure."
                )
            ))

        # Sample / scope drift
        u_a = set(candidate_a_meta.get("scope", candidate_a_meta.get("universe", [])))
        u_b = set(candidate_b_meta.get("scope", candidate_b_meta.get("universe", [])))
        if u_a and u_b and u_a != u_b:
            findings.append(ConsistencyFinding(
                check_id="DRIFT_SCOPE_MISMATCH",
                finding_type="SAMPLE_DRIFT",
                severity="WARNING",
                target_file=str(candidate_a_meta.get("source", "candidate")),
                message=(
                    f"Sample scope drift detected: Candidate A scope ({u_a}) differs from "
                    f"Candidate B scope ({u_b}). Requires explicit disclosure of sample composition."
                )
            ))

        return findings

    def audit_report_file(self, file_path: Union[str, Path]) -> List[ConsistencyFinding]:
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return [ConsistencyFinding(
                check_id="REPORT_NOT_FOUND",
                finding_type="CONTRADICTION",
                severity="BLOCKING_FAIL",
                target_file=str(file_path),
                message=f"Report file {file_path} not found."
            )]
        text = p.read_text(encoding="utf-8")
        return self.audit_text_content(text, file_path=str(p))

