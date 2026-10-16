param(
    [ValidateSet('prepare','render','all')][string]$Stage = 'all',
    [string]$LlmCsv,
    [string]$HumanWorkbook,
    [string]$OutputDir,
    [string]$PythonExe,
    [string]$OriginPython = 'C:\Users\Admin\.codex\skills\editaplot-main\runtime\.editaplot-venv\Scripts\python.exe',
    [string]$RouteEvidence,
    [switch]$Probe
)
$ErrorActionPreference = 'Stop'
if (-not $PythonExe) {
    if ($Stage -eq 'render') {
        $PythonExe = $OriginPython
    } else {
        $PythonExe = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
    }
}
if (-not $RouteEvidence -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'verified_route_evidence.json'))) {
    $RouteEvidence = Join-Path $PSScriptRoot 'verified_route_evidence.json'
}
$arguments = @((Join-Path $PSScriptRoot 'fig5.py'), $Stage)
if ($Stage -eq 'all') { $arguments += @('--origin-python', $OriginPython) }
if ($LlmCsv) { $arguments += @('--llm-session', $LlmCsv) }
if ($HumanWorkbook) { $arguments += @('--human', $HumanWorkbook) }
if ($OutputDir) { $arguments += @('--output-dir', $OutputDir) }
if ($RouteEvidence) { $arguments += @('--route-evidence', $RouteEvidence) }
if ($Probe) { $arguments += '--probe' }
& $PythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw "Figure 5 $Stage failed with exit code $LASTEXITCODE" }
