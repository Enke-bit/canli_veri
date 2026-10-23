"""Kaynak API -> MSSQL senkronizasyonunu elle calistirir.

Kullanim:
    python scripts/sync_api_to_mssql.py
    python scripts/sync_api_to_mssql.py --full
    python scripts/sync_api_to_mssql.py --entities clinics,patients
    python scripts/sync_api_to_mssql.py --source-url http://127.0.0.1:8001

Cikis kodlari:
    0 = basarili
    1 = senkronizasyon hatasi (SyncLog'da Failed)
    2 = yapilandirma / veritabani baglanti hatasi
    3 = baska bir senkronizasyon hala calisiyor
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db import build_engine, check_connection  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402
from app.sync_engine import ENTITY_ORDER, SyncEngine  # noqa: E402

LOCK_FILE = PROJECT_ROOT / "logs" / "sync.lock"


def acquire_lock(stale_seconds: int, logger) -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age > stale_seconds:
            logger.warning(
                "Eski kilit dosyasi bulundu (%.0f sn), sahiplenildi: %s", age, LOCK_FILE
            )
            try:
                LOCK_FILE.unlink()
            except OSError:
                logger.error("Eski kilit dosyasi silinemedi: %s", LOCK_FILE)
                return False
        else:
            try:
                content = LOCK_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                content = "(okunamadi)"
            logger.error(
                "Baska bir senkronizasyon calisiyor olabilir. Kilit: %s (%s). "
                "Calisan islem yoksa bu dosyayi silebilirsiniz.",
                LOCK_FILE,
                content,
            )
            return False
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()} started={time.strftime('%Y-%m-%d %H:%M:%S')}")
        return True
    except FileExistsError:
        logger.error("Kilit yarisi: baska bir surec kilidi aldi.")
        return False


def release_lock(logger) -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        logger.warning("Kilit dosyasi silinemedi: %s", LOCK_FILE)


def parse_entities(raw: str) -> list[str]:
    entities = [part.strip().lower() for part in raw.split(",") if part.strip()]
    unknown = [item for item in entities if item not in ENTITY_ORDER]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Bilinmeyen tur(ler): {', '.join(unknown)}. Gecerli: {', '.join(ENTITY_ORDER)}"
        )
    # Bagimlilik sirasini koru.
    return [entity for entity in ENTITY_ORDER if entity in entities]


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="API -> MSSQL senkronizasyonu")
    parser.add_argument("--source-url", default=None)
    parser.add_argument(
        "--entities",
        type=parse_entities,
        default=list(ENTITY_ORDER),
        help="Varsayilan: clinics,patients,appointments",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Checkpoint'i yok say ve tum kayitlari cek (upsert guvenlidir)",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Kilit dosyasini kullanma (yalnizca test/gelistirme icin)",
    )
    args = parser.parse_args(argv)

    logger = configure_logging("sync", "sync.log", settings.log_level)
    if args.source_url:
        settings = replace(settings, source_api_url=args.source_url.rstrip("/"))

    if not args.no_lock and not acquire_lock(settings.sync_lock_stale_seconds, logger):
        return 3

    engine = None
    try:
        logger.info("Kaynak API: %s", settings.source_api_url)
        engine = build_engine(settings)
        try:
            check_connection(engine)
        except Exception as exc:  # noqa: BLE001
            logger.error("MSSQL baglantisi kurulamadi: %s", exc)
            logger.error(
                "SQL Server servisi, DB_SERVER, veritabani adi ve ODBC surucusunu "
                "kontrol edin. Kurulum icin: python scripts/init_db.py"
            )
            return 2

        sync = SyncEngine(settings, engine)
        try:
            result = sync.run(entities=args.entities, force_full=args.full)
        finally:
            sync.close()

        print("")
        print("=" * 62)
        print(f"Senkronizasyon job_id: {result.job_id}")
        print(f"Durum               : {'BASARILI' if result.success else 'BASARISIZ'}")
        print("-" * 62)
        print(f"{'Tur':<14}{'Okunan':>8}{'Eklenen':>9}{'Guncel':>8}{'Silinen':>9}{'Hata':>6}")
        for stats in result.entities:
            print(
                f"{stats.entity:<14}{stats.read:>8}{stats.inserted:>9}"
                f"{stats.updated:>8}{stats.deleted_marked:>9}{stats.errors:>6}"
            )
        if result.skipped_entities:
            print(f"Calistirilmayan turler: {', '.join(result.skipped_entities)}")
        if result.error:
            print(f"Hata: {result.error}")
        print("=" * 62)
        print("Ayrinti: logs/sync.log ve dbo.SyncLog tablosu")

        return 0 if result.success else 1
    except KeyboardInterrupt:
        logger.warning("Senkronizasyon kullanici tarafindan durduruldu.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if not args.no_lock:
            release_lock(logger)


if __name__ == "__main__":
    raise SystemExit(main())
