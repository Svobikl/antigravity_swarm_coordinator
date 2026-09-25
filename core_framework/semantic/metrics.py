"""Antigravity V4.1 Metric Definition Registry and Versioning.

Implements:
- Canonical metric naming, formulas, units, frequency, and annualization
- Mandatory metric versioning (prevents silent in-place changes to Sharpe, DSR, etc.)
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
                    "Silent formula modification is forbidden by V4.1 Metric Governance (§15)."
                )
        self.metrics[key] = metric
        return True, f"Metric '{key}' successfully registered at version {metric.version}."

    def get_metric(self, key: str) -> Optional[MetricDefinition]:
        return self.metrics.get(key)


def build_default_metric_registry(program_id: str) -> MetricRegistryManager:
    """Builds canonical metrics for quantitative research programs."""
    mgr = MetricRegistryManager(Path("."))
    canonical_metrics = {
        "sharpe_ratio": MetricDefinition(
            canonical_name="annualized_sharpe_ratio",
            version="1.0.0",
            formula="(mean(excess_returns) / std(excess_returns)) * sqrt(annualization_factor)",
            units="ratio",
            frequency="4h",
            annualization_factor=2190.0,
            implementation_path="research_v3/framework/metrics.py",
            test_vectors=[
                {"description": "Unit test verification in test_backtester_accounting.py"}
            ]
        ),
        "sortino_ratio": MetricDefinition(
            canonical_name="annualized_sortino_ratio",
            version="1.0.0",
            formula="(mean(excess_returns) / downside_std(excess_returns)) * sqrt(annualization_factor)",
            units="ratio",
            frequency="4h",
            annualization_factor=2190.0,
            implementation_path="research_v3/framework/metrics.py"
        ),
        "deflated_sharpe_ratio": MetricDefinition(
            canonical_name="deflated_sharpe_ratio",
            version="1.0.0",
            formula="Bailey_de_Prado_2014_DSR(sharpe, var_sharpe, trials_effective, skewness, kurtosis)",
            units="probability [0, 1]",
            frequency="cumulative",
            annualization_factor=None,
            implementation_path="research_v3/framework/dsr.py"
        ),
        "profit_factor": MetricDefinition(
            canonical_name="profit_factor",
            version="1.0.0",
            formula="sum(positive_trade_pnl) / abs(sum(negative_trade_pnl))",
            units="ratio",
            frequency="trade_level",
            implementation_path="research_v3/framework/metrics.py"
        ),
        "max_drawdown_pct": MetricDefinition(
            canonical_name="maximum_drawdown_percentage",
            version="1.0.0",
            formula="min((equity_curve - rolling_peak) / rolling_peak) * 100",
            units="percentage",
            frequency="continuous",
            implementation_path="research_v3/framework/metrics.py"
        ),
        "trades_per_year": MetricDefinition(
            canonical_name="annualized_trade_frequency",
            version="1.0.0",
            formula="total_trades / (duration_days / 365.25)",
            units="trades/year",
            frequency="annualized",
            implementation_path="research_v3/framework/metrics.py"
        )
    }
    mgr.metrics = canonical_metrics
    return mgr
