# Backward-compatible entry point. The public server now lives on Droidian;
# this PC supplies preferred outbound RAG compute.
& (Join-Path $PSScriptRoot "start_pc_worker.ps1")
exit $LASTEXITCODE
