"""Antigravity V4.1 Semantic Integrity Schemas and Data Models.

Defines the core schema for:
- 4-Axis Completion Model (Mechanical, Semantic, Scientific, Forward)
- Invariants & Governed Overrides
- Metric Registry & Versioning
- Execution & Data Contracts
- Claim Registry & Provenance
- Program Manifest
- Subagent Contracts
- Memory Classification
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class FourAxisStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    PASS_WITH_FINDINGS = "PASS_WITH_FINDINGS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScientificVerdict(str, Enum):
    EXPLORATORY = "EXPLORATORY"
    SCREEN_PASS = "SCREEN_PASS"
    INNER_VALIDATED = "INNER_VALIDATED"
    OUTER_VALIDATED = "OUTER_VALIDATED"
    NESTED_VALIDATED = "NESTED_VALIDATED"
    FORWARD_SHADOW = "FORWARD_SHADOW"
    FORWARD_VALIDATED = "FORWARD_VALIDATED"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


class MemoryClass(str, Enum):
    CONTEXT = "CONTEXT"
    HYPOTHESIS = "HYPOTHESIS"
    EXPLORATORY_RESULT = "EXPLORATORY_RESULT"
    VALIDATED_RESULT = "VALIDATED_RESULT"
    INVALIDATED_RESULT = "INVALIDATED_RESULT"
    PROGRAM_STATE_POINTER = "PROGRAM_STATE_POINTER"


class DeploymentStatus(str, Enum):
    RESEARCH = "RESEARCH"
    PAPER_TRADING_ONLY = "PAPER_TRADING_ONLY"
    FORWARD_SHADOW = "FORWARD_SHADOW"
    FORWARD_VALIDATED = "FORWARD_VALIDATED"
    HUMAN_APPROVED_PRODUCTION = "HUMAN_APPROVED_PRODUCTION"


@dataclass
class FourAxisReportHeader:
    mechanical_completion: FourAxisStatus = FourAxisStatus.NOT_STARTED
    semantic_integrity: FourAxisStatus = FourAxisStatus.NOT_STARTED
    scientific_validity: FourAxisStatus = FourAxisStatus.NOT_STARTED
    forward_validation: FourAxisStatus = FourAxisStatus.NOT_STARTED
    deployment_status: DeploymentStatus = DeploymentStatus.PAPER_TRADING_ONLY

    def format_markdown(self) -> str:
        return (
            f"```text\n"
            f"MECHANICAL_COMPLETION: {self.mechanical_completion.value}\n"
            f"SEMANTIC_INTEGRITY:    {self.semantic_integrity.value}\n"
            f"SCIENTIFIC_VALIDITY:   {self.scientific_validity.value}\n"
            f"FORWARD_VALIDATION:    {self.forward_validation.value}\n"
            f"DEPLOYMENT_STATUS:     {self.deployment_status.value}\n"
            f"```"
        )


@dataclass
class InvariantDefinition:
    value: Any
    type: str  # 'bool', 'int', 'float', 'str', 'list', 'dict'
    user_locked: bool = False
    description: str = ""
    source_reference: str = ""

    def validate_type(self) -> bool:
        if self.type == "bool":
            return isinstance(self.value, bool)
        elif self.type == "int":
            return isinstance(self.value, int) and not isinstance(self.value, bool)
        elif self.type == "float":
            return isinstance(self.value, (int, float)) and not isinstance(self.value, bool)
        elif self.type == "str":
            return isinstance(self.value, str)
        elif self.type == "list":
            return isinstance(self.value, list)
        elif self.type == "dict":
            return isinstance(self.value, dict)
        return True


@dataclass
class ProgramInvariants:
    program_id: str
    version: str = "1.0.0"
    created_at: str = ""
    source_hash: str = ""
    invariants: Dict[str, Dict[str, InvariantDefinition]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "program_id": self.program_id,
            "version": self.version,
            "created_at": self.created_at,
            "source_hash": self.source_hash,
            "invariants": {}
        }
        for cat, invs in self.invariants.items():
            res["invariants"][cat] = {
                k: asdict(v) for k, v in invs.items()
            }
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProgramInvariants":
        invs: Dict[str, Dict[str, InvariantDefinition]] = {}
        for cat, cat_dict in data.get("invariants", {}).items():
            invs[cat] = {}
            for k, v in cat_dict.items():
                if isinstance(v, dict) and "value" in v:
                    invs[cat][k] = InvariantDefinition(
                        value=v["value"],
                        type=v.get("type", "str"),
                        user_locked=v.get("user_locked", False),
                        description=v.get("description", ""),
                        source_reference=v.get("source_reference", "")
                    )
                else:
                    # Inferred basic scalar
                    t_name = type(v).__name__
                    invs[cat][k] = InvariantDefinition(value=v, type=t_name)
        return cls(
            program_id=data.get("program_id", ""),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", ""),
            source_hash=data.get("source_hash", ""),
            invariants=invs
        )

    def get_invariant(self, dotted_path: str) -> Optional[InvariantDefinition]:
        parts = dotted_path.split(".", 1)
        if len(parts) == 2:
            cat, name = parts
            return self.invariants.get(cat, {}).get(name)
        for cat in self.invariants.values():
            if dotted_path in cat:
                return cat[dotted_path]
        return None


@dataclass
class InvariantOverride:
    override_id: str
    invariant_id: str
    old_value: Any
    new_value: Any
    override_type: str  # 'GOVERNED_EXPERIMENT', 'FORMAL_PLAN_REVISION'
    reason: str
    evidence_path: str
    affected_tasks: List[str] = field(default_factory=list)
    affected_experiments: List[str] = field(default_factory=list)
    required_reruns: List[str] = field(default_factory=list)
    actor: str = "swarm-coordinator"
    timestamp_utc: str = ""
    user_approval_required: bool = False
    user_approved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvariantOverride":
        return cls(**data)


@dataclass
class MetricDefinition:
    canonical_name: str
    version: str
    formula: str
    units: str
    frequency: Optional[str] = None
    annualization_factor: Optional[float] = None
    implementation_path: Optional[str] = None
    test_vectors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricDefinition":
        return cls(**data)


@dataclass
class ExecutionContract:
    contract_id: str
    name: str
    maker_fee_bps: float
    taker_fee_bps: float
    slippage_bps: float
    total_roundtrip_bps: float
    capital_cap_pct: float = 35.0
    cash_reserve_pct: float = 10.0
    execution_delay_candles: int = 0
    allowed_for_production: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionContract":
        return cls(**data)


@dataclass
class DataContract:
    contract_id: str
    source: str
    symbol: str
    timeframe: str
    start_time: str
    end_time: str
    causal_availability: bool = True
    timezone: str = "UTC"
    sha256_hash: str = ""
    missingness_policy: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataContract":
        return cls(**data)


@dataclass
class ClaimDefinition:
    claim_id: str
    claim_text: str
    metric_name: str
    metric_version: str
    value: Union[float, int, str, bool]
    units: str
    execution_contract_id: str
    evaluation_period_start: str
    evaluation_period_end: str
    duration_years: float
    sample_count: int
    trade_count: int
    trades_per_year: float
    artifact_source: str
    experiment_id: str
    validation_status: ScientificVerdict
    supersedes_claim_id: Optional[str] = None
    superseded_by_claim_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["validation_status"] = self.validation_status.value
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClaimDefinition":
        data_copy = dict(data)
        if "validation_status" in data_copy and isinstance(data_copy["validation_status"], str):
            data_copy["validation_status"] = ScientificVerdict(data_copy["validation_status"])
        return cls(**data_copy)


@dataclass
class ProgramManifest:
    program_id: str
    manifest_id: str
    framework_version: str = "4.1.0"
    created_at: str = ""
    hashes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProgramManifest":
        return cls(**data)


@dataclass
class SubagentContract:
    task_id: str
    read_set: List[str]
    write_set: List[str]
    active_skills: List[str]
    input_contract: Dict[str, Any]
    output_contract: Dict[str, Any]
    acceptance_criteria: List[str]
    forbidden_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentContract":
        return cls(**data)


def compute_file_sha256(path: Union[str, Path]) -> str:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
