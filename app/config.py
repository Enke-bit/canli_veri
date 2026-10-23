"""Uygulama yapilandirmasi.

Tum hassas/ortama bagli degerler .env dosyasindan okunur. Kod icinde
parola veya gercek sunucu bilgisi tutulmaz.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


def _odbc_escape(value: str) -> str:
    """ODBC baglanti dizesi icin guvenli deger uretir."""
    if any(ch in value for ch in ";={}"):
        return "{" + value.replace("}", "}}") + "}"
    return value


@dataclass(frozen=True)
class Settings:
    db_server: str = r".\SQLEXPRESS"
    db_database: str = "DentSyncDemo"
    db_driver: str = "ODBC Driver 18 for SQL Server"
    db_trusted_connection: bool = True
    db_encrypt: bool = True
    db_trust_server_certificate: bool = True
    db_username: str | None = None
    db_password: str | None = None
    db_connection_timeout: int = 10

    source_api_url: str = "http://127.0.0.1:8001"
    source_data_file: str = "data/synthetic_source.json"

    sync_page_size: int = 200
    sync_overlap_seconds: int = 120
    sync_lock_stale_seconds: int = 3600

    http_timeout_seconds: float = 15.0
    http_max_retries: int = 4
    http_backoff_seconds: float = 1.0

    log_level: str = "INFO"

    # Dashboard / tarayici erisimi
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "null",  # file:// uzerinden acilan sayfalar
    )
    # Yerel makinede herhangi bir porttan gelen isteklere izin verir.
    # Yalnizca loopback icin gecerlidir; disariya acik ortamda kapatilmali.
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    # Dashboard'dan senkronizasyon baslatma. Yerel demo icin .env'de acilir.
    enable_sync_trigger: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_server=os.getenv("DB_SERVER", cls.db_server),
            db_database=os.getenv("DB_DATABASE", cls.db_database),
            db_driver=os.getenv("DB_DRIVER", cls.db_driver),
            db_trusted_connection=_env_bool("DB_TRUSTED_CONNECTION", True),
            db_encrypt=_env_bool("DB_ENCRYPT", True),
            db_trust_server_certificate=_env_bool("DB_TRUST_SERVER_CERTIFICATE", True),
            db_username=os.getenv("DB_USERNAME") or None,
            db_password=os.getenv("DB_PASSWORD") or None,
            db_connection_timeout=_env_int("DB_CONNECTION_TIMEOUT", 10),
            source_api_url=os.getenv("SOURCE_API_URL", cls.source_api_url).rstrip("/"),
            source_data_file=os.getenv("SOURCE_DATA_FILE", cls.source_data_file),
            sync_page_size=_env_int("SYNC_PAGE_SIZE", 200),
            sync_overlap_seconds=_env_int("SYNC_OVERLAP_SECONDS", 120),
            sync_lock_stale_seconds=_env_int("SYNC_LOCK_STALE_SECONDS", 3600),
            http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 15.0),
            http_max_retries=_env_int("HTTP_MAX_RETRIES", 4),
            http_backoff_seconds=_env_float("HTTP_BACKOFF_SECONDS", 1.0),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            cors_origins=_env_list("CORS_ORIGINS", cls.cors_origins),
            cors_origin_regex=os.getenv("CORS_ORIGIN_REGEX", cls.cors_origin_regex),
            enable_sync_trigger=_env_bool("ENABLE_SYNC_TRIGGER", False),
        )

    def odbc_connection_string(self, database: str | None = None) -> str:
        """pyodbc icin baglanti dizesi. Parola asla loglanmaz."""
        db = database or self.db_database
        parts = [
            f"DRIVER={{{self.db_driver}}}",
            f"SERVER={_odbc_escape(self.db_server)}",
            f"DATABASE={_odbc_escape(db)}",
            f"Encrypt={'yes' if self.db_encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if self.db_trust_server_certificate else 'no'}",
        ]
        if self.db_trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            if not self.db_username or not self.db_password:
                raise ValueError(
                    "DB_TRUSTED_CONNECTION=false ise DB_USERNAME ve DB_PASSWORD zorunludur."
                )
            parts.append(f"UID={_odbc_escape(self.db_username)}")
            parts.append(f"PWD={_odbc_escape(self.db_password)}")
        return ";".join(parts) + ";"

    def sqlalchemy_url(self, database: str | None = None) -> str:
        return "mssql+pyodbc:///?odbc_connect=" + quote_plus(
            self.odbc_connection_string(database)
        )

    def masked_summary(self) -> dict[str, object]:
        """Loglanabilir, sirsiz baglanti ozeti."""
        return {
            "server": self.db_server,
            "database": self.db_database,
            "driver": self.db_driver,
            "trusted_connection": self.db_trusted_connection,
            "encrypt": self.db_encrypt,
            "trust_server_certificate": self.db_trust_server_certificate,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def resolve_data_file(path: str | None = None) -> Path:
    """Goreli veri yollarini proje kokune gore cozer."""
    raw = path or get_settings().source_data_file
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate
