# Hedef API'yi baslatir - port 8000
# Kullanim:  .\scripts\run_target_api.ps1
# Yonetici izni gerekmez.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Sanal ortam bulunamadi: $python" -ForegroundColor Red
    exit 1
}

Write-Host "Hedef API: http://127.0.0.1:8000  (dokumantasyon: /docs)" -ForegroundColor Green
Write-Host "Panel    : http://127.0.0.1:8000/dashboard" -ForegroundColor Green
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
