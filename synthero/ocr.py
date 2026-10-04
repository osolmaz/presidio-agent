"""Exact text positions from Tesseract: words with boxes, grouped into lines.

Only the positions are trusted; the text is used to find values, never as a value.
Tesseract joins words on one row even when they belong to different columns (a
city at the left margin, a card number at the right). A line is split where the
gap between two words is much wider than the text height.
"""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass

from PIL import Image

from synthero.geometry import Box

JUNK = "|[]\\{}"  # what Tesseract makes of cell borders and specks


@dataclass(frozen=True)
class Word:
    text: str
    box: Box
    row: tuple[str, str, str] = ("", "", "")  # Tesseract's (block, paragraph, line)


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def box(self) -> Box:
        boxes = [w.box for w in self.words]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def parse_tsv(tsv: str) -> list[Word]:
    """Words from Tesseract's TSV output, split at "|" and stripped of specks."""
    out: list[Word] = []
    for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (r.get("text") or "").strip()
        if not text:
            continue
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        row = (r["block_num"], r["par_num"], r["line_num"])
        # Split a word at "|", sharing its box by character count.
        pos = 0
        for part in text.split("|"):
            px1 = x + int(w * pos / len(text))
            px2 = x + int(w * (pos + len(part)) / len(text))
            pos += len(part) + 1
            clean = part.strip(JUNK)
            if clean:
                out.append(Word(clean, (px1, y, px2, y + h), row))
    return out


def words(img: Image.Image, langs: str = "deu+eng") -> list[Word]:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    tsv = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", langs, "--psm", "3", "tsv"],
        input=buf.getvalue(),
        capture_output=True,
        check=True,
    ).stdout.decode()
    return parse_tsv(tsv)


def group_lines(ws: list[Word], gap_factor: float = 3.0) -> list[Line]:
    """Words grouped by Tesseract row, split at wide gaps, top to bottom."""
    rows: dict[tuple[str, str, str], list[Word]] = {}
    for w in ws:
        rows.setdefault(w.row, []).append(w)
    result: list[Line] = []
    for row in rows.values():
        row.sort(key=lambda w: w.box[0])
        h = max(1, sorted(w.box[3] - w.box[1] for w in row)[len(row) // 2])
        group = [row[0]]
        for w in row[1:]:
            if w.box[0] - group[-1].box[2] > gap_factor * h:
                result.append(Line(tuple(group)))
                group = []
            group.append(w)
        result.append(Line(tuple(group)))
    result.sort(key=lambda ln: (ln.box[1], ln.box[0]))
    return result


def lines(img: Image.Image, gap_factor: float = 3.0) -> list[Line]:
    return group_lines(words(img), gap_factor)
