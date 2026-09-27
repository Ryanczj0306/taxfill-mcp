"""Form-line registry, helper and guard — Phase J JF6a, pitfall P-015.

A printed line number is a per-year fact, and engine text that types one as a
literal serves every year the same string. Two of the five keys this tranche
records contradict a literal the engine prints today: the Form 1040-NR
treaty-exempt line is 22 / 1c / 1k by year (the engine always says 1k), and
Form 8959's withholding reconciliation is Part V on every face 2019-2026 (the
engine says Part IV). A third has no literal that is right for every year:
Schedule 1's other-income line, where JF1a sends a resident's treaty income, is
"8" on the 2019/2020 faces and "8z" from 2021. So the numbers live in each
federal pack's top-level ``form_lines`` block and render through
``knowledge.form_line``.

Four layers here:

* the acceptance values, pinned per year against the faces they were read off;
* the schema's refusals (draft vs final URLs, absent-by-face entries, ...);
* the GUARD: a static scan of the strings in calc.py / estimate.py / intake.py /
  server.py for the ROADMAP's line-literal regex, plus the same prefixes before
  a line number moved out of the string (a field that is not form_line(...)).
  Today's hits sit in a frozen debt list that JF6b / JF6c shrink to zero. A new
  one fails the guard, and so does a debt row that no longer matches the source
  (the list is self-clearing, like the P-007 tables), so it can only ever shrink;
* the FACE CHECK: each entry's quote AND its designator against the face it
  cites, with offline negative controls on verbatim excerpts and a
  network-marked run over every entry.
"""

from __future__ import annotations

