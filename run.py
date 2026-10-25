"""DentSync - tum projeyi tek komutla calistirir.

Kullanim
--------
    python run.py

Yaptigi isler
-------------
1. Sanal ortami ve paketleri kontrol eder (gerekirse kendini .venv ile yeniden baslatir).
2. .env ve sentetik veri dosyasini kontrol eder; eksikse ne yapilacagini soyler.
3. Kaynak API'yi (8001) ve Hedef API'yi (8000) baslatir.
4. Ikisinin de /health yaniti verdigini dogrular ve MSSQL baglantisini raporlar.
5. Paneli tarayicida acar.
6. Ctrl+C'ye kadar ikisini de ayakta tutar, cikista ikisini de kapatir.

Secenekler
----------
    --sync              Acilista bir senkronizasyon calistir
    --full              --sync ile birlikte tam cekim yapar (checkpoint yok sayilir)
    --no-browser        Tarayiciyi acmaz
    --open X            Acilacak sayfa: panel | sema | kilavuz | slayt | docs | none
    --source-port N     Kaynak API portu (varsayilan 8001)
    --target-port N     Hedef API portu (varsayilan 8000)
    --check             Yalnizca ortami kontrol et, sunucu baslatma

Cikis kodlari: 0 basarili, 1 ortam hatasi, 2 sunucu baslatilamadi, 130 Ctrl+C.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

import runner_utils as ru
from runner_utils import C, fail, info, ok, say, warn

PAGES = {
    "panel": ("/dashboard", "Canli analitik paneli"),
    "sema": ("/mimari", "Mimari ve canli veri akisi"),
    "kilavuz": ("/kilavuz", "Sifirdan calistirma kilavuzu"),
    "slayt": ("/slayt", "Sunum: canli veri cekme mimarisi"),
    "senkron": ("/slayt-senkron", "Sunum: canli veri nasil cekilir (basit)"),
    "gereksinim": ("/slayt-gereksinim", "Sunum: canli veri icin gereken sistemler"),
    "docs": ("/docs", "API dokumantasyonu (Swagger)"),
}


def banner() -> None:
    say("")
    say(f"{C.BOLD}{C.CYAN}  DentSync{C.RESET} {C.DIM}| MSSQL + Python API otomatik veri senkronizasyonu{C.RESET}")
    say(f"{C.DIM}  Kaynak API :8001  ->  Sync  ->  MSSQL  ->  Hedef API :8000{C.RESET}")
    say("")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DentSync projesini tek komutla calistirir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ornek: python run.py --sync --open panel",
    )
    parser.add_argument("--sync", action="store_true", help="Acilista bir senkronizasyon calistir")
    parser.add_argument("--full", action="store_true", help="--sync ile tam cekim yap")
    parser.add_argument("--no-browser", action="store_true", help="Tarayiciyi acma")
    parser.add_argument(
        "--open",
        default="panel",
        choices=sorted(PAGES) + ["none"],
        help="Acilacak sayfa (varsayilan: panel)",
    )
    parser.add_argument("--source-port", type=int, default=8001)
    parser.add_argument("--target-port", type=int, default=8000)
    parser.add_argument("--check", action="store_true", help="Yalnizca ortami kontrol et")
    return parser.parse_args(argv)


def check_environment() -> list[str]:
    """Kurulumu denetler; baslatmayi engelleyen sorunlari dondurur."""
    problems = ru.preflight()

    import pyodbc

    drivers = pyodbc.drivers()
    from app.config import get_settings

    settings = get_settings()
    if settings.db_driver not in drivers:
        problems.append(
            f"ODBC surucusu bulunamadi: '{settings.db_driver}'. "
            f"Kurulu: {', '.join(drivers) or '(yok)'}. "
            ".env icindeki DB_DRIVER degerini kurulu bir surucuyle degistirin."
        )
    return problems


def report_environment() -> None:
    from app.config import get_settings

    settings = get_settings()
    info(f"Python      : {sys.version.split()[0]}  ({sys.executable})")
    info(f"MSSQL       : {settings.db_server} / {settings.db_database}")
    info(f"ODBC        : {settings.db_driver}")
    info(f"Kaynak API  : {settings.source_api_url}")
    say("")


def verify_database() -> bool:
    """MSSQL baglantisini ve tablo varligini dogrular."""
    try:
        from sqlalchemy import text

        from app.db import build_engine
        from app.config import get_settings

        engine = build_engine(get_settings())
        try:
            with engine.connect() as connection:
                count = connection.execute(
                    text("SELECT COUNT(*) FROM sys.tables WHERE name IN "
                         "('Clinics','Patients','Appointments','SyncState','SyncLog')")
                ).scalar_one()
                db_name = connection.execute(text("SELECT DB_NAME()")).scalar_one()
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001
        fail("MSSQL baglantisi kurulamadi.")
        say(f"      {C.DIM}{str(exc)[:220]}{C.RESET}")
        say("")
        say("  Cozum icin sirasiyla deneyin:")
        say(f"    {C.BOLD}.venv\\Scripts\\python.exe scripts\\init_db.py{C.RESET}")
        say(f"    {C.BOLD}.venv\\Scripts\\python.exe scripts\\init_db.py --check-only{C.RESET}")
        return False

    if count < 5:
        warn(f"Veritabani '{db_name}' acildi ama bazi tablolar eksik ({count}/5).")
        say(f"      Duzenlemek icin: {C.BOLD}.venv\\Scripts\\python.exe scripts\\init_db.py{C.RESET}")
    else:
        ok(f"MSSQL hazir: {db_name} | 5 tablo dogrulandi")
    return True


def start_source_api(port: int) -> subprocess.Popen | None:
    """Kaynak API'yi baslatir; zaten calisiyorsa mevcut olani kullanir."""
    base = f"http://127.0.0.1:{port}"
    if ru.wait_for_health(base + "/health", timeout=1.5):
        ok(f"Kaynak API zaten calisiyor: {base}")
        return None

    if ru.port_in_use(port):
        warn(f"{port} portu dolu; mevcut surecin saglikli oldugu dogrulaniyor...")
        if ru.wait_for_health(base + "/health", timeout=8):
            return None
        fail(f"{port} portundaki surec saglikli yanit vermiyor. Baska bir port secin: --source-port 8011")
        raise SystemExit(2)

    info("Kaynak API baslatiliyor...")
    process = ru.start_api("mock_source.main:app", port, "run_source_api.log")
    if not ru.wait_for_health(base + "/health"):
        ru.stop_process(process, "Kaynak API")
        fail("Kaynak API baslatilamadi. Ayrinti: logs/run_source_api.log")
        raise SystemExit(2)
    ok(f"Kaynak API hazir: {base}")
    return process


