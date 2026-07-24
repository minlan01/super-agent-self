[CmdletBinding()]
param(
    [Parameter()]
    [string]$TeamRoot
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($TeamRoot)) {
    $TeamRoot = $scriptRoot
}
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
    param([Parameter(Mandatory)][string]$Message)
    $failures.Add($Message)
}

function Read-Utf8Json {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing JSON file: $Path"
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Invalid UTF-8 JSON in $Path : $($_.Exception.Message)"
    }
}

function Convert-CodePoints {
    param([Parameter(Mandatory)][int[]]$Codes)
    return -join ($Codes | ForEach-Object { [char]$_ })
}

$config = Read-Utf8Json -Path (Join-Path $TeamRoot 'team.config.json')
$runtime = Read-Utf8Json -Path (Join-Path $TeamRoot 'runtime-policy.json')

if ($runtime.prompt_encoding -ne 'utf-8') {
    Add-Failure 'prompt_encoding must be utf-8.'
}

if ($config.max_parallel_agents -gt 4 -or $runtime.budgets.max_parallel_agents -gt 4) {
    Add-Failure 'Maximum parallel agents must not exceed 4.'
}

if (-not $runtime.security.production_requires_human_approval) {
    Add-Failure 'Production operations must require human approval.'
}

if ($runtime.risk_levels.R3.approval -notmatch '^human_') {
    Add-Failure 'R3 approval must be explicitly human-bound.'
}

if (-not $runtime.security.prohibit_self_review) {
    Add-Failure 'Runtime policy must prohibit self-review.'
}

$agents = @($config.agents)
if ($agents.Count -eq 0) {
    Add-Failure 'At least one agent is required.'
}

$duplicateIds = $agents | Group-Object id | Where-Object Count -gt 1
foreach ($duplicate in $duplicateIds) {
    Add-Failure "Duplicate agent id: $($duplicate.Name)"
}

$duplicatePrompts = $agents | Group-Object prompt_file | Where-Object Count -gt 1
foreach ($duplicate in $duplicatePrompts) {
    Add-Failure "Prompt file is shared by multiple agents: $($duplicate.Name)"
}

$agentIds = @($agents.id)
if ($config.entry_agent -notin $agentIds) {
    Add-Failure "Entry agent does not exist: $($config.entry_agent)"
}

$identitySection = '## ' + (Convert-CodePoints @(0x8EAB, 0x4EFD, 0x4E0E, 0x4F7F, 0x547D))
$completionSection = '## ' + (Convert-CodePoints @(0x5B8C, 0x6210, 0x5B9A, 0x4E49))
$outputSection = '## ' + (Convert-CodePoints @(0x8F93, 0x51FA, 0x534F, 0x8BAE))
$nonResponsibilitySection = '## ' + (Convert-CodePoints @(0x975E, 0x804C, 0x8D23))
$prohibitedSection = '## ' + (Convert-CodePoints @(0x660E, 0x786E, 0x7981, 0x6B62))
$requiredPromptSections = @($identitySection, $completionSection, $outputSection)

$forbiddenPatterns = @(
    '(?m)^\s*\.\.\.\s*$',
    '(?i)\bTODO\b',
    '(?i)rest of code',
    '(?i)implement here',
    '(?i)similar to above'
)

foreach ($agent in $agents) {
    $promptPath = Join-Path $TeamRoot $agent.prompt_file
    if (-not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
        Add-Failure "Missing prompt for $($agent.id): $($agent.prompt_file)"
        continue
    }

    $prompt = Get-Content -LiteralPath $promptPath -Raw -Encoding UTF8
    $lineCount = (Get-Content -LiteralPath $promptPath -Encoding UTF8).Count
    if ($lineCount -lt 70) {
        Add-Failure "Prompt is too shallow for $($agent.id): $lineCount lines"
    }

    foreach ($section in $requiredPromptSections) {
        if (-not $prompt.Contains($section)) {
            Add-Failure "Prompt $($agent.id) is missing a mandatory section."
        }
    }

    if (($prompt -notmatch [regex]::Escape($nonResponsibilitySection)) -and
        ($prompt -notmatch [regex]::Escape($prohibitedSection))) {
        Add-Failure "Prompt $($agent.id) is missing an explicit non-responsibility section."
    }

    foreach ($pattern in $forbiddenPatterns) {
        if ($prompt -match $pattern) {
            Add-Failure "Prompt $($agent.id) contains forbidden placeholder pattern: $pattern"
        }
    }
}

foreach ($pathProperty in $config.paths.PSObject.Properties) {
    $sharedPath = Join-Path $TeamRoot ([string]$pathProperty.Value)
    if (-not (Test-Path -LiteralPath $sharedPath -PathType Leaf)) {
        Add-Failure "Missing shared file $($pathProperty.Name): $($pathProperty.Value)"
    }
}

foreach ($route in $config.mandatory_routing) {
    if ($route.implementer -notin $agentIds) {
        Add-Failure "Routing references unknown implementer: $($route.implementer)"
    }

    foreach ($reviewer in $route.reviewers) {
        if ($reviewer -notin $agentIds) {
            Add-Failure "Routing references unknown reviewer: $reviewer"
        }
        if ($reviewer -eq $route.implementer) {
            Add-Failure "Implementer cannot review itself: $reviewer"
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Host "Agent team validation failed with $($failures.Count) issue(s):" -ForegroundColor Red
    foreach ($failure in $failures) {
        Write-Host "- $failure" -ForegroundColor Red
    }
    exit 1
}

Write-Host 'Agent team validation passed.' -ForegroundColor Green
Write-Host "Agents: $($agents.Count)"
Write-Host "Entry agent: $($config.entry_agent)"
Write-Host "Maximum parallel agents: $($config.max_parallel_agents)"
Write-Host 'All prompt files, shared contracts, routing references and safety gates are valid.'

