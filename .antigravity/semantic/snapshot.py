"""Antigravity V4.1 Source Snapshot and Plan Freezing.

Implements:
- Verbatim preservation of original task / Master Plan
- SHA256 integrity verification (PROGRAM_SOURCE_HASH)
- Detection of unapproved source alterations
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, Union


class SourceSnapshotManager:
    """Manages immutable source snapshots and SHA256 integrity verification."""

    def __init__(self, program_dir: Union[str, Path]):
        self.program_dir = Path(program_dir)
        self.snapshot_path = self.program_dir / "PROGRAM_SOURCE_SNAPSHOT.md"
        self.hash_path = self.program_dir / "PROGRAM_SOURCE_HASH"

    def create_snapshot(self, raw_content: str, force: bool = False) -> Tuple[str, Path]:
        """Creates the verbatim source snapshot and writes the SHA256 hash."""
        if self.snapshot_path.exists() and not force:
            raise FileExistsError(f"Snapshot already exists at {self.snapshot_path}. Plan is frozen.")

        normalized_content = raw_content.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
        with open(self.snapshot_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(normalized_content)

        sha256_hash = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        with open(self.hash_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{sha256_hash}\n")

        return sha256_hash, self.snapshot_path

    def get_source_hash(self) -> Optional[str]:
        """Reads recorded SHA256 hash."""
        if not self.hash_path.exists():
            return None
        return self.hash_path.read_text(encoding="utf-8").strip()

    def verify_integrity(self) -> Tuple[bool, str]:
        """Verifies that PROGRAM_SOURCE_SNAPSHOT.md matches PROGRAM_SOURCE_HASH."""
        if not self.snapshot_path.exists():
            return False, "PROGRAM_SOURCE_SNAPSHOT.md missing."
        if not self.hash_path.exists():
            return False, "PROGRAM_SOURCE_HASH missing."

        recorded_hash = self.get_source_hash()
        current_hash = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()

        if current_hash != recorded_hash:
            return False, (
                f"Source plan hash mismatch! Recorded: {recorded_hash}, Current: {current_hash}. "
                "The original master plan was modified post-freeze without governed authority."
            )
        return True, "Source snapshot verified with valid SHA256 hash."
