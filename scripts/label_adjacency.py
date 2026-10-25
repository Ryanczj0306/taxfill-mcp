#!/usr/bin/env python
"""Phase K JK10 (2026-10-24): the label-adjacency guard — a numbered key equals the line printed beside its widget.

Pitfalls P-031 (AL Form 40 2023 keyed one line high) and P-032 (ME 1040ME 2023's lines 21-23 bound by widget NAME,
a 3-cycle against the printed rows) were base-pack mis-binds that the relations could not see and that a name or
/Rect diff between years carried forward. This guard reads, for every widget a pack binds under a numbered key, the
line the pack-blind anchor (taxfill_core.anchor, JK15) reads beside the widget on the pack's own blank, and requires
the key's line to equal it.

The key rule is scripts/anchor_benchmark.py's ``key_line`` ("21", "5a", "line_21", "21.col_b"; every other key
shape is not checked) with one addition, the COLUMN CONVENTIONS of formpacks/column_keys.yaml: in the packs and
line ranges listed there a trailing letter names a column of printed line N ("1a" / "1b" = Delaware's line 1,
Column A / Column B), so the key maps to N. A widget's claim is the set of lines of every numbered key bound to its
field (one value fills every widget of a field), exactly as in the benchmark; the widget agrees when the anchor's
printed_line is one of them. Widgets the anchor gives no printed_line, and keys of any other shape, are not
checked. Tiers are ignored: every printed_line the anchor reads is compared.

Fixer round 2 (Phase K JK10, 2026-10-24) closed the silent half. A family keyed in another shape ("1_wages_fed",
"line19_d01", "A1a_A") declares one regex in formpacks/key_shapes.yaml, checked on each listed pack's own face (every
line it maps a key to is printed there). formpacks/label_adjacency_coverage.yaml records each pack's line-bearing
keys and how many the gate compared; a pack below the ledger's floor names its reason, and the gate fails when a
pack's coverage falls below its row (a regression) or rises past it (a stale row). A line check cannot see a swap
between two columns of one printed row: both claim the row's one line.

Fixer round 3 (Phase K JK10, 2026-10-24) made the ledger's denominator non-circular: a key is line-bearing when it
carries a line-like token (:func:`line_like`) outside the ledger's ``not_lines`` families, or when a rule maps it, so
a pack keyed mostly in an undeclared shape falls below the floor (reason shape-not-declared) instead of reporting
OK. Column shapes name the headings their faces print; the generic ``line-boxes`` shape maps "N.<what>" keys.

Fixer round 4 (Phase K JK10, 2026-10-24): a fraction cannot see a whole schedule left dark. The line-bearing keys are
grouped in FAMILIES (the key with its line tokens replaced by "#": "schedITbus_#", "ehrc.#"); a DARK family — one
holding DARK_FAMILY_MIN or more undeclared keys, or DARK_FAMILY_MIN or more keys of which the gate checks none — makes
the pack PARTIAL whatever its fraction, and its ledger row names the family (``dark``) and the reason.

Fixer round 5 (Phase K JK10, 2026-10-24) closed the class those size thresholds left open. THE DECLARE-ME RULE: an
undeclared line-like key beside one of whose widgets the anchor reads a printed line (:attr:`Result.readable`) puts
its pack below the floor, whatever its family's size, until a shape or convention declares it or the ledger's
``not_lines`` lists it with its reason; the ledger row names those families (``declare``). AZ Form 140's charitable
worksheet ("ws3_1c_..." ... "ws3_7c_...", seven keys the anchor reads 1c-7c beside) and MT 2023's four "ltc.N" rows
had reported OK. Families are now built by PREFIX (:func:`key_family`: the key up to its first line token, the
descriptive tail dropped), and DARK_FAMILY_MIN = 5 governs only the families the anchor reads no line beside.

Fixer round 6 (Phase K JK10, 2026-10-24): the gate stops chasing instances. Its honest output is the check plus a
COUNTED list of what a line-number check cannot see, each count kept exact per pack in the ledger (a stale count
fails the gate like a stale fraction). The declare-me invariant holds over every pack: no row at or above the floor
holds an undeclared key the anchor can read.

WHAT THE GATE CANNOT SEE (one list; the ledger header and formpacks/CONVENTIONS.md "What the gate cannot see" say
the same):

(a) a SAME-ROW COLUMN SWAP: two boxes of one printed row claim the row's one line ("1_wages_fed" <-> "1_wages_ny",
    Column A <-> Column B), except where the face labels each column's box with its own designator (MS 80-105
    "13A"/"13B"). Counted (``same_row``, :attr:`Result.same_row`): the checked keys whose line another checked key of
    a different field claims on the same printed row (the boxes overlap vertically on one page, and the anchor reads
    that line beside both).
(b) an UNREAD box: one the anchor reads NO line beside, inside any family, declared or not (f8962's monthly table,
    AZ 140's page-4 and page-5 rows): a 3-cycle among such boxes passes. Counted (``unread``, :attr:`Result.unread`).
(c) a CROSS-SECTION SWAP between sections that print the same line number: OK 511 / 511-A / 511-B line "1", OH
    IT 1040 / Schedule A / Schedule of Business Income, MT Form 2's tax calculation / Schedule I Part II, WI
    Schedules 1 / 2, NY IT-201 items D2 / E / F ("2"), CA Schedule CA's B7_A / 7_A / II7_A, Schedule 1-A 2026's
    1 / 28a / 28b. Each box reads the line its key claims, so a swap between sections passes. Counted
    (``cross_section``, :attr:`Result.cross_section`): the checked keys whose line another checked key of a different
    field claims on a different printed row (another page, or no vertical overlap), the anchor reading that line
    beside both. A section-aware comparison (the anchor also reading the section a row sits in) is an open item.
(d) a key the gate compares NOTHING for, beside whose box the anchor reads a line: the key carries no line token
    (:func:`line_like`) and no rule maps it (UT TC-40's "withholding_*", IA 1040's "spouse_net_income", NY IT-203's
    "D2_months_you_yonkers", VA 760's "exemptions_section_a_total_count"), or a ``not_lines`` family leaves it out
    (MT Form 2's dd529 item boxes, AZ 140's *_more_space boxes, RI-1040's Schedule W rows; the final review,
    2026-10-25), so a box bound to the wrong row passes. Counted (``descriptive``, :attr:`Result.descriptive`).
    Keys on boxes the exceptions table excuses take part in (a) and (c) like agreeing ones: an exception row
    matches the widget, its claimed lines and the anchor's line, so another key claiming that line passes there.

Keys a ``not_lines`` family leaves out carry the family's adjudicated reason instead; a line that is only a letter
(MT Form 2 2023's exemption rows a-d) is in no shape the gate can express, so its pack reads PARTIAL with the reason.

A disagreement is either a pack defect or an anchor miss, settled by a blind vision check of the row. One that is
not a pack defect goes in formpacks/label_adjacency_exceptions.yaml, one row per disagreeing WIDGET naming exactly
that disagreement (pack, field, widget index, the key's line and the anchor's line), grouped in families that share
the adjudicated reason; every other disagreement fails the gate. The table is self-clearing: a row that no longer
matches a live disagreement (the pack was re-keyed, or the anchor now reads the key's line or another line) fails
the gate as stale, and a second row for the same widget is refused when the table loads.

Usage (the gate itself is packages/core/tests/test_label_adjacency.py, network-marked):

    label_adjacency.py                          # every shipped pack whose blank is cached; exit 1 on a failure
    label_adjacency.py --pack states/al/2023/al40 [--pack ...]
    label_adjacency.py --mandatory              # the two historical rotations (knowledge/anchor/mandatory)
    label_adjacency.py --out DIR                # also write DIR/disagreements.json, DIR/key.json, DIR/crops/ for
                                                # a blind adjudication of the unexcused disagreements
    label_adjacency.py --coverage               # every pack's checked / line-bearing keys, its verdict and its
                                                # undeclared key families
    label_adjacency.py --pack ID --write-ledger # rewrite those packs' coverage-ledger rows from a measurement
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))


def _benchmark():
    """scripts/anchor_benchmark.py (its key rule, truth join, crop renderer and mandatory fixtures)."""
    if "anchor_benchmark" in sys.modules:
        return sys.modules["anchor_benchmark"]
    spec = importlib.util.spec_from_file_location("anchor_benchmark", REPO / "scripts" / "anchor_benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["anchor_benchmark"] = mod
    spec.loader.exec_module(mod)
    return mod


B = _benchmark()
A = B.A

COLUMN_KEYS = REPO / "formpacks" / "column_keys.yaml"
KEY_SHAPES = REPO / "formpacks" / "key_shapes.yaml"
EXCEPTIONS = REPO / "formpacks" / "label_adjacency_exceptions.yaml"
COVERAGE = REPO / "formpacks" / "label_adjacency_coverage.yaml"
_LETTERED = re.compile(r"^0*(\d{1,3})([a-z])$")


# ── column conventions ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Convention:
    id: str
    packs: tuple[str, ...]
    lines: frozenset[int]
    letters: dict
    header: tuple[str, ...]

    def covers(self, pack: str, key: str) -> str | None:
        """The row's line when this convention maps ``key`` of ``pack`` (else None)."""
        m = _LETTERED.match(key)
        if not m or pack not in self.packs or m.group(2) not in self.letters:
            return None
        n = int(m.group(1))
        return str(n) if n in self.lines else None


