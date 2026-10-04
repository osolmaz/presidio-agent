"""Code 128 barcodes that encode a personal value: read them from pixels and redraw them.

A receipt's barcode usually encodes the number printed next to it. Changing the
digits without the bars would leave the old number in the image. A scan rarely
resolves the bars well enough to decode them, so whenever a changed number has a
barcode beside it, the bars are replaced by a Code 128 of the new number across
the same width. `decode_widths` checks the drawn bars in the tests.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from PIL import Image, ImageDraw

from synthero.geometry import Box, bands, ink_threshold, pixels

# Bar and space widths (in modules) of the Code 128 symbols 0..105 and the stop
# pattern, from the standard (ISO/IEC 15417).
WIDTHS = [
    "212222",
    "222122",
    "222221",
    "121223",
    "121322",
    "131222",
    "122213",
    "122312",
    "132212",
    "221213",
    "221312",
    "231212",
    "112232",
    "122132",
    "122231",
    "113222",
    "123122",
    "123221",
    "223211",
    "221132",
    "221231",
    "213212",
    "223112",
    "312131",
    "311222",
    "321122",
    "321221",
    "312212",
    "322112",
    "322211",
    "212123",
    "212321",
    "232121",
    "111323",
    "131123",
    "131321",
    "112313",
    "132113",
    "132311",
    "211313",
    "231113",
    "231311",
    "112133",
    "112331",
    "132131",
    "113123",
    "113321",
    "133121",
    "313121",
    "211331",
    "231131",
    "213113",
    "213311",
    "213131",
    "311123",
    "311321",
    "331121",
    "312113",
    "312311",
    "332111",
    "314111",
    "221411",
    "431111",
    "111224",
    "111422",
    "121124",
    "121421",
    "141122",
    "141221",
    "112214",
    "112412",
    "122114",
    "122411",
    "142112",
    "142211",
    "241211",
    "221114",
    "413111",
    "241112",
    "134111",
    "111242",
    "121142",
    "121241",
    "114212",
    "124112",
    "124211",
    "411212",
    "421112",
    "421211",
    "212141",
    "214121",
    "412121",
    "111143",
    "111341",
    "131141",
    "114113",
    "114311",
    "411113",
    "411311",
    "113141",
    "114131",
    "311141",
    "411131",
    "211412",
    "211214",
    "211232",
]
STOP = "2331112"
START_B, START_C, CODE_B = 104, 105, 100
SYMBOLS = {w: i for i, w in enumerate(WIDTHS)}


def symbols_for(digits: str) -> list[int]:
    """Code set C for digit pairs; an odd last digit switches to set B. Includes start and checksum."""
    if not digits.isdigit():
        raise ValueError(f"only digits can be encoded: {digits!r}")
    syms = [START_C] + [int(digits[i : i + 2]) for i in range(0, len(digits) - 1, 2)]
    if len(digits) % 2:
        syms += [CODE_B, ord(digits[-1]) - 32]
    checksum = (syms[0] + sum(i * s for i, s in enumerate(syms[1:], start=1))) % 103
    return [*syms, checksum]


def widths_for(digits: str) -> list[int]:
    """Module widths, bar first, alternating bar and space, stop included."""
    return [int(c) for s in symbols_for(digits) for c in WIDTHS[s]] + [int(c) for c in STOP]


def decode_widths(widths: Sequence[int]) -> str | None:
    """Digits encoded by module widths, or None when they are not a valid Code 128 C/B symbol run."""
    if len(widths) < 13 or (len(widths) - 7) % 6 or "".join(map(str, widths[-7:])) != STOP:
        return None
    syms = []
    for i in range(0, len(widths) - 7, 6):
        s = SYMBOLS.get("".join(map(str, widths[i : i + 6])))
        if s is None:
            return None
        syms.append(s)
    if len(syms) < 2 or syms[0] not in (START_B, START_C):
        return None
    *body, checksum = syms
    if (body[0] + sum(i * s for i, s in enumerate(body[1:], start=1))) % 103 != checksum:
        return None
    return _text(body)


def _text(body: list[int]) -> str | None:
    out, code_c = [], body[0] == START_C
    for s in body[1:]:
        if s == CODE_B:
            code_c = False
        elif code_c and s < 100:
            out.append(f"{s:02d}")
        elif not code_c and 16 <= s <= 25:  # set B digits "0".."9"
            out.append(chr(s + 32))
        else:
            return None
    return "".join(out)


def runs(row: Sequence[bool]) -> list[int]:
    """Lengths of alternating runs, starting at the first True (bar)."""
    start = next((i for i, v in enumerate(row) if v), None)
    end = max((i for i, v in enumerate(row) if v), default=-1)
    if start is None:
        return []
    out, length, cur = [], 0, True
    for v in row[start : end + 1]:
        if v == cur:
            length += 1
        else:
            out.append(length)
            cur, length = v, 1
    out.append(length)
    return out


def find_bars(gray: Image.Image, region: Box, line_height: int, min_runs: int = 40) -> Box | None:
    """A barcode inside `region`: at least two line heights of rows whose ink alternates many times.

    A text line can alternate as often as bars, but not for that many rows. Columns
    whose ink runs on above and below the block (a frame or cell line) are not bars.
    """
    x0, y0, x1, y1 = region
    px = pixels(gray)
    cut = ink_threshold(gray)
    busy = [len(runs([px[x, y] < cut for x in range(x0, x1)])) >= min_runs for y in range(y0, y1)]
    tall = [(y0 + a, y0 + b) for a, b in bands(busy) if b - a >= 2 * line_height]
    if not tall:
        return None
    top, bottom = max(tall, key=lambda band: band[1] - band[0])
    above, below = max(0, top - 6), min(gray.height - 1, bottom + 5)
    cols = [
        x
        for x in range(x0, x1)
        if any(px[x, y] < cut for y in range(top, bottom)) and not (px[x, above] < cut and px[x, below] < cut)
    ]
    return (cols[0], top, cols[-1] + 1, bottom) if cols else None


def pattern_widths(digits: str, modules: int) -> list[int]:
    """A bar pattern of `modules` modules derived from the digits: looks like bars, encodes nothing.

    Used when a valid Code 128 of the new number does not fit the old barcode's width.
    """
    rng = random.Random(digits)
    widths: list[int] = []
    while sum(widths) < modules:
        widths.append(rng.choice((1, 1, 2, 2, 3, 4)))
    widths[-1] -= sum(widths) - modules
    if widths[-1] <= 0:
        widths.pop()
    if len(widths) % 2 == 0:  # end on a bar: merge the last space into the bar before it
        last = widths.pop()
        widths[-1] += last
    return widths


def draw(img: Image.Image, bars: Box, digits: str, ink: tuple[int, int, int], paper: tuple[int, int, int]) -> bool:
    """Paint over `bars` and draw new bars across the same width.

    Returns True when the bars are a valid Code 128 of `digits`, False when that does not
    fit (modules under one pixel) and a pattern that encodes nothing was drawn instead.
    """
    x0, y0, x1, y1 = bars
    widths = widths_for(digits)
    valid = (x1 - x0) >= sum(widths)
    if not valid:
        widths = pattern_widths(digits, x1 - x0)
    module = (x1 - x0) / sum(widths)
    d = ImageDraw.Draw(img)
    d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=paper)
    pos = 0
    for i, w in enumerate(widths):
        if i % 2 == 0:
            left, right = x0 + round(pos * module), x0 + round((pos + w) * module) - 1
            d.rectangle((left, y0, max(left, right), y1 - 1), fill=ink)
        pos += w
    return valid
