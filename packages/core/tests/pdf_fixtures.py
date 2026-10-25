"""Synthetic AcroForm PDF fixtures for filler/render/verify tests.

:func:`make_acroform_pdf` builds a multi-page fillable PDF with reportlab's
``canvas.acroForm`` — text fields (with ``/MaxLen`` and the *comb* field
flag), checkboxes with custom export/on state names (real IRS forms use
states like ``/1``, ``/2`` instead of ``/Yes``), and RADIO GROUPS: several
``kind: "radio"`` specs sharing one ``name`` become ONE ``/Btn`` field whose
``/T``-less kid widgets each carry a different on-state in their ``/AP /N``
dict — exactly how real IRS forms implement filing status and yes/no blocks.

Why this exists: real IRS PDFs are never vendored in the repo (dev plan
section 5), so every test that needs a fillable PDF generates a synthetic
one into ``tmp_path`` at test time. Never commit the generated binaries.

The helper is intentionally test-only (reportlab lives in the dev dependency
group) and is shared by later integration tests — keep its API stable.

Field naming note: IRS AcroForms use XFA-derived hierarchical names like
``topmostSubform[0].Page1[0].f1_7[0]``. reportlab writes whatever name you
give as a single flat ``/T`` entry; pypdf then reports that flat string
verbatim as the fully qualified field name. So passing the full dotted name
here produces a PDF whose qualified names match a real pack's
``acroform_root + "." + field`` exactly — which is all the filler needs.

Real IRS forms, however, are TRUE hierarchies: a parent field tree
(``topmostSubform[0]`` -> ``Page1[0]`` -> ``f1_7[0]``) whose terminal field
dict carries ``/T``/``/FT`` (and inheritable keys like ``/MaxLen``/``/DA``)
with the widget annotation as a ``/Kids`` entry that has NO ``/T`` of its
own. Pass ``hierarchical: True`` on a field spec to get that shape: a pypdf
post-pass splits the flat reportlab field into the parent chain, so the
filler's ``/Parent``-walking ``/V`` placement and verify's qualified-name /
inherited-key reconstruction run against the structure real packs hit in M2.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# PDF text-field flag "comb" (one character per cell): bit position 25,
# i.e. value 1 << 24 (PDF 32000-1 table 228). Requires /MaxLen.
COMB_FLAG = 1 << 24

# reportlab hardcodes "Yes" as the checkbox on-state; custom states are
# produced by renaming the appearance-state keys in a pypdf post-pass.
_REPORTLAB_ON = "/Yes"

_TEXT_DEFAULTS: dict[str, Any] = {"width": 144, "height": 18}
_CHECKBOX_DEFAULTS: dict[str, Any] = {"size": 14}


def _normalize_state(name: str) -> str:
    """Accept 'Yes', '1' or '/1' and return the PDF name form ('/1')."""
    return name if name.startswith("/") else f"/{name}"


def make_acroform_pdf(
    out_path: str | Path,
    fields_spec: list[dict[str, Any]],
    *,
    page_size: tuple[float, float] = letter,
    texts: list[tuple] | None = None,
    draw_labels: bool = True,
) -> Path:
    """Generate a synthetic AcroForm PDF and return its path.

    Args:
        out_path: where to write the PDF (parent directories are created).
        fields_spec: one dict per field with keys:

            - ``name`` (required): the flat AcroForm field name; may contain
              dots/brackets (e.g. ``"topmostSubform[0].Page1[0].f1_7[0]"``) —
              pypdf reports it verbatim as the fully qualified name.
            - ``kind``: ``"text"`` (default), ``"checkbox"`` or ``"radio"``.
              Radio: every spec with the SAME ``name`` adds one option
              widget (kid) to a single shared /Btn field; each spec needs
              its own ``on_value`` (e.g. ``"/1"``, ``"/2"``) and may set
              ``x``/``y``/``size``. The kids carry no ``/T`` of their own —
              the real IRS radio shape.
            - ``page``: 1-based page number (default 1). Pages are created up
              to the highest page referenced.
            - ``x``, ``y``: position in points from the bottom-left corner;
              omitted fields are auto-stacked top-down per page.
            - ``width``, ``height``: text-field rect in points (144 x 18).
            - ``maxlen``: text only — written as ``/MaxLen``.
            - ``comb``: text only — set the comb field flag (requires
              ``maxlen``; one character per comb cell).
            - ``value``: text only — pre-filled ``/V`` written by reportlab
              (default empty).
            - ``on_value``: checkbox only — the export/on state name, with or
              without the leading slash (default ``"Yes"``; e.g. ``"1"`` or
              ``"/1"`` to mimic IRS checkboxes).
            - ``size``: checkbox edge length in points (default 14).
            - ``hierarchical``: build a TRUE parent-field/kid-widget tree from
              the dotted name (the real IRS AcroForm shape) instead of a flat
              merged field — requires at least one dot in ``name``. The
              terminal field dict carries ``/T``/``/FT`` and the inheritable
              keys (``/MaxLen``, ``/DA``, ``/V``, ``/Ff``); the widget
              annotation keeps geometry/appearance only and has no ``/T``.
        page_size: reportlab page size tuple (default US letter, 612 x 792).
        texts: extra printed text, ``(page, x, y, text)`` or ``(page, x, y, text, font_size)`` — the
            captions and line numbers a test needs (Phase K JK15, 2026-10-24: the anchor tests).
        draw_labels: False drops the debugging label drawn left of every field, so a page prints only
            ``texts``. A spec may also carry ``tooltip`` (written as /TU).

    Returns:
        ``Path`` to the written PDF.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    specs: list[dict[str, Any]] = []
    for raw in fields_spec:
        spec = dict(raw)
        if "name" not in spec:
            raise ValueError(
                f"fields_spec entry {raw!r} is missing 'name' — every field needs "
                f"the AcroForm field name (e.g. 'topmostSubform[0].Page1[0].f1_7[0]')"
            )
        spec.setdefault("kind", "text")
        spec.setdefault("page", 1)
        if spec["kind"] not in ("text", "checkbox", "radio"):
            raise ValueError(
                f"field '{spec['name']}': kind must be 'text', 'checkbox' or 'radio', "
                f"got {spec['kind']!r}"
            )
        if spec["kind"] == "radio" and not spec.get("on_value"):
            raise ValueError(
                f"field '{spec['name']}': radio specs require 'on_value' (the option's "
                f"export state, e.g. '/1') — every spec sharing this name adds one "
                f"option widget to the group"
            )
        if spec["kind"] == "text" and spec.get("comb") and not spec.get("maxlen"):
            raise ValueError(
                f"field '{spec['name']}': comb=True requires 'maxlen' "
                f"(the number of comb cells) — the PDF spec mandates /MaxLen for comb fields"
            )
        if spec.get("hierarchical") and "." not in spec["name"]:
            raise ValueError(
                f"field '{spec['name']}': hierarchical=True needs a dotted name "
                f"(e.g. 'topmostSubform[0].Page1[0].f1_7[0]') to split into parent fields"
            )
        specs.append(spec)

    n_pages = max([s["page"] for s in specs] + [t[0] for t in texts or []] or [1])

    # Pass 1 — reportlab: draw pages, labels and form fields.
    buffer = io.BytesIO()
    canv = canvas.Canvas(buffer, pagesize=page_size)
    for page_no in range(1, n_pages + 1):
        canv.setFont("Helvetica", 9)
        if draw_labels:
            canv.drawString(72, page_size[1] - 50, f"taxfill synthetic fixture — page {page_no}")
        for t in texts or []:
            if t[0] == page_no:
                canv.setFont("Helvetica", t[4] if len(t) > 4 else 9)
                canv.drawString(t[1], t[2], t[3])
        canv.setFont("Helvetica", 9)
        next_y = page_size[1] - 92  # auto-stack cursor, top-down
        for spec in (s for s in specs if s["page"] == page_no):
            x = spec.get("x", 220)
            y = spec.get("y")
            if y is None:
                y = next_y
                next_y -= 30
            # Visible label so rendered pages are non-trivial and debuggable.
            label = spec["name"].rsplit(".", 1)[-1]
            if spec["kind"] == "radio":
                label = f"{label} {_normalize_state(str(spec['on_value']))}"
            if draw_labels:
                canv.drawString(72, y + 4, label)
            extra = {"tooltip": spec["tooltip"]} if spec.get("tooltip") else {}
            if spec["kind"] == "text":
                canv.acroForm.textfield(
                    name=spec["name"],
                    x=x,
                    y=y,
                    width=spec.get("width", _TEXT_DEFAULTS["width"]),
                    height=spec.get("height", _TEXT_DEFAULTS["height"]),
                    maxlen=spec.get("maxlen"),
                    fieldFlags=COMB_FLAG if spec.get("comb") else "",
                    value=spec.get("value", ""),
                    **extra,
                )
            elif spec["kind"] == "radio":
                # Each call with the same name adds one kid widget to the
                # shared /Btn field; reportlab uses `value` verbatim as the
                # kid's /AP /N on-state name.
                canv.acroForm.radio(
                    name=spec["name"],
                    value=_normalize_state(str(spec["on_value"])).lstrip("/"),
                    selected=False,
                    x=x,
                    y=y,
                    size=spec.get("size", _CHECKBOX_DEFAULTS["size"]),
                    fieldFlags="noToggleToOff radio",  # drop reportlab's default 'required'
                    **extra,
                )
            else:
                canv.acroForm.checkbox(
                    name=spec["name"],
                    x=x,
                    y=y,
                    size=spec.get("size", _CHECKBOX_DEFAULTS["size"]),
                    checked=False,
                    fieldFlags="",  # reportlab defaults to 'required'; keep fixtures neutral
                    **extra,
                )
        canv.showPage()
    canv.save()

    # Pass 2 — pypdf: rename checkbox appearance states to the custom
    # export values (reportlab offers no API for this).
    renames = {
        s["name"]: _normalize_state(str(s["on_value"]))
        for s in specs
        if s["kind"] == "checkbox" and _normalize_state(str(s.get("on_value", "Yes"))) != _REPORTLAB_ON
    }
    buffer.seek(0)
    writer = PdfWriter(clone_from=buffer)
    if renames:
        for page in writer.pages:
            for ref in page.get("/Annots", []):
                annot = ref.get_object()
                on_state = renames.get(annot.get("/T"))
                if on_state is None:
                    continue
                ap = annot.get("/AP")
                if ap is None:
                    continue
                ap = ap.get_object()
                for ap_key in ("/N", "/D"):
                    if ap_key not in ap:
                        continue
                    states = ap[ap_key].get_object()
                    if _REPORTLAB_ON in states:
                        states[NameObject(on_state)] = states.raw_get(_REPORTLAB_ON)
                        del states[NameObject(_REPORTLAB_ON)]

    # Pass 3 — pypdf: split flat fields into true parent/kid hierarchies
    # (the real IRS AcroForm shape; see the module docstring).
    hierarchical_names = {s["name"] for s in specs if s.get("hierarchical")}
    if hierarchical_names:
        _split_into_hierarchy(writer, hierarchical_names)

    with out_path.open("wb") as fh:
        writer.write(fh)
    return out_path


