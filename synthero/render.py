"""Redraw one located value in a scan; every other word keeps its pixels.

The old value's ink is erased (every connected piece of it, but never above or
below its own line) and the new value is drawn in the Liberation font whose
rendering of the old value best matches the original's width and ink density,
at the original letter height. Measurements always come from the original scan,
so repeated edits on one page cannot degrade it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from synthero import fonts
from synthero.geometry import Box, paper_level, pixels

RGB = tuple[int, int, int]


def _ink_colour(img: Image.Image, cut: int) -> RGB:
    """Mean colour of the darkest third of the ink pixels: the printed colour, not its anti-aliased rim."""
    raw = img.convert("RGB").tobytes()
    ink = sorted((px for px in zip(raw[0::3], raw[1::3], raw[2::3], strict=True) if sum(px) / 3 < cut), key=sum)
    darkest = ink[: max(1, len(ink) // 3)]
    if not darkest:
        return (15, 15, 15)
    r, g, b = (int(sum(c) / len(darkest)) for c in zip(*darkest, strict=True))
    return (r, g, b)


def _free_right(gray: Image.Image, box: Box, cut: int, gap: int = 1, limit: int = 400) -> int:
    """x of the next ink to the right of the box (another word, or a cell line), or the page edge."""
    _, y1, x2, y2 = box
    px = pixels(gray)
    blank = 0
    for x in range(x2, min(gray.width, x2 + limit)):
        if any(px[x, y] < cut for y in range(y1, y2)):
            if blank >= gap:
                return x
            blank = 0
        else:
            blank += 1
    return min(gray.width, x2 + limit)


def _free_vertical(gray: Image.Image, box: Box, cut: int, step: int, limit: int = 12) -> int:
    """Blank rows above (step -1) or below (step +1) the box, before the neighbouring line's ink."""
    x1, y1, x2, y2 = box
    px = pixels(gray)
    y = y1 - 1 if step < 0 else y2
    n = 0
    while 0 <= y < gray.height and n < limit:
        if any(px[x, y] < cut for x in range(x1, x2)):
            return max(0, n - 1)
        n += 1
        y += step
    return n


def _value_rows(gray: Image.Image, x1: int, x2: int, y1: int, y2: int, cut: int) -> tuple[int, int]:
    """The run's own ink rows inside the line, ignoring vertical cell lines.

    A value can be printed smaller than its label ("Nr.:" bold, the number regular).
    """
    px = pixels(gray)
    band = max(1, y2 - y1)
    cols = [x for x in range(x1, x2) if sum(1 for y in range(y1, y2) if px[x, y] < cut) < 0.7 * band]
    rows = [y for y in range(y1, y2) if any(px[x, y] < cut for x in cols)]
    return (rows[0], rows[-1] + 1) if rows else (y1, y2)


@dataclass(frozen=True)
class Measure:
    """The original value's ink: its box (the run's own rows), the ink cut, and the paper level."""

    value_box: Box
    cut: int
    paper: int

    @property
    def ink_h(self) -> int:
        return self.value_box[3] - self.value_box[1]


def measure(source: Image.Image, line_box: Box, run_box: Box) -> Measure:
    gray = source.convert("L")
    lx1, ly1, lx2, ly2 = line_box
    local = gray.crop((max(0, lx1 - 20), max(0, ly1 - 10), min(gray.width, lx2 + 20), min(gray.height, ly2 + 10)))
    paper = paper_level(local)
    ty1, ty2 = _value_rows(gray, run_box[0], run_box[2], ly1, ly2, paper - 70)
    return Measure((run_box[0], ty1, run_box[2], ty2), paper - 70, paper)


