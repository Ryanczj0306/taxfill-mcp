"""Pub 15-T (2026) percentage-method knowledge (Phase J JP1b).

The tables are transcribed; these tests DERIVE every row from the pack's own rate schedules and standard
deductions as the second pass: a STANDARD row starts at a bracket floor shifted by (standard deduction - Worksheet
1A line 1g) and carries the tax up to that floor; a Step 2 checkbox row is the half-width bracket shifted by half the
standard deduction, carrying half the tax.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from taxfill_core.knowledge import load_knowledge

# The withholding table -> the rate schedule and standard deduction it is built on ("Single or Married Filing
# Separately" is ONE table, built on the single schedule).
_BASIS = {"married_filing_jointly": "married_filing_jointly", "single_or_mfs": "single",
          "head_of_household": "head_of_household"}


def _pack():
    return load_knowledge("federal", 2026)


def _cumulative(schedule, upto: int) -> Decimal:
    tax = Decimal(0)
    for b in schedule:
        top = b.but_not_over if b.but_not_over is not None else upto
        if upto <= b.over:
            break
        tax += Decimal(min(upto, top) - b.over) * Decimal(str(b.rate))
    return tax


def _half_up(x: Decimal, q: str) -> Decimal:
    return x.quantize(Decimal(q), rounding=ROUND_HALF_UP)


def test_jp1b_the_block_reads_pub_15t_2026():
    pw = _pack().payroll_withholding
    assert pw is not None and "p15t--2026.pdf" in pw.citation.url
    assert (pw.worksheet_1a_line_1g["married_filing_jointly"], pw.worksheet_1a_line_1g["other"], pw.allowance_value) == (
        12_900, 8_600, 4_300)
    assert pw.pay_periods["biweekly"] == 26 and pw.pay_periods["daily"] == 260
    addon = pw.nonresident_alien_addon
    assert addon["w4_2020_or_later"]["annually"] == Decimal("16100.00")
    assert addon["pre_2020"]["annually"] == Decimal("11800.00")
    assert "nearest dollar" in pw.rounding
    assert load_knowledge("federal", 2025).payroll_withholding is None


@pytest.mark.parametrize("status", list(_BASIS))
def test_jp1b_every_standard_row_is_the_rate_schedule_shifted(status):
    pack = _pack()
    basis = _BASIS[status]
    schedule = pack.tax.rate_schedules.schedules[basis]
    line_1g = pack.payroll_withholding.worksheet_1a_line_1g["married_filing_jointly" if basis == "married_filing_jointly"
                                                            else "other"]
    offset = pack.tax.standard_deduction.amounts[basis] - line_1g
    rows = getattr(pack.payroll_withholding.standard, status)
    assert (rows[0].at_least, rows[0].below, rows[0].rate) == (0, offset, Decimal(0))
    assert len(rows) == len(schedule) + 1
    for row, bracket in zip(rows[1:], schedule):
        assert row.at_least == offset + bracket.over, (status, row)
        assert row.rate == Decimal(str(bracket.rate)), (status, row)
        assert row.tentative == _cumulative(schedule, bracket.over), (status, row)


@pytest.mark.parametrize("status", list(_BASIS))
def test_jp1b_every_checkbox_row_is_the_half_width_bracket(status):
    pack = _pack()
    basis = _BASIS[status]
    schedule = pack.tax.rate_schedules.schedules[basis]
    half_sd = Decimal(pack.tax.standard_deduction.amounts[basis]) / 2
    rows = getattr(pack.payroll_withholding.step2_checkbox, status)
    assert (rows[0].at_least, Decimal(rows[0].below)) == (0, _half_up(half_sd, "1"))
    for row, bracket in zip(rows[1:], schedule):
        assert row.at_least == int(_half_up(half_sd + Decimal(bracket.over) / 2, "1")), (status, row)
        assert row.rate == Decimal(str(bracket.rate))
        assert row.tentative == _half_up(_cumulative(schedule, bracket.over) / 2, "0.01"), (status, row)


def test_jp1b_the_tables_are_contiguous_and_refuse_a_gap():
    from pydantic import ValidationError  # noqa: PLC0415

    from taxfill_core.knowledge import WithholdingTables  # noqa: PLC0415

    good = _pack().payroll_withholding.standard.model_dump()
    good["single_or_mfs"][2]["at_least"] += 1
    with pytest.raises(ValidationError, match="must end where"):
        WithholdingTables.model_validate(good)
