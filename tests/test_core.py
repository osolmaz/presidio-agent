"""Unit tests that need no model and no Tesseract: synthetic pages drawn with Pillow."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from synthero import barcode, cli, detect, geometry, leak, locate, match, ocr, render, synth, values, vl
from synthero import page as synthero_page
from synthero.detect import Value

FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def page(lines: list[tuple[int, int, str]], size=(600, 300)) -> Image.Image:
    """A white page with black text lines at (x, y)."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 14)
    for x, y, text in lines:
        d.text((x, y), text, font=f, fill="black")
    return img


# --- match ---------------------------------------------------------------


def test_find_all_tolerates_ocr_splits_but_not_other_digits():
    lines = [["10117", "BERLIN"], ["Alexanderplatz", "3", "10178", "Berlin"], ["Nr.:", "EMN-SP-2607", "12-7781"]]
    assert match.find_all("10117 BERLIN", lines) == [match.Match(0, 0, 1, 1.0)]
    assert [(m.line, m.first_word, m.last_word) for m in match.find_all("EMN-SP-260712-7781", lines)] == [(2, 1, 2)]


def test_find_all_finds_every_occurrence():
    lines = [["Datum:", "12.07.2026", "Lieferzeitpunkt:", "12.07.2026"]]
    assert [(m.first_word, m.last_word) for m in match.find_all("12.07.2026", lines)] == [(1, 1), (3, 3)]


def test_contains_allows_small_slips():
    assert match.contains("Kd-Nr.: 60120873", "60120873")
    assert match.contains("LEON HARTMANN", "LEON HARTMAN")
    assert not match.contains("BEISPIELALLEE 42", "LEON HARTMANN")


# --- values --------------------------------------------------------------


def test_replacer_is_consistent_and_keeps_format():
    r = values.Replacer(random.Random(3))
    first = r.replace("LEON HARTMANN", "person", "customer")
    assert first == first.upper() and r.replace("LEON HARTMANN", "person", "customer") == first
    staff = r.replace("KELLER", "person", "salesperson")
    assert staff.split()[-1] != first.split()[-1]  # different owners, different people
    card = r.replace("************7318", "card", "payment")
    assert card.startswith("************") and len(card) == 16 and card != "************7318"
    assert r.replace("x@y.de", "email", "customer").endswith("@example.com")


def test_dates_and_times_shift_together():
    r = values.Replacer(random.Random(1))
    a, b = r.replace("12.07.2026", "date", "document"), r.replace("13.07.2026", "date", "document")
    da, db = (int(x.split(".")[0]) for x in (a, b))
    assert (db - da) % 31 in (1, -30 % 31)  # one day apart before and after
    assert values.shift_times("11:10:22 Uhr", 15) == "11:25:22 Uhr"


# --- detect --------------------------------------------------------------


def test_parse_drops_malformed_items_and_scales_boxes():
    answer = [
        {"text": "KELLER", "type": "person", "owner": "Salesperson", "bbox_2d": [500, 500, 600, 520]},
        {"text": "", "type": "person"},
        {"text": "x", "type": "nonsense"},
        "junk",
        {"text": "KELLER", "type": "person", "owner": "salesperson", "bbox_2d": [0, 0, 1, 1]},
    ]
    vals = detect.parse(answer, 2000, 1000)
    assert vals == [Value("KELLER", "person", "salesperson", (1000, 500, 1200, 520))]


# --- geometry ------------------------------------------------------------


def test_ink_lines_splits_rows_and_columns():
    img = page([(20, 20, "LEON HARTMANN"), (20, 60, "10117 BERLIN"), (420, 60, "7713086621953398")])
    lines = geometry.ink_lines(img.convert("L"))
    assert len(lines) == 3
    assert sorted(b[0] < 300 for b in lines) == [False, True, True]


def test_split_tall_box_returns_both_lines():
    img = page([(20, 20, "LEON HARTMANN"), (20, 40, "BEISPIELALLEE 42")])
    gray = img.convert("L")
    parts = geometry.split_tall_box(gray, (15, 15, 250, 60), line_height=14)
    assert len(parts) == 2 and parts[0][3] <= parts[1][1]