import ast
import itertools
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from taxfill_core.knowledge import (
    FormLineEntry,
    FormLineError,
    KnowledgePack,
    form_line,
    form_line_entry,
    load_knowledge,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
FEDERAL_YEARS = sorted(int(p.stem) for p in (KNOWLEDGE_DIR / "federal").glob("[0-9][0-9][0-9][0-9].yaml"))
DRAFT = " (2026 DRAFT form — re-verify at final)"

# The five keys JF1a / JF3 / JF4 consume, each with the value read off every
# shipped year's face on 2026-09-24 (URLs in the packs).
EXPECTED: dict[str, dict[int, str]] = {
    "sched1.other_income": {2019: "8", 2020: "8", **{y: "8z" for y in range(2021, 2027)}},
    "f1040nr.treaty_exempt": {2019: "22", 2020: "1c", 2021: "1c", **{y: "1k" for y in range(2022, 2027)}},
    "f8959.withholding_part": {y: "V" for y in range(2019, 2027)},
    "f1040.additional_medicare_withholding": {2019: "17", **{y: "25c" for y in range(2020, 2027)}},
    "sched_se.ss_wages": {y: "8a" for y in range(2019, 2027)},
    # JF4 (read 2026-09-27): the prior-year figures the safe harbor asks for — AGI moved to 11a in 2025.
    "f1040.agi": {2019: "8b", **{y: "11" for y in range(2020, 2025)}, 2025: "11a", 2026: "11a"},
    "f1040.total_tax": {2019: "16", **{y: "24" for y in range(2020, 2026)}, 2026: "24a"},
    # JR2a (read 2026-09-27): the IRA distribution lines the statements name.
    "f1040.ira_distributions": {y: "4a" for y in range(2019, 2027)},
    "f1040.ira_taxable": {y: "4b" for y in range(2019, 2027)},
}
READ = {k: "2026-09-27" for k in ("f1040.agi", "f1040.total_tax", "f1040.ira_distributions", "f1040.ira_taxable")}
DRAFT_CREATED = {
    "sched1.other_income": "4/24/26",
    "f1040nr.treaty_exempt": "8/19/26",
    "f8959.withholding_part": "5/27/26",
    "f1040.additional_medicare_withholding": "8/19/26",
    "sched_se.ss_wages": "4/27/26",
    "f1040.agi": "8/19/26",
    "f1040.total_tax": "8/19/26",
    "f1040.ira_distributions": "8/19/26",
    "f1040.ira_taxable": "8/19/26",
}


def _copy_knowledge(tmp_path: Path) -> Path:
    base = tmp_path / "knowledge"
    (base / "federal").mkdir(parents=True)
    for year in FEDERAL_YEARS:
        shutil.copy(KNOWLEDGE_DIR / "federal" / f"{year}.yaml", base / "federal" / f"{year}.yaml")
    return base


def _raw(year: int) -> dict:
    return yaml.safe_load((KNOWLEDGE_DIR / "federal" / f"{year}.yaml").read_text(encoding="utf-8"))


# ══ acceptance: the values, per year ══════════════════════════════════════════


def test_schedule_1_other_income_is_8_before_2021_and_8z_from_2021():
    """P-015: the ROADMAP's pinned acceptance, read off the faces."""
    assert form_line(2020, "sched1.other_income") == "8"
    assert form_line(2019, "sched1.other_income") == "8"
    assert form_line(2021, "sched1.other_income") == "8z"
    assert form_line(2025, "sched1.other_income") == "8z"


@pytest.mark.parametrize("year", FEDERAL_YEARS)
def test_every_shipped_pack_records_the_jf6a_keys(year: int):
    # A new federal pack (2027 at JT6) carries its own block, read off its own
    # faces, before anything renders a line for it.
    recorded = load_knowledge("federal", year).form_lines or {}
    assert set(EXPECTED) <= set(recorded), f"{year}: missing {sorted(set(EXPECTED) - set(recorded))}"


@pytest.mark.parametrize("year", FEDERAL_YEARS)
@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_every_year_records_every_jf6a_key_with_its_face(key: str, year: int):
    assert year in EXPECTED[key], f"{year} is not pinned: read its {key} face and extend EXPECTED"
    entry = form_line_entry(year, key)
    assert entry.line == EXPECTED[key][year], f"{key} {year}"
    assert entry.read == READ.get(key, "2026-09-24")
    if year == 2026:
        assert entry.line_source == f"draft Created {DRAFT_CREATED[key]}"
        assert entry.url.startswith("https://www.irs.gov/pub/irs-dft/") and entry.url.endswith("--dft.pdf")
        assert form_line(year, key) == EXPECTED[key][year] + DRAFT
    else:
        assert entry.line_source == "final"
        assert entry.url.startswith("https://www.irs.gov/pub/irs-prior/") and entry.url.endswith(f"--{year}.pdf")
        assert form_line(year, key) == EXPECTED[key][year]


def test_a_2026_draft_entry_carries_the_draft_suffix():
    """P-015: a line read off an IRS draft never renders as if it were final."""
    assert form_line(2026, "sched1.other_income") == "8z (2026 DRAFT form — re-verify at final)"
    assert form_line(2026, "f1040.additional_medicare_withholding") == "25c (2026 DRAFT form — re-verify at final)"
    entry = form_line_entry(2026, "sched1.other_income")
    assert entry.is_draft and entry.line == "8z"  # the bare designator, for keying data


@pytest.mark.parametrize("year", [2018, 2027, 1990])
def test_an_unknown_year_raises(year: int):
    with pytest.raises(FormLineError, match=f"no form lines for federal tax year {year}"):
        form_line(year, "sched1.other_income")


def test_an_unknown_key_raises_naming_the_key_and_the_face_to_read():
    with pytest.raises(FormLineError) as excinfo:
        form_line(2025, "sched2.not_a_recorded_role")
    msg = str(excinfo.value)
    assert "'sched2.not_a_recorded_role'" in msg and "knowledge/federal/2025.yaml" in msg
    assert "irs-prior/<form>--2025.pdf" in msg and "P-015" in msg
    assert "sched1.other_income" in msg  # lists what IS recorded


def test_the_error_is_a_lookup_error_not_a_value_error():
    # estimate.py wraps whole computations in `except ValueError`; a missing line
    # number must never be swallowed there.
    assert issubclass(FormLineError, LookupError)
    assert not issubclass(FormLineError, ValueError)


def test_a_pack_and_its_year_render_the_same():
    for year in FEDERAL_YEARS:
        pack = load_knowledge("federal", year)
        for key in EXPECTED:
            assert form_line(pack, key) == form_line(year, key)


def test_form_line_rejects_a_bool_or_a_string_year():
    with pytest.raises(TypeError):
        form_line(True, "sched1.other_income")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        form_line("2025", "sched1.other_income")  # type: ignore[arg-type]


def test_the_block_is_top_level_so_the_sources_meta_test_sees_it():
    for year in FEDERAL_YEARS:
        raw = _raw(year)
        assert "form_lines" in raw, year
        assert "form_lines" not in (raw.get("tax") or {}), year


def test_1040nr_treaty_line_is_22_then_1c_then_1k():
    """P-015: the literal the engine prints ("1040-NR line 1k") is wrong for 2019-2021."""
    assert [form_line(y, "f1040nr.treaty_exempt") for y in range(2019, 2026)] == [
        "22", "1c", "1c", "1k", "1k", "1k", "1k",
    ]


def test_8959_withholding_is_part_v_on_every_face():
    """P-015: calc.py's "via Part IV" names the wrong Part in every shipped year."""
    for year in FEDERAL_YEARS:
        entry = form_line_entry(year, "f8959.withholding_part")
        assert entry.line == "V" and entry.printed == "Part V Withholding Reconciliation"


# ══ absent-by-face entries and cache behaviour ════════════════════════════════


def test_an_absent_entry_is_recorded_and_form_line_refuses_it(tmp_path: Path):
    base = _copy_knowledge(tmp_path)
    path = base / "federal" / "2019.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["form_lines"]["f8889.hsa_deduction"] = {
        "line": None,
        "absent": "illustrative: the form has no such line this year",
        "line_source": "final",
        "url": "https://www.irs.gov/pub/irs-prior/f8889--2019.pdf",
        "read": "2026-09-24",
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    entry = form_line_entry(2019, "f8889.hsa_deduction", base_dir=base)
    assert entry.line is None and "no such line" in entry.absent
    with pytest.raises(FormLineError, match="does not exist on the 2019 form: illustrative"):
        form_line(2019, "f8889.hsa_deduction", base_dir=base)


def test_a_pack_without_the_block_raises(tmp_path: Path):
    base = _copy_knowledge(tmp_path)
    path = base / "federal" / "2024.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("form_lines")
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    with pytest.raises(FormLineError, match="has no form_lines block"):
        form_line(2024, "sched1.other_income", base_dir=base)


def test_an_edited_pack_is_re_read_not_served_from_the_cache(tmp_path: Path):
    base = _copy_knowledge(tmp_path)
    assert form_line(2022, "sched_se.ss_wages", base_dir=base) == "8a"
    path = base / "federal" / "2022.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["form_lines"]["sched_se.ss_wages"]["line"] = "18a"
    raw["form_lines"]["sched_se.ss_wages"]["printed"] = "18a illustrative relabel"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    assert form_line(2022, "sched_se.ss_wages", base_dir=base) == "18a"


# ══ the schema's refusals ═════════════════════════════════════════════════════

_FINAL = {
    "line": "8z",
    "line_source": "final",
    "url": "https://www.irs.gov/pub/irs-prior/f1040s1--2025.pdf",
    "read": "2026-09-24",
    "printed": "8z Other income. List type and amount:",
}


@pytest.mark.parametrize(
    "change,match",
    [
        ({"absent": "both set"}, "exactly one of"),
        ({"line": None}, "exactly one of"),
        ({"line": "line 8z", "printed": "line 8z"}, "bare printed designator"),
        ({"printed": "Other income. List type and amount:"}, "show that designator"),
        ({"printed": "8zz Other income"}, "show that designator"),
        ({"line_source": "draft"}, "draft Created"),
        ({"line_source": "draft Created 4/24/26"}, "disagrees with url"),
        ({"url": "https://www.irs.gov/pub/irs-dft/f1040s1--dft.pdf"}, "disagrees with url"),
        ({"url": "https://example.com/f1040s1.pdf"}, "official US government host"),
        ({"read": "9/24/26"}, "ISO date"),
    ],
)
def test_entry_schema_refuses(change: dict, match: str):
    with pytest.raises(ValidationError, match=match):
        FormLineEntry(**{**_FINAL, **change})


def _pack_with(year: int, key: str, entry: dict, *, provisional: bool | None = None) -> dict:
    raw = _raw(year)
    raw["form_lines"] = {key: entry}
    if provisional is False:
        raw.pop("provisional", None)
    return raw


def test_a_final_entry_must_cite_that_years_face():
    wrong_year = {**_FINAL, "url": "https://www.irs.gov/pub/irs-prior/f1040s1--2024.pdf"}
    with pytest.raises(ValidationError, match="cites the 2025 face itself"):
        KnowledgePack.model_validate(_pack_with(2025, "sched1.other_income", wrong_year))
    # irs-pdf serves whichever revision is current, so it names no year: a 2019
    # pack citing it would pass on today's face.
    for year in (2019, 2025):
        moving = {**_FINAL, "url": "https://www.irs.gov/pub/irs-pdf/f1040s1.pdf"}
        with pytest.raises(ValidationError, match="not irs-pdf/<form>.pdf, which moves"):
            KnowledgePack.model_validate(_pack_with(year, "sched1.other_income", moving))
    KnowledgePack.model_validate(_pack_with(2025, "sched1.other_income", dict(_FINAL)))


def test_a_draft_entry_needs_a_provisional_pack():
    draft = {
        **_FINAL,
        "line_source": "draft Created 4/24/26",
        "url": "https://www.irs.gov/pub/irs-dft/f1040s1--dft.pdf",
    }
    KnowledgePack.model_validate(_pack_with(2026, "sched1.other_income", draft))  # provisional: fine
    with pytest.raises(ValidationError, match="filing-grade"):
        KnowledgePack.model_validate(_pack_with(2026, "sched1.other_income", draft, provisional=False))


@pytest.mark.parametrize("key", ["Sched1.other_income", "sched1", "sched1.other income", "sched1.other.income"])
def test_keys_are_form_dot_role(key: str):
    with pytest.raises(ValidationError, match="must be '<form>.<role>'"):
        KnowledgePack.model_validate(_pack_with(2025, key, dict(_FINAL)))


# ══ the guard: no new line literal in engine text (P-015) ═════════════════════

# The ROADMAP's regex, verbatim. A hit is a typed form line number; the fix is to
# render it through form_line(pack, key) from the year's form_lines block.
LINE_LITERAL_RE = re.compile(r"(Schedule [123]|Form 1040(-NR)?|8959|8889|Schedule 1-A)[^\n]{0,15}line \d")
# The same prefix before a line number that is NOT typed into the string: a
# replacement field other than a form_line(...) call (rendered "{}" below), a
# .format() template field, a positional %-format. It catches the literal moved out of the
# string — into a constant, a dict, or a year-branching helper like
# calc._capital_loss_1040_line — which the verbatim regex cannot see. Its window
# is 30, not 15, to reach the IRS's own "Form 1040, 1040-SR, or 1040-NR, line"
# (23 characters from the prefix); at 30 it finds nothing else today.
LINE_FIELD_RE = re.compile(
    LINE_LITERAL_RE.pattern.replace("{0,15}", "{0,30}").removesuffix(r"\d") + r"(\{[^{}]*\}|%[-+ #0-9.]*[sdir])"
)
# Extends a hit to the whole designator ("line 11a", not "line 1") so a debt row
# names the literal a reader will actually find.
_DESIGNATOR_TAIL_RE = re.compile(r"[0-9A-Za-z]*")
# How a form_line(...) field renders in the scan: neither a digit nor a brace, so
# "Schedule 1 line {form_line(year, key)}" matches neither regex.
_FORM_LINE_FIELD = "<form_line>"

GUARDED: dict[str, Path] = {
    "calc.py": REPO_ROOT / "packages" / "core" / "src" / "taxfill_core" / "calc.py",
    "estimate.py": REPO_ROOT / "packages" / "core" / "src" / "taxfill_core" / "estimate.py",
    "intake.py": REPO_ROOT / "packages" / "core" / "src" / "taxfill_core" / "intake.py",
    "server.py": REPO_ROOT / "packages" / "mcp-server" / "src" / "taxfill_mcp" / "server.py",
}


def _is_text(node: ast.AST) -> bool:
    """Whether an expression is (or may be) text built from string literals."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.IfExp):
        return _is_text(node.body) or _is_text(node.orelse)
    if isinstance(node, ast.BoolOp):
        return any(_is_text(v) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_text(node.left) or _is_text(node.right)
    return False


def _is_form_line_call(node: ast.AST) -> bool:
    """``form_line(...)`` or ``knowledge.form_line(...)``: the registry helper, and only it
    (test_form_line_in_the_guarded_modules_is_the_registry_helper keeps the name bound to it)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "form_line"
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "form_line"
        and isinstance(func.value, ast.Name)
        and func.value.id == "knowledge"
    )


