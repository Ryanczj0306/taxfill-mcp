"""P-031: an AL Form 40 page-1 line key equals the line number printed beside its widget.

The 2023 pack once keyed lines 5a/5b, 20a/20b and 21-34 from a superseded face, one number high — key "22" on
printed line 21, "34_total_donations" on printed 33 — and its relations were consistent with the shifted keys, so
verify never noticed. The network half (the number Alabama prints in the gutter left of each page-1 widget, on
every shipped year's own blank) moved into the label-adjacency gate, test_label_adjacency.py (Phase K JK10,
2026-10-24); this file keeps the offline pinned map.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKS = sorted((REPO / "formpacks" / "states" / "al").glob("*/al40/pack.yaml"))


def test_p031_every_al40_year_is_checked():
    assert {p.parent.parent.name for p in PACKS} >= {"2023"}


# The same map pinned OFFLINE, so a revert fails the PR suite and not only the weekly network layer.
PAGE1_MAP = {
    "5a": "ALTXWH", "5b": "WAGESINC", "6": "INTDIVINC", "7": "TOTOTHERINC", "8": "TOTALINC", "9": "TOTADJINC",
    "10": "ADJGRSINC", "11": "ITMSTDDED", "12": "FEDTXLIABDED", "13": "PERSEXEMP", "14": "DEPEXMPTION",
    "15": "TOTDED", "16": "TAXINC", "17": "TAXDUE", "18": "NETTAXDUE", "19": "ADDTAX", "20a": "CONTALDEMPTY",
    "20b": "TOTALREPPTY", "21": "TOTTAXLIB", "22": "TOTALWH", "23": "ESTMEXTSIONPMT", "31": "ESTPEN",
    "32": "OVERPAID", "33": "PG1LINE33", "34": "CHECKOFF1", "35": "REFTOYOU", "26": "SCHCPPAYMENT", "27": "TOTPMT",
    "30": "AMTOWE",
    "24": "AMENDEDPAYMENTS",
    "25": "REFUNDABLERC",
    "28": "AMENDEDRETURNONLY",
    "29": "ADJUSTEDTOTALPAYMENTS",
}


@pytest.mark.parametrize("path", PACKS, ids=lambda p: p.parent.parent.name)
def test_p031_page1_key_to_widget_map_is_pinned(path: Path):
    from taxfill_core.schemas.formpack import load_pack

    field_of = {f.line: f.field for f in load_pack(path).fields}
    assert len(PAGE1_MAP) == 33
    assert {k: field_of.get(k) for k in PAGE1_MAP} == PAGE1_MAP
    for stale in ("5_al_tax_withheld", "20_amount", "21_amount", "34_total_donations", "34_first_checkoff"):
        assert stale not in field_of, f"{stale!r} is a pre-P-031 key"
