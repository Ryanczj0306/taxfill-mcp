"""Phase K JK28 (2026-10-23) — money combs whose printed face spends cells on commas (``format: money_comma_cells``).

The Oregon Form OR-40 dollar boxes (2023-2025, lines 7-55b) are 11-cell right-aligned comb widgets (/Ff 29360128,
/MaxLen 11, /Q 2) printed as three boxes of three cells with a comma printed in the cell between two boxes (cells 4
and 8), then '.' and a printed '0 0'. Mapped as plain money lines, fill_form wrote bare whole dollars that filled the
cells from the right with no regard for the comma cells: 1234567 printed '123[4]567' with the 4 in the second comma
cell and the first box empty, 12345 put its 2 in a comma cell, and only amounts under 1,000 landed right. Read by eye
or by a scanner, 1,234,567 could pass as 123,567. ``format: money_comma_cells`` writes the comma-grouped amount
('1,234,567') instead, so each comma cell gets the comma and each digit its printed cell, and verify reads the value
back through parse_money (commas dropped), so assertions, relations and the recompute see the number.

The census of every money line on a comb widget (which boxes print comma cells, which print the commas on a cell rule)
sits with the format's definition in schemas/formpack.py; test_pack_invariants.py holds the packs to it. The render
tests read the cached blanks (network-marked: a warm cache or the network).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from taxfill_core.filler import _qualified_name, _render_comma_cells, _render_money, fill_form
from taxfill_core.schemas.formpack import (
    MONEY_COMMA_CELLS,
    MONEY_COMMA_CELLS_RE,
    FormPack,
    PackField,
    load_pack,
    money_comma_cells_text,
)
from taxfill_core.verify import expected_rendering, normalize_on_disk, parse_money, verify_form

REPO_ROOT = Path(__file__).resolve().parents[3]
SCALE = 600 / 72  # 600 dpi: one pixel is 0.12 pt
OR40_PACKS = [REPO_ROOT / f"formpacks/states/or/{year}/or40/pack.yaml" for year in (2023, 2024, 2025)]
COMMA_CELLS = (3, 7)  # zero-based: the printed face puts its commas in cells 4 and 8


def _field(**overrides) -> PackField:
    spec = {"line": "7", "field": "or-40-p3-1", "type": "money", "maxlen": 11, "comb": True,
            "format": MONEY_COMMA_CELLS}
    spec.update(overrides)
    return PackField(**spec)


def _write(pf: PackField, value: object) -> str:
    whole, _ = _render_money(pf, value)
    return _render_comma_cells(pf, whole)


# ---------------------------------------------------------------------------
# The rendering rule (offline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "written"), [
    (0, "0"), (7, "7"), (999, "999"), (1000, "1,000"), (12345, "12,345"), (1234567, "1,234,567"),
    (123456789, "123,456,789"), (Decimal("1234.50"), "1,235"), (1234.49, "1,234"), (-0.4, "0"),
    (-5, "-5"), (-12345, "-12,345"), (-1234567, "-1,234,567"), (-12345678, "-12,345,678"),
    # a 3- or 6-digit negative: the cell left of the first digit is a comma cell, so it stays blank and the minus
    # takes the digit cell beyond it, never the printed comma (Phase K JK28 fix, 2026-10-23)
    (-123, "- 123"), (-999, "- 999"), (-123456, "- 123,456"), (-100000, "- 100,000"), (-99999999, "-99,999,999"),
])
def test_comma_cells_write_the_whole_dollars_comma_grouped_keeping_the_sign(value: object, written: str):
    assert _write(_field(), value) == written


def test_the_formatter_groups_by_thousands():
    assert money_comma_cells_text("1234567") == "1,234,567"
    assert money_comma_cells_text("-1000") == "-1,000"
    assert money_comma_cells_text("0") == "0"
    assert money_comma_cells_text("-123") == "- 123"
    assert money_comma_cells_text("-123456") == "- 123,456"
    assert money_comma_cells_text("-12") == "-12"


@pytest.mark.parametrize("digits", range(1, 9))
def test_the_minus_sign_never_lands_in_a_comma_cell(digits: int):
    """Right-aligned in an 11-cell box with comma cells 4 and 8, the minus sits in a digit cell for every length the
    box holds (1-8 digits; 9 needs 13 cells and is refused)."""
    text = money_comma_cells_text("-" + "9" * digits)
    assert len(text) <= 11 and MONEY_COMMA_CELLS_RE.fullmatch(text)
    cells = text.rjust(11)
    assert cells.index("-") not in COMMA_CELLS, cells
    assert all(cells[i] in " ," for i in COMMA_CELLS), cells
    if digits % 3 == 0:  # the old placement ('-999', '-999,999') put the minus on the printed comma: not the shape
        assert not MONEY_COMMA_CELLS_RE.fullmatch(text.replace("- ", "-"))


@pytest.mark.parametrize(("value", "needs", "limit"), [
    (1234567890, "13 cells", "at most 999,999,999 "),
    (-123456789, "13 cells", "at most -99,999,999 when negative"),
    (-100000000, "13 cells", "at most -99,999,999 when negative"),
])
def test_an_amount_the_cells_cannot_hold_is_refused_saying_what_to_do(value: int, needs: str, limit: str):
    with pytest.raises(ValueError, match=f"needs {needs} but this box has 11.*{limit}") as caught:
        _write(_field(), value)
    assert "write it on the form by hand" in str(caught.value)
    if value < 0:
        assert "minus sign" in str(caught.value)


def test_a_shorter_comb_holds_fewer_digits():
    assert _write(_field(maxlen=7), 999999) == "999,999"
    with pytest.raises(ValueError, match="holds at most 999,999"):
        _write(_field(maxlen=7), 1000000)
    assert _write(_field(maxlen=7), -99999) == "-99,999"
    with pytest.raises(ValueError, match="holds at most -99,999 when negative"):
        _write(_field(maxlen=7), -100000)  # '- 100,000' is 9 characters


def test_the_format_is_refused_on_a_line_that_is_not_a_comb_money_line():
    with pytest.raises(ValueError, match="is for a money line whose box is a comb"):
        _field(comb=False)
    with pytest.raises(ValueError, match="is for a money line whose box is a comb"):
        _field(type="text")
    # a line built around the schema (model_construct) is still refused by the filler
    loose = PackField.model_construct(line="7", field="f", type="money", maxlen=None, comb=False,
                                      format=MONEY_COMMA_CELLS)
    with pytest.raises(ValueError, match="is for a comb money line"):
        _render_comma_cells(loose, "1234567")


def test_verify_reads_the_comma_grouped_amount_as_the_number():
    pf = _field()
    for written, asserted in (("1,234,567", 1234567), ("-12,345", -12345), ("0", 0), ("1,235", Decimal("1234.50")),
                              ("- 123", -123), ("- 123,456", -123456)):
        assert normalize_on_disk(pf, written) == expected_rendering(pf, asserted)
        assert parse_money(written) == Decimal(expected_rendering(pf, asserted))
    assert normalize_on_disk(pf, "123,567") != expected_rendering(pf, 1234567)


# ---------------------------------------------------------------------------
# The OR-40 render: each digit inside its printed cell, each comma cell holding a comma (cached blanks)
# ---------------------------------------------------------------------------

# A consistent demo set (9 = 7 + 8, 14 = 10 + 11 + 12 + 13, 15 = 9 - 14, 23 = 21 + 22), so the relations run on what
# the boxes hold: line -> (amount, how the box must read cell by cell, right-aligned).
OR40_AMOUNTS = {
    "7": (1234567, "1,234,567"),
    "8": (12345, "12,345"),
    "9": (1246912, "1,246,912"),
    "10": (1000000, "1,000,000"),
    "11": (200000, "200,000"),
    "12": (50000, "50,000"),
    "13": (9257, "9,257"),
    "14": (1259257, "1,259,257"),
    "15": (-12345, "-12,345"),  # a negative amount: its minus sign in the cell left of its first digit
    # 3- and 6-digit negatives: the cell left of the first digit is a comma cell, left blank; the minus goes beyond it
    "16": (-123456, "- 123,456"),
    "17": (-123, "- 123"),
    "18": (-99999999, "-99,999,999"),  # the most negative amount the cells hold
    "19": (-999, "- 999"),
    "21": (123456789, "123,456,789"),  # every cell
    "22": (0, "0"),
    "23": (123456789, "123,456,789"),
}


def _blank(pack: FormPack) -> Path:
    from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank

    try:
        return Path(fetch_pack_blank(pack))
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cache empty and network unreachable: {exc}")


def _gray(pdf: Path, page_index: int, box: tuple[float, float, float, float], *, forms: bool):
    """``box`` (x0, y0, x1, y1 in page points) of a page at 600 dpi, grayscale; forms off draws the printed page."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        if forms:
            doc.init_forms()
        page = doc[page_index]
        width, height = page.get_size()
        x0, y0, x1, y1 = box
        bitmap = page.render(scale=SCALE, crop=(x0, y0, width - x1, height - y1), draw_annots=forms,
                             may_draw_forms=forms)
        return bitmap.to_pil().convert("L")
    finally:
        doc.close()


