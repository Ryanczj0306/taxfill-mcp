"""render_pdf tests (dev plan sections 3 and 10). Synthetic PDFs only.

PNG outputs are verified with Pillow (dev-only dependency, pulled in via
reportlab) — the renderer itself encodes PNGs with the standard library.
"""

from pathlib import Path

import pytest
from PIL import Image

from pdf_fixtures import make_acroform_pdf
from taxfill_core.filler import fill_form
from taxfill_core.render import DEFAULT_DPI, RenderedPage, render_pdf
from taxfill_core.schemas.formpack import FormPack

# US letter: 612 x 792 points (the fixture default page size).
LETTER_W, LETTER_H = 612, 792


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    """A two-page synthetic PDF with visible labels and form fields."""
    return make_acroform_pdf(
        tmp_path / "doc.pdf",
        [
            {"name": "root[0].Page1[0].f1_1[0]", "page": 1},
            {"name": "root[0].Page1[0].c1_1[0]", "kind": "checkbox", "page": 1, "on_value": "/1"},
            {"name": "root[0].Page2[0].f2_1[0]", "page": 2},
        ],
    )


def expected_px(points: float, dpi: float) -> int:
    return round(points * dpi / 72)


def test_renders_every_page_with_correct_dimensions(two_page_pdf: Path, tmp_path: Path):
    out_dir = tmp_path / "png"
    results = render_pdf(two_page_pdf, out_dir)

    assert [r.page for r in results] == [1, 2]  # ordered, 1-based
    for r in results:
        assert isinstance(r, RenderedPage)
        assert r.path.is_file()
        assert r.path.parent == out_dir
        # ~170 dpi letter: about 1445 x 1870 px — non-trivial dimensions.
        assert abs(r.width_px - expected_px(LETTER_W, DEFAULT_DPI)) <= 2
        assert abs(r.height_px - expected_px(LETTER_H, DEFAULT_DPI)) <= 2
        with Image.open(r.path) as img:
            assert img.format == "PNG"
            assert img.size == (r.width_px, r.height_px)
            # Pages carry drawn labels/fields: not a single flat color.
            assert len(img.convert("L").getcolors(maxcolors=4096) or []) > 1

    # Distinct artifact per page, named for traceability.
    names = {r.path.name for r in results}
    assert names == {"doc_page001.png", "doc_page002.png"}


def test_page_selection_renders_only_requested_pages(two_page_pdf: Path, tmp_path: Path):
    results = render_pdf(two_page_pdf, tmp_path / "png", pages=[2])
    assert [r.page for r in results] == [2]
    assert results[0].path.name == "doc_page002.png"
    assert not (tmp_path / "png" / "doc_page001.png").exists()


def test_page_order_is_caller_order(two_page_pdf: Path, tmp_path: Path):
    results = render_pdf(two_page_pdf, tmp_path / "png", pages=[2, 1])
    assert [r.page for r in results] == [2, 1]


def test_dpi_scales_dimensions(two_page_pdf: Path, tmp_path: Path):
    results = render_pdf(two_page_pdf, tmp_path / "png", pages=[1], dpi=72)
    assert results[0].width_px == LETTER_W  # scale = 72/72 = 1
    assert results[0].height_px == LETTER_H


def test_crop_changes_dimensions(two_page_pdf: Path, tmp_path: Path):
    full = render_pdf(two_page_pdf, tmp_path / "full", pages=[1])[0]
    # Bottom-left quarter of the page in page coordinates.
    quarter = render_pdf(
        two_page_pdf, tmp_path / "crop", pages=[1], crop=(0, 0, LETTER_W / 2, LETTER_H / 2)
    )[0]
    assert quarter.width_px < full.width_px
    assert quarter.height_px < full.height_px
    assert abs(quarter.width_px - expected_px(LETTER_W / 2, DEFAULT_DPI)) <= 2
    assert abs(quarter.height_px - expected_px(LETTER_H / 2, DEFAULT_DPI)) <= 2
    with Image.open(quarter.path) as img:
        assert img.size == (quarter.width_px, quarter.height_px)


def dark_pixel_count(png_path: Path) -> int:
    with Image.open(png_path) as img:
        return sum(img.convert("L").histogram()[:128])  # pixels darker than mid-gray


