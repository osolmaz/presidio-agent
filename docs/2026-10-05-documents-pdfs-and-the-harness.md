---
date: 2026-10-05
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Documents, digital PDFs, and the synthetic data harness
tags: [synthero, pdf, ocr, fonts, barcodes, eval, design]
---

# Documents, digital PDFs, and the synthetic data harness

This note follows [Value-first detection](2026-10-05-value-first-detection.md).
It records how synthero grew from one scanned page to whole documents of any
kind, and what each change fixed.

## Goal

A harness that makes synthetic copies of invoices and receipts with all personal
data replaced, accurately enough that no original value survives, on one 16 GB
GPU. The models are Ternary Bonsai 27B (PQ2_0, about 14.7 GB with its vision
projector, through the Llama app on khazaddum) and Tesseract. Qwen-Image was
considered for redrawing crops: see [Qwen-Image](#qwen-image).

## Architecture

```text
source.load      document -> pages: image + word boxes
  scan page      embedded image (no resampling), words from Tesseract
  digital page   rendered with pdftoppm, words and boxes from the text layer
detect           Bonsai, two passes: image; image + page text for what was missed
                 compound lines split; amounts dropped
locate           exact word matches claim their boxes first
                 near matches (a digit differs): a full-resolution read decides
                 the printed text; never on a claimed box
                 pixel lines near the hint, read back, when nothing else matches
synth            one replacer per document copy (same identity on every page)
  fonts          family and weight voted per page by letter-shape overlap
  render         erase the value's own ink, draw the new value
  barcode        Code 128 of the new number beside it; other barcodes scrambled
  verify         read-back of each edit; leak check of every page
```

## What changed, and why

| Change | Problem it fixed |
| --- | --- |
| The model's reading of a value is only a first guess; a crop read gives the printed text | Bonsai read `66128344` as `66128244`. The leak check searched the wrong string, so the real number could have stayed unflagged. |
| Crops get a blank margin and are upscaled to 64 px before reading | Tight crops made Bonsai misread the first digit (`628173` as `528173`). |
| Exact matches claim boxes; weaker evidence cannot take a claimed box | `19:10 Uhr` was matched to the `19:10:03 Uhr` line, so that line was edited twice and the real `19:10 Uhr` stayed. |
| Near matches are tried for every value | `12.07.2026` is printed twice; OCR misread one copy, and only the other was edited. |
| Frames and bars (vertical ink longer than three lines) are not text | The receipt's edge line ran through the footer, so the pixel line finder merged text, barcode, and digits into one block. |
| Pixel candidates must be at least half a line tall and one line wide | Each dash of a `-----` separator became a candidate line and pushed the real lines out. |
| Whole-line fallback only when the word counts agree | The barcode's digits were matched to the 6-word footer line above them. |
| A second detection pass with the page's text | The first pass missed the loyalty card number. |
| Compound identifier lines are split into id, date, and time parts | The model returned a whole footer line as one id; its date must shift like every other date. |
| Amounts are never values; leak pieces depend on the type | The review pass listed `146,50 EUR` and `3.450 Bits`, and the shop's e-mail; the unit `Bits` and the shop's name then counted as leaks. |
| Font family and weight are voted per page by shape overlap | Width and ink density alone picked bold Liberation Sans for a narrow mono receipt font, and a different font for each value. |
| Barcodes beside a changed number are redrawn as Code 128 of it; every other barcode is scrambled | The bars kept encoding the old number. The fixture's bars are about 2 px per module, too blurred to decode, so their content cannot be checked and is treated as personal. |
| Documents, not pages | A person must have the same new name on every page. |
| Digital PDFs through their text layer | The text layer gives exact words and boxes, so no OCR guessing is needed. |

## Eval

`scripts/eval.sh` runs the invoice fixture (`osolmaz/invoice-fixture`, all
synthetic) in three sets:

- `real`: `drucker.pdf` (3 scanned pages) and `gutschein_reiseadapter.pdf` (1).
- `sim`: the 11 digital PDFs of up to 3 pages, turned into scan-like images by
  `scripts/simulate_scan.py` (128 dpi, skew, tint, blur, noise, JPEG). They have
  no text layer, so they take the scan path.
- `digital`: the same 11 PDFs with their text layer.

A copy is good when every detected value is located and edited, the edits read
back, and the leak check passes on every page.

Results: see [Results](#results).

## Qwen-Image

Whole-page Qwen-Image edits mixed values up and garbled small text
(see the notes repo, `2026-10-03-qwen-image-invoice-edits.md`). The useful role
left is a crop-level edit for text whose font no installed font matches, accepted
only when Bonsai reads the new value back. Editing needs the encoder's vision
weights (`mmproj-BF16.gguf`), now downloaded on khazaddum, and a server started
with `--llm_vision`. Restarting the khazaddum Qwen-Image server for that was not
allowed in this session, so it is not tested. The font vote already matches the
fixture's fonts closely, so the gain is unclear.

## Results

To be filled in after the eval.
