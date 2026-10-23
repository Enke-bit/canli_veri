# Kaynak (mock) API'yi baslatir - port 8001
# Kullanim:  .\scripts\run_source_api.ps1
# Yonetici izni gerekmez.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Sanal ortam bulunamadi: $python" -ForegroundColor Red
    Write-Host "Once: python -m venv .venv ; .\.venv\Scripts\python -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

$dataFile = Join-Path $root "data\synthetic_source.json"
if (-not (Test-Path $dataFile)) {
    Write-Host "Sentetik veri dosyasi yok. Uretiliyor..." -ForegroundColor Yellow
    & $python "scripts\generate_synthetic_data.py"
}

Write-Host "Kaynak API: http://127.0.0.1:8001  (dokumantasyon: /docs)" -ForegroundColor Green
& $python -m uvicorn mock_source.main:app --host 127.0.0.1 --port 8001
