# Antigravity RTK (Token Killer) Rules

Mandatory pre-filtering directives for developer CLI commands:

1. **Mandatory RTK CLI Proxy (`rtk-token-killer`):**
   - Route `git status`, `git log`, and `git diff` through `rtk git ...` (50% to 90% token reduction).
   - Route `pytest` and `python -m pytest` through `rtk pytest ...` (90% to 98% token reduction).
   - Route file discovery and inspection through `rtk find <pattern>`, `rtk read -l aggressive <path>`, and `rtk json <path>`.
2. **Windows Platform Tree Guard:**
   - NEVER execute `rtk tree` on Windows (`win32`). Windows `tree.com` parameter conflicts trigger errors. Preserve native `tree`.
3. **Compound Operator Resilience:**
   - Multi-segment commands (`;`, `&&`, `||`, `|`) must apply `rtk` per supported subcommand while preserving quotes and shell logic.
