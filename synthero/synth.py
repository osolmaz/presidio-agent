"""Make one synthetic copy from an analysed scan, and the answer keys that describe it.

No model or OCR is called here: the readers are passed in, so the whole edit path is
tested with fakes. The public key holds new values only; the private key maps old to
new and must never be served or shared.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from PIL import Image, ImageDraw

from synthero import barcode, fonts, geometry, leak, match, render, values
from synthero.detect import Value
from synthero.geometry import Box
from synthero.locate import Located, Reader, overlaps

PageReader = Callable[[Image.Image], str]

# Values whose number a barcode may encode.
BARCODE_TYPES = {"id", "card"}


class Place(TypedDict):
    box: list[int]
    read_back_ok: NotRequired[bool]
    barcode: NotRequired[list[int]]  # bars redrawn beside the new value
    barcode_valid: NotRequired[bool]  # True: a Code 128 of the new value; False: a pattern that encodes nothing


class Change(TypedDict):
    type: str
    owner: str
    new: str
    located: bool
    places: list[Place]
    read_back_ok: bool


class LeakVerdict(TypedDict):
    passed: bool
    leaked_types: list[str]


class PageKey(TypedDict):
    page: int
    changes: list[Change]
    barcodes_scrambled: int  # other barcodes, whose content is unknown, redrawn to encode nothing
    leak_check: NotRequired[LeakVerdict]


class Key(TypedDict):
    seed: int
    pages: list[PageKey]


class PrivateChange(TypedDict):
    type: str
    owner: str
    old: str
    new: str
    located: bool


class PrivatePage(TypedDict):
    page: int
    changes: list[PrivateChange]
    leaks: NotRequired[list[leak.Leak]]


class PrivateKey(TypedDict):
    seed: int
    pages: list[PrivatePage]


@dataclass(frozen=True)
class Analysed:
    """One page: its image, the values found on it, where each is printed, and its other text."""

    image: Image.Image
    values: list[Value]
    locs: list[list[Located]]
    context: str


@dataclass(frozen=True)
class Copy:
    images: list[Image.Image]
    key: Key
    private_key: PrivateKey


def printed_text(v: Value, places: list[Located]) -> str:
    """What is printed for the value: the most common reading over its places, else the model's.

    The parts of a value wrapped over two lines are joined in order.
    """
    parts = sorted((p for p in places if p.words is not None), key=lambda p: p.words or (0, 0))
    if parts:
        return " ".join(p.printed for p in parts)
    texts = [p.printed for p in places]
    return max(texts, key=texts.count) if texts else v.text


def part_of(new: str, words: tuple[int, int] | None, total: int) -> str:
    """The words of the new value that a place prints, for a value wrapped over lines."""
    if words is None:
        return new
    tokens = new.split()
    if len(tokens) < 2:  # one word: split its characters
        tokens = list(new)
    n = len(tokens)

    def split(i: int) -> int:  # the same share of the words, and never an empty line
        return i if n == total else (0 if i == 0 else n if i == total else min(max(round(i * n / total), 1), n - 1))

    joiner = " " if len(new.split()) > 1 else ""
    return joiner.join(tokens[split(words[0]) : split(words[1])])


def page_line_height(locs: list[list[Located]]) -> int:
    """The median height of the page's located values: the line height for barcode tests."""
    heights = sorted(p.run_box[3] - p.run_box[1] for places in locs for p in places)
    return heights[len(heights) // 2] if heights else 12


def _redraw_barcode(
    out: Image.Image, scan: Image.Image, run: Box, new: str, line_h: int
) -> tuple[list[int], bool] | None:
    """Replace a barcode beside a changed number with one that encodes the new number."""
    digits = match.digits(new)
    if len(digits) < 8 or len(digits) != len(match.digits(new.replace(" ", ""))):
        return None
    gray = scan.convert("L")
    h = max(4, line_h)
    width = run[2] - run[0]
    region = (
        max(0, run[0] - width),
        max(0, run[1] - 8 * h),
        min(gray.width, run[2] + width),
        min(gray.height, run[3] + 8 * h),
    )
    bars = barcode.find_bars(gray, region, h)
    if bars is None:
        return None
    # The bars never cover the number printed above or below them.
    above = (bars[1] + bars[3]) / 2 < (run[1] + run[3]) / 2
    top, bottom = (bars[1], min(bars[3], run[1] - 1)) if above else (max(bars[1], run[3] + 1), bars[3])
    if bottom - top < h:
        return None
    bars = (bars[0], top, bars[2], bottom)
    paper = geometry.paper_colour(scan.crop(region))
    # Paint over the old bars' uneven ends too, everywhere but on the printed number.
    paint_over(out, barcode.full_extent(gray, bars, h // 2), [run], paper)
    valid = barcode.draw(out, bars, digits, (20, 20, 20), paper)
    return list(bars), valid


def page_style(scan: Image.Image, locs: list[list[Located]]) -> fonts.Style | None:
    """The font family and weight of the page's values, voted by all of them."""
    samples = []
    for loc in (p for places in locs for p in places):
        m = render.measure(scan, loc.line_box, loc.run_box)
        samples.append((scan.crop(m.value_box), loc.printed, m.ink_h))
    return fonts.page_style(samples) if samples else None


def paint_over(out: Image.Image, area: Box, keep: list[Box], paper: tuple[int, int, int]) -> None:
    """Paper over `area`, except on the boxes in `keep` (values already redrawn)."""
    mask = Image.new("L", out.size, 0)
    d = ImageDraw.Draw(mask)
    d.rectangle((area[0], area[1], area[2] - 1, area[3] - 1), fill=255)
    for b in keep:
        d.rectangle((b[0] - 1, b[1] - 1, b[2], b[3]), fill=0)
    out.paste(Image.new("RGB", out.size, paper), (0, 0), mask)


def scramble_barcodes(
    out: Image.Image, scan: Image.Image, locs: list[list[Located]], redrawn: list[list[int]], seed: int
) -> int:
    """Redraw every other barcode on the page as bars that encode nothing.

    A barcode that was not redrawn for a changed number may still encode personal data
    (an invoice or customer number), and a scan rarely resolves it well enough to tell.
    """
    line_h = page_line_height(locs)
    gray = scan.convert("L")
    done = [(b[0], b[1], b[2], b[3]) for b in redrawn]
    count = 0
    for bars in barcode.find_all(gray, line_h):
        if any(overlaps(bars, d) for d in done):
            continue
        paper = geometry.paper_colour(scan.crop(barcode.full_extent(gray, bars, line_h)))
        x0, y0, x1, _ = bars
        values = [p.run_box for places in locs for p in places]
        paint_over(out, barcode.full_extent(gray, bars, line_h // 2), values, paper)
        widths = barcode.pattern_widths(f"{seed}:{x0}:{y0}", x1 - x0)
        barcode.draw_widths(out, bars, widths, (20, 20, 20), paper)
        count += 1
    return count


def _edit_value(
    out: Image.Image,
    scan: Image.Image,
    new: str,
    places: list[Located],
    read: Reader | None,
    style: fonts.Style | None,
    line_h: int,
) -> tuple[Image.Image, list[Place]]:
    done: list[Place] = []
    total = len(" ".join(p.printed for p in places if p.words is not None).split())
    for loc in places:
        text = loc.before + part_of(new, loc.words, total) + loc.after
        old = loc.before + loc.printed + loc.after
        out, area = render.replace_words(out, scan, loc.line_box, loc.run_box, old, text, loc.next_x, style)
        place: Place = {"box": list(loc.run_box)}
        if read is not None:
            place["read_back_ok"] = match.contains(read(out.crop(area)), text)
        is_number = loc.value.type in BARCODE_TYPES
        bars = _redraw_barcode(out, scan, loc.run_box, new, line_h) if is_number else None
        if bars is not None:
            place["barcode"], place["barcode_valid"] = bars
        done.append(place)
    return out, done


def make_copy(
    pages: list[Analysed],
    seed: int,
    read: Reader | None = None,
    read_page: PageReader | None = None,
) -> Copy:
    """One synthetic copy of a document: every located value replaced with a consistent invented one.

    One replacer serves all pages, so a person, number, or date shift is the same on every
    page. `read` reads back each edit (None: no read-back). `read_page` reads each finished
    page for the leak check (None: no leak check), which searches for every detected value,
    located or not.
    """
    repl = values.Replacer(random.Random(seed))
    done = [_copy_page(page, n, repl, seed, read, read_page) for n, page in enumerate(pages, start=1)]
    key: Key = {"seed": seed, "pages": [d[1] for d in done]}
    private_key: PrivateKey = {"seed": seed, "pages": [d[2] for d in done]}
    return Copy([d[0] for d in done], key, private_key)


def _copy_page(
    page: Analysed,
    n: int,
    repl: values.Replacer,
    seed: int,
    read: Reader | None,
    read_page: PageReader | None,
) -> tuple[Image.Image, PageKey, PrivatePage]:
    scan, vals, locs = page.image, page.values, page.locs
    out = scan.convert("RGB").copy()
    style = page_style(scan, locs)
    public: list[Change] = []
    private: list[PrivateChange] = []
    for v, places in zip(vals, locs, strict=True):
        old = printed_text(v, places)
        new = repl.replace(old, v.type, v.owner)
        edits: list[Place] = []
        if new != old:
            out, edits = _edit_value(out, scan, new, places, read, style, page_line_height(locs))
        ok = bool(edits) and all(p.get("read_back_ok", True) for p in edits)
        public.append(
            {"type": v.type, "owner": v.owner, "new": new, "located": bool(places), "places": edits, "read_back_ok": ok}
        )
        private.append({"type": v.type, "owner": v.owner, "old": old, "new": new, "located": bool(places)})
    redrawn = [p["barcode"] for c in public for p in c["places"] if "barcode" in p]
    scrambled = scramble_barcodes(out, scan, locs, redrawn, seed)
    key: PageKey = {"page": n, "changes": public, "barcodes_scrambled": scrambled}
    private_page: PrivatePage = {"page": n, "changes": private}
    if read_page is not None:
        olds = sorted(
            {(v.type, t) for v, ps in zip(vals, locs, strict=True) for t in [v.text] + [p.printed for p in ps]}
        )
        # A value the replacer could not change is a leak, and must not excuse itself.
        changed = [c["new"] for c in private if c["new"] != c["old"]]
        leaks = leak.check(read_page(out), olds, page.context, changed)
        leaks += [{"type": c["type"], "pieces": ["(unchanged)"]} for c in private if c["new"] == c["old"]]
        key["leak_check"] = {"passed": not leaks, "leaked_types": sorted({x["type"] for x in leaks})}
        private_page["leaks"] = leaks
    return out, key, private_page


def page_context(ocr_text: str, vals: list[Value], locs: list[list[Located]]) -> str:
    """The page's other text (labels, the business's own address): the OCR text without the values."""
    for v, ps in zip(vals, locs, strict=True):
        for t in [v.text] + [p.printed for p in ps]:
            ocr_text = ocr_text.replace(t, " ")
    return ocr_text


def analysis_to_json(vals: list[Value], locs: list[list[Located]]) -> dict[str, object]:
    return {
        "values": [{"text": v.text, "type": v.type, "owner": v.owner, "hint": list(v.hint)} for v in vals],
        "located": [
            [
                {
                    "line_box": list(p.line_box),
                    "run_box": list(p.run_box),
                    "next_x": p.next_x,
                    "how": p.how,
                    "printed": p.printed,
                    "words": list(p.words) if p.words else None,
                    "before": p.before,
                    "after": p.after,
                }
                for p in ps
            ]
            for ps in locs
        ],
    }


def _box(v: object) -> Box:
    if not (isinstance(v, list) and len(v) == 4 and all(isinstance(n, int) for n in v)):
        raise ValueError(f"not a box: {v!r}")
    return (v[0], v[1], v[2], v[3])


def _str(d: dict[str, object], k: str) -> str:
    v = d.get(k)
    if not isinstance(v, str):
        raise ValueError(f"{k} is not a string: {v!r}")
    return v


def analysis_from_json(data: object) -> tuple[list[Value], list[list[Located]]]:
    """Inverse of `analysis_to_json`; raises ValueError on a malformed cache."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("values"), list)
        or not isinstance(data.get("located"), list)
    ):
        raise ValueError("malformed analysis cache")
    vals = [Value(_str(v, "text"), _str(v, "type"), _str(v, "owner"), _box(v["hint"])) for v in data["values"]]
    locs: list[list[Located]] = []
    for v, places in zip(vals, data["located"], strict=True):
        locs.append(
            [
                Located(
                    v,
                    _box(p["line_box"]),
                    _box(p["run_box"]),
                    _next_x(p["next_x"]),
                    _str(p, "how"),
                    _str(p, "printed"),
                    _span(p.get("words")),
                )
                for p in places
            ]
        )
    return vals, locs


def _span(v: object) -> tuple[int, int] | None:
    if v is None:
        return None
    if isinstance(v, list) and len(v) == 2 and all(isinstance(n, int) for n in v):
        return (v[0], v[1])
    raise ValueError(f"not a word span: {v!r}")


def _next_x(v: object) -> int | None:
    if v is None or isinstance(v, int):
        return v
    raise ValueError(f"next_x is not an int: {v!r}")