def replace_words(
    dest: Image.Image,
    source: Image.Image,
    line_box: Box,
    run_box: Box,
    old: str,
    new: str,
    next_x: int | None = None,
    style: fonts.Style | None = None,
    pad: int = 6,
) -> tuple[Image.Image, Box]:
    """Redraw the words in `run_box` (inside the line `line_box`) as `new`.

    `dest` is the page so far, `source` the original scan, which all measurements use.
    `next_x` is where the next kept word on the line starts, and `style` the page's font
    family and weight (`fonts.page_style`). Returns the new page and the area to read back.
    """
    gray = source.convert("L")
    lx1, ly1, lx2, ly2 = line_box
    m = measure(source, line_box, run_box)
    vx1, ty1, vx2, ty2 = value_box = m.value_box
    cut, ink_h = m.cut, m.ink_h
    paper: RGB = (m.paper, m.paper, m.paper)
    original = source.crop(value_box)
    ink = _ink_colour(original, cut)
    font, width_scale = fonts.best(original, old, ink_h, style)

    # Free space to the right (next word or cell line) and above/below (neighbouring lines).
    right = next_x - 4 if next_x is not None else _free_right(gray, value_box, cut)
    pad_top = min(pad, _free_vertical(gray, line_box, cut, -1))
    pad_bottom = min(pad, _free_vertical(gray, line_box, cut, +1))
    gx1, _, gx2, _ = font.getbbox(new)
    text_w = int(gx2 - gx1)
    max_w = max(vx2 - vx1, right - vx1 - 3)
    squeeze = min(width_scale, max_w / max(1, text_w))

    # Draw with the tops of the capitals on the original's top ink row.
    cap_top = int(font.getbbox("H")[1])
    canvas_h = ink_h + pad_top + pad_bottom
    canvas = Image.new("L", (text_w + 2, canvas_h + 8), 0)
    ImageDraw.Draw(canvas).text((-gx1 + 1, pad_top - cap_top), new, font=font, fill=255)
    canvas = canvas.crop((0, 0, canvas.width, canvas_h))
    if abs(squeeze - 1.0) > 0.01:
        canvas = canvas.resize((max(1, int(canvas.width * squeeze)), canvas_h), Image.Resampling.LANCZOS)

    area_x2 = min(source.width, max(vx2, vx1 + canvas.width) + pad, max(right, vx2 + 1))
    area = (max(0, vx1 - pad), max(0, ty1 - pad_top), area_x2, min(source.height, ty2 + pad_bottom))
    w, h = area[2] - area[0], area[3] - area[1]
    patch = Image.new("RGB", (w, h), paper)
    noise = Image.effect_noise((w, h), 8).convert("RGB")
    patch = Image.blend(patch, Image.composite(noise, patch, noise.convert("L").point(lambda v: 60)), 0.1)
    text_mask = Image.new("L", (w, h), 0)
    text_mask.paste(canvas, (vx1 - area[0], 0))
    patch.paste(Image.new("RGB", (w, h), ink), (0, 0), text_mask)
    patch = patch.filter(ImageFilter.GaussianBlur(0.35))
    mask = Image.new("L", (w, h), 0)
    # Solid over the old ink, soft only at the outer edge, which is blank paper.
    ImageDraw.Draw(mask).rectangle((2, 0 if pad_top < 3 else 2, w - 3, h - 1 if pad_bottom < 3 else h - 3), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    out = dest.convert("RGB").copy()
    # Erase every connected piece of the old value's ink first, also where it reaches
    # outside the box, so no sliver of an old letter survives.
    erase_old_ink(out, gray, value_box, cut, ink_h, paper)
    out.paste(patch, area[:2], mask)
    read_area = (min(area[0], lx1), min(area[1], ly1), max(area[2], lx2), max(area[3], ly2))
    return out, read_area


def _component(ink: list[list[bool]], seen: list[list[bool]], start: tuple[int, int]) -> list[tuple[int, int]]:
    """All ink pixels 4-connected to `start`; marks them in `seen`."""
    h, w = len(ink), len(ink[0])
    stack, comp = [start], []
    seen[start[1]][start[0]] = True
    while stack:
        x, y = stack.pop()
        comp.append((x, y))
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and ink[ny][nx] and not seen[ny][nx]:
                seen[ny][nx] = True
                stack.append((nx, ny))
    return comp


def erase_old_ink(out: Image.Image, gray: Image.Image, value_box: Box, cut: int, ink_h: int, paper: RGB) -> None:
    """Paint paper over all ink connected to the old value, plus its anti-aliased rim.

    Table lines touch the value too; a piece much taller or wider than the text is
    left alone.
    """
    vx1, vy1, vx2, vy2 = value_box
    # Sideways the old letters may reach past the box; up and down never past the line,
    # so a neighbouring line's ink is never touched.
    m = max(4, ink_h)
    rx1, ry1 = max(0, vx1 - m), max(0, vy1 - 2)
    rx2, ry2 = min(gray.width, vx2 + 3 * m), min(gray.height, vy2 + 2)
    w, h = rx2 - rx1, ry2 - ry1
    if w <= 0 or h <= 0:
        return
    px = pixels(gray)
    ink = [[px[rx1 + x, ry1 + y] < cut for x in range(w)] for y in range(h)]
    seen = [[False] * w for _ in range(h)]
    keep = Image.new("L", (w, h), 0)
    kp = pixels(keep)
    seeds = [(x, y) for y in range(max(0, vy1 - ry1), min(h, vy2 - ry1)) for x in range(vx1 - rx1, min(w, vx2 - rx1))]
    for sx, sy in seeds:
        if not ink[sy][sx] or seen[sy][sx]:
            continue
        comp = _component(ink, seen, (sx, sy))
        xs = [p[0] for p in comp]
        ys = [p[1] for p in comp]
        if max(ys) - min(ys) > 2.2 * ink_h or max(xs) - min(xs) > 3 * (vx2 - vx1 + ink_h):
            continue  # a table line, not a letter
        for x, y in comp:
            kp[x, y] = 255
    keep = keep.filter(ImageFilter.MaxFilter(5))
    out.paste(Image.new("RGB", (w, h), paper), (rx1, ry1), keep)
