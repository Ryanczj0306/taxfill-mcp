"""Phase J JS3a — scripts/scaffold_state_year.py: newest-base triage, recorded rows, cache-first/offline, year tokens."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from pdf_fixtures import make_acroform_pdf

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("scaffold_state_year", REPO / "scripts" / "scaffold_state_year.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


@pytest.mark.parametrize(("url", "base", "target", "want"), [
    # AL files the TY-N Form 40 in the N+1 upload folder: both years move together.
    ("https://www.revenue.alabama.gov/wp-content/uploads/2024/01/23f40.pdf", 2023, 2024,
     "https://www.revenue.alabama.gov/wp-content/uploads/2025/01/24f40.pdf"),
    ("https://www.revenue.alabama.gov/wp-content/uploads/2024/01/23f40.pdf", 2023, 2025,
     "https://www.revenue.alabama.gov/wp-content/uploads/2026/01/25f40.pdf"),
    # CT's MMYY revision suffix.
    ("https://portal.ct.gov/-/media/drs/forms/2023/income/ct-1040_1223.pdf", 2023, 2024,
     "https://portal.ct.gov/-/media/drs/forms/2024/income/ct-1040_1224.pdf"),
    # A URL-encoded space separates the year from the form number.
    ("https://revenue.ky.gov/Forms/Form%20740%202023.pdf", 2023, 2025, "https://revenue.ky.gov/Forms/Form%20740%202025.pdf"),
    # A form number next to the year is left alone.
    ("https://dor.sc.gov/sites/dor/files/forms/SC1040_2023.pdf", 2023, 2024,
     "https://dor.sc.gov/sites/dor/files/forms/SC1040_2024.pdf"),
    ("https://files.tax.utah.gov/tax/forms/2024/tc-40.pdf", 2024, 2025, "https://files.tax.utah.gov/tax/forms/2025/tc-40.pdf"),
])
def test_year_tokens_derive(url, base, target, want):
    assert sc._candidate_url(url, base, target) == (want, True)


def test_a_revision_date_in_the_name_is_not_derived():
    assert sc._revision_dated("https://otr.cfo.dc.gov/x/2023_D40_Form_0002_01222024.pdf")      # DC MMDDYYYY
    assert sc._revision_dated("https://otr.cfo.dc.gov/x/2024_D40_Form_0002_011525.pdf")        # DC MMDDYY
    assert sc._revision_dated("https://tax.idaho.gov/x/EFO00089_08-23-2023.pdf")               # ID MM-DD-YYYY
    for plain in ("https://dor.sc.gov/x/SC1040_2023.pdf", "https://revenue.ky.gov/Forms/Form%20740%202023.pdf",
                  "https://portal.ct.gov/x/ct-1040_1223.pdf", "https://files.tax.utah.gov/tax/forms/2024/tc-40.pdf"):
        assert not sc._revision_dated(plain), plain


def test_base_newest_triages_each_form_against_its_newest_shipped_year():
    newest = {str(p.relative_to(sc.STATES)).rsplit("/", 1)[0]: y for y, p in sc.base_packs(2025, "newest")}
    assert newest["ut/2024/tc40"] == 2024 and "ut/2023/tc40" not in newest
    assert newest["al/2023/al40"] == 2023                       # no newer AL pack: its 2023 base stands
    fixed = sc.base_packs(2024, "2023")
    assert fixed and all(y == 2023 for y, _p in fixed)


def test_newest_base_reports_a_form_already_shipped_for_the_target_year():
    rows = {(r["state"], r["form"]): r for r in sc.scaffold(2025, "newest")}
    assert rows[("ar", "ar1000f")]["status"] == "shipped (2025 pack exists)"    # AR 2025 shipped 2026-08-21
    assert rows[("ut", "tc40")]["status"] == "shipped (2025 pack exists)"       # UT 2025 shipped 2026-09-28 (JS3b)
    assert rows[("ca", "form540")]["status"] == "candidate"                     # CA 540 2025 is still open work (a re-map)
    legacy = {(r["state"], r["form"]): r for r in sc.scaffold(2025, "2023")}
    assert legacy[("ar", "ar1000f")]["status"] == "candidate"                   # a fixed base keeps the old census


def _mini_states(tmp: Path, url: str) -> Path:
    pack = tmp / "states" / "zz" / "2024" / "f1" / "pack.yaml"
    pack.parent.mkdir(parents=True)
    pack.write_text(yaml.safe_dump({"source_url": url, "fields": [{"line": "a", "field": "Page1.a"},
                                                                  {"line": "b", "field": "Page1.b"}]}))
    return tmp / "states"


def test_recorded_rows_replace_the_derivation_and_the_triage_is_cache_first(tmp_path: Path):
    url = "https://tax.example.gov/forms/2025/zz-f1-final.pdf"
    states = _mini_states(tmp_path, "https://tax.example.gov/forms/2024/zz-f1.pdf")
    cache = tmp_path / "cache"
    blank = make_acroform_pdf(cache / "zz-f1-2025.pdf", [{"name": "Page1.a"}, {"name": "Page1.b"}, {"name": "Page1.c"}])
    digest = hashlib.sha256(blank.read_bytes()).hexdigest()
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps({"rows": [{"state": "zz", "form_dir": "f1", "year": 2025, "url": url, "sha256": digest,
                                          "verdict": "PORTABLE"}]}))
    [row] = sc.scaffold(2025, "newest", rows_path=rows, triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert (row["candidate_url"], row["source"], row["base_year"]) == (url, "recorded", 2024)
    assert row["status"].startswith("PORTABLE") and row["reproduces"] is True
    blank.write_bytes(blank.read_bytes() + b"\n% another revision\n")         # the cached file is not the pinned one
    [row] = sc.scaffold(2025, "newest", rows_path=rows, triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"].startswith("DIGEST-MISMATCH") and row["reproduces"] is False
    blank.unlink()
    [row] = sc.scaffold(2025, "newest", rows_path=rows, triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"] == "NOT-CACHED (offline)"


def test_js5_a_candidate_that_is_the_base_blank_is_same_as_base(tmp_path: Path):
    # NM TRD's gateway serves a file by the GUID in its path: "2024pit-1.pdf" / "2025pit-1.pdf" were the 2023 blank.
    states = _mini_states(tmp_path, "https://tax.example.gov/forms/2024/zz-f1.pdf")
    cache = tmp_path / "cache"
    blank = make_acroform_pdf(cache / "zz-f1-2025.pdf", [{"name": "Page1.a"}, {"name": "Page1.b"}])
    pack = states / "zz" / "2024" / "f1" / "pack.yaml"
    raw = yaml.safe_load(pack.read_text())
    pack.write_text(yaml.safe_dump({**raw, "pdf_sha256": hashlib.sha256(blank.read_bytes()).hexdigest()}))
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"].startswith("SAME-AS-BASE")
    blank.write_bytes(blank.read_bytes() + b"\n% the next year's revision\n")
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"].startswith("PORTABLE")


def test_offline_never_downloads(tmp_path: Path, monkeypatch):
    states = _mini_states(tmp_path, "https://tax.example.gov/forms/2024/zz-f1.pdf")
    monkeypatch.setattr(sc.urllib.request, "urlopen", lambda *a, **k: pytest.fail("offline triage opened a URL"))
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=tmp_path / "c", states_dir=states)
    assert row["candidate_url"] == "https://tax.example.gov/forms/2025/zz-f1.pdf" and row["status"].startswith("NOT-CACHED")


def test_the_recorded_rows_file_is_public_data_only():
    doc = json.loads((REPO / "scripts" / "state_discovery_rows.json").read_text())
    assert len(doc["rows"]) == 16
    for r in doc["rows"]:
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]) and r["url"].startswith("https://")
        assert (sc.STATES / r["state"]).is_dir() and any((sc.STATES / r["state"]).glob(f"*/{r['form_dir']}/pack.yaml"))
    assert "/private/" not in json.dumps(doc) and "/Users/" not in json.dumps(doc)


@pytest.mark.network
def test_ut_2025_triages_portable_against_ut_2024():
    # A fixed base keeps the census: newest mode stops triaging a form once its target-year pack ships (JS3b
    # shipped UT 2025 the next day, and this test, pinned to newest mode, went red unnoticed until JS3c).
    rows = {(r["state"], r["form"]): r for r in sc.scaffold(2025, "2024", triage=True)}
    ut = rows[("ut", "tc40")]
    assert ut["base_year"] == 2024 and ut["status"].startswith("PORTABLE"), ut
    newest = {(r["state"], r["form"]): r for r in sc.scaffold(2025, "newest")}
    assert newest[("ut", "tc40")]["status"].startswith("shipped"), newest[("ut", "tc40")]


@pytest.mark.network
def test_the_triage_reproduces_every_recorded_row():
    # The recorded verdicts were measured against the 2023 base (the 2026-09-12 discovery run), so the triage
    # replays that base; newest mode would skip every row JS3b has since shipped.
    for year in (2024, 2025):
        recorded = [r for r in sc.scaffold(year, "2023", rows_path=sc.DEFAULT_ROWS, triage=True)
                    if r.get("recorded_verdict")]
        assert len(recorded) == 8
        bad = [(r["state"], year, r["status"], r["recorded_verdict"]) for r in recorded if not r["reproduces"]]
        if any("URL-DEAD" in b[2] for b in bad):
            pytest.skip(f"a recorded blank could not be fetched: {bad}")
        assert not bad, bad
