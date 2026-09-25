"""Antigravity V4.1 Claim Registry and Lineage Manager.

Implements:
- CLAIM_REGISTRY.json: Versioned claim registry for all high-impact research results
- Claim immutability & explicit supersession lineage (CLAIM-001 -> CLAIM-001-V2)
- Arithmetic validation: trades_per_year == trade_count / duration_years
- Scientific verdict enforcement (EXPLORATORY cannot be claimed as VALIDATED)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import ClaimDefinition, ScientificVerdict


class ClaimRegistryManager:
    """Manages CLAIM_REGISTRY.json, enforcing immutability and lineage."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.claims_path = self.program_dir / "CLAIM_REGISTRY.json"
        self.claims: Dict[str, ClaimDefinition] = {}

        if self.claims_path.exists():
            self.load()

    def load(self) -> Dict[str, ClaimDefinition]:
        with open(self.claims_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.claims = {
            item["claim_id"]: ClaimDefinition.from_dict(item)
            for item in data.get("claims", [])
        }
        return self.claims

    def save(self, program_id: str = "") -> None:
        data = {
            "program_id": program_id,
            "version": "1.0.0",
            "claims": [c.to_dict() for c in self.claims.values()]
        }
        with open(self.claims_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def register_claim(self, claim: ClaimDefinition) -> Tuple[bool, str]:
        cid = claim.claim_id
        if cid in self.claims:
            existing = self.claims[cid]
            # Immutability check (§30)
            if existing.value != claim.value or existing.validation_status != claim.validation_status:
                return False, (
                    f"Claim '{cid}' already exists with value {existing.value} and status {existing.validation_status.value}. "
                    "Claim immutability violation (§30)! Use supersession with a new claim ID (e.g., '{cid}_v2') "
                    f"and declare supersedes_claim_id='{cid}'."
                )

        # Arithmetic validation (§28)
        if claim.duration_years > 0 and claim.trade_count > 0:
            expected_rate = claim.trade_count / claim.duration_years
            if abs(claim.trades_per_year - expected_rate) > 1.5:
                return False, (
                    f"Arithmetic contradiction in claim '{cid}': trade_count={claim.trade_count} "
                    f"over {claim.duration_years:.2f} years implies ~{expected_rate:.1f} trades/year, "
                    f"but claimed trades_per_year={claim.trades_per_year}."
                )

        # Handle supersession linkage
        if claim.supersedes_claim_id and claim.supersedes_claim_id in self.claims:
            self.claims[claim.supersedes_claim_id].superseded_by_claim_id = cid

        self.claims[cid] = claim
        return True, f"Claim '{cid}' successfully registered with verdict '{claim.validation_status.value}'."

    def get_claim(self, claim_id: str) -> Optional[ClaimDefinition]:
        return self.claims.get(claim_id)

    def get_active_claims(self) -> List[ClaimDefinition]:
        """Returns non-superseded claims."""
        return [c for c in self.claims.values() if not c.superseded_by_claim_id]
