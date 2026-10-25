"""Phase K JK15 (2026-10-24): the pack-blind anchor (taxfill_core.anchor) on synthetic blanks.

Every pitfall KG6 names gets an offline case here: numbers inside captions, a number on the row above or below,
two amount columns on one row, a box captioned above it, a /TU (or a worded field name) naming another row (P-032's
rotated names), multi-widget fields, and a page whose text runs vertically. The tier gate is tested both ways: with
no table and with a failing one, nothing above "low" is emitted, and "high" is never emitted at all.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from taxfill_core import anchor as A

from pdf_fixtures import make_acroform_pdf

ANCHOR_SRC = Path(A.__file__)
LEADER = "." * 40
BOX_X = 470.0


def _rows(rows, *, page=1, top=700.0, pitch=24.0, beside=True):
    """IRS-style rows: gutter number, caption, leaders, the number again beside the amount box."""
    texts, fields = [], []
    for i, row in enumerate(rows):
        num, caption, name = row[:3]
        extra = row[3] if len(row) > 3 else {}
        y = top - i * pitch
        if num:
            texts.append((page, 40, y, num))
        texts.append((page, 60, y, caption))
        texts.append(_leader(page, 60, y, caption))
        if num and beside:
            texts.append((page, BOX_X - 18, y, num))
        if name:
            fields.append({"name": name, "page": page, "x": BOX_X, "y": y - 4, "width": 90, "height": 14, **extra})
    return texts, fields


def _leader(page, x, y, caption, end=BOX_X - 22):
    """Dot leaders from the end of a caption to the beside column, as printed forms run them."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    start = x + stringWidth(caption, "Helvetica", 9) + 3
    dots = int((end - start) / stringWidth(".", "Helvetica", 9))
    return (page, start, y, "." * max(dots, 3))


def _pdf(tmp_path, texts, fields, name="blank.pdf"):
    return make_acroform_pdf(tmp_path / name, fields, texts=texts, draw_labels=False)


def _by_field(amap):
    return {(w.field, w.widget_index): w for w in amap.widgets}


@pytest.fixture
def passing_table(tmp_path):
    # licensing fails closed (round 3): the top tier needs top_tier_kinds to name the widget group
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": True,
                                    "thresholds": {"top": 3.0, "med": 2.0}, "top_tier_kinds": ["text"]}),
                    encoding="utf-8")
    return path


@pytest.fixture
def failing_table(tmp_path):
    path = tmp_path / "failing.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": False,
                                    "thresholds": {"top": 3.0, "med": 2.0}}), encoding="utf-8")
    return path


BASIC = [
    ("1", "Wages, salaries, tips", "A1"),
    ("2", "Taxable interest", "A2"),
    ("3", "Ordinary dividends", "A3"),
    ("4", "Other income", "A4"),
    ("5", "Total income. Add lines 1 through 4", "A5"),
]


# ── blindness ─────────────────────────────────────────────────────────────────


def test_anchor_module_is_blind_to_packs():
    tree = ast.parse(ANCHOR_SRC.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = ("taxfill_core.schemas", "taxfill_core.discovery", "taxfill_core.handfill", "taxfill_core.knowledge",
              "taxfill_core.overlay", "taxfill_core.filler", "taxfill_core.verify", "PIL")
    assert not [m for m in imported if m.startswith(banned)], imported
    third_party = {m.split(".")[0] for m in imported} - {"__future__", "ctypes", "hashlib", "math", "re", "collections",
                                                          "dataclasses", "pathlib", "taxfill_core", "yaml"}
    assert third_party == {"pypdfium2"}, third_party  # pypdf comes in through packbuild.extract_fields
    doc = ast.get_docstring(tree)
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [x for x in strings if "pack.yaml" in x and x.strip() != (doc or "").strip()]


# ── text runs ─────────────────────────────────────────────────────────────────


def test_text_runs_are_user_space_words_with_boxes(tmp_path):
    pdf = _pdf(tmp_path, [(1, 96, 600, "1 a Total amount"), (2, 300, 100, "21.")], [])
    runs = A.text_runs(pdf)
    texts = [(r.page, r.text) for r in runs]
    assert (1, "1") in texts and (1, "a") in texts and (1, "Total") in texts and (2, "21.") in texts
    one = next(r for r in runs if r.text == "1")
    assert 95 <= one.x0 < one.x1 <= 104 and 598 <= one.y0 < one.y1 <= 610  # bottom-left origin, PDF points


# ── the tier gate ─────────────────────────────────────────────────────────────


def test_without_a_table_nothing_above_low_is_emitted(tmp_path):
    texts, fields = _rows(BASIC)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=tmp_path / "missing.yaml")
    assert [w.printed_line for w in amap.widgets] == ["1", "2", "3", "4", "5"]
    assert {w.confidence for w in amap.widgets} == {A.LOW}
    assert set(amap.fields.values()) == {A.LOW}
    assert amap.basis["table"] is None and amap.basis["tiers"] == [A.LOW, A.NONE]


def test_a_failing_table_licenses_nothing_above_low(tmp_path, failing_table):
    texts, fields = _rows(BASIC)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=failing_table)
    assert {w.confidence for w in amap.widgets} <= {A.LOW, A.NONE}
    assert amap.basis["passed"] is False and "passed is false" in amap.basis["note"]


def test_a_table_for_another_method_licenses_nothing(tmp_path):
    path = tmp_path / "other.yaml"
    path.write_text(yaml.safe_dump({"method": "jk15-v0", "passed": True, "thresholds": {"top": 1, "med": 0.5}}))
    texts, fields = _rows(BASIC)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=path)
    assert {w.confidence for w in amap.widgets} == {A.LOW}


def test_a_passing_table_licenses_the_top_tier_and_high_is_never_emitted(tmp_path, passing_table):
    texts, fields = _rows(BASIC)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    assert {w.confidence for w in amap.widgets} == {A.TOP}
    assert A.TOP == "anchored (unverified line map)"
    assert "high" not in A.TIERS and all("high" not in w.confidence for w in amap.widgets)
    assert all(w.evidence[:2] == [f"beside:{w.printed_line}", f"gutter:{w.printed_line}"] for w in amap.widgets)
    assert amap.basis["passed"] is True and A.TOP in amap.basis["tiers"]


def test_anchor_basis_names_the_table(tmp_path, passing_table, failing_table):
    good = A.anchor_basis(passing_table)
    assert good["passed"] is True and len(good["sha256"]) == 16 and good["table"].endswith("benchmark.yaml")
    assert "unverified line map" in good["note"]
    bad = A.anchor_basis(failing_table)
    assert bad["passed"] is False and bad["tiers"] == [A.LOW, A.NONE] and bad["table"].endswith("failing.yaml")
    none = A.anchor_basis(tmp_path / "absent.yaml")
    assert none["table"] is None and "no anchor benchmark table has passed" in none["note"]


def test_the_committed_table_has_not_passed_until_adjudicated():
    table = A.load_table()
    if table is None:
        pytest.skip("no committed table yet")
    basis = A.anchor_basis()
    if table.get("passed") is not True:
        assert basis["tiers"] == [A.LOW, A.NONE]
    assert table.get("method") == A.METHOD


