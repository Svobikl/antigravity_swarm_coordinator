<#
.SYNOPSIS
    Installs and restores Antigravity Swarm Coordinator configuration, skills, and plugins.

.DESCRIPTION
    This script restores the default Antigravity Swarm Coordinator setup:
    1. Global entry point prompt (~/.gemini/GEMINI.md)
    2. Global skills catalog (~/.gemini/config/skills)
    3. Antigravity Swarm (ASW) plugin (~/.gemini/config/plugins/antigravity-swarm)
    4. Optional: Installs local .antigravity framework into a target project repository.

.PARAMETER TargetRepoPath
    Optional path to a target repository where .antigravity should be deployed.

.PARAMETER SkipGlobalPrompt
    Skip installing ~/.gemini/GEMINI.md

.PARAMETER SkipGlobalSkills
    Skip copying skills to ~/.gemini/config/skills

.PARAMETER SkipPlugin
    Skip copying plugins/antigravity-swarm to ~/.gemini/config/plugins

.EXAMPLE
    .\install.ps1
    Installs global prompt, skills, and plugin.

.EXAMPLE
    .\install.ps1 -TargetRepoPath "C:\MyProject"
    Installs global components plus copies .antigravity into C:\MyProject.
#>

[CmdletBinding()]
param (
    [string]$TargetRepoPath = "",
    [switch]$SkipGlobalPrompt,
    [switch]$SkipGlobalSkills,
    [switch]$SkipPlugin
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GeminiDir = Join-Path $HOME ".gemini"
$ConfigDir = Join-Path $GeminiDir "config"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Swarm Coordinator Setup & Restore Script   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Global Entry Point Prompt (~/.gemini/GEMINI.md)
if (-not $SkipGlobalPrompt) {
    Write-Host "`n[1/3] Configuring Global Entry Point Prompt..." -ForegroundColor Yellow
    if (-not (Test-Path $GeminiDir)) {
        New-Item -ItemType Directory -Path $GeminiDir -Force | Out-Null
    }
    
    $SourcePrompt = Join-Path $ScriptDir "global_entrypoint\GEMINI.md"
    $DestPrompt = Join-Path $GeminiDir "GEMINI.md"
    
    if (Test-Path $DestPrompt) {
        $BackupPrompt = Join-Path $GeminiDir "GEMINI.md.bak"
        Copy-Item -Path $DestPrompt -Destination $BackupPrompt -Force
        Write-Host "  -> Existing GEMINI.md backed up to $BackupPrompt" -ForegroundColor Gray
    }
    
    Copy-Item -Path $SourcePrompt -Destination $DestPrompt -Force
    Write-Host "  -> Successfully deployed to: $DestPrompt" -ForegroundColor Green
}

# 2. Global Skills (~/.gemini/config/skills)
if (-not $SkipGlobalSkills) {
    Write-Host "`n[2/3] Installing Global Swarm & Governance Skills..." -ForegroundColor Yellow
    $SkillsDestDir = Join-Path $ConfigDir "skills"
    if (-not (Test-Path $SkillsDestDir)) {
        New-Item -ItemType Directory -Path $SkillsDestDir -Force | Out-Null
    }
    
    $SkillsSourceDir = Join-Path $ScriptDir "core_framework\skills"
    $skills = Get-ChildItem -Path $SkillsSourceDir -Directory
    
    foreach ($s in $skills) {
        $target = Join-Path $SkillsDestDir $s.Name
        Copy-Item -Path $s.FullName -Destination $target -Recurse -Force
        Write-Host "  -> Installed skill: $($s.Name)" -ForegroundColor Gray
    }
    Write-Host "  -> Successfully installed $($skills.Count) skills to: $SkillsDestDir" -ForegroundColor Green
}

# 3. Antigravity Swarm Plugin (~/.gemini/config/plugins/antigravity-swarm)
if (-not $SkipPlugin) {
    Write-Host "`n[3/3] Installing Antigravity Swarm (ASW) Plugin..." -ForegroundColor Yellow
    $PluginsDestDir = Join-Path $ConfigDir "plugins"
    $AswDestDir = Join-Path $PluginsDestDir "antigravity-swarm"
    if (-not (Test-Path $PluginsDestDir)) {
        New-Item -ItemType Directory -Path $PluginsDestDir -Force | Out-Null
    }
    
    $AswSourceDir = Join-Path $ScriptDir "plugins\antigravity-swarm"
    Copy-Item -Path $AswSourceDir -Destination $PluginsDestDir -Recurse -Force
    Write-Host "  -> Successfully deployed ASW plugin to: $AswDestDir" -ForegroundColor Green
}

# 4. Optional Target Repository Deployment
if ($TargetRepoPath -ne "") {
    Write-Host "`n[+] Deploying .antigravity into Target Repository: $TargetRepoPath" -ForegroundColor Yellow
    if (-not (Test-Path $TargetRepoPath)) {
        New-Item -ItemType Directory -Path $TargetRepoPath -Force | Out-Null
    }
    
    $TargetAntigravity = Join-Path $TargetRepoPath ".antigravity"
    $SourceAntigravity = Join-Path $ScriptDir ".antigravity"
    
    Copy-Item -Path $SourceAntigravity -Destination $TargetRepoPath -Recurse -Force
    Write-Host "  -> Successfully copied .antigravity framework to: $TargetAntigravity" -ForegroundColor Green
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host " Setup complete! Swarm Coordinator is ready for use.     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
