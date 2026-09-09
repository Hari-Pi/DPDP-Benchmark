# One-command Windows entry point for the preferred DPDP worker.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$logDir = Join-Path $root "logs"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "pc-worker-$stamp.log"
$exitCode = 0

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Host "DPDP PC worker startup: $(Get-Date -Format o)"
    Write-Host "Live log: $logPath"
    Write-Host "Keep this window open. Ctrl+C stops the worker."

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "[startup] Checking for DPDP updates..."
        & git -C $root pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not update the repository; continuing with local files."
        }
    }

    Write-Host "[startup] Launching the preferred PC worker..."
    & (Join-Path $root "scripts\start_pc_worker.ps1")
    if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
} catch {
    $exitCode = 1
    Write-Host "[fatal] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "The complete startup log is saved at: $logPath" -ForegroundColor Yellow
} finally {
    Stop-Transcript | Out-Null
}

Write-Host "DPDP worker stopped. Log saved at: $logPath"
exit $exitCode