# ── pitfalls ──────────────────────────────────────────────────────────────────


def test_numbers_inside_captions_are_never_designators(tmp_path, passing_table):
    texts, fields = _rows(BASIC + [("10", "Add lines 1 through 9", "L10")])
    # rows with no designator whose caption ends in a number right before the box
    for i, tail in enumerate(["see page 12", "for 2025", "up to $1,500", "rate of 6%", "from Form 8812",
                              "from Form 940", "lines 1, 2, and 9"]):
        y = 500 - i * 24
        texts.append((1, 300, y, f"Credit {tail}"))
        width = len(f"Credit {tail}") * 4.6
        fields.append({"name": f"C{i}", "x": 300 + width + 4, "y": y - 4, "width": 90, "height": 14})
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    got = {w.field: w.printed_line for w in amap.widgets}
    assert got["L10"] == "10"
    assert {got[f"C{i}"] for i in range(7)} == {None}, got


def test_a_number_on_the_row_above_or_below_is_not_borrowed(tmp_path, passing_table):
    texts = [(1, 40, 600, "4"), (1, 60, 600, "Line four"), (1, 40, 570, "6"), (1, 60, 570, "Line six"),
             (1, 40, 585 + 13, "5")]  # a stray "5" half a row above the middle box
    fields = [{"name": "MID", "x": BOX_X, "y": 581, "width": 90, "height": 10}]
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    (w,) = amap.widgets
    assert w.printed_line is None


def test_two_amount_columns_share_the_row_and_stay_below_the_top_tier(tmp_path, passing_table):
    texts, fields = _rows(BASIC[:4])
    texts.append((1, 40, 580, "7"))
    texts.append((1, 60, 580, "Gains and losses"))
    texts.append((1, 300, 580, "7"))
    fields += [{"name": "L7A", "x": 320, "y": 576, "width": 70, "height": 14},
               {"name": "L7B", "x": 400, "y": 576, "width": 70, "height": 14}]
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert w["L7A"].printed_line == w["L7B"].printed_line == "7"
    assert "multi_column_row" in w["L7A"].evidence and "multi_column_row" in w["L7B"].evidence
    assert A.TOP not in (w["L7A"].confidence, w["L7B"].confidence)
    assert w["A1"].confidence == A.TOP


def test_a_box_captioned_above_takes_its_label_not_a_line(tmp_path, passing_table):
    texts, fields = _rows(BASIC)
    texts.append((1, 60, 300, "Your first name and middle initial"))
    fields.append({"name": "FIRST", "x": 58, "y": 280, "width": 200, "height": 14})
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}["FIRST"]
    assert w.printed_line is None and w.label == "Your first name and middle initial"
    assert w.confidence == A.LOW


def test_a_tooltip_naming_another_line_lowers_the_tier(tmp_path, passing_table):
    rows = [("20", "Income tax", "L20", {"tooltip": "Line 20. Income tax"}),
            ("21", "Nonresident credit", "L21", {"tooltip": "Line 22. Total tax"}),
            ("22", "Total tax", "L22", {"tooltip": "Line 23. Tax credits"}),
            ("23", "Tax credits", "L23", {"tooltip": "Line 21. Nonresident credit"}),
            ("24", "Net tax", "L24", {"tooltip": "Line 24. Net tax"})]
    texts, fields = _rows(rows)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    for name, printed, named in (("L21", "21", "22"), ("L22", "22", "23"), ("L23", "23", "21")):
        assert w[name].printed_line == printed
        assert f"tu_other_line:{named}" in w[name].evidence
        assert w[name].confidence == A.LOW
    assert w["L20"].confidence == w["L24"].confidence == A.TOP and "tu_line:20" in w["L20"].evidence


def test_rotated_widget_names_lower_the_tier_p032(tmp_path, passing_table):
    rows = [("19", "TAXABLE INCOME", "Form Taxable income"),
            ("20", "INCOME TAX", "Form Income tax"),
            ("21", "NONRESIDENT CREDIT", "Form Total tax"),
            ("22", "TOTAL TAX", "Form Tax credits"),
            ("23", "NONREFUNDABLE TAX CREDITS", "Form Nonresident credit"),
            ("24", "NET TAX", "Form Net tax")]
    texts, fields = _rows(rows)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    for name, printed in (("Form Total tax", "21"), ("Form Tax credits", "22"), ("Form Nonresident credit", "23")):
        assert w[name].printed_line == printed  # the row, never the name
        assert "tu_words_other_row" in w[name].evidence and w[name].confidence == A.LOW
    assert w["Form Net tax"].confidence == A.TOP and "tu_words_same_row" in w["Form Net tax"].evidence


def test_every_widget_of_a_field_is_anchored_and_the_field_takes_the_lowest(tmp_path, passing_table):
    texts, fields = _rows(BASIC)
    texts += [(1, 40, 540, "8"), (1, 60, 540, "Choice eight"), _leader(1, 60, 540, "Choice eight"),
              (1, BOX_X - 18, 540, "8")]
    fields += [{"name": "R", "kind": "radio", "on_value": "/1", "x": BOX_X, "y": 536, "size": 12},
               {"name": "R", "kind": "radio", "on_value": "/2", "x": BOX_X, "y": 200, "size": 12}]
    # page 2: a carry-forward box whose caption repeats line 5 — that number is caption text
    texts += [(2, 60, 700, "Amount from line 5"), _leader(2, 60, 700, "Amount from line 5")]
    fields.append({"name": "L5_ECHO", "page": 2, "x": BOX_X, "y": 696, "width": 90, "height": 14})
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = _by_field(amap)
    assert w[("R", 0)].printed_line == "8" and w[("R", 1)].printed_line is None
    assert w[("R", 1)].confidence == A.NONE and amap.fields["R"] == A.NONE
    echo = w[("L5_ECHO", 0)]
    assert echo.printed_line is None and echo.label == "Amount from line 5"


def test_sub_letter_rows_take_their_head_number(tmp_path, passing_table):
    texts, fields = _rows(BASIC)
    texts += [(1, 40, 560, "6"), (1, 60, 560, "Payments:")]
    for i, letter in enumerate("abc"):
        y = 536 - i * 24
        texts += [(1, 52, y, f"{letter}."), (1, 64, y, f"Payment kind {letter}"),
                  _leader(1, 64, y, f"Payment kind {letter}"),
                  (1, BOX_X - 18, y, f"6{letter}")]
        fields.append({"name": f"L6{letter}", "x": BOX_X, "y": y - 4, "width": 90, "height": 14})
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert [w[f"L6{x}"].printed_line for x in "abc"] == ["6a", "6b", "6c"]
    assert all(f"gutter_sub:6{x}" in w[f"L6{x}"].evidence for x in "abc")


