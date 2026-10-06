"""Candidate personal values proposed by Presidio's rule-based recognizers.

Presidio reads a page's text and flags strings that look like personal data. A flag
is only a candidate: the vision model checks each one against the image, and the agent
decides about any candidate the model did not accept. Nothing is edited on a flag alone.
Pure functions; the Presidio engine itself is built in `recognizers.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from presidio_agent.match import norm

# Presidio entities worth checking on invoices and receipts. Places, organisations,
# web sites, postal codes, and VAT IDs are left out: on these documents they are the
# business's own details or name-recognizer noise far more often than personal data.
ENTITIES = frozenset(
    {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "DATE_TIME",
        "DE_TAX_ID",
        "DE_ID_CARD",
        "DE_PASSPORT",
        "DE_HEALTH_INSURANCE",
        "DE_SOCIAL_SECURITY",
    }
)
# The value type a candidate gets when the agent accepts it; the agent may choose another.
VALUE_TYPE = {
    "PERSON": "person",
    "EMAIL_ADDRESS": "email",
    "PHONE_NUMBER": "phone",
    "IBAN_CODE": "iban",
    "CREDIT_CARD": "card",
    "DATE_TIME": "date",
}
MIN_SCORE = 0.4
MIN_CHARS = 3  # letters and digits; shorter flags are fragments


@dataclass(frozen=True)
class Candidate:
    text: str
    entity: str  # Presidio's entity type, such as PERSON or IBAN_CODE
    score: float


# Presidio's results as plain tuples: (start, end, entity type, score) in the analysed text.
Span = tuple[int, int, str, float]
Analyze = Callable[[str], list[Span]]


def from_spans(text: str, spans: Iterable[Span]) -> list[Candidate]:
    """The flags worth checking, each (text, entity) once, in the order Presidio found them."""
    out: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for start, end, entity, score in spans:
        flagged = " ".join(text[start:end].split())
        if entity not in ENTITIES or score < MIN_SCORE or len(norm(flagged)) < MIN_CHARS:
            continue
        if (flagged, entity) not in seen:
            seen.add((flagged, entity))
            out.append(Candidate(flagged, entity, round(score, 2)))
    return out


def find(text: str, analyze: Analyze | None) -> list[Candidate]:
    """Presidio's candidates for one page's text, or none when Presidio is not installed."""
    return from_spans(text, analyze(text)) if analyze is not None and text.strip() else []


def value_type(entity: str) -> str:
    """The value type for a Presidio entity: German ID numbers and anything unmapped are ids."""
    return VALUE_TYPE.get(entity, "id")


def covered(candidate: str, value: str) -> bool:
    """A candidate is covered when it and a found value contain each other, ignoring case and punctuation."""
    c, v = norm(candidate), norm(value)
    return bool(c and v) and (c in v or v in c)


def unconfirmed(candidates: Iterable[Candidate], values: Iterable[str]) -> list[Candidate]:
    """The candidates that no found value covers: what the agent still has to decide about."""
    found = list(values)
    return [c for c in candidates if not any(covered(c.text, v) for v in found)]
