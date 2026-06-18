#!/usr/bin/env python
"""Introspect a blank AcroForm PDF for state-pack authoring (M5/M7).

Dumps every form field (name, type, page, rect, maxlen, checkbox on-states) as
JSON AND renders a "sentinel sweep": every text field filled with its OWN field
name, every checkbox checked. On the rendered pages each box shows its field
name, so a reviewer (or a vision agent) reads off field -> printed line directly.
The dump's per-field page+rect localizes each field for cross-checking.

Usage:  python scripts/introspect_pdf.py /path/to/blank.pdf [out_dir]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
from taxfill_core.render import render_pdf  # noqa: E402


def _fields(reader: PdfReader) -> list[dict]:
    out = []
    for pi, page in enumerate(reader.pages, 1):
        for annot in page.get("/Annots") or []:
            o = annot.get_object()
            if o.get("/Subtype") != "/Widget":
                continue
            node = o
            name = o.get("/T")
            ft = o.get("/FT")
            if name is None and o.get("/Parent") is not None:
                node = o.get("/Parent").get_object()
                name, ft = node.get("/T"), node.get("/FT")
            on_states = []
            if ft == "/Btn":
                ap = o.get("/AP")
                if ap and ap.get_object().get("/N"):
                    on_states = [str(k) for k in ap.get_object()["/N"].get_object().keys() if k != "/Off"]
            out.append({
                "name": str(name) if name is not None else None,
                "type": "checkbox" if ft == "/Btn" else "text",
                "page": pi,
                "rect": [round(float(x)) for x in (o.get("/Rect") or [])],
                "maxlen": int(node.get("/MaxLen")) if node.get("/MaxLen") is not None else None,
                "on_states": on_states,
            })
    return out


def _sentinel_fill(reader: PdfReader, out_pdf: Path) -> None:
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        for annot in page.get("/Annots") or []:
            o = annot.get_object()
            if o.get("/Subtype") != "/Widget":
                continue
            node = o if o.get("/T") is not None else (o.get("/Parent").get_object() if o.get("/Parent") else o)
            name = node.get("/T")
            ft = node.get("/FT") or o.get("/FT")
            if name is None:
                continue
            if ft == "/Btn":
                ap = o.get("/AP")
                on = None
                if ap and ap.get_object().get("/N"):
                    on = next((k for k in ap.get_object()["/N"].get_object().keys() if k != "/Off"), None)
                if on is not None:
                    o[NameObject("/AS")] = NameObject(on)
                    node[NameObject("/V")] = NameObject(on)
            else:
                node[NameObject("/V")] = TextStringObject(str(name).strip())
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass
    with out_pdf.open("wb") as fh:
        writer.write(fh)


def main() -> int:
    pdf = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / ".cache" / "introspect" / pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf))
    fields = _fields(reader)
    filled = out_dir / f"{pdf.stem}_sweep.pdf"
    _sentinel_fill(reader, filled)
    pages = render_pdf(filled, out_dir, dpi=170)
    summary = {
        "pdf": str(pdf),
        "n_pages": len(reader.pages),
        "n_fields": len(fields),
        "n_text": sum(1 for f in fields if f["type"] == "text"),
        "n_checkbox": sum(1 for f in fields if f["type"] == "checkbox"),
        "pages": [{"page": p.page, "png": str(p.path)} for p in pages],
        "fields": fields,
    }
    (out_dir / "fields.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("pdf", "n_pages", "n_fields", "n_text", "n_checkbox", "pages")}, indent=1))
    print(f"\nfields.json + sweep render in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
