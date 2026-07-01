"""Verification engine — dev plan section 10.

Verification is an INDEPENDENT pass over what is actually on disk: it never
imports the filler. The small value normalizers below deliberately
reimplement the filler's documented rendering rules so a filler bug cannot
hide behind shared code. Every check maps to a known pitfall id where one
exists (``knowledge/pitfalls.yaml``), and every report lists those pitfalls
as PASS/FAIL so agents and users see the self-check happening.

Documented rendering rules (mirror of the filler's spec, on purpose):

* **money** lines are filled in WHOLE DOLLARS: IRS rounding (50 cents or
  more rounds away from zero), rendered as a plain integer string with no
  commas, currency symbols, or cents (``1234.50 -> "1235"``, ``-2.5 -> "-3"``);
* **comb** fields — and any field with ``format: ssn_digits_only`` — take
  DIGITS ONLY; dashes overflow comb cells (pitfall P-001);
* plain **text** is stripped and internal whitespace runs collapse to one
  space;
* **checkboxes** carry the pack's ``on_state`` when checked and ``"/Off"``
  (or no ``/V`` at all) when not.

Relation grammar (``pack.relations``)::

    relation := expr '==' expr
    expr     := term (('+' | '-') term)*
    term     := unary (('*' | '/') unary)*
    unary    := '-' unary | atom
    atom     := NUMBER | LINE | '(' expr ')'
              | ('max' | 'min') '(' expr (',' expr)* ')'
              | 'sum' '(' LINE '..' LINE ')'
    LINE     := [0-9]+[a-z]?          e.g. '9', '24', '1a'
              | word id               e.g. 'L1e' (letter-led identifier)

Disambiguation rule: a bare integer token (e.g. ``24``) is a LINE REFERENCE
when the pack's field map or the supplied values contain that line key;
otherwise it is a numeric literal (so ``37 == max(0, 24 - 33)`` reads ``0``
as zero). Tokens with a letter suffix and word identifiers are always line
references. ``sum()`` range endpoints must share the same numeric prefix and
carry single lowercase-letter suffixes; the range expands inclusively
(``1a..1h`` -> 1a, 1b, ..., 1h). A referenced line with no supplied value is
treated as 0 (IRS blank-means-zero), but every blank-as-zero substitution is
listed in the report. Evaluation is EXACT-DECIMAL arithmetic (never binary
floats — a multi-operand cent-level sum landing exactly on the .50 boundary
must round like the IRS says, not like float accumulation drifts). Both
sides are compared in whole dollars: exact integer equality after IRS
rounding. Non-finite or non-numeric operand values become FAIL checks (a
data failure, never a crash); only malformed relation STRINGS raise
ValueError (a pack-authoring error).

Disk is the source of truth for relation math and the recompute pass: the
numeric value of every money line found in the on-disk dump is parsed from
the dump itself, and any caller-supplied ``values`` entry for an on-disk
money line is cross-checked against it — divergence is a FAIL. Supplied
values only SUPPLEMENT lines absent from the dump (e.g. another form's
carry-over amounts). A self-consistent ``values`` dict can therefore never
green-light a PDF whose disk state was never checked.

Cross-form grammar (``pack.cross_form``): ``<ref> == <ref>`` where each ref
is either a local line id or ``<form_key>.<line>`` (split at the FIRST dot).
``form_key`` is the caller-assigned key of another :class:`FilingItem`
passed to :func:`verify_filing`.

Clipping heuristic (pitfall P-001): the font size is parsed from the
widget's ``/DA`` default-appearance string (``<size> Tf``); ``0 Tf`` means
auto-size and is safe. Otherwise the estimated text width is
``len(value) * 0.5 * font_size`` — 0.5 is the documented average Helvetica
glyph-width ratio — compared against the widget rectangle width. A missing
``/DA`` conservatively assumes 10 pt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core.schemas.formpack import FormPack, PackField

__all__ = [
    "AssertionCheck",
    "CheckboxCheck",
    "ClippingCheck",
    "CrossFormCheck",
    "FilingItem",
    "IdentityCheck",
    "PitfallCheck",
    "RecomputeCheck",
    "RegressionDiff",
    "RelationCheck",
    "TextWidget",
    "VerifyReport",
    "assertion_diff",
    "checkbox_audit",
    "clipping_scan",
    "digits_only",
    "independent_recompute",
    "irs_round",
    "normalize_text",
    "parse_money",
    "qualified_field_name",
    "read_pdf_fields",
    "read_text_widgets",
    "regression_diff",
    "relations",
    "render_money",
    "verify_filing",
    "verify_form",
]

Status = Literal["PASS", "FAIL", "SKIPPED"]
PASS: Status = "PASS"
FAIL: Status = "FAIL"
# SKIPPED marks a check that could not be evaluated in this run (e.g. a
# cross_form rule whose target form is legitimately not part of the filing).
# Skipped checks stay visible in the report but never flip ``ok`` — silence
# would hide them, FAIL would reject legitimate filings.
SKIPPED: Status = "SKIPPED"

# --- Clipping-scan constants (documented in the module docstring) ----------
_AVG_CHAR_WIDTH_RATIO = 0.5  # average Helvetica glyph width as a fraction of font size
_DEFAULT_FONT_SIZE = 10.0  # conservative assumption when a widget carries no /DA
_FONT_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s+Tf")

_NON_DIGIT_RE = re.compile(r"\D+")
_WS_RE = re.compile(r"\s+")
_LETTER_RANGE_ENDPOINT_RE = re.compile(r"(\d+)([a-z])")


# ---------------------------------------------------------------------------
# Normalizers — small, pure, and intentionally duplicated from the filler's
# documented rules so verification stays an independent pass.
# ---------------------------------------------------------------------------


def irs_round(value: int | float | str | Decimal) -> int:
    """Round to whole dollars per IRS rules: 50 cents or more rounds away from zero."""
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        if not decimal_value.is_finite():  # NaN/Infinity slip through Decimal()
            raise InvalidOperation
        with localcontext() as ctx:
            ctx.prec = 50  # quantize raises above the default 28-digit context
            return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError(
            f"cannot round {value!r} to whole dollars — pass a finite number "
            f"(digits with an optional sign and decimal point)"
        ) from None


def digits_only(value: str) -> str:
    """Strip every non-digit character (comb / ssn_digits_only rendering)."""
    return _NON_DIGIT_RE.sub("", value)


def normalize_text(value: str) -> str:
    """Strip and collapse internal whitespace runs to single spaces."""
    return _WS_RE.sub(" ", value.strip())


def render_money(value: int | float | str | Decimal) -> str:
    """Whole-dollar rendering: plain integer string, no commas/symbols/cents."""
    return str(irs_round(value))


def parse_money(raw: object) -> Decimal | None:
    """Parse a money value from a filled field or an intended value.

    Accepts numbers and strings with optional '$', thousands commas, spaces,
    a leading '-', or accountant parentheses for negatives ('(123)' -> -123).
    Returns None for blank, non-numeric, or non-finite input ('NaN' and
    'Infinity' are not money; callers decide how to report None).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        parsed = Decimal(str(raw))
        return parsed if parsed.is_finite() else None
    text = str(raw).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite():  # Decimal() accepts 'NaN'/'Infinity'; money is finite
        return None
    return -value if negative else value


def _checkbox_is_on(raw: str | None) -> bool:
    """A checkbox is off when /V is absent, empty, or any spelling of /Off."""
    if raw is None:
        return False
    text = raw.strip()
    if not text:
        return False
    return text.lstrip("/").casefold() != "off"


def _checkbox_member_selected(pack: FormPack, pack_field: PackField, fields: Mapping[str, str]) -> bool:
    """True when this group member is the SELECTED option, not just non-/Off.

    Several radio options can share ONE AcroForm field (e.g. filing-status
    c1_3[0] with states /1../5): every member then reads the SAME on-disk
    value, so :func:`_checkbox_is_on` is True for all of them even though one
    option is selected. The selected member is the one whose ``on_state``
    equals the field's value; members on their OWN field read their own
    on_state when checked and /Off otherwise — so matching on_state is the
    one rule that is correct for both shapes.
    """
    raw = _lookup_raw(pack, pack_field, fields)
    if not _checkbox_is_on(raw):
        return False
    on_state = pack_field.on_state or "/1"
    return raw.strip().lstrip("/").casefold() == on_state.strip().lstrip("/").casefold()


def _coerce_checkbox_state(value: object, on_state: str) -> bool:
    """Interpret an intended checkbox value as checked/unchecked."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip()
    if text == on_state:
        return True
    low = text.casefold()
    if low in ("", "off", "/off", "false", "no", "n", "0"):
        return False
    if low in ("true", "yes", "y", "x", "on", "1"):
        return True
    if text.startswith("/"):
        # A slash-led PDF state name that is neither this field's on_state
        # nor /Off: never coerce it to 'checked' — the agent asserted a
        # wrong export value and must be told, not silently passed.
        raise ValueError(
            f"checkbox value {value!r} is ambiguous — it looks like a PDF state name but is neither "
            f"this field's on_state {on_state!r} nor '/Off'; supply true/false (or yes/no), or the "
            f"exact on_state from the pack (the filler writes the pack's on_state when true and /Off "
            f"when false)"
        )
    raise ValueError(
        f"checkbox value {value!r} is ambiguous — supply true/false (or yes/no); "
        f"the filler writes the pack's on_state when true and /Off when false"
    )


def expected_rendering(pack_field: PackField, value: object) -> str:
    """What the filler's documented rules would write to disk for ``value``."""
    if pack_field.type == "checkbox":
        on_state = pack_field.on_state or "/1"
        return on_state if _coerce_checkbox_state(value, on_state) else "/Off"
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""  # an intentional "this line must be blank" assertion
    if pack_field.type == "money":
        parsed = parse_money(value)
        if parsed is None:
            raise ValueError(
                f"line '{pack_field.line}': expected money value {value!r} is not a "
                f"number — pass digits with an optional sign/decimal point "
                f"(the form is filled in whole dollars)"
            )
        return render_money(parsed)
    text = str(value)
    if pack_field.comb or pack_field.format == "ssn_digits_only":
        return digits_only(text)
    return normalize_text(text)


