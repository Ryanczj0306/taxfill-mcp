"""Deterministic AcroForm fill — dev plan sections 3, 10 and 11.

:func:`fill_form` writes a values dict (keyed by the pack's logical *line*
ids) into a blank official PDF, driven entirely by the form pack's
line-to-field map. Hard rules:

- **Never invent a value.** Only lines present in the values dict are
  touched; everything else stays exactly as it is in the blank PDF.
- **No model arithmetic.** This module formats and writes; every number must
  arrive already computed by ``calc`` (the verifier independently recomputes
  it later).
- **Prescriptive errors** (dev plan section 11): every failure says exactly
  what to do next, so a weak agent can self-correct mechanically.

pypdf specifics encoded here (dev plan section 10):

- checkboxes need BOTH the field ``/V`` and the widget ``/AS`` set to the
  pack's ``on_state`` (pitfall P-003 territory: a ``/V`` without ``/AS``
  renders unchecked);
- radio groups (IRS filing status etc.) are ONE ``/Btn`` field whose
  ``/T``-less kid widgets each carry a different on-state in their
  ``/AP /N`` dict; the pack maps every option as its own checkbox line on
  the SAME field with its own ``on_state`` — the chosen state lands as
  ``/AS`` only on the kid that defines it, sibling kids go ``/Off``, and
  ``/V`` is set once on the shared field dict;
- ``update_page_form_field_values(..., auto_regenerate=False)``, then the
  AcroForm ``NeedAppearances`` flag is set so viewers regenerate appearance
  streams;
- comb fields take digits only, and ``format: ssn_digits_only`` strips
  dashes/spaces *before* the MaxLen check — a dashed SSN written into a
  9-cell comb field silently clips its last digits (pitfall P-001);
- no identifying-number box ever takes the literal ``'NRA'`` (pitfall
  P-026). An MFS filer whose nonresident-alien spouse has no SSN/ITIN and
  needs none writes 'NRA' in the MFS ENTRY SPACE below the filing status
  checkboxes (Instructions for Form 1040, Married Filing Separately) — an
  ordinary text line (``filing_status.spouse_or_qualifying_person_name`` on
  the 2023/2024 packs, ``filing_status.mfs_spouse_name`` on 2025) — and
  leaves the spouse-SSN comb blank. Every ``ssn_digits_only`` or comb line
  refuses 'NRA' with an error naming the pack's entry-space line.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject

from taxfill_core.knowledge import assert_pack_filing_grade, provisional_marker
from taxfill_core.redact import redact
from taxfill_core.schemas.formpack import FormPack, PackField

# The one input-normalization format the filler understands today.
# Add new formats here AND in the docstring of PackField.format.
_SSN_DIGITS_ONLY = "ssn_digits_only"
_KNOWN_FORMATS = frozenset({_SSN_DIGITS_ONLY})

# P-026. An MFS filer whose nonresident-alien spouse has (and needs) no
# SSN/ITIN writes the literal 'NRA' in the MFS ENTRY SPACE, never in the
# spouse-SSN box: the Instructions for Form 1040, Married Filing Separately,
# say "Be sure to enter your spouse's SSN or ITIN in the space for spouse's
# SSN" and, for a spouse with none, "enter 'NRA' in the entry space" (the
# 2023/2024 text adds "below the filing status checkboxes"). So NO
# identifying-number or comb line accepts it; the entry space is an ordinary
# text line and takes it as text.
_NRA_LITERAL = "NRA"

# The MFS entry space by pack key, with the instruction text for the revision
# that uses it. The key is read from the pack itself (never assumed from the
# year): the 2023/2024 Form 1040 packs and every Form 1040-X pack carry
# 'filing_status.spouse_or_qualifying_person_name'; the 2025 Form 1040 pack
# carries 'filing_status.mfs_spouse_name'.
_MFS_ENTRY_SPACE_LINES: tuple[str, ...] = (
    "filing_status.mfs_spouse_name",
    "filing_status.spouse_or_qualifying_person_name",
)
_NRA_INSTRUCTION_1040: dict[int, str] = {
    2023: (
        "Instructions for Form 1040 (2023), Married Filing Separately: \"Be sure to enter your "
        "spouse's SSN or Individual Taxpayer Identification Number (ITIN) in the space for "
        "spouse's SSN on Form 1040 or 1040-SR. If your spouse doesn't have and isn't required "
        "to have an SSN or ITIN, enter 'NRA' in the entry space below the filing status "
        "checkboxes.\""
    ),
    2024: (
        "Instructions for Form 1040 (2024), Married Filing Separately: \"Be sure to enter your "
        "spouse's SSN or ITIN in the space for spouse's SSN on Form 1040 or 1040-SR. If your "
        "spouse doesn't have and isn't required to have an SSN or ITIN, enter 'NRA' in the "
        "entry space below the filing status checkboxes.\""
    ),
    2025: (
        "Instructions for Form 1040 (2025), Married Filing Separately: \"Be sure to enter "
        "your spouse's SSN or ITIN in the space for spouse's SSN on Form 1040 or 1040-SR. If "
        "your spouse doesn't have and isn't required to have an SSN or ITIN, enter 'NRA' in "
        "the entry space.\""
    ),
}
_NRA_INSTRUCTION_1040X = (
    "Instructions for Form 1040-X (Rev. December 2025), Changing to married filing "
    "separately: \"If your spouse doesn't have and isn't required to have an SSN or ITIN, "
    "enter 'NRA' next to their name in the entry space below the filing status checkboxes.\""
)


def _nra_refusal(pack: FormPack | None, pf: PackField) -> str:
    """The prescriptive refusal for 'NRA' on an identifying-number / comb line (P-026)."""
    lines = {f.line for f in pack.fields} if pack is not None else set()
    entry = next((key for key in _MFS_ENTRY_SPACE_LINES if key in lines), None)
    form = pack.form if pack is not None else None
    if form == "1040-X":
        quote = _NRA_INSTRUCTION_1040X
    else:
        # The pack's own year when read; otherwise the nearest read revision.
        year = pack.tax_year if pack is not None else max(_NRA_INSTRUCTION_1040)
        read = [y for y in _NRA_INSTRUCTION_1040 if y <= year] or [min(_NRA_INSTRUCTION_1040)]
        quote = _NRA_INSTRUCTION_1040[max(read)]
    takes = (
        "a real 9-digit SSN or ITIN (digits only) or stays blank"
        if pf.format == _SSN_DIGITS_ONLY
        else "digits only (one digit per cell)"
    )
    head = (
        f"line '{pf.line}': 'NRA' never goes in an identifying-number or comb box — this line "
        f"takes {takes}. {quote} "
    )
    if entry is not None and pack is not None and form in ("1040", "1040-X"):
        name_rule = (
            " (the same space takes the spouse's name: \"Enter your spouse's name in the entry space\")"
            if form == "1040"
            else ""
        )
        return head + (
            f"On this pack ({form} {pack.tax_year}) the entry space is line '{entry}': write "
            f"'NRA' there{name_rule} and leave the spouse-SSN box blank"
        )
    return head + (
        f"This is Form {form or '(unknown)'}, not Form 1040 or 1040-X: leave this box blank "
        f"rather than writing letters in it and follow this form's own instructions for a "
        f"spouse with no SSN or ITIN. On Form 1040 the literal goes in the MFS entry space "
        f"('filing_status.mfs_spouse_name' on the 2025 pack, "
        f"'filing_status.spouse_or_qualifying_person_name' on 2023/2024)"
    )


# Checkbox answer words (case-insensitive). Anything else string-ish is
# rejected with a prescriptive "supply yes|no" error rather than guessed at.
_CHECKBOX_ON_WORDS = frozenset({"yes", "y", "true", "on", "x", "1", "checked"})
_CHECKBOX_OFF_WORDS = frozenset({"no", "n", "false", "off", "0", "unchecked", ""})

_OFF_STATE = "/Off"


class FillResult(BaseModel):
    """What :func:`fill_form` wrote, for the assertion-diff verify pass."""

    model_config = ConfigDict(extra="forbid")

    written: dict[str, str] = Field(
        description=(
            "Fully qualified AcroForm field name -> the exact rendered value "
            "written to the PDF (checkboxes: the on_state or '/Off')."
        )
    )
    rehearsal: bool = Field(default=False, description="JT0a: a rehearsal fill of a DRAFT form, stamped NOT FOR FILING.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal notes, e.g. IRS whole-dollar rounding adjustments.",
    )


def _render_text(pf: PackField, value: object, pack: FormPack | None = None) -> str:
    """Normalize and validate a text value; returns the string to write.

    ``pack`` lets a refusal name the pack's own lines (the P-026 'NRA' refusal
    names the MFS entry-space line of that pack's revision)."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(
            f"line '{pf.line}' is a text field — pass a string "
            f"(got {type(value).__name__}); for dollar amounts use a money-type line, "
            f"for checkboxes a checkbox-type line"
        )
    text = str(value)
    if pf.format is not None:
        if pf.format not in _KNOWN_FORMATS:
            raise ValueError(
                f"line '{pf.line}': unknown format '{pf.format}' — supported formats: "
                f"{sorted(_KNOWN_FORMATS)}; fix the pack or drop the format key"
            )
        if pf.format == _SSN_DIGITS_ONLY:
            # P-026: the MFS no-TIN literal belongs in the entry space, never in
            # an SSN box (the spouse's included) — refuse it with the pack's line.
            if text.strip().upper() == _NRA_LITERAL:
                raise ValueError(_nra_refusal(pack, pf))
            # P-001: strip BEFORE the MaxLen check — dashes overflow comb cells.
            text = text.replace("-", "").replace(" ", "")
    return text


