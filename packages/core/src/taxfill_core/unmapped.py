"""The pack-less fill: describe and fill a blank that has no form pack (Phase K JK16, 2026-10-25).

Core only, as JK14 was: no MCP tool calls this yet (ADR-0002 is Proposed; the ROADMAP's JK16 box binds). The MCP
wiring of get_form_map / fill_form with ``form="unmapped"`` will call :func:`describe_unmapped` and
:func:`fill_unmapped`, whose results are the response shapes ADR-0002's Decision sets out.

- :func:`describe_unmapped` — get_form_map's field list: every AcroForm field of the blank with its kind, flags,
  options and on-states, whether it may ever be filled (``refusal``), and each widget's page, rect and pack-blind
  anchor (taxfill_core.anchor); a field's ``confidence`` is its lowest widget's. It writes the sweep copy: each
  fillable field shows "#<index>" on every one of its widgets, so the user can confirm boxes on a rendered page
  (KG11). The sweep holds no user data (rule 5 refuses a local blank that holds a typed value).
- :func:`fill_unmapped` — fill_form's PDF response, or its worksheet-only response for a flat blank (rule 10) and
  when no anchor benchmark table has passed (KG6). The blank is named by ``blank_sha256`` + ``source_url`` and
  loaded through ``fetch.load_unmapped_blank``, which re-runs every fetch check (rule 1, a shipped pack wins, among
  them). Values are keyed by qualified field name.

Guardrails (docs/dev/ROADMAP.md, Phase K; ADR-0002):

- KG5: the grade "unmapped_draft" is a constant on every result; every page of every PDF written here (the draft and
  the sweep) carries filler.UNMAPPED_STAMP, drawn into the content stream where it prints (taxfill_core.stamp). No
  parameter turns it off, the PDF is written once, already stamped, from memory (no unstamped copy reaches disk, no
  temporary file), and it is written only after stamp_check passed on its bytes.
- KG7: ReadOnly, pushbutton, viewer-guard, signature, calculated and hidden widgets are never written; a value for
  one comes back in ``hand_write`` with the reason, and the rest of the fill goes on. Every value written or listed
  carries VALUE_LABEL; ``provenance`` only adds a source beside it.
- KG11 (rule 13): a value is refused when any widget of its field is anchored "none", and when any is anchored in
  CONFIRM_TIERS unless the field is in ``confirmed_fields``.
- Rule 14: an unknown field name, a choice not in /Opt, a checkbox value naming no declared on-state, and a /MaxLen
  or comb violation refuse the whole call — no PDF is written and no value is echoed.

The binding readings of ADR-0002's open questions are module constants or predicates, each with a comment naming
its question, so the user's answer is a one-line change: Q1 (FORMAT_ACTION_IS_CALCULATED), Q11
(PROVENANCE_REPLACES_LABEL), Q13 (CONFIRM_TIERS); Q7 and Q14 live where the fetch enforces them
(fetch.revision_dated_accepted, fetch.REFUSE_PARTLY_SCANNED).
"""
from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from taxfill_core.anchor import LOW, MED, NONE, TIERS, TOP, WidgetAnchor, anchor_widgets
from taxfill_core.datadir import user_path, write_output
from taxfill_core.fetch import UnmappedBlank, compute_sha256, load_unmapped_blank, unmapped_cache_dir
from taxfill_core.packbuild import STANDARD_FORMAT, action_script

__all__ = [
    "CONFIRMED_LABEL",
    "CONFIRM_TIERS",
    "FORMAT_ACTION_IS_CALCULATED",
    "GRADE",
    "LIMITS",
    "PROVENANCE_REPLACES_LABEL",
    "PROVENANCE_SOURCES",
    "REFUSALS",
    "VALUE_LABEL",
    "calculated_reason",
    "describe_unmapped",
    "fill_unmapped",
    "value_label",
]

GRADE = "unmapped_draft"  # KG5: a constant; nothing a caller passes changes it
STATUS_DRAFT = "unverified_draft"
STATUS_WORKSHEET = "worksheet_only"
VALUE_LABEL = "agent-computed, unverified"  # KG7
CONFIRMED_LABEL = "user-confirmed on the rendered page"  # KG11
PROVENANCE_SOURCES = frozenset({"from a document", "from the user"})
RECORD_KEY = "/TaxfillUnmapped"  # the output's /Info record (ADR-0002 fill_form): no values in it

# ── binding readings of ADR-0002's open questions (each a one-line change once the user answers) ───────────────────

# ADR-0002 Open question 1 (KG7 and format actions), decided 2026-10-25: the user accepted the amendment. An /AA /F
# action refuses a field only when it is not a single call to one of Acrobat's standard format functions
# (packbuild.STANDARD_FORMAT), with the reason "custom_format_script"; /AA /C still refuses it as "calculated". The
# ADR measured the cached blanks' refused text widgets at 5.6% this way, 43% under the earlier reading (True: any /F).
FORMAT_ACTION_IS_CALCULATED = False

# ADR-0002 Open question 13 (a floor for "med"). Binding reading: "med" is refused like "low" unless the field is in
# confirmed_fields (KG6 says so until the user sets a floor from the JK15 table's measured med precision). Setting a
# floor is dropping MED from this set.
CONFIRM_TIERS = frozenset({LOW, MED})