def start_target_api(port: int) -> subprocess.Popen | None:
    base = f"http://127.0.0.1:{port}"
    if ru.wait_for_health(base + "/health", timeout=1.5):
        ok(f"Hedef API zaten calisiyor: {base}")
        return None

    if ru.port_in_use(port):
        warn(f"{port} portu dolu; mevcut surecin saglikli oldugu dogrulaniyor...")
        if ru.wait_for_health(base + "/health", timeout=8):
            return None
        fail(f"{port} portundaki surec saglikli yanit vermiyor. Baska bir port secin: --target-port 8010")
        raise SystemExit(2)

    info("Hedef API baslatiliyor...")
    process = ru.start_api("app.main:app", port, "run_target_api.log")
    if not ru.wait_for_health(base + "/health"):
        ru.stop_process(process, "Hedef API")
        fail("Hedef API baslatilamadi. Ayrinti: logs/run_target_api.log")
        raise SystemExit(2)
    ok(f"Hedef API hazir: {base}")
    return process


def run_sync(full: bool) -> bool:
    from app.config import get_settings
    from app.db import build_engine
    from app.sync_engine import SyncEngine

    settings = get_settings()
    info("Senkronizasyon calisiyor" + (" (tam cekim)" if full else "") + "...")
    engine = build_engine(settings)
    sync = SyncEngine(settings, engine)
    try:
        result = sync.run(force_full=full)
    finally:
        sync.close()
        engine.dispose()

    for stats in result.entities:
        say(
            f"      {stats.entity:<14} okunan {stats.read:>5}  "
            f"eklenen {stats.inserted:>5}  guncellenen {stats.updated:>5}  "
            f"silinen {stats.deleted_marked:>4}  hata {stats.errors}"
        )
    if result.success:
        ok("Senkronizasyon basarili.")
    else:
        fail(f"Senkronizasyon basarisiz: {result.error}")
    return result.success


