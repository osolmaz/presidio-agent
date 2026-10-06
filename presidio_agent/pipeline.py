"""The fixed de-identification flow for one document, shared by the CLI and the agent's tools.

1. Each page becomes an image with word boxes (`source`).
2. Presidio proposes candidates from the page's text (`candidates`).
3. The vision model reads the personal values, checking Presidio's candidates (`detect`).
4. Each value is located wherever it is printed (`locate`).
5. Each copy redraws every located value with a consistent invented one, reads every
   edit back, and checks each page for any surviving original value (`synth`).

The analysis, the candidates, and the old-to-new mappings hold original personal data
and go to the private folder only. The output folder gets the page images, the box
overlays, the copies, and their public answer keys with new values only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from presidio_agent import candidates, detect, locate, ocr, source, synth, vl
from presidio_agent.candidates import Analyze, Candidate
from presidio_agent.detect import Value
from presidio_agent.locate import Located

# Red: OCR words matched the value. Purple: OCR and a second reading agreed on a
# corrected value. Orange: found from pixels and read back.
BOX_COLOURS = {"ocr": (220, 30, 30), "ocr+read": (150, 40, 200), "pixels": (230, 140, 0)}


@dataclass(frozen=True)
class Workspace:
    out: str  # copies, page images, public answer keys
    private: str  # analysis caches, candidates, old-to-new mappings: never serve or share

    def create(self) -> None:
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(self.private, exist_ok=True)

    def private_path(self, stem: str, page: int, kind: str) -> str:
        return os.path.join(self.private, f"{stem}.p{page}.{kind}.json")


@dataclass
class PageAnalysis:
    number: int
    page: source.Page
    analysed: synth.Analysed
    candidates: list[Candidate] = field(default_factory=list)

    def unconfirmed(self) -> list[Candidate]:
        """Presidio's candidates that no found value covers."""
        return candidates.unconfirmed(self.candidates, (v.text for v in self.analysed.values))

    def summary(self) -> str:
        places = [p for ps in self.analysed.locs for p in ps]
        by_ocr = sum(1 for p in places if p.how != "pixels")
        located = sum(1 for ps in self.analysed.locs if ps)
        return (
            f"page {self.number} ({self.page.kind}): {len(self.analysed.values)} personal values, "
            f"{located} located in {len(places)} places ({by_ocr} by OCR, {len(places) - by_ocr} by pixels), "
            f"{len(self.unconfirmed())} of {len(self.candidates)} Presidio candidates not confirmed"
        )


@dataclass
class Document:
    path: str
    stem: str
    pages: list[PageAnalysis]


