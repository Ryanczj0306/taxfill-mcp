"""Form Pack schema — the ``pack.yaml`` spec from dev plan section 5.

A *form pack* is versioned DATA describing one tax form for one jurisdiction
and one tax year: the AcroForm line-to-field map, math relations enforced by
the verifier, cross-form consistency rules, identity fields that must match
across the whole filing, signature placement, and official mailing addresses.

Key principle (dev plan section 3): the engine is jurisdiction- and
form-agnostic. Federal and state forms use this same schema; coverage grows
by adding packs under ``formpacks/``, never by changing engine code.

Blank PDFs are downloaded at runtime from the official ``source_url`` and
verified against ``pdf_sha256`` — never vendored in the repo.

Validation errors are intentionally prescriptive (dev plan section 11):
every failure tells the pack author exactly what to fix.
"""

from __future__ import annotations

import difflib
import functools
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The three field types the filler knows how to write (dev plan section 5).
FieldType = Literal["text", "checkbox", "money"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JURISDICTION_RE = re.compile(r"^(federal|states/[a-z]{2})$")
_SHA256_PLACEHOLDER = "..."  # authoring placeholder; fetch_blank refuses to verify against it


# A relation may end in " unless <line>" (Phase K JK28, 2026-10-16): the face's own checkbox that tells the reader a
# line is computed another way. IA 1040 prints "Check if using alternate tax (line 5), tax reduction calculation (line
# 12), or low-income exemption", and a single filer who uses the Income Tax Reduction Worksheet (41-146) enters its
# amount on line 12 — "Enter the smaller number here and on IA 1040, line 12. Check the box on IA 1040, step 5 if the
# amount on line 3 is used" — so "12 == max(7 - 11, 0)" fails that correct return. verify reports a guarded relation
# SKIPPED while its box is checked on the PDF. The keyword is a whole word; no line key may spell it.
RELATION_GUARD_KEYWORD = "unless"
_GUARD_WORD_RE = re.compile(rf"\b{RELATION_GUARD_KEYWORD}\b", re.IGNORECASE)
_GUARD_GRAMMAR = f"'<expr> == <expr> {RELATION_GUARD_KEYWORD} <checkbox line>'"


def split_relation_guard(relation: str) -> tuple[str, str | None]:
    """Split a relation into its equation and its ``unless`` guard: ``(equation, guard line or None)``.

    ``"12 == max(7 - 11, 0) unless alt_tax_method"`` -> ``("12 == max(7 - 11, 0)", "alt_tax_method")``; a relation
    with no clause comes back whole with ``None``. Only the CLAUSE is checked here — the equation's arithmetic is the
    verify evaluator's to parse — and a malformed clause raises :class:`ValueError` saying how to write it: the
    keyword must stand alone after the equation, at most once, followed by exactly one line key.
    """
    found = list(_GUARD_WORD_RE.finditer(relation))
    if not found:
        return relation, None
    if len(found) > 1:
        raise ValueError(
            f"relation {relation!r}: '{RELATION_GUARD_KEYWORD}' appears {len(found)} times — a relation takes at most "
            f"one guard, written {_GUARD_GRAMMAR}; to suspend it for either of two boxes, declare the arithmetic "
            f"once per path or leave it undeclared"
        )
    match = found[0]
    before, after = relation[: match.start()], relation[match.end():]
    if match.group() != RELATION_GUARD_KEYWORD:
        raise ValueError(
            f"relation {relation!r}: write the guard keyword in lowercase, {_GUARD_GRAMMAR} (found {match.group()!r})"
        )
    if (before and not before[-1].isspace()) or (after and not after[0].isspace()):
        raise ValueError(
            f"relation {relation!r}: '{RELATION_GUARD_KEYWORD}' must stand alone between spaces, written "
            f"{_GUARD_GRAMMAR}"
        )
    equation, guard = before.strip(), after.strip()
    if "==" not in equation:
        raise ValueError(
            f"relation {relation!r}: '{RELATION_GUARD_KEYWORD}' must follow a whole equation, written "
            f"{_GUARD_GRAMMAR} — nothing before it reads '<expr> == <expr>'"
        )
    if not guard or len(guard.split()) != 1:
        raise ValueError(
            f"relation {relation!r}: '{RELATION_GUARD_KEYWORD}' must be followed by exactly ONE line key — the "
            f"checkbox line whose check suspends the relation, written {_GUARD_GRAMMAR}"
            + (f"; found {guard!r}" if guard else "; found nothing")
        )
    return equation, guard


def _require_http_url(value: str, key: str) -> str:
    if not value.startswith(("https://", "http://")):
        raise ValueError(
            f"{key} must be a full official URL starting with https:// "
            f"(blank forms and verify pages come from .gov sites only)"
        )
    return value


# PackField.format values that read an identifying number (Phase K JK28, 2026-10-23). Both take an SSN or ITIN with or
# without dashes and spaces, and verify compares such a line by its digits however it was written.
#   ssn_digits_only  the 9 digits alone: a 9-cell comb, or a plain box (P-001: dashes overflow a comb's cells).
#   ssn_dash_cells   'ddd-dd-dddd': an 11-cell comb whose printed face spends cells 4 and 7 on the two dashes (the OR
#                    Form OR-40 SSN boxes), so each dash cell gets the dash and each digit lands in its printed cell.
SSN_DIGITS_ONLY = "ssn_digits_only"
SSN_DASH_CELLS = "ssn_dash_cells"
SSN_FORMATS = frozenset({SSN_DIGITS_ONLY, SSN_DASH_CELLS})
SSN_DASH_CELLS_MAXLEN = 11
SSN_DASH_CELLS_RE = re.compile(r"\d{3}-\d{2}-\d{4}")


def ssn_dash_cells_text(digits: str) -> str:
    """The 11 characters an ``ssn_dash_cells`` comb holds for 9 digits: 'ddd-dd-dddd' (Phase K JK28, 2026-10-23)."""
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


# PackField.format for a MONEY line whose box is a comb that spends cells on printed thousands separators (Phase K
# JK28, 2026-10-23).
#   money_comma_cells  the whole-dollar amount comma-grouped ('1,234,567'), written into a right-aligned comb whose
#                      printed face puts a comma in every 4th cell from the right, so each comma cell gets the comma
#                      and each digit lands in its printed cell. A negative amount carries its minus sign in the
#                      nearest DIGIT cell left of its first digit, never in a comma cell: '-5', '-12,345',
#                      '-1,234,567' put it in the cell next to the first digit, but an amount of 3 or 6 (or 9) digits
#                      has a comma cell there, which is left blank and the minus goes one cell further left
#                      ('- 123', '- 123,456'), so the sign never overprints a printed comma (Phase K JK28 fix,
#                      2026-10-23). verify reads the value back through parse_money, which drops the commas and the
#                      space, so relations and the independent recompute see the number.
# Census of every money line bound to a widget with the Comb bit (/Ff bit 25) on its pack's cached blank, 2026-10-23:
# 576 lines in 12 packs; one representative widget per (pack, /MaxLen, width) rendered at 600 dpi with 1234567,
# 12345 and 123 filled.
#   OR Form OR-40 2023 / 2024 / 2025, lines 7-55b (48 / 46 / 48 lines): /MaxLen 11, /Q 2, 158 pt wide; printed as
#       three boxes of 3 cells with a comma printed in the cell between two boxes (cells 4 and 8), then '.' and a
#       printed '0 0'. Bare digits put a digit in a comma cell (1234567 printed '123[4]567'): money_comma_cells.
#   LA Form IT-540 2023 / 2024 / 2025 (47 / 47 / 48 lines, /MaxLen 3-9), MA Form 1 2023 / 2025 (83 / 84 lines,
#       /MaxLen 4-8) and VA Form 760 2023 / 2024 / 2025 (41 lines each, /MaxLen 3-9): the printed commas sit ON the
#       rule between two digit cells and spend no cell, so the bare digits land one per printed cell. No format.
#   IA 1040 2023 lines 32a / 32b (/MaxLen 9 and 17, /Q 0): the direct-deposit routing and account number boxes,
#       digit cells only. No separator.
# test_pack_invariants.py (network-marked, reading the cached blank) holds every money line on a comb widget to this
# census: it uses the format or is listed with what its box prints; and the format is used only by a pack the census
# found with comma cells (MONEY_COMBS_WITH_COMMA_CELLS there, offline), since on LA / MA / VA it would put commas in
# digit cells.
MONEY_COMMA_CELLS = "money_comma_cells"
MONEY_FORMATS = frozenset({MONEY_COMMA_CELLS})
PACK_FORMATS = SSN_FORMATS | MONEY_FORMATS
# A digit group of 3 after a minus is written '- ddd': the cell between them is a printed comma cell, left blank.
MONEY_COMMA_CELLS_RE = re.compile(r"(?:-?\d{1,2}|(?:- )?\d{3})(?:,\d{3})*")


def money_comma_cells_text(whole: str) -> str:
    """A whole-dollar amount as a ``money_comma_cells`` comb holds it: '1234567' -> '1,234,567', '-12345' ->
    '-12,345' (Phase K JK28, 2026-10-23). ``whole`` is the filler's whole-dollar rendering: an optional '-', digits.

    The minus sign takes the nearest digit cell left of the first digit: when the amount's leading group is a full
    3 digits the cell next to it is a comma cell, so that cell is written blank and the minus goes one further left
    ('-123' -> '- 123', '-123456' -> '- 123,456'), never on top of a printed comma."""
    negative = whole.startswith("-")
    grouped = f"{int(whole[1:] if negative else whole):,}"
    if not negative or grouped == "0":
        return grouped
    return f"- {grouped}" if len(grouped.split(",")[0]) == 3 else f"-{grouped}"


class PackField(BaseModel):
    """One line of the form mapped to one AcroForm field."""

    model_config = ConfigDict(extra="forbid")

    line: str = Field(description="Logical line key, e.g. '1a', 'identifying_number', 'filing_status.single'.")
    field: str = Field(description="AcroForm field name relative to acroform_root, e.g. 'Page1[0].f1_7[0]'.")
    type: FieldType
    maxlen: int | None = Field(default=None, ge=1, description="Maximum characters (e.g. comb cell count).")
    comb: bool = Field(default=False, description="True for comb fields (one character per cell).")
    format: str | None = Field(
        default=None,
        description=(
            "Input normalization hint for the filler: 'ssn_digits_only' (dashes overflow comb cells), "
            "'ssn_dash_cells' (an 11-cell comb whose printed face puts a dash in cells 4 and 7: written ddd-dd-dddd) "
            "or, on a money line, 'money_comma_cells' (a right-aligned comb whose printed face puts a comma in every "
            "4th cell from the right: written comma-grouped, 1,234,567)."
        ),
    )
    on_state: str | None = Field(
        default=None,
        description="Checkbox export value to set, e.g. '/1' (pypdf needs both /V and widget /AS).",
    )
    required: bool = Field(
        default=False,
        description=(
            "True when the line must be answered on every filing; drives the "
            "unanswered-required checkbox audit (pitfall P-003)."
        ),
    )
    reserved: bool = Field(
        default=False,
        description=(
            "True for a printed 'Reserved for future use' row kept mapped so a relation can name it (the "
            "RESERVED_LINE_KEEPS table): fill_form warns when a value lands on it and audit_pack skips it (JEa)."
        ),
    )
    group: str | None = Field(
        default=None,
        description=(
            "Checkbox group id — the yes/no boxes of one question share a group "
            "(e.g. 'line12'); a required group must have at least one member "
            "checked. Valid on checkbox fields only."
        ),
    )
    # Phase K JEe2 (2026-10-25): strict, finite and at least overlay.MIN_FONT_SIZE (6 pt), so a bool, inf, nan or a
    # tiny size (written into the /DA with :g, 1e-05 Tf is no PDF number) is refused here, at pack load.
    font_size: float | None = Field(
        default=None,
        ge=6,
        strict=True,
        allow_inf_nan=False,
        description=(
            "Points, for a box the blank sizes edge to edge for its glyphs at its /DA size (Phase K JEe2: "
            "RI-1040's dates of birth, initials, suffixes and signature dates): fill_form writes the widget's /DA "
            "at this size, font and colour kept, before the appearance is built, and verify measures the value "
            "at it. At least 6 pt and at most the widget's own /DA size (fill_form refuses a larger one, or an "
            "auto-size box). Text and money lines only; leave it out everywhere else."
        ),
    )

    @model_validator(mode="after")
    def _check_options_match_type(self) -> "PackField":
        if self.type == "checkbox":
            if self.on_state is None:
                raise ValueError(
                    f"field '{self.line}': checkbox fields require 'on_state' "
                    f"(the PDF export value, e.g. \"/1\") — dump the blank PDF's "
                    f"field states to find it"
                )
            if self.comb or self.maxlen is not None or self.format is not None or self.font_size is not None:
                raise ValueError(
                    f"field '{self.line}': 'maxlen', 'comb', 'format' and 'font_size' apply only to "
                    f"text and money fields — remove them from this checkbox"
                )
        else:
            if self.on_state is not None:
                raise ValueError(
                    f"field '{self.line}': 'on_state' applies only to checkbox fields — "
                    f"remove it or change the field type to checkbox"
                )
            if self.group is not None:
                raise ValueError(
                    f"field '{self.line}': 'group' applies only to checkbox fields "
                    f"(the yes/no boxes of one question share a group id) — "
                    f"remove it or change the field type to checkbox"
                )
            if self.comb and self.maxlen is None:
                raise ValueError(
                    f"field '{self.line}': comb fields require 'maxlen' "
                    f"(the number of comb cells) so the clipping scan can catch overflow"
                )
            if self.format == MONEY_COMMA_CELLS and (self.type != "money" or not self.comb):
                raise ValueError(
                    f"field '{self.line}': format '{MONEY_COMMA_CELLS}' is for a money line whose box is a comb with "
                    f"printed comma cells, but this line is type {self.type} with comb={self.comb} — map it type: "
                    f"money, comb: true and maxlen: <the widget's /MaxLen>, or drop the format"
                )
        return self


class Signature(BaseModel):
    """Where the human signs (dev plan section 9: exact signature locations)."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page number carrying the signature block.")
    standalone_only: bool = Field(
        default=False,
        description="True when the form is signed only if filed alone (e.g. Form 8843 attached to a 1040-NR is NOT separately signed).",
    )


class Mailing(BaseModel):
    """Official paper-filing addresses; this project is print-and-mail by design (no e-filing)."""

    model_config = ConfigDict(extra="forbid")

    no_payment: str = Field(description="Mailing address when no payment is enclosed.")
    with_payment: str = Field(description="Mailing address when a payment is enclosed.")
    verify_url: str = Field(
        description="Official where-to-file page to re-verify addresses before mailing (watched by the nightly drift job)."
    )

    @field_validator("verify_url")
    @classmethod
    def _verify_url_is_http(cls, value: str) -> str:
        return _require_http_url(value, "mailing.verify_url")


# JT0c: the forms whose own final revision makes a fill filing-grade in a provisional year, keyed
# (jurisdiction, form). The Form 1040-ES for a year posts final in its January (the 2026 revision is
# irs.gov/pub/irs-prior/f1040es--2026.pdf, Created 2/12/26) and its vouchers fall due during that year.
OWN_FINAL_REVISION_FORMS = frozenset({("federal", "1040-ES")})


# ---------------------------------------------------------------------------
# Page-header mirrors (Phase K JK28, 2026-10-16)
# ---------------------------------------------------------------------------
# A form that repeats the filer's name and SSN at the top of its later pages maps each repeat as a line of its own:
# CA Form 540 prints "Your name:" and "Your SSN or ITIN:" across the top of Sides 2-6 (pack lines name.full and
# identifying_number.page6). Nothing filled or checked them: the JK5 release-candidate walkthrough's Form 540 printed
# blank headers on Sides 2-6 and verify_form passed. `FormPack.mirrors` maps such a line to a TEMPLATE over the pack's
# other lines; fill_form fills a mirror the caller leaves out, and verify checks each one on disk. Both render the
# template with render_mirror below: verify never imports the filler, so the one renderer lives here, beside the spec
# it implements. The language:
#
#   {line}        the line's value as fill_form renders it (after the line's own formatting, e.g. ssn_digits_only)
#   {line[a:b]}   a Python-style character slice of it: split SSN boxes ({ssn[0:3]}, {ssn[3:5]}, {ssn[5:9]}) and
#                 truncations such as "first 10 characters of your last name" ({name.last[:10]}); a negative bound
#                 counts from the end, and there is no step. A slice of a line in an SSN format (ssn_digits_only,
#                 ssn_dash_cells) reads its 9 DIGITS, so {ssn[3:5]} is the middle two whether the line holds
#                 999887777 or 999-88-7777 (Phase K JK28, 2026-10-23: the dashes shifted every slice past the first)
#   [ ... ]       an optional segment, kept only when a placeholder inside it renders non-empty (the spouse's part of
#                 a joint return's name line); segments do not nest
#
# A placeholder's value is whitespace-collapsed and stripped before it is sliced. After rendering, whitespace runs
# collapse to one space and the result is stripped. A template whose placeholders all render empty renders "" (its
# literal text included), so a mirror never prints a caption with no value behind it. Braces and square brackets are
# syntax only: a template carries no literal '{', '}', '[' or ']'.
#
# A name can be too wide for its header box (CA's "Your name:" holds about 18 capitals), and a template cannot say how
# to shorten it. `FormPack.mirror_abbreviations` lets a pack name, per mirror, the placeholders whose words the header
# may shorten to a leading part (an initial, with or without a period) or leave out; every other placeholder and all
# literal text stay whole, in order. Both sides measure a mirror against its box with taxfill_core.textfit (Phase K
# JK28, 2026-10-16): fill_form writes the first value of mirror_ladder below that its box holds (the full value, then
# two fixed abbreviations), or leaves the box blank for the filer to hand-write when none fits, and verify expects
# exactly that and accepts another allowed abbreviation only when the full value does not fit. render_mirror_pieces
# says which line each piece of a rendering came from.

_TEMPLATE_WS_RE = re.compile(r"\s+")
_MIRROR_SLOT_RE = re.compile(r"(?P<line>[^\[\]{}]+)(?:\[(?P<slice>[^\[\]{}]*)\])?")
_MIRROR_SLICE_RE = re.compile(r"\s*(?P<start>[+-]?\d+)?\s*:\s*(?P<stop>[+-]?\d+)?\s*")
_MIRROR_INDEX_RE = re.compile(r"\s*[+-]?\d+\s*")


class MirrorSlot(NamedTuple):
    """One ``{line}`` or ``{line[a:b]}`` placeholder of a mirror template."""

    line: str
    start: int | None = None
    stop: int | None = None


class MirrorSegment(NamedTuple):
    """One optional ``[ ... ]`` segment of a mirror template: printed only when a placeholder in it renders non-empty."""

    parts: tuple[str | MirrorSlot, ...]


def _parse_mirror_slot(template: str, body: str) -> MirrorSlot:
    match = _MIRROR_SLOT_RE.fullmatch(body)
    if match is None:
        raise ValueError(
            f"template {template!r}: placeholder {{{body}}} must be {{line}} or {{line[a:b]}} — a line key, then an "
            f"optional Python-style slice"
        )
    line, raw = match.group("line"), match.group("slice")
    if raw is None:
        return MirrorSlot(line)
    bounds = _MIRROR_SLICE_RE.fullmatch(raw)
    if bounds is None:
        if _MIRROR_INDEX_RE.fullmatch(raw):
            index = int(raw)
            one = f"[{index}:]" if index == -1 else f"[{index}:{index + 1}]"
            hint = f"[{raw.strip()}] is an index, not a slice; the one character it means is {one}"
        else:
            hint = "write [a:b], [a:] or [:b] with whole numbers (a negative one counts from the end; there is no step)"
        raise ValueError(f"template {template!r}: placeholder {{{body}}} has a malformed slice: {hint}")
    start = int(bounds.group("start")) if bounds.group("start") is not None else None
    stop = int(bounds.group("stop")) if bounds.group("stop") is not None else None
    if stop == 0:
        # [:0], [-1:0], [3:0] and [:-0] end before the first character, whatever the start (Phase K JK28, 2026-10-16:
        # the same-sign rule below let [:0] and [-1:0] load, a mirror that could never print).
        raise ValueError(
            f"template {template!r}: placeholder {{{body}}} selects nothing — a stop bound of 0 ends the slice before "
            f"its first character, so it is empty for every value; leave the stop out to read to the end ([a:]) or "
            f"give the number of characters to keep ([:10])"
        )
    if start is not None and stop is not None and (start < 0) == (stop < 0) and start >= stop:
        raise ValueError(
            f"template {template!r}: placeholder {{{body}}} selects nothing — [{start}:{stop}] is empty for every "
            f"value; the stop bound must come after the start"
        )
    return MirrorSlot(line, start, stop)


@functools.lru_cache(maxsize=256)
def parse_mirror_template(template: str) -> tuple[str | MirrorSlot | MirrorSegment, ...]:
    """Parse a page-header mirror template (the language above) into literal text, slots and optional segments.

    Raises :class:`ValueError`, saying what to fix, on an unclosed or stray brace or bracket, a nested segment, a
    segment with no placeholder, a malformed or empty slice, or a template that names no line at all (a constant
    would be a value the filler invents). Line keys are not checked here: :class:`FormPack` checks them against its
    own lines.
    """
    parts: list[str | MirrorSlot | MirrorSegment] = []
    segment: list[str | MirrorSlot] | None = None
    literal: list[str] = []

    def flush(into: list) -> None:
        if literal:
            into.append("".join(literal))
            literal.clear()

    index = 0
    while index < len(template):
        char = template[index]
        if char == "{":
            close = template.find("}", index + 1)
            if close == -1:
                raise ValueError(
                    f"template {template!r}: the '{{' at position {index} is never closed — a placeholder is "
                    f"{{line}} or {{line[a:b]}}"
                )
            into = parts if segment is None else segment
            flush(into)
            into.append(_parse_mirror_slot(template, template[index + 1:close]))
            index = close + 1
            continue
        if char == "}":
            raise ValueError(
                f"template {template!r}: stray '}}' at position {index} — braces only wrap a placeholder, {{line}} "
                f"or {{line[a:b]}}"
            )
        if char == "[":
            if segment is not None:
                raise ValueError(
                    f"template {template!r}: the '[' at position {index} opens a segment inside another — optional "
                    f"segments do not nest"
                )
            flush(parts)
            segment = []
        elif char == "]":
            if segment is None:
                raise ValueError(
                    f"template {template!r}: stray ']' at position {index} — square brackets wrap an optional "
                    f"segment, [ ... ], or the slice inside a placeholder, {{line[a:b]}}"
                )
            flush(segment)
            if not any(isinstance(part, MirrorSlot) for part in segment):
                raise ValueError(
                    f"template {template!r}: the optional segment closed at position {index} holds no placeholder, "
                    f"so it can never print — put a {{line}} inside it or drop the brackets"
                )
            parts.append(MirrorSegment(tuple(segment)))
            segment = None
        else:
            literal.append(char)
        index += 1
    if segment is not None:
        raise ValueError(f"template {template!r}: an optional segment opened with '[' is never closed with ']'")
    flush(parts)
    if not any(isinstance(part, (MirrorSlot, MirrorSegment)) for part in parts):
        raise ValueError(
            f"template {template!r} names no line — a mirror repeats other lines of the pack, so write at least one "
            f"{{line}} placeholder (a constant would be a value the filler invents)"
        )
    return tuple(parts)


def mirror_sources(template: str) -> tuple[str, ...]:
    """The lines a mirror template reads, in order of first appearance."""
    seen: list[str] = []
    for part in parse_mirror_template(template):
        for slot in part.parts if isinstance(part, MirrorSegment) else (part,):
            if isinstance(slot, MirrorSlot) and slot.line not in seen:
                seen.append(slot.line)
    return tuple(seen)


def mirror_digit_lines(fields: Collection[PackField]) -> frozenset[str]:
    """The lines a mirror slice reads by their digits: every line in an SSN format (Phase K JK28, 2026-10-23).

    fill_form and verify pass it to the renderers below as ``digit_lines``."""
    return frozenset(pf.line for pf in fields if pf.format in SSN_FORMATS)


def _slot_text(slot: MirrorSlot, values: Mapping[str, object], digit_lines: Collection[str] = ()) -> str:
    value = values.get(slot.line)
    text = "" if value is None else _TEMPLATE_WS_RE.sub(" ", str(value)).strip()
    if slot.line in digit_lines and (slot.start is not None or slot.stop is not None):
        # An SSN-format line is sliced by its digits: 'ddd-dd-dddd' (ssn_dash_cells, or a value written with its
        # dashes) and 'ddddddddd' give the same three boxes. A value that is not a number keeps its own characters.
        digits = text.replace("-", "").replace(" ", "")
        if digits.isdigit():
            text = digits
    return text[slot.start:slot.stop]


def render_mirror_pieces(
    template: str, values: Mapping[str, object], *, digit_lines: Collection[str] = ()
) -> list[tuple[str, str | None]]:
    """The pieces :func:`render_mirror` joins, before its whitespace collapse, each with where it came from.

    ``(text, line)`` for a placeholder (the line it reads) and ``(text, None)`` for literal text, in template order,
    with every optional segment that prints expanded in place and every other one left out. Empty when every
    placeholder renders empty. :func:`mirror_words` reads the lines to apply a pack's ``mirror_abbreviations``.
    A slice of a line in ``digit_lines`` (:func:`mirror_digit_lines`: the SSN-format lines) reads its digits.
    """
    pieces: list[tuple[str, str | None]] = []
    for part in parse_mirror_template(template):
        if isinstance(part, MirrorSlot):
            pieces.append((_slot_text(part, values, digit_lines), part.line))
        elif isinstance(part, MirrorSegment):
            inner = [
                (piece, None) if isinstance(piece, str) else (_slot_text(piece, values, digit_lines), piece.line)
                for piece in part.parts
            ]
            if any(text.strip() for text, line in inner if line is not None):
                pieces.extend(inner)
        else:
            pieces.append((part, None))
    return pieces if any(text.strip() for text, line in pieces if line is not None) else []


def render_mirror(template: str, values: Mapping[str, object], *, digit_lines: Collection[str] = ()) -> str:
    """Render a mirror template over ``values`` (line -> its value as fill_form renders it; a missing line is blank).

    The ONE renderer of the template language: fill_form calls it on the rendered values it is about to write and
    verify on the values it reads back from the PDF, so a template means the same thing on both sides. Returns ``""``
    when every placeholder renders empty, whatever literal text the template carries.
    """
    pieces = render_mirror_pieces(template, values, digit_lines=digit_lines)
    return _TEMPLATE_WS_RE.sub(" ", "".join(text for text, _ in pieces)).strip()


def mirror_words(
    template: str, values: Mapping[str, object], shortenable: Collection[str], *, digit_lines: Collection[str] = ()
) -> list[tuple[str, bool]]:
    """The words of :func:`render_mirror`'s value, in order, each flagged True when it may be abbreviated.

    A word may be abbreviated when every character of it comes from a placeholder in ``shortenable`` (the pack's
    ``mirror_abbreviations`` for the mirror): literal text, and a word glued to a line that stays whole, never shorten.
    fill_form builds its abbreviations from these words (:func:`mirror_ladder`) and verify checks a header against them.
    """
    words: list[tuple[str, bool]] = []
    chars: list[str] = []
    may = True
    for text, line in render_mirror_pieces(template, values, digit_lines=digit_lines):
        own = line is not None and line in shortenable
        for char in text:
            if char.isspace():
                if chars:
                    words.append(("".join(chars), may))
                chars, may = [], True
            else:
                chars.append(char)
                may = may and own
    if chars:
        words.append(("".join(chars), may))
    return words


def mirror_ladder(
    template: str, values: Mapping[str, object], shortenable: Collection[str] = (), *,
    digit_lines: Collection[str] = (),
) -> list[str]:
    """The values fill_form tries for a mirror, longest first: it writes the first one the mirror's box holds.

    The template's full value, then, when ``shortenable`` (the pack's ``mirror_abbreviations`` for the mirror) covers
    a word of it (:func:`mirror_words`), two abbreviations: every such word cut to its first letter and every other
    word whole ("A Q WASHINGTON" for "ALEXANDRA Q WASHINGTON"), then only the first such word's letter kept and the
    others left out ("A WASHINGTON"). A rung equal to an earlier one is dropped. Empty when the template renders
    empty. verify computes the value a header must hold from the same ladder (Phase K JK28, 2026-10-16).
    """
    full = render_mirror(template, values, digit_lines=digit_lines)
    if not full:
        return []
    ladder = [full]
    words = mirror_words(template, values, shortenable, digit_lines=digit_lines) if shortenable else []
    may = [index for index, (_, short) in enumerate(words) if short]
    if not may:
        return ladder
    initials = " ".join(word[:1] if short else word for word, short in words)
    lead = may[0]
    first = " ".join(word[:1] if i == lead else word for i, (word, short) in enumerate(words) if not short or i == lead)
    for rung in (initials, first):
        if rung not in ladder:
            ladder.append(rung)
    return ladder


def mirror_order(mirrors: Mapping[str, str]) -> list[str]:
    """The mirror lines in dependency order: a mirror that reads another mirror comes after it.

    Raises :class:`ValueError` naming the loop when mirrors read each other in a cycle (:class:`FormPack` refuses
    one at load, so a validated pack always has an order).
    """
    order: list[str] = []
    state: dict[str, str] = {}

    def visit(mirror: str, path: tuple[str, ...]) -> None:
        if state.get(mirror) == "done":
            return
        if state.get(mirror) == "open":
            loop = " -> ".join((*path[path.index(mirror):], mirror))
            raise ValueError(
                f"mirrors read each other in a cycle ({loop}), so none of them can be built first — build each "
                f"mirror from the page-1 originals, not from another mirror of the loop"
            )
        state[mirror] = "open"
        for source in mirror_sources(mirrors[mirror]):
            if source in mirrors and source != mirror:  # a self-reference has its own refusal (FormPack)
                visit(source, (*path, mirror))
        state[mirror] = "done"
        order.append(mirror)

    for mirror in mirrors:
        visit(mirror, ())
    return order


def _did_you_mean(name: str, lines: Collection[str]) -> str:
    close = difflib.get_close_matches(name, list(lines), n=3)
    return f" (did you mean {', '.join(repr(line) for line in close)}?)" if close else ""


class FormPack(BaseModel):
    """A complete ``pack.yaml`` for one form, one jurisdiction, one tax year."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. '1040-NR', '8843', '540NR'.")
    jurisdiction: str = Field(description="'federal' or 'states/<two-letter code>', e.g. 'states/ca'.")
    tax_year: int = Field(ge=1990, le=2100)
    source_url: str = Field(description="Official URL of the blank PDF (downloaded at runtime, never vendored).")
    mirror_urls: list[str] = Field(
        default_factory=list,
        description=(
            "Exact Wayback Machine snapshots of source_url (https://web.archive.org/web/<14-digit ts>id_/<source_url>), "
            "tried ONLY when the official host answers 401/403 and ALWAYS digest-verified against pdf_sha256 (Phase J "
            "JS1b: mass.gov refuses non-browser fetchers)."
        ),
    )
    pdf_sha256: str = Field(
        description="SHA-256 of the blank PDF for checksum verification; '...' is allowed only as an authoring placeholder."
    )
    acroform_root: str = Field(
        description="XFA-derived AcroForm root name; varies per form (e.g. 'topmostSubform[0]', Sched OI: 'form1040-NR[0]')."
    )
    source_status: Literal["final", "draft"] = Field(
        default="final",
        description=(
            "JT0a: 'draft' for a pack authored drafts-first against an irs.gov/pub/irs-dft/ form (the IRS "
            "cover sheet: \"there are never any changes to the last posted draft of the form and the final "
            "revision of the form\"); only a draft pack may use an irs-dft URL, and only in a provisional year."
        ),
    )
    draft_created: str | None = Field(
        default=None, description="The draft's footer stamp, e.g. '8/19/26' (\"Created 8/19/26\"); drafts only."
    )
    filing_grade_basis: Literal["year_knowledge", "own_final_revision"] = Field(
        default="year_knowledge",
        description=(
            "JT0c: what makes a fill of this pack filing-grade. 'year_knowledge' (every pack by default): the "
            "year's knowledge pack must not be provisional. 'own_final_revision': the form's own FINAL revision "
            "is the authority, so it fills in a provisional year. Allowlisted to the estimated-tax voucher "
            "(OWN_FINAL_REVISION_FORMS): the Form 1040-ES for the year in progress is final and due in that year "
            "(the 2026 Q4 voucher on 2027-01-15), long before the year's return forms are."
        ),
    )
    fields: list[PackField] = Field(min_length=1)
    relations: list[str] = Field(
        default_factory=list,
        description=(
            "Intra-form math relations enforced by the verifier, e.g. '1z == sum(1a..1h)'. One may end in "
            "' unless <checkbox line>' (JK28): verify reports it SKIPPED while that box is checked on the PDF."
        ),
    )
    cross_form: list[str] = Field(
        default_factory=list,
        description="Cross-form consistency rules, e.g. '1k == sched_oi.L1e'.",
    )
    identity_fields: list[str] = Field(
        default_factory=list,
        description="Lines that must match across every form in the filing (name, identifying number, address).",
    )
    identity_per_person: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of identity_fields whose value belongs to ONE PERSON rather than to the "
            "filing, so a difference across forms is legitimate rather than an error. Form 8889's "
            "box is printed 'Social security number of HSA beneficiary' and Form 8606's header is "
            "'If married, file a separate form for each spouse required to file' — on a joint "
            "return either can carry the SPOUSE's SSN while the 1040 carries the primary filer's. "
            "verify reports a difference on these as SKIPPED (visible, does not flip ok) with both "
            "values printed, instead of the FAIL that rejected every correct spouse-owned filing."
        ),
    )
    standalone_only_lines: list[str] = Field(
        default_factory=list,
        description=(
            "Lines the form carries only when it is filed BY ITSELF. Forms 8843, 8606 and 5329 print "
            "'Fill in your address(es) only if you are filing this form by itself and not with your "
            "(U.S.) tax return', so attached to a return their address boxes are correctly BLANK. In a "
            "verify_filing that also holds a Form 1040, 1040-SR, 1040-NR or 1040-X, a blank value on these lines is "
            "neither an identity mismatch nor a missing current address (P-002); a filled one is still checked "
            "against the confirmed current address and against any other form that maps the same line. "
            "Verified alone, the form is treated as filed by itself."
        ),
    )
    mirrors: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Phase K JK28 page-header mirrors: a line that repeats other lines of this pack at the top of a later "
            "page -> the template that builds it, e.g. {'name.full': '{name.first} {name.middle_initial} "
            "{name.last} {name.suffix}'}. fill_form fills a mirror the caller leaves out (FillResult.mirrored), "
            "measured against its box, and verify checks every one on disk (the identity section). The template "
            "language and when to declare one: formpacks/CONVENTIONS.md, 'Page-header mirrors'. Unrelated to "
            "mirror_urls (Wayback copies of the blank)."
        ),
    )
    mirror_abbreviations: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Phase K JK28: a mirror (a key of `mirrors`) -> the placeholders of its template whose words the header "
            "may shorten to a leading part (an initial, with or without a period) or leave out, for a name too wide "
            "for its box; every other placeholder and all literal text stay whole, in order. fill_form abbreviates a "
            "built value its box cannot hold (mirror_ladder: those words cut to initials, then only the first "
            "initial kept), and verify accepts an abbreviation only when the full value does not fit. E.g. "
            "{'name.full': ['name.first', 'name.middle_initial']} keeps name.last and name.suffix whole."
        ),
    )
    signature: Signature | None = Field(
        default=None,
        description="Omitted for attachment-only schedules that carry no signature block of their own.",
    )
    mailing: Mailing | None = Field(
        default=None,
        description="Omitted for schedules mailed inside a parent return's envelope.",
    )

    @field_validator("jurisdiction")
    @classmethod
    def _check_jurisdiction(cls, value: str) -> str:
        if not _JURISDICTION_RE.fullmatch(value):
            raise ValueError(
                f"jurisdiction must be 'federal' or 'states/<two-letter lowercase code>' "
                f"(e.g. 'states/ca'), got {value!r}"
            )
        return value

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, value: str) -> str:
        # source_url drives the only outbound fetch (see fetch.fetch_blank), so enforce the
        # official-government-host guarantee at load time too — shared rule with
        # knowledge.is_official_gov_host (.gov/.mil/*.state.<xx>.us; bare .us is an open
        # registry and is refused). Defence-in-depth alongside the fetch-time allowlist.
        from taxfill_core.knowledge import is_official_gov_host

        value = _require_http_url(value, "source_url")
        host = (urlparse(value).hostname or "").lower()
        if not is_official_gov_host(host):
            raise ValueError(
                f"source_url must point to an official US government host (.gov, .mil, or "
                f"*.state.<xx>.us), got {host!r} — blank forms are downloaded only from "
                f"official government sites"
            )
        return value

    @field_validator("pdf_sha256")
    @classmethod
    def _check_sha256(cls, value: str) -> str:
        if value == _SHA256_PLACEHOLDER:
            # Allowed while authoring a pack; fetch-time verification refuses
            # to download against a placeholder digest.
            return value
        if not _SHA256_RE.fullmatch(value.lower()):
            raise ValueError(
                "pdf_sha256 must be a 64-character hex SHA-256 digest of the blank PDF "
                "(or the literal '...' placeholder while authoring) — "
                "compute it with: shasum -a 256 blank.pdf"
            )
        return value.lower()

    @model_validator(mode="after")
    def _check_mirror_urls(self) -> "FormPack":
        for mirror in self.mirror_urls:
            match = re.fullmatch(r"https://web\.archive\.org/web/(\d{14})id_/(.+)", mirror)
            if match is None or match.group(2) != self.source_url:
                raise ValueError(
                    f"mirror_urls entry {mirror!r} must be an exact Wayback snapshot of THIS pack's source_url — "
                    f"https://web.archive.org/web/<14-digit timestamp>id_/{self.source_url}"
                )
        if self.mirror_urls and self.pdf_sha256 == _SHA256_PLACEHOLDER:
            raise ValueError("mirror_urls need a real pdf_sha256: a mirror is only ever used digest-verified")
        return self

    @model_validator(mode="after")
    def _check_draft_source(self) -> "FormPack":
        # JT0a: an irs-dft URL is a DRAFT form, so it needs the draft status and its footer stamp; a
        # final pack never points at a draft.
        is_dft = "/pub/irs-dft/" in self.source_url
        if self.source_status == "draft":
            if not self.draft_created:
                raise ValueError("a draft pack records draft_created — the 'Created <date>' stamp in the draft's footer")
        elif is_dft or self.draft_created:
            raise ValueError(
                "a final pack cannot use an irs.gov/pub/irs-dft/ source_url or carry draft_created — set "
                "source_status: draft (drafts-first authoring, docs/dev/CONTRIBUTING-PACKS.md) or point at the final form"
            )
        return self

    @model_validator(mode="after")
    def _check_filing_grade_basis(self) -> "FormPack":
        if self.filing_grade_basis == "own_final_revision":
            if (self.jurisdiction, self.form) not in OWN_FINAL_REVISION_FORMS:
                raise ValueError(
                    f"filing_grade_basis: own_final_revision is allowlisted to {sorted(OWN_FINAL_REVISION_FORMS)}; "
                    f"{self.jurisdiction} {self.form} fills against its year's knowledge pack (year_knowledge)"
                )
            if self.source_status != "final" or "/pub/irs-prior/" not in self.source_url:
                raise ValueError(
                    "filing_grade_basis: own_final_revision rests on the form's FINAL revision — source_status final "
                    "and a source_url under irs.gov/pub/irs-prior/"
                )
        return self

    @model_validator(mode="after")
    def _check_unique_lines(self) -> "FormPack":
        seen: set[str] = set()
        for f in self.fields:
            if f.line in seen:
                raise ValueError(
                    f"duplicate line key '{f.line}' in fields[] — each logical line "
                    f"must map to exactly one AcroForm field"
                )
            seen.add(f.line)
        return self

    @model_validator(mode="after")
    def _check_identity_fields_reference_lines(self) -> "FormPack":
        # identity_fields must be logical line keys (the 'line:' values), NOT AcroForm
        # 'field:' names — the verifier's identity cross-check matches on line key, so a
        # field-name entry never matches and turns every filing FAIL (it also silently
        # disables the name/SSN consistency guarantee for that form).
        lines = {f.line for f in self.fields}
        unknown = [k for k in self.identity_fields if k not in lines]
        if unknown:
            raise ValueError(
                f"identity_fields entries must be logical line keys (the 'line:' values), "
                f"not AcroForm 'field:' names — {unknown} match no line in this pack. "
                f"Use line keys, e.g. [name, identifying_number, mailing_address.street]"
            )
        # A per-person entry only means anything for a field the filing actually
        # compares, so it must be declared as an identity field first.
        not_identity = [k for k in self.identity_per_person if k not in set(self.identity_fields)]
        if not_identity:
            raise ValueError(
                f"identity_per_person entries must also appear in identity_fields — {not_identity} "
                f"do not. The flag RELAXES the cross-form comparison for a field, so a field that is "
                f"not compared in the first place has nothing to relax"
            )
        unknown_standalone = [k for k in self.standalone_only_lines if k not in lines]
        if unknown_standalone:
            raise ValueError(
                f"standalone_only_lines entries must be logical line keys (the 'line:' values) — "
                f"{unknown_standalone} match no line in this pack"
            )
        return self

    @model_validator(mode="after")
    def _check_relation_guards(self) -> "FormPack":
        # Phase K JK28: an " unless <line>" guard (split_relation_guard) suspends a relation while a CHECKBOX of this
        # pack is checked on the PDF. A guard naming a money or text line, or no line at all, could never be read as
        # checked, so the relation would be enforced on exactly the return the author meant to exempt — refuse it here.
        types = {f.line: f.type for f in self.fields}
        for relation in self.relations:
            _, guard = split_relation_guard(relation)
            if guard is None:
                continue
            if guard not in types:
                raise ValueError(
                    f"relation {relation!r}: the '{RELATION_GUARD_KEYWORD}' guard names {guard!r}, which is no line "
                    f"key of this pack — name the CHECKBOX line (its 'line:' value) whose check suspends the relation"
                )
            if types[guard] != "checkbox":
                raise ValueError(
                    f"relation {relation!r}: the '{RELATION_GUARD_KEYWORD}' guard names {guard!r}, a {types[guard]} "
                    f"line — a guard must be a CHECKBOX line (verify skips the relation while that box is checked)"
                )
        # cross_form rules take no guard: _cross_form_check would read "x unless box" as the line key "x unless box"
        # of the other form, find nothing and compare against a silent 0.
        for rule in self.cross_form:
            if _GUARD_WORD_RE.search(rule):
                raise ValueError(
                    f"cross_form rule {rule!r}: an '{RELATION_GUARD_KEYWORD}' guard applies to `relations` only — a "
                    f"cross_form rule is checked whenever both forms are in the filing. Drop the guard, or leave the "
                    f"rule undeclared and say why in a comment"
                )
        return self

    @model_validator(mode="after")
    def _check_cross_form_local_refs(self) -> "FormPack":
        # A cross_form operand containing a dot is parsed as '<form_key>.<line>'. A LOCAL
        # line id that itself contains a dot and is digit-led (e.g. '5.b') is misread as
        # form key '5' and the rule is SILENTLY skipped (never PASS/FAIL) — false confidence.
        # Forbid it: rename the line to avoid the dot (e.g. '5_b').
        token_re = re.compile(r"[A-Za-z0-9_.]+")
        for rule in self.cross_form:
            for tok in token_re.findall(rule):
                head, _, rest = tok.partition(".")
                if rest and head.isdigit() and not rest.isdigit():  # digit-led dotted id, not a float literal
                    raise ValueError(
                        f"cross_form rule {rule!r}: operand {tok!r} is a dotted, digit-led local "
                        f"line id — the cross-form parser reads {head!r} as a form key and silently "
                        f"skips the rule. Rename the line to avoid the dot (e.g. {tok.replace('.', '_')!r})."
                    )
        return self

    @model_validator(mode="after")
    def _check_mirrors(self) -> "FormPack":
        # Phase K JK28: a page-header mirror is a TEXT line of this pack that owns its AcroForm field, and its
        # template reads other text or money lines of this pack in an order that exists.
        if not self.mirrors and not self.mirror_abbreviations:
            return self
        by_line = {f.line: f for f in self.fields}
        for mirror, template in self.mirrors.items():
            pack_field = by_line.get(mirror)
            if pack_field is None:
                raise ValueError(
                    f"mirrors: key '{mirror}' is not a line of this pack{_did_you_mean(mirror, by_line)} — a mirror "
                    f"key is the line key (the 'line:' value) of the header box it fills"
                )
            if pack_field.type != "text":
                raise ValueError(
                    f"mirrors: '{mirror}' is a {pack_field.type} line — a page-header mirror repeats a name or an "
                    f"identifying number, so only a text line can be one"
                )
            shared = [f.line for f in self.fields if f.field == pack_field.field and f.line != mirror]
            if shared:
                raise ValueError(
                    f"mirrors: '{mirror}' binds AcroForm field '{pack_field.field}', which {shared} also bind(s) — one "
                    f"write already fills every widget of a shared field, so the mirror is redundant (and building "
                    f"it would overwrite that line); drop the mirrors entry"
                )
            try:
                sources = mirror_sources(template)
            except ValueError as exc:
                raise ValueError(f"mirrors['{mirror}']: {exc}") from None
            if mirror in sources:
                raise ValueError(
                    f"mirrors['{mirror}']: the template {template!r} reads '{mirror}' itself — a mirror is built from "
                    f"OTHER lines (the page-1 originals), never from its own box"
                )
            for source in sources:
                source_field = by_line.get(source)
                if source_field is None:
                    raise ValueError(
                        f"mirrors['{mirror}']: placeholder {{{source}}} names no line of this pack"
                        f"{_did_you_mean(source, by_line)} — a placeholder holds a line key (the 'line:' value), "
                        f"e.g. {{name.last}}"
                    )
                if source_field.type == "checkbox":
                    raise ValueError(
                        f"mirrors['{mirror}']: placeholder {{{source}}} names a checkbox line, which renders as a PDF "
                        f"state name, not text — build the mirror from text or money lines"
                    )
        mirror_order(self.mirrors)  # refuses a cycle, naming it
        for mirror, lines in self.mirror_abbreviations.items():
            if mirror not in self.mirrors:
                raise ValueError(
                    f"mirror_abbreviations: '{mirror}' is not a mirror of this pack"
                    f"{_did_you_mean(mirror, self.mirrors)} — declare its template under mirrors first, then list the "
                    f"placeholders its header may abbreviate"
                )
            pack_field, template = by_line[mirror], self.mirrors[mirror]
            if pack_field.comb or pack_field.format in SSN_FORMATS:
                raise ValueError(
                    f"mirror_abbreviations: '{mirror}' is a comb or ssn_digits_only line, which verify compares digit "
                    f"for digit — an identifying number is never abbreviated; drop the entry"
                )
            sources = mirror_sources(template)
            if not lines:
                raise ValueError(
                    f"mirror_abbreviations['{mirror}'] lists no placeholder — name the lines of {template!r} its "
                    f"header may abbreviate, or drop the entry"
                )
            for line in lines:
                if line not in sources:
                    raise ValueError(
                        f"mirror_abbreviations['{mirror}']: '{line}' is not a placeholder of its template {template!r}"
                        f"{_did_you_mean(line, sources)} — list only lines that template reads ({', '.join(sources)})"
                    )
            repeated = sorted({line for line in lines if lines.count(line) > 1})
            if repeated:
                raise ValueError(
                    f"mirror_abbreviations['{mirror}'] lists {', '.join(repeated)} more than once — name each "
                    f"placeholder once"
                )
            if not set(sources) - set(lines):
                raise ValueError(
                    f"mirror_abbreviations['{mirror}'] lets the header abbreviate every placeholder of {template!r}, "
                    f"so initials alone would pass — leave at least one line whole (on a name header, the last name)"
                )
        return self