def print_status(source_port: int, target_port: int) -> None:
    target = ru.health_summary(f"http://127.0.0.1:{target_port}") or {}
    source = ru.health_summary(f"http://127.0.0.1:{source_port}") or {}

    db = (target.get("database") or {}).get("name", "<=")
    counts = source.get("counts") or {}
    say("")
    say(f"  {C.BOLD}Durum{C.RESET}")
    say(f"    Kaynak API   {C.GREEN}calisiyor{C.RESET}  http://127.0.0.1:{source_port}"
        f"   {C.DIM}({counts.get('clinics', '<=')} klinik / {counts.get('patients', '<=')} hasta / "
        f"{counts.get('appointments', '<=')} randevu){C.RESET}")
    say(f"    Hedef API    {C.GREEN}calisiyor{C.RESET}  http://127.0.0.1:{target_port}"
        f"   {C.DIM}(MSSQL: {db}){C.RESET}")
    say("")
    say(f"  {C.BOLD}Sayfalar{C.RESET}")
    for key, (path, label) in PAGES.items():
        say(f"    {key:<9} http://127.0.0.1:{target_port}{path:<12} {C.DIM}{label}{C.RESET}")
    say("")
    say(f"  {C.DIM}Loglar: logs/run_source_api.log | logs/run_target_api.log | logs/sync.log{C.RESET}")
    say(f"  {C.DIM}Durdurmak icin Ctrl+C.{C.RESET}")
    say("")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ru.ensure_venv()
    banner()

    if args.full and not args.sync:
        warn("--full tek basina etkisiz; --sync ile birlikte kullanilir.")

    say(f"{C.BOLD}1) Ortam kontrolu{C.RESET}")
    report_environment()

    problems = ru.preflight()
    if problems:
        for problem in problems:
            fail(problem)
        say("")
        return 1
    ok(".env ve sentetik veri dosyasi mevcut")

    try:
        env_problems = check_environment()
    except Exception as exc:  # noqa: BLE001
        fail(f"Ortam denetlenemedi: {exc}")
        return 1
    if env_problems:
        for problem in env_problems:
            fail(problem)
        say("")
        return 1

    if not verify_database():
        return 1

    if args.check:
        say("")
        ok("Ortam hazir. Sunuculari baslatmak icin: python run.py")
        return 0

    say("")
    say(f"{C.BOLD}2) Sunucular{C.RESET}")
    source_process = target_process = None
    exit_code = 0
    interrupted = False
    try:
        source_process = start_source_api(args.source_port)
        target_process = start_target_api(args.target_port)

        if args.sync:
            say("")
            say(f"{C.BOLD}3) Ilk senkronizasyon{C.RESET}")
            if not run_sync(args.full):
                exit_code = 1

        print_status(args.source_port, args.target_port)

        if not args.no_browser and args.open != "none":
            path, label = PAGES[args.open]
            url = f"http://127.0.0.1:{args.target_port}{path}"
            info(f"{label} aciliyor...")
            ru.open_url(url, delay=0.6)

        # Alt sureclerden biri olurse kullaniciyi bilgilendir.
        while True:
            if source_process is not None and source_process.poll() is not None:
                fail("Kaynak API beklenmedik sekilde kapandi. logs/run_source_api.log")
                exit_code = 2
                break
            if target_process is not None and target_process.poll() is not None:
                fail("Hedef API beklenmedik sekilde kapandi. logs/run_target_api.log")
                exit_code = 2
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        say("")
        info("Kapatiliyor...")
        interrupted = True
    finally:
        ru.stop_process(target_process, "Hedef API")
        ru.stop_process(source_process, "Kaynak API")
        say("")
        ok("Tum servisler durduruldu. Verileriniz MSSQL'de korunuyor.")
        say("")

    if interrupted and exit_code == 0:
        return 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
