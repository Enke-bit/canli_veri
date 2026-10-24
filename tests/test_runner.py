"""Calistirici betiklerin (run.py ve run_*.py) temel testleri.

Bu testler sunucu baslatmaz; yalnizca dosyalarin, arayuzlerin ve
--help/--check gibi zararsiz yolların calistigini dogrular.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RUNNERS = [
    "run.py",
    "run_panel.py",
    "run_sema.py",
    "run_sifir_kurulum.py",
    "run_slayt.py",
]


@pytest.mark.parametrize("name", RUNNERS)
def test_runner_file_exists_and_is_importable(name):
    path = PROJECT_ROOT / name
    assert path.exists(), f"{name} bulunamadi"
    source = path.read_text(encoding="utf-8")
    assert "runner_utils" in source, f"{name} ortak yardimciyi kullanmiyor"
    # Dosya sozdizimi hatasi icermemeli.
    compile(source, name, "exec")


@pytest.mark.parametrize("name", RUNNERS)
def test_runner_help_exits_cleanly(name):
    """--help her betikte aninda cikmali; sunucu baslatmamali."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / name), "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "Traceback" not in result.stderr, result.stderr[-1200:]
    assert "usage:" in (result.stdout + result.stderr).lower()
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("name", "page"),
    [
        ("run_panel.py", "/dashboard"),
        ("run_sema.py", "/mimari"),
        ("run_sifir_kurulum.py", "/kilavuz"),
        ("run_slayt.py", "/slayt"),
    ],
)
def test_page_runners_url_only_prints_url_without_starting_server(name, page):
    """--url-only sunucu baslatmadan adresi yazar (CI icin onemli)."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / name), "--url-only", "--port", "8099"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-1200:]
    assert f"http://127.0.0.1:8099{page}" in result.stdout


def test_run_py_lists_pages_in_help():
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "run.py"), "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    for page in ("panel", "sema", "kilavuz", "slayt", "docs"):
        assert page in output
    assert "--sync" in output


def test_runner_utils_page_urls():
    import runner_utils as ru

    assert ru.page_url("/dashboard") == "http://127.0.0.1:8000/dashboard"
    assert ru.page_url("/mimari", port=8010) == "http://127.0.0.1:8010/mimari"


def test_runner_utils_port_probe():
    import socket

    import runner_utils as ru

    # Bos bir portu dinlemeye alip in_use dogrulanir.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert ru.port_in_use(port) is True


def test_runner_utils_preflight_reports_missing_pieces(tmp_path, monkeypatch):
    import runner_utils as ru

    monkeypatch.setattr(ru, "ROOT", tmp_path)
    problems = ru.preflight()
    assert any(".env" in problem for problem in problems)
    assert any("Sentetik veri" in problem for problem in problems)


def test_runner_utils_preflight_ok(tmp_path, monkeypatch):
    import runner_utils as ru

    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "synthetic_source.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ru, "ROOT", tmp_path)
    assert ru.preflight() == []