# ADR-0002 Open question 11 (label exemptions). Binding reading: every written or listed value carries VALUE_LABEL and
# a declared provenance is only added beside it. A source the user lets stand in for the label goes in this set.
PROVENANCE_REPLACES_LABEL: frozenset[str] = frozenset()

# Why a field is never written (KG7, ADR-0002 rule 12, the JK15 note on hidden widgets), most specific first.
REFUSALS: dict[str, str] = {
    "signature": "a signature widget: sign the printed form by hand",
    "pushbutton": "a pushbutton holds no value",
    "viewer_guard": "a page-covering viewer guard (P-027), never a taxpayer line",
    "read_only": "ReadOnly: the form does not take a typed value here",
    "hidden": "hidden by its annotation flags (/F Hidden or NoView): the form shows it only through its own script",
    "calculated": ("the form computes it with its own script (an /AA /C calculate action, KG7) and taxfill runs no "
                   "form script: work out the value yourself and write it on the printed form by hand"),
    "custom_format_script": ("the form rewrites it with a custom format script (/AA /F that is not one standard "
                             "Acrobat format call, KG7): write it on the printed form by hand"),
    "unknown_kind": "a widget with no field type (/FT): no value can be written into it",
    "unanchored": "no printed line or caption could be tied to one of its boxes (anchored 'none', KG11)",
}
_REFUSAL_ORDER = tuple(REFUSALS)
_CONFIRM_TEXT = ("anchored only {tier!r}: confirm its boxes on the rendered sweep page and pass it in "
                 "confirmed_fields, or write it on the printed form by hand (KG11)")

LIMITS: list[str] = [
    "no line map: each field was tied to a printed line by a pack-blind anchor, an unverified guess",
    "no relations of record: no line's arithmetic was checked",
    "no identity or cross_form checks",
    "no P-003 required-checkbox audit",
    "no revision pin: the blank is named by its sha256 only, and its revision was not reviewed",
    "form scripts and XFA bindings did not run: calculated boxes and boxes with a custom format script stay blank "
    "(hand_write); a box with a standard Acrobat format is written as given, unformatted",
    f"every value is {VALUE_LABEL}",
    "this draft is never filing-grade, whatever any check says",
]
NEXT_STEP_FILL = (
    "This is an unverified draft, never filing-grade: run verify_form with form='unmapped' on this output, then "
    "render_form on every page and check each value against its printed line; write the hand_write entries on the "
    "printed form by hand."
)
NEXT_STEP_WORKSHEET = (
    "No PDF was written. Copy each worksheet line onto the printed form by hand, checking it against the form's "
    "instructions; every value is agent-computed and unverified, and the result is never filing-grade."
)
NEXT_STEP_DESCRIBE = (
    "Show the sweep page with render_form; a field anchored 'low' or 'med' is written only after the user confirms "
    "its boxes there (confirmed_fields). Fill with values keyed by these field names; the output is an unverified "
    "draft, never filing-grade."
)

_ON_WORDS = frozenset({"yes", "y", "true", "on", "x", "checked"})
_OFF_WORDS = frozenset({"no", "n", "false", "off", "unchecked", ""})
_TEXT_KINDS = frozenset({"text", "choice"})
_BUTTON_KINDS = frozenset({"checkbox", "radio"})


class UnmappedFillRefused(ValueError):
    """Rule 14 (or another whole-call refusal): no PDF was written; the message names no value."""


# ── Q1: calculated widgets ───────────────────────────────────────────────────


def calculated_reason(nodes: Sequence) -> str | None:
    """"calculated" when a widget or a field above it (``nodes``: the widget and its /Parent chain) carries an /AA /C
    (calculate) action (or any /AA /F while FORMAT_ACTION_IS_CALCULATED); "custom_format_script" for an /F that is
    not one standard format call (Open question 1's amendment, accepted 2026-10-25); else None."""
    reason = None
    for node in nodes:
        aa = node.get("/AA")
        if aa is None:
            continue
        aa = aa.get_object()
        if "/C" in aa:
            return "calculated"
        if "/F" in aa:
            if FORMAT_ACTION_IS_CALCULATED:
                return "calculated"
            if not STANDARD_FORMAT.match(action_script(aa["/F"])):
                reason = "custom_format_script"
    return reason


def value_label(source: str | None) -> str:
    """KG7's label for one value, with its declared provenance beside it (Open question 11's binding reading)."""
    if source in PROVENANCE_REPLACES_LABEL:
        return str(source)
    return f"{VALUE_LABEL}; {source}" if source else VALUE_LABEL


# ── reading the blank ────────────────────────────────────────────────────────


@dataclass
class _Widget:
    info: dict
    anchor: WidgetAnchor
    refusal: str | None
    rect: list[float]


