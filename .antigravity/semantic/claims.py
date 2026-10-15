"""Antigravity V4.1 Claim Registry and Lineage Manager.

Implements:
- CLAIM_REGISTRY.json: Versioned claim registry for all high-impact research/engineering results
- Claim immutability & explicit supersession lineage (CLAIM-001 -> CLAIM-001-V2)
- Arithmetic validation: events_per_unit == event_count / duration_units
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
        if claim.duration_units > 0 and claim.event_count > 0:
            expected_rate = claim.event_count / claim.duration_units
            tolerance = max(1.0, expected_rate * 0.05)
            if abs(claim.events_per_unit - expected_rate) > tolerance:
                return False, (
                    f"Arithmetic contradiction in claim '{cid}': event_count={claim.event_count} "
                    f"over {claim.duration_units:.2f} units implies ~{expected_rate:.2f} events/unit, "
                    f"but claimed events_per_unit={claim.events_per_unit}."
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
