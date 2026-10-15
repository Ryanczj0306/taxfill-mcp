"""P-032: Form 1040ME lines 21/22/23 — a widget's NAME is not its row.

Page 2 of every 1040ME blank since 2023 names three money widgets "1040ME Nonresident credit",
"1040ME Total tax" and "1040ME Tax credits", and prints them rotated against those captions: "Total tax"
sits on the row printed 21 (NONRESIDENT CREDIT), "Tax credits" on 22 (TOTAL TAX) and "Nonresident credit"
on 23 (NONREFUNDABLE TAX CREDITS). The 2023 pack once bound the three lines by widget name, so a filer's
line-21 amount landed in the line-23 box, 22's in 21's and 23's in 22's — and the relations
22 == 20 + 20a - 21 and 24 == 22 - 23, written against the KEYS, passed. This measures, on every shipped
year's own blank, that the widget bound to each of the three keys has that key's number printed in the
gutter left of it, and pins the (key, widget) map offline so a revert fails PR CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKS = sorted((REPO / "formpacks" / "states" / "me").glob("*/f1040me/pack.yaml"))
LINES = ("21", "22", "23")

# The widget that sits on each printed row, identical on the 2023, 2024 and 2025 blanks.
ROW_WIDGET = {
    "21": "1040ME Total tax",
    "22": "1040ME Tax credits",
    "23": "1040ME Nonresident credit",
}


def test_p032_every_shipped_year_is_checked():
    assert {p.parent.parent.name for p in PACKS} >= {"2023", "2025"}


@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.parent.name)
def test_p032_lines_21_23_bind_the_widget_on_the_printed_row(path: Path):
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(path)
    field_of = {f.line: f.field for f in pack.fields}
    assert {k: field_of.get(k) for k in LINES} == ROW_WIDGET
    # The keys did not move, so the face arithmetic the pack declares is unchanged.
    assert "22 == 20 + 20a - 21" in pack.relations
    assert "24 == 22 - 23" in pack.relations


@pytest.mark.network
@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.parent.name)
def test_p032_the_number_printed_left_of_each_widget_equals_its_key(path: Path):
    import pypdf
    import pypdfium2 as pdfium

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(path)
    blank = fetch_pack_blank(pack)
    field_of = {f.line: f.field for f in pack.fields}
    key_of = {field_of[k]: k for k in LINES}
    rects: dict[str, tuple[int, list[float]]] = {}
    for page_no, page in enumerate(pypdf.PdfReader(str(blank)).pages):
        for annot in page.get("/Annots", []) or []:
            annot = annot.get_object()
            name = annot.get("/T") or (annot["/Parent"].get_object().get("/T") if "/Parent" in annot else None)
            if str(name) in key_of:
                rects[str(name)] = (page_no, [float(v) for v in annot["/Rect"]])
    assert set(rects) == set(key_of), f"widgets bound to lines 21-23 not all found on the blank: {sorted(rects)}"
    doc = pdfium.PdfDocument(str(blank))
    textpages: dict[int, object] = {}
    wrong = []
    for name, key in key_of.items():
        page_no, (x0, y0, _, y1) = rects[name]
        textpage = textpages.setdefault(page_no, doc[page_no].get_textpage())
        # The right-hand column prints "21." / "22." / "23." in the ~45 pt gutter left of each money box.
        gutter = textpage.get_text_bounded(left=x0 - 45, bottom=y0, right=x0, top=y1)
        printed = re.search(r"(\d+[a-z]?)\.", gutter)
        if not printed or printed.group(1) != key:
            wrong.append(f"key {key!r} -> {name!r} sits beside printed {gutter.strip()!r}")
    assert not wrong, "\n".join(wrong)
