"""Phase J JR1: Form 1099-R box 7 distribution codes — the per-revision Table 1 transcription, the
combination rules, and the semantic checks extract_document runs. Hypothetical demo readings only."""
from __future__ import annotations

import pytest

from taxfill_core.distribution_codes import codes_for, interpret, parse_box7, validate
from taxfill_core.extract import extract_document

# Table 1's "Used with code" column, transcribed per revision 2026-09-27 (i1099r 2019/2023/2024/2025/2026).
GOLDEN_USED_WITH = {2019: {'1': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '2': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '3': ['D'],
        '4': ['8', 'A', 'B', 'D', 'G', 'H', 'K', 'L', 'M', 'P'],
        '5': [],
        '6': ['W'],
        '7': ['A', 'B', 'D', 'K', 'L', 'M'],
        '8': ['1', '2', '4', 'B', 'J', 'K'],
        '9': [],
        'A': ['4', '7'],
        'B': ['1', '2', '4', '7', '8', 'G', 'L', 'M', 'P', 'U'],
        'C': ['D'],
        'D': ['1', '2', '3', '4', '7', 'C'],
        'E': [],
        'F': [],
        'G': ['4', 'B', 'K'],
        'H': ['4'],
        'J': ['8', 'P'],
        'K': ['1', '2', '4', '7', '8', 'G'],
        'L': ['1', '2', '4', '7', 'B'],
        'M': ['1', '2', '4', '7', 'B'],
        'N': [],
        'P': ['1', '2', '4', 'B', 'J'],
        'Q': [],
        'R': [],
        'S': [],
        'T': [],
        'U': ['B'],
        'W': ['6']},
 2023: {'1': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '2': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '3': ['D'],
        '4': ['8', 'A', 'B', 'D', 'G', 'H', 'K', 'L', 'M', 'P'],
        '5': [],
        '6': ['W'],
        '7': ['A', 'B', 'D', 'K', 'L', 'M'],
        '8': ['1', '2', '4', 'B', 'J', 'K'],
        '9': [],
        'A': ['4', '7'],
        'B': ['1', '2', '4', '7', '8', 'G', 'L', 'M', 'P', 'U'],
        'C': ['D'],
        'D': ['1', '2', '3', '4', '7', 'C'],
        'E': [],
        'F': [],
        'G': ['4', 'B', 'K'],
        'H': ['4'],
        'J': ['8', 'P'],
        'K': ['1', '2', '4', '7', '8', 'G'],
        'L': ['1', '2', '4', '7', 'B'],
        'M': ['1', '2', '4', '7', 'B'],
        'N': [],
        'P': ['1', '2', '4', 'B', 'J'],
        'Q': [],
        'R': [],
        'S': [],
        'T': [],
        'U': ['B'],
        'W': ['6']},
 2024: {'1': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '2': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '3': ['D'],
        '4': ['8', 'A', 'B', 'D', 'G', 'H', 'K', 'L', 'M', 'P'],
        '5': [],
        '6': ['W'],
        '7': ['A', 'B', 'D', 'K', 'L', 'M'],
        '8': ['1', '2', '4', 'B', 'J', 'K'],
        '9': [],
        'A': ['4', '7'],
        'B': ['1', '2', '4', '7', '8', 'G', 'L', 'M', 'P', 'U'],
        'C': ['D'],
        'D': ['1', '2', '3', '4', '7', 'C'],
        'E': [],
        'F': [],
        'G': ['4', 'B', 'K'],
        'H': ['4'],
        'J': ['8', 'P'],
        'K': ['1', '2', '4', '7', '8', 'G'],
        'L': ['1', '2', '4', '7', 'B'],
        'M': ['1', '2', '4', '7', 'B'],
        'N': [],
        'P': ['1', '2', '4', 'B', 'J'],
        'Q': [],
        'R': [],
        'S': [],
        'T': [],
        'U': ['B'],
        'W': ['6']},
 2025: {'1': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '2': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '3': ['D'],
        '4': ['8', 'A', 'B', 'D', 'G', 'H', 'K', 'L', 'M', 'P', 'Y'],
        '5': [],
        '6': ['W'],
        '7': ['A', 'B', 'D', 'K', 'L', 'M', 'Y'],
        '8': ['1', '2', '4', 'B', 'J', 'K'],
        '9': [],
        'A': ['4', '7'],
        'B': ['1', '2', '4', '7', '8', 'G', 'L', 'M', 'P', 'U'],
        'C': ['D'],
        'D': ['1', '2', '3', '4', '7', 'C'],
        'E': [],
        'F': [],
        'G': ['4', 'B', 'K'],
        'H': ['4'],
        'J': ['8', 'P', 'S'],
        'K': ['1', '2', '4', '7', '8', 'G', 'Y'],
        'L': ['1', '2', '4', '7', 'B'],
        'M': ['1', '2', '4', '7', 'B'],
        'N': [],
        'P': ['1', '2', '4', 'B', 'J'],
        'Q': [],
        'R': [],
        'S': ['J'],
        'T': [],
        'U': ['B'],
        'W': ['6'],
        'Y': ['4', '7', 'K']},
 2026: {'1': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '2': ['8', 'B', 'D', 'K', 'L', 'M', 'P'],
        '3': ['D'],
        '4': ['8', 'A', 'B', 'D', 'G', 'H', 'K', 'L', 'M', 'P', 'Y'],
        '5': [],
        '6': ['W'],
        '7': ['A', 'B', 'D', 'K', 'L', 'M', 'Y'],
        '8': ['1', '2', '4', 'B', 'J', 'K'],
        '9': [],
        'A': ['4', '7'],
        'B': ['1', '2', '4', '7', '8', 'G', 'L', 'M', 'P', 'U'],
        'C': ['D'],
        'D': ['1', '2', '3', '4', '7', 'C'],
        'E': [],
        'F': [],
        'G': ['4', 'B', 'K'],
        'H': ['4'],
        'J': ['8', 'P', 'S'],
        'K': ['1', '2', '4', '7', '8', 'G', 'Y'],
        'L': ['1', '2', '4', '7', 'B'],
        'M': ['1', '2', '4', '7', 'B'],
        'N': [],
        'P': ['1', '2', '4', 'B', 'J'],
        'Q': [],
        'R': [],
        'S': ['J'],
        'T': [],
        'U': ['B'],
        'W': ['6'],
        'Y': ['4', '7', 'K']}}


