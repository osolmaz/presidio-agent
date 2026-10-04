"""Invent replacement values for PII spans, keeping each span's format.

Every owner (customer, staff, ...) gets its own invented identity, so the same
person or card gets the same new value everywhere on the page. Names, streets,
and numbers are invented; postal codes match their city; e-mails use the
reserved example.com domain. Dates and times on a page all move by one shift.
"""

from __future__ import annotations

import random
import re

from synthero import dates

FIRST = ["Jonas", "Mira", "Selin", "Tobias", "Lena", "Arda", "Clara", "Noah", "Ida", "Emil", "Nora", "Felix"]
LAST = ["Brandt", "Okafor", "Aydin", "Kessler", "Vogt", "Lindqvist", "Hahn", "Moreau", "Petrovic", "Sauer"]
STREETS = ["Hafenstraße", "Lindenstraße", "Gartenweg", "Birkenallee", "Kirchplatz", "Uferweg", "Am Mühlbach"]
CITIES = [
    ("20457", "Hamburg"),
    ("80331", "München"),
    ("50667", "Köln"),
    ("01067", "Dresden"),
    ("04109", "Leipzig"),
    ("28195", "Bremen"),
    ("90402", "Nürnberg"),
]

UMLAUTS: dict[str, str | int | None] = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


class Identity:
    """Invented values for one owner."""

    def __init__(self, rng: random.Random, taken_last: set[str]) -> None:
        self.first = rng.choice(FIRST)
        self.last = rng.choice([n for n in LAST if n not in taken_last] or LAST)
        taken_last.add(self.last)
        self.street = rng.choice(STREETS)
        self.house = str(rng.randint(1, 98))
        self.postal, self.city = rng.choice(CITIES)


class Replacer:
    """Consistent, format-preserving replacements for one synthetic copy."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.identities: dict[str, Identity] = {}
        self.taken_last: set[str] = set()
        # (owner, type, old text) -> new text: a repeated value stays consistent
        self.seen: dict[tuple[str, str, str], str] = {}
        self.day_shift = rng.randint(20, 80)
        self.minute_shift = rng.randint(-180, 180)

    def identity(self, owner: str) -> Identity:
        if owner not in self.identities:
            self.identities[owner] = Identity(self.rng, self.taken_last)
        return self.identities[owner]

    def replace(self, text: str, type_: str, owner: str) -> str:
        key = (owner, type_, text)
        if key not in self.seen:
            self.seen[key] = match_case(self._new(text, type_, owner), text)
        return self.seen[key]

    def _new(self, text: str, type_: str, owner: str) -> str:
        p = self.identity(owner)
        if type_ in ("date", "time"):
            return dates.shift(text, self.day_shift) if type_ == "date" else shift_times(text, self.minute_shift)
        has_digits = bool(re.search(r"\d", text))
        made = {
            # A surname alone, as "KELLER", stays a surname.
            "person": p.last if len(text.split()) == 1 else f"{p.first} {p.last}",
            "street": f"{p.street} {p.house}" if has_digits else p.street,
            "city": f"{p.postal} {p.city}" if re.search(r"\d{5}", text) else p.city,
            "email": f"{ascii_mail(p.first)}.{ascii_mail(p.last)}@example.com",
        }
        if type_ == "iban":
            return iban_like(text, self.rng)
        if type_ == "card":
            return card_like(text, self.rng)
        return made.get(type_) or same_shape(text, self.rng)  # id, phone


def match_case(new: str, old: str) -> str:
    letters = [c for c in old if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return new.upper()
    if letters and all(c.islower() for c in letters):
        return new.lower()
    return new


def ascii_mail(s: str) -> str:
    return s.lower().translate(str.maketrans(UMLAUTS))


def same_shape(old: str, rng: random.Random) -> str:
    """New digits and letters in the same places; separators and masks (****, XXXX, ####) stay."""
    masked = {i for m in re.finditer(r"[Xx]{2,}", old) for i in range(m.start(), m.end())}
    out, first = [], True
    for i, c in enumerate(old):
        if i in masked:
            out.append(c)
        elif c.isdigit():
            out.append(str(rng.randint(1 if first else 0, 9)))
            first = False
        elif c.isalpha() and c.isascii():
            out.append(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") if c.isupper() else rng.choice("abcdefghjkmnprstuvwxyz"))
        else:
            out.append(c)
    return "".join(out)


def iban_check(country: str, bban: str) -> str:
    """The two IBAN check digits (ISO 13616, mod 97) for a country code and account part."""
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{98 - int(digits) % 97:02d}"


def iban_like(old: str, rng: random.Random) -> str:
    """A valid IBAN in the old one's layout: same country, length, and spacing; new account digits."""
    compact = re.sub(r"\s", "", old)
    m = re.search(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", compact)
    if m is None:
        return same_shape(old, rng)
    iban = m.group(0)
    country = iban[:2]
    bban = "".join(str(rng.randint(0, 9)) if c.isdigit() else c for c in iban[4:])
    new = country + iban_check(country, bban) + bban
    out, chars = [], iter(new)
    for c in old[old.find(iban[0]) :]:  # keep the old spacing
        out.append(c if c.isspace() else next(chars, ""))
    return old[: old.find(iban[0])] + "".join(out) + "".join(chars)


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = int(c) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def card_like(old: str, rng: random.Random) -> str:
    """New card digits in the same layout; a full card number keeps a valid Luhn check digit.

    Masked numbers ("************7318") keep their stars and get new visible digits.
    """
    new = same_shape(old, rng)
    digits = re.sub(r"\D", "", new)
    if len(digits) < 12 or re.search(r"[*#•]|[Xx]{2,}", old):  # masked: the check digit is unknown
        return new
    body = digits[:-1]
    check = next(str(c) for c in range(10) if luhn_ok(body + str(c)))
    last = max(i for i, c in enumerate(new) if c.isdigit())
    return new[:last] + check + new[last + 1 :]


def shift_times(text: str, minutes: int) -> str:
    def repl(m: re.Match[str]) -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        sec = m.group(3) or ""
        t = (h * 60 + mi + minutes) % (24 * 60)
        return f"{t // 60:02d}:{t % 60:02d}{sec}"

    return re.sub(r"\b(\d{1,2}):(\d{2})(:\d{2})?\b", repl, text)
