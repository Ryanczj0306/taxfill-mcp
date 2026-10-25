"""The pack-path golden (Phase K JK16b, 2026-10-25): the KG8 gate for the four tools the no-pack fallback rides.

scripts/golden_pack_path.py snapshots what get_form_map returns over every shipped pack, today's pack-path refusal
texts, and fetch_blank -> fill_form -> verify_form -> verify_filing on synthetic demo packs through the server's real
``_load_any_pack`` and ``fetch_pack_blank`` (a temporary TAXFILL_DATA_DIR, the demo blanks seeded into a temporary
TAXFILL_BLANKS_CACHE; nothing stubbed). This module runs its --check logic in-process. ADR-0002 ("What stays
byte-identical for packs") requires it to match unchanged after every unmapped branch lands; an intended pack-path
change (KG8: a wrong-value fix) regenerates it with ``python scripts/golden_pack_path.py --write`` in the same commit.

Offline; one full run takes about ten seconds.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDENS = REPO_ROOT / "packages" / "core" / "tests" / "goldens" / "pack_path"
SCRIPT = REPO_ROOT / "scripts" / "golden_pack_path.py"


def _harness():
    spec = importlib.util.spec_from_file_location("golden_pack_path", SCRIPT)
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def test_every_pack_path_snapshot_matches_the_tools():
    problems = _harness().drift(GOLDENS)
    assert not problems, (
        "the pack-path output of fetch_blank / get_form_map / fill_form / verify_form / verify_filing changed:\n  "
        + "\n  ".join(problems)
        + "\nKG8: only a pack-path wrong-value fix may move it; regenerate with: python scripts/golden_pack_path.py "
        "--write"
    )


def test_every_shipped_pack_has_its_form_map_pinned():
    from taxfill_core.discovery import list_forms

    pinned = set()
    for path in GOLDENS.glob("form_maps_*.json"):
        pinned |= {(path.name, key) for key in json.loads(path.read_text(encoding="utf-8"))}
    shipped = {(f"form_maps_{s.jurisdiction.replace('/', '_')}.json", f"{s.tax_year}/{s.form_key}")
               for s in list_forms()}
    assert len(shipped) > 250 and pinned == shipped
    hand_fill = json.loads((GOLDENS / "_refusals.json").read_text(encoding="utf-8"))["get_form_map"]["hand_fill"]
    assert len(hand_fill) == len(list((REPO_ROOT / "formpacks").glob("**/handfill.yaml")))


def test_the_demo_chain_ran_the_real_fetch_fill_and_verify():
    chain = json.loads((GOLDENS / "_demo_chain.json").read_text(encoding="utf-8"))
    acro = chain["acroform"]
    # fetch_blank found the seeded blank by digest under its cache name (no download, no stub)
    assert acro["fetch_blank"]["path"].startswith("<cache>/") and len(acro["fetch_blank"]["sha256"]) == 64
    assert acro["fill_form"]["written"] == acro["fill_form_pdf_values"]
    assert acro["verify_form"]["ok"] is True and acro["verify_form_wrong_expected"]["ok"] is False
    assert acro["verify_form_bad_relation"]["sections"]["relations"]["failed"] == 1
    assert chain["hand_fill"]["fill_form"]["render_mode"] == "hand_fill_overlay"
    assert chain["hand_fill"]["verify_form"]["verdict"] == "OVERLAY" and chain["hand_fill"]["verify_form"]["ok"]
    assert chain["verify_filing"]["mixed"]["ok"] is True
    assert chain["verify_filing"]["mixed"]["form_keys"] == ["demo_golden", "demo_print"]


def test_no_snapshot_call_passes_form_unmapped():
    # ADR-0002: the golden pins no call with form "unmapped" (that key routes to the fallback).
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"""['"]unmapped['"]""", source)
    for path in GOLDENS.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "'unmapped'" not in text and '"form": "unmapped"' not in text, path.name


def test_snapshots_carry_no_local_paths_or_timestamps():
    pattern = re.compile(r"/(?:Users|home|private|tmp|var)/|[A-Za-z]:\\\\|\b20\d\d-\d\d-\d\dT\d\d:\d\d")
    for path in GOLDENS.glob("*.json"):
        hit = pattern.search(path.read_text(encoding="utf-8"))
        assert hit is None, f"{path.name}: {hit.group(0)!r}"


def test_a_one_character_pack_edit_fails_naming_the_file(tmp_path, monkeypatch):
    # The gate must see a change wherever get_form_map reads: one relation of the OH IT 1040 2025 pack edited in a
    # COPY of the data tree makes the OH snapshot alone drift.
    data = tmp_path / "data"
    shutil.copytree(REPO_ROOT / "formpacks", data / "formpacks")
    (data / "knowledge").symlink_to(REPO_ROOT / "knowledge")
    pack = next((data / "formpacks" / "states" / "oh" / "2025").glob("*/pack.yaml"))
    text = pack.read_text(encoding="utf-8")
    edited = re.sub(r"(\n  - \"[^\"\n]*?)(\d)(\")", lambda m: m.group(1) + str((int(m.group(2)) + 1) % 10) + m.group(3),
                    text, count=1)
    assert edited != text
    pack.write_text(edited, encoding="utf-8")
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(data))
    problems = _harness().drift(GOLDENS, only={"form_maps_states_oh.json", "form_maps_states_ri.json"})
    assert len(problems) == 1 and problems[0].startswith("form_maps_states_oh.json: drifted at 2025/"), problems