@pytest.mark.parametrize("revision", sorted(GOLDEN_USED_WITH))
def test_jr1_the_table_matches_the_transcription_of_each_revision(revision: int):
    table = codes_for(revision)
    assert sorted(table) == sorted(GOLDEN_USED_WITH[revision])
    for code, used in GOLDEN_USED_WITH[revision].items():
        assert sorted(table[code]["used_with"]) == used, (revision, code)
        for other in used:                                     # the relation is symmetric
            assert code in table[other]["used_with"], (revision, code, other)


def test_jr1_the_combination_rules():
    def errors(raw, year=2026):
        return [f.rule_id for f in validate(parse_box7(raw), year) if f.severity == "error"]
    assert "V1" in errors("NQ7")                               # "a maximum of two alphanumeric codes"
    assert errors("7 1") == ["V2"]                             # only 8 and 1, 8 and 2, 8 and 4
    assert errors("8 1") == []
    assert errors("Q+B") == ["V4"]                             # "Do not combine code Q or T with any other codes"
    assert errors("Y") == ["V5"]                               # Y needs 4, 7 or K
    assert errors("7Y") == []


def test_jr1_codes_follow_the_revision_of_the_tax_year():
    assert [f.rule_id for f in validate(["Y", "7"], 2024)] == ["V0"]   # Y is new in 2025
    assert validate(["S", "J"], 2025) == [] and validate(["S", "J"], 2026) == []
    assert [f.rule_id for f in validate(["S", "J"], 2024)] == ["V3"]
    assert interpret("N", 2025).meanings[0].title == "Recharacterized IRA contribution made for 2025."
    assert interpret("R", 2025).meanings[0].title == "Recharacterized IRA contribution made for 2024 or a previous year."
    assert interpret("R", 2023).meanings[0].title == "Recharacterized IRA contribution made for 2022."
    assert interpret("P", 2021).revision == 2019 and interpret("P", 2021).meanings[0].title.endswith("taxable in 2020.")


def _read(fields, year=2026):
    return extract_document("documents/1099r.pdf", "1099-R", {"recipient_tin": "123456789", **fields}, tax_year=year)


def test_jr1_an_n_code_with_a_taxable_amount_is_an_error_finding():
    r = _read({"1": "6500", "2a": "500", "7a": "N"})
    assert [f.rule_id for f in r.findings if f.severity == "error"] == ["V6"]
    assert {f.key: f for f in r.fields}["7"].status == "ok"      # a payer error is a real reading
    assert "request a CORRECTED Form 1099-R" in r.findings[0].message
    assert "1 findings (1 errors)" in r.caveat
    assert r.interpretation.meanings[0].title == "Recharacterized IRA contribution made for 2026."


def test_jr1_the_box_rules():
    def ids(r):
        return sorted(f.rule_id for f in r.findings)
    assert "V7" in ids(_read({"1": "5000", "2a": "0", "7a": "R", "7b": "X"}))
    assert "V13" in ids(_read({"1": "1000", "2a": "2000", "7a": "7"}))
    assert "V14" in ids(_read({"1": "1000", "7a": "8", "7d": "40"}))
    assert "V9" in ids(_read({"1": "10000", "2a": "10000", "7a": "7", "7b": "X", "2b_not_determined": "X"}))
    h = _read({"1": "8000", "2a": "8000", "7a": "H"})
    assert any(f.rule_id == "V10" and f.severity == "error" for f in h.findings)
    g = _read({"1": "8000", "2a": "8000", "7a": "G"})
    assert any(f.rule_id == "V10" and f.severity == "warning" for f in g.findings)
    j = _read({"1": "3000", "2a": "400", "7a": "J", "7b": "X"}, year=2024)
    assert any(f.rule_id == "V7" and f.severity == "error" for f in j.findings)
    s = _read({"1": "3000", "2a": "3000", "7a": "S"})
    assert any(f.rule_id == "V12" and "25%" in f.message for f in s.findings)
    assert _read({"1": "3000", "2a": "3000", "7a": "7"}).findings == []


def test_jr1_form_5498_box_4_is_counted_once():
    r = extract_document("documents/5498.pdf", "5498", {"participant_tin": "123456789", "5": "12000", "4": "6500"})
    assert [(f.rule_id, f.severity) for f in r.findings] == [("V15", "info")]
    assert "count the contribution ONCE" in r.findings[0].message
