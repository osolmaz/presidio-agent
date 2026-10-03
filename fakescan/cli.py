"""Make synthetic copies of a scanned document with new personal data.

    python3 -m fakescan SCAN.png [--n 3] [--out /dev/shm/fake-scan/out] [--seed 1]

For each copy it writes copy-N.png and copy-N.json (the answer key: every
changed field, its old and new text, its box, and whether a read-back matched).
The text location and labels are computed once per scan and cached next to the
outputs. Everything is written under --out, which defaults to RAM (/dev/shm).
"""
import argparse
import json
import os
import random
import re

from PIL import Image, ImageDraw

from . import fields, render, values, vl


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def analyse(scan: Image.Image, cache: str):
    if os.path.exists(cache):
        return json.load(open(cache))
    lines = vl.locate_lines(scan)
    labels = fields.label_lines(lines)
    for ln, lab in zip(lines, labels):
        # Consistency: every date on the page moves by the same shift, also the ones the model missed.
        if lab == "none" and re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", ln["text"]):
            lab = "date"
        ln["field"] = lab
    json.dump(lines, open(cache, "w"), indent=1, ensure_ascii=False)
    return lines


def debug_boxes(scan: Image.Image, lines, path: str):
    img = scan.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for ln in lines:
        d.rectangle(ln["box"], outline=(220, 30, 30) if ln["field"] != "none" else (60, 140, 220), width=2)
    img.save(path)


def make_copy(scan, lines, seed, verify=True):
    rng = random.Random(seed)
    person = values.Person(rng)
    out = scan.convert("RGB").copy()
    changes = []
    for ln in lines:
        if ln["field"] == "none":
            continue
        new_text = values.replace(ln["field"], ln["text"], person, rng)
        if new_text == ln["text"]:
            continue
        out, padded = render.replace_line(out, ln["box"], new_text, ln["text"])
        change = {"field": ln["field"], "old": ln["text"], "new": new_text, "box": list(ln["box"])}
        if verify:
            got = vl.read_text(out.crop(padded))
            change["read_back"] = got
            change["read_back_ok"] = norm(got) == norm(new_text)
        changes.append(change)
    return out, {"seed": seed, "person": vars(person), "changes": changes}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="/dev/shm/fake-scan/out")
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    scan = Image.open(a.scan).convert("RGB")
    stem = os.path.splitext(os.path.basename(a.scan))[0]
    lines = analyse(scan, os.path.join(a.out, f"{stem}.lines.json"))
    debug_boxes(scan, lines, os.path.join(a.out, f"{stem}.boxes.png"))
    scan.save(os.path.join(a.out, f"{stem}.original.png"))
    print(f"{len(lines)} lines, {sum(ln['field'] != 'none' for ln in lines)} to change", flush=True)

    for i in range(a.n):
        img, key = make_copy(scan, lines, a.seed + i, verify=not a.no_verify)
        img.save(os.path.join(a.out, f"{stem}.copy-{i + 1}.png"))
        json.dump(key, open(os.path.join(a.out, f"{stem}.copy-{i + 1}.json"), "w"), indent=1, ensure_ascii=False)
        ok = sum(c.get("read_back_ok", False) for c in key["changes"])
        print(f"copy {i + 1}: {len(key['changes'])} fields changed, {ok} read back correctly", flush=True)


if __name__ == "__main__":
    main()
