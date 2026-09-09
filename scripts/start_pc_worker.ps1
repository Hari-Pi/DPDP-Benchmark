# Start Windows as the preferred DPDP worker. A connected Colab worker takes
# over automatically if this worker disconnects or cannot answer a request.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$env:DPDP_WORKER_KIND = "pc"
$env:DPDP_WORKER_ID = if ($env:DPDP_WORKER_ID) {
    $env:DPDP_WORKER_ID
} else {
    "pc-$env:COMPUTERNAME"
}
$env:DPDP_WORKER_TOKEN = if ($env:DPDP_WORKER_TOKEN) {
    $env:DPDP_WORKER_TOKEN
} else {
    "5ecd4ade12ee5be628977b535b77a9a90f2205d980cd5fb8a9629ffd4d6b3abc"
}

$python = (Get-Command python -ErrorAction Stop).Source
& $python -m pip install -q -r requirements.txt websockets requests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama --exact --accept-package-agreements --accept-source-agreements
        $env:PATH += ";$env:LOCALAPPDATA\Programs\Ollama"
    } else {
        Write-Error "Install Ollama from https://ollama.com/download/windows and rerun."
    }
}

try {
    Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null
} catch {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 2
        try {
            Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null
            $ready = $true
            break
        } catch {}
    }
    if (-not $ready) { Write-Error "Ollama did not start." }
}

$models = (& ollama list) -join "`n"
if ($models -notmatch "nomic-embed-text") { & ollama pull nomic-embed-text }
if ($models -notmatch "qwen2.5:7b-instruct") { & ollama pull qwen2.5:7b-instruct }

if ($env:DPDP_SKIP_INGEST -ne "1") {
    & $python scripts/fetch_sources.py
    & $python scripts/extract_text.py
    & $python -m dpdp_rag.ingest
}

Write-Host "Connecting this PC as the preferred worker for dpdp.hari-pi.com..."
& $python -m dpdp_rag.worker
