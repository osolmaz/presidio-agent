"""Make synthetic copies of a scanned document with new personal data.

    python3 -m fakescan SCAN.png [--n 3] [--out /dev/shm/fake-scan/out] [--seed 1]

The model finds every text line and the exact PII spans in it (type and owner).
Code invents consistent new values per owner and type, replaces only the span
text, and redraws only the words that contain a span. Each copy is read back,
and the finished page is checked for any surviving original value.

Outputs (in --out): copy-N.png and copy-N.json, the public answer key with new
values only. The original text, the spans, and the old-to-new mappings go to
--private, which must never be served or shared.
"""
import argparse
import json
import os
import random
import re

from PIL import Image, ImageDraw

from . import fields, leak, ocr, render, values, vl


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def has_ink(scan: Image.Image, box, min_dark=8) -> bool:
    """Pixel cross-check of an OCR box: it must contain ink."""
    gray = scan.convert("L").crop(tuple(box))
    data = list(gray.getdata())
    if not data:
        return False
    paper = sorted(data)[int(len(data) * 0.9)]
    return sum(1 for v in data if v < paper - 70) >= min_dark


def analyse(scan: Image.Image, cache: str):
    """OCR lines with exact word boxes, and the PII spans Bonsai marks in them. Cached per scan.

    A span is located when every word it covers has an OCR box with ink in it; other
    spans are not edited, but the leak check still searches for them.
    """
    if os.path.exists(cache):
        data = json.load(open(cache))
        return data["lines"], data["spans"]
    lines = ocr.lines(scan)
    spans = fields.find_spans(lines, image=scan)
    for s in spans:
        covered = [w for w in lines[s["line"]]["words"] if w["start"] < s["end"] and s["start"] < w["end"]]
        line_h = sorted(w["box"][3] - w["box"][1] for w in lines[s["line"]]["words"])[len(lines[s["line"]]["words"]) // 2]
        s["located"] = (bool(covered) and all(has_ink(scan, w["box"]) for w in covered)
                        and all(w["box"][3] - w["box"][1] <= 1.6 * line_h for w in covered))
    json.dump({"lines": lines, "spans": spans}, open(cache, "w"), indent=1, ensure_ascii=False)
    return lines, spans


def debug_boxes(scan: Image.Image, lines, spans, path: str):
    img = scan.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    pii_lines = {s["line"] for s in spans}
    for i, ln in enumerate(lines):
        d.rectangle(ln["box"], outline=(220, 30, 30) if i in pii_lines else (60, 140, 220), width=2)
    img.save(path)


def word_runs(line: str, line_spans):
    """Group the words that overlap a span into runs of consecutive words: [(a, b, start, end)]."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]
    hit = [any(s["start"] < we and ws < s["end"] for s in line_spans) for ws, we in words]
    runs, a = [], None
    for i, h in enumerate(hit + [False]):
        if h and a is None:
            a = i
        elif not h and a is not None:
            runs.append((a, i - 1, words[a][0], words[i - 1][1]))
            a = None
    return runs


def apply(text: str, offset: int, repl):
    """Replace spans [(start, end, new)] (line offsets) inside text that starts at `offset`."""
    for start, end, new in sorted(repl, reverse=True):
        if offset <= start and end <= offset + len(text):
            text = text[: start - offset] + new + text[end - offset:]
    return text


def make_copy(scan, lines, spans, seed, verify=True, leak_check=True):
    """Return the copy, its public answer key (no old values), and the private old-to-new mapping."""
    rng = random.Random(seed)
    repl = values.Replacer(rng)
    out = scan.convert("RGB").copy()
    public, private = [], []
    by_line = {}
    for s in spans:
        if s.get("located", True):
            by_line.setdefault(s["line"], []).append(s)
    for i, line_spans in sorted(by_line.items()):
        ln = lines[i]
        old_line = ln["text"]
        r = [(s["start"], s["end"], repl.replace(s["text"], s["type"], s["owner"])) for s in line_spans]
        new_line = apply(old_line, 0, r)
        if new_line == old_line:
            continue
        area = None
        words = ln["words"]
        for a, b, start, end in reversed(word_runs(old_line, line_spans)):
            new_run = apply(old_line[start:end], start, r)
            run_box = [min(w["box"][0] for w in words[a:b + 1]), min(w["box"][1] for w in words[a:b + 1]),
                       max(w["box"][2] for w in words[a:b + 1]), max(w["box"][3] for w in words[a:b + 1])]
            next_x = words[b + 1]["box"][0] if b + 1 < len(words) else None
            out, area = render.replace_words(out, ln["box"], old_line, new_line, a, b, new_run, source=scan,
                                             run_box=run_box, next_x=next_x, old_run=old_line[start:end])
        change = {"line": i, "box": list(ln["box"]), "new": new_line,
                  "spans": [{"type": s["type"], "owner": s["owner"], "new": n} for s, (_, _, n) in zip(line_spans, r)]}
        if verify and area is not None:
            change["read_back_ok"] = norm(vl.read_text(out.crop(area))) == norm(new_line)
        public.append(change)
        private.append({"line": i, "old": old_line, "new": new_line,
                        "spans": [{"type": s["type"], "owner": s["owner"], "old": s["text"], "new": n}
                                  for s, (_, _, n) in zip(line_spans, r)]})
    key = {"seed": seed, "changes": public}
    private_key = {"seed": seed, "changes": private}
    if leak_check:
        # Search for every PII value the model found, also the ones that could not be edited.
        old_values = [(s["type"], s["text"]) for s in spans]
        # Text on the page that is not PII (labels, the vendor's address) does not count as a leak.
        all_by_line = {}
        for s in spans:
            all_by_line.setdefault(s["line"], []).append(s)
        context = " ".join(apply(ln["text"], 0, [(s["start"], s["end"], " ") for s in all_by_line.get(i, [])])
                           for i, ln in enumerate(lines))
        new_values = [sp["new"] for c in private for sp in c["spans"]]
        _, leaks = leak.check(out, old_values, context, new_values)
        key["leak_check"] = {"passed": not leaks, "leaked_types": sorted({x["type"] for x in leaks})}
        private_key["leaks"] = leaks
    return out, key, private_key


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="/dev/shm/fake-scan/out")
    ap.add_argument("--private", default="/dev/shm/fake-scan/private",
                    help="folder for the original text, spans, and old-to-new mappings; never serve or share it")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--no-leak-check", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.private, exist_ok=True)
    scan = Image.open(a.scan).convert("RGB")
    stem = os.path.splitext(os.path.basename(a.scan))[0]
    lines, spans = analyse(scan, os.path.join(a.private, f"{stem}.analysis.json"))
    debug_boxes(scan, lines, spans, os.path.join(a.out, f"{stem}.boxes.png"))
    scan.save(os.path.join(a.out, f"{stem}.original.png"))
    located = [s for s in spans if s.get("located", True)]
    print(f"{len(lines)} lines, {len(spans)} PII spans, {len(located)} located and editable", flush=True)

    for i in range(a.n):
        img, key, private_key = make_copy(scan, lines, spans, a.seed + i, verify=not a.no_verify,
                                          leak_check=not a.no_leak_check)
        base = f"{stem}.copy-{i + 1}"
        img.save(os.path.join(a.out, base + ".png"))
        json.dump(key, open(os.path.join(a.out, base + ".json"), "w"), indent=1, ensure_ascii=False)
        json.dump(private_key, open(os.path.join(a.private, base + ".private.json"), "w"), indent=1, ensure_ascii=False)
        ok = sum(c.get("read_back_ok", False) for c in key["changes"])
        lc = key.get("leak_check")
        verdict = "" if lc is None else ("leak check passed" if lc["passed"] else f"LEAK of {lc['leaked_types']}")
        print(f"copy {i + 1}: {len(key['changes'])} lines changed, {ok} read back correctly, {verdict}", flush=True)


if __name__ == "__main__":
    main()
