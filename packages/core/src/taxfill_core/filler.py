"""Deterministic AcroForm fill — dev plan sections 3, 10 and 11.

:func:`fill_form` writes a values dict (keyed by the pack's logical *line*
ids) into a blank official PDF, driven entirely by the form pack's
line-to-field map. Hard rules:

- **Never invent a value.** Only lines present in the values dict are
  touched; everything else stays exactly as it is in the blank PDF. The one
  derived write is a page-header mirror (Phase K JK28): a line the pack
  declares in ``mirrors`` and the caller left out is built from the values the
  caller DID give (CA Form 540's Sides 2-6 "Your name:" from its Side 1 name
  lines), never from anything else, and only when its box holds it.
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
- a comb divides its widget /Rect into /MaxLen equal cells, and where the
  separators printed in the box follow a narrower grid (the IRS Form 1040
  and 1040-X SSN boxes) the written widget is narrowed to that grid first,
  so the printed dots fall between the digits wherever the comb is laid
  out from the /Rect (pitfall P-033, Phase K JK28);
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

import re
from collections.abc import Collection, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, StreamObject

from taxfill_core.datadir import home_display, user_path, write_output
from taxfill_core.knowledge import assert_pack_filing_grade, provisional_marker
from taxfill_core.redact import redact
from taxfill_core.schemas.formpack import FormPack, PackField, mirror_ladder, mirror_order
from taxfill_core.schemas.handfill import HandFillPack
from taxfill_core.textfit import Fit, WidgetBox, widget_box
from taxfill_core.textfit import fit as box_fit

if TYPE_CHECKING:  # pragma: no cover - typing only; the runtime import is local (see fill_form)
    from taxfill_core.overlay import OverlayResult

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
    guards_hidden: list[str] = Field(
        default_factory=list,
        description=(
            "P-027: the page-covering viewer-guard widgets (a DOR's 'use Adobe Reader' panel, a white 'print "
            "lid' that prints over the page) the filler set Hidden so the return prints in any viewer; "
            "'<field> (page N)' each. Empty for a form without them."
        ),
    )
    combs_aligned: list[str] = Field(
        default_factory=list,
        description=(
            "Phase K JK28: the comb widgets whose /Rect the filler narrowed or shifted so the separators printed in "
            "the box fall between the characters (the 2023-2026 Form 1040 and 1040-X SSN boxes); "
            "'<field> (page N): x <old> -> <new>' each. Empty when every comb already clears its separators."
        ),
    )
    mirrored: list[str] = Field(
        default_factory=list,
        description=(
            "Phase K JK28: the page-header mirror lines (the pack's `mirrors`) the filler built from their templates "
            "because the caller left them out — line ids. A mirror the caller supplied is written as given and not "
            "listed. A built value too wide for its box is abbreviated as the pack's mirror_abbreviations allow, "
            "with an informational warning; one that still does not fit, or that the line refuses, is left blank "
            "(and not listed) with a warning saying what to do."
        ),
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


def _field_names(writer: PdfWriter) -> set[str]:
    """Every qualified AcroForm field name — pypdf's ``get_fields()``, or a walk when pypdf cannot build it.

    pypdf 6's ``get_fields()`` raises ``KeyError('/AP')`` on a radio field one of whose kid widgets carries no
    /AP dictionary at all: AZ Form 140NR 2023's "Filing Status" (four kids, no appearance, no on-state name), and AZ
    Form 140PY 2023's "Filing Status" (four kids) and "Res Status" (two kids), likewise without /AP.
    Only that error falls back, to a walk of /AcroForm /Fields and /Kids that names every /T-bearing node the
    way ``get_fields()`` does. (verify has its own copy on purpose: it never imports the filler.)
    """
    try:
        return set(writer.get_fields() or {})
    except KeyError as exc:
        if exc.args != ("/AP",):
            raise
    acroform = writer._root_object.get("/AcroForm")
    names: set[str] = set()
    if acroform is None:
        return names
    fields = acroform.get_object().get("/Fields")
    stack = [(ref, "") for ref in (fields.get_object() if fields is not None else [])]
    seen: set[int] = set()
    while stack:
        ref, prefix = stack.pop()
        node = ref.get_object()
        if id(node) in seen:
            continue
        seen.add(id(node))
        title = node.get("/T")
        name = f"{prefix}.{title}" if prefix and title else (str(title) if title else prefix)
        if title:
            names.add(name)
        kids = node.get("/Kids")
        stack.extend((kid, name) for kid in (kids.get_object() if kids is not None else []))
    return names


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


# Annotation flags (PDF 32000-1 table 165) and field flags (table 226) the P-027 pass reads.
F_HIDDEN, F_PRINT, F_NOVIEW = 2, 4, 32
_MULTILINE_FLAG = 1 << 12  # field /Ff bit 13 (Multiline): the viewer wraps the text (page-header mirrors, JK28)
_FF_READONLY, _FF_PUSHBUTTON = 1, 1 << 16
# A widget covering at least this share of its page's VISIBLE area (the CropBox) is a candidate viewer guard.
GUARD_PAGE_SHARE = 0.85
# P-027b: a pushbutton flagged NoView + Print is invisible on screen and printed on paper, so one that covers at least this
# share of the visible page is treated as a print lid. AL Form 40NR 2023's NOL-85A pages carry white lids over the top
# 72.6-83.1% of the page, under GUARD_PAGE_SHARE, and those pages printed with the whole form body covered.
LID_PAGE_SHARE = 0.5


def _inherited_attr(annot: object, key: str) -> object | None:
    """An inheritable field attribute (/FT, /Ff), from the widget or the nearest ancestor that sets it."""
    node = annot
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        value = node.get(key)  # type: ignore[union-attr]
        if value is not None:
            return value
        parent = node.get("/Parent")  # type: ignore[union-attr]
        node = parent.get_object() if parent is not None else None
    return None


def visible_box(page: object) -> tuple[float, float, float, float]:
    """The part of a page a viewer shows and a printer prints: its CropBox (pypdf answers the MediaBox when the
    page sets none), as (left, bottom, right, top)."""
    box = page.cropbox  # type: ignore[attr-defined]
    xs, ys = sorted((float(box.left), float(box.right))), sorted((float(box.bottom), float(box.top)))
    return xs[0], ys[0], xs[1], ys[1]


def is_viewer_guard(annot: object, page_box: tuple[float, float, float, float]) -> bool:
    """A page-covering pushbutton or ReadOnly text panel: a DOR's viewer guard, never a taxpayer line.

    AL Form 40 ships a yellow "WARNING: PLEASE USE A DIFFERENT PDF VIEWER" pushbutton over every page
    and a white ``printlid.N`` pushbutton (NoView + Print) that prints over it; MO-1040 prints a white
    ReadOnly text panel, "PLEASE, USE THE PRINT BUTTON ON THE FORM". The forms' own JavaScript hides
    them in Acrobat; taxfill never runs it (P-007 class 4), so the filler hides them itself (P-027).

    Coverage is measured against the page's VISIBLE area, ``page_box`` (``visible_box(page)``), not its
    MediaBox: AL Form 40's worksheet pages crop a short window out of a full Letter MediaBox, and their print
    lids cover all of that window but under a third of the MediaBox — measured against the MediaBox they
    stayed printable and both worksheets printed blank (found by the JS5 AL 2025 port's re-verify).

    P-027b: a pushbutton flagged NoView + Print (shown on no screen, printed on paper) is a print lid from
    ``LID_PAGE_SHARE`` of the visible area up. AL Form 40NR's NOL-85A pages carry white lids over 72.6-83.1% of
    the page, below ``GUARD_PAGE_SHARE``; under the 85% rule alone they stayed printable and those pages printed
    with the form body covered (found by the JS6 AL 40NR 2023 placement verify). Only a ``/Btn`` pushbutton
    qualifies: it holds no taxpayer value, so hiding one can never drop a line; a viewable pushbutton, or any
    text panel, still needs the 85% coverage.
    """
    rect = annot.get("/Rect")  # type: ignore[attr-defined]
    if rect is None or len(rect) != 4:
        return False
    xs = sorted((float(rect[0]), float(rect[2])))
    ys = sorted((float(rect[1]), float(rect[3])))
    bx0, by0, bx1, by1 = page_box
    visible = max((bx1 - bx0) * (by1 - by0), 1.0)
    covered = max(0.0, min(xs[1], bx1) - max(xs[0], bx0)) * max(0.0, min(ys[1], by1) - max(ys[0], by0))
    if covered < LID_PAGE_SHARE * visible:
        return False
    flags = int(_inherited_attr(annot, "/Ff") or 0)
    pushbutton = bool(flags & _FF_PUSHBUTTON)
    if covered >= GUARD_PAGE_SHARE * visible:
        field_type = _inherited_attr(annot, "/FT")
        return pushbutton or (field_type == "/Tx" and bool(flags & _FF_READONLY))
    annot_flags = int(annot.get("/F", 0))  # type: ignore[attr-defined]
    is_button = _inherited_attr(annot, "/FT") == "/Btn"
    return pushbutton and is_button and bool(annot_flags & F_NOVIEW) and bool(annot_flags & F_PRINT)


def _drop_xfa(writer: PdfWriter) -> bool:
    """Remove the XFA stream from a filled hybrid form, as ``pdftk ... drop_xfa`` does (Phase K JK5).

    Every IRS fillable blank is a hybrid: AcroForm fields plus an XFA (LiveCycle) stream that holds its own copy of the
    field data. This filler writes the AcroForm values only, and Adobe Acrobat / Reader can draw a hybrid form from its
    XFA data, which stays empty: the filled return then shows, and prints, blank there, while pdfium and macOS Preview
    read the AcroForm values and look right (that gap is why pdftk has ``drop_xfa``). Without the XFA stream every
    viewer reads the AcroForm values. The RC dry run found the 2025 Form 1040 output still carrying it.
    """
    acroform = writer._root_object.get("/AcroForm")
    if acroform is None:
        return False
    acroform = acroform.get_object()
    if "/XFA" not in acroform:
        return False
    xfa = acroform["/XFA"].get_object()
    del acroform["/XFA"]
    # pypdf still writes the unlinked packets (template, datasets, ...), so empty them: the bytes go too
    for packet in xfa if isinstance(xfa, ArrayObject) else [xfa]:
        packet = packet.get_object()
        if isinstance(packet, StreamObject):
            try:
                packet.set_data(b"")
            except Exception:  # noqa: BLE001 — a filter pypdf cannot re-encode: the packet is unlinked anyway
                pass
    return True


# Phase K JK28 (2026-10-16): comb cells against the separators printed in the box. A comb widget's cells are its /Rect
# split evenly: "the field shall be automatically divided into as many equally spaced positions, or combs, as the
# value of MaxLen" (ISO 32000-1:2008, 12.7.4.3, Table 228, bit 25 Comb). On the IRS Form 1040 and 1040-X SSN boxes
# (2023-2026) the dotted 3-2-4 separators follow a narrower grid than the widget (the 2025 Form 1040: a 107 pt widget,
# 11.89 pt cells, separators 21.7 pt apart), so the dots cross the third and fifth digits in every viewer that draws
# the comb. The XFA template cannot help: its comb field spans the same box as the widget (and the field's own para
# marginLeft of 12 pt would put the cells at 481-576 pt, which does not match the dots either), and the dots are
# separate draws. The filler narrows the widget to the grid its separators imply before any appearance is built, so
# pypdf's appearance and pdfium's (measured) lay out aligned cells, as must any viewer that divides the /Rect as the
# spec says (Acrobat under NeedAppearances; not yet observed there). Measured over the 2,229 comb widgets of the 265
# distinct cached blanks (JK28; counted by digest, so the Rev. 12-2024 Form 843, cached under two URLs, counts once):
# the rule fires on the 22 federal boxes whose separators crossed a digit and on nothing else.
_FF_COMB = 1 << 24
# Only ink a reader sees is a separator: white rules and the tinted cell outlines some state blanks print (DE, IA, IL,
# LA, MA, OR and VA; luminance 210-242) are left out. Luminance on the 0-255 scale (ITU-R BT.601 weights).
COMB_INK_LUMINANCE = 200
COMB_EDGE = 1.2              # pt: a stroke this close to the widget's left or right edge is the box's own border
COMB_BORDER_REACH = 2.0      # pt: how far outside the widget a box border is looked for
COMB_BORDER_TOLERANCE = 0.5  # pt: how far the new cells may reach past a printed border (or, with none, the widget)
COMB_FIT = 0.35              # pt: the most a separator may sit off the cell boundary it is fitted to
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_DA_FONT_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s+Tf")


def _compose(inner: tuple[float, ...], outer: tuple[float, ...]) -> tuple[float, ...]:
    """The PDF matrix product ``inner x outer`` (``inner`` applies first)."""
    a1, b1, c1, d1, e1, f1 = inner
    a2, b2, c2, d2, e2, f2 = outer
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def vertical_strokes(pdfium_page: object) -> list[tuple[float, float, float]]:
    """Every visible thin vertical stroke painted on a page, as ``(x, bottom, top)`` in page space (Phase K JK28).

    Read from the page's vector content through pdfium's page-object API, nested form XObjects composed in: stroked
    vertical line segments (a dotted rule is one segment under a dash pattern) and filled boxes at most 1.6 pt wide.
    Text objects are never read, so a printed digit, dash or slash is not a stroke; ink paler than
    ``COMB_INK_LUMINANCE`` (white, drop-out tints) is skipped. ``pdfium_page`` is a ``pypdfium2.PdfPage``.
    """
    import ctypes  # noqa: PLC0415 - only the comb pass needs it

    import pypdfium2.raw as pdfium_c  # noqa: PLC0415 - the AcroForm path imports pdfium only when a comb is written

    def matrix(obj: object) -> tuple[float, ...]:
        m = pdfium_c.FS_MATRIX()
        return (m.a, m.b, m.c, m.d, m.e, m.f) if pdfium_c.FPDFPageObj_GetMatrix(obj, m) else _IDENTITY

    def inked(obj: object, stroked: bool) -> bool:
        r, g, b, alpha = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        read = pdfium_c.FPDFPageObj_GetStrokeColor if stroked else pdfium_c.FPDFPageObj_GetFillColor
        if not read(obj, r, g, b, alpha):
            return True  # a pattern or shading paint has no single colour: count it
        return alpha.value > 0 and 0.299 * r.value + 0.587 * g.value + 0.114 * b.value < COMB_INK_LUMINANCE

    strokes: list[tuple[float, float, float]] = []
    page = pdfium_page.raw  # type: ignore[attr-defined]
    top_level = [pdfium_c.FPDFPage_GetObject(page, i) for i in range(pdfium_c.FPDFPage_CountObjects(page))]
    stack = [(top_level, _IDENTITY, 0)]
    while stack:
        objects, ctm, depth = stack.pop()
        for obj in objects:
            kind = pdfium_c.FPDFPageObj_GetType(obj)
            if kind == pdfium_c.FPDF_PAGEOBJ_FORM and depth < 16:
                count = pdfium_c.FPDFFormObj_CountObjects(obj)
                stack.append(([pdfium_c.FPDFFormObj_GetObject(obj, i) for i in range(count)],
                              _compose(matrix(obj), ctm), depth + 1))
                continue
            if kind != pdfium_c.FPDF_PAGEOBJ_PATH:
                continue
            fill_mode, stroke = ctypes.c_int(0), ctypes.c_int(0)
            if not pdfium_c.FPDFPath_GetDrawMode(obj, fill_mode, stroke):
                continue
            stroked = bool(stroke.value) and inked(obj, True)
            filled = bool(fill_mode.value) and inked(obj, False)
            if not (stroked or filled):
                continue
            a, b, c, d, e, f = _compose(matrix(obj), ctm)
            subpaths: list[list[tuple[int, float, float]]] = []
            for index in range(pdfium_c.FPDFPath_CountSegments(obj)):
                segment = pdfium_c.FPDFPath_GetPathSegment(obj, index)
                x, y = ctypes.c_float(), ctypes.c_float()
                if not pdfium_c.FPDFPathSegment_GetPoint(segment, x, y):
                    continue
                seg_type = pdfium_c.FPDFPathSegment_GetType(segment)
                point = (seg_type, a * x.value + c * y.value + e, b * x.value + d * y.value + f)
                if seg_type == pdfium_c.FPDF_SEGMENT_MOVETO or not subpaths:
                    subpaths.append([point])
                else:
                    subpaths[-1].append(point)
                if pdfium_c.FPDFPathSegment_GetClose(segment):
                    first = subpaths[-1][0]
                    subpaths[-1].append((pdfium_c.FPDF_SEGMENT_LINETO, first[1], first[2]))
            for sub in subpaths:
                if stroked:
                    for (_, xa, ya), (seg_type, xb, yb) in zip(sub, sub[1:]):
                        if seg_type == pdfium_c.FPDF_SEGMENT_LINETO and abs(xb - xa) <= 0.3 and abs(yb - ya) >= 0.3:
                            strokes.append(((xa + xb) / 2, min(ya, yb), max(ya, yb)))
                if filled and len(sub) >= 3:
                    xs, ys = [p[1] for p in sub], [p[2] for p in sub]
                    if max(xs) - min(xs) <= 1.6 and max(ys) - min(ys) >= 0.3:
                        strokes.append(((max(xs) + min(xs)) / 2, min(ys), max(ys)))
    return strokes


def comb_cell_grid(
    rect: tuple[float, float, float, float],
    max_len: int,
    font_size: float,
    strokes: Sequence[tuple[float, float, float]],
) -> tuple[float, float] | None:
    """The horizontal extent a comb widget must span so the separators printed in its box fall between its characters.

    ``rect`` is the widget's (x0, y0, x1, y1), ``max_len`` its /MaxLen, ``font_size`` its /DA size (0: auto) and
    ``strokes`` the page's :func:`vertical_strokes`. Returns ``(x0', x1')`` or None — None whenever the widget's own
    cells already keep every separator clear of the characters (the zone a centred digit occupies, 0.278 em either
    side of the cell centre plus 0.5 pt), or when no uniform grid fixes it inside the printed box. A stroke within
    ``COMB_EDGE`` of the widget's edge, or up to ``COMB_BORDER_REACH`` outside it, is the box border: the new cells
    start at the left border (or the widget's edge) and never reach more than ``COMB_BORDER_TOLERANCE`` past a border.
    The separators are fitted to cell boundaries (both sides of the gap between two separate boxes count as one
    separator), each within ``COMB_FIT``, with the cell width kept within 80-110% of the widget's; of the grids that
    clear every separator, the one that strays least (its start's distance from the left border plus its largest fit
    error) wins. Phase K JK28.
    """
    x0, y0, x1, y1 = rect
    n = int(max_len)
    height = y1 - y0
    cell = (x1 - x0) / n if n else 0.0
    if n < 2 or cell <= 0 or height <= 0:
        return None
    zone = 0.278 * (font_size if font_size > 0 else min(0.7 * height, cell)) + 0.5
    xs = sorted(x for x, bottom, top in strokes
                if x0 - COMB_BORDER_REACH <= x <= x1 + COMB_BORDER_REACH
                and min(top, y1) - max(bottom, y0) >= 0.25 * height)
    rules: list[list[float]] = []
    for x in xs:  # one rule may be painted as several pieces (dots, dashes, a doubled stroke)
        if rules and x - rules[-1][-1] <= 0.6:
            rules[-1].append(x)
        else:
            rules.append([x])
    lines = [sum(rule) / len(rule) for rule in rules]
    inside = [x for x in lines if x0 + COMB_EDGE <= x <= x1 - COMB_EDGE]
    left = [x for x in lines if x < x0 + COMB_EDGE]
    right = [x for x in lines if x > x1 - COMB_EDGE]

    def clear(start: float, width: float) -> bool:
        return all(abs(x - (start + (min(max(int((x - start) // width), 0), n - 1) + 0.5) * width)) >= zone
                   for x in inside)

    if not inside or clear(x0, cell):
        return None
    groups: list[list[float]] = []
    for x in inside:  # the two sides of the gap between separate boxes are one separator
        if groups and x - groups[-1][-1] <= 0.3 * cell:
            groups[-1].append(x)
        else:
            groups.append([x])
    if any(len(group) > 2 for group in groups) or len(groups) > n - 1:
        return None
    marks = [sum(group) / len(group) for group in groups]
    anchor = max(left) if left else x0
    low = anchor - COMB_BORDER_TOLERANCE
    high = (min(right) if right else x1) + COMB_BORDER_TOLERANCE
    assignments: set[tuple[int, ...]] = set()
    if len(marks) == 1:
        assignments = {(k,) for k in range(1, n)}
    else:
        for span in range(len(marks) - 1, n - 1):  # boundaries between the first and the last separator
            width = (marks[-1] - marks[0]) / span
            steps = [round((x - marks[0]) / width) for x in marks]
            if 0.8 * cell <= width <= 1.1 * cell and steps[-1] == span and len(set(steps)) == len(steps):
                assignments |= {tuple(first + s for s in steps) for first in range(1, n - span)}
    best: tuple[float, float, float] | None = None
    for ks in sorted(assignments):
        fits = [(anchor, sum(k * (x - anchor) for k, x in zip(ks, marks)) / sum(k * k for k in ks))]
        if len(marks) >= 2:
            k_mean, x_mean = sum(ks) / len(ks), sum(marks) / len(marks)
            slope = sum((k - k_mean) * (x - x_mean) for k, x in zip(ks, marks)) / sum((k - k_mean) ** 2 for k in ks)
            fits.append((x_mean - slope * k_mean, slope))
        for start, width in fits:
            if not 0.8 * cell <= width <= 1.1 * cell or start < low or start + n * width > high:
                continue
            off = max(abs(x - (start + k * width)) for k, x in zip(ks, marks))
            if off > COMB_FIT or not clear(start, width):
                continue
            score = abs(start - anchor) + off
            if best is None or score < best[0]:
                best = (score, start, width)
    return None if best is None else (best[1], best[1] + n * best[2])


def _da_font_size(da: object) -> float:
    """The font size of a /DA string ('/Helv 8 Tf 0 g' -> 8.0); 0.0 for auto-size or when none is set."""
    match = _DA_FONT_SIZE.search(str(da)) if da is not None else None
    return float(match.group(1)) if match else 0.0


def _align_comb_cells(writer: PdfWriter, blank_pdf: Path, text_updates: Mapping[str, str]) -> list[str]:
    """Narrow or shift every written comb widget whose cells cross the separators printed in its box (Phase K JK28).

    Only a non-empty value in a /Tx widget with the Comb flag and a /MaxLen of 2 or more is considered, on an unrotated
    page; a widget with its own border or background colour (/MK /BC, /BG), or a rotation (/MK /R), keeps its /Rect,
    since the viewer would move that drawing with it. The new extent comes from :func:`comb_cell_grid` over the blank's
    :func:`vertical_strokes`; the vertical extent never changes. Returns ``'<field> (page N): x <old> -> <new>'`` each.
    The pass is cosmetic and never blocks a fill: a page pdfium cannot open or walk keeps its widgets as published,
    and a widget the grid rule fails on keeps its /Rect.
    """
    acroform = writer._root_object.get("/AcroForm")
    default_da = acroform.get_object().get("/DA") if acroform is not None else None
    todo: list[tuple[int, DictionaryObject, str, tuple[float, float, float, float], int, float]] = []
    for index, page in enumerate(writer.pages):
        if int(page.get("/Rotate", 0) or 0) % 360:
            continue
        for ref in page.get("/Annots", []) or []:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(annot)
            if not text_updates.get(name):
                continue
            max_len = _inherited_attr(annot, "/MaxLen")
            flags = int(_inherited_attr(annot, "/Ff") or 0)
            if _inherited_attr(annot, "/FT") != "/Tx" or not flags & _FF_COMB or max_len is None or int(max_len) < 2:
                continue
            look = annot.get("/MK")
            look = look.get_object() if look is not None else {}
            if float(look.get("/R", 0) or 0) % 360 or look.get("/BC") or look.get("/BG"):
                continue
            rect = annot.get("/Rect")
            if rect is None or len(rect) != 4:
                continue
            xa, xb = sorted((float(rect[0]), float(rect[2])))
            ya, yb = sorted((float(rect[1]), float(rect[3])))
            font_size = _da_font_size(_inherited_attr(annot, "/DA") or default_da)
            todo.append((index, annot, name, (xa, ya, xb, yb), int(max_len), font_size))
    if not todo:
        return []
    import pypdfium2 as pdfium  # noqa: PLC0415 - see vertical_strokes

    try:
        doc = pdfium.PdfDocument(str(blank_pdf))
    except pdfium.PdfiumError:  # pragma: no cover - pypdf parsed this blank; a cosmetic pass never blocks a fill
        return []
    changed: list[str] = []
    strokes: dict[int, list[tuple[float, float, float]]] = {}
    try:
        for index, annot, name, (xa, ya, xb, yb), max_len, font_size in todo:
            if index not in strokes:
                strokes[index] = []  # a page pdfium cannot open or walk keeps its widgets as published
                try:
                    page = doc[index]  # IndexError / PdfiumError when pypdf and pdfium read the page tree apart
                except Exception:  # noqa: BLE001 — a cosmetic pass never blocks a fill
                    pass
                else:
                    try:
                        strokes[index] = vertical_strokes(page)
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        page.close()
            try:
                grid = comb_cell_grid((xa, ya, xb, yb), max_len, font_size, strokes[index])
            except Exception:  # noqa: BLE001 — the widget keeps its /Rect
                continue
            if grid is None:
                continue
            annot[NameObject("/Rect")] = ArrayObject(
                [FloatObject(round(grid[0], 3)), FloatObject(ya), FloatObject(round(grid[1], 3)), FloatObject(yb)])
            changed.append(f"{name} (page {index + 1}): x {xa:.2f}-{xb:.2f} -> {grid[0]:.2f}-{grid[1]:.2f}")
    finally:
        doc.close()
    return changed


def _annotation_flag_pass(writer: PdfWriter, written: Mapping[str, str]) -> list[str]:
    """P-027: every written widget becomes viewable and printable; every viewer guard is hidden.

    A blank may ship a mapped widget Hidden or NoView (OH IT 1040's MFS spouse SSN, DE PIT-RES's
    amended-return lines, every AL Form 40 data field) and un-hide it only through its own JavaScript.
    taxfill writes the value and never runs the script, so without this pass the value sits invisible
    in the file, verify reads it back as present, and the printed return is blank where it matters.
    Returns the guards hidden, ``'<field> (page N)'`` each.
    """
    hidden: list[str] = []
    for index, page in enumerate(writer.pages, 1):
        page_box = visible_box(page)
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            flags = int(annot.get("/F", 0))
            if _qualified_name(annot) in written:
                wanted = (flags & ~(F_HIDDEN | F_NOVIEW)) | F_PRINT
                if wanted != flags:
                    annot[NameObject("/F")] = NumberObject(wanted)
                continue
            if not is_viewer_guard(annot, page_box):
                continue
            if flags & F_HIDDEN and not flags & F_PRINT:
                continue  # already dark on screen and paper
            annot[NameObject("/F")] = NumberObject(F_HIDDEN)
            hidden.append(f"{_qualified_name(annot)} (page {index})")
    return hidden


def _mirror_boxes(writer: PdfWriter, names: Collection[str]) -> dict[str, list[WidgetBox]]:
    """The widgets of the fields ``names`` (qualified names) on the blank, as :mod:`taxfill_core.textfit` measures them.

    Each widget's width, its /DA (up the /Parent chain, else the AcroForm's default /DA) with the face resolved
    through the AcroForm /DR fonts, and its multiline flag (/Ff bit 13, inherited the same way). Phase K JK28: the
    page-header mirrors are measured against these before they are written. A /DA font the /DR lacks, and that is
    not one pypdf builds itself (its Core-14 table), is measured as Helvetica: pypdf draws it so and writes
    /Helvetica into the widget's /DA when it fills the box, which is the face verify then reads.
    """
    acroform = writer._root_object.get("/AcroForm")
    acroform = acroform.get_object() if acroform is not None else {}
    default_da = acroform.get("/DA")
    base_fonts: dict[str, str] = {}
    try:
        fonts = acroform["/DR"].get_object()["/Font"].get_object()
    except (KeyError, AttributeError, TypeError):
        fonts = {}
    for key, ref in (fonts or {}).items():
        base = ref.get_object().get("/BaseFont") if hasattr(ref, "get_object") else None
        if base is not None:
            base_fonts[str(key).lstrip("/")] = str(base).lstrip("/")
    dr_fonts = {str(key).lstrip("/") for key in (fonts or {})}
    try:  # the font names pypdf builds without a /DR entry: Core-14, Arial, Courier New, Times New Roman
        from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS  # noqa: PLC0415

        pypdf_builds: frozenset[str] | None = frozenset(CORE_FONT_METRICS)
    except Exception:  # noqa: BLE001 — a pypdf without that private table: measure each /DA font as named
        pypdf_builds = None

    def inherited(node: object, key: str) -> object | None:
        seen: set[int] = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            if key in node:  # type: ignore[operator]
                return node[key]  # type: ignore[index]
            parent = node.get("/Parent")  # type: ignore[union-attr]
            node = parent.get_object() if parent is not None else None
        return None

    boxes: dict[str, list[WidgetBox]] = {}
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget" or (name := _qualified_name(annot)) not in names:
                continue
            rect = annot.get("/Rect")
            width = abs(float(rect[2]) - float(rect[0])) if rect else 0.0
            da = inherited(annot, "/DA") or default_da
            if isinstance(da, bytes):
                da = da.decode("latin-1")
            flags = inherited(annot, "/Ff")
            multiline = flags is not None and bool(int(flags) & _MULTILINE_FLAG)
            box = widget_box(width, None if da is None else str(da), base_fonts=base_fonts, multiline=multiline)
            if box.font and box.font not in dr_fonts and pypdf_builds is not None and box.font not in pypdf_builds:
                box = box._replace(font="Helvetica", courier=False)  # what pypdf draws, and names in the /DA
            boxes.setdefault(name, []).append(box)
    return boxes


def _fill_mirrors(
    pack: FormPack,
    values: Mapping[str, object],
    rendered: Mapping[str, str],
    text_updates: dict[str, str],
    written: dict[str, str],
    warnings: list[str],
    boxes: Mapping[str, Sequence[WidgetBox]],
) -> list[str]:
    """Page-header mirrors (Phase K JK28): fill each ``pack.mirrors`` line the caller left out; return those lines.

    A mirror the caller supplied (a non-blank value) is written as given: never rebuilt, never measured here (verify
    measures it). Every other one is built from the values this fill writes, ``rendered`` (each line the caller gave,
    after its own formatting) plus the mirrors built before it, in ``mirror_order``, and written only when its box
    holds it. The box is the field's ``boxes`` (the blank's widgets), measured with :func:`taxfill_core.textfit.fit`:
    within the line's maxlen and no wider than its narrowest widget less 2 pt. A value too wide is replaced by the
    first abbreviation of :func:`~taxfill_core.schemas.formpack.mirror_ladder` that fits, which only a pack whose
    ``mirror_abbreviations`` covers the mirror has, with an informational warning. When nothing fits the mirror is
    left BLANK, and a warning says to hand-write it after printing. A comb box keeps the filler's own rules (maxlen,
    digits only, the P-026 'NRA' refusal): a built value it refuses is left blank with a warning saying why. A
    template that renders empty is skipped. Applies to every AcroForm fill, rehearsals included.
    """
    if not pack.mirrors:
        return []
    by_line = {pf.line: pf for pf in pack.fields}
    sources = dict(rendered)
    mirrored: list[str] = []
    for line in mirror_order(pack.mirrors):
        supplied = values.get(line)
        if line in values and not (isinstance(supplied, str) and not supplied.strip()):
            continue  # a caller-supplied mirror always wins
        template = pack.mirrors[line]
        shortenable = pack.mirror_abbreviations.get(line, [])
        ladder = mirror_ladder(template, sources, shortenable)
        sources[line] = ""  # until it is written, a mirror reads as the blank it is (for a mirror of this mirror)
        if not ladder:
            continue  # every line the template reads is blank: nothing to mirror
        pack_field = by_line[line]
        qualified = f"{pack.acroform_root}.{pack_field.field}" if pack.acroform_root else pack_field.field
        try:
            candidates = [_render_text(pack_field, rung, pack) for rung in ladder]
            if pack_field.comb:
                _enforce_length(pack_field, candidates[0], pack)  # no comb mirror abbreviates (the schema refuses)
        except ValueError as exc:
            warnings.append(
                f"mirror line '{line}' left blank: its template {template!r} builds {redact(ladder[0])!r}, which "
                f"the line refuses ({exc}) — fill '{line}' yourself with a value it accepts (a value you pass for a "
                f"mirror is written as given) and re-verify"
            )
            continue
        fits: list[Fit] = []
        for text in candidates:
            fits.append(box_fit(text, boxes.get(qualified, ()), maxlen=pack_field.maxlen, comb=pack_field.comb))
            if fits[-1].fits is not False:  # it fits, or no widget of the field could be measured
                break
        else:
            shortest = (
                f", nor the shortest abbreviation the pack's mirror_abbreviations allow, {redact(ladder[-1])!r} "
                f"({fits[-1].detail})" if len(ladder) > 1 else ", and the pack allows no shorter form of it"
            )
            warnings.append(
                f"mirror line '{line}' left blank: its box cannot hold {redact(ladder[0])!r} ({fits[0].detail})"
                f"{shortest} — fill_form never writes a header its box would cut off, so hand-write it in the box "
                f"after printing (verify_form does not fail a header left blank for this reason: its check is "
                f"SKIPPED)"
            )
            continue
        text = candidates[len(fits) - 1]
        if len(fits) > 1:
            warnings.append(
                f"mirror line '{line}': {redact(ladder[0])!r} does not fit its box ({fits[0].detail}), so fill_form "
                f"wrote {redact(text)!r} ({fits[-1].detail}); the pack's mirror_abbreviations let this header cut "
                f"{_and(shortenable)} to initials or leave them out — informational: verify_form accepts it"
            )
        text_updates[qualified] = text
        written[qualified] = text
        sources[line] = text
        mirrored.append(line)
    return mirrored


def _and(names: Sequence[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


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
    pack: FormPack | HandFillPack,
    values: Mapping[str, object],
    blank_pdf: str | Path,
    out_path: str | Path,
    *,
    rehearsal: bool = False,
) -> FillResult | OverlayResult:
    """Fill ``blank_pdf`` with ``values`` per the pack's field map; write ``out_path``.

    DISPATCH: a print-only :class:`HandFillPack` (``render_mode: hand_fill``) has no
    AcroForm to write into, so it is routed to :func:`taxfill_core.overlay.stamp_overlay`,
    which stamps the worksheet values at the pack's ``overlay`` coordinates and returns an
    :class:`~taxfill_core.overlay.OverlayResult` instead of a :class:`FillResult`. A
    hand-fill pack with NO coordinates raises there, pointing at ``hand_fill_worksheet``.
    Everything below this paragraph is the AcroForm path and is untouched by the dispatch.

    Args:
        pack: the validated form pack (line -> AcroForm field map), or a hand-fill pack.
        values: logical line id -> value. Text lines take strings, money
            lines take int/float/Decimal (IRS whole-dollar rounding is
            applied; rendered as a plain integer string), checkbox lines
            take yes/no/true/false/bool. Radio-group options (several
            checkbox lines mapping to ONE field, each with its own
            on_state) take at most one yes. **Only lines present here are
            touched** — the filler never invents a value — with two
            consequences: a yes writes the other members of that line's
            checkbox ``group`` /Off (P-028), since the question has one answer
            and a blank may ship a sibling pre-checked; and a page-header
            mirror the pack declares (``pack.mirrors``, Phase K JK28) that is
            absent or blank here is built from the lines given here and written
            when its box holds it, abbreviated or left blank otherwise (see
            :func:`_fill_mirrors`).
        blank_pdf: path to the blank official PDF (fetched and
            checksum-verified upstream).
        out_path: where to write the filled PDF (parents are created).

    Returns:
        :class:`FillResult` with ``written`` (fully qualified field name ->
        exact rendered value) for the verifier's assertion diff, plus
        ``warnings`` (e.g. rounding adjustments) and ``mirrored`` (the
        page-header mirror lines the filler built).

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
    if isinstance(pack, HandFillPack):
        if rehearsal:
            raise ValueError(
                f"rehearsal fills are AcroForm-only (a DRAFT pack.yaml in a provisional year); the "
                f"{pack.form} {pack.tax_year} hand-fill pack stamps a print blank — call fill_form without rehearsal"
            )
        # Local import: the overlay module pulls in pypdfium2, which the AcroForm path needs only for overlay's
        # Helvetica widths, through taxfill_core.textfit, when it measures a page-header mirror.
        # Page-header mirrors (Phase K JK28) are AcroForm-only and out of scope here: a HandFillPack declares no
        # `mirrors`, and the overlay stamps exactly the worksheet values it is given.
        from taxfill_core.overlay import stamp_overlay

        return stamp_overlay(blank_pdf, pack, values, out_path)
    if rehearsal:
        _require_rehearsable(pack)
    else:
        assert_pack_filing_grade(pack, action="fill a form")

    # "~/..." works as the out_path an agent types (Phase K JK28); messages show the home folder as "~".
    blank_pdf = user_path(blank_pdf)
    out_path = user_path(out_path)

    by_line = {pf.line: pf for pf in pack.fields}
    unknown = sorted(k for k in values if k not in by_line)
    if unknown:
        raise ValueError(
            f"unknown line key(s) {unknown} for form {pack.form} ({pack.tax_year}) — "
            f"valid line ids: {sorted(by_line)}; fix the key(s) or add the line to the pack"
        )
    if not blank_pdf.is_file():
        raise FileNotFoundError(
            f"blank PDF not found at {home_display(blank_pdf)} — download it first from the pack's "
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
    rendered_by_line: dict[str, str] = {}  # text/money line -> the value written, as page-header mirrors read it

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
            rendered_by_line[line] = rendered
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
            f"{home_display(blank_pdf)} could not be parsed as a PDF ({exc}) — the download is "
            f"corrupt or not a PDF; re-fetch the blank from the pack's source_url "
            f"({pack.source_url}) via fetch_blank and retry"
        ) from exc

    _repair_empty_field_array(writer)
    available = _field_names(writer)
    # Page-header mirrors (Phase K JK28): every caller value is validated and rendered, so build the mirrors the
    # caller left out from exactly what this fill writes, measured against the widgets of the blank just opened.
    mirror_fields = {f"{pack.acroform_root}.{by_line[m].field}" if pack.acroform_root else by_line[m].field
                     for m in pack.mirrors}
    mirrored = _fill_mirrors(pack, values, rendered_by_line, text_updates, written, warnings,
                             _mirror_boxes(writer, mirror_fields) if mirror_fields else {})
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

    # P-028: the selected member of a checkbox group clears its separate-field siblings. A blank may
    # ship one of them pre-checked (GA 500's voucher "Paper Return"), and a sibling the caller did not
    # name is otherwise left as the blank had it — two ticks on a one-answer question. The on-member's
    # own field is skipped (its radio kids go /Off in _set_checkboxes), and so is a sibling the PDF lacks.
    for group in on_lines_by_group:
        for pf in pack.fields:
            if pf.type != "checkbox" or pf.group != group:
                continue
            sibling = f"{pack.acroform_root}.{pf.field}" if pack.acroform_root else pf.field
            if sibling in checkbox_updates or sibling not in available:
                continue
            checkbox_updates[sibling] = (pf.line, _OFF_STATE)
            written[sibling] = _OFF_STATE

    # Phase K JK28: before any appearance is built from a widget's /Rect, narrow each written comb whose cells cross
    # the separators printed in its box (the IRS SSN boxes) to the grid those separators imply.
    combs_aligned = _align_comb_cells(writer, blank_pdf, text_updates) if text_updates else []
    if text_updates:
        # auto_regenerate=False: do not let pypdf toggle NeedAppearances per
        # call; we set the flag once, explicitly, below (dev plan section 10).
        writer.update_page_form_field_values(None, text_updates, auto_regenerate=False)
    if checkbox_updates:
        _set_checkboxes(writer, checkbox_updates)
    # P-027: what was written must show and print; a DOR's viewer guard must not.
    guards_hidden = _annotation_flag_pass(writer, written)

    # Viewers must regenerate appearance streams for the values to show.
    writer.set_need_appearances_writer(True)
    _drop_xfa(writer)

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

    write_output(out_path, writer.write)
    return FillResult(
        written=written, warnings=warnings, rehearsal=rehearsal, guards_hidden=guards_hidden,
        combs_aligned=combs_aligned, mirrored=mirrored,
    )
