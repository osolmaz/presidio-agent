"""Shift every date in a text by a number of days, keeping how each date is written.

Handled forms, in German and English: 12.07.2026, 12.07.26, 13.07., 2026-07-12,
12/07/2026, 1. Juli 2026, 01 Jul 2026, Jul 01 2026, July 1, 2026, and Juli 2026
(a month alone moves by whole months). Padding, month-name style and case, and
two- or four-digit years are kept. One pattern scans the text once, so no date is
shifted twice.
"""

from __future__ import annotations

import datetime as dt
import re

MONTH_NAMES = [
    ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
     "Dezember"],
    ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
     "December"],
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
]  # fmt: skip
_LOOKUP = {name.lower(): (style, i + 1) for style, names in enumerate(MONTH_NAMES) for i, name in enumerate(names)}
_LOOKUP.update({"maerz": (0, 3), "sept": (3, 9)})
_MONTH = "|".join(sorted((re.escape(n) for n in _LOOKUP), key=len, reverse=True))
YEAR_FOR_DAY_MONTH = 2000  # a leap year, so 29.02. without a year stays valid

PATTERN = re.compile(
    rf"(?P<iso>(?P<iy>\d{{4}})-(?P<im>\d{{2}})-(?P<id>\d{{2}}))"
    rf"|(?P<dot>(?<![\d.])(?P<dd>\d{{1,2}})\.(?P<dm>\d{{1,2}})\.(?P<dy>\d{{4}}|\d{{2}}(?!\d))?(?![\d,]))"
    rf"|(?P<slash>(?<!\d)(?P<sd>\d{{1,2}})/(?P<sm>\d{{1,2}})/(?P<sy>\d{{4}}|\d{{2}})(?!\d))"
    rf"|(?P<dmy>(?<!\d)(?P<nd>\d{{1,2}})(?P<ndot>\.?)\s+(?P<nm>{_MONTH})(?P<nmdot>\.?)(?:\s+(?P<ny>\d{{4}}))?)"
    rf"|(?P<mdy>(?P<md>{_MONTH})(?P<mddot>\.?)\s+(?P<mdd>\d{{1,2}})(?P<comma>,?)\s+(?P<mdy_y>\d{{4}}))"
    rf"|(?P<my>(?P<mo>{_MONTH})\s+(?P<moy>\d{{4}}))",
    re.IGNORECASE,
)


def _pad(n: int, like: str) -> str:
    """Two digits when the original had two ("07", "12"), else as few as needed ("1")."""
    return f"{n:02d}" if len(like) == 2 else str(n)


def _year(y: int, like: str | None) -> str:
    return "" if like is None else (f"{y % 100:02d}" if len(like) == 2 else str(y))


def _full_year(text: str | None) -> int:
    if text is None:
        return YEAR_FOR_DAY_MONTH
    return int(text) + (2000 if len(text) == 2 else 0)


def _name(month: int, like: str) -> str:
    style, _ = _LOOKUP[like.lower()]
    name = MONTH_NAMES[style][month - 1]
    return name.upper() if like.isupper() and len(like) > 1 else name.lower() if like.islower() else name


def _shift(m: re.Match[str], days: int) -> str:  # noqa: PLR0911  one return per written form
    g = m.groupdict()
    try:
        if g["iso"]:
            d = dt.date(int(g["iy"]), int(g["im"]), int(g["id"])) + dt.timedelta(days)
            return d.isoformat()
        if g["dot"]:
            d = dt.date(_full_year(g["dy"]), int(g["dm"]), int(g["dd"])) + dt.timedelta(days)
            return f"{_pad(d.day, g['dd'])}.{_pad(d.month, g['dm'])}.{_year(d.year, g['dy'])}"
        if g["slash"]:
            d = dt.date(_full_year(g["sy"]), int(g["sm"]), int(g["sd"])) + dt.timedelta(days)
            return f"{_pad(d.day, g['sd'])}/{_pad(d.month, g['sm'])}/{_year(d.year, g['sy'])}"
        if g["dmy"]:
            d = dt.date(_full_year(g["ny"]), _LOOKUP[g["nm"].lower()][1], int(g["nd"])) + dt.timedelta(days)
            year = f" {_year(d.year, g['ny'])}" if g["ny"] else ""
            return f"{_pad(d.day, g['nd'])}{g['ndot']} {_name(d.month, g['nm'])}{g['nmdot']}{year}"
        if g["mdy"]:
            d = dt.date(int(g["mdy_y"]), _LOOKUP[g["md"].lower()][1], int(g["mdd"])) + dt.timedelta(days)
            return f"{_name(d.month, g['md'])}{g['mddot']} {_pad(d.day, g['mdd'])}{g['comma']} {d.year}"
        months = max(1, round(days / 30.44)) if days > 0 else min(-1, round(days / 30.44))
        index = int(g["moy"]) * 12 + _LOOKUP[g["mo"].lower()][1] - 1 + months
        return f"{_name(index % 12 + 1, g['mo'])} {index // 12}"
    except ValueError:  # not a real date, such as 31.02.
        return m.group(0)


def shift(text: str, days: int) -> str:
    """Every date in `text` moved by `days`."""
    return PATTERN.sub(lambda m: _shift(m, days), text)