def normalize_on_disk(pack_field: PackField, raw: str) -> str:
    """Normalize an on-disk raw value with the same rules as the intended side."""
    if pack_field.type == "checkbox":
        return raw if _checkbox_is_on(raw) else "/Off"
    if not raw.strip():
        return ""
    if pack_field.type == "money":
        parsed = parse_money(raw)
        return render_money(parsed) if parsed is not None else normalize_text(raw)
    if pack_field.comb or pack_field.format == "ssn_digits_only":
        return digits_only(raw)
    return normalize_text(raw)


def qualified_field_name(pack: FormPack, pack_field: PackField) -> str:
    """Fully qualified AcroForm name: ``<acroform_root>.<field path>``.

    Flat AcroForms (e.g. CA FTB) have top-level field names and an empty
    ``acroform_root``, so the name is the field itself with no leading dot.
    """
    return f"{pack.acroform_root}.{pack_field.field}" if pack.acroform_root else pack_field.field


def _lookup_raw(pack: FormPack, pack_field: PackField, fields: Mapping[str, str]) -> str | None:
    """Find the on-disk raw value for a pack field in a field dump.

    Tries the fully qualified name first, then the bare field path (tolerates
    packs whose ``field`` already includes the root).
    """
    qualified = qualified_field_name(pack, pack_field)
    if qualified in fields:
        return fields[qualified]
    if pack_field.field in fields:
        return fields[pack_field.field]
    return None


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class AssertionCheck(BaseModel):
    """One line of the assertion diff: intended value vs what is on disk."""

    model_config = ConfigDict(extra="forbid")

    line: str
    status: Status
    expected: str
    actual: str | None = None
    detail: str


class RelationCheck(BaseModel):
    """One pack relation evaluated against the supplied line values."""

    model_config = ConfigDict(extra="forbid")

    relation: str
    status: Status
    lhs: int | None = None
    rhs: int | None = None
    blank_as_zero: list[str] = Field(default_factory=list)
    detail: str


class RecomputeCheck(BaseModel):
    """One line of the independent recompute pass (no-LLM-arithmetic rule)."""

    model_config = ConfigDict(extra="forbid")

    line: str
    status: Status
    filled: int | None = None
    recomputed: int
    detail: str


class ClippingCheck(BaseModel):
    """One filled text widget/field checked for MaxLen and width overflow."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Status
    detail: str


class CheckboxCheck(BaseModel):
    """One required checkbox or checkbox group audited for an answer."""

    model_config = ConfigDict(extra="forbid")

    group: str
    status: Status
    members: list[str] = Field(default_factory=list)
    detail: str


class IdentityCheck(BaseModel):
    """One identity field compared across every form in the filing."""

    model_config = ConfigDict(extra="forbid")

    field: str
    status: Status
    values: dict[str, str] = Field(default_factory=dict, description="form_key -> normalized on-disk value.")
    detail: str


class CrossFormCheck(BaseModel):
    """One cross-form relation ('1k == sched_oi.L1e') across filing items."""

    model_config = ConfigDict(extra="forbid")

    form_key: str
    relation: str
    status: Status
    lhs: int | None = None
    rhs: int | None = None
    blank_as_zero: list[str] = Field(default_factory=list)
    detail: str


class RegressionDiff(BaseModel):
    """Field-level diff vs a baseline dump, proving only intended fields changed.

    Informational by design: the verifier cannot know which changes were
    intended, so this section never flips :attr:`VerifyReport.ok` — the
    caller compares the diff against the change it meant to make.
    """

    model_config = ConfigDict(extra="forbid")

    added: dict[str, str] = Field(default_factory=dict, description="name -> new value (absent from baseline).")
    removed: dict[str, str] = Field(default_factory=dict, description="name -> old value (absent from current dump).")
    changed: dict[str, tuple[str, str]] = Field(default_factory=dict, description="name -> (old, new).")

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


class PitfallCheck(BaseModel):
    """One known-pitfall self-check (knowledge/pitfalls.yaml) shown PASS/FAIL."""

    model_config = ConfigDict(extra="forbid")

    id: str
    status: Status
    detail: str


class TextWidget(BaseModel):
    """Geometry + appearance of one text widget, as the clipping scan needs it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str = ""
    max_len: int | None = Field(default=None, ge=1, description="PDF /MaxLen (e.g. comb cell count).")
    da: str | None = Field(
        default=None,
        description="PDF /DA default-appearance string, e.g. '/Helv 9 Tf 0 g'; '0 Tf' means auto-size.",
    )
    rect_width: float = Field(default=0.0, ge=0.0, description="Widget rectangle width in points; 0 when unknown.")


class VerifyReport(BaseModel):
    """Aggregated verification report for one form or a whole filing.

    ``ok`` is True only when every check in every section passes —
    except :attr:`regression`, which is informational (see RegressionDiff).
    ``pitfall_checks`` always covers at least P-001 (clipping) and P-003
    (required checkboxes); :func:`verify_filing` adds P-002
    (address/identity), and :func:`verify_form` adds it when
    ``confirmed_current_address`` is supplied.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    form_keys: list[str] = Field(default_factory=list)
    assertions: list[AssertionCheck] = Field(default_factory=list)
    relations: list[RelationCheck] = Field(default_factory=list)
    recompute: list[RecomputeCheck] = Field(default_factory=list)
    clipping: list[ClippingCheck] = Field(default_factory=list)
    checkboxes: list[CheckboxCheck] = Field(default_factory=list)
    identity: list[IdentityCheck] = Field(default_factory=list)
    cross_form: list[CrossFormCheck] = Field(default_factory=list)
    regression: RegressionDiff | None = None
    blank_as_zero: list[str] = Field(default_factory=list)
    pitfall_checks: list[PitfallCheck] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# PDF reading — thin, isolated pypdf layer (everything else works on dicts)
# ---------------------------------------------------------------------------


def _pdf_text(value: object) -> str:
    """Decode a PDF string value to str (pypdf can hand back raw bytes).

    pypdf returns a ByteStringObject (a ``bytes`` subclass) when a string is
    not valid PDFDocEncoding/UTF-16; plain ``str()`` would render ``b'...'``.
    """
    if isinstance(value, bytes):
        if value.startswith((b"\xfe\xff", b"\xff\xfe")):
            try:
                return value.decode("utf-16")
            except UnicodeDecodeError:
                pass
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return str(value)


def read_pdf_fields(pdf_path: str | Path) -> dict[str, str]:
    """Dump ``{fully_qualified_field_name: raw_value}`` from a filled PDF."""
    from pypdf import PdfReader  # local import keeps the pypdf layer isolated

    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"no PDF at {path} — pass the filled PDF written by fill_form "
            f"(check the workspace drafts/ directory) or a blank from fetch_blank"
        )
    reader = PdfReader(str(path))
    raw_fields = reader.get_fields()
    if not raw_fields:
        raise ValueError(
            f"{path} has no AcroForm fields — it is not a fillable form; "
            f"re-download the blank with fetch_blank from the pack's official "
            f"source_url and refill it"
        )
    dump: dict[str, str] = {}
    for name, field in raw_fields.items():
        value = field.get("/V")
        dump[name] = "" if value is None else _pdf_text(value)
    return dump


def _inherited(obj: Mapping, key: str) -> object | None:
    """Resolve a possibly inherited PDF dictionary key via the /Parent chain."""
    node, hops = obj, 0
    while node is not None and hops < 64:
        if key in node:
            return node[key]
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        hops += 1
    return None


def _widget_qualified_name(obj: Mapping) -> str:
    """Join /T parts up the /Parent chain into a fully qualified field name."""
    parts: list[str] = []
    node, hops = obj, 0
    while node is not None and hops < 64:
        title = node.get("/T")
        if title:
            parts.append(str(title))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        hops += 1
    return ".".join(reversed(parts))


def read_text_widgets(pdf_path: str | Path) -> list[TextWidget]:
    """Collect every text widget's value, /MaxLen, /DA and rect width via pypdf."""
    from pypdf import PdfReader  # local import keeps the pypdf layer isolated

    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"no PDF at {path} — pass the filled PDF written by fill_form "
            f"(check the workspace drafts/ directory)"
        )
    reader = PdfReader(str(path))
    acroform = reader.trailer["/Root"].get("/AcroForm")
    default_da = acroform.get_object().get("/DA") if acroform is not None else None

    widgets: list[TextWidget] = []
    for page in reader.pages:
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            if _inherited(annot, "/FT") != "/Tx":
                continue
            # Skip read-only text widgets (Ff bit 1, ReadOnly). They cannot
            # receive taxpayer input, so the filler never writes them; any
            # value present is a decorative/banner default baked into the blank
            # (e.g. NC D-400's fixed-18pt "PRINT" banner, IL-1040's "Help"
            # tooltip). Scanning them for clipping yields false positives on a
            # value the user can neither change nor see clipped.
            flags = _inherited(annot, "/Ff")
            if flags is not None and int(flags) & 1:
                continue
            rect = annot.get("/Rect")
            rect_width = abs(float(rect[2]) - float(rect[0])) if rect else 0.0
            value = _inherited(annot, "/V")
            max_len = _inherited(annot, "/MaxLen")
            da = _inherited(annot, "/DA") or default_da
            widgets.append(
                TextWidget(
                    name=_widget_qualified_name(annot),
                    value="" if value is None else _pdf_text(value),
                    max_len=int(max_len) if max_len is not None and int(max_len) >= 1 else None,
                    da=_pdf_text(da) if da is not None else None,
                    rect_width=rect_width,
                )
            )
    return widgets