def _runs(flags: list[bool], left: float) -> list[tuple[float, float]]:
    """The x extents (page points) of each run of True columns."""
    runs, start = [], None
    for col, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = col
        elif not flag and start is not None:
            runs.append((left + start / SCALE, left + col / SCALE))
            start = None
    return runs


def _cells_and_glyphs(blank: Path, filled: Path, page_index: int, rect: list[float]):
    """The printed cells under ``rect`` (read off the blank: the spans between its tinted vertical rules, each flagged
    when the printed face puts a comma in it) and the glyphs fill_form drew (black ink in the filled render: the
    printed face is a pale tint), each glyph as ``(x0, x1, ink height in pixels)``."""
    x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
    box = (x0 - 4.0, y0, x1 + 4.0, y1)
    printed, drawn = _gray(blank, page_index, box, forms=False), _gray(filled, page_index, box, forms=True)
    width, height = printed.size
    tint, ink = printed.load(), drawn.load()
    rules = _runs([sum(1 for row in range(height) if tint[col, row] < 245) >= 0.5 * height for col in range(width)],
                  box[0])
    cells = []
    for (_, left), (right, _) in zip(rules, rules[1:]):
        cols = range(round((left - box[0]) * SCALE) + 3, round((right - box[0]) * SCALE) - 3)
        comma = any(tint[col, row] < 245 for col in cols for row in range(height // 6, height - height // 6))
        cells.append((left, right, comma))
    glyphs = []
    for a, b in _runs([any(ink[col, row] < 100 for row in range(height)) for col in range(width)], box[0]):
        cols = range(round((a - box[0]) * SCALE), round((b - box[0]) * SCALE))
        rows = [row for row in range(height) if any(ink[col, row] < 100 for col in cols)]
        glyphs.append((a, b, max(rows) - min(rows) + 1))
    return cells, glyphs


def _assert_the_box_reads(cells, glyphs, reads: str, label: str) -> None:
    assert len(cells) == 11, f"{label}: {len(cells)} printed cells, expected 11"
    commas = tuple(index for index, (_, _, comma) in enumerate(cells) if comma)
    assert commas == COMMA_CELLS, f"{label}: printed commas in cells {commas}, expected {COMMA_CELLS}"
    held: list[list[tuple[float, float, int]]] = [[] for _ in cells]
    for glyph in glyphs:
        home = [i for i, (left, right, _) in enumerate(cells) if left <= glyph[0] and glyph[1] <= right]
        assert home, f"{label}: a glyph at x {glyph[0]:.1f}-{glyph[1]:.1f} straddles a printed cell rule"
        held[home[0]].append(glyph)
    digit_height = max(height for _, _, height in glyphs)
    expected = " " * (len(cells) - len(reads)) + reads
    for index, (char, inside) in enumerate(zip(expected, held)):
        if char == " ":
            assert not inside, f"{label}: cell {index + 1} should be empty, holds {inside}"
        elif char.isdigit():
            assert index not in COMMA_CELLS, f"{label}: the expected reading puts a digit in comma cell {index + 1}"
            assert len(inside) == 1 and inside[0][2] >= 0.8 * digit_height, (
                f"{label}: printed digit cell {index + 1} should hold one digit ('{char}'), holds {inside}")
        else:  # a written comma (in a comma cell) or a minus sign: one short glyph, never a digit
            assert char == "-" or index in COMMA_CELLS, f"{label}: a comma expected outside the comma cells"
            assert char != "-" or index not in COMMA_CELLS, f"{label}: the expected reading puts its minus in a comma cell"
            assert len(inside) == 1 and inside[0][2] < 0.5 * digit_height, (
                f"{label}: cell {index + 1} should hold '{char}', holds {inside} (a digit is {digit_height} px tall)")


@pytest.mark.network
@pytest.mark.parametrize("pack_path", OR40_PACKS, ids=lambda p: p.parts[-3])
def test_or40_money_digits_sit_in_their_printed_cells(pack_path: Path, tmp_path: Path):
    pack = load_pack(pack_path)
    blank = _blank(pack)
    out = tmp_path / "or40.pdf"
    fill_form(pack, {line: amount for line, (amount, _) in OR40_AMOUNTS.items()}, blank, out)

    by_field = {pf.field: pf.line for pf in pack.fields if pf.line in OR40_AMOUNTS}
    checked = set()
    for page_index, page in enumerate(PdfReader(str(out)).pages):
        for ref in page.get("/Annots", []) or []:
            annot = ref.get_object()
            line = by_field.get(_qualified_name(annot))
            if line is None:
                continue
            cells, glyphs = _cells_and_glyphs(blank, out, page_index, [float(v) for v in annot["/Rect"]])
            _assert_the_box_reads(cells, glyphs, OR40_AMOUNTS[line][1],
                                  f"OR-40 {pack.tax_year} line {line} (page {page_index + 1})")
            checked.add(line)
    assert checked == set(OR40_AMOUNTS)

    # verify reads every box back as its amount, and the relations run on the numbers the boxes hold
    report = verify_form(pack, out, expected={line: amount for line, (amount, _) in OR40_AMOUNTS.items()})
    failures = [check.detail for check in report.assertions if check.status == "FAIL"]
    assert not failures, failures
    expected_sides = {"9 == 7 + 8": 1246912, "14 == 10 + 11 + 12 + 13": 1259257, "15 == 9 - 14": -12345,
                      "23 == 21 + 22": 123456789}
    for relation, side in expected_sides.items():
        found = [check for check in report.relations if check.relation == relation]
        assert found and all(check.status == "PASS" and check.lhs == check.rhs == side for check in found), (
            relation, found)


@pytest.mark.network
def test_comma_cells_are_refused_on_a_widget_that_is_not_a_right_aligned_comb_of_its_cells(tmp_path: Path):
    """A pack line claiming comma cells on a widget of another cell count (the VA Form 760 2025 line-1 box, a 9-cell
    comb), or on a plain box, is refused before anything is written."""
    pack = load_pack(REPO_ROOT / "formpacks/states/va/2025/va760/pack.yaml")
    blank = _blank(pack)
    wrong = pack.model_copy(update={"fields": [
        pf.model_copy(update={"format": MONEY_COMMA_CELLS, "comb": True, "maxlen": 11}) if pf.line == "1" else pf
        for pf in pack.fields
    ]})
    with pytest.raises(ValueError, match="is a comb of 9 cells with /Q 2 .*fix the pack for this blank"):
        fill_form(wrong, {"1": 1234}, blank, tmp_path / "va.pdf")
    assert not (tmp_path / "va.pdf").exists()
    # a plain (non-comb) widget is refused too: the OR-40 page-1 "Last name" box
    or40 = load_pack(OR40_PACKS[-1])
    plain = or40.model_copy(update={"fields": [
        *or40.fields, PackField(line="probe", field="or-40-p1-11", type="money", maxlen=11, comb=True,
                                format=MONEY_COMMA_CELLS)]})
    with pytest.raises(ValueError, match="is not a comb — fix the pack for this blank"):
        fill_form(plain, {"probe": 1234}, _blank(or40), tmp_path / "or40.pdf")
