---
name: token-economizer
description: Zero-API environment micro-skills (EnvFacts), TurnGuard loop protection, and cache-aware token accounting.
---

# TokenEconomizer (`token_economizer.py`)

Zero-API-overhead environment micro-skill distillation, live edit-test loop protection, and cache-aware effective token benchmarking for Antigravity Swarm Coordinator.

## Core Capabilities
- **EnvFacts Micro-Skills (`AD-1`):** Learns recurring repository environment repairs (`form_repair`, `env_value`, `arg_repair`, `absent_tool`, `boundary`, `win_shell_repair`) from Antigravity JSONL transcripts (`K_PROMOTE=3`, `GAMMA=0.8`, `LAMBDA=5.0`, `FIRE_GATE=0.40`, `CONTRADICT_STREAK=2`, `<= 150` tokens).
- **Hook Channel Hygiene (`SessionStart` / `PreInvocation`):** Injects learned `EnvFacts` once via KV-cached `systemMessage` at `SessionStart`, suppresses cascading `ASW .* MODE ENABLED!` re-injections, and emits single-turn `ephemeralMessage` redirects.
- **TurnGuard & p90 EnvelopeTracker:** Detects stagnant mid-turn edit-test spirals (`SpiralState` MD5 failure signatures + `decision_router.py --mode judge-loop --compact`) with zero false nudges on productive multi-file grinds.
- **Cache-Aware Accounting:** Measures both raw tokens and cache-weighted `effective_tokens` (`1.0 * input + 0.05 * cache_read + 5.0 * output` for Gemini 4 / Claude Opus 5.5).

## CLI Commands

```bash
python .antigravity/scripts/token_economizer.py --status --json
python .antigravity/scripts/token_economizer.py --fold <transcript.jsonl> --repo . --json
python .antigravity/scripts/token_economizer.py --microskills --repo . --json
python .antigravity/scripts/token_economizer.py --forget <fact_id> --repo . --json
python .antigravity/scripts/token_economizer.py --unforget <fact_id> --repo . --json
python .antigravity/scripts/token_economizer.py --benchmark --output .asw/evidence/token-economizer-ab-report.json
```

## Vault Sync & Feature-Flag Isolation
- **Obsidian Vault Sync:** `python .antigravity/scripts/memory_manager.py --sync-envfacts --project-path .` writes active facts to `Environment Micro-Skills.md` and includes them in `--recall`.
- **Negative-State Disable Switch:** Set `ASW_TOKEN_ECONOMIZER_ENABLED=0` (or `"token_economizer_enabled": false` in `.antigravity/decision_config.json`) to short-circuit all hooks, `TurnGuard`, `EnvFacts` recall/sync, and CLI commands with zero disk writes (`{"enabled": false, "status": "disabled"}`).
