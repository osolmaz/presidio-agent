# AGENTS.md

These instructions apply to this repository.

## Commands To Run Before Finishing

```sh
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy presidio_agent tests
uv run pytest --cov=presidio_agent --cov-fail-under=85
uv run python scripts/check-mutation.py --min-kill-rate 85
uvx slophammer-py@0.5.0 dry .
uvx slophammer-py@0.5.0 check .
```

Use uv for everything: `uv add` and `uv remove` change dependencies and `uv.lock`
together, and `uv run` runs commands in the project environment.

CI runs the same gates; do not finish with any of them red. The tests need the
Liberation fonts (`fonts-liberation`). They use fakes for the model server and
OCR; one test runs the real Presidio analyzer.

## Rules

- Python 3.12+. The runtime dependencies are Pillow, Tau (`tau-ai`, pinned to a
  commit), and Presidio with the German spaCy model; Presidio is imported only in
  `recognizers.py`, which loads it on first use. Tesseract and the llama.cpp server are external programs
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
- The agent decides; the edits come from its tools (`tools.py`, exposed to Tau by
  `extension.py`), which run the fixed flow in `pipeline.py`. Tau's own tools stay
  available, and the policy (`agent.md`) keeps the agent from editing copies itself.
- Configure through command-line options only (`settings.py`), never environment
  variables. The launcher sets `LLAMA_BASE_URL` and `TAU_HOME` only because Tau's
  own code reads them.
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