@dataclass
class _Field:
    index: int
    name: str
    kind: str
    info: dict
    widgets: list[_Widget] = field(default_factory=list)

    @property
    def refusal(self) -> str | None:
        reasons = {w.refusal for w in self.widgets if w.refusal}
        if reasons:
            return min(reasons, key=_REFUSAL_ORDER.index)
        if any(w.anchor.confidence == NONE for w in self.widgets):
            return "unanchored"
        return None

    @property
    def confidence(self) -> str:
        return max((w.anchor.confidence for w in self.widgets), key=TIERS.index)

    @property
    def needs_confirmation(self) -> bool:
        return any(w.anchor.confidence in CONFIRM_TIERS for w in self.widgets)

    @property
    def on_states(self) -> list[str]:
        out: list[str] = []
        for w in self.widgets:
            out.extend(s for s in w.info.get("on_states") or [] if s not in out)
        return out

    @property
    def first(self) -> _Widget:
        return self.widgets[0]


def _widget_refusal(info: dict, annot, page_box) -> str | None:
    from taxfill_core.filler import F_HIDDEN, F_NOVIEW, is_viewer_guard  # noqa: PLC0415
    from taxfill_core.packbuild import _chain  # noqa: PLC0415

    kind = info["kind"]
    if kind == "signature":
        return "signature"
    if kind == "pushbutton":
        return "pushbutton"
    if is_viewer_guard(annot, page_box):
        return "viewer_guard"
    if info.get("read_only"):
        return "read_only"
    if int(annot.get("/F", 0)) & (F_HIDDEN | F_NOVIEW):
        return "hidden"
    calculated = calculated_reason(_chain(annot))
    if calculated:
        return calculated
    if kind == "unknown":
        return "unknown_kind"
    return None


def _read_fields(path: Path, table: str | Path | None) -> tuple[list[_Field], dict]:
    """Every field of the blank in document order, its widgets anchored; and the anchor basis."""
    from pypdf import PdfReader  # noqa: PLC0415

    from taxfill_core.filler import visible_box  # noqa: PLC0415
    from taxfill_core.packbuild import _qualified_name, extract_fields  # noqa: PLC0415

    infos = extract_fields(path)
    amap = anchor_widgets(path, table=table)
    reader = PdfReader(str(path))
    annots = []
    for page in reader.pages:
        box = visible_box(page)
        for ref in page.get("/Annots") or []:
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Widget" and _qualified_name(obj):
                annots.append((obj, box))
    if not (len(infos) == len(amap.widgets) == len(annots)):  # all three walk /Annots in page order
        raise RuntimeError(f"widget walk mismatch ({len(infos)} / {len(amap.widgets)} / {len(annots)})")
    fields: dict[str, _Field] = {}
    for info, anchor, (annot, box) in zip(infos, amap.widgets, annots):
        f = fields.get(info["name"])
        if f is None:
            f = fields[info["name"]] = _Field(index=len(fields) + 1, name=info["name"], kind=info["kind"], info=info)
        rect = [float(v) for v in info["rect"]] if len(info["rect"]) == 4 else [0.0, 0.0, 0.0, 0.0]
        f.widgets.append(_Widget(info=info, anchor=anchor, refusal=_widget_refusal(info, annot, box), rect=rect))
    return list(fields.values()), amap.basis


def _table_passed(basis: dict) -> bool:
    """KG6: the PDF fill is built only on a passing anchor benchmark table that licenses tiers above "low"."""
    return basis.get("passed") is True and TOP in (basis.get("tiers") or [])


def _field_entry(f: _Field) -> dict:
    info = f.info
    refusal = f.refusal
    return {
        "index": f.index, "name": f.name, "kind": f.kind, "tooltip": info.get("tooltip"), "maxlen": info.get("maxlen"),
        "comb": bool(info.get("comb")), "multiline": bool(info.get("multiline")), "options": info.get("options") or [],
        "on_states": f.on_states, "fillable": refusal is None, "refusal": refusal,
        "needs_confirmation": refusal is None and f.needs_confirmation,
        "widgets": [{"page": w.info["page"], "rect": w.rect,
                     "anchor": {"printed_line": w.anchor.printed_line, "label": w.anchor.label,
                                "confidence": w.anchor.confidence}} for w in f.widgets],
        "confidence": f.confidence,
    }


def _place(f: _Field) -> dict:
    a = f.first.anchor
    return {"field": f.name, "page": f.first.info["page"], "pages": sorted({w.info["page"] for w in f.widgets}),
            "printed_line": a.printed_line, "label": a.label}


def _hand_write(f: _Field, reason: str, value: object = None, *, tier: str | None = None) -> dict:
    why = _CONFIRM_TEXT.format(tier=tier) if reason == "needs_confirmation" else REFUSALS[reason]
    entry = {**_place(f), "value": value, "reason": reason, "why": why}
    if value is not None:
        entry["value_label"] = VALUE_LABEL
    return entry


# ── describe (get_form_map) ──────────────────────────────────────────────────


