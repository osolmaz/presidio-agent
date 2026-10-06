"""Draw assets/cover.svg, the README cover, with every letter as an outline.

    uv run --with fonttools --with uharfbuzz --with pillow python scripts/make_cover.py FONT_DIR

FONT_DIR holds YodelGrotesk-Bold.otf and YodelGrotesk-Regular.otf from
https://github.com/osolmaz/yodel-grotesk (assets/fonts/yodel-grotesk). Each string is
shaped with HarfBuzz, so kerning and ligatures survive, and each glyph is drawn at the
position HarfBuzz returns. The SVG has no text elements and needs no font.

The picture: an invoice fragment before and after. Values found on the original carry
the red outline of the tool's box overlay; the copy has invented values in their place,
with the labels and the layout unchanged.
"""

from __future__ import annotations

import itertools
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

WIDTH, HEIGHT = 960, 320
BACKGROUND = "#F5F0E6"
TEXT = "#111111"
SECONDARY = "#4A4A4A"
CARD = "#FFFFFF"
CARD_BORDER = "#D9D3C7"
LABEL = "#6E6A62"
FOUND = "#DC1E1E"  # the box overlay's colour for a value matched by words
ARROW = "#7A756C"

NAME = "presidio-agent"
TAGLINE = ["A local agent that replaces the personal data on", "invoices and receipts with invented values."]
ROWS = [
    ("Kunde:", "Leon Hartmann", "Mira Vogt"),
    ("Kd-Nr.:", "60120873", "48213097"),
    ("Datum:", "12.07.2026", "03.08.2026"),
]


@dataclass
class Font:
    face: TTFont
    hb_font: hb.Font
    upem: int

    @classmethod
    def load(cls, path: Path) -> Font:
        data = path.read_bytes()
        face = hb.Face(data)
        return cls(TTFont(path), hb.Font(face), face.upem)


def shaped(font: Font, text: str, size: float, tracking: float = 0.0) -> list[tuple[str, float]]:
    """Glyph names and x positions in pixels, with HarfBuzz's kerning, then tracking and collision fixes."""
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font.hb_font, buf, {"kern": True, "liga": True})
    names = font.face.getGlyphOrder()
    scale = size / font.upem
    out, x = [], 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
        out.append((names[info.codepoint], x + pos.x_offset * scale))
        x += pos.x_advance * scale + tracking
    return separate(font, out, size)


RASTER = 8  # outline samples per pixel when measuring the gap between two glyphs


def bounds(font: Font, glyph: str, size: float) -> tuple[float, float] | None:
    pen = BoundsPen(font.face.getGlyphSet())
    font.face.getGlyphSet()[glyph].draw(pen)
    if pen.bounds is None:
        return None
    scale = size / font.upem
    return pen.bounds[0] * scale, pen.bounds[2] * scale


def row_extents(font: Font, glyph: str, size: float) -> dict[int, tuple[float, float]]:
    """For each sampled row of the glyph's filled outline, its leftmost and rightmost x in pixels."""
    glyph_set = font.face.getGlyphSet()
    scale = size / font.upem * RASTER
    pen = RecordingPen()
    glyph_set[glyph].draw(TransformPen(pen, (scale, 0, 0, -scale, 0, 0)))
    contours = polygons(pen.value)
    if not contours:
        return {}
    xs = [x for c in contours for x, _ in c]
    ys = [y for c in contours for _, y in c]
    left, top = math.floor(min(xs)), math.floor(min(ys))
    img = Image.new("1", (math.ceil(max(xs)) - left + 2, math.ceil(max(ys)) - top + 2), 0)
    draw = ImageDraw.Draw(img)
    for contour in contours:
        draw.polygon([(x - left, y - top) for x, y in contour], fill=1)
    out: dict[int, tuple[float, float]] = {}
    for row in range(img.height):
        filled = [x for x in range(img.width) if img.getpixel((x, row))]
        if filled:
            out[row + top] = ((filled[0] + left) / RASTER, (filled[-1] + 1 + left) / RASTER)
    return out


def polygons(segments: list[tuple[str, tuple[tuple[float, float], ...]]]) -> list[list[tuple[float, float]]]:
    """A recorded outline as polygons, with each curve sampled at 8 points."""
    contours: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for op, pts in segments:
        if op == "moveTo":
            cur = [pts[0]]
        elif op == "lineTo":
            cur.append(pts[0])
        elif op in ("qCurveTo", "curveTo"):
            cur.extend(bezier([cur[-1], *pts], step / 8) for step in range(1, 9))
        elif op in ("closePath", "endPath"):
            contours.append(cur)
            cur = []
    return [c for c in contours if len(c) > 2]


