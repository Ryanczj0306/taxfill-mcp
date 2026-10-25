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
    assert newest["al/2024/al40"] == 2024 and "al/2023/al40" not in newest   # AL 2024 shipped 2026-10-14 (JS5): it is the newest base below 2025
    fixed = sc.base_packs(2024, "2023")
    assert fixed and all(y == 2023 for y, _p in fixed)


def test_newest_base_reports_a_form_already_shipped_for_the_target_year():
    rows = {(r["state"], r["form"]): r for r in sc.scaffold(2025, "newest")}
    assert rows[("ar", "ar1000f")]["status"] == "shipped (2025 pack exists)"    # AR 2025 shipped 2026-08-21
    assert rows[("ut", "tc40")]["status"] == "shipped (2025 pack exists)"       # UT 2025 shipped 2026-09-28 (JS3b)
    assert rows[("ca", "form540")]["status"] == "shipped (2025 pack exists)"   # CA 540 2025 shipped 2026-10-01 (JS5, a re-map)
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


# ── Phase K JK10 (2026-10-24): the label-adjacency guard on the base pack, and the /Rect diff ──

def _rows_pdf(path: Path, order: list[str], *, extra: str = "") -> Path:
    """Rows "1".."3" printed IRS-style (gutter number, caption, leaders, the number again beside the box); the box on
    row i is the field order[i]."""
    texts, fields = [], []
    for i, (num, caption) in enumerate((("1", "Wages and salaries"), ("2", "Taxable interest"),
                                        ("3", "Ordinary dividends"))):
        y = 700.0 - 24.0 * i
        texts += [(1, 40, y, num), (1, 60, y, caption), (1, 160, y, "." * 50), (1, 452, y, num)]
        fields.append({"name": order[i], "page": 1, "x": 470.0, "y": y - 4, "width": 90, "height": 14})
    if extra:
        texts.append((1, 40, 100, extra))
    return make_acroform_pdf(path, fields, texts=texts, draw_labels=False)


def _ported(tmp: Path, monkeypatch, keys: dict[str, str], candidate_order: list[str]) -> tuple[Path, Path]:
    """A 2024 base pack (its blank seeded into a scratch shared cache) and a cached 2025 candidate blank."""
    from taxfill_core.fetch import seed_blank

    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp / "shared"))
    base_url = "https://tax.example.gov/forms/2024/zz-f1.pdf"
    base_pdf = _rows_pdf(tmp / "src" / "base.pdf", ["A1", "A2", "A3"])
    digest = hashlib.sha256(base_pdf.read_bytes()).hexdigest()
    seed_blank(base_pdf, base_url, digest)
    pack = tmp / "states" / "zz" / "2024" / "f1" / "pack.yaml"
    pack.parent.mkdir(parents=True)
    pack.write_text(yaml.safe_dump({"source_url": base_url, "pdf_sha256": digest,
                                    "fields": [{"line": k, "field": f} for k, f in keys.items()]}))
    cache = tmp / "cache"
    _rows_pdf(cache / "zz-f1-2025.pdf", candidate_order, extra="Rev. 2025")
    return tmp / "states", cache


