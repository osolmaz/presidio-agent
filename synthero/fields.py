"""Find the personal data on a page as exact spans, with their type and owner."""
import json
import re

from . import vl

TYPES = ["person", "street", "city", "email", "phone", "date", "time", "id", "card", "iban"]

PROMPT = """The image is a scanned invoice or receipt. Below are its text lines as read by OCR,
numbered. Use the image to understand the document; copy text only from the OCR lines.
Find every piece of personal data and every transaction identifier that must change in a
new synthetic copy: people's names, the customer's address, e-mail, phone, customer, contract,
order, receipt, trace, terminal, and approval numbers, card numbers and IBANs, dates and times.
Do not mark the business's own name, address, phone, tax numbers, or bank details, and do not
mark labels such as "Datum:" or "Kd-Nr.:".

For each piece, give:
- "line": the line number,
- "text": the exact characters of the piece, copied from the OCR line: only the value itself,
  without labels and without titles such as "Herr" or "Dr.",
- "type": one of {types},
- "owner": whose data it is, as a short word: one word per person ("customer", "salesperson",
  "manager", ...), or "payment" or "document" for card and document data. Use the same owner
  for all pieces about the same person or thing, and different owners for different people.

Answer with only a JSON array.

{listing}"""


def find_spans(lines, image=None):
    """Return the validated spans: [{"line", "start", "end", "text", "type", "owner"}].

    `lines` come from OCR; with `image`, the model also sees the scan for context.
    """
    listing = "\n".join(f"{i}: {ln['text']}" for i, ln in enumerate(lines))
    content = [{"type": "text", "text": PROMPT.format(types=", ".join(TYPES), listing=listing)}]
    if image is not None:
        content.insert(0, {"type": "image_url", "image_url": {"url": vl._data_url(image)}})
    answer = vl.parse_json(vl.chat(content, max_tokens=2048))
    spans = []
    for s in answer if isinstance(answer, list) else []:
        try:
            i, text = int(s["line"]), str(s["text"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= i < len(lines)) or not text or s.get("type") not in TYPES:
            continue
        start = lines[i]["text"].find(text)
        if start < 0:  # not an exact substring: never replace on a guess
            continue
        spans.append({"line": i, "start": start, "end": start + len(text), "text": text,
                      "type": s["type"], "owner": str(s.get("owner") or "document").lower()})
    return add_missed_dates(lines, spans)


def add_missed_dates(lines, spans):
    """Safety net: a full date that no span covers becomes a date span."""
    for i, ln in enumerate(lines):
        for m in re.finditer(r"\b\d{2}\.\d{2}\.\d{4}\b", ln["text"]):
            covered = any(s["line"] == i and s["start"] < m.end() and m.start() < s["end"] for s in spans)
            if not covered:
                spans.append({"line": i, "start": m.start(), "end": m.end(), "text": m.group(0),
                              "type": "date", "owner": "document"})
    return spans


if __name__ == "__main__":
    import sys
    print(json.dumps(find_spans(json.load(open(sys.argv[1]))), indent=1, ensure_ascii=False))
