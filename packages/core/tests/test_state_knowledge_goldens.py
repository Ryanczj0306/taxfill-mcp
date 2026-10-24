"""The golden diff over every tool that reads state knowledge (Phase K JK21).

scripts/golden_snapshots.py snapshots what state_tax (the calc op), state_scope, filing_summary,
file_and_pay and get_sources return for every knowledge/states/<st>/<year>.yaml. This module runs
its --check logic in-process: any drift fails with the snapshot file and the first differing key.
It is the gate for JK20, JK22, JK24 and JK26, which restructure the state knowledge layer and must
not change what the tools emit. An intended output change is regenerated with
``python scripts/golden_snapshots.py --write`` and reviewed in the diff.

Offline; one full run takes a few seconds.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDENS = REPO_ROOT / "packages" / "core" / "tests" / "goldens" / "state_knowledge"


def _harness():
    spec = importlib.util.spec_from_file_location("golden_snapshots", REPO_ROOT / "scripts" / "golden_snapshots.py")
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def test_every_state_knowledge_snapshot_matches_the_tools():
    problems = _harness().drift(GOLDENS)
    assert not problems, (
        "the tools' output over the state knowledge changed:\n  " + "\n  ".join(problems)
        + "\nIf the change is intended, regenerate with: python scripts/golden_snapshots.py --write"
    )


def test_every_jurisdiction_year_has_a_snapshot():
    expected = {f"{p.parent.name}_{p.stem}.json" for p in (REPO_ROOT / "knowledge" / "states").glob("*/[0-9]*.yaml")}
    on_disk = {p.name for p in GOLDENS.glob("*.json")}
    assert expected and expected <= on_disk
    assert on_disk - expected == {"_no_income_tax.json"}


def test_snapshots_carry_no_local_paths_or_timestamps():
    pattern = re.compile(r"/(?:Users|home|private|tmp)/|[A-Za-z]:\\\\|<data>|\b20\d\d-\d\d-\d\dT\d\d:\d\d")
    for path in GOLDENS.glob("*.json"):
        hit = pattern.search(path.read_text(encoding="utf-8"))
        assert hit is None, f"{path.name}: {hit.group(0)!r}"


def test_the_stored_form_expands_to_the_live_output():
    # compress() is lossless: the committed file expands to exactly what the tools return now.
    g = _harness()
    stored = json.loads((GOLDENS / "oh_2025.json").read_text(encoding="utf-8"))
    with g._memoized_yaml():
        live = g._jsonable(g.snapshot_jurisdiction_year("oh", 2025), "<unused>")
    assert g.expand(stored) == live
    # ... and the tail split really is in use (the OH notes are stored once, not per call).
    assert "$2,394.32" in stored["state_tax"]["work_common_tail"]


def test_a_one_character_knowledge_edit_fails_naming_the_file(tmp_path, monkeypatch):
    # The harness must see a change anywhere a tool reads: edit one character of an OH 2025 tax note
    # in a COPY of the knowledge tree and the OH 2025 snapshot alone must report drift.
    data = tmp_path / "data"
    shutil.copytree(REPO_ROOT / "knowledge", data / "knowledge")
    (data / "formpacks").mkdir()
    pack = data / "knowledge" / "states" / "oh" / "2025.yaml"
    text = pack.read_text(encoding="utf-8")
    assert text.count("this op''s result when line 7") == 1
    pack.write_text(text.replace("this op''s result when line 7", "this op''s result when line 8"), encoding="utf-8")
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(data))

    g = _harness()
    problems = g.drift(GOLDENS, only={"oh_2025.json", "oh_2024.json"})
    assert len(problems) == 1, problems
    assert problems[0].startswith("oh_2025.json: drifted at state_tax[0].work: first change at character ")
    assert "result when line 7" in problems[0] and "result when line 8" in problems[0]


def test_the_snapshot_set_stays_small():
    # ~5.2 MB at JK21 (127 files); ~6.3 MB after JK27, which snapshots get_sources in every year (a state's
    # registry block became per year) and adds an amended return to the demo manifest; ~7.2 MB after JK20, whose
    # registry entries keep every description of a URL instead of the first. A file over 256 KB, or a set over
    # 7.5 MB, means the grid grew by accident.
    sizes = {p.name: p.stat().st_size for p in GOLDENS.glob("*.json")}
    assert max(sizes.values()) < 256 * 1024, max(sizes, key=sizes.get)
    assert sum(sizes.values()) < 7_500_000


# A tool's refusal is output (calc refuses an unsupported grid point with a ValueError naming why), so the harness
# stores every raised error as data. A crash is not output: the JK21 snapshots stored three pydantic ValidationErrors
# as the answers for Florida (state_scope) and New Mexico 2025 (filing_summary, file_and_pay), and nobody noticed until
# JK27. Only a refusal may appear; a missing file is a crash too.
_REFUSAL_TYPES = {"ValueError"}


def test_no_snapshot_records_a_crash_as_the_answer():
    g = _harness()
    crashes = []

    def walk(node, where):
        if isinstance(node, dict):
            err = node.get("error")
            if isinstance(err, str) and err.split(":", 1)[0] not in _REFUSAL_TYPES:
                crashes.append(f"{where}: {err[:160]}")
            for key, value in node.items():
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{where}[{i}]")

    for path in sorted(GOLDENS.glob("*.json")):
        walk(g.expand(json.loads(path.read_text(encoding="utf-8"))), path.name)
    assert not crashes, "a snapshot stores a crash as a tool's answer:\n  " + "\n  ".join(crashes)
