"""The shipped packages never need Pillow (Phase K JK27).

taxfill-core depends on pydantic, pyyaml, pypdf and pypdfium2. Pillow reaches the dev environment only through
reportlab, a test dependency, so a test run never noticed that overlay._darkness turned its render into a Pillow image:
on a clean install verify_overlay raised ImportError on every Hawaii N-11 check (its painted ovals and minus boxes
are measured as ink). The ADR-0002 review found it; _darkness now reads the bitmap buffer.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SOURCES = sorted((REPO / "packages").glob("*/src/**/*.py"))


def test_no_shipped_module_imports_pillow():
    offenders = [
        str(path.relative_to(REPO)) for path in SOURCES
        if re.search(r"(?m)^\s*(?:import PIL|from PIL\b)|\.to_pil\(", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


class _NoPillow:
    def find_spec(self, name, path=None, target=None):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL' (blocked: a clean install has no Pillow)")
        return None


def test_hawaii_overlay_verifies_without_pillow(monkeypatch, tmp_path):
    from taxfill_core.fetch import FetchError, fetch_blank
    from taxfill_core.handfill import load_hand_fill_pack_for
    from taxfill_core.overlay import stamp_overlay, verify_overlay

    pack = load_hand_fill_pack_for("n11", 2025, "states/hi")
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except FetchError as exc:
        pytest.skip(f"cannot fetch the 2025 HI N-11 blank: {exc}")
    for name in [m for m in sys.modules if m == "PIL" or m.startswith("PIL.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_NoPillow(), *sys.meta_path])
    ovals = [ln for ln in pack.lines if ln.type == "checkbox" and any(b.mark == "fill" for b in (ln.boxes or []))]
    values = {ovals[0].line: True}
    result = stamp_overlay(blank, pack, values, tmp_path / "n11_2025.pdf")
    report = verify_overlay(pack, result.out_path, values)
    assert report.ok, [c.detail for c in report.checks if c.status != "PASS"]