# ---------------------------------------------------------------------------
# Assertion diff — every filled field re-read from disk vs intended values
# ---------------------------------------------------------------------------


def assertion_diff(
    pack: FormPack,
    fields: Mapping[str, str],
    expected: Mapping[str, object],
) -> list[AssertionCheck]:
    """Per-line PASS/FAIL comparing on-disk values against intended values.

    Both sides are normalized with the documented rendering rules, so a
    formatting difference (commas, dashes, whitespace) that renders the same
    value passes, while a value difference fails. Render safety (clipping)
    is checked separately by :func:`clipping_scan` — a dashed SSN can match
    its intended digits here and still fail the clipping scan (P-001).
    """
    by_line = {f.line: f for f in pack.fields}
    checks: list[AssertionCheck] = []
    for line, want in expected.items():
        pack_field = by_line.get(line)
        if pack_field is None:
            checks.append(
                AssertionCheck(
                    line=line,
                    status=FAIL,
                    expected=str(want),
                    detail=(
                        f"line '{line}' is not in the {pack.form} pack's field map — "
                        f"list the valid line keys with get_form_map('{pack.form}', "
                        f"{pack.tax_year}) and resubmit using one of those"
                    ),
                )
            )
            continue
        try:
            want_rendered = expected_rendering(pack_field, want)
        except ValueError as exc:
            checks.append(AssertionCheck(line=line, status=FAIL, expected=str(want), detail=str(exc)))
            continue
        raw = _lookup_raw(pack, pack_field, fields)
        if raw is None:
            checks.append(
                AssertionCheck(
                    line=line,
                    status=FAIL,
                    expected=want_rendered,
                    detail=(
                        f"field '{qualified_field_name(pack, pack_field)}' is missing from "
                        f"the PDF dump — refill the form with fill_form, or fix the pack's "
                        f"acroform_root/field path if the blank truly lacks this field"
                    ),
                )
            )
            continue
        actual_normalized = normalize_on_disk(pack_field, raw)
        if actual_normalized == want_rendered:
            checks.append(
                AssertionCheck(
                    line=line,
                    status=PASS,
                    expected=want_rendered,
                    actual=raw,
                    detail=f"on-disk value matches the intended value for line '{line}'",
                )
            )
        else:
            checks.append(
                AssertionCheck(
                    line=line,
                    status=FAIL,
                    expected=want_rendered,
                    actual=raw,
                    detail=(
                        f"line '{line}': intended {want_rendered!r} but the PDF carries "
                        f"{raw!r} (normalized {actual_normalized!r}) — refill the line "
                        f"with fill_form and re-verify"
                    ),
                )
            )
    return checks


# ---------------------------------------------------------------------------
# Relation math — safe mini-evaluator (no eval()), grammar in module docstring
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<float>\d+\.\d+)"
    r"|(?P<lineid>\d+[a-z]?)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>==|\.\.|[+\-*/(),])"
)


def _grammar_error(relation: str, reason: str) -> ValueError:
    return ValueError(
        f"could not parse relation '{relation}': {reason} — supported grammar is "
        f"'<expr> == <expr>' with + - * / parentheses, max(...), min(...), and "
        f"sum(1a..1h) ranges over digit+letter line ids; fix the relation string "
        f"in pack.yaml (see the verify module docstring for the full grammar)"
    )


