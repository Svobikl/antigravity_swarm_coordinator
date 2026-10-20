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

"""Run Harness2 Recursive Self-Improvement Adaptation Workflow with Obsidian Vault Sync.

Executes the full adaptation cycle (Propose -> Probe -> Compose -> Select -> Reflect)
with Tri-Model routing:
  - Tier 1A: Gemini 4 Argon High (proposer="antigravity"/gemini-4-argon)
  - Tier 1B: Claude Opus 5.5 (selector="antigravity_opus"/claude-opus-5-5)
  - Tier 2:  Gemini 3.8 Flash High (executor/probes/test runner)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add repo root and .antigravity to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ANTIGRAVITY_DIR = _REPO_ROOT / ".antigravity"
_SCRIPTS_DIR = _ANTIGRAVITY_DIR / "scripts"
for p in (_REPO_ROOT, _ANTIGRAVITY_DIR, _SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from harness2.core.schedule import mode_token, run_domain
    from harness2.core.spec import ChannelSpec
    from harness2.demo import DemoAdapter, DemoProposer
    from sync_harness_experience import resolve_obsidian_vault, sync_library_to_obsidian
except ImportError:
    from .antigravity.harness2.core.schedule import mode_token, run_domain
    from .antigravity.harness2.core.spec import ChannelSpec
    from .antigravity.harness2.demo import DemoAdapter, DemoProposer
    from .antigravity.scripts.sync_harness_experience import (
        resolve_obsidian_vault,
        sync_library_to_obsidian,
    )


def run_adaptation(
    *,
    demo: bool = True,
    project: str = "lucid-volta",
    domain: str = "accounting",
    mode: str = "both",
    k: int = 2,
    output: Path | str = "runs/adapt",
    sync_obsidian: bool = False,
    vault_dir: Path | str | None = None,
) -> dict:
    """Execute adaptation workflow and optionally sync experiences to Obsidian vault."""
    root = Path(output).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    modes = ("agg", "seq") if mode == "both" else (mode_token(mode),)
    library_root = root / "library" / f"k{k}"

    if demo:
        adapter = DemoAdapter(root)
        # Configure Tri-Model channels explicitly
        proposer_channel = ChannelSpec("antigravity", "gemini-4-argon")
        selector_channel = ChannelSpec("antigravity_opus", "claude-opus-5-5")
        adapter.spec.channels["proposer"] = proposer_channel
        adapter.spec.channels["selector"] = selector_channel

        proposer = DemoProposer(proposer_channel)
        selector_prop = DemoProposer(selector_channel)

        tasks = adapter.tasks()
        target_domain = domain if domain else adapter.domain_of(tasks[0])

        result = run_domain(
            target_domain,
            tasks,
            k,
            adapter=adapter,
            prop=proposer,
            selector_prop=selector_prop,
            runs_root=adapter.spec.runs_root,
            library_root=library_root,
            modes=modes,
        )
        result["execution_count"] = adapter.execution_count
        result["editor_calls"] = len(proposer._calls)
        result["project"] = project
        result["channels"] = {
            "proposer": f"{proposer_channel.kind}/{proposer_channel.model}",
            "selector": f"{selector_channel.kind}/{selector_channel.model}",
        }
    else:
        # Non-demo substrate execution placeholder
        raise NotImplementedError("Live non-demo substrate adaptation requires active model credentials")

    # Write summary.json and demo.json reports
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (root / "demo.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # Obsidian Vault Experience Sync
    if sync_obsidian:
        synced_notes = sync_library_to_obsidian(
            library_root,
            project=project,
            vault_dir=vault_dir,
        )
        result["obsidian_synced_notes"] = [str(p) for p in synced_notes]
        summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", default=False, help="Run deterministic demo adaptation")
    parser.add_argument("--project", type=str, default="lucid-volta", help="Project identifier for vault notes")
    parser.add_argument("--domain", type=str, default="accounting", help="Domain to adapt")
    parser.add_argument("--mode", choices=("parallel", "sequential", "both"), default="both", help="Adaptation recursion mode")
    parser.add_argument("--k", type=int, default=2, help="Number of candidate harnesses per step")
    parser.add_argument("--output", type=Path, default=Path("runs/adapt"), help="Output directory")
    parser.add_argument("--sync-obsidian", action="store_true", default=False, help="Sync experiences to Obsidian vault")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Explicit Obsidian vault directory")

    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be positive")

    result = run_adaptation(
        demo=args.demo,
        project=args.project,
        domain=args.domain,
        mode=args.mode,
        k=args.k,
        output=args.output,
        sync_obsidian=args.sync_obsidian,
        vault_dir=args.vault_dir,
    )

    print(
        f"Harness2 adaptation complete: {result['done']} succeeded, {result['failed']} failed.\n"
        f"Summary written to: {args.output / 'summary.json'}"
    )
    if args.sync_obsidian:
        print(f"Synced {len(result.get('obsidian_synced_notes', []))} note(s) into Obsidian vault.")
    return int(result["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