# Field-dict keys moved from the flat merged field onto the terminal field
# dict when splitting: /FT and /Ff define the field; /V, /MaxLen and /DA are
# the inheritable keys real IRS forms keep on field (not widget) dicts.
_FIELD_LEVEL_KEYS = ("/FT", "/Ff", "/V", "/MaxLen", "/DA")


def _split_into_hierarchy(writer: PdfWriter, names: set[str]) -> None:
    """Rebuild flat reportlab fields named in ``names`` as parent/kid trees.

    For a flat field ``A.B.C``: creates field dicts ``A`` -> ``B`` -> ``C``
    linked by ``/Kids``/``/Parent``; the terminal dict ``C`` carries ``/T``
    plus the field-level keys, and the original widget annotation becomes its
    ``/T``-less kid. The AcroForm ``/Fields`` entry is swapped for the root.

    Radio groups already ARE a parent field with ``/T``-less kid widgets, but
    reportlab gives that parent a flat dotted ``/T``; for those, the parent
    keeps its ``/Kids``/``/FT``/``/Ff`` and only the dotted name is split
    into an ancestor chain (second loop below).
    """
    acroform = writer._root_object["/AcroForm"].get_object()
    fields_arr = acroform["/Fields"]
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            flat = annot.get("/T")
            if flat is None or str(flat) not in names:
                continue
            parts = str(flat).split(".")
            node_refs = []
            for part in parts:
                node = DictionaryObject()
                node[NameObject("/T")] = TextStringObject(part)
                node_refs.append(writer._add_object(node))
            for parent_ref, child_ref in zip(node_refs, node_refs[1:]):
                parent_ref.get_object()[NameObject("/Kids")] = ArrayObject([child_ref])
                child_ref.get_object()[NameObject("/Parent")] = parent_ref
            terminal_ref = node_refs[-1]
            terminal = terminal_ref.get_object()
            for key in _FIELD_LEVEL_KEYS:
                if key in annot:
                    terminal[NameObject(key)] = annot.raw_get(key)
                    del annot[key]
            del annot["/T"]
            terminal[NameObject("/Kids")] = ArrayObject([ref])
            annot[NameObject("/Parent")] = terminal_ref
            new_fields = ArrayObject([f for f in fields_arr if f.get_object() is not annot])
            new_fields.append(node_refs[0])
            acroform[NameObject("/Fields")] = new_fields
            fields_arr = new_fields

    # Radio parents: the flat-named field is NOT a page annotation (only its
    # /T-less kids are), so it is found via the AcroForm /Fields array. The
    # field keeps its /Kids widgets; the dotted name is split into ancestors.
    for field_ref in list(fields_arr):
        field = field_ref.get_object()
        flat = field.get("/T")
        if flat is None or str(flat) not in names or "/Kids" not in field:
            continue
        parts = str(flat).split(".")
        if len(parts) < 2:
            continue
        ancestor_refs = []
        for part in parts[:-1]:
            node = DictionaryObject()
            node[NameObject("/T")] = TextStringObject(part)
            ancestor_refs.append(writer._add_object(node))
        for parent_ref, child_ref in zip(ancestor_refs, ancestor_refs[1:]):
            parent_ref.get_object()[NameObject("/Kids")] = ArrayObject([child_ref])
            child_ref.get_object()[NameObject("/Parent")] = parent_ref
        field[NameObject("/T")] = TextStringObject(parts[-1])
        ancestor_refs[-1].get_object()[NameObject("/Kids")] = ArrayObject([field_ref])
        field[NameObject("/Parent")] = ancestor_refs[-1]
        new_fields = ArrayObject([f for f in fields_arr if f.get_object() is not field])
        new_fields.append(ancestor_refs[0])
        acroform[NameObject("/Fields")] = new_fields
        fields_arr = new_fields


