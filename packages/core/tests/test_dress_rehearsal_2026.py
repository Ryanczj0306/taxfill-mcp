"""TY2026 dress rehearsals, scenarios t-t4 (Phase J JT4c).

SYNTHETIC households with demo amounts — each fixture is built only from its own stated facts. Each runs the
whole path in REHEARSAL mode: extract -> calc -> fill (the 2026 draft packs) -> verify_filing -> filing_summary ->
file_and_pay. The blanks come from the local cache (never a download); an empty cache SKIPS, like the readonly
sweeps. All four flip to final mode at JT6.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from taxfill_core.calc import (
    elective_deferral_room,
    schedule_1a_deductions,
    tax_from_taxable_income,
)
from taxfill_core.estimate import IncomeSnapshot, W2Box12, W2Facts, estimate_refund
from taxfill_core.extract import extract_document
from taxfill_core.fetch import _cache_path, compute_sha256, default_cache_dir
from taxfill_core.file_and_pay import FilingManifestItem, file_and_pay
from taxfill_core.filing_summary import filing_summary
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import FormPack, load_pack
from taxfill_core.schemas.profile import Answer, Household, Identity, Profile, Provenance
from taxfill_core.verify import FilingItem, verify_filing

from test_filing_integration import _build_values

REPO_ROOT = Path(__file__).resolve().parents[3]
US = Provenance.user_stated()
YEAR = 2026


def _ans(v):
    return Answer(value=v, provenance=US)


def _pack(form: str) -> FormPack:
    return load_pack(REPO_ROOT / f"formpacks/federal/{YEAR}/{form}/pack.yaml")


def _cached_blank(pack: FormPack) -> Path:
    path = _cache_path(default_cache_dir(), pack.source_url)
    if not path.is_file() or compute_sha256(path) != pack.pdf_sha256:
        pytest.skip(f"the {pack.form} {pack.tax_year} blank is not cached — warm it with fetch_blank "
                    f"({pack.source_url}); a dress rehearsal never downloads")
    return path


def _fill_and_verify(tmp_path: Path, money: dict[str, dict[str, int]], independent=None, text=None):
    items = []
    for key, lines in money.items():
        pack = _pack(key)
        values = _build_values(pack, lines)
        values.update((text or {}).get(key, {}))
        out = tmp_path / f"{key}.pdf"
        fill_form(pack, values, _cached_blank(pack), out, rehearsal=True)
        items.append(FilingItem(form_key=key, pack=pack, pdf_path=out))
    report = verify_filing(items, independent=independent, rehearsal=True)
    fails = {name: [c.detail for c in (getattr(report, name) or []) if c.status == "FAIL"]
             for name in ("assertions", "relations", "recompute", "clipping", "checkboxes", "identity", "cross_form")}
    assert report.ok, "verify_filing(rehearsal=True) failed:\n" + "\n".join(
        f"[{n}] {d}" for n, ds in fails.items() for d in ds)
    return report


def _passed(report) -> set[tuple[str, str]]:
    return {(c.form_key, c.relation) for c in report.cross_form if c.status == "PASS"}


# ── t: a hypothetical U.S. citizen with two CONCURRENT employers all year ──

T_W2S = [
    W2Facts(employer="Demo Full-Time Co", box1=70_000, box2=5_500, box3=80_000, box4=4_960, box5=80_000, box6=1_160,
            box12=[W2Box12(code="D", amount=10_000), W2Box12(code="DD", amount=7_000)]),
    W2Facts(employer="Demo Part-Time Co", box1=18_000, box2=900, box3=21_000, box4=1_302, box5=21_000, box6=304,
            box12=[W2Box12(code="D", amount=3_000), W2Box12(code="DD", amount=2_400)]),
]
T_INTEREST, T_CAR_LOAN = 400, 1_480


def test_t_two_concurrent_employers(tmp_path):
    # extract: the 2026 W-2 readings route code D to the one per-person 402(g) limit; the 1098-VLI passes V19-V21.
    for w in T_W2S:
        doc = extract_document(f"docs/{w.employer}.pdf", "W-2", {
            "employee_ssn": "123-45-6789", "employer_ein": "12-3456789", "1": str(w.box1), "2": str(w.box2),
            "12a": f"D {w.coded('D')}.00", "12b": f"DD {w.coded('DD')}.00"}, tax_year=YEAR)
        assert not [f for f in doc.findings if f.severity == "error"]
        assert any(f.rule_id == "V25" and "402(g)" in f.message for f in doc.findings)
    vli = extract_document("docs/demo-1098vli.pdf", "1098-VLI", {
        "lender_name": "Demo Auto Credit", "1": f"{T_CAR_LOAN}.00", "2a": "2026", "2b": "Demo", "2c": "Wagon",
        "2d": "1DEMO00000VIN0001", "3a": "2026-02-10", "4": "31,000.00", "5": "0", "6": True, "7": True},
        tax_year=YEAR)
    assert not vli.findings
    # calc: the 402(g) room across BOTH employers, Schedule 1-A Part IV, the tax.
    room = elective_deferral_room(deferrals=[{"employer": w.employer, "elective_deferrals": w.coded("D")}
                                             for w in T_W2S], year=YEAR)
    assert (room.limit, room.room) == (24_500, 24_500 - 13_000)
    wages = sum(w.box1 for w in T_W2S)
    agi = wages + T_INTEREST
    s1a = schedule_1a_deductions(magi=agi, filing_status="single", year=YEAR, car_loan_interest=T_CAR_LOAN)
    assert s1a.total_deduction == T_CAR_LOAN
    std = 16_100
    taxable = agi - std - s1a.total_deduction
    tax = tax_from_taxable_income(taxable, "single", YEAR).tax
    withheld = sum(w.box2 for w in T_W2S)
    owed = tax - withheld
    assert owed > 0
    # the estimate from the structured W-2s agrees with the return.
    profile = Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
                      identity=Identity(us_person=_ans(True)))
    est = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=T_W2S, interest=T_INTEREST, car_loan_interest=T_CAR_LOAN))
    assert est.point == -owed
    # fill + verify (rehearsal).
    report = _fill_and_verify(tmp_path, {
        "f1040": {"1a": wages, "1z": wages, "2b": T_INTEREST, "9": agi, "11a": agi, "11b": agi, "12e": std,
                  "13a": s1a.total_deduction, "14": std + s1a.total_deduction, "15": taxable, "16": tax, "18": tax, "22": tax,
                  "24a": tax, "24c": tax, "25a": withheld, "25d": withheld, "33": withheld, "37": owed},
        "sched_1a": {"1": agi, "3": agi, "36": s1a.total_deduction, "44": s1a.total_deduction},
    }, independent={"f1040": {"16": tax}})
    assert {("f1040", "13a == sched_1a.44"), ("sched_1a", "1 == f1040.11b")} <= _passed(report)
    # filing_summary + file_and_pay: 2027-04-15 and the with-payment address.
    item = FilingManifestItem(form="1040", tax_year=YEAR, bottom_line=-owed, state="California")
    summary = filing_summary([item], today=date(2027, 2, 1)).items[0]
    assert f"you owe ${owed:,}" in summary.headline
    ret = file_and_pay([item]).returns[0]
    assert any("2027-04-15" in d for d in ret.deadlines)
    assert "Louisville, KY 40293-1000" in ret.mailing_address


# ── t4: a hypothetical head-of-household filer with a qualifying child (the JR2c what-if) ──

T4 = {"wages": 182_000, "withheld": 36_000, "roth_contribution": 7_000, "contribution_date": "2026-03-10",
      "transfer_date": "2026-11-03", "value_at_transfer": 8_000, "conversion_date": "2026-11-12", "gift": 600}


def test_t4_recharacterize_then_convert_with_a_170p_gift(tmp_path):
    from taxfill_core.calc import charitable_deduction, child_tax_credit, ira_recharacterization  # noqa: PLC0415

    f = T4
    # extract: the two 1099-Rs read as code N (recharacterized this year) and code 2 (a conversion under 59½).
    for code, gross, taxable in (("N", f["value_at_transfer"], "0.00"), ("2", f["value_at_transfer"], None)):
        reading = {"recipient_tin": "123-45-6789", "1": f"{gross}.00", "7": code, "7_ira_sep_simple": code == "2"}
        if taxable is not None:
            reading["2a"] = taxable
        else:
            reading["2b_not_determined"] = True
        doc = extract_document(f"docs/demo-1099r-{code}.pdf", "1099-R", reading, tax_year=YEAR)
        assert not [x for x in doc.findings if x.severity == "error"], doc.findings
    # calc: recharacterize the excess Roth contribution, then convert — Form 8606 from the op.
    r = ira_recharacterization(
        direction="roth_to_traditional", amount=f["roth_contribution"], contribution_year=YEAR,
        contribution_date=f["contribution_date"], transfer_date=f["transfer_date"],
        contributions_during=f["roth_contribution"], closing_fmv=f["value_at_transfer"], whole_account=True,
        magi=f["wages"], filing_status="head_of_household", covered_by_employer_plan=True,
        then_convert={"date": f["conversion_date"], "amount": f["value_at_transfer"],
                      "taxable_income_before": 150_000, "magi_before": f["wages"], "dec31_total_value": 0})
    assert r.form_1099r_code == "N" and r.deduction["deductible"] == 0
    converted_taxable = r.then_convert.taxable_amount
    assert converted_taxable == f["value_at_transfer"] - f["roth_contribution"]          # 7,000 / 8,000 = 0.875
    gift = charitable_deduction(YEAR, "head_of_household", [{"amount": f["gift"], "cash": True, "teos_code": "PC"}],
                                agi=f["wages"] + converted_taxable)
    nonitemizer = gift.nonitemizer_deduction
    assert nonitemizer == f["gift"]
    agi = f["wages"] + converted_taxable
    std = 24_150
    taxable = agi - std - nonitemizer
    tax = tax_from_taxable_income(taxable, "head_of_household", YEAR).tax
    ctc = child_tax_credit(1, 0, agi, tax, f["wages"], "head_of_household", YEAR)
    credits = ctc.nonrefundable_used
    after = tax - credits
    refund = f["withheld"] - after
    report = _fill_and_verify(tmp_path, {
        "f1040": {"1a": f["wages"], "1z": f["wages"], "4a": 2 * f["value_at_transfer"], "4b": converted_taxable,
                  "9": agi, "11a": agi, "11b": agi, "12e": std, "12f": nonitemizer, "14": std + nonitemizer,
                  "15": taxable, "16": tax, "18": tax, "19": credits, "21": credits, "22": after, "24a": after,
                  "24c": after, "25a": f["withheld"], "25d": f["withheld"], "33": f["withheld"],
                  "34": max(0, refund), "35a": max(0, refund), "37": max(0, -refund)},
        "f8606": {"1": f["roth_contribution"], "3": f["roth_contribution"], "5": f["roth_contribution"],
                  "8": f["value_at_transfer"], "9": f["value_at_transfer"],
                  "11": f["roth_contribution"], "13": f["roth_contribution"],
                  "16": f["value_at_transfer"], "17": f["roth_contribution"], "18": converted_taxable},
    }, independent={"f1040": {"16": tax}}, text={
        "f1040": {"filing_status.single": False, "filing_status.hoh": True,
                  "filing_status.hoh_qss_child_name": "Demo Child"},
        "f8606": {"10.dec": "0.875"}})
    assert report.ok
    # filing_summary + file_and_pay, with the recharacterization statement attached.
    item = FilingManifestItem(form="1040", tax_year=YEAR, bottom_line=refund, state="Texas",
                              attached_forms=["8606"], attached_statements=["recharacterization statement"])
    assert f"refund ${refund:,}" in filing_summary([item], today=date(2027, 2, 1)).items[0].headline
    ret = file_and_pay([item]).returns[0]
    assert any("2027-04-15" in d for d in ret.deadlines)
    assert any("RECHARACTERIZATION STATEMENT" in a for a in ret.assemble)
    assert ret.mailing_address is None and any("not published yet" in n for n in ret.notes)   # the 2026 refund address


# ── t2: a hypothetical J-1 researcher who is a resident alien for TY2026 ──

def test_t2_a_resident_j1_researcher_keeps_the_treaty_exemption(tmp_path):
    from taxfill_core.calc import treaty_benefit  # noqa: PLC0415
    from taxfill_core.residency import classify  # noqa: PLC0415
    from taxfill_core.schemas.profile import Immigration, ResidencyFacts, VisaPeriod  # noqa: PLC0415

    # Arrived 2024-01-10 on a J-1 as a researcher: an exempt individual for 2024 and 2025 (2 of the previous 6
    # years), so 2026's days count — a resident alien for the whole of 2026.
    imm = Immigration(visa_timeline=[VisaPeriod(status="J-1 researcher", sub_status="employment", start=date(2024, 1, 10),
                                                provenance=US)])
    rf = ResidencyFacts(days_in_us={2024: _ans(356), 2025: _ans(365), 2026: _ans(365)})
    profile = Profile(household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
                      identity=Identity(us_person=_ans(False), citizenship_country=_ans("China")),
                      immigration=imm, residency_facts=rf)
    assert classify([{"status": "J-1 researcher", "start": "2024-01-10", "end": None}], {2024: 356, 2025: 365, 2026: 365},
                    YEAR).classification == "resident"
    w2 = W2Facts(employer="Demo Research University", box1=60_000, box2=6_000, box3=60_000, box4=3_720,
                 box5=60_000, box6=870, box12=[W2Box12(code="DD", amount=6_600)])
    doc = extract_document("docs/demo-w2-j1.pdf", "W-2", {"employee_ssn": "123-45-6789", "employer_ein": "12-3456789",
                                                          "1": "60000", "2": "6000", "12a": "DD 6600"}, tax_year=YEAR)
    assert not [f for f in doc.findings if f.severity == "error"]
    # calc: China Art. 19 survives the saving clause for a resident — reported in parentheses on Schedule 1.
    treaty = treaty_benefit("china", "teacher_wages", w2.box1, year=YEAR, years_in_status=3, resident_alien=True)
    exempt = treaty.exempt_amount
    assert exempt == w2.box1 and "IN PARENTHESES on Schedule 1 line 8z" in treaty.work
    est = estimate_refund(profile, YEAR, IncomeSnapshot(w2s=[w2], treaty_exempt_income=exempt))
    assert est.point == w2.box2
    # fill + verify: the wages on line 1a, the exemption as a negative on Schedule 1 line 8z.
    std = 16_100
    report = _fill_and_verify(tmp_path, {
        "f1040": {"1a": w2.box1, "1z": w2.box1, "8": -exempt, "12e": std, "14": std, "25a": w2.box2,
                  "25d": w2.box2, "33": w2.box2, "34": w2.box2, "35a": w2.box2},
        "sched_1": {"8z": -exempt, "9": -exempt, "10": -exempt},
    }, text={"sched_1": {"8z.type": "Exempt income, China, Art. 19"}})
    assert ("f1040", "8 == sched_1.10") in _passed(report)
    item = FilingManifestItem(form="1040", tax_year=YEAR, bottom_line=w2.box2, state="Massachusetts",
                              direct_deposit=True)
    ret = file_and_pay([item]).returns[0]
    assert any("2027-04-15" in d for d in ret.deadlines) and any("routing and account" in p for p in ret.payment)
    assert f"refund ${w2.box2:,}" in filing_summary([item], today=date(2027, 2, 1)).items[0].headline


# ── t3: a hypothetical married couple filing jointly (no visa history) ──

def test_t3_a_joint_return_with_overtime_an_hsa_dividends_and_a_covered_loss(tmp_path):
    from taxfill_core.calc import hsa_deduction, tax_with_preferential_rates  # noqa: PLC0415
    from taxfill_core.schemas.profile import Spouse  # noqa: PLC0415

    plant = W2Facts(employer="Demo Plant Co", box1=62_000, box2=5_200, box3=62_000, box4=3_844, box5=62_000,
                    box6=899, box12=[W2Box12(code="TT", amount=3_000), W2Box12(code="DD", amount=8_000)])
    clinic = W2Facts(employer="Demo Clinic", box1=48_000, box2=4_100, box3=48_000, box4=2_976, box5=48_000,
                     box6=696, box12=[W2Box12(code="W", amount=3_000), W2Box12(code="DD", amount=9_000)])
    ordinary, qualified = 2_400, 1_800
    proceeds, basis = 9_000, 10_000
    # extract: TT and W route; the covered long-term 1099-B goes straight to Schedule D line 8a (Exception 1).
    tt = extract_document("docs/demo-w2-plant.pdf", "W-2", {"employee_ssn": "123-45-6789", "employer_ein": "12-3456789",
                                                           "1": "62000", "2": "5200", "12a": "TT 3000"}, tax_year=YEAR)
    assert any(f.rule_id == "V25" and "Schedule 1-A Part III" in f.message for f in tt.findings)
    w = extract_document("docs/demo-w2-clinic.pdf", "W-2", {"employee_ssn": "123-45-6780", "employer_ein": "12-3456780",
                                                           "1": "48000", "2": "4100", "12a": "W 3000"}, tax_year=YEAR)
    assert any("NEVER a second deduction" in f.message for f in w.findings)
    b = extract_document("docs/demo-1099b.pdf", "1099-B", {
        "recipient_tin": "123-45-6780", "1a": "100 sh. Demo Index Fund", "1d": f"{proceeds}.00", "1e": f"{basis}.00",
        "2_long_term": True, "12": True}, tax_year=YEAR)
    assert any(f.rule_id == "V26" and "Schedule D line 8a" in f.message for f in b.findings)
    # calc: Form 8889 (family coverage; code W is employer money), Schedule 1-A Part III, the QDCG tax.
    hsa = hsa_deduction(coverage="family", year=YEAR, personal_contributions=2_000, employer_contributions=3_000,
                        married=True)
    wages = plant.box1 + clinic.box1
    loss = proceeds - basis
    agi = wages + ordinary + loss - hsa.deduction
    s1a = schedule_1a_deductions(magi=agi, filing_status="married_filing_jointly", year=YEAR, qualified_overtime=3_000)
    std = 32_200
    taxable = agi - std - s1a.total_deduction
    tax = tax_with_preferential_rates(taxable, qualified, net_long_term_gain=loss,
                                      filing_status="married_filing_jointly", year=YEAR).tax
    withheld = plant.box2 + clinic.box2
    refund = withheld - tax
    # the estimate: each spouse's own W-2s; the code-W guard fires beside the HSA adjustment.
    profile = Profile(household=Household(marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"),
                                          spouse=Spouse(us_person=_ans(True))),
                      identity=Identity(us_person=_ans(True)))
    est = estimate_refund(profile, YEAR, IncomeSnapshot(
        w2s=[plant], dividends=ordinary, qualified_dividends=qualified,
        spouse=IncomeSnapshot(w2s=[clinic], capital_gain_long=loss, pre_agi_adjustments=hsa.deduction)))
    assert est.point == refund
    assert any("code W" in a for a in est.assumptions)
    # fill + verify.
    report = _fill_and_verify(tmp_path, {
        "f1040": {"1a": wages, "1z": wages, "3a": qualified, "3b": ordinary, "7a": loss,
                  "9": wages + ordinary + loss, "10": hsa.deduction,
                  "11a": agi, "11b": agi, "12e": std, "13a": s1a.total_deduction, "14": std + s1a.total_deduction,
                  "15": taxable, "16": tax, "18": tax, "22": tax, "24a": tax, "24c": tax, "25a": withheld,
                  "25d": withheld, "33": withheld, "34": max(0, refund), "35a": max(0, refund), "37": max(0, -refund)},
        "sched_1": {"13": hsa.deduction, "26": hsa.deduction},
        "sched_1a": {"1": agi, "3": agi, "16a.iii": 3_000, "17": 3_000, "20": 3_000, "21": 3_000, "22": agi,
                     "23": 300_000, "27": s1a.total_deduction, "44": s1a.total_deduction},
        "f8889": {"2": hsa.deduction, "3": hsa.annual_limit, "5": hsa.annual_limit, "6": hsa.annual_limit,
                  "8": hsa.annual_limit, "9": 3_000, "11": 3_000, "12": hsa.annual_limit - 3_000, "13": hsa.deduction},
        "sched_b": {"dividend_1.amount": ordinary, "6": ordinary},
        "sched_d": {"8a.d": proceeds, "8a.e": basis, "8a.h": loss, "15": loss, "16": loss, "21": loss},
    }, text={
        "f1040": {"filing_status.single": False, "filing_status.mfj": True},
        "sched_1a": {"16a.i": "Demo Plant Co", "16a.ii": "12-3456789"},
        "sched_b": {"dividend_1.payer": "Demo Index Fund"},
    })
    assert {("f1040", "10 == sched_1.26"), ("f1040", "13a == sched_1a.44"), ("sched_b", "6 == f1040.3b"),
            ("sched_d", "16 == f1040.7a")} <= _passed(report)
    item = FilingManifestItem(form="1040", tax_year=YEAR, bottom_line=refund, state="Ohio", filing_jointly=True,
                              direct_deposit=True, attached_forms=["8889"])
    ret = file_and_pay([item]).returns[0]
    assert any("2027-04-15" in d for d in ret.deadlines) and any("BOTH" in s for s in ret.sign)