def test_a_page_whose_text_runs_vertically_is_read_in_its_own_frame(tmp_path, passing_table):
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    raw = tmp_path / "rot.pdf"
    canv = canvas.Canvas(str(raw), pagesize=(612, 792))
    for i, (num, caption) in enumerate([("1", "Wages"), ("2", "Interest"), ("3", "Dividends")]):
        x = 500 - i * 24
        for text, y in ((num, 40), (caption, 60), (LEADER, 250), (num, BOX_X - 18)):
            canv.saveState()
            canv.translate(x, y)
            canv.rotate(90)
            canv.setFont("Helvetica", 9)
            canv.drawString(0, 0, text)
            canv.restoreState()
        canv.acroForm.textfield(name=f"L{num}", x=x - 10, y=BOX_X, width=14, height=90)
    canv.save()
    writer = PdfWriter(clone_from=PdfReader(str(raw)))
    writer.pages[0].rotate(90)
    out = tmp_path / "rotated.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    amap = A.anchor_widgets(out, table=passing_table)
    assert {w.field: w.printed_line for w in amap.widgets} == {"L1": "1", "L2": "2", "L3": "3"}
    assert all(w.rect[2] - w.rect[0] < w.rect[3] - w.rect[1] for w in amap.widgets)  # rects stay user space


def test_normalize_line_and_tooltip_lines():
    assert [A.normalize_line(t) for t in ("21", "21.", "(5a)", "05A:", "0", "2025", "$1,500", "6%", "a")] == [
        "21", "21", "5a", "5a", None, None, None, None, None]
    assert A._tu_line("Line 1a. Total amount from Form(s) W-2") == "1a"
    assert A._tu_line("11. Adjusted gross income") == "11"
    assert A._tu_line("Enter the amount from line 23") is None
    assert A._name_line("topmostSubform[0].Page1[0].Line16[0]") == "16" and A._name_line("f1_47[0]") is None


# ── Phase K JK15 (2026-10-24) round 2: multi-column rows, repeated designators, the /TU cap, the passed gate ──


def _de_rows(n=4, *, b_marker="designator"):
    """Delaware PIT-RES style: "N." before Column A (the spouse), ".00" after it, then Column B's marker: "N." again
    ("designator"), nothing ("none"), or a printed column letter "B" that names no line ("letter")."""
    texts, fields = [], []
    for i in range(n):
        num, y = str(i + 1), 640 - i * 18
        caption = f"Income item {'abcdefgh'[i]}"
        texts += [(1, 40, y, f"{num}."), (1, 60, y, caption), _leader(1, 60, y, caption, end=286),
                  (1, 300, y, f"{num}."), (1, 380, y, ".00"), (1, 480, y, ".00")]
        if b_marker != "none":
            texts.append((1, 395, y, f"{num}." if b_marker == "designator" else "B"))
        fields += [{"name": f"ln{num}ColA", "x": 318, "y": y - 3, "width": 60, "height": 12},
                   {"name": f"ln{num}ColB", "x": 418, "y": y - 3, "width": 60, "height": 12}]
    return texts, fields


@pytest.mark.parametrize("b_marker", ["designator", "none", "letter"])
def test_a_two_column_row_never_reaches_the_top_tier(tmp_path, passing_table, b_marker):
    texts, fields = _de_rows(b_marker=b_marker)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    for n in "1234":
        a, b = w[f"ln{n}ColA"], w[f"ln{n}ColB"]
        assert a.printed_line == n and "multi_column_row" in a.evidence, a
        assert "multi_column_row" in b.evidence, b
        assert A.TOP not in (a.confidence, b.confidence), (a, b)
        if b_marker == "designator":
            # ".00" closes Column A, so the "N." after it is Column B's own designator, not caption text
            assert b.printed_line == n and f"beside:{n}" in b.evidence, b
        elif b_marker == "letter":
            # Column B gets no line at all, yet Column A is capped: the cap does not wait for the neighbour's line
            assert b.printed_line is None and not any(e.startswith("repeated_line") for e in a.evidence), (a, b)


def test_a_designator_repeated_on_one_page_stays_below_the_top_tier(tmp_path, passing_table):
    part1, f1 = _rows([("1", "Part one first", "P1L1"), ("2", "Part one second", "P1L2"),
                       ("3", "Part one third", "P1L3"), ("4", "Part one fourth", "P1L4")], top=700)
    part2, f2 = _rows([("1", "Part two first", "P2L1"), ("2", "Part two second", "P2L2"),
                       ("3", "Part two third", "P2L3")], top=500)
    page2, f3 = _rows([("1", "Other page first", "Q1"), ("2", "Other page second", "Q2"),
                       ("3", "Other page third", "Q3")], page=2)
    amap = A.anchor_widgets(_pdf(tmp_path, part1 + part2 + page2, f1 + f2 + f3), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    for n in "123":
        for name in (f"P1L{n}", f"P2L{n}"):
            assert w[name].printed_line == n and f"repeated_line:{n}" in w[name].evidence
            assert w[name].confidence != A.TOP, w[name]
        assert w[f"Q{n}"].confidence == A.TOP  # once on its own page: the designator identifies the box
    assert w["P1L4"].confidence == A.TOP


def test_a_tooltip_naming_another_line_caps_even_when_its_words_match_no_row(tmp_path, passing_table):
    rows = [("6", "Gains", "L6", {"tooltip": "Line 6. Gains"}),
            ("7", "Losses", "L7", {"tooltip": "Line 9. Zebra quantum"}),
            ("8", "Rents", "L8", {"tooltip": "Line 8. Rents"})]
    texts, fields = _rows(rows)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert w["L7"].printed_line == "7" and "tu_other_line:9" in w["L7"].evidence
    assert "tu_words_other_row" not in w["L7"].evidence  # only the /TU line cap can lower it
    assert w["L7"].confidence == A.LOW
    assert w["L6"].confidence == w["L8"].confidence == A.TOP


@pytest.mark.parametrize("passed", ["yes", "true", 1, "True"])
def test_a_table_whose_passed_is_not_exactly_true_licenses_nothing(tmp_path, passed):
    path = tmp_path / "truthy.yaml"
    path.write_text(yaml.safe_dump({"method": A.METHOD, "passed": passed, "thresholds": {"top": 3.0, "med": 2.0}}))
    texts, fields = _rows(BASIC)
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=path)
    assert {w.confidence for w in amap.widgets} == {A.LOW}
    assert amap.basis["passed"] is False and amap.basis["tiers"] == [A.LOW, A.NONE]


def _button_rows(kind, nums=("6", "7"), name="box7"):
    """Two rows whose only widget is a button that scores at the top: one radio group with an option on each row,
    or a checkbox on each row (``name`` and ``name + "b"``)."""
    rows = []
    for i, num in enumerate(nums):
        if kind == "radio":
            extra = {"kind": "radio", "on_value": f"/{i + 1}", "size": 10}
            rows.append((num, f"Check if event {'AB'[i]} applies", name, extra))
        else:
            extra = {"kind": "checkbox", "width": 10, "height": 10}
            rows.append((num, f"Check if event {'AB'[i]} applies", name + ("b" if i else ""), extra))
    return rows


def _first(amap):
    return _first_of(amap.widgets)


