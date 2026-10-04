"""Pick the installed font that best reproduces a printed value.

The old value is rendered in each candidate font, stretched to the original's ink
box, and compared with the original's ink pixel by pixel. The font whose letter
shapes overlap the original's best wins, so a narrow receipt font gets a narrow
font and a bold heading gets a bold one. The width correction is applied to the
new value too, so a value of the same length takes the same space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

Font = ImageFont.FreeTypeFont

# Common families on Linux, as (regular, bold): metric clones of Arial, Courier, and
# Helvetica Narrow, and the DejaVu family. Families that are not installed are skipped;
# Liberation is required.
FAMILIES = {
    "Liberation Sans": ("liberation/LiberationSans-Regular.ttf", "liberation/LiberationSans-Bold.ttf"),
    "Liberation Mono": ("liberation/LiberationMono-Regular.ttf", "liberation/LiberationMono-Bold.ttf"),
    "DejaVu Sans": ("dejavu/DejaVuSans.ttf", "dejavu/DejaVuSans-Bold.ttf"),
    "DejaVu Sans Condensed": ("dejavu/DejaVuSansCondensed.ttf", "dejavu/DejaVuSansCondensed-Bold.ttf"),
    "DejaVu Sans Mono": ("dejavu/DejaVuSansMono.ttf", "dejavu/DejaVuSansMono-Bold.ttf"),
    "Nimbus Sans Narrow": ("urw-base35/NimbusSansNarrow-Regular.otf", "urw-base35/NimbusSansNarrow-Bold.otf"),
    "Nimbus Mono PS": ("urw-base35/NimbusMonoPS-Regular.otf", "urw-base35/NimbusMonoPS-Bold.otf"),
}
# How much better the other weight must reproduce a value to override the page's weight.
WEIGHT_MARGIN = 0.05
FONT_ROOTS = ("/usr/share/fonts/truetype", "/usr/share/fonts/opentype")


def _find(name: str) -> str | None:
    return next((f"{root}/{name}" for root in FONT_ROOTS if Path(f"{root}/{name}").exists()), None)


def available() -> dict[str, tuple[str, str]]:
    """Installed families, as paths to (regular, bold)."""
    found = {}
    for family, (regular, bold) in FAMILIES.items():
        r, b = _find(regular), _find(bold)
        if r and b:
            found[family] = (r, b)
    return found


def shape_cut(img: Image.Image) -> int:
    """Halfway between the ink and the paper: the stroke without the scan's blur around it."""
    data = sorted(img.convert("L").tobytes())
    if not data:
        return 128
    ink, paper = data[len(data) // 20], data[min(len(data) - 1, len(data) * 9 // 10)]
    return (ink + paper) // 2 if paper - ink > 40 else ink - 1


def ink_mask(img: Image.Image, cut: int) -> Image.Image:
    """255 where the pixel is ink, cropped to the ink's bounding box."""
    mask = img.convert("L").point(lambda v: 255 if v < cut else 0)
    box = mask.getbbox()
    return mask.crop(box) if box else mask


def font_for_ink_height(path: str, text: str, ink_h: int) -> Font:
    """The largest size at which `text`'s rendered ink is at most `ink_h` tall.

    Measured on the rendered ink: some fonts' boxes include their whole line height.
    """
    low, high = 6, max(8, ink_h * 3)
    while low < high:  # ink height grows with the size, so a binary search finds the largest fit
        mid = (low + high + 1) // 2
        if render_mask(text, ImageFont.truetype(path, mid)).height <= ink_h:
            low = mid
        else:
            high = mid - 1
    return ImageFont.truetype(path, low)


def render_mask(text: str, font: Font) -> Image.Image:
    x1, y1, x2, y2 = font.getbbox(text)
    img = Image.new("L", (int(x2 - x1) + 4, int(y2 - y1) + 4), 255)
    ImageDraw.Draw(img).text((2 - x1, 2 - y1), text, font=font, fill=0)
    return ink_mask(img, 128)


def overlap(a: Image.Image, b: Image.Image) -> float:
    """Intersection over union of two same-sized masks, each grown by a pixel for scan blur."""
    a, b = a.filter(ImageFilter.MaxFilter(3)), b.filter(ImageFilter.MaxFilter(3))
    pa, pb = a.tobytes(), b.tobytes()
    both = sum(1 for x, y in zip(pa, pb, strict=True) if x and y)
    either = sum(1 for x, y in zip(pa, pb, strict=True) if x or y)
    return both / either if either else 0.0


# How much a font loses per unit of log width correction: a narrow font stretched 1.75
# times looks like a wide one after stretching, but it is not the font that was printed.
WIDTH_PENALTY = 0.5


def score(target: Image.Image, old: str, ink_h: int, path: str) -> tuple[float, Font, float]:
    """How well `old` in this font reproduces the target, the font, and its width correction.

    The letter shapes are compared after stretching to the original's box, and the score
    loses `WIDTH_PENALTY` per unit of |ln(stretch)|, so the font must also fit its width.
    """
    # Sized to the target's own height: both are cut halfway between ink and paper, while
    # `ink_h` also counts the light anti-aliased rows and would make every font too big.
    font = font_for_ink_height(path, old, target.height if target.height > 1 else ink_h)
    rendered = render_mask(old, font)
    w, h = max(1, target.width), max(1, target.height)
    stretched = rendered.resize((w, h), Image.Resampling.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    scale = w / max(1, rendered.width)
    return overlap(target, stretched) - WIDTH_PENALTY * abs(math.log(scale)), font, scale


def target_mask(original: Image.Image) -> Image.Image:
    return ink_mask(original, shape_cut(original))


@dataclass(frozen=True)
class Style:
    family: str
    bold: bool


def page_style(samples: list[tuple[Image.Image, str, int]]) -> Style:
    """The family and weight that reproduce all of a page's values best: (crop, old text, ink height) each.

    A document is printed in one or two families and mostly one weight; voting with
    every value is far more reliable than judging a few letters alone.
    """
    families = available()
    if not families:
        raise RuntimeError("no fonts found; install fonts-liberation")
    masks = [(target_mask(crop), text, ink_h) for crop, text, ink_h in samples]
    totals = {
        Style(family, bold): sum(score(m, text, h, paths[bold])[0] for m, text, h in masks)
        for family, paths in families.items()
        for bold in (False, True)
    }
    return max(totals, key=lambda s: totals[s])


def best(original: Image.Image, old: str, ink_h: int, style: Style | None = None) -> tuple[Font, float]:
    """The font that reproduces `old` best, and its width correction.

    With the page's `style`, its family is kept, and its weight too unless the other
    weight is clearly better (a bold name among regular numbers).
    """
    families = available()
    if not families:
        raise RuntimeError("no fonts found; install fonts-liberation")
    target = target_mask(original)
    if style is None or style.family not in families:
        paths = [p for pair in families.values() for p in pair]
        _, font, scale = max((score(target, old, ink_h, p) for p in paths), key=lambda s: s[0])
        return font, scale
    pair = families[style.family]
    usual = score(target, old, ink_h, pair[style.bold])
    other = score(target, old, ink_h, pair[not style.bold])
    _, font, scale = other if other[0] > usual[0] + WEIGHT_MARGIN else usual
    return font, scale
