---
name: rea-reference-recon
description: Extracts evidence-backed behavior and UI specs from reference apps/SW via REA CLI.
---

# REA Reference-Product Recon

Extract observable workflows, state transitions, and UI architecture from shipped software or remote SaaS products before planning or coding.

## When to Activate

- Activate when the user requests behavior or UI modeled on another product (*"works/looks like X"*, *"similar to Y"*, *"fungovalo/vypadalo jako X"*, *"podobná XY"*).
- Activate when inspecting a shipped binary, `.app` bundle, `.asar`, Electron/JS tree, SQLite snapshot, or release package.
- Skip for ordinary analysis of a complete local source repository. Use normal repo search and file reads instead.

## Step 0 — Opt-In Scope Check (`ask_question`)

Reference analogies (*"chci funkcionalitu jako X"*, *"podobná XY"*, *"looks like Y"*) are often figurative.

- **Figurative Analogy (`ask_confirmation == true`):** Call `ask_question` first (bundle into Spec-Kit Clarify when active):
  1. `(Recommended)` **Basic model & docs lookup (skip REA)** — use general knowledge without `rea_bridge.py`.
  2. **Full REA reverse-engineering** — run `rea_bridge.py --recon` and lock `### Reference Product Parity`.
- **Explicit REA or Artifact (`ask_confirmation == false`):** On `rea`, `--with-rea`, `.app`, or `.asar`, run `Step 1` directly.

## Step 1 — CLI-First Evidence Extraction (`0` Idle MCP Tokens)

Never register an always-on global REA MCP server or paste raw multi-megabyte Evidence JSON into prompt context.
Invoke the token-bounded CLI bridge first:

```bash
python .antigravity/scripts/rea_bridge.py --recon "<target>" --output ".asw/evidence/reference-<slug>.md"
```

- Check runtime readiness first when needed with `--preflight` or target resolution with `--resolve "<target>"`.
- The bridge saves full raw output to `.asw/evidence/rea-raw-<slug>.json` and writes a compact `TOON`-formatted summary to `.asw/evidence/reference-<slug>.md`.
- Read only the compact markdown brief (`.asw/evidence/reference-<slug>.md`) during planning and implementation.
- For large JavaScript/Electron graphs, inspect retained raw JSON lazily via summary and paged views rather than full reads.

## Step 2 — Dual-Track Fallback (`FALLBACK_REQUIRED`)

When no local binary, `.app`, `.asar`, or bundle exists on disk, `rea_bridge.py` emits `FALLBACK_REQUIRED` with `track: "remote_saas_fallback"`.

1. Dispatch `asw-librarian` (`Model="pro"`) to inspect official product documentation, public UI walkthroughs, and API semantics.
2. When a live web surface is reachable without bypassing auth or anti-bot gates, dispatch `browser` (`Model="flash"`) to record observable workflows.
3. Populate `.asw/evidence/reference-<slug>.md` with:
   - Core user workflows and navigation hierarchy.
   - Interactive UI states (empty, loading, active, keyboard shortcuts, error states).
   - Edge cases, boundaries, and residual unknowns.

## Step 3 — Clean-Room `### Reference Product Parity` Contract

Before coding, lock observable reference behavior inside `<!-- <frozen-after-approval> -->` of `.asw/plans/<slug>.md` under `### Reference Product Parity`:

- **Observable Workflows:** Required user journeys, command inputs, and expected state transitions.
- **UI & UX Ergonomics:** Layout hierarchy, interaction density, keyboard navigation, and feedback patterns.
- **Verification Mapping:** Map parity claims to `I/O & Edge-Case Matrix` rows (`M1..Mn`).
- **Observations vs. Unknowns:** Separate verified artifact facts from inferred design choices and unverified gaps.

## Legal & Clean-Room Boundaries

- Never copy proprietary source code, copyrighted artwork, brand logos, icons, or licensed assets.
- Never circumvent DRM, license checks, authentication gates, or CAPTCHAs.
- Never use cracked disassemblers or unauthorized keys. Native engines (Ghidra, Hopper, IDA, Kuna) require valid local licenses.
- Analyze only software and endpoints you own or are authorized to examine.

## On-Demand Reference Playbook

Read [references/recon-playbook.md](references/recon-playbook.md) only when you need direct `rea` CLI subcommands, summary-first `inspect-analysis-view` paging, target routing, or MIT license details.