def _tokenize(relation: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(relation):
        match = _TOKEN_RE.match(relation, pos)
        if match is None:
            raise _grammar_error(relation, f"unexpected character {relation[pos]!r} at position {pos}")
        if match.lastgroup != "ws":
            tokens.append((match.lastgroup or "", match.group()))
        pos = match.end()
    return tokens


class _Tokens:
    """A token stream with prescriptive parse errors."""

    def __init__(self, relation: str) -> None:
        self.relation = relation
        self.items = _tokenize(relation)
        self.pos = 0

    def peek(self) -> tuple[str | None, str | None]:
        if self.pos < len(self.items):
            return self.items[self.pos]
        return (None, None)

    def next(self) -> tuple[str, str]:
        kind, text = self.peek()
        if kind is None or text is None:
            raise _grammar_error(self.relation, "unexpected end of expression")
        self.pos += 1
        return kind, text

    def expect_op(self, op: str) -> None:
        kind, text = self.peek()
        if kind != "op" or text != op:
            found = repr(text) if kind is not None else "end of expression"
            raise _grammar_error(self.relation, f"expected '{op}' but found {found}")
        self.pos += 1


class _BadOperand(Exception):
    """A line value that is not a finite number (data failure, not grammar)."""

    def __init__(self, line: str, value: object) -> None:
        super().__init__(line)
        self.line = line
        self.value = value


def _parse_expr(toks: _Tokens, line_names: frozenset[str], resolve) -> Decimal:
    value = _parse_term(toks, line_names, resolve)
    while True:
        kind, text = toks.peek()
        if kind == "op" and text in ("+", "-"):
            toks.next()
            right = _parse_term(toks, line_names, resolve)
            value = value + right if text == "+" else value - right
        else:
            return value


def _parse_term(toks: _Tokens, line_names: frozenset[str], resolve) -> Decimal:
    value = _parse_unary(toks, line_names, resolve)
    while True:
        kind, text = toks.peek()
        if kind == "op" and text in ("*", "/"):
            toks.next()
            right = _parse_unary(toks, line_names, resolve)
            value = value * right if text == "*" else value / right
        else:
            return value


def _parse_unary(toks: _Tokens, line_names: frozenset[str], resolve) -> Decimal:
    kind, text = toks.peek()
    if kind == "op" and text == "-":
        toks.next()
        return -_parse_unary(toks, line_names, resolve)
    return _parse_atom(toks, line_names, resolve)


def _parse_args(toks: _Tokens, line_names: frozenset[str], resolve) -> list[Decimal]:
    toks.expect_op("(")
    args = [_parse_expr(toks, line_names, resolve)]
    while toks.peek() == ("op", ","):
        toks.next()
        args.append(_parse_expr(toks, line_names, resolve))
    toks.expect_op(")")
    return args


def _parse_sum_range(toks: _Tokens, resolve) -> Decimal:
    toks.expect_op("(")
    start_kind, start = toks.next()
    toks.expect_op("..")
    end_kind, end = toks.next()
    toks.expect_op(")")
    start_match = _LETTER_RANGE_ENDPOINT_RE.fullmatch(start) if start_kind == "lineid" else None
    end_match = _LETTER_RANGE_ENDPOINT_RE.fullmatch(end) if end_kind == "lineid" else None
    if (
        start_match is None
        or end_match is None
        or start_match.group(1) != end_match.group(1)
        or ord(end_match.group(2)) < ord(start_match.group(2))
    ):
        raise _grammar_error(
            toks.relation,
            f"sum() range '{start}..{end}' is invalid — endpoints must share the same "
            f"numeric prefix and carry single lowercase-letter suffixes in order, "
            f"e.g. sum(1a..1h)",
        )
    prefix = start_match.group(1)
    return sum(
        (
            resolve(f"{prefix}{chr(code)}")
            for code in range(ord(start_match.group(2)), ord(end_match.group(2)) + 1)
        ),
        Decimal(0),
    )


def _parse_atom(toks: _Tokens, line_names: frozenset[str], resolve) -> Decimal:
    kind, text = toks.next()
    if kind == "float":
        return Decimal(text)
    if kind == "lineid":
        if text.isdigit() and text not in line_names:
            return Decimal(text)  # bare integer not mapped anywhere -> numeric literal
        return resolve(text)
    if kind == "name":
        if toks.peek() == ("op", "("):
            if text == "sum":
                return _parse_sum_range(toks, resolve)
            if text in ("max", "min"):
                args = _parse_args(toks, line_names, resolve)
                return max(args) if text == "max" else min(args)
            raise _grammar_error(
                toks.relation, f"unknown function '{text}' — supported functions: max(), min(), sum()"
            )
        return resolve(text)
    if kind == "op" and text == "(":
        value = _parse_expr(toks, line_names, resolve)
        toks.expect_op(")")
        return value
    raise _grammar_error(toks.relation, f"unexpected token {text!r}")


def _eval_relation_sides(
    relation: str,
    values: Mapping[str, float | int | Decimal],
    line_names: frozenset[str],
) -> tuple[Decimal, Decimal, list[str]]:
    """Evaluate both sides of '<expr> == <expr>' in exact Decimal; returns (lhs, rhs, blanks)."""
    blanks: list[str] = []

    def resolve(line: str) -> Decimal:
        value = values.get(line)
        if value is None:
            blanks.append(line)
            return Decimal(0)
        if isinstance(value, bool):
            raise _BadOperand(line, value)
        try:
            # str() round-trips the shortest float repr, so 50.4 stays
            # exactly 50.4 — never the binary 50.39999... artifact.
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise _BadOperand(line, value) from None
        if not number.is_finite():
            raise _BadOperand(line, value)
        return number

    toks = _Tokens(relation)
    lhs = _parse_expr(toks, line_names, resolve)
    toks.expect_op("==")
    rhs = _parse_expr(toks, line_names, resolve)
    trailing_kind, trailing = toks.peek()
    if trailing_kind is not None:
        raise _grammar_error(relation, f"unexpected trailing token {trailing!r}")
    return lhs, rhs, list(dict.fromkeys(blanks))


def evaluate_expression(
    expr: str,
    values: Mapping[str, float | int | Decimal],
    line_names: frozenset[str] | None = None,
) -> Decimal:
    """Evaluate ONE arithmetic expression in the relation grammar against ``values``.

    Supports ``+ - * /``, parentheses, ``max()/min()/sum(1a..1h)`` and line-id
    references — the same grammar the verifier uses for ``lhs == rhs`` relations,
    exposed here for one-sided evaluation. Missing/blank refs count as 0
    (IRS blank-means-zero). ``line_names`` is the set of ids that are real lines
    (a bare integer NOT in the set is a numeric literal); defaults to ``values`` keys.
    Raises :class:`ValueError` on a malformed expression (a pack-authoring error).

    This is the compute engine behind the hand-fill worksheet for print-only forms
    (:mod:`taxfill_core.handfill`).
    """
    names = frozenset(line_names) if line_names is not None else frozenset(values)

    def resolve(line: str) -> Decimal:
        value = values.get(line)
        if value is None:
            return Decimal(0)
        if isinstance(value, bool):
            raise _BadOperand(line, value)
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise _BadOperand(line, value) from None
        if not number.is_finite():
            raise _BadOperand(line, value)
        return number

    toks = _Tokens(expr)
    result = _parse_expr(toks, names, resolve)
    trailing_kind, trailing = toks.peek()
    if trailing_kind is not None:
        raise _grammar_error(expr, f"unexpected trailing token {trailing!r}")
    return result


def _check_relation(
    relation: str,
    values: Mapping[str, float | int | Decimal],
    line_names: frozenset[str],
) -> RelationCheck:
    try:
        lhs, rhs, blanks = _eval_relation_sides(relation, values, line_names)
    except (ZeroDivisionError, InvalidOperation):
        # decimal raises DivisionByZero (a ZeroDivisionError) for x/0 and
        # InvalidOperation for 0/0 — both are the same data failure here.
        return RelationCheck(
            relation=relation,
            status=FAIL,
            detail=(
                f"division by zero while evaluating '{relation}' — a denominator line "
                f"is blank or zero; fill the denominator line (blank lines count as 0) "
                f"or correct the relation in pack.yaml"
            ),
        )
    except _BadOperand as exc:
        return RelationCheck(
            relation=relation,
            status=FAIL,
            detail=(
                f"line '{exc.line}' carries a non-numeric or non-finite value {exc.value!r} — "
                f"relation math needs finite dollar amounts; refill the line (or correct the "
                f"supplied value) and re-verify"
            ),
        )
    except RecursionError:
        raise _grammar_error(
            relation,
            "the expression nests too deeply to evaluate — flatten the parentheses",
        ) from None
    try:
        lhs_dollars, rhs_dollars = irs_round(lhs), irs_round(rhs)
    except ValueError:
        return RelationCheck(
            relation=relation,
            status=FAIL,
            detail=(
                f"a side of '{relation}' evaluates to an amount that cannot be rounded to whole "
                f"dollars (non-finite or astronomically large) — check the relation's literals in "
                f"pack.yaml and the line values, then re-verify"
            ),
        )
    blank_note = f"; blank-as-zero: {', '.join(blanks)}" if blanks else ""
    if lhs_dollars == rhs_dollars:
        return RelationCheck(
            relation=relation,
            status=PASS,
            lhs=lhs_dollars,
            rhs=rhs_dollars,
            blank_as_zero=blanks,
            detail=f"{lhs_dollars} == {rhs_dollars} (whole dollars, IRS rounding){blank_note}",
        )
    return RelationCheck(
        relation=relation,
        status=FAIL,
        lhs=lhs_dollars,
        rhs=rhs_dollars,
        blank_as_zero=blanks,
        detail=(
            f"relation '{relation}' failed: left side = {lhs_dollars}, right side = "
            f"{rhs_dollars} (difference {lhs_dollars - rhs_dollars:+d}){blank_note} — "
            f"recompute the input lines with calc and refill them, then re-verify"
        ),
    )


def relations(pack: FormPack, values: Mapping[str, float | int | Decimal]) -> list[RelationCheck]:
    """Evaluate every ``pack.relations`` entry against the supplied line values.

    Missing lines count as 0 (IRS blank-means-zero) and each substitution is
    listed in the check's ``blank_as_zero``. Arithmetic is exact Decimal and
    sides are compared in whole dollars (exact integer equality after IRS
    rounding). Non-finite or non-numeric values become FAIL checks; only
    malformed relation strings raise :class:`ValueError` (a pack-authoring
    error, not a data failure) with a prescriptive message.

    Note: :func:`verify_form` / :func:`verify_filing` derive the values for
    on-disk money lines from the PDF dump itself — call them rather than
    feeding this function self-reported numbers.
    """
    line_names = frozenset(f.line for f in pack.fields) | frozenset(values)
    return [_check_relation(relation, values, line_names) for relation in pack.relations]


# ---------------------------------------------------------------------------
# Disk-derived line values — relation math and the recompute pass run on what
# is actually in the PDF, never on a caller's self-reported numbers alone
# ---------------------------------------------------------------------------


def _disk_money_values(
    pack: FormPack, fields: Mapping[str, str]
) -> tuple[dict[str, Decimal], set[str], dict[str, str]]:
    """Money line values as actually on disk: (parsed, blank lines, garbage raw)."""
    parsed: dict[str, Decimal] = {}
    blank: set[str] = set()
    garbage: dict[str, str] = {}
    for pack_field in pack.fields:
        if pack_field.type != "money":
            continue
        raw = _lookup_raw(pack, pack_field, fields)
        if raw is None:
            continue  # field absent from the dump entirely
        if not raw.strip():
            blank.add(pack_field.line)
            continue
        value = parse_money(raw)
        if value is None:
            garbage[pack_field.line] = raw
        else:
            parsed[pack_field.line] = value
    return parsed, blank, garbage


def _merge_disk_and_supplied(
    pack: FormPack,
    fields: Mapping[str, str],
    supplied: Mapping[str, float | int] | None,
) -> tuple[dict[str, float | int | Decimal], list[AssertionCheck]]:
    """Numeric line values for relation/cross-form/recompute math, tied to disk.

    The on-disk dump is authoritative for every money line it contains;
    caller-supplied values only supplement lines absent from the dump and are
    cross-checked against the disk otherwise — divergence, a non-numeric
    money value on disk, or a non-finite supplied value each become a FAIL
    check (reported in the assertions section).
    """
    parsed, blank, garbage = _disk_money_values(pack, fields)
    checks: list[AssertionCheck] = []
    for line, raw in sorted(garbage.items()):
        checks.append(
            AssertionCheck(
                line=line,
                status=FAIL,
                expected="a numeric whole-dollar amount",
                actual=raw,
                detail=(
                    f"money line '{line}' carries non-numeric text {raw!r} on disk — relation math "
                    f"and the independent recompute run on the ON-DISK numbers; refill the line via "
                    f"fill_form with the calc result and re-verify"
                ),
            )
        )
    merged: dict[str, float | int | Decimal] = dict(parsed)
    for line, value in (supplied or {}).items():
        if line in garbage:
            continue  # already failed above; nothing trustworthy to compare
        try:
            supplied_dollars = irs_round(value)
        except (ValueError, TypeError):
            checks.append(
                AssertionCheck(
                    line=line,
                    status=FAIL,
                    expected="a finite number",
                    actual=str(value),
                    detail=(
                        f"the value supplied to the verifier for line '{line}' is not a finite "
                        f"number ({value!r}) — resubmit a plain dollar amount"
                    ),
                )
            )
            continue
        if line in merged:
            disk_dollars = irs_round(merged[line])
            if supplied_dollars != disk_dollars:
                checks.append(
                    AssertionCheck(
                        line=line,
                        status=FAIL,
                        expected=str(supplied_dollars),
                        actual=str(merged[line]),
                        detail=(
                            f"line '{line}': the verifier was given {supplied_dollars} but the PDF "
                            f"carries {disk_dollars} on disk — relation math and the recompute run "
                            f"on the ON-DISK number; refill the line via fill_form (or correct the "
                            f"supplied value) and re-verify"
                        ),
                    )
                )
            # The disk value stays authoritative either way.
        elif line in blank:
            if supplied_dollars != 0:
                checks.append(
                    AssertionCheck(
                        line=line,
                        status=FAIL,
                        expected=str(supplied_dollars),
                        actual="",
                        detail=(
                            f"line '{line}': the verifier was given {supplied_dollars} but the line "
                            f"is BLANK on disk (blank means 0) — fill the line via fill_form with "
                            f"the calc result and re-verify"
                        ),
                    )
                )
            else:
                merged[line] = 0  # blank-means-zero, confirmed by the caller
        else:
            merged[line] = value  # supplement: line not on this form's dump
    return merged, checks


# ---------------------------------------------------------------------------
# Independent recompute — the verifier's half of the no-LLM-arithmetic rule
# ---------------------------------------------------------------------------


def independent_recompute(
    values: Mapping[str, float | int | Decimal],
    independent: Mapping[str, float | int],
) -> list[RecomputeCheck]:
    """Diff filled values against independently recomputed numbers.

    ``independent`` comes from a second pass of the calc engine over the
    versioned data packs (the caller supplies it); this function only
    compares, in whole dollars. Relation math proves internal consistency —
    this pass proves agreement with the authoritative tables.
    """
    checks: list[RecomputeCheck] = []
    for line, number in independent.items():
        recomputed = irs_round(number)
        filled_raw = values.get(line)
        if filled_raw is None:
            checks.append(
                RecomputeCheck(
                    line=line,
                    status=FAIL,
                    recomputed=recomputed,
                    detail=(
                        f"line '{line}' was independently recomputed as {recomputed} but no "
                        f"filled value was supplied — fill the line via fill_form with the "
                        f"calc result, or drop it from the recompute set if it is not on "
                        f"this form"
                    ),
                )
            )
            continue
        filled = irs_round(filled_raw)
        if filled == recomputed:
            checks.append(
                RecomputeCheck(
                    line=line,
                    status=PASS,
                    filled=filled,
                    recomputed=recomputed,
                    detail=f"line '{line}': filled value {filled} matches the independent recompute",
                )
            )
        else:
            checks.append(
                RecomputeCheck(
                    line=line,
                    status=FAIL,
                    filled=filled,
                    recomputed=recomputed,
                    detail=(
                        f"line '{line}': filled value {filled} disagrees with the independent "
                        f"recompute {recomputed} — the filled number must come from calc over "
                        f"the versioned tables (no-LLM-arithmetic rule); rerun calc, refill "
                        f"the line, and re-verify"
                    ),
                )
            )
    return checks


# ---------------------------------------------------------------------------
# Clipping scan — pitfall P-001
# ---------------------------------------------------------------------------


def _font_size_from_da(da: str | None) -> float | None:
    """Parse the font size from a /DA string; None when no '<size> Tf' found."""
    if not da:
        return None
    match = _FONT_SIZE_RE.search(da)
    return float(match.group(1)) if match else None


def _coerce_widgets(source: Sequence[TextWidget | Mapping]) -> list[TextWidget]:
    return [w if isinstance(w, TextWidget) else TextWidget.model_validate(w) for w in source]


def clipping_scan(source: str | Path | Sequence[TextWidget | Mapping]) -> list[ClippingCheck]:
    """Flag filled text widgets whose value would clip (pitfall P-001).

    Accepts a filled PDF path or pre-parsed :class:`TextWidget` records
    (plain dicts are coerced). Two checks per non-empty widget, in order:

    1. ``len(value) > /MaxLen`` — hard clipping; the PDF silently drops the
       overflow (invisible in field dumps; this is the P-001 SSN incident);
    2. width heuristic — ``len(value) * 0.5 * font_size`` vs the widget rect
       width; ``0 Tf`` auto-size is safe; a missing /DA assumes 10 pt.
    """
    widgets = read_text_widgets(source) if isinstance(source, (str, Path)) else _coerce_widgets(source)
    checks: list[ClippingCheck] = []
    for widget in widgets:
        if not widget.value:
            continue  # nothing written, nothing to clip
        length = len(widget.value)
        if widget.max_len is not None and length > widget.max_len:
            overflow = length - widget.max_len
            checks.append(
                ClippingCheck(
                    name=widget.name,
                    status=FAIL,
                    detail=(
                        f"value is {length} characters but MaxLen is {widget.max_len} — the "
                        f"last {overflow} character(s) would be silently clipped (pitfall "
                        f"P-001); shorten the value and refill (SSN/EIN comb fields take "
                        f"digits only: use format 'ssn_digits_only')"
                    ),
                )
            )
            continue
        font_size = _font_size_from_da(widget.da)
        if font_size == 0:
            checks.append(
                ClippingCheck(
                    name=widget.name,
                    status=PASS,
                    detail="auto-sized font (0 Tf) — the viewer shrinks text to fit; safe",
                )
            )
            continue
        assumed = ""
        if font_size is None:
            font_size = _DEFAULT_FONT_SIZE
            assumed = " (no /DA on the widget; assumed 10pt)"
        if widget.rect_width <= 0:
            checks.append(
                ClippingCheck(
                    name=widget.name,
                    status=PASS,
                    detail=(
                        "widget width unknown (rect width 0) — width heuristic skipped; "
                        "MaxLen check passed, confirm visually with render_form"
                    ),
                )
            )
            continue
        estimated = length * _AVG_CHAR_WIDTH_RATIO * font_size
        if estimated > widget.rect_width:
            checks.append(
                ClippingCheck(
                    name=widget.name,
                    status=FAIL,
                    detail=(
                        f"estimated text width {estimated:.1f}pt (len {length} x 0.5 x "
                        f"{font_size:g}pt Helvetica heuristic{assumed}) exceeds the widget "
                        f"width {widget.rect_width:.1f}pt — text may be visually clipped "
                        f"(pitfall P-001); shorten the value or switch the field to "
                        f"auto-size, then re-render to confirm"
                    ),
                )
            )
        else:
            checks.append(
                ClippingCheck(
                    name=widget.name,
                    status=PASS,
                    detail=(
                        f"fits: estimated {estimated:.1f}pt within the {widget.rect_width:.1f}pt "
                        f"widget{assumed}"
                    ),
                )
            )
    return checks


def _pack_maxlen_checks(
    pack: FormPack,
    fields: Mapping[str, str],
    skip_names: frozenset[str] = frozenset(),
) -> list[ClippingCheck]:
    """MaxLen-only clipping checks derived from the pack (no geometry needed).

    Lets P-001 be checked from a plain field dump even when widget geometry
    was not parsed. Fields already covered by a scanned widget are skipped.
    """
    checks: list[ClippingCheck] = []
    for pack_field in pack.fields:
        if pack_field.type == "checkbox" or pack_field.maxlen is None:
            continue
        qualified = qualified_field_name(pack, pack_field)
        # A widget covers this field only on a whole-name-component match:
        # exact, or a '.'-boundary suffix (a deeper root). A bare endswith()
        # would let 'OtherPage1[0].f1_7[0]' suppress 'Page1[0].f1_7[0]'.
        dotted_suffix = f".{pack_field.field}"
        if any(
            name == qualified or name == pack_field.field or name.endswith(dotted_suffix)
            for name in skip_names
        ):
            continue
        raw = _lookup_raw(pack, pack_field, fields)
        if not raw:
            continue
        length = len(raw)
        if length > pack_field.maxlen:
            overflow = length - pack_field.maxlen
            checks.append(
                ClippingCheck(
                    name=f"{qualified} (line {pack_field.line})",
                    status=FAIL,
                    detail=(
                        f"value is {length} characters but the pack's maxlen is "
                        f"{pack_field.maxlen} — the last {overflow} character(s) would be "
                        f"silently clipped (pitfall P-001); refill line '{pack_field.line}' "
                        f"with a value that fits (comb fields take digits only)"
                    ),
                )
            )
        else:
            checks.append(
                ClippingCheck(
                    name=f"{qualified} (line {pack_field.line})",
                    status=PASS,
                    detail=f"{length} character(s) within maxlen {pack_field.maxlen}",
                )
            )
    return checks


# ---------------------------------------------------------------------------
# Checkbox audit — pitfall P-003
# ---------------------------------------------------------------------------


def checkbox_audit(pack: FormPack, fields: Mapping[str, str]) -> list[CheckboxCheck]:
    """Audit required checkboxes and required checkbox groups (pitfall P-003).

    A group is required when ANY member is marked ``required``; it fails when
    every member is /Off (the question was silently left unanswered — the
    8843 line 12 / Sched OI item I incident). Ungrouped required checkboxes
    fail individually when /Off. Every group (required or not) also fails when
    MORE than one member is checked: the options of one question are mutually
    exclusive (the two-filing-status incident). Non-required ungrouped boxes
    are not audited.
    """
    groups: dict[str, list[PackField]] = {}
    singles: list[PackField] = []
    for pack_field in pack.fields:
        if pack_field.type != "checkbox":
            continue
        if pack_field.group:
            groups.setdefault(pack_field.group, []).append(pack_field)
        elif pack_field.required:
            singles.append(pack_field)

    checks: list[CheckboxCheck] = []
    for group_id, members in groups.items():
        member_lines = [member.line for member in members]
        # Count SELECTED members, not merely non-/Off ones: radio options
        # sharing one field all read the same value, so on_state-matching is
        # the only count that is right for both radio and separate-field groups.
        on_lines = [
            member.line
            for member in members
            if _checkbox_member_selected(pack, member, fields)
        ]
        # At-most-one holds for every group, required or not: the members of
        # one question are mutually exclusive, so >1 checked is always invalid.
        if len(on_lines) > 1:
            checks.append(
                CheckboxCheck(
                    group=group_id,
                    status=FAIL,
                    members=member_lines,
                    detail=(
                        f"checkbox group '{group_id}' has {len(on_lines)} boxes checked "
                        f"({', '.join(on_lines)}) — exactly one is allowed; the options of one "
                        f"question are mutually exclusive, so uncheck all but one via fill_form "
                        f"and re-verify"
                    ),
                )
            )
            continue
        if not any(member.required for member in members):
            continue
        if on_lines:
            checks.append(
                CheckboxCheck(
                    group=group_id,
                    status=PASS,
                    members=member_lines,
                    detail=f"required checkbox group '{group_id}' is answered (at least one box checked)",
                )
            )
        else:
            checks.append(
                CheckboxCheck(
                    group=group_id,
                    status=FAIL,
                    members=member_lines,
                    detail=(
                        f"required checkbox group '{group_id}' is unanswered — every member "
                        f"is /Off (pitfall P-003); answer the question by setting exactly one "
                        f"of {', '.join(member_lines)} to true via fill_form, then re-verify"
                    ),
                )
            )
    for pack_field in singles:
        if _checkbox_is_on(_lookup_raw(pack, pack_field, fields)):
            checks.append(
                CheckboxCheck(
                    group=pack_field.line,
                    status=PASS,
                    members=[pack_field.line],
                    detail=f"required checkbox '{pack_field.line}' is checked",
                )
            )
        else:
            checks.append(
                CheckboxCheck(
                    group=pack_field.line,
                    status=FAIL,
                    members=[pack_field.line],
                    detail=(
                        f"required checkbox '{pack_field.line}' is unanswered (/Off) — "
                        f"set it to true via fill_form (pitfall P-003); if this is one box "
                        f"of a yes/no question, give both boxes a shared 'group' in the pack"
                    ),
                )
            )
    return checks


# ---------------------------------------------------------------------------
# Regression diff
# ---------------------------------------------------------------------------


def regression_diff(fields: Mapping[str, str], baseline: Mapping[str, str]) -> RegressionDiff:
    """Field-level diff of the current dump vs a baseline dump.

    Proves "only intended fields changed": compare the result against the
    edit you meant to make. Purely informational — see :class:`RegressionDiff`.
    """
    added = {name: value for name, value in fields.items() if name not in baseline}
    removed = {name: value for name, value in baseline.items() if name not in fields}
    changed = {
        name: (baseline[name], fields[name])
        for name in fields
        if name in baseline and fields[name] != baseline[name]
    }
    return RegressionDiff(added=added, removed=removed, changed=changed)


# ---------------------------------------------------------------------------
# Cross-form verification — verify_filing
# ---------------------------------------------------------------------------


class FilingItem(BaseModel):
    """One form of the filing as :func:`verify_filing` needs it."""

    model_config = ConfigDict(extra="forbid")

    form_key: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Caller-assigned key other forms' cross_form rules use, e.g. 'sched_oi'.",
    )
    pack: FormPack
    fields: dict[str, str] | None = Field(
        default=None, description="On-disk field dump (read_pdf_fields output)."
    )
    pdf_path: Path | None = Field(default=None, description="Filled PDF to dump when 'fields' is not given.")
    values: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Supplemental numeric line values for relation/cross-form math. The on-disk dump is "
            "authoritative for money lines it contains: entries here are cross-checked against the "
            "disk (divergence fails) and only supplement lines absent from the dump."
        ),
    )

    @model_validator(mode="after")
    def _check_disk_source(self) -> "FilingItem":
        if self.fields is None and self.pdf_path is None:
            raise ValueError(
                f"filing item '{self.form_key}': supply 'fields' (a read_pdf_fields dump) "
                f"or 'pdf_path' (the filled PDF) — verification re-reads what is actually "
                f"on disk"
            )
        return self

    def on_disk_fields(self) -> dict[str, str]:
        if self.fields is not None:
            return self.fields
        assert self.pdf_path is not None  # guaranteed by _check_disk_source
        return read_pdf_fields(self.pdf_path)


