"""Sunumu tek komutla acar:  http://127.0.0.1:8000/slayt

    python run_slayt.py

"Canli veri cekme mimarisi" slayt destesini (14 slayt) tarayicida acar.
Sunum icinde: sag/sol ok tuslari gezinme, F tam ekran, Home/End, P yazdir/PDF.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/slayt"
LABEL = "Sunum: canli veri cekme mimarisi (14 slayt)"
NOTES = [
    "Klavye: sag/sol ok tuslari, F tam ekran, Home/End, P yazdir.",
    "Icerik: problem, akis, artimli cekme, ortusme, upsert, retry, olcekleme.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
