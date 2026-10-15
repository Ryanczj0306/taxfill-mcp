"""Offline tests for scripts/release_smoke.py (Phase J JA1), the installed-wheel check CI's packaging job runs.

The script itself only runs against a built wheel in CI; these tests pin its logic without building anything: the
expectations it reads from a checkout, each comparison on synthetic counts, and ``main`` end to end with the
observation of the installed packages monkeypatched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("release_smoke", REPO / "scripts" / "release_smoke.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


smoke = _load()


def _touch(path: Path, text: str = "x: 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def tiny_repo(tmp_path):
    """A two-state checkout: federal 2025 (two packs), CA 2025 (one pack + a hand-fill), state knowledge 2025."""
    root = tmp_path / "repo"
    _touch(root / "formpacks" / "federal" / "2025" / "f1040" / "pack.yaml")
    _touch(root / "formpacks" / "federal" / "2025" / "f8843" / "pack.yaml")
    _touch(root / "formpacks" / "states" / "ca" / "2025" / "ca540" / "pack.yaml")
    _touch(root / "formpacks" / "states" / "ca" / "2025" / "ca540_hf" / "handfill.yaml")
    _touch(root / "formpacks" / "README.md", "# packs\n")
    _touch(root / "formpacks" / "federal" / "2025" / "f1040" / "blank.pdf", "%PDF")  # never staged
    _touch(root / "knowledge" / "federal" / "2025.yaml")
    for st in ("ca", "ny"):
        _touch(root / "knowledge" / "states" / st / "2025.yaml")
    _touch(root / "knowledge" / "states" / "no_income_tax.yaml")
    _touch(root / smoke.E2E_TEST, 'EXPECTED_TOOLS = {"calc", "list_forms"}\n\n'
                                  "def test_x():\n    assert len(names) == 2\n")
    return root


# ── expectations read from a checkout ────────────────────────────────────────


def test_repo_form_sets_reads_the_pack_layout(tiny_repo):
    assert smoke.repo_form_sets(tiny_repo / "formpacks") == {
        ("federal", 2025): {"f1040", "f8843"}, ("states/ca", 2025): {"ca540"}}


def test_repo_form_sets_refuses_an_off_layout_pack(tiny_repo):
    _touch(tiny_repo / "formpacks" / "federal" / "f1040" / "pack.yaml")
    with pytest.raises(ValueError, match="layout"):
        smoke.repo_form_sets(tiny_repo / "formpacks")


def test_data_digests_cover_what_stage_data_copies(tiny_repo):
    files = set(smoke.data_digests(tiny_repo))
    assert "formpacks/states/ca/2025/ca540_hf/handfill.yaml" in files and "formpacks/README.md" in files
    assert not any(f.endswith(".pdf") for f in files)
    assert smoke.DATA_SUFFIXES == {".yaml", ".yml", ".md"}
    stage = (REPO / "scripts" / "stage_data.py").read_text(encoding="utf-8")
    assert '{".yaml", ".yml", ".md"}' in stage, "release_smoke.DATA_SUFFIXES must follow stage_data.py"


def test_state_knowledge_counts_ignore_the_non_state_files(tiny_repo):
    assert smoke.state_knowledge_counts(tiny_repo / "knowledge") == (2, {2025: 2})


def test_pinned_tools_reads_the_set_and_the_literal(tiny_repo):
    assert smoke.pinned_tools(tiny_repo / smoke.E2E_TEST) == ({"calc", "list_forms"}, 2)


def test_the_real_e2e_pin_is_self_consistent():
    names, literal = smoke.pinned_tools(REPO / smoke.E2E_TEST)
    assert literal is not None and len(names) == literal


def test_the_real_checkout_has_one_state_pack_per_jurisdiction_every_year():
    jurisdictions, counts = smoke.state_knowledge_counts(REPO / "knowledge")
    assert jurisdictions == 42 and counts and set(counts.values()) == {42}


# ── the comparisons, on synthetic counts ─────────────────────────────────────


def test_check_forms_names_the_missing_and_the_extra():
    want = {("federal", 2025): {"f1040", "f8843"}, ("states/ca", 2025): {"ca540"}}
    assert smoke.check_forms(want, {k: set(v) for k, v in want.items()}) == []
    got = {("federal", 2025): {"f1040", "f9999"}}
    out = smoke.check_forms(want, got)
    assert len(out) == 2
    assert "missing ['f8843']" in out[0] and "not in the checkout ['f9999']" in out[0]
    assert out[1].startswith("list_forms('states/ca', 2025): 0 packs in the wheel, 1 in the checkout")


def test_check_data_files_flags_missing_extra_and_stale():
    want = {"a.yaml": "1", "b.yaml": "2", "c.md": "3"}
    assert smoke.check_data_files(want, dict(want)) == []
    out = smoke.check_data_files(want, {"a.yaml": "1", "b.yaml": "X", "d.yaml": "4"})
    assert len(out) == 3
    assert "missing from the wheel" in out[0] and "c.md" in out[0]
    assert "not the checkout" in out[1] and "d.yaml" in out[1]
    assert "stale staging" in out[2] and "b.yaml" in out[2]


def test_check_state_knowledge_wants_every_jurisdiction_every_year():
    assert smoke.check_state_knowledge(42, {2024: 42, 2025: 42}, {2024: 42, 2025: 42}) == []
    out = smoke.check_state_knowledge(42, {2024: 42, 2025: 42}, {2024: 41, 2025: 42})
    assert any("wheel {2024: 41" in line for line in out)
    assert any("state knowledge 2024: 41 packs" in line for line in out)
    assert smoke.check_state_knowledge(42, {}, {}) == ["the checkout has no state knowledge year at all"]


def test_check_tools_compares_names_not_only_the_count():
    pinned = {"calc", "list_forms"}
    assert smoke.check_tools({"calc", "list_forms"}, pinned, 2) == []
    out = smoke.check_tools({"calc", "fill_form"}, pinned, 2)  # same count, different tool
    assert out and "unexpected ['fill_form']" in out[0] and "missing ['list_forms']" in out[0]
    assert "disagrees with itself" in smoke.check_tools(pinned, pinned, 3)[0]


def _sdist(dist: Path, name: str, members: list[str]) -> None:
    import io
    import tarfile

    dist.mkdir(parents=True, exist_ok=True)
    top = name.removesuffix(".tar.gz")
    with tarfile.open(dist / name, "w:gz") as tar:
        for member in members:
            data = b"x"
            info = tarfile.TarInfo(f"{top}/{member}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_check_sdists_wants_both_and_refuses_the_bundle_recipe(tmp_path):
    """Check 7: PyPI freezes the sdist too, so the repo-only bundle/ recipe must stay out of it."""
    dist = tmp_path / "dist"
    _sdist(dist, "taxfill_core-0.1.0.tar.gz", ["pyproject.toml", "README.md", "src/taxfill_core/__init__.py"])
    _sdist(dist, "taxfill_mcp-0.1.0.tar.gz", ["pyproject.toml", "README.md", "src/taxfill_mcp/__init__.py",
                                              "tests/test_server_e2e.py"])
    members = smoke.sdist_members(dist)
    assert members["taxfill_mcp-0.1.0.tar.gz"] == ["README.md", "pyproject.toml", "src/taxfill_mcp/__init__.py",
                                                   "tests/test_server_e2e.py"]
    assert smoke.check_sdists(members) == []

    _sdist(dist, "taxfill_mcp-0.1.0.tar.gz", ["pyproject.toml", "bundle/README.md", "bundle/manifest.json"])
    [problem] = smoke.check_sdists(smoke.sdist_members(dist))
    assert "taxfill_mcp-0.1.0.tar.gz carries repo-only files" in problem and "bundle/README.md" in problem

    (dist / "taxfill_core-0.1.0.tar.gz").unlink()
    problems = smoke.check_sdists(smoke.sdist_members(dist))
    assert any("expected one taxfill_core-*.tar.gz" in p for p in problems)


def test_check_location(tmp_path):
    site, repo = tmp_path / "venv" / "site-packages", tmp_path / "repo"
    pkg = site / "taxfill_core" / "__init__.py"
    assert smoke.check_location(site / "taxfill_core" / "_data", [pkg], [site], repo, None) == []
    out = smoke.check_location(repo, [repo / "packages" / "core" / "src" / "taxfill_core" / "__init__.py"],
                               [site], repo, str(repo))
    assert len(out) == 4
    assert "TAXFILL_DATA_DIR is set" in out[0] and "not inside site-packages" in out[1]
    assert "inside the checkout" in out[2] and "outside site-packages" in out[3]


# ── main, with the installed packages' observation monkeypatched ─────────────


def _observed(repo: Path, site: Path) -> dict:
    return {
        "data_root": site / "taxfill_core" / "_data",
        "package_files": [site / "taxfill_core" / "__init__.py", site / "taxfill_mcp" / "__init__.py"],
        "versions": ("0.1.0", "0.1.0"),
        "forms": smoke.repo_form_sets(repo / "formpacks"),
        "digests": smoke.data_digests(repo),
        "state_knowledge": smoke.state_knowledge_counts(repo / "knowledge"),
        "load_errors": [],
        "tools": smoke.pinned_tools(repo / smoke.E2E_TEST)[0],
    }


def test_main_passes_when_the_wheel_matches_and_fails_on_each_drift(tiny_repo, tmp_path, monkeypatch, capsys):
    site = tmp_path / "venv" / "site-packages"
    monkeypatch.setattr(smoke, "site_dirs", lambda: [site])
    monkeypatch.delenv("TAXFILL_DATA_DIR", raising=False)
    good = _observed(tiny_repo, site)
    monkeypatch.setattr(smoke, "observe", lambda keys: good)
    monkeypatch.syspath_prepend(str(REPO / "scripts"))  # as a test runner that imports from scripts/ would have it
    before = list(sys.path)
    assert smoke.main(["--repo", str(tiny_repo)]) == 0
    assert sys.path == before, "main() must not touch the caller's sys.path (only the script entry point strips scripts/)"
    assert "OK — the installed wheel matches the checkout" in capsys.readouterr().out

    drifts = {
        "forms": {("federal", 2025): {"f1040"}, ("states/ca", 2025): {"ca540"}},
        "state_knowledge": (2, {2025: 1}),
        "tools": {"calc"},
        "load_errors": ["load_state_knowledge('ny', 2025): ValidationError"],
        "data_root": tiny_repo,
    }
    for key, value in drifts.items():
        monkeypatch.setattr(smoke, "observe", lambda keys, key=key, value=value: {**good, key: value})
        assert smoke.main(["--repo", str(tiny_repo)]) == 1, key
        assert "FAIL" in capsys.readouterr().err, key


def test_main_runs_the_sdist_check_only_with_dist(tiny_repo, tmp_path, monkeypatch, capsys):
    site = tmp_path / "venv" / "site-packages"
    monkeypatch.setattr(smoke, "site_dirs", lambda: [site])
    monkeypatch.delenv("TAXFILL_DATA_DIR", raising=False)
    monkeypatch.setattr(smoke, "observe", lambda keys: _observed(tiny_repo, site))
    dist = tmp_path / "dist"
    _sdist(dist, "taxfill_core-0.1.0.tar.gz", ["pyproject.toml"])
    _sdist(dist, "taxfill_mcp-0.1.0.tar.gz", ["pyproject.toml", "bundle/README.md"])
    assert smoke.main(["--repo", str(tiny_repo)]) == 0
    capsys.readouterr()
    assert smoke.main(["--repo", str(tiny_repo), "--dist", str(dist)]) == 1
    assert "carries repo-only files" in capsys.readouterr().err


def test_main_reads_the_checkout_from_the_env(tiny_repo, tmp_path, monkeypatch):
    site = tmp_path / "venv" / "site-packages"
    monkeypatch.setattr(smoke, "site_dirs", lambda: [site])
    monkeypatch.delenv("TAXFILL_DATA_DIR", raising=False)
    monkeypatch.setattr(smoke, "observe", lambda keys: _observed(tiny_repo, site))
    monkeypatch.setenv(smoke.REPO_ENV, str(tiny_repo))
    assert smoke.main([]) == 0
    monkeypatch.delenv(smoke.REPO_ENV)
    with pytest.raises(SystemExit):
        smoke.main([])


def test_checkout_mode_runs_against_this_repo(monkeypatch, capsys):
    """The documented quick self-check, on the real checkout through the editable install (no wheel)."""
    monkeypatch.delenv("TAXFILL_DATA_DIR", raising=False)
    assert smoke.main(["--repo", str(REPO), "--checkout"]) == 0, capsys.readouterr().err
