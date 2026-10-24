"""Calistirici betikleri icin ek testler: yetim surec davranisi.

Alt sureclerin ebeveynle birlikte oldugunu (Windows Job Object) dogrular.
Kaynak API (mock_source) kullanilir; MSSQL'e ihtiyac duymaz.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows'a ozgu davranis")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _health(port: int) -> int | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            return response.status
    except Exception:  # noqa: BLE001
        return None


def _wait_health(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(port) == 200:
            return True
        time.sleep(0.4)
    return False


def _wait_down(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(port) is None:
            return True
        time.sleep(0.4)
    return False


def test_child_api_dies_with_parent(tmp_path):
    """Ebeveyn zorla oldurulse bile uvicorn ayakta kalmamali (yetim surec yok)."""
    port = _free_port()
    script = tmp_path / "parent.py"
    script.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, r'{PROJECT_ROOT}')\n"
        "import runner_utils as ru\n"
        f"ru.start_api('mock_source.main:app', {port}, 'test_orphan.log')\n"
        "print('started', flush=True)\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )

    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert _wait_health(port), "Alt surec baslatilamadi"
        # En kotu senaryo: ebeveyni zorla oldur; cocuk da olmeli.
        process.kill()
        process.wait(timeout=15)
        assert _wait_down(port), "Yetim uvicorn sureci kaldi"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        # Testin biraktigi log dosyasini temizle.
        log_file = PROJECT_ROOT / "logs" / "test_orphan.log"
        if log_file.exists():
            try:
                log_file.unlink()
            except OSError:
                pass
