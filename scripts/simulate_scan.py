#!/usr/bin/env python3
"""Turn a digital PDF into scan-like page images, to test the raster path on more documents.

    python scripts/simulate_scan.py DOC.pdf OUT_DIR [--dpi 128] [--seed 1]

Each page is rendered at 300 dpi and then degraded like an office scan: down-sampled
to --dpi, a slight skew, a warm paper tint, blur, sensor noise, and JPEG compression.
The result has no text layer, so synthero treats it as a scan (Tesseract positions).
Writes OUT_DIR/STEM.pdf with one scanned image per page.
"""

from __future__ import annotations

import argparse
import io
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


def degrade(page: Image.Image, dpi: int, rng: random.Random) -> Image.Image:
    scale = dpi / 300
    img = page.convert("RGB").resize((round(page.width * scale), round(page.height * scale)), Image.Resampling.LANCZOS)
    img = img.rotate(rng.uniform(-0.6, 0.6), resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
    tint = Image.new("RGB", img.size, (rng.randint(244, 252), rng.randint(242, 250), rng.randint(232, 244)))
    img = ImageChops.multiply(img, tint)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.7)))
    noise = Image.effect_noise(img.size, rng.uniform(6, 12)).convert("RGB")
    img = Image.blend(img, ImageChops.multiply(img, noise), 0.08)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(60, 80))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--dpi", type=int, default=128)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.pdf).stem
    rng = random.Random(f"{a.seed}:{stem}")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "300", "-png", a.pdf, f"{tmp}/page"], check=True)
        pages = [degrade(Image.open(p), a.dpi, rng) for p in sorted(Path(tmp).glob("page-*.png"))]
    pages[0].save(out / f"{stem}.pdf", save_all=True, append_images=pages[1:], resolution=a.dpi)
    print(out / f"{stem}.pdf", len(pages), "pages")


if __name__ == "__main__":
    main()
