# Windows Task Scheduler'da 5 dakikalik senkronizasyon gorevi olusturur.
# Kullanim:
#   .\scripts\register_sync_task.ps1
#   .\scripts\register_sync_task.ps1 -IntervalMinutes 10 -RunNow
#
# Notlar:
# - Yonetici izni GEREKMEZ; gorev yalnizca sizin kullaniciniz icin olusturulur.
# - Ayni isimde gorev varsa guncellenir (/F). Baska gorevlere dokunulmaz.
# - Gorev yalnizca kullanici oturum actiginda calisir (varsayilan).
param(
    [int]$IntervalMinutes = 5,
    [string]$TaskName = "DentSync - API to MSSQL",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\sync_api_to_mssql.py"

if (-not (Test-Path $python)) {
    Write-Host "Sanal ortam bulunamadi: $python" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $script)) {
    Write-Host "Senkronizasyon betigi bulunamadi: $script" -ForegroundColor Red
    exit 1
}
if ($IntervalMinutes -lt 1) {
    Write-Host "IntervalMinutes en az 1 olmalidir." -ForegroundColor Red
    exit 1
}

$action = '"' + $python + '" "' + $script + '"'
Write-Host "Gorev adi : $TaskName"
Write-Host "Komut     : $action"
Write-Host "Aralik    : her $IntervalMinutes dakika"

schtasks.exe /Create /TN $TaskName /TR $action /SC MINUTE /MO $IntervalMinutes /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "Gorev olusturulamadi (cikis kodu $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

schtasks.exe /Query /TN $TaskName /V /FO LIST | Out-Host

if ($RunNow) {
    Write-Host "Gorev simdi calistiriliyor..." -ForegroundColor Yellow
    schtasks.exe /Run /TN $TaskName | Out-Host
}

Write-Host ""
Write-Host "Bilgi: gorev yalnizca giris yapmis oldugunuzda calisir." -ForegroundColor Cyan
Write-Host "Log:  $root\logs\sync.log" -ForegroundColor Cyan
Write-Host "Kaldirmak icin: .\scripts\unregister_sync_task.ps1" -ForegroundColor Cyan
