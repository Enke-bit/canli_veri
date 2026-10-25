"""Basit anlatim sunumunu acar:  http://127.0.0.1:8000/slayt-senkron

    python run_slayt_senkron.py

"Canli veri nasil cekilir?" sorusunu 11 slaytta sade dille anlatir:
sorun, 4 kural, bir turun 6 adimi, hata durumu ve ozet.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/slayt-senkron"
LABEL = "Sunum: canli veri nasil cekilir (basit anlatim)"
NOTES = [
    "11 slayt: sorun, 4 kural, bir turun 6 adimi, hata durumu, ozet.",
    "Klavye: sag/sol ok tuslari, F tam ekran, P yazdir.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