def bezier(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    while len(points) > 1:
        points = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in itertools.pairwise(points)]
    return points[0]


def separate(font: Font, glyphs: list[tuple[str, float]], size: float) -> list[tuple[str, float]]:
    """Push a glyph and everything after it right until its outline clears its neighbour's by 1% of the size."""
    out = list(glyphs)
    for i in range(1, len(out)):
        prev, cur = row_extents(font, out[i - 1][0], size), row_extents(font, out[i][0], size)
        shared = prev.keys() & cur.keys()
        if not shared:
            continue
        gap = min((out[i][1] + cur[r][0]) - (out[i - 1][1] + prev[r][1]) for r in shared)
        if gap < 0.01 * size:
            shift = 0.01 * size - gap
            out[i:] = [(g, x + shift) for g, x in out[i:]]
    return out


def width(font: Font, glyphs: list[tuple[str, float]], size: float) -> float:
    last, x = glyphs[-1]
    end = bounds(font, last, size)
    return x + (end[1] if end else 0)


def path(font: Font, text: str, x: float, y: float, size: float, fill: str, tracking: float = 0.0) -> str:
    """One <path> for a string with its baseline at (x, y)."""
    glyph_set = font.face.getGlyphSet()
    scale = size / font.upem
    pen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    for glyph, gx in shaped(font, text, size, tracking):
        glyph_set[glyph].draw(TransformPen(pen, (scale, 0, 0, -scale, x + gx, y)))
    return f'<path fill="{fill}" d="{pen.getCommands()}"/>'


def card(regular: Font, x: float, y: float, w: float, h: float, values: list[str], outlined: bool) -> str:
    size, line, pad = 13.5, 26, 14
    label_w = max(width(regular, shaped(regular, r[0], size), size) for r in ROWS)
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{CARD}" stroke="{CARD_BORDER}"/>']
    for i, ((label, _, _), value) in enumerate(zip(ROWS, values, strict=True)):
        base = y + pad + 16 + i * line
        vx = x + pad + label_w + 8
        parts.append(path(regular, label, x + pad, base, size, LABEL))
        parts.append(path(regular, value, vx, base, size, TEXT))
        if outlined:
            vw = width(regular, shaped(regular, value, size), size)
            parts.append(
                f'<rect x="{vx - 3:.1f}" y="{base - 13.5:.1f}" width="{vw + 6:.1f}" height="19" '
                f'fill="none" stroke="{FOUND}" stroke-width="1.5"/>'
            )
    return "".join(parts)


def build(font_dir: Path) -> str:
    bold = Font.load(font_dir / "YodelGrotesk-Bold.otf")
    regular = Font.load(font_dir / "YodelGrotesk-Regular.otf")
    card_w, card_h, gap = 172, 100, 36
    right = WIDTH - 64
    first_x = right - 2 * card_w - gap
    card_y = (HEIGHT - card_h) / 2
    arrow_y = card_y + card_h / 2
    a0, a1 = first_x + card_w + 10, first_x + card_w + gap - 10
    label = " ".join(TAGLINE)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="presidio-agent: {label}">',
        f"<title>presidio-agent: {label}</title>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="{BACKGROUND}"/>',
        path(bold, NAME, 64, 142, 64, TEXT, tracking=-5),
        path(regular, TAGLINE[0], 64, 196, 19, SECONDARY),
        path(regular, TAGLINE[1], 64, 222, 19, SECONDARY),
        card(regular, first_x, card_y, card_w, card_h, [r[1] for r in ROWS], outlined=True),
        f'<path d="M{a0:.1f} {arrow_y:.1f}H{a1 - 6:.1f}" stroke="{ARROW}" stroke-width="1.5"/>',
        f'<path d="M{a1:.1f} {arrow_y:.1f}l-7 -4.5v9z" fill="{ARROW}"/>',
        card(regular, first_x + card_w + gap, card_y, card_w, card_h, [r[2] for r in ROWS], outlined=False),
        "</svg>",
    ]
    return "".join(parts) + "\n"


def main() -> int:
    font_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/fonts/yodel-grotesk")
    out = Path(__file__).resolve().parent.parent / "assets" / "cover.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(font_dir), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
