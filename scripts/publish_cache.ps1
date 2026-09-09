param(
  [string]$DroidianHost = "droidian",
  [string]$DroidianUser = "dazai",
  [string]$RemoteRoot = "/home/dazai/dpdp-coordinator/artifacts/current/cache",
  [switch]$IncludeModels
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$index = Join-Path $repo "chroma_db"
$models = Join-Path $env:USERPROFILE ".ollama\models"
if (!(Test-Path $index)) { throw "Missing $index. Run the PC worker and ingest once first." }
if (!(Test-Path $models)) { Write-Warning "No Ollama model directory found at $models; publishing index only." }
ssh "$DroidianUser@$DroidianHost" "mkdir -p '$RemoteRoot/chroma_db' '$RemoteRoot/ollama/models'"
scp -r "$index\*" "$DroidianUser@${DroidianHost}:$RemoteRoot/chroma_db/"
if ($IncludeModels -and (Test-Path $models)) {
  Write-Warning "Copying approximately 10 GB of Ollama weights to Droidian."
  scp -r "$models\*" "$DroidianUser@${DroidianHost}:$RemoteRoot/ollama/models/"
} elseif (Test-Path $models) {
  Write-Host "Skipping Ollama weights (Colab will download them directly). Use -IncludeModels to override." -ForegroundColor Yellow
}
Write-Host "Index cache published. Restart/rerun the Colab worker; it will verify and restore it." -ForegroundColor Green