class _MissingFormKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _cross_form_check(
    rule: str,
    form_key: str,
    values_by_key: Mapping[str, Mapping[str, float | int | Decimal]],
) -> CrossFormCheck:
    """One cross-form rule, evaluated over the disk-derived per-form values."""
    sides = [side.strip() for side in rule.split("==")]
    if len(sides) != 2 or not all(sides):
        raise ValueError(
            f"cross_form rule '{rule}' on form '{form_key}' must be "
            f"'<ref> == <ref>' with exactly one '==', where each ref is a local line "
            f"id or '<form_key>.<line>' — fix the rule in pack.yaml"
        )
    blanks: list[str] = []

    def resolve(ref: str) -> Decimal:
        if "." in ref:
            key, line = ref.split(".", 1)
            target = values_by_key.get(key)
            if target is None:
                raise _MissingFormKey(key)
            value = target.get(line)
            label = f"{key}.{line}"
        else:
            value = values_by_key[form_key].get(ref)
            label = f"{form_key}.{ref}"
        if value is None:
            blanks.append(label)
            return Decimal(0)
        return Decimal(str(value))

    try:
        lhs, rhs = resolve(sides[0]), resolve(sides[1])
    except _MissingFormKey as exc:
        # A filing legitimately omits schedules it does not need; the rule is
        # skipped (visibly), not failed. If the side that IS present carries a
        # nonzero amount, warn: that amount usually must flow through the
        # absent form, so the agent must confirm the schedule is not required.
        caution = ""
        for side in sides:
            try:
                present = resolve(side)
            except _MissingFormKey:
                continue
            if present != 0:
                caution = (
                    f" — caution: '{side}' is {irs_round(present)} (nonzero); if that "
                    f"amount flows through '{exc.key}', attach that form to the filing "
                    f"and re-verify"
                )
        return CrossFormCheck(
            form_key=form_key,
            relation=rule,
            status=SKIPPED,
            detail=(
                f"cross_form rule '{rule}' not checked: form_key '{exc.key}' is not part "
                f"of this filing (normal when the schedule is not required){caution}"
            ),
        )
    lhs_dollars, rhs_dollars = irs_round(lhs), irs_round(rhs)
    blank_note = f"; blank-as-zero: {', '.join(blanks)}" if blanks else ""
    if lhs_dollars == rhs_dollars:
        return CrossFormCheck(
            form_key=form_key,
            relation=rule,
            status=PASS,
            lhs=lhs_dollars,
            rhs=rhs_dollars,
            blank_as_zero=blanks,
            detail=f"{lhs_dollars} == {rhs_dollars} (whole dollars){blank_note}",
        )
    return CrossFormCheck(
        form_key=form_key,
        relation=rule,
        status=FAIL,
        lhs=lhs_dollars,
        rhs=rhs_dollars,
        blank_as_zero=blanks,
        detail=(
            f"cross_form rule '{rule}' failed on '{form_key}': left side = "
            f"{lhs_dollars}, right side = {rhs_dollars}{blank_note} — the two forms "
            f"disagree; recompute with calc, refill the wrong form, and re-verify"
        ),
    )


