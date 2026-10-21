<#
.SYNOPSIS
    Installs and restores Antigravity Swarm Coordinator configuration, 200 curated skills, and plugins (Windows).

.DESCRIPTION
    Restores the full Antigravity Swarm Coordinator setup:
    1. Global entry point prompts (~/.gemini/GEMINI.md and ~/.agents/AGENTS.md)
    2. Global 200-skill Multi-Domain Golden Catalog (~/.gemini/config/skills, ~/.gemini/antigravity-ide/skills, ~/.agents/skills)
    3. Antigravity Swarm (ASW) plugin & Claude Opus 5.5 subagent TOMLs (~/.gemini/config/plugins/antigravity-swarm)
    4. Optional: Deploys .antigravity framework into a target project repository (-TargetRepoPath).
#>

[CmdletBinding()]
param (
    [string]$TargetRepoPath = "",
    [switch]$SkipGlobalPrompt,
    [switch]$SkipGlobalSkills,
    [switch]$SkipPlugin,
    [switch]$CleanSkills
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPy = Join-Path $ScriptDir "install.py"

$PyArgs = @($InstallPy)
if ($TargetRepoPath -ne "") { $PyArgs += @("--target-repo", $TargetRepoPath) }
if ($SkipGlobalPrompt)      { $PyArgs += "--skip-prompt" }
if ($SkipGlobalSkills)      { $PyArgs += "--skip-skills" }
if ($SkipPlugin)            { $PyArgs += "--skip-plugin" }
if ($CleanSkills)           { $PyArgs += "--clean-skills" }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Swarm Coordinator Setup (Windows / PS)     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

& python @PyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installation failed with exit code $LASTEXITCODE"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Setup complete! Swarm Coordinator + 200 skills ready.    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
