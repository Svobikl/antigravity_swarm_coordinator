# REA Reference Recon Playbook

On-demand CLI reference for `rea` (`rea-agents`, MIT) when drilling beyond `rea_bridge.py --recon` summaries.

## Target Routing Table

| Target Artifact | Track | Primary REA CLI Command | Notes |
|---|---|---|---|
| Electron `app.asar` or JS/TS bundle | Local CLI | `rea analyze-javascript-application <path> --json` | Static modules, imports, Electron IPC boundaries. |
| Shipped `.app`, dir, ASAR, or exe | Local CLI | `rea audit-release-exposure <path> --json` | Reports exposure checks with stable IDs and remediation. |
| `.NET` managed PE/CLI assembly | Local CLI | `rea inspect-managed-artifact <path> --json` | Inspects types, members, and metadata without execution. |
| SQLite database snapshot | Local CLI | `rea inspect-sqlite-database <path> --json` | Requires Node `24.22.1+` or `26.12.1+` (`DatabaseSync.limits`). |
| Go compiled executable/library | Local CLI | `rea inspect-go-binary <path> --json` | Recovers Go version, module deps, and build settings. |
| Rust compiled binary | Local CLI | `rea inspect-rust-binary <path> --json` | Recovers `cargo-auditable` crate dependency inventory. |
| Remote SaaS / closed cloud app | Dual-Track | `rea_bridge.py --recon "<name>"` -> `FALLBACK_REQUIRED` | Route to `asw-librarian` (`pro`) + `browser` (`flash`). |

## Core CLI Recipes

Save large JSON outputs to disk instead of reading full output inline.

### 1. JavaScript & Electron Applications

```bash
# Full raw Evidence saved to disk (never paste raw output into context)
rea analyze-javascript-application /absolute/path/to/app --json > .asw/evidence/rea-raw-app.json

# Project compact summary (~10 KB even for large Electron apps)
rea inspect-analysis-view '{"source":{"kind":"evidence-file","path":".asw/evidence/rea-raw-app.json"},"view":{"kind":"summary"}}' --json
```

### 2. Summary-First Paging (`inspect-analysis-view`)

Page through modules or findings incrementally using `offset` and `limit`:

```bash
# Page module inventory (32 items per page)
rea inspect-analysis-view '{"source":{"kind":"evidence-file","path":".asw/evidence/rea-raw-app.json"},"view":{"kind":"page","collection":"modules","offset":0,"limit":32}}' --json

# Stream JSONL observation identities without full property blobs
rea inspect-analysis-view '{"source":{"kind":"evidence-file","path":".asw/evidence/rea-raw-app.json"},"view":{"kind":"javascript-facts","property_keys":[],"offset":0,"limit":32}}' --format jsonl
```

### 3. Release Exposure, Managed, SQLite, Go & Rust

```bash
# Release exposure audit for a shipped .app bundle or directory
rea audit-release-exposure /Applications/Example.app --json

# Managed .NET PE/CLI assembly inspection
rea inspect-managed-artifact /absolute/path/Assembly.dll --json

# Quiescent SQLite snapshot: inventory first, then scoped table query
rea inspect-sqlite-database ./snapshot.sqlite --json
rea inspect-sqlite-database ./snapshot.sqlite --table settings --column key --column value --row-limit 20 --json

# Go and Rust static metadata
rea inspect-go-binary /absolute/path/go-app --json
rea inspect-rust-binary /absolute/path/rust-app --json
```

## Node.js Runtime & Wrapper Notes

- REA `inspect-sqlite-database` requires Node `^22.23.4 || ^24.22.1 || >=26.12.1` (`DatabaseSync.limits` API).
- Note that Node `v26.12.0` fails this requirement; `rea_bridge.py --preflight` checks version compatibility automatically.
- `install.py` provisions a SHA256-verified Node `24.x` LTS runtime under `~/.gemini/rea-runtime/` and installs the `rea` wrapper when needed.

## Evidence Discipline

- Separate **Observed Facts** (with Evidence IDs and file paths) from **Inferences** and **Unknowns**.
- Static artifact analysis never proves runtime execution paths.
- Use quiescent SQLite snapshots rather than copying live WAL-active databases.
- Preserve coverage limits (`omitted_fields`, `inapplicable_checks`, `partial` flags) in `.asw/evidence/reference-<slug>.md`.

## Upstream Attribution & Lawful Use Disclaimer

Derived from **REA (Reverse Engineer Anything)**: `https://github.com/morluto/rea` (`rea-agents`).

```text
MIT License

Copyright (c) 2026 morluto

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Lawful & Clean-Room Use:** Use REA strictly for authorized interoperability, security auditing, and clean-room behavioral specification. Do not copy protected code or assets, bypass DRM/licensing/auth/CAPTCHA gates, or run unauthorized scans against third-party services.
