"""DentSyncDemo veritabanini ve semasini guvenli sekilde olusturur.

- Veritabani yoksa olusturur; varsa dokunmaz.
- Tablolar yoksa olusturur; var olan tablo/veriyi silmez.
- --check-only ile yalnizca mevcut durumu raporlar.

Kullanim:
    python scripts/init_db.py
    python scripts/init_db.py --check-only
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyodbc  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402

SQL_FILE = PROJECT_ROOT / "sql" / "create_tables.sql"
EXPECTED_TABLES = ["Clinics", "Patients", "Appointments", "SyncState", "SyncLog"]
DB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def split_sql_batches(script: str) -> list[str]:
    """SSMS 'GO' ayiricilarini SQL Server'in anlayacagi partilere boler."""
    batches: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def _safe_db_name(name: str) -> str:
    if not DB_NAME_PATTERN.match(name):
        raise ValueError(
            "Veritabani adi yalnizca harf, rakam ve alt cizgi icerebilir: " + name
        )
    return name


def _connect(settings: Settings, database: str) -> pyodbc.Connection:
    return pyodbc.connect(
        settings.odbc_connection_string(database), timeout=settings.db_connection_timeout
    )


def ensure_database(settings: Settings, logger) -> bool:
    """Veritabani yoksa olusturur. True = yeni olusturuldu."""
    name = _safe_db_name(settings.db_database)
    with _connect(settings, "master") as connection:
        connection.autocommit = True
        cursor = connection.cursor()
        exists = cursor.execute("SELECT DB_ID(?)", name).fetchval()
        if exists is not None:
            logger.info("Veritabani zaten var: %s (dokunulmadi)", name)
            return False
        # Veritabani adi parametre olarak verilemez; _safe_db_name ile dogrulandi.
        cursor.execute(f"CREATE DATABASE [{name}]")
        logger.info("Veritabani olusturuldu: %s", name)
        return True


def apply_schema(settings: Settings, logger) -> None:
    script = SQL_FILE.read_text(encoding="utf-8")
    batches = split_sql_batches(script)
    with _connect(settings, settings.db_database) as connection:
        connection.autocommit = True
        cursor = connection.cursor()
        for index, batch in enumerate(batches, start=1):
            try:
                cursor.execute(batch)
                while cursor.nextset():
                    pass
            except pyodbc.Error as exc:
                logger.error("SQL partisi %s basarisiz: %s", index, exc)
                raise
    logger.info("Sema betigi uygulandi (%s parti).", len(batches))


def report(settings: Settings, logger) -> bool:
    """Tablolari ve satir sayilarini raporlar. Semada eksik varsa False."""
    with _connect(settings, settings.db_database) as connection:
        cursor = connection.cursor()
        rows = cursor.execute(
            "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') ORDER BY name"
        ).fetchall()
        existing = {row[0] for row in rows}
        logger.info("Mevcut tablolar: %s", ", ".join(sorted(existing)) or "(yok)")
        missing = [table for table in EXPECTED_TABLES if table not in existing]
        if missing:
            logger.error("Eksik tablolar: %s", ", ".join(missing))
            return False
        for table in EXPECTED_TABLES:
            count = cursor.execute(f"SELECT COUNT(*) FROM dbo.[{table}]").fetchval()
            logger.info("  %-14s %s satir", table, count)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DentSyncDemo veritabani kurulumu")
    parser.add_argument("--server", default=None)
    parser.add_argument("--database", default=None)
    parser.add_argument("--driver", default=None)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Sema olusturmadan yalnizca mevcut durumu kontrol et",
    )
    args = parser.parse_args(argv)

    logger = configure_logging("init_db", "init_db.log")
    settings = get_settings()
    overrides = {}
    if args.server:
        overrides["db_server"] = args.server
    if args.database:
        overrides["db_database"] = args.database
    if args.driver:
        overrides["db_driver"] = args.driver
    if overrides:
        settings = replace(settings, **overrides)

    logger.info("Baglanti hedefi: %s", settings.masked_summary())

    available = pyodbc.drivers()
    if settings.db_driver not in available:
        logger.error(
            "ODBC surucusu bulunamadi: '%s'. Kurulu suruculer: %s",
            settings.db_driver,
            ", ".join(available) or "(yok)",
        )
        logger.error(
            "Microsoft ODBC Driver 18 for SQL Server kurun veya .env icinde "
            "DB_DRIVER degerini kurulu bir surucuyle degistirin."
        )
        return 2

    try:
        if not args.check_only:
            ensure_database(settings, logger)
            apply_schema(settings, logger)
        ok = report(settings, logger)
    except pyodbc.Error as exc:
        logger.error("SQL Server islemi basarisiz: %s", exc)
        logger.error(
            "Kontrol edin: SQL Server servisi calisiyor mu, DB_SERVER dogru mu, "
            "Windows Authentication izniniz var mi, ODBC surucusu kurulu mu?"
        )
        return 1
    except ValueError as exc:
        logger.error("Yapilandirma hatasi: %s", exc)
        return 2

    if ok:
        logger.info("Veritabani hazir: %s", settings.db_database)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
