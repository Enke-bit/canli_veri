"""Gereksinim sunumunu acar:  http://127.0.0.1:8000/slayt-gereksinim

    python run_slayt_gereksinim.py

"Canli veri cekmek icin gereken sistemler ve uygulanma yontemleri" sunumu
(12 slayt): altyapi, kaynak sozlesme, veritabani yapilari, senkronizasyon
servisi, guvenlik, operasyon, kabul kriterleri ve yol haritasi.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/slayt-gereksinim"
LABEL = "Sunum: canli veri icin gereken sistemler"
NOTES = [
    "12 slayt: 5 katman, kaynak sozlesmesi, yontem secimi, kabul kriterleri, fazlar.",
    "Her gereksinim projede hangi dosyayla karsilaniyor, tabloda gosterilir.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