# (resolved path, mtime_ns, size) -> the validated pack. A pack is parsed and validated ONCE per file version
# (Phase J JD2: the suite and list_forms re-parsed every pack.yaml on every call — 3 s per list_forms); every
# caller gets its own deep copy, so no caller can mutate another's pack.
_PACK_CACHE: dict[tuple[str, int, int], FormPack] = {}


def load_pack(path: str | Path) -> FormPack:
    """Parse and validate a ``pack.yaml`` file, returning a :class:`FormPack`.

    Raises :class:`ValueError` when the file is not a YAML mapping and
    :class:`pydantic.ValidationError` when the mapping violates the schema.
    A file whose path, modification time and size are unchanged is served from a cache — as a deep copy.
    """
    path = Path(path).expanduser()  # `taxfill seed-blank --pack ~/...` (Phase K JK28)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _PACK_CACHE.get(key)
    if cached is not None:
        return cached.model_copy(deep=True)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{_display(path)}: a form pack must be a YAML mapping (key: value pairs), "
            f"got {type(raw).__name__} — see docs/dev/DEV_PLAN.md section 5 for the schema"
        )
    pack = FormPack.model_validate(raw)
    _PACK_CACHE[key] = pack
    return pack.model_copy(deep=True)



def _display(path) -> str:
    """The data-relative form of a pack path for messages (Phase K JK27; a late import avoids a cycle)."""
    from taxfill_core.datadir import display_path  # noqa: PLC0415

    return display_path(path)
