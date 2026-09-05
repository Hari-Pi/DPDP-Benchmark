# Start the DPDP RAG server on this PC with token auth for public exposure.
#   powershell -File scripts\start_pc_stack.ps1 [-Token <value>]
#
# Token resolution order: -Token param -> .env (DPDP_TOKEN=...) -> prompt
# (offering to generate a strong random token). The .env file is gitignored.
param([string]$Token = "")

$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root ".env"

if (-not $Token -and (Test-Path $envFile)) {
    $line = Select-String -Path $envFile -Pattern '^DPDP_TOKEN=(.+)$' | Select-Object -First 1
    if ($line) { $Token = $line.Matches[0].Groups[1].Value.Trim() }
}
if (-not $Token) {
    $gen = Read-Host "Enter an access token (press Enter to auto-generate a strong one)"
    if (-not $gen) {
        $bytes = New-Object byte[] 24
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $gen = [System.BitConverter]::ToString($bytes).Replace("-", "").ToLower()
    }
    $Token = $gen
    Set-Content -Path $envFile -Value "DPDP_TOKEN=$Token" -NoNewline -Encoding ascii
    Write-Host "Token saved to .env (gitignored). Share it with the people you want to have access."
}

Write-Host "Access token: $Token"

# free the port
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep 2

$env:DPDP_TOKEN = $Token
Start-Process -FilePath "C:\Users\Hari\scoop\apps\python\current\python.exe" `
    -ArgumentList "-m","uvicorn","dpdp_rag.server:app","--app-dir",$root,`
                  "--host","0.0.0.0","--port","8000" -WindowStyle Hidden
Remove-Item Env:DPDP_TOKEN

Start-Sleep 6
try {
    $h = Invoke-RestMethod http://127.0.0.1:8000/health
    Write-Host "server up: $($h.status)"
    $need = (Invoke-RestMethod http://127.0.0.1:8000/auth/check).token_required
    Write-Host "token gate: $(if ($need) {'ON'} else {'OFF — set DPDP_TOKEN'})"
} catch { Write-Host "server FAILED: $($_.Exception.Message)"; exit 1 }