# ── Phase K JK16 (2026-10-25): synthetic demo returns for the pack-less fill ───────────────────────────────────────

DEMO_BOX_X = 470.0


def demo_rows(rows, *, page: int = 1, top: float = 640.0, pitch: float = 24.0):
    """IRS-style printed rows: a gutter number, a caption, dot leaders, the number again beside an amount box.

    ``rows``: ``(number, caption, field name or None[, field spec overrides])``. Returns ``(texts, fields)`` for
    :func:`make_acroform_pdf`.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    texts, fields = [], []
    for i, row in enumerate(rows):
        num, caption, name = row[:3]
        extra = row[3] if len(row) > 3 else {}
        y = top - i * pitch
        texts.append((page, 40, y, num))
        texts.append((page, 60, y, caption))
        start = 60 + stringWidth(caption, "Helvetica", 9) + 3
        end = DEMO_BOX_X - 22
        texts.append((page, start, y, "." * max(int((end - start) / stringWidth(".", "Helvetica", 9)), 3)))
        texts.append((page, DEMO_BOX_X - 18, y, num))
        if name:
            fields.append({"name": name, "page": page, "x": DEMO_BOX_X, "y": y - 4, "width": 90, "height": 14,
                           **extra})
    return texts, fields


def make_demo_return(
    out_path: str | Path,
    *,
    form: str = "DEMO-1",
    year: str = "2025",
    pages: int = 1,
    texts: list[tuple] | None = None,
    fields: list[dict[str, Any]] | None = None,
    edits: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """A synthetic demo return: page 1 prints "Form <form>" and the tax year at title size (the fetch's rule 7), each
    later page a small running header; ``texts`` and ``fields`` as for :func:`make_acroform_pdf`, then
    :func:`edit_widgets` applies ``edits``. Demo values only: no person, no real figures."""
    printed = [(1, 72, 750, f"Form {form}  Demo Individual Income Tax Return", 12), (1, 430, 718, year, 28),
               *[(p, 72, 760, f"Form {form} ({year})  Page {p}", 8) for p in range(2, pages + 1)], *(texts or [])]
    path = make_acroform_pdf(out_path, fields or [], texts=printed, draw_labels=False)
    if edits:
        edit_widgets(path, edits)
    return path


def _js(script: str) -> DictionaryObject:
    from pypdf.generic import TextStringObject as _T

    return DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): _T(script)})


def edit_widgets(path: str | Path, edits: dict[str, dict[str, Any]]) -> Path:
    """Post-pass over a fixture's flat fields, by field name. Each edit may carry:

    - ``aa``: ``{"C": script, "F": script, ...}`` — an /AA dictionary of JavaScript actions (a calculated total is
      ``{"C": "AFSimple_Calculate(...)"}``; a format-only box ``{"F": "AFNumber_Format(0, 0, 0, 0, '', true);"}``);
    - ``ff``: bits OR-ed into the field's /Ff (1 ReadOnly, 1 << 16 pushbutton with ``ft: "/Btn"``);
    - ``f``: the widget's annotation flags /F (2 Hidden, 4 Print, 32 NoView);
    - ``ft``: replace /FT ("/Sig" for a signature widget, "/Btn" with the pushbutton bit for a pushbutton);
    - ``options``: a combo-box choice field with these /Opt export values;
    - ``rect``: replace the widget's /Rect (a page-covering viewer guard);
    - ``merge``: True on a name given to several flat fields — one field dict with the widgets as /T-less kids.
    """
    from pypdf.generic import NumberObject, RectangleObject
    from pypdf.generic import TextStringObject as _T

    path = Path(path)
    writer = PdfWriter(clone_from=str(path))
    acroform = writer._root_object["/AcroForm"].get_object()
    merged: dict[str, Any] = {}
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            name = str(annot.get("/T")) if annot.get("/T") is not None else None
            edit = edits.get(name or "")
            if not edit:
                continue
            if "aa" in edit:
                annot[NameObject("/AA")] = DictionaryObject(
                    {NameObject(f"/{k}"): _js(v) for k, v in edit["aa"].items()})
            if "ff" in edit:
                annot[NameObject("/Ff")] = NumberObject(int(annot.get("/Ff", 0)) | edit["ff"])
            if "f" in edit:
                annot[NameObject("/F")] = NumberObject(edit["f"])
            if "ft" in edit:
                annot[NameObject("/FT")] = NameObject(edit["ft"])
            if "options" in edit:
                annot[NameObject("/FT")] = NameObject("/Ch")
                annot[NameObject("/Ff")] = NumberObject(1 << 17)  # combo
                annot[NameObject("/Opt")] = ArrayObject([_T(o) for o in edit["options"]])
                annot.pop(NameObject("/MaxLen"), None)
            if "rect" in edit:
                annot[NameObject("/Rect")] = RectangleObject(edit["rect"])
            if edit.get("merge"):
                parent_ref = merged.get(name)
                if parent_ref is None:
                    parent = DictionaryObject({NameObject("/T"): _T(name), NameObject("/Kids"): ArrayObject()})
                    for key in ("/FT", "/Ff", "/V", "/DA", "/MaxLen", "/AA"):
                        if key in annot:
                            parent[NameObject(key)] = annot.raw_get(key)
                    parent_ref = merged[name] = writer._add_object(parent)
                    acroform[NameObject("/Fields")] = ArrayObject(
                        [*(f for f in acroform["/Fields"] if f.get_object() is not annot), parent_ref])
                else:
                    acroform[NameObject("/Fields")] = ArrayObject(
                        [f for f in acroform["/Fields"] if f.get_object() is not annot])
                for key in ("/T", "/FT", "/Ff", "/V", "/DA", "/MaxLen", "/AA"):
                    if key in annot:
                        del annot[key]
                annot[NameObject("/Parent")] = parent_ref
                parent_ref.get_object()["/Kids"].append(ref)
    with path.open("wb") as fh:
        writer.write(fh)
    return path
