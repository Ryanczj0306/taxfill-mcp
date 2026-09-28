"""Phase J JS4d — the NM PIT-1 2023 overlay: every line of the manifest stamps into its printed box.

NM TRD serves the blank from its document-library host (an AWS API gateway), which fetch_blank now accepts only
against the manifest's pinned sha256 (fetch.PINNED_ONLY_BLANK_HOSTS).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

NM = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "nm" / "2023" / "pit1" / "handfill.yaml"

# A demo married-filing-jointly return (placeholder identifiers only).
GOLDEN = {
    "1a": "TESS Q TAXPAYER", "1b": "123-45-6789", "1e": "R", "1f": "01/15/1980",
    "2a": "SAM R TAXPAYER", "2b": "123-45-6780", "2e": "R", "2f": "02/20/1981",
    "3b": "100 DEMO STREET", "3c": "SANTA FE", "3c.state": "NM", "3c.zip": "87501",
    "5": "03", "filing_status.mfj": "yes",
    "dep1.first": "DANI", "dep1.last": "TAXPAYER", "dep1.ssn": "999-88-0001", "dep1.dob": "03/14/2020",
    "9": 88000, "10": 0, "11": 0, "12": 27700, "13": 0, "14": 0, "15": 0, "16": 0,
    "18": 2100, "18a": "R", "19": 0, "20": 0, "21": 0, "24": 0, "25": 0, "26": 0, "27": 2500, "28": 0, "29": 0,
    "30": 0, "31": 0, "34": 0, "36": 0, "37": 0, "40": 0, "41": 0,
    "re.routing": "011000015", "re.account": "000123456789", "re.checking": "yes", "re.foreign_no": "yes",
    "signature.date": "04/01/2024", "signature.dl_number": "NONE", "spouse.signature_date": "04/01/2024",
    "spouse.dl_number": "DECLINED", "phone": "505-555-0100", "email": "tess@example.com",
}
FULL = {
    **GOLDEN, "tax_year.begin": "04/01/2023", "tax_year.end": "03/31/2024", "1c": "yes", "2d": "yes", "3a": "yes",
    "3d": "CANADA", "3d.province": "ONTARIO", "4a": "PAT PAYEE", "4b": "999-88-0003", "4c": "05/05/2023",
    "6a": "yes", "6b": "10/15/2024", "filing_status.hoh_person": "DREW TAXPAYER",
    "dep2.first": "DREW", "dep2.last": "TAXPAYER", "dep2.ssn": "999-88-0002", "dep2.dob": "07/04/2016",
    "9": -4500, "12a": "yes", "16": 300, "16a": 1200, "25": 150, "25a": 600, "35": "2",
    "hsd_share": "yes", "signature.dl_state": "NM", "signature.dl_expiration": "01/15/2028",
    "spouse.dl_state": "NM", "spouse.dl_expiration": "02/20/2027",
    "preparer.date": "04/02/2024", "preparer.firm": "DEMO TAX SERVICES", "preparer.nmbtin": "02-123456-00-0",
    "preparer.ptin": "P01234567", "preparer.fein": "12-3456789", "preparer.phone": "505-555-0101", "preparer.rpd41338": "yes",
}


def test_js4d_every_pit1_line_carries_coordinates_and_the_ssn_repeats_on_page_2():
    pack = load_hand_fill_pack(NM)
    assert [ln.line for ln in pack.lines if not ln.boxes] == []
    assert [b.page for b in next(ln for ln in pack.lines if ln.line == "1b").boxes] == [1, 2]


@pytest.mark.network
def test_js4d_the_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(NM)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)   # the pinned-only NM TRD host
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the PIT-1 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "pit1.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    loss = next(s for s in result.stamped_lines if s.line == "9")
    assert loss.value == "-4,500"                                       # NM: the minus sign left of the number
    wrong = verify_overlay(pack, result.out_path, {**FULL, "9": 4500})
    assert not wrong.ok and "9" in [c.line for c in wrong.checks if c.status == "FAIL"]
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 2
