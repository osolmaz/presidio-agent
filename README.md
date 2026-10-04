# synthero

synthero makes synthetic copies of invoices and receipts: scanned images, scanned
PDFs, and digital PDFs. Each copy has new, consistent personal data across all its
pages, and every other pixel of the original is kept. Each copy comes with an
answer key. It runs on one 16 GB GPU.

## How it works

| Step | Tool | What it does |
| --- | --- | --- |
| 0. Load | poppler, Tesseract | Splits the document into page images with word boxes. A scanned page keeps its own image and gets word boxes from Tesseract. A digital PDF page is rendered and gets exact word boxes from its text layer. |
| 1. Detect | vision model (Ternary Bonsai 27B, 2-bit) | Reads every personal value from the page image in two passes: first the image alone, then the image with the page's text, to find what the first pass missed. Values are names, the customer's address, e-mail, phone, customer, contract, receipt, terminal, and card numbers, dates, and times. Each value comes with its type and owner. No label lists: the model decides what is personal. Amounts are never replaced, so totals stay consistent. |
| 2. Locate | word boxes, pixels, vision model | Finds every place each value is printed, and what is printed there. A value matches words fuzzily, with equal digits. If a digit differs, the model reads that spot again at full resolution, and its reading is the printed text. If OCR fails, the text lines found from pixels near the model's hint are read back. An exact match claims its place first, so a weaker match cannot take it. Frames and barcode bars do not merge text lines. |
| 3. Invent | code | Makes new values in the same format. Every owner gets one invented identity. All dates move by one shift, and all times by one shift. E-mails use `example.com`. |
| 4. Redraw | code | Erases only the value's own ink and draws the new value at the original letter height and in the original ink colour. The font family and weight are voted per page: each candidate font renders the old values, and its letter shapes are compared with the original ink. Labels and every other word keep their pixels. A barcode beside a changed number gets a Code 128 of the new number. Every other barcode gets bars that encode nothing, because its content cannot be read from a scan. |
| 5. Verify | vision model | Reads each edit back. Then it reads the whole page and searches for every piece of every original value: the leak check. A value that could not be located is not edited, and it fails the leak check. |

The design and its results are in [`docs/`](docs/).

## Install

Requirements:

- Python 3.11+
- Tesseract with the German and English data (`tesseract-ocr`, `tesseract-ocr-deu`)
- poppler (`poppler-utils`) for PDFs
- the Liberation fonts (`fonts-liberation`); DejaVu (`fonts-dejavu-extra`) and the URW fonts (`fonts-urw-base35`) give closer matches
- an OpenAI-compatible vision model server, such as llama.cpp's `llama-server` or the Llama app

```sh
pip install -e .
```

The tested model is `prism-ml/Ternary-Bonsai-2-27B-gguf:PQ2_0` (about 14.7 GB
of VRAM with its vision projector). It runs on a 16 GB laptop GPU.

## Use

```sh
export SYNTHERO_VL=http://127.0.0.1:8081                       # the model server
export SYNTHERO_MODEL=prism-ml/Ternary-Bonsai-2-27B-gguf:PQ2_0 # needed by routers such as the Llama app
synthero scan.png --n 3                                         # an image
synthero invoice.pdf --n 3                                      # a scanned or digital PDF
python -m synthero.page /dev/shm/synthero/out                   # comparison page: index.html
```

Outputs, in `--out` (default `/dev/shm/synthero/out`, in RAM):

- `STEM.copy-K.pN.png` and `STEM.copy-K.pdf`: the synthetic copy, page by page and as one PDF. Every copy is an image, also for a digital PDF.
- `STEM.copy-K.json`: its answer key, with new values only. For each page it holds each value's type, owner, new text, boxes, read-back result, the barcodes redrawn, and the leak check verdict.
- `STEM.pN.original.png` and `STEM.pN.boxes.png`: each page, and its located values. Red: matched by words. Purple: corrected by a second reading. Orange: found from pixels.

The analysis cache and the old-to-new mappings go to `--private` (default
`/dev/shm/synthero/private`). They contain the original personal data. Never
serve, share, or commit them.

Options: `--n` sets the number of copies. `--seed` sets the first seed.
`--dpi` sets the resolution for digital PDF pages (150). `--no-verify` skips the
read-back, and `--no-leak-check` skips the leak check.
Use a copy only when its leak check passed.

## Limits

- Detection recall depends on the model. A missed value is neither edited nor
  searched for. On the eval fixture, the values found on a scan and on its digital
  twin agreed 85% of the time (`scripts/eval_consistency.py`). Check
  `STEM.pN.boxes.png`.
- QR codes are not handled yet.
- The redraw uses common Linux fonts. A typeface that is not like one of them
  will look different.
- Copies of digital PDFs are images, without a text layer.
- Amounts and line items do not change, so totals stay consistent.

## Eval

`scripts/eval.sh FIXTURE_DIR` runs every PDF in a folder in three sets: the real
scans, the digital PDFs turned into scan-like images (`scripts/simulate_scan.py`),
and the digital PDFs as they are. Each set gets its own comparison page.
`scripts/eval_table.py` summarises the public keys, and
`scripts/eval_consistency.py` compares detection between scans and their digital
twins. Results: [docs](docs/2026-10-05-documents-pdfs-and-the-harness.md#results).

## Development

See [AGENTS.md](AGENTS.md) for the checks. The tests need no model, no server,
and no Tesseract.
