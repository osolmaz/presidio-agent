"""Replace the text in one line box and paste it back into the scan.

Only pixels inside the (slightly enlarged) box change; the rest of the scan is
copied unchanged, so repeated edits cannot degrade the page.
"""
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

FONTS = {
    (False, False): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    (True, False): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    (False, True): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    (True, True): "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
}


def _ink_and_paper(crop: Image.Image):
    gray = crop.convert("L")
    px = sorted(gray.getdata())
    n = len(px)
    dark_cut = px[max(0, n // 20)] + 40           # pixels near the darkest 5 percent are ink
    ink_px = [p for p in crop.convert("RGB").getdata() if sum(p) / 3 <= dark_cut]
    paper = tuple(int(v) for v in ImageStat.Stat(crop.convert("RGB")).median)
    ink = tuple(int(sum(c) / len(ink_px)) for c in zip(*ink_px)) if ink_px else (20, 20, 20)
    ink_share = sum(1 for p in px if p <= dark_cut) / n
    return ink, paper, ink_share


def _fit_font(text, box_w, box_h, bold, mono):
    path = FONTS[(bold, mono)]
    size = max(6, int(box_h * 0.95))
    while size > 6:
        font = ImageFont.truetype(path, size)
        x1, y1, x2, y2 = font.getbbox(text)
        if x2 - x1 <= box_w * 1.02 and y2 - y1 <= box_h * 1.05:
            return font
        size -= 1
    return ImageFont.truetype(path, 6)


def replace_line(scan: Image.Image, box, new_text: str, rng: random.Random, mono=False, pad=4):
    """Return a new scan with the text in `box` replaced by `new_text`."""
    x1, y1, x2, y2 = box
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(scan.width, x2 + pad), min(scan.height, y2 + pad)
    crop = scan.crop((x1, y1, x2, y2)).convert("RGB")
    ink, paper, ink_share = _ink_and_paper(crop)
    bold = ink_share > 0.16

    # Blank the box with the paper colour and a little scan noise.
    patch = Image.new("RGB", crop.size, paper)
    noise = Image.effect_noise(crop.size, 6).convert("RGB")
    patch = Image.blend(patch, Image.composite(noise, patch, noise.convert("L").point(lambda v: 40)), 0.15)

    w, h = crop.size
    font = _fit_font(new_text, w - 2 * pad, h - 2 * pad, bold, mono)
    draw = ImageDraw.Draw(patch)
    bx1, by1, bx2, by2 = font.getbbox(new_text)
    ty = pad + ((h - 2 * pad) - (by2 - by1)) // 2 - by1
    draw.text((pad - bx1, ty), new_text, font=font, fill=ink)

    # Match a scan: slight blur, then paste with a soft edge.
    patch = patch.filter(ImageFilter.GaussianBlur(0.6))
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).rectangle((1, 1, w - 2, h - 2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))
    out = scan.convert("RGB").copy()
    out.paste(patch, (x1, y1), mask)
    return out, (x1, y1, x2, y2)