def parse_lines(spec: str) -> frozenset[int]:
    """"1-7, 9-25, 27" -> {1..7, 9..25, 27}; refuses an empty, reversed or malformed range."""
    out: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,3})(?:-(\d{1,3}))?", part)
        if not m:
            raise ValueError(f"line range {part!r} is not N or N-M")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if lo < 1 or hi < lo:
            raise ValueError(f"line range {part!r} is empty or reversed")
        out.update(range(lo, hi + 1))
    return frozenset(out)


def load_conventions(path: Path = COLUMN_KEYS) -> list[Convention]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for row in data.get("conventions") or []:
        letters = {str(k): str(v) for k, v in (row.get("letters") or {}).items()}
        if not letters or not all(re.fullmatch(r"[a-z]", k) for k in letters):
            raise ValueError(f"{path.name}: {row.get('id')}: letters must map single lower-case letters to columns")
        header = tuple(str(h) for h in row.get("header") or ())
        if not header:
            raise ValueError(f"{path.name}: {row.get('id')}: cite the column header the face prints (header)")
        out.append(Convention(id=str(row["id"]), packs=tuple(row["packs"]), lines=parse_lines(row["lines"]),
                              letters=letters, header=header))
    ids = [c.id for c in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate convention ids")
    return out


# ── declared key shapes ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Shape:
    """Phase K JK10 (2026-10-24): one pack family's key shape, declared in formpacks/key_shapes.yaml — a regex whose
    named groups ``n`` (the printed line number) and optional ``x`` (its lower-case sub-line letter) give the line a
    key of the listed packs names ("1_wages_fed" -> "1" on NY IT-203)."""
    id: str
    packs: tuple[str, ...]
    pattern: re.Pattern
    means: str
    examples: dict
    header: tuple[str, ...] = ()   # fixer round 3: column headings every listed face must print (a column shape)
    line: str = ""                 # fixer round 4: the one printed line of a NAMED block whose keys carry no number

    def covers(self, pack: str, key: str) -> str | None:
        if pack not in self.packs:
            return None
        m = self.pattern.match(key)
        if m and self.line:
            return self.line
        if not m or int(m.group("n")) == 0:
            return None
        g = m.groupdict()
        return f"{int(g['n'])}{(g.get('x') or '').lower()}{g.get('d') or ''}"  # the anchor reads "1Y" as "1y"


def load_shapes(path: Path = KEY_SHAPES) -> list[Shape]:
    """The declared key shapes; each needs packs, a pattern with an ``n`` group (``x`` optional), what it means and
    at least one example key -> line that the pattern reproduces (fixer round 5: an optional ``d`` group is a digit
    the face prints after the sub-line letter, CA Schedule CA's "9b1"). A column shape (keys naming a column of line N)
    also lists ``header``: the column headings each listed face must print, checked like a column convention's.
    Fixer round 4 (Phase K JK10, 2026-10-24): a NAMED block — keys glued to a section name with no line number in
    them (MS 80-105's "age65_blind.taxpayer_blind" boxes on line 8) — gives the printed ``line`` instead, and its
    pattern has no named groups."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for row in data.get("shapes") or []:
        sid = str(row.get("id") or "")
        missing = [k for k in ("id", "packs", "pattern", "means", "examples") if not row.get(k)]
        if missing:
            raise ValueError(f"{path.name}: shape {sid!r} lacks {missing} — name the packs, the regex, what its "
                             "groups mean and at least one example key with its printed line")
        pattern = re.compile(str(row["pattern"]))
        line = str(row.get("line") or "")
        if line:
            if pattern.groupindex or not re.fullmatch(r"[1-9]\d{0,2}[a-z]?", line):
                raise ValueError(f"{path.name}: {sid}: a named block gives one printed line (\"8\", \"5a\") and a "
                                 "pattern without named groups")
        elif "n" not in pattern.groupindex or set(pattern.groupindex) - {"n", "x", "d"}:
            raise ValueError(f"{path.name}: {sid}: the pattern's named groups are n (the line number), an "
                             "optional x (its sub-line letter) and an optional d (a digit after the letter, "
                             "\"9b1\"), nothing else")
        shape = Shape(id=sid, packs=tuple(row["packs"]), pattern=pattern, means=str(row["means"]).strip(),
                      examples={str(k): str(v) for k, v in row["examples"].items()},
                      header=tuple(str(h) for h in row.get("header") or ()), line=line)
        for key, line in shape.examples.items():
            got = shape.covers(shape.packs[0], key)
            if got != line:
                raise ValueError(f"{path.name}: {sid}: example {key!r} maps to {got!r}, not {line!r}")
        out.append(shape)
    ids = [s.id for s in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate shape ids")
    return out


SHAPES: list[Shape] = load_shapes() if KEY_SHAPES.exists() else []


def claim_line(pack: str, key: str, conventions: list[Convention],
               shapes: list[Shape] | None = None) -> tuple[str | None, str | None]:
    """(the printed line a key claims, the convention or shape id that mapped it or None) — None when the key is
    unchecked. Order: the column conventions, then the declared key shapes, then KEY_RULE."""
    for conv in conventions:
        line = conv.covers(pack, key)
        if line is not None:
            return line, conv.id
    for shape in SHAPES if shapes is None else shapes:
        line = shape.covers(pack, key)
        if line is not None:
            return line, shape.id
    return B.key_line(key), None


def printed_designators(blank: Path) -> set[str]:
    """Every line designator the blank prints: a word ("21", "5a", "(5a)", "21.") or a split sub-line ("8 a"), and a
    sub-line whose letter stands apart on its row ("3 Ordinary dividends ... a", "37a. ... b."): "Nx" counts as
    printed when one page prints the number N (alone or as "Ny") and a lone letter x."""
    runs = A.text_runs(blank)
    out = {n for r in runs if (n := A.normalize_line(r.text))} | printed_sublines(blank)
    # fixer round 5: a designator glued to a check-box glyph of a private-use font ("11\uf0a8" on AZ 140NR's
    # "11 [] Nonresident 12 [] ...")
    out |= {n for r in runs if _PUA.search(r.text) and (n := A.normalize_line(_PUA.sub("", r.text)))}
    # fixer round 5: a sub-line with an entry digit printed as one word ("9b1", ".9b2" on CA Schedule CA)
    out |= {f"{int(m.group(1))}{m.group(2)}{m.group(3)}" for r in runs if (m := _SUBSUB.match(r.text.strip()))}
    numbers: dict[int, set[str]] = {}
    letters: dict[int, set[str]] = {}
    for r in runs:
        if n := A.normalize_line(r.text):
            numbers.setdefault(r.page, set()).add(re.match(r"\d+", n).group(0))
        elif m := _LETTER.match(r.text.strip()):
            letters.setdefault(r.page, set()).add(m.group(1))
    for page, nums in numbers.items():
        out |= {f"{n}{x}" for n in nums for x in letters.get(page, ())}
    return out


def shape_problems(shape: Shape, pack: str, blank: Path, keys: list[str]) -> list[str]:
    """Why ``shape`` does not hold on ``pack``'s own blank: it maps none of the pack's keys, it maps a key to a
    line the face does not print (see printed_designators), or the face does not print one of its column
    headings."""
    mapped = {k: line for k in keys if (line := shape.covers(pack, k)) is not None}
    if not mapped:
        return [f"{shape.id} maps no key of {pack}"]
    printed = printed_designators(blank)
    absent = sorted({line for line in mapped.values() if line not in printed}, key=B.line_sort_key)
    problems = [f"{shape.id} maps keys of {pack} to lines the blank does not print: {absent} (e.g. "
                f"{[k for k, v in mapped.items() if v == absent[0]][:3]})"] if absent else []
    if shape.header:
        text = face_text(blank)
        problems += [f"{shape.id}: header {h!r} is not printed on {pack}'s blank" for h in shape.header
                     if " ".join(h.split()) not in text]
    return problems


_SUBLINE = re.compile(r"^[.·•]?\(?(\d{1,3})([a-z])\)?[.:]?$")
_LETTER = re.compile(r"^\(?([a-z])\)?[.:]?$")
_PUA = re.compile("[\ue000-\uf8ff]")
_SUBSUB = re.compile(r"^[.·•]*\(?(\d{1,3})([a-z])(\d)\)?[.:]?$")   # ".9b2" after its leader dots


def printed_sublines(blank: Path) -> set[str]:
    """Every lower-case sub-line designator the blank prints: "26a" as one word, or "26" with "a" right after it on
    the same baseline ("8 a"). Upper case is left out: "7B" is an attachment sequence number, not a line."""
    runs = A.text_runs(blank)
    out: set[str] = set()
    for i, r in enumerate(runs):
        m = _SUBLINE.match(r.text.strip())
        if m:
            out.add(f"{int(m.group(1))}{m.group(2)}")
            continue
        n = A.normalize_line(r.text)
        if n and n.isdigit() and i + 1 < len(runs):
            nxt = runs[i + 1]
            lm = _LETTER.match(nxt.text.strip())
            if lm and nxt.page == r.page and abs(nxt.y0 - r.y0) < 2 and 0 <= nxt.x0 - r.x1 < 6:
                out.add(f"{n}{lm.group(1)}")
    return out


def face_text(blank: Path) -> str:
    """The blank's printed text, every page, whitespace collapsed to single spaces."""
    import pypdfium2 as pdfium  # noqa: PLC0415

    doc = pdfium.PdfDocument(str(blank))
    try:
        return " ".join(" ".join(doc[i].get_textpage().get_text_range().split()) for i in range(len(doc)))
    finally:
        doc.close()


def convention_problems(conv: Convention, blank: Path) -> list[str]:
    """Why ``conv`` does not hold on one of its packs' blanks: a header string the face does not print, or a covered
    line N that the face prints as a sub-line "N<letter>" (then "Na" is a real line there, not a column)."""
    text = face_text(blank)
    problems = [f"header {h!r} is not printed on the blank" for h in conv.header if " ".join(h.split()) not in text]
    subs = printed_sublines(blank)
    clash = sorted((f"{n}{x}" for n in conv.lines for x in conv.letters if f"{n}{x}" in subs), key=B.line_sort_key)
    if clash:
        problems.append(f"the blank prints sub-line designators {clash}: those lines are not column rows")
    return problems


# ── exceptions ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Excuse:
    """One adjudicated disagreement: on ``pack``'s blank, widget ``widget`` of ``field`` is bound to a key of line(s)
    ``lines`` while the anchor reads ``anchor`` beside it, and a blind check of the row found the key right."""
    pack: str
    field: str
    widget: int
    lines: frozenset[str]
    anchor: str
    reason: str
    family: str

    @property
    def id(self) -> str:
        return f"{self.pack}:{self.field}:w{self.widget}"

    def matches(self, row: Row) -> bool:
        return (row.pack == self.pack and row.widget.field == self.field and row.widget.widget_index == self.widget
                and row.widget.printed_line == self.anchor and row.lines == set(self.lines))


def _lines(value) -> frozenset[str]:
    vals = value if isinstance(value, list) else [value]
    return frozenset(str(v).strip() for v in vals if str(v).strip())


def load_exceptions(path: Path = EXCEPTIONS) -> dict[tuple[str, str, int], Excuse]:
    """(pack, field, widget index) -> its adjudicated row. Every family carries a reason and the adjudication it comes
    from (a row may carry its own reason); a second row for the same widget is refused."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[tuple[str, str, int], Excuse] = {}
    for fam in data.get("families") or []:
        missing = [k for k in ("family", "reason", "adjudication") if not str(fam.get(k) or "").strip()]
        if missing or not fam.get("rows"):
            raise ValueError(f"{path.name}: family {fam.get('family')!r} lacks {missing or ['rows']} — give every "
                             f"family an id, the adjudicated reason, the adjudication and at least one row")
        for row in fam["rows"]:
            absent = [k for k in ("pack", "field", "widget", "line", "anchor") if str(row.get(k, "")).strip() == ""]
            if absent:
                raise ValueError(f"{path.name}: a row of family {fam['family']!r} lacks {absent}: {row} — name the "
                                 "pack, the field, the widget index, the key's line and the anchor's line")
            exc = Excuse(pack=str(row["pack"]), field=str(row["field"]), widget=int(row["widget"]),
                             lines=_lines(row["line"]), anchor=str(row["anchor"]),
                             reason=str(row.get("reason") or fam["reason"]).strip(), family=str(fam["family"]))
            if exc.anchor in exc.lines:
                raise ValueError(f"{path.name}: {exc.id} lists the anchor's line {exc.anchor!r} among the key's lines "
                                 "— that widget agrees and needs no row; remove it")
            k = (exc.pack, exc.field, exc.widget)
            if k in out:
                raise ValueError(f"{path.name}: duplicate row for {exc.id} (families {out[k].family!r} and "
                                 f"{exc.family!r}) — keep one")
            out[k] = exc
    return out


# ── the check ────────────────────────────────────────────────────────────────


@dataclass
class Row:
    pack: str
    blank: Path
    widget: A.WidgetAnchor
    claims: dict[str, str] = field(default_factory=dict)       # key -> the line it claims
    via: dict[str, str] = field(default_factory=dict)          # key -> the column convention that mapped it

    @property
    def id(self) -> str:
        return f"{self.pack}:p{self.widget.page}:{self.widget.field}:w{self.widget.widget_index}"

    @property
    def lines(self) -> set[str]:
        return set(self.claims.values())

    @property
    def agrees(self) -> bool:
        return self.widget.printed_line in self.lines


@dataclass
class Result:
    pack: str
    blank: Path
    rows: list[Row]
    line_keys: set[str] = field(default_factory=set)   # every key the gate maps to a line (KEY_RULE or declared)
    undeclared: set[str] = field(default_factory=set)  # line-like keys (line_like) no rule or shape maps
    # fixer round 5: undeclared key -> the printed lines the anchor reads beside its widgets (THE DECLARE-ME RULE)
    readable: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # fixer round 6: descriptive key (no line token, no rule) -> the printed lines the anchor reads beside its widgets
    descriptive: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def checked_keys(self) -> set[str]:
        """The line-bearing keys compared on at least one widget (the anchor read a printed line beside it)."""
        return {k for r in self.rows for k in r.claims}

    @property
    def coverage(self) -> tuple[int, int]:
        """(checked line-bearing keys, line-bearing keys). Phase K JK10 (2026-10-24), fixer round 3: the denominator
        is NOT the keys the gate can map (that count is circular: a pack keyed in an undeclared shape reported a high
        fraction) but every key that carries a line-like token (:func:`line_like`) outside the ledger's not-lines
        families, plus every key the gate maps."""
        return len(self.checked_keys), len(self.line_keys) + len(self.undeclared)

    @property
    def mapped(self) -> int:
        """The keys the gate maps to a printed line (the round-2 denominator, kept as the ledger's ``mapped``)."""
        return len(self.line_keys)

    @property
    def dark(self) -> tuple[str, ...]:
        """The key families the gate leaves wholly dark (:func:`dark_families`)."""
        return dark_families(self.undeclared, self.line_keys, self.checked_keys)

    @property
    def declare(self) -> tuple[str, ...]:
        """Fixer round 5, THE DECLARE-ME RULE: the families of the undeclared keys beside whose widgets the anchor
        reads a printed line. The gate could compare them and compares none; until a shape or convention declares
        them (or not_lines lists them with its reason) they put the pack below the floor."""
        return declare_families(self.readable)

    @property
    def unread(self) -> int:
        """The line-bearing keys beside none of whose widgets the anchor reads a printed line: the gate's blind
        residue, inside any family (a 3-cycle among them passes). Counted per pack in the ledger."""
        return len(self.line_keys - self.checked_keys) + len(self.undeclared - set(self.readable))

    @cached_property
    def shared_line_keys(self) -> tuple[frozenset[str], frozenset[str]]:
        """Fixer round 6: (same-row keys, cross-section keys) — the checked keys whose line another checked key of a
        DIFFERENT field also claims: on the same printed row (the two boxes overlap vertically on one page; blind spot
        (a)) or on a different row (another page, or no vertical overlap; blind spot (c)). A swap between such keys
        passes the line check. A key can be in both. A key whose box is an excused disagreement counts too (the
        final review, 2026-10-25): an exception row matches the widget, its claimed lines and the anchor's line, so
        another key claiming the same line passes at that box as well; in a passing pack every disagreement is
        excused, so every compared box takes part."""
        boxes: dict[str, list[tuple[str, int, float, float]]] = {}
        by_line: dict[str, set[str]] = {}
        for r in self.rows:
            w = r.widget
            y0, y1 = sorted((float(w.rect[1]), float(w.rect[3])))
            for k, ln in r.claims.items():
                boxes.setdefault(k, []).append((w.field, w.page, y0, y1))
                by_line.setdefault(ln, set()).add(k)
        same: set[str] = set()
        cross: set[str] = set()
        for ks in by_line.values():
            for a in ks:
                for b in ks - {a}:
                    for fa, pa, a0, a1 in boxes[a]:
                        for fb, pb, b0, b1 in boxes[b]:
                            if fa != fb:
                                (same if pa == pb and max(a0, b0) < min(a1, b1) else cross).add(a)
        return frozenset(same), frozenset(cross)

    @property
    def same_row(self) -> int:
        """Blind spot (a), counted: the checked keys a same-row column swap could exchange unseen."""
        return len(self.shared_line_keys[0])

    @property
    def cross_section(self) -> int:
        """Blind spot (c), counted: the checked keys a swap between sections printing the same line could exchange."""
        return len(self.shared_line_keys[1])

    @property
    def blind(self) -> dict[str, int]:
        """The counted blind spots, by ledger column (fixer round 6)."""
        return {"same_row": self.same_row, "unread": self.unread, "cross_section": self.cross_section,
                "descriptive": len(self.descriptive)}

    @property
    def disagreements(self) -> list[Row]:
        return [r for r in self.rows if not r.agrees]

    @staticmethod
    def _excused(row: Row, exceptions: dict[tuple[str, str, int], Excuse]) -> bool:
        exc = exceptions.get((row.pack, row.widget.field, row.widget.widget_index))
        return exc is not None and exc.matches(row)

    def unexcused(self, exceptions: dict[tuple[str, str, int], Excuse]) -> list[Row]:
        """Disagreements the exceptions table does not name exactly (widget, key's lines and anchor's line)."""
        return [r for r in self.disagreements if not self._excused(r, exceptions)]

    def stale(self, exceptions: dict[tuple[str, str, int], Excuse]) -> list[str]:
        """Exception rows for this pack that match no live disagreement: the pack was re-keyed or re-bound, or the
        anchor now reads the key's line (or yet another line) beside the widget."""
        live = [r for r in self.disagreements if self._excused(r, exceptions)]
        matched = {(r.pack, r.widget.field, r.widget.widget_index) for r in live}
        return sorted(e.id for k, e in exceptions.items() if e.pack == self.pack and k not in matched)


def check_blank(pack: str, blank: Path, keys: list[dict], root: str = "",
                conventions: list[Convention] | None = None) -> Result:
    """Compare every numbered key of ``keys`` ({"key", "field", "on_state"?, "line"?}) with the anchor on ``blank``.

    ``line`` overrides the key rule (the mandatory fixtures' explicit claims for shapes such as "20_amount").
    """
    conventions = load_conventions() if conventions is None else conventions
    index: dict[str, list[tuple[int, dict]]] = {}
    for w in B.extract_fields(blank):
        same = index.setdefault(w["name"], [])
        same.append((len(same), w))
    claims: dict[tuple[str, int], dict[str, str]] = {}
    via: dict[tuple[str, int], dict[str, str]] = {}
    line_keys: set[str] = set()
    undeclared: set[str] = set()
    und_targets: dict[str, list[tuple[str, int]]] = {}   # fixer round 5: an undeclared key's widgets
    desc_targets: dict[str, list[tuple[str, int]]] = {}  # fixer round 6: a descriptive key's widgets
    for k in keys:
        key = str(k["key"])
        line, conv = (k["line"], None) if k.get("line") else claim_line(pack, key, conventions)
        name = f"{root}.{k['field']}" if root else str(k["field"])
        targets = index.get(name, [])
        if k.get("on_state"):
            narrowed = [(i, w) for i, w in targets if k["on_state"] in (w.get("on_states") or [])]
            targets = narrowed or targets
        if line is None:
            if line_like(key) and not_line_family(key, pack=pack) is None:
                undeclared.add(key)
                und_targets.setdefault(key, []).extend((name, i) for i, _ in targets)
            else:  # no line token, or a not_lines family leaves it out: the gate compares nothing for it
                desc_targets.setdefault(key, []).extend((name, i) for i, _ in targets)
            continue
        line_keys.add(key)
        for i, _ in targets:
            claims.setdefault((name, i), {})[key] = line
            if conv:
                via.setdefault((name, i), {})[key] = conv
    rows = []
    read: dict[tuple[str, int], str] = {}
    for w in A.raw_anchors(blank):
        if "not_an_entry" in w.evidence or not w.printed_line:
            continue
        read[(w.field, w.widget_index)] = w.printed_line
        c = claims.get((w.field, w.widget_index))
        if c:
            rows.append(Row(pack=pack, blank=blank, widget=w, claims=c, via=via.get((w.field, w.widget_index), {})))
    def beside(targets: dict[str, list[tuple[str, int]]]) -> dict[str, tuple[str, ...]]:
        return {key: tuple(sorted({read[t] for t in ts if t in read}, key=B.line_sort_key))
                for key, ts in targets.items() if any(t in read for t in ts)}

    return Result(pack=pack, blank=blank, rows=rows, line_keys=line_keys, undeclared=undeclared,
                  readable=beside(und_targets), descriptive=beside(desc_targets))


def check_pack(pack_id: str, blank: Path, conventions: list[Convention] | None = None) -> Result:
    """The guard on a shipped pack (``formpacks/<pack_id>/pack.yaml``) against its own blank."""
    pack = B.load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    return check_blank(pack_id, blank, B.pack_keys(pack), pack.acroform_root or "", conventions)


def cached_pack_blank(pack_id: str) -> Path | None:
    """The pack's pinned blank from the blank cache (sha256-checked), or None when it is not cached."""
    pack = B.load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    blank = B.cached_blank(pack.source_url)
    return blank if blank is not None and B.sha256_of(blank) == pack.pdf_sha256 else None


def all_pack_ids() -> list[str]:
    return sorted(B.pack_id(p) for p in (REPO / "formpacks").glob("**/pack.yaml"))


# ── the coverage ledger (Phase K JK10, 2026-10-24) ───────────────────────────
#
# A key the gate cannot compare (its shape is not declared, or the anchor reads no printed line beside its widget)
# passes silently; the ledger names every such pack. formpacks/label_adjacency_coverage.yaml records, per shipped
# pack, how many of its line-bearing keys the gate compared on at least one widget. A pack below the ledger's floor
# carries the reason. The gate fails when a pack's coverage differs from its row: fewer checked keys is a
# regression; more (or a changed line-bearing or mapped count) is a stale row to update (``--write-ledger``), so the
# ledger stays exact.
#
# Fixer round 3 (Phase K JK10, 2026-10-24): the denominator is not circular. Round 2 counted as line-bearing only the
# keys the gate could already map (KEY_RULE, a column convention, a declared shape), so a pack keyed mostly in an
# undeclared shape ("13.a" on MS 80-105, "sched1.5" on MT Form 2) reported "OK 26/26" while its main lines went
# unchecked. A key is now LINE-BEARING when it carries a line-like token (:func:`line_like`) and belongs to none of
# the ledger's ``not_lines`` families (identity values, household-member rows, rows numbered by position), or when
# the gate maps it. The keys a rule maps are the ledger's ``mapped`` column; ``lines - mapped`` are the undeclared
# ones.

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_LINE_NUMBER = re.compile(r"^0*\d{1,3}[A-Za-z]{0,2}$")
_LINE_WORD = re.compile(r"(?:line|ln)0*\d{1,3}(?!\d)", re.I)
_GLUED_SECTION = re.compile(r"^[A-Z]{1,3}0*\d{1,3}[a-z]\d?$")   # fixer round 4: "B9b1", "A1a" (CA Schedule CA)
_AGE_BEFORE = frozenset({"over", "under", "age", "ages"})
_AGE_AFTER = frozenset({"older", "or", "younger"})


def line_like(key: str) -> bool:
    """Phase K JK10 (2026-10-24), fixer round 3 — THE TOKEN RULE. Split the key into its letter-and-digit runs (every
    other character separates); the key is line-like when one run

    * is a line number: 1-3 digits with at most two trailing letters ("21", "5a", "13A", "12yb"; "1.cents",
      "13.a", "7.2019", "sch_1a.3", "moa_12y", "12-Y"), unless it is an age threshold (right after "over", "under",
      "age" or "ages", or right before "older", "or" or "younger": "you_65_or_older", "spouse_over_65"), or
    * contains "line" or "ln" directly followed by 1-3 digits ("line21", "mailing_address_line1", "SCHAACPRTILN5"), or
    * is a line glued to its section letter (fixer round 4): 1-3 capitals, the line number, its sub-line letter and
      an optional entry digit ("A1a", "B9b1" = Section B line 9b1 on CA Schedule CA; not "PROP12", "W2").

    A digit run glued to other letters ("d01", "s1", "sched3", "pt2", "w2", "c3", "age65") is a digit cell, a
    schedule, part, row or column index, not a printed line; four or more digits ("1040", "2019") are a form number
    or a year.
    """
    return first_line_token(key) is not None


def first_line_token(key: str) -> re.Match | None:
    """The first letter-and-digit run of ``key`` that makes it line-like (:func:`line_like`), or None."""
    toks = list(_TOKEN.finditer(key))
    for i, m in enumerate(toks):
        tok = m.group(0)
        if _LINE_WORD.search(tok) or _GLUED_SECTION.match(tok):
            return m
        if _LINE_NUMBER.match(tok):
            age = (i > 0 and toks[i - 1].group(0).lower() in _AGE_BEFORE) or (
                i + 1 < len(toks) and toks[i + 1].group(0).lower() in _AGE_AFTER)
            if not age:
                return m
    return None


@dataclass(frozen=True)
class NotLines:
    """One ledger ``not_lines`` family: keys that carry a line-like token but are left out of the denominator."""
    id: str
    pattern: re.Pattern
    reason: str
    examples: tuple[str, ...]
    not_examples: tuple[str, ...] = ()   # fixer round 4: line-bearing keys the family must NOT match (regressions)
    packs: tuple[str, ...] = ()          # fixer round 5: the packs it applies to (empty: every pack)

    def hides(self, key: str, pack: str | None = None) -> bool:
        return (not self.packs or pack in self.packs) and bool(self.pattern.search(key))


def load_not_lines(path: Path = COVERAGE) -> list[NotLines]:
    """The ledger's ``not_lines`` allow-list; each family has an id, a case-insensitive regex (searched in the key),
    the reason its keys name no printed line, example keys it must match (each one line-like) and, fixer round 4,
    ``not_examples``: line-bearing keys a too-broad pattern once hid, which it must not match. Fixer round 5: a
    family that holds on one form only (MT 2023's lettered exemption rows) lists its ``packs``."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for row in data.get("not_lines") or []:
        missing = [k for k in ("id", "pattern", "reason", "examples") if not row.get(k)]
        if missing:
            raise ValueError(f"{path.name}: not_lines family {row.get('id')!r} lacks {missing} — give its id, the "
                             "regex, why its keys name no printed line and example keys")
        fam = NotLines(id=str(row["id"]), pattern=re.compile(str(row["pattern"]), re.I),
                       reason=str(row["reason"]).strip(), examples=tuple(str(e) for e in row["examples"]),
                       not_examples=tuple(str(e) for e in row.get("not_examples") or ()),
                       packs=tuple(str(p) for p in row.get("packs") or ()))
        for ex in fam.examples:
            if not line_like(ex) or not fam.pattern.search(ex):
                raise ValueError(f"{path.name}: not_lines {fam.id}: example {ex!r} is not line-like or does not "
                                 "match the family's pattern")
        for ex in fam.not_examples:
            if not line_like(ex) or fam.pattern.search(ex):
                raise ValueError(f"{path.name}: not_lines {fam.id}: not_example {ex!r} is not line-like or the "
                                 "family's pattern hides it — anchor the pattern so the line-bearing key counts")
        out.append(fam)
    ids = [f.id for f in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate not_lines ids")
    return out


NOT_LINES: list[NotLines] = load_not_lines() if COVERAGE.exists() else []


def not_line_family(key: str, families: list[NotLines] | None = None, pack: str | None = None) -> str | None:
    """The id of the ``not_lines`` family that leaves ``key`` (of ``pack``) out of the denominator (None when none
    does). A family that lists its packs applies to those packs only."""
    for fam in NOT_LINES if families is None else families:
        if fam.hides(key, pack):
            return fam.id
    return None


# Fixer round 4 (Phase K JK10, 2026-10-24): a key FAMILY is the key with each line token ("1", "13a", "21") replaced
# by "#" ("schedITbus_1" and "schedITbus_16" -> "schedITbus_#"; "sch_m.34a.c" -> "sch_m.#.c"). The gate compares no
# undeclared key, so a family of DARK_FAMILY_MIN or more of them is a wholly unchecked block of lines (a schedule
# keyed in a shape nobody declared: OH Schedule IT BUS, MT 2023's EHRC and UPINT schedules), and a 3-cycle planted
# inside it passed both the gate and triage while the pack's fraction stayed above the floor; so does a declared
# family of DARK_FAMILY_MIN or more keys beside none of whose widgets the anchor reads a line (Form 2555's "N.no"
# boxes). Such a DARK family makes the pack PARTIAL whatever its fraction; the ledger row of a pack whose fraction
# is at or above the floor lists its dark families (``dark``) with the reason (shape-not-declared when a family is
# undeclared). A row whose fraction is already below the floor needs no list: its reason and note stand.
#
# Fixer round 5 (Phase K JK10, 2026-10-24): FAMILIES BY PREFIX. Round 4's family kept a key's descriptive tail, so
# AZ Form 140's charitable worksheet "ws3_1c_gifts_cash_or_check" ... "ws3_7c_multiply_by_31pct" made seven
# one-key families and the dark rule never fired. A key's family is now the key up to and including its FIRST line
# token (:func:`first_line_token`), digit runs as "#", the tail dropped: all seven are "ws#_#". DARK_FAMILY_MIN stays
# 5, and it now governs only the families the anchor reads NO line beside: an undeclared key the anchor CAN read is
# caught by THE DECLARE-ME RULE (:attr:`Result.readable`) whatever its family's size (MT 2023's four "ltc.N" LTC
# rent rows). The none-checked half of the dark rule also groups by round 4's uniform-tail family (:func:`tail_family`,
# "#.no", "sch_m.#.b"): a column of boxes that share a tail sits inside a prefix family whose other keys are checked.
DARK_FAMILY_MIN = 5
_FAMILY_TOKEN = re.compile(r"\d+[a-z]?")


def tail_family(key: str) -> str:
    """Round 4's family: every digit run, with one trailing lower-case letter, replaced by "#" ("sch_m.#.b")."""
    return _FAMILY_TOKEN.sub("#", key)


def key_family(key: str) -> str:
    """The key's family (fixer round 5): the key up to and including its first line token, the descriptive tail
    dropped, digit runs as "#" ("ws3_4c_add_1c_3c" -> "ws#_#", "sch_m.34a.c" -> "sch_m.#"); a key with no line
    token is its own :func:`tail_family`."""
    m = first_line_token(key)
    return tail_family(key[:m.end()] if m else key)


def dark_families(undeclared, line_keys=(), checked=()) -> tuple[str, ...]:
    """The sorted DARK families: a family (:func:`key_family`) holding DARK_FAMILY_MIN or more of the ``undeclared``
    keys, or holding DARK_FAMILY_MIN or more line-bearing keys (``undeclared`` and the mapped ``line_keys``) none of
    which is ``checked``; and a uniform-tail family (:func:`tail_family`) of DARK_FAMILY_MIN or more keys none
    checked, unless its prefix family is already dark. Given only the undeclared keys (an offline census, no blank),
    the undeclared half."""
    undeclared, checked = set(map(str, undeclared)), set(map(str, checked))
    keys = undeclared | set(map(str, line_keys))
    fams: dict[str, list[str]] = {}
    tails: dict[str, list[str]] = {}
    for k in keys:
        fams.setdefault(key_family(k), []).append(k)
        tails.setdefault(tail_family(k), []).append(k)
    dark = {f for f, ks in fams.items() if sum(k in undeclared for k in ks) >= DARK_FAMILY_MIN
            or (len(ks) >= DARK_FAMILY_MIN and not any(k in checked for k in ks))}
    dark |= {t for t, ks in tails.items() if t not in fams and len(ks) >= DARK_FAMILY_MIN
             and not any(k in checked for k in ks) and key_family(ks[0]) not in dark}
    return tuple(sorted(dark))


def declare_families(readable) -> tuple[str, ...]:
    """The sorted families (:func:`key_family`) of the undeclared keys the anchor reads a line beside."""
    return tuple(sorted({key_family(str(k)) for k in readable}))


def recorded_dark(checked: int, lines: int, floor: float, dark) -> tuple[str, ...]:
    """The dark families a ledger row records: all of them when the fraction is at or above the floor (they alone
    make the pack PARTIAL), none when the fraction is already below it."""
    return () if below_floor(checked, lines, floor) else tuple(sorted(dark))


@dataclass(frozen=True)
class LedgerRow:
    checked: int
    lines: int
    mapped: int
    reason: str = ""
    note: str = ""
    dark: tuple[str, ...] = ()   # fixer round 4: the undeclared families of DARK_FAMILY_MIN or more keys
    declare: tuple[str, ...] = ()  # fixer round 5: families of undeclared keys the anchor reads a line beside
    unread: int | None = None    # fixer round 5: line-bearing keys the anchor reads no line beside (blind residue)
    # fixer round 6: the other counted blind spots (:data:`BLIND_SPOTS`)
    same_row: int | None = None
    cross_section: int | None = None
    descriptive: int | None = None


# Fixer round 6 (Phase K JK10, 2026-10-24): the ledger columns that count what the gate cannot see, each with the
# sentence a stale count quotes. (b) ``unread`` is compared on its own (round 5) and listed here for the docs.
BLIND_SPOTS = {
    "same_row": "(a) checked keys whose line another field claims on the same printed row (a same-row column swap "
                "passes)",
    "unread": "(b) line-bearing keys the anchor reads no line beside",
    "cross_section": "(c) checked keys whose line another field claims on a different printed row (a swap between "
                     "sections printing the same line number passes)",
    "descriptive": "(d) keys the gate compares nothing for (no line token, or a not_lines family) beside whose box "
    "the anchor reads a line",
}


@dataclass(frozen=True)
class Ledger:
    floor: float
    reasons: dict
    rows: dict


def below_floor(checked: int, lines: int, floor: float, dark=(), declare=()) -> bool:
    """A pack with no line-bearing key, fewer than ``floor`` of them checked, a ``dark`` family (:func:`dark_families`)
    or, fixer round 5, an undeclared key the anchor reads a line beside (``declare``, :attr:`Result.declare`) is
    below the floor."""
    return lines == 0 or checked < floor * lines or bool(dark) or bool(declare)


def coverage_verdict(checked: int, lines: int, floor: float, dark=(), declare=()) -> str:
    """OK / PARTIAL n/m / UNCHECKED — never OK below the floor, nor with a wholly unchecked family, nor with an
    undeclared key the anchor reads a line beside."""
    tail = f"; undeclared, wholly unchecked: {', '.join(dark)}" if dark else ""
    if declare:
        tail += f"; undeclared keys the anchor reads a line beside (declare them): {', '.join(declare)}"
    if not below_floor(checked, lines, floor, dark, declare):
        return f"OK ({checked}/{lines} line-bearing keys checked)"
    if checked == 0:
        return f"UNCHECKED (0/{lines} line-bearing keys checked{tail})"
    return f"PARTIAL {checked}/{lines} (line-bearing keys checked; floor {floor:.0%}{tail})"


def load_ledger(path: Path = COVERAGE) -> Ledger:
    """The coverage ledger, validated: every row 0 <= checked <= mapped <= lines; a row below the floor (or listing
    a ``dark`` family) names a defined reason and a note — shape-not-declared when only its dark families put it
    there; a row at or above it carries neither (the ledger lists reasons only where they hold)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    floor = float(data.get("floor") or 0)
    if not 0 < floor <= 1:
        raise ValueError(f"{path.name}: floor must be a fraction in (0, 1], not {data.get('floor')!r}")
    reasons = {str(k): str(v).strip() for k, v in (data.get("reasons") or {}).items()}
    rows: dict[str, LedgerRow] = {}
    for pack, raw in (data.get("packs") or {}).items():
        if "mapped" not in raw:
            raise ValueError(f"{path.name}: {pack} lacks mapped (the keys a rule or shape maps)")
        dark, declare = raw.get("dark") or [], raw.get("declare") or []
        for col, fams in (("dark", dark), ("declare", declare)):
            if not isinstance(fams, list) or any(not isinstance(f, str) or "#" not in f for f in fams):
                raise ValueError(f"{path.name}: {pack}: {col} lists key families, each with '#' for its line tokens")
        for col in BLIND_SPOTS:
            if col not in raw:
                raise ValueError(f"{path.name}: {pack} lacks {col} — {BLIND_SPOTS[col]}; measure it with "
                                 f"scripts/label_adjacency.py --pack {pack} --write-ledger")
        row = LedgerRow(checked=int(raw["checked"]), lines=int(raw["lines"]), mapped=int(raw["mapped"]),
                        reason=str(raw.get("reason") or ""), note=str(raw.get("note") or "").strip(),
                        dark=tuple(sorted(dark)), declare=tuple(sorted(declare)), unread=int(raw["unread"]),
                        same_row=int(raw["same_row"]), cross_section=int(raw["cross_section"]),
                        descriptive=int(raw["descriptive"]))
        if not 0 <= row.checked <= row.mapped <= row.lines or not 0 <= row.unread <= row.lines - row.checked:
            raise ValueError(f"{path.name}: {pack}: need 0 <= checked ({row.checked}) <= mapped ({row.mapped}) "
                             f"<= lines ({row.lines}) and 0 <= unread ({row.unread}) <= lines - checked")
        if not (0 <= row.same_row <= row.checked and 0 <= row.cross_section <= row.checked
                and row.descriptive >= 0):
            raise ValueError(f"{path.name}: {pack}: need 0 <= same_row ({row.same_row}) <= checked, 0 <= "
                             f"cross_section ({row.cross_section}) <= checked and descriptive "
                             f"({row.descriptive}) >= 0")
        if below_floor(row.checked, row.lines, floor, row.dark, row.declare):
            if row.reason not in reasons or not row.note:
                raise ValueError(f"{path.name}: {pack} is below the floor ({row.checked}/{row.lines}"
                                 f"{', dark ' + str(list(row.dark)) if row.dark else ''}"
                                 f"{', declare ' + str(list(row.declare)) if row.declare else ''}): give a reason "
                                 f"from {sorted(reasons)} and a note saying which keys and why")
            if row.dark and below_floor(row.checked, row.lines, floor):
                raise ValueError(f"{path.name}: {pack}: its fraction ({row.checked}/{row.lines}) is below the floor; "
                                 "remove its dark list (the reason and note stand)")
        elif row.reason or row.note:
            raise ValueError(f"{path.name}: {pack} is at or above the floor ({row.checked}/{row.lines}): remove its "
                             "reason and note")
        rows[str(pack)] = row
    return Ledger(floor=floor, reasons=reasons, rows=rows)


def ledger_problems(pack: str, checked: int, lines: int, ledger: Ledger, mapped: int | None = None,
                    dark=None, declare=None, unread: int | None = None, blind: dict | None = None) -> list[str]:
    """Why ``pack``'s measured coverage does not match its ledger row (empty when it matches exactly); ``mapped``
    (the keys a rule maps), ``dark`` (:func:`dark_families`), ``declare`` (fixer round 5: the families of undeclared
    keys the anchor reads a line beside), ``unread`` (the line-bearing keys it reads no line beside) and, fixer
    round 6, ``blind`` (:attr:`Result.blind`: the counted blind spots, by ledger column) are compared too when
    given."""
    row = ledger.rows.get(pack)
    fix = f"scripts/label_adjacency.py --pack {pack} --write-ledger"
    if row is None:
        return [f"{pack}: no row in {COVERAGE.name} — add it ({fix}); it measures {checked}/{lines}"]
    if declare is not None and tuple(sorted(declare)) != row.declare:
        new = sorted(set(declare) - set(row.declare))
        if new:
            return [f"{pack}: the anchor reads a printed line beside undeclared key famil"
                    f"{'y' if len(new) == 1 else 'ies'} {new} that the gate compares on no widget (a 3-cycle among "
                    f"them would pass): declare a shape in key_shapes.yaml (or a column convention) and check it on "
                    f"the face, or list the keys in the ledger's not_lines with the reason they name no line; until "
                    f"then record the families in the row's declare list with a reason ({fix})"]
        return [f"{pack}: the ledger row is stale — its declare families {list(row.declare)} are now "
                f"{sorted(declare)}; update it ({fix})"]
    if unread is not None and row.unread is not None and unread != row.unread:
        return [f"{pack}: the ledger row is stale — {unread} line-bearing keys sit where the anchor reads no line "
                f"(the row records {row.unread}); update it ({fix})"]
    for col, got in (blind or {}).items():
        want = getattr(row, col, None)
        if col != "unread" and want is not None and got != want:
            return [f"{pack}: the ledger row is stale — blind spot {BLIND_SPOTS[col]}: the gate measures {got}, the "
                    f"row records {want} ({col}); update it ({fix})"]
    want = None if dark is None else recorded_dark(checked, lines, ledger.floor, dark)
    if want is not None and want != row.dark:
        new = sorted(set(want) - set(row.dark))
        if new:
            return [f"{pack}: key famil{'y' if len(new) == 1 else 'ies'} {new} of {DARK_FAMILY_MIN}+ keys the gate "
                    f"compares on no widget (a 3-cycle inside would pass): declare the shape in key_shapes.yaml and "
                    f"check it on the face (or make the anchor read the rows), or record the family in the row's dark "
                    f"list with its reason ({fix})"]
        return [f"{pack}: the ledger row is stale — its dark families {list(row.dark)} are now "
                f"{list(want)}; update it ({fix})"]
    if (checked, lines) == (row.checked, row.lines) and mapped in (None, row.mapped):
        return []
    if checked < row.checked:
        return [f"{pack}: coverage REGRESSED to {checked}/{lines} line-bearing keys checked; the ledger records "
                f"{row.checked}/{row.lines}. A key shape, a binding or an anchor read the gate relied on is gone: "
                f"restore it, or, when the drop is intended, update the row ({fix}) and give the reason"]
    return [f"{pack}: the ledger row is stale — the gate now checks {checked}/{lines} line-bearing keys "
            f"({mapped if mapped is not None else row.mapped} mapped), the row records {row.checked}/{row.lines} "
            f"({row.mapped} mapped); update it ({fix})"]


def diagnose(res: Result, keys: list[dict], root: str = "") -> dict[str, int]:
    """Why each unchecked line-bearing key went unchecked: no rule or shape maps it (shape-not-declared), no widget
    of its field on the blank, its widget's page has no text layer, or the anchor read no printed line beside it."""
    anchors: dict[str, list] = {}
    for w in A.raw_anchors(res.blank):
        anchors.setdefault(w.field, []).append(w)
    text_pages = {r.page for r in A.text_runs(res.blank)}
    why: dict[str, int] = {}
    checked = res.checked_keys
    for k in keys:
        key = str(k["key"])
        if key in res.undeclared:
            why["shape-not-declared"] = why.get("shape-not-declared", 0) + 1
            continue
        if key not in res.line_keys or key in checked:
            continue
        ws = anchors.get(f"{root}.{k['field']}" if root else str(k["field"]))
        cause = ("no-widget" if not ws else "no-text-layer" if ws[0].page not in text_pages
                 else "anchor-reads-no-designators")
        why[cause] = why.get(cause, 0) + 1
    return why


def key_families(keys, n: int = 5) -> str:
    """The ``n`` commonest key families (digits shown as #) of ``keys``: "sched#.# x74, sched#_part#.# x31"."""
    counts: dict[str, int] = {}
    for k in keys:
        fam = re.sub(r"\d+", "#", str(k))
        counts[fam] = counts.get(fam, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return ", ".join(f"{f} x{c}" for f, c in top)


def _in_family(key: str, fam: str) -> bool:
    return fam in (key_family(key), tail_family(key))


def suggest_reason(res: Result, keys: list[dict], root: str = "", floor: float | None = None) -> tuple[str, str]:
    """(reason, note) for a pack below the floor, from :func:`diagnose` — a draft the maintainer confirms. A pack
    only its dark or declare families put there (``floor``: the ledger's) is shape-not-declared (or, for a dark
    declared family, anchor-reads-no-designators), its note naming them."""
    checked, lines = res.coverage
    if lines == 0:
        return "shape-not-declared", f"none of its {len(keys)} keys names a printed line in a shape the gate reads"
    floor = load_ledger().floor if floor is None else floor
    if (res.dark or res.declare) and not below_floor(checked, lines, floor):
        und = {f: sum(_in_family(k, f) for k in res.undeclared) for f in res.dark}
        size = {f: sum(_in_family(k, f) for k in res.undeclared | res.line_keys) for f in res.dark}
        reason = "shape-not-declared" if any(und.values()) or res.declare else "anchor-reads-no-designators"
        parts = [f"{f} x{size[f]}" + (f" ({und[f]} undeclared)" if und[f] else " (no line read beside them)")
                 for f in res.dark]
        note = f"{checked}/{lines} checked"
        if parts:
            note += ", but whole families go unchecked: " + ", ".join(parts)
        if res.declare:
            note += ("; the anchor reads a line beside undeclared keys: "
                     + ", ".join(f"{k} -> {'/'.join(v)}" for k, v in sorted(res.readable.items())[:6])
                     + (" ..." if len(res.readable) > 6 else ""))
        return reason, note
    why = diagnose(res, keys, root)
    top = max(why, key=why.get) if why else "anchor-reads-no-designators"
    parts = ", ".join(f"{n} {c}" for c, n in sorted(why.items(), key=lambda kv: -kv[1]))
    reason = top if top in ("no-text-layer", "shape-not-declared") else "anchor-reads-no-designators"
    note = f"{checked}/{lines} checked; the {lines - checked} unchecked: {parts}"
    if res.undeclared:
        note += f"; undeclared families: {key_families(res.undeclared)}"
    return reason, note


def write_ledger(measured: dict[str, tuple], path: Path = COVERAGE) -> int:
    """Rewrite the ledger's ``packs:`` block from ``measured`` (pack -> checked, lines, mapped, suggested reason,
    note[, dark families[, declare families, unread[, (same_row, cross_section, descriptive)]]]), keeping the text
    above it and every pack not measured. A
    row below the floor keeps its recorded reason and note when it has them and its undeclared count
    (lines - mapped), dark and declare families are unchanged, else takes the suggestion. Returns the number of rows
    changed."""
    text = path.read_text(encoding="utf-8")
    head, sep, _ = text.partition("\npacks:\n")
    if not sep:
        raise ValueError(f"{path.name}: no top-level 'packs:' block")
    ledger = load_ledger(path)
    rows = {p: (r.checked, r.lines, r.mapped, r.reason, r.note, r.dark, r.declare, r.unread,
                (r.same_row, r.cross_section, r.descriptive))
            for p, r in ledger.rows.items()}
    changed = 0
    for pack, measure in measured.items():
        checked, lines, mapped, reason, note = measure[:5]
        dark = recorded_dark(checked, lines, ledger.floor, measure[5] if len(measure) > 5 else ())
        declare = tuple(sorted(measure[6])) if len(measure) > 6 else ()
        old = rows.get(pack)
        unread = measure[7] if len(measure) > 7 else lines - checked   # unmeasured: every unchecked key
        # fixer round 6: (same_row, cross_section, descriptive); unmeasured: none counted
        blind = tuple(measure[8]) if len(measure) > 8 else (0, 0, 0)
        if below_floor(checked, lines, ledger.floor, dark, declare):
            if old and old[3] and old[1] - old[2] == lines - mapped and old[5] == dark and old[6] == declare:
                reason, note = old[3], old[4]
        else:
            reason = note = ""
        new = (checked, lines, mapped, reason, note, dark, declare, unread, blind)
        changed += new != old
        rows[pack] = new
    out = [head, "\npacks:\n"]
    for pack in sorted(rows):
        checked, lines, mapped, reason, note, dark, declare, unread, (same, cross, desc) = rows[pack]
        cell = (f"checked: {checked}, lines: {lines}, mapped: {mapped}, unread: {unread}, same_row: {same}, "
                f"cross_section: {cross}, descriptive: {desc}")
        if dark:
            cell += f", dark: [{', '.join(json.dumps(f) for f in dark)}]"
        if declare:
            cell += f", declare: [{', '.join(json.dumps(f) for f in declare)}]"
        if reason:
            cell += f", reason: {reason}, note: {json.dumps(note)}"
        out.append(f"  {pack}: {{{cell}}}\n")
    path.write_text("".join(out), encoding="utf-8")
    load_ledger(path)
    return changed


# ── the mandatory rotations (KG6 fixtures from JK15) ─────────────────────────


def check_mandatory(case: dict, blank: Path) -> tuple[Result, dict]:
    """The guard on a historical map; every ``must_flag`` key must come out as a disagreement on all its widgets."""
    pack = f"mandatory/{case['case']}"
    result = check_blank(pack, blank, case["keys"], case.get("acroform_root") or "", [])
    flagged, missed = [], []
    for key in case["must_flag"]:
        rows = [r for r in result.rows if str(key) in r.claims]
        (flagged if rows and all(not r.agrees for r in rows) else missed).append(str(key))
    return result, {"must_flag": len(case["must_flag"]), "flagged": flagged, "missed": missed}


# ── the blind adjudication handoff ───────────────────────────────────────────


def blank_digest(path: Path, _memo: dict = {}) -> str:  # noqa: B006 — a per-process memo
    if path not in _memo:
        _memo[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _memo[path]


def write_adjudication(out: Path, rows: list[Row]) -> dict:
    """disagreements.json (blind: the candidate lines sorted, never which side claims which), key.json (the sides;
    the adjudicator does not read it) and one crop per group under out/crops/.

    A group is one box on one blank (same blank sha256, page, field, widget index): several years can share a blank,
    and a box is judged once.
    """
    crops = out / "crops"
    groups: dict[tuple, list[Row]] = {}
    for r in sorted(rows, key=lambda r: r.id):
        g = (blank_digest(r.blank), r.widget.page, r.widget.field, r.widget.widget_index)
        groups.setdefault(g, []).append(r)
    items, group_list, key = [], [], {}
    for n, (g, members) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0].id), 1):
        gid = f"g{n:03d}"
        first = members[0]
        crop = crops / B._crop_name(first.id)
        B.render_crop(first.blank, first.widget.page, first.widget.rect, crop)
        cands = sorted({first.widget.printed_line, *(c for m in members for c in m.lines)}, key=B.line_sort_key)
        group_list.append({"group": gid, "blank": B.home_display(first.blank), "blank_sha256": g[0][:16],
                           "page": first.widget.page, "rect": first.widget.rect, "crop": B.home_display(crop),
                           "candidates": cands, "members": [m.id for m in members]})
        for m in members:
            items.append({"id": m.id, "group": gid, "pack": m.pack, "blank": B.home_display(m.blank),
                          "page": m.widget.page, "field": m.widget.field, "widget_index": m.widget.widget_index,
                          "rect": m.widget.rect, "crop": B.home_display(crop), "candidates": cands})
            key[m.id] = {"group": gid, "anchor_line": m.widget.printed_line,
                         "key_lines": sorted(m.lines, key=B.line_sort_key), "keys": dict(sorted(m.claims.items())),
                         "conventions": m.via, "tier": B.tier_of(m.widget), "score": m.widget.score,
                         "evidence": m.widget.evidence, "label": m.widget.label}
    out.mkdir(parents=True, exist_ok=True)
    (out / "disagreements.json").write_text(json.dumps({"groups": group_list, "items": items}, indent=1) + "\n",
                                            encoding="utf-8")
    (out / "key.json").write_text(json.dumps({"items": key}, indent=1) + "\n", encoding="utf-8")
    return {"items": len(items), "groups": len(group_list)}


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", action="append", default=[], help="a pack id (formpacks/<id>/pack.yaml); repeatable")
    ap.add_argument("--glob", default=None, help="only the pack ids matching this glob (e.g. 'states/de/*')")
    ap.add_argument("--mandatory", action="store_true", help="run the two historical rotations instead")
    ap.add_argument("--out", type=Path, default=None,
                    help="a scratch directory OUTSIDE the repo for the blind-adjudication files and crops")
    ap.add_argument("--coverage", action="store_true",
                    help="print every pack's coverage (line-bearing keys checked / line-bearing keys, verdict)")
    ap.add_argument("--write-ledger", action="store_true",
                    help=f"rewrite the measured packs' rows of formpacks/{COVERAGE.name} (a new row below the floor "
                         "gets a suggested reason to confirm)")
    args = ap.parse_args(argv)
    if args.mandatory:
        bad = 0
        for case in B.load_mandatory():
            blank = B.cached_blank(case["source_url"])
            if blank is None or B.sha256_of(blank) != case["pdf_sha256"]:
                raise SystemExit(f"{case['case']}: its blank is not cached — fetch {case['source_url']} first")
            _, res = check_mandatory(case, blank)
            print(f"{case['case']}: flagged {len(res['flagged'])}/{res['must_flag']}; missed {res['missed']}")
            bad += bool(res["missed"])
        return 1 if bad else 0
    ids = args.pack or all_pack_ids()
    if args.glob:
        ids = [p for p in ids if fnmatch.fnmatch(p, args.glob)]
    conventions, exceptions, ledger = load_conventions(), load_exceptions(), load_ledger()
    failing, uncached, rows_out, mapped, measured, below = [], [], [], 0, {}, []
    tot_checked = tot_lines = tot_mapped = 0
    tot_blind = dict.fromkeys(BLIND_SPOTS, 0)
    for pid in ids:
        blank = cached_pack_blank(pid)
        if blank is None:
            uncached.append(pid)
            continue
        pack = B.load_pack(REPO / "formpacks" / pid / "pack.yaml")
        keys, root = B.pack_keys(pack), pack.acroform_root or ""
        res = check_blank(pid, blank, keys, root, conventions)
        mapped += sum(1 for r in res.rows if r.via)
        checked, lines = res.coverage
        tot_checked, tot_lines, tot_mapped = tot_checked + checked, tot_lines + lines, tot_mapped + res.mapped
        blind = res.blind
        for col, n in blind.items():
            tot_blind[col] += n
        dark, declare = res.dark, res.declare
        if below_floor(checked, lines, ledger.floor, dark, declare):
            below.append(f"{pid} ({checked}/{lines}{', dark ' + ', '.join(dark) if dark else ''}"
                         f"{', declare ' + ', '.join(declare) if declare else ''})")
        if args.write_ledger:
            reason, note = (suggest_reason(res, keys, root, ledger.floor)
                            if below_floor(checked, lines, ledger.floor, dark, declare) else ("", ""))
            measured[pid] = (checked, lines, res.mapped, reason, note, dark, declare, res.unread,
                             (blind["same_row"], blind["cross_section"], blind["descriptive"]))
        if args.coverage:
            print(f"{pid}: {coverage_verdict(checked, lines, ledger.floor, dark, declare)}; {res.mapped} mapped, "
                  f"{len(res.undeclared)} undeclared" + (f" ({key_families(res.undeclared, 3)})" if res.undeclared
                                                          else "")
                  + "; blind: " + ", ".join(f"{n} {col}" for col, n in blind.items()))
        bad = res.unexcused(exceptions)
        stale = res.stale(exceptions)
        cover = [] if args.write_ledger else ledger_problems(pid, checked, lines, ledger, res.mapped, dark, declare,
                                                             res.unread, blind)
        if bad or stale or cover:
            failing.append(pid)
            print(f"{pid}: {len(bad)} unexcused disagreement(s){f', stale exceptions {stale}' if stale else ''}")
            for r in bad:
                print(f"    {r.id} anchor={r.widget.printed_line} keys={r.claims}")
            for c in cover:
                print(f"    {c}")
        rows_out.extend(bad)
    print(f"\n{len(ids)} packs: {len(ids) - len(uncached) - len(failing)} pass, {len(failing)} fail "
          f"({len(rows_out)} widgets), {len(uncached)} not cached; {mapped} checked widgets mapped by a column "
          f"convention or a declared key shape; {tot_checked}/{tot_lines} line-bearing keys checked "
          f"({tot_mapped} mapped by a rule or shape, {tot_lines - tot_mapped} undeclared); what the gate cannot see: "
          + ", ".join(f"{n} {col}" for col, n in tot_blind.items()))
    if below:
        print(f"{len(below)} pack(s) below the coverage floor ({ledger.floor:.0%}; the gate checks too few of their "
              f"keys — each row in {COVERAGE.name} says why): " + ", ".join(below))
    if args.write_ledger:
        print(f"ledger: {write_ledger(measured)} row(s) changed in {COVERAGE.name}")
    if uncached:
        print("not cached (fetch with `taxfill fetch-blank`, or set TAXFILL_BLANKS_CACHE): " + ", ".join(uncached))
    if args.out:
        n = write_adjudication(args.out, rows_out)
        print(f"wrote {n['items']} items in {n['groups']} groups to {B.home_display(args.out)}")
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
