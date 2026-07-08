<#
.SYNOPSIS
  Re-launch the 6 models with remaining gaps (deepseek + 5 free models).
  The 3 fully-complete paid models (gpt-oss, qwen3.6, qwen3.5) are skipped.

  Resume-safe: batch_run.py skips completed trials on re-run.
#>

$ErrorActionPreference = "Stop"
if (-not (Test-Path "batch_run.py")) { Write-Host "!! Run from project root" -ForegroundColor Red; exit 1 }

# Read API keys
$envContent = Get-Content ".env"
$OR_KEY = (($envContent | Where-Object { $_ -match '^OPENROUTER_API_KEY=' }) -replace '^OPENROUTER_API_KEY=', '').Trim().Trim('"').Trim("'")
$DS_KEY = (($envContent | Where-Object { $_ -match '^DEEPSEEK_API_KEY=' }) -replace '^DEEPSEEK_API_KEY=', '').Trim().Trim('"').Trim("'")

$OR_HOST = "https://openrouter.ai/api"
$DS_HOST = "https://api.deepseek.com"

$models = @(
    @{ tag="deepseek"; model="deepseek-v4-flash";                     host=$DS_HOST; key=$DS_KEY;  keyenv="DEEPSEEK_API_KEY";    workers=2; offset=0;  max_tokens=1024 }
    @{ tag="laguna";   model="poolside/laguna-xs-2.1:free";           host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=2;  max_tokens=1024 }
    @{ tag="gemma";    model="google/gemma-4-31b-it:free";            host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=4;  max_tokens=2048 }
    @{ tag="north";    model="cohere/north-mini-code:free";           host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=6;  max_tokens=1024 }
    @{ tag="super";    model="nvidia/nemotron-3-super-120b-a12b:free";host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=8;  max_tokens=1024 }
    @{ tag="nano";     model="nvidia/nemotron-3-nano-30b-a3b:free";   host=$OR_HOST; key=$OR_KEY; keyenv="OPENROUTER_API_KEY";  workers=2; offset=10; max_tokens=1024 }
)

Write-Host "`n  Re-launching $($models.Count) models to fill gaps:`n" -ForegroundColor Cyan

$processes = @()
foreach ($m in $models) {
    $conts = "c$($m.offset)-$($m.offset + $m.workers - 1)"
    Write-Host ("  {0,-12} {1,-44} w={2} {3}" -f $m.tag, $m.model, $m.workers, $conts) -ForegroundColor DarkGray

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

    $proc = Start-Process -FilePath "python" `
        -ArgumentList $args `
        -RedirectStandardOutput "runs/_full2_$($m.tag).log" `
        -RedirectStandardError "runs/_full2_$($m.tag).err" `
        -NoNewWindow -PassThru
    $processes += [PSCustomObject]@{ Tag=$m.tag; PID=$proc.Id }
}

Write-Host "`n  Launched $($models.Count) gap-fill processes.`n" -ForegroundColor Green
$processes | Format-Table Tag, PID -AutoSize
