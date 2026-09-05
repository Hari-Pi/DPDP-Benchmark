# Start Ollama with the model spread across all GPUs and reduced per-GPU load:
#   OLLAMA_SCHED_SPREAD=1  -> distribute model layers over GPU 0 and GPU 1
#   OLLAMA_FLASH_ATTENTION=1 -> memory-efficient attention (less VRAM, faster)
#   OLLAMA_KV_CACHE_TYPE=q8_0  -> quantized KV cache (~half the KV memory)
#   OLLAMA_MAX_LOADED_MODELS=1 -> only one model in VRAM at a time
#   OLLAMA_NUM_PARALLEL=1      -> one request at a time (lowest load)
#   OLLAMA_KEEP_ALIVE=30m      -> no CPU-heavy reload cycles between runs
# Usage:  powershell -File scripts\start_ollama.ps1
Get-Process ollama* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2

$env:OLLAMA_SCHED_SPREAD      = "1"
$env:OLLAMA_FLASH_ATTENTION   = "1"
$env:OLLAMA_KV_CACHE_TYPE     = "q8_0"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_NUM_PARALLEL      = "1"
$env:OLLAMA_KEEP_ALIVE        = "30m"

Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep 5
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        Invoke-RestMethod http://127.0.0.1:11434/api/version | Out-Null
        $ok = $true
        break
    } catch { Start-Sleep 2 }
}
if ($ok) { Write-Host "ollama up (sched-spread + flash-attn + q8 KV)" }
else     { Write-Host "ollama failed to start"; exit 1 }
