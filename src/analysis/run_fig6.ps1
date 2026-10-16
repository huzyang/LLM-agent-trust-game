param(
    [ValidateSet('prepare','render','all')][string]$Stage = 'all',
    [string]$LlmCsv,
    [string]$HumanWorkbook,
    [string]$OutputDir,
    [string]$RouteEvidence,
    [string]$DataPython,
    [string]$OriginPython = 'C:\Users\Admin\.codex\skills\editaplot-main\runtime\.editaplot-venv\Scripts\python.exe',
    [switch]$Probe
)
$ErrorActionPreference = 'Stop'
if (-not $DataPython) { $DataPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe' }
if (-not $RouteEvidence -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'verified_route_evidence.json'))) { $RouteEvidence = Join-Path $PSScriptRoot 'verified_route_evidence.json' }
$arguments = @((Join-Path $PSScriptRoot 'fig6.py'), $Stage)
if ($LlmCsv) { $arguments += @('--llm', $LlmCsv) }
if ($HumanWorkbook) { $arguments += @('--human', $HumanWorkbook) }
if ($OutputDir) { $arguments += @('--output-dir', $OutputDir) }
if ($RouteEvidence) { $arguments += @('--route-evidence', $RouteEvidence) }
if ($Probe) { $arguments += '--probe' }
if ($Stage -eq 'all') { $arguments += @('--origin-python', $OriginPython) }
if ($Stage -eq 'render') { & $OriginPython @arguments } else { & $DataPython @arguments }
if ($LASTEXITCODE -ne 0) { throw "Figure6 $Stage failed: $LASTEXITCODE" }
