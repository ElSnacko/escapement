<#
.SYNOPSIS
  Launch the FULL escapement suite across 9 models in parallel.

  Each model runs all 5 scenario groups sequentially:
    1. agent_coding      A,B    (n=15)
    2. ops_worker        A      (n=15)
    3. config_exposure   A,B    (n=30)
    4. config_exposure   D      (n=15)
    5. goal_pres_v2 + goal_guard_v2  A  (n=15)

  Sandbox allocation (16 containers):
    DeepSeek    offset 0   workers 2   (containers 0-1)
    GPT-OSS     offset 2   workers 2   (containers 2-3)
    Qwen3.6     offset 4   workers 2   (containers 4-5)
    Qwen3.5     offset 6   workers 2   (containers 6-7)
    Nano        offset 8   workers 2   (containers 8-9)
    Super       offset 10  workers 2   (containers 10-11)
    Laguna      offset 12  workers 2   (containers 12-13)
    North       offset 14  workers 1   (container 14)
    Gemma       offset 15  workers 1   (container 15)

USAGE
  .\scripts\launch_full.ps1                # all 9 models
  .\scripts\launch_full.ps1 -DryRun        # print commands without launching

MONITOR
  Get-Content runs\_full_deepseek.log -Wait
  Get-ChildItem runs\_full_*.log | ForEach-Object { Get-Content $_ -Tail 1 }

RESUME
  Re-running is safe -- batch_run.py skips completed trials.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path "batch_run.py")) {
    Write-Host "!! Run from project root" -ForegroundColor Red
    exit 1
}

# --- Read API keys from .env ---
$envContent = Get-Content ".env" -ErrorAction Stop
$OR_KEY = ($envContent | Where-Object { $_ -match '^OPENROUTER_API_KEY=' }) -replace '^OPENROUTER_API_KEY=', ''
$DS_KEY = ($envContent | Where-Object { $_ -match '^DEEPSEEK_API_KEY=' }) -replace '^DEEPSEEK_API_KEY=', ''
$OR_KEY = $OR_KEY.Trim().Trim('"').Trim("'")
$DS_KEY = $DS_KEY.Trim().Trim('"').Trim("'")

if (-not $OR_KEY) { Write-Host "!! OPENROUTER_API_KEY not in .env" -ForegroundColor Red; exit 1 }
if (-not $DS_KEY) { Write-Host "!! DEEPSEEK_API_KEY not in .env" -ForegroundColor Red; exit 1 }

# --- Model configs ---
$OR_HOST = "https://openrouter.ai/api"
$DS_HOST = "https://api.deepseek.com"

$models = @(
    @{ tag="deepseek";  model="deepseek-v4-flash";                     host=$DS_HOST; key=$DS_KEY;  keyenv="DEEPSEEK_API_KEY";    workers=2; offset=0;  max_tokens=1024 }
    @{ tag="gpt-oss";   model="openai/gpt-oss-120b";                   host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=2;  max_tokens=1024 }
    @{ tag="qwen3.6";   model="qwen/qwen3.6-35b-a3b";                  host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=4;  max_tokens=1024 }
    @{ tag="qwen3.5";   model="qwen/qwen3.5-27b";                      host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=6;  max_tokens=1024 }
    @{ tag="nano";      model="nvidia/nemotron-3-nano-30b-a3b:free";   host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=8;  max_tokens=1024 }
    @{ tag="super";     model="nvidia/nemotron-3-super-120b-a12b:free";host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=10; max_tokens=1024 }
    @{ tag="laguna";    model="poolside/laguna-xs-2.1:free";           host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=12; max_tokens=1024 }
    @{ tag="north";     model="cohere/north-mini-code:free";           host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=1; offset=14; max_tokens=1024 }
    @{ tag="gemma";     model="google/gemma-4-31b-it:free";            host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=1; offset=15; max_tokens=2048 }
)

# --- Verify containers ---
Write-Host "`n  Verifying sandbox containers..." -ForegroundColor Cyan
$missing = @()
for ($i = 0; $i -lt 16; $i++) {
    $cname = "escapement-sandbox-$i"
    $running = docker inspect -f '{{.State.Running}}' $cname 2>$null
    if ($running -ne "true") { $missing += $i }
}
if ($missing.Count -gt 0) {
    Write-Host "  Missing containers: $($missing -join ', ')" -ForegroundColor Yellow
    Write-Host "  Starting them..." -ForegroundColor Yellow
    foreach ($i in $missing) {
        docker start "escapement-sandbox-$i" 2>$null
    }
    Start-Sleep 3
}

# --- Launch ---
Write-Host "`n  Launching $($models.Count) models in parallel:`n" -ForegroundColor Cyan
Write-Host "  tag            model                                        w  containers" -ForegroundColor DarkGray
Write-Host "  $('-' * 72)" -ForegroundColor DarkGray

$processes = @()
foreach ($m in $models) {
    $conts = if ($m.workers -eq 1) { "c$($m.offset)" } else { "c$($m.offset)-$($m.offset + $m.workers - 1)" }
    $line = "  {0,-14} {1,-44} {2,2}  {3}" -f $m.tag, $m.model, $m.workers, $conts
    Write-Host $line -ForegroundColor DarkGray

    $args = @(
        "scripts/full_sweep.py",
        "--model", $m.model,
        "--host", $m.host,
        "--key-env", $m.keyenv,
        "--api-key", $m.key,
        "--workers", $m.workers,
        "--sandbox-offset", $m.offset,
        "--max-tokens", $m.max_tokens
    )

    $logOut = "runs/_full_$($m.tag).log"
    $logErr = "runs/_full_$($m.tag).err"

    if ($DryRun) {
        Write-Host "    [DRY] python $($args -join ' ')" -ForegroundColor Yellow
        continue
    }

    $proc = Start-Process -FilePath "python" `
        -ArgumentList $args `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError $logErr `
        -NoNewWindow `
        -PassThru
    $processes += [PSCustomObject]@{ Tag=$m.tag; PID=$proc.Id; Model=$m.model }
}

if ($DryRun) {
    Write-Host "`n  [DRY RUN] No processes launched.`n" -ForegroundColor Yellow
    return
}

Write-Host "`n  All $($models.Count) processes launched.`n" -ForegroundColor Green
Write-Host "  PIDs:" -ForegroundColor DarkGray
$processes | Format-Table Tag, PID, Model -AutoSize

Write-Host "  Monitor:" -ForegroundColor DarkGray
Write-Host "    Get-Content runs\_full_deepseek.log -Wait" -ForegroundColor DarkGray
Write-Host "    Get-ChildItem runs\_full_*.log | ForEach-Object { Write-Host `$_.Name; Get-Content `$_ -Tail 3 }" -ForegroundColor DarkGray
Write-Host ""
