"""Cross-pack integration goldens (dev plan section 10: ``verify_filing``).

The per-pack golden (``test_formpacks_federal.py``) proves each form fills and
its own relations parse. This module proves the *filing* level: assemble a full
federal return from the REAL cached blank PDFs, fill every form with a coherent
value set, and run :func:`verify_filing` over the whole stack — exercising the
cross-form reference chains (e.g. ``f1040.8 == sched_1.10``,
``sched_c.31 == sched_1.3``, ``sched_a.2 == f1040.11``) and the cross-form
identity check (same SSN/name on every form) end to end.

These are WIRING fixtures, not full tax computations: the numbers are
internally consistent so every relation and cross_form ref holds. Scenario A's
line 16 (tax) is the ONE figure taken from the calc engine's tax-table lookup
(not a placeholder), and ``verify_filing(independent=...)`` independently
recomputes it — so the multi-form path exercises the no-LLM-arithmetic
guardrail end to end (test_e2e.py covers it for a single synthetic form).

Network-marked: needs the official blanks (warm ``.cache/blanks`` or network).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.calc import tax_from_taxable_income
from taxfill_core.fetch import OfflineFetchError, fetch_blank
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import FormPack, load_pack
from taxfill_core.verify import FilingItem, verify_filing

from test_formpacks_federal import synthetic_values

REPO_ROOT = Path(__file__).resolve().parents[3]

SSN = "999001234"
IDENTITY_CONSTANTS = {
    "identifying_number": SSN,
    "name": "Jordan Q Taxpayer",
    "name.first": "Jordan",
    "name.last": "Taxpayer",
    "mailing_address": "500 Market St, San Jose CA 95113",
    "mailing_address.street": "500 Market St",
    "mailing_address.city": "San Jose",
    "mailing_address.state": "CA",
    "mailing_address.zip": "95113",
}

# ── Scenario A — full-year resident, 2023 Form 1040 + 6 schedules ────────────
# W-2 wages 30,000; interest 500; dividends 300; Sched C net profit 48,000;
# itemizes (Sched A) state tax 3,000. Chains exercised: Sched C 31 -> Sched 1 3;
# Sched 1 10 -> 1040 8; Sched B 4/6 -> 1040 2b/3b; 1040 11 -> Sched A 2;
# Sched A 17 -> 1040 12; Sched 2/3 -> 1040 17/20/23/31.
A_FORMS = {
    "f1040": "formpacks/federal/2023/f1040/pack.yaml",
    "sched_1": "formpacks/federal/2023/sched_1/pack.yaml",
    "sched_2": "formpacks/federal/2023/sched_2/pack.yaml",
    "sched_3": "formpacks/federal/2023/sched_3/pack.yaml",
    "sched_a": "formpacks/federal/2023/sched_a/pack.yaml",
    "sched_b": "formpacks/federal/2023/sched_b/pack.yaml",
    "sched_c": "formpacks/federal/2023/sched_c/pack.yaml",
}
# Line 15 (taxable income) drives line 16 (tax). Line 16 is NOT a hand-picked
# placeholder: it comes from the calc engine's tax-table lookup so the filing
# exercises the no-LLM-arithmetic guardrail (independent recompute) end to end
# — the single-form test_e2e.py is the only other place that does. Lines 18/22/
# 24 follow line 16 (17/21/23 are zero in this stack) and 37 == 24 - 33.
A_TAXABLE_INCOME = 75800
A_FILING_STATUS = "single"
A_TAX = tax_from_taxable_income(A_TAXABLE_INCOME, A_FILING_STATUS, year=2023).tax
A_TOTAL_PAYMENTS = 4000  # line 33 == 25d + 26 + 32 == 25d == 4000
A_MONEY = {
    "f1040": {
        "1a": 30000, "1z": 30000, "2b": 500, "3b": 300, "8": 48000,
        "9": 78800, "11": 78800, "12": 3000, "14": 3000, "15": A_TAXABLE_INCOME,
        "16": A_TAX, "18": A_TAX, "22": A_TAX, "24": A_TAX,
        "25a": A_TOTAL_PAYMENTS, "25d": A_TOTAL_PAYMENTS, "33": A_TOTAL_PAYMENTS,
        "37": max(0, A_TAX - A_TOTAL_PAYMENTS),
    },
    "sched_1": {"3": 48000, "10": 48000},
    "sched_c": {
        "1": 50000, "3": 50000, "5": 50000, "7": 50000,
        "8": 2000, "28": 2000, "29": 48000, "31": 48000,
    },
    "sched_a": {
        "2": 78800, "3": 5910, "5a": 3000, "5d": 3000, "5e": 3000,
        "7": 3000, "17": 3000,
    },
    "sched_b": {"2": 500, "4": 500, "6": 300},
    "sched_2": {},
    "sched_3": {},
}
# cross_form refs that MUST evaluate to PASS (target form present in this stack).
A_CROSS_FORM_PASS = {
    ("sched_c", "31 == sched_1.3"),
    ("f1040", "8 == sched_1.10"),
    ("f1040", "10 == sched_1.26"),
    ("f1040", "17 == sched_2.3"),
    ("f1040", "20 == sched_3.8"),
    ("f1040", "23 == sched_2.21"),
    ("f1040", "31 == sched_3.15"),
    ("sched_a", "2 == f1040.11"),
    ("sched_a", "17 == f1040.12"),
    ("sched_b", "4 == f1040.2b"),
    ("sched_b", "6 == f1040.3b"),
    ("sched_3", "8 == f1040.20"),
    ("sched_3", "15 == f1040.31"),
}

# ── Scenario B — nonresident alien, 2022 Form 1040-NR stack ──────────────────
# F-1 student, self-employment 20,000 (Sched C -> Sched 1 -> 1040-NR line 8).
# 2022 ships no sched 2/3/a/b packs, so 1040-NR's refs to those legitimately
# SKIP (their amounts are zero, so no caution).
B_FORMS = {
    "f1040nr": "formpacks/federal/2022/f1040nr/pack.yaml",
    "f8843": "formpacks/federal/2022/f8843/pack.yaml",
    "sched_oi": "formpacks/federal/2022/sched_oi/pack.yaml",
    "sched_1": "formpacks/federal/2022/sched_1/pack.yaml",
    "sched_c": "formpacks/federal/2022/sched_c/pack.yaml",
}
# Line 16 (tax) is the calc engine's tax-table lookup for taxable income 20,000
# (single, 2022) — NOT a hand-picked placeholder — so the 1040-NR stack also
# exercises the no-LLM-arithmetic recompute (B_INDEPENDENT below). Lines 18/22/24
# follow line 16 (17/21/23 are zero) and 37 == 24 - 33 with payments zero, so the
# filer owes the full tax.
B_TAXABLE_INCOME = 20000
B_TAX = tax_from_taxable_income(B_TAXABLE_INCOME, "single", year=2022).tax
B_MONEY = {
    "f1040nr": {
        "8": 20000, "9": 20000, "11": 20000, "15": B_TAXABLE_INCOME,
        "16": B_TAX, "18": B_TAX, "22": B_TAX, "24": B_TAX, "37": B_TAX,
    },
    "sched_1": {"3": 20000, "10": 20000},
    "sched_c": {"1": 20000, "3": 20000, "5": 20000, "7": 20000, "29": 20000, "31": 20000},
    "f8843": {},
    "sched_oi": {},
}
B_CROSS_FORM_PASS = {
    ("sched_c", "31 == sched_1.3"),
    ("f1040nr", "8 == sched_1.10"),
}

# Independent-recompute set per scenario, keyed form_key -> {line: expected}.
# Both scenarios' line 16 is a real tax-table lookup; verify_filing(independent=)
# re-derives it from the versioned tables and the recompute section must PASS —
# the multi-form half of the no-LLM-arithmetic guarantee, exercised on BOTH the
# resident 1040 and the nonresident 1040-NR stack.
A_INDEPENDENT = {"f1040": {"16": A_TAX}}
B_INDEPENDENT = {"f1040nr": {"16": B_TAX}}

SCENARIOS = {
    "A_resident_1040_2023": (A_FORMS, A_MONEY, A_CROSS_FORM_PASS, A_INDEPENDENT),
    "B_nra_1040nr_2022": (B_FORMS, B_MONEY, B_CROSS_FORM_PASS, B_INDEPENDENT),
}


def _build_values(pack: FormPack, money: dict[str, int]) -> dict[str, object]:
    """Checkbox + text scaffolding from synthetic_values; money from the chain.

    Synthetic money values are distinct-per-line and would break relations, so
    they are dropped: only the nonzero chain lines are filled (blank reads as 0
    in the relation/cross-form math). Identity lines are pinned to shared
    constants so the cross-form identity check sees one taxpayer.
    """
    money_lines = {pf.line for pf in pack.fields if pf.type == "money"}
    present = {pf.line for pf in pack.fields}
    values: dict[str, object] = {
        line: val for line, val in synthetic_values(pack).items() if line not in money_lines
    }
    for line in list(values):
        if line.endswith((".apt", ".foreign_country", ".foreign_province", ".foreign_postal_code")) or line.startswith("business_address"):
            del values[line]
    for line, const in IDENTITY_CONSTANTS.items():
        if line in present:
            values[line] = const
    for line, amount in money.items():
        if amount:
            values[line] = amount
    return values


@pytest.mark.network
@pytest.mark.parametrize("scenario", sorted(SCENARIOS), ids=lambda s: s)
def test_filing_verifies_clean(scenario: str, tmp_path: Path):
    forms, money, expected_pass, independent = SCENARIOS[scenario]
    items: list[FilingItem] = []
    for key, rel_pack in forms.items():
        pack = load_pack(REPO_ROOT / rel_pack)
        try:
            blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
        except OfflineFetchError as exc:
            pytest.skip(f"cache empty and network unreachable: {exc}")
        filled = tmp_path / f"{key}.pdf"
        fill_form(pack, _build_values(pack, money.get(key, {})), blank, filled)
        items.append(FilingItem(form_key=key, pack=pack, pdf_path=filled))

    report = verify_filing(items, independent=independent)

    def _fails(section):
        return [c for c in (section or []) if c.status == "FAIL"]

    failures = {
        name: [c.detail for c in _fails(getattr(report, name))]
        for name in ("assertions", "relations", "recompute", "clipping", "checkboxes", "identity", "cross_form")
    }
    assert report.ok, "verify_filing reported failures:\n" + "\n".join(
        f"[{name}] {detail}" for name, details in failures.items() for detail in details
    )

    # Prove the cross-form chains actually fired (PASS), not vacuously SKIPPED.
    passed = {(c.form_key, c.relation) for c in report.cross_form if c.status == "PASS"}
    missing = expected_pass - passed
    assert not missing, (
        f"these cross_form chains did not evaluate to PASS (skipped or absent): {sorted(missing)}\n"
        f"PASS were: {sorted(passed)}"
    )

    # The no-LLM-arithmetic guardrail: when a recompute set is supplied (scenario
    # A's f1040 line 16 tax-table lookup), the recompute section must PASS — the
    # filled tax came from calc over the versioned tables, not from mental math.
    if independent is not None:
        expected_lines = {f"{fk}: {line}" for fk, lines in independent.items() for line in lines}
        recompute_lines = {c.line for c in report.recompute if c.status == "PASS"}
        assert expected_lines <= recompute_lines, (
            f"independent recompute did not PASS for {sorted(expected_lines - recompute_lines)} "
            f"— PASS lines were {sorted(recompute_lines)}"
        )
    else:
        assert not report.recompute, "no recompute set was supplied; the section must be empty"