def _first_of(widgets):
    return {w.field: w for w in reversed(widgets)}  # each field's first widget


@pytest.mark.parametrize("kind", ["checkbox", "radio"])
def test_the_top_tier_is_licensed_per_widget_kind(tmp_path, kind):
    """Phase K JK15 round 2: the TEST checkboxes measured 10/11 at the top tier, so the committed table licenses the
    top tier for text boxes only (top_tier_kinds); a checkbox or radio button that scores at the top is capped at med,
    and says why. Round 3: licensing fails closed, so a table of this METHOD whose top_tier_kinds is missing or not a
    list licenses NO group for the top tier."""
    texts, fields = _rows([*_button_rows(kind), ("8", "Total amount", "amt8")])
    blank = _pdf(tmp_path, texts, fields)
    table = tmp_path / "kinds.yaml"
    base = {"method": A.METHOD, "passed": True, "thresholds": {"top": 3.0, "med": 2.0}}
    table.write_text(yaml.safe_dump({**base, "top_tier_kinds": ["text"]}))
    amap = A.anchor_widgets(blank, table=table)
    by = _first(amap)
    assert by["box7"].kind == kind
    assert by["amt8"].confidence == A.TOP
    assert by["box7"].score >= 3.0 and by["box7"].confidence == A.MED
    assert "top_kind_not_licensed:checkbox" in by["box7"].evidence
    assert amap.basis["top_tier_kinds"] == ["text"] and "text widgets only" in amap.basis["note"]
    for kinds in (None, "text", {"text": True}):
        doc = dict(base) if kinds is None else {**base, "top_tier_kinds": kinds}
        table.write_text(yaml.safe_dump(doc))
        amap = A.anchor_widgets(blank, table=table)
        assert {w.confidence for w in amap.widgets} == {A.MED}, kinds
        assert amap.basis["top_tier_kinds"] == [] and "no widget group" in amap.basis["note"]


def test_the_committed_table_keeps_checkboxes_and_radios_below_the_top_tier(tmp_path):
    """Round 3: the committed table, as committed and with its passed forced true, never licenses a top-scoring
    checkbox or radio button for the top tier."""
    committed = A.table_path()
    if not committed.is_file():
        pytest.skip("no committed table yet")
    texts, fields = _rows([*_button_rows("checkbox", ("4", "5")), *_button_rows("radio", ("6", "7"), "radio8"),
                           ("8", "Total", "amt9")])
    blank = _pdf(tmp_path, texts, fields)
    forced = tmp_path / "forced.yaml"
    forced.write_text(yaml.safe_dump({**A.load_table(committed), "passed": True}))
    for table in (committed, forced):
        widgets = A.anchor_widgets(blank, table=table).widgets
        buttons = [w for w in widgets if w.kind in ("checkbox", "radio")]
        assert {w.kind for w in buttons} == {"checkbox", "radio"} and len(buttons) == 4
        assert all(w.score >= 3.0 for w in buttons), buttons
        assert all(w.confidence != A.TOP for w in buttons), table
        by = _first_of(widgets)
    doc = A.load_table(committed)
    if doc.get("method") == A.METHOD and "text" in (doc.get("top_tier_kinds") or []):
        assert by["amt9"].confidence == A.TOP  # the same table does license the text box beside them


def test_the_committed_table_licenses_the_top_tier_for_text_only():
    table = A.load_table()
    if table is None or table.get("passed") is not True:
        pytest.skip("the committed table has not passed")
    assert table["top_tier_kinds"] == ["text"], "checkboxes measured 10/11 at the top tier in TEST run 2"


# ── Phase K JK15 (2026-10-24) round 3: the row-identification invariant ──


def _gutter_rows(nums, top):
    return _rows([(n, f"Ordinary item {n}", f"L{n}") for n in nums], top=top)


def test_a_count_box_before_the_amount_box_never_takes_the_rows_top_tier(tmp_path, passing_table):
    """Georgia 500 line 14: "14. Enter the number from Line 7c. [count] Multiply by $4,000 ...... 14. [amount]". The
    count box has the gutter "14." and a /TU naming 14; caption words stand between it and the amount box, whose "14."
    stands too far left to be its beside designator. A fill by line 14 must not put the amount into the count box."""
    texts, fields = _gutter_rows(["11", "12", "13"], 700)
    y = 628
    texts += [(1, 40, y, "14."), (1, 60, y, "Enter the number from Line 7c."), (1, 202, y, "Multiply by $4,000"),
              _leader(1, 202, y, "Multiply by $4,000", end=340), (1, 343, y, "14.")]
    fields += [{"name": "L14_7C", "x": 176, "y": y - 4, "width": 18, "height": 14, "tooltip": "Line 14. Number"},
               {"name": "L14", "x": BOX_X, "y": y - 4, "width": 90, "height": 14, "tooltip": "Line 14. Amount"}]
    more, more_f = _gutter_rows(["15", "16"], 604)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    count = w["L14_7C"]
    assert count.printed_line == "14" and count.confidence != A.TOP, count
    assert w["L14"].confidence != A.TOP, w["L14"]
    assert "shared_row:L14" in count.evidence and count.score <= A.CAP_SHARED_ROW, count
    assert w["L13"].confidence == w["L15"].confidence == A.TOP  # rows with one box keep it


def test_a_year_box_before_the_amount_box_never_takes_the_rows_top_tier(tmp_path, passing_table):
    """1040-X line 23: "23 Amount of line 21 you want applied to your (enter year): [year] estimated tax 23 [amount]".
    "tax 23" reads as caption text, so the amount box gets no line; the year box must not take line 23's top tier."""
    texts, fields = _gutter_rows(["20", "21", "22"], 700)
    y = 628
    texts += [(1, 40, y, "23"), (1, 60, y, "Amount of line 21 you want applied to your (enter year):"),
              (1, 320, y, "estimated tax 23")]
    fields += [{"name": "f2_06", "x": 284, "y": y - 4, "width": 34, "height": 14,
                "tooltip": "23. Amount of line 21 you want applied to your (enter year):"},
               {"name": "f2_07", "x": 400, "y": y - 4, "width": 70, "height": 14,
                "tooltip": "23. Amount of line 21 you want applied to your (year) estimated tax."}]
    more, more_f = _gutter_rows(["24", "25"], 604)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    year = w["f2_06"]
    assert year.printed_line == "23" and "shared_row:f2_07" in year.evidence, year
    assert year.confidence != A.TOP and w["f2_07"].confidence != A.TOP, (year, w["f2_07"])
    assert w["L22"].confidence == w["L24"].confidence == A.TOP


