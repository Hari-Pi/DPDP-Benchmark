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

$gpuName = "none"
$vramMiB = 0
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpuName = ((& nvidia-smi --query-gpu=name --format=csv,noheader)[0]).Trim()
    $vramMiB = [int](((& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)[0]).Trim())
}
if ($vramMiB -ge 32768) {
    $parallel = 4; $context = 8192
} elseif ($vramMiB -ge 20000) {
    $parallel = 3; $context = 6144
} elseif ($vramMiB -ge 12000) {
    $parallel = 2; $context = 5120
} else {
    $parallel = 1; $context = 4096
}
if (-not $env:DPDP_WORKER_CONCURRENCY) { $env:DPDP_WORKER_CONCURRENCY = "$parallel" }
if (-not $env:DPDP_NUM_CTX) { $env:DPDP_NUM_CTX = "$context" }
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = $env:DPDP_WORKER_CONCURRENCY }
if (-not $env:OLLAMA_MAX_LOADED_MODELS) { $env:OLLAMA_MAX_LOADED_MODELS = "2" }
if (-not $env:OLLAMA_MAX_QUEUE) { $env:OLLAMA_MAX_QUEUE = "64" }
if (-not $env:OLLAMA_CONTEXT_LENGTH) { $env:OLLAMA_CONTEXT_LENGTH = $env:DPDP_NUM_CTX }
if (-not $env:OLLAMA_FLASH_ATTENTION) { $env:OLLAMA_FLASH_ATTENTION = "1" }
if (-not $env:OLLAMA_KV_CACHE_TYPE) { $env:OLLAMA_KV_CACHE_TYPE = "q8_0" }
if (-not $env:OLLAMA_KEEP_ALIVE) { $env:OLLAMA_KEEP_ALIVE = "-1" }
if (-not $env:DPDP_GPU_RETRIEVAL) { $env:DPDP_GPU_RETRIEVAL = "1" }
Write-Host "GPU: $gpuName; VRAM=${vramMiB}MiB; workers=$env:DPDP_WORKER_CONCURRENCY; context=$env:DPDP_NUM_CTX"

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

$embedWarmup = @{ model = "nomic-embed-text"; input = "warmup"; keep_alive = -1 } | ConvertTo-Json
$chatWarmup = @{ model = "qwen2.5:7b-instruct"; prompt = ""; keep_alive = -1 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:11434/api/embed -Method Post -ContentType "application/json" -Body $embedWarmup | Out-Null
Invoke-RestMethod http://127.0.0.1:11434/api/generate -Method Post -ContentType "application/json" -Body $chatWarmup | Out-Null
& ollama ps

if ($env:DPDP_SKIP_INGEST -ne "1") {
    & $python scripts/fetch_sources.py
    & $python scripts/extract_text.py
    & $python -m dpdp_rag.ingest
}

Write-Host "Connecting this PC as the preferred worker for dpdp.hari-pi.com..."
& $python -m dpdp_rag.worker