# --- locate --------------------------------------------------------------


def test_locate_falls_back_to_pixels_when_ocr_text_is_garbage():
    img = page([(20, 20, "HERR"), (20, 45, "LEON HARTMANN"), (20, 70, "BEISPIELALLEE 42")])
    ocr_lines = [ocr.Line((ocr.Word("een", (20, 45, 140, 60)),))]
    truth = {"HERR": (20, 20), "LEON HARTMANN": (20, 45), "BEISPIELALLEE 42": (20, 70)}

    value = Value("LEON HARTMANN", "person", "customer", (20, 40, 200, 65))
    reader = ink_width_reader(list(truth))

    places = locate.locate(img, [value], ocr_lines, reader)[0]
    assert len(places) == 1 and places[0].how == "pixels"
    assert abs(places[0].run_box[1] - 45) <= 6


# --- render --------------------------------------------------------------


def test_replace_only_changes_pixels_near_the_value():
    img = page([(20, 20, "Kd-Nr.: 60120873"), (20, 60, "LEON HARTMANN")])
    gray = img.convert("L")
    line = geometry.ink_lines(gray)[0]
    words = geometry.word_boxes(gray, line)
    run = words[-1]
    out, _ = render.replace_words(img, img, line, run, "60120873", "79074391")
    a, b = geometry.pixels(img.convert("L")), geometry.pixels(out.convert("L"))
    changed = [(x, y) for y in range(img.height) for x in range(img.width) if a[x, y] != b[x, y]]
    assert changed
    assert all(run[0] - 25 <= x and run[1] - 8 <= y <= run[3] + 8 for x, y in changed)
    assert not [(x, y) for x, y in changed if 55 <= y < 80]  # the next line is untouched


# --- leak ----------------------------------------------------------------


def test_leak_check_flags_survivors_and_excuses_only_places():
    old = [("person", "LEON HARTMANN"), ("city", "10117 BERLIN"), ("email", "LEON.HARTMANN@EXAMPLE.COM")]
    leaks = leak.check(
        "MIRA VOGT 10178 Berlin LEON.HARTMANN@EXAMPLE.COM",
        old,
        context="Alexanderplatz 3 10178 Berlin",
        new_values=["MIRA.VOGT@EXAMPLE.COM"],
    )
    types = {x["type"] for x in leaks}
    assert "person" in types and "email" in types  # the surname survives in the old e-mail
    assert "city" not in types  # BERLIN is also the shop's city
    assert all("EXAMPLE" not in x["pieces"] for x in leaks)  # the new values use it too


# --- synth -----------------------------------------------------------------


def test_make_copy_edits_every_place_and_keeps_old_values_out_of_the_public_key():
    img = page([(20, 20, "Kd-Nr.: 60120873"), (20, 60, "Ref 60120873")])
    gray = img.convert("L")
    value = Value("60120873", "id", "customer", (0, 0, 600, 300))
    places = []
    for line in geometry.ink_lines(gray):
        run = geometry.word_boxes(gray, line)[-1]
        places.append(locate.Located(value, line, run, None, "ocr", "60120873"))
    new = values.Replacer(random.Random(1)).replace("60120873", "id", "customer")
    copy = synth.make_copy(
        [synth.Analysed(img, [value], [places], "Kd-Nr.: Ref")],
        seed=1,
        read=lambda crop: f"Ref {new}",
        read_page=lambda page: f"Kd-Nr.: {new} Ref {new}",
    )
    change = copy.key["pages"][0]["changes"][0]
    assert change["new"] == new and len(change["places"]) == 2 and change["read_back_ok"]
    assert copy.key["pages"][0]["leak_check"] == {"passed": True, "leaked_types": []}
    assert "60120873" not in json.dumps(copy.key)
    assert copy.private_key["pages"][0]["changes"][0]["old"] == "60120873"
    for p in places:
        assert copy.images[0].crop(p.run_box).tobytes() != img.crop(p.run_box).tobytes()


