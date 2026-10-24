"""Paneli tek komutla acar:  http://127.0.0.1:8000/dashboard

    python run_panel.py

Hedef API (8000) calismiyorsa baslatir, paneli tarayicida acar ve siz
Ctrl+C yapana kadar acik tutar. API zaten calisiyorsa yalnizca sayfayi acar.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir (CI/betik kullanimi icin)
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/dashboard"
LABEL = "Canli analitik paneli (dashboard)"
NOTES = [
    "Panel, MSSQL'deki gercek verileri gosterir; sahte veri uretmez.",
    "Icerik: saglik durumu, metrikler, durum dagilimi, trend, klinik hacmi, sync akisi.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
