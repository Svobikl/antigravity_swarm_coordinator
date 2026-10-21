---
name: asw-harness-adapt
description: Executes Harness2 recursive Propose-Probe-Compose-Select-Reflect adaptation sweeps.
---

# ASW Harness² Adaptation Engine

## Purpose
Execute Harness² recursive self-improvement sweeps across Antigravity and Claude Code agent architectures. Coordinate the Tri-Model Cross-Family Cognitive Architecture, run closed-loop adaptation sweeps (`Propose -> Probe -> Compose -> Select -> Reflect`), and sync verified transferable lessons into the Obsidian Knowledge Vault without grader verdict leakage.

## Tri-Model Cognitive Routing Matrix
Every Harness² adaptation cycle enforces strict cross-family cognitive separation of duties:

| Tier | Role | Assigned Model | Substrate / Channel |
|---|---|---|---|
| **Tier 1A** | Proposer & Synthesizer | **`Gemini 4 Argon (High)`** (`Model="pro"`) | `antigravity/gemini-4-argon` |
| **Tier 1B** | Blind Candidate Selector & Reflector | **`Claude Opus 5.5`** (Native Antigravity) | `antigravity_opus/claude-opus-5-5` |
| **Tier 2** | Bounded Probe Executor & Test Runner | **`Gemini 3.8 Flash (High)`** (`Model="flash"`) | `opencode` / `antigravity` executor |

### Cognitive Separation Invariant
The primary proposer (`Gemini 4 Argon High`) MUST NEVER grade or select its own candidate proposals. Blind selection is owned by `Claude Opus 5.5` evaluating anonymized deliverables and trajectories to prevent self-confirmation bias.

## 5-Phase Adaptation Lifecycle
1. **Propose (Tier 1A - Gemini 4 Argon High)**:
   - Proposes candidate harness mutations across three invariant-preserving vectors:
     - `INV`: Invariant-hardening adaptations (governance rules, budget tripwires, shell safety).
     - `DOM`: Domain-specialized skill prompts and toolchains.
     - `COMPOSE`: Harmonized multi-component merges.
2. **Probe (Tier 2 - Gemini 3.8 Flash High)**:
   - Rolls out candidate harnesses in isolated ephemeral workspaces/worktrees.
   - Captures full observable trajectories and deliverables.
3. **Compose (Tier 1A - Gemini 4 Argon High)**:
   - Performs cross-candidate pairwise and multi-way synthesis on promising candidates.
4. **Select (Tier 1B - Claude Opus 5.5)**:
   - Evaluates anonymized candidate deliverables and trajectories against task requirements.
   - Selects winning configuration (`<why>...</why>`) and records choice.
5. **Reflect (Tier 1A + 1B)**:
   - Generates transferable lesson (`cue`, `lesson`, `evidence`, `confidence`) stored in `EXPERIENCE.md`.
   - Tripwire validation ensures zero grader verdict leaks (`assert_no_grader_verdicts`).

## Continual Experience Sync to Obsidian Knowledge Vault
Continual adaptation knowledge is synchronized into persistent long-term memory:
- **Path-Independent Resolution**: The Obsidian Vault root is dynamically discovered via `resolve_obsidian_vault()` honoring `OBSIDIAN_VAULT_PATH` or defaulting to `Path.home() / "Documents" / "AgentMemory"`. Hardcoded user paths are strictly prohibited.
- **Target Note**: `<vault>/projects/<project>/experiences/<domain>.md`.
- **Note Schema**:
  - YAML frontmatter with `type: harness-experience`, `project`, `domain`, and ISO `updated` timestamp.
  - Granular sections per `task_id` detailing adopted harness, why chosen, and transferable lessons.
- **Tripwire Gate**: Sync refuses any file that contains raw grader verdicts (`Score:`, `Verdict: PASS/FAIL`, `test_pass_rate`).

## Canonical Tooling & Scripts
- Adaptation CLI:
  ```bash
  python .antigravity/scripts/run_harness_adapt.py --demo --project <project> --output <dir> --sync-obsidian
  ```
- Standalone Experience Sync CLI:
  ```bash
  python .antigravity/scripts/sync_harness_experience.py --library <library_dir> --project <project>
  ```