def _sweep(path: Path, fields: list[_Field], out: Path) -> list[dict]:
    """The sweep copy: every widget hidden, each fillable field's boxes outlined and labelled "#<index>" in the content
    stream, every page stamped. Written once, from memory."""
    from pypdf import PdfWriter  # noqa: PLC0415

    from taxfill_core.filler import UNMAPPED_STAMP, _drop_xfa  # noqa: PLC0415
    from taxfill_core.overlay import _num, _overlay_page, _text_op  # noqa: PLC0415
    from taxfill_core.stamp import draw_stamp, stamp_check  # noqa: PLC0415

    writer = PdfWriter(clone_from=str(path))
    _drop_xfa(writer)
    obstacles: list[list[tuple[float, float, float, float]]] = [[] for _ in writer.pages]
    marks: list[bytes] = [b"" for _ in writer.pages]
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") == "/Widget":
                from pypdf.generic import NameObject, NumberObject  # noqa: PLC0415

                annot[NameObject("/F")] = NumberObject(2)  # Hidden: the outlines and indexes below show the boxes
    for f in fields:
        for w in f.widgets:
            x0, y0, x1, y1 = w.rect
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            if f.refusal is not None or x1 - x0 < 1 or y1 - y0 < 1:
                continue  # hidden in the sweep and drawn nowhere: nothing for the stamp to avoid
            obstacles[w.info["page"] - 1].append((x0, y0, x1, y1))
            size = max(4.0, min(8.0, (y1 - y0) * 0.7))
            op, _ = _text_op(x0 + 1.0, y0 + max(0.5, (y1 - y0 - size) / 2 + 0.2 * size), size, f"#{f.index}")
            marks[w.info["page"] - 1] += (b"q 0 0 0.75 RG 0 0 0.75 rg 0.6 w " + b" ".join(
                _num(v) for v in (x0, y0, x1 - x0, y1 - y0)) + b" re S " + op + b"Q\n")
    for page, content in zip(writer.pages, marks):
        if content:
            page.merge_page(_overlay_page(page, content))
    stamp = draw_stamp(writer, path, UNMAPPED_STAMP, extra_obstacles=obstacles, what="the sweep copy")
    buf = io.BytesIO()
    writer.write(buf)
    check = stamp_check(buf.getvalue(), UNMAPPED_STAMP)
    if not check["ok"]:  # KG5 holds for the sweep too: it is written only once its stamp prints on every page
        raise UnmappedFillRefused(f"the sweep copy's stamp does not print on page(s) {check['failed_pages']} — no "
                                  f"sweep was written; print the blank from the agency's forms page and fill it by hand")
    write_output(out, lambda fh: fh.write(buf.getvalue()))
    return stamp


def describe_unmapped(
    blank: UnmappedBlank,
    *,
    sweep_path: str | Path | None = None,
    anchor_table: str | Path | None = None,
) -> dict:
    """get_form_map's unmapped response for a blank from ``fetch.load_unmapped_blank`` (ADR-0002 Decision).

    Keys: ``grade``, ``form`` ("unmapped"), ``jurisdiction``, ``tax_year``, ``source_url``, ``blank_sha256``,
    ``fields`` (name, kind, tooltip, maxlen, comb, multiline, options, on_states, fillable, refusal,
    needs_confirmation, widgets with page / rect / anchor, confidence; plus the ``index`` the sweep shows),
    ``hand_write`` (every field that is never filled, with its reason), ``sweep_path``, ``anchor_basis``, ``limits``
    and ``next_step``. ``sweep_path`` defaults to ``<sha256>.sweep.pdf`` beside the blank; ``anchor_table`` overrides
    the committed benchmark table (tests).
    """
    path = Path(blank.path)
    fields, basis = _read_fields(path, anchor_table)
    out = user_path(sweep_path) if sweep_path is not None else path.with_name(f"{blank.sha256}.sweep.pdf")
    if out.resolve() in {path.resolve(), path.with_suffix(".json").resolve()}:  # Phase K JK16 (2026-10-25)
        raise UnmappedFillRefused("sweep_path is the stored blank or its record — pass a new file path for the sweep "
                                  "copy, or leave sweep_path out; nothing was written")
    _sweep(path, fields, out)
    return {
        "grade": GRADE, "form": "unmapped", "jurisdiction": blank.jurisdiction, "tax_year": blank.tax_year,
        "source_url": blank.source_url, "blank_sha256": blank.sha256,
        "fields": [_field_entry(f) for f in fields],
        "hand_write": [_hand_write(f, f.refusal) for f in fields if f.refusal is not None],
        "sweep_path": str(out), "anchor_basis": basis, "limits": list(LIMITS), "next_step": NEXT_STEP_DESCRIBE,
    }


# ── writing values: exactly the fields named, nothing else (Phase K JK16 fix, 2026-10-25) ──────────────────────


def _terminal(annot):
    """The field dict that holds a widget's value: the widget itself when it carries /T (a merged field), else its
    /Parent."""
    if annot.get("/T") is not None:
        return annot
    parent = annot.get("/Parent")
    return parent.get_object() if parent is not None else annot


