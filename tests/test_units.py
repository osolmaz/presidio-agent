"""Exact behaviour of the pure helpers; these pin the details mutation testing probes."""

from __future__ import annotations

import random

import pytest
from PIL import Image, ImageDraw

from synthero import barcode, detect, geometry, leak, locate, match, values
from synthero.detect import Value


def blank(w: int = 100, h: int = 60) -> Image.Image:
    return Image.new("L", (w, h), 255)


def bar(img: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    ImageDraw.Draw(img).rectangle(box, fill=0)
    return img


# --- geometry ------------------------------------------------------------


def testbands_merge_short_gaps_only():
    flags = [False, True, True, False, True, False, False, True]
    assert geometry.bands(flags) == [(1, 3), (4, 5), (7, 8)]
    assert geometry.bands(flags, min_gap=2) == [(1, 5), (7, 8)]
    assert geometry.bands([True, True]) == [(0, 2)]
    assert geometry.bands([]) == []


def test_typical_line_height_is_the_median_and_ignores_empty_boxes():
    assert geometry.typical_line_height([(0, 0, 5, 10), (0, 0, 5, 20), (0, 0, 5, 12), (0, 5, 5, 5)]) == 12
    assert geometry.typical_line_height([(0, 0, 5, 2)]) == 4
    assert geometry.typical_line_height([]) == 12


def test_centre_distance():
    assert geometry.centre_distance((0, 0, 2, 2), (6, 8, 8, 10)) == 10.0
    assert geometry.centre_distance((0, 0, 4, 4), (0, 0, 4, 4)) == 0.0


def test_paper_level_and_threshold():
    img = bar(blank(10, 10), (0, 0, 9, 0))  # one dark row of ten
    assert geometry.paper_level(img) == 255
    assert geometry.ink_threshold(img) == 185
    assert geometry.paper_level(Image.new("L", (0, 0))) == 255


def test_pixels_rejects_colour_images():
    try:
        geometry.pixels(Image.new("RGB", (2, 2)))
    except ValueError as e:
        assert "grayscale" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_has_ink_counts_dark_pixels():
    img = bar(blank(), (10, 10, 13, 11))  # 8 pixels
    assert geometry.has_ink(img, (0, 0, 100, 60))
    assert not geometry.has_ink(img, (0, 0, 100, 60), min_dark=9)
    assert not geometry.has_ink(img, (50, 50, 60, 60))


def test_ink_lines_ignores_long_rules_and_splits_at_wide_gaps():
    img = blank(200, 60)
    bar(img, (0, 30, 199, 30))  # a table rule across the page
    bar(img, (10, 10, 40, 19))
    bar(img, (50, 10, 60, 19))  # close: same line
    bar(img, (150, 10, 170, 19))  # far: another column
    lines = geometry.ink_lines(img)
    assert lines == [(10, 10, 61, 20), (150, 10, 171, 20)]
    assert geometry.ink_lines(img, (0, 0, 100, 60)) == [(10, 10, 61, 20)]


def test_split_tall_box_only_when_taller_than_the_factor():
    img = blank()
    bar(img, (10, 10, 50, 19))
    bar(img, (10, 25, 50, 34))
    assert geometry.split_tall_box(img, (5, 8, 55, 36), line_height=10) == [(5, 10, 55, 20), (5, 25, 55, 35)]
    assert geometry.split_tall_box(img, (5, 8, 55, 24), line_height=10) == [(5, 8, 55, 24)]
    assert geometry.split_tall_box(blank(), (5, 8, 55, 36), line_height=10) == [(5, 8, 55, 36)]


def test_word_boxes_split_at_gaps_wider_than_a_third_of_the_height():
    img = blank()
    bar(img, (10, 10, 20, 29))
    bar(img, (24, 10, 30, 29))  # gap 3 < 7: same word
    bar(img, (40, 10, 50, 29))  # gap 9: new word
    assert geometry.word_boxes(img, (0, 10, 100, 30)) == [(10, 10, 31, 30), (40, 10, 51, 30)]


# --- match ---------------------------------------------------------------


def test_norm_and_digits():
    assert match.norm("Müller-Lüdenscheidt, 12a") == "MÜLLERLÜDENSCHEIDT12A"
    assert match.digits("DE89 3704-0044") == "8937040044"


def test_same_digits():
    assert match.same_digits("10117 Berlin", "10117 BERLN")
    assert not match.same_digits("10117 Berlin", "10178 Berlin")
    assert match.same_digits("Keller", "Kel1er")  # no digits in the value: no rule


def test_similarity_bounds():
    assert match.similarity("abc", "ABC") == 1.0
    assert match.similarity("", "abc") == 0.0
    assert match.similarity("abc", "--") == 0.0
    assert 0.5 < match.similarity("HARTMANN", "HARTMAN") < 1.0


def test_find_value_prefers_the_best_run_and_respects_the_threshold():
    lines = [["Herr", "LEON", "HARTMAN"], ["LEON", "HARTMANN", "x"]]
    assert match.find_value("LEON HARTMANN", lines) == match.Match(1, 0, 1, 1.0)
    assert match.find_value("LEON HARTMANN", [["LEO", "HART"]]) is None
    assert match.find_value("LEON HARTMANN", [["LEO", "HART"]], min_score=0.5) is not None
    # Runs may be up to two words longer than the value.
    assert match.find_value("ABCDEFGHIJ", [["AB", "CD", "EF", "GH", "IJ"]]) is None
    assert match.find_value("ABCDEFGHIJ", [["ABC", "DEF", "GHIJ"]]) == match.Match(0, 0, 2, 1.0)


def test_find_all_skips_overlaps_and_respects_digits():
    assert match.find_all("12345", [["12345", "12345"], ["12346"]]) == [
        match.Match(0, 0, 0, 1.0),
        match.Match(0, 1, 1, 1.0),
    ]
    assert match.find_all("ABCDEFGH", [["ABCDEFGX"]], min_score=0.99) == []


def test_contains():
    assert match.contains("Kd-Nr.: 60120873 x", "60120873")
    assert match.contains("6012087", "60120873")  # shorter reading, close enough
    assert not match.contains("12", "60120873")
    assert not match.contains("anything", "--")
    assert not match.contains("Kd-Nr.: 99999999", "60120873")


# --- values --------------------------------------------------------------


def test_replacer_types():
    r = values.Replacer(random.Random(5))
    p = r.identity("customer")
    assert r.replace("Leon Hartmann", "person", "customer") == f"{p.first} {p.last}"
    assert r.replace("Hartmann", "person", "customer") == p.last
    assert r.replace("Beispielallee 42", "street", "customer") == f"{p.street} {p.house}"
    assert r.replace("Beispielallee", "street", "customer") == p.street
    assert r.replace("10117 Berlin", "city", "customer") == f"{p.postal} {p.city}"
    assert r.replace("Berlin", "city", "customer") == p.city
    mail = r.replace("leon@web.de", "email", "customer")
    assert mail == mail.lower() and mail.endswith("@example.com") and "." in mail.split("@")[0]
    assert r.replace("leon@web.de", "email", "customer") == mail
    assert r.replace("12.07.2026", "date", "doc") == values.shift_dates("12.07.2026", r.day_shift)
    assert r.replace("11:10", "time", "doc") == values.shift_times("11:10", r.minute_shift)


def test_replacer_shifts_are_bounded():
    for seed in range(20):
        r = values.Replacer(random.Random(seed))
        assert 20 <= r.day_shift <= 80 and -180 <= r.minute_shift <= 180


def test_identities_have_distinct_surnames():
    r = values.Replacer(random.Random(0))
    lasts = {r.identity(f"o{i}").last for i in range(len(values.LAST))}
    assert len(lasts) == len(values.LAST)
    ident = r.identity("o0")
    assert ident.first in values.FIRST and ident.street in values.STREETS and 1 <= int(ident.house) <= 98
    assert (ident.postal, ident.city) in values.CITIES


def test_same_shape_keeps_separators_and_never_starts_with_zero():
    rng = random.Random(0)
    for _ in range(50):
        new = values.same_shape("0123-AB.cd ****", rng)
        assert new[4] == "-" and new[7] == "." and new[10:] == " ****"
        assert new[0] != "0" and new[:4].isdigit() and new[5:7].isupper() and new[8:10].islower()
    assert values.same_shape("Ä", rng) == "Ä"


def test_shift_dates_full_short_and_invalid():
    assert values.shift_dates("am 30.12.2025 bis 31.12.", 2) == "am 01.01.2026 bis 02.01."
    assert values.shift_dates("31.02.2026 und 31.02.", 1) == "31.02.2026 und 31.02."
    assert values.shift_dates("1.2.2026", 1) == "1.2.2026"


def test_shift_times_wraps_and_keeps_seconds():
    assert values.shift_times("23:50:07", 15) == "00:05:07"
    assert values.shift_times("0:10", -20) == "23:50"


def test_match_case_and_ascii_mail():
    assert values.match_case("Mira Vogt", "LEON") == "MIRA VOGT"
    assert values.match_case("Mira Vogt", "leon") == "mira vogt"
    assert values.match_case("Mira Vogt", "Leon") == "Mira Vogt"
    assert values.match_case("12", "34") == "12"
    assert values.ascii_mail("Jörg Weiß") == "joerg weiss"


# --- leak ----------------------------------------------------------------


def test_pieces():
    assert leak.pieces("Leon Hartmann") == {"LEONHARTMANN", "LEON", "HARTMANN"}
    assert leak.pieces("DE89 3704.0044-05") == {"DE893704004405", "893704004405"}
    assert leak.pieces("A 1") == set()
    assert leak.pieces("Al 12") == {"AL12"}  # the whole value counts once it has 4 characters


def test_leak_check_whole_page():
    old = [("street", "Beispielallee 42"), ("id", "60120873")]
    assert leak.check("Gartenweg 7 Nr 1234", old, context="") == []
    assert leak.check("BEISPIELALLEE 7", old, context="") == [{"type": "street", "pieces": ["BEISPIELALLEE"]}]
    assert leak.check("BEISPIELALLEE 7", old, context="Beispielallee") == []
    assert leak.check("60120873", old, context="60120873") == [{"type": "id", "pieces": ["60120873"]}]


# --- detect --------------------------------------------------------------


def test_parse_defaults_and_scaling():
    answer = [
        {"text": " Leon ", "type": "person", "bbox_2d": [100, 200, 300, 400]},
        {"text": "x@y.de", "type": "email", "owner": "  ", "bbox_2d": [1, 2, 3]},
        {"text": "x@y.de", "type": "id"},
    ]
    assert detect.parse(answer, 500, 1000) == [
        Value("Leon", "person", "document", (50, 200, 150, 400)),
        Value("x@y.de", "email", "document", (0, 0, 500, 1000)),
        Value("x@y.de", "id", "document", (0, 0, 500, 1000)),
    ]
    assert detect.parse({"text": "x"}, 10, 10) == []


# --- barcode -------------------------------------------------------------


def test_code128_round_trip_even_and_odd_lengths():
    for digits in ("842607130031480842", "4827103121075820131207202619104", "12"):
        widths = barcode.widths_for(digits)
        assert barcode.decode_widths(widths) == digits
        assert sum(widths) == 11 * len(barcode.symbols_for(digits)) + 13
    assert barcode.symbols_for("12")[-1] == (105 + 12) % 103


def test_decode_rejects_damage():
    widths = barcode.widths_for("842607130031480842")
    assert barcode.decode_widths(widths[:-1]) is None
    broken = list(widths)
    broken[6], broken[7] = broken[7], broken[6]
    assert barcode.decode_widths(broken) is None
    assert barcode.decode_widths([1] * 13) is None


def test_symbols_reject_letters():
    with pytest.raises(ValueError):
        barcode.symbols_for("12A4")


def test_draw_then_find_and_read_from_pixels():
    img = Image.new("RGB", (500, 120), "white")
    ImageDraw.Draw(img).text((40, 90), "842607130031480842", fill="black")
    barcode.draw(img, (40, 20, 40 + 3 * 134, 80), "842607130031480842", (0, 0, 0), (255, 255, 255))
    gray = img.convert("L")
    bars = barcode.find_bars(gray, (0, 0, 500, 120), line_height=10)
    assert bars is not None and bars[1] == 20 and bars[3] == 80
    row = [geometry.pixels(gray)[x, 50] < 128 for x in range(bars[0], bars[2])]
    assert barcode.decode_widths([n // 3 for n in barcode.runs(row)]) == "842607130031480842"


def test_find_bars_ignores_text_and_frames():
    img = Image.new("L", (300, 200), 255)
    d = ImageDraw.Draw(img)
    for y in range(20, 180, 14):
        d.text((20, y), "1234567890 1234567890 1234567890", fill=0)
    d.line((10, 0, 10, 199), fill=0)
    assert barcode.find_bars(img, (0, 0, 300, 200), line_height=10) is None


def test_runs():
    assert barcode.runs([False, True, True, False, True, False]) == [2, 1, 1]
    assert barcode.runs([False, False]) == []


# --- detect: compound values -----------------------------------------------


def test_split_compound_footer_line():
    v = Value("48271 0312 107 582013 12.07.2026 19:10", "id", "document", (0, 0, 1, 1))
    parts = detect.split_compound(v)
    assert [(p.text, p.type) for p in parts] == [
        ("48271", "id"),
        ("0312", "id"),
        ("107", "id"),
        ("582013", "id"),
        ("12.07.2026", "date"),
        ("19:10", "time"),
    ]
    assert detect.split_compound(Value("00 075 00", "id", "d", (0, 0, 1, 1))) == [
        Value("00 075 00", "id", "d", (0, 0, 1, 1))
    ]
    assert detect.normalise([v, Value("12.07.2026", "date", "document", (0, 0, 1, 1))])[4:] == parts[4:]


def test_close_digits():
    assert match.close_digits("66128244", "Terminal-ID 66128344")
    assert not match.close_digits("66128244", "Terminal-ID 12345")
    assert not match.close_digits("66128244", "Terminal-ID")
    assert match.close_digits("Keller", "anything")
    assert match.find_value("66128244", [["66128344"]]) is None
    assert match.find_value("66128244", [["66128344"]], strict=False) == match.Match(0, 0, 0, 0.875)


# --- geometry: frames and bars -------------------------------------------


def test_vertical_runs_removed_clears_only_long_runs():
    col = [True] * 3 + [False] + [True] * 5 + [False, True]
    assert geometry._vertical_runs_removed(col, 5) == [True] * 3 + [False] + [False] * 5 + [False, True]
    assert geometry._vertical_runs_removed(col, 6) == col
    assert geometry._vertical_runs_removed([True] * 4, 4) == [False] * 4


def test_longest_true_run():
    assert geometry.longest_true_run([True, False, True, True, False]) == 2
    assert geometry.longest_true_run([]) == 0


def test_text_mask_drops_frames_and_rules_but_keeps_letters():
    img = blank(100, 100)
    bar(img, (5, 0, 5, 99))  # a frame line down the page
    bar(img, (0, 50, 99, 50))  # a rule across it
    bar(img, (20, 20, 30, 29))  # a letter
    mask = geometry.text_mask(img, (0, 0, 100, 100), rule_px=36)
    assert not any(row[5] for row in mask)
    assert not any(mask[50])
    assert mask[25][25] and sum(map(sum, mask)) == 110  # 11 x 10, rectangles are inclusive


def test_lines_and_words_ignore_a_frame_crossing_them():
    img = blank(200, 120)
    bar(img, (8, 0, 9, 119))  # the receipt's edge
    bar(img, (20, 20, 40, 29))
    bar(img, (50, 20, 70, 29))
    bar(img, (20, 60, 70, 69))
    assert geometry.ink_lines(img) == [(20, 20, 71, 30), (20, 60, 71, 70)]
    assert geometry.word_boxes(img, (0, 20, 200, 30)) == [(20, 20, 41, 30), (50, 20, 71, 30)]


def test_a_barcode_too_narrow_for_code128_gets_a_pattern_of_the_same_width():
    img = Image.new("RGB", (200, 60), "white")
    assert not barcode.draw(img, (10, 10, 110, 50), "4827103121075820131207202619104", (0, 0, 0), (255, 255, 255))
    gray = img.convert("L")
    row = [geometry.pixels(gray)[x, 30] < 128 for x in range(0, 200)]
    assert row.index(True) == 10 and max(i for i, v in enumerate(row) if v) == 109
    widths = barcode.pattern_widths("123", 100)
    assert sum(widths) == 100 and len(widths) % 2 == 1 and min(widths) >= 1
    assert barcode.pattern_widths("123", 100) == widths and barcode.pattern_widths("124", 100) != widths


def test_overlaps():
    assert locate.overlaps((0, 0, 10, 10), (4, 4, 20, 20))  # 36 of 100
    assert not locate.overlaps((0, 0, 10, 10), (9, 9, 20, 20))
    assert not locate.overlaps((0, 0, 10, 10), (10, 0, 20, 10))


def test_code128_text_boundaries():
    assert barcode._text([105, 0, 99]) == "0099"
    assert barcode._text([105, 100]) == ""
    assert barcode._text([105, 101]) is None  # FNC/shift codes are not digits
    assert barcode._text([105, 99, 100, 16, 25]) == "9909"
    assert barcode._text([105, 100, 15]) is None  # "/" in set B
    assert barcode._text([105, 100, 26]) is None  # ":" in set B
    assert barcode._text([104, 16, 25]) == "09"
    for d in "0123456789":
        assert barcode.decode_widths(barcode.widths_for("1" + d)) == "1" + d
        assert barcode.decode_widths(barcode.widths_for("12" + d)) == "12" + d  # odd: last digit in set B


def test_find_bars_boundaries():
    img = Image.new("L", (300, 100), 255)
    d = ImageDraw.Draw(img)
    for i in range(20):  # exactly 40 runs per row: 20 bars and the 20 gaps... minus the trailing one
        d.rectangle((10 + 6 * i, 30, 12 + 6 * i, 49), fill=0)
    assert barcode.find_bars(img, (0, 0, 300, 100), line_height=10, min_runs=39) == (10, 30, 127, 50)
    assert barcode.find_bars(img, (0, 0, 300, 100), line_height=10, min_runs=40) is None
    assert barcode.find_bars(img, (0, 0, 300, 100), line_height=11, min_runs=39) is None  # 20 rows < 22
    d.rectangle((5, 0, 5, 99), fill=0)  # a frame through the block is not a bar
    assert barcode.find_bars(img, (0, 0, 300, 100), line_height=10, min_runs=39) == (10, 30, 127, 50)


def test_pattern_widths_shape():
    for n in (1, 2, 7, 50, 171):
        widths = barcode.pattern_widths("4827", n)
        assert sum(widths) == n and len(widths) % 2 == 1 and all(w >= 1 for w in widths)
    assert max(barcode.pattern_widths("4827", 400)) <= 4 + 4


def test_pieces_by_type():
    assert leak.pieces("3.450 Bits", "id") == {"3450BITS", "3450"}  # the whole value, and its digits
    assert leak.pieces("leon.hartmann@web-shop.de", "email") == {"LEONHARTMANN", "LEON", "HARTMANN"}
    assert leak.pieces("HRB 789012 B", "id") == {"HRB789012B", "789012"}
    assert leak.pieces("Leon Hartmann", "person") == {"LEONHARTMANN", "LEON", "HARTMANN"}


def test_amounts_are_never_values():
    for amount in ("146,50 EUR", "3.450 Bits", "18,50", "1.234,56 €", "152 Bits"):
        assert detect.is_amount(amount), amount
    for not_amount in ("60120873", "12.07.2026", "HRB 789012 B", "00 075 00", "DE312456789", "19:10 Uhr"):
        assert not detect.is_amount(not_amount), not_amount
    hint = (0, 0, 1, 1)
    values = [Value("146,50 EUR", "id", "d", hint), Value("146,50", "card", "d", hint), Value("1357", "id", "d", hint)]
    assert detect.normalise(values) == [Value("1357", "id", "d", hint)]


def _bars(img: Image.Image, x0: int, top: int, bottom: int, count: int = 25) -> None:
    d = ImageDraw.Draw(img)
    for i in range(count):
        d.rectangle((x0 + 6 * i, top, x0 + 6 * i + 2, bottom), fill=0)


def test_bar_rows_stop_at_the_digits_and_tolerate_small_damage():
    img = Image.new("L", (300, 100), 255)
    _bars(img, 10, 30, 49)
    d = ImageDraw.Draw(img)
    d.rectangle((10, 52, 160, 60), fill=0)  # the printed number under the bars
    d.rectangle((10, 35, 22, 35), fill=0)  # a speck across two gaps: still a bar row (2 of 150 columns differ)
    assert barcode._bar_rows(img, 10, 160, 25, 62) == (30, 50)
    d.rectangle((10, 31, 40, 31), fill=0)  # a long smear: 15 of 150 columns differ, still >= 85% the same
    assert barcode._bar_rows(img, 10, 160, 25, 62) == (30, 50)
    d.rectangle((10, 30, 100, 30), fill=0)  # most of the top row smeared: not a bar row
    assert barcode._bar_rows(img, 10, 160, 25, 62) == (31, 50)


def test_is_barcode_threshold():
    img = Image.new("L", (200, 60), 255)
    _bars(img, 0, 10, 49, count=20)  # columns 0..116
    assert barcode.is_barcode(img, (0, 10, 117, 50))
    d = ImageDraw.Draw(img)
    d.rectangle((3, 10, 5, 29), fill=0)  # gaps half filled in 3 of every 6 columns...
    d.rectangle((9, 10, 11, 29), fill=0)
    assert barcode.is_barcode(img, (0, 10, 117, 50))  # ...in two places only: 6 of 117 columns
    for i in range(20):
        d.rectangle((6 * i + 3, 10, 6 * i + 5, 29), fill=0)  # every gap half ink: half the columns
    assert not barcode.is_barcode(img, (0, 10, 117, 50))
    assert barcode.is_barcode(img, (0, 10, 117, 50), min_share=0.45)


def test_find_all_splits_side_by_side_codes_only_at_wide_gaps():
    img = Image.new("L", (400, 100), 255)
    _bars(img, 10, 20, 49)  # 10..156
    _bars(img, 190, 20, 49)  # gap of 34 px
    assert [b[0] for b in barcode.find_all(img, line_height=10)] == [10, 190]  # 34 > 3 * 10
    assert [b[0] for b in barcode.find_all(img, line_height=12)] == [10]  # 34 < 36: one block
    assert barcode.find_all(img, line_height=16) == []  # 30 rows < 2 * 16


def test_find_value_run_lengths_and_threshold():
    words = [["AB", "CD", "EF", "GH"]]
    assert match.find_value("ABCDEF", words) == match.Match(0, 0, 2, 1.0)  # a 1-word value spans up to 3 words
    assert match.find_value("ABCDEFGH", words, min_score=0.9) is None  # would need 4
    assert match.find_value("AB CDEFGH", words) == match.Match(0, 0, 3, 1.0)  # a 2-word value spans up to 4
    assert match.find_value("ABCDEFX", [["ABCDEFG"]], min_score=6 / 7) == match.Match(0, 0, 0, 6 / 7)
    assert match.find_all("ABC", [["ABC", "ABC", "ABC"]]) == [match.Match(0, i, i, 1.0) for i in range(3)]