def _repair_empty_field_array(writer: PdfWriter) -> int:
    """Rebuild an EMPTY AcroForm /Fields array from the widgets on the pages; return how many roots.

    The IRS draft Schedule 3-A (2026, Created 6/24/26) ships an /AcroForm whose /Fields is ``[]`` while all
    16 of its widgets sit in the pages' /Annots — viewers still show the boxes, but a fields-based reader
    (pypdf, so this filler and verify) sees no form at all. Only that shape is repaired: a blank whose
    /Fields lists anything is left exactly as published, and a PDF with no widgets stays unfillable.
    """
    root = writer._root_object
    acroform = root.get("/AcroForm")
    if acroform is None:
        return 0
    acroform = acroform.get_object()
    if acroform.get("/Fields"):
        return 0
    roots, seen = [], set()
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            node = ref.get_object()
            if node.get("/Subtype") != "/Widget" or not hasattr(ref, "idnum"):
                continue
            # The same draft's intermediate nodes (form1[0], Page1[0]) carry no /Kids either, so a reader
            # that walks down from /Fields would stop at the root: re-link every hop on the way up.
            while node.get("/Parent") is not None:
                parent_ref = node.raw_get("/Parent")   # the IndirectObject, not the resolved dictionary
                parent = parent_ref.get_object()
                kids = parent.get("/Kids")
                if kids is None:
                    kids = ArrayObject()
                    parent[NameObject("/Kids")] = kids
                if all(getattr(k, "idnum", None) != ref.idnum for k in kids):
                    kids.append(ref)
                ref, node = parent_ref, parent
            if ref.idnum not in seen:
                seen.add(ref.idnum)
                roots.append(ref)
    if roots:
        acroform[NameObject("/Fields")] = ArrayObject(roots)
    return len(roots)


