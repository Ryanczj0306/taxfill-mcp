"""Phase J JS4d — the SC1040 2023 overlay: every line of the manifest stamps into its printed box.

Coordinates were measured from the blank's ruling lines and stamped, verified and read page by page (the
manifest's header says how); the same read found the 51 printed entries the manifest had never listed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

SC = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "sc" / "2023" / "sc1040" / "handfill.yaml"

# A demo married-filing-jointly return (placeholder identifiers only).
GOLDEN = {
    "identifying_number": "123-45-6789", "spouse.identifying_number": "123-45-6780",
    "name.first": "TESS Q", "name.last": "TAXPAYER", "spouse.first_name": "SAM R", "spouse.last_name": "TAXPAYER",
    "mailing_address.street": "100 DEMO STREET", "county_code": "40", "mailing_address.city": "COLUMBIA",
    "mailing_address.state": "SC", "mailing_address.zip": "29201", "phone": "803-555-0100",
    "filing_status.mfj": "yes", "dependents_count": "1", "dependents_under6_count": "1", "taxpayers_65_count": "0",
    "dependent_1.first_name": "DANI", "dependent_1.last_name": "TAXPAYER", "dependent_1.ssn": "999-88-0001",
    "dependent_1.relationship": "DAUGHTER", "dependent_1.date_of_birth": "03/14/2020",
    "1": 72500, "a": 1500, "f": 400, "w": 4610, "t": 4610, "6": 2600, "11": 0, "12": 150, "13": 0,
    "16": 2900, "17": 0, "18": 0, "19": 0, "20": 0, "21": 0, "22a": 0, "22b": 0, "22c": 0, "22d": 0,
    "26": 0, "26.no_use_tax": "yes", "27": 0, "28": 0, "35.direct_deposit": "yes", "37.checking": "yes",
    "37.routing": "011000015", "37.account": "000123456789", "signature.date": "04/01/2024",
}
FULL = {
    **GOLDEN, "tax_year.begin": "04/01", "tax_year.end": "03/31", "name.suffix": "JR", "spouse.suffix": "SR",
    "new_address": "yes", "combat_zone": "yes", "combat_zone_name": "DEMO ZONE", "extension": "yes",
    "b": 300, "b.type": "RENTAL LOSS", "h": 800, "h.other": "yes", "h.other_type": "ROYALTY", "j": 50, "j.type": "FIRE",
    "p.taxpayer": 3000, "p.taxpayer.dob": "05/01/1960", "q.spouse": 1200, "q.spouse.dob": "06/02/1957",
    "s": 80, "s.days": "10", "32.penalties": 10, "32.interest": 5, "33": 20, "33.exception_code": "A",
    "36.withdrawal_date": "04/15/2024", "36.withdrawal_amount": 75,
    "dependent_2.first_name": "DREW", "dependent_2.last_name": "TAXPAYER", "dependent_2.ssn": "999-88-0002",
    "dependent_2.relationship": "SON", "dependent_2.date_of_birth": "07/04/2016",
    "preparer_discussion.yes": "yes", "preparer.name": "PAT PREPARER", "preparer.date": "04/02/2024",
    "preparer.self_employed": "yes", "preparer.ptin": "P01234567", "preparer.firm": "DEMO TAX SERVICES, 1 MAIN ST, COLUMBIA SC 29201",
    "preparer.fein": "12-3456789", "preparer.phone": "803-555-0101",
}


def test_js4d_every_sc1040_line_carries_coordinates_and_the_ssn_repeats_in_the_headers():
    pack = load_hand_fill_pack(SC)
    assert [ln.line for ln in pack.lines if not ln.boxes] == []
    ssn = next(ln for ln in pack.lines if ln.line == "identifying_number")
    assert [b.page for b in ssn.boxes] == [1, 2, 3]


def test_js4d_lines_4_and_32_add_their_dotted_sub_lines():
    # Manual until the compute grammar took dotted ids (JP5c): the p/q sub-lines and Line 32's two blanks.
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(SC), FULL).lines}
    assert (ws["4"], ws["5"], ws["32"], ws["34"]) == ("14,750", "59,550", "15", "35")


@pytest.mark.network
def test_js4d_the_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(SC)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the SC1040 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "sc1040.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    wrong = verify_overlay(pack, result.out_path, {**FULL, "1": 7250})
    assert not wrong.ok and "1" in [c.line for c in wrong.checks if c.status == "FAIL"]
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 3 and all(Path(p.path).stat().st_size > 1000 for p in pages)
