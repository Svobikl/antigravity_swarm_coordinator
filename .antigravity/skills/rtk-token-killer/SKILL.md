---
name: rtk-token-killer
description: Token-optimized CLI proxy (rtk) reducing git, pytest, file-read, and search output tokens by 50-98%.
---

# RTK Token Killer (`rtk`)

## Overview
`rtk` (Token Killer) is a high-performance CLI proxy designed to drastically reduce token consumption when running developer commands in AI-assisted workflows. By pre-filtering verbose outputs, pruning redundant metadata, and compacting syntax trees, `rtk` achieves an **87.8% average token reduction** across git, pytest, file exploration, and JSON inspections without losing critical debugging signal.

## Core Commands & Verbs

### 1. Git Inspection (`50% - 90% Token Reduction`)
Always run git commands through `rtk`:
- **Status:** `rtk git status` (summarizes modified, untracked, and staged files cleanly)
- **Log:** `rtk git log -n 10` (compact one-line format with commit hashes and author dates)
- **Diff:** `rtk git diff HEAD~1 HEAD` or `rtk git diff --staged` (compact diff omitting unchanged hunk context lines)

### 2. Test Execution (`90% - 98% Token Reduction`)
Pre-filter pytest execution to prevent context saturation from verbose test outputs:
- **Pytest:** `rtk pytest tests/` or `rtk pytest tests/test_catalog.py -v`
- Condenses passing test matrices into single-line counters.
- Isolates traceback frames to root cause failure assertions.

### 3. File Discovery & Inspection (`60% - 85% Token Reduction`)
- **Find Files:** `rtk find <pattern>` (compact path listings ignoring `.git`, `node_modules`, `__pycache__`)
- **Aggressive Read:** `rtk read -l aggressive <file_path>` (strips decorative banners, boilerplate comments, and redundant empty lines)
- **File Summary:** `rtk summary <file_path>` (structural AST overview of classes, functions, and exports)

### 4. JSON & Error Filtering
- **JSON Query:** `rtk json <path_to_json>` (filters or minifies structural JSON keys)
- **Error Capture:** `rtk err <command>` (isolates stderr and failure lines, dropping noisy stdout chatter)

## Windows PowerShell & OS Safety Rules
- **NEVER execute `rtk tree` or `rtk find` on Windows (`win32`):**
  Windows includes `tree.com` (`/F /A`) and `C:\Windows\System32\find.exe` which cause parameter format conflicts (`FIND: Parameter format not correct`). Always bypass `rtk tree` and `rtk find` on Windows and use native `Get-ChildItem`, `tree`, or `find` (while rewriting `find` -> `rtk find` on POSIX).
- **PowerShell Stream Redirection:**
  Never use PowerShell `>` or `>>` redirection into files read by tools, as PowerShell may default to UTF-16LE. Use standard UTF-8 outputs or pass target file paths to tools directly.
- **Compound Commands:**
  When executing compound commands in PowerShell (using `;` or `&&`), apply `rtk` to each supported subcommand independently:
  ```powershell
  rtk git status; rtk pytest tests/ -v
  ```