def _write_text_fields(writer, updates: Mapping[str, str]) -> None:
    """Write each text or choice value into the widgets of exactly the field it names, with its appearance.

    pypdf's update_page_form_field_values matches a widget when its qualified name OR its terminal /T equals a key, so
    a value for "wages" also lands in "sub.wages" (a calculated, unanchored, ReadOnly or hidden field that shares the
    leaf name) and is printed there unreported (KG7). It is therefore called once per widget, on a one-widget stand-in
    for the page (pypdf reads the page only to flatten). pypdf also builds an appearance only when the node it treats
    as the field carries /FT itself, so a field that inherits /FT from an ancestor got a /V and a blank box; the
    inherited /FT is copied onto the terminal field first (the same type, stated where pypdf looks for it)."""
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject  # noqa: PLC0415

    from taxfill_core.packbuild import _inherited, _qualified_name  # noqa: PLC0415

    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(annot)
            if name not in updates:
                continue
            terminal = _terminal(annot)
            if terminal.get("/FT") is None:
                inherited = _inherited(annot, "/FT")
                if inherited is not None:
                    terminal[NameObject("/FT")] = NameObject(str(inherited))
            stand_in = DictionaryObject({NameObject("/Annots"): ArrayObject([ref])})
            writer.update_page_form_field_values(stand_in, {name: updates[name]}, auto_regenerate=None)


def _field_states(reader) -> dict[str, tuple]:
    """Every field's value as the PDF holds it: qualified name -> (/V up the /Parent chain, each widget's /AS)."""
    from taxfill_core.packbuild import _inherited, _qualified_name  # noqa: PLC0415

    out: dict[str, tuple] = {}
    for page in reader.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(annot)
            if not name:
                continue
            value = _inherited(annot, "/V")
            value = None if value is None else str(value.get_object())
            states = out.get(name, (None, ()))[1]
            state = annot.get("/AS")
            out[name] = (value, (*states, None if state is None else str(state)))
    return out


def _audit_values(blank: Path, data: bytes, written: Mapping[str, str]) -> None:
    """The draft holds exactly ``written``: every written field carries its value, and no other field's /V or /AS
    differs from the blank's. Run on the bytes before they reach disk; a mismatch refuses the call (KG7: no value
    may reach a field the response does not report)."""
    from pypdf import PdfReader  # noqa: PLC0415

    before = _field_states(PdfReader(str(blank)))
    after = _field_states(PdfReader(io.BytesIO(data)))
    stray = sorted(n for n in after.keys() | before.keys() if n not in written and after.get(n) != before.get(n))
    unstored = sorted(n for n, v in written.items()
                      if (after.get(n) or (None,))[0] != v and not (v == "/Off" and (after.get(n) or (None,))[0] is None))
    if stray or unstored:
        parts = []
        if stray:
            parts.append(f"{len(stray)} field(s) not asked for changed ({', '.join(map(repr, stray[:10]))})")
        if unstored:
            parts.append(f"{len(unstored)} value(s) did not reach their field ({', '.join(map(repr, unstored[:10]))})")
        raise UnmappedFillRefused(
            f"the draft does not hold exactly the values written: {'; '.join(parts)} — no PDF was written; write "
            f"these values on the printed form by hand, and report the blank's URL so the writer can be fixed")


# ── fill (fill_form) ─────────────────────────────────────────────────────────


def _build_draft(path: Path, text_updates: Mapping[str, str], button_updates: Mapping[str, tuple[str, str]],
                 written: Mapping[str, str], *, what: str):
    """The draft's whole document, as fill_form writes it from the blank at ``path``: (writer, stamp placements,
    viewer guards hidden). Everything but the /Info record is here, so the result is a function of the blank and
    the written values alone. Phase K JK17 (2026-10-25): verify_unmapped rebuilds the draft with this same function
    and compares the file against it object by object, so a change the fill did not make (an edited appearance, a
    document script, a second stamp) fails verify."""
    from pypdf import PdfWriter  # noqa: PLC0415

    from taxfill_core.filler import (  # noqa: PLC0415
        UNMAPPED_STAMP,
        _annotation_flag_pass,
        _drop_xfa,
        _repair_empty_field_array,
        _set_checkboxes,
    )
    from taxfill_core.stamp import draw_stamp  # noqa: PLC0415

    writer = PdfWriter(clone_from=str(path))
    _repair_empty_field_array(writer)
    if text_updates:  # per widget, never by pypdf's leaf-name match (KG7)
        _write_text_fields(writer, text_updates)
    if button_updates:
        _set_checkboxes(writer, dict(button_updates))
    guards_hidden = _annotation_flag_pass(writer, written)
    writer.set_need_appearances_writer(True)
    _drop_xfa(writer)
    stamp = draw_stamp(writer, path, UNMAPPED_STAMP, what=what)
    return writer, stamp, guards_hidden


def _names(kind: str, names) -> list[str]:
    if names is None:
        return []
    if isinstance(names, (str, bytes)) or not all(isinstance(n, str) for n in names):
        raise UnmappedFillRefused(f"{kind} must be a list of field names — nothing was written")
    return list(names)


def _not_win_ansi(text: str) -> int:
    """How many characters of ``text`` WinAnsiEncoding (Windows-1252), the encoding of the standard fonts a text box's
    appearance is drawn in, cannot hold (rule 14: such a value is refused, not written corrupted)."""
    count = 0
    for ch in text:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            count += 1
    return count


