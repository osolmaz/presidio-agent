"""Check that no original PII value survives on a finished page.

The whole page is read again, and every old span value is searched for: the
whole value and each significant piece of it (words of 4+ letters, digit runs of
4+). A piece that also appears in the page's non-PII text (labels, the vendor's
own address) is not unique to the person, so it is not counted. No word lists.
"""
import re

from . import vl

PLACE_TYPES = {"city", "street"}


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-ZÄÖÜß]", "", s.upper())


def pieces(old_value: str):
    """The parts of an old value that would identify it if they reappeared."""
    out = {norm(old_value)}
    out.update(norm(t) for t in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", old_value))
    out.update(re.findall(r"\d{4,}", re.sub(r"[.\- ]", "", old_value)))
    return {p for p in out if len(p) >= 4}


def read_page(img) -> str:
    return vl.chat([{"type": "image_url", "image_url": {"url": vl._data_url(img)}},
                    {"type": "text", "text": "Read all the text on this page, top to bottom, exactly as printed. "
                                             "Answer with only the text."}], max_tokens=4096)


def check(img, old_values, context: str, new_values=()):
    """old_values: [(type, old text)]. Returns (page_text, leaks): [{"type", "pieces"}].

    Pieces that also occur in the non-PII context or in the new values (for example the
    reserved example.com domain) are not unique to the old data, so they are not leaks.
    """
    page = norm(read_page(img))
    shared = norm(context)
    new_text = "|".join(norm(v) for v in new_values)
    leaks = []
    for type_, old in old_values:
        # A piece that the new values also contain (the example.com domain, a year) is
        # there by design. A city or street can also be the shop's own; a name, e-mail,
        # or number cannot, so only place names are excused by the page's other text.
        excusable = type_ in PLACE_TYPES
        found = sorted(p for p in pieces(old)
                       if p in page and p not in new_text and not (excusable and p in shared))
        if found:
            leaks.append({"type": type_, "pieces": found})
    return page, leaks
