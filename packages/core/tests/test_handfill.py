"""Hand-fill worksheet engine tests (print-only forms — C3 fallback).

Print-only state forms (no AcroForm widgets, no XFA — e.g. HI N-11 2023) can't be
filled; instead the engine turns a line manifest + confirmed inputs into a
line->value worksheet the filer transcribes onto the printed blank. These tests pin
the compute engine (shared relation grammar), the entered/computed/blank sourcing,
and schema validation. Synthetic packs only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from taxfill_core.handfill import Worksheet, hand_fill_worksheet, load_hand_fill_pack
from taxfill_core.schemas.handfill import HandFillPack
from taxfill_core.verify import evaluate_expression

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDFILL_PACKS = sorted(REPO_ROOT.glob("formpacks/**/handfill.yaml"))
_LINE_ID_RE = re.compile(r"^(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*)(?:\.(?:[0-9]+[a-z]?|[a-z][a-z0-9_]*))*$")


def _pack(lines: list[dict]) -> HandFillPack:
    return HandFillPack.model_validate(
        {
            "form": "TEST",
            "jurisdiction": "states/zz",
            "tax_year": 2023,
            "source_url": "https://example.gov/blank.pdf",
            "pdf_sha256": "a" * 64,
            "lines": lines,
        }
    )


def _by_line(ws: Worksheet) -> dict[str, tuple[str, str]]:
    return {ln.line: (ln.value, ln.source) for ln in ws.lines}


# ── the shared expression evaluator (also used by the verifier) ────────────


def test_evaluate_expression_arithmetic_and_blank_is_zero():
    v = {"1": 50000, "2": 1000, "3": 3000}
    assert evaluate_expression("1 + 2 - 3", v) == 48000
    assert evaluate_expression("max(0, 3 - 1)", v) == 0  # 3-1 = -47000 -> floored 0
    assert evaluate_expression("missing_line + 5", v) == 5  # blank ref counts as 0
    assert evaluate_expression("sum(1a..1c)", {"1a": 10, "1b": 20, "1c": 30}) == 60


def test_evaluate_expression_rejects_malformed():
    with pytest.raises(ValueError):
        evaluate_expression("1 + + 2", {"1": 1})
    with pytest.raises(ValueError):
        evaluate_expression("1 == 2", {"1": 1, "2": 2})  # a single expr, not a relation


# ── the worksheet builder ──────────────────────────────────────────────────


def test_worksheet_computes_chain_and_floors_at_zero():
    ws = hand_fill_worksheet(
        _pack(
            [
                {"line": "1", "label": "Federal AGI", "type": "money"},
                {"line": "2", "label": "Additions", "type": "money"},
                {"line": "3", "label": "Subtractions", "type": "money"},
                {"line": "4", "label": "State AGI", "type": "money", "compute": "1 + 2 - 3"},
                {"line": "5", "label": "Deduction", "type": "money"},
                {"line": "6", "label": "Taxable income", "type": "money", "compute": "max(0, 4 - 5)"},
            ]
        ),
        {"1": 50000, "2": 1000, "3": 3000, "5": 60000},
    )
    by = _by_line(ws)
    assert by["4"] == ("48,000", "computed")  # 50000 + 1000 - 3000
    assert by["6"] == ("0", "computed")  # max(0, 48000 - 60000)
    assert by["1"] == ("50,000", "entered")
    assert by["3"] == ("3,000", "entered")


def test_worksheet_blank_entered_text_and_checkbox():
    ws = hand_fill_worksheet(
        _pack(
            [
                {"line": "name", "label": "Your name", "type": "text"},
                {"line": "donate", "label": "Checkoff", "type": "checkbox"},
                {"line": "decline", "label": "Other checkoff", "type": "checkbox"},
                {"line": "unasked", "label": "Unanswered checkoff", "type": "checkbox"},
                {"line": "9", "label": "Unfilled money line", "type": "money"},
                {"line": "10", "label": "Reserved compute over blanks", "type": "money", "compute": "9 + 0"},
            ]
        ),
        {"name": "ALICE EXAMPLE", "donate": True, "decline": "no"},
    )
    by = _by_line(ws)
    assert by["name"] == ("ALICE EXAMPLE", "entered")
    assert by["donate"] == ("X", "entered")
    assert by["decline"] == ("", "blank")  # 'no' is an empty box, NOT a tick (P-014)
    assert by["unasked"] == ("", "blank")
    assert by["9"] == ("", "blank")
    assert by["10"] == ("0", "computed")  # 9 is blank(0) -> computes 0


# ── checkbox answers (pitfall P-014) ───────────────────────────────────────
#
# Until 2026-09 the checkbox branch shared the text branch's "non-empty?" test, so
# 'no', False and '0' all came back as a ticked 'X' — on the FEDERAL FBAR packs (8
# checkbox lines a year) and every print-only state pack. The answer is now read with
# the AcroForm filler's own yes/no vocabulary, and anything else is refused.


def _checkbox_pack() -> HandFillPack:
    return _pack([{"line": "donate", "label": "Checkoff", "type": "checkbox"}])


@pytest.mark.parametrize(
    "answer", ["yes", "YES", " y ", "true", "on", "x", "X", "1", "checked", True, 1]
)
def test_checkbox_yes_answer_ticks_the_box(answer):
    ws = hand_fill_worksheet(_checkbox_pack(), {"donate": answer})
    assert _by_line(ws)["donate"] == ("X", "entered")


@pytest.mark.parametrize(
    "answer", ["no", "No", " n ", "false", "FALSE", "off", "0", "unchecked", "", "   ", False, 0, None]
)
def test_checkbox_no_answer_leaves_the_box_empty(answer):
    """P-014: until 2026-09 every non-empty one of these rendered 'X'."""
    ws = hand_fill_worksheet(_checkbox_pack(), {"donate": answer})
    assert _by_line(ws)["donate"] == ("", "blank")


@pytest.mark.parametrize("answer", ["maybe", "yes please", "2", 2, -1, 1.0, 0.5, ["yes"]])
def test_checkbox_unrecognised_answer_raises_naming_the_line(answer):
    with pytest.raises(ValueError) as exc:
        hand_fill_worksheet(_checkbox_pack(), {"donate": answer})
    msg = str(exc.value)
    assert "line donate ('Checkoff') is a checkbox" in msg
    assert "yes|no" in msg and "Omit the line to leave the box blank" in msg


def test_checkbox_error_redacts_the_answer():
    # redact() masks identifier-shaped content only (SSN/ITIN-shaped ids, 6+ digit
    # runs), so a short word comes back exactly as typed — the filer can see what was
    # refused — while an id pasted into the wrong line never leaves the process.
    with pytest.raises(ValueError, match=r"got 'maybe'\."):
        hand_fill_worksheet(_checkbox_pack(), {"donate": "maybe"})
    with pytest.raises(ValueError) as exc:
        hand_fill_worksheet(_checkbox_pack(), {"donate": "123-45-6789"})
    assert "[redacted-id]" in str(exc.value) and "6789" not in str(exc.value)
    with pytest.raises(ValueError) as exc:
        hand_fill_worksheet(_checkbox_pack(), {"donate": 12345678})
    assert "[redacted-number]" in str(exc.value) and "12345678" not in str(exc.value)


def test_checkbox_vocabulary_matches_the_acroform_filler():
    """One answer, one meaning, whichever pipeline the form goes through.

    handfill keeps its own copy of the filler's word sets (it never imports the
    filler); this pins the copy — the sets AND the bool / 0-1 / refuse handling —
    so neither can drift from the other.
    """
    from taxfill_core import filler, handfill
    from taxfill_core.schemas.formpack import PackField
    from taxfill_core.schemas.handfill import HandFillLine

    assert handfill._CHECKBOX_ON_WORDS == filler._CHECKBOX_ON_WORDS
    assert handfill._CHECKBOX_OFF_WORDS == filler._CHECKBOX_OFF_WORDS

    pf = PackField(line="donate", field="c1_1[0]", type="checkbox", on_state="/1")
    ln = HandFillLine(line="donate", label="Checkoff", type="checkbox")

    def outcome(fn, *args):
        try:
            return fn(*args)
        except ValueError:
            return "refused"

    # None is excluded on purpose: the filler refuses it, the worksheet treats it as an
    # omitted line (as it does for money and text) — neither ticks the box.
    answers = sorted(filler._CHECKBOX_ON_WORDS | filler._CHECKBOX_OFF_WORDS) + [
        "YES", " No ", "maybe", "2", True, False, 0, 1, 2, -1, 1.0, 0.0,
    ]
    for answer in answers:
        by_filler = outcome(filler._checkbox_state, pf, answer)
        by_filler = {"/1": True, "/Off": False}.get(by_filler, by_filler)
        assert outcome(handfill._checkbox_checked, ln, answer) == by_filler, answer


FBAR_PACKS = [p for p in HANDFILL_PACKS if p.parts[-2] == "fincen114"]


@pytest.mark.parametrize("path", FBAR_PACKS, ids=lambda p: p.parts[-3])
def test_fbar_no_answer_leaves_every_box_empty(path):
    """The FEDERAL case: FinCEN Form 114's yes/no lines (third-party filer, the
    per-account 'amount unknown' boxes, the item-44 e-signature) answered 'no'
    must not come back ticked."""
    pack = load_hand_fill_pack(path)
    boxes = [ln.line for ln in pack.lines if ln.type == "checkbox"]
    assert boxes, f"{path} has no checkbox lines — this test would prove nothing"
    by = _by_line(hand_fill_worksheet(pack, {"third_party_filing": "no", "account1_15a": False}))
    assert by["third_party_filing"] == ("", "blank")
    assert by["account1_15a"] == ("", "blank")
    # Every one of the pack's checkbox lines answered 'no' comes back empty.
    by = _by_line(hand_fill_worksheet(pack, {line: "no" for line in boxes}))
    assert all(by[line] == ("", "blank") for line in boxes), {line: by[line] for line in boxes}
    by = _by_line(hand_fill_worksheet(pack, {"third_party_filing": "yes"}))
    assert by["third_party_filing"] == ("X", "entered")


def test_money_line_error_redacts_the_answer():
    """P-014 companion: the money-line error goes through redact() like the checkbox
    error, so an SSN typed into an amount is never echoed in clear."""
    pack = load_hand_fill_pack(FBAR_PACKS[0])
    money = next(ln.line for ln in pack.lines if ln.type == "money")
    with pytest.raises(ValueError) as exc:
        hand_fill_worksheet(pack, {money: "123-45-6789"})
    assert "123-45-6789" not in str(exc.value)
    assert "[redacted-id]" in str(exc.value)


def test_fbar_packs_are_discovered():
    assert {p.parts[-3] for p in FBAR_PACKS} >= {"2023", "2024", "2025"}


@pytest.mark.parametrize(
    "path", HANDFILL_PACKS or [None], ids=lambda p: f"{p.parts[-4]}-{p.parts[-3]}-{p.parts[-2]}" if p else "none"
)
def test_every_shipped_checkbox_line_honours_no(path):
    """Pack-invariant sweep: every checkbox line of every shipped hand-fill pack
    (FBAR + the CT/NM/HI/SC returns) answered no is empty, answered yes is 'X'."""
    if path is None:
        pytest.skip("no shipped hand-fill packs")
    pack = load_hand_fill_pack(path)
    boxes = [ln.line for ln in pack.lines if ln.type == "checkbox"]
    if not boxes:
        pytest.skip(f"{path} has no checkbox lines")
    for no in ("no", False, "0", "off"):
        by = _by_line(hand_fill_worksheet(pack, {line: no for line in boxes}))
        ticked = [line for line in boxes if by[line] != ("", "blank")]
        assert not ticked, f"answered {no!r} but ticked: {ticked}"
    by = _by_line(hand_fill_worksheet(pack, {line: "yes" for line in boxes}))
    assert all(by[line] == ("X", "entered") for line in boxes)


# ── money rendering ────────────────────────────────────────────────────────


def test_money_zero_never_renders_as_negative_zero():
    """A small negative that rounds to 0, and 0 times a negative, are Decimal('-0') —
    which formatted as '-0' until 2026-09. Genuine negatives keep their sign."""
    ws = hand_fill_worksheet(
        _pack(
            [
                {"line": "1", "label": "Payments", "type": "money"},
                {"line": "2", "label": "Tax", "type": "money"},
                {"line": "3", "label": "Net, rounds to zero", "type": "money", "compute": "1 - 2"},
                {"line": "4", "label": "Rate base", "type": "money"},
                {"line": "5", "label": "Adjustment", "type": "money"},
                {"line": "6", "label": "Zero times a negative", "type": "money", "compute": "4 * 5"},
                {"line": "7", "label": "Entered small negative", "type": "money"},
                {"line": "8", "label": "Entered -0", "type": "money"},
                {"line": "9", "label": "Half rounds away from zero", "type": "money"},
                {"line": "10", "label": "Real negative", "type": "money"},
            ]
        ),
        {"1": "0.2", "2": "0.6", "4": 0, "5": -5, "7": "-0.4", "8": "-0", "9": "-0.5", "10": "-1234.5"},
    )
    by = _by_line(ws)
    assert by["3"] == ("0", "computed")  # 0.2 - 0.6 = -0.4 -> -0 -> '0'
    assert by["6"] == ("0", "computed")  # 0 * -5 = Decimal('-0')
    assert by["7"] == ("0", "entered")
    assert by["8"] == ("0", "entered")
    assert by["9"] == ("-1", "entered")  # ROUND_HALF_UP: -0.5 -> -1, not a zero
    assert by["10"] == ("-1,235", "entered")


def test_worksheet_preserves_printed_order_and_metadata():
    pack = _pack([{"line": "1", "label": "L1", "type": "money"}, {"line": "2", "label": "L2", "type": "money"}])
    ws = hand_fill_worksheet(pack, {"1": 5})
    assert [ln.line for ln in ws.lines] == ["1", "2"]
    assert ws.form == "TEST" and ws.tax_year == 2023
    assert ws.print_url == "https://example.gov/blank.pdf"
    assert "no fillable fields" in ws.instructions.lower()


def test_worksheet_no_values_all_blank_or_zero():
    ws = hand_fill_worksheet(_pack([{"line": "1", "label": "L1", "type": "money"},
                                    {"line": "2", "label": "L2", "type": "money", "compute": "1 * 2"}]))
    by = _by_line(ws)
    assert by["1"] == ("", "blank")
    assert by["2"] == ("0", "computed")  # 1 is blank(0) -> 0*2 = 0


# ── schema validation ────────────────────────────────────────────────────────


def test_pack_requires_at_least_one_line():
    with pytest.raises(Exception):
        _pack([])


def test_pack_render_mode_is_hand_fill_and_roundtrips(tmp_path):
    pack = _pack([{"line": "1", "label": "L1", "type": "money"}])
    assert pack.render_mode == "hand_fill"
    p = tmp_path / "handfill.yaml"
    import yaml
    p.write_text(yaml.safe_dump(pack.model_dump()), encoding="utf-8")
    loaded = load_hand_fill_pack(p)
    assert loaded.form == "TEST" and loaded.lines[0].label == "L1"


# ── shipped print-only packs (e.g. HI N-11) ────────────────────────────────


@pytest.mark.parametrize(
    "path", HANDFILL_PACKS or [None], ids=lambda p: f"{p.parts[-4]}-{p.parts[-2]}" if p else "none"
)
def test_shipped_handfill_packs_validate_and_build(path):
    if path is None:
        pytest.skip("no shipped hand-fill packs")
    pack = load_hand_fill_pack(path)
    assert pack.render_mode == "hand_fill"
    # Hand-fill packs began as the C3 fallback for print-only STATE forms, but the
    # class is broader than that: FinCEN Form 114 (the FBAR) is a FEDERAL filing
    # with no fillable PDF at all — it is e-file only through the BSA E-Filing
    # System and irs.gov states a printed Form 114 is not accepted — so it ships
    # as formpacks/federal/<year>/fincen114/handfill.yaml.
    assert pack.jurisdiction == "federal" or pack.jurisdiction.startswith("states/")
    assert pack.pdf_sha256 != "..." and len(pack.pdf_sha256) == 64
    bad = [ln.line for ln in pack.lines if not _LINE_ID_RE.fullmatch(ln.line)]
    assert not bad, f"line ids violate the grammar: {bad}"
    # building the worksheet evaluates EVERY compute expression — a malformed one raises here
    ws = hand_fill_worksheet(pack, {})
    assert len(ws.lines) == len(pack.lines)


def test_hi_n11_income_chain_computes():
    """End-to-end on the shipped HI N-11 pack: the Hawaii-AGI chain derives correctly."""
    hi = [p for p in HANDFILL_PACKS if p.parts[-4] == "hi"]
    if not hi:
        pytest.skip("HI N-11 pack not present")
    pack = load_hand_fill_pack(hi[0])
    ws = hand_fill_worksheet(pack, {"7": 80000, "8": 2000, "13": 5000, "14": 3000})
    by = {ln.line: (ln.value, ln.source) for ln in ws.lines}
    assert by["11"] == ("2,000", "computed")   # 8 + 9 + 10 = 2000
    assert by["12"] == ("82,000", "computed")  # 7 + 11
    assert by["19"] == ("8,000", "computed")   # 13 + 14 + ... = 8000
    assert by["20"] == ("74,000", "computed")  # 12 - 19
