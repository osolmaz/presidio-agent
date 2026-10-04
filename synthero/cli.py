"""Make synthetic copies of a scanned document with new personal data.

    synthero SCAN.png [--n 3] [--out /dev/shm/synthero/out] [--seed 1]

1. Tesseract gives word positions; its text is never trusted as a value.
2. The model reads the personal values from the image (type, owner, rough box).
3. Each value is located: OCR words that match it, else pixel lines read back.
4. Each copy replaces located values with consistent invented ones, redrawing only
   their words; it is read back, and the whole page is checked for any surviving
   original value. Values that could not be located make the copy fail that check.

Outputs (in --out): copy-N.png and copy-N.json, the public answer key with new
values only. The analysis and the old-to-new mappings go to --private, which must
never be served or shared.
"""

from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw

from synthero import detect, locate, ocr, synth, vl
from synthero.detect import Value
from synthero.locate import Located

# Red: OCR words matched the value. Purple: OCR and a second reading agreed on a
# corrected value. Orange: found from pixels and read back.
BOX_COLOURS = {"ocr": (220, 30, 30), "ocr+read": (150, 40, 200), "pixels": (230, 140, 0)}


def _save(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def analyse(scan: Image.Image, ocr_lines: list[ocr.Line], cache: str) -> tuple[list[Value], list[list[Located]]]:
    """Detected values and every place each is printed. Cached per scan in the private folder."""
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return synth.analysis_from_json(json.load(f))
    vals = detect.find_values(scan, "\n".join(ln.text for ln in ocr_lines))
    locs = locate.locate(scan, vals, ocr_lines, vl.read_text)
    _save(cache, synth.analysis_to_json(vals, locs))
    return vals, locs


def debug_boxes(scan: Image.Image, locs: list[list[Located]], path: str) -> None:
    img = scan.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for places in locs:
        for loc in places:
            d.rectangle(loc.run_box, outline=BOX_COLOURS.get(loc.how, (230, 140, 0)), width=2)
    img.save(path)


def summary(i: int, key: synth.Key) -> str:
    edited = [c for c in key["changes"] if c["places"]]
    ok = sum(c["read_back_ok"] for c in edited)
    lc = key.get("leak_check")
    verdict = "" if lc is None else ("leak check passed" if lc["passed"] else f"LEAK of {lc['leaked_types']}")
    return f"copy {i}: {len(edited)} values replaced, {ok} read back correctly, {verdict}"


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
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
    scan = Image.open(a.scan).convert("RGB")
    stem = os.path.splitext(os.path.basename(a.scan))[0]
    ocr_lines = ocr.lines(scan)
    vals, locs = analyse(scan, ocr_lines, os.path.join(a.private, f"{stem}.analysis.json"))
    debug_boxes(scan, locs, os.path.join(a.out, f"{stem}.boxes.png"))
    scan.save(os.path.join(a.out, f"{stem}.original.png"))
    places = [p for ps in locs for p in ps]
    by_ocr = sum(1 for p in places if p.how != "pixels")
    print(
        f"{len(vals)} personal values, {sum(1 for ps in locs if ps)} located in {len(places)} places "
        f"({by_ocr} by OCR, {len(places) - by_ocr} by pixels)",
        flush=True,
    )
    context = synth.page_context(" ".join(ln.text for ln in ocr_lines), vals, locs)
    for i in range(a.n):
        copy = synth.make_copy(
            scan,
            vals,
            locs,
            a.seed + i,
            context,
            read=None if a.no_verify else vl.read_text,
            read_page=None if a.no_leak_check else vl.read_page,
        )
        base = f"{stem}.copy-{i + 1}"
        copy.image.save(os.path.join(a.out, base + ".png"))
        _save(os.path.join(a.out, base + ".json"), copy.key)
        _save(os.path.join(a.private, base + ".private.json"), copy.private_key)
        print(summary(i + 1, copy.key), flush=True)


if __name__ == "__main__":
    main()