def _render_text(f: _Field, value: object, money: bool, warnings: list[str]) -> str:
    """The text one value writes into a text or choice field; rule 14 refuses without echoing the value."""
    from taxfill_core.filler import whole_dollars  # noqa: PLC0415

    what = f"field {f.name!r}"
    if money:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise UnmappedFillRefused(f"{what} is marked as money: pass a plain number (int, float or Decimal), with no "
                                      f"'$' or ',' — nothing was written")
        try:
            text, warning = whole_dollars(value, what)
        except ValueError:
            raise UnmappedFillRefused(f"{what} is marked as money but its value is not a finite number — pass a plain "
                                      f"number; nothing was written") from None
        if warning:
            warnings.append(warning)
    elif isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnmappedFillRefused(f"{what} takes a string (got {type(value).__name__}); for a whole-dollar amount pass a "
                                  f"number and list the field in money_fields — nothing was written")
    else:
        text = str(value)
    if f.kind == "choice":
        options = f.info.get("options") or []
        match = next((o["export"] for o in options if text in (o["export"], o["display"])), None)
        if match is None:
            raise UnmappedFillRefused(
                f"{what}: the value is not one of the {len(options)} choices its /Opt lists — pass one of the options "
                f"get_form_map returns for it; nothing was written")
        return match
    unprintable = _not_win_ansi(text)
    if unprintable:  # Phase K JK16 (2026-10-25): pypdf only logs "text corruption" and writes a garbled box
        raise UnmappedFillRefused(
            f"{what}: the value holds {unprintable} character(s) the form's font cannot print (outside the WinAnsi set "
            f"a form's text boxes use: CJK, emoji and most non-Latin scripts) — pass the value in Latin characters, "
            f"or write it on the printed form by hand; nothing was written")
    maxlen = f.info.get("maxlen")
    if maxlen is not None and len(text) > maxlen:
        box = "comb box" if f.info.get("comb") else "box"
        raise UnmappedFillRefused(
            f"{what}: the value is {len(text)} characters but its {box} holds at most {maxlen} (/MaxLen) — shorten it "
            f"to {maxlen} or fewer, or write it on the printed form by hand; nothing was written")
    if ("\n" in text or "\r" in text) and not f.info.get("multiline"):
        raise UnmappedFillRefused(f"{what} is a single-line box but the value holds a line break — pass one line; "
                                  f"nothing was written")
    return text


def _button_state(f: _Field, value: object) -> str:
    """The /AS state a checkbox or radio value names: a declared on-state, or /Off; rule 14 refuses anything else."""
    states = f.on_states
    what = f"field {f.name!r}"
    if isinstance(value, bool):
        word = "yes" if value else "no"
    elif isinstance(value, str):
        word = value.strip()
    else:
        raise UnmappedFillRefused(f"{what} is a {f.kind}: pass one of its on-states {states}, or yes / no — nothing "
                                  f"was written")
    named = word if word.startswith("/") else f"/{word}"
    if named in states:
        return named
    if word.lower() in _OFF_WORDS or named == "/Off":
        return "/Off"
    if word.lower() in _ON_WORDS and len(states) == 1:
        return states[0]
    raise UnmappedFillRefused(
        f"{what}: the value names no on-state the widget declares ({states}) — pass one of them"
        + (" (yes is ambiguous: the field has several)" if len(states) > 1 else "") + "; nothing was written")


def _line_order(entry: dict, index: int, f: _Field | None) -> tuple:
    """Worksheet order: by page, then by printed line; a line with no printed number after the numbered ones, top to
    bottom and left to right by its first box; then the caller's order."""
    from taxfill_core.anchor import _line_key  # noqa: PLC0415

    line = entry.get("printed_line")
    if line:
        return (entry.get("page") or 0, 0, *_line_key(line), 0.0, 0.0, index)
    rect = f.first.rect if f is not None else [0.0, 0.0, 0.0, 0.0]
    return (entry.get("page") or 0, 1, 0, "", -max(rect[1], rect[3]), min(rect[0], rect[2]), index)


def _worksheet(blank: UnmappedBlank, lines: list[tuple[dict, _Field | None]], note: str | None = None) -> dict:
    keyed = [(_line_order(line, i, f), line) for i, (line, f) in enumerate(lines)]
    ordered = [line for _, line in sorted(keyed, key=lambda pair: pair[0])]
    sheet = {"grade": GRADE, "form": "unmapped", "source_url": blank.source_url, "blank_sha256": blank.sha256,
             "tax_year": blank.tax_year, "jurisdiction": blank.jurisdiction, "lines": ordered}
    if note:
        sheet["note"] = note
    return sheet


