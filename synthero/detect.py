"""Find the personal data on a scan, as values read from the image by the model.

The model returns each value as printed, with its type, its owner, and a rough box.
The rough box is only a hint for where to look; positions come from OCR and pixels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from synthero import vl

EDGE_PUNCTUATION = " \t:;,=-\u2013\u2014|("  # a label's colon, a list's comma, a title's dash: not the value
TYPES = ("person", "street", "city", "email", "phone", "date", "time", "id", "card", "iban")

PROMPT = """This is a scanned invoice or receipt. List every piece of personal data and every
transaction identifier that must change in a new synthetic copy: people's names, the customer's
address (the postal code and city together, as printed), e-mail, phone, customer, contract, order,
receipt, trace, terminal, and approval numbers, card numbers (payment, loyalty, customer cards) and
IBANs, the number printed under a barcode, dates and times. Do not list
the business's own name, address, phone, tax numbers, or bank details, amounts or prices, product or
article numbers, or labels such as "Datum:" or "Kd-Nr.:". List a value once even if it is printed
several times.

For each piece give:
- "text": the value exactly as printed, without its label and without titles such as "Herr" or "Dr.",
- "type": one of {types},
- "owner": one word per person ("customer", "salesperson", "manager", ...), or "payment" or
  "document" for card and document data; the same owner for all pieces about the same person
  or thing, and different owners for different people,
- "bbox_2d": [x1, y1, x2, y2], roughly where it is, from 0 to 1000 relative to the image.

Answer with only a JSON array."""

REVIEW = """This is the same scanned document. These personal values were already found:
{found}

Below is the page's text as read by OCR. OCR makes mistakes, so trust the image over it; use the text
only to notice what may be missing. List every piece of personal data about a customer or staff
member, or transaction identifier, that is printed on the page but missing above, in the same JSON
format (text as printed in the image, type, owner, bbox_2d). Still do not list the business's own
name, address, e-mail, web site, phone, tax, register, or bank details, amounts, prices, points or
bonus balances, product or article numbers, or labels. Answer with only a JSON array, [] if nothing
is missing.

OCR text:
{ocr}"""

DATE = re.compile(r"\d{1,2}\.\d{1,2}\.(\d{2,4})?")
TIME = re.compile(r"\d{1,2}:\d{2}(:\d{2})?")


def is_amount(text: str) -> bool:
    """A money amount or a number with a unit word ("146,50 EUR", "3.450 Bits", "18,50").

    Amounts are not personal data and must stay consistent with the totals, so they are
    never replaced, whatever the model says.
    """
    t = text.strip()
    with_unit = re.fullmatch(r"[-+]?\d[\d.,]*\s*(EUR|€|[A-Z][a-z]+)", t) is not None
    decimal = re.fullmatch(r"[-+]?(€\s*)?\d{1,3}([.]\d{3})*,\d{2}(\s*(EUR|€))?", t) is not None
    return with_unit or decimal


@dataclass(frozen=True)
class Value:
    text: str
    type: str
    owner: str
    hint: tuple[int, int, int, int]  # rough box in pixels, from the model


def parse(answer: object, width: int, height: int) -> list[Value]:
    """Validate the model's answer; drop anything malformed. Pure, so it is tested without a model."""
    values = []
    seen = set()
    for item in answer if isinstance(answer, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip(EDGE_PUNCTUATION)
        type_ = item.get("type")
        box = item.get("bbox_2d")
        if not text or type_ not in TYPES:
            continue
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            box = [0, 0, 1000, 1000]
        key = (text, type_)
        if key in seen:
            continue
        seen.add(key)
        x1, y1, x2, y2 = (float(v) for v in box)
        hint = (
            round(x1 * width / 1000),
            round(y1 * height / 1000),
            round(x2 * width / 1000),
            round(y2 * height / 1000),
        )
        owner = str(item.get("owner") or "document").strip().lower() or "document"
        values.append(Value(text, str(type_), owner, hint))
    return values


def split_compound(v: Value) -> list[Value]:
    """An identifier line that holds dates or times ("48271 0312 12.07.2026 19:10") becomes its parts,
    so each part is located and replaced by its own rule (dates shift with the page)."""
    tokens = v.text.split()
    if v.type != "id" or len(tokens) < 2 or not any(DATE.fullmatch(t) or TIME.fullmatch(t) for t in tokens):
        return [v]
    parts = []
    for t in tokens:
        type_ = "date" if DATE.fullmatch(t) else "time" if TIME.fullmatch(t) else "id"
        if type_ != "id" or sum(c.isdigit() for c in t) >= 3:
            parts.append(Value(t, type_, v.owner, v.hint))
    return parts


def _not_personal(v: Value) -> bool:
    """Amounts, and a year alone, identify no one; they are never replaced."""
    return (v.type in ("id", "card") and is_amount(v.text)) or (
        v.type == "date" and re.fullmatch(r"(19|20)\d{2}", v.text) is not None
    )


def normalise(values: list[Value]) -> list[Value]:
    """Compound values split, amounts and bare years dropped, and every (text, type) once."""
    out: list[Value] = []
    seen: set[tuple[str, str]] = set()
    for v in (part for value in values for part in split_compound(value)):
        if (v.text, v.type) not in seen and not _not_personal(v):
            seen.add((v.text, v.type))
            out.append(v)
    return out


def find_values(scan: Image.Image, ocr_text: str) -> list[Value]:
    """Two passes: the image alone, then the image with the OCR text, for what the first pass missed."""
    prompt = PROMPT.format(types=", ".join(TYPES))
    first = parse(vl.parse_objects(vl.chat([vl.image_part(scan), vl.text_part(prompt)], max_tokens=4096)), *scan.size)
    found = "\n".join(f"- {v.type}: {v.text}" for v in first) or "(none)"
    review = REVIEW.format(found=found, ocr=ocr_text)
    second = vl.parse_objects(
        vl.chat([vl.image_part(scan), vl.text_part(prompt), vl.text_part(review)], max_tokens=4096)
    )
    return normalise(first + parse(second, *scan.size))
