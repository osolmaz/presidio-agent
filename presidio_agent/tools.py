"""What the agent can do, as plain functions over one session's documents.

`extension.py` exposes these to Tau as tools. Every report is a JSON-ready dict for the
model. Reports contain original values, so the agent's session log belongs in the
private folder (the launcher puts it there).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from presidio_agent import candidates, detect, pipeline
from presidio_agent.candidates import Analyze
from presidio_agent.detect import Value
from presidio_agent.pipeline import Document, PageAnalysis, Workspace

Report = dict[str, object]


def page_report(doc: Document, page: PageAnalysis, out: str) -> Report:
    analysed = page.analysed
    return {
        "page": page.number,
        "kind": page.page.kind,
        "image": os.path.join(out, f"{doc.stem}.p{page.number}.original.png"),
        "boxes": os.path.join(out, f"{doc.stem}.p{page.number}.boxes.png"),
        "values": [
            {"text": v.text, "type": v.type, "owner": v.owner, "located": bool(places)}
            for v, places in zip(analysed.values, analysed.locs, strict=True)
        ],
        "unconfirmed_candidates": [
            {"text": c.text, "entity": c.entity, "score": c.score, "suggested_type": candidates.value_type(c.entity)}
            for c in page.unconfirmed()
        ],
    }


def document_report(doc: Document, out: str) -> Report:
    return {"document": doc.path, "pages": [page_report(doc, p, out) for p in doc.pages]}


@dataclass
class Session:
    """The documents analysed in one agent session, by absolute path."""

    ws: Workspace
    analyze: Analyze | None
    docs: dict[str, Document] = field(default_factory=dict)

    def _doc(self, path: str) -> Document:
        key = os.path.abspath(path)
        if key not in self.docs:
            self.docs[key] = pipeline.analyse_document(key, self.ws, self.analyze)
        return self.docs[key]

    def analyse(self, path: str) -> Report:
        """Find the personal values of a document, with Presidio's candidates the vision model did not confirm."""
        return document_report(self._doc(path), self.ws.out)

    def accept(self, path: str, page: int, text: str, type_: str, owner: str) -> Report:
        """Add a value the agent decided is personal; report whether it was found on the page."""
        doc = self._doc(path)
        if not 1 <= page <= len(doc.pages):
            return {"error": f"page {page} does not exist; the document has {len(doc.pages)} pages"}
        if type_ not in detect.TYPES:
            return {"error": f"type {type_!r} is not one of {list(detect.TYPES)}"}
        size = doc.pages[page - 1].page.image.size
        located = pipeline.accept_value(doc, page, Value(text, type_, owner, (0, 0, *size)), self.ws)
        return {"accepted": text, "page": page, "located": located}

    def copies(self, path: str, n: int, seed: int) -> Report:
        """Make `n` synthetic copies; report each copy's files and its read-back and leak-check verdicts."""
        doc = self._doc(path)
        results = pipeline.make_copies(doc, self.ws, n, seed)
        return {
            "copies": [
                {
                    "pdf": r.pdf,
                    "key": r.pdf.removesuffix(".pdf") + ".json",
                    "summary": pipeline.copy_summary(r.number, r.key),
                    "leak_check_passed": all("leak_check" in p and p["leak_check"]["passed"] for p in r.key["pages"]),
                }
                for r in results
            ]
        }
