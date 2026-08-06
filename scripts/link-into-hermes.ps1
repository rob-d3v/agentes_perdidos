# link-into-hermes.ps1 - expose the agentes_perdidos agent library to Hermes Agent.
#
# Hermes discovers skills under <HERMES_HOME>/skills/<category>/<skill>/SKILL.md.
# This script creates one directory junction per agent under the category
# "agentes-perdidos", so the SKILL.md files stay single-sourced in this repo:
# edit here, Hermes sees it immediately. No copy, no drift.
#
# Junctions (not symlinks) are used on purpose - they need no admin rights and
# no Developer Mode on Windows.
#
# ASCII-only on purpose: Windows PowerShell 5.1 decodes a BOM-less .ps1 as the
# system ANSI codepage, which corrupts UTF-8 punctuation into parse errors.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\link-into-hermes.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\link-into-hermes.ps1 -Unlink

param(
    [string]$HermesHome = "",
    [switch]$Unlink
)

$ErrorActionPreference = "Stop"

if (-not $HermesHome) { $HermesHome = $env:HERMES_HOME }
if (-not $HermesHome) { $HermesHome = Join-Path $env:LOCALAPPDATA "hermes" }

$repoRoot  = Split-Path -Parent $PSScriptRoot
$agentsDir = Join-Path $repoRoot "agents"
$category  = Join-Path $HermesHome "skills\agentes-perdidos"

if (-not (Test-Path $agentsDir)) {
    throw "agents/ not found at $agentsDir"
}

if ($Unlink) {
    if (Test-Path $category) {
        # Delete each junction with recursive=$false so we never touch the repo
        # the junction points at.
        Get-ChildItem $category -Force -Directory | ForEach-Object {
            [System.IO.Directory]::Delete($_.FullName, $false)
            Write-Host "unlinked  $($_.Name)"
        }
        Remove-Item $category -Recurse -Force
    }
    Write-Host "done - agentes-perdidos removed from $HermesHome\skills"
    exit 0
}

New-Item -ItemType Directory -Force -Path $category | Out-Null

# A DESCRIPTION.md at the category root is what Hermes shows when listing
# categories; the bundled skill tree uses the same convention.
$readme = @(
    "# agentes-perdidos",
    "",
    "Agent library from $repoRoot, linked in (not copied). Each subdirectory is a",
    "junction to agents/<name>/ - editing a SKILL.md in the repo updates the",
    "skill Hermes loads."
)
Set-Content -Path (Join-Path $category "DESCRIPTION.md") -Value $readme -Encoding utf8

$linked = 0
$skipped = 0
Get-ChildItem $agentsDir -Directory | ForEach-Object {
    if (-not (Test-Path (Join-Path $_.FullName "SKILL.md"))) {
        Write-Host "skip      $($_.Name) (no SKILL.md)"
        $skipped++
        return
    }
    $target = Join-Path $category $_.Name
    if (Test-Path $target) { [System.IO.Directory]::Delete($target, $false) }
    New-Item -ItemType Junction -Path $target -Target $_.FullName | Out-Null
    Write-Host "linked    $($_.Name)"
    $linked++
}

Write-Host ""
Write-Host "$linked skill(s) linked, $skipped skipped -> $category"
Write-Host "Verify with: hermes skills list"
