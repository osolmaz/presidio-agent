"""presidio-agent: de-identify documents with a local agent, or with the fixed flow alone.

    presidio-agent [TAU OPTIONS] [PROMPT]     the agent: Tau with this package's tools
    presidio-agent copy DOCUMENT [--n 3]      the fixed flow, without the agent

DOCUMENT is an image or a PDF (scanned pages, text pages, or both). See `pipeline` for
the steps and `agent.md` for what the agent decides. Outputs go to --out; the analysis,
Presidio's candidates, and the old-to-new mappings go to --private, which must never be
served or shared.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from presidio_agent import agent, extension, pipeline, recognizers


def copy_main(argv: Sequence[str]) -> None:
    ap = argparse.ArgumentParser(prog="presidio-agent copy", description="Make synthetic copies without the agent.")
    ap.add_argument("document", help="an image or a PDF")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150, help="resolution for digital PDF pages")
    ap.add_argument("--out", default=extension.DEFAULT_OUT)
    ap.add_argument(
        "--private",
        default=extension.DEFAULT_PRIVATE,
        help="folder for the analysis and old-to-new mappings; never serve or share it",
    )
    ap.add_argument("--no-presidio", action="store_true", help="skip Presidio's candidates")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--no-leak-check", action="store_true")
    a = ap.parse_args(argv)

    ws = pipeline.Workspace(a.out, a.private)
    doc = pipeline.analyse_document(a.document, ws, None if a.no_presidio else recognizers.analyzer(), a.dpi)
    for page in doc.pages:
        print(page.summary(), flush=True)
    for result in pipeline.make_copies(doc, ws, a.n, a.seed, verify=not a.no_verify, leak_check=not a.no_leak_check):
        print(pipeline.copy_summary(result.number, result.key, verified=not a.no_verify), flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["copy"]:
        copy_main(args[1:])
    else:
        agent.run(args)


if __name__ == "__main__":
    main()
