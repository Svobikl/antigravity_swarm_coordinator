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

"""Sync verified Harness2 EXPERIENCE.md files into the Obsidian Knowledge Vault.

Resolves the vault path-independently via OBSIDIAN_VAULT_PATH or ~/Documents/AgentMemory.
Extracts transferable lessons and structures them into:
    <vault>/projects/<project>/experiences/<domain>.md
Ensures no grader verdicts leak into knowledge artifacts.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Sequence

# Ensure harness2 package can be imported
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ANTIGRAVITY_DIR = _REPO_ROOT / ".antigravity"
for p in (_REPO_ROOT, _ANTIGRAVITY_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from harness2.core import context, library
except ImportError:
    from .antigravity.harness2.core import context, library

# Expanded markers to catch raw grader verdicts and leaked test scores
EXTENDED_VERDICT_MARKERS = tuple(context.GRADER_VERDICT_MARKERS) + (
    "Verdict: PASS",
    "Verdict: FAIL",
    "Score: 100",
    "Score:",
    "test_pass_rate",
    "passed_count",
    "pass_rate",
    "judge_findings",
)


def resolve_obsidian_vault(vault_dir: Path | str | None = None) -> Path:
    """Resolve the Obsidian Vault root path dynamically without hardcoded user paths."""
    if vault_dir is not None:
        return Path(vault_dir).expanduser().resolve()
    env_vault = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_vault:
        return Path(env_vault).expanduser().resolve()
    return (Path.home() / "Documents" / "AgentMemory").expanduser().resolve()


def parse_experience_fields(exp_text: str) -> dict[str, str]:
    """Extract cue, lesson, evidence, confidence, task_id, and why from EXPERIENCE.md."""
    data: dict[str, str] = {}
    if not exp_text or not isinstance(exp_text, str):
        return data

    # Title / task_id
    m_task = re.search(r"^#\s+([^\r\n]+)", exp_text, re.MULTILINE)
    if m_task:
        data["task_id"] = m_task.group(1).strip()

    # Adopted label
    m_adopted = re.search(r"-\s+adopted:\s*`([^`]+)`", exp_text)
    if m_adopted:
        data["adopted"] = m_adopted.group(1).strip()

    # Why chosen
    m_why = re.search(
        r"##\s+Why this was chosen\s*\n(.*?)(?=\n##|\Z)", exp_text, re.DOTALL | re.IGNORECASE
    )
    if m_why:
        data["why"] = m_why.group(1).strip()

    # Transferable lesson fields
    for field in ("cue", "lesson", "evidence", "confidence"):
        m_field = re.search(
            rf"-\s+\*\*{field}\*\*:\s*([^\r\n]+)", exp_text, re.IGNORECASE
        )
        if m_field:
            data[field] = m_field.group(1).strip()

    return data


def has_experience(experience: dict | str | None) -> bool:
    """Check if experience content is verified and decision-complete."""
    if experience is None:
        return False
    if isinstance(experience, str):
        if not experience.strip():
            return False
        # Must explicitly contain cue and lesson bullets
        if "- **cue**:" not in experience or "- **lesson**:" not in experience:
            return False
        fields = parse_experience_fields(experience)
        return bool(fields.get("cue") and fields.get("lesson"))
    if isinstance(experience, dict):
        return bool(
            experience.get("cue")
            and str(experience["cue"]).strip()
            and experience.get("lesson")
            and str(experience["lesson"]).strip()
        )
    return False


# Monkey-patch library.has_experience so that library methods accept text seamlessly
_orig_library_has_experience = library.has_experience


def _patched_library_has_experience(exp: dict | str | None) -> bool:
    if isinstance(exp, str):
        return has_experience(exp)
    return _orig_library_has_experience(exp)


library.has_experience = _patched_library_has_experience


def assert_no_grader_verdicts(
    target: Path | str, markers: Sequence[str] = EXTENDED_VERDICT_MARKERS
) -> None:
    """Validate that target (string, file, or directory) does not leak grader verdicts."""
    if isinstance(target, str):
        # Check if it's an existing directory
        try:
            p = Path(target)
            if p.is_dir():
                _scan_dir_for_verdicts(p, markers)
                return
            if p.is_file():
                _scan_file_for_verdicts(p, markers)
                return
        except (OSError, ValueError):
            pass
        # Plain text
        _scan_text_for_verdicts(target, markers)
        return

    p = Path(target)
    if p.is_dir():
        _scan_dir_for_verdicts(p, markers)
    elif p.is_file():
        _scan_file_for_verdicts(p, markers)


def _scan_text_for_verdicts(text: str, markers: Sequence[str]) -> None:
    for m in markers:
        if m.lower() in text.lower():
            where = text.lower().index(m.lower())
            snippet = text[max(0, where - 30) : where + 60]
            raise ValueError(
                f"grader verdict would leak into knowledge vault: matched marker {m!r} "
                f"near {snippet!r}"
            )


def _scan_file_for_verdicts(path: Path, markers: Sequence[str]) -> None:
    for m in markers:
        if m.lower() in path.name.lower():
            raise ValueError(
                f"grader verdict marker {m!r} matched in filename: {path.name!r}"
            )
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        _scan_text_for_verdicts(content, markers)
    except OSError:
        pass


def _scan_dir_for_verdicts(root: Path, markers: Sequence[str]) -> None:
    for item in root.rglob("*"):
        if item.is_file():
            _scan_file_for_verdicts(item, markers)


# Monkey-patch context.assert_no_grader_verdicts so any direct call is protected
_orig_context_assert_no_grader_verdicts = context.assert_no_grader_verdicts


def _patched_context_assert_no_grader_verdicts(
    target: Path | str, markers: Sequence[str] = EXTENDED_VERDICT_MARKERS
) -> None:
    assert_no_grader_verdicts(target, markers=markers)


context.assert_no_grader_verdicts = _patched_context_assert_no_grader_verdicts


def sync_experience_file(
    exp_path: Path,
    project: str,
    domain: str | None = None,
    vault_dir: Path | str | None = None,
) -> Path | None:
    """Sync a single verified EXPERIENCE.md file into the Obsidian vault domain note."""
    exp_path = Path(exp_path)
    if not exp_path.is_file():
        return None

    content = exp_path.read_text(encoding="utf-8")

    # 1. Assert tripwire: no grader verdicts allowed
    assert_no_grader_verdicts(content)

    # 2. Assert verified experience
    if not has_experience(content):
        return None

    fields = parse_experience_fields(content)
    task_id = fields.get("task_id")
    if not task_id:
        # Infer task_id from directory structure: .../harnesses/<task_id>/EXPERIENCE.md
        if exp_path.parent.name and exp_path.parent.parent.name == "harnesses":
            task_id = exp_path.parent.name
        else:
            task_id = "unknown-task"

    if domain is None:
        # Infer domain from path: <library>/<mode>/<domain>/harnesses/<task_id>/EXPERIENCE.md
        parts = exp_path.parts
        if "harnesses" in parts:
            h_idx = parts.index("harnesses")
            if h_idx > 0:
                domain = parts[h_idx - 1]
    domain = (domain or "general").strip()

    vault = resolve_obsidian_vault(vault_dir)
    target_dir = vault / "projects" / project / "experiences"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{domain}.md"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    task_section = _format_task_section(task_id, fields)

    if target_file.is_file():
        existing = target_file.read_text(encoding="utf-8")
        updated_note = _merge_task_into_note(existing, task_id, task_section, project, domain, now_iso)
    else:
        updated_note = _create_new_note(project, domain, now_iso, task_section)

    target_file.write_text(updated_note, encoding="utf-8")
    return target_file


def _format_task_section(task_id: str, fields: dict[str, str]) -> str:
    lines = [f"### {task_id}"]
    if fields.get("adopted"):
        lines.append(f"- **Adopted**: `{fields['adopted']}`")
    if fields.get("why"):
        lines.append(f"- **Why Chosen**: {fields['why']}")
    lines.append("- **Transferable Lesson**:")
    for f in ("cue", "lesson", "evidence", "confidence"):
        val = fields.get(f)
        if val:
            lines.append(f"  - **{f}**: {val}")
    lines.append("")
    return "\n".join(lines)


def _create_new_note(project: str, domain: str, now_iso: str, initial_task_section: str) -> str:
    return (
        "---\n"
        "type: harness-experience\n"
        f"project: {project}\n"
        f"domain: {domain}\n"
        f"updated: {now_iso}\n"
        "---\n\n"
        f"# Harness Experiences — {domain}\n\n"
        f"Continual adaptation experiences captured by Harness² for domain `{domain}` in project `{project}`.\n\n"
        "## Tasks\n\n"
        f"{initial_task_section}\n"
    )


def _merge_task_into_note(
    existing: str, task_id: str, task_section: str, project: str, domain: str, now_iso: str
) -> str:
    # Update frontmatter timestamp
    note = re.sub(
        r"^updated:\s*[^\r\n]+",
        f"updated: {now_iso}",
        existing,
        flags=re.MULTILINE,
    )
    if "updated:" not in note:
        note = re.sub(
            r"^---\n",
            f"---\nupdated: {now_iso}\n",
            note,
            count=1,
        )

    # Check if task already exists
    pattern = rf"(###\s+{re.escape(task_id)}\b.*?)(?=\n###|\Z)"
    if re.search(pattern, note, re.DOTALL):
        note = re.sub(pattern, task_section.strip() + "\n", note, flags=re.DOTALL)
    else:
        if "## Tasks" in note:
            note = re.sub(
                r"(##\s+Tasks[^\r\n]*\n)",
                rf"\1\n{task_section}\n",
                note,
                count=1,
            )
        else:
            note = note.rstrip() + f"\n\n## Tasks\n\n{task_section}\n"

    return note


def sync_library_to_obsidian(
    library_root: Path | str,
    project: str,
    vault_dir: Path | str | None = None,
) -> list[Path]:
    """Scan library root for all EXPERIENCE.md files and sync verified ones into vault."""
    root = Path(library_root).expanduser().resolve()
    if not root.is_dir():
        return []

    synced_notes: set[Path] = set()

    for exp_file in sorted(root.rglob("EXPERIENCE.md")):
        # First verify no grader verdicts (raises ValueError on leaks)
        content = exp_file.read_text(encoding="utf-8")
        assert_no_grader_verdicts(content)

        # Skip unverified
        if not has_experience(content):
            continue

        res = sync_experience_file(exp_file, project=project, vault_dir=vault_dir)
        if res:
            synced_notes.add(res)

    return sorted(synced_notes)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True, help="Path to library directory")
    parser.add_argument("--project", type=str, required=True, help="Project name in Obsidian vault")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Explicit Obsidian vault path")
    args = parser.parse_args(argv)

    synced = sync_library_to_obsidian(args.library, project=args.project, vault_dir=args.vault_dir)
    print(f"Synced {len(synced)} experience note(s) to Obsidian vault for project '{args.project}'.")
    for note in synced:
        print(f"  - {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
