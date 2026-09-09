param(
  [string]$DroidianHost = "droidian",
  [string]$DroidianUser = "dazai",
  [string]$RemoteRoot = "/home/dazai/dpdp-coordinator/artifacts/current/cache"
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$index = Join-Path $repo "chroma_db"
$models = Join-Path $env:USERPROFILE ".ollama\models"
if (!(Test-Path $index)) { throw "Missing $index. Run the PC worker and ingest once first." }
if (!(Test-Path $models)) { Write-Warning "No Ollama model directory found at $models; publishing index only." }
ssh "$DroidianUser@$DroidianHost" "mkdir -p '$RemoteRoot/chroma_db' '$RemoteRoot/ollama/models'"
scp -r "$index\*" "$DroidianUser@${DroidianHost}:$RemoteRoot/chroma_db/"
if (Test-Path $models) { scp -r "$models\*" "$DroidianUser@${DroidianHost}:$RemoteRoot/ollama/models/" }
Write-Host "Cache published. Restart/rerun the Colab worker; it will verify and restore the cache." -ForegroundColor Green
