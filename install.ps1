<#
.SYNOPSIS
    Installs and restores Antigravity Swarm Coordinator configuration, 200 curated skills, plugins, and enforced Obsidian Knowledge Vault (Windows).

.DESCRIPTION
    Restores the full Antigravity Swarm Coordinator setup:
    1. Global entry point prompts (~/.gemini/GEMINI.md and ~/.agents/AGENTS.md)
    2. Global 200-skill Multi-Domain Golden Catalog (~/.gemini/config/skills, ~/.gemini/antigravity-ide/skills, ~/.agents/skills)
    3. Antigravity Swarm (ASW) plugin & Claude Opus 5.5 subagent TOMLs (~/.gemini/config/plugins/antigravity-swarm)
    4. Enforced local Obsidian Self-Learning Knowledge Vault (~/Documents/AgentMemory) + project indexing
    5. Optional: Deploys .antigravity framework into a target project repository (-TargetRepoPath).
#>

[CmdletBinding()]
param (
    [string]$TargetRepoPath = "",
    [string]$VaultDir = "",
    [switch]$SkipGlobalPrompt,
    [switch]$SkipGlobalSkills,
    [switch]$SkipPlugin,
    [switch]$SkipVault,
    [switch]$CleanSkills,
    [switch]$InstallObsidianApp
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallPy = Join-Path $ScriptDir "install.py"

$PyArgs = @($InstallPy)
if ($TargetRepoPath -ne "") { $PyArgs += @("--target-repo", $TargetRepoPath) }
if ($VaultDir -ne "")       { $PyArgs += @("--vault-dir", $VaultDir) }
if ($SkipGlobalPrompt)      { $PyArgs += "--skip-prompt" }
if ($SkipGlobalSkills)      { $PyArgs += "--skip-skills" }
if ($SkipPlugin)            { $PyArgs += "--skip-plugin" }
if ($SkipVault)             { $PyArgs += "--skip-vault" }
if ($CleanSkills)           { $PyArgs += "--clean-skills" }
if ($InstallObsidianApp)    { $PyArgs += "--install-obsidian-app" }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Swarm Coordinator Setup (Windows / PS)     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

& python @PyArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installation failed with exit code $LASTEXITCODE"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Setup complete! Swarm Coordinator + Obsidian Vault ready." -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
