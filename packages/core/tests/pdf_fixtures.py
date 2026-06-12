"""Synthetic AcroForm PDF fixtures for filler/render/verify tests.

:func:`make_acroform_pdf` builds a multi-page fillable PDF with reportlab's
``canvas.acroForm`` — text fields (with ``/MaxLen`` and the *comb* field
flag), and checkboxes with custom export/on state names (real IRS forms use
states like ``/1``, ``/2`` instead of ``/Yes``).

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
) -> Path:
    """Generate a synthetic AcroForm PDF and return its path.

    Args:
        out_path: where to write the PDF (parent directories are created).
        fields_spec: one dict per field with keys:

            - ``name`` (required): the flat AcroForm field name; may contain
              dots/brackets (e.g. ``"topmostSubform[0].Page1[0].f1_7[0]"``) —
              pypdf reports it verbatim as the fully qualified name.
            - ``kind``: ``"text"`` (default) or ``"checkbox"``.
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
        if spec["kind"] not in ("text", "checkbox"):
            raise ValueError(
                f"field '{spec['name']}': kind must be 'text' or 'checkbox', "
                f"got {spec['kind']!r}"
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

    n_pages = max((s["page"] for s in specs), default=1)

    # Pass 1 — reportlab: draw pages, labels and form fields.
    buffer = io.BytesIO()
    canv = canvas.Canvas(buffer, pagesize=page_size)
    for page_no in range(1, n_pages + 1):
        canv.setFont("Helvetica", 9)
        canv.drawString(72, page_size[1] - 50, f"taxfill synthetic fixture — page {page_no}")
        next_y = page_size[1] - 92  # auto-stack cursor, top-down
        for spec in (s for s in specs if s["page"] == page_no):
            x = spec.get("x", 220)
            y = spec.get("y")
            if y is None:
                y = next_y
                next_y -= 30
            # Visible label so rendered pages are non-trivial and debuggable.
            canv.drawString(72, y + 4, spec["name"].rsplit(".", 1)[-1])
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
                )
            else:
                canv.acroForm.checkbox(
                    name=spec["name"],
                    x=x,
                    y=y,
                    size=spec.get("size", _CHECKBOX_DEFAULTS["size"]),
                    checked=False,
                    fieldFlags="",  # reportlab defaults to 'required'; keep fixtures neutral
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