def test_jk10_a_rotated_base_pack_is_base_misbound_even_when_the_names_port(tmp_path: Path, monkeypatch):
    # P-032's shape: the base binds line 2 to the widget on row 3 and line 3 to the one on row 2, and the next
    # year's blank carries the same names on the same rows, so a name (or /Rect) diff calls it PORTABLE.
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A3", "3": "A2"}, ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["names_status"].startswith("PORTABLE") and row["moved"] == 0
    assert row["base_label_adjacency"].startswith("OFF (2 key(s)") and "2, 3" in row["base_label_adjacency"]
    assert row["status"].startswith("BASE-MISBOUND (fix the 2024 pack first")
    # the recorded verdicts were measured by names: a recorded PORTABLE row still reproduces
    rows = tmp_path / "rows.json"
    cand = cache / "zz-f1-2025.pdf"
    rows.write_text(json.dumps({"rows": [{"state": "zz", "form_dir": "f1", "year": 2025, "verdict": "PORTABLE",
                                          "url": "https://tax.example.gov/forms/2025/zz-f1.pdf",
                                          "sha256": hashlib.sha256(cand.read_bytes()).hexdigest()}]}))
    [row] = sc.scaffold(2025, "newest", rows_path=rows, triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"].startswith("BASE-MISBOUND") and row["reproduces"] is True


def test_jk10_a_correct_base_with_unmoved_widgets_stays_portable(tmp_path: Path, monkeypatch):
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A2", "3": "A3"}, ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["status"].startswith("PORTABLE"), row
    assert row["base_label_adjacency"] == "OK (3/3 line-bearing keys checked)" and row["moved"] == 0


def test_jk10_a_mapped_widget_that_moved_forces_a_re_map(tmp_path: Path, monkeypatch):
    # the same names on the next year's blank, but A2 and A3 traded rows: identical topology, different binding
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A2", "3": "A3"}, ["A1", "A3", "A2"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["names_status"].startswith("PORTABLE")
    assert row["status"] == "RE-MAP (2 mapped widgets moved on the page)" and row["moved_sample"] == ["A2", "A3"]


def test_jk10_the_rect_diff_rule():
    base = {"r.A": [(1, (10.0, 10.0, 50.0, 20.0))], "r.B": [(1, (10.0, 30.0, 50.0, 40.0))],
            "r.C": [(1, (0.0, 0.0, 1.0, 1.0)), (2, (0.0, 0.0, 1.0, 1.0))], "r.D": [(1, (0.0, 0.0, 9.0, 9.0))]}
    cand = {"r.A": [(1, (10.9, 10.0, 50.0, 20.0))],                     # within the tolerance
            "r.B": [(2, (10.0, 30.0, 50.0, 40.0))],                     # another page
            "r.C": [(1, (0.0, 0.0, 1.0, 1.0))]}                         # one widget fewer; D is gone (not a move)
    assert sc.moved_widgets({"A", "B", "C", "D"}, base, cand) == ["B", "C"]
    cand["r.A"] = [(1, (11.5, 10.0, 50.0, 20.0))]
    assert sc.moved_widgets({"A"}, base, cand) == ["A"]


def test_jk10_offline_triage_reports_an_uncached_base_blank(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "empty"))
    states = _mini_states(tmp_path, "https://tax.example.gov/forms/2024/zz-f1.pdf")
    pack = states / "zz" / "2024" / "f1" / "pack.yaml"
    pack.write_text(yaml.safe_dump({**yaml.safe_load(pack.read_text()), "pdf_sha256": "0" * 64}))
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=tmp_path / "c", states_dir=states)
    assert row["base_label_adjacency"] == "NOT-CACHED (offline)"


# ── Phase K JK10 (2026-10-24), fixer round 2: overrides whatever the candidate's state; never OK at 0 checked ──

def _base_only(tmp: Path, monkeypatch, keys: dict[str, str], url: str) -> Path:
    """A 2024 base pack at ``url`` whose blank (rows 1-3, boxes A1-A3) is seeded into a scratch shared cache."""
    from taxfill_core.fetch import seed_blank

    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp / "shared"))
    base_pdf = _rows_pdf(tmp / "src" / "base.pdf", ["A1", "A2", "A3"])
    digest = hashlib.sha256(base_pdf.read_bytes()).hexdigest()
    seed_blank(base_pdf, url, digest)
    pack = tmp / "states" / "zz" / "2024" / "f1" / "pack.yaml"
    pack.parent.mkdir(parents=True)
    pack.write_text(yaml.safe_dump({"source_url": url, "pdf_sha256": digest,
                                    "fields": [{"line": k, "field": f} for k, f in keys.items()]}))
    return tmp / "states"


ROTATED = {"1": "A1", "2": "A3", "3": "A2"}


def test_jk10_a_misbound_base_overrides_a_no_year_token_row(tmp_path: Path, monkeypatch):
    states = _base_only(tmp_path, monkeypatch, ROTATED, "https://tax.example.gov/forms/zz-f1.pdf")
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=tmp_path / "c", states_dir=states)
    assert row["base_label_adjacency"].startswith("OFF (2 key(s)")
    assert row["status"].startswith("BASE-MISBOUND (fix the 2024 pack first") and row["port_status"] == "no-year-token"


def test_jk10_a_misbound_base_overrides_an_uncached_candidate(tmp_path: Path, monkeypatch):
    states = _base_only(tmp_path, monkeypatch, ROTATED, "https://tax.example.gov/forms/2024/zz-f1.pdf")
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=tmp_path / "c", states_dir=states)
    assert row["status"].startswith("BASE-MISBOUND") and row["port_status"] == "NOT-CACHED (offline)"


