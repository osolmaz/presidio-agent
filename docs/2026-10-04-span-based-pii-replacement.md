---
date: 2026-10-04
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Span-based PII replacement
tags: [fake-scan, pii, design, plan]
---

# Span-based PII replacement

## Problem

fake-scan labelled whole lines with one field type, and code then guessed which
part of the line was the value. The guesses were hard-coded: a list of titles
(`HERR`, `FRAU`) to keep in front of a name, a `label:` pattern for numbers, and
a list of common words that the leak check ignores. They failed on a line such
as `Verkäufer: KELLER`: the label was not on any list, so the whole line was
replaced, the label disappeared, the salesperson got the customer's new name,
and the case came out wrong because it was matched against the whole line.

## Design

The model finds the PII; code only replaces it.

1. **Spans, not lines.** The labelling call returns, for every line, the exact
   substrings that are personal data or transaction identifiers:
   `{"line": 12, "text": "KELLER", "type": "person", "owner": "staff"}`.
   The business's own name, address, and tax or bank details are not marked.
2. **Validation.** A span whose text is not an exact substring of its line is
   dropped. Nothing is replaced on a guess.
3. **One identity per owner.** Code invents one set of values for each owner
   (`customer`, `staff`, `payment`, and so on), so the same person or card
   gets the same new value everywhere on the page, also inside an e-mail.
4. **Format-preserving values per type.** Names, streets, and cities come from
   invented lists; e-mails use `example.com`; numbers keep their length and
   separators; all dates on the page move by the same number of days; times
   move by the same number of minutes. The case is matched to the span alone.
5. **Substring replacement.** Only the span text changes. Labels and any text
   before or after the value stay as printed, without any rule that knows them.
6. **Word-level redraw.** The renderer redraws only the words that overlap a
   span and keeps every other word's original pixels, also words after the
   value on the same line.
7. **Safety nets.** A full date (`dd.mm.yyyy`) that no span covers becomes a
   date span. The leak check reads the finished page and searches for every old
   span value and its pieces; a piece that also appears in the page's non-PII
   text (for example the vendor's city) is not counted, so no word list is needed.

## Removed

- the `HERR`/`FRAU` title list and the `label:` pattern in `values.py`
- the whole-line field labels in `fields.py`
- the shared-first-words logic in `render.py`
- the common-word list in `leak.py`

## Test

Page 2 of `drucker.pdf` and the till receipt from `gutschein_reiseadapter.pdf`,
two copies each, on Qwen3.8-27B Q6_K. Pass when: the `Verkäufer:` label stays
and the salesperson gets a name different from the customer's; every copy passes
the leak check; and the leak check still flags every field on the original.

## Results

To be filled in after the test.