def test_filled_values_appear_on_rendered_pixels(tmp_path: Path):
    """The render+vision pass exists to make filled values VISIBLE (P-001):
    a value present in the field dump but absent from pixels is exactly the
    bug class this module must expose. Render the field rects of a blank vs
    a filled form and require ink to appear."""
    root = "r[0]"
    blank = make_acroform_pdf(
        tmp_path / "blank.pdf",
        [
            {"name": f"{root}.f1[0]", "x": 220, "y": 700, "width": 144, "height": 18},
            {"name": f"{root}.c1[0]", "kind": "checkbox", "x": 220, "y": 660, "on_value": "/1"},
        ],
    )
    pack = FormPack.model_validate(
        {
            "form": "TEST-R",
            "jurisdiction": "federal",
            "tax_year": 2023,
            "source_url": "https://www.irs.gov/pub/irs-pdf/testr.pdf",
            "pdf_sha256": "...",
            "acroform_root": root,
            "fields": [
                {"line": "t", "field": "f1[0]", "type": "text"},
                {"line": "c", "field": "c1[0]", "type": "checkbox", "on_state": "/1"},
            ],
        }
    )
    filled = tmp_path / "filled.pdf"
    fill_form(pack, {"t": "HELLO 12345", "c": "yes"}, blank, filled)

    crops = {"text": (220, 700, 364, 718), "box": (220, 660, 234, 674)}
    for name, crop in crops.items():
        before = render_pdf(blank, tmp_path / f"blank_{name}", pages=[1], crop=crop)[0]
        after = render_pdf(filled, tmp_path / f"filled_{name}", pages=[1], crop=crop)[0]
        assert (before.width_px, before.height_px) == (after.width_px, after.height_px)
        # Filled regions must gain dark pixels (text glyphs / the check mark).
        assert dark_pixel_count(after.path) > dark_pixel_count(before.path), (
            f"{name}: filled render shows no new ink — form values are not being drawn"
        )


# --- prescriptive errors ------------------------------------------------------


def test_out_of_range_page_says_valid_range(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"page 5 is out of range.*between 1 and 2"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[1, 5])


def test_page_zero_is_rejected_pages_are_one_based(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"pages are 1-based"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[0])


def test_non_integer_page_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"page numbers must be integers"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[1.5])


def test_empty_page_list_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"pages=\[\] selects nothing"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[])


def test_inverted_crop_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"x0 < x1 and y0 < y1"):
        render_pdf(two_page_pdf, tmp_path / "png", crop=(300, 100, 200, 400))


def test_crop_outside_page_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"falls outside page 1"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[1], crop=(0, 0, 9999, 100))


def test_wrong_crop_arity_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"4-tuple \(x0, y0, x1, y1\)"):
        render_pdf(two_page_pdf, tmp_path / "png", crop=(0, 0, 100))


def test_non_numeric_crop_is_rejected(two_page_pdf: Path, tmp_path: Path):
    # Regression: a raw "could not convert string to float" leaked out before.
    with pytest.raises(ValueError, match=r"crop values must be numbers"):
        render_pdf(two_page_pdf, tmp_path / "png", crop=(0, 0, "wide", 100))


def test_missing_pdf_is_prescriptive(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"PDF not found"):
        render_pdf(tmp_path / "ghost.pdf", tmp_path / "png")


def test_non_positive_dpi_is_rejected(two_page_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match=r"dpi must be a positive number"):
        render_pdf(two_page_pdf, tmp_path / "png", dpi=0)


def test_subpixel_crop_is_rejected_prescriptively(two_page_pdf: Path, tmp_path: Path):
    # Regression: pdfium failed with the misleading 'Crop exceeds page
    # dimensions' when the cropped region rounded to zero pixels.
    with pytest.raises(ValueError, match=r"smaller than one pixel.*widen the crop"):
        render_pdf(two_page_pdf, tmp_path / "png", pages=[1], crop=(0, 0, 0.1, 0.1))


def test_corrupt_pdf_says_recreate(tmp_path: Path):
    # Regression: pdfium's 'Failed to load document' gave the agent no next step.
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"%PDF-1.7 truncated garbage")
    with pytest.raises(ValueError, match=r"could not be opened as a PDF.*re-run fill_form"):
        render_pdf(bad, tmp_path / "png")
