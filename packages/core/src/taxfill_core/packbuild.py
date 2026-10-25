"""Pack-authoring helper — dev plan section 8 / M7 (mechanize form-pack creation).

Turning a blank AcroForm PDF into a ``pack.yaml`` is mostly boilerplate: dump
every widget, detect the XFA AcroForm root, strip it off each field name, compute
the blank's checksum. This module does exactly that and emits a **skeleton**
FormPack so the only human work left is the part that needs judgment — naming
each logical line and writing the relations — which the vision-mapping step then
fills in against the sentinel-sweep render.

The skeleton is deliberately NOT shippable: its ``line`` keys are the raw field
paths (a "rename me" placeholder), and a companion TODO lists the checkboxes
whose on-state could not be detected. A pack only ships after the vision map +
adversarial audit. The skeleton just removes the typing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, StreamObject, TextStringObject

from taxfill_core.fetch import compute_sha256

__all__ = ["FieldInfo", "extract_fields", "detect_acroform_root", "build_skeleton", "sentinel_sweep"]


class FieldInfo(dict):
    """A single widget (a plain dict).

    The original keys keep their meaning: ``name`` (fully qualified), ``type`` ("checkbox" for every /Btn widget,
    else "text" — build_skeleton keys on it), ``page``, ``rect``, ``maxlen``, ``on_states``.

    Phase K JK14 (2026-10-24) adds, read up the /Parent chain where the spec makes the key inheritable:

    - ``kind``: "text", "checkbox", "radio", "pushbutton", "choice", "signature", or "unknown" (no /FT at all);
      ``choice_type`` ("combo" or "list") and ``options`` (the /Opt entries as ``{"export", "display"}``) for a
      choice field, ``options`` too for a button that declares /Opt;
    - ``tooltip`` (/TU), ``ff`` (the raw /Ff integer) and the named flag booleans ``read_only``, ``required``,
      ``multiline``, ``password``, ``comb``, ``do_not_scroll`` (text fields), ``pushbutton``, ``radio``,
      ``no_toggle_to_off`` (buttons) — a bit that the field's type does not define reads False;
    - ``da_font`` / ``da_size`` (the /DA font resource name and size, the AcroForm /DA when the field has none;
      a size of 0 means auto-size) and ``quadding`` (/Q: 0 left, 1 centred, 2 right; the AcroForm /Q, else 0);
    - ``calculated``: the field or widget carries an /AA /C (calculate) action, or an /AA /F (format) action that is
      anything but a single call to one of Acrobat's standard format functions (KG7 as amended 2026-10-25, ADR-0002
      Open question 1) — such a widget is never written by the pack-less fallback, ReadOnly or not;
      ``format_action``: it carries any /AA /F; ``javascript``: any /AA or /A action on it is JavaScript.
    """


# /Ff bit positions (PDF 32000-1:2008 tables 221, 226, 228, 230): bit n is the value 1 << (n - 1).
FF_READ_ONLY = 1 << 0
FF_REQUIRED = 1 << 1
FF_MULTILINE = 1 << 12        # text
FF_PASSWORD = 1 << 13         # text
FF_NO_TOGGLE_TO_OFF = 1 << 14  # button (radio)
FF_RADIO = 1 << 15            # button
FF_PUSHBUTTON = 1 << 16       # button
FF_COMBO = 1 << 17            # choice
FF_DO_NOT_SCROLL = 1 << 23    # text
FF_COMB = 1 << 24             # text

_DA_FONT_RE = re.compile(r"/([^\s/\[\]()<>]+)\s+(-?[\d.]+)\s+Tf")
# The /AA triggers that make a field computed or reformatted by the viewer (KG7).
# KG7 as amended (ADR-0002 Open question 1, accepted by the user 2026-10-25): a calculate (/C) action may compute the
# value, and so may a format (/F) action, unless it is a single call to one of Acrobat's standard format functions,
# which only formats the value it is given.
STANDARD_FORMAT = re.compile(
    r"^\s*AF(?:Number|Percent|Date|Time|Special)_Format(?:Ex)?\s*\([^;()]*\)\s*;?\s*$", re.DOTALL)


def action_script(action) -> str:
    """An action's JavaScript text ("" when it carries none)."""
    action = action.get_object()
    js = action.get("/JS") if hasattr(action, "get") else None
    if js is None:
        return ""
    js = js.get_object()
    if hasattr(js, "get_data"):
        return js.get_data().decode("latin-1", "replace")
    return str(js)


def _qualified_name(annot) -> str:
    """Fully qualified field name: /T parts joined by '.' up the /Parent chain.

    Mirrors taxfill_core.filler._qualified_name so a skeleton's `field` matches the
    name the filler/verifier address on real hierarchical (XFA) IRS AcroForms — not
    just the leaf /T (which only coincides on flat state forms).
    """
    parts: list[str] = []
    node = annot
    seen: set[int] = set()
    while node is not None:
        if id(node) in seen:
            break
        seen.add(id(node))
        title = node.get("/T")
        if title:
            parts.append(str(title))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _chain(annot) -> list:
    """The widget and every ancestor field dict, nearest first (cycle-safe)."""
    nodes: list = []
    node = annot
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        nodes.append(node)
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return nodes


