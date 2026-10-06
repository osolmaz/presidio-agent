"""Loading documents: images, scanned PDF pages, and PDF text layers."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw, ImageFont

from presidio_agent import barcode, fonts, ocr, source

XHTML = """<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>
<page width="595" height="842"><flow><block><line>
<word xMin="72" yMin="36" xMax="108" yMax="48">LEON</word>
<word xMin="112" yMin="36" xMax="180" yMax="48">HARTMANN</word>
</line><line><word xMin="72" yMin="10" xMax="100" yMax="20">Top</word>
<word xMin="1" yMin="1" xMax="2" yMax="2"> </word></line>
</block></flow></page>
<page width="595" height="842"></page>
</doc></body></html>"""

IMAGE_LIST = """page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image    1055  1491  rgb     3   8  image  no         3  0   128   128 1424K  31%
   2     1 image     100   100  rgb     3   8  image  no         5  0   128   128   10K  31%
   2     2 smask     100   100  gray    1   8  image  no         6  0   128   128    1K  31%
   2     3 image     100   100  rgb     3   8  image  no         7  0   128   128   10K  31%
"""


def test_text_layer_scales_points_to_pixels_and_sorts_lines():
    pages = source.text_layer(XHTML, 150 / 72)
    assert len(pages) == 2 and pages[1] == []
    top, name = pages[0]
    assert top.text == "Top" and name.text == "LEON HARTMANN"
    assert name.words[0].box == (150, 75, 225, 100)


def test_scanned_pages_are_pages_with_one_image():
    assert source.scanned_pages(IMAGE_LIST) == {1}


def test_load_image_and_scanned_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "lines", lambda img: [ocr.Line((ocr.Word("x", (0, 0, 1, 1)),))])
    img = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(img).text((20, 20), "LEON HARTMANN", fill="black")
    img.save(tmp_path / "scan.png")
    img.save(tmp_path / "scan.pdf", resolution=100)
    [png] = source.load(str(tmp_path / "scan.png"))
    assert png.kind == "scan" and png.image.size == (300, 200)
    [pdf] = source.load(str(tmp_path / "scan.pdf"))
    assert pdf.kind == "scan" and pdf.image.size == (300, 200)  # the embedded image, not a re-render
    with pytest.raises(ValueError):
        source.load(str(tmp_path / "notes.txt"))


def test_find_all_barcodes_skips_text_and_logos():
    img = Image.new("RGB", (700, 300), "white")
    barcode.draw(img, (40, 20, 40 + 2 * 134, 60), "842607130031480842", (0, 0, 0), (255, 255, 255))
    barcode.draw(img, (400, 20, 400 + 2 * 134, 60), "123456789012345678", (0, 0, 0), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for y in range(120, 280, 12):
        d.text((40, y), "LEON HARTMANN 10117 BERLIN 60120873 ELEKTROMARKT NORD GMBH", fill="black")
    found = barcode.find_all(img.convert("L"), line_height=10)
    assert [(b[0], b[1], b[3]) for b in found] == [(40, 20, 60), (400, 20, 60)]
    assert not barcode.is_barcode(img.convert("L"), (40, 120, 400, 160))


def test_fonts_pick_the_family_and_weight_a_value_was_printed_in():
    families = fonts.available()
    assert "Liberation Sans" in families and "Liberation Mono" in families
    mono_bold = ImageFont.truetype(families["Liberation Mono"][1], 20)
    img = Image.new("RGB", (260, 40), "white")
    ImageDraw.Draw(img).text((5, 5), "60120873 4512", font=mono_bold, fill="black")
    crop = img.crop(img.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox())
    style = fonts.page_style([(crop, "60120873 4512", crop.height)])
    assert style.bold and "Mono" in style.family
    font, scale = fonts.best(crop, "60120873 4512", crop.height, style)
    assert font.path == families[style.family][1] and 0.9 < scale < 1.1
    assert fonts.shape_cut(Image.new("L", (4, 4), 200)) == 199  # no contrast: everything below the paper
