"""Phase J JS5 — the WV IT-140 2025 overlay: a print-only return inside the 2025 booklet, stamped end to end.

WV published no fillable 2025 IT-140; the return is pages 3-4 of the 56-page, AES-encrypted (empty user password)
Forms and Instructions booklet. formpacks/states/wv/2025/it140/handfill.yaml measured every box from those pages'
own ruling lines and caption cells (its banner says how). This file keeps that true: the manifest covers every
printed entry with coordinates, the demo and full returns stamp with no warning onto the real booklet, the OVERLAY
verdict passes on all 114 placements, the identity repeats in the page 2 header, a wrong value still FAILS, and the
stamped output is the two return pages only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.handfill import hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.overlay import stamp_overlay, verify_overlay

WV = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "wv" / "2025" / "it140" / "handfill.yaml"

# A demo married-filing-jointly resident return with a refund (placeholder identifiers only).
GOLDEN = {
    "identifying_number": "123-45-6789", "spouse.identifying_number": "123-45-6780",
    "name.last": "TAXPAYER", "name.first": "TESS", "name.middle_initial": "Q",
    "spouse.name.last": "TAXPAYER", "spouse.name.first": "SAM", "spouse.name.middle_initial": "R",
    "mailing_address.street": "100 DEMO STREET", "mailing_address.city": "CHARLESTON", "mailing_address.state": "WV",
    "mailing_address.zip": "25301", "telephone_number": "304-555-0100", "email": "tess@example.com",
    "filing_status.married_filing_joint": "yes",
    "exemptions.a": "1", "exemptions.b": "1", "exemptions.c": "1", "exemptions.e": "3",
    "dependent_1.name.first": "DANA", "dependent_1.name.last": "TAXPAYER", "dependent_1.ssn": "999-88-0001",
    "dependent_1.date_of_birth": "05 14 2018",
    "1": 98500, "2": 1200, "3": 4300, "6.count": "3", "6": 6000, "8": 3350, "8.method.tax_table": "yes",
    "9": 150, "13": 40, "15": 3600, "16": 500, "25": 860, "26a": 5, "27": 100, "28": 755,
    "refund.account_type.checking": "yes", "refund.routing_number": "011000015", "refund.account_number": "000123456789",
    "signature.discuss_with_preparer.no": "yes",
    "signature.date": "04/01/2026", "spouse.signature_date": "04/01/2026", "signature.telephone": "304-555-0100",
}

# Every box exercised: a loss on line 1, every check box marked, the amended / penalty / credit / preparer entries.
FULL = {
    **GOLDEN,
    "deceased.taxpayer": "yes", "deceased.taxpayer.date_of_death": "03/02/2025",
    "spouse.deceased": "yes", "spouse.deceased.date_of_death": "04/03/2025",
    "name.suffix": "JR", "spouse.name.suffix": "SR", "mailing_address.street2": "APT 2",
    "extended_due_date": "10/15/2026",
    "amended_return.yes": "yes", "nonresident_special.yes": "yes", "nonresident_part_year.yes": "yes", "injured_spouse.yes": "yes",
    "filing_status.single": "yes", "filing_status.head_of_household": "yes", "filing_status.married_filing_separate": "yes",
    "filing_status.widow": "yes",
    "exemptions.c": "4", "exemptions.d": "1", "exemptions.e": "7", "exemptions.d.decedent_ssn": "999-88-0002",
    "exemptions.d.year_spouse_died": "2024",
    "dependent_2.name.first": "DREW", "dependent_2.name.last": "TAXPAYER", "dependent_2.ssn": "999-88-0003",
    "dependent_2.date_of_birth": "08 22 2015",
    "dependent_3.name.first": "DALE", "dependent_3.name.last": "TAXPAYER", "dependent_3.ssn": "999-88-0004",
    "dependent_3.date_of_birth": "11 30 2012",
    "dependent_4.name.first": "DEVON", "dependent_4.name.last": "TAXPAYER", "dependent_4.ssn": "999-88-0005",
    "dependent_4.date_of_birth": "01 09 2021",
    "1": -8300, "2": 1200, "3": 500, "5": 100, "6.count": "7", "6": 14000, "8": 10,
    "8.method.rate_schedule": "yes", "8.method.nonresident_part_year": "yes",
    "9": 5, "11": 50, "12": 25, "12.request_waiver": "yes", "12.qualified_farmer": "yes", "12.request_annualized": "yes",
    "12.request_short_method": "yes", "13": 40, "13.no_use_tax": "yes", "15": 3600, "15.nrsr_withholding": "yes",
    "16": 500, "17": 60, "18": 70, "19": 80, "20": 90, "21a": 110, "21b": 120, "21c": 130, "22": 75,
    "24": 120, "25": 4715, "26a": 5, "26b": 6, "26c": 7, "27": 100, "28": 4597,
    "refund.account_type.savings": "yes", "signature.discuss_with_preparer.yes": "yes",
    "preparer.id_number": "12-3456789", "preparer.date": "04/02/2026", "preparer.telephone": "304-555-0102",
    "preparer.name": "PAT PREPARER", "preparer.firm": "DEMO TAX SERVICES",
}

MONEY_LINES = [str(n) for n in range(1, 29)] + ["21a", "21b", "21c", "26a", "26b", "26c"]


def test_js5_the_2025_manifest_covers_the_two_return_pages_of_the_booklet():
    pack = load_hand_fill_pack(WV)
    assert pack.tax_year == 2025 and pack.source_pages == [3, 4]
    assert pack.source_url.endswith("/PIT/2025/it140.PersonalIncomeTaxFormsAndInstructions.2025.pdf")
    assert [ln.line for ln in pack.lines if not ln.boxes] == []                      # nothing is left hand-written
    assert sum(len(ln.boxes) for ln in pack.lines) == 114 and len(pack.lines) == 112
    assert {b.page for ln in pack.lines for b in ln.boxes} == {1, 2}
    by = {ln.line: ln for ln in pack.lines}
    assert [b.page for b in by["identifying_number"].boxes] == [1, 2]                 # SSN also in the page 2 header
    assert [b.page for b in by["name.last"].boxes] == [1, 2]                          # PRIMARY LAST NAME up there too
    assert all(by[k].type == "money" for k in MONEY_LINES)
    # the 2025 face renumbered page 2: the new penalty line 12 and credit line 21 carry their own boxes
    assert {"12.request_waiver", "12.qualified_farmer", "12.request_annualized", "12.request_short_method"} <= by.keys()
    assert "21 A. Motor Vehicle" in by["21a"].label and "26 A. Children" in by["26a"].label
    assert by["2"].label == "Additions to income (line 61 of Schedule M)" and "line 59" in by["2"].note
    assert all(b.cells is None and b.comb is None and b.mark is None and b.minus is None
               for ln in pack.lines for b in ln.boxes)                                 # plain boxes and X marks only
    assert sorted(ln.line for ln in pack.lines if ln.compute) == ["10", "14", "21", "23", "26", "4", "7"]


def test_js5_the_2025_computes_follow_the_face():
    pack = load_hand_fill_pack(WV)
    ws = {ln.line: ln.value for ln in hand_fill_worksheet(pack, GOLDEN).lines}
    assert (ws["4"], ws["7"], ws["10"], ws["14"]) == ("95400", "89400", "3200", "3240")  # money_style plain: no commas
    # blank_zero_computes: line 21 (no credit claimed) stays BLANK per the tips, not "0"; 24 is entered-only
    assert (ws["21"], ws["23"], ws["24"], ws["25"], ws["26"], ws["28"]) == ("", "4100", "", "860", "5", "755")
    full = {ln.line: ln.value for ln in hand_fill_worksheet(pack, FULL).lines}
    assert (full["4"], full["7"], full["10"], full["21"], full["23"]) == ("-7600", "0", "5", "360", "4835")
    assert pack.money_style == "plain" and pack.blank_zero_computes is True  # the booklet's own tips (P-029)


@pytest.mark.network
def test_js5_the_demo_returns_stamp_cleanly_and_verify_on_the_real_booklet(tmp_path):
    from taxfill_core.fetch import OfflineFetchError, fetch_blank
    from taxfill_core.render import render_pdf

    pack = load_hand_fill_pack(WV)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:  # pragma: no cover - offline with a cold cache
        pytest.skip(f"cannot fetch the 2025 IT-140 booklet: {exc}")
    for values in (GOLDEN, FULL):
        result = stamp_overlay(blank, pack, values, tmp_path / "it140_2025.pdf")
        assert result.warnings == [] and result.hand_written_lines == [] and result.page_count == 2
        assert sorted(s.page for s in result.stamped_lines if s.line == "identifying_number") == [1, 2]
        report = verify_overlay(pack, result.out_path, values)
        assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
        assert len(report.checks) == 114                                              # blank lines' boxes are checked empty
        # the independent recompute: a blank-by-rule compute (GOLDEN's 21, no credit) agrees with a recompute of 0
        # instead of asking the caller to stamp the 0 the tips forbid (P-029); FULL's 7 is a stamped 0 whose operands exist
        indep = {"4": 95400, "21": 0, "23": 4100} if values is GOLDEN else {"4": -7600, "7": 0, "21": 360}
        checked = verify_overlay(pack, result.out_path, values, independent=indep)
        assert checked.ok and len(checked.recompute) == 3, [c.detail for c in checked.recompute]
    wrong = verify_overlay(pack, result.out_path, {**FULL, "1": 8300, "13.no_use_tax": "no"})   # -8,300 is not 8,300
    assert not wrong.ok and [c.line for c in wrong.checks if c.status == "FAIL"] == ["1", "4", "13.no_use_tax"]
    pages = render_pdf(result.out_path, tmp_path / "png")
    assert len(pages) == 2 and all(Path(p.path).stat().st_size > 1000 for p in pages)
