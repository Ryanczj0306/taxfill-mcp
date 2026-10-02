"""Shared pytest fixtures (Phase J JT0b): planning-year tests test BEHAVIOUR, not today's contents of the
provisional pack — a 2026 block added at the finals must not turn the suite red.

Also the freshness quarantine hook (Phase J JT0c): a network test named in scripts/freshness_quarantine.yaml
is xfail on a FETCH failure only, until its row expires."""
from __future__ import annotations

import datetime as dt
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml


def pytest_collection_modifyitems(config, items):
    if not any(item.get_closest_marker("network") for item in items):
        return
    from taxfill_core.fetch import FetchError  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "freshness_quarantine", Path(__file__).resolve().parents[1] / "scripts" / "freshness_quarantine.py")
    quarantine = sys.modules.setdefault(spec.name, importlib.util.module_from_spec(spec))
    spec.loader.exec_module(quarantine)
    quarantine.quarantine_items(items, quarantine.load(), dt.date.today(), FetchError)


def _knowledge() -> Path:
    """The knowledge tree the engine reads — $TAXFILL_DATA_DIR honoured, so a scratch copy is tested as-is."""
    from taxfill_core.datadir import knowledge_dir  # noqa: PLC0415

    return knowledge_dir()


def _provisional_years() -> list[int]:
    from taxfill_core.knowledge import provisional_marker  # noqa: PLC0415

    years = sorted(int(p.stem) for p in (_knowledge() / "federal").glob("[0-9][0-9][0-9][0-9].yaml"))
    return [y for y in years if provisional_marker("federal", y) is not None]


@pytest.fixture
def planning_year() -> int:
    """The newest federal year whose knowledge pack is provisional (planning-only); skip when none ships."""
    years = _provisional_years()
    if not years:
        pytest.skip("no provisional (planning-only) federal knowledge pack ships")
    return years[-1]


@pytest.fixture
def synthetic_provisional_pack(tmp_path: Path, planning_year: int):
    """``make(strip)`` -> a tmp knowledge dir whose planning-year pack has the named blocks REMOVED and declared
    in ``provisional.blocks_deliberately_absent`` — whether or not the real pack ships them today."""

    def make(strip: list[str]) -> Path:
        source = _knowledge()
        base = tmp_path / "knowledge"
        if base.exists():
            shutil.rmtree(base)
        for part in ("federal", "treaties", "forms"):
            if (source / part).is_dir():
                shutil.copytree(source / part, base / part)
        for name in ("sources.yaml", "pitfalls.yaml"):
            shutil.copy(source / name, base / name)
        path = base / "federal" / f"{planning_year}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for block in strip:
            data.pop(block, None)
            if isinstance(data.get("tax"), dict):
                data["tax"].pop(block, None)
        absent = data["provisional"].setdefault("blocks_deliberately_absent", [])
        absent.extend(b for b in strip if b not in absent)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return base

    return make