def test_make_copy_fails_the_leak_check_for_a_value_it_could_not_locate():
    img = page([(20, 20, "LEON HARTMANN")])
    value = Value("LEON HARTMANN", "person", "customer", (0, 0, 600, 300))
    pages = [synth.Analysed(img, [value], [[]], "")]
    copy = synth.make_copy(pages, seed=1, read_page=lambda page: "LEON HARTMANN")
    assert copy.key["pages"][0]["changes"][0]["located"] is False
    assert copy.key["pages"][0]["leak_check"] == {"passed": False, "leaked_types": ["person"]}


def test_a_value_the_replacer_cannot_change_fails_the_leak_check():
    img = page([(20, 20, "Zeitraum: Q3")])
    gray = img.convert("L")
    line = geometry.ink_lines(gray)[0]
    value = Value("Q3", "date", "document", (0, 0, 600, 300))  # no date form the replacer knows
    loc = locate.Located(value, line, line, None, "ocr", "Q3")
    copy = synth.make_copy(
        [synth.Analysed(img, [value], [[loc]], "Zeitraum:")], seed=1, read_page=lambda p: "Zeitraum: Q3"
    )
    assert copy.key["pages"][0]["leak_check"]["passed"] is False


def test_one_document_gets_one_identity_across_pages():
    img = page([(20, 20, "LEON HARTMANN")])
    gray = img.convert("L")
    line = geometry.ink_lines(gray)[0]
    value = Value("LEON HARTMANN", "person", "customer", (0, 0, 600, 300))
    loc = locate.Located(value, line, line, None, "ocr", "LEON HARTMANN")
    pages = [synth.Analysed(img, [value], [[loc]], ""), synth.Analysed(img, [value], [[loc]], "")]
    copy = synth.make_copy(pages, seed=4)
    first, second = (p["changes"][0]["new"] for p in copy.key["pages"])
    assert first == second and [p["page"] for p in copy.key["pages"]] == [1, 2]
    assert len(copy.images) == 2


def test_analysis_cache_round_trips_and_rejects_garbage():
    v = Value("KELLER", "person", "staff", (1, 2, 3, 4))
    locs = [[locate.Located(v, (0, 0, 10, 10), (2, 0, 8, 10), None, "pixels", "KELLER")]]
    data = json.loads(json.dumps(synth.analysis_to_json([v], locs)))
    assert synth.analysis_from_json(data) == ([v], locs)
    with pytest.raises(ValueError):
        synth.analysis_from_json({"values": [{"text": "x"}], "located": [[]]} | {"values": "nope"})


def test_via_ocr_splits_a_tall_box_and_keeps_only_the_part_that_reads_back():
    img = page([(20, 20, "LEON HARTMANN"), (20, 40, "BEISPIELALLEE 42")])
    gray = img.convert("L")
    rows = geometry.ink_lines(gray)
    merged = (15, 15, 250, 60)  # Tesseract merged the two lines into one tall box
    normal = [ocr.Line((ocr.Word("Rechnung", (300, 20 + 20 * i, 360, 31 + 20 * i)),)) for i in range(4)]
    ocr_lines = [ocr.Line((ocr.Word("BEISPIELALLEE", merged), ocr.Word("42", merged))), *normal]

    texts = {rows[0][1]: "LEON HARTMANN", rows[1][1]: "BEISPIELALLEE 42"}

    value = Value("BEISPIELALLEE 42", "street", "customer", (0, 0, 600, 300))
    found = locate.locate(img, [value], ocr_lines, ink_width_reader(list(texts.values())))[0]
    assert len(found) == 1
    assert abs(found[0].run_box[1] - rows[1][1]) <= 2 and found[0].run_box[3] <= 60


def ink_width_reader(texts: list[str]) -> locate.Reader:
    """A fake model for pages drawn by `page`: names a one-line crop by the width of its ink."""
    widths = {t: page([(0, 0, t)]).convert("L").point(lambda v: 255 if v < 128 else 0).getbbox() for t in texts}

    def read(crop: Image.Image) -> str:
        box = crop.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
        if box is None or box[3] - box[1] > 20:  # blank, or more than one line
            return ""
        return min(texts, key=lambda t: abs((widths[t] or box)[2] - (widths[t] or box)[0] - (box[2] - box[0])))

    return read


