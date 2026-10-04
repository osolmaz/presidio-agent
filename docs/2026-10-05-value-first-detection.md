---
date: 2026-10-05
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Value-first PII detection with OCR positions
tags: [synthero, pii, ocr, design, plan]
---

# Value-first PII detection with OCR positions

## Current state

synthero (formerly fake-scan) makes synthetic copies of scanned invoices and
receipts. Tesseract gives word positions, Bonsai marks PII spans in the OCR
text, code invents consistent values, the renderer redraws only the changed
words, and the leak check fails any copy where an original value survives.
See [Span-based PII replacement](2026-10-04-span-based-pii-replacement.md).

On page 2 of `drucker.pdf`, two failures came from the OCR, not the model:

- Tesseract read the bold line `LEON HARTMANN` as `een`. Bonsai only marks text
  that appears exactly in the OCR lines, so the name could not be marked and
  stayed on the copy. Before the switch to OCR input, Bonsai found the name in
  every run.
- Tesseract's box for `BEISPIELALLEE 42` is 30 px tall where a line is about
  10 px. It covers the bottom of the name line and the street line together,
  so the new street was drawn over the name and the street's own row stayed empty.

## Design

1. **OCR text is not trusted, only positions.** Tesseract supplies word boxes.
   Its text is used to find where a value is, never to decide what the value is.
2. **Bonsai reads the values from the image.** The detection call gets the image
   and returns each PII value as printed, with type, owner, and an approximate
   box. This is what Bonsai is good at.
3. **Code finds each value on the page,** in this order:
   1. Fuzzy-match the value against runs of consecutive OCR words on one line
      (character alignment after normalisation). A good match gives the exact
      word boxes.
   2. When no OCR run matches, as with `een`, use the pixel line finder: the
      page's ink rows split into text lines. Take the lines near the model's
      approximate box, read each one back with the model, and keep the line whose
      reading contains the value.
   3. When neither works, the value is not edited. The leak check still searches
      for it, so the copy fails instead of shipping with the value.
4. **Tall boxes are split along the ink.** A box much taller than the page's
   typical line height covers several text lines; it is split at the blank rows
   inside it, and the part that holds the value is used.
5. **Read-back compares what is drawn.** The expected text for a changed line is
   the read-back of the original line with the old value swapped for the new one,
   not the OCR text, so OCR noise no longer counts as a rendering failure.
6. **Everything else stays:** consistent values per owner, word-level redraw,
   whole-letter erasing, the leak check with type-based excuses, and the split
   between public answer keys and private mappings.

## Production requirements

- Pure functions for matching, line finding, box splitting, and value
  generation, with unit tests that need no model and no Tesseract.
- Model and Tesseract calls behind small interfaces, so tests can replace them.
- `ruff`, `mypy`, `pytest` with coverage, and Slophammer (`slophammer-py`) in CI.
- One command, `synthero SCAN.png`, with outputs in RAM by default and the
  private folder never served.

## Test

Page 2 of `drucker.pdf` and the till receipt from `gutschein_reiseadapter.pdf`,
on Bonsai within 16 GB. Pass when the customer's name is replaced, the street
is drawn on its own line, no label is lost, and every copy passes the leak check.

## Results

Bonsai (Ternary Bonsai 2 27B, PQ2_0) through the Llama app on khazaddum, one
16 GB GPU.

- The value-first design worked as planned on page 2 of `drucker.pdf`: the bold
  name that Tesseract read as `een` was located from pixels and read back, the
  street was drawn on its own line, and no label was lost.
- The test then grew into the whole fixture, and each failure it showed changed
  the design further: crop reads that correct the model's misread digits, claimed
  boxes, frames ignored by the line finder, a second detection pass, barcodes,
  per-page fonts, documents, and digital PDFs.
  [Documents, digital PDFs, and the harness](2026-10-05-documents-pdfs-and-the-harness.md)
  records those changes and the eval over 24 documents.
