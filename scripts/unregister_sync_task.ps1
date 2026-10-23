# Olusturulan senkronizasyon gorevini kaldirir (yalnizca bu gorev).
# Kullanim: .\scripts\unregister_sync_task.ps1 [-Force]
param(
    [string]$TaskName = "DentSync - API to MSSQL",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$query = schtasks.exe /Query /TN $TaskName 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Gorev bulunamadi: $TaskName" -ForegroundColor Yellow
    exit 0
}

if (-not $Force) {
    $answer = Read-Host "Silinecek gorev: $TaskName. Onayliyor musunuz? (e/H)"
    if ($answer -notmatch '^[eE]$') {
        Write-Host "Iptal edildi."
        exit 0
    }
}

schtasks.exe /Delete /TN $TaskName /F | Out-Host
if ($LASTEXITCODE -eq 0) {
    Write-Host "Gorev kaldirildi: $TaskName" -ForegroundColor Green
} else {
    Write-Host "Gorev kaldirilamadi (cikis kodu $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}