def test_ocr_groups_rows_and_splits_columns():
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t20\t60\t40\t14\t90\t10117",
            "5\t1\t1\t1\t1\t2\t65\t60\t55\t14\t90\tBERLIN|",
            "5\t1\t1\t1\t1\t3\t420\t60\t140\t14\t90\t7713086621953398",
            "5\t1\t1\t1\t2\t1\t20\t20\t40\t14\t90\tHERR",
        ]
    )
    lines = ocr.group_lines(ocr.parse_tsv(tsv))
    assert [ln.text for ln in lines] == ["HERR", "10117 BERLIN", "7713086621953398"]
    assert lines[1].words[1].text == "BERLIN" and lines[1].box == (
        20,
        60,
        112,
        74,
    )  # the "|" keeps its share of the box


def test_parse_objects_salvages_a_cut_off_answer():
    answer = 'Here:\n```json\n[{"text": "x", "box": {"a": 1}}, {"text": "y"}, {"text": "cut'
    assert vl.parse_objects(answer) == [{"text": "x", "box": {"a": 1}}, {"text": "y"}]
    assert vl.parse_objects("{broken} {}") == [{}]


def test_page_shows_new_values_only(tmp_path):
    page_img = Image.new("RGB", (10, 10), "white")
    page_img.save(tmp_path / "scan.p1.original.png")
    page_img.save(tmp_path / "scan.copy-1.p1.png")
    key = {
        "seed": 1,
        "pages": [
            {
                "page": 1,
                "barcodes_scrambled": 1,
                "changes": [
                    {
                        "type": "person",
                        "owner": "customer",
                        "new": "MIRA VOGT",
                        "located": True,
                        "read_back_ok": True,
                        "places": [{}],
                    }
                ],
                "leak_check": {"passed": True, "leaked_types": []},
            }
        ],
    }
    (tmp_path / "scan.copy-1.json").write_text(json.dumps(key))
    html_text = Path(synthero_page.build(str(tmp_path))).read_text(encoding="utf-8")
    assert "MIRA VOGT" in html_text and "Leak check passed" in html_text and "1 barcodes scrambled" in html_text
    assert "scan.copy-1.p1.png" in html_text


# --- cli -----------------------------------------------------------------


def test_cli_end_to_end_with_fake_model_and_ocr(tmp_path, monkeypatch, capsys):
    scan = page([(20, 20, "Kunde: LEON HARTMANN"), (20, 60, "Kd-Nr.: 60120873")])
    scan.save(tmp_path / "scan.png")
    gray = scan.convert("L")
    rows = geometry.ink_lines(gray)

    def ocr_line(row: tuple[int, int, int, int], texts: list[str]) -> ocr.Line:
        boxes = geometry.word_boxes(gray, row)
        return ocr.Line(tuple(ocr.Word(t, b) for t, b in zip(texts, boxes, strict=True)))

    lines = [ocr_line(rows[0], ["Kunde:", "LEON", "HARTMANN"]), ocr_line(rows[1], ["Kd-Nr.:", "60120873"])]
    found = [
        Value("LEON HARTMANN", "person", "customer", (0, 0, 600, 40)),
        Value("60120873", "id", "customer", (0, 50, 600, 80)),
    ]
    monkeypatch.setattr(ocr, "lines", lambda img: lines)
    monkeypatch.setattr(detect, "find_values", lambda img, text: found)
    monkeypatch.setattr(vl, "read_text", lambda img: "")
    monkeypatch.setattr(vl, "read_page", lambda img: "Kunde: Kd-Nr.:")
    out, private = tmp_path / "out", tmp_path / "private"
    monkeypatch.setattr(
        "sys.argv", ["synthero", str(tmp_path / "scan.png"), "--n", "2", "--out", str(out), "--private", str(private)]
    )
    cli.main()
    cli.main()  # the second run reads the cached analysis
    printed = capsys.readouterr().out
    assert "page 1 (scan): 2 personal values, 2 located in 2 places (2 by OCR, 0 by pixels)" in printed
    assert "copy 2: 2 values replaced, 0 read back correctly, 0 barcodes scrambled, leak check passed" in printed
    public = (out / "scan.copy-1.json").read_text(encoding="utf-8")
    assert "HARTMANN" not in public and "60120873" not in public
    assert "HARTMANN" in (private / "scan.copy-1.private.json").read_text(encoding="utf-8")
    assert (out / "scan.p1.boxes.png").exists() and (out / "scan.copy-2.pdf").exists()