class _LiteralScan(ast.NodeVisitor):
    """Every line-literal hit in a module's strings, keyed by enclosing scope.

    Covers plain strings, docstrings (the MCP tool docstrings in server.py are
    text the agent reads) and text BUILT from literals: an f-string (its format
    specs too), a ternary or `or` between strings, a `+` concatenation. Each is
    scanned as every text it can render, so
    f"Schedule 3{', line 10' if y == 2020 else ' line 11'}" hits twice and
    f"Form 1040 line {'25c'}" once. A form_line(...) field renders as
    "<form_line>"; any other field (a name, a subscript, any other call) reads
    as "{}", and "line {}" after a prefix is a hit of its own (LINE_FIELD_RE),
    so a literal hoisted into a constant or a helper still shows. No function
    body and no call's arguments are skipped: a form_lines key is
    '<form>.<role>' with no space, so a real form_line call never matches.

    Known gaps (listed in P-015 and the ROADMAP JF6b notes, not enforced): a
    named %-format ("line %(l)s" % d), a literal split across a join, a letter
    appended after a trusted field (f"line {form_line(y, k)}{'c'}"), a
    capitalised "Line" or a newline before "line", and any prefix outside the
    ROADMAP regex (Schedule D / SE / C / 8812, Forms 8606 / 1116 / 8960).
    """

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.hits: Counter[tuple[str, str]] = Counter()

    def _scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def _renderings(self, node: ast.AST) -> list[str]:
        """The texts an expression can render; any other part reads "{}" and is scanned on its own."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if _is_form_line_call(node):
            self.generic_visit(node)
            return [_FORM_LINE_FIELD]
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append([v.value])
                    continue
                if v.format_spec is not None:  # f"{x:{'...'}}" is text too
                    self.visit(v.format_spec)
                parts.append(self._renderings(v.value))
            return ["".join(p) for p in itertools.product(*parts)]
        if _is_text(node):
            if isinstance(node, ast.IfExp):
                self.visit(node.test)
                return self._renderings(node.body) + self._renderings(node.orelse)
            if isinstance(node, ast.BoolOp):
                return [text for v in node.values for text in self._renderings(v)]
            if isinstance(node, ast.BinOp):
                return [a + b for a in self._renderings(node.left) for b in self._renderings(node.right)]
        self.visit(node)
        return ["{}"]

    def _record(self, node: ast.AST) -> None:
        # A literal counts as often as it appears in ONE rendering (the union of
        # the renderings' multisets), so the text shared by both arms of a
        # ternary is counted once, not once per arm.
        where = ".".join(self.scope) or "<module>"
        seen: Counter[tuple[str, str]] = Counter()
        for text in self._renderings(node):
            here: Counter[tuple[str, str]] = Counter()
            for regex in (LINE_LITERAL_RE, LINE_FIELD_RE):
                for m in regex.finditer(text):
                    tail = _DESIGNATOR_TAIL_RE.match(text, m.end())
                    here[(where, m.group(0) + (tail.group(0) if tail else ""))] += 1
            seen |= here
        self.hits += seen

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self._record(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._record(node)

    def _text_or_walk(self, node: ast.IfExp | ast.BoolOp | ast.BinOp) -> None:
        if _is_text(node):
            self._record(node)
        else:
            self.generic_visit(node)

    visit_IfExp = visit_BoolOp = visit_BinOp = _text_or_walk


def line_literals(module: str, source: str) -> Counter[tuple[str, str, str]]:
    scan = _LiteralScan()
    scan.visit(ast.parse(source))
    return Counter({(module, where, literal): n for (where, literal), n in scan.hits.items()})


def _current_literals() -> Counter[tuple[str, str, str]]:
    total: Counter[tuple[str, str, str]] = Counter()
    for module, path in GUARDED.items():
        total += line_literals(module, path.read_text(encoding="utf-8"))
    return total


def _new_literals(actual: Counter, debt: dict) -> dict:
    return {key: n - debt.get(key, 0) for key, n in actual.items() if n > debt.get(key, 0)}


def _stale_rows(actual: Counter, debt: dict) -> dict:
    return {key: (n, actual.get(key, 0)) for key, n in debt.items() if actual.get(key, 0) < n}


# (module, enclosing scope, literal) -> occurrences, frozen 2026-09-24 at the
# JF6a baseline. JF6b removes the calc.py rows and JF6c the rest; the list only
# ever shrinks. NEVER add a row to make the guard pass — render the line through
# form_line(pack, key) instead, adding the key to each year's form_lines block
# after reading that year's face.
FORM_LINE_DEBT: dict[tuple[str, str, str], int] = {
    # ── estimate.py ──
    ('estimate.py', 'IncomeSnapshot', 'Form 1040-NR (line 2b'): 1,
    ('estimate.py', 'estimate_refund', 'Form 1040-NR (line 2b'): 1,
    ('estimate.py', 'estimate_refund', 'Form 1040-NR line 12'): 1,
    # ── intake.py ──
    ('intake.py', '_income_document_questions', 'Form 1040-NR line 2b'): 1,
    ('intake.py', '_income_document_questions', 'Form 1040-NR, line 2b'): 1,
    ('intake.py', '_prior_filings_questions', 'Form 1040 line 11'): 1,
    ('intake.py', '_prior_filings_questions', 'Form 1040: line 11'): 1,
    # ── server.py ──
    ('server.py', 'calc', 'Form 1040 line 13b'): 1,
    ('server.py', 'calc', 'Form 1040 line 15'): 1,
    ('server.py', 'calc', 'Form 1040 line 6b'): 1,
    ('server.py', 'calc', 'Form 1040), Part I, line 1'): 1,
    ('server.py', 'calc', 'Schedule 1 Part II line 13'): 1,
    ('server.py', 'calc', 'Schedule 2 line 2'): 1,
    ('server.py', 'calc', 'Schedule 3 line 2'): 1,
}


def test_no_new_form_line_literal_in_engine_text():
    """P-015: a line number typed into engine text serves every year the same string."""
    new = _new_literals(_current_literals(), FORM_LINE_DEBT)
    assert not new, (
        "new form line literal(s) in engine text (P-015) — render each through "
        "form_line(pack_or_year, key) from knowledge/federal/<year>.yaml's form_lines block "
        "(read the key off every shipped year's face first), never add a FORM_LINE_DEBT row:\n"
        + "\n".join(f"  {m}  {where}: {lit!r} (+{n})" for (m, where, lit), n in sorted(new.items()))
    )


def test_form_line_debt_rows_still_match_the_source():
    """P-015: self-clearing — a row whose literal is gone must be deleted or shrunk."""
    stale = _stale_rows(_current_literals(), FORM_LINE_DEBT)
    assert not stale, (
        "FORM_LINE_DEBT rows no longer match the source (a literal was rewired through form_line "
        "or moved to another function) — delete the row or lower its count to the actual:\n"
        + "\n".join(
            f"  {m}  {where}: {lit!r} frozen {frozen}, found {found}"
            for (m, where, lit), (frozen, found) in sorted(stale.items())
        )
    )


def test_the_guard_catches_a_new_literal_anywhere():
    """P-015 acceptance: a new literal added to any guarded module fails the guard."""
    probes: dict[str, list[tuple[str, str]]] = {
        # an f-string in a function, a module-level constant, a docstring
        'def _jf6a_probe(year):\n    return f"report it on Schedule 1 line 8z for {year}"\n':
            [("_jf6a_probe", "Schedule 1 line 8z")],
        '_JF6A_PROBE = "Additional Medicare Tax withholding goes on Form 1040 line 25c"\n':
            [("<module>", "Form 1040 line 25c")],
        'class _Jf6aProbe:\n    def run(self):\n        """Credits flow to Form 8959 Part V, line 24."""\n':
            [("_Jf6aProbe.run", "8959 Part V, line 24")],
        # the line typed inside a replacement field: a hand-coded year branch (the
        # shape calc.excess_ss already uses) and a constant field
        "def _jf6a_branch(y):\n    return f\"Schedule 1{' line 8' if y < 2021 else ' line 8z'}\"\n":
            [("_jf6a_branch", "Schedule 1 line 8"), ("_jf6a_branch", "Schedule 1 line 8z")],
        "_JF6A_FIELD = f\"Form 1040 line {'25c'}\"\n":
            [("<module>", "Form 1040 line 25c")],
        # the same branch by concatenation, and a literal behind `or`
        'def _jf6a_concat(y):\n    return "Schedule 1 line " + ("8" if y < 2021 else "8z")\n':
            [("_jf6a_concat", "Schedule 1 line 8"), ("_jf6a_concat", "Schedule 1 line 8z")],
        'def _jf6a_default(label):\n    return label or "Schedule 2 line 11"\n':
            [("_jf6a_default", "Schedule 2 line 11")],
        # nothing is exempt by name: a local def, or a method, called form_line
        'def form_line(year, key):\n    return "Schedule 1 line 8z"\n':
            [("form_line", "Schedule 1 line 8z")],
        'def _jf6a_method(r):\n    return r.form_line("Form 1040 line 16")\n':
            [("_jf6a_method", "Form 1040 line 16")],
        # the literal moved out of the string (LINE_FIELD_RE): a hoisted constant,
        # a year-table helper, a method that is not the registry's, .format, %
        '_JF6A_L = "25c"\ndef _jf6a_hoisted():\n    return f"Form 1040 line {_JF6A_L}"\n':
            [("_jf6a_hoisted", "Form 1040 line {}")],
        'def _jf6a_table(year):\n    return f"Schedule 1 line {_jf6a_line(year)}"\n':
            [("_jf6a_table", "Schedule 1 line {}")],
        'def _jf6a_other(r):\n    return f"Form 1040 line {r.form_line(2025)}"\n':
            [("_jf6a_other", "Form 1040 line {}")],
        '_JF6A_FMT = "Form 1040 line {}".format("25c")\n':
            [("<module>", "Form 1040 line {}")],
        '_JF6A_PCT = "Form 1040, 1040-SR, or 1040-NR, line %s" % "7"\n':
            [("<module>", "Form 1040, 1040-SR, or 1040-NR, line %s")],
        # a literal inside a replacement field's format spec
        "def _jf6a_spec(x):\n    return f\"{x:{'Form 1040 line 25c'}}\"\n":
            [("_jf6a_spec", "Form 1040 line 25c")],
    }
    for module, path in GUARDED.items():
        source = path.read_text(encoding="utf-8")
        for addition, expected in probes.items():
            new = _new_literals(line_literals(module, source + "\n\n" + addition), FORM_LINE_DEBT)
            for where, literal in expected:
                assert new.get((module, where, literal)) == 1, f"{module}: the guard missed {literal!r} in {addition!r}"
            assert sum(new.values()) == len(expected), f"{module}: {addition!r} -> {new}"


def test_the_guard_passes_text_rendered_through_form_line():
    source = (
        "from taxfill_core.knowledge import form_line\n"
        "def ok(year, pack):\n"
        "    a = f\"Schedule 1 line {form_line(year, 'sched1.other_income')}\"\n"
        "    b = f\"Form 1040 line {form_line(pack, 'f1040.additional_medicare_withholding')}\"\n"
        "    c = 'Schedule SE line ' + form_line(year, 'sched_se.ss_wages')\n"
        "    d = f\"Form 8959 Part {form_line(year, 'f8959.withholding_part') if year else ''}\"\n"
        "    e = f\"Form 1040, 1040-SR, or 1040-NR, line {knowledge.form_line(year, 'f1040.capital_loss')}\"\n"
        "    return a, b, c, d, e\n"
    )
    assert line_literals("probe.py", source) == Counter()


def test_the_guard_counts_text_shared_by_both_arms_once():
    # Both renderings of the f-string carry "Form 1040 line 16"; the reader sees it
    # once, so it is one occurrence (a debt row's count stays the source's count).
    source = "def f(a):\n    return f\"Form 1040 line 16{' (Schedule 2 line 2)' if a else ''}\"\n"
    assert line_literals("probe.py", source) == Counter(
        {("probe.py", "f", "Form 1040 line 16"): 1, ("probe.py", "f", "Schedule 2 line 2"): 1}
    )


def test_every_guarded_module_exists_and_parses():
    for module, path in GUARDED.items():
        assert path.is_file(), f"{module}: {path} moved — update GUARDED so the guard keeps scanning it"
        ast.parse(path.read_text(encoding="utf-8"))
    assert {k[0] for k in FORM_LINE_DEBT} <= set(GUARDED)


def _form_line_rebindings(source: str) -> list[str]:
    """Whatever in a module would make ``form_line`` or ``knowledge`` — the two names whose
    calls the scan lets render a line — mean something other than the registry helper.
    A pydantic field or other class-body name does not count: it shadows nothing outside
    its class."""
    tree = ast.parse(source)
    in_class_body = {
        id(name)
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for stmt in cls.body
        if isinstance(stmt, (ast.Assign, ast.AnnAssign))
        for name in ast.walk(stmt)
    }
    watched = ("form_line", "knowledge")
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in watched:
            found.append(f"line {node.lineno}: defines {node.name}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in watched:
            if id(node) not in in_class_body:
                found.append(f"line {node.lineno}: assigns {node.id}")
        elif isinstance(node, ast.arg) and node.arg in watched:
            # A parameter shadows the helper inside its function body just as an
            # assignment does: `def f(y, form_line=None): ... {form_line(y, k)}`.
            found.append(f"line {node.lineno}: takes a parameter {node.arg}")
        elif isinstance(node, ast.ExceptHandler) and node.name in watched:
            found.append(f"line {node.lineno}: binds {node.name} in an except clause")
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name in watched:
            found.append(f"line {node.lineno}: binds {node.name} in a match pattern")
        elif isinstance(node, ast.MatchMapping) and node.rest in watched:
            found.append(f"line {node.lineno}: binds {node.rest} in a match pattern")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                if bound == "form_line" and not (alias.name == "form_line" and (node.module or "").endswith("knowledge")):
                    found.append(f"line {node.lineno}: imports {alias.name} from {node.module} as form_line")
                if bound == "knowledge" and not (alias.name == "knowledge" and node.module in (None, "taxfill_core")):
                    found.append(f"line {node.lineno}: imports {alias.name} from {node.module} as knowledge")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname in watched and not alias.name.endswith(".knowledge"):
                    found.append(f"line {node.lineno}: imports {alias.name} as {alias.asname}")
    return found


# Rebindings that exist today, frozen like FORM_LINE_DEBT: calc.py's Schedule 1-A
# line helper takes a `form_line: str` parameter (the Part/line it prints), which
# JF6b renames when calc.py imports knowledge.form_line. A row that no longer
# matches fails, so the list only shrinks.
REBINDING_DEBT: dict[str, list[str]] = {}   # JF6b renamed calc.py's _step_part parameter


def test_form_line_in_the_guarded_modules_is_the_registry_helper():
    """P-015: the scan trusts a form_line(...) field, so the name must BE knowledge.form_line —
    a local `def form_line` returning a table value would otherwise launder a hard-coded line."""
    for module, path in GUARDED.items():
        found = sorted(f.split(": ", 1)[1] for f in _form_line_rebindings(path.read_text(encoding="utf-8")))
        assert found == sorted(REBINDING_DEBT.get(module, [])), (
            f"{module}: {found} — a new rebinding of form_line/knowledge, or a REBINDING_DEBT row that "
            f"no longer matches (delete it)"
        )
    for launderer in (
        "def form_line(year, key):\n    return _TABLE[year]\n",
        "form_line = lambda year, key: '7a' if year >= 2025 else '7'\n",
        "from taxfill_core.calc_helpers import line_for as form_line\n",
        "import taxfill_core.tables as knowledge\n",
        "def f(y):\n    knowledge = _Tables()\n    return knowledge\n",
        "def _sp(year, form_line=None):\n    return f\"Schedule 1 line {form_line(year, 'sched1.other_income')}\"\n",
        "def _kp(year, knowledge):\n    return f\"Form 1040 line {knowledge.form_line(year, 'k.k')}\"\n",
        "f = lambda year, form_line: form_line(year, 'k.k')\n",
        "try:\n    pass\nexcept Exception as form_line:\n    pass\n",
        "match x:\n    case {'a': 1, **form_line}:\n        pass\n",
        "match x:\n    case [*form_line]:\n        pass\n",
        "match x:\n    case str() as knowledge:\n        pass\n",
    ):
        assert _form_line_rebindings(launderer), launderer
    for fine in (
        "from taxfill_core.knowledge import form_line\n",
        "from .knowledge import form_line\n",
        "from taxfill_core import knowledge\n",
        "import taxfill_core.knowledge as knowledge\n",
        "class Line(BaseModel):\n    form_line: str = Field(description='the Schedule 1-A line')\n",
    ):
        assert _form_line_rebindings(fine) == [], fine


# ══ the sources topic behind the block ════════════════════════════════════════


@pytest.mark.parametrize(
    "query",
    ["form line numbers", "line number", "which line", "draft forms", "renumbered lines", "form_line_numbers"],
)
def test_line_number_queries_route_to_the_new_topic(query: str):
    """P-015: before the topic, the first three routed to ira_basis_and_roth_conversions
    (Form 8606's line-by-line answers) and "draft forms" was a clean miss."""
    from taxfill_core.sources import get_sources

    r = get_sources(query, 2025, base_dir=KNOWLEDGE_DIR)
    assert {s.topic for s in r.sources} == {"form_line_numbers"}, query


@pytest.mark.parametrize(
    "query,expected",
    [
        # A question about ONE form's line stays with that form's topic.
        ("Form 8606 line 15c", "ira_basis_and_roth_conversions"),
        ("Schedule SE line 8a", "self_employment"),
        ("Form 8606", "ira_basis_and_roth_conversions"),
        ("safe harbor", "estimated_tax"),
        ("underpayment penalty", "underpayment_penalty"),  # its own topic since JF2.1 (IRC 6654, Form 2210)
        ("treaty", "nonresident_and_treaties"),
        ("other income", "other_income_and_rewards"),
        ("self employment tax", "self_employment"),
    ],
)
def test_the_new_topic_does_not_steal_its_neighbours(query: str, expected: str):
    from taxfill_core.sources import get_sources

    r = get_sources(query, 2025, base_dir=KNOWLEDGE_DIR)
    assert {s.topic for s in r.sources} == {expected}, f"{query!r} -> {sorted({s.topic for s in r.sources})}"


@pytest.mark.parametrize(
    "query", ["f8833.pdf", "p519.pdf", "fw8ben.pdf", "f1040nr.pdf", "revision", "form revision", "protocol revision"]
)
def test_file_name_and_revision_queries_keep_the_treaty_topic(query: str):
    # A first cut of the answers text said "pdf" and "revision" twice and took
    # every one of these off nonresident_and_treaties (sources.yaml comment).
    from taxfill_core.sources import get_sources

    topics = {s.topic for s in get_sources(query, 2025, base_dir=KNOWLEDGE_DIR).sources}
    assert "nonresident_and_treaties" in topics and "form_line_numbers" not in topics, (query, sorted(topics))


@pytest.mark.parametrize("query", ["prior year", "prior year safe harbor", "estimated tax prior year", "prior-year tax liability"])
def test_prior_year_queries_are_not_pulled_onto_the_new_topic(query: str):
    # The first draft of the answers text said "prior-year forms" and every one of
    # these moved here; whatever they route to, it is not a line-number registry.
    from taxfill_core.sources import get_sources

    r = get_sources(query, 2025, base_dir=KNOWLEDGE_DIR)
    assert "form_line_numbers" not in {s.topic for s in r.sources}, query


# ══ every entry against its face ══════════════════════════════════════════════


def _norm(text: str) -> str:
    text = text.replace("▶", " ").replace("’", "'")
    text = re.sub(r"(\s?\.){2,}", " ", re.sub(r"\s+", " ", text))  # dot leaders
    return re.sub(r"\s+", " ", text).strip()


# A `printed` piece's own line labels, set aside when its words are looked up
# ("8a Total social security wages ..." is found as "Total social security ...").
_LEADING_LABEL_RE = re.compile(r"^\d{1,2}[a-z]?\s")
_TRAILING_LABEL_RE = re.compile(r"\s(\d{1,2}[a-z])$")
# The first token after the quoted words on the face: where pypdf puts the
# right-margin entry-box label ("... List type and amount 8 9 Combine ..."),
# allowing the split form pypdf sometimes gives a label ("1 k").
_NEXT_TOKEN_RE = re.compile(r"[^0-9A-Za-z]{0,4}([0-9A-Za-z]+)(?: ([a-z])(?![0-9A-Za-z]))?")


def _words(piece: str, line: str | None = None) -> str:
    """A piece's words without its line labels. With ``line``, a trailing label is set aside only when it IS
    that designator (JF6b): "... on Form 1040, 1040-SR, or 1040-NR, line 13a" keeps its "13a", a reference
    the line's own label ends with, and the entry-box "44" after it is what the face check then finds."""
    trailing = _TRAILING_LABEL_RE.search(piece)
    if trailing and (line is None or trailing.group(1) == line):
        piece = piece[:trailing.start()]
    return _norm(_LEADING_LABEL_RE.sub("", piece))


def _labels_the_line(piece: str, line: str) -> bool:
    """Whether a `printed` piece is the one that labels the line: it starts or ends with the
    designator ("8z Other income ...", "c Other forms ... 25c") or names the Part."""
    tokens = piece.split()
    return bool(tokens) and (line in (tokens[0], tokens[-1]) or piece.startswith(f"Part {line} "))


def _designator_follows(face: str, end: int, line: str) -> bool:
    m = _NEXT_TOKEN_RE.match(face, end)
    if not m:
        return False
    token, split_letter = m.groups()
    return token == line or bool(split_letter and token.isdigit() and token + split_letter == line)


def _token_after(face: str, end: int) -> str:
    m = _NEXT_TOKEN_RE.match(face, end)
    return m.group(1) if m else "(nothing)"


def face_quote_problems(entry: FormLineEntry, face_text: str) -> list[str]:
    """What an entry claims that its face's extracted text does not show; [] when all of it checks.

    The words alone prove nothing about the number: a renumbered line keeps its
    words ("Other income. List type and amount" is line 8 in 2019 and 8z in
    2021). So besides every `printed` piece (split on '…') being on the face and
    a draft's "Created" stamp still being in its footer, the DESIGNATOR must be
    where pypdf prints it: for a line, the first token after the labelling
    piece's words at some place they occur (the right-margin entry box); for a
    Part, inside the quote itself ("Part V Withholding Reconciliation").
    """
    face = _norm(face_text)
    problems: list[str] = []
    if entry.is_draft and entry.line_source.removeprefix("draft ") not in face:
        problems.append(f"{entry.line_source.removeprefix('draft ')!r} is not on the face — a newer draft? re-read it")
    pieces = [p.strip() for p in (entry.printed or "").split("…")]
    for piece in pieces:
        if not _words(piece, entry.line):
            problems.append(f"printed piece {piece!r} quotes no words to find")
        elif _words(piece, entry.line) not in face:
            problems.append(f"{_words(piece, entry.line)!r} is not on the face")
    if entry.line is None:
        return problems
    label = next((p for p in pieces if _labels_the_line(p, entry.line)), None)
    if label is None:
        problems.append(f"no printed piece starts or ends with {entry.line!r} or names 'Part {entry.line}'")
    elif not label.startswith(f"Part {entry.line} ") and _words(label, entry.line):
        words = _words(label, entry.line)
        ends = [m.end() for m in re.finditer(re.escape(words), face)]
        if ends and not any(_designator_follows(face, end, entry.line) for end in ends):
            found = sorted({_token_after(face, end) for end in ends})
            problems.append(f"the face prints {found} after {words!r}, not {entry.line!r} — was the line renumbered?")
    return problems


# Verbatim pypdf text (normalised) from the faces these entries cite, just
# enough of each for the check to be proven able to fail without the network.
_FACE_EXCERPTS = {
    "https://www.irs.gov/pub/irs-prior/f1040s1--2019.pdf": (
        "7 Unemployment compensation 7 8 Other income. List type and amount 8 9 Combine lines 1 through 8."
    ),
    "https://www.irs.gov/pub/irs-prior/f1040--2020.pdf": (
        "This is your total tax 24 25 Federal income tax withheld from: a Form(s) W-2 25a b Form(s) 1099 25b "
        "c Other forms (see instructions) 25c d Add lines 25a through 25c 25d"
    ),
    "https://www.irs.gov/pub/irs-prior/f1040nr--2020.pdf": (
        "See instructions . 1b c Total income exempt by a treaty from Schedule OI (Form 1040-NR), Item L, "
        "line 1(e) 1c 2a Tax-exempt interest"
    ),
    "https://www.irs.gov/pub/irs-prior/f8959--2019.pdf": (
        "and go to Part V 18 Part V Withholding Reconciliation 19 Medicare tax withheld from Form W-2, box 6."
    ),
    "https://www.irs.gov/pub/irs-dft/f1040s1--dft.pdf": (
        "See instructions 8v 8z Other income. List type and amount: 8z 9 Total other income. Add lines 8a "
        "through 8z 9 10 Combine lines 1 through 7 and 9. … (Form 1040) 2026 Created 4/24/26"
    ),
}
_EXCERPTED = [
    (2019, "sched1.other_income"),
    (2020, "f1040.additional_medicare_withholding"),
    (2020, "f1040nr.treaty_exempt"),
    (2019, "f8959.withholding_part"),
    (2026, "sched1.other_income"),
]


@pytest.mark.parametrize("year,key", _EXCERPTED)
def test_the_face_check_passes_the_real_entry_on_its_face(year: int, key: str):
    entry = form_line_entry(year, key)
    assert face_quote_problems(entry, _FACE_EXCERPTS[entry.url]) == []


@pytest.mark.parametrize(
    "year,key,change,problem",
    [
        # A renumbered line that kept its words: the ROADMAP's own headline case,
        # then the 1040-NR and 1040 withholding lines on neighbouring numbers.
        (2019, "sched1.other_income", {"line": "8z", "printed": "8z Other income. List type and amount"},
         "prints ['8'] after 'Other income. List type and amount', not '8z'"),
        (2020, "f1040nr.treaty_exempt",
         {"line": "1k", "printed": "1k Total income exempt by a treaty from Schedule OI (Form 1040-NR), Item L, line 1(e)"},
         "not '1k'"),
        (2020, "f1040.additional_medicare_withholding",
         {"line": "25b", "printed": "25 Federal income tax withheld from: … c Other forms (see instructions) 25b"},
         "prints ['25c'] after 'c Other forms (see instructions)', not '25b'"),
        # the next line's number sits two tokens on ("... amount 8 9 Combine"): not a match
        (2019, "sched1.other_income", {"line": "9", "printed": "9 Other income. List type and amount"}, "not '9'"),
        # the wrong Part's name, the wrong words, a re-posted draft
        (2019, "f8959.withholding_part", {"line": "IV", "printed": "Part IV Withholding Reconciliation"},
         "'Part IV Withholding Reconciliation' is not on the face"),
        (2019, "sched1.other_income", {"printed": "8 Other income. List kind and amount"}, "is not on the face"),
        (2026, "sched1.other_income", {"line_source": "draft Created 9/1/26"}, "'Created 9/1/26' is not on the face"),
    ],
)
def test_the_face_check_catches_a_renumbered_line_that_kept_its_words(year, key, change, problem):
    """P-015: the face re-read checks the NUMBER, not only the words around it."""
    entry = form_line_entry(year, key)
    wrong = FormLineEntry(**{**entry.model_dump(), **change})
    problems = face_quote_problems(wrong, _FACE_EXCERPTS[entry.url])
    assert any(problem in p for p in problems), problems


@pytest.mark.network
@pytest.mark.parametrize("year", FEDERAL_YEARS)
def test_every_entry_quotes_its_face(year: int):
    """P-015: every entry against the face it cites (face_quote_problems): the words, the
    designator where pypdf prints it, and a draft's "Created" stamp — a newer draft posted at
    the same irs-dft URL fails here, which is the signal to re-read it."""
    from pypdf import PdfReader

    from taxfill_core.fetch import OfflineFetchError, fetch_blank

    for key, entry in (load_knowledge("federal", year).form_lines or {}).items():
        try:
            # A draft is re-downloaded: the IRS posts a newer draft at the same URL.
            blank = fetch_blank(entry.url, force=entry.is_draft)
        except OfflineFetchError as exc:
            pytest.skip(f"cache empty and network unreachable: {exc}")
        face = "\n".join(page.extract_text() or "" for page in PdfReader(blank).pages)
        assert face_quote_problems(entry, face) == [], f"{year} {key} on {entry.url}"


# ══ JF6b: every line calc.py names comes from the registry ═══════════════════
# Read off every year's face on 2026-09-27 (the 2026 values off the drafts); None = the form has no such line
# that year (recorded as `absent` with the reason). Two finds: the 2021 Schedule 1 sends Form 8889 line 16 to
# 8e and line 20 to 8z (both were printed as 8f), and from 2024 Form 1116 line 20 adds Schedule 2 line 1z, not
# line 2.
JF6B_EXPECTED: dict[str, dict[int, str | None]] = {
    "f1040.wages": {**{y: '1' for y in range(2019, 2022)}, **{y: '1a' for y in range(2022, 2027)}},
    "f1040.qualified_dividends": {y: '3a' for y in range(2019, 2027)},
    "f1040.pensions": {2019: '4c', **{y: '5a' for y in range(2020, 2027)}},
    "f1040.pensions_taxable": {2019: '4d', **{y: '5b' for y in range(2020, 2027)}},
    "f1040.ss_benefits": {2019: '5a', **{y: '6a' for y in range(2020, 2027)}},
    "f1040.ss_taxable": {2019: '5b', **{y: '6b' for y in range(2020, 2027)}},
    "f1040.capital_gain": {2019: '6', **{y: '7' for y in range(2020, 2025)}, **{y: '7a' for y in range(2025, 2027)}},
    "f1040.deduction": {2019: '9', 2020: '12', 2021: '12a', **{y: '12' for y in range(2022, 2025)}, **{y: '12e' for y in range(2025, 2027)}},
    "f1040.taxable_income": {2019: '11b', **{y: '15' for y in range(2020, 2027)}},
    "f1040.tax": {2019: '12a', **{y: '16' for y in range(2020, 2027)}},
    "f1040.ctc": {2019: '13a', **{y: '19' for y in range(2020, 2027)}},
    "f1040.eic": {2019: '18a', 2020: '27', 2021: '27a', **{y: '27' for y in range(2022, 2025)}, **{y: '27a' for y in range(2025, 2027)}},
    "f1040.actc": {2019: '18b', **{y: '28' for y in range(2020, 2027)}},
    "f1040.sched_1a": {**{y: None for y in range(2019, 2025)}, 2025: '13b', 2026: '13a'},
    "f1040nr.sched_1a": {**{y: None for y in range(2019, 2025)}, 2025: '13c', 2026: '13a'},
    "sched1.hsa_deduction": {**{y: '12' for y in range(2019, 2021)}, **{y: '13' for y in range(2021, 2027)}},
    "sched1.se_deduction": {**{y: '14' for y in range(2019, 2021)}, **{y: '15' for y in range(2021, 2027)}},
    "sched1.student_loan_interest": {**{y: '20' for y in range(2019, 2021)}, **{y: '21' for y in range(2021, 2027)}},
    "sched1.stock_options": {**{y: '8' for y in range(2019, 2021)}, 2021: '8j', **{y: '8k' for y in range(2022, 2027)}},
    "sched1.hsa_distributions": {**{y: '8' for y in range(2019, 2021)}, 2021: '8e', **{y: '8f' for y in range(2022, 2027)}},
    "sched1.hsa_testing_income": {**{y: '8' for y in range(2019, 2021)}, 2021: '8z', **{y: '8f' for y in range(2022, 2027)}},
    "sched2.ftc_regular_tax_addition": {**{y: '2' for y in range(2019, 2024)}, **{y: '1z' for y in range(2024, 2027)}},
    "sched2.se_tax": {y: '4' for y in range(2019, 2027)},
    "sched2.additional_medicare": {**{y: '8' for y in range(2019, 2021)}, **{y: '11' for y in range(2021, 2026)}, 2026: '17b'},
    "sched2.additional_medicare_se": {**{y: None for y in range(2019, 2026)}, 2026: '11'},
    "sched2.niit": {**{y: '8' for y in range(2019, 2021)}, **{y: '12' for y in range(2021, 2026)}, 2026: '6'},
    "sched2.hsa_distribution_tax": {**{y: None for y in range(2019, 2021)}, **{y: '17c' for y in range(2021, 2026)}, 2026: '13c'},
    "sched2.hsa_eligibility_tax": {**{y: None for y in range(2019, 2021)}, **{y: '17d' for y in range(2021, 2026)}, 2026: '13d'},
    "sched3.foreign_tax_credit": {y: '1' for y in range(2019, 2027)},
    "sched3.dependent_care": {y: '2' for y in range(2019, 2027)},
    "sched3.excess_ss": {2019: '11', 2020: '10', **{y: '11' for y in range(2021, 2027)}},
    "sched1a.total": {**{y: None for y in range(2019, 2025)}, 2025: '38', 2026: '44'},
    "f8959.total_tax": {**{y: '18' for y in range(2019, 2026)}, 2026: None},
    "f8889.contributions": {y: '2' for y in range(2019, 2027)},
    "f8889.limitation": {y: '3' for y in range(2019, 2027)},
    "f8889.employer_contributions": {y: '9' for y in range(2019, 2027)},
    "f8889.deduction": {y: '13' for y in range(2019, 2027)},
    "f8889.rolled_over": {y: '14b' for y in range(2019, 2027)},
    "f8889.taxable_distributions": {y: '16' for y in range(2019, 2027)},
    "f8889.distribution_tax": {y: '17b' for y in range(2019, 2027)},
    "f8889.last_month_income": {y: '18' for y in range(2019, 2027)},
    "f8889.funding_distribution": {y: '19' for y in range(2019, 2027)},
    "f8889.testing_income": {y: '20' for y in range(2019, 2027)},
    "f8889.testing_tax": {y: '21' for y in range(2019, 2027)},
}


@pytest.mark.parametrize("year", FEDERAL_YEARS)
@pytest.mark.parametrize("key", sorted(JF6B_EXPECTED))
def test_jf6b_every_year_records_every_key_with_its_face(key: str, year: int):
    entry = form_line_entry(year, key)
    assert entry.line == JF6B_EXPECTED[key][year], (key, year, entry.line)
    assert entry.read == "2026-09-27"
    stem = entry.url.rsplit("/", 1)[-1].split("--")[0]
    face = f"irs-dft/{stem}--dft.pdf" if year == 2026 else f"irs-prior/{stem}--{year}.pdf"
    assert entry.url.endswith(face)


def _addmed_parts(year: int) -> list[str]:
    parts = [form_line(year, "sched2.additional_medicare")]
    if form_line_entry(year, "sched2.additional_medicare_se").line is not None:
        parts.append(form_line(year, "sched2.additional_medicare_se"))
    return parts


@pytest.mark.parametrize("year", FEDERAL_YEARS)
def test_jf6b_surtax_work_names_the_years_own_schedule_2_lines(year: int):
    from taxfill_core.calc import additional_medicare_tax, niit  # noqa: PLC0415
    addmed = additional_medicare_tax(medicare_wages=260_000, se_net_profit=50_000, filing_status="single",
                                     year=year).work
    for part in _addmed_parts(year):
        assert f"line {part}" in addmed, (year, part)
    assert f"Part {form_line(year, 'f8959.withholding_part')}" in addmed and "Part IV" not in addmed
    tax = niit(magi=300_000, net_investment_income=20_000, filing_status="single", year=year).work
    assert f"Schedule 2 line {form_line(year, 'sched2.niit')}" in tax
    if year in (2019, 2020):
        assert "(check box a)" in addmed and "check box b" in tax        # '8 Taxes from: a Form 8959 b Form 8960'
    if year == 2026:
        assert "line 17b" in addmed and "line 11" in addmed and "line 6" in tax


@pytest.mark.parametrize("year", [y for y in FEDERAL_YEARS if y >= 2025])
def test_jf6b_hsa_work_names_the_years_own_destinations(year: int):
    from taxfill_core.calc import hsa_deduction  # noqa: PLC0415
    r = hsa_deduction("self_only", year=year, distributions_total=5_000, qualified_medical_expenses=3_000)
    assert f"Schedule 1 Part I line {form_line(year, 'sched1.hsa_distributions')}" in r.work
    assert f"Schedule 2 Part II line {form_line(year, 'sched2.hsa_distribution_tax')}" in r.work
    assert f"Part II, line {form_line(year, 'sched1.hsa_deduction')}" in r.work
    if year == 2026:
        assert "13c" in r.work


def test_jf6b_the_eic_line_is_read_off_each_face():
    from taxfill_core.calc import eitc  # noqa: PLC0415
    for year, line in ((2019, "18a"), (2021, "27a"), (2024, "27"), (2025, "27a")):
        work = eitc(earned_income=20_000, agi=20_000, qualifying_children=1, filing_status="single", year=year).work
        assert f"(Form 1040 line {line})" in work, year


def test_jf6b_the_foreign_tax_credit_regular_tax_follows_the_1116_instructions():
    from taxfill_core.calc import foreign_tax_credit_election  # noqa: PLC0415
    for year, line in ((2023, "2"), (2024, "1z"), (2025, "1z")):
        r = foreign_tax_credit_election(creditable_foreign_taxes=250, all_foreign_income_passive=True,
                                        all_reported_on_payee_statement=True, year=year)
        assert f"plus Schedule 2 line {line}, less Form 4972 tax" in str(r.model_dump()), year


def test_jf6b_the_capital_loss_destination_is_the_registry_not_a_year_table():
    import taxfill_core.calc as calc  # noqa: PLC0415
    assert not hasattr(calc, "_capital_loss_1040_line")
    r = calc.capital_loss_limitation(short_term=-9_000, long_term=0, taxable_income_before_capital_loss=50_000,
                                     year=2024, following_years=[{"short_term": 0, "long_term": 0,
                                                                  "taxable_income_before_capital_loss": 50_000,
                                                                  "year": 2028}])
    assert "carried to Form 1040 line 7." in r.work
    assert r.schedule_d_lines["21"].endswith("Form 1040 line 7")
    assert "no 2028 knowledge pack yet" in str(r.years[-1].model_dump())     # a year past the packs: no guess


def test_jf6b_no_calc_py_debt_is_left():
    assert not [k for k in FORM_LINE_DEBT if k[0] == "calc.py"]
