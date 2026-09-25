"""Antigravity V4.1 Memory Classification and Supersession Manager.

Implements:
- Typed Memory Classes (CONTEXT, HYPOTHESIS, EXPLORATORY_RESULT, VALIDATED_RESULT, INVALIDATED_RESULT, PROGRAM_STATE_POINTER)
- Memory Supersession & Invalidation (prevents resurrection of obsolete/failed conclusions)
- Memory Write Gate (only coordinator with verified evidence can create VALIDATED_RESULT)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schema import MemoryClass


@dataclass
class MemoryEntry:
    memory_id: str
    memory_class: MemoryClass
    title: str
    content: str
    created_at: str
    created_by: str
    status: str = "ACTIVE"  # 'ACTIVE', 'SUPERSEDED', 'INVALIDATED'
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None
    evidence_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["memory_class"] = self.memory_class.value
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        d = dict(data)
        if isinstance(d.get("memory_class"), str):
            d["memory_class"] = MemoryClass(d["memory_class"])
        return cls(**d)


class MemoryCurator:
    """Manages persistent semantic memory with strict supersession and write gating."""

    def __init__(self, memory_dir: Union[str, Path] = ".agent-workspace/memory"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.memory_dir / "MEMORY_LEDGER.json"
        self.memories: Dict[str, MemoryEntry] = {}

        if self.ledger_path.exists():
            self.load()

    def load(self) -> Dict[str, MemoryEntry]:
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.memories = {
            item["memory_id"]: MemoryEntry.from_dict(item)
            for item in data.get("memories", [])
        }
        return self.memories

    def save(self) -> None:
        data = {
            "version": "1.0.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "memories": [m.to_dict() for m in self.memories.values()]
        }
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def store_memory(
        self,
        memory_id: str,
        memory_class: MemoryClass,
        title: str,
        content: str,
        actor: str,
        evidence_path: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        # Memory Write Gate (§48): Only validated evidence can produce VALIDATED_RESULT
        if memory_class == MemoryClass.VALIDATED_RESULT:
            if not evidence_path or not Path(evidence_path).exists():
                return False, (
                    f"Memory Write Gate rejected '{memory_id}': VALIDATED_RESULT requires "
                    f"valid, non-empty evidence_path on disk (provided: '{evidence_path}')."
                )
            if actor != "swarm-coordinator" and not actor.endswith("-auditor"):
                return False, (
                    f"Memory Write Gate rejected '{memory_id}': Only swarm-coordinator or "
                    f"auditor roles may persist VALIDATED_RESULT memories. Subagent actor '{actor}' is restricted."
                )

        # Handle supersession (§47)
        if supersedes_id and supersedes_id in self.memories:
            old_mem = self.memories[supersedes_id]
            old_mem.status = "SUPERSEDED"
            old_mem.superseded_by_id = memory_id

        entry = MemoryEntry(
            memory_id=memory_id,
            memory_class=memory_class,
            title=title,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            created_by=actor,
            status="ACTIVE",
            supersedes_id=supersedes_id,
            evidence_path=evidence_path,
            tags=tags or []
        )
        self.memories[memory_id] = entry
        self.save()
        return True, f"Memory '{memory_id}' stored successfully as {memory_class.value}."

    def invalidate_memory(self, memory_id: str, reason: str, actor: str) -> Tuple[bool, str]:
        """Explicitly marks a memory as INVALIDATED to prevent retrieval of obsolete conclusions."""
        if memory_id not in self.memories:
            return False, f"Memory '{memory_id}' not found."
        mem = self.memories[memory_id]
        mem.status = "INVALIDATED"
        mem.content = f"INVALIDATED ({reason})\nOriginal: {mem.content}"
        self.save()
        return True, f"Memory '{memory_id}' marked INVALIDATED."

    def get_active_memories(self, memory_class: Optional[MemoryClass] = None) -> List[MemoryEntry]:
        """Returns only ACTIVE memories, safely excluding SUPERSEDED or INVALIDATED entries."""
        res = [m for m in self.memories.values() if m.status == "ACTIVE"]
        if memory_class:
            res = [m for m in res if m.memory_class == memory_class]
        return res
