---
date: 2026-10-04
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Span-based PII replacement
tags: [synthero, pii, design, plan]
---

# Span-based PII replacement

## Problem

synthero labelled whole lines with one field type, and code then guessed which
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

## Positions from OCR (added 2026-10-05)

The model's line coordinates were the weak point: smaller models placed some
boxes one or more lines off, so edits landed on the wrong line or were skipped.
Positions now come from Tesseract 5.3.4 (`deu+eng`), which gives every word an
exact box. Bonsai gets the image and the OCR lines and only marks which pieces
are PII. Tesseract reads cell borders and specks as `|`, `]`, and `\`: words are
split at `|` and these characters are never drawn. A span is edited only when
every word it covers has an OCR box with ink in it that is not taller than about
1.6 lines; other spans stay unedited and the leak check flags them.

## Results

On page 2 of `drucker.pdf`, with Ternary Bonsai 2 27B PQ2_0 through the Llama
app on khazaddum (14.7 GB of the 16 GB GPU), about 100 s per run of two copies:

- Positions: Bonsai alone located 10 of 12 spans; with Tesseract boxes, 14 of 15.
- The `Verkäufer:` label stays, and the salesperson, manager, and customer get
  different invented names.
- The header row (number, dates) is clean: values in their cells, borders intact.
- The leak check works as a gate: it flags spans that could not be edited (the
  contract number, whose OCR box spans two lines), and it no longer excuses a
  surviving name or number because the same text appears elsewhere on the page.

Open problems:

1. **Detection recall.** In the three OCR-based runs, Bonsai did not mark the
   customer's name `LEON HARTMANN`, although it marked the e-mail that contains
   it. A missed span is not edited.
2. **Merged OCR boxes.** On the customer block, Tesseract's box for the street
   line reaches into the name line above. The new street is drawn over the
   bottom of the name, and the old street's row stays empty. The height check
   compares a word with its own line, so it misses a line whose words are all
   too tall; it should compare with the page's typical line height.
3. **Read-back** is 6 of 10 lines. Part of it is OCR noise in the expected text.
4. **Over-marking.** Bonsai also marks the insurer's address and the shop's own
   IBAN. Harmless, but `same_shape` then turns the IBAN's `DE` into random letters.
5. **Barcodes** still encode the old values; the leak check reads only text.

Next: compare box heights with the page's typical line height; run detection
twice (two prompts or two models) and take the union of spans; keep IBAN and
card prefixes; then redraw or blank barcodes.
