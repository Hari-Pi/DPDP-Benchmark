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
    $gpuNames = @(& nvidia-smi --query-gpu=name --format=csv,noheader)
    $gpuMemory = @(& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
    $gpuName = $gpuNames[0].Trim()
    $vramMiB = [int]$gpuMemory[0].Trim()
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
if (-not $env:DPDP_MAX_OUTPUT_TOKENS) { $env:DPDP_MAX_OUTPUT_TOKENS = "2000" }
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = $env:DPDP_WORKER_CONCURRENCY }
if (-not $env:OLLAMA_MAX_LOADED_MODELS) { $env:OLLAMA_MAX_LOADED_MODELS = "2" }
if (-not $env:OLLAMA_MAX_QUEUE) { $env:OLLAMA_MAX_QUEUE = "64" }
if (-not $env:OLLAMA_CONTEXT_LENGTH) { $env:OLLAMA_CONTEXT_LENGTH = $env:DPDP_NUM_CTX }
if (-not $env:OLLAMA_FLASH_ATTENTION) { $env:OLLAMA_FLASH_ATTENTION = "1" }
if (-not $env:OLLAMA_KV_CACHE_TYPE) { $env:OLLAMA_KV_CACHE_TYPE = "q8_0" }
if (-not $env:OLLAMA_KEEP_ALIVE) { $env:OLLAMA_KEEP_ALIVE = "-1" }
if (-not $env:DPDP_GPU_RETRIEVAL) { $env:DPDP_GPU_RETRIEVAL = "1" }
Write-Host "GPU: $gpuName; VRAM=${vramMiB}MiB; workers=$env:DPDP_WORKER_CONCURRENCY; context=$env:DPDP_NUM_CTX; output_tokens=$env:DPDP_MAX_OUTPUT_TOKENS"

Write-Host "[setup] Checking Python dependencies..."
$python = (Get-Command python -ErrorAction Stop).Source
& $python -m pip install -q -r requirements.txt websockets requests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Checking the Droidian coordinator and worker credential..."
$workerHeaders = @{ Authorization = "Bearer $env:DPDP_WORKER_TOKEN" }
try {
    Invoke-RestMethod https://dpdp.hari-pi.com/internal/worker/artifact-manifest -Headers $workerHeaders -TimeoutSec 15 | Out-Null
    Write-Host "Coordinator preflight passed."
} catch {
    Write-Error "Cannot authenticate with the coordinator: $($_.Exception.Message)"
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama --exact --accept-package-agreements --accept-source-agreements
        $env:PATH += ";$env:LOCALAPPDATA\Programs\Ollama"
    } else {
        Write-Error "Install Ollama from https://ollama.com/download/windows and rerun."
    }
}

Write-Host "[setup] Checking the Ollama service..."
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
Write-Host "[setup] Checking required models..."
if ($models -notmatch "nomic-embed-text") { & ollama pull nomic-embed-text }
if ($models -notmatch "qwen2.5:7b-instruct") { & ollama pull qwen2.5:7b-instruct }

Write-Host "[setup] Warming GPU models..."
$embedWarmup = @{ model = "nomic-embed-text"; input = "warmup"; keep_alive = -1 } | ConvertTo-Json
$chatWarmup = @{ model = "qwen2.5:7b-instruct"; prompt = ""; keep_alive = -1 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:11434/api/embed -Method Post -ContentType "application/json" -Body $embedWarmup | Out-Null
Invoke-RestMethod http://127.0.0.1:11434/api/generate -Method Post -ContentType "application/json" -Body $chatWarmup | Out-Null
& ollama ps

if ($env:DPDP_SKIP_INGEST -ne "1") {
    Write-Host "[setup] Updating sources and validating the vector index..."
    & $python scripts/fetch_sources.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python scripts/extract_text.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python -m dpdp_rag.ingest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Connecting this PC as the preferred worker for dpdp.hari-pi.com..."
& $python -m dpdp_rag.worker
if ($LASTEXITCODE -ne 0) {
    Write-Error "The PC worker stopped with exit code $LASTEXITCODE."
}
