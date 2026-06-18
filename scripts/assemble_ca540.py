#!/usr/bin/env python
"""Assemble the CA Form 540 (2023) pack.yaml from the verified field->line map.

Takes the vision-mapping output (/tmp/ca540_map.json) + the introspection dump
(.cache/introspect/2023-540/fields.json, for maxlen/on_states), resolves the
duplicate line ids, types each field, groups the filing-status checkboxes, and
emits a schema-valid pack.yaml with high-confidence relations (read verbatim
from the printed line labels) + the federal AGI cross_form. The field map is the
load-bearing artifact; it is then adversarially audited (sentinel fill+render).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MAP = json.load(open("/tmp/ca540_map.json"))
INTRO = json.load(open(REPO / ".cache/introspect/2023-540/fields.json"))
META = {f["name"]: f for f in INTRO["fields"]}
SHA = "58b5a25d40476a3d0c3f5b51556cec906dd8aea2f448f0ce3e3d9f4e92170e33"

# Resolve duplicate line ids (a pack requires unique line ids).
RENAME = {
    "2002": "identifying_number.page6",   # SSN repeated on the signature page
    "1045": "7.count", "1047": "8.count", "1049": "9.count", "2015": "10.count",  # exemption count boxes
    "5004 CB": "113.ftb_5805", "5005 CB": "113.ftb_5805f",  # the two line-113 checkboxes (money line 113 = field 5006)
}
FILING_STATUS = {"filing_status.single", "filing_status.mfj", "filing_status.mfs", "filing_status.hoh", "filing_status.qss"}

# High-confidence relations transcribed verbatim from the printed line labels.
RELATIONS = [
    "11 == 7 + 8 + 9 + 10",                 # "Exemption amount: Add line 7 through line 10"
    "15 == 13 - 14",                         # "Subtract line 14 from line 13" (may be negative)
    "17 == 15 + 16",                         # "California AGI. Combine line 15 and line 16"
    "19 == max(0, 17 - 18)",                 # "Subtract line 18 from line 17 ... If less than zero, enter -0-"
    "33 == max(0, 31 - 32)",                 # "Subtract line 32 from line 31 ... If less than zero, enter -0-"
    "35 == 33 + 34",                         # "Add line 33 and line 34"
    "48 == max(0, 35 - 47)",                 # "Subtract line 47 from line 35 ... If less than zero, enter -0-"
    "64 == 48 + 61 + 62 + 63",               # "Add line 48, line 61, line 62, and line 63. Total tax"
    "78 == 71 + 72 + 73 + 74 + 75 + 76 + 77",  # "Add line 71 through line 77. Total payments"
    "93 == max(0, 78 - 91)",                 # "If line 78 is more than line 91, subtract line 91 from line 78"
    "94 == max(0, 91 - 78)",                 # "If line 91 is more than line 78, subtract line 78 from line 91"
    "99 == 97 - 98",                         # "Overpaid tax available this year. Subtract line 98 from line 97"
    "100 == max(0, 64 - 95)",                # "Tax due. If line 95 is less than line 64, subtract line 95 from line 64"
    "110 == 400 + 401 + 403 + 405 + 406 + 407 + 408 + 410 + 413 + 422 + 423 + 424 + 425 + 438 + 439 + 440 + 444 + 445",  # "Add amounts in code 400 through 445"
]
CROSS_FORM = [
    "13 == f1040.11",   # "Enter federal adjusted gross income from federal Form 1040 or 1040-SR, line 11"
]


def build():
    fields = []
    for fld, m in MAP.items():
        line = RENAME.get(fld, m["line"])
        ftype = "text" if (fld in RENAME and ".count" in RENAME[fld]) else m["type"]  # count boxes are text
        entry = {"line": line, "field": fld, "type": ftype}
        meta = META.get(fld, {})
        if ftype == "checkbox":
            entry["on_state"] = m["on_state"] or (meta.get("on_states") or ["/Yes"])[0]
            if line in FILING_STATUS:
                entry["group"] = "filing_status"
        elif ftype == "text" and meta.get("maxlen"):
            entry["maxlen"] = meta["maxlen"]
        fields.append(entry)
    # mark one filing_status member required (group audit, pitfall P-003)
    for e in fields:
        if e.get("group") == "filing_status" and e["line"] == "filing_status.single":
            e["required"] = True
    fields.sort(key=lambda e: (META.get(e["field"], {}).get("page", 9), -META.get(e["field"], {}).get("rect", [0, 0])[1] if META.get(e["field"], {}).get("rect") else 0))

    pack = {
        "form": "540",
        "jurisdiction": "states/ca",
        "tax_year": 2023,
        "source_url": "https://www.ftb.ca.gov/forms/2023/2023-540.pdf",
        "pdf_sha256": SHA,
        "acroform_root": "",  # CA FTB fields are top-level (no XFA subform root)
        "fields": fields,
        "relations": RELATIONS,
        "cross_form": CROSS_FORM,
        "identity_fields": ["name.first", "name.last", "identifying_number"],
        "signature": {"page": 6},
        "mailing": None,  # CA where-to-file lives in knowledge/states/ca (like federal f1040)
    }
    return pack


if __name__ == "__main__":
    pack = build()
    out = REPO / "formpacks" / "states" / "ca" / "2023" / "form540" / "pack.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.dump(pack, sort_keys=False, allow_unicode=True, width=120))
    print(f"wrote {out} — {len(pack['fields'])} fields, {len(pack['relations'])} relations")
