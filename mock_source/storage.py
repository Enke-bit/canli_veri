"""Sentetik kaynak verisinin dosya tabanli, kilitli deposu.

- Okuma/yazma ayni surec icinde RLock ile korunur.
- Dosyaya yazma atomiktir (gecici dosya + os.replace).
- Bu depo tek surec (tek uvicorn worker) icin tasarlanmistir.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_lock = threading.RLock()


class SourceDataError(RuntimeError):
    """Kaynak veri dosyasi yok veya bozuk."""


def data_path() -> Path:
    raw = os.getenv("SOURCE_DATA_FILE", "data/synthetic_source.json")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _validate_structure(data: Any) -> None:
    if not isinstance(data, dict):
        raise SourceDataError("Kaynak veri dosyasinin kok nesnesi JSON object olmalidir.")
    for key in ("clinics", "patients", "appointments"):
        if key not in data or not isinstance(data[key], list):
            raise SourceDataError(
                f"Kaynak veri dosyasinda '{key}' listesi bulunamadi veya gecersiz."
            )


def load_data(required: bool = True) -> dict[str, Any]:
    path = data_path()
    with _lock:
        if not path.exists():
            if not required:
                return {"meta": {}, "clinics": [], "patients": [], "appointments": []}
            raise SourceDataError(
                f"Sentetik veri dosyasi bulunamadi: {path}. "
                "Once 'python scripts/generate_synthetic_data.py' komutunu calistirin."
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise SourceDataError(
                f"Kaynak veri dosyasi gecerli JSON degil ({path}): {exc}"
            ) from exc
        _validate_structure(data)
        return data


def save_data(data: dict[str, Any]) -> None:
    """Atomik yazma: yarim kalmis dosya birakmaz."""
    _validate_structure(data)
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        temp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


@contextmanager
def transaction() -> Iterator[dict[str, Any]]:
    """Oku-degistir-yaz islemini kilit altinda yapar."""
    with _lock:
        data = load_data(required=True)
        yield data
        save_data(data)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
