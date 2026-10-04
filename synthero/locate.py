"""Find where each detected value is printed, and what exactly is printed there.

The model's page-level reading of a value is a first guess: it can misread a
digit, and OCR text can be garbage. Positions come from OCR word boxes and pixel
text lines; the printed text comes from two readers agreeing.

Order of evidence:
1. OCR word runs that spell the value (fuzzy letters, equal digits), every one of
   them. A box taller than a line is split at blank rows, and the part whose
   reading contains the value is used; when that is not exactly one part, none is.
2. OCR word runs that spell the value except for a digit or two. The run is read
   again at full resolution; when that reading agrees with the OCR digits, two
   readers agree on what is printed, and that text is the value here.
3. Pixel text lines near the model's hint, each read back; the line whose reading
   holds the value wins, and the reading gives the printed text.
4. Otherwise the value is not located; it is not edited, and the leak check
   still searches for it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from synthero import geometry, match
from synthero.detect import Value
from synthero.geometry import Box
from synthero.ocr import Line

Reader = Callable[[Image.Image], str]


@dataclass(frozen=True)
class Located:
    value: Value
    line_box: Box  # the whole printed line
    run_box: Box  # exactly the value's words
    next_x: int | None  # where the next kept word on the line starts
    how: str  # "ocr", "ocr+read", or "pixels"
    printed: str  # the text printed here, which can differ from the model's first reading


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _clip_rows(box: Box, rows: Box) -> Box:
    return (box[0], rows[1], box[2], rows[3])


@dataclass(frozen=True)
class Page:
    gray: Image.Image
    scan: Image.Image
    lines: list[Line]
    line_h: int
    read: Reader


def _band(page: Page, run: Box, text: str) -> Box | None:
    """The run itself, or for a box taller than a line, the one part whose reading holds `text`."""
    parts = geometry.split_tall_box(page.gray, run, page.line_h)
    if len(parts) > 1:
        parts = [p for p in parts if match.contains(page.read(page.scan.crop(p)), text)]
    return parts[0] if len(parts) == 1 else None


def _ocr_place(page: Page, value: Value, m: match.Match, exact: bool) -> Located | None:
    words = page.lines[m.line].words
    run = _union([w.box for w in words[m.first_word : m.last_word + 1]])
    band = _band(page, run, value.text)
    if band is None:
        return None  # cannot tell which part holds the value: do not guess
    run, line = _clip_rows(run, band), _clip_rows(page.lines[m.line].box, band)
    if not geometry.has_ink(page.gray, run):
        return None
    nxt = words[m.last_word + 1].box[0] if m.last_word + 1 < len(words) else None
    if exact:
        return Located(value, line, run, nxt, "ocr", value.text)
    # Digits differ between the model and OCR: a full-resolution reading decides.
    ocr_text = " ".join(w.text for w in words[m.first_word : m.last_word + 1])
    reading = page.read(page.scan.crop(run)).strip()
    if not reading or not match.same_digits(ocr_text, reading) or not match.contains(reading, value.text, 0.75):
        return None
    return Located(value, line, run, nxt, "ocr+read", reading)


def via_ocr(page: Page, value: Value) -> list[Located]:
    """Every OCR run that spells the value; near misses only when a second reading confirms them."""
    texts = [[w.text for w in ln.words] for ln in page.lines]
    exact = match.find_all(value.text, texts)
    found = [_ocr_place(page, value, m, exact=True) for m in exact]
    if not exact:
        found = [_ocr_place(page, value, m, exact=False) for m in match.find_all(value.text, texts, strict=False)]
    return [p for p in found if p is not None]


def via_pixels(page: Page, value: Value, search_lines: int = 4) -> Located | None:
    _, hy1, _, hy2 = value.hint
    span = search_lines * page.line_h
    region = (0, max(0, hy1 - span), page.gray.width, min(page.gray.height, hy2 + span))
    lines = geometry.ink_lines(page.gray, region)
    for line in sorted(lines, key=lambda b: geometry.centre_distance(b, value.hint))[: 2 * search_lines]:
        for part in geometry.split_tall_box(page.gray, line, page.line_h):
            reading = page.read(page.scan.crop(part))
            if match.contains(reading, value.text):
                located = _value_in_line(page.gray, value, part, reading)
                if located is not None:
                    return located
    return None


def _value_in_line(gray: Image.Image, value: Value, line: Box, reading: str) -> Located | None:
    """The value's own words inside a line found from pixels, so labels keep their pixels.

    The reading's words are matched to the line's ink words; when they do not line up
    and the value is not the whole line, the value is not edited (the leak check gates it).
    """
    words = reading.split()
    boxes = geometry.word_boxes(gray, line)
    m = match.find_value(value.text, [words], strict=False)
    if m is not None and len(boxes) == len(words):
        run = _union(boxes[m.first_word : m.last_word + 1])
        nxt = boxes[m.last_word + 1][0] if m.last_word + 1 < len(boxes) else None
        return Located(value, line, run, nxt, "pixels", " ".join(words[m.first_word : m.last_word + 1]))
    if match.similarity(reading, value.text) >= 0.85 and match.close_digits(value.text, reading):
        return Located(value, line, line, None, "pixels", reading.strip())
    return None


def locate(scan: Image.Image, values: list[Value], ocr_lines: list[Line], read: Reader) -> list[list[Located]]:
    """For each value, every place it is printed; an empty list when it cannot be found."""
    gray = scan.convert("L")
    line_h = geometry.typical_line_height([w.box for ln in ocr_lines for w in ln.words])
    page = Page(gray, scan, ocr_lines, line_h, read)
    result = []
    for v in values:
        places = via_ocr(page, v)
        if not places:
            one = via_pixels(page, v)
            places = [one] if one is not None else []
        result.append(places)
    return result