def _render_money(pf: PackField, value: object) -> tuple[str, str | None]:
    """Apply IRS whole-dollar rounding; returns (rendered, optional warning).

    Renders a plain integer string: no commas, no '$', no cents. IRS rule:
    50 cents or more rounds up (away from zero), under 50 cents rounds down.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(
            f"line '{pf.line}' is a money field — pass int, float or Decimal "
            f"(got {type(value).__name__}); strip any '$' or ',' and resubmit a plain number"
        )
    try:
        # Decimal(str(float)) avoids binary-float artifacts like 88.49999999.
        exact = value if isinstance(value, Decimal) else Decimal(str(value))
        if not exact.is_finite():  # NaN propagates quietly through quantize
            raise InvalidOperation
        with localcontext() as ctx:
            ctx.prec = 50
            rounded = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if rounded == 0:
            # Decimal keeps the sign of zero: -0.4 quantizes to Decimal('-0'),
            # which would land as '-0' on the form. Normalize to plain '0'.
            rounded = abs(rounded)
    except InvalidOperation:
        raise ValueError(
            f"line '{pf.line}': {redact(repr(value))} cannot be rendered as a whole-dollar amount — "
            f"pass a finite number of dollars (e.g. 1234.56)"
        ) from None
    warning = None
    if rounded != exact:
        warning = (
            f"line '{pf.line}': rounded {exact} to {rounded} "
            f"(IRS whole-dollar rounding: 50 cents or more rounds up)"
        )
    return str(rounded), warning


def _enforce_length(pf: PackField, rendered: str, pack: FormPack | None = None) -> None:
    """MaxLen and comb digits-only checks (P-001 clipping class)."""
    if pf.comb and rendered.strip().upper() == _NRA_LITERAL:
        raise ValueError(_nra_refusal(pack, pf))  # P-026: no comb box takes 'NRA'
    if pf.maxlen is not None and len(rendered) > pf.maxlen:
        if pf.comb:
            # Comb fields ARE the SSN/EIN fields, so this error echoes the single
            # most identifier-shaped value in the whole engine — redacted. The
            # message stays prescriptive: the caller knows what they just sent.
            raise ValueError(
                f"line '{pf.line}': value '{redact(rendered)}' ({len(rendered)} characters) exceeds "
                f"comb MaxLen {pf.maxlen} — resubmit digits only"
            )
        raise ValueError(
            f"line '{pf.line}': value '{redact(rendered)}' is {len(rendered)} characters but the "
            f"field allows at most {pf.maxlen} — shorten it to {pf.maxlen} characters or fewer"
        )
    if pf.comb and rendered and not rendered.isdigit():
        raise ValueError(
            f"line '{pf.line}': comb fields take digits only (one digit per cell) — "
            f"value '{redact(rendered)}' contains non-digits; strip dashes, spaces and letters "
            f"and resubmit"
        )


def _checkbox_state(pf: PackField, value: object) -> str:
    """Map a yes/no-ish answer to the pack's on_state or '/Off'."""
    on_state = pf.on_state
    assert on_state is not None  # guaranteed by the FormPack schema validator
    if isinstance(value, bool):
        checked = value
    elif isinstance(value, str):
        word = value.strip().lower()
        if word in _CHECKBOX_ON_WORDS:
            checked = True
        elif word in _CHECKBOX_OFF_WORDS:
            checked = False
        else:
            raise ValueError(
                f"line '{pf.line}': cannot interpret {redact(repr(value))} as a checkbox answer — "
                f"supply yes|no (or true|false); to leave the box untouched, omit the line"
            )
    elif value is None:
        raise ValueError(
            f"line '{pf.line}': checkbox answer is None — supply yes|no; "
            f"to leave the box untouched, omit the line entirely"
        )
    elif isinstance(value, int) and value in (0, 1):
        checked = bool(value)
    else:
        # Never coerce arbitrary objects (2, 2.5, lists, ...) into an answer.
        raise ValueError(
            f"line '{pf.line}': cannot interpret {value!r} ({type(value).__name__}) "
            f"as a checkbox answer — supply yes|no (or true|false); "
            f"to leave the box untouched, omit the line"
        )
    return on_state if checked else _OFF_STATE


