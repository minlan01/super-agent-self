[CmdletBinding()]
param(
    [Parameter()]
    [string]$SourceRoot,

    [Parameter()]
    [string]$TargetProject = 'F:\Agents\super-agent-self',

    [Parameter()]
    [switch]$AllowOverwrite
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = $scriptRoot
}

$sourceResolved = (Resolve-Path -LiteralPath $SourceRoot).Path
if (-not (Test-Path -LiteralPath $TargetProject -PathType Container)) {
    throw "Target project is not mounted: $TargetProject"
}

$targetResolved = (Resolve-Path -LiteralPath $TargetProject).Path
$destination = Join-Path $targetResolved '.agent-team'
if ((Test-Path -LiteralPath $destination) -and -not $AllowOverwrite) {
    throw "Destination already exists. Re-run with -AllowOverwrite after reviewing it: $destination"
}

if (-not (Test-Path -LiteralPath $destination)) {
    New-Item -ItemType Directory -Path $destination | Out-Null
}

$sourcePrefix = $sourceResolved.TrimEnd('\') + '\'
Get-ChildItem -LiteralPath $sourceResolved -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($sourcePrefix.Length)
    $targetFile = Join-Path $destination $relative
    $targetDirectory = Split-Path -Parent $targetFile
    if (-not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
    }

    if ((Test-Path -LiteralPath $targetFile) -and -not $AllowOverwrite) {
        throw "Refusing to overwrite existing file: $targetFile"
    }

    if ($AllowOverwrite) {
        Copy-Item -LiteralPath $_.FullName -Destination $targetFile -Force
    }
    else {
        Copy-Item -LiteralPath $_.FullName -Destination $targetFile
    }
}

Write-Host "Agent team copied to $destination"
Write-Host 'Run Validate-Team.ps1 from the copied directory before configuring the tool.'

