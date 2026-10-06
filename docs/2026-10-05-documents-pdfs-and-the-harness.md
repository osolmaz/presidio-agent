---
date: 2026-10-05
author: Onur Solmaz <2453968+osolmaz@users.noreply.github.com>
title: Documents, digital PDFs, and the synthetic data harness
tags: [presidio-agent, pdf, ocr, fonts, barcodes, eval, design]
---

# Documents, digital PDFs, and the synthetic data harness

This note follows [Value-first detection](2026-10-05-value-first-detection.md).
It records how presidio-agent grew from one scanned page to whole documents of any
kind, and what each change fixed.

## Goal

A harness that makes synthetic copies of invoices and receipts with all personal
data replaced, accurately enough that no original value survives, on one 16 GB
GPU. The models are Ternary Bonsai 27B (PQ2_0, about 14.7 GB with its vision
projector, through the Llama app on a laptop with a 16 GB GPU) and Tesseract. Qwen-Image was
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
| A one-digit correction needs six digits; an amount or a percentage is never a value | `0000` was "corrected" to the tax rate `0,00%`. |
| Near matches fold look-alike letters inside codes (Z/2, O/0, I/1, S/5, B/8, G/6) | A creditor ID with `ZZZ` was read as `22Z` and could not be located. |
| Bare years are not values | A year alone identifies no one, and the date shifter rightly left it unchanged. |
| Readings split at `|`; a run glued to the next word is trimmed at a blank column | Tesseract read `4194|Datum:` as one word, and `Datum:` was erased. |
| Punctuation printed in a run is drawn back; a reading that differs only in punctuation keeps the model's form | A comma after a name was lost; `12.07.` read as `12.07` was no date and stayed. |
| Wrapped values take their text from the model, never from OCR | OCR read `DE68` as `DF68.`, which broke the new IBAN's country code. |
| Fonts are sized by the letters' core rows and lose score per unit of width stretch | Skew and blur made regular fonts too wide, so stretched narrow fonts won. |
| Patches take the paper's colour; old letters are erased with their blur halo | Gray boxes on tinted paper, and faint ghosts of the old letters. |
| Unchanged values fail the leak check | A date form the shifter did not know stayed unchanged but excused itself as a "new" value. |

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
weights (`mmproj-BF16.gguf`), now downloaded on the test laptop, and a server started
with `--llm_vision`. Restarting the Qwen-Image server for that was not
allowed in this session, so it is not tested. The font vote already matches the
fixture's fonts closely, so the gain is unclear.

## Results

Model: `prism-ml/Ternary-Bonsai-2-27B-gguf:PQ2_0` through the Llama app on
a laptop with an RTX 3080 Laptop GPU (16 GB; about 14.7 GB used). Tesseract 5.3.4,
poppler, one copy per document.

### Development runs

Each run found failures that changed the design; every failure in one run was
fixed before the next.

| Run | Code | Documents passed | Failures |
| --- | --- | --- | --- |
| A | `19a8bf0` | 22 of 24 | a bare year left unchanged; a creditor ID read with `ZZZ` as `22Z` |
| B | `f63e93a` | 24 of 24 | none by the checks; by eye: a label erased beside a glued OCR word, a lost comma, a wrapped IBAN that took OCR's misread country code, condensed fonts on scans |
| C | `3af6ec1` | stopped | `12.07.` read without its dot; uneven ends of skewed barcodes |
| D | `1111797` | 24 of 24 | by eye: gray patches on tinted paper, a faint halo of old letters, a comma's trim that cut into a name |
| E | `c326d0a` | 24 of 24 | final run, below |

### Final run

Run E on `c326d0a`, 36 pages, one copy per document: every detected value (349)
was located, edited, and read back, and every page passed the leak check.

