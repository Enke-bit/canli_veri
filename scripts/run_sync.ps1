# Senkronizasyonu bir kez calistirir.
# Kullanim:  .\scripts\run_sync.ps1 [-Full]
# Yonetici izni gerekmez. Cikis kodunu oldugu gibi dondurur.
param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Sanal ortam bulunamadi: $python" -ForegroundColor Red
    exit 1
}

$arguments = @("scripts\sync_api_to_mssql.py")
if ($Full) { $arguments += "--full" }

& $python @arguments
exit $LASTEXITCODE
