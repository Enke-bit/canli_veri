"""Calistirici betiklerin ortak yardimcilari.

run.py ve run_*.py dosyalari buradaki kucuk fonksiyonlari kullanir.
Amac: Windows'ta tek komutla projeyi ayaga kaldirmak, sayfa acmak ve
Ctrl+C ile temiz kapatmak. Harici paket gerektirmez (yalnizca stdlib).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

# Windows konsolu Turkce karakterleri ve oklari basamayabilir (ör. cp1254).
# Kodlama degistirilemiyorsa en azindan cokmeyi engelle: desteklenmeyen
# karakter '<=' olarak yazilir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        pass

# Windows terminalinde renk destegi (yoksa sessizce duz metne doner).
_NO_COLOR = os.getenv("NO_COLOR") is not None or not sys.stdout.isatty()


class C:
    RESET = "" if _NO_COLOR else "\033[0m"
    BOLD = "" if _NO_COLOR else "\033[1m"
    DIM = "" if _NO_COLOR else "\033[2m"
    GREEN = "" if _NO_COLOR else "\033[92m"
    YELLOW = "" if _NO_COLOR else "\033[93m"
    RED = "" if _NO_COLOR else "\033[91m"
    CYAN = "" if _NO_COLOR else "\033[96m"
    BLUE = "" if _NO_COLOR else "\033[94m"


def say(message: str = "") -> None:
    """Konsola yazar; kodlama hatasi olsa bile cokmez."""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe, flush=True)


def ok(message: str) -> None:
    say(f"{C.GREEN}[OK]{C.RESET}   {message}")


def warn(message: str) -> None:
    say(f"{C.YELLOW}[!]{C.RESET}    {message}")


def fail(message: str) -> None:
    say(f"{C.RED}[X]{C.RESET}    {message}")


def info(message: str) -> None:
    say(f"{C.CYAN}[i]{C.RESET}    {message}")


def title(message: str) -> None:
    line = "=" * 66
    say(f"\n{C.BOLD}{line}\n  {message}\n{line}{C.RESET}\n")


def ensure_venv() -> None:
    """Betik global Python ile calistirildiysa sanal ortama gec.

    Boylece kullanici '.venv\\Scripts\\activate' yapmayi unutsa bile
    paketler bulunur. Sanal ortam yoksa anlasilir bir mesaj verir.
    """
    if os.getenv("MSSQLSYNC_NO_REEXEC") == "1":
        return

    try:
        import fastapi  # noqa: F401
        return
    except ImportError:
        pass

    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = ROOT / ".venv" / "bin" / "python"  # Linux/macOS

    if not venv_python.exists():
        fail("Sanal ortam bulunamadi ve paketler kurulu degil.")
        say("")
        say("  Once su komutlari calistirin:")
        say(f"    {C.BOLD}python -m venv .venv{C.RESET}")
        say(f"    {C.BOLD}.venv\\Scripts\\python.exe -m pip install -r requirements.txt{C.RESET}")
        say("")
        raise SystemExit(1)

    # Ayni betigi sanal ortamdaki Python ile yeniden baslat.
    env = os.environ.copy()
    env["MSSQLSYNC_NO_REEXEC"] = "1"
    result = subprocess.run([str(venv_python), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]], env=env)
    raise SystemExit(result.returncode)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        return sock.connect_ex((host, port)) == 0


def wait_for_health(url: str, timeout: float = 40.0, expect_json: bool = True) -> bool:
    """API /health 200 donene kadar bekler."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    if not expect_json:
                        return True
                    body = response.read(200)
                    if body.startswith(b"{"):
                        return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            pass
        time.sleep(0.35)
    return False


def health_summary(base_url: str) -> dict | None:
    try:
        with urllib.request.urlopen(base_url + "/health", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - teshis amacli, hata yutulur
        return None


def preflight() -> list[str]:
    """Kurulumun temel parcalarini kontrol eder; uyari listesi dondurur."""
    problems: list[str] = []
    if not (ROOT / ".env").exists():
        problems.append(
            ".env dosyasi yok. '.env.example' dosyasini kopyalayin: "
            "Copy-Item .env.example .env"
        )
    if not (ROOT / "data" / "synthetic_source.json").exists():
        problems.append(
            "Sentetik veri yok. Calistirin: "
            ".venv\\Scripts\\python.exe scripts\\generate_synthetic_data.py"
        )
    return problems


def start_api(module: str, port: int, log_name: str) -> subprocess.Popen:
    """Uvicorn'u alt surec olarak baslatir; cikti logs/<log_name> dosyasina yazilir.

    Windows'ta cocuk surec bir Job Object'e atanir. Boylece bu betik ne sekilde
    sonlanirsa sonlansin (Ctrl+C, pencere kapatma, hatta zorla oldurme) uvicorn
    de olur; arkada "yetim" sunucu kalmaz.
    """
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_name
    handle = open(log_path, "a", encoding="utf-8")
    handle.write(f"\n\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} baslatildi: {module}:{port} ===\n")
    handle.flush()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")

    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
        **kwargs,
    )
    process._log_handle = handle  # type: ignore[attr-defined]  # kapanista kapatilir
    _assign_to_job(process)
    return process