def test_two_boxes_each_with_its_own_designator_beside_both_keep_the_top_tier(tmp_path, passing_table):
    """The 1040 "2a Tax-exempt interest . . 2a [box] b Taxable interest . . 2b [box]" row: every box in the band has
    its own distinct beside designator, so each designator identifies its box and both keep the top tier."""
    texts, fields = _gutter_rows(["1"], 700)
    y = 676
    texts += [(1, 40, y, "2a"), (1, 60, y, "Tax-exempt interest"), _leader(1, 60, y, "Tax-exempt interest", end=190),
              (1, 196, y, "2a"), (1, 300, y, "b"), (1, 310, y, "Taxable interest"),
              _leader(1, 310, y, "Taxable interest"), (1, BOX_X - 18, y, "2b")]
    fields += [{"name": "f1_58", "x": 212, "y": y - 4, "width": 80, "height": 14, "tooltip": "Line 2a. Tax-exempt"},
               {"name": "f1_59", "x": BOX_X, "y": y - 4, "width": 90, "height": 14, "tooltip": "Line 2b. Taxable"}]
    more, more_f = _gutter_rows(["3", "4"], 652)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert w["f1_58"].printed_line == "2a" and "beside:2a" in w["f1_58"].evidence, w["f1_58"]
    assert w["f1_59"].printed_line == "2b" and "beside:2b" in w["f1_59"].evidence, w["f1_59"]
    assert w["f1_58"].confidence == w["f1_59"].confidence == A.TOP, (w["f1_58"], w["f1_59"])
    assert not any(e.startswith("shared_row:") for x in (w["f1_58"], w["f1_59"]) for e in x.evidence)


def test_a_cap_keeps_a_widget_below_the_top_tier_whatever_the_thresholds():
    """tier_for never gives the top tier to a widget that carries a cap's evidence, even under a table whose top
    threshold sits at or below the cap."""
    th = {"top": 1.0, "med": 0.5, "top_kinds": frozenset({"text"})}
    for ev in ("shared_row:L14", "multi_column_row", "repeated_line:2"):
        a = A.WidgetAnchor(field="X", widget_index=0, page=1, rect=[0, 0, 1, 1], kind="text", printed_line="14",
                           score=A.CAP_SHARED_ROW, evidence=[ev])
        assert A.tier_for(a, th) == A.MED, ev
    a = A.WidgetAnchor(field="X", widget_index=0, page=1, rect=[0, 0, 1, 1], kind="text", printed_line="14", score=2.0)
    assert A.tier_for(a, th) == A.TOP


# ── Phase K JK15 (2026-10-24) round 4: the one-to-one rule (a designator maps to one box on the page) ──


def _same_line(w):
    return [e for e in w.evidence if e.startswith("same_line:")]


def test_a_count_box_on_the_designator_line_never_takes_the_top_tier_from_the_amount_box_below(tmp_path,
                                                                                               passing_table):
    """Wisconsin Form 1 line 30: "30 Earned income credit. Number of qualifying children . . > [count]" on the first
    printed line, "Federal credit" on the next, and "(see instructions) [credit] .00 x [pct] % = . . . . 30 [amount]"
    two printed lines lower. The amount box is capped (two columns on its row), so it was no rival; the count box kept
    line 30's top tier. A fill by line 30 must not put the credit into the count box."""
    texts, fields = _gutter_rows(["27", "28", "29"], 700)
    y = 628
    texts += [(1, 40, y, "30"), (1, 60, y, "Earned income credit. Number of qualifying children"),
              _leader(1, 60, y, "Earned income credit. Number of qualifying children", end=282)]
    fields.append({"name": "30", "x": 289, "y": y - 4, "width": 29, "height": 14,
                   "tooltip": "Line 30. Number of qualifying children"})
    texts += [(1, 60, y - 12, "Federal credit")]
    y2 = y - 24
    texts += [(1, 60, y2, "(see instructions)"), (1, 216, y2, "x"), (1, 264, y2, "%"), (1, 272, y2, "="),
              (1, 282, y2, "." * 30), (1, BOX_X - 18, y2, "30")]
    fields += [{"name": "30a", "x": 140, "y": y2 - 4, "width": 70, "height": 14},
               {"name": "30percent", "x": 226, "y": y2 - 4, "width": 34, "height": 14},
               {"name": "line30", "x": BOX_X, "y": y2 - 4, "width": 90, "height": 14,
                "tooltip": "Line 30. Earned income credit"}]
    more, more_f = _gutter_rows(["31", "32"], 580)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    count, amount = w["30"], w["line30"]
    assert count.printed_line == "30" and amount.printed_line == "30", (count, amount)
    assert count.confidence != A.TOP and "same_line:line30" in count.evidence, count
    assert count.score <= A.CAP_SAME_LINE, count
    assert amount.confidence != A.TOP and "same_line:30" in amount.evidence, amount
    assert w["L29"].confidence == w["L31"].confidence == A.TOP  # their designators map to one box each


def test_a_description_box_on_the_designator_line_never_takes_the_top_tier_from_the_amount_box_below(
        tmp_path, passing_table):
    """Form 2555 line 23: "23 Any other foreign earned income ... List type [description]" on the designator line,
    then a full-width continuation box and "23 [amount]" one printed line lower. The amount box is capped by the
    continuation box on its row, so it was no rival; the description box kept line 23's top tier."""
    texts, fields = _rows([("21", "Ordinary item 21", "L21", {"tooltip": "Line 21. Item"}),
                           ("22", "Ordinary item 22", "L22", {"tooltip": "Line 22. Item"})], top=700, pitch=12)
    y = 676
    texts += [(1, 40, y, "23"), (1, 60, y, "Any other foreign earned income. List type")]
    fields.append({"name": "desc23", "x": 260, "y": y - 3, "width": 190, "height": 12,
                   "tooltip": "Line 23. Any other foreign earned income. List type"})
    y2 = y - 12
    texts.append((1, BOX_X - 18, y2, "23"))
    fields += [{"name": "desc23b", "x": 60, "y": y2 - 3, "width": 380, "height": 12},
               {"name": "amt23", "x": BOX_X, "y": y2 - 3, "width": 90, "height": 12,
                "tooltip": "Line 23. Amount"}]
    more, more_f = _rows([("24", "Ordinary item 24", "L24", {"tooltip": "Line 24. Item"}),
                          ("25", "Ordinary item 25", "L25", {"tooltip": "Line 25. Item"})], top=y2 - 12, pitch=12)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    desc, amount = w["desc23"], w["amt23"]
    assert desc.printed_line == "23" and amount.printed_line == "23" and "beside:23" in amount.evidence, (desc, amount)
    assert desc.confidence != A.TOP and "same_line:amt23" in desc.evidence, desc
    assert amount.confidence != A.TOP, amount
    assert w["L22"].confidence == w["L24"].confidence == A.TOP