def _check_inputs(values, money_fields, provenance, confirmed_fields, known: set[str] | None):
    if not isinstance(values, Mapping) or not all(isinstance(k, str) for k in values):
        raise UnmappedFillRefused("values must map field names to values — nothing was written")
    money, confirmed = _names("money_fields", money_fields), _names("confirmed_fields", confirmed_fields)
    provenance = dict(provenance or {})
    if known is not None:
        unknown = sorted({*values, *money, *confirmed} - known)
        if unknown:
            shown = ", ".join(repr(n) for n in unknown[:10]) + (f" and {len(unknown) - 10} more" if len(unknown) > 10
                                                                 else "")
            raise UnmappedFillRefused(
                f"unknown field name(s) {shown}: the blank has no such field — use the qualified names get_form_map "
                f"returns for this blank; nothing was written")
    stray = sorted(set(provenance) - set(values))
    if stray:
        raise UnmappedFillRefused(f"provenance names field(s) with no value ({', '.join(map(repr, stray[:10]))}) — "
                                  f"declare a source only for a value you pass; nothing was written")
    bad = sorted(k for k, v in provenance.items() if v not in PROVENANCE_SOURCES)
    if bad:
        raise UnmappedFillRefused(f"provenance for {', '.join(map(repr, bad[:10]))} must be one of "
                                  f"{sorted(PROVENANCE_SOURCES)} — nothing was written")
    return set(money), provenance, set(confirmed)


def _labels(names, provenance: Mapping[str, str]) -> dict[str, str]:
    return {name: value_label(provenance.get(name)) for name in names}


def _worksheet_only(blank: UnmappedBlank, values, provenance, fields: list[_Field] | None, money: set[str],
                    why: str) -> dict:
    """Rule 10 (a flat blank) and KG6 (no passing anchor table): no PDF, a graded worksheet of every value."""
    warnings: list[str] = []
    lines, hand_write = [], []
    by_name = {f.name: f for f in fields or []}
    for key, value in values.items():
        f = by_name.get(key)
        if f is not None:
            shown = (_button_state(f, value) if f.kind in _BUTTON_KINDS
                     else _render_text(f, value, key in money, warnings) if f.kind in _TEXT_KINDS else value)
            place = _place(f)
        else:  # a flat blank: the key is the printed line as the agent reads it
            shown, place = value, {"field": None, "page": None, "pages": [], "printed_line": key, "label": None}
        label = value_label(provenance.get(key))
        lines.append(({**place, "value": shown, "value_label": label, "status": "hand_write"}, f))
        hand_write.append({**place, "value": shown, "value_label": label, "reason": STATUS_WORKSHEET, "why": why})
    note = None if fields else "no printed line was matched to a box: this blank has no fillable field"
    return {
        "grade": GRADE, "status": STATUS_WORKSHEET, "worksheet": _worksheet(blank, lines, note),
        "hand_write": hand_write, "labels": _labels(values, provenance), "warnings": warnings,
        "limits": list(LIMITS), "next_step": NEXT_STEP_WORKSHEET,
    }