def test_ocr_near_miss_takes_the_printed_text_from_a_second_reading():
    img = page([(20, 20, "Terminal-ID 66128344")])
    gray = img.convert("L")
    row = geometry.ink_lines(gray)[0]
    label, number = geometry.word_boxes(gray, row)
    lines = [ocr.Line((ocr.Word("Terminal-1D", label), ocr.Word("66128344", number)))]
    value = Value("66128244", "id", "document", (0, 0, 600, 60))  # the model misread one digit
    for reading in ("66128344", "66128244", "66128249"):  # agrees with OCR, with the model, with neither

        def read(crop: Image.Image, r: str = reading) -> str:
            return r  # the crop holds the number only

        places = locate.locate(img, [value], lines, read)[0]
        assert [(p.how, p.printed, p.run_box) for p in places] == [("ocr+read", reading, number)]
    far = locate.locate(img, [value], lines, lambda crop: "99999999")[0]
    assert far == []


def test_a_box_claimed_by_an_exact_match_is_not_taken_by_a_near_one():
    img = page([(20, 20, "Uhrzeit: 19:10:03 Uhr")])
    gray = img.convert("L")
    boxes = geometry.word_boxes(gray, geometry.ink_lines(gray)[0])
    lines = [ocr.Line(tuple(ocr.Word(t, b) for t, b in zip(["Uhrzeit:", "19:10:03", "Uhr"], boxes, strict=True)))]
    exact = Value("19:10:03", "time", "document", (0, 0, 600, 60))
    near = Value("19:10 Uhr", "time", "document", (0, 0, 600, 60))  # printed elsewhere, OCR missed it
    places = locate.locate(img, [exact, near], lines, lambda crop: "Uhrzeit: 19:10:03 Uhr")
    assert [p.how for p in places[0]] == ["ocr"] and places[1] == []


def test_make_copy_uses_the_printed_text_and_redraws_the_barcode():
    img = Image.new("RGB", (520, 140), "white")
    barcode.draw(img, (40, 20, 40 + 3 * 134, 80), "842607130031480842", (0, 0, 0), (255, 255, 255))
    ImageDraw.Draw(img).text((60, 90), "842607130031480842", font=ImageFont.truetype(FONT, 14), fill="black")
    gray = img.convert("L")
    run = geometry.ink_lines(gray, (0, 85, 520, 140))[0]
    value = Value("842607130031480B42", "id", "document", (0, 0, 520, 140))
    loc = locate.Located(value, run, run, None, "ocr+read", "842607130031480842")
    copy = synth.make_copy([synth.Analysed(img, [value], [[loc]], "")], seed=3, read_page=lambda p: "")
    change = copy.key["pages"][0]["changes"][0]
    assert change["places"][0]["barcode"][1] == 20 and change["places"][0]["barcode_valid"]
    assert copy.private_key["pages"][0]["changes"][0]["old"] == "842607130031480842"
    new_digits = match.digits(change["new"])
    bars = change["places"][0]["barcode"]
    out_gray = copy.images[0].convert("L")
    row = [geometry.pixels(out_gray)[x, 50] < 128 for x in range(bars[0], bars[2])]
    module = (bars[2] - bars[0]) / sum(barcode.widths_for(new_digits))
    assert barcode.decode_widths([max(1, round(n / module)) for n in barcode.runs(row)]) == new_digits


