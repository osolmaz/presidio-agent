"""Check that no original personal value survives on a finished page.

The whole page is read again, and every old value is searched for: the whole
value and each significant piece of it (words of 4+ letters, digit runs of 4+).
No word lists. Pure: the reading of the page is passed in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypedDict

PLACE_TYPES = {"city", "street"}


class Leak(TypedDict):
    type: str
    pieces: list[str]


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-ZÄÖÜß]", "", s.upper())


NUMBER_TYPES = {"id", "card", "iban", "phone", "date", "time"}


def pieces(old_value: str, type_: str = "person") -> set[str]:
    """The parts of an old value that would identify it if they reappeared.

    Names and places are identified by their words, numbers by their digit runs (a
    unit such as "Bits" next to a number identifies nothing), and an e-mail by its local
    part: the domain can be the business's own, and a name in it is checked as the name.
    """
    if type_ == "email":
        old_value = old_value.partition("@")[0]
    out = {norm(old_value)}
    if type_ not in NUMBER_TYPES:
        out.update(norm(t) for t in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", old_value))
    out.update(re.findall(r"\d{4,}", re.sub(r"[.\- ]", "", old_value)))
    return {p for p in out if len(p) >= 4}


LONG_DIGITS = 6  # a digit piece this long is unlikely to occur inside another number by chance


def digit_runs(text: str) -> set[str]:
    """The numbers on a page: digit runs within each word ("12.07.2026" is one run), and the
    joins of neighbouring all-digit words ("00 075 00", IBAN blocks), never across a letter."""
    runs: set[str] = set()
    group: list[str] = []
    for word in text.split():
        compact = re.sub(r"[.\-/:]", "", word)
        runs.update(re.findall(r"\d+", compact))
        if compact.isdigit():
            group.append(compact)
            runs.add("".join(group))
            runs.update("".join(group[i:]) for i in range(len(group)))
        else:
            group = []
    return runs


def _on_page(piece: str, page: str, runs: set[str]) -> bool:
    """A word piece anywhere in the page; a digit piece as a whole number, or inside one when long.

    Matching digits across the whole normalised page would join neighbouring numbers
    ("2026 07" holds "2607") and report leaks that are not there.
    """
    if not piece.isdigit():
        return piece in page
    return piece in runs or (len(piece) >= LONG_DIGITS and any(piece in r for r in runs))


def check(
    page_text: str, old_values: Iterable[tuple[str, str]], context: str, new_values: Iterable[str] = ()
) -> list[Leak]:
    """Old values ([(type, text)]) whose pieces are still on the page.

    A piece that the new values also contain (the example.com domain, a year) is there
    by design. A city or street can also be the business's own, so place pieces that
    occur in `context` (the page's text without the personal values) are excused; a
    name, e-mail, or number never is.
    """
    page = norm(page_text)
    runs = digit_runs(page_text)
    shared = norm(context)
    new_text = "|".join(norm(v) for v in new_values)
    leaks: list[Leak] = []
    for type_, old in old_values:
        excusable = type_ in PLACE_TYPES
        found = sorted(
            p
            for p in pieces(old, type_)
            if _on_page(p, page, runs) and p not in new_text and not (excusable and p in shared)
        )
        if found:
            leaks.append({"type": type_, "pieces": found})
    return leaks
