<#
.SYNOPSIS
  Launch all OpenRouter free-tier models in PARALLEL through ALL scenarios.
  Each model gets its own sandbox container and its own log file.

DESIGN
  8 models run simultaneously. Per model:
    1. config_exposure frames A,B x agency off/on  (4 cells)
    2. goal_preservation + goal_guarding frame A x agency off/on  (4 cells)
  = 8 cells x N trials per model.

  At ~2.3 min/trial: 80 trials/model ~= 3h.  All 8 in parallel ~= 3h total.

USAGE
  .\scripts\openrouter_overnight.ps1                # all 8 models, N=10
  .\scripts\openrouter_overnight.ps1 -N 5           # quick test run
  .\scripts\openrouter_overnight.ps1 -Models "openai/gpt-oss-120b:free"  # one model

MONITOR
  Get-Content logs\openrouter_0.log -Wait            # tail a specific model
  Get-ChildItem logs\*.log | ForEach-Object { ... }  # check all

RESUME
  Re-running the script is safe — batch_run.py skips completed trials.
#>

param(
    [int]$N = 20,
    [string[]]$Models = @(
        "openai/gpt-oss-120b",
        "nvidia/nemotron-3-nano-30b-a3b",
        "nvidia/nemotron-3-super-120b-a12b",
        "google/gemma-4-31b-it",
        "google/gemma-4-26b-a4b-it",
        "cohere/north-mini-code:free"
    )
)

$ErrorActionPreference = "Stop"

# Verify we're in the project root
if (-not (Test-Path "batch_run.py")) {
    Write-Host "!! Run from project root (batch_run.py not found)" -ForegroundColor Red
    exit 1
}

# Ensure log directory exists
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }

# Verify sandbox containers exist
$expectedContainers = $Models | ForEach-Object { "escapement-sandbox-[$($_.Substring(0,1))]" }  # placeholder
for ($i = 0; $i -lt $Models.Count; $i++) {
    $cname = "escapement-sandbox-$i"
    $running = docker inspect -f '{{.State.Running}}' $cname 2>$null
    if ($running -ne "true") {
        Write-Host "!! Container $cname is not running. Start it first:" -ForegroundColor Red
        Write-Host "   docker start $cname" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "`n  Launching $($Models.Count) models in parallel (N=$N per cell)`n" -ForegroundColor Cyan

# Launch each model as a background process
$processes = @()
for ($i = 0; $i -lt $Models.Count; $i++) {
    $model = $Models[$i]
    $container = "escapement-sandbox-$i"
    $logFile = "logs\openrouter_$i.log"
    $modelName = $model.Split("/")[1].Replace(":free", "")
    $startTime = Get-Date -Format "HH:mm:ss"

    Write-Host "  [$i] $startTime  $model  ->  $container  ->  $logFile" -ForegroundColor DarkGray

    $proc = Start-Process -FilePath "python" `
        -ArgumentList "scripts/run_model_sweep.py", $model, $container, $N `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "logs\openrouter_$i.err" `
        -NoNewWindow `
        -PassThru
    $processes += $proc
}

Write-Host "`n  All $($Models.Count) processes launched. Monitoring...`n" -ForegroundColor Green
Write-Host "  Tail a log:  Get-Content logs\openrouter_0.log -Wait" -ForegroundColor DarkGray
Write-Host "  Check procs: Get-Process python | Format-Table Id, StartTime`n" -ForegroundColor DarkGray

# Wait for all to complete
foreach ($p in $processes) {
    $p.WaitForExit()
}

$endTime = Get-Date -Format "HH:mm:ss"
Write-Host "`n{'='*80}" -ForegroundColor Green
Write-Host "  ALL MODELS COMPLETE at $endTime" -ForegroundColor Green
Write-Host "$('=' * 80)`n" -ForegroundColor Green

# Aggregate results
Write-Host "  Aggregating results..." -ForegroundColor Cyan
& python scripts/aggregate.py --rescore
