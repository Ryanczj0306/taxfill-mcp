"""Phase K JK28 (2026-10-23) — SSN combs whose printed face spends cells on the dashes (``format: ssn_dash_cells``).

The Oregon Form OR-40 SSN boxes (2023-2025: the filer's SSN, repeated in the header of pages 2-8, the spouse's and the
three dependents') are 11-cell comb widgets printed as three boxes, a dash, two boxes, a dash and four boxes: cells 4
and 7 hold the printed dashes. Mapped ``ssn_digits_only``, fill_form wrote the 9 bare digits into the first nine cells,
so the 4th digit sat on the first printed dash and every later digit one or two cells off its printed box (found while
re-mapping OR-40 2023). ``format: ssn_dash_cells`` writes 'ddd-dd-dddd' instead — the dash cells get the dash — and
verify keeps comparing the line by its digits, so a value given or found with or without its dashes verifies.
MO-1040 2023-2025's page-1 SSN_1 / SSN_2 are the same 11-cell combs under three printed boxes with the dashes
printed between them, and use the format too (the MO tests below).
The render tests read the cached blanks (network-marked: a warm cache or the network).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from taxfill_core.filler import _qualified_name, _render_text, fill_form
from taxfill_core.schemas.formpack import SSN_DASH_CELLS, SSN_DASH_CELLS_MAXLEN, FormPack, PackField, load_pack
from taxfill_core.verify import (
    _mirror_box_refusal,
    _mirror_same,
    _mirror_written,
    expected_rendering,
    normalize_on_disk,
    verify_form,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCALE = 600 / 72  # 600 dpi: one pixel is 0.12 pt
OR40_PACKS = [REPO_ROOT / f"formpacks/states/or/{year}/or40/pack.yaml" for year in (2023, 2024, 2025)]
# Demo SSNs (the 999 area is never issued).
DEMO_SSNS = {
    "identifying_number": "999-88-0507",
    "spouse_ssn": "999-88-0508",
    "dependent_1.ssn": "999880511",      # given without dashes: the line writes them
    "dependent_2.ssn": "999 88 0512",
    "dependent_3.ssn": "999-88-0513",
}
DASH_CELLS = (3, 6)  # zero-based: the printed face puts its dashes in cells 4 and 7


def _field(**overrides) -> PackField:
    spec = {"line": "identifying_number", "field": "ssn", "type": "text", "maxlen": 11, "comb": True,
            "format": SSN_DASH_CELLS}
    spec.update(overrides)
    return PackField(**spec)


# ---------------------------------------------------------------------------
# The rendering rule (offline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("given", ["999-88-0507", "999880507", "999 88 0507", " 999-880507 "])
def test_dash_cells_write_the_dashed_form_however_the_number_is_given(given: str):
    assert _render_text(_field(), given) == "999-88-0507"


def test_dash_cells_leave_a_blank_blank():
    assert _render_text(_field(), "") == ""
    assert _render_text(_field(), "  ") == ""


@pytest.mark.parametrize("given", ["99988050", "9998805071", "999-88-05O7", "ABC-DE-FGHI"])
def test_dash_cells_refuse_anything_but_nine_digits(given: str):
    with pytest.raises(ValueError, match="not a 9-digit SSN or ITIN .* pass the 9 digits"):
        _render_text(_field(), given)


def test_dash_cells_refuse_nra():
    with pytest.raises(ValueError, match="'NRA' never goes in an identifying-number or comb box"):
        _render_text(_field(), "NRA")


@pytest.mark.parametrize("shape", [{"comb": False}, {"maxlen": 9}, {"maxlen": 12}, {"comb": False, "maxlen": None}])
def test_dash_cells_are_refused_on_a_line_that_is_not_an_eleven_cell_comb(shape: dict):
    with pytest.raises(ValueError, match="is for an 11-cell comb .* fix the pack"):
        _render_text(_field(**shape), "999-88-0507")


def test_verify_compares_a_dash_cell_line_by_its_digits():
    pf = _field()
    for written in ("999-88-0507", "999880507"):
        for asserted in ("999-88-0507", "999880507", "999 88 0507"):
            assert normalize_on_disk(pf, written) == expected_rendering(pf, asserted) == "999880507"
    assert normalize_on_disk(pf, "999-88-0508") != expected_rendering(pf, "999-88-0507")
    assert expected_rendering(pf, "NRA") == "NRA"  # P-026: never digit-stripped to a blank


def test_a_dash_cell_mirror_is_built_dashed_and_compared_by_digits():
    pf = _field()
    assert _mirror_written(pf, "999880507") == "999-88-0507"
    assert _mirror_box_refusal(pf, "999880507") is None
    assert _mirror_box_refusal(pf, "99988050") == "the box takes a 9-digit SSN or ITIN in its 3-2-4 cells"
    assert "11-cell comb line" in _mirror_box_refusal(_field(maxlen=9), "999880507")
    assert _mirror_same(pf, "999-88-0507", "999880507")


# ---------------------------------------------------------------------------
# The OR-40 render: each digit inside its printed cell (cached blanks)
# ---------------------------------------------------------------------------


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
    """The printed cells of the box under ``rect`` (read off the blank: the spans between its tinted vertical rules,
    each flagged when the printed face puts a dash in it) and the glyphs fill_form drew (black ink in the filled
    render: the printed face is a pale tint), each as ``(x0, x1, ink height in pixels)``."""
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
        dashed = any(tint[col, row] < 245 for col in cols for row in range(height // 3, 2 * height // 3))
        cells.append((left, right, dashed))
    glyphs = []
    for a, b in _runs([any(ink[col, row] < 100 for row in range(height)) for col in range(width)], box[0]):
        cols = range(round((a - box[0]) * SCALE), round((b - box[0]) * SCALE))
        rows = [row for row in range(height) if any(ink[col, row] < 100 for col in cols)]
        glyphs.append((a, b, max(rows) - min(rows) + 1))
    return cells, glyphs


def _assert_digits_in_their_cells(cells, glyphs, label: str) -> None:
    assert len(cells) == 11, f"{label}: {len(cells)} printed cells, expected 11"
    dashed = tuple(index for index, (_, _, dash) in enumerate(cells) if dash)
    assert dashed == DASH_CELLS, f"{label}: printed dashes in cells {dashed}, expected {DASH_CELLS}"
    held: list[list[tuple[float, float, int]]] = [[] for _ in cells]
    for glyph in glyphs:
        home = [i for i, (left, right, _) in enumerate(cells) if left <= glyph[0] and glyph[1] <= right]
        assert home, f"{label}: a glyph at x {glyph[0]:.1f}-{glyph[1]:.1f} straddles a printed cell rule"
        held[home[0]].append(glyph)
    digit_height = max(height for _, _, height in glyphs)
    for index, inside in enumerate(held):
        if index in DASH_CELLS:
            # a dash cell holds nothing or the written dash: never a digit
            assert len(inside) <= 1 and all(height < 0.4 * digit_height for _, _, height in inside), (
                f"{label}: a digit sits in printed dash cell {index + 1} (glyphs {inside})")
        else:
            assert len(inside) == 1 and inside[0][2] >= 0.8 * digit_height, (
                f"{label}: printed digit cell {index + 1} holds {len(inside)} digit(s), expected one ({inside})")


@pytest.mark.network
@pytest.mark.parametrize("pack_path", OR40_PACKS, ids=lambda p: p.parts[-3])
def test_or40_ssn_digits_sit_in_their_printed_cells(pack_path: Path, tmp_path: Path):
    pack = load_pack(pack_path)
    blank = _blank(pack)
    out = tmp_path / "or40.pdf"
    fill_form(pack, DEMO_SSNS, blank, out)

    by_field = {pf.field: pf.line for pf in pack.fields if pf.line in DEMO_SSNS}
    checked: dict[str, int] = {}
    for page_index, page in enumerate(PdfReader(str(out)).pages):
        for ref in page.get("/Annots", []) or []:
            annot = ref.get_object()
            line = by_field.get(_qualified_name(annot))
            if line is None:
                continue
            cells, glyphs = _cells_and_glyphs(blank, out, page_index, [float(v) for v in annot["/Rect"]])
            _assert_digits_in_their_cells(cells, glyphs, f"OR-40 {pack.tax_year} {line} (page {page_index + 1})")
            checked[line] = checked.get(line, 0) + 1
    # the filer's SSN prints on all eight pages (one field, eight widgets); every other box once
    assert checked == {line: 8 if line == "identifying_number" else 1 for line in DEMO_SSNS}

    # verify reads every box back by its digits, whichever way the assertion spells the number
    for spelling in (DEMO_SSNS, {line: value.replace("-", "").replace(" ", "") for line, value in DEMO_SSNS.items()}):
        report = verify_form(pack, out, expected=spelling)
        failures = [check.detail for check in report.assertions if check.status == "FAIL"]
        assert not failures, failures


@pytest.mark.network
def test_dash_cells_are_refused_on_a_widget_that_is_not_an_eleven_cell_comb(tmp_path: Path):
    """The VT IN-111 2023 SSN widgets carry /MaxLen 11 but no Comb flag (a plain box): a pack that claimed dash cells
    there is refused before anything is written."""
    pack = load_pack(REPO_ROOT / "formpacks/states/vt/2023/in111/pack.yaml")
    blank = _blank(pack)
    wrong = pack.model_copy(update={"fields": [
        pf.model_copy(update={"format": SSN_DASH_CELLS}) if pf.line == "identifying_number" else pf
        for pf in pack.fields
    ]})
    with pytest.raises(ValueError, match="is not a comb — fix the pack for this blank"):
        fill_form(wrong, {"identifying_number": "999-88-0507"}, blank, tmp_path / "vt.pdf")
    assert not (tmp_path / "vt.pdf").exists()


# ---------------------------------------------------------------------------
# The MO-1040 page-1 SSN boxes (cached blanks)
# ---------------------------------------------------------------------------
# MO-1040 2023-2025 prints its page-1 "Social Security Number" and "Spouse's Social Security Number" as three black-
# ruled boxes (3, 2 and 4 digits) with a dash printed in each gap and no cell rules inside them; the SSN_1 / SSN_2
# widgets are 11-cell combs over them (/Ff 29360128, /MaxLen 11), so cells 4 and 7 fall on the printed dashes. The
# packs mapped them as plain text and told the caller to type the dashes: 9 bare digits printed the 4th on the first
# dash and every later one off its box, and verify compared the line as text (Phase K JK28, 2026-10-23).

MO1040_PACKS = [REPO_ROOT / f"formpacks/states/mo/{year}/mo1040/pack.yaml" for year in (2023, 2024, 2025)]
MO_SSNS = {"SSN_1": "999880507", "SSN_2": "999-88-0508"}  # the filer's given bare, the spouse's dashed
MO_DIGITS_PER_BOX = (3, 2, 4)


def _boxes_dashes_and_glyphs(blank: Path, filled: Path, page_index: int, rect: list[float]):
    """The printed boxes under ``rect`` (read off the blank: the spans between its black vertical rules), the printed
    dashes in the gaps between them, and the glyphs fill_form drew (ink in the filled render where the printed face is
    white), each glyph as ``(x0, x1, ink height in pixels)``."""
    x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])
    box = (x0 - 4.0, y0, x1 + 4.0, y1)
    printed, drawn = _gray(blank, page_index, box, forms=False), _gray(filled, page_index, box, forms=True)
    width, height = printed.size
    face, ink = printed.load(), drawn.load()
    rules = _runs([sum(1 for row in range(height) if face[col, row] < 128) >= 0.5 * height for col in range(width)],
                  box[0])
    boxes = [(rules[i][1], rules[i + 1][0]) for i in range(0, len(rules) - 1, 2)]
    middle = range(height // 3, 2 * height // 3)
    dashes = []
    for (_, gap_left), (gap_right, _) in zip(boxes, boxes[1:]):
        cols = range(round((gap_left - box[0]) * SCALE) + 2, round((gap_right - box[0]) * SCALE) - 2)
        dash = _runs([col in cols and any(face[col, row] < 128 for row in middle) for col in range(width)], box[0])
        dashes.append((dash[0][0], dash[-1][1]) if dash else None)
    fresh = [[ink[col, row] < 100 and face[col, row] >= 200 for row in range(height)] for col in range(width)]
    glyphs = []
    for a, b in _runs([any(column) for column in fresh], box[0]):
        cols = range(round((a - box[0]) * SCALE), round((b - box[0]) * SCALE))
        rows = [row for row in range(height) if any(fresh[col][row] for col in cols)]
        glyphs.append((a, b, max(rows) - min(rows) + 1))
    return boxes, dashes, glyphs


def _assert_digits_in_their_boxes(rect: list[float], boxes, dashes, glyphs, label: str) -> None:
    assert len(boxes) == 3, f"{label}: {len(boxes)} printed boxes, expected 3 (3-2-4 digits)"
    # cells 4 and 7 of the widget's 11 equal cells hold the printed dashes
    left, cell = min(rect[0], rect[2]), abs(rect[2] - rect[0]) / SSN_DASH_CELLS_MAXLEN
    for dash, index in zip(dashes, DASH_CELLS):
        assert dash is not None, f"{label}: no printed dash between the boxes"
        assert left + index * cell <= dash[0] and dash[1] <= left + (index + 1) * cell, (
            f"{label}: the printed dash at x {dash[0]:.1f}-{dash[1]:.1f} is not inside cell {index + 1}")
    digit_height = max(height for _, _, height in glyphs)
    digits = [glyph for glyph in glyphs if glyph[2] >= 0.8 * digit_height]
    assert len(digits) == 9, f"{label}: {len(digits)} digits drawn, expected 9 ({glyphs})"
    held = [[g for g in digits if box_left <= g[0] and g[1] <= box_right] for box_left, box_right in boxes]
    assert sum(map(len, held)) == 9, (
        f"{label}: digit(s) outside every printed box (boxes {boxes}, digits {digits})")
    assert tuple(map(len, held)) == MO_DIGITS_PER_BOX, (
        f"{label}: the boxes hold {tuple(map(len, held))} digits, expected {MO_DIGITS_PER_BOX}")


@pytest.mark.network
@pytest.mark.parametrize("pack_path", MO1040_PACKS, ids=lambda p: p.parts[-3])
def test_mo1040_ssn_digits_sit_in_their_printed_boxes(pack_path: Path, tmp_path: Path):
    pack = load_pack(pack_path)
    for line in MO_SSNS:
        (pf,) = [pf for pf in pack.fields if pf.line == line]
        assert (pf.comb, pf.maxlen, pf.format) == (True, 11, SSN_DASH_CELLS), line
    blank = _blank(pack)
    out = tmp_path / "mo1040.pdf"
    result = fill_form(pack, MO_SSNS, blank, out)
    assert {result.written[line] for line in MO_SSNS} == {"999-88-0507", "999-88-0508"}

    checked: dict[str, int] = {}
    for page_index, page in enumerate(PdfReader(str(out)).pages):
        for ref in page.get("/Annots", []) or []:
            annot = ref.get_object()
            line = _qualified_name(annot)
            if line not in MO_SSNS:
                continue
            rect = [float(v) for v in annot["/Rect"]]
            boxes, dashes, glyphs = _boxes_dashes_and_glyphs(blank, out, page_index, rect)
            _assert_digits_in_their_boxes(rect, boxes, dashes, glyphs, f"MO-1040 {pack.tax_year} {line}")
            checked[line] = checked.get(line, 0) + 1
    assert checked == dict.fromkeys(MO_SSNS, 1)  # one widget each, on page 1

    for spelling in (MO_SSNS, {"SSN_1": "999-88-0507", "SSN_2": "999880508"}):
        report = verify_form(pack, out, expected=spelling)
        failures = [check.detail for check in report.assertions if check.status == "FAIL"]
        assert not failures, failures


@pytest.mark.network
def test_verify_filing_reads_the_mo1040_ssn_by_the_digits_the_1040_carries(tmp_path: Path):
    """A Form 1040 (digits-only SSN comb) and an MO-1040 filled with the same SSN, the MO box given WITH its dashes as
    its old pack comment asked: every identity check passes, and the MO SSN_1 check reports the same 9 digits as the
    1040's identifying_number. (The two checks key on the line name, SSN_1 and identifying_number, so verify_filing
    does not compare them with each other.)"""
    from taxfill_core.verify import FilingItem, verify_filing  # noqa: PLC0415

    f1040 = load_pack(REPO_ROOT / "formpacks/federal/2025/f1040/pack.yaml")
    mo1040 = load_pack(REPO_ROOT / "formpacks/states/mo/2025/mo1040/pack.yaml")
    federal_pdf, state_pdf = tmp_path / "f1040.pdf", tmp_path / "mo1040.pdf"
    fill_form(f1040, {"identifying_number": "999-88-0507"}, _blank(f1040), federal_pdf)
    fill_form(mo1040, {"SSN_1": "999-88-0507", "firstname-1": "Pat", "lastname-1": "Example"}, _blank(mo1040),
              state_pdf)
    report = verify_filing([FilingItem(form_key="f1040", pack=f1040, pdf_path=str(federal_pdf)),
                            FilingItem(form_key="mo1040", pack=mo1040, pdf_path=str(state_pdf))])
    checks = {check.field: check for check in report.identity}
    failures = [check.detail for check in report.identity if check.status == "FAIL"]
    assert not failures, failures
    assert checks["identifying_number"].status == checks["SSN_1"].status == "PASS"
    assert checks["identifying_number"].values == {"f1040": "999880507"}
    assert checks["SSN_1"].values == {"mo1040": "999880507"}
