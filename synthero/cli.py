"""Make synthetic copies of a scanned or digital document with new personal data.

    synthero DOCUMENT [--n 3] [--out /dev/shm/synthero/out] [--seed 1]

DOCUMENT is an image or a PDF (scanned pages, text pages, or both).

1. Each page is an image with word boxes: from Tesseract for a scan, from the text
   layer for a digital PDF page. OCR text is never trusted as a value.
2. The model reads the personal values from the page image (type, owner, rough box).
3. Each value is located: OCR words that match it, a corrected reading, or pixel lines.
4. Each copy replaces located values with consistent invented ones across all pages,
   redrawing only their words; barcodes are redrawn; each edit is read back, and each
   page is checked for any surviving original value. A value that could not be
   located fails that check.

Outputs (in --out): STEM.pN.original.png and STEM.pN.boxes.png per page, and per copy
STEM.copy-K.pN.png, STEM.copy-K.pdf, and STEM.copy-K.json, the public answer key with
new values only. The analysis and the old-to-new mappings go to --private, which must
never be served or shared.
"""

from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw

from synthero import detect, locate, ocr, source, synth, vl
from synthero.locate import Located

# Red: OCR words matched the value. Purple: OCR and a second reading agreed on a
# corrected value. Orange: found from pixels and read back.
BOX_COLOURS = {"ocr": (220, 30, 30), "ocr+read": (150, 40, 200), "pixels": (230, 140, 0)}


def _save(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def analyse(page: source.Page, cache: str) -> synth.Analysed:
    """The values on a page and every place each is printed. Cached per page in the private folder."""
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            vals, locs = synth.analysis_from_json(json.load(f))
    else:
        vals = detect.find_values(page.image, "\n".join(ln.text for ln in page.lines))
        locs = locate.locate(page.image, vals, page.lines, vl.read_text, ocr.lines)
        _save(cache, synth.analysis_to_json(vals, locs))
    context = synth.page_context(" ".join(ln.text for ln in page.lines), vals, locs)
    return synth.Analysed(page.image, vals, locs, context)


def debug_boxes(scan: Image.Image, locs: list[list[Located]], path: str) -> None:
    img = scan.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for places in locs:
        for loc in places:
            d.rectangle(loc.run_box, outline=BOX_COLOURS.get(loc.how, (230, 140, 0)), width=2)
    img.save(path)


def summary(i: int, key: synth.Key) -> str:
    changes = [c for p in key["pages"] for c in p["changes"]]
    edited = [c for c in changes if c["places"]]
    ok = sum(c["read_back_ok"] for c in edited)
    checks = [p["leak_check"] for p in key["pages"] if "leak_check" in p]
    leaked = sorted({t for lc in checks for t in lc["leaked_types"]})
    verdict = "" if not checks else ("leak check passed" if not leaked else f"LEAK of {leaked}")
    bars = sum(p["barcodes_scrambled"] for p in key["pages"])
    return f"copy {i}: {len(edited)} values replaced, {ok} read back correctly, {bars} barcodes scrambled, {verdict}"


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("document", help="an image or a PDF")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150, help="resolution for digital PDF pages")
    ap.add_argument("--out", default="/dev/shm/synthero/out")
    ap.add_argument(
        "--private",
        default="/dev/shm/synthero/private",
        help="folder for the analysis and old-to-new mappings; never serve or share it",
    )
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--no-leak-check", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.private, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.document))[0]
    pages = []
    for n, page in enumerate(source.load(a.document, a.dpi), start=1):
        analysed = analyse(page, os.path.join(a.private, f"{stem}.p{n}.analysis.json"))
        page.image.save(os.path.join(a.out, f"{stem}.p{n}.original.png"))
        debug_boxes(page.image, analysed.locs, os.path.join(a.out, f"{stem}.p{n}.boxes.png"))
        places = [p for ps in analysed.locs for p in ps]
        by_ocr = sum(1 for p in places if p.how != "pixels")
        print(
            f"page {n} ({page.kind}): {len(analysed.values)} personal values, "
            f"{sum(1 for ps in analysed.locs if ps)} located in {len(places)} places "
            f"({by_ocr} by OCR, {len(places) - by_ocr} by pixels)",
            flush=True,
        )
        pages.append(analysed)
    for i in range(a.n):
        copy = synth.make_copy(
            pages,
            a.seed + i,
            read=None if a.no_verify else vl.read_text,
            read_page=None if a.no_leak_check else vl.read_page,
        )
        base = os.path.join(a.out, f"{stem}.copy-{i + 1}")
        for n, image in enumerate(copy.images, start=1):
            image.save(f"{base}.p{n}.png")
        copy.images[0].save(f"{base}.pdf", save_all=True, append_images=copy.images[1:])
        _save(f"{base}.json", copy.key)
        _save(os.path.join(a.private, f"{stem}.copy-{i + 1}.private.json"), copy.private_key)
        print(summary(i + 1, copy.key), flush=True)


if __name__ == "__main__":
    main()