def _identity_checks(
    items: Sequence[FilingItem],
    fields_by_key: Mapping[str, Mapping[str, str]],
) -> list[IdentityCheck]:
    identity_names: list[str] = []
    for item in items:
        for name in item.pack.identity_fields:
            if name not in identity_names:
                identity_names.append(name)

    checks: list[IdentityCheck] = []
    for name in identity_names:
        values_by_form: dict[str, str] = {}
        for item in items:
            pack_field = next((f for f in item.pack.fields if f.line == name), None)
            if pack_field is None:
                continue  # schedules legitimately omit some identity lines
            raw = _lookup_raw(item.pack, pack_field, fields_by_key[item.form_key]) or ""
            values_by_form[item.form_key] = normalize_on_disk(pack_field, raw)
        if not values_by_form:
            checks.append(
                IdentityCheck(
                    field=name,
                    status=FAIL,
                    detail=(
                        f"identity field '{name}' is declared in identity_fields but no "
                        f"pack in this filing maps a line with that key — add the line to "
                        f"fields[] in the pack(s) or remove it from identity_fields"
                    ),
                )
            )
            continue
        listing = ", ".join(f"{key}={value!r}" for key, value in values_by_form.items())
        distinct = {value.casefold() for value in values_by_form.values()}
        if distinct == {""}:
            checks.append(
                IdentityCheck(
                    field=name,
                    status=FAIL,
                    values=values_by_form,
                    detail=(
                        f"identity field '{name}' is blank on every form ({listing}) — "
                        f"fill it on each form via fill_form before verifying"
                    ),
                )
            )
        elif len(distinct) > 1:
            checks.append(
                IdentityCheck(
                    field=name,
                    status=FAIL,
                    values=values_by_form,
                    detail=(
                        f"identity field '{name}' differs across the filing: {listing} — "
                        f"every form must carry the same value; refill the mismatched "
                        f"form(s). For addresses, use the user's CURRENT mailing address "
                        f"(where they receive mail TODAY — pitfall P-002)"
                    ),
                )
            )
        else:
            sample = next(iter(values_by_form.values()))
            scope = (
                f"matches on all {len(values_by_form)} forms"
                if len(values_by_form) > 1
                else "present on one form only — nothing to cross-check"
            )
            checks.append(
                IdentityCheck(
                    field=name,
                    status=PASS,
                    values=values_by_form,
                    detail=f"identity field '{name}' {scope}: {sample!r}",
                )
            )
    return checks


_ADDR_TOKEN_RE = re.compile(r"[a-z0-9]+")

