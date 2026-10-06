"""Page geometry from pixels alone: text lines, line height, and splitting tall boxes.

These functions take a grayscale image and plain boxes, need no model and no
OCR, and are the fallback when OCR positions cannot be trusted.
"""

from __future__ import annotations

from statistics import median
from typing import Protocol, cast

from PIL import Image

Box = tuple[int, int, int, int]


class Pixels(Protocol):
    """Pixel access of a one-band ("L") image, typed: Pillow's own type covers every mode."""

    def __getitem__(self, xy: tuple[int, int]) -> int: ...

    def __setitem__(self, xy: tuple[int, int], value: int) -> None: ...


def pixels(img: Image.Image) -> Pixels:
    if img.mode != "L":
        raise ValueError(f"expected a grayscale image, got mode {img.mode}")
    px = img.load()
    if px is None:
        raise ValueError("image has no pixel data")
    return cast(Pixels, px)


def gray_values(img: Image.Image) -> list[int]:
    """All pixel values of the image in grayscale, row by row."""
    return list(img.convert("L").tobytes())


def paper_level(gray: Image.Image) -> int:
    """The paper's gray level: the 90th percentile, so ink and stains do not move it."""
    data = sorted(gray_values(gray))
    return data[min(len(data) - 1, int(len(data) * 0.9))] if data else 255


def paper_colour(img: Image.Image) -> tuple[int, int, int]:
    """The paper's colour: the per-channel median of the pixels near the paper's gray level.

    Scans and printed paper are rarely neutral gray; a gray patch on cream paper shows.
    """
    rgb = img.convert("RGB")
    level = paper_level(rgb.convert("L"))
    gray = gray_values(rgb)
    raw = rgb.tobytes()
    near = [i for i, v in enumerate(gray) if v >= level - 10]
    if not near:
        return (level, level, level)
    r, g, b = (sorted(raw[3 * i + c] for i in near)[len(near) // 2] for c in range(3))
    return (r, g, b)


def ink_threshold(gray: Image.Image) -> int:
    """Pixels darker than this are ink: 70 levels below the paper."""
    return paper_level(gray) - 70


def typical_line_height(boxes: list[Box]) -> int:
    """Median height of the given boxes, at least 4 px."""
    heights = [b[3] - b[1] for b in boxes if b[3] > b[1]]
    return max(4, int(median(heights))) if heights else 12


def bands(flags: list[bool], min_gap: int = 1) -> list[tuple[int, int]]:
    """Runs of True values, merged across gaps shorter than `min_gap`: [(start, end)]."""
    out: list[tuple[int, int]] = []
    start = None
    gap = 0
    for i, f in enumerate(flags):
        if f:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                out.append((start, i - gap + 1))
                start, gap = None, 0
    if start is not None:
        out.append((start, len(flags) - gap))
    return out


def _vertical_runs_removed(column: list[bool], rule_px: int) -> list[bool]:
    """A column of ink flags with every unbroken vertical run of `rule_px` or more cleared."""
    out = list(column)
    start = None
    for i, v in enumerate([*column, False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= rule_px:
                out[start:i] = [False] * (i - start)
            start = None
    return out


def text_mask(gray: Image.Image, region: Box, rule_px: int = 36) -> list[list[bool]]:
    """Ink flags of `region` as mask[y][x], without frames, cell lines, and barcode bars.

    A vertical run of ink longer than `rule_px` (three lines by default) is never a letter,
    and a row whose ink runs unbroken over half the width is a horizontal rule.
    """
    x0, y0, x1, y1 = region
    cut = ink_threshold(gray)
    px = pixels(gray)
    cols = [_vertical_runs_removed([px[x, y] < cut for y in range(y0, y1)], rule_px) for x in range(x0, x1)]
    mask = [[cols[x][y] for x in range(x1 - x0)] for y in range(y1 - y0)]
    for row in mask:
        if longest_true_run(row) > 0.5 * len(row):
            row[:] = [False] * len(row)
    return mask


def longest_true_run(flags: list[bool]) -> int:
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def ink_lines(gray: Image.Image, region: Box | None = None, gap_factor: float = 3.0, rule_px: int = 36) -> list[Box]:
    """Text lines in `region` (the whole page by default), found from rows of ink.

    Rows with ink form bands; a band is split sideways where a blank gap is wider
    than `gap_factor` times the band height (separate columns on one row). Rules,
    frames, and barcode bars are ignored (`text_mask`), so they do not merge lines.
    """
    x0, y0, x1, y1 = region or (0, 0, gray.width, gray.height)
    mask = text_mask(gray, (x0, y0, x1, y1), rule_px)
    lines: list[Box] = []
    for top, bottom in bands([any(row) for row in mask], min_gap=2):
        height = max(1, bottom - top)
        cols = [any(mask[y][x] for y in range(top, bottom)) for x in range(x1 - x0)]
        for left, right in bands(cols, min_gap=max(3, int(gap_factor * height))):
            lines.append((x0 + left, y0 + top, x0 + right, y0 + bottom))
    return lines


def split_tall_box(gray: Image.Image, box: Box, line_height: int, factor: float = 1.6) -> list[Box]:
    """Split a box that is taller than `factor` lines at the blank rows inside it.

    Returns the box itself when it is not too tall or has no blank rows to split at.
    """
    x0, y0, x1, y1 = box
    if y1 - y0 <= factor * line_height:
        return [box]
    parts = [(x0, y0 + t, x1, y0 + b) for t, b in bands(_row_ink(gray, box), min_gap=1)]
    return parts or [box]


def _row_ink(gray: Image.Image, box: Box) -> list[bool]:
    x0, y0, x1, y1 = box
    cut = ink_threshold(gray)
    px = pixels(gray)
    return [any(px[x, y] < cut for x in range(x0, x1)) for y in range(y0, y1)]


def has_ink(gray: Image.Image, box: Box, min_dark: int = 8) -> bool:
    """True when the box holds at least `min_dark` ink pixels."""
    crop = gray.crop(box)
    cut = ink_threshold(crop)
    return sum(1 for v in gray_values(crop) if v < cut) >= min_dark


def word_boxes(gray: Image.Image, line: Box, rule_px: int = 36) -> list[Box]:
    """Split one text line into word boxes at blank gaps wider than about a third of its height.

    Frames and cell lines that cross the line are not words.
    """
    x0, y0, x1, y1 = line
    pad = rule_px  # look above and below, so a frame crossing the line is seen as long
    outer = (x0, max(0, y0 - pad), x1, min(gray.height, y1 + pad))
    mask = text_mask(gray, outer, rule_px)
    rows = range(y0 - outer[1], y1 - outer[1])
    cols = [any(mask[y][x] for y in rows) for x in range(x1 - x0)]
    gap = max(3, int((y1 - y0) * 0.35))
    return [(x0 + a, y0, x0 + b, y1) for a, b in bands(cols, min_gap=gap)]


def centre_distance(a: Box, b: Box) -> float:
    """Distance between the centres of two boxes."""
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)
