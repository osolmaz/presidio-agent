# presidio-agent

presidio-agent is a local agent that makes synthetic copies of invoices and receipts.
It replaces every piece of personal data in place with a consistent invented value and
keeps every other pixel of the original, and each copy comes with an answer key. It runs
on one machine with one GPU, so no document ever leaves it.

It joins two open-source projects. [Presidio](https://github.com/microsoft/presidio)'s
rule-based recognizers flag candidates in each page's text: IBANs, card numbers, e-mail
addresses, phone numbers, dates, names, and German ID numbers. A vision model reads the
page image and decides which of those candidates, and what else, is personal.
[Tau](https://github.com/huggingface/tau), Hugging Face's Python agent harness, runs
the agent that drives the work and decides about every candidate the vision model did
not confirm. The steps that edit pixels are
fixed and tested code, and the agent never edits a file itself.

presidio-agent is an independent project. It is not affiliated with or endorsed by the
Presidio team.

## Pipeline

| Step | Tool | What it does |
| --- | --- | --- |
| Load | poppler, Tesseract | Splits the document into page images with word boxes. A scanned page gets word boxes from Tesseract, and a digital PDF page gets exact ones from its text layer. |
| Propose | Presidio | Flags candidates in the page's text with Presidio's recognizers, set up for German and English. `copy --no-presidio` turns it off. |
| Detect | vision model | Reads every personal value from the page image in two passes: the image alone, then the image with the page's text and Presidio's candidates. Each value comes with its type and owner. Amounts are never replaced, so totals stay consistent. |
| Decide | Tau agent | Opens the page image for each candidate the vision model did not confirm, and accepts the candidate when it is a person's data or skips it when it is the business's own. |
| Locate | word boxes, pixels, vision model | Finds every place each value is printed. A value matches words fuzzily with equal digits; a doubtful digit is read again at full resolution, and pixel lines near the model's hint are the fallback when OCR fails. |
| Redraw | code | Gives every owner one invented identity and shifts all dates by one offset, then erases only each value's own ink and draws the new value in the original ink colour and letter height, in a font voted per page. Barcodes beside changed numbers get a Code 128 of the new number. |
| Verify | vision model | Reads each edit back, then reads the whole page and searches it for every piece of every original value. A value that could not be located is not edited and fails this leak check. |

The design and its results are in [`docs/`](docs/).

## Install

Requirements:

- Python 3.12+
- Tesseract with the German and English data (`tesseract-ocr`, `tesseract-ocr-deu`)
- poppler (`poppler-utils`) for PDFs
- the Liberation fonts (`fonts-liberation`); DejaVu (`fonts-dejavu-extra`) and the URW fonts (`fonts-urw-base35`) give closer matches
- a llama.cpp server (`llama-server`) with a vision model and its `--mmproj` projector

```sh
pip install "presidio-agent @ git+https://github.com/osolmaz/presidio-agent.git"
```

The install includes Presidio and the German spaCy model it uses for names. The tested model is
`prism-ml/Ternary-Bonsai-2-27B-gguf:PQ2_0` with its vision projector, about 14.7 GB of
VRAM, so it fits a 16 GB GPU.

## Use

Point presidio-agent at the llama.cpp server and start the agent:

```sh
export PRESIDIO_AGENT_VL=http://127.0.0.1:8080      # the llama.cpp server
export PRESIDIO_AGENT_MODEL=ternary-bonsai-2-27b     # the model id it serves
presidio-agent                                       # Tau's TUI with presidio-agent's tools
presidio-agent -p "Make two synthetic copies of invoice.pdf."
```

The agent has three tools of its own, and Tau's read tool to look at a page image:

- `find_personal_values` analyses a document. It reports the values found with whether each
  was located, and Presidio's candidates that the vision model did not confirm.
- `accept_value` adds a value the agent decided is personal.
- `make_copies` makes the copies and reports how each copy did in the read-back and the leak check.

Tau's other tools stay available, and the agent's policy leaves every edit to its own
tools. Other Tau options, such as `--provider` and `--model`, pass through unchanged.

The fixed flow also runs without the agent, for scripts and evals:

```sh
presidio-agent copy invoice.pdf --n 3        # an image or a scanned or digital PDF
python -m presidio_agent.page /dev/shm/presidio-agent/out   # comparison page: index.html
```

Outputs, in `--out` (default `/dev/shm/presidio-agent/out`, in RAM):

- `STEM.copy-K.pN.png` and `STEM.copy-K.pdf`: the synthetic copy, page by page and as one PDF. Every copy is an image, also for a digital PDF.
- `STEM.copy-K.json`: its answer key, with new values only. For each page it holds each value's type, owner, new text, boxes, read-back result and the barcodes redrawn, with the leak check verdict.
- `STEM.pN.original.png` and `STEM.pN.boxes.png`: each page, and its located values. Red: matched by words. Purple: corrected by a second reading. Orange: found from pixels.

The analysis, Presidio's candidates, the old-to-new mappings, and the agent's Tau
sessions go to `--private` (default `/dev/shm/presidio-agent/private`). They contain the
original personal data. Never serve or commit them. Use a copy only when its
leak check passed.

## Limits

- Detection recall depends on the model. A value that neither Presidio nor the model
  finds is neither edited nor searched for. On the eval fixture, the values found on a
  scan and on its digital twin agreed 85% of the time before Presidio's candidates were
  added (`scripts/eval_consistency.py`). Check `STEM.pN.boxes.png`.
- QR codes are not handled yet.
- The redraw uses common Linux fonts. A typeface that is not like one of them will look
  different.
- Copies of digital PDFs are images, without a text layer.
- Amounts and line items do not change, so totals stay consistent.
- Tau is pinned to a commit that detects llama.cpp vision models
  ([huggingface/tau#757](https://github.com/huggingface/tau/pull/757)), until a release
  includes it.

## Eval

`scripts/eval.sh FIXTURE_DIR` runs every PDF in a folder in three sets: the real
scans, the digital PDFs turned into scan-like images (`scripts/simulate_scan.py`),
and the digital PDFs as they are. Each set gets its own comparison page.
`scripts/eval_table.py` summarises the public keys, and
`scripts/eval_consistency.py` compares detection between scans and their digital
twins. Results: [docs](docs/2026-10-05-documents-pdfs-and-the-harness.md#results).

## Development

See [AGENTS.md](AGENTS.md) for the checks. The tests use fakes in place of the model
server and OCR, with one test that runs the real Presidio analyzer.

## License

MIT. Presidio and Tau are MIT-licensed as well.
