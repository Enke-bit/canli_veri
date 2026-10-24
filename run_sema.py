"""Semali mimari anlatimini tek komutla acar:  http://127.0.0.1:8000/mimari

    python run_sema.py

Hedef API (8000) calismiyorsa baslatir, mimari sayfasini tarayicida acar.
Sayfa; 6 SVG sema ile veri akisini, ER modelini, senkronizasyon sirasini,
checkpoint/ortusme penceresini, hata-retry kararini ve aktarim ritmini anlatir.

Secenekler:
    --port 8010     Farkli port
    --no-browser    Tarayiciyi acma
    --url-only      Yalnizca adresi yazdir
"""
from __future__ import annotations

import runner_utils as ru

PAGE = "/mimari"
LABEL = "Mimari ve canli veri akisi (SVG semalar)"
NOTES = [
    "6 sema: uctan uca akis, ER modeli, tur sirasi, checkpoint, hata/retry, ritim.",
    "Tasarim kararlarinin gerekceleri ve olcekleme yol haritasi da bu sayfada.",
]


def main(argv: list[str] | None = None) -> int:
    return ru.run_page_script(PAGE, LABEL, NOTES, argv)


if __name__ == "__main__":
    raise SystemExit(main())
