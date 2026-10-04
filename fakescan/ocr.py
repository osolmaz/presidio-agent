"""Exact text positions from Tesseract: words with boxes, grouped into lines.

Tesseract joins words on one row even when they belong to different columns
(a city at the left margin, a card number at the right). A line is split where
the gap between two words is much wider than the text height.
"""
import csv
import io
import subprocess

from PIL import Image

JUNK = "|[]\\{}"  # what Tesseract makes of cell borders and specks


def words(img: Image.Image, langs="deu+eng"):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    tsv = subprocess.run(["tesseract", "stdin", "stdout", "-l", langs, "--psm", "3", "tsv"],
                         input=buf.getvalue(), capture_output=True, check=True).stdout.decode()
    out = []
    for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (r.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        row = (r["block_num"], r["par_num"], r["line_num"])
        # Tesseract reads cell borders and specks as "|", "]", "\". Split a word at "|",
        # sharing its box by character count, and strip the specks from the text.
        parts = text.split("|")
        pos = 0
        for part in parts:
            px1 = x + int(w * pos / max(1, len(text)))
            px2 = x + int(w * (pos + len(part)) / max(1, len(text)))
            pos += len(part) + 1
            clean = part.strip(JUNK)
            if clean:
                out.append({"text": clean, "box": (px1, y, px2, y + h), "conf": float(r["conf"]), "row": row})
    return out


def lines(img: Image.Image, gap_factor=3.0):
    """[{"text", "box", "words": [{"text", "box", "start", "end"}]}], top to bottom."""
    rows = {}
    for w in words(img):
        rows.setdefault(w["row"], []).append(w)
    result = []
    for ws in rows.values():
        ws.sort(key=lambda w: w["box"][0])
        h = max(1, sorted(w["box"][3] - w["box"][1] for w in ws)[len(ws) // 2])
        group = [ws[0]]
        for w in ws[1:]:
            if w["box"][0] - group[-1]["box"][2] > gap_factor * h:
                result.append(_line(group))
                group = []
            group.append(w)
        result.append(_line(group))
    result.sort(key=lambda ln: (ln["box"][1], ln["box"][0]))
    return result


def _line(ws):
    text, items, pos = [], [], 0
    for w in ws:
        if text:
            pos += 1
        items.append({"text": w["text"], "box": list(w["box"]), "start": pos, "end": pos + len(w["text"])})
        text.append(w["text"])
        pos += len(w["text"])
    box = [min(w["box"][0] for w in ws), min(w["box"][1] for w in ws),
           max(w["box"][2] for w in ws), max(w["box"][3] for w in ws)]
    return {"text": " ".join(text), "box": box, "words": items}