def test_jk10_a_base_the_gate_cannot_check_is_unchecked_never_ok(tmp_path: Path, monkeypatch):
    # keys in no line-bearing shape: the guard compares nothing, so the base is UNCHECKED, not "OK (0 checked)"
    named = {"wages": "A1", "interest": "A3", "dividends": "A2"}
    states, cache = _ported(tmp_path, monkeypatch, named, ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["base_label_adjacency"] == "UNCHECKED (0/0 line-bearing keys checked)"
    assert row["names_status"].startswith("PORTABLE") and row["port_status"].startswith("PORTABLE")
    assert row["status"].startswith("BASE-UNCHECKED (check the 2024 pack's line binding by hand")


def test_jk10_a_base_below_the_floor_is_partial(tmp_path: Path, monkeypatch):
    # one of three line-bearing keys binds a field the blank lacks: 2/3 checked is below the 70% floor
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A2", "3": "GONE"}, ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["base_label_adjacency"].startswith("PARTIAL 2/3")
    assert row["status"].startswith("BASE-UNCHECKED") and "PARTIAL 2/3" in row["status"]


# ── Phase K JK10 (2026-10-24), fixer round 3: the non-circular denominator; handfill bases ──

def test_jk10_undeclared_line_keys_count_against_the_base(tmp_path: Path, monkeypatch):
    # rows 2 and 3 are keyed "2.a" / "3.a" (rotated), a shape no rule maps for this pack: round 2 counted only the
    # keys a rule maps (1 of 1 -> OK); every line-like key now counts, so 1/3 checked is PARTIAL, never OK
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2.a": "A3", "3.a": "A2"}, ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["base_label_adjacency"].startswith("PARTIAL 1/3"), row["base_label_adjacency"]
    assert row["status"].startswith("BASE-UNCHECKED") and row["port_status"].startswith("PORTABLE")


def test_jk10_a_handfill_base_is_not_label_checked_and_keeps_its_port_status(tmp_path: Path, monkeypatch):
    from taxfill_core.fetch import seed_blank

    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "shared"))
    url = "https://tax.example.gov/forms/2024/zz-f1.pdf"
    base_pdf = _rows_pdf(tmp_path / "src" / "base.pdf", ["A1", "A2", "A3"])
    digest = hashlib.sha256(base_pdf.read_bytes()).hexdigest()
    seed_blank(base_pdf, url, digest)
    hf = tmp_path / "states" / "zz" / "2024" / "f1" / "handfill.yaml"
    hf.parent.mkdir(parents=True)
    hf.write_text(yaml.safe_dump({"source_url": url, "pdf_sha256": digest, "render_mode": "hand_fill",
                                  "lines": [{"line": "1", "label": "Wages", "type": "money",
                                             "overlay": {"page": 1, "x": 470, "y": 696, "w": 90}}]}))
    cache = tmp_path / "cache"
    _rows_pdf(cache / "zz-f1-2025.pdf", ["A1", "A2", "A3"], extra="Rev. 2025")
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=tmp_path / "states")
    assert row["kind"] == "handfill.yaml"
    assert row["base_label_adjacency"] == sc.HANDFILL_BASE
    assert not row["status"].startswith(("BASE-UNCHECKED", "BASE-MISBOUND")) and "port_status" not in row


# ── Phase K JK10 (2026-10-24), fixer round 4: a dark key family; the handfill verdict's wording ──

def test_jk10_a_base_with_a_dark_family_is_base_unchecked_whatever_its_fraction(tmp_path: Path, monkeypatch):
    # rows 1-3 checked, one more line-like key ("sx_9") no rule maps, on a widget the blank lacks (so the anchor
    # reads no line beside it): 3/4 is above the floor (OK). A family of DARK_FAMILY_MIN undeclared keys is a whole
    # schedule the gate cannot compare (round 3: OH Schedule of Business Income, 22 keys, OK at 121/152), so the
    # base is PARTIAL — shown here with the minimum lowered to one key.
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A2", "3": "A3", "sx_9": "GONE"},
                            ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["base_label_adjacency"].startswith("OK (3/4"), row["base_label_adjacency"]
    la = sc._label_adjacency()
    monkeypatch.setattr(la, "DARK_FAMILY_MIN", 1)
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    assert row["base_label_adjacency"].startswith("PARTIAL 3/4") and "sx_#" in row["base_label_adjacency"]
    assert row["status"].startswith("BASE-UNCHECKED") and "port_status" in row


# ── Phase K JK10 (2026-10-24), fixer round 5: the declare-me rule ──

def test_jk10_an_undeclared_key_the_anchor_reads_makes_the_base_unchecked_whatever_its_family_size(
        tmp_path: Path, monkeypatch):
    # rows 1-3 checked (3/4, above the floor) and one undeclared key "sx_9" on row A3's box: the anchor reads line 3
    # beside it, so the gate could compare it and compares nothing — a 1-key family, far under DARK_FAMILY_MIN (the
    # round-4 verifier's AZ 140 worksheet and MT 2023 LTC rows read OK this way). The base is PARTIAL, the family
    # named, until a shape declares it.
    states, cache = _ported(tmp_path, monkeypatch, {"1": "A1", "2": "A2", "3": "A3", "sx_9": "A3"},
                            ["A1", "A2", "A3"])
    [row] = sc.scaffold(2025, "newest", triage=True, offline=True, cache_dir=cache, states_dir=states)
    verdict = row["base_label_adjacency"]
    assert verdict.startswith("PARTIAL 3/4") and "declare them): sx_#" in verdict, verdict
    assert row["status"].startswith("BASE-UNCHECKED") and row["port_status"].startswith("PORTABLE")


def test_jk10_the_handfill_verdict_asks_for_a_vision_check_of_the_overlay_boxes():
    assert sc.HANDFILL_BASE == ("NOT-APPLICABLE (handfill base: no AcroForm binding; vision-check the overlay boxes "
                                "on port)")
