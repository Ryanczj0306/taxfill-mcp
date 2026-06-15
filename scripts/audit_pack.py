#!/usr/bin/env python
"""M2 field-map audit harness.

Given a pack path, fill the *real* cached blank PDF with traceable sentinel
values (one distinct value per mapped line), render every page to PNG, and
emit a JSON mapping {line -> value, field, type}. A reviewer then opens the
PNGs and confirms each sentinel lands at the correct printed line — the one
correctness property the offline assertion-diff test cannot prove.

Usage:  python scripts/audit_pack.py formpacks/federal/2023/sched_a/pack.yaml [out_dir]
Offline: relies on the warm blank cache (.cache/blanks); no network needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core" / "src"))
sys.path.insert(0, str(REPO / "packages" / "core" / "tests"))

from taxfill_core.fetch import fetch_blank  # noqa: E402
from taxfill_core.filler import fill_form  # noqa: E402
from taxfill_core.render import render_pdf  # noqa: E402
from taxfill_core.schemas.formpack import load_pack  # noqa: E402
from taxfill_core.verify import verify_form  # noqa: E402
from test_formpacks_federal import synthetic_values  # noqa: E402


def main() -> int:
    pack_path = Path(sys.argv[1])
    if not pack_path.is_absolute():
        pack_path = REPO / pack_path
    pack = load_pack(pack_path)
    tag = f"{pack_path.parent.parent.name}_{pack_path.parent.name}"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / ".cache" / "audit" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)  # warm cache, offline OK
    values = synthetic_values(pack)
    filled = out_dir / f"{tag}_filled.pdf"
    result = fill_form(pack, values, blank, filled)

    pages = render_pdf(filled, out_dir, dpi=170)

    # Build the human-traceable line -> value map (what each printed line should show).
    field_by_line = {pf.line: pf for pf in pack.fields}
    mapping = []
    for line, val in values.items():
        pf = field_by_line[line]
        shown = "[X checked]" if val is True else val
        mapping.append({"line": line, "shows": shown, "field": pf.field, "type": pf.type})
    mapping.sort(key=lambda m: m["line"])

    # Verify report (assertion/clipping/checkbox) for cross-reference.
    report = verify_form(pack, filled, expected=values)
    fails = []
    for section in (report.assertions, report.clipping, report.checkboxes, report.relations):
        for chk in section:
            if chk.status == "FAIL":
                fails.append(chk.detail)

    summary = {
        "pack": str(pack_path.relative_to(REPO)),
        "form": pack.form,
        "tax_year": pack.tax_year,
        "mapped_lines": len(values),
        "written_fields": len(result.written),
        "pages_rendered": [{"page": p.page, "png": str(p.path), "px": [p.width_px, p.height_px]} for p in pages],
        "verify_fails": fails,
        "mapping": mapping,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
