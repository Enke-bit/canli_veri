"""Sifirdan calistirma kilavuzunu tek komutla acar:  http://127.0.0.1:8000/kilavuz

    python run_sifir_kurulum.py

Hedef API (8000) calismiyorsa baslatir, kilavuzu tarayicida acar.
Kilavuz; Python, SQL Server, ODBC, venv, .env, veritabani, sentetik veri,
iki API, senkronizasyon ve otomasyonu sirayla anlatir.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/kilavuz"
LABEL = "Sifirdan calistirma kilavuzu"
NOTES = [
    "15 bolum: ortam kontrolu, .env, MSSQL, sentetik veri, API'ler, sync, otomasyon.",
    "Her komutun beklenen ciktisi ve 8 satirlik sorun giderme tablosu vardir.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
