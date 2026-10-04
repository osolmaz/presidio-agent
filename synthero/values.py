"""Invent replacement values for PII spans, keeping each span's format.

Every owner (customer, staff, ...) gets its own invented identity, so the same
person or card gets the same new value everywhere on the page. Names, streets,
and numbers are invented; postal codes match their city; e-mails use the
reserved example.com domain. Dates and times on a page all move by one shift.
"""
import datetime as dt
import random
import re

FIRST = ["Jonas", "Mira", "Selin", "Tobias", "Lena", "Arda", "Clara", "Noah", "Ida", "Emil", "Nora", "Felix"]
LAST = ["Brandt", "Okafor", "Aydin", "Kessler", "Vogt", "Lindqvist", "Hahn", "Moreau", "Petrovic", "Sauer"]
STREETS = ["Hafenstraße", "Lindenstraße", "Gartenweg", "Birkenallee", "Kirchplatz", "Uferweg", "Am Mühlbach"]
CITIES = [("20457", "Hamburg"), ("80331", "München"), ("50667", "Köln"), ("01067", "Dresden"),
          ("04109", "Leipzig"), ("28195", "Bremen"), ("90402", "Nürnberg")]


class Identity:
    """Invented values for one owner."""

    def __init__(self, rng: random.Random, taken_last: set):
        self.first = rng.choice(FIRST)
        self.last = rng.choice([n for n in LAST if n not in taken_last] or LAST)
        taken_last.add(self.last)
        self.street = rng.choice(STREETS)
        self.house = str(rng.randint(1, 98))
        self.postal, self.city = rng.choice(CITIES)


class Replacer:
    """Consistent, format-preserving replacements for one synthetic copy."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.identities = {}
        self.taken_last = set()
        self.seen = {}  # (owner, type, old text) -> new text: a repeated value stays consistent
        self.day_shift = rng.randint(20, 80)
        self.minute_shift = rng.randint(-180, 180)

    def identity(self, owner):
        if owner not in self.identities:
            self.identities[owner] = Identity(self.rng, self.taken_last)
        return self.identities[owner]

    def replace(self, text: str, type_: str, owner: str) -> str:
        key = (owner, type_, text)
        if key not in self.seen:
            self.seen[key] = match_case(self._new(text, type_, owner), text)
        return self.seen[key]

    def _new(self, text, type_, owner):
        p = self.identity(owner)
        if type_ == "person":
            words = text.split()
            if len(words) == 1:  # a surname alone, as "KELLER"
                return p.last
            return f"{p.first} {p.last}"
        if type_ == "street":
            return f"{p.street} {p.house}" if re.search(r"\d", text) else p.street
        if type_ == "city":
            return f"{p.postal} {p.city}" if re.search(r"\d{5}", text) else p.city
        if type_ == "email":
            return f"{ascii_mail(p.first)}.{ascii_mail(p.last)}@example.com"
        if type_ == "date":
            return shift_dates(text, self.day_shift)
        if type_ == "time":
            return shift_times(text, self.minute_shift)
        return same_shape(text, self.rng)  # id, card, iban, phone


def match_case(new: str, old: str) -> str:
    letters = [c for c in old if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return new.upper()
    if letters and all(c.islower() for c in letters):
        return new.lower()
    return new


def ascii_mail(s: str) -> str:
    return s.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))


def same_shape(old: str, rng: random.Random) -> str:
    """New digits and letters in the same places; separators and masking stars stay."""
    out, first = [], True
    for c in old:
        if c.isdigit():
            out.append(str(rng.randint(1 if first else 0, 9)))
            first = False
        elif c.isalpha() and c.isascii():
            out.append(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") if c.isupper() else rng.choice("abcdefghjkmnprstuvwxyz"))
        else:
            out.append(c)
    return "".join(out)


def shift_dates(text: str, days: int) -> str:
    def full(m):
        try:
            d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) + dt.timedelta(days=days)
        except ValueError:
            return m.group(0)
        return f"{d.day:02d}.{d.month:02d}.{d.year}"

    def short(m):  # "13.07." without a year
        try:
            d = dt.date(2026, int(m.group(2)), int(m.group(1))) + dt.timedelta(days=days)
        except ValueError:
            return m.group(0)
        return f"{d.day:02d}.{d.month:02d}."

    text = re.sub(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", full, text)
    return re.sub(r"\b(\d{2})\.(\d{2})\.(?!\d)", short, text)


def shift_times(text: str, minutes: int) -> str:
    def repl(m):
        h, mi = int(m.group(1)), int(m.group(2))
        sec = m.group(3) or ""
        t = (h * 60 + mi + minutes) % (24 * 60)
        return f"{t // 60:02d}:{t % 60:02d}{sec}"

    return re.sub(r"\b(\d{1,2}):(\d{2})(:\d{2})?\b", repl, text)