def _qualified_name(annot: object) -> str:
    """Fully qualified field name of a widget: /T parts joined by '.' up the /Parent chain."""
    parts: list[str] = []
    node = annot
    seen: set[int] = set()
    while node is not None:
        if id(node) in seen:  # defensive: malformed /Parent cycle
            break
        seen.add(id(node))
        title = node.get("/T")  # type: ignore[union-attr]
        if title:
            parts.append(str(title))
        parent = node.get("/Parent")  # type: ignore[union-attr]
        node = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _normal_states(annot: object) -> list[str] | None:
    """The widget's /AP /N appearance-state names, or None when /AP is absent."""
    ap = annot.get("/AP")  # type: ignore[attr-defined]
    if ap is None:
        return None
    normal = ap.get_object().get("/N")
    if normal is None:
        return None
    return sorted(str(k) for k in normal.get_object().keys())


def _set_checkboxes(writer: PdfWriter, updates: dict[str, tuple[str, str]]) -> None:
    """Set checkbox/radio values: field ``/V`` AND widget ``/AS`` (dev plan section 10).

    ``updates`` maps the qualified field name to ``(line, state)``.

    A plain checkbox is one widget. A radio group (real IRS filing status,
    digital-assets yes/no, ...) is ONE /Btn field whose /T-less kid widgets
    each carry a DIFFERENT on-state in their /AP /N dict: the chosen state is
    written as /AS only on the kid that defines it, every sibling kid goes
    /Off, and /V is set once on the /T-bearing field dictionary.
    """
    widgets_by_field: dict[str, list] = {}
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            qualified = _qualified_name(annot)
            if qualified in updates:
                widgets_by_field.setdefault(qualified, []).append(annot)
    missing = sorted(q for q in updates if q not in widgets_by_field)
    if missing:  # pre-checked against get_fields(), so this is defensive
        raise ValueError(
            f"checkbox field(s) {missing} have no widget annotation in the PDF — "
            f"re-introspect the blank PDF and fix the pack's field names"
        )
    for qualified, (line, state) in updates.items():
        widgets = widgets_by_field[qualified]
        carriers = widgets  # state == /Off: every widget (kid) goes /Off
        if state != _OFF_STATE:
            # Guard against pack typos: the on_state must be a state the PDF
            # actually defines, or viewers will render it unchecked. In a
            # radio group only ONE kid's /AP /N carries the chosen state.
            carriers = []
            known: list[str] = []
            for annot in widgets:
                states = _normal_states(annot)
                if states is None:
                    continue
                known.extend(states)
                if state in states:
                    carriers.append(annot)
            if not carriers:
                if known:
                    raise ValueError(
                        f"line '{line}': on_state '{state}' is not a state of "
                        f"checkbox field '{qualified}' — the PDF offers "
                        f"{sorted(set(known))}; dump the blank PDF's field states "
                        f"and fix the pack's on_state"
                    )
                if len(widgets) > 1:
                    raise ValueError(
                        f"line '{line}': none of the {len(widgets)} kid widgets of "
                        f"field '{qualified}' carries an /AP /N appearance dictionary — "
                        f"cannot tell which kid shows state '{state}'; re-introspect "
                        f"the blank PDF (it may be malformed) and fix the pack"
                    )
                carriers = widgets  # single widget without /AP: trust the pack
        carrier_ids = {id(annot) for annot in carriers}
        for annot in widgets:
            annot[NameObject("/AS")] = NameObject(
                state if id(annot) in carrier_ids else _OFF_STATE
            )
        # /V belongs on the *field* dictionary: the widget itself when the
        # field and widget are merged (it carries /T), else the ancestor
        # that carries /T (the shared radio-group field dict).
        field_obj = widgets[0]
        while "/T" not in field_obj and field_obj.get("/Parent") is not None:
            field_obj = field_obj["/Parent"].get_object()
        field_obj[NameObject("/V")] = NameObject(state)


