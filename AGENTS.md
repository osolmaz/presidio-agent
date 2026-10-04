# AGENTS.md

These instructions apply to this repository.

## Commands To Run Before Finishing

```sh
ruff format --check .
ruff check .
mypy synthero tests
pytest --cov=synthero --cov-fail-under=85
python scripts/check-mutation.py --min-kill-rate 85
uvx slophammer-py@0.5.0 dry .
uvx slophammer-py@0.5.0 check .
```

CI runs the same gates; do not finish with any of them red. The tests need the
Liberation fonts (`fonts-liberation`) and no model, server, or Tesseract.

## Rules

- Python 3.11+. The only runtime dependency is Pillow; Tesseract and the model
  server are external programs reached through `ocr.py` and `vl.py`.
- Strict mypy and Ruff `ANN`: annotate every function. No `Any`; narrow model
  answers and cached JSON at the boundary (`detect.parse`,
  `synth.analysis_from_json`).
- Keep the boundaries: `vl.py`, `ocr.py`, and `cli.py` do IO. `match`,
  `geometry`, `values`, `leak`, `detect.parse`, `locate`, `render`, and `synth`
  take their readers as arguments and are tested with fakes.
- Never trust OCR text as a value. The model reads values; OCR and pixels only
  give positions.
- Privacy: the public answer key holds new values only. Old values, the
  analysis cache, and the old-to-new mappings go to the private folder, which
  must never be served, logged, committed, or uploaded. Never commit scans or
  outputs (`.gitignore` covers images and PDFs).
- A value that cannot be located is not edited and must fail the leak check;
  never guess a position.
- Add or update tests for every behaviour change.
- Document design changes in `docs/` with SimpleDoc front matter.

## Slophammer

Quality gates follow the Slophammer standards:
https://github.com/osolmaz/slophammer/blob/main/docs/AGENT_ENTRYPOINT.md