# USPS street/unit/directional abbreviations + full state names, canonicalized to ONE
# form so "100 Current Street, Illinois" and "100 Current St, IL" compare equal. The
# form/user may abbreviate either side, so both sides are canonicalized before diffing.
_ADDR_CANON = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
    "lane": "ln", "court": "ct", "circle": "cir", "place": "pl", "terrace": "ter",
    "parkway": "pkwy", "highway": "hwy", "square": "sq", "trail": "trl", "way": "way",
    "apartment": "apt", "suite": "ste", "unit": "unit", "building": "bldg",
    "floor": "fl", "room": "rm", "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "post": "po", "box": "box",
}
_STATE_CANON = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa", "wisconsin": "wi",
    "wyoming": "wy",
}
# Tokens that carry no address identity (country designators, filler).
_ADDR_NOISE = {"usa", "us", "united", "states", "of", "the", "and"}


def _addr_tokens(text: str) -> set[str]:
    """Canonical address tokens, lowercased — order/punctuation/abbreviation-agnostic."""
    out = set()
    for tok in _ADDR_TOKEN_RE.findall(text.casefold()):
        tok = _ADDR_CANON.get(tok, _STATE_CANON.get(tok, tok))
        if tok not in _ADDR_NOISE:
            out.add(tok)
    return out


# Which pack lines hold the FILER's own current mailing address. Shipped packs name it
# many ways (mailing_address.street, home_address + city + zip_code, address_line1, ...),
# and many packs also carry addresses that must NOT participate (preparer, spouse-deceased,
# physician, school, landlord, moving-expense, MD's separate PHYSICAL address, ...).
# _FILER_ADDR_INCLUDE selects candidate lines; _FILER_ADDR_EXCLUDE vetoes non-filer ones.
# test_verify pins the exact per-pack selection as a reviewed golden fixture, so a new
# pack whose address lines fall through gets caught by the suite, not in production.
_FILER_ADDR_INCLUDE = re.compile(
    r"""(?ix)^ (?:voucher_\d+\.)? (?:
          mailing_address (?:$|[._])           # mailing_address, .street/.city/..., _line1
        | (?:current_home_|home_|present_)?address (?:_?line_?\d)? $
        | mailing_(?:city|zip|state) \w*
        | city (?:_(?:or_)?(?:town|post_office))? (?:_or_post_office)? (?:_town_post_office)? $
        | city_town_or_post_office $
        | state $
        | zip (?:_?code|_or_postal_code|_ext)? $
        | d\.zip (?:code|ext) $                 # MO's letter-prefixed zip cells
    )"""
)
_FILER_ADDR_EXCLUDE = re.compile(
    r"(?i)spouse|preparer|prep|firm|employer|physician|landlord|school|schhbc|business|"
    r"foreign|home_country|email|crp|movexp|nri_|physical|deceased|estate|voucher\.name|"
    r"^22[ab]\.|in_care_of|care_of"
)


def _is_filer_address_line(line: str) -> bool:
    return bool(_FILER_ADDR_INCLUDE.match(line)) and not _FILER_ADDR_EXCLUDE.search(line)


def _confirmed_address_checks(
    forms: Sequence[tuple[str, FormPack, Mapping[str, str]]],
    confirmed_current_address: str,
) -> list[IdentityCheck]:
    """Compare each form's TAXPAYER MAILING address against the user-confirmed current address.

    Pitfall P-002's original shape: ONE wrong historical address landing consistently on
    every form passes the cross-form consistency check — only a comparison against the
    address the user confirmed they receive mail at TODAY can catch it.

    Only the FILER's own mailing address participates (see ``_is_filer_address_line``);
    preparer/spouse/physician/school/landlord/physical/foreign addresses are excluded.
    Component-split addresses are joined, both sides are canonicalized (USPS
    abbreviations + state names), and the canonical token SETS must match exactly —
    symmetric, so a wrong house number ('10' vs '100'), a missing city, an extra unit,
    or a stale street all FAIL, while 'Street' vs 'St' and 'Illinois' vs 'IL' PASS.
    A participating form whose address lines are all blank FAILs explicitly (a blank
    return address is exactly the P-002 hazard).
    """
    if not normalize_text(confirmed_current_address):
        raise ValueError(
            "confirmed_current_address is blank — pass the user's CURRENT mailing address "
            "(where they receive mail TODAY, from intake), or omit the parameter"
        )
    want_tokens = _addr_tokens(confirmed_current_address)
    field_label = "mailing_address (vs user-confirmed current address)"

    per_form: dict[str, dict[str, str]] = {}
    participating: set[str] = set()
    for key, pack, fields in forms:
        for pack_field in pack.fields:
            if pack_field.type == "checkbox" or not _is_filer_address_line(pack_field.line):
                continue
            participating.add(key)
            raw = _lookup_raw(pack, pack_field, fields)
            if raw is None:
                continue
            value = normalize_on_disk(pack_field, raw)
            if value:
                per_form.setdefault(key, {})[pack_field.line] = value

    if not participating:
        return [
            IdentityCheck(
                field=field_label,
                status=FAIL,
                detail=(
                    "confirmed_current_address was supplied but no pack in this filing maps a "
                    "filer mailing-address line — map the taxpayer's mailing address (e.g. "
                    "'mailing_address.street' / 'home_address' + 'city' + 'zip_code') so the "
                    "P-002 cross-check can run, or omit the parameter"
                ),
            )
        ]

    checks: list[IdentityCheck] = []
    for key in sorted(participating):
        comps = per_form.get(key)
        if not comps:
            checks.append(
                IdentityCheck(
                    field=field_label,
                    status=FAIL,
                    detail=(
                        f"form {key!r} maps filer mailing-address lines but they are all BLANK — "
                        f"fill the current mailing address via fill_form and re-verify (a blank "
                        f"return address is pitfall P-002: IRS mail cannot reach the filer)"
                    ),
                )
            )
            continue
        on_disk = ", ".join(comps[k] for k in sorted(comps))
        disk_tokens = _addr_tokens(on_disk)
        missing = sorted(want_tokens - disk_tokens)
        extra = sorted(disk_tokens - want_tokens)
        if missing or extra:
            checks.append(
                IdentityCheck(
                    field=field_label,
                    status=FAIL,
                    values=comps,
                    detail=(
                        f"form {key!r} mailing address {on_disk!r} differs from the user-confirmed "
                        f"CURRENT mailing address {confirmed_current_address!r}"
                        f"{' (missing: ' + ', '.join(missing) + ')' if missing else ''}"
                        f"{' (unexpected: ' + ', '.join(extra) + ')' if extra else ''} — "
                        f"a consistent but outdated address still sends IRS bills and notices to the "
                        f"wrong place (pitfall P-002); refill the mailing address and re-verify"
                    ),
                )
            )
        else:
            checks.append(
                IdentityCheck(
                    field=field_label,
                    status=PASS,
                    values=comps,
                    detail=(
                        f"form {key!r} mailing address {on_disk!r} matches the user-confirmed current "
                        f"mailing address"
                    ),
                )
            )
    return checks


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _all_pass(*sections: Sequence) -> bool:
    """True when no check failed (SKIPPED checks are visible but non-fatal)."""
    return all(check.status != FAIL for section in sections for check in section)


def _aggregate_blanks(*sections: Sequence) -> list[str]:
    seen: dict[str, None] = {}
    for section in sections:
        for check in section:
            for blank in check.blank_as_zero:
                seen.setdefault(blank, None)
    return list(seen)


def _pitfall_p001(clipping: Sequence[ClippingCheck]) -> PitfallCheck:
    failures = sum(1 for check in clipping if check.status == FAIL)
    if failures:
        return PitfallCheck(
            id="P-001",
            status=FAIL,
            detail=(
                f"clipping scan: {failures} of {len(clipping)} filled text field(s) would "
                f"clip — see the clipping section; shorten the value(s) (comb fields take "
                f"digits only), refill, and re-verify"
            ),
        )
    detail = (
        f"clipping scan clean: {len(clipping)} filled text field(s) checked "
        f"(MaxLen + Helvetica width heuristic; auto-size is safe)"
        if clipping
        else "clipping scan: no filled text fields to check"
    )
    return PitfallCheck(id="P-001", status=PASS, detail=detail)


def _pitfall_p002(identity: Sequence[IdentityCheck]) -> PitfallCheck:
    address_checks = [check for check in identity if "address" in check.field.casefold()]
    if not address_checks:
        return PitfallCheck(
            id="P-002",
            status=PASS,
            detail=(
                "no address identity field declared — add 'mailing_address' to "
                "identity_fields in the packs to enable the current-address cross-check"
            ),
        )
    failures = [check for check in address_checks if check.status == FAIL]
    if failures:
        return PitfallCheck(
            id="P-002",
            status=FAIL,
            detail=(
                "the return address is inconsistent across the filing or differs from the "
                "user-confirmed current address — see the identity section; refill with the "
                "user's CURRENT mailing address (where they receive mail TODAY, not a "
                "historical address)"
            ),
        )
    confirmed = any("user-confirmed" in check.field for check in address_checks)
    addresses = [value for check in address_checks for value in check.values.values()]
    used = addresses[0] if addresses else ""
    if confirmed:
        return PitfallCheck(
            id="P-002",
            status=PASS,
            detail=(
                f"address used across the filing: {used!r} — matches the user-confirmed "
                f"current mailing address"
            ),
        )
    return PitfallCheck(
        id="P-002",
        status=PASS,
        detail=(
            f"address used across the filing: {used!r} — confirm this is where the user "
            f"receives mail TODAY (the IRS sends bills and notices here); pass "
            f"confirmed_current_address to verify_filing to make this check exact"
        ),
    )


