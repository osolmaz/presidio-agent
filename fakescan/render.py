"""Replace the text in one line box and paste it back into the scan.

Only pixels inside the box change; the rest of the scan is copied unchanged,
so repeated edits cannot degrade the page.

The model's box is only roughly right, so `snap_box` finds the real ink of the
line around it first. The new text is drawn in the regular or bold font whose
stroke density is closer to the original, at the original letter height.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = {
    # Liberation Sans has Arial's widths and Liberation Mono has Courier's, the
    # usual fonts of printed invoices and till receipts.
    (False, False): "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    (True, False): "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    (False, True): "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    (True, True): "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
}


def _percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def paper_level(gray: Image.Image) -> int:
    return _percentile(list(gray.getdata()), 0.90)


def snap_box(scan: Image.Image, box, grow_y=0.6, grow_x=40):
    """Return the tight ink bounds of the text line that the model's box points at."""
    gray = scan.convert("L")
    x1, y1, x2, y2 = box
    h = max(4, y2 - y1)
    sx1, sx2 = max(0, x1 - grow_x), min(scan.width, x2 + grow_x)
    sy1, sy2 = max(0, int(y1 - grow_y * h)), min(scan.height, int(y2 + grow_y * h))
    region = gray.crop((sx1, sy1, sx2, sy2))
    w, rh = region.size
    cut = paper_level(region) - 70
    px = region.load()
    # Table rules: a row inked across most of the width, or a column inked down
    # most of the height, is a line of the form, not text.
    def longest_run(values):
        best = run = 0
        for v in values:
            run = run + 1 if v else 0
            best = max(best, run)
        return best

    # A table line is one long unbroken run of ink; text always has gaps.
    rule_rows = {y for y in range(rh) if longest_run(px[x, y] < cut for x in range(w)) > max(20, 0.2 * w)}
    rule_cols = {x for x in range(w) if longest_run(px[x, y] < cut for y in range(rh)) > 0.45 * rh}
    rows = [0 if y in rule_rows else sum(1 for x in range(w) if x not in rule_cols and px[x, y] < cut)
            for y in range(rh)]

    # The ink band nearest the middle of the model's box.
    centre = (y1 + y2) // 2 - sy1
    inked = [r > 1 for r in rows]
    if not any(inked):
        return box
    start = min((y for y in range(rh) if inked[y]), key=lambda y: abs(y - centre))
    top = bottom = start
    while top > 0 and (inked[top - 1] or (top > 1 and inked[top - 2])):
        top -= 1
    while bottom < rh - 1 and (inked[bottom + 1] or (bottom < rh - 2 and inked[bottom + 2])):
        bottom += 1

    band_h = bottom - top + 1
    # Stay within a few pixels of the model's box sideways, and drop vertical
    # cell lines (columns inked down almost the whole band).
    reach = max(6, int(1.5 * h))  # the model's box can be off by a word's width
    lo, hi = max(0, x1 - sx1 - reach), min(w, x2 - sx1 + reach)
    cols = [lo <= x < hi and x not in rule_cols
            and 0 < sum(1 for y in range(top, bottom + 1) if px[x, y] < cut) < 0.85 * band_h for x in range(w)]
    ink_cols = [x for x in range(w) if cols[x]]
    # A vertical cell line ends the text line: split there and keep the part that
    # overlaps the model's box the most, so a neighbouring cell's text stays out.
    # A cell line, unlike a letter stem, also runs above and below the text band.
    # The test uses the two rows right next to the band: a horizontal cell line a few
    # rows away is inked across every column and must not count.
    def reaches_out(x):
        above = all(0 <= y < rh and px[x, y] < cut for y in (top - 1, top - 2))
        below = all(0 <= y < rh and px[x, y] < cut for y in (bottom + 1, bottom + 2))
        return above and below

    walls = [x for x in range(lo, hi)
             if sum(1 for y in range(top, bottom + 1) if px[x, y] < cut) >= 0.85 * band_h and reaches_out(x)]
    if walls and ink_cols:
        parts, cur = [], [ink_cols[0]]
        for x in ink_cols[1:]:
            if any(cur[-1] < wx < x for wx in walls):
                parts.append(cur)
                cur = [x]
            else:
                cur.append(x)
        parts.append(cur)
        mx1, mx2 = x1 - sx1, x2 - sx1
        ink_cols = max(parts, key=lambda c: sum(1 for x in c if mx1 <= x < mx2))
    if ink_cols:
        # Recompute the band from the kept columns only, so a neighbour cell's ink cannot stretch it.
        rows2 = [y for y in range(rh) if y not in rule_rows and any(px[x, y] < cut for x in ink_cols)]
        near = [y for y in rows2 if top - 2 <= y <= bottom + 2]
        if near:
            top, bottom = min(near), max(near)
            band_h = bottom - top + 1
    # Keep the model's box when the snap is clearly wrong.
    if not ink_cols or not (0.5 * h <= band_h <= 1.6 * h):
        return box
    return (sx1 + ink_cols[0], sy1 + top, sx1 + ink_cols[-1] + 1, sy1 + bottom + 1)


