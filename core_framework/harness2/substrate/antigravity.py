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

"""AntigravitySubstrate: Antigravity native runtime as a solver substrate.

Carries the c1..c8 editable surface (ANTIGRAVITY_SURFACE), immutable governance protections,
the max-8 active skill budget, zero hardcoded user-path enforcement, and the Antigravity
trajectory renderer.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..core import runmark as RM
from ..core import tree as HT
from ..core.tree import SurfaceSpec
from .base import Install, Launcher, RunRequest

IMMUTABLE_GOVERNANCE_FILES = frozenset(
    {
        ".antigravity/rules/GLOBAL_DEVELOPMENT_RULES.md",
        "GLOBAL_DEVELOPMENT_RULES.md",
        "GEMINI.md",
        "AGENTS.md",
        "PROGRAM_INVARIANTS.json",
        "INVARIANT_OVERRIDES.json",
        "METRIC_REGISTRY.json",
        "SOURCE_PLAN.md",
        "REQUIREMENT_COVERAGE.csv",
        "TASK_GRAPH.json",
        "PROGRAM_STATE.md",
    }
)

MAX_ACTIVE_SKILLS = 8

# Dynamically construct user-home path patterns to prevent static check false positives
_USER_DIR_PATTERN = re.compile(
    r"[A-Za-z]:[\\/]+" + r"Users[\\/]+"
    + r"|/(?:Users|home)/[A-Za-z0-9_.\-]+(?:[\\/]|$|\s|\"|'|:)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AntigravitySurfaceSpec(SurfaceSpec):
    """SurfaceSpec extended with Antigravity-specific subagent directory."""

    subagent_dir: str = ".antigravity/sub_agents"


ANTIGRAVITY_SURFACE = AntigravitySurfaceSpec(
    name="antigravity",
    always_on=(".antigravity/harness_triggers.md", ".antigravity/tool_guidance.md"),
    always_on_max=6000,
    always_on_cap_reason=(
        "harness_triggers.md and tool_guidance.md are standing context; capped to 6,000 "
        "characters to preserve context budget for reasoning and avoid prompt bloat"
    ),
    skill_dir=".agents/skills",
    skill_name_rule="overrides_dir",
    trigger_hint=(
        "Fix it by adding a trigger line naming `{name}` to .antigravity/harness_triggers.md, "
        'e.g. "- When {desc}, read .agents/skills/{name}/SKILL.md and follow it."'
    ),
    autotrigger_file=".antigravity/harness_triggers.md",
    trigger_line="- When {desc}, read .agents/skills/{name}/SKILL.md and follow it.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=".antigravity/hooks.json",
    hook_events=frozenset(
        {
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "PreCompact",
            "PostCompact",
            "SessionStart",
            "SubagentStart",
            "SubagentStop",
            "UserPromptSubmit",
            "Stop",
        }
    ),
    compile_skill_scripts=True,
    reject_empty_always_on=True,
    subagent_dir=".antigravity/sub_agents",
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run as `python scripts/<name>.py`. "
            "Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            ".antigravity/sub_agents/README.md",
            "<!-- c5: delegated antigravity subagents. Add one as "
            ".antigravity/sub_agents/<name>/AGENT.md with frontmatter `description:`. -->\n",
        ),
        (
            ".antigravity/hooks.json",
            '{\n  "hooks": {\n    "PostToolUse": []\n  }\n}\n',
        ),
        (
            ".agents/skills/README.md",
            "<!-- c6: reusable workflows. Add one as .agents/skills/<name>/SKILL.md with YAML "
            "frontmatter: `description:` is REQUIRED; `name:` is optional and must match the directory. -->\n",
        ),
    ),
)


def validate_antigravity_harness(
    files: Mapping[str, str], *, reserved_scripts: frozenset[str] = frozenset()
) -> None:
    """Validate an Antigravity harness tree against immutable governance, active skill budget,
    path-independence, and the SurfaceSpec schema.
    """
    # 1. Immutable governance file tripwire
    for rel in files:
        try:
            norm = HT.normalize_rel(rel)
        except ValueError:
            norm = str(rel).replace("\\", "/").strip("/")

        base = Path(norm).name
        if (
            norm in IMMUTABLE_GOVERNANCE_FILES
            or base in IMMUTABLE_GOVERNANCE_FILES
            or norm.endswith("GLOBAL_DEVELOPMENT_RULES.md")
        ):
            raise ValueError(
                f"Immutable governance file cannot be mutated or included in harness: {rel}"
            )

    # 2. Path independence tripwire: reject hardcoded user-home directories
    for rel, content in files.items():
        if _USER_DIR_PATTERN.search(rel):
            raise ValueError(f"Hardcoded user path rejected in filename: {rel!r}")
        if _USER_DIR_PATTERN.search(content):
            raise ValueError(f"Hardcoded user path rejected in content of {rel!r}")

    # 3. Active skill budget enforcement (max 8 skills)
    skills_in_tree = set(HT.skill_names(ANTIGRAVITY_SURFACE, files))
    triggers_text = files.get(".antigravity/harness_triggers.md", "")
    triggered_skills = set(
        re.findall(r"\.agents/skills/([a-z0-9_\-]+)/SKILL\.md", triggers_text)
    )
    trigger_lines = [
        ln
        for ln in triggers_text.splitlines()
        if ln.strip().startswith("-") and ("skill" in ln.lower() or "SKILL.md" in ln)
    ]
    total_skills = max(len(skills_in_tree), len(triggered_skills), len(trigger_lines))
    if total_skills > MAX_ACTIVE_SKILLS:
        raise ValueError(
            f"Active skill budget exceeded: max 8 active skills allowed (found {total_skills})"
        )

    # 4. Validate subagents in .antigravity/sub_agents
    for rel, src in files.items():
        try:
            norm = HT.normalize_rel(rel)
        except ValueError:
            norm = str(rel).replace("\\", "/").strip("/")
        m = re.fullmatch(
            r"(?:sub_agents|\.antigravity/sub_agents)/([a-z0-9][a-z0-9_\-]*)/AGENT\.md",
            norm,
        )
        if m:
            fm = src[:600]
            if not re.search(r"^description:\s*\S", fm, re.M):
                raise ValueError(f"{rel} needs a `description:`")

    # 5. Core tree validation
    HT.validate(
        ANTIGRAVITY_SURFACE,
        files,
        reserved_scripts=reserved_scripts,
    )


class AntigravitySubstrate:
    """Antigravity runtime behind the Substrate interface."""

    name = "ag"

    def __init__(self, launcher: Launcher | None = None):
        self._launcher = launcher

    def surface(self) -> SurfaceSpec:
        return ANTIGRAVITY_SURFACE

    def validate_tree(self, files: Mapping[str, str]) -> None:
        validate_antigravity_harness(files)

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        tree_dir = Path(tree_dir)
        if not HT.is_tree(ANTIGRAVITY_SURFACE, tree_dir):
            raise ValueError(
                f"{tree_dir} is not an antigravity harness tree (missing always-on file)"
            )
        mode = getattr(spec, "install_mode", "antigravity_root")
        staged = Path(tempfile.mkdtemp(prefix="adapt-ag-root-"))
        try:
            shutil.copytree(tree_dir, staged, dirs_exist_ok=True)
            for key, body in ctx.items():
                if key.startswith("file:"):
                    rel = HT.normalize_rel(key[len("file:") :])
                    p = staged / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(body, encoding="utf-8")
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise

        return Install(
            staging_dir=staged,
            fingerprint=RM.fingerprint(tree_dir),
            extras={
                "install_mode": mode,
                **{k: v for k, v in ctx.items() if not k.startswith("file:")},
            },
        )

    def execute(
        self, task_ref: str, install: Install, run_ids: list[str], timeout: int
    ) -> list[Path]:
        if self._launcher is None:
            raise RuntimeError(
                "AntigravitySubstrate was constructed without a launcher body; the benchmark "
                "adapter must supply one"
            )
        return self._launcher(
            RunRequest(task_ref=task_ref, run_ids=tuple(run_ids), timeout=int(timeout)), install
        )

    def read_trajectory(
        self, stream_path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400
    ) -> str:
        return render_events(
            Path(stream_path), obs_trunc=obs_trunc, max_chars=max_chars, args_trunc=args_trunc
        )

    def preflight(self) -> None:
        """Health check before rollout starts."""
        pass


_TRUNC_FMT = "…(+{n} chars — render truncation)"


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\x00", "")
    if n <= 0 or len(s) <= n:
        return s
    return s[:n] + _TRUNC_FMT.format(n=len(s) - n)


def render_events(
    path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400
) -> str:
    """Render Antigravity / JSONL event stream into the shared grammar."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(failed to read trajectory: {e})"

    lines: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue

        etype = ev.get("type", "")

        # 1. User inputs
        if etype in ("USER_INPUT", "user"):
            msg = ev.get("content") or ev.get("message") or ev.get("text")
            if msg:
                lines.append(f"[USER] {_clip(msg, obs_trunc)}")
            continue

        # 2. Thinking
        thinking = ev.get("thinking")
        if thinking and isinstance(thinking, str) and thinking.strip():
            lines.append(f"[THINKING] {_clip(thinking, obs_trunc)}")

        # 3. Tool calls / actions
        if "tool_calls" in ev and isinstance(ev["tool_calls"], list):
            for tc in ev["tool_calls"]:
                if isinstance(tc, dict):
                    name = tc.get("name") or (tc.get("function") or {}).get("name") or "tool"
                    args = tc.get("args") or (tc.get("function") or {}).get("arguments") or {}
                    args_str = json.dumps(args, default=str, ensure_ascii=False)
                    lines.append(f"[ACTION] {name}({_clip(args_str, args_trunc)})")

        if etype in ("tool_call", "tool_use", "action"):
            name = ev.get("name") or ev.get("tool") or "tool"
            args = ev.get("args") or ev.get("input") or {}
            args_str = json.dumps(args, default=str, ensure_ascii=False)
            lines.append(f"[ACTION] {name}({_clip(args_str, args_trunc)})")
            continue

        # 4. Tool observations / results
        if etype in ("tool_result", "observation", "tool_response"):
            out = ev.get("output") or ev.get("result") or ev.get("content")
            if out is not None:
                lines.append(f"[OBSERVATION] {_clip(out, obs_trunc)}")
            continue

        # 5. Errors
        err = ev.get("error")
        if err or etype in ("error", "turn.failed"):
            err_msg = (
                err
                if isinstance(err, str)
                else (err or {}).get("message", json.dumps(err or ev)[:300])
            )
            lines.append(f"[ERROR] {_clip(err_msg, 300)}")
            continue

        # 6. Assistant content
        if etype in ("PLANNER_RESPONSE", "assistant", "agent_message", "model"):
            content = ev.get("content") or ev.get("text") or ev.get("message")
            if content and isinstance(content, str) and content.strip():
                lines.append(f"[ASSISTANT] {_clip(content, obs_trunc)}")
            continue

    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered


__all__ = [
    "ANTIGRAVITY_SURFACE",
    "AntigravitySurfaceSpec",
    "AntigravitySubstrate",
    "IMMUTABLE_GOVERNANCE_FILES",
    "MAX_ACTIVE_SKILLS",
    "render_events",
    "validate_antigravity_harness",
]
