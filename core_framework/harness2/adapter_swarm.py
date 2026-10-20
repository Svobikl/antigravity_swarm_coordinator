# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Antigravity Swarm Task Adapter conforming to the BenchmarkAdapter protocol.

Isolates rollouts in temporary git worktrees (with isolated workspace copy fallback)
and supports reuse_base=True for k=1 failure-recovery mode.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .core.spec import BenchmarkAdapter, BenchPrompts, BenchSpec, ChannelSpec, SubstrateLike
from .core.tree import SurfaceSpec

try:
    from .substrate.antigravity import AntigravitySubstrate
except ImportError:
    AntigravitySubstrate = None


class SwarmSubstrate:
    """Default substrate for Antigravity Swarm tasks when AntigravitySubstrate is absent."""

    name: str = "ag"

    def surface(self) -> SurfaceSpec:
        return SurfaceSpec(
            always_on=(".antigravity/harness_triggers.md", ".antigravity/tool_guidance.md"),
            always_on_max=6000,
            skill_dir=".agents/skills",
            hooks_file=".antigravity/hooks.json",
        )


class SwarmTaskAdapter:
    """Implements BenchmarkAdapter protocol for Antigravity Swarm tasks.

    Features:
    - Isolates each rollout in a temporary git worktree (or isolated copy fallback).
    - Cleans up worktrees, locks, and temporary directories in finally: blocks.
    - Supports reuse_base=True to reuse a captured failed rollout as base1 without re-running.
    """

    def __init__(
        self,
        repo_dir: Path | str | None = None,
        runs_root: Path | str | None = None,
        task_id: str = "swarm_task",
        task_prompt: str = "",
        spec: BenchSpec | None = None,
        substrate: SubstrateLike | None = None,
        reuse_base: bool = False,
        captured_base_dir: Path | str | None = None,
        executor_fn: Callable[[Path, Path, str], None] | None = None,
        domain: str = "engineering",
        task_files_dir: Path | str | None = None,
    ) -> None:
        self.repo_dir = Path(repo_dir or Path.cwd())
        self.runs_root = Path(runs_root or (self.repo_dir / "runs"))
        self.task_id = task_id
        self._task_prompt = task_prompt
        self.reuse_base = reuse_base
        self.captured_base_dir = Path(captured_base_dir) if captured_base_dir else None
        self.executor_fn = executor_fn
        self._domain = domain
        self._task_files_dir = Path(task_files_dir) if task_files_dir else None

        if substrate is not None:
            self.substrate = substrate
        elif AntigravitySubstrate is not None:
            self.substrate = AntigravitySubstrate()
        else:
            self.substrate = SwarmSubstrate()

        if spec is not None:
            self.spec = spec
        else:
            prompts = BenchPrompts(
                work="Antigravity Swarm software engineering task execution and verification.",
                domain_word="domain",
                deliverable_word="deliverable",
            )
            channels = {
                "proposer": ChannelSpec("antigravity", "gemini-4-argon"),
                "selector": ChannelSpec("antigravity_opus", "claude-opus-5-5"),
            }
            self.spec = BenchSpec(
                name="swarm",
                runs_root=self.runs_root,
                install_mode="antigravity_root",
                prompts=prompts,
                channels=channels,
            )

    def tasks(self, split: str = "all") -> list[str]:
        return [self.task_id]

    def domain_of(self, task_id: str) -> str:
        return self._domain

    def task_prompt(self, task_id: str) -> str:
        return self._task_prompt

    def task_files(self, task_id: str) -> Path | None:
        return self._task_files_dir

    def base_harness(self) -> Path:
        return self.repo_dir

    def validate_tree(self, tree: dict[str, str]) -> None:
        self.substrate.surface().validate(tree)

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        score_file = Path(run_dir) / "score.json"
        if score_file.is_file():
            try:
                return json.loads(score_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        if self.delivered(run_dir):
            return {"pass": True, "score": 1.0}
        return {"pass": False, "score": 0.0}

    def delivered(self, run_dir: Path) -> bool:
        rd = Path(run_dir)
        deliv_dir = rd / "deliverables"
        if deliv_dir.is_dir() and any(deliv_dir.iterdir()):
            return True
        if (rd / "delivered").is_file():
            return True
        if (rd / "output" / "answer.md").is_file():
            return True
        if (rd / "receipt.json").is_file():
            return True
        return bool(self.deliverable_text(run_dir).strip())

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        rd = Path(run_dir)
        for name in ("trajectory.txt", "trajectory.jsonl", "RUN_TRANSCRIPT.txt", "transcript.txt"):
            f = rd / name
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                if len(text) > obs_trunc:
                    return text[:obs_trunc] + f"\n... [TRUNCATED {len(text) - obs_trunc} chars]"
                return text
        return ""

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        rd = Path(run_dir)
        deliv_dir = rd / "deliverables"
        res: dict[str, str] = {}
        if deliv_dir.is_dir():
            for p in sorted(deliv_dir.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(deliv_dir).as_posix()
                    res[rel] = p.read_text(encoding="utf-8", errors="replace")
        ans = rd / "output" / "answer.md"
        if ans.is_file():
            res["answer.md"] = ans.read_text(encoding="utf-8", errors="replace")
        return res

    def deliverable_text(self, run_dir: Path) -> str:
        files = self.deliverable_files(run_dir)
        if files:
            return "\n\n".join(f"=== {k} ===\n{v}" for k, v in files.items())
        rd = Path(run_dir)
        ans = rd / "output" / "answer.md"
        if ans.is_file():
            return ans.read_text(encoding="utf-8", errors="replace")
        deliv_file = rd / "delivered.txt"
        if deliv_file.is_file():
            return deliv_file.read_text(encoding="utf-8", errors="replace")
        return ""

    def execute(
        self,
        task_id: str,
        harness_dir: Path | None,
        run_id: str,
        *,
        timeout: int | None = None,
    ) -> Path:
        """Run one rollout and return its run directory, idempotently by run_id.

        If reuse_base is True and this is a base rollout (harness_dir is None or run_id starts
        with 'base'), the captured base trajectory is returned immediately without re-running.
        """
        is_base = harness_dir is None or run_id == "base1" or run_id.startswith("base")
        if self.reuse_base and is_base and self.captured_base_dir is not None:
            if self.captured_base_dir.exists():
                return self.captured_base_dir

        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        worktree_dir = Path(tempfile.mkdtemp(prefix=f"swarm-wt-{run_id}-"))
        use_git_worktree = False

        # Attempt git worktree isolation if repository has HEAD commit
        if (self.repo_dir / ".git").exists():
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "--verify", "HEAD"],
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                )
                if r.returncode == 0:
                    if worktree_dir.exists():
                        worktree_dir.rmdir()
                    wt_res = subprocess.run(
                        ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
                        cwd=self.repo_dir,
                        capture_output=True,
                        text=True,
                    )
                    if wt_res.returncode == 0:
                        use_git_worktree = True
            except Exception:
                use_git_worktree = False

        try:
            # Fallback to isolated directory copy if git worktree could not be added
            if not use_git_worktree:
                if not worktree_dir.exists():
                    worktree_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    self.repo_dir,
                    worktree_dir,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "runs", "*.pyc"),
                    dirs_exist_ok=True,
                )

            # Apply harness tree modifications if provided
            if harness_dir is not None and Path(harness_dir).is_dir():
                shutil.copytree(harness_dir, worktree_dir, dirs_exist_ok=True)

            # Execute rollout
            if self.executor_fn is not None:
                self.executor_fn(worktree_dir, run_dir, task_id)
            elif os.environ.get("HARNESS2_SWARM_MOCK_EXEC"):
                cmd = os.environ["HARNESS2_SWARM_MOCK_EXEC"].split()
                subprocess.run(
                    cmd,
                    cwd=worktree_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                # Default minimal executor recording
                (run_dir / "delivered").write_text("status=done\n", encoding="utf-8")
                (run_dir / "trajectory.txt").write_text(
                    f"[ACTION] rollout task={task_id} run_id={run_id}\n[OBSERVATION] complete\n",
                    encoding="utf-8",
                )
        finally:
            if use_git_worktree:
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree_dir)],
                        cwd=self.repo_dir,
                        capture_output=True,
                        text=True,
                    )
                    subprocess.run(
                        ["git", "worktree", "prune"],
                        cwd=self.repo_dir,
                        capture_output=True,
                        text=True,
                    )
                except Exception:
                    pass
            shutil.rmtree(worktree_dir, ignore_errors=True)

        return run_dir


__all__ = ["SwarmTaskAdapter", "SwarmSubstrate"]
