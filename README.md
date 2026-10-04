# synthero

synthero makes synthetic copies of a scanned invoice or receipt. Each copy has
new, consistent personal data, and every other pixel of the scan is kept. Each
copy comes with an answer key. It runs on one 16 GB GPU.

## How it works

| Step | Tool | What it does |
| --- | --- | --- |
| 1. Detect | vision model (Ternary Bonsai 27B, 2-bit) | Reads every personal value from the image: names, the customer's address, e-mail, phone, customer, contract, receipt, terminal, and card numbers, dates, times. Each value comes with its type and owner. No label lists: the model decides what is personal. |
| 2. Locate | Tesseract OCR and pixels | Finds every place each value is printed. OCR text is never trusted as a value. It only gives word boxes. A value matches OCR words fuzzily, but its digits must match exactly. A box taller than a line is split at blank rows, and the model reads each part to pick the right one. If OCR fails, the text lines found from pixels near the model's hint are read back by the model. |
| 3. Invent | code | Makes new values in the same format. Every owner gets one invented identity. All dates move by one shift, and all times by one shift. E-mails use `example.com`. |
| 4. Redraw | code | Erases only the value's own ink and draws the new value in the Liberation font, size, weight, and ink colour that best match the original. Labels and every other word keep their pixels. |
| 5. Verify | vision model | Reads each edit back. Then it reads the whole page and searches for every piece of every original value: the leak check. A value that could not be located is not edited, and it fails the leak check. |

The design and its results are in [`docs/`](docs/).

## Install

Requirements:

- Python 3.11+
- Tesseract with the German and English data (`tesseract-ocr`, `tesseract-ocr-deu`)
- the Liberation fonts (`fonts-liberation`)
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
synthero scan.png --n 3
python -m synthero.page /dev/shm/synthero/out                   # comparison page: index.html
```

Outputs, in `--out` (default `/dev/shm/synthero/out`, in RAM):

- `scan.copy-N.png`: the synthetic copy.
- `scan.copy-N.json`: its answer key, with new values only. It holds each value's type, owner, new text, boxes, read-back result, and the leak check verdict.
- `scan.boxes.png`: the located values. Red boxes were located by OCR, orange boxes by pixels.

The analysis cache and the old-to-new mappings go to `--private` (default
`/dev/shm/synthero/private`). They contain the original personal data. Never
serve, share, or commit them.

Options: `--n` sets the number of copies. `--seed` sets the first seed.
`--no-verify` skips the read-back, and `--no-leak-check` skips the leak check.
Use a copy only when its leak check passed.

## Limits

- Detection recall depends on the model. A missed value is neither edited nor
  searched for. Check `scan.boxes.png`.
- Barcodes and QR codes still encode the original data.
- The redraw uses Liberation Sans and Mono. Unusual typefaces will look
  different.
- Amounts and line items do not change, so totals stay consistent.

## Development

See [AGENTS.md](AGENTS.md) for the checks. The tests need no model, no server,
and no Tesseract.
