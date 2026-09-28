"""Phase J JS4c — the CT-1040 2023 overlay pilot: every line of the manifest stamps into its printed box.

The coordinates were measured from the blank's own vector rectangles and underline strokes, stamped with
sentinels, verified and read page by page (formpacks/states/ct/2023/ct1040/handfill.yaml says how). This file
keeps that true: a demo return stamps with no warning, the OVERLAY verdict passes on all 160+ placements, the
SSN lands in all four page headers, and a wrong value still FAILS on the real form.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

CT = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "ct" / "2023" / "ct1040" / "handfill.yaml"

# A demo married-filing-jointly return (placeholder identifiers only).
GOLDEN = {
    "identifying_number": "123-45-6789", "spouse.identifying_number": "123-45-6780",
    "name.first": "TESS", "name.mi": "Q", "name.last": "TAXPAYER", "name.suffix": "JR",
    "spouse.first_name": "SAM", "spouse.mi": "R", "spouse.last_name": "TAXPAYER",
    "mailing_address.street": "100 DEMO STREET", "mailing_address.street2": "APT 2", "mailing_address.city": "HARTFORD",
    "mailing_address.state": "CT", "mailing_address.zip": "06101",
    "filing_status.mfj": "yes", "attach.ct_dependent": "yes",
    "1": 98500, "2": 1200, "4": 3400, "6": 3950, "7": 250, "9": 0, "11": 300, "13": 0, "15": 45,
    "18a.fein": "12-3456789", "18a.wages": 91000, "18a": 3100, "18b.fein": "12-3456789", "18b.wages": 7500, "18b": 420,
    "19": 500, "20": 0, "20a": 0, "20b": 0, "20c": 0, "23": 0, "24": 0, "24a": 5,
    "25a.checking": "yes", "25b": "011000015", "25c": "000123456789",
    "signature.date": "04012024", "signature.phone": "860-555-0100", "spouse.signature_date": "04012024",
    "signature.email": "tess@example.com",
    "31": 1200, "39": 400, "42": 3000, "51": 98300, "52a": "NEW YORK", "52a.code": "NY", "53a": 5200, "54a": "0.0529",
    "56a": 190, "57a": 250,
    "60.town": "HARTFORD", "60.description": "100 DEMO STREET", "60.date_1": "07-15-2023", "60.date_2": "01-15-2024",
    "60.amount": 4200, "61.town": "HARTFORD", "61.description": "2019 DEMO SEDAN", "61.date_1": "07-15-2023",
    "61.amount": 310, "63": 4510, "65": 300, "66": ".00", "67": 0, "69b": 45, "70a": 5,
}


# Every remaining entry filled too — a fiscal-year, paid-preparer, designee return — so every box is exercised.
FULL = {
    **GOLDEN, "tax_year.begin": "04-01", "tax_year.end": "03-31-2024", "spouse.suffix": "SR",
    "mailing_address.country_code": "CAN", "residence.city": "WEST HARTFORD", "residence.zip": "06107",
    "signature.daytime_phone": "860-555-0101", "preparer.date": "04022024", "preparer.phone": "203-555-0102",
    "preparer.name": "PAT PREPARER", "preparer.fein": "12-3456789", "preparer.self_employed": "yes",
    "preparer.firm": "DEMO TAX SERVICES, 1 MAIN ST, HARTFORD CT 06103", "preparer.ptin": "P01234567",
    "designee.name": "DANA DESIGNEE", "designee.phone": "860-555-0103", "designee.pin": "12345",
    "18c.fein": "12-3456789", "18c.wages": 1200, "18c": 60, "25d": "yes", "37": 150, "48": 500, "48.account": "123456789",
    "52b": "OHIO", "52b.code": "OH", "53b": 800, "54b": "0.0081", "57b": 40,
    "62.town": "HARTFORD", "62.description": "2021 DEMO WAGON", "62.date_1": "07-15-2023", "62.date_2": "01-15-2024",
    "62.amount": 280,
}


def test_js4c_every_ct1040_line_carries_coordinates():
    pack = load_hand_fill_pack(CT)
    assert [ln.line for ln in pack.lines if not ln.boxes] == []
    ssn = next(ln for ln in pack.lines if ln.line == "identifying_number")
    assert [b.page for b in ssn.boxes] == [1, 2, 3, 4]              # page 1 and every page header
    assert all(b.cells and len(b.cells) == 9 for b in ssn.boxes)   # 3-2-4 around the printed dashes


@pytest.mark.network
def test_js4c_the_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(CT)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the CT-1040 blank: {exc}")
    result = stamp_overlay(blank, pack, GOLDEN, tmp_path / "ct1040.pdf")
    assert result.warnings == [] and result.hand_written_lines == []
    assert sorted(s.page for s in result.stamped_lines if s.line == "identifying_number") == [1, 2, 3, 4]
    report = verify_overlay(pack, result.out_path, GOLDEN)
    assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    assert len(report.checks) == sum(len(ln.boxes) for ln in pack.lines)   # blank lines' boxes are checked empty
    wrong = verify_overlay(pack, result.out_path, {**GOLDEN, "1": 8500})    # stamped 98,500 is not 8,500
    assert not wrong.ok and [c.line for c in wrong.checks if c.status == "FAIL"] == ["1", "3", "5"]
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 4 and all(Path(p.path).stat().st_size > 1000 for p in pages)
    full = stamp_overlay(blank, pack, FULL, tmp_path / "full.pdf")
    assert full.warnings == [] and verify_overlay(pack, full.out_path, FULL).ok
