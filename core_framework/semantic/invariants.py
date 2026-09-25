"""Antigravity V4.1 Invariant Manager and Auditor.

Enforces:
- Canonical invariant definition & persistence in PROGRAM_INVARIANTS.json
- Governed overrides in INVARIANT_OVERRIDES.json
- Prevention of silent invariant drift (38 bps -> 34 bps, DSR 0.95 -> 0.80)
- User-locked invariant protection (cannot be changed autonomously without human approval)
- Hard drift (blocking completion) vs Soft drift (reported as alternative)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import (
    InvariantDefinition,
    InvariantOverride,
    ProgramInvariants,
    compute_file_sha256,
)


@dataclass
class InvariantFinding:
    invariant_id: str
    finding_type: str  # 'HARD_DRIFT', 'SOFT_DRIFT', 'USER_LOCKED_VIOLATION', 'UNAUTHORIZED_OVERRIDE', 'POST_HOC_CRITERION_CHANGE'
    canonical_value: Any
    observed_value: Any
    source_location: str
    message: str
    is_blocking: bool = True


class InvariantManager:
    """Manages loading, validation, and auditing of program invariants."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.invariants_path = self.program_dir / "PROGRAM_INVARIANTS.json"
        self.overrides_path = self.program_dir / "INVARIANT_OVERRIDES.json"
        self.invariants: Optional[ProgramInvariants] = None
        self.overrides: List[InvariantOverride] = []

        if self.invariants_path.exists():
            self.load_invariants()
        if self.overrides_path.exists():
            self.load_overrides()

    def load_invariants(self) -> ProgramInvariants:
        with open(self.invariants_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.invariants = ProgramInvariants.from_dict(data)
        return self.invariants

    def load_overrides(self) -> List[InvariantOverride]:
        with open(self.overrides_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.overrides = [InvariantOverride.from_dict(item) for item in data.get("overrides", [])]
        return self.overrides

    def save_invariants(self) -> None:
        if not self.invariants:
            return
        with open(self.invariants_path, "w", encoding="utf-8") as f:
            json.dump(self.invariants.to_dict(), f, indent=2)

    def save_overrides(self) -> None:
        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump({
                "program_id": self.invariants.program_id if self.invariants else "",
                "overrides": [ov.to_dict() for ov in self.overrides]
            }, f, indent=2)

    def register_override(self, override: InvariantOverride) -> Tuple[bool, str]:
        """Registers a governed override after validating user-lock and integrity."""
        if not self.invariants:
            return False, "Invariants not loaded"

        inv = self.invariants.get_invariant(override.invariant_id)
        if not inv:
            return False, f"Invariant '{override.invariant_id}' not found in canonical invariants."

        # Check user-locked invariants (§11)
        if inv.user_locked and not override.user_approved:
            return False, (
                f"Invariant '{override.invariant_id}' is USER_LOCKED. "
                "Autonomous change is prohibited without explicit human approval (user_approved=True)."
            )

        # Check that override is properly documented
        if not override.reason or not override.evidence_path:
            return False, "Override rejected: must specify non-empty 'reason' and 'evidence_path'."

        # Record override
        self.overrides.append(override)
        self.save_overrides()
        return True, f"Override {override.override_id} successfully recorded for {override.invariant_id}."

    def get_effective_value(self, invariant_id: str) -> Tuple[Any, Optional[InvariantOverride]]:
        """Returns effective invariant value, accounting for valid governed overrides."""
        if not self.invariants:
            return None, None
        inv = self.invariants.get_invariant(invariant_id)
        if not inv:
            return None, None

        # Check for overrides
        matching_overrides = [ov for ov in self.overrides if ov.invariant_id == invariant_id]
        if matching_overrides:
            latest = matching_overrides[-1]
            return latest.new_value, latest

        return inv.value, None

    def audit_value(
        self,
        invariant_id: str,
        observed_value: Any,
        source_location: str,
        allow_soft_drift: bool = False
    ) -> Optional[InvariantFinding]:
        """Audits an observed value against the canonical invariant and active overrides."""
        if not self.invariants:
            return InvariantFinding(
                invariant_id=invariant_id,
                finding_type="HARD_DRIFT",
                canonical_value="UNSPECIFIED",
                observed_value=observed_value,
                source_location=source_location,
                message="PROGRAM_INVARIANTS.json missing or unloaded.",
                is_blocking=True
            )

        inv = self.invariants.get_invariant(invariant_id)
        if not inv:
            return None  # Unconstrained field

        effective_val, active_override = self.get_effective_value(invariant_id)

        # If values match effective value, no finding
        if observed_value == effective_val:
            return None

        # Value differs! Check if active override exists
        if active_override:
            # An override exists, but observed does not even match the override
            return InvariantFinding(
                invariant_id=invariant_id,
                finding_type="HARD_DRIFT",
                canonical_value=effective_val,
                observed_value=observed_value,
                source_location=source_location,
                message=(
                    f"Observed value {observed_value} does not match active governed override "
                    f"{active_override.override_id} ({effective_val})."
                ),
                is_blocking=True
            )

        # No override exists! This is unauthorized drift!
        if inv.user_locked:
            return InvariantFinding(
                invariant_id=invariant_id,
                finding_type="USER_LOCKED_VIOLATION",
                canonical_value=inv.value,
                observed_value=observed_value,
                source_location=source_location,
                message=(
                    f"CRITICAL: User-locked invariant '{invariant_id}' drifted from "
                    f"{inv.value} to {observed_value} without approved human override!"
                ),
                is_blocking=True
            )

        if allow_soft_drift:
            return InvariantFinding(
                invariant_id=invariant_id,
                finding_type="SOFT_DRIFT",
                canonical_value=inv.value,
                observed_value=observed_value,
                source_location=source_location,
                message=(
                    f"Soft drift detected on '{invariant_id}' ({inv.value} -> {observed_value}). "
                    "Must be labeled as experimental alternative; canonical baseline must remain reported."
                ),
                is_blocking=False
            )

        return InvariantFinding(
            invariant_id=invariant_id,
            finding_type="HARD_DRIFT",
            canonical_value=inv.value,
            observed_value=observed_value,
            source_location=source_location,
            message=(
                f"Unauthorized hard invariant drift detected on '{invariant_id}': "
                f"canonical={inv.value}, observed={observed_value}. "
                "Must be governed via INVARIANT_OVERRIDES.json."
            ),
            is_blocking=True
        )


def build_default_invariants(program_id: str, source_hash: str = "") -> ProgramInvariants:
    """Constructs default canonical invariants adhering to Long-Horizon V4.1 standards."""
    now_str = datetime.now(timezone.utc).isoformat()
    return ProgramInvariants(
        program_id=program_id,
        version="1.0.0",
        created_at=now_str,
        source_hash=source_hash,
        invariants={
            "safety": {
                "real_capital_allowed": InvariantDefinition(
                    value=False,
                    type="bool",
                    user_locked=True,
                    description="Autonomous real capital deployment strictly forbidden (§0)",
                    source_reference="MASTER_PLAN_SECTION_0"
                )
            },
            "scientific": {
                "outer_oos_selection_allowed": InvariantDefinition(
                    value=False,
                    type="bool",
                    user_locked=True,
                    description="Outer OOS data may never be used for feature/model selection (§16, §77)",
                    source_reference="MASTER_PLAN_SECTION_16"
                ),
                "require_factorial_ablation_for_interactions": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=False,
                    description="Any claim of interaction effects must include complete factorial ablation (§37)",
                    source_reference="MASTER_PLAN_SECTION_37"
                )
            },
            "statistical": {
                "dsr_significance_threshold": InvariantDefinition(
                    value=0.95,
                    type="float",
                    user_locked=True,
                    description="Canonical Deflated Sharpe Ratio significance threshold (§61)",
                    source_reference="MASTER_PLAN_SECTION_61"
                ),
                "max_pbo_threshold": InvariantDefinition(
                    value=0.20,
                    type="float",
                    user_locked=False,
                    description="Maximum allowable probability of backtest overfitting (§62)",
                    source_reference="MASTER_PLAN_SECTION_62"
                )
            },
            "economic": {
                "e1_roundtrip_bps": InvariantDefinition(
                    value=38.0,
                    type="float",
                    user_locked=False,
                    description="Canonical Tier E1 roundtrip execution friction in basis points (§15)",
                    source_reference="MASTER_PLAN_SECTION_15"
                ),
                "allow_cost_redefinition": InvariantDefinition(
                    value=False,
                    type="bool",
                    user_locked=True,
                    description="Silent modification of execution friction is prohibited (§3)",
                    source_reference="MASTER_PLAN_SECTION_3"
                )
            },
            "data": {
                "free_first": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=False,
                    description="Open-source and free data must be exhausted before paid sources (§21)",
                    source_reference="MASTER_PLAN_SECTION_21"
                ),
                "point_in_time_causality": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=True,
                    description="Strict causality with zero lookahead bias across all features and sentiment (§28)",
                    source_reference="MASTER_PLAN_SECTION_28"
                )
            },
            "agentic": {
                "max_active_skills_per_leaf": InvariantDefinition(
                    value=8,
                    type="int",
                    user_locked=True,
                    description="Maximum number of active skills loaded in context per leaf task (§82)",
                    source_reference="MASTER_PLAN_SECTION_82"
                ),
                "single_global_orchestrator": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=True,
                    description="swarm-coordinator is the sole authority for global scope and state (§4, §41)",
                    source_reference="MASTER_PLAN_SECTION_4"
                )
            },
            "completion": {
                "independent_auditor_signoff_required": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=True,
                    description="Dual auditor sign-off (completion-auditor and semantic-completion-auditor) required (§23)",
                    source_reference="MASTER_PLAN_SECTION_23"
                ),
                "four_axis_evaluation_required": InvariantDefinition(
                    value=True,
                    type="bool",
                    user_locked=True,
                    description="Must report mechanical, semantic, scientific, and forward status (§2)",
                    source_reference="MASTER_PLAN_SECTION_2"
                )
            },
            "user_defined": {}
        }
    )