| Set | Document | Pages | Values | Located | Edited | Read back | Barcodes scrambled | Leak check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| real | drucker | 3 | 46 | 46 | 46 | 46 | 3 | passed |
| real | gutschein_reiseadapter | 1 | 22 | 22 | 22 | 22 | 0 | passed |
| sim | beleg | 1 | 10 | 10 | 10 | 10 | 0 | passed |
| sim | coworking_juli | 1 | 8 | 8 | 8 | 8 | 0 | passed |
| sim | einnahme1_1 | 1 | 15 | 15 | 15 | 15 | 0 | passed |
| sim | einnahme1_2 | 1 | 10 | 10 | 10 | 10 | 0 | passed |
| sim | einnahme2 | 1 | 9 | 9 | 9 | 9 | 0 | passed |
| sim | erstattung_gesamt | 2 | 24 | 24 | 24 | 24 | 0 | passed |
| sim | rechnung_lautsprecher | 1 | 8 | 8 | 8 | 8 | 0 | passed |
| sim | telekom_1 | 3 | 17 | 17 | 17 | 17 | 0 | passed |
| sim | telekom_2 | 3 | 19 | 19 | 19 | 19 | 0 | passed |
| sim | ueberweisungseingang_ausland_09.07.2026 | 1 | 14 | 14 | 14 | 14 | 0 | passed |
| sim | umsatzdetails_medienbeitrag_20260731 | 1 | 8 | 8 | 8 | 8 | 0 | passed |
| digital | beleg | 1 | 9 | 9 | 9 | 9 | 0 | passed |
| digital | coworking_juli | 1 | 10 | 10 | 10 | 10 | 0 | passed |
| digital | einnahme1_1 | 1 | 11 | 11 | 11 | 11 | 0 | passed |
| digital | einnahme1_2 | 1 | 10 | 10 | 10 | 10 | 0 | passed |
| digital | einnahme2 | 1 | 9 | 9 | 9 | 9 | 0 | passed |
| digital | erstattung_gesamt | 2 | 21 | 21 | 21 | 21 | 0 | passed |
| digital | rechnung_lautsprecher | 1 | 11 | 11 | 11 | 11 | 0 | passed |
| digital | telekom_1 | 3 | 17 | 17 | 17 | 17 | 0 | passed |
| digital | telekom_2 | 3 | 21 | 21 | 21 | 21 | 0 | passed |
| digital | ueberweisungseingang_ausland_09.07.2026 | 1 | 12 | 12 | 12 | 12 | 0 | passed |
| digital | umsatzdetails_medienbeitrag_20260731 | 1 | 8 | 8 | 8 | 8 | 0 | passed |

### Detection consistency

The leak check can only search for values that were detected. To estimate
detection recall, `scripts/eval_consistency.py` compares the values found on each
simulated scan with those found on its digital twin; both show the same content.

| Document | Digital | Scan | Both | Digital only | Scan only |
| --- | --- | --- | --- | --- | --- |
| beleg | 9 | 10 | 9 | 0 | 1 |
| coworking_juli | 10 | 8 | 7 | 3 | 1 |
| einnahme1_1 | 11 | 15 | 11 | 0 | 4 |
| einnahme1_2 | 10 | 10 | 10 | 0 | 0 |
| einnahme2 | 8 | 8 | 8 | 0 | 0 |
| erstattung_gesamt | 20 | 22 | 19 | 1 | 3 |
| rechnung_lautsprecher | 8 | 8 | 8 | 0 | 0 |
| telekom_1 | 13 | 13 | 13 | 0 | 0 |
| telekom_2 | 17 | 15 | 15 | 2 | 0 |
| ueberweisungseingang_ausland_09.07.2026 | 12 | 14 | 10 | 2 | 4 |
| umsatzdetails_medienbeitrag_20260731 | 8 | 8 | 8 | 0 | 0 |

agreement: 118 of 139 distinct values found in both versions

About 85% agreement. Part of the difference is policy, not reading: on one
version the model lists the business's own e-mail, invoice number, or a bank
reference, and on the other it does not. Part is a real miss, such as the invoice
number in a title. This is the weakest link: a value the model never lists is
neither replaced nor searched for.

### Not done

- Qwen-Image crop editing, see [Qwen-Image](#qwen-image).
- QR codes.
- A third detection pass on enlarged page tiles, to raise recall on small text.
