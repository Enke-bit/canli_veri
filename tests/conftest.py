"""pytest ortak fixture'lari.

Iki katman:
1. Saf Python testleri (her zaman calisir).
2. MSSQL entegrasyon testleri: ayri bir DenSyncTest veritabani kullanir.
   SQL Server yoksa otomatik atlanir (skip). Mevcut DentSyncDemo verisine
   dokunulmaz.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402

TEST_DATABASE = "DentSyncTest"


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def mssql_settings(settings):
    """Test veritabani ayarlari. Guvenlik: ad 'Test' ile bitmelidir."""
    if not TEST_DATABASE.endswith("Test"):
        pytest.fail("Test veritabani adi 'Test' ile bitmelidir.")
    return replace(settings, db_database=TEST_DATABASE)


@pytest.fixture(scope="session")
def mssql_engine(mssql_settings):
    """Test veritabanini (yoksa) olusturur ve semayi uygular."""
    import pyodbc
    from sqlalchemy import text

    from app.db import build_engine
    from scripts.init_db import apply_schema, ensure_database

    if mssql_settings.db_driver not in pyodbc.drivers():
        pytest.skip(f"ODBC surucusu kurulu degil: {mssql_settings.db_driver}")

    class _SilentLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    try:
        ensure_database(mssql_settings, _SilentLogger())
        apply_schema(mssql_settings, _SilentLogger())
        engine = build_engine(mssql_settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MSSQL entegrasyon testi atlandi (baglanti yok): {exc}")

    yield engine
    engine.dispose()


@pytest.fixture()
def clean_db(mssql_engine):
    """Test veritabanindaki tablolari temizler (yalnizca DenSyncTest)."""
    from sqlalchemy import text

    with mssql_engine.begin() as connection:
        for table in (
            "Appointments",
            "Patients",
            "Clinics",
            "SyncState",
            "SyncLog",
        ):
            connection.execute(text(f"DELETE FROM dbo.[{table}]"))
    yield mssql_engine


@pytest.fixture()
def source_data_file(tmp_path, monkeypatch):
    """Mock API'nin gecici veri dosyasi."""
    path = tmp_path / "synthetic_source.json"
    monkeypatch.setenv("SOURCE_DATA_FILE", str(path))
    return path


@pytest.fixture(scope="session")
def source_api_server():
    """Mock kaynak API'yi gercek HTTP uzerinden test etmek icin
    arka planda rastgele bir portta uvicorn baslatir."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from mock_source.main import app as source_app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        source_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    last_error = None
    while time.time() < deadline:
        if server.started:
            try:
                response = httpx.get(base_url + "/openapi.json", timeout=2)
                if response.status_code == 200:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        time.sleep(0.2)
    else:
        server.should_exit = True
        pytest.fail(f"Kaynak API test sunucusu baslatilamadi: {last_error}")

    yield base_url

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session", autouse=True)
def _quiet_logging():
    os.environ.setdefault("LOG_LEVEL", "WARNING")
