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
LineOcr = Callable[[Image.Image], list[Line]]  # OCR of one line crop: words with boxes in the crop


def _no_line_ocr(crop: Image.Image) -> list[Line]:
    return []


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
    line_ocr: LineOcr = _no_line_ocr

    @property
    def rule_px(self) -> int:
        """Vertical ink longer than three lines is a frame or barcode, never a letter."""
        return 3 * self.line_h


def _crop(page: Page, box: Box) -> Image.Image:
    """The box with a margin of blank paper around it: letters at a tight edge get misread."""
    pad = max(2, page.line_h // 2)
    x0, y0, x1, y1 = box
    margin = (max(0, x0 - pad), max(0, y0 - 2), min(page.scan.width, x1 + pad), min(page.scan.height, y1 + 2))
    out = Image.new("RGB", (margin[2] - margin[0] + 2 * pad, margin[3] - margin[1] + 2 * pad), "white")
    out.paste(page.scan.crop(margin).convert("RGB"), (pad, pad))
    return out


def _band(page: Page, run: Box, text: str) -> Box | None:
    """The run itself, or for a box taller than a line, the one part whose reading holds `text`."""
    parts = geometry.split_tall_box(page.gray, run, page.line_h)
    if len(parts) > 1:
        parts = [p for p in parts if match.contains(page.read(_crop(page, p)), text)]
    return parts[0] if len(parts) == 1 else None


def _snap(page: Page, run: Box, line: Box) -> Box:
    """Grow an OCR run to the whole ink words that lie mostly inside it, so a number OCR read
    only in part is still erased completely, but a label beside it keeps its pixels."""
    touched = [
        w
        for w in geometry.word_boxes(page.gray, line, page.rule_px)
        if min(w[2], run[2]) - max(w[0], run[0]) >= 0.5 * (w[2] - w[0])
    ]
    return _union([run, *touched]) if touched else run


def _printed(reading: str, value: Value) -> str | None:
    """The span of a full-resolution reading that holds the value."""
    words = reading.split()
    m = match.find_value(value.text, [words], min_score=0.75, strict=False)
    return " ".join(words[m.first_word : m.last_word + 1]) if m else None


def _ocr_place(page: Page, value: Value, m: match.Match, exact: bool) -> Located | None:
    words = page.lines[m.line].words
    run = _union([w.box for w in words[m.first_word : m.last_word + 1]])
    band = _band(page, run, value.text)
    if band is None:
        return None  # cannot tell which part holds the value: do not guess
    line = _clip_rows(page.lines[m.line].box, band)
    run = _snap(page, _clip_rows(run, band), line)
    if not geometry.has_ink(page.gray, run):
        return None
    nxt = next((w.box[0] for w in words[m.last_word + 1 :] if w.box[0] >= run[2]), None)
    # A full-resolution reading of the run says what is printed there.
    printed = _printed(page.read(_crop(page, run)), value)
    if exact:
        return Located(value, line, run, nxt, "ocr", printed or value.text)
    # OCR and the model disagree on a digit: the reading says what is printed, and must be
    # close to the value. Boxes that another value matched exactly are not taken (`locate`),
    # and the leak check searches every reading.
    return None if printed is None else Located(value, line, run, nxt, "ocr+read", printed)


def via_pixels(page: Page, value: Value, search_lines: int = 6) -> Located | None:
    _, hy1, _, hy2 = value.hint
    span = search_lines * page.line_h
    region = (0, max(0, hy1 - span), page.gray.width, min(page.gray.height, hy2 + span))
    # Dashes, dots, and specks are not text lines.
    lines = [
        b
        for b in geometry.ink_lines(page.gray, region, rule_px=page.rule_px)
        if b[3] - b[1] >= page.line_h / 2 and b[2] - b[0] >= page.line_h
    ]
    for line in sorted(lines, key=lambda b: geometry.centre_distance(b, value.hint))[: 2 * search_lines]:
        for part in geometry.split_tall_box(page.gray, line, page.line_h):
            reading = page.read(_crop(page, part))
            if match.contains(reading, value.text):
                located = _value_in_line(page, value, part, reading)
                if located is not None:
                    return located
    return None


def _word_box_options(page: Page, line: Box) -> list[list[Box]]:
    """Two independent splits of a line into words: from pixels, and from the OCR words inside it."""
    ocr_words = [
        w.box
        for ln in page.lines
        for w in ln.words
        if w.box[0] >= line[0] - 2
        and w.box[2] <= line[2] + 2
        and line[1] - 2 <= (w.box[1] + w.box[3]) / 2 <= line[3] + 2
    ]
    return [geometry.word_boxes(page.gray, line, page.rule_px), sorted(ocr_words)]


def _value_in_line(page: Page, value: Value, line: Box, reading: str) -> Located | None:
    """The value's own words inside a line found from pixels, so labels keep their pixels.

    The reading's words are mapped to the line's words, split from pixels or by OCR. When
    neither split has as many words as the reading, the line alone is OCR'd at three times
    its size; when that does not place the value either, it is not edited (the leak check
    gates it).
    """
    words = reading.split()
    m = match.find_value(value.text, [words], strict=False)
    boxes = next((b for b in _word_box_options(page, line) if len(b) == len(words)), None)
    if m is not None and boxes is not None:
        run = _union(boxes[m.first_word : m.last_word + 1])
        nxt = boxes[m.last_word + 1][0] if m.last_word + 1 < len(boxes) else None
        return Located(value, line, run, nxt, "pixels", " ".join(words[m.first_word : m.last_word + 1]))
    same_words = len(value.text.split()) == len(words)
    if same_words and match.similarity(reading, value.text) >= 0.85 and match.close_digits(value.text, reading):
        return Located(value, line, line, None, "pixels", reading.strip())
    if m is not None:
        return _value_by_line_ocr(page, value, line, " ".join(words[m.first_word : m.last_word + 1]))
    return None


LINE_OCR_SCALE = 3


def _value_by_line_ocr(page: Page, value: Value, line: Box, printed: str) -> Located | None:
    """OCR of the line alone, enlarged: its word boxes place a value the reading confirmed."""
    x0, y0, _, y1 = line
    crop = page.scan.crop(line)
    big = crop.resize((crop.width * LINE_OCR_SCALE, crop.height * LINE_OCR_SCALE), Image.Resampling.LANCZOS)
    words = [w for ln in page.line_ocr(big) for w in ln.words]
    m = match.find_value(printed, [[w.text for w in words]], min_score=0.75, strict=False)
    if m is None:
        return None
    s = LINE_OCR_SCALE

    def back(b: Box) -> Box:
        return (x0 + b[0] // s, y0, x0 + -(-b[2] // s), y1)

    run = _union([back(w.box) for w in words[m.first_word : m.last_word + 1]])
    nxt = back(words[m.last_word + 1].box)[0] if m.last_word + 1 < len(words) else None
    return Located(value, line, run, nxt, "pixels", printed)


def overlaps(a: Box, b: Box, min_share: float = 0.3) -> bool:
    """True when the boxes share at least `min_share` of the smaller one's area."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return False
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h >= min_share * max(1, smaller)


def locate(
    scan: Image.Image,
    values: list[Value],
    ocr_lines: list[Line],
    read: Reader,
    line_ocr: LineOcr = _no_line_ocr,
) -> list[list[Located]]:
    """For each value, every place it is printed; an empty list when it cannot be found.

    Exact OCR matches claim their boxes first; weaker evidence (a corrected digit, a
    pixel line) cannot take a box another value already holds.
    """
    gray = scan.convert("L")
    line_h = geometry.typical_line_height([w.box for ln in ocr_lines for w in ln.words])
    page = Page(gray, scan, ocr_lines, line_h, read, line_ocr)
    texts = [[w.text for w in ln.words] for ln in ocr_lines]
    result: list[list[Located]] = []
    for v in values:
        found = [_ocr_place(page, v, m, exact=True) for m in match.find_all(v.text, texts)]
        result.append([p for p in found if p is not None])
    claimed = [p.run_box for places in result for p in places]
    for i, v in enumerate(values):
        # A value can be printed twice with OCR misreading one copy, so near matches are
        # tried for every value, on boxes nobody holds yet.
        near = [m for m in match.find_all(v.text, texts, strict=False) if not _claimed(page, m, claimed)]
        places = [p for p in (_ocr_place(page, v, m, exact=False) for m in near) if p is not None]
        if not result[i] and not places:
            one = via_pixels(page, v)
            places = [one] if one is not None and not any(overlaps(one.run_box, c) for c in claimed) else []
        claimed += [p.run_box for p in places]
        result[i] += places
    return result


def _claimed(page: Page, m: match.Match, claimed: list[Box]) -> bool:
    words = page.lines[m.line].words[m.first_word : m.last_word + 1]
    return any(overlaps(w.box, c) for w in words for c in claimed)
