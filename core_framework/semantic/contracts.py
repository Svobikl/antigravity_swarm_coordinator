"""Antigravity V4.1 Execution and Data Contract Registries.

Implements:
- EXECUTION_CONTRACTS.json: Versioned transaction-cost and capital-constraint contracts (E0, E1, E2, E3).
- DATA_CONTRACTS.json: Versioned dataset contracts with date boundaries, causal flags, and hashes.
- Enforces that all backtests reference explicit contract IDs rather than ambiguous prose.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import DataContract, ExecutionContract


class ExecutionContractManager:
    """Manages versioned execution contracts (EXECUTION_CONTRACTS.json)."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.contracts_path = self.program_dir / "EXECUTION_CONTRACTS.json"
        self.contracts: Dict[str, ExecutionContract] = {}

        if self.contracts_path.exists():
            self.load()

    def load(self) -> Dict[str, ExecutionContract]:
        with open(self.contracts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.contracts = {
            k: ExecutionContract.from_dict(v) for k, v in data.get("contracts", {}).items()
        }
        return self.contracts

    def save(self, program_id: str = "") -> None:
        data = {
            "program_id": program_id,
            "version": "1.0.0",
            "contracts": {k: v.to_dict() for k, v in self.contracts.items()}
        }
        with open(self.contracts_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def register_contract(self, contract: ExecutionContract) -> Tuple[bool, str]:
        cid = contract.contract_id
        if cid in self.contracts:
            existing = self.contracts[cid]
            if existing.total_roundtrip_bps != contract.total_roundtrip_bps:
                return False, (
                    f"Execution contract '{cid}' already exists with {existing.total_roundtrip_bps} bps. "
                    "In-place cost changes are prohibited. Register a new contract ID (e.g. E1_V2)."
                )
        self.contracts[cid] = contract
        return True, f"Contract '{cid}' registered ({contract.total_roundtrip_bps} bps roundtrip)."

    def get_contract(self, contract_id: str) -> Optional[ExecutionContract]:
        return self.contracts.get(contract_id)


class DataContractManager:
    """Manages versioned data contracts (DATA_CONTRACTS.json)."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.contracts_path = self.program_dir / "DATA_CONTRACTS.json"
        self.contracts: Dict[str, DataContract] = {}

        if self.contracts_path.exists():
            self.load()

    def load(self) -> Dict[str, DataContract]:
        with open(self.contracts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.contracts = {
            k: DataContract.from_dict(v) for k, v in data.get("contracts", {}).items()
        }
        return self.contracts

    def save(self, program_id: str = "") -> None:
        data = {
            "program_id": program_id,
            "version": "1.0.0",
            "contracts": {k: v.to_dict() for k, v in self.contracts.items()}
        }
        with open(self.contracts_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def register_contract(self, contract: DataContract) -> Tuple[bool, str]:
        self.contracts[contract.contract_id] = contract
        return True, f"Data contract '{contract.contract_id}' registered for symbol '{contract.symbol}'."

    def get_contract(self, contract_id: str) -> Optional[DataContract]:
        return self.contracts.get(contract_id)


def build_default_execution_contracts(program_id: str) -> ExecutionContractManager:
    """Builds canonical execution contracts adhering to Master Plan V3.5 §15."""
    mgr = ExecutionContractManager(Path("."))
    mgr.contracts = {
        "E0_ZERO_COST": ExecutionContract(
            contract_id="E0_ZERO_COST",
            name="Ideal Zero Cost Benchmark",
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            total_roundtrip_bps=0.0,
            capital_cap_pct=100.0,
            cash_reserve_pct=0.0,
            allowed_for_production=False,
            notes="Exploratory upper-bound reference only"
        ),
        "E1_CANONICAL_REALISTIC": ExecutionContract(
            contract_id="E1_CANONICAL_REALISTIC",
            name="Canonical Realistic Friction V1",
            maker_fee_bps=5.0,
            taker_fee_bps=5.0,
            slippage_bps=14.0,
            total_roundtrip_bps=38.0,
            capital_cap_pct=35.0,
            cash_reserve_pct=10.0,
            allowed_for_production=True,
            notes="Master Plan contract: 5 bps taker entry + 5 bps taker exit + 14 bps slippage x 2 = 38 bps roundtrip"
        ),
        "E2_STRESSED": ExecutionContract(
            contract_id="E2_STRESSED",
            name="High Friction Stress Scenario",
            maker_fee_bps=10.0,
            taker_fee_bps=10.0,
            slippage_bps=25.0,
            total_roundtrip_bps=70.0,
            capital_cap_pct=35.0,
            cash_reserve_pct=10.0,
            allowed_for_production=False,
            notes="Stress testing for high volatility regimes"
        )
    }
    return mgr
