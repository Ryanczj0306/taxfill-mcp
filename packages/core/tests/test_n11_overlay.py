"""Phase J JS4d — the HI N-11 2023 overlay: every line of the manifest stamps into its printed box.

N-11 is a machine-read form: one character per printed cell, ovals PAINTED (overlay.mark: fill) and a loss
shown by shading the printed minus (overlay.minus), as its page-2 Example shows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

HI = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "hi" / "2023" / "n11" / "handfill.yaml"

# A demo married-filing-jointly return (placeholder identifiers only).
GOLDEN = {
    "name.first": "TESS", "name.mi": "Q", "name.last": "TAXPAYER", "name.last_four": "TAXP",
    "identifying_number": "123-45-6789",
    "spouse.first_name": "SAM", "spouse.mi": "R", "spouse.last_name": "TAXPAYER", "spouse.last_four": "TAXP",
    "spouse.identifying_number": "123-45-6780",
    "mailing_address.street": "100 DEMO STREET", "mailing_address.city": "HONOLULU",
    "mailing_address.state": "HI", "mailing_address.zip": "96813",
    "filing_status.mfj": "yes", "6a.yourself": "yes", "6b.spouse": "yes", "6b.count": 2,
    "dependent_1.name": "DANI TAXPAYER", "dependent_1.ssn": "999-88-0001", "dependent_1.relationship": "DAUGHTER",
    "6c": 1, "6d": 0, "name.as_shown": "TESS Q AND SAM R TAXPAYER",
    "7": 88000, "8": 0, "9": 0, "10": 0, "13": 0, "14": 0, "15": 0, "16": 0, "17": 0, "18": 0,
    "23": 4400, "24": 83600, "25": 3432, "27.tax_table": "yes", "27": 5176,
    "28": 0, "29": 0, "30": 0, "31": 0, "32": 0, "35": 0, "37": 5800, "38": 0, "39": 0, "40": 0,
    "43a.yourself": "yes", "44": 2, "46": 0, "47b": "011000015", "47c.checking": "yes", "47d": "000123456789",
    "53.no": "yes", "54.no": "yes", "55.no": "yes", "election_fund.yourself": "yes",
    "signature.date": "04/01/2024", "spouse.signature_date": "04/01/2024",
    "signature.occupation": "ENGINEER", "signature.daytime_phone": "808-555-0100",
    "spouse.occupation": "TEACHER", "spouse.daytime_phone": "808-555-0101",
}
# Every line: a loss year (minus boxes shaded on 7, 12, 20, 24, 34, 36, 51, 52), every oval painted.
FULL = {
    **GOLDEN, "tax_year.begin": "04/01/23", "tax_year.end": "03/31/24",
    "amended": "yes", "nol_carryback": "yes", "irs_adjustment": "yes", "first_time_filer": "yes",
    "name.suffix": "JR", "spouse.suffix": "SR", "deceased.taxpayer": "yes", "deceased.taxpayer_date": "05/05/23",
    "deceased.spouse": "yes", "deceased.spouse_date": "06/06/23", "care_of": "PAT PAYEE",
    "mailing_address.foreign_province": "ONTARIO", "mailing_address.country": "CANADA",
    "filing_status.single": "yes", "filing_status.mfs": "yes", "filing_status.hoh": "yes", "filing_status.qss": "yes",
    "filing_status.mfs_spouse_name": "SAM R TAXPAYER", "filing_status.hoh_name": "DREW TAXPAYER",
    "6a.age65": "yes", "6b.age65": "yes", "6b.count": 4, "6b.mfs_spouse": "yes",
    **{f"dependent_{i}.name": f"CHILD{i} TAXPAYER" for i in range(2, 7)},
    **{f"dependent_{i}.ssn": f"999-88-000{i}" for i in range(2, 7)},
    **{f"dependent_{i}.relationship": "SON" for i in range(2, 7)},
    "6c": 6, "6d": 12,
    "7": -4500, "8": 100, "9": 200, "10": 300, "claimed_as_dependent": "yes",
    "21a": 100, "21b": 200, "21c": 300, "21d": 400, "21e": 50, "21f": 60, "22": 1110, "24": -5010,
    "25.disabled.yourself": "yes", "25.disabled.spouse": "yes", "25": 22880,
    "27.tax_rate_schedule": "yes", "27.capital_gains_worksheet": "yes", "27.other_forms": "yes", "27": 0, "27a": 0,
    "28.dhs_exemptions": "3", "28": 330, "29": 150,
    "43a.spouse": "yes", "43b.yourself": "yes", "43b.spouse": "yes", "43c.yourself": "yes", "43c.spouse": "yes",
    "44": 24, "46": 100, "47a.foreign_bank": "yes", "47c.savings": "yes",
    "49": 0, "50": 25, "50.n210": "yes", "51": -300, "52": -1200,
    "53.yes": "yes", "53": 50000, "53.activity": "CONSULTING", "53.product": "SOFTWARE", "53.ge_id": "123-456-7890-01",
    "54.yes": "yes", "54": 24000, "54.ge_id": "123-456-7890-02",
    "55.yes": "yes", "55": 1000, "55.activity": "FARMING", "55.product": "PAPAYA", "55.ge_id": "123-456-7890-03",
    "designee.name": "PAT PAYEE", "designee.phone": "808-555-0102", "designee.id_number": "12345",
    "election_fund.spouse": "yes",
    "preparer.date": "04/02/2024", "preparer.self_employed": "yes", "preparer.ptin": "P01234567",
    "preparer.name": "PAT PREPARER", "preparer.fein": "12-3456789", "preparer.firm": "DEMO TAX SERVICES, HONOLULU 96813",
    "preparer.phone": "808-555-0103",
}
MINUS_LINES = ("7", "12", "20", "24", "34", "36", "51", "52")


def test_js4d_every_n11_line_carries_coordinates_and_the_header_repeats_on_pages_2_to_4():
    pack = load_hand_fill_pack(HI)
    assert [ln.line for ln in pack.lines if not ln.boxes] == []
    by_line = {ln.line: ln for ln in pack.lines}
    assert [b.page for b in by_line["identifying_number"].boxes] == [1, 2, 3, 4]
    assert [b.page for b in by_line["spouse.identifying_number"].boxes] == [1, 2, 3, 4]
    assert [b.page for b in by_line["name.as_shown"].boxes] == [2, 3, 4]
    # every oval is painted (the preparer's self-employed SQUARE takes an X), and every printed minus box is
    # declared on its money line
    marks = {ln.line: b.mark for ln in pack.lines if ln.type == "checkbox" for b in ln.boxes}
    assert {k for k, m in marks.items() if m != "fill"} == {"preparer.self_employed"} and len(marks) == 42
    assert sorted(ln.line for ln in pack.lines if any(b.minus for b in ln.boxes)) == sorted(MINUS_LINES)


def test_js4d_the_computes_follow_the_face():
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(HI), GOLDEN).lines}
    assert (ws["6e"], ws["20"], ws["26"], ws["36"], ws["41"]) == ("3", "88,000", "80,168", "5,176", "5,800")
    assert (ws["42"], ws["45"], ws["47a"], ws["48"]) == ("624", "622", "622", "0")
    assert ws["22"] == ""        # itemizers only, after the page-19 limitation: never computed
    loss = {ln.line: ln.value for ln in hand_fill_worksheet(load_hand_fill_pack(HI), FULL).lines}
    # a negative Balance (line 36) is overpaid by its absolute value plus the payments (Instructions page 22)
    assert (loss["34"], loss["36"], loss["42"], loss["48"]) == ("-480", "-480", "6,280", "0")


@pytest.mark.network
def test_js4d_the_demo_return_stamps_cleanly_and_verifies_on_the_real_blank(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(HI)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the N-11 blank: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "n11.pdf")
        assert result.warnings == [] and result.hand_written_lines == []
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
    loss = next(s for s in result.stamped_lines if s.line == "7")
    assert loss.value == "4500"                                  # digits unsigned: the minus box carries the sign
    wrong = verify_overlay(pack, result.out_path, {**FULL, "7": 4500, "amended": ""})
    failed = {c.line for c in wrong.checks if c.status == "FAIL"}
    assert {"7", "amended"} <= failed                            # a shaded minus and a painted oval both read back
    assert len(render_pdf(result.out_path, tmp_path / "png")) == 4