def _inherited(annot, key: str):
    """Walk the /Parent chain for an inheritable attribute (/FT, /MaxLen, /Ff, /DA, /Q, /Opt)."""
    for node in _chain(annot):
        if node.get(key) is not None:
            return node.get(key)
    return None


def _options(opt) -> list[dict[str, str]]:
    """/Opt as export/display pairs: an entry is a text string (both) or a two-element array [export, display]."""
    out: list[dict[str, str]] = []
    for item in opt.get_object() if opt is not None else []:
        item = item.get_object()
        if isinstance(item, list) and len(item) >= 2:
            out.append({"export": str(item[0].get_object()), "display": str(item[1].get_object())})
        else:
            out.append({"export": str(item), "display": str(item)})
    return out


def _actions(annot) -> tuple[bool, bool, bool]:
    """(calculated, format_action, javascript) over the widget and its ancestors: an /AA /C, or an /AA /F that is not
    one standard format call (KG7 as amended); any /AA /F; any JavaScript /AA or /A."""
    calculated = format_action = javascript = False
    for node in _chain(annot):
        aa = node.get("/AA")
        actions = []
        if aa is not None:
            aa = aa.get_object()
            calculated = calculated or "/C" in aa
            if "/F" in aa:
                format_action = True
                calculated = calculated or not STANDARD_FORMAT.match(action_script(aa["/F"]))
            actions.extend(aa[key] for key in aa)
        if node.get("/A") is not None:
            actions.append(node["/A"])
        for action in actions:
            action = action.get_object()
            if hasattr(action, "get") and action.get("/S") == "/JavaScript":
                javascript = True
    return calculated, format_action, javascript


def _kind(ft, ff: int) -> str:
    if ft == "/Btn":
        return "pushbutton" if ff & FF_PUSHBUTTON else "radio" if ff & FF_RADIO else "checkbox"
    return {"/Tx": "text", "/Ch": "choice", "/Sig": "signature"}.get(ft, "unknown")


def extract_fields(pdf_path: str | Path) -> list[FieldInfo]:
    """Every AcroForm widget in document order (see :class:`FieldInfo` for the keys)."""
    reader = PdfReader(str(pdf_path))
    acroform = reader.trailer["/Root"].get("/AcroForm")
    acroform = acroform.get_object() if acroform is not None else {}
    default_da = acroform.get("/DA")
    default_q = acroform.get("/Q")
    out: list[FieldInfo] = []
    for page_index, page in enumerate(reader.pages, 1):
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(obj)
            if not name:
                continue
            ft = _inherited(obj, "/FT")
            maxlen = _inherited(obj, "/MaxLen")
            ff = int(_inherited(obj, "/Ff") or 0)
            kind = _kind(ft, ff)
            on_states: list[str] = []
            if ft == "/Btn":
                ap = obj.get("/AP")
                normal = ap.get_object().get("/N") if ap else None
                normal = normal.get_object() if normal is not None else None
                # A pushbutton's /N is ONE appearance stream, not a dict of states: its keys (/BBox, /Matrix, ...)
                # are stream attributes, never on-states (Phase K JK14, 2026-10-24).
                if normal is not None and not isinstance(normal, StreamObject):
                    on_states = [str(k) for k in normal.keys() if k != "/Off"]
            da = _inherited(obj, "/DA")
            da = da if da is not None else default_da
            da_match = _DA_FONT_RE.search(str(da)) if da is not None else None
            quadding = _inherited(obj, "/Q")
            quadding = quadding if quadding is not None else default_q
            tooltip = _inherited(obj, "/TU")
            opt = _inherited(obj, "/Opt")
            calculated, format_action, javascript = _actions(obj)
            text, button = ft == "/Tx", ft == "/Btn"
            out.append(FieldInfo(
                name=name,
                type="checkbox" if ft == "/Btn" else "text",
                page=page_index,
                rect=[round(float(x)) for x in (obj.get("/Rect") or [])],
                maxlen=int(maxlen) if maxlen is not None else None,
                on_states=on_states,
                kind=kind,
                choice_type=("combo" if ff & FF_COMBO else "list") if kind == "choice" else None,
                options=_options(opt) if opt is not None and ft in ("/Ch", "/Btn") else [],
                tooltip=str(tooltip) if tooltip is not None else None,
                ff=ff,
                read_only=bool(ff & FF_READ_ONLY),
                required=bool(ff & FF_REQUIRED),
                multiline=text and bool(ff & FF_MULTILINE),
                password=text and bool(ff & FF_PASSWORD),
                comb=text and bool(ff & FF_COMB),
                do_not_scroll=text and bool(ff & FF_DO_NOT_SCROLL),
                pushbutton=button and bool(ff & FF_PUSHBUTTON),
                radio=button and bool(ff & FF_RADIO),
                no_toggle_to_off=button and bool(ff & FF_NO_TOGGLE_TO_OFF),
                da_font=da_match.group(1) if da_match else None,
                da_size=float(da_match.group(2)) if da_match else None,
                quadding=int(quadding) if quadding is not None else 0,
                calculated=calculated,
                format_action=format_action,
                javascript=javascript,
            ))
    return out