def test_a_box_with_the_designator_printed_beside_it_is_a_rival_even_when_it_got_no_line(tmp_path, passing_table):
    """Wisconsin 2023 line 15a: "a Rent paid - heat included [rent]" takes 15a from its gutter letter, while the
    credit box half a line lower reads "Find credit from 15a [credit]": "from 15a" reads as caption text, so the credit
    box gets no line at all. "15a" is still printed immediately before it, so 15a names two boxes."""
    texts, fields = _gutter_rows(["13", "14"], 700)
    texts += [(1, 40, 652, "15"), (1, 60, 652, "School property tax credit")]
    rows = [("a", 630, "Rent paid - heat included", "rent15a"), ("b", 594, "Property taxes paid", "tax15b"),
            ("c", 576, "Other property paid", "oth15c")]
    for letter, y, caption, name in rows:
        texts += [(1, 52, y, letter), (1, 64, y, caption)]
        fields.append({"name": name, "x": 195, "y": y - 4, "width": 73, "height": 14,
                       "tooltip": f"Line 15{letter}; {caption}"})
    y = 612
    texts += [(1, 384, y, "Find credit from"), (1, BOX_X - 18, y, "15a")]
    fields.append({"name": "credit15a", "x": BOX_X, "y": y - 3, "width": 90, "height": 12})
    more, more_f = _gutter_rows(["16", "17"], 552)
    amap = A.anchor_widgets(_pdf(tmp_path, texts + more, fields + more_f), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    rent, credit = w["rent15a"], w["credit15a"]
    assert credit.printed_line is None, credit
    assert rent.printed_line == "15a" and rent.confidence != A.TOP, rent
    assert _same_line(rent) == ["same_line:credit15a"] and rent.score <= A.CAP_SAME_LINE, rent
    assert w["L14"].confidence == w["L16"].confidence == A.TOP


def test_a_designator_printed_once_per_part_caps_both_boxes_whatever_the_other_scores(tmp_path, passing_table):
    """Two Parts on one page each print "1" before their own box. Part II's line-1 row has two amount columns, so its
    box is capped and was no repeated_line rival; Part I's box kept line 1's top tier. Without its Part, "1" does not
    identify the box (the repeated-line rationale), so both are capped."""
    part1, f1 = _rows([("1", "Part one first", "P1L1"), ("2", "Part one second", "P1L2"),
                       ("3", "Part one third", "P1L3")], top=740)
    part2, f2 = _de_rows(n=1)
    amap = A.anchor_widgets(_pdf(tmp_path, part1 + part2, f1 + f2), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert w["ln1ColA"].printed_line == "1" and w["ln1ColA"].score <= A.CAP_MULTI_COLUMN, w["ln1ColA"]
    assert w["P1L1"].printed_line == "1" and w["P1L1"].confidence != A.TOP, w["P1L1"]
    assert "same_line:ln1ColA" in w["P1L1"].evidence, w["P1L1"]
    assert "same_line:P1L1" in w["ln1ColA"].evidence and w["ln1ColA"].confidence != A.TOP, w["ln1ColA"]
    assert w["P1L2"].confidence == w["P1L3"].confidence == A.TOP


def test_a_lone_designator_with_one_box_keeps_the_top_tier(tmp_path, passing_table):
    """The positive case: each designator is printed once, before one box, and no other box's /TU or name names it.
    A line number inside another row's caption ("Enter the amount from line 7") is not printed before that row's box
    (its own "8" is), so line 7 keeps its one box."""
    texts, fields = _rows([("6", "Ordinary item 6", "L6", {"tooltip": "Line 6. Item"}),
                           ("7", "Ordinary item 7", "L7", {"tooltip": "Line 7. Item"}),
                           ("8", "Enter the amount from line 7", "L8", {"tooltip": "Line 8. From line 7"}),
                           ("9", "Ordinary item 9", "L9", {"tooltip": "Line 9. Item"})])
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert {n: w[f"L{n}"].printed_line for n in "6789"} == {n: n for n in "6789"}
    assert all(w[f"L{n}"].confidence == A.TOP and not _same_line(w[f"L{n}"]) for n in "6789"), w


def test_a_cap_on_a_rotated_page_keeps_the_rows_count_box_below_the_top_tier(tmp_path, passing_table):
    """The row-band cap read in a rotated page's own frame: a count box and an amount box on line 2's row of a page
    whose text runs vertically."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    raw = tmp_path / "rot.pdf"
    canv = canvas.Canvas(str(raw), pagesize=(612, 792))
    for i, (num, caption) in enumerate([("1", "Wages"), ("2", "Number of items"), ("3", "Dividends")]):
        x = 500 - i * 24
        for text, y in ((num, 40), (caption, 60), (LEADER, 250), (num, BOX_X - 18)):
            canv.saveState()
            canv.translate(x, y)
            canv.rotate(90)
            canv.setFont("Helvetica", 9)
            canv.drawString(0, 0, text)
            canv.restoreState()
        canv.acroForm.textfield(name=f"L{num}", x=x - 10, y=BOX_X, width=14, height=90)
        if num == "2":
            canv.acroForm.textfield(name="count2", x=x - 10, y=180, width=14, height=30)
    canv.save()
    writer = PdfWriter(clone_from=PdfReader(str(raw)))
    writer.pages[0].rotate(90)
    out = tmp_path / "rotated.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    amap = A.anchor_widgets(out, table=passing_table)
    w = {x.field: x for x in amap.widgets}
    assert w["L2"].printed_line == "2" and w["L2"].confidence != A.TOP, w["L2"]
    assert "shared_row:count2" in w["L2"].evidence, w["L2"]
    assert w["L1"].confidence == w["L3"].confidence == A.TOP


# ── option boxes: their own caption, and Yes/No pairs (Phase K JK15b, 2026-10-25; docs/dev/JK19-PILOT.md D3, D5) ──


def _box(name, x, y, *, size=10, kind="checkbox", on_value=None, page=1):
    spec = {"name": name, "page": page, "x": x, "y": y, "kind": kind, "size": size}
    if on_value:
        spec["on_value"] = on_value
    return spec


def _checkbox_table(tmp_path):
    """A passing table that licenses BOTH widget groups for the top tier, so only a cap can keep a box below it."""
    path = tmp_path / "both.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": True,
                                    "thresholds": {"top": 3.0, "med": 2.0}, "top_tier_kinds": ["text", "checkbox"]}))
    return path


def _text_anchors(widgets):
    return {(w.field, w.widget_index): (w.printed_line, w.label, w.score, tuple(w.evidence), w.confidence)
            for w in widgets if w.kind not in ("checkbox", "radio")}


def test_an_option_box_is_labelled_by_the_caption_on_its_own_right(tmp_path, passing_table):
    """D3: OR-40-N 2023 prints "1. [ ] Single  2. [ ] Married filing jointly  3. [ ] Married filing separately", and
    the Philadelphia School Income Tax return "Check Box If Applies: [ ] Address Change [ ] Amended Return [ ] Final
    Return". The label was the caption to the box's left, the previous option's ("Married filing jointly" labelled
    "Single", "Amended Return" labelled "Address Change"); it now names the box's own option."""
    texts = [(1, 40, 300, "Filing status"),
             (1, 44, 280, "1."), (1, 70, 280, "Single"), (1, 138, 280, "2."), (1, 165, 280, "Married filing jointly"),
             (1, 275, 280, "3."), (1, 302, 280, "Married filing separately"),
             (1, 40, 200, "Check Box If Applies:"), (1, 160, 200, "Address Change"), (1, 250, 200, "Amended Return"),
             (1, 340, 200, "Final Return")]
    fields = [_box("fs1", 55, 278), _box("fs2", 150, 278), _box("fs3", 287, 278),
              _box("addr", 145, 198), _box("amended", 235, 198), _box("final", 325, 198)]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table))
    assert {k: w[k].label for k in ("fs1", "fs2", "fs3")} == {
        "fs1": "Single", "fs2": "Married filing jointly", "fs3": "Married filing separately"}
    assert {k: w[k].label for k in ("addr", "amended", "final")} == {
        "addr": "Address Change", "amended": "Amended Return", "final": "Final Return"}
    assert all("label_right" in w[k].evidence for k in ("fs1", "fs2", "addr", "final"))
    assert [w[k].printed_line for k in ("fs1", "fs2", "fs3")] == ["1", "2", "3"]  # the designators did not move


