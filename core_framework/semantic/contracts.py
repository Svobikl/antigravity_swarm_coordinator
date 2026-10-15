"""Antigravity V4.1 Execution and Data Contract Registries.

Implements:
- EXECUTION_CONTRACTS.json: Versioned environment, cost, latency, or resource-constraint contracts.
- DATA_CONTRACTS.json: Versioned dataset contracts with time/split boundaries, causal flags, and hashes.
- Enforces that all evaluations and benchmarks reference explicit contract IDs rather than ambiguous prose.
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
            if existing.to_dict() != contract.to_dict():
                return False, (
                    f"Execution contract '{cid}' already exists with different parameters. "
                    f"In-place contract changes are prohibited. Register a new versioned contract ID (e.g. '{cid}_V2')."
                )
        self.contracts[cid] = contract
        return True, f"Execution contract '{cid}' registered."

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
        return True, f"Data contract '{contract.contract_id}' registered for '{contract.symbol}'."

    def get_contract(self, contract_id: str) -> Optional[DataContract]:
        return self.contracts.get(contract_id)


def build_default_execution_contracts(program_id: str) -> ExecutionContractManager:
    """Builds a clean, project-agnostic execution contract registry."""
    mgr = ExecutionContractManager(Path("."))
    mgr.contracts = {}
    return mgr

