"""calc.state_tax returns a state's per-person exemption CREDITS as structured fields (Phase K JK28, 2026-10-16).

Before JK28 the op stopped at the rate-schedule tax (CA Form 540 line 31). California's exemption credits — lines
7-10 "Multiply the number you enter in the box by the pre-printed dollar amount for that line", line 11 "Exemption
amount: Add line 7 through line 10", line 32 "Exemption credits. Enter the amount from line 11. If your federal AGI is
more than [the threshold], see instructions" and line 33 "Subtract line 32 from line 31. If less than zero, enter
-0-" — lived only in the work text, so an agent completing the return did that subtraction itself. The pack now
carries them as data (``tax.exemption_credits``) and the op applies them when the caller passes
``exemption_credit_counts`` (and ``federal_agi`` for the line 32 AGI limitation).

Every figure below is read off the fetched FTB documents: the Form 540 face and booklet for 2023, 2024 and 2025
(https://www.ftb.ca.gov/forms/<year>/<year>-540-booklet.pdf — p. 12 lines 6-11, p. 14 line 32 and the AGI Limitation
Worksheet, the rate schedules on p. 75), each worked by hand in the test's comment.

Phase K JK28 (2026-10-23): the other TY2025 states whose per-person exemptions are credits ship the block too, each
read off its own 2025 face and instructions (fetched twice, identical sha256, prefixes in each pack's comment):
AR1000F lines 7A-7C ($29 a box, $29 a dependent; no AGI rule), DE PIT-RES lines 27a-27b ($110 an exemption, $110
per 60-or-over box; no AGI rule), IA 1040 Step 3 ($40 personal, 2 for statuses 2 and 4; $20 per 65+/blind; $40 a
dependent; no AGI rule), NE 1040N line 18 ($171 x line 4; residents; no AGI rule) and OR-40 line 25 ($256 x line
6e, with the instructions' worksheet CEILINGS: Regular boxes and dependents denied above $100,000 federal AGI for
single/MFS and $200,000 for all others, Severe-disability and disabled-child exemptions above $100,000 for every
status — modeled as ``agi_ceiling``, a cliff per kind, never a silent full credit).

Closed, with the reason each is NOT a per-person exemption credit (the 2026-10-16 survey of the 2025 faces):

* OH — a BASE exemption (IT 1040 line 4 "Exemption amount" reduces income) plus a separate $20-per-exemption
  "Exemption credit" (Schedule of Credits line 9) that is income-gated: "To qualify, your modified adjusted gross
  income (MAGI) less exemptions must be less than $30,000" (2025 IT 1040 booklet). A MAGI-gated credit on a
  schedule beside a base exemption, not the exemption itself.
* KY — no general per-person credit: Schedule ITC Section B "PERSONAL TAX CREDITS" gives only conditional amounts
  (65 or over $40, legally blind $40, Kentucky National Guard $20) flowing to Form 740.
* AZ — base exemptions (age 65+, blind, other, qualifying parent) reduce income on Form 140; dependents get the
  line 49 "Dependent Tax Credit", a dependent credit with its own rules, not a per-person exemption credit.
* ME — a base exemption (Form 1040ME line 18 "EXEMPTION. (Multiply line 13 x $5,150.)" with "CAUTION - your
  exemption amount may be limited."); dependents go through a Maine Schedule A credit, not a per-person credit.
* UT — the exemptions feed a percentage TAXPAYER tax credit (TC-40 line 16 "Initial credit before phase-out -
  multiply line 15 by 6% (.06)", line 19 "Phase-out amount - multiply line 18 by 1.3% (.013)"), not a fixed
  amount per person.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from taxfill_core.calc import state_tax
from taxfill_core.knowledge import load_state_knowledge

REPO = Path(__file__).resolve().parents[3]
KNOWLEDGE = REPO / "knowledge"


def _ca(base, year: int = 2025, **kw):
    return state_tax("ca", base, year=year, knowledge_dir=KNOWLEDGE, **kw)


# ── the three worked 2025 returns ──────────────────────────────────────────────


def test_ca_2025_single_personal_and_senior():
    # Single, California AGI (line 17) $150,000, federal AGI (line 13) $150,000, 65 or older.
    # Line 19 = 150,000 - 5,706 = 144,294. Schedule X (booklet p. 75): over 72,724 -> $3,201.97 + 9.30% of the amount
    # over 72,724 = 3,201.97 + 0.093 x 71,570 = 3,201.97 + 6,656.01 = 9,857.98 -> line 31 = $9,858.
    # Line 7 = 1 x $153; line 9 = 1 x $153; line 11 = $306. 150,000 is not more than $252,203 -> line 32 = $306.
    # Line 33 = 9,858 - 306 = $9,552.
    from taxfill_core.calc import StateExemptionCreditsResult

    r = _ca(150_000, exemption_credit_counts={"personal": 1, "senior": 1}, federal_agi=150_000)
    assert r.tax == 9_858
    ec = r.exemption_credits
    assert isinstance(ec, StateExemptionCreditsResult) and ec.applied
    assert {k: (v.line, v.count, v.amount_each, v.credit) for k, v in ec.credits.items()} == {
        "personal": ("7", 1, 153, 153),
        "blind": ("8", 0, 153, 0),
        "senior": ("9", 1, 153, 153),
        "dependent": ("10", 0, 475, 0),
    }
    assert (ec.exemption_amount, ec.limitation_reduction, ec.total, ec.tax_after_credits) == (306, 0, 306, 9_552)
    assert (ec.federal_agi, ec.agi_threshold) == (150_000, 252_203)
    assert ec.lines == {"exemption_amount": "11", "total": "32", "tax_after_credits": "33"}
    assert ec.citation.url == "https://www.ftb.ca.gov/forms/2025/2025-540-booklet.pdf"
    assert "line 11 (exemption amount) = $306" in r.work
    assert "is not more than the $252,203 [single] threshold, so line 32 = line 11 = $306" in r.work
    assert "line 33 = max(0, $9,858 - $306) = $9,552" in r.work


def test_ca_2025_married_filing_jointly_with_two_dependents():
    # MFJ, California AGI $200,000, federal AGI $200,000, two dependents. Line 19 = 200,000 - 11,412 = 188,588.
    # Schedule Y (p. 75): over 145,448 -> $6,403.94 + 9.30% of the amount over 145,448 = 6,403.94 + 0.093 x 43,140
    # = 6,403.94 + 4,012.02 = 10,415.96 -> line 31 = $10,416.
    # Line 7 = 2 x $153 = $306 (box 2 -> "enter 2"); line 10 = 2 x $475 = $950; line 11 = $1,256.
    # 200,000 is not more than $504,411 -> line 32 = $1,256; line 33 = 10,416 - 1,256 = $9,160.
    r = _ca(
        200_000, filing_status="married_filing_jointly",
        exemption_credit_counts={"personal": 2, "dependent": 2}, federal_agi=200_000,
    )
    assert r.tax == 10_416
    ec = r.exemption_credits
    assert (ec.credits["personal"].credit, ec.credits["dependent"].credit) == (306, 950)
    assert (ec.exemption_amount, ec.total, ec.tax_after_credits, ec.limitation_reduction) == (1_256, 1_256, 9_160, 0)
    assert ec.agi_threshold == 504_411


def test_ca_2025_agi_over_the_threshold_runs_the_worksheet():
    # MFJ, federal AGI $560,000 (California AGI the same), two dependents. Line 19 = 560,000 - 11,412 = 548,588;
    # Schedule Y: 6,403.94 + 0.093 x (548,588 - 145,448 = 403,140) = 6,403.94 + 37,492.02 = 43,895.96 -> $43,896.
    # AGI Limitation Worksheet (booklet p. 14):
    #   a 560,000; b 504,411 (MFJ); c = 55,589; d = 55,589 / 2,500 = 22.2356 -> "round it to the next higher whole
    #   number" = 23; e = 23 x $6 = $138; f = 2 (line 7's box); g = 138 x 2 = 276; h = $306; i = 306 - 276 = $30;
    #   j = 2 (line 10's box); k = 138 x 2 = 276; l = $950; m = 950 - 276 = $674; n = 30 + 674 = $704 -> line 32.
    # Line 33 = 43,896 - 704 = $43,192. The limitation took 1,256 - 704 = $552.
    r = _ca(
        560_000, filing_status="married_filing_jointly",
        exemption_credit_counts={"personal": 2, "dependent": 2}, federal_agi=560_000,
    )
    assert r.tax == 43_896
    ec = r.exemption_credits
    assert ec.exemption_amount == 1_256  # lines 7-10 keep the unreduced amounts; only line 32 is limited
    assert (ec.total, ec.limitation_reduction, ec.tax_after_credits) == (704, 552, 43_192)
    assert "$55,589 / $2,500 = 22.2356, rounded up to 23 step(s) x $6 = $138 off each credit counted" in r.work
    assert "personal + blind + senior: $306 - 2 x $138 = $30" in r.work
    assert "dependent: $950 - 2 x $138 = $674" in r.work
    assert "line 32 = $704 ($552 less than line 11)" in r.work


# ── the worksheet's edges ──────────────────────────────────────────────────────


def test_a_group_floors_at_zero_on_its_own():
    # HOH, federal AGI $450,000, one dependent. c = 450,000 - 378,310 = 71,690; d = 28.676 -> 29; e = 29 x 6 = $174.
    # i = 153 - 1 x 174 = -21 -> "If zero or less, enter -0-" = $0; m = 475 - 1 x 174 = $301; n = $301.
    r = _ca(
        450_000, filing_status="head_of_household",
        exemption_credit_counts={"personal": 1, "dependent": 1}, federal_agi=450_000,
    )
    ec = r.exemption_credits
    assert (ec.exemption_amount, ec.total, ec.limitation_reduction) == (628, 301, 327)
    assert "personal + blind + senior: $153 - 1 x $174 = -$21 -> $0" in r.work


def test_married_filing_separately_steps_by_1250():
    # MFS, federal AGI $260,000: c = 260,000 - 252,203 = 7,797; d = 7,797 / 1,250 ("$1,250 if married/RDP filing
    # separately") = 6.2376 -> 7; e = $42; line 32 = 153 - 42 = $111. (A $2,500 step would give 4 x 6 = 24 -> $129.)
    r = _ca(
        260_000, filing_status="married_filing_separately",
        exemption_credit_counts={"personal": 1}, federal_agi=260_000,
    )
    assert (r.exemption_credits.total, r.exemption_credits.limitation_reduction) == (111, 42)


@pytest.mark.parametrize(
    "agi,expected_total",
    [
        (252_203, 153),  # equal to the threshold: "more than" is false, no limitation
        (252_204, 147),  # $1 over: 1/2,500 -> rounds up to 1 step -> $6
        (277_203, 93),  # exactly 25,000 over: 10 steps, a whole number, no rounding -> $60
        (277_204, 87),  # 25,001 over: 10.0004 -> 11 steps -> $66
    ],
)
def test_the_step_count_rounds_up_only_a_fraction(agi, expected_total):
    r = _ca(150_000, exemption_credit_counts={"personal": 1}, federal_agi=agi)
    assert r.exemption_credits.total == expected_total
    # Booklet p. 14 "Is Form 540, line 13 more than:" — an AGI equal to the threshold is not limited at all.
    over = agi > 252_203
    assert ("is more than the $252,203 [single] threshold by" in r.work) is over
    assert ("is not more than the $252,203 [single] threshold" in r.work) is not over


def test_line_33_floors_at_zero():
    # Single, California AGI $6,706: line 19 = 1,000; line 31 = 1% x 1,000 = $10; line 32 = $153 -> line 33 = $0.
    r = _ca(6_706, exemption_credit_counts={"personal": 1}, federal_agi=6_706)
    assert r.tax == 10
    assert (r.exemption_credits.total, r.exemption_credits.tax_after_credits) == (153, 0)


def test_qualifying_surviving_spouse_uses_the_joint_column_and_two_personal_credits():
    # Line 7: "If you checked box 2 or 5, enter 2" (box 5 = qualifying surviving spouse/RDP); the worksheet's line b
    # groups "Married/RDP filing jointly or qualifying surviving spouse/RDP $504,411".
    r = _ca(
        150_000, filing_status="qualifying_surviving_spouse",
        exemption_credit_counts={"personal": 2, "dependent": 1}, federal_agi=504_412,
    )
    ec = r.exemption_credits
    assert ec.agi_threshold == 504_411
    assert (ec.exemption_amount, ec.total) == (781, 781 - 3 * 6)  # 1 step x $6 off each of the three credits
    assert "[married_filing_jointly (qualifying surviving spouse uses the married-filing-jointly column)]" in r.work


def test_a_dependent_of_another_enters_zero_and_needs_no_agi():
    # Line 7 with line 6 checked: "Single or married/RDP filing separately, enter -0-." Nothing to limit, so
    # federal_agi is not required.
    r = _ca(20_000, exemption_credit_counts={"personal": 0})
    ec = r.exemption_credits
    assert ec.applied and (ec.exemption_amount, ec.total, ec.tax_after_credits) == (0, 0, r.tax)
    assert ec.federal_agi is None


# ── 2023 and 2024 ──────────────────────────────────────────────────────────────


def test_ca_2023_amounts():
    # HOH, California AGI $60,000: line 19 = 60,000 - 10,726 = 49,274; Schedule Z 2023: over 20,839 -> $208.39 +
    # 2.00% x 28,435 = 777.09 -> $777. Lines 7 and 10 (2023 face "X $144", "X $446"): 144 + 446 = $590 -> line 33 = $187.
    r = _ca(
        60_000, year=2023, filing_status="head_of_household",
        exemption_credit_counts={"personal": 1, "dependent": 1}, federal_agi=60_000,
    )
    assert r.tax == 777
    assert (r.exemption_credits.exemption_amount, r.exemption_credits.tax_after_credits) == (590, 187)
    assert r.exemption_credits.citation.url == "https://www.ftb.ca.gov/forms/2023/2023-540-booklet.pdf"
    # The 2023 head-of-household threshold is $355,558: $1 over -> 1 step -> $6 off each credit (144-6 + 446-6).
    over = _ca(
        60_000, year=2023, filing_status="head_of_household",
        exemption_credit_counts={"personal": 1, "dependent": 1}, federal_agi=355_559,
    )
    assert (over.exemption_credits.agi_threshold, over.exemption_credits.total) == (355_558, 578)


def test_ca_2024_amounts_and_limitation():
    # Single, federal AGI = California AGI = $250,000, 65 or older. Line 19 = 250,000 - 5,540 = 244,460; Schedule X
    # 2024 (p. 75): over 70,606 -> $3,108.72 + 9.30% x 173,854 = 3,108.72 + 16,168.42 = 19,277.14 -> $19,277.
    # Lines 7 and 9 (2024 face "X $149"): $298. Worksheet: c = 250,000 - 244,857 = 5,143; d = 2.0572 -> 3; e = $18;
    # f = 2; g = 36; h = 298; i = $262; m = 0; line 32 = $262; line 33 = 19,277 - 262 = $19,015.
    r = _ca(250_000, year=2024, exemption_credit_counts={"personal": 1, "senior": 1}, federal_agi=250_000)
    assert r.tax == 19_277
    ec = r.exemption_credits
    assert (ec.exemption_amount, ec.agi_threshold, ec.total, ec.tax_after_credits) == (298, 244_857, 262, 19_015)


@pytest.mark.parametrize(
    "year,amount,dependent,thresholds",
    [
        (2023, 144, 446, (237_035, 474_075, 237_035, 355_558)),
        (2024, 149, 461, (244_857, 489_719, 244_857, 367_291)),
        (2025, 153, 475, (252_203, 504_411, 252_203, 378_310)),
    ],
)
def test_each_year_ships_its_own_face_amounts(year, amount, dependent, thresholds):
    # The Form 540 face of each year: lines 7-9 "X $144" / "X $149" / "X $153", line 10 "X $446" / "X $461" /
    # "X $475"; booklet p. 14 "Is Form 540, line 13 more than:" single or MFS / MFJ or QSS / HOH.
    from taxfill_core.knowledge import StateExemptionCredits

    block = load_state_knowledge("ca", year, base_dir=KNOWLEDGE).tax.exemption_credits
    assert isinstance(block, StateExemptionCredits)
    assert {k: c.amount for k, c in block.credits.items()} == {
        "personal": amount, "blind": amount, "senior": amount, "dependent": dependent,
    }
    assert {k: c.line for k, c in block.credits.items()} == {"personal": "7", "blind": "8", "senior": "9", "dependent": "10"}
    lim = block.agi_limitation
    statuses = ("single", "married_filing_jointly", "married_filing_separately", "head_of_household")
    assert tuple(lim.threshold[s] for s in statuses) == thresholds
    assert tuple(lim.step[s] for s in statuses) == (2_500, 2_500, 1_250, 2_500)
    assert lim.reduction_per_step == 6 and lim.groups == [["personal", "blind", "senior"], ["dependent"]]
    assert block.credits["personal"].max_count == {
        "single": 1, "married_filing_jointly": 2, "married_filing_separately": 1, "head_of_household": 1,
    }
    assert "If you checked box 2 or 5, enter 2 in the box." in block.credits["personal"].note
    for kind in ("blind", "senior"):  # "if both are ..., enter 2": the second count is the spouse/RDP's
        assert block.credits[kind].max_count == block.credits["personal"].max_count, (year, kind)
        assert "You cannot claim a personal exemption credit for your spouse/RDP" in block.credits[kind].note
    assert "if both are visually impaired, enter 2." in block.credits["blind"].note
    assert "if both are 65 or older," in block.credits["senior"].note
    assert f"by December 31, {year}*" in block.credits["senior"].note
    assert any("38 CA Exemption Credit Percentage" in n for n in block.notes)  # the 540NR proration warning
    assert f"forms/{year}/{year}-540-booklet.pdf" in block.citation.url


# ── backward compatibility ─────────────────────────────────────────────────────


def test_without_counts_nothing_changes_but_the_result_says_not_applied():
    # The 2023 CA golden rows (test_tax_calc.GRADUATED_GOLDENS) still hold, field for field.
    for base, status, base_after, tax in (
        (150_000, "single", 144_637, 10_104),
        (800_000, "married_filing_jointly", 789_274, 67_618),
        (60_000, "head_of_household", 49_274, 777),
        (1_000_000, "married_filing_separately", 994_637, 104_330),
    ):
        r = _ca(base, year=2023, filing_status=status)
        assert (r.base_after_exemptions, r.tax) == (base_after, tax)
        ec = r.exemption_credits
        assert ec.applied is False and ec.credits == {}
        assert (ec.exemption_amount, ec.total, ec.tax_after_credits, ec.limitation_reduction) == (None,) * 4
        assert "Exemption credits NOT applied" in ec.note and "Exemption credits NOT applied" in r.work
        assert set(r.inputs) == {"state", "taxable_base", "year", "exemptions_count", "dependents_count", "filing_status"}


def test_line_33_is_counted_from_the_schedule_and_the_result_says_so():
    # Booklet p. 13 (2023-2025), "Line 31 – Tax": "Tax Table – If your taxable income on line 19 is $100,000 or less,
    # use the tax table beginning on page 69." tax_after_credits starts from tax, the rate-schedule amount, so below
    # $100,000 the filed line 33 is the Tax Table's line 31 minus line 32: the note, the field and the data say so.
    from taxfill_core.calc import StateExemptionCreditsResult

    r = _ca(80_000, exemption_credit_counts={"personal": 1}, federal_agi=80_000)
    assert ("Line 33 here is counted from the rate-schedule tax: when the filed tax line comes from the state's tax "
            "table instead (the notes say when), line 33 = max(0, that table amount - $153).") in r.exemption_credits.note
    description = StateExemptionCreditsResult.model_fields["tax_after_credits"].description
    assert "(CA: line 19 of $100,000 or less takes line 31 from the Tax Table)" in description
    for year in (2023, 2024, 2025):
        notes = load_state_knowledge("ca", year, base_dir=KNOWLEDGE).tax.exemption_credits.notes
        assert any("\"Tax Table – If your taxable income on line 19 is $100,000 or less, use the tax table beginning "
                   "on page 69.\"" in note and "the filed line 33 is max(0, the Tax Table's line 31 - line 32)" in note
                   for note in notes), year
    assert "Line 33 starts from the filed line 31." in r.work


def test_federal_agi_without_counts_is_named_not_dropped_silently():
    ca = _ca(80_000, federal_agi=80_000)
    assert ca.exemption_credits.applied is False
    assert ("federal_agi was passed but no exemption_credit_counts, so nothing was applied and the AGI was not "
            "read.") in ca.exemption_credits.note
    assert "federal_agi was passed" not in _ca(80_000).exemption_credits.note
    il = state_tax("il", 50_000, exemptions_count=1, federal_agi=60_000, knowledge_dir=KNOWLEDGE)
    assert ("federal_agi ($60,000.00) was passed, but IL's pack ships no exemption credits for it to limit, so it was "
            "not used.") in il.work
    assert il.exemption_credits is None and il.inputs["federal_agi"] == "60000"


def test_the_credits_never_move_the_tax_line():
    plain = _ca(560_000, filing_status="married_filing_jointly")
    credited = _ca(
        560_000, filing_status="married_filing_jointly",
        exemption_credit_counts={"personal": 2, "dependent": 2}, federal_agi=560_000,
    )
    for field in ("tax", "rate", "rate_structure", "marginal_rate", "base_after_exemptions", "state", "base_kind"):
        assert getattr(plain, field) == getattr(credited, field), field
    assert credited.inputs["exemption_credit_counts"] == {"personal": 2, "dependent": 2}
    assert credited.inputs["federal_agi"] == "560000"


def test_a_state_without_the_block_keeps_its_old_output_shape():
    r = state_tax("il", 50_000, exemptions_count=1, knowledge_dir=KNOWLEDGE)
    assert r.exemption_credits is None
    dumped = r.model_dump(mode="json")
    assert "exemption_credits" not in dumped
    assert sorted(dumped) == [
        "base_after_exemptions", "base_kind", "citation", "inputs", "marginal_rate", "rate", "rate_structure",
        "state", "tax", "work",
    ]
    assert "xemption credit" not in r.work
    # Zero counts are harmless anywhere (like exemptions_count=0); they are echoed and change nothing.
    zero = state_tax("il", 50_000, exemptions_count=1, exemption_credit_counts={"personal": 0}, knowledge_dir=KNOWLEDGE)
    assert zero.tax == r.tax and zero.exemption_credits is None
    assert zero.inputs["exemption_credit_counts"] == {"personal": 0}


def test_the_serialization_schema_keeps_the_typed_fields():
    # The wrap serializer that drops an absent exemption_credits key must not cost StateTaxResult its JSON schema: a
    # "-> dict[str, Any]" annotation on it collapsed the serialization schema to a bare object with no fields.
    from taxfill_core.calc import StateTaxResult

    schema = StateTaxResult.model_json_schema(mode="serialization")
    assert {"tax", "rate", "work", "citation", "exemption_credits"} <= set(schema.get("properties", {})), schema
    assert "tax" in schema["required"] and "exemption_credits" not in schema["required"]


# ── refusals ───────────────────────────────────────────────────────────────────


def test_a_state_without_the_block_refuses_nonzero_credit_counts():
    with pytest.raises(ValueError) as err:
        state_tax("il", 50_000, year=2025, exemption_credit_counts={"personal": 1}, knowledge_dir=KNOWLEDGE)
    msg = str(err.value)
    assert msg.startswith("IL 2025: exemption_credit_counts was supplied ({'personal': 1}) but the pack ships no "
                          "exemption_credits block")
    assert "(packs that ship them for 2025: ar, ca, de, ia, ne, or)" in msg
    assert "never a guessed amount" in msg


def test_ca_refuses_what_its_form_does_not_print():
    with pytest.raises(ValueError, match=r"unknown credit kind\(s\) \['elderly'\]"):
        _ca(50_000, exemption_credit_counts={"elderly": 1}, federal_agi=50_000)
    with pytest.raises(ValueError, match=r"exemption_credit_counts\['personal'\] = 2 is more than the 1 that Form 540 "
                                         r"line 7 allows for single"):
        _ca(50_000, exemption_credit_counts={"personal": 2}, federal_agi=50_000)
    with pytest.raises(ValueError, match=r"is more than the 2 that Form 540 line 8"):
        _ca(50_000, filing_status="married_filing_jointly", exemption_credit_counts={"blind": 3}, federal_agi=50_000)


@pytest.mark.parametrize("year", (2023, 2024, 2025))
@pytest.mark.parametrize("status", ("single", "head_of_household", "married_filing_separately"))
@pytest.mark.parametrize(("kind", "line"), (("blind", "8"), ("senior", "9")))
def test_only_a_joint_return_counts_two_blind_or_senior_credits(year, status, kind, line):
    # Form 540 line 8 "Blind: If you (or your spouse/RDP) are visually impaired, enter 1; if both are visually impaired,
    # enter 2." and line 9 "Senior: If you (or your spouse/RDP) are 65 or older, enter 1; if both are 65 or older,
    # enter 2." The second count is the spouse/RDP's: a single or head-of-household return has none, and on a separate
    # return "You cannot claim a personal exemption credit for your spouse/RDP even if your spouse/RDP had no income,
    # is not filing a tax return, and is not claimed as a dependent on another person's tax return." (the booklet's
    # "Married/RDP Filing Separately", 2023 p. 4, 2024 and 2025 p. 5).
    with pytest.raises(ValueError, match=rf"exemption_credit_counts\['{kind}'\] = 2 is more than the 1 that Form 540 "
                                         rf"line {line} allows for {status}: "):
        _ca(50_000, year=year, filing_status=status, exemption_credit_counts={kind: 2}, federal_agi=50_000)
    one = _ca(50_000, year=year, filing_status=status, exemption_credit_counts={kind: 1}, federal_agi=50_000)
    assert one.exemption_credits.credits[kind].count == 1
    joint = _ca(50_000, year=year, filing_status="married_filing_jointly", exemption_credit_counts={kind: 2},
                federal_agi=50_000)
    assert joint.exemption_credits.credits[kind].credit == 2 * joint.exemption_credits.credits[kind].amount_each


def test_ca_refuses_credits_without_the_agi_the_limitation_reads():
    with pytest.raises(ValueError) as err:
        _ca(50_000, exemption_credit_counts={"personal": 1})
    msg = str(err.value)
    assert "exemption_credit_counts needs federal_agi" in msg
    assert "$252,203 single, $504,411 married_filing_jointly, $252,203 married_filing_separately, $378,310 " \
           "head_of_household" in msg


def test_ca_base_exemption_counts_point_at_the_credit_input():
    with pytest.raises(ValueError) as err:
        _ca(50_000, exemptions_count=1)
    assert str(err.value).endswith(
        "CA's per-person exemptions are CREDITS against tax (Form 540 lines 7, 8, 9, 10): pass their counts as "
        "exemption_credit_counts (kinds: personal, blind, senior, dependent) with federal_agi, and read the result's "
        "exemption_credits."
    )
    with pytest.raises(ValueError, match="dependents_count was supplied") as err:
        _ca(50_000, dependents_count=1)
    assert "pass their counts as exemption_credit_counts" in str(err.value)


def test_input_validation():
    with pytest.raises(TypeError, match="exemption_credit_counts must be a mapping"):
        _ca(50_000, exemption_credit_counts=[1])
    with pytest.raises(TypeError, match=r"exemption_credit_counts\['personal'\] must be an int"):
        _ca(50_000, exemption_credit_counts={"personal": "1"}, federal_agi=50_000)
    with pytest.raises(TypeError, match=r"exemption_credit_counts\['personal'\] must be an int"):
        _ca(50_000, exemption_credit_counts={"personal": True}, federal_agi=50_000)
    with pytest.raises(ValueError, match=r"exemption_credit_counts\['senior'\] must be >= 0"):
        _ca(50_000, exemption_credit_counts={"senior": -1}, federal_agi=50_000)
    with pytest.raises(ValueError, match="federal_agi string 'lots' is not a number"):
        _ca(50_000, exemption_credit_counts={"personal": 1}, federal_agi="lots")


# ── the schema ─────────────────────────────────────────────────────────────────


def _ca_block_raw() -> dict:
    import yaml

    raw = yaml.safe_load((KNOWLEDGE / "states" / "ca" / "2025.yaml").read_text(encoding="utf-8"))
    return copy.deepcopy(raw["tax"]["exemption_credits"])


def test_the_schema_rejects_a_malformed_block():
    from taxfill_core.knowledge import StateExemptionCredits

    StateExemptionCredits.model_validate(_ca_block_raw())  # the shipped block is valid
    cases = {
        "groups miss a kind": lambda b: b["agi_limitation"].__setitem__("groups", [["personal", "blind"], ["dependent"]]),
        "a kind twice": lambda b: b["agi_limitation"].__setitem__(
            "groups", [["personal", "blind", "senior"], ["dependent", "senior"]]),
        "a status missing": lambda b: b["agi_limitation"]["threshold"].pop("head_of_household"),
        "a zero step": lambda b: b["agi_limitation"]["step"].__setitem__("single", 0),
        "a zero amount": lambda b: b["credits"]["blind"].__setitem__("amount", 0),
        "a negative max_count": lambda b: b["credits"]["personal"]["max_count"].__setitem__("single", -1),
        "an empty note": lambda b: b["credits"]["senior"].__setitem__("note", "  "),
        "a bad kind key": lambda b: b["credits"].__setitem__("Blind-2", b["credits"].pop("blind")),
        "an unknown field": lambda b: b.__setitem__("phaseout", 1),
        "no credits": lambda b: (b.__setitem__("credits", {}), b.__setitem__("agi_limitation", None)),
    }
    for name, mutate in cases.items():
        block = _ca_block_raw()
        mutate(block)
        with pytest.raises(ValidationError):
            StateExemptionCredits.model_validate(block)
            pytest.fail(name)


# ── the MCP-facing surfaces ────────────────────────────────────────────────────


def test_the_jk21_goldens_hold_the_credit_calls():
    # scripts/golden_snapshots.py snapshots the credit calls for every pack that ships the block (CA), so a later
    # restructure of the state knowledge layer cannot drop the block silently.
    spec = importlib.util.spec_from_file_location("golden_snapshots", REPO / "scripts" / "golden_snapshots.py")
    harness = sys.modules.get(spec.name)
    if harness is None:
        harness = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = harness
        spec.loader.exec_module(harness)
    for year in (2023, 2024, 2025):
        stored = json.loads((REPO / "packages/core/tests/goldens/state_knowledge" / f"ca_{year}.json").read_text())
        calls = harness.expand(stored)["state_tax"]
        applied = [c for c in calls if (c.get("exemption_credits") or {}).get("applied")]
        assert len(applied) == 9, year  # 4 statuses x (under, over the threshold) + the single floor call
        assert any(c["exemption_credits"]["limitation_reduction"] > 0 for c in applied)
        assert any("needs federal_agi" in c.get("error", "") for c in calls), year
    il = harness.state_tax_grid(load_state_knowledge("il", 2025, base_dir=KNOWLEDGE).tax)
    assert not any("exemption_credit_counts" in args for args in il)


# ── Phase K JK28 (2026-10-23): AR, DE, IA, NE and OR (2025) ───────────────────────


def _st(state, base, **kw):
    return state_tax(state, base, year=2025, knowledge_dir=KNOWLEDGE, **kw)


def _lines(ec):
    return {k: (v.line, v.count, v.amount_each, v.credit) for k, v in ec.credits.items()}


def test_ar_2025_personal_tax_credits():
    # AR1000F, MFJ, line 25 AGI $60,000: line 27 standard deduction $4,940 -> line 28 = $55,060. 2025 Indexed Tax
    # Brackets, 3.9% band: 55,060 x .039 = 2,147.34 - 419.96 = 1,727.38 -> $1,727 (the op's line 29 / 33).
    # Line 7A: Yourself + Spouse (2) + one "65 or over" + one "65 Special" = 4 boxes x $29 = $116 (instructions p. 12
    # "Multiply the number by $29"); line 7B: 2 dependents x $29 = $58; line 7C = $174 -> line 34.
    # Line 38 = 1,727 - 174 = $1,553 (lines 31-32 and 35-36 zero).
    r = _st("ar", 60_000, filing_status="married_filing_jointly",
            exemption_credit_counts={"personal": 2, "senior": 1, "senior_special": 1, "dependent": 2})
    assert r.tax == 1_727
    ec = r.exemption_credits
    assert ec.applied and ec.form == "AR1000F"
    assert _lines(ec) == {
        "personal": ("7A", 2, 29, 58), "senior": ("7A", 1, 29, 29), "senior_special": ("7A", 1, 29, 29),
        "blind": ("7A", 0, 29, 0), "deaf": ("7A", 0, 29, 0), "head_of_household_or_surviving_spouse": ("7A", 0, 29, 0),
        "dependent": ("7B", 2, 29, 58),
    }
    assert (ec.exemption_amount, ec.limitation_reduction, ec.total, ec.tax_after_credits) == (174, 0, 174, 1_553)
    assert (ec.federal_agi, ec.agi_threshold, ec.agi_ceilings) == (None, None, None)
    assert ec.lines == {"exemption_amount": "7C", "total": "34", "tax_after_credits": "38"}
    assert ec.citation.url.endswith("2025_AR1000F_FullYearResidentIndividualIncomeTaxReturn.pdf")
    assert "line 7C (exemption amount) = $174. no AGI limitation in this pack, so line 34 = $174" in r.work
    assert "line 38 = max(0, $1,727 - $174) = $1,553" in r.work
    assert "agi_ceilings" not in ec.model_dump(mode="json")


def test_ar_2025_box_limits():
    # The head-of-household/surviving-spouse box is printed "(Filing status 3 only)" / "(Filing status 6 only)".
    with pytest.raises(ValueError, match=r"\['head_of_household_or_surviving_spouse'\] = 1 is more than the 0 that "
                                         r"AR1000F line 7A allows for single"):
        _st("ar", 40_000, exemption_credit_counts={"head_of_household_or_surviving_spouse": 1})
    hoh = _st("ar", 40_000, filing_status="head_of_household",
              exemption_credit_counts={"personal": 1, "head_of_household_or_surviving_spouse": 1})
    assert hoh.exemption_credits.total == 58
    qss = _st("ar", 40_000, filing_status="qualifying_surviving_spouse",
              exemption_credit_counts={"personal": 1, "head_of_household_or_surviving_spouse": 1})
    assert qss.exemption_credits.total == 58
    # Yourself + Spouse at most: 3 on a joint return, 2 for a surviving spouse (no spouse on the return), are refused.
    with pytest.raises(ValueError, match=r"\['personal'\] = 3 is more than the 2 that AR1000F line 7A allows for "
                                         r"married_filing_jointly"):
        _st("ar", 40_000, filing_status="married_filing_jointly", exemption_credit_counts={"personal": 3})
    with pytest.raises(ValueError, match=r"\['deaf'\] = 2 is more than the 1 that AR1000F line 7A allows for "
                                         r"qualifying_surviving_spouse"):
        _st("ar", 40_000, filing_status="qualifying_surviving_spouse", exemption_credit_counts={"deaf": 2})


def test_ar_2025_reads_no_agi_and_says_so():
    r = _st("ar", 50_000, exemption_credit_counts={"personal": 1}, federal_agi=50_000)
    assert r.exemption_credits.federal_agi is None and r.exemption_credits.total == 29
    assert "federal_agi $50,000.00 was passed, but AR's exemption credits have no AGI rule, so it was not used" in r.work
    with pytest.raises(ValueError) as err:
        _st("ar", 50_000, exemptions_count=1)
    assert str(err.value).endswith(
        "AR's per-person exemptions are CREDITS against tax (AR1000F lines 7A, 7B): pass their counts as "
        "exemption_credit_counts (kinds: personal, senior, senior_special, blind, deaf, "
        "head_of_household_or_surviving_spouse, dependent), and read the result's exemption_credits."
    )


def test_de_2025_personal_credits():
    # PIT-RES, MFJ, line 12 Delaware AGI $80,000: line 20 standard deduction $6,500 -> line 23 = $73,500 ($60,000 or
    # over: "$2,943.50 plus 6.60% (.066) over, for the portion over $60,000") = 2,943.50 + 891.00 = 3,834.50 -> $3,835.
    # Line 27a: 2 exemptions (taxpayer, spouse) + 1 dependent = 3 x $110 = $330; line 27b: one 60-or-over box x $110.
    # Credits $440; line 33 = 3,835 - 440 = $3,395 (lines 25 and 28-31 zero).
    r = _st("de", 80_000, filing_status="married_filing_jointly",
            exemption_credit_counts={"personal": 2, "dependent": 1, "senior": 1})
    assert r.tax == 3_835
    ec = r.exemption_credits
    assert _lines(ec) == {"personal": ("27a", 2, 110, 220), "senior": ("27b", 1, 110, 110),
                          "dependent": ("27a", 1, 110, 110)}
    assert (ec.exemption_amount, ec.total, ec.tax_after_credits) == (440, 440, 3_395)
    assert ec.lines == {"exemption_amount": "27a + 27b", "total": "32", "tax_after_credits": "33"}
    with pytest.raises(ValueError, match=r"\['senior'\] = 2 is more than the 1 that Form PIT-RES line 27b allows for "
                                         r"single"):
        _st("de", 80_000, exemption_credit_counts={"senior": 2})


def test_de_2025_line_32_is_limited_to_the_tax():
    # Instructions p. 10, Line 32: "The total of all non-refundable credits (Lines 27a through 31) is limited to the
    # amount of your Delaware tax liability on Line 26." Single, line 12 $5,750: line 23 = 5,750 - 3,250 = $2,500 ->
    # 2.2% x (2,500 - 2,000) = $11 (lines 25 and 28-31 zero, so line 26 = $11). Lines 27a + 27b = 3 x $110 = $330,
    # limited to $11 on line 32; line 33 = $0.
    r = _st("de", 5_750, exemption_credit_counts={"personal": 1, "dependent": 1, "senior": 1})
    assert r.tax == 11
    ec = r.exemption_credits
    assert (ec.exemption_amount, ec.limitation_reduction, ec.tax_limit_reduction, ec.total, ec.tax_after_credits) == (
        330, 0, 319, 11, 0)
    assert "Form PIT-RES limits line 32 to the tax on line 26: min($330, $11) = $11 ($319 more than the tax" in r.work
    assert ec.model_dump(mode="json")["tax_limit_reduction"] == 319
    # Under the tax the limit takes nothing, and the field still says so.
    full = _st("de", 80_000, filing_status="married_filing_jointly", exemption_credit_counts={"personal": 2})
    assert (full.exemption_credits.total, full.exemption_credits.tax_limit_reduction) == (220, 0)
    # A pack whose form prints no such limit (CA: line 33 floors at zero) keeps its output without the field.
    ca = _ca(1_000, exemption_credit_counts={"personal": 1}, federal_agi=1_000).exemption_credits
    assert ca.total > 0 and "tax_limit_reduction" not in ca.model_dump(mode="json")


def test_ia_2025_step_3_exemption_credits():
    # IA 1040, head of household (status 4), line 4 Iowa taxable income $50,000: line 5 = 50,000 x 3.8% = $1,900.
    # Step 3 a "Enter 1 (enter 2 if filing status 2 or 4)" -> 2 x $40 = $80; c 1 dependent x $40 = $40; d = $120 ->
    # line 8. Line 12 "Subtract line 11 from line 7. If less than zero, enter zero." = 1,900 - 120 = $1,780.
    r = _st("ia", 50_000, filing_status="head_of_household", exemption_credit_counts={"personal": 2, "dependent": 1})
    assert r.tax == 1_900
    ec = r.exemption_credits
    assert _lines(ec) == {"personal": ("Step 3a", 2, 40, 80), "senior": ("Step 3b", 0, 20, 0),
                          "blind": ("Step 3b", 0, 20, 0), "dependent": ("Step 3c", 1, 40, 40)}
    assert (ec.exemption_amount, ec.total, ec.tax_after_credits) == (120, 120, 1_780)
    assert ec.lines == {"exemption_amount": "Step 3d", "total": "8", "tax_after_credits": "12"}
    # MFJ, both 65 or older, one blind: line b = 3 x $20 = $60; line a = 2 x $40 = $80.
    joint = _st("ia", 50_000, filing_status="married_filing_jointly",
                exemption_credit_counts={"personal": 2, "senior": 2, "blind": 1})
    assert joint.exemption_credits.total == 140
    # Qualifying surviving spouse is status 5: "enter 1", although calc resolves it to the joint column.
    with pytest.raises(ValueError, match=r"\['personal'\] = 2 is more than the 1 that IA 1040 Step 3a allows "
                                         r"for qualifying_surviving_spouse"):
        _st("ia", 50_000, filing_status="qualifying_surviving_spouse", exemption_credit_counts={"personal": 2})
    with pytest.raises(ValueError, match=r"\['personal'\] = 3 is more than the 2 that IA 1040 Step 3a allows "
                                         r"for head_of_household"):
        _st("ia", 50_000, filing_status="head_of_household", exemption_credit_counts={"personal": 3})
    # A line that starts with a word stands alone in messages: "IA 1040 Step 3a", never "line Step 3a".
    with pytest.raises(ValueError) as err:
        _st("ia", 50_000, exemptions_count=1)
    assert "(IA 1040 Step 3a, Step 3b, Step 3c)" in str(err.value) and "line Step" not in str(err.value)
    assert "line Step" not in r.work and "Step 3d (exemption amount) = $120" in r.work
    # Line 12 floors at zero.
    low = _st("ia", 1_000, filing_status="married_filing_jointly", exemption_credit_counts={"personal": 2})
    assert (low.tax, low.exemption_credits.tax_after_credits) == (38, 0)


def test_ne_2025_personal_exemption_credit():
    # Form 1040N, MFJ, line 5 federal AGI $100,000: line 6 standard deduction $17,200 -> line 14 = $82,800. Tax
    # Calculation Schedule, MFJ: "$3,086.10 + 5.20% of the excess over $77,730" = 3,086.10 + 263.64 = 3,349.74 ->
    # $3,350 (line 15 = line 17). Line 4: 4a 1 + 4b 1 + 4c 2 = 4; line 18 "$171 times the number on line 4" = $684.
    # Line 35 = 3,350 - 684 = $2,666 (lines 16 and 19-33 zero).
    r = _st("ne", 100_000, filing_status="married_filing_jointly",
            exemption_credit_counts={"personal": 2, "dependent": 2})
    assert r.tax == 3_350
    ec = r.exemption_credits
    assert _lines(ec) == {"personal": ("4a-4b", 2, 171, 342), "dependent": ("4c", 2, 171, 342)}
    assert (ec.exemption_amount, ec.total, ec.tax_after_credits) == (684, 684, 2_666)
    assert ec.lines == {"exemption_amount": "18", "total": "18", "tax_after_credits": "35"}
    # Line 4b is for a joint return only.
    for status in ("single", "married_filing_separately", "head_of_household", "qualifying_surviving_spouse"):
        with pytest.raises(ValueError, match=r"\['personal'\] = 2 is more than the 1 that Form 1040N line 4a-4b"):
            _st("ne", 100_000, filing_status=status, exemption_credit_counts={"personal": 2})


def test_or_2025_exemption_credit_under_the_ceiling():
    # OR-40, single, line 15 $60,000, federal AGI (line 7) $60,000: Table 5 standard deduction $2,835 -> line 19 =
    # $57,165; Chart S: 4.75% x 4,400 = 209.00 + 6.75% x 6,700 = 452.25 + 8.75% x 46,065 = 4,030.6875 -> 4,691.94 ->
    # $4,692. Worksheet line 1: AGI not more than $100,000 -> 1 "Regular" box; line 5 = 1 x $256 -> line 25.
    # Line 29 = 4,692 - 256 = $4,436 (lines 21-23, 26-27 zero).
    r = _st("or", 60_000, exemption_credit_counts={"regular": 1}, federal_agi=60_000)
    assert r.tax == 4_692
    ec = r.exemption_credits
    assert (ec.exemption_amount, ec.limitation_reduction, ec.total, ec.tax_after_credits) == (256, 0, 256, 4_436)
    assert ec.federal_agi == 60_000 and ec.agi_threshold is None
    assert ec.agi_ceilings == {"regular": 100_000, "dependent": 100_000, "severe_disability": 100_000,
                               "disabled_child": 100_000}
    assert ec.lines == {"exemption_amount": "6e x $256", "total": "25", "tax_after_credits": "29"}
    assert "agi_ceilings" in ec.model_dump(mode="json")


def test_or_2025_the_ceilings_are_cliffs_per_kind():
    # MFJ, federal AGI $150,000, 2 Regular boxes, 1 dependent, 1 Severe disability box. Worksheet: line 1 (AGI not
    # more than $200,000 for "all others") = 2 + 1 = 3; line 2 (more than $100,000 -> "enter 0") = 0; line 5 =
    # 3 x $256 = $768. Line 6e x $256 = 4 x 256 = $1,024; the ceiling took $256.
    # Tax: line 19 = 150,000 - 5,670 = 144,330; Chart J: 418 + 904.50 + 8.75% x 122,130 = 10,686.375 -> 12,008.875
    # -> $12,009; line 29 = 12,009 - 768 = $11,241.
    r = _st("or", 150_000, filing_status="married_filing_jointly",
            exemption_credit_counts={"regular": 2, "dependent": 1, "severe_disability": 1}, federal_agi=150_000)
    ec = r.exemption_credits
    assert r.tax == 12_009
    assert (ec.exemption_amount, ec.limitation_reduction, ec.total, ec.tax_after_credits) == (1_024, 256, 768, 11_241)
    assert ec.agi_ceilings["regular"] == 200_000 and ec.agi_ceilings["severe_disability"] == 100_000
    assert "severe_disability: more than $100,000 -> $256 denied" in r.work
    assert "regular: not more than $200,000 -> allowed" in r.work
    # The single ceiling: $100,000 keeps the credit, $100,001 ("more than $100,000") denies it.
    at = _st("or", 100_000, exemption_credit_counts={"regular": 1}, federal_agi=100_000).exemption_credits
    over = _st("or", 100_000, exemption_credit_counts={"regular": 1}, federal_agi=100_001).exemption_credits
    assert (at.total, over.total, over.limitation_reduction) == (256, 0, 256)
    # MFJ over $200,000: every kind denied, line 25 = $0.
    high = _st("or", 250_000, filing_status="married_filing_jointly",
               exemption_credit_counts={"regular": 2, "dependent": 2}, federal_agi=200_001).exemption_credits
    assert (high.exemption_amount, high.total) == (1_024, 0)
    # A qualifying surviving spouse is one of "all others" ($200,000) but has one Regular box.
    qss = _st("or", 150_000, filing_status="qualifying_surviving_spouse",
              exemption_credit_counts={"regular": 1, "dependent": 1}, federal_agi=150_000).exemption_credits
    assert qss.total == 512
    with pytest.raises(ValueError, match=r"\['regular'\] = 2 is more than the 1 that Form OR-40 line 6a-6b allows "
                                         r"for qualifying_surviving_spouse"):
        _st("or", 150_000, filing_status="qualifying_surviving_spouse",
            exemption_credit_counts={"regular": 2}, federal_agi=150_000)


def test_or_2025_refuses_counts_without_the_agi_the_ceiling_reads():
    with pytest.raises(ValueError) as err:
        _st("or", 60_000, exemption_credit_counts={"regular": 1, "severe_disability": 1})
    msg = str(err.value)
    assert msg.startswith("OR 2025: exemption_credit_counts needs federal_agi — Form OR-40 denies regular, "
                          "severe_disability credits when federal AGI (Form OR-40 line 7) is more than regular: "
                          "$100,000 single, $200,000 married_filing_jointly")
    assert "severe_disability: $100,000 single, $100,000 married_filing_jointly" in msg
    assert msg.endswith("so the ceiling is applied, never skipped.")
    # Zero counts read no AGI.
    zero = _st("or", 60_000, exemption_credit_counts={"regular": 0})
    assert (zero.exemption_credits.total, zero.exemption_credits.federal_agi) == (0, None)
    with pytest.raises(ValueError) as err:
        _st("or", 60_000, dependents_count=1)
    assert "(kinds: regular, severe_disability, dependent, disabled_child) with federal_agi" in str(err.value)


@pytest.mark.parametrize("state", ("oh", "ky", "az", "me", "ut"))
def test_the_closed_states_ship_no_exemption_credit_block(state):
    # Closed by the module docstring's reasons: none of these is a per-person exemption credit.
    assert load_state_knowledge(state, 2025, base_dir=KNOWLEDGE).tax.exemption_credits is None
    with pytest.raises(ValueError, match="ships no exemption_credits block"):
        _st(state, 50_000, exemption_credit_counts={"personal": 1})


def test_the_2025_goldens_hold_the_five_new_blocks():
    spec = importlib.util.spec_from_file_location("golden_snapshots", REPO / "scripts" / "golden_snapshots.py")
    harness = sys.modules.get(spec.name)
    if harness is None:
        harness = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = harness
        spec.loader.exec_module(harness)
    for state in ("ar", "de", "ia", "ne", "or"):
        stored = json.loads((REPO / "packages/core/tests/goldens/state_knowledge" / f"{state}_2025.json").read_text())
        calls = harness.expand(stored)["state_tax"]
        applied = [c for c in calls if (c.get("exemption_credits") or {}).get("applied")]
        assert applied, state
        assert all(c["exemption_credits"]["total"] > 0 for c in applied if c["exemption_credits"]["federal_agi"]
                   is None), state
    or_calls = harness.expand(json.loads(
        (REPO / "packages/core/tests/goldens/state_knowledge/or_2025.json").read_text()))["state_tax"]
    assert any(c.get("exemption_credits", {}).get("limitation_reduction") for c in or_calls)
    assert any("needs federal_agi" in c.get("error", "") for c in or_calls)


def _or_block_raw() -> dict:
    import yaml

    raw = yaml.safe_load((KNOWLEDGE / "states" / "or" / "2025.yaml").read_text(encoding="utf-8"))
    return copy.deepcopy(raw["tax"]["exemption_credits"])


def test_the_schema_rejects_a_malformed_ceiling():
    from taxfill_core.knowledge import StateExemptionCredits

    StateExemptionCredits.model_validate(_or_block_raw())
    cases = {
        "an unknown kind": lambda b: b["agi_ceiling"]["ceilings"].__setitem__("elderly", {
            "single": 1, "married_filing_jointly": 1, "married_filing_separately": 1, "head_of_household": 1}),
        "a status missing": lambda b: b["agi_ceiling"]["ceilings"]["regular"].pop("single"),
        "a zero ceiling": lambda b: b["agi_ceiling"]["ceilings"]["regular"].__setitem__("single", 0),
        "no ceilings": lambda b: b["agi_ceiling"].__setitem__("ceilings", {}),
        "an empty worksheet": lambda b: b["agi_ceiling"].__setitem__("worksheet", " "),
        "a limitation too": lambda b: b.__setitem__("agi_limitation", _ca_block_raw()["agi_limitation"]),
        "a negative QSS maximum": lambda b: b["credits"]["regular"].__setitem__(
            "max_count_qualifying_surviving_spouse", -1),
        "a QSS maximum without max_count": lambda b: b["credits"]["dependent"].__setitem__(
            "max_count_qualifying_surviving_spouse", 1),
        "an empty tax-limit line": lambda b: b.__setitem__("limited_to_tax_line", " "),
    }
    for name, mutate in cases.items():
        block = _or_block_raw()
        mutate(block)
        with pytest.raises(ValidationError):
            StateExemptionCredits.model_validate(block)
            pytest.fail(name)


# ── Phase K JK28 final review (2026-10-23): every TY2025 face figure, restated ────────────────────────────────────
# A golden regenerated with --write takes whatever the pack says, so a mistyped amount, box maximum or ceiling would
# pass it. These tables restate each kind's printed figures from the forms the packs quote: AR1000F lines 7A-7C
# ($29 a box; the head-of-household/surviving-spouse box "(Filing status 3 only)" / "(Filing status 6 only)"); DE
# PIT-RES lines 27a-27b ($110); IA 1040 Step 3 ($40 a/c, $20 b; "Enter 1 (enter 2 if filing status 2 or 4)"); NE 1040N
# line 4 and line 18 ($171, 4b for a joint return only); OR-40 lines 6a-6e and 25 ($256), with the Instructions'
# "Exemption credit worksheet" (re-read 2026-10-23, sha256 4ee45bad719499e2): "1. If your federal AGI is more than
# $100,000 and your filing status is single or married filing separately, or more than $200,000 for all others, enter
# 0 ..." (Regular boxes and line 6c dependents); "2. If your federal AGI is more than $100,000, enter 0" (Severe
# disability); "3. If your federal AGI is more than $100,000, enter 0" (line 6d children with a qualifying disability).

_S, _J, _M, _H = "single", "married_filing_jointly", "married_filing_separately", "head_of_household"


def _per(single, joint, separate, hoh):
    return {_S: single, _J: joint, _M: separate, _H: hoh}


FACE_2025 = {  # state -> kind -> (amount, line, max_count per status or None, the QSS maximum or None)
    "ar": {
        **{kind: (29, "7A", _per(1, 2, 2, 1), 1)
           for kind in ("personal", "senior", "senior_special", "blind", "deaf")},
        "head_of_household_or_surviving_spouse": (29, "7A", _per(0, 0, 0, 1), 1),
        "dependent": (29, "7B", None, None),
    },
    "de": {
        "personal": (110, "27a", _per(1, 2, 2, 1), 1),
        "senior": (110, "27b", _per(1, 2, 2, 1), 1),
        "dependent": (110, "27a", None, None),
    },
    "ia": {
        "personal": (40, "Step 3a", _per(1, 2, 1, 2), 1),
        "senior": (20, "Step 3b", _per(1, 2, 1, 1), 1),
        "blind": (20, "Step 3b", _per(1, 2, 1, 1), 1),
        "dependent": (40, "Step 3c", None, None),
    },
    "ne": {
        "personal": (171, "4a-4b", _per(1, 2, 1, 1), 1),
        "dependent": (171, "4c", None, None),
    },
    "or": {
        "regular": (256, "6a-6b", _per(1, 2, 2, 1), 1),
        "severe_disability": (256, "6a-6b", _per(1, 2, 2, 1), 1),
        "dependent": (256, "6c", None, None),
        "disabled_child": (256, "6d", None, None),
    },
}
OR_CEILINGS_2025 = {
    "regular": _per(100_000, 200_000, 100_000, 200_000),
    "dependent": _per(100_000, 200_000, 100_000, 200_000),
    "severe_disability": _per(100_000, 100_000, 100_000, 100_000),
    "disabled_child": _per(100_000, 100_000, 100_000, 100_000),
}


@pytest.mark.parametrize("state", sorted(FACE_2025))
def test_every_2025_credit_kind_carries_its_face_figures(state):
    block = load_state_knowledge(state, 2025, base_dir=KNOWLEDGE).tax.exemption_credits
    shipped = {kind: (c.amount, c.line, c.max_count, c.max_count_qualifying_surviving_spouse)
               for kind, c in block.credits.items()}
    assert shipped == FACE_2025[state]
    if state == "or":
        assert block.agi_ceiling.ceilings == OR_CEILINGS_2025
    else:
        assert block.agi_ceiling is None and block.agi_limitation is None


@pytest.mark.parametrize("state", sorted(FACE_2025))
def test_every_2025_box_maximum_is_the_refusal_boundary(state):
    # At the maximum the call goes through and the line is count x amount; one more is refused, per status and kind.
    agi = {"federal_agi": 50_000} if state == "or" else {}
    for kind, (amount, _line, most, qss_most) in FACE_2025[state].items():
        cases = [] if most is None else [(status, n) for status, n in most.items()]
        if qss_most is not None:
            cases.append(("qualifying_surviving_spouse", qss_most))
        for status, n in cases:
            if n:
                ok = _st(state, 60_000, filing_status=status, exemption_credit_counts={kind: n}, **agi)
                assert ok.exemption_credits.credits[kind].credit == n * amount, (state, kind, status)
            with pytest.raises(ValueError, match=rf"\['{kind}'\] = {n + 1} is more than the {n} that"):
                _st(state, 60_000, filing_status=status, exemption_credit_counts={kind: n + 1}, **agi)


@pytest.mark.parametrize("status", (_S, _J, _M, _H))
def test_or_2025_each_kind_is_allowed_at_its_ceiling_and_denied_one_dollar_over(status):
    for kind, table in OR_CEILINGS_2025.items():
        counts = {kind: 1} | ({"dependent": 1} if kind == "disabled_child" else {})
        at = _st("or", 60_000, filing_status=status, exemption_credit_counts=counts,
                 federal_agi=table[status]).exemption_credits
        over = _st("or", 60_000, filing_status=status, exemption_credit_counts=counts,
                   federal_agi=table[status] + 1).exemption_credits
        assert at.credits[kind].credit == 256 and at.agi_ceilings[kind] == table[status], (kind, status)
        crossed = [k for k in counts if OR_CEILINGS_2025[k][status] == table[status]]  # denied one dollar over
        assert (at.total, at.total - over.total) == (256 * len(counts), 256 * len(crossed)), (kind, status)
        assert f"{kind}: more than ${table[status]:,} -> $256 denied" in _st(
            "or", 60_000, filing_status=status, exemption_credit_counts=counts, federal_agi=table[status] + 1).work


def test_or_2025_line_6d_counts_a_child_with_a_disability():
    # Two dependents, one a child with a qualifying disability: 6c 2 + 6d 1 + one Regular box = 4 x $256 = $1,024.
    ec = _st("or", 60_000, filing_status=_H, exemption_credit_counts={"regular": 1, "dependent": 2,
                                                                        "disabled_child": 1},
             federal_agi=60_000).exemption_credits
    assert ec.credits["disabled_child"].line == "6d" and ec.credits["disabled_child"].credit == 256
    assert (ec.exemption_amount, ec.total) == (1_024, 1_024)
