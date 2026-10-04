"""Find a value inside OCR lines, tolerating OCR noise. Pure functions, no model."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


def norm(s: str) -> str:
    """Upper case, letters and digits only: what survives OCR noise."""
    return re.sub(r"[^0-9A-ZÄÖÜß]", "", s.upper())


@dataclass(frozen=True)
class Match:
    line: int
    first_word: int
    last_word: int
    score: float


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def same_digits(value: str, candidate: str) -> bool:
    """A value with digits must keep them exactly: a different postcode is a different address."""
    return digits(value) == digits(candidate) if digits(value) else True


def close_digits(value: str, candidate: str, min_score: float = 0.75) -> bool:
    """Digits that differ by a misread or two, as when one reader got a digit wrong."""
    dv, dc = digits(value), digits(candidate)
    if not dv:
        return True
    return bool(dc) and difflib.SequenceMatcher(None, dv, dc).ratio() >= min_score


def similarity(a: str, b: str) -> float:
    """0..1 similarity of two strings after normalisation."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _digits_ok(value: str, run: str, strict: bool) -> bool:
    return same_digits(value, run) if strict else close_digits(value, run)


def find_value(value: str, lines: list[list[str]], min_score: float = 0.85, strict: bool = True) -> Match | None:
    """Best run of consecutive words, on one line, that spells `value`.

    `lines` is a list of lines, each a list of OCR words. Runs up to two words longer
    than the value are tried, because OCR splits words ("260712" -> "2607 12").
    Returns None when nothing reaches `min_score`. With `strict`, the digits must be
    equal; otherwise close (one reader may have misread a digit).
    """
    target_words = max(1, len(value.split()))
    best: Match | None = None
    for li, words in enumerate(lines):
        for a in range(len(words)):
            for b in range(a, min(len(words), a + target_words + 2)):
                run = " ".join(words[a : b + 1])
                score = similarity(value, run)
                if score >= min_score and _digits_ok(value, run, strict) and (best is None or score > best.score):
                    best = Match(li, a, b, score)
    return best


def find_all(value: str, lines: list[list[str]], min_score: float = 0.85, strict: bool = True) -> list[Match]:
    """Every place a value appears: per line, the best non-overlapping runs that reach `min_score`."""
    target_words = max(1, len(value.split()))
    found: list[Match] = []
    for li, words in enumerate(lines):
        runs = []
        for a in range(len(words)):
            for b in range(a, min(len(words), a + target_words + 2)):
                run = " ".join(words[a : b + 1])
                score = similarity(value, run)
                if score >= min_score and _digits_ok(value, run, strict):
                    runs.append(Match(li, a, b, score))
        taken: set[int] = set()
        for m in sorted(runs, key=lambda r: -r.score):
            span = set(range(m.first_word, m.last_word + 1))
            if not span & taken:
                found.append(m)
                taken |= span
    return found


def contains(reading: str, value: str, min_score: float = 0.85) -> bool:
    """True when `value` appears in `reading`, allowing small OCR or model slips."""
    nr, nv = norm(reading), norm(value)
    if not nv:
        return False
    if nv in nr:
        return True
    if len(nr) < len(nv):
        return similarity(nr, nv) >= min_score
    best = max(difflib.SequenceMatcher(None, nr[i : i + len(nv)], nv).ratio() for i in range(len(nr) - len(nv) + 1))
    return best >= min_score
