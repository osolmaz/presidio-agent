# AGENTS.md

These instructions apply to this repository.

## Commands To Run Before Finishing

```sh
ruff format --check .
ruff check .
mypy presidio_agent tests
pytest --cov=presidio_agent --cov-fail-under=85
python scripts/check-mutation.py --min-kill-rate 85
uvx slophammer-py@0.5.0 dry .
uvx slophammer-py@0.5.0 check .
```

CI runs the same gates; do not finish with any of them red. The tests need the
Liberation fonts (`fonts-liberation`). They use fakes for the model server and
OCR, and skip the Presidio test when the `presidio` extra is not installed.

## Rules

- Python 3.12+. The runtime dependencies are Pillow and Tau (`tau-ai`, pinned to a
  commit); Presidio is the optional `presidio` extra and is imported only in
  `recognizers.py`. Tesseract and the llama.cpp server are external programs
  reached through `ocr.py` and `vl.py`.
- Strict mypy and Ruff `ANN`: annotate every function. No `Any`; narrow model
  answers and cached JSON at the boundary (`detect.parse`,
  `synth.analysis_from_json`).
- Keep the boundaries: `vl.py`, `ocr.py`, `recognizers.py`, `pipeline.py`,
  `agent.py`, and `cli.py` do IO. `candidates`, `match`, `geometry`, `values`,
  `leak`, `detect.parse`, `locate`, `render`, and `synth` take their readers as
  arguments and are tested with fakes.
- Presidio only proposes. Its candidates go to the vision model and the agent;
  nothing is edited because Presidio flagged it.
- The agent decides; it never edits pixels or files. Its tools (`tools.py`,
  exposed to Tau by `extension.py`) run the fixed flow in `pipeline.py`, and the
  extension blocks every other Tau tool except `read`.
- Never trust OCR text as a value. The model reads values; OCR and pixels only
  give positions.
- Privacy: the public answer key holds new values only. Old values, the
  analysis cache, Presidio's candidates, the old-to-new mappings, and the
  agent's Tau sessions (the launcher sets `TAU_HOME` inside it) go to the
  private folder, which must never be served, logged, committed, or uploaded. Never commit scans or
  outputs (`.gitignore` covers images and PDFs).
- A value that cannot be located is not edited and must fail the leak check;
  never guess a position.
- Add or update tests for every behaviour change.
- Document design changes in `docs/` with SimpleDoc front matter.

## Slophammer

Quality gates follow the Slophammer standards:
https://github.com/osolmaz/slophammer/blob/main/docs/AGENT_ENTRYPOINT.md