# --------------------------------------------------------------------------
# Windows Job Object: cocuk surecin ebeveynle birlikte olmesini garantiler.
# --------------------------------------------------------------------------
_JOB_HANDLE = None


def _assign_to_job(process: subprocess.Popen) -> None:
    global _JOB_HANDLE
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - Windows'ta her zaman var
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    try:
        if _JOB_HANDLE is None:
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            _JOB_HANDLE = handle
        kernel32.AssignProcessToJobObject(_JOB_HANDLE, int(process._handle))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - job atanamazsa normal terminate'e doneriz
        pass


def _kill_tree(pid: int) -> None:
    """Windows'ta cocuk surec agacini oldurur (uvicorn alt islemleri dahil)."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001
        pass


def stop_process(process: subprocess.Popen | None, name: str = "") -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        _kill_tree(process.pid)
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            pass
    else:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                pass
    handle = getattr(process, "_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass
    if name:
        info(f"{name} durduruldu.")


def open_url(url: str, delay: float = 0.0) -> None:
    if delay:
        time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        warn(f"Tarayici otomatik acilamadi. Adresi elle acin: {url}")


def ensure_target_api(port: int = 8000, verbose: bool = True) -> subprocess.Popen | None:
    """Hedef API calismiyorsa baslatir. Zaten calisiyorsa None doner."""
    base = f"http://127.0.0.1:{port}"
    if wait_for_health(base + "/health", timeout=1.5):
        if verbose:
            ok(f"Hedef API zaten calisiyor: {base}")
        return None

    if port_in_use(port):
        warn(f"{port} portu baska bir surec tarafindan kullaniliyor; mevcut surec denenecek.")
        if wait_for_health(base + "/health", timeout=8):
            return None
        fail(f"{port} portundaki surec saglikli yanit vermiyor.")
        raise SystemExit(2)

    if verbose:
        info("Hedef API baslatiliyor...")
    process = start_api("app.main:app", port, "run_target_api.log")
    if not wait_for_health(base + "/health"):
        stop_process(process, "Hedef API")
        fail("Hedef API baslatilamadi. Ayrinti: logs/run_target_api.log")
        raise SystemExit(2)
    if verbose:
        ok(f"Hedef API hazir: {base}")
    return process


def page_url(page: str, port: int = 8000) -> str:
    return f"http://127.0.0.1:{port}{page}"


def open_page(page: str, port: int = 8000, label: str = "Sayfa", browser: bool = True) -> None:
    """Hedef API'yi garantiler, sayfayi tarayicida acar, Ctrl+C'ye kadar bekler."""
    owner = ensure_target_api(port)
    url = page_url(page, port)
    say("")
    say(f"  {C.BOLD}{label}{C.RESET}")
    say(f"  {C.CYAN}{url}{C.RESET}")
    say("")
    if owner is not None:
        say(f"  {C.DIM}Bu pencere kapanirsa API de kapanir. Durdurmak icin Ctrl+C.{C.RESET}")
    else:
        say(f"  {C.DIM}API baska bir pencerede calisiyor; bu pencereyi kapatabilirsiniz.{C.RESET}")
    say("")

    if browser:
        open_url(url)
    else:
        say(f"  {C.DIM}Tarayici acilmadi (--no-browser).{C.RESET}")
        say("")

    if owner is None:
        return

    try:
        while owner.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        say("")
        info("Kapatiliyor...")
    finally:
        stop_process(owner, "Hedef API")


def run_page_script(
    page: str,
    label: str,
    notes: list[str],
    argv: list[str] | None = None,
    default_port: int = 8000,
) -> int:
    """run_panel.py / run_sema.py gibi sayfa betiklerinin ortak govdesi.

    Secenekler:
        --port N        Hedef API portu (varsayilan 8000)
        --no-browser    Tarayiciyi acma
        --url-only      Yalnizca adresi yazdir; sunucu baslatma ve bekleme yok
        --help          Bu yardimi goster
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=f"DentSync - {label}",
        epilog="Ornek: python run_panel.py --no-browser",
    )
    parser.add_argument(
        "--port", type=int, default=default_port, help=f"Hedef API portu (varsayilan {default_port})"
    )
    parser.add_argument("--no-browser", action="store_true", help="Tarayiciyi acma")
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="Yalnizca adresi yazdir; sunucu baslatma ve bekleme yok",
    )
    args = parser.parse_args(argv)

    ensure_venv()
    title(f"DentSync | {label}")
    for note in notes:
        info(note)
    url = page_url(page, args.port)
    if args.url_only:
        say(url)
        return 0

    say("")
    open_page(page, port=args.port, label=label, browser=not args.no_browser)
    return 0