def test_line_ocr_places_a_value_when_the_word_splits_disagree():
    img = page([(20, 20, "Hotline Nummer 0800 / 77 88 990")])
    gray = img.convert("L")
    line = geometry.ink_lines(gray)[0]
    value = Value("800 / 77 88 990", "phone", "business", (0, 0, 600, 60))  # the model dropped a digit
    reading = "Hotline-Nummer: 0800/77 88 990"  # the reader joins words the ink keeps apart
    boxes = geometry.word_boxes(gray, line)
    assert len(boxes) != len(reading.split())

    def line_ocr(crop: Image.Image) -> list[ocr.Line]:  # a fake Tesseract on the enlarged line
        x = (boxes[2][0] - line[0]) * 3
        words = [ocr.Word("Hotline", (0, 0, 60, 30)), ocr.Word("Nummer", (70, 0, 140, 30))]
        words += [
            ocr.Word(t, (x + 40 * i, 0, x + 40 * i + 30, 30)) for i, t in enumerate(["0800", "/", "77", "88", "990"])
        ]
        return [ocr.Line(tuple(words))]

    places = locate.locate(img, [value], [], lambda crop: reading, line_ocr)[0]
    assert [(p.how, p.printed) for p in places] == [("pixels", "0800/77 88 990")]
    assert places[0].run_box[0] == boxes[2][0]
    assert locate.locate(img, [value], [], lambda crop: reading)[0] == []  # without line OCR: not placed


def test_a_corrected_reading_that_is_an_amount_is_not_taken():
    img = page([(20, 20, "incl."), (120, 20, "0,00%"), (220, 20, "Mwst"), (320, 20, "0,00")])
    gray = img.convert("L")
    boxes = sorted(geometry.ink_lines(gray))
    words = ["incl.", "0,00%", "Mwst", "0,00"]
    lines = [ocr.Line(tuple(ocr.Word(t, b) for t, b in zip(words, boxes, strict=True)))]
    value = Value("0000", "id", "document", (0, 0, 600, 60))
    assert locate.locate(img, [value], lines, lambda crop: "incl. 0,00% Mwst 0,00")[0] == []


def test_a_value_wrapped_over_two_lines_is_found_and_split():
    img = page([(20, 20, "von dem Konto IBAN DE68"), (20, 40, "1000 0000 2468 1357 90 abgebucht")])
    gray = img.convert("L")
    rows = sorted(geometry.ink_lines(gray), key=lambda b: b[1])
    texts = [["von", "dem", "Konto", "IBAN", "DE68"], ["1000", "0000", "2468", "1357", "90", "abgebucht"]]
    lines = [
        ocr.Line(tuple(ocr.Word(t, b) for t, b in zip(words, geometry.word_boxes(gray, row), strict=True)))
        for words, row in zip(texts, rows, strict=True)
    ]
    value = Value("DE68 1000 0000 2468 1357 90", "iban", "customer", (0, 0, 600, 300))
    places = locate.locate(img, [value], lines, lambda crop: "")[0]
    assert [(p.how, p.printed, p.words) for p in places] == [
        ("wrapped", "DE68", (0, 1)),
        ("wrapped", "1000 0000 2468 1357 90", (1, 6)),
    ]
    misread = [ocr.Line((*lines[0].words[:-1], ocr.Word("DF68.", lines[0].words[-1].box))), lines[1]]
    from_value = locate.locate(img, [value], misread, lambda crop: "")[0]
    assert [p.printed for p in from_value] == ["DE68", "1000 0000 2468 1357 90"]  # never the OCR text
    assert synth.printed_text(value, places) == "DE68 1000 0000 2468 1357 90"
    assert synth.part_of("DE42 7783 5337 4068 1241 58", (1, 6), 6) == "7783 5337 4068 1241 58"
    assert synth.part_of("A B C", (1, 6), 6) == "B C"  # another word count: the same share, never empty
    assert synth.part_of("A B C", (0, 1), 6) == "A"
    assert synth.part_of("ABCDEF", (0, 1), 6) == "A" and synth.part_of("ABCDEF", (1, 6), 6) == "BCDEF"
    assert synth.part_of("ABCDEFGHIJKL", (0, 1), 6) == "AB"
    copy = synth.make_copy([synth.Analysed(img, [value], [places], "")], seed=1)
    assert len(copy.key["pages"][0]["changes"][0]["places"]) == 2
    _, locs = synth.analysis_from_json(json.loads(json.dumps(synth.analysis_to_json([value], [places]))))
    assert locs == [places]