def detect_acroform_root(field_names: list[str]) -> str:
    """The longest dotted token-prefix shared by every field name (the XFA root).

    Federal forms nest under e.g. ``topmostSubform[0]`` so that is the root and
    pack fields are stored relative to it. Flat AcroForms (state DOR PDFs) have
    top-level opaque names with no shared dotted prefix -> root is ``""``.
    """
    dotted = [n for n in field_names if "." in n]
    if not dotted or len(dotted) != len(field_names):
        return ""
    split = [n.split(".") for n in dotted]
    common: list[str] = []
    for tokens in zip(*split):
        first = tokens[0]
        if all(t == first for t in tokens):
            common.append(first)
        else:
            break
    # Never consume the final (leaf) token as the root.
    if common and len(common) >= min(len(s) for s in split):
        common = common[:-1]
    return ".".join(common)


def _relative(name: str, root: str) -> str:
    if root and name.startswith(root + "."):
        return name[len(root) + 1:]
    return name


def build_skeleton(
    pdf_path: str | Path,
    *,
    form: str,
    jurisdiction: str,
    tax_year: int,
    source_url: str,
) -> dict[str, Any]:
    """Emit a skeleton FormPack dict (+ a `_todo` list) from a blank PDF.

    The returned dict validates against :class:`~taxfill_core.schemas.formpack.FormPack`
    (it imports lazily to avoid a hard schema dependency here). ``line`` keys are
    the relative field paths — rename them during vision mapping. ``_todo`` is
    stripped before validation and surfaced to the author separately.

    Pushbuttons (``kind == "pushbutton"``: print, clear, calculate and link buttons) hold no value, so they are
    not fillable: they get no ``fields`` entry, and one ``_todo`` entry lists them all ("pushbutton, not
    fillable") so the author can see they were skipped (Phase K JK14, 2026-10-24). Before JK14 they appeared as
    checkboxes with an on-state read from their appearance stream (/BBox), later /1 plus a no-on-state TODO each.
    """
    fields = extract_fields(pdf_path)
    root = detect_acroform_root([f["name"] for f in fields])
    pack_fields: list[dict[str, Any]] = []
    todo: list[str] = []
    seen_lines: set[str] = set()
    pushbuttons = [_relative(f["name"], root) for f in fields if f["kind"] == "pushbutton"]
    if pushbuttons:
        todo.append(f"pushbutton, not fillable — skipped {len(pushbuttons)}: {', '.join(pushbuttons)}")
    for f in fields:
        if f["kind"] == "pushbutton":
            continue
        rel = _relative(f["name"], root)
        if f["type"] == "checkbox":
            on_state = f["on_states"][0] if f["on_states"] else "/1"
            if not f["on_states"]:
                todo.append(f"checkbox {rel}: no on-state detected — confirm export value (defaulted to /1)")
            # Disambiguate radio options (same field, different on-states).
            line = f"{rel}::{on_state}" if f["on_states"] and len(f["on_states"]) else rel
        else:
            on_state = None
            line = rel
        # Guarantee unique line keys.
        base, n = line, 2
        while line in seen_lines:
            line = f"{base}#{n}"
            n += 1
        seen_lines.add(line)
        entry: dict[str, Any] = {"line": line, "field": rel, "type": f["type"]}
        if f["type"] == "checkbox":
            entry["on_state"] = on_state
        else:
            if f["maxlen"]:
                entry["maxlen"] = f["maxlen"]
        pack_fields.append(entry)

    return {
        "form": form,
        "jurisdiction": jurisdiction,
        "tax_year": tax_year,
        "source_url": source_url,
        "pdf_sha256": compute_sha256(pdf_path),
        "acroform_root": root,
        "fields": pack_fields,
        "relations": [],
        "cross_form": [],
        "identity_fields": [],
        "_todo": todo,
    }


def sentinel_sweep(pdf_path: str | Path, out_pdf: str | Path) -> Path:
    """Write a copy with every text field filled with its OWN field name and every
    checkbox checked, so a rendered page shows field->printed-line for vision mapping."""
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            node = obj if obj.get("/T") is not None else (obj.get("/Parent").get_object() if obj.get("/Parent") else obj)
            name = node.get("/T")
            ft = node.get("/FT") or obj.get("/FT")
            if name is None:
                continue
            if ft == "/Btn":
                ap = obj.get("/AP")
                on = None
                if ap and ap.get_object().get("/N"):
                    on = next((k for k in ap.get_object()["/N"].get_object().keys() if k != "/Off"), None)
                if on is not None:
                    obj[NameObject("/AS")] = NameObject(on)
                    node[NameObject("/V")] = NameObject(on)
            else:
                node[NameObject("/V")] = TextStringObject(str(name).strip())
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with out_pdf.open("wb") as fh:
        writer.write(fh)
    return out_pdf
