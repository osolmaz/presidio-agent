"""Presidio's analyzer, set up for German and English invoices.

Presidio ships its generic recognizers (IBAN, e-mail, phone, card, date) for English
only, so they are registered again for German next to Presidio's German ones and the
German spaCy name recognizer. Building the analyzer loads spaCy, so it happens once,
on first use.
"""

from __future__ import annotations

import functools

from presidio_agent.candidates import Analyze, Span

LANGUAGE = "de"
SPACY_MODEL = "de_core_news_md"


@functools.cache
def analyzer() -> Analyze:
    """Presidio's analyzer as a function from text to spans, built once."""
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry  # noqa: PLC0415 -- loads spaCy on first use
    from presidio_analyzer.nlp_engine import NlpEngineProvider  # noqa: PLC0415 -- loads spaCy on first use
    from presidio_analyzer.predefined_recognizers import (  # noqa: PLC0415 -- loads spaCy on first use
        CreditCardRecognizer,
        DateRecognizer,
        DeHealthInsuranceRecognizer,
        DeIdCardRecognizer,
        DePassportRecognizer,
        DeSocialSecurityRecognizer,
        DeTaxIdRecognizer,
        EmailRecognizer,
        IbanRecognizer,
        PhoneRecognizer,
        SpacyRecognizer,
    )

    nlp = NlpEngineProvider(
        nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": LANGUAGE, "model_name": SPACY_MODEL}]}
    ).create_engine()
    registry = RecognizerRegistry(supported_languages=[LANGUAGE])
    for recognizer in (
        SpacyRecognizer(supported_language=LANGUAGE, supported_entities=["PERSON"]),
        IbanRecognizer(supported_language=LANGUAGE),
        EmailRecognizer(supported_language=LANGUAGE),
        PhoneRecognizer(supported_language=LANGUAGE, supported_regions=("DE", "AT", "CH", "US", "GB", "FR")),
        CreditCardRecognizer(supported_language=LANGUAGE),
        DateRecognizer(supported_language=LANGUAGE),
        DeTaxIdRecognizer(),
        DeIdCardRecognizer(),
        DePassportRecognizer(),
        DeHealthInsuranceRecognizer(),
        DeSocialSecurityRecognizer(),
    ):
        registry.add_recognizer(recognizer)
    engine = AnalyzerEngine(nlp_engine=nlp, registry=registry, supported_languages=[LANGUAGE])

    def analyze(text: str) -> list[Span]:
        return [(r.start, r.end, r.entity_type, r.score) for r in engine.analyze(text=text, language=LANGUAGE)]

    return analyze
