# BMAD-METHOD V7 5 Orthogonal Review Lenses & 4-Route Cascading Triage

Every non-trivial code change in `asw-review` and `opposition-reviewer` is audited across **5 orthogonal, context-isolated lenses** so that plan bias never blinds the reviewer.

---

## Lens 1: `blind-hunter` (Diff-Only, Zero Plan Bias)
- **Input:** `{diff_file}` only (never read the plan, intent, or implementation notes).
- **Mandatory Finding Floor:** Compute $N = \min(\lfloor\sqrt{\text{kB}} + 1\rfloor, 10)$ where $\text{kB}$ is the UTF-8 byte size of `{diff_file}` divided by $1024$.
- **Method:** Hunt purely from the diff for logic inversions, off-by-one bounds, unclosed resources, silent exception swallowing, race conditions, and state corruption. Report at least $N$ concrete candidate findings (or document every inspected branch if the diff is tiny).

---

## Lens 2: `edge-case-hunter` (Path Walkthrough + `deletion-check` + `claims-check`)
- **Input:** `{diff_file}` and changed source files first; read `## Implementation Notes` (`{claims_file}`) **only after** completing the path walkthrough.
- **Step 2A — Exhaustive Path Walkthrough:** Walk every branching path, null/empty/NaN boundary, enum exhaustiveness, resource/handle lifetime, and callee signature/return-type contract.
- **Step 2B — `deletion-check`:** For every removed or replaced function, branch, guard, or config key in `{diff_file}`, verify whether a caller, fallback contract, or baseline mode still depended on it.
- **Step 2C — `claims-check` (Treat Agent Claims as Unverified Testimony):** Read `## Implementation Notes` and treat every claim made by the implementation agent as an unverified assertion. Attempt to falsify each claim against the exact lines of code and test outputs.

---

## Lens 3: `verification-gap` (Caller Hop Trace, `missing-adoption` & `broken-verification`)
- **Input:** `{diff_file}`, changed source files, and test files.
- **Step 3A — 1–3 Hop Caller/Consumer Trace (`missing-adoption gap`):** Trace every modified or renamed function/component 1–3 hops outward to all callers and sibling call sites. Flag `BMAD_DELETION_OR_ADOPTION_GAP` if one call site was updated while a sibling call site or live worker entrypoint still uses the old signature or deleted symbol.
- **Step 3B — Test Realism Audit (`broken-verification gap`):** For each changed behavior, write a concrete **Demonstration** of how a bug could slip through the current tests. Reject tests that only assert mocks were called, check source-code strings via regex, or assert `is not None` without checking domain output values.

---

## Lens 4: `intent-alignment` (Verbatim User Intent vs. Exercised Surface)
- **Input:** `{verbatim_intent}` (from `<frozen-after-approval>`) and `{diff_file}` (do NOT read the agent's task breakdown).
- **Method:** Compare the surface area and behavior requested by the user's original prompt against the surface area actually modified and tested in `{diff_file}`. Catch cases where the agent completed its own self-authored tasks while missing the user's real runtime surface (e.g., testing an internal helper instead of the live UI/voice/pipeline boundary).

---

## Lens 5: `opus-cross-family` (`Claude Opus 5.5` + Deterministic Local Engine)
- **Command:** `python .antigravity/scripts/invoke_opus_reviewer.py --mode diff-review --files "<changed_files>" --plan ".asw/plans/<slug>.md"`
- **Checks:** Executes all 4 opposition attack vectors, Zero Heuristic Substitution tripwires (`2A..2F`, `3A..3C`, `4A..4F`), `<frozen-after-approval>` tamper check (`BMAD_FROZEN_CONTRACT_VIOLATION`), unresolved triage check (`BMAD_UNRESOLVED_TRIAGE_ITEM`), and deletion/adoption check (`BMAD_DELETION_OR_ADOPTION_GAP`).

---

## 4-Route Cascading Triage Protocol (`## Review Triage Log`)

Every verified finding from Lenses 1–5 must be logged in `## Review Triage Log` and routed by highest blast radius:

1. **`[intent_gap]` (Highest Blast Radius):** The implementation built the wrong thing or violated user intent.
   - **Action:** Revert code to `baseline_revision`, ask the human to clarify, and re-enter `step-02-plan`.
2. **`[bad_plan]` (Plan Design Flaw):** The plan's technical approach was flawed or hit an architectural dead-end.
   - **Action:** Extract `KEEP` notes (any reusable insights/tests), revert code to `baseline_revision`, record the dead-end in `## Plan Change Log` (so the next pass never repeats it), amend the non-frozen plan (`## Code Map` / `## Execution Tasks`), and re-run `step-03-implement`.
3. **`[patch]` (Localized Code/Test Defect):** The plan is sound, but the code or test has a localized bug or missing edge case.
   - **Action:** Re-engage the `step-03` subagent `conversationId` with the exact finding, apply the minimal fix, re-run 3-layer verification, and append `-> RESOLVED` to the `## Review Triage Log` entry.
4. **`[defer]` (Out-of-Scope Improvement):** Valid observation that belongs to a separate goal.
   - **Action:** Append to `.asw/plans/deferred-work.md` and mark `-> DEFERRED` in `## Review Triage Log`.
