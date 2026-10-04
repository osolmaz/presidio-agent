"""Check that no original value survives on a finished page.

The whole page is read again, and every old value is searched for: the whole
value and each significant piece of it (words of 4+ letters, digit runs of 4+).
Labels such as "Datum:" are not searched, because they are not personal data.
"""
import re

from . import vl

COMMON = {"STRASSE", "STRAßE", "ALLEE", "BERLIN", "EXAMPLE", "HERR", "FRAU", "DATUM", "UHR"}


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-ZÄÖÜß]", "", s.upper())


def pieces(old_value: str):
    """The parts of an old value that would identify it if they reappeared."""
    out = {norm(old_value)}
    for tok in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", old_value):
        if tok.upper() not in COMMON:
            out.add(norm(tok))
    out.update(re.findall(r"\d{4,}", old_value.replace(".", "").replace("-", "").replace(" ", "")))
    return {p for p in out if len(p) >= 4}


def read_page(img) -> str:
    return vl.chat([{"type": "image_url", "image_url": {"url": vl._data_url(img)}},
                    {"type": "text", "text": "Read all the text on this page, top to bottom, exactly as printed. "
                                             "Answer with only the text."}], max_tokens=4096)


def check(img, private_changes):
    """Return (page_text, leaks): one leak per field whose old value still appears."""
    page = read_page(img)
    flat = norm(page)
    leaks = []
    for c in private_changes:
        found = sorted(p for p in pieces(c["old_value"]) if p in flat)
        if found:
            leaks.append({"field": c["field"], "pieces": found})
    return page, leaks
