#!/usr/bin/env python
"""Assemble the CA Form 540NR (2023) pack.yaml from the verified field->line map.

Same pipeline as assemble_ca540.py (vision map -> dedup -> type -> relations from
the printed labels), for the Nonresident/Part-Year form. The field map is then
adversarially vision-audited before the pack ships.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MAP = json.load(open("/tmp/ca540nr_map.json"))
INTRO = json.load(open(REPO / ".cache/introspect/2023-540nr/fields.json"))
META = {f["name"]: f for f in INTRO["fields"]}
SHA = "6b52d0fb454d15331fe51688930c805a31469947aa4e5f78a926c899f150574c"

RENAME = {
    "2002": "identifying_number.page6",          # SSN repeated on the signature page
    "3023 CB": "91.full_year_health_coverage",   # line-91 health-coverage checkbox (money line 91 = field 3024)
}
# Page-6 corrections from the adversarial vision audit (the render is authoritative
# over the vision-mapper's label guesses in the dense preparer block):
#  - the left preparer column rendered one row low (6004 under "Firm's name",
#    6006 under "Firm's address"); the signature line itself is hand-signed (no field).
#  - 6008 radio: /0 widget is "Yes" (left), /1 is "No" — so ".no" must use /1.
#  - 2001 is the repeated name header, not a signature field (match 540's name.full).
FIXES = {
    "2001": {"line": "name.full"},
    "6004": {"line": "paid_preparer.firm_name"},
    "6006": {"line": "paid_preparer.firm_address"},
    "6008 RB": {"on_state": "/1"},
}
FILING_STATUS = {"filing_status.single", "filing_status.mfj", "filing_status.mfs", "filing_status.hoh", "filing_status.qss"}

# High-confidence relations transcribed verbatim from the printed line labels.
# The prorated-tax lines (36 ratio, 37 = 35 x 36, 39 = 11 x 38) are intentionally
# OMITTED (ratio/multiply with a CA-AGI factor — not a simple sum/difference).
RELATIONS = [
    "11 == 7 + 8 + 9 + 10",                        # "Add line 7 through line 10"
    "15 == 13 - 14",                                # "Subtract line 14 from line 13" (may be negative)
    "17 == 15 + 16",                                # "Combine line 15 and line 16"
    "19 == max(0, 17 - 18)",                        # "Subtract line 18 from line 17 ... If less than zero, enter -0-"
    "40 == max(0, 37 - 39)",                        # "CA Regular Tax Before Credits. Subtract line 39 from line 37"
    "42 == 40 + 41",                                # "Add line 40 and line 41"
    "63 == max(0, 42 - 62)",                        # "Subtract line 62 from line 42 ... If less than zero, enter -0-"
    "74 == 63 + 71 + 72 + 73",                      # "Add line 63, line 71, line 72, and line 73. Total tax"
    "88 == 81 + 82 + 83 + 84 + 85 + 86 + 87",       # "Add line 81 through line 87. Total payments"
    "92 == max(0, 88 - 91)",                        # "If line 88 is more than line 91, subtract line 91 from line 88"
    "93 == max(0, 91 - 88)",                        # "If line 91 is more than line 88, subtract line 88 from line 91"
    "101 == max(0, 92 - 74)",                       # "Overpaid tax. If line 92 is more than line 74 ..."
    "103 == 101 - 102",                             # "Subtract line 102 from line 101"
    "104 == max(0, 74 - 92)",                       # "Tax due. If line 92 is less than line 74 ..."
    "120 == 400 + 401 + 403 + 405 + 406 + 407 + 408 + 410 + 413 + 422 + 423 + 424 + 425 + 438 + 439 + 440 + 444 + 445",  # "Add code 400 through 446"
    "121 == 93 + 104 + 120",                        # "AMOUNT YOU OWE. Add line 93, line 104, and line 120"
    "125 == 103 - 120",                             # "REFUND. Subtract line 120 from line 103"
]
# The federal AGI source is 1040/1040-SR OR 1040-NR (NRA filers) — both refs;
# verify_filing skips whichever form is not part of the filing.
CROSS_FORM = ["13 == f1040.11", "13 == f1040nr.11"]


def build():
    fields = []
    for fld, m in MAP.items():
        line = RENAME.get(fld, m["line"])
        entry = {"line": line, "field": fld, "type": m["type"]}
        meta = META.get(fld, {})
        if m["type"] == "checkbox":
            entry["on_state"] = m["on_state"] or (meta.get("on_states") or ["/Yes"])[0]
            if line in FILING_STATUS:
                entry["group"] = "filing_status"
        elif m["type"] == "text":
            if meta.get("maxlen"):
                entry["maxlen"] = meta["maxlen"]
            else:
                # No PDF-declared MaxLen: bound to the box's visible capacity
                # (clipping heuristic is len x 5pt) so a long value can't clip
                # invisibly (pitfall P-001). Only for genuinely narrow boxes.
                rect = meta.get("rect")
                if rect:
                    cap = int((rect[2] - rect[0]) / 5)
                    if 1 <= cap <= 20:
                        entry["maxlen"] = cap
        fields.append(entry)
    # Apply the audit-confirmed page-6 corrections.
    for e in fields:
        fix = FIXES.get(e["field"])
        if fix:
            e.update(fix)
    for e in fields:
        if e.get("group") == "filing_status" and e["line"] == "filing_status.single":
            e["required"] = True
    fields.sort(key=lambda e: (META.get(e["field"], {}).get("page", 9), -(META.get(e["field"], {}).get("rect") or [0, 0])[1]))

    return {
        "form": "540NR",
        "jurisdiction": "states/ca",
        "tax_year": 2023,
        "source_url": "https://www.ftb.ca.gov/forms/2023/2023-540nr.pdf",
        "pdf_sha256": SHA,
        "acroform_root": "",
        "fields": fields,
        "relations": RELATIONS,
        "cross_form": CROSS_FORM,
        "identity_fields": ["name.first", "name.last", "identifying_number"],
        "signature": {"page": 6},
        "mailing": None,
    }


if __name__ == "__main__":
    pack = build()
    out = REPO / "formpacks" / "states" / "ca" / "2023" / "form540nr" / "pack.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# California Form 540NR (2023) — Nonresident or Part-Year Resident Income Tax Return.\n"
        "#\n"
        "# Authored via scripts/introspect_pdf.py + a 6-page vision mapping + scripts/assemble_ca540nr.py,\n"
        "# then ADVERSARIALLY VISION-AUDITED. Relations transcribed verbatim from the printed line labels;\n"
        "# the prorated-tax lines (36/37/39, a CA-AGI ratio) are intentionally relation-free. cross_form\n"
        "# line 13 = federal AGI (Form 1040 line 11 OR 1040-NR line 11 for nonresident-alien filers).\n"
        "# Flat AcroForm: acroform_root empty, top-level field names; blank fetched from FTB + checksum-verified.\n"
    )
    out.write_text(header + yaml.dump(pack, sort_keys=False, allow_unicode=True, width=120))
    print(f"wrote {out} — {len(pack['fields'])} fields, {len(pack['relations'])} relations")
