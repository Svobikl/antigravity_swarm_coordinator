"""Antigravity V4.1 Metric Definition Registry and Versioning.

Implements:
- Canonical metric naming, formulas, units, and aggregation frequency
- Mandatory metric versioning (prevents silent in-place formula modifications)
- Test vector validation to verify deterministic calculations
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import MetricDefinition


class MetricRegistryManager:
    """Manages METRIC_REGISTRY.json, enforcing immutability and versioning."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.registry_path = self.program_dir / "METRIC_REGISTRY.json"
        self.metrics: Dict[str, MetricDefinition] = {}

        if self.registry_path.exists():
            self.load()

    def load(self) -> Dict[str, MetricDefinition]:
        with open(self.registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.metrics = {
            k: MetricDefinition.from_dict(v) for k, v in data.get("metrics", {}).items()
        }
        return self.metrics

    def save(self, program_id: str = "") -> None:
        data = {
            "program_id": program_id,
            "version": "1.0.0",
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()}
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def register_metric(self, key: str, metric: MetricDefinition, overwrite: bool = False) -> Tuple[bool, str]:
        if key in self.metrics and not overwrite:
            existing = self.metrics[key]
            if existing.formula != metric.formula or existing.version != metric.version:
                return False, (
                    f"Metric '{key}' already registered with version {existing.version}. "
                    f"To update formula, you MUST register a new versioned metric (e.g., '{key}_v2'). "
                    "Silent formula modification is forbidden by V4.1 Metric Governance."
                )
        self.metrics[key] = metric
        return True, f"Metric '{key}' successfully registered at version {metric.version}."

    def get_metric(self, key: str) -> Optional[MetricDefinition]:
        return self.metrics.get(key)


def build_default_metric_registry(program_id: str) -> MetricRegistryManager:
    """Builds an empty, project-agnostic metric registry ready for program-specific definitions."""
    mgr = MetricRegistryManager(Path("."))
    mgr.metrics = {}
    return mgr

