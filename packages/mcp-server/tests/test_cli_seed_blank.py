"""Phase J JS1b — `taxfill seed-blank`: cache a browser-saved blank for a host that refuses fetchers, digest-checked."""
from __future__ import annotations

import hashlib
from pathlib import Path

from taxfill_core.fetch import cached_blank_path
from taxfill_core.schemas.formpack import load_pack
from taxfill_mcp.cli import main

MA = Path(__file__).resolve().parents[3] / "formpacks" / "states" / "ma" / "2023" / "form1" / "pack.yaml"
PDF = b"%PDF-1.7\n% synthetic taxfill fixture, not a real form\n%%EOF\n"


def test_seed_blank_with_url_and_digest(tmp_path: Path, capsys):
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(PDF)
    url, digest = "https://www.mass.gov/doc/2099-form-0-demo-return/download", hashlib.sha256(PDF).hexdigest()
    assert main(["seed-blank", str(saved), "--url", url, "--sha256", digest, "--cache-dir", str(tmp_path / "c")]) == 0
    assert "verified" in capsys.readouterr().out
    assert cached_blank_path(url, digest, cache_dir=tmp_path / "c") is not None


def test_seed_blank_refuses_bytes_that_are_not_the_packs(tmp_path: Path, capsys):
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(PDF)                      # not the MA Form 1 the pack pins
    assert main(["seed-blank", str(saved), "--pack", str(MA), "--cache-dir", str(tmp_path / "c")]) == 1
    assert "a different revision" in capsys.readouterr().err
    assert cached_blank_path(load_pack(MA).source_url, load_pack(MA).pdf_sha256, cache_dir=tmp_path / "c") is None


def test_seed_blank_needs_a_pack_or_both_url_and_digest(tmp_path: Path, capsys):
    assert main(["seed-blank", str(tmp_path / "x.pdf"), "--url", "https://www.mass.gov/x"]) == 2
    assert "--pack" in capsys.readouterr().err
