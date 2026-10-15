# Launcher for the main script fig3.py; run from any working directory.
param(
    [string[]]$LlmSessions = @(),
    [string]$HumanWorkbook = '',
    [ValidateSet('all', 'prepare', 'render')][string]$Mode = 'all',
    [string]$OutputDirectory = '',
    [string]$PythonExecutable = '',
    [string]$OriginPythonExecutable = '',
    [switch]$CheckOnly,
    [switch]$CloseOrigin,
    [string]$HumanCacheDirectory = ''
)

$ErrorActionPreference = 'Stop'
$taskRepository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path

function Get-Fig3PythonInfo {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $null }
    $taskProbe = @'
import importlib.util, json, platform, struct, sys
names = ['numpy', 'pandas', 'scipy', 'openpyxl', 'originpro']
print(json.dumps({'executable': sys.executable, 'compatible': platform.python_implementation() == 'CPython' and (3,10) <= sys.version_info[:2] < (3,13) and struct.calcsize('P') == 8, 'modules': {n: importlib.util.find_spec(n) is not None for n in names}}))
'@
    $taskResult = & $Candidate -c $taskProbe
    if ($LASTEXITCODE -ne 0) { return $null }
    return (($taskResult -join "`n") | ConvertFrom-Json)
}

$taskDataCandidates = @()
if ($PythonExecutable) {
    $taskDataCandidates = @($PythonExecutable)
} else {
    $taskDataCandidates = @(
        (Join-Path $taskRepository '.venv\Scripts\python.exe'),
        (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
        'D:\anaconda3\python.exe'
    )
    $taskPathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($taskPathPython) { $taskDataCandidates += $taskPathPython.Source }
}
$taskPythonInfo = $null
foreach ($taskCandidate in $taskDataCandidates) {
    $taskInfo = Get-Fig3PythonInfo $taskCandidate
    if ($taskInfo -and $taskInfo.compatible -and $taskInfo.modules.numpy -and $taskInfo.modules.pandas) {
        if ($Mode -eq 'render' -or ($taskInfo.modules.scipy -and $taskInfo.modules.openpyxl)) {
            $taskPythonInfo = $taskInfo
            break
        }
    }
}
if (-not $taskPythonInfo) {
    throw 'Compatible 64-bit Python 3.10-3.12 with data dependencies not found. See README_fig3.md and requirements_fig3.txt.'
}

$taskOriginPython = ''
if ($Mode -ne 'prepare') {
    if ($OriginPythonExecutable) {
        $taskOriginCandidates = @($OriginPythonExecutable)
    } else {
        $taskOriginCandidates = @(
            $taskPythonInfo.executable,
            (Join-Path $env:USERPROFILE '.codex\skills\editaplot-main\runtime\.editaplot-venv\Scripts\python.exe')
        )
    }
    foreach ($taskCandidate in $taskOriginCandidates) {
        $taskInfo = Get-Fig3PythonInfo $taskCandidate
        if ($taskInfo -and $taskInfo.compatible -and $taskInfo.modules.numpy -and $taskInfo.modules.pandas -and $taskInfo.modules.originpro) {
            $taskOriginPython = $taskInfo.executable
            break
        }
    }
    if (-not $taskOriginPython) {
        throw 'Origin Python dependencies not found. Install requirements_fig3.txt or pass -OriginPythonExecutable.'
    }
}

if ($Mode -eq 'render') {
    if (-not $OutputDirectory -or -not (Test-Path -LiteralPath (Join-Path $OutputDirectory 'analysis_plan.json'))) {
        throw 'Render mode requires -OutputDirectory pointing to prepared Figure 3 tables.'
    }
} else {
    if (-not $LlmSessions.Count) {
        $LlmSessions = @((Join-Path $taskRepository 'outputs\20261011_000304_540158_llm_01'))
    }
    if (-not $HumanWorkbook) {
        $HumanWorkbook = Join-Path $taskRepository 'human_experiment_datas\2024_NHB_model_Trust Game.xlsx'
    }
    if (-not (Test-Path -LiteralPath $HumanWorkbook -PathType Leaf)) { throw "Human workbook not found: $HumanWorkbook" }
    foreach ($taskSession in $LlmSessions) {
        $taskCsv = $taskSession
        if (Test-Path -LiteralPath $taskSession -PathType Container) {
            $taskCsv = Join-Path $taskSession 'agent_rounds_all.csv'
            if (-not (Test-Path -LiteralPath $taskCsv -PathType Leaf)) { $taskCsv = Join-Path $taskSession 'agent_rounds.csv' }
        }
        if (-not (Test-Path -LiteralPath $taskCsv -PathType Leaf)) { throw "LLM CSV not found: $taskCsv" }
    }
}

if ($CheckOnly) {
    [ordered]@{ main_script = (Join-Path $PSScriptRoot 'fig3.py'); repository = $taskRepository; mode = $Mode; data_python = $taskPythonInfo.executable; origin_python = $taskOriginPython; human_workbook = $HumanWorkbook; llm_sessions = $LlmSessions } | ConvertTo-Json -Depth 4
    return
}

$taskArguments = @((Join-Path $PSScriptRoot 'fig3.py'), $Mode)
if ($Mode -ne 'render') {
    $taskArguments += @('--human', $HumanWorkbook)
    foreach ($taskSession in $LlmSessions) { $taskArguments += @('--llm-session', $taskSession) }
}
if ($taskOriginPython -and $taskOriginPython -ne $taskPythonInfo.executable) { $taskArguments += @('--origin-python', $taskOriginPython) }
if ($OutputDirectory) { $taskArguments += @('--output-dir', $OutputDirectory) }
if ($CloseOrigin) { $taskArguments += '--close-origin' }
if ($HumanCacheDirectory) { $taskArguments += @('--human-cache-dir', $HumanCacheDirectory) }
& $taskPythonInfo.executable @taskArguments
if ($LASTEXITCODE -ne 0) { throw "Figure 3 pipeline failed with exit code $LASTEXITCODE." }