def test_a_caption_printed_left_of_its_box_keeps_the_left_reading(tmp_path, passing_table):
    """A row that prints each caption LEFT of its box ("Yes [ ] No [ ]") keeps the left reading, and so does a box
    whose caption ends "check here" (Delaware PIT-NON line 38: "... check here a. ( ) Enter amount from Line 36"). A
    heading set in a large type beside a box is not its caption (Louisiana IT-540's title beside "Name Change")."""
    texts = [(1, 40, 400, "Did you move this year?"), (1, 300, 400, "Yes"), (1, 340, 400, "No"),
             (1, 20, 300, "If you elect the STANDARD DEDUCTION check here"), (1, 263, 300, "a."),
             (1, 295, 300, "Enter amount from Line 36"),
             (1, 20, 200, "Name Change"), (1, 94, 196, "2025 STATE RESIDENT", 22)]
    fields = [_box("moved_yes", 320, 398), _box("moved_no", 355, 398), _box("std", 277, 296, size=15),
              _box("namechg", 77, 198)]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table))
    assert w["moved_yes"].label == "Yes" and w["moved_no"].label == "No"
    assert w["std"].label.startswith("If you elect the STANDARD DEDUCTION check here")
    assert w["namechg"].label == "Name Change"


def _schedule_h_page():
    """Schedule H (Form 1040) 2025's shape: a gutter column of designators (7, 8, A, 9), the stacked Yes/No pair of
    question A captioned "Yes." then "No.", and line 9's pair "No." then "Yes." with a wrapped caption between."""
    texts = [(1, 45, 720, "7"), (1, 65, 720, "Total social security wages"), _leader(1, 65, 720, "Total social security wages"),
             (1, 45, 696, "8"), (1, 65, 696, "Total Medicare wages"), _leader(1, 65, 696, "Total Medicare wages"),
             (1, 45, 640, "A"), (1, 65, 640, "Did you pay any one household employee cash wages of $2,800 or more?"),
             (1, 65, 629, "(If any household employee was your spouse, see the line A instructions.)"),
             (1, 79, 605, "Yes. Skip lines B and C and go to line 1."), (1, 79, 593, "No. Go to line B."),
             (1, 45, 440, "9"), (1, 65, 440, "Did you pay total cash wages of $1,000 or more in any calendar quarter?"),
             (1, 65, 429, "(Don't count cash wages paid to your spouse.)"),
             (1, 79, 405, "No. Stop. Include the amount from line 8 above on Schedule 2, line 9."),
             (1, 120, 394, "see the line 9 instructions."),
             (1, 79, 370, "Yes. Go to line 10.")]
    fields = [{"name": "f7", "page": 1, "x": BOX_X, "y": 716, "width": 90, "height": 14},
              {"name": "f8", "page": 1, "x": BOX_X, "y": 692, "width": 90, "height": 14},
              _box("c1_1[0]", 65, 604, size=8), _box("c1_1[1]", 65, 592, size=8),
              _box("c1_4[1]", 65, 404, size=8), _box("c1_4[0]", 65, 369, size=8)]
    return texts, fields


def test_a_stacked_yes_no_pair_anchors_to_its_questions_designator(tmp_path, passing_table, monkeypatch):
    """D5: Schedule H 2025 anchored the boxes of its stacked Yes/No pairs `none` (c1_1[1], c1_4[0] among them), so line
    9 "Yes" could only be hand-written and its hand_write entry did not say which box. Each box of the pair now takes
    its question's designator (A, 9) and the label "Yes" or "No", capped below the top tier (one designator names two
    boxes). The text widgets on the page come out identical to a run without the option passes."""
    texts, fields = _schedule_h_page()
    blank = _pdf(tmp_path, texts, fields)
    w = _first(A.anchor_widgets(blank, table=_checkbox_table(tmp_path)))
    got = {k: (w[k].printed_line, w[k].label) for k in ("c1_1[0]", "c1_1[1]", "c1_4[1]", "c1_4[0]")}
    assert got == {"c1_1[0]": ("A", "Yes"), "c1_1[1]": ("A", "No"), "c1_4[1]": ("9", "No"), "c1_4[0]": ("9", "Yes")}
    for k, partner in (("c1_1[0]", "c1_1[1]"), ("c1_4[0]", "c1_4[1]")):
        assert f"yes_no_pair:{partner}" in w[k].evidence and f"pair_head:{w[k].printed_line}" in w[k].evidence
        assert w[k].confidence in (A.MED, A.LOW) and w[k].confidence != A.NONE
    with_options = _text_anchors(A.anchor_widgets(blank, table=passing_table).widgets)
    monkeypatch.setattr(A, "_option_labels", lambda words, boxes: None)
    monkeypatch.setattr(A, "_pair_yes_no", lambda words, boxes: None)
    assert _text_anchors(A.anchor_widgets(blank, table=passing_table).widgets) == with_options
    assert with_options[("f7", 0)][0] == "7" and with_options[("f8", 0)][0] == "8"


def test_a_side_by_side_yes_no_pair_under_column_headers_takes_the_rows_line_and_stays_below_the_top_tier(tmp_path):
    """D5, side by side: Schedule H page 2 prints "Yes  No" once over two columns of boxes and "10 [ ] [ ]" per row.
    Both boxes of a row take its line, labelled from their column header, and neither reaches the top tier even under
    a table that licenses checkboxes (the multi-box-row rule)."""
    texts = [(1, 536, 724, "Yes"), (1, 559, 724, "No")]
    fields = []
    for i, (num, caption) in enumerate((("10", "Did you pay unemployment contributions to only one state?"),
                                        ("11", "Did you pay all state unemployment contributions by April 15?"))):
        y = 700 - i * 12
        texts += [(1, 45, y, num), (1, 65, y, caption), _leader(1, 65, y, caption, end=505), (1, 517, y, num)]
        fields += [_box(f"c2_{i + 1}[0]", 540, y - 1, size=8), _box(f"c2_{i + 1}[1]", 561, y - 1, size=8)]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=_checkbox_table(tmp_path)))
    for i, num in ((1, "10"), (2, "11")):
        yes, no = w[f"c2_{i}[0]"], w[f"c2_{i}[1]"]
        assert (yes.printed_line, yes.label, no.printed_line, no.label) == (num, "Yes", num, "No")
        assert yes.confidence != A.TOP and no.confidence != A.TOP


