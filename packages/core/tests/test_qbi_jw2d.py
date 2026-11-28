"""JW2d (walkthrough finding P1-01; P-039): the 2025 Form 8995 pack, calc op qbi_deduction and the 1099-DIV box 5 finding.

Three fictitious returns are worked by hand from the printed 2025 Form 8995 lines (quoted in the pack's comments):

* RETURN_A: two businesses, both prior-year carryforwards absorbed, the deduction before the limit (line 10) binding.
  Lines 4, 8 and 13 are each 2 more than a multiple of 5, so 20% of them ends in .4 and one more dollar rounds the
  product up: a $1 move of a multiplicand then changes its product, which it otherwise would not.
* RETURN_B: the income limitation (line 14) binding, the business loss carryforward larger than this year's QBI.
* RETURN_C: both loss carryforwards larger than this year's income, so both carryforward lines are live.

A $1 move cannot fail every rule on one return: "15 == min(10, 14)" sees only the smaller operand, and the
carryforward rules see lines 2, 3, 6 and 7 only when the loss is larger than the income (else both sides are zero).
Each mutation below names the return on which it is live. All names and numbers are fictitious.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.extract import extract_document
from taxfill_core.fetch import cached_blank_path
from taxfill_core.filler import fill_form
from taxfill_core.knowledge import form_line, load_knowledge
from taxfill_core.qbi import qbi_deduction
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import FilingItem, qualified_field_name, relations, verify_filing, verify_form

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = load_pack(REPO_ROOT / "formpacks/federal/2025/f8995/pack.yaml")
F1040 = load_pack(REPO_ROOT / "formpacks/federal/2025/f1040/pack.yaml")
F1040NR = load_pack(REPO_ROOT / "formpacks/federal/2025/f1040nr/pack.yaml")

REL_4 = "4 == max(0, 2 - max(3, -3))"
REL_5 = "5 == 4 * 0.20"
REL_8 = "8 == max(0, 6 - max(7, -7))"
REL_9 = "9 == 8 * 0.20"
REL_10 = "10 == 5 + 9"
REL_13 = "13 == max(0, 11 - 12)"
REL_14 = "14 == 13 * 0.20"
REL_15 = "15 == min(10, 14)"
REL_16 = "max(16, -16) == max(0, max(3, -3) - 2)"
REL_17 = "max(17, -17) == max(0, max(7, -7) - 6)"
REL_11 = "11 == min(11, 394600)"
ALL_RELATIONS = [REL_4, REL_5, REL_8, REL_9, REL_10, REL_13, REL_14, REL_15, REL_16, REL_17, REL_11]

# 2 = 30,000 - 4,998 = 25,002; 4 = 25,002 - 3,000 = 22,002; 5 = 4,400.4 -> 4,400. 8 = 1,212 - 200 = 1,012;
# 9 = 202.4 -> 202; 10 = 4,602. 13 = 80,000 - 4,998 = 75,002; 14 = 15,000.4 -> 15,000; 15 = min(4,602, 15,000).
# 16 and 17: the carryforwards are absorbed ("If greater than zero, enter -0-"), left blank.
RETURN_A = {"1.i.c": 30_000, "1.ii.c": -4_998, "2": 25_002, "3": 3_000, "4": 22_002, "5": 4_400,
            "6": 1_212, "7": 200, "8": 1_012, "9": 202, "10": 4_602,
            "11": 80_000, "12": 4_998, "13": 75_002, "14": 15_000, "15": 4_602}
# 2 = 2,000; 3 = 5,000, so 4 = 0, 5 = 0 and 16 = 3,000. 8 = 25,002; 9 = 5,000.4 -> 5,000; 10 = 5,000.
# 13 = 20,000 - 1,000 = 19,000; 14 = 3,800; 15 = min(5,000, 3,800) = 3,800: the income limitation binds.
RETURN_B = {"1.i.c": 2_000, "2": 2_000, "3": 5_000, "4": 0, "5": 0,
            "6": 25_002, "8": 25_002, "9": 5_000, "10": 5_000,
            "11": 20_000, "12": 1_000, "13": 19_000, "14": 3_800, "15": 3_800, "16": 3_000}
# 2 = -1,000; 3 = 500: 4 = 0, 16 = 500 - (-1,000) = 1,500. 6 = 300; 7 = 1,000: 8 = 0, 17 = 700.
# 10 = 0; 13 = 50,000; 14 = 10,000; 15 = 0.
RETURN_C = {"1.i.c": -1_000, "2": -1_000, "3": 500, "4": 0, "5": 0, "6": 300, "7": 1_000, "8": 0, "9": 0,
            "10": 0, "11": 50_000, "12": 0, "13": 50_000, "14": 10_000, "15": 0, "16": 1_500, "17": 700}
RETURNS = {"A": RETURN_A, "B": RETURN_B, "C": RETURN_C}
PAREN_BOXES = ("3", "7", "16", "17")


def _check(relation: str, values: dict[str, int]):
    return next(c for c in relations(PACK, values) if c.relation == relation)


# ── the pack ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_pack_declares_the_face_relations_and_the_line_13a_legs():
    assert PACK.form == "8995" and PACK.tax_year == 2025 and PACK.jurisdiction == "federal"
    assert PACK.relations == ALL_RELATIONS
    assert PACK.cross_form == ["15 == f1040.13a", "15 == f1040nr.13a"]
    assert PACK.identity_fields == ["name", "identifying_number"]
    keys = {f.line for f in PACK.fields}
    rows = {f"1.{r}.{c}" for r in ("i", "ii", "iii", "iv", "v") for c in "abc"}
    assert keys == {"name", "identifying_number"} | rows | {str(n) for n in range(2, 18)}


@pytest.mark.parametrize("name", sorted(RETURNS))
@pytest.mark.parametrize("sign", [1, -1], ids=["parens-positive", "parens-negative"])
def test_a_correct_return_passes_every_relation(name, sign):
    values = {k: (sign * v if k in PAREN_BOXES else v) for k, v in RETURNS[name].items()}
    checks = relations(PACK, values)
    assert {c.relation for c in checks} == set(ALL_RELATIONS)
    assert [c.detail for c in checks if c.status != "PASS"] == []


# (return, relation, line, delta): every operand of every rule, on a return where a $1 move reaches the rule.
MUTATIONS = [
    *[("A", REL_4, line, 1) for line in ("4", "2", "3")],
    *[("A", REL_5, line, 1) for line in ("5", "4")],
    *[("A", REL_8, line, 1) for line in ("8", "6", "7")],
    *[("A", REL_9, line, 1) for line in ("9", "8")],
    *[("A", REL_10, line, 1) for line in ("10", "5", "9")],
    *[("A", REL_13, line, 1) for line in ("13", "11", "12")],
    *[("A", REL_14, line, 1) for line in ("14", "13")],
    ("A", REL_15, "15", 1), ("A", REL_15, "10", -1),
    ("B", REL_15, "15", -1), ("B", REL_15, "14", -1),
    *[("B", REL_16, line, 1) for line in ("16", "3", "2")],
    ("A", REL_16, "16", 1),
    *[("C", REL_16, line, 1) for line in ("16", "3", "2")],
    *[("C", REL_17, line, 1) for line in ("17", "7", "6")],
    ("A", REL_17, "17", 1),
]


@pytest.mark.parametrize("ret, relation, line, delta", MUTATIONS,
                         ids=[f"{r}:{rel.split(' ==')[0]}:{ln}{d:+d}" for r, rel, ln, d in MUTATIONS])
def test_each_rule_fails_when_an_operand_moves_a_dollar(ret, relation, line, delta):
    values = dict(RETURNS[ret])
    assert _check(relation, values).status == "PASS"
    values[line] = values.get(line, 0) + delta
    assert _check(relation, values).status == "FAIL", (relation, line, delta)


def test_the_20_percent_lines_round_half_away_from_zero():
    # Line 4 of 1,003 -> 200.60 -> 201 (the pack comment's own example); 1,002 -> 200.40 -> 200.
    assert _check(REL_5, {"4": 1_003, "5": 201}).status == "PASS"
    assert _check(REL_5, {"4": 1_003, "5": 200}).status == "FAIL"
    assert _check(REL_5, {"4": 1_002, "5": 200}).status == "PASS"


def test_a_carryforward_written_on_the_wrong_side_of_zero_still_fails_a_wrong_total():
    # Line 4 "Combine lines 2 and 3": a filler that ADDED the parenthesised loss (25,002 + 3,000) fails either sign.
    for sign in (1, -1):
        assert _check(REL_4, {**RETURN_A, "3": sign * 3_000, "4": 28_002}).status == "FAIL"


@pytest.mark.parametrize("line_11, status", [
    (394_600, "PASS"), (394_601, "FAIL"), (500_000, "FAIL"), (197_301, "PASS"), (-2_500, "PASS"), (None, "PASS")])
def test_line_11_above_the_larger_printed_threshold_fails(line_11, status):
    # The note above line 1: "at or below $197,300 ($394,600 if married filing jointly)". The face has no
    # filing-status box, so 197,301 on a return that is not joint passes (the residual the pack header records).
    values = {} if line_11 is None else {"11": line_11}
    assert _check(REL_11, values).status == status


def test_the_line_11_literal_is_the_largest_2025_threshold():
    thresholds = load_knowledge("federal", 2025).tax.qbi_deduction.thresholds
    assert REL_11 == f"11 == min(11, {max(thresholds.values())})"
    assert max(thresholds, key=thresholds.get) == "married_filing_jointly"


def _dump(pack, values: dict[str, int]) -> dict[str, str]:
    by_line = {f.line: f for f in pack.fields}
    return {qualified_field_name(pack, by_line[line]): str(amount) for line, amount in values.items()}


@pytest.mark.parametrize("parent, leg", [(F1040, "f1040"), (F1040NR, "f1040nr")])
def test_line_15_ties_to_line_13a_of_the_return_it_is_filed_with(parent, leg):
    def filing(line_13a: int):
        return verify_filing([
            FilingItem(form_key="f8995", pack=PACK, fields=_dump(PACK, RETURN_A)),
            FilingItem(form_key=leg, pack=parent, fields=_dump(parent, {"13a": line_13a})),
        ])

    rule, other = f"15 == {leg}.13a", "15 == f1040nr.13a" if leg == "f1040" else "15 == f1040.13a"
    good = {c.relation: c.status for c in filing(4_602).cross_form}
    assert (good[rule], good[other]) == ("PASS", "SKIPPED")     # one return per filing: the other leg is skipped
    assert {c.relation: c.status for c in filing(4_603).cross_form}[rule] == "FAIL"


# ── calc op qbi_deduction ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_walkthrough_shape_box_5_dividends_only():
    # A single index-fund holder: no business, $40 of section 199A dividends, Form 8995 line 11 169,907 and line 12
    # 1,900 qualified dividends + 2,800 net capital gain (the smaller of Schedule D lines 15 and 16).
    r = qbi_deduction(169_907, "single", 2025, qualified_reit_dividends=40, qualified_dividends=1_900,
                      schedule_d_long_term=2_800, schedule_d_net=2_800)
    assert r.deduction == 8
    assert r.lines == {"2": 0, "4": 0, "5": 0, "6": 40, "8": 40, "9": 8, "10": 8,
                       "11": 169_907, "12": 4_700, "13": 165_207, "14": 33_041, "15": 8}
    assert r.independent == r.lines
    assert (r.qbi_loss_carryforward, r.reit_ptp_loss_carryforward, r.income_limited) == (0, 0, False)
    assert r.threshold == 197_300
    assert any("45 days" in c and "holding period" in c for c in r.confirm)
    assert "Form 1040 line 13a" in r.work
    assert [c.detail for c in relations(PACK, r.lines) if c.status != "PASS"] == []


def test_return_a_from_the_op_matches_the_hand_worked_lines():
    r = qbi_deduction(80_000, "married_filing_jointly", 2025,
                      businesses=[{"name": "Example Design Studio", "tin": "999-88-0101", "qbi": 30_000},
                                  {"name": "Example Bike Repair", "tin": "999880102", "qbi": -4_998}],
                      qbi_loss_carryforward=-3_000, qualified_reit_dividends=1_000, ptp_income=212,
                      reit_ptp_loss_carryforward=200, qualified_dividends=4_998)
    money = {k: v for k, v in r.lines.items() if isinstance(v, int)}
    assert money == RETURN_A
    assert {k: v for k, v in r.lines.items() if isinstance(v, str)} == {
        "1.i.a": "Example Design Studio", "1.i.b": "999880101", "1.ii.a": "Example Bike Repair", "1.ii.b": "999880102"}
    assert r.deduction == 4_602 and r.income_limited is False and r.threshold == 394_600
    assert r.inputs["qbi_loss_carryforward"] == 3_000   # the "( )" sign is ignored either way


def test_a_loss_carryforward_larger_than_income_carries_forward():
    r = qbi_deduction(50_000, "head_of_household", 2025, businesses=[{"name": "Example Crafts", "qbi": -1_000}],
                      qbi_loss_carryforward=500, ptp_income=300, reit_ptp_loss_carryforward=1_000)
    money = {k: v for k, v in r.lines.items() if isinstance(v, int)}
    assert money == RETURN_C
    assert (r.qbi_loss_carryforward, r.reit_ptp_loss_carryforward, r.deduction) == (1_500, 700, 0)
    assert "Carry forward to next year: line 16 ($1,500); line 17 ($700)." in r.work


def test_the_income_limitation_binds():
    r = qbi_deduction(20_000, "single", 2025, businesses=[{"name": "Example Tutoring", "qbi": 2_000}],
                      qbi_loss_carryforward=5_000, qualified_reit_dividends=25_002, net_capital_gain=1_000)
    money = {k: v for k, v in r.lines.items() if isinstance(v, int)}
    assert money == RETURN_B
    assert r.income_limited is True and r.deduction == 3_800 < r.lines["10"]


def test_a_sixth_business_goes_on_the_statement_and_into_line_2():
    biz = [{"name": f"Example Shop {n}", "qbi": 1_000} for n in range(1, 7)]
    r = qbi_deduction(60_000, "single", 2025, businesses=biz)
    assert r.lines["2"] == 6_000 and r.lines["1.v.c"] == 1_000
    assert r.statement_businesses == [{"name": "Example Shop 6", "tin": "", "qbi": 1_000}]
    assert any("attach a statement" in c for c in r.confirm)


@pytest.mark.parametrize("status, at, threshold", [
    ("single", 197_300, 197_300), ("married_filing_jointly", 394_600, 394_600),
    ("married_filing_separately", 197_300, 197_300), ("head_of_household", 197_300, 197_300),
    ("qualifying_surviving_spouse", 197_300, 197_300)])
def test_at_the_threshold_computes_and_one_dollar_above_refuses(status, at, threshold):
    assert load_knowledge("federal", 2025).tax.qbi_deduction.thresholds[status] == threshold
    assert qbi_deduction(at, status, 2025, qualified_reit_dividends=100).deduction == 20
    with pytest.raises(ValueError, match="REFUSED") as err:
        qbi_deduction(at + 1, status, 2025, qualified_reit_dividends=100)
    assert "Form 8995-A" in str(err.value) and "no number" in str(err.value)


def test_an_sstb_is_a_qualified_business_at_or_below_the_threshold_and_refused_above():
    below = qbi_deduction(150_000, "single", 2025, businesses=[{"name": "Example Law", "qbi": 10_000}], sstb=True)
    assert below.deduction == 2_000 and "Exception 1" in below.work
    with pytest.raises(ValueError, match="REFUSED") as err:
        qbi_deduction(197_301, "single", 2025, businesses=[{"name": "Example Law", "qbi": 10_000}], sstb=True)
    assert "Schedule A (Form 8995-A)" in str(err.value)


def test_a_cooperative_patron_is_refused():
    with pytest.raises(ValueError, match="REFUSED.*cooperative"):
        qbi_deduction(50_000, "single", 2025, qualified_reit_dividends=100, cooperative_patron=True)


@pytest.mark.parametrize("year", [2024, 2026])
def test_a_year_without_the_block_is_refused(year):
    with pytest.raises(ValueError, match="TY2025 only"):
        qbi_deduction(50_000, "single", year, qualified_reit_dividends=100)


def test_the_op_lines_are_the_pack_keys_and_the_form_lines():
    keys = {f.line for f in PACK.fields}
    r = qbi_deduction(80_000, "single", 2025, businesses=[{"name": "Example Design Studio", "qbi": 30_000}],
                      qualified_reit_dividends=40)
    assert set(r.lines) <= keys
    pack = load_knowledge("federal", 2025)
    assert form_line(pack, "f8995.deduction") == "15" and form_line(pack, "f1040.qbi_deduction") == "13a"


def _cached_blank():
    path = cached_blank_path(PACK.source_url, PACK.pdf_sha256)
    if path is None:
        pytest.skip(f"the Form 8995 blank is not cached — warm it with fetch_blank({PACK.source_url})")
    return path


@pytest.mark.parametrize("case", ["walkthrough", "A", "C"])
def test_the_op_output_fills_the_pack_and_verifies_with_the_recompute(case, tmp_path):
    if case == "walkthrough":
        r = qbi_deduction(169_907, "single", 2025, qualified_reit_dividends=40, qualified_dividends=1_900,
                          schedule_d_long_term=2_800, schedule_d_net=2_800)
    elif case == "A":
        r = qbi_deduction(80_000, "married_filing_jointly", 2025,
                          businesses=[{"name": "Example Design Studio", "tin": "999-88-0101", "qbi": 30_000},
                                      {"name": "Example Bike Repair", "tin": "999880102", "qbi": -4_998}],
                          qbi_loss_carryforward=3_000, qualified_reit_dividends=1_000, ptp_income=212,
                          reit_ptp_loss_carryforward=200, qualified_dividends=4_998)
    else:
        r = qbi_deduction(50_000, "single", 2025, businesses=[{"name": "Example Crafts", "qbi": -1_000}],
                          qbi_loss_carryforward=500, ptp_income=300, reit_ptp_loss_carryforward=1_000)
    values = {"name": "Avery Example", "identifying_number": "999-88-1234", **r.lines}
    out = tmp_path / "f8995.pdf"
    fill_form(PACK, values, _cached_blank(), out)
    report = verify_form(PACK, out, expected=values, independent=r.independent)
    fails = [c.detail for section in (report.assertions, report.relations, report.recompute, report.clipping)
             for c in section if c.status == "FAIL"]
    assert report.ok, fails
    assert {c.line for c in report.recompute if c.status == "PASS"} == set(r.independent)
    assert len(r.independent) > 0


def test_the_recompute_catches_a_line_the_relations_do_not_tie(tmp_path):
    # Line 2 carries no relation (a sixth business goes on a statement); the op's recompute still checks it.
    r = qbi_deduction(80_000, "single", 2025, businesses=[{"name": "Example Design Studio", "qbi": 30_000}])
    wrong = {"name": "Avery Example", "identifying_number": "999-88-1234", **r.lines, "2": 30_001}
    out = tmp_path / "f8995_wrong.pdf"
    fill_form(PACK, wrong, _cached_blank(), out)
    report = verify_form(PACK, out, independent=r.independent)
    assert not report.ok
    assert [c.line for c in report.recompute if c.status == "FAIL"] == ["2"]


def test_verify_form_fails_a_form_8995_above_every_threshold(tmp_path):
    # The verifier's repro: a hand-filled Form 8995 with line 11 of 500,000 and every other line consistent.
    values = {"name": "Avery Example", "identifying_number": "999-88-1234", "1.i.c": 100_000, "2": 100_000,
              "4": 100_000, "5": 20_000, "10": 20_000, "11": 500_000, "13": 500_000, "14": 100_000, "15": 20_000}
    out = tmp_path / "f8995_above.pdf"
    fill_form(PACK, values, _cached_blank(), out)
    report = verify_form(PACK, out, expected=values)
    assert not report.ok
    assert [c.relation for c in report.relations if c.status == "FAIL"] == [REL_11]


# ── extraction: Form 1099-DIV box 5 ──────────────────────────────────────────────────────────────────────────────────


def _div(year, **boxes):
    return extract_document("documents/example-1099div.pdf", "1099-DIV", {"1a": "900.00", "1b": "700.00", **boxes},
                            tax_year=year)


def test_box_5_over_zero_carries_the_finding_for_2025():
    doc = _div(2025, **{"5": "40.00"})
    [f] = [f for f in doc.findings if f.rule_id == "V31"]
    assert f.severity == "info" and f.boxes == ["5"]
    assert "qualified REIT dividends for Form 8995 line 6" in f.message
    assert "This amount is reported to you on Form 1099-DIV, line 5." in f.message      # Instructions for Form 8995
    assert "This amount is included in the amount reported in box 1a" in f.message      # still part of box 1a
    assert "held for 45 days or less during the 91-day period" in f.message and "CONFIRM" in f.message
    assert "calc op qbi_deduction" in f.message and "Form 8995-A" in f.message
    assert "Instructions for Form 8995 (2025)" in f.citation


@pytest.mark.parametrize("year", [2024, 2026, None])
def test_box_5_in_a_year_without_a_read_form_8995_names_no_line(year):
    [f] = [f for f in _div(year, **{"5": "40.00"}).findings if f.rule_id == "V31"]
    assert "line 6" not in f.message and "Form 8995 (2025)" not in f.citation
    assert "held for 45 days or less" in f.message
    assert ("no tax_year was given" if year is None else f"{year} is not one") in f.message


@pytest.mark.parametrize("box5", [None, "0", "0.00"])
def test_no_box_5_no_finding(box5):
    doc = _div(2025, **({} if box5 is None else {"5": box5}))
    assert not [f for f in doc.findings if f.rule_id == "V31"]


def test_the_doc_spec_keeps_box_5_part_of_box_1a():
    from taxfill_core.extract import DOC_SPECS

    assert "Box 5 (section 199A dividends) is part of box 1a" in DOC_SPECS["1099-DIV"].status_note


# ── get_sources routing (the knowledge-gap pattern's neighbour theft) ───────────────────────────────────────────────


@pytest.mark.parametrize("query", ["Form 8995", "8995", "qualified business income", "QBI deduction",
                                   "section 199A dividends", "qualified REIT dividends", "8995-A", "SSTB"])
@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_qbi_queries_route_to_the_new_topic(query, year):
    from taxfill_core.sources import get_sources

    assert {s.topic for s in get_sources(query, year).sources} == {"qbi_deduction"}, query


@pytest.mark.parametrize("query, expected", [
    ("dividends", {"investment_income"}),
    ("self employment tax", {"self_employment"}),
    ("Schedule C", {"self_employment"}),
    ("capital gains", {"investment_income"}),
    ("net investment income", {"investment_income"}),
    ("FDAP", {"nonresident_fdap"}),
])
def test_the_new_topic_does_not_steal_its_neighbours(query, expected):
    from taxfill_core.sources import get_sources

    assert {s.topic for s in get_sources(query, 2025).sources} == expected, query


@pytest.mark.parametrize("query", ["qualified dividends", "1099-DIV", "ordinary dividends", "capital gains", "wages",
                                   "net capital gain", "capital gain distributions"])
def test_the_dividend_and_wage_queries_stay_where_they_were(query):
    # Their routes did not move with the topic (the route probe before and after it); the new topic is not among them.
    from taxfill_core.sources import get_sources

    assert "qbi_deduction" not in {s.topic for s in get_sources(query, 2025).sources}, query


def test_file_and_pay_no_longer_calls_the_2025_form_8995_an_unmapped_draft():
    from taxfill_core.file_and_pay import _unmapped_attachments

    assert _unmapped_attachments(["8995"], 2025) == []
    assert _unmapped_attachments(["8995"], 2024) == ["8995"]     # no 2024 pack: still the stamped draft
