"""P-030: NJ-1040 line 6 — a pre-printed oval must not shift the row's keys.

Line 6 ("Regular") prints three ovals, each LEFT of its label: "Self" (printed solid black, no widget — every
filer takes it), "Spouse/CU Partner" and "Domestic Partner". The 2023 and 2024 packs once keyed the row's two
widgets by order (``_self``, ``_spouse_cu``), one oval off, so a "self" answer marked Spouse/CU Partner.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.discovery import load_form_pack

REPO = Path(__file__).resolve().parents[3]
YEARS = sorted(int(p.parent.parent.name) for p in (REPO / "formpacks" / "states" / "nj").glob("*/nj1040/pack.yaml"))
LABEL_RIGHT_OF = {"exemption_6_regular_spouse_cu": "Spouse/", "exemption_6_regular_domestic_partner": "Domestic"}


def test_p030_every_shipped_year_is_checked():
    assert {2023, 2024} <= set(YEARS)


@pytest.mark.parametrize("year", YEARS)
def test_p030_line6_keys_name_the_two_widget_ovals(year: int):
    lines = {f.line for f in load_form_pack("nj1040", year, "states/nj").fields}
    assert "exemption_6_regular_self" not in lines, "Self is pre-printed: no widget, so no key (P-030)"
    assert set(LABEL_RIGHT_OF) <= lines


@pytest.mark.network
@pytest.mark.parametrize("year", YEARS)
def test_p030_the_label_printed_right_of_each_line6_widget_matches_its_key(year: int):
    import pypdf
    import pypdfium2 as pdfium

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(REPO / "formpacks" / "states" / "nj" / str(year) / "nj1040" / "pack.yaml")
    blank = fetch_pack_blank(pack)
    field_of = {f.line: f.field for f in pack.fields}
    rects = {}
    for page_no, page in enumerate(pypdf.PdfReader(str(blank)).pages):
        for annot in page.get("/Annots", []) or []:
            annot = annot.get_object()
            name = annot.get("/T") or (annot["/Parent"].get_object().get("/T") if "/Parent" in annot else None)
            if name in {field_of[k] for k in LABEL_RIGHT_OF}:
                rects[name] = (page_no, [float(v) for v in annot["/Rect"]])
    textpages = {}
    for key, label in LABEL_RIGHT_OF.items():
        page_no, (x0, y0, x1, y1) = rects[field_of[key]]
        if page_no not in textpages:
            textpages[page_no] = pdfium.PdfDocument(str(blank))[page_no].get_textpage()
        right = textpages[page_no].get_text_bounded(left=x1, bottom=y0 - 4, right=x1 + 70, top=y1 + 12)
        assert label in right, f"{year} {key} -> {field_of[key]}: the text right of the widget is {right!r}"
    page_no, (x0, y0, _, y1) = rects[field_of["exemption_6_regular_spouse_cu"]]
    left = textpages[page_no].get_text_bounded(left=x0 - 60, bottom=y0 - 4, right=x0, top=y1 + 4)
    assert "Self" in left, f"{year}: the pre-printed Self oval should sit left of the first widget, got {left!r}"
