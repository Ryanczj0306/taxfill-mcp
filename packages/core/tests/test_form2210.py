"""Phase J JP5c — the Form 2210 packs (2025 final, 2026 draft), verified by recomputing from JP5a/b.

``penalty.form2210_lines`` works Part III Section A the way the face prints it and checks each column's line 17
against the 6654(b)(3) ledger; with Schedule AI it adds every face line of JP5b's columns. The goldens fill a pack
from those lines, and verify must find every printed relation true and every recomputed line equal. Demo figures
only; the payment schedules are the Instructions for Form 2210 (2025) Example 3 and the JP5b Q4-heavy year.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.fetch import cached_blank_path
from taxfill_core.filler import fill_form, rehearsal_only
from taxfill_core.penalty import form2210_lines, underpayment_penalty
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import verify_form

from test_underpayment_penalty import EXAMPLE_3_PAYMENTS, Q4_HEAVY, Q4_PAYMENTS

REPO_ROOT = Path(__file__).resolve().parents[3]


def _pack(year: int):
    return load_pack(REPO_ROOT / f"formpacks/federal/{year}/f2210/pack.yaml")


def _cached_blank(pack) -> Path:
    path = cached_blank_path(pack.source_url, pack.pdf_sha256)
    if path is None:
        pytest.skip(f"the Form 2210 blank is not cached — warm it with fetch_blank({pack.source_url})")
    return path


def _part_i(line9: int) -> dict[str, int]:
    # A demo Part I whose line 9 is the prior-year safe harbor: 4 = 1 + 2 - 3, 5 = 90% of 4, 9 = min(5, 8).
    line4 = line9 + 4_000
    return {"1": line4 + 1_000, "2": 1_000, "3": 2_000, "4": line4, "5": round(line4 * 0.9), "7": line4, "8": line9,
            "9": line9}


def _golden(tmp_path, year: int, values: dict, lines: dict[str, int]):
    pack = _pack(year)
    rehearsal = rehearsal_only(pack)
    out = tmp_path / f"f2210_{year}.pdf"
    fill_form(pack, values, _cached_blank(pack), out, rehearsal=rehearsal)
    report = verify_form(pack, out, expected=values, independent=lines, rehearsal=rehearsal)
    fails = [c.detail for section in (report.assertions, report.relations, report.recompute, report.clipping,
                                      report.checkboxes) for c in section if c.status == "FAIL"]
    assert report.ok, fails
    assert {c.line for c in report.recompute if c.status == "PASS"} == set(lines)
    return report


def test_jp5c_section_a_follows_the_face_and_agrees_with_the_ledger():
    r = underpayment_penalty([4000] * 4, EXAMPLE_3_PAYMENTS, year=2025)
    lines = form2210_lines(r)
    # Line 11 per window: (a) 4/30 is AFTER 4/15, so column (a) holds nothing; 6/15 lands in (b), 9/15 in (c), 1/15
    # in (d) — and the 4/30 payment sits in column (b)'s window (after April 15 through June 15).
    assert [lines[f"11.{c}"] for c in "abcd"] == [0, 5000, 4000, 4000]
    assert [lines[f"17.{c}"] for c in "abcd"] == [row.underpayment for row in r.installments] == [4000, 3000, 3000, 3000]
    assert (lines["14.b"], lines["15.b"], lines["16.b"]) == (4000, 1000, 0)
    assert lines["19"] == r.penalty_whole_dollars == 204


def test_jp5c_golden_round_trip_regular_method(tmp_path):
    r = underpayment_penalty(required_annual_payment=16000, payments=EXAMPLE_3_PAYMENTS, year=2025)
    lines = form2210_lines(r)
    values = {"name": "Demo Filer", "identifying_number": "123-45-6789", "line9_more_than_line6.yes": True,
              **_part_i(16000), **lines}
    report = _golden(tmp_path, 2025, values, lines)
    passed = {c.relation for c in report.relations if c.status == "PASS"}
    assert {"9 == min(5, 8)", "14.b == 17.a", "15.c == max(0, 13.c - 14.c)", "17.d == max(0, 10.d - 15.d)"} <= passed
    # The regular method leaves Schedule AI blank, and every declared Schedule AI relation holds on the blank (the
    # line-24 "25% of line 9" and line-31 "line 29 minus line 30" rows are exactly the two that would not, so the
    # pack does not declare them).
    assert not [c for c in report.relations if c.relation.startswith("ai.") and c.status != "PASS"]
    assert not [r for r in _pack(2025).relations if r.startswith(("ai.24", "ai.31"))]


def test_jp5c_golden_round_trip_with_schedule_ai(tmp_path):
    r = underpayment_penalty(required_annual_payment=12000, payments=Q4_PAYMENTS, year=2025,
                             annualized={**Q4_HEAVY, "se_net_earnings": [4000, 6000, 9000, 20000]})
    lines = form2210_lines(r)
    assert [lines[f"10.{c}"] for c in "abcd"] == [lines[f"ai.27.{c}"] for c in "abcd"]   # box C: line 10 = AI 27
    values = {"name": "Demo Filer", "identifying_number": "123-45-6789", "line9_more_than_line6.yes": True,
              "part_ii.c": True, **_part_i(12000), **lines}
    report = _golden(tmp_path, 2025, values, lines)
    passed = {c.relation for c in report.relations if c.status == "PASS"}
    assert {"ai.3.b == ai.1.b * 2.4", "ai.26.a == ai.24.a", "ai.27.c == min(ai.23.c, ai.26.c)",
            "ai.33.a == 0.496 * min(ai.28.a, ai.31.a)", "ai.15.d == ai.36.d"} <= passed


def test_jp5c_the_2026_draft_golden_uses_line_9b_in_rehearsal_mode(tmp_path):
    r = underpayment_penalty(required_annual_payment=8000, year=2026, payments=[{"date": "2026-04-15", "amount": 8000}],
                             annualized={"filing_status": "single", "agi": [30000, 45000, 60000, 90000],
                                         "standard_deduction": 16100, "additional_deductions": [1000, 1500, 2000, 3000]})
    lines = form2210_lines(r)
    assert [lines[f"ai.9b.{c}"] for c in "abcd"] == [1000, 1500, 2000, 3000] and "ai.9.a" not in lines
    values = {"name": "Demo Filer", "identifying_number": "123-45-6789", "part_ii.c": True, **_part_i(8000), **lines}
    report = _golden(tmp_path, 2026, values, lines)
    assert "ai.10.d == ai.8.d + ai.9a.d + ai.9b.d" in {c.relation for c in report.relations if c.status == "PASS"}


def test_jp5c_the_recompute_catches_section_a_arrears_that_do_not_compound(tmp_path):
    # A filler that ignored line 14 (last column's underpayment) would put 1,000 on 17(b) of the ratable-withholding
    # year; the printed relation "17.b == max(0, 10.b - 15.b)" still holds on its own numbers, the recompute does not.
    r = underpayment_penalty(required_annual_payment=12000, withholding=8000, year=2025)
    lines = form2210_lines(r)
    assert [lines[f"17.{c}"] for c in "abcd"] == [1000, 2000, 3000, 3000]
    pack = _pack(2025)
    wrong = {**lines, "14.b": 0, "15.b": 2000, "17.b": 1000}
    out = tmp_path / "wrong.pdf"
    fill_form(pack, {"name": "Demo Filer", "identifying_number": "123-45-6789", **_part_i(12000), "6": 8000,
                     "7": 8000, **wrong}, _cached_blank(pack), out)
    report = verify_form(pack, out, independent=lines)
    assert not report.ok
    assert {"14.b", "15.b", "17.b"} <= {c.line for c in report.recompute if c.status == "FAIL"}


def test_jp5c_the_packs_bind_the_tables_and_leave_the_shaded_cells_unmapped():
    old, new = ({f.line: f.field for f in _pack(y).fields} for y in (2025, 2026))
    assert (len(old), len(new)) == (167, 171)
    for shaded in ("12.a", "13.a", "14.a", "16.a", "16.d", "18.d", "ai.22.a", "ai.25.a", "ai.2.a", "ai.20.d"):
        assert shaded not in old and shaded not in new
    # The draft: 9 becomes 9a, a new 9b, and every Schedule AI widget below moves +4.
    assert old["ai.9.a"] == "Page3[0].Part1Table[0].Line9[0].f3_33[0]"
    assert new["ai.9a.a"] == "Page3[0].Part1Table[0].Line9a[0].f3_33[0]"
    assert new["ai.9b.d"] == "Page3[0].Part1Table[0].Line9b[0].f3_40[0]"
    assert (old["ai.36.d"], new["ai.36.d"]) == ("Page3[0].PartIITable[0].Line36[0].f3_144[0]",
                                               "Page3[0].PartIITable[0].Line36[0].f3_148[0]")
    assert _pack(2026).source_status == "draft" and _pack(2026).draft_created == "4/16/26"
    assert _pack(2025).cross_form == _pack(2026).cross_form == ["1 == f1040nr.22"]
