"""Phase J JR4a — the 2025 Form 5329 pack, verified by recomputing from JR3c's rules.

A hypothetical filer, age 45, with three facts: a $10,000 code-1 early distribution from a 401(k), a Roth IRA excess
contribution withdrawn before the due date with $300 of earnings (Form 1099-R box 7 "J8"), and a $1,000 traditional
IRA excess carried from 2024. The Line 15 / Line 23 instructions put the corrective earnings on line 1 AND line 2 with
exception 21: "include the earnings as an early distribution on line 1 of Form 5329 ... Report this amount on line 2
and enter exception number 21." Demo figures only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.estimate import IncomeSnapshot, RetirementDistribution, estimate_refund, form5329_lines
from taxfill_core.fetch import _cache_path, compute_sha256, default_cache_dir
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.schemas.profile import Profile
from taxfill_core.verify import verify_form

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "formpacks/federal/2025/f5329/pack.yaml"

EARLY = RetirementDistribution(gross=10_000, taxable_amount=10_000, codes="1", label="Demo 401(k) Plan")
CORRECTIVE = RetirementDistribution(gross=7_300, taxable_amount=300, codes="J8", label="Demo Roth IRA")


def _snapshot(**extra) -> IncomeSnapshot:
    return IncomeSnapshot(wages=60_000, retirement_distributions=[EARLY, CORRECTIVE], traditional_ira_excess=1_000,
                          traditional_ira_dec31_value=20_000, **extra)


def _cached_blank(pack) -> Path:
    path = _cache_path(default_cache_dir(), pack.source_url)
    if not path.is_file() or compute_sha256(path) != pack.pdf_sha256:
        pytest.skip(f"the Form 5329 blank is not cached — warm it with fetch_blank({pack.source_url})")
    return path


def test_jr4a_form5329_lines_recompute_from_the_jr3c_rules():
    lines = form5329_lines(_snapshot(), 2025)
    # Part I: the J8 earnings ride on line 1 and come off on line 2 (exception 21); only the code-1 $10,000 is taxed.
    assert {k: lines[k] for k in ("1", "2", "3", "4")} == {"1": 10_300, "2": 300, "3": 10_000, "4": 1_000}
    # Part III: 6% of the smaller of line 16 or the December 31 value.
    assert (lines["16"], lines["17"]) == (1_000, 60)
    assert "24" not in lines and "25" not in lines          # no Roth excess: Part IV stays blank
    # The same rules the estimator priced: its two slots are the form's tax lines.
    est = estimate_refund(Profile(), 2025, _snapshot())
    slots = {c.slot: c.amount for c in est.composition}
    assert slots["early_distribution_additional_tax"] == lines["4"]
    assert slots["ira_excess_contribution_excise"] == lines["17"]


def test_jr4a_the_helper_follows_the_simple_rate_the_exception_amount_and_the_cap():
    simple = form5329_lines(IncomeSnapshot(retirement_distributions=[RetirementDistribution(
        gross=4_000, taxable_amount=4_000, codes="S", ira_sep_simple=True)]), 2025)
    assert (simple["3"], simple["4"]) == (4_000, 1_000)     # the line-4 Caution: 25%, not 10% — why 4 has no relation
    excepted = form5329_lines(IncomeSnapshot(retirement_distributions=[RetirementDistribution(
        gross=12_000, taxable_amount=12_000, codes="1", early_exception_amount=5_000)]), 2025)
    assert {k: excepted[k] for k in ("1", "2", "3", "4")} == {"1": 12_000, "2": 5_000, "3": 7_000, "4": 700}
    capped = form5329_lines(IncomeSnapshot(roth_ira_excess=7_000, roth_ira_dec31_value=5_000), 2025)
    assert capped == {"24": 7_000, "25": 300}
    assert form5329_lines(IncomeSnapshot(retirement_distributions=[RetirementDistribution(
        gross=12_000, taxable_amount=12_000, codes="7")]), 2025) == {}



def test_jr4a_the_helper_keys_bare_designators_on_a_draft_year():
    # form_line() renders a draft year's line as "4 (2026 DRAFT form — re-verify at final)" for text; the keys of a
    # verify independent map must be the bare designators the pack keys.
    lines = form5329_lines(IncomeSnapshot(retirement_distributions=[EARLY], roth_ira_excess=1_000), 2026)
    assert set(lines) == {"1", "2", "3", "4", "24", "25"}

def test_jr4a_golden_round_trip_with_the_exception_21_entry(tmp_path):
    pack = load_pack(PACK)
    lines = form5329_lines(_snapshot(), 2025)
    values: dict[str, object] = {
        "name": "Demo Filer", "identifying_number": "123-45-6789", "2.exception_number": "21",
        # Part III as the face asks: line 9 from the 2024 Form 5329 line 16, nothing absorbed on 10-12.
        "9": 1_000, "14": 1_000, **lines,
    }
    out = tmp_path / "f5329.pdf"
    result = fill_form(pack, values, _cached_blank(pack), out)
    field_of = {f.line: f"{pack.acroform_root}.{f.field}" for f in pack.fields}
    assert {field_of[k] for k in ("2.exception_number", "1", "2", "3", "4", "9", "14", "16", "17")} <= set(result.written)
    report = verify_form(pack, out, expected=values, independent=lines)
    fails = [c.detail for section in (report.assertions, report.relations, report.recompute, report.clipping,
                                      report.checkboxes) for c in section if c.status == "FAIL"]
    assert report.ok, fails
    assert {c.line for c in report.recompute if c.status == "PASS"} == set(lines)
    # The printed "Subtract line 2 from line 1" and Part III's arithmetic hold on disk.
    passed = {c.relation for c in report.relations if c.status == "PASS"}
    assert {"3 == 1 - 2", "14 == max(0, 9 - 13)", "16 == 14 + 15"} <= passed


def test_jr4a_the_recompute_catches_a_line_4_that_ignores_the_exception(tmp_path):
    # A filler that taxed the corrective earnings (10% of line 1) puts $1,030 on line 4 — the relations cannot see it
    # (line 4 carries no relation), the JR3c recompute does.
    pack = load_pack(PACK)
    lines = form5329_lines(_snapshot(), 2025)
    wrong = {"name": "Demo Filer", "identifying_number": "123-45-6789", "2.exception_number": "21", **lines,
             "9": 1_000, "14": 1_000, "4": 1_030}
    out = tmp_path / "f5329_wrong.pdf"
    fill_form(pack, wrong, _cached_blank(pack), out)
    report = verify_form(pack, out, independent=lines)
    assert not report.ok
    assert [c.line for c in report.recompute if c.status == "FAIL"] == ["4"]


def test_jr4a_the_pack_is_per_person_and_signs_only_standalone():
    pack = load_pack(PACK)
    assert pack.identity_per_person == ["identifying_number"]
    assert pack.signature is not None and (pack.signature.page, pack.signature.standalone_only) == (3, True)
    assert pack.cross_form == []                            # Schedule 2 line 8 is the COMBINED tax of both spouses
    assert not [r for r in pack.relations if r.startswith(("4 ", "54a", "54b", "17 ", "25 "))]
    assert "mailing_address.street" not in pack.identity_fields


# ── JR4b: the 2023 / 2024 ports and the 2026 draft ──────────────────────────


def _pack(year: int):
    return load_pack(REPO_ROOT / f"formpacks/federal/{year}/f5329/pack.yaml")


def test_jr4b_the_2024_port_swaps_the_preparer_address_and_ein():
    old, new = ({f.line: f.field for f in _pack(y).fields} for y in (2025, 2024))
    # TRAP: the same widget names, but 2024's f3_11 is the firm ADDRESS row and f3_12 the EIN — 2025 the reverse.
    assert (new["preparer.firm_address"], new["preparer.firm_ein"]) == ("Page3[0].f3_11[0]", "Page3[0].f3_12[0]")
    assert (old["preparer.firm_address"], old["preparer.firm_ein"]) == ("Page3[0].f3_12[0]", "Page3[0].f3_11[0]")
    assert {k: v for k, v in new.items() if not k.startswith("preparer.firm_")} == {
        k: v for k, v in old.items() if not k.startswith("preparer.firm_")}
    assert _pack(2024).relations == _pack(2025).relations


def test_jr4b_the_2023_part_ix_is_the_pre_2024_layout():
    pack = _pack(2023)
    lines = {f.line: f.field for f in pack.fields}
    assert len(pack.fields) == 73 and pack.signature.page == 2
    # 52 / 53 / 54 / 55 with the 10%-rate box — no 52a-54b split, so no "55 == 54a + 54b" and no line-54 relation
    # (the 2023 RC waiver enters the reduced shortfall on line 54).
    assert [lines[k] for k in ("52", "53", "54", "55.reduced_rate", "55")] == [
        "Page2[0].f2_27[0]", "Page2[0].f2_28[0]", "Page2[0].f2_29[0]", "Page2[0].c2_1[0]", "Page2[0].f2_30[0]"]
    assert "52a" not in lines and not [r for r in pack.relations if r.startswith(("54", "55"))]
    assert (lines["preparer.firm_address"], lines["preparer.firm_ein"]) == ("Page2[0].f2_34[0]", "Page2[0].f2_35[0]")


def test_jr4b_the_2026_draft_moves_page_1_by_two_and_adds_the_trump_account_parts():
    pack = _pack(2026)
    lines = {f.line: f.field for f in pack.fields}
    assert (pack.source_status, pack.draft_created, pack.signature.page) == ("draft", "7/31/26", 4)
    assert [lines[k] for k in ("mailing_address.city", "mailing_address.state", "mailing_address.zip")] == [
        "Page1[0].f1_5[0]", "Page1[0].f1_6[0]", "Page1[0].f1_7[0]"]
    assert (lines["1"], lines["2.exception_number"], lines["25"]) == (
        "Page1[0].f1_11[0]", "Page1[0].f1_12[0]", "Page1[0].f1_36[0]")
    assert [lines[str(n)] for n in range(56, 64)] == [f"Page3[0].f3_{n}[0]" for n in range(8, 16)]
    # Part X's 6% has no "smaller of ... or the value" clause, and Part XI is 100%: both declared.
    assert {"58 == 56 + 57", "60 == max(0, 58 - 59)", "61 == 60 * 0.06", "63 == 62"} <= set(pack.relations)
    assert lines["preparer.firm_ein"] == "Page3[0].f3_19[0]" and lines["preparer.firm_address"] == "Page3[0].f3_20[0]"


@pytest.mark.parametrize("year", [2023, 2024, 2026])
def test_jr4b_per_pack_golden_with_the_exception_21_entry(year, tmp_path):
    from taxfill_core.filler import rehearsal_only  # noqa: PLC0415

    pack = _pack(year)
    rehearsal = rehearsal_only(pack)
    assert rehearsal == (year == 2026)                     # the draft fills only in rehearsal mode
    lines = form5329_lines(_snapshot(), year)
    values = {"name": "Demo Filer", "identifying_number": "123-45-6789", "2.exception_number": "21",
              "9": 1_000, "14": 1_000, **lines}
    out = tmp_path / f"f5329_{year}.pdf"
    fill_form(pack, values, _cached_blank(pack), out, rehearsal=rehearsal)
    report = verify_form(pack, out, expected=values, independent=lines, rehearsal=rehearsal)
    fails = [c.detail for section in (report.assertions, report.relations, report.recompute, report.clipping,
                                      report.checkboxes) for c in section if c.status == "FAIL"]
    assert report.ok, fails
    assert {c.line for c in report.recompute if c.status == "PASS"} == set(lines)
