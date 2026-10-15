"""Antigravity V4 to V4.1 Migration and Upgrade Tool.

Implements:
- Upgrades existing Long-Horizon V4 programs to V4.1 Semantic Integrity
- Initializes PROGRAM_SOURCE_SNAPSHOT.md and PROGRAM_SOURCE_HASH
- Generates PROGRAM_INVARIANTS.json and INVARIANT_OVERRIDES.json
- Initializes METRIC_REGISTRY.json, EXECUTION_CONTRACTS.json, DATA_CONTRACTS.json, and CLAIM_REGISTRY.json
- Enriches REQUIREMENT_COVERAGE.csv with 'requirement_intent' and 'linked_invariant' columns
- Generates PROGRAM_MANIFEST.json with SHA256 hashes
- Preserves all historical artifacts and backward compatibility
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Union
import pandas as pd

from .schema import (
    ProgramManifest,
    compute_file_sha256,
)
from .invariants import build_default_invariants
from .metrics import build_default_metric_registry
from .contracts import build_default_execution_contracts
from .snapshot import SourceSnapshotManager


def upgrade_v4_workspace(
    program_dir: Union[str, Path],
    root_dir: Union[str, Path] = ".",
    program_id: str = "DEFAULT_MODE5_PROGRAM"
) -> Dict[str, Any]:
    p_dir = Path(program_dir).resolve()
    results = {"upgraded_files": [], "warnings": []}

    print(f"Upgrading workspace to Antigravity V4.1: {p_dir}")

    # 1. Source Snapshot & Hash
    source_plan = p_dir / "SOURCE_PLAN.md"
    snap_mgr = SourceSnapshotManager(p_dir)
    if source_plan.exists() and not snap_mgr.snapshot_path.exists():
        content = source_plan.read_text(encoding="utf-8")
        h, snap_p = snap_mgr.create_snapshot(content)
        results["upgraded_files"].append(str(snap_p.name))
        results["upgraded_files"].append(str(snap_mgr.hash_path.name))
        print(f"  [+] Created PROGRAM_SOURCE_SNAPSHOT.md and PROGRAM_SOURCE_HASH (SHA256: {h[:12]}...)")
    elif snap_mgr.snapshot_path.exists():
        print("  [.] Source snapshot already exists.")

    source_hash = snap_mgr.get_source_hash() or ""

    # 2. Invariants & Governed Overrides
    inv_path = p_dir / "PROGRAM_INVARIANTS.json"
    if not inv_path.exists():
        invs = build_default_invariants(program_id=program_id, source_hash=source_hash)
        with open(inv_path, "w", encoding="utf-8") as f:
            json.dump(invs.to_dict(), f, indent=2)
        results["upgraded_files"].append("PROGRAM_INVARIANTS.json")
        print("  [+] Initialized canonical PROGRAM_INVARIANTS.json")

    ovr_path = p_dir / "INVARIANT_OVERRIDES.json"
    if not ovr_path.exists():
        with open(ovr_path, "w", encoding="utf-8") as f:
            json.dump({"program_id": program_id, "overrides": []}, f, indent=2)
        results["upgraded_files"].append("INVARIANT_OVERRIDES.json")
        print("  [+] Initialized empty INVARIANT_OVERRIDES.json")

    # 3. Metric Registry
    metric_path = p_dir / "METRIC_REGISTRY.json"
    if not metric_path.exists():
        m_mgr = build_default_metric_registry(program_id=program_id)
        m_mgr.registry_path = metric_path
        m_mgr.save(program_id=program_id)
        results["upgraded_files"].append("METRIC_REGISTRY.json")
        print("  [+] Initialized METRIC_REGISTRY.json")

    # 4. Execution Contracts
    exec_path = p_dir / "EXECUTION_CONTRACTS.json"
    if not exec_path.exists():
        e_mgr = build_default_execution_contracts(program_id=program_id)
        e_mgr.contracts_path = exec_path
        e_mgr.save(program_id=program_id)
        results["upgraded_files"].append("EXECUTION_CONTRACTS.json")
        print("  [+] Initialized EXECUTION_CONTRACTS.json")

    # 5. Data Contracts
    data_path = p_dir / "DATA_CONTRACTS.json"
    if not data_path.exists():
        dc_data = {
            "program_id": program_id,
            "version": "1.0.0",
            "contracts": {}
        }
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(dc_data, f, indent=2)
        results["upgraded_files"].append("DATA_CONTRACTS.json")
        print("  [+] Initialized DATA_CONTRACTS.json")

    # 6. Claim Registry
    claim_path = p_dir / "CLAIM_REGISTRY.json"
    if not claim_path.exists():
        cl_data = {
            "program_id": program_id,
            "version": "1.0.0",
            "claims": []
        }
        with open(claim_path, "w", encoding="utf-8") as f:
            json.dump(cl_data, f, indent=2)
        results["upgraded_files"].append("CLAIM_REGISTRY.json")
        print("  [+] Initialized CLAIM_REGISTRY.json")

    # 7. Enrich REQUIREMENT_COVERAGE.csv with intent and linked_invariant
    cov_path = p_dir / "REQUIREMENT_COVERAGE.csv"
    if cov_path.exists():
        cov_df = pd.read_csv(cov_path)
        modified = False
        if "requirement_intent" not in cov_df.columns:
            cov_df["requirement_intent"] = cov_df["description"].apply(
                lambda d: f"Ensure faithful implementation and evidence-backed verification of: {str(d)[:60]}"
            )
            modified = True
        if "linked_invariant" not in cov_df.columns:
            cov_df["linked_invariant"] = "quality.require_three_layer_verification"
            modified = True

        if modified:
            cov_df.to_csv(cov_path, index=False)
            results["upgraded_files"].append("REQUIREMENT_COVERAGE.csv (enriched)")
            print("  [+] Enriched REQUIREMENT_COVERAGE.csv with 'requirement_intent' and 'linked_invariant'")

    # 8. Build PROGRAM_MANIFEST.json
    manifest_path = p_dir / "PROGRAM_MANIFEST.json"
    manifest = ProgramManifest(
        program_id=program_id,
        manifest_id=f"MANIFEST_{program_id}_V4_1",
        framework_version="4.1.0",
        created_at=datetime.now(timezone.utc).isoformat(),
        hashes={
            "source_snapshot": compute_file_sha256(snap_mgr.snapshot_path) if snap_mgr.snapshot_path.exists() else "",
            "invariants": compute_file_sha256(inv_path),
            "metric_registry": compute_file_sha256(metric_path),
            "execution_contracts": compute_file_sha256(exec_path),
            "data_contracts": compute_file_sha256(data_path),
            "claim_registry": compute_file_sha256(claim_path),
            "task_graph": compute_file_sha256(p_dir / "TASK_GRAPH.json"),
            "requirement_coverage": compute_file_sha256(cov_path)
        }
    )
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, indent=2)
    results["upgraded_files"].append("PROGRAM_MANIFEST.json")
    print(f"  [+] Created PROGRAM_MANIFEST.json with {len(manifest.hashes)} file hashes")

    print("\nWorkspace upgrade to Antigravity V4.1 complete.")
    return results