def fill_unmapped(
    blank_sha256: str,
    *,
    source_url: str,
    tax_year: int,
    jurisdiction: str,
    values: Mapping[str, object],
    out_path: str | Path,
    money_fields: Sequence[str] | None = None,
    provenance: Mapping[str, str] | None = None,
    confirmed_fields: Sequence[str] | None = None,
    expected_title: str | None = None,
    cache_dir: str | Path | None = None,
    workspace_root: str | Path | None = None,
    anchor_table: str | Path | None = None,
) -> dict:
    """Fill a blank that has no pack (ADR-0002 fill_form, ``form="unmapped"``); return the PDF or worksheet response.

    The blank is loaded by ``blank_sha256`` + ``source_url`` (+ ``jurisdiction``) through
    ``fetch.load_unmapped_blank``, which re-runs every fetch check, rule 1 (a shipped pack wins) and rule 5 (no typed
    value in a local blank) among them. ``values`` is keyed by qualified field name (for a flat blank, by the printed
    line). ``money_fields`` get IRS whole-dollar rendering; ``provenance`` ("from a document" / "from the user") is
    recorded beside the KG7 label; ``confirmed_fields`` are the fields whose boxes the user confirmed on the sweep page.
    There is no switch for the stamp or the grade.

    PDF response: ``grade``, ``status`` ("unverified_draft"), ``out_path``, ``output_sha256``, ``written`` (field ->
    the rendered value or on-state), ``hand_write`` (field, page, printed_line, label, value, reason), ``labels``,
    ``confirmed``, ``stamp`` (text, pages, placements), ``worksheet`` (its own ``grade``; lines ordered by page and
    printed line), ``warnings``, ``guards_hidden``, ``limits``, ``next_step``. Worksheet-only response (a flat blank,
    rule 10, or no passing anchor table, KG6): ``grade``, ``status`` ("worksheet_only"), ``worksheet``,
    ``hand_write`` (every value), ``labels``, ``warnings``, ``limits``, ``next_step``; no PDF is written.

    Raises ``fetch.UnmappedBlankRefused`` (a fetch check, rule 1), :class:`UnmappedFillRefused` (rule 14 and other
    whole-call refusals; no PDF written, no value echoed) and ``stamp.StampRefused`` (a page with no room).
    """
    from taxfill_core.filler import UNMAPPED_STAMP  # noqa: PLC0415
    from taxfill_core.stamp import stamp_check  # noqa: PLC0415

    blank = load_unmapped_blank(blank_sha256, tax_year=tax_year, source_url=source_url, jurisdiction=jurisdiction,
                                expected_title=expected_title, cache_dir=cache_dir, workspace_root=workspace_root)
    if blank.kind == "flat":  # rule 10: nothing to fill
        money, prov, _ = _check_inputs(values, money_fields, provenance, confirmed_fields, None)
        return _worksheet_only(blank, values, prov, None, money,
                               "the blank has no fillable field (a flat form): write it on the printed form by hand")
    path = Path(blank.path)
    fields, basis = _read_fields(path, anchor_table)
    by_name = {f.name: f for f in fields}
    money, prov, confirmed = _check_inputs(values, money_fields, provenance, confirmed_fields, set(by_name))
    not_text = sorted(n for n in money if by_name[n].kind != "text")
    if not_text:
        raise UnmappedFillRefused(f"money_fields names {', '.join(map(repr, not_text[:10]))}, which "
                                  f"{'is' if len(not_text) == 1 else 'are'} not a text field — nothing was written")
    if not _table_passed(basis):  # KG6: no passing benchmark table, no PDF fill
        return _worksheet_only(blank, values, prov, fields, money,
                               "no anchor benchmark table has passed (KG6), so no value is written into the PDF")

    # Rule 14 first, over every value: a malformed one refuses the whole call before anything is written.
    warnings: list[str] = []
    rendered: dict[str, str] = {}
    for name, value in values.items():
        f = by_name[name]
        if f.kind in _BUTTON_KINDS:
            rendered[name] = _button_state(f, value)
        elif f.kind in _TEXT_KINDS:
            rendered[name] = _render_text(f, value, name in money, warnings)
    out_path = user_path(out_path)
    if out_path.resolve() == path.resolve():
        raise UnmappedFillRefused("out_path is the stored blank itself — pass a new file path for the draft, such as "
                                  "~/taxfill-workspace/<year>/drafts/<form>.pdf; nothing was written")
    # The shared blank cache holds blanks, their records and sweep pages, never a value (ADR-0002 rules 5-6), and
    # `taxfill purge` does not clear it (Phase K JK16b review, 2026-10-25: out_path = the sweep page wrote the values
    # there).
    if out_path.resolve().is_relative_to(unmapped_cache_dir(cache_dir).resolve()):
        raise UnmappedFillRefused("out_path is inside the shared blank cache, which never holds a value — pass a file "
                                  "path in your workspace, such as ~/taxfill-workspace/<year>/drafts/<form>.pdf; "
                                  "nothing was written")

    hand_write: list[dict] = []
    text_updates: dict[str, str] = {}
    button_updates: dict[str, tuple[str, str]] = {}
    for name, value in values.items():
        f = by_name[name]
        shown = rendered.get(name, value)
        if f.refusal is not None:
            hand_write.append(_hand_write(f, f.refusal, shown))
            continue
        lowest = f.confidence
        if f.needs_confirmation and name not in confirmed:
            hand_write.append(_hand_write(f, "needs_confirmation", shown, tier=lowest))
            continue
        if f.kind in _BUTTON_KINDS:
            button_updates[name] = (name, rendered[name])
        else:
            text_updates[name] = rendered[name]
    written = {**text_updates, **{n: s for n, (_, s) in button_updates.items()}}
    written = {n: written[n] for n in values if n in written}  # the caller's order

    writer, stamp, guards_hidden = _build_draft(path, text_updates, button_updates, written,
                                                what=f"the blank {blank.sha256[:16]}")
    labels = _labels(written, prov)
    confirmed_map = {n: CONFIRMED_LABEL for n in written if n in confirmed}
    record = {
        "grade": GRADE, "stamp": UNMAPPED_STAMP, "source_url": blank.source_url, "blank_sha256": blank.sha256,
        "tax_year": blank.tax_year, "jurisdiction": blank.jurisdiction, "written_fields": list(written),
        "labels": labels, "sources": {n: prov[n] for n in written if n in prov}, "confirmed": confirmed_map,
    }
    writer.add_metadata({RECORD_KEY: json.dumps(record, sort_keys=True)})
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    _audit_values(path, data, written)
    check = stamp_check(data, UNMAPPED_STAMP)
    if not check["ok"]:
        raise UnmappedFillRefused(
            f"the draft's stamp does not print on page(s) {check['failed_pages']} — no PDF was written; this form "
            f"cannot be drafted here: print the blank from the agency's forms page and fill it by hand")
    write_output(out_path, lambda fh: fh.write(data))

    lines = []
    for name, value in values.items():
        f = by_name[name]
        status = "written" if name in written else "hand_write"
        lines.append(({**_place(f), "value": written.get(name, rendered.get(name, value)),
                       "value_label": value_label(prov.get(name)), "status": status}, f))
    if not written:
        warnings.append("no value was written: every value is in hand_write (the PDF is the stamped blank)")
    return {
        "grade": GRADE, "status": STATUS_DRAFT, "out_path": str(out_path), "output_sha256": compute_sha256(out_path),
        "written": written, "hand_write": hand_write, "labels": labels, "confirmed": confirmed_map,
        "stamp": {"text": UNMAPPED_STAMP, "pages": [p["page"] for p in stamp], "placements": stamp},
        "worksheet": _worksheet(blank, lines), "warnings": warnings, "guards_hidden": guards_hidden,
        "limits": list(LIMITS), "next_step": NEXT_STEP_FILL,
    }
