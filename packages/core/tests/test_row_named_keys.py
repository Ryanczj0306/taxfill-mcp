"""Keys named for the row their box sits on (Phase K, 2026-10-25): NY IT-203 lines 8-12, MT Form 2 2023 15a-15c.

NY IT-203 2023-2025 keyed lines 8-12 by the right line number but named them one row off (8_taxable_ira_fed sat on
the "Other gains or losses" box), so a caller choosing a key by its name would put IRA income on line 8. The
label-adjacency gate (JK10) compares line numbers only, so this test pins the names: offline, each field carries
the key below; with the cached blank, the face prints that line number followed by the words the key is named for.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from taxfill_core.schemas.formpack import load_pack

REPO = Path(__file__).resolve().parents[3]
YEARS = (2023, 2024, 2025)

# field -> (key, printed line, the words the face prints after the line number)
ROWS = {
    "federal 8 dollars": ("8_other_gains_fed", "8", "Other gains or losses"),
    "nys 8 dollars": ("8_other_gains_ny", "8", "Other gains or losses"),
    "line 9 box": ("9_iras_beneficiary", "9", "Taxable amount of IRA distributions. Beneficiaries: mark X in box"),
    "federal 9 dollars": ("9_taxable_ira_fed", "9", "Taxable amount of IRA distributions"),
    "nys 9 dollars": ("9_taxable_ira_ny", "9", "Taxable amount of IRA distributions"),
    "line 10 box": ("10_pensions_beneficiary", "10", "Taxable amount of pensions/annuities. Beneficiaries: mark X in box"),
    "federal 10 dollars": ("10_taxable_pensions_fed", "10", "Taxable amount of pensions/annuities"),
    "nys 10 dollars": ("10_taxable_pensions_ny", "10", "Taxable amount of pensions/annuities"),
    "federal 11 dollars": ("11_rental_partnership_fed", "11", "Rental real estate, royalties, partnerships"),
    "nys 11 dollars": ("11_rental_partnership_ny", "11", "Rental real estate, royalties, partnerships"),
    "federal 12 dollars": ("12_rental_real_estate_fed", "12", "Rental real estate included"),
    "federal 13 dollars": ("13_farm_income_fed", "13", "Farm income or loss"),
}


def _pack(year: int):
    return load_pack(REPO / "formpacks" / "states" / "ny" / str(year) / "it203" / "pack.yaml")


@pytest.mark.parametrize("year", YEARS)
def test_lines_8_to_13_carry_the_key_named_for_their_row(year):
    keys = {f.field: f.line for f in _pack(year).fields}
    assert {field: keys.get(field) for field in ROWS} == {field: row[0] for field, row in ROWS.items()}


@pytest.mark.network
@pytest.mark.parametrize("year", YEARS)
def test_the_face_prints_each_row_the_key_is_named_for(year):
    import pypdfium2 as pdfium

    from taxfill_core.fetch import fetch_pack_blank

    pdf = pdfium.PdfDocument(str(fetch_pack_blank(_pack(year))))
    text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    for key, line, words in ROWS.values():
        assert re.search(rf"(?m)^{line} {re.escape(words)}", text), f"{year} {key}: the face prints no '{line} {words}'"


def test_mt_form2_2023_credit_code_boxes_take_the_letter_codes():
    """MT Form 2 2023 lines 15a-15c: the 4-cell box is the "Tax credit code" and the codes are letters (BBSC, ...).

    It was keyed nrcredits.15a.year and mapped comb: true, which takes digits only, so no real code could be written.
    """
    pack = load_pack(REPO / "formpacks" / "states" / "mt" / "2023" / "form2" / "pack.yaml")
    by_field = {f.field: f for f in pack.fields}
    for x in "abc":
        f = by_field[f"Nonrefundable Credits Line 15{x}"]
        assert (f.line, f.type, f.comb, f.maxlen) == (f"nrcredits.15{x}.code", "text", False, 4)