def _pitfall_p003(checkboxes: Sequence[CheckboxCheck]) -> PitfallCheck:
    failures = sum(1 for check in checkboxes if check.status == FAIL)
    if failures:
        return PitfallCheck(
            id="P-003",
            status=FAIL,
            detail=(
                f"required-checkbox audit: {failures} of {len(checkboxes)} required "
                f"checkbox(es)/group(s) unanswered — see the checkboxes section; answer "
                f"each named group via fill_form and re-verify"
            ),
        )
    detail = (
        f"required-checkbox audit clean: {len(checkboxes)} required checkbox(es)/group(s) answered"
        if checkboxes
        else "required-checkbox audit: no required checkboxes declared in this pack"
    )
    return PitfallCheck(id="P-003", status=PASS, detail=detail)


def verify_form(
    pack: FormPack,
    fields: Mapping[str, str] | str | Path,
    *,
    expected: Mapping[str, object] | None = None,
    values: Mapping[str, float | int] | None = None,
    independent: Mapping[str, float | int] | None = None,
    widgets: Sequence[TextWidget | Mapping] | None = None,
    baseline: Mapping[str, str] | None = None,
    confirmed_current_address: str | None = None,
) -> VerifyReport:
    """Run every single-form check and aggregate a :class:`VerifyReport`.

    ``fields`` may be a field dump (dict) or a filled-PDF path (then the dump
    and, unless ``widgets`` is given, the widget geometry are read from disk).

    Relation math and the independent recompute are tied to DISK: the value
    of every money line present in the dump is parsed from the dump itself;
    ``values`` entries are cross-checked against the disk (divergence is a
    FAIL in the assertions section) and only supplement lines absent from
    the dump. ``expected`` adds the per-line assertion diff; ``baseline``
    adds the informational regression diff; ``confirmed_current_address``
    (the address the user receives mail at TODAY, from intake) adds the
    P-002 address comparison. Clipping and the checkbox audit always run;
    ``pitfall_checks`` always reports P-001 and P-003, plus P-002 when
    ``confirmed_current_address`` is given.
    """
    if isinstance(fields, (str, Path)):
        pdf_path = Path(fields)
        fields = read_pdf_fields(pdf_path)
        if widgets is None:
            widgets = read_text_widgets(pdf_path)
    widget_models = _coerce_widgets(widgets or [])

    merged_values, value_checks = _merge_disk_and_supplied(pack, fields, values)
    assertion_checks = (
        assertion_diff(pack, fields, expected) if expected is not None else []
    ) + value_checks
    relation_checks = relations(pack, merged_values)
    recompute_checks = (
        independent_recompute(merged_values, independent) if independent is not None else []
    )
    clipping_checks = clipping_scan(widget_models) + _pack_maxlen_checks(
        pack, fields, skip_names=frozenset(w.name for w in widget_models)
    )
    checkbox_checks = checkbox_audit(pack, fields)
    identity_checks = (
        _confirmed_address_checks([(pack.form, pack, fields)], confirmed_current_address)
        if confirmed_current_address is not None
        else []
    )
    regression = regression_diff(fields, baseline) if baseline is not None else None

    pitfall_checks = [_pitfall_p001(clipping_checks)]
    if confirmed_current_address is not None:
        pitfall_checks.append(_pitfall_p002(identity_checks))
    pitfall_checks.append(_pitfall_p003(checkbox_checks))

    return VerifyReport(
        ok=_all_pass(
            assertion_checks,
            relation_checks,
            recompute_checks,
            clipping_checks,
            checkbox_checks,
            identity_checks,
        ),
        form_keys=[pack.form],
        assertions=assertion_checks,
        relations=relation_checks,
        recompute=recompute_checks,
        clipping=clipping_checks,
        checkboxes=checkbox_checks,
        identity=identity_checks,
        regression=regression,
        blank_as_zero=_aggregate_blanks(relation_checks),
        pitfall_checks=pitfall_checks,
    )


def verify_filing(
    items: Sequence[FilingItem | Mapping],
    *,
    independent: Mapping[str, Mapping[str, float | int]] | None = None,
    confirmed_current_address: str | None = None,
) -> VerifyReport:
    """Verify a whole filing: identity consistency + cross-form relations.

    Each item also gets its own relation math, required-checkbox audit, and
    pack-maxlen clipping checks (section entries are prefixed with the item's
    ``form_key``). Relation and cross-form math run on DISK-derived money
    values; each item's ``values`` are cross-checked against its dump and
    only supplement lines absent from it (divergence is a FAIL in the
    assertions section). ``independent`` (keyed ``form_key -> {line: expected}``,
    mirroring :func:`verify_form`) runs the independent recompute against each
    item's disk-derived values — the verifier's half of the no-LLM-arithmetic
    rule, guarding the table-lookup lines (1040 line 16/13/19/27, 1040-NR
    16/23a) that no relation covers. ``confirmed_current_address`` (the address
    the user receives mail at TODAY, from intake) compares every on-disk
    address line against it — the P-002 incident shape where ONE wrong
    historical address lands consistently on every form. ``pitfall_checks``
    reports P-001, P-002 (the address used across the filing), and P-003.
    """
    filing_items = [item if isinstance(item, FilingItem) else FilingItem.model_validate(item) for item in items]
    if not filing_items:
        raise ValueError(
            "verify_filing needs at least one filing item — pass "
            "[{form_key, pack, fields|pdf_path, values}] for every form in the filing"
        )
    items_by_key: dict[str, FilingItem] = {}
    for item in filing_items:
        if item.form_key in items_by_key:
            raise ValueError(
                f"duplicate form_key '{item.form_key}' — give every filing item a unique "
                f"key (cross_form rules resolve targets by form_key)"
            )
        items_by_key[item.form_key] = item
    fields_by_key = {item.form_key: item.on_disk_fields() for item in filing_items}

    # Disk-derived numeric values per form (caller values cross-checked).
    values_by_key: dict[str, Mapping[str, float | int | Decimal]] = {}
    value_checks: list[AssertionCheck] = []
    for item in filing_items:
        merged, checks = _merge_disk_and_supplied(item.pack, fields_by_key[item.form_key], item.values)
        values_by_key[item.form_key] = merged
        value_checks.extend(
            check.model_copy(update={"line": f"{item.form_key}: {check.line}"}) for check in checks
        )

    if independent is not None:
        unknown_keys = sorted(set(independent) - set(items_by_key))
        if unknown_keys:
            raise ValueError(
                f"independent recompute references unknown form_key(s) {unknown_keys} — "
                f"key the recompute set by the filing items' form_key(s) {sorted(items_by_key)}"
            )

    relation_checks: list[RelationCheck] = []
    recompute_checks: list[RecomputeCheck] = []
    clipping_checks: list[ClippingCheck] = []
    checkbox_checks: list[CheckboxCheck] = []
    cross_form_checks: list[CrossFormCheck] = []
    for item in filing_items:
        item_fields = fields_by_key[item.form_key]
        relation_checks.extend(
            check.model_copy(update={"relation": f"{item.form_key}: {check.relation}"})
            for check in relations(item.pack, values_by_key[item.form_key])
        )
        if independent is not None and item.form_key in independent:
            recompute_checks.extend(
                check.model_copy(update={"line": f"{item.form_key}: {check.line}"})
                for check in independent_recompute(
                    values_by_key[item.form_key], independent[item.form_key]
                )
            )
        item_widgets = read_text_widgets(item.pdf_path) if item.fields is None and item.pdf_path else []
        clipping_checks.extend(
            check.model_copy(update={"name": f"{item.form_key}: {check.name}"})
            for check in clipping_scan(item_widgets)
            + _pack_maxlen_checks(item.pack, item_fields, skip_names=frozenset(w.name for w in item_widgets))
        )
        checkbox_checks.extend(
            check.model_copy(update={"group": f"{item.form_key}: {check.group}"})
            for check in checkbox_audit(item.pack, item_fields)
        )
        cross_form_checks.extend(
            _cross_form_check(rule, item.form_key, values_by_key) for rule in item.pack.cross_form
        )
    identity_checks = _identity_checks(filing_items, fields_by_key)
    if confirmed_current_address is not None:
        identity_checks.extend(
            _confirmed_address_checks(
                [(item.form_key, item.pack, fields_by_key[item.form_key]) for item in filing_items],
                confirmed_current_address,
            )
        )

    return VerifyReport(
        ok=_all_pass(
            value_checks,
            relation_checks,
            recompute_checks,
            clipping_checks,
            checkbox_checks,
            identity_checks,
            cross_form_checks,
        ),
        form_keys=[item.form_key for item in filing_items],
        assertions=value_checks,
        relations=relation_checks,
        recompute=recompute_checks,
        clipping=clipping_checks,
        checkboxes=checkbox_checks,
        identity=identity_checks,
        cross_form=cross_form_checks,
        blank_as_zero=_aggregate_blanks(relation_checks, cross_form_checks),
        pitfall_checks=[
            _pitfall_p001(clipping_checks),
            _pitfall_p002(identity_checks),
            _pitfall_p003(checkbox_checks),
        ],
    )