REHEARSAL_STAMP = "REHEARSAL — DRAFT FORM — NOT FOR FILING"


def rehearsal_only(pack: FormPack) -> bool:
    """True when ``pack`` can be filled only in REHEARSAL mode: a DRAFT pack (JT0a), or — JT3d — a FINAL
    pack whose year's knowledge pack is planning-only, such as the continuous-use Form 8833 (Rev.
    12-2022) in the TY2026 set. A pack whose own final revision is its authority (JT0c, the 1040-ES)
    fills normally, so it is never rehearsal-only."""
    if pack.source_status == "draft":
        return True
    return (pack.filing_grade_basis == "year_knowledge"
            and provisional_marker(pack.jurisdiction, pack.tax_year) is not None)


def _require_rehearsable(pack: FormPack) -> None:
    if not rehearsal_only(pack):
        raise ValueError(
            f"rehearsal=True is only for a DRAFT pack (source_status: draft) or a final pack in a planning-only "
            f"year; {pack.form} {pack.tax_year} is '{pack.source_status}' and fills normally — fill it without "
            f"rehearsal"
        )


def fill_form(
    pack: FormPack,
    values: Mapping[str, object],
    blank_pdf: str | Path,
    out_path: str | Path,
    *,
    rehearsal: bool = False,
) -> FillResult:
    """Fill ``blank_pdf`` with ``values`` per the pack's field map; write ``out_path``.

    Args:
        pack: the validated form pack (line -> AcroForm field map).
        values: logical line id -> value. Text lines take strings, money
            lines take int/float/Decimal (IRS whole-dollar rounding is
            applied; rendered as a plain integer string), checkbox lines
            take yes/no/true/false/bool. Radio-group options (several
            checkbox lines mapping to ONE field, each with its own
            on_state) take at most one yes. **Only lines present here are
            touched** — the filler never invents a value.
        blank_pdf: path to the blank official PDF (fetched and
            checksum-verified upstream).
        out_path: where to write the filled PDF (parents are created).

    Returns:
        :class:`FillResult` with ``written`` (fully qualified field name ->
        exact rendered value) for the verifier's assertion diff, plus
        ``warnings`` (e.g. rounding adjustments).

    Raises:
        ValueError: unknown line keys, malformed values, MaxLen/comb
            violations, or pack fields missing from the PDF — every message
            says what to do next.
        FileNotFoundError: ``blank_pdf`` does not exist.
        ProvisionalPackError: the year's knowledge pack is planning-only, so
            filling a return for that year would rest on projection-grade
            numbers. Checked FIRST, before any other validation, so the caller
            learns the year is unfilable before spending effort on values.

    ``rehearsal`` (JT0a) is CORE-ONLY — no MCP tool passes it: a DRAFT pack (source_status draft) may be
    filled in a provisional year to rehearse the drafts-first authoring, every page stamped
    "REHEARSAL — DRAFT FORM — NOT FOR FILING". JT3d: so may a FINAL pack whose year is planning-only
    (:func:`rehearsal_only`). It never unlocks a filing-grade fill, and a pack that fills normally refuses it.
    """
    if rehearsal:
        _require_rehearsable(pack)
    else:
        assert_pack_filing_grade(pack, action="fill a form")

    blank_pdf = Path(blank_pdf)
    out_path = Path(out_path)

    by_line = {pf.line: pf for pf in pack.fields}
    unknown = sorted(k for k in values if k not in by_line)
    if unknown:
        raise ValueError(
            f"unknown line key(s) {unknown} for form {pack.form} ({pack.tax_year}) — "
            f"valid line ids: {sorted(by_line)}; fix the key(s) or add the line to the pack"
        )
    if not blank_pdf.is_file():
        raise FileNotFoundError(
            f"blank PDF not found at {blank_pdf} — download it first from the pack's "
            f"source_url ({pack.source_url}) via fetch_blank and pass that path"
        )

    warnings: list[str] = []
    written: dict[str, str] = {}
    text_updates: dict[str, str] = {}
    # Checkbox lines are collected per field: a RADIO GROUP maps several
    # option lines (filing_status.single, .mfj, ...) onto ONE /Btn field,
    # each with its own on_state — at most one may be answered yes.
    checkbox_lines: dict[str, list[tuple[str, str]]] = {}
    target_line: dict[str, str] = {}  # qualified field -> first line writing it

    for line, value in values.items():
        pf = by_line[line]
        # Flat AcroForms (e.g. CA FTB) have top-level field names and an empty
        # acroform_root; XFA-derived forms (federal) prepend the subform root.
        qualified = f"{pack.acroform_root}.{pf.field}" if pack.acroform_root else pf.field
        is_checkbox = pf.type == "checkbox"
        if qualified in target_line and not (is_checkbox and qualified in checkbox_lines):
            # Without this check the later line silently overwrites the
            # earlier one AND `written` only records the survivor, so even
            # the verifier's assertion diff would miss the loss. (Checkbox
            # lines sharing one field are a radio group — resolved below.)
            raise ValueError(
                f"lines '{target_line[qualified]}' and '{line}' both map to AcroForm "
                f"field '{qualified}' — a field holds one value; submit only one of "
                f"these lines, or fix the pack so each line maps to its own field"
            )
        target_line.setdefault(qualified, line)
        if is_checkbox:
            state = _checkbox_state(pf, value)
            checkbox_lines.setdefault(qualified, []).append((line, state))
            landed = state != _OFF_STATE
        else:
            if pf.type == "money":
                rendered, warning = _render_money(pf, value)
                if warning:
                    warnings.append(warning)
            else:
                rendered = _render_text(pf, value, pack)
            _enforce_length(pf, rendered, pack)
            text_updates[qualified] = rendered
            written[qualified] = rendered
            landed = rendered.strip() not in ("", "0")
        if pf.reserved and landed:
            warnings.append(
                f"line '{line}' is a printed 'Reserved for future use' row of Form {pack.form} ({pack.tax_year}); the "
                f"pack keeps it mapped only so a relation can name it. Leave it blank unless the IRS un-reserves it."
            )

    # Resolve each checkbox field to a single state. Multiple lines on one
    # field are radio-group options: at most one may be on; "no" answers for
    # sibling options are redundant but harmless (they confirm /Off).
    checkbox_updates: dict[str, tuple[str, str]] = {}
    on_lines_by_group: dict[str, list[str]] = {}  # PackField.group -> lines turned on
    for qualified, entries in checkbox_lines.items():
        on_entries = [(line, state) for line, state in entries if state != _OFF_STATE]
        if len(on_entries) > 1:
            on_lines = " and ".join(f"'{line}'" for line, _ in on_entries)
            raise ValueError(
                f"lines {on_lines} both turn on AcroForm field '{qualified}' — these "
                f"are options of ONE radio/choice group and the field holds a single "
                f"selection; answer yes to exactly one of these lines and omit (or "
                f"answer no to) the others"
            )
        # No on-entry means every submitted option answered no: whole group /Off.
        line, state = on_entries[0] if on_entries else entries[0]
        checkbox_updates[qualified] = (line, state)
        written[qualified] = state
        for on_line, _ in on_entries:
            group = by_line[on_line].group
            if group is not None:
                on_lines_by_group.setdefault(group, []).append(on_line)

    # Mutual exclusion across a checkbox GROUP. The five 1040 filing-status
    # options and every yes/no block are separate single-widget /Btn fields
    # that share only a `group` id — the same-field guard above never fires
    # for them, so check the group here: at most one member may be on.
    for group, on_group_lines in on_lines_by_group.items():
        if len(on_group_lines) > 1:
            conflicting = " and ".join(f"'{line}'" for line in sorted(on_group_lines))
            raise ValueError(
                f"lines {conflicting} all turn on members of checkbox group '{group}' — "
                f"these are the mutually exclusive options of ONE question and exactly one "
                f"may be selected; answer yes to a single member and omit (or answer no to) "
                f"the others"
            )

    try:
        writer = PdfWriter(clone_from=str(blank_pdf))
    except Exception as exc:
        # pypdf raises assorted parse errors (PdfStreamError, PdfReadError, ...)
        # on truncated/corrupt files; none of them say what to do next.
        raise ValueError(
            f"{blank_pdf} could not be parsed as a PDF ({exc}) — the download is "
            f"corrupt or not a PDF; re-fetch the blank from the pack's source_url "
            f"({pack.source_url}) via fetch_blank and retry"
        ) from exc

    _repair_empty_field_array(writer)
    available = set(writer.get_fields() or {})
    if written and not available:
        raise ValueError(
            f"{blank_pdf.name} has no AcroForm fields — this is not a fillable PDF; "
            f"re-download the official blank from {pack.source_url}"
        )
    missing = sorted(q for q in written if q not in available)
    if missing:
        sample = sorted(available)[:15]
        raise ValueError(
            f"field(s) {missing} not found in {blank_pdf.name} — the PDF has fields "
            f"like {sample}; check the pack's acroform_root ('{pack.acroform_root}') "
            f"and field names, or re-introspect the blank PDF"
        )

    if text_updates:
        # auto_regenerate=False: do not let pypdf toggle NeedAppearances per
        # call; we set the flag once, explicitly, below (dev plan section 10).
        writer.update_page_form_field_values(None, text_updates, auto_regenerate=False)
    if checkbox_updates:
        _set_checkboxes(writer, checkbox_updates)

    # Viewers must regenerate appearance streams for the values to show.
    writer.set_need_appearances_writer(True)

    if rehearsal:
        from pypdf.annotations import FreeText  # noqa: PLC0415

        for index, page in enumerate(writer.pages):
            top = float(page.mediabox.top)
            writer.add_annotation(page_number=index, annotation=FreeText(
                text=REHEARSAL_STAMP, rect=(36, top - 30, 420, top - 12), font="Helvetica", bold=True,
                font_size="11pt", font_color="cc0000", border_color=None, background_color=None,
            ))
        warnings.append(f"{REHEARSAL_STAMP}: drafts-first rehearsal of {pack.form} {pack.tax_year} "
                        f"(draft Created {pack.draft_created}).")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        writer.write(fh)
    return FillResult(written=written, warnings=warnings, rehearsal=rehearsal)
