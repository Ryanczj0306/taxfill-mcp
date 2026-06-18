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

from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from taxfill_core.fetch import compute_sha256

__all__ = ["FieldInfo", "extract_fields", "detect_acroform_root", "build_skeleton", "sentinel_sweep"]


class FieldInfo(dict):
    """A single widget: name, type, page, rect, maxlen, on_states (a plain dict)."""


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


def _inherited(annot, key: str):
    """Walk the /Parent chain for an inheritable attribute (/FT, /MaxLen)."""
    node = annot
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if node.get(key) is not None:
            return node.get(key)
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return None


def extract_fields(pdf_path: str | Path) -> list[FieldInfo]:
    """Every AcroForm widget in document order (name, type, page, rect, maxlen, on_states)."""
    reader = PdfReader(str(pdf_path))
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
            on_states: list[str] = []
            if ft == "/Btn":
                ap = obj.get("/AP")
                if ap and ap.get_object().get("/N"):
                    on_states = [str(k) for k in ap.get_object()["/N"].get_object().keys() if k != "/Off"]
            out.append(FieldInfo(
                name=name,
                type="checkbox" if ft == "/Btn" else "text",
                page=page_index,
                rect=[round(float(x)) for x in (obj.get("/Rect") or [])],
                maxlen=int(maxlen) if maxlen is not None else None,
                on_states=on_states,
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
    """
    fields = extract_fields(pdf_path)
    root = detect_acroform_root([f["name"] for f in fields])
    pack_fields: list[dict[str, Any]] = []
    todo: list[str] = []
    seen_lines: set[str] = set()
    for f in fields:
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
