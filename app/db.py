"""SQLAlchemy motoru ve oturum yonetimi."""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def build_engine(settings: Settings, database: str | None = None) -> Engine:
    """Baglanti havuzlu motor olusturur (her istekte yeni baglanti degil)."""
    engine = create_engine(
        settings.sqlalchemy_url(database),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        connect_args={"timeout": settings.db_connection_timeout},
        future=True,
    )
    logger.info("SQLAlchemy motoru hazir: %s", settings.masked_summary())
    return engine


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = build_engine(settings)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI bagimliligi: istek basina oturum, sonunda kapanir."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Testlerde yapilandirma degistiginde motoru temizler."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def check_connection(engine: Engine) -> None:
    """Baglantiyi dogrular; hata varsa acik mesajla yukseltir."""
    from sqlalchemy import text

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