def test_an_inline_yes_no_radio_pair_shares_the_rows_line_and_is_capped(tmp_path):
    """D5, inline: "12 Did you ...? ( ) Yes ( ) No", one radio field with a widget per answer. The "No" widget had no
    line of its own (only words lie between it and the "Yes" widget); it now takes the row's, and both widgets of the
    one field are capped below the top tier, which the multi-column rule (fields of different names only) missed."""
    texts = [(1, 40, 500, "12"), (1, 60, 500, "Did you receive a distribution from a foreign trust?"),
             (1, 300, 500, "12"), (1, 335, 500, "Yes"), (1, 375, 500, "No")]
    fields = [_box("q12", 320, 498, kind="radio", on_value="/1"), _box("q12", 360, 498, kind="radio", on_value="/2")]
    amap = A.anchor_widgets(_pdf(tmp_path, texts, fields), table=_checkbox_table(tmp_path))
    yes, no = sorted((x for x in amap.widgets if x.field == "q12"), key=lambda x: x.rect[0])
    assert (yes.printed_line, yes.label, no.printed_line, no.label) == ("12", "Yes", "12", "No")
    assert "pair_of:q12" in no.evidence
    assert yes.confidence != A.TOP and no.confidence != A.TOP


def test_a_sub_letter_row_hangs_from_the_joined_head_above_it_not_the_line_before(tmp_path, passing_table):
    """Phase K JK15b (2026-10-25): Schedule C (2022-2025) prints "47a Do you have evidence ...? [ ] Yes [ ] No" and,
    indented under it, "b If "Yes," is the evidence written? [ ] Yes [ ] No"; Form 2555 prints 13a / b the same way,
    Schedule 1 prints 2a / b. The joined "47a" is wider than the gutter's "46", so it ended right of the "b" and the
    sub-letter hung from 46: line 46b, which pair_of then lent to the "No" box at med. Row b is line 47b."""
    texts = []
    for num, y in (("44", 700), ("45", 676), ("46", 652)):
        texts += [(1, 40, y, num), (1, 62, y, f"Question {num}")]
    texts += [(1, 40, 628, "47a"), (1, 62, 628, "Do you have evidence to support your deduction?"),
              _leader(1, 62, 628, "Do you have evidence to support your deduction?", end=390),
              (1, 410, 628, "Yes"), (1, 450, 628, "No"),
              (1, 49, 604, "b"), (1, 62, 604, "If \"Yes,\" is the evidence written?"),
              _leader(1, 62, 604, "If \"Yes,\" is the evidence written?", end=390),
              (1, 410, 604, "Yes"), (1, 450, 604, "No"),
              (1, 49, 580, "c"), (1, 62, 580, "Amount of the written evidence"),
              _leader(1, 62, 580, "Amount of the written evidence")]
    fields = [_box("c2_7[0]", 396, 626), _box("c2_7[1]", 436, 626), _box("c2_8[0]", 396, 602),
              _box("c2_8[1]", 436, 602),
              {"name": "f47c", "page": 1, "x": BOX_X, "y": 576, "width": 90, "height": 14}]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table))
    assert w["f47c"].printed_line == "47c", w["f47c"]
    yes, no = w["c2_8[0]"], w["c2_8[1]"]
    assert (yes.printed_line, yes.label, no.printed_line, no.label) == ("47b", "Yes", "47b", "No"), (yes, no)
    assert "pair_of:c2_8[0]" in no.evidence
    assert not any(x.printed_line == "46b" for x in w.values())


def test_a_lettered_head_does_not_parent_an_earlier_or_equal_letter(tmp_path, passing_table):
    """The joined head counts only for a later letter: "5b" over an indented "a" (a second column's restart) is not
    a parent, so the row gets no line from it rather than "5a"."""
    texts = [(1, 40, 700, "3"), (1, 62, 700, "Line three"), (1, 40, 676, "4"), (1, 62, 676, "Line four"),
             (1, 40, 652, "5b"), (1, 62, 652, "Line five b"),
             (1, 49, 628, "a"), (1, 62, 628, "Restarted letter"), _leader(1, 62, 628, "Restarted letter")]
    fields = [{"name": "fa", "page": 1, "x": BOX_X, "y": 624, "width": 90, "height": 14}]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table))
    assert w["fa"].printed_line not in ("5a", "4a"), w["fa"]


def test_the_pronoun_i_starting_a_sentence_is_not_a_yes_no_pairs_gutter_letter(tmp_path, passing_table):
    """Phase K JK15b (2026-10-25): WV IT-140 (2023, 2024) page 2 prints "I authorize the Tax Division to discuss my
    return with my preparer [ ] YES [ ] NO" with its "I" in the column of line numbers above, and the pair took
    printed_line "I" (pair_head). A bare capital followed at a word space is a word; the boxes keep their labels and
    no line. A gutter letter set apart from its caption (Schedule H's "A") still heads its pair."""
    texts = [(1, 40, 700, "27"), (1, 62, 700, "Line twenty-seven"), (1, 40, 676, "28"),
             (1, 62, 676, "Line twenty-eight"), (1, 40, 652, "29"), (1, 62, 652, "Line twenty-nine"),
             (1, 40, 628, "I authorize the Tax Division to discuss my return with my preparer"),
             (1, 382, 628, "YES"), (1, 422, 628, "NO")]
    fields = [_box("Check Box1", 368, 626), _box("Check Box2", 408, 626)]
    w = _first(A.anchor_widgets(_pdf(tmp_path, texts, fields), table=passing_table))
    yes, no = w["Check Box1"], w["Check Box2"]
    assert (yes.label, no.label) == ("Yes", "No")
    assert yes.printed_line is None and no.printed_line is None, (yes, no)
    assert not any(e.startswith("pair_head:") for e in yes.evidence + no.evidence)


def test_a_pairs_head_keeps_a_sub_letter_set_flush_against_its_number():
    """Phase K JK15b (2026-10-25): Schedule B's 2026 draft sets "7a" as "7" and "a" with the "a" starting 0.00002 pt
    left of the "7"'s right edge (2025 prints it 0.00002 pt right of it), and the stacked pair under it took line "7".
    A sub-letter flush against its number, either side by a hair, is that sub-line."""
    def word(text, x0, cy, width=5.0, h=10.0):
        return A._Word(text=text, x0=x0, y0=cy - h / 2, x1=x0 + width, y1=cy + h / 2, h=h, run=None)

    words = [word("5", 40, 300), word("6", 40, 250), word("7", 40, 200), word("8", 40, 60),
             word("At any time during the year", 60, 200, width=150)]
    seven = words[2]
    words.append(word("a", seven.x1 - 0.00002, 200))
    pair = (A._Box(info={"name": "yes"}, index=0, x0=60, y0=170, x1=68, y1=178),
            A._Box(info={"name": "no"}, index=0, x0=60, y0=158, x1=68, y1=166))
    assert A._pair_head(pair, words, list(pair)) == "7a"
    words[-1] = word("a", seven.x1 + 0.00002, 200)
    assert A._pair_head(pair, words, list(pair)) == "7a"