def _save(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def _load(path: str) -> object:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def page_text(page: source.Page) -> str:
    return "\n".join(ln.text for ln in page.lines)


def _candidates(page: source.Page, cache: str, analyze: Analyze | None) -> list[Candidate]:
    if os.path.exists(cache):
        data = _load(cache)
        rows = data if isinstance(data, list) else []
        return [Candidate(str(c["text"]), str(c["entity"]), float(c["score"])) for c in rows]
    found = candidates.find(page_text(page), analyze)
    _save(cache, [{"text": c.text, "entity": c.entity, "score": c.score} for c in found])
    return found


def _analysed(page: source.Page, vals: list[Value], locs: list[list[Located]]) -> synth.Analysed:
    context = synth.page_context(" ".join(ln.text for ln in page.lines), vals, locs)
    return synth.Analysed(page.image, vals, locs, context)


def analyse_page(page: source.Page, number: int, stem: str, ws: Workspace, analyze: Analyze | None) -> PageAnalysis:
    """Candidates, values, and places for one page, each cached in the private folder."""
    found = _candidates(page, ws.private_path(stem, number, "candidates"), analyze)
    cache = ws.private_path(stem, number, "analysis")
    if os.path.exists(cache):
        vals, locs = synth.analysis_from_json(_load(cache))
    else:
        vals = detect.find_values(page.image, page_text(page), [c.text for c in found])
        locs = locate.locate(page.image, vals, page.lines, vl.read_text, ocr.lines)
        _save(cache, synth.analysis_to_json(vals, locs))
    return PageAnalysis(number, page, _analysed(page, vals, locs), found)


def debug_boxes(scan: Image.Image, locs: list[list[Located]], path: str) -> None:
    img = scan.convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for places in locs:
        for loc in places:
            d.rectangle(loc.run_box, outline=BOX_COLOURS.get(loc.how, (230, 140, 0)), width=2)
    img.save(path)


def stem_of(document: str) -> str:
    return os.path.splitext(os.path.basename(document))[0]


def analyse_document(document: str, ws: Workspace, analyze: Analyze | None, dpi: int = 150) -> Document:
    """Every page of a document analysed, with its image and box overlay in the output folder."""
    ws.create()
    stem = stem_of(document)
    pages = []
    for number, page in enumerate(source.load(document, dpi), start=1):
        result = analyse_page(page, number, stem, ws, analyze)
        page.image.save(os.path.join(ws.out, f"{stem}.p{number}.original.png"))
        debug_boxes(page.image, result.analysed.locs, os.path.join(ws.out, f"{stem}.p{number}.boxes.png"))
        pages.append(result)
    return Document(document, stem, pages)


def accept_value(doc: Document, number: int, value: Value, ws: Workspace) -> bool:
    """Add a value the agent decided is personal, locate it, and update the page's cache.
    Returns whether it was found on the page; an unlocated value is kept and fails the leak check."""
    page = doc.pages[number - 1]
    vals = [*page.analysed.values, value]
    locs = [*page.analysed.locs, *locate.locate(page.page.image, [value], page.page.lines, vl.read_text, ocr.lines)]
    _save(ws.private_path(doc.stem, number, "analysis"), synth.analysis_to_json(vals, locs))
    page.analysed = _analysed(page.page, vals, locs)
    debug_boxes(page.page.image, locs, os.path.join(ws.out, f"{doc.stem}.p{number}.boxes.png"))
    return bool(locs[-1])


@dataclass(frozen=True)
class CopyResult:
    number: int
    pdf: str
    key: synth.Key


def copy_summary(i: int, key: synth.Key, verified: bool = True) -> str:
    changes = [c for p in key["pages"] for c in p["changes"]]
    edited = [c for c in changes if c["places"]]
    ok = sum(c["read_back_ok"] for c in edited)
    checks = [p["leak_check"] for p in key["pages"] if "leak_check" in p]
    leaked = sorted({t for lc in checks for t in lc["leaked_types"]})
    verdict = "" if not checks else ("leak check passed" if not leaked else f"LEAK of {leaked}")
    bars = sum(p["barcodes_scrambled"] for p in key["pages"])
    readback = f"{ok} read back correctly" if verified else "read-back skipped"
    return f"copy {i}: {len(edited)} values replaced, {readback}, {bars} barcodes scrambled, {verdict}"


def make_copies(
    doc: Document, ws: Workspace, n: int, seed: int, verify: bool = True, leak_check: bool = True
) -> list[CopyResult]:
    """`n` synthetic copies, each written as page images, a PDF, and a public answer key."""
    results = []
    pages = [p.analysed for p in doc.pages]
    for i in range(1, n + 1):
        copy = synth.make_copy(
            pages,
            seed + i - 1,
            read=vl.read_text if verify else None,
            read_page=vl.read_page if leak_check else None,
        )
        base = os.path.join(ws.out, f"{doc.stem}.copy-{i}")
        for number, image in enumerate(copy.images, start=1):
            image.save(f"{base}.p{number}.png")
        copy.images[0].save(f"{base}.pdf", save_all=True, append_images=copy.images[1:])
        _save(f"{base}.json", copy.key)
        _save(os.path.join(ws.private, f"{doc.stem}.copy-{i}.private.json"), copy.private_key)
        results.append(CopyResult(i, f"{base}.pdf", copy.key))
    return results
