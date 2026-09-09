# One-command Windows entry point for the preferred DPDP worker.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "Checking for DPDP updates..."
    & git -C $root pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Could not update the repository; continuing with local files."
    }
}

& (Join-Path $root "scripts\start_pc_worker.ps1")
exit $LASTEXITCODE
