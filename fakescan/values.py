"""Invent replacement values that keep the original's format.

All names, streets, and numbers are invented. Postal codes match their city so
an address stays plausible. E-mails always use the reserved example.com domain.
"""
import random
import re

FIRST = ["Jonas", "Mira", "Selin", "Tobias", "Lena", "Arda", "Clara", "Noah", "Ida", "Emil", "Nora", "Felix"]
LAST = ["Brandt", "Okafor", "Aydin", "Kessler", "Vogt", "Lindqvist", "Hahn", "Moreau", "Petrović", "Sauer"]
STREETS = ["Hafenstraße", "Lindenstraße", "Gartenweg", "Am Mühlbach", "Birkenallee", "Kirchplatz", "Uferweg"]
CITIES = [("20457", "Hamburg"), ("80331", "München"), ("50667", "Köln"), ("01067", "Dresden"),
          ("04109", "Leipzig"), ("28195", "Bremen"), ("90402", "Nürnberg")]


class Person:
    def __init__(self, rng: random.Random):
        self.first, self.last = rng.choice(FIRST), rng.choice(LAST)
        self.street = f"{rng.choice(STREETS)} {rng.randint(1, 98)}"
        self.postal, self.city = rng.choice(CITIES)
        self.date_shift = rng.randint(20, 80)  # days, the same for every date on the page


def match_case(new: str, old: str) -> str:
    letters = [c for c in old if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return new.upper()
    return new


def ascii_mail(s: str) -> str:
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ć": "c", "ğ": "g", "ş": "s"})
    return s.lower().translate(table)


def same_shape_digits(old: str, rng: random.Random) -> str:
    """Replace every digit, keep separators, length, and a nonzero first digit."""
    out = []
    first = True
    for c in old:
        if c.isdigit():
            out.append(str(rng.randint(1 if first else 0, 9)))
            first = False
        else:
            out.append(c)
    return "".join(out)


def shift_dates(text: str, days: int) -> str:
    import datetime as dt

    def repl(m):
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            new = dt.date(y, mth, d) + dt.timedelta(days=days)
        except ValueError:
            return m.group(0)
        return f"{new.day:02d}.{new.month:02d}.{new.year}"

    return re.sub(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", repl, text)


def replace(field: str, text: str, person: Person, rng: random.Random) -> str:
    """Return the new text for a whole line, changing only the value part."""
    if field == "person_name":
        old_tokens = text.split()
        prefix = [t for t in old_tokens if t.upper() in ("HERR", "FRAU", "HERRN", "MR", "MRS")]
        return " ".join(prefix + [match_case(f"{person.first} {person.last}", text)])
    if field == "street":
        return match_case(person.street, text)
    if field == "postal_city":
        return match_case(f"{person.postal} {person.city}", text)
    if field == "email":
        return match_case(f"{ascii_mail(person.first)}.{ascii_mail(person.last)}@example.com", text)
    if field == "date":
        return shift_dates(text, person.date_shift)
    # Numbers: keep any label such as "Kd-Nr.:" and change only the digits after it.
    m = re.match(r"^(.*?[:#]\s*)?(.*)$", text)
    label, value = (m.group(1) or ""), m.group(2)
    return label + same_shape_digits(value, rng)