def test_read_span_splits_cell_borders_and_keeps_punctuation():
    v = Value("EMN-260712-4194", "id", "document", (0, 0, 1, 1))
    span = locate.read_span("EMN-260712-4194|Datum:", v)
    assert span is not None and span.printed == "EMN-260712-4194" and span.start == 0 and span.end < 0.75
    name = locate.read_span("Leon Hartmann,", Value("Leon Hartmann", "person", "c", (0, 0, 1, 1)))
    assert name is not None and (name.printed, name.before, name.after) == ("Leon Hartmann", "", ",")
    date = locate.read_span(": 1. Juli 2026", Value("1. Juli 2026", "date", "d", (0, 0, 1, 1)))
    assert date is not None and (date.printed, date.before) == ("1. Juli 2026", "")
    assert date.start > 0  # the label's colon lies outside the span: it is trimmed off and kept
    comma = locate.read_span("Hartmann,", Value("Hartmann", "person", "c", (0, 0, 1, 1)))
    assert comma is not None and comma.after == ","
    assert locate.read_span("0,00%", Value("0000", "id", "d", (0, 0, 1, 1))) is None


def test_a_run_glued_to_the_next_word_is_trimmed_at_a_gap():
    img = page([(20, 20, "EMN-260712-4194"), (160, 20, "Datum:")])
    gray = img.convert("L")
    words = geometry.word_boxes(gray, geometry.ink_lines(gray)[0])
    number, label = words[0], words[-1]
    glued = (number[0], number[1], label[2], number[3])  # Tesseract made one word of both
    lines = [ocr.Line((ocr.Word("EMN-260712-4194", glued),))]
    value = Value("EMN-260712-4194", "id", "document", (0, 0, 600, 60))
    places = locate.locate(img, [value], lines, lambda crop: "EMN-260712-4194|Datum:")[0]
    assert len(places) == 1 and places[0].printed == "EMN-260712-4194"
    assert number[2] <= places[0].run_box[2] < label[0]  # the label keeps its pixels
    assert places[0].next_x is None


def test_punctuation_in_the_run_is_drawn_back():
    img = page([(20, 20, "Lieber Leon Hartmann,")])
    gray = img.convert("L")
    line = geometry.ink_lines(gray)[0]
    words = geometry.word_boxes(gray, line)
    run = (words[1][0], line[1], words[-1][2], line[3])
    value = Value("Leon Hartmann", "person", "customer", (0, 0, 600, 60))
    loc = locate.Located(value, line, run, None, "ocr", "Leon Hartmann", None, "", ",")
    reads: list[str] = []

    def read(crop: Image.Image) -> str:
        reads.append("x")
        return ""

    copy = synth.make_copy([synth.Analysed(img, [value], [[loc]], "")], seed=1, read=read)
    new = copy.key["pages"][0]["changes"][0]["new"]
    assert not new.endswith(",")  # the key holds the value; the comma is only drawn
    assert reads  # the edit was read back


def test_a_reading_that_drops_only_punctuation_keeps_the_value_form():
    span = locate.read_span("12.07", Value("12.07.", "date", "document", (0, 0, 1, 1)))
    assert span is not None and span.printed == "12.07."


def test_paint_over_spares_the_kept_boxes():
    img = Image.new("RGB", (40, 20), (0, 0, 0))
    synth.paint_over(img, (0, 0, 40, 20), [(10, 5, 20, 15)], 250)
    assert img.getpixel((2, 2)) == (250, 250, 250) and img.getpixel((15, 10)) == (0, 0, 0)
