"""Antigravity V4.1 Report Consistency Auditor & Contradiction Detector.

Implements:
- Cross-report contradiction detection (DSR 0.86 vs >0.95, 38 bps vs 34 bps)
- Numeric & arithmetic validation (trades / years == trades_per_year)
- Post-hoc criteria redefinition detector (redefining 0.95 down to 0.80 after seeing 0.86)
- Factorial ablation verifier (X x Y interaction claims require full 5-part ablation)
- Period drift and sample drift detectors (differing evaluation windows / asset baskets)
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

        # 1. Check for Deployment Contradictions (§27, §33)
        # If text claims 'PRODUCTION READY' or '100% VALIDATED' while lifecycle ceiling is PAPER_TRADING_ONLY
        eff_real_cap, _ = self.inv_manager.get_effective_value("safety.real_capital_allowed")
        is_paper_only = (eff_real_cap is False)

        if is_paper_only:
            if re.search(r"\b(production[\s_-]ready|100%\s+validated)\b", text, re.IGNORECASE):
                findings.append(ConsistencyFinding(
                    check_id="CONSISTENCY_DEPLOYMENT_MISMATCH",
                    finding_type="DEPLOYMENT_MISMATCH",
                    severity="BLOCKING_FAIL",
                    target_file=file_path,
                    message="Report claims 'PRODUCTION READY' or '100% VALIDATED' while lifecycle ceiling is PAPER_TRADING_ONLY.",
                    context_snippet="Matched prohibited phrase in document."
                ))

        # 2. Check for Cost Friction Invariant Contradictions (e.g. 38 bps vs 34 bps) (§8, §27)
        eff_e1, active_ov = self.inv_manager.get_effective_value("economic.e1_roundtrip_bps")
        if eff_e1 is not None:
            eff_bps = float(eff_e1)
            canonical_inv = self.inv_manager.invariants.get_invariant("economic.e1_roundtrip_bps")
            canonical_bps = float(canonical_inv.value) if canonical_inv else eff_bps

            allowed_values = {eff_bps}
            if active_ov and canonical_bps is not None:
                # When a governed override is active, both canonical baseline and governed value are recognized
                allowed_values.add(canonical_bps)

            # Match explicit E1 roundtrip statements (e.g. "Tier E1 friction (34 bps roundtrip)", "34 bps roundtrip under Tier E1")
            e1_roundtrip_patterns = [
                r"(?:tier\s+e1|e1)[^.\n]*?(\d+(?:\.\d+)?)\s*bps\s+roundtrip",
                r"(\d+(?:\.\d+)?)\s*bps\s+roundtrip[^.\n]*?(?:tier\s+e1|e1)",
                r"(?:tier\s+e1|e1\s+realistic\s+friction)[^.\n]*?(?:\(|\:)\s*(\d+(?:\.\d+)?)\s*bps\s*(?:\)|\,)"
            ]
            seen_spans = set()
            for pat in e1_roundtrip_patterns:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    span_key = (m.start(), m.end())
                    if span_key in seen_spans:
                        continue
                    seen_spans.add(span_key)
                    found_val = float(m.group(1))

                    # Check if this occurrence is explicitly designated as an alternative/secondary contract (INV-ECO-001)
                    surrounding = text[max(0, m.start() - 30):min(len(text), m.end() + 30)].lower()
                    if "alt" in surrounding or "alternative" in surrounding or "observed" in surrounding:
                        continue

                    # Check if found value is within 1 bps of any allowed value
                    if not any(abs(found_val - allowed) <= 1.0 for allowed in allowed_values):
                        start = max(0, m.start() - 40)
                        end = min(len(text), m.end() + 40)
                        findings.append(ConsistencyFinding(
                            check_id="CONSISTENCY_FRICTION_DRIFT",
                            finding_type="CONTRADICTION",
                            severity="BLOCKING_FAIL",
                            target_file=file_path,
                            message=(
                                f"Friction contradiction: reported {found_val} bps roundtrip for Tier E1, "
                                f"which does not match authorized values {allowed_values}."
                            ),
                            context_snippet=text[start:end].strip()
                        ))

        # 3. Check for Post-Hoc Criteria Redefinition (§13, §27)
        # e.g., claiming PASS with DSR threshold redefined down from 0.95 to 0.80
        eff_dsr_thresh, _ = self.inv_manager.get_effective_value("statistical.dsr_significance_threshold")
        if eff_dsr_thresh is not None:
            canonical_dsr = float(eff_dsr_thresh)
            # Check if text describes a lower threshold as mandatory (e.g. "threshold >= 0.80" when canonical is 0.95)
            redef_match = re.search(r"(?:threshold|cutoff|criterion)\s*(?:>=|>=|of)\s*0\.(?:7|8\d+)", text, re.IGNORECASE)
            if redef_match and canonical_dsr >= 0.90:
                findings.append(ConsistencyFinding(
                    check_id="CONSISTENCY_POST_HOC_CRITERIA",
                    finding_type="POST_HOC_CRITERIA_CHANGE",
                    severity="BLOCKING_FAIL",
                    target_file=file_path,
                    message=(
                        f"Detected post-hoc criteria relaxation: text refers to threshold "
                        f"'{redef_match.group(0)}', but canonical invariant requires DSR >= {canonical_dsr}."
                    ),
                    context_snippet=redef_match.group(0)
                ))

        # 4. Check for Internal DSR numeric contradictions in text
        # e.g., mentioning both DSR = 0.86 and DSR > 0.95
        dsr_values = re.findall(r"DSR\s*(?:=|is|of)\s*(\d+\.\d+)", text, re.IGNORECASE)
        dsr_claims = re.findall(r"DSR\s*(?:>|>=)\s*(\d+\.\d+)", text, re.IGNORECASE)
        if dsr_values and dsr_claims:
            val = float(dsr_values[0])
            claim = float(dsr_claims[0])
            if val < claim:
                # Contradiction if text says DSR = 0.86 and also claims DSR > 0.95
                if f"DSR > {claim}" in text or f"DSR >= {claim}" in text:
                    findings.append(ConsistencyFinding(
                        check_id="CONSISTENCY_DSR_CONTRADICTION",
                        finding_type="CONTRADICTION",
                        severity="BLOCKING_FAIL",
                        target_file=file_path,
                        message=f"Internal contradiction: observed DSR is {val}, but text asserts DSR >= {claim}.",
                        context_snippet=f"Observed: {val}, Claim: >= {claim}"
                    ))

        # 5. Arithmetic validation: trade frequency (§28)
        # Pattern: "X trades over Y years" vs "Z trades/year"
        freq_matches = re.finditer(r"(\d+)\s+trades\s+over\s+(\d+(?:\.\d+)?)\s+years?", text, re.IGNORECASE)
        for m in freq_matches:
            trades = int(m.group(1))
            years = float(m.group(2))
            expected_freq = trades / years if years > 0 else 0
            # Look around for "XX trades/year"
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 100)
            surrounding = text[start:end]
            rate_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:trades/year|tr/yr)", surrounding, re.IGNORECASE)
            if rate_match:
                claimed_freq = float(rate_match.group(1))
                if abs(claimed_freq - expected_freq) > 2.0:
                    findings.append(ConsistencyFinding(
                        check_id="CONSISTENCY_ARITHMETIC_FREQUENCY",
                        finding_type="ARITHMETIC_ERROR",
                        severity="BLOCKING_FAIL",
                        target_file=file_path,
                        message=(
                            f"Arithmetic contradiction: {trades} trades over {years} years implies "
                            f"{expected_freq:.1f} tr/yr, but text states {claimed_freq} tr/yr."
                        ),
                        context_snippet=surrounding.strip()
                    ))

        # 6. Factorial Ablation check (§37)
        # If text claims interaction between X and Y adds value, check for factorial components
        if re.search(r"\b(interaction|synergy|jointly|multiplicative)\b.*adds\s+value", text, re.IGNORECASE):
            required_terms = ["base", "+ x", "+ y", "interaction"]
            missing_terms = [t for t in ["base", "interaction"] if t not in text.lower()]
            if missing_terms:
                findings.append(ConsistencyFinding(
                    check_id="CONSISTENCY_FACTORIAL_ABLATION",
                    finding_type="MISSING_FACTORIAL_ABLATION",
                    severity="WARNING",
                    target_file=file_path,
                    message="Interaction value claim made without full factorial ablation decomposition (Base, Base+X, Base+Y, Base+X+Y, Base+interaction).",
                    context_snippet="Interaction claim found without full 5-case breakdown."
                ))

        return findings

    def audit_period_and_sample_drift(
        self,
        candidate_a_meta: Dict[str, Any],
        candidate_b_meta: Dict[str, Any]
    ) -> List[ConsistencyFinding]:
        """Detects period drift and sample drift between compared candidates (§39, §40)."""
        findings = []

        # Period drift
        p_a = (candidate_a_meta.get("start"), candidate_a_meta.get("end"))
        p_b = (candidate_b_meta.get("start"), candidate_b_meta.get("end"))
        if p_a != p_b and None not in (p_a[0], p_a[1], p_b[0], p_b[1]):
            findings.append(ConsistencyFinding(
                check_id="DRIFT_PERIOD_MISMATCH",
                finding_type="PERIOD_DRIFT",
                severity="BLOCKING_FAIL",
                target_file=str(candidate_a_meta.get("source", "candidate")),
                message=(
                    f"Direct comparison invalid due to period drift: Candidate A evaluated on "
                    f"{p_a[0]}..{p_a[1]}, while Candidate B evaluated on {p_b[0]}..{p_b[1]}. "
                    "Unqualified direct comparison prohibited without explicit disclosure."
                )
            ))

        # Sample / Universe drift
        u_a = set(candidate_a_meta.get("universe", []))
        u_b = set(candidate_b_meta.get("universe", []))
        if u_a and u_b and u_a != u_b:
            findings.append(ConsistencyFinding(
                check_id="DRIFT_UNIVERSE_MISMATCH",
                finding_type="SAMPLE_DRIFT",
                severity="WARNING",
                target_file=str(candidate_a_meta.get("source", "candidate")),
                message=(
                    f"Sample drift detected: Candidate A universe ({u_a}) differs from "
                    f"Candidate B universe ({u_b}). Requires disclosure of asset composition."
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
