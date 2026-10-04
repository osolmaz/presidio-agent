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

from PIL import Image

from synthero import barcode, geometry, leak, match, render, values
from synthero.detect import Value
from synthero.geometry import Box
from synthero.locate import Located, Reader

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


class Key(TypedDict):
    seed: int
    changes: list[Change]
    leak_check: NotRequired[LeakVerdict]


class PrivateChange(TypedDict):
    type: str
    owner: str
    old: str
    new: str
    located: bool


class PrivateKey(TypedDict):
    seed: int
    changes: list[PrivateChange]
    leaks: NotRequired[list[leak.Leak]]


@dataclass(frozen=True)
class Copy:
    image: Image.Image
    key: Key
    private_key: PrivateKey


def printed_text(v: Value, places: list[Located]) -> str:
    """What is printed for the value: the most common reading over its places, else the model's."""
    texts = [p.printed for p in places]
    return max(texts, key=texts.count) if texts else v.text


def _redraw_barcode(out: Image.Image, scan: Image.Image, run: Box, new: str) -> tuple[list[int], bool] | None:
    """Replace a barcode beside a changed number with one that encodes the new number."""
    digits = match.digits(new)
    if len(digits) < 8 or len(digits) != len(match.digits(new.replace(" ", ""))):
        return None
    gray = scan.convert("L")
    h = max(4, run[3] - run[1])
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
    paper = geometry.paper_level(gray.crop(region))
    valid = barcode.draw(out, bars, digits, (20, 20, 20), (paper, paper, paper))
    return list(bars), valid


def _edit_value(
    out: Image.Image, scan: Image.Image, new: str, places: list[Located], read: Reader | None
) -> tuple[Image.Image, list[Place]]:
    done: list[Place] = []
    for loc in places:
        out, area = render.replace_words(out, scan, loc.line_box, loc.run_box, loc.printed, new, loc.next_x)
        place: Place = {"box": list(loc.run_box)}
        if read is not None:
            place["read_back_ok"] = match.contains(read(out.crop(area)), new)
        bars = _redraw_barcode(out, scan, loc.run_box, new) if loc.value.type in BARCODE_TYPES else None
        if bars is not None:
            place["barcode"], place["barcode_valid"] = bars
        done.append(place)
    return out, done


def make_copy(
    scan: Image.Image,
    vals: list[Value],
    locs: list[list[Located]],
    seed: int,
    context: str,
    read: Reader | None = None,
    read_page: PageReader | None = None,
) -> Copy:
    """Replace every located value with a consistent invented one.

    `read` reads back each edit (None: no read-back). `read_page` reads the whole
    finished page for the leak check (None: no leak check), which searches for every
    detected value, located or not. `context` is the page's text without the values.
    """
    repl = values.Replacer(random.Random(seed))
    out = scan.convert("RGB").copy()
    public: list[Change] = []
    private: list[PrivateChange] = []
    for v, places in zip(vals, locs, strict=True):
        old = printed_text(v, places)
        new = repl.replace(old, v.type, v.owner)
        done: list[Place] = []
        if new != old:
            out, done = _edit_value(out, scan, new, places, read)
        ok = bool(done) and all(p.get("read_back_ok", True) for p in done)
        public.append(
            {"type": v.type, "owner": v.owner, "new": new, "located": bool(places), "places": done, "read_back_ok": ok}
        )
        private.append({"type": v.type, "owner": v.owner, "old": old, "new": new, "located": bool(places)})
    key: Key = {"seed": seed, "changes": public}
    private_key: PrivateKey = {"seed": seed, "changes": private}
    if read_page is not None:
        olds = sorted(
            {(v.type, t) for v, ps in zip(vals, locs, strict=True) for t in [v.text] + [p.printed for p in ps]}
        )
        leaks = leak.check(read_page(out), olds, context, [c["new"] for c in private])
        key["leak_check"] = {"passed": not leaks, "leaked_types": sorted({x["type"] for x in leaks})}
        private_key["leaks"] = leaks
    return Copy(out, key, private_key)


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
                    v, _box(p["line_box"]), _box(p["run_box"]), _next_x(p["next_x"]), _str(p, "how"), _str(p, "printed")
                )
                for p in places
            ]
        )
    return vals, locs


def _next_x(v: object) -> int | None:
    if v is None or isinstance(v, int):
        return v
    raise ValueError(f"next_x is not an int: {v!r}")
