"""Load a document as pages: an image, and the words printed on it with their boxes.

- An image file, or a PDF page that is one scanned image: the native image, and
  words from Tesseract (positions only; OCR text is never trusted as a value).
- A PDF page with a text layer: rendered at `dpi`, and words with exact text and
  boxes from the text layer (poppler's `pdftotext -bbox-layout`).

Either way the rest of the pipeline sees the same thing, and every copy is an image.
"""

from __future__ import annotations

import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from presidio_agent import ocr

XHTML = "{http://www.w3.org/1999/xhtml}"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}


@dataclass(frozen=True)
class Page:
    image: Image.Image
    lines: list[ocr.Line]
    kind: str  # "scan" (words from OCR) or "text" (words from the PDF text layer)


def text_layer(xhtml: str, scale: float) -> list[list[ocr.Line]]:
    """Lines of words per page from `pdftotext -bbox-layout`, boxes scaled from points to pixels."""
    root = ET.fromstring(xhtml)
    pages = []
    for page in root.iter(f"{XHTML}page"):
        lines = []
        for line in page.iter(f"{XHTML}line"):
            words = tuple(
                ocr.Word((w.text or "").strip(), _scaled(w, scale))
                for w in line.iter(f"{XHTML}word")
                if (w.text or "").strip()
            )
            if words:
                lines.append(ocr.Line(words))
        pages.append(sorted(lines, key=lambda ln: (ln.box[1], ln.box[0])))
    return pages


def _scaled(word: ET.Element, scale: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax"))
    return (int(x1 * scale), int(y1 * scale), round(x2 * scale), round(y2 * scale))


def scanned_pages(image_list: str) -> set[int]:
    """Pages that hold exactly one image, from `pdfimages -list`: candidates for a scan."""
    counts: dict[int, int] = {}
    for row in image_list.splitlines()[2:]:
        cols = row.split()
        if len(cols) > 2 and cols[0].isdigit() and cols[2] == "image":
            counts[int(cols[0])] = counts.get(int(cols[0]), 0) + 1
    return {page for page, n in counts.items() if n == 1}


def _run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, check=True, text=True).stdout


def _pdf_pages(path: Path, dpi: int) -> list[Page]:
    words = text_layer(_run("pdftotext", "-bbox-layout", str(path), "-"), dpi / 72)
    single_image = scanned_pages(_run("pdfimages", "-list", str(path)))
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, lines in enumerate(words, start=1):
            if not lines and n in single_image:  # a scan: take the image as it is, no resampling
                _run("pdfimages", "-png", "-f", str(n), "-l", str(n), str(path), f"{tmp}/scan{n}")
                image = Image.open(next(Path(tmp).glob(f"scan{n}-*.png"))).convert("RGB")
                pages.append(Page(image, ocr.lines(image), "scan"))
            else:
                _run("pdftoppm", "-r", str(dpi), "-f", str(n), "-l", str(n), "-png", str(path), f"{tmp}/page{n}")
                image = Image.open(next(Path(tmp).glob(f"page{n}-*.png"))).convert("RGB")
                pages.append(Page(image, lines or ocr.lines(image), "text" if lines else "scan"))
    return pages


def load(path: str, dpi: int = 150) -> list[Page]:
    """The pages of an image file or a PDF."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return _pdf_pages(p, dpi)
    if p.suffix.lower() in IMAGE_SUFFIXES:
        image = Image.open(p).convert("RGB")
        return [Page(image, ocr.lines(image), "scan")]
    raise ValueError(f"not an image or a PDF: {path}")