def _ink_density(img: Image.Image, cut: int) -> float:
    data = list(img.convert("L").getdata())
    return sum(1 for p in data if p < cut) / max(1, len(data))


def _render(text, font, size, ink, paper):
    x1, y1, x2, y2 = font.getbbox(text)
    img = Image.new("RGB", size, paper)
    ImageDraw.Draw(img).text((-x1, (size[1] - (y2 - y1)) // 2 - y1), text, font=font, fill=ink)
    return img


def _font_for_width(path, text, target_w, max_h):
    """Largest font size at which `text` is at most `target_w` wide and its capitals at most `max_h` tall."""
    for size in range(max(8, max_h * 3), 5, -1):
        f = ImageFont.truetype(path, size)
        x1, _, x2, _ = f.getbbox(text)
        _, t, _, b = f.getbbox("H")
        if x2 - x1 <= target_w * 1.02 and b - t <= max_h:
            return f
    return ImageFont.truetype(path, 6)


def _font_for_height(path, text, target_h, max_w=None):
    """Font size whose letter height matches the original, and whose width fits the original line."""
    # Plain capitals and digits only: accents such as the dots of Ö would make the font too small.
    probe = "".join(c for c in text if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") or "H"
    size = 6
    for s in range(max(6, target_h * 2), 5, -1):
        f = ImageFont.truetype(path, s)
        _, t, _, b = f.getbbox(probe)
        x1, _, x2, _ = f.getbbox(text)
        if b - t <= target_h and (max_w is None or x2 - x1 <= max_w):
            size = s
            break
    return ImageFont.truetype(path, size)


def _free_right(gray: Image.Image, box, cut, gap=1, limit=400):
    """x of the next ink to the right of the line (another word, or a cell line), or the page edge."""
    x1, y1, x2, y2 = box
    px = gray.load()
    blank = 0
    for x in range(x2, min(gray.width, x2 + limit)):
        if any(px[x, y] < cut for y in range(y1, y2)):
            if blank >= gap:
                return x
            blank = 0
        else:
            blank += 1
    return min(gray.width, x2 + limit)


def _free_vertical(gray: Image.Image, box, cut, step, limit=12):
    """Blank rows above (step -1) or below (step +1) the line, before the neighbouring line's ink."""
    x1, y1, x2, y2 = box
    px = gray.load()
    y = y1 - 1 if step < 0 else y2
    n = 0
    while 0 <= y < gray.height and n < limit:
        if any(px[x, y] < cut for x in range(x1, x2)):
            return max(0, n - 1)
        n += 1
        y += step
    return n


def word_spans(gray: Image.Image, box, cut):
    """Split a line's ink into words at gaps wider than about a third of the letter height."""
    x1, y1, x2, y2 = box
    px = gray.load()
    min_gap = max(3, int((y2 - y1) * 0.35))
    spans, start, blank = [], None, 0
    for x in range(x1, x2):
        inked = any(px[x, y] < cut for y in range(y1, y2))
        if inked:
            if start is None:
                start = x
            elif blank >= min_gap:
                spans.append((start, x - blank))
                start = x
            blank = 0
        elif start is not None:
            blank += 1
    if start is not None:
        spans.append((start, x2 - blank))
    return spans


def replace_line(scan: Image.Image, box, new_text: str, old_text: str = "", pad=6):
    """Return a new scan where the words that differ between old_text and new_text are redrawn.

    Words they share at the start (labels such as "Datum:") keep their original pixels.
    Also returns the changed area.
    """
    tight = snap_box(scan, box)
    tx1, ty1, tx2, ty2 = tight
    ink_h = ty2 - ty1
    gray = scan.convert("L")
    local = gray.crop((max(0, tx1 - 20), max(0, ty1 - 10), min(scan.width, tx2 + 20), min(scan.height, ty2 + 10)))
    paper_v = paper_level(local)
    cut = paper_v - 70
    paper = (paper_v,) * 3

    # Keep the leading words both texts share; redraw from the first differing word.
    old_words, new_words = old_text.split(), new_text.split()
    k = 0
    while k < min(len(old_words), len(new_words)) - 1 and old_words[k] == new_words[k]:
        k += 1
    spans = word_spans(gray, tight, cut)
    if k and len(spans) == len(old_words):
        vx1 = spans[k][0]
        draw_text = " ".join(new_words[k:])
    else:
        vx1, draw_text = tx1, new_text
    # The value can be printed smaller than its label ("Nr.:" bold, the number regular), so
    # measure the value's own ink rows.
    px = gray.load()
    band = max(1, ty2 - ty1)
    # Leave out vertical cell lines: columns inked down most of the band.
    vcols = [x for x in range(vx1, tx2) if sum(1 for y in range(ty1, ty2) if px[x, y] < cut) < 0.7 * band]
    vrows = [y for y in range(ty1, ty2) if any(px[x, y] < cut for x in vcols)]
    if vrows and k:
        ty1, ty2 = vrows[0], vrows[-1] + 1
        ink_h = ty2 - ty1
    value_box = (vx1, ty1, tx2, ty2)

    orig = scan.crop(value_box).convert("RGB")
    ink_px = sorted(p for p in orig.getdata() if sum(p) / 3 < cut)
    ink = tuple(int(sum(c) / len(ink_px)) for c in zip(*ink_px[: max(1, len(ink_px) // 2)])) if ink_px else (15, 15, 15)

    # Style: render the OLD value in each font at the measured height and keep the one
    # closest to the original pixels in width and ink density. Its width correction is
    # applied to the new value too, so a value of the same length takes the same space.
    old_value = " ".join(old_words[k:]) if k and len(spans) == len(old_words) else old_text
    orig_w = max(1, tx2 - vx1)
    target = _ink_density(orig, cut)
    best = None
    for bold in (False, True):
        for mono in (False, True):
            path = FONTS[(bold, mono)]
            # The largest size at which the OLD text is no wider than the original and
            # no taller than its ink: width is robust against "@", descenders, and umlauts.
            f = _font_for_width(path, old_value, orig_w, ink_h + 1)
            ow = max(1, f.getbbox(old_value)[2] - f.getbbox(old_value)[0])
            r = _render(old_value, f, (ow, ink_h + 2), (0, 0, 0), (255, 255, 255))
            density = _ink_density(r, 128)
            score = abs(ow - orig_w) / orig_w + 2 * abs(density - target)
            if mono:  # monospace only when it fits clearly better than the normal font
                score *= 1.6
            if best is None or score < best[0]:
                best = (score, f, orig_w / ow)
    _, font, width_scale = best

    # Free space to the right (next word or cell line) and above/below (neighbouring lines).
    right = _free_right(gray, tight, cut)
    pad_top = min(pad, _free_vertical(gray, tight, cut, -1))
    pad_bottom = min(pad, _free_vertical(gray, tight, cut, +1))
    gx1, _, gx2, _ = font.getbbox(draw_text)
    text_w = gx2 - gx1
    max_w = max(tx2 - vx1, right - vx1 - 3)
    squeeze = min(width_scale, max_w / max(1, text_w))

    # Draw with the tops of the capitals on the original's top ink row.
    cap_top = font.getbbox("H")[1]
    canvas_h = ink_h + pad_top + pad_bottom
    canvas = Image.new("L", (text_w + 2, canvas_h + 8), 0)
    ImageDraw.Draw(canvas).text((-gx1 + 1, pad_top - cap_top), draw_text, font=font, fill=255)
    canvas = canvas.crop((0, 0, canvas.width, canvas_h))
    if abs(squeeze - 1.0) > 0.01:
        canvas = canvas.resize((max(1, int(canvas.width * squeeze)), canvas_h), Image.LANCZOS)

    area_x2 = min(scan.width, max(tx2, vx1 + canvas.width) + pad, max(right, tx2 + 1))
    area = (max(0, vx1 - pad), max(0, ty1 - pad_top), area_x2, min(scan.height, ty2 + pad_bottom))
    w, h = area[2] - area[0], area[3] - area[1]
    patch = Image.new("RGB", (w, h), paper)
    noise = Image.effect_noise((w, h), 8).convert("RGB")
    patch = Image.blend(patch, Image.composite(noise, patch, noise.convert("L").point(lambda v: 60)), 0.1)
    text_mask = Image.new("L", (w, h), 0)
    text_mask.paste(canvas, (vx1 - area[0], 0))
    patch.paste(Image.new("RGB", (w, h), ink), (0, 0), text_mask)
    patch = patch.filter(ImageFilter.GaussianBlur(0.5))
    mask = Image.new("L", (w, h), 0)
    # Solid over the old ink, soft only at the outer edge, which is blank paper.
    ImageDraw.Draw(mask).rectangle((2, 0 if pad_top < 3 else 2, w - 3, h - 1 if pad_bottom < 3 else h - 3), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    out = scan.convert("RGB").copy()
    out.paste(patch, area[:2], mask)
    line_area = (min(area[0], tight[0]), min(area[1], tight[1]), max(area[2], tight[2]), max(area[3], tight[3]))
    return out, line_area
