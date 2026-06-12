"""Page rendering to PNG via pypdfium2 — dev plan sections 3 and 10.

:func:`render_pdf` rasterizes PDF pages to PNG artifacts so the calling
agent can vision-review every page (the render+vision pass is what catches
the P-001 class of bugs: values clipped in comb cells are invisible in field
dumps and only show up on pixels). Default resolution is ~170 dpi per the
dev plan; scale factor = dpi / 72 (PDF canvas units are 1/72 inch).

PNG encoding is implemented with the standard library (zlib) so
``taxfill-core`` needs no imaging dependency at runtime; tests verify the
output bytes with Pillow, which is available in the dev environment only.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

import pypdfium2 as pdfium
from pydantic import BaseModel, ConfigDict, Field

# Dev plan section 10: render at ~170 dpi for the vision pass.
DEFAULT_DPI = 170

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# PNG color type by channel count: 1 -> grayscale, 3 -> truecolor, 4 -> truecolor+alpha.
_PNG_COLOR_TYPE = {1: 0, 3: 2, 4: 6}


class RenderedPage(BaseModel):
    """One rendered page: which page it is and where the PNG landed."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page number in the source PDF.")
    path: Path = Field(description="Path of the written PNG artifact.")
    width_px: int = Field(ge=1, description="PNG width in pixels.")
    height_px: int = Field(ge=1, description="PNG height in pixels.")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _write_png(path: Path, bitmap: pdfium.PdfBitmap) -> tuple[int, int]:
    """Encode a pypdfium2 bitmap (rendered with rev_byteorder=True) as a PNG file."""
    width, height, stride = bitmap.width, bitmap.height, bitmap.stride
    channels = bitmap.n_channels
    color_type = _PNG_COLOR_TYPE.get(channels)
    if color_type is None:  # defensive: render() below always requests RGB(A)
        raise RuntimeError(
            f"cannot encode a {channels}-channel bitmap as PNG — "
            f"render with rev_byteorder=True and an opaque fill color"
        )
    data = bytes(bitmap.buffer)
    row_bytes = width * channels
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # PNG filter type 0 (None) per scanline
        start = row * stride  # stride may exceed row_bytes (padding)
        raw += data[start : start + row_bytes]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    path.write_bytes(
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )
    return width, height


def _validate_pages(pages: Sequence[int] | None, n_pages: int, pdf_name: str) -> list[int]:
    if pages is None:
        return list(range(1, n_pages + 1))
    selected: list[int] = []
    for p in pages:
        if isinstance(p, bool) or not isinstance(p, int):
            raise ValueError(
                f"page numbers must be integers, got {p!r} — pass 1-based page "
                f"numbers like pages=[1, 2], or pages=None for all pages"
            )
        if not 1 <= p <= n_pages:
            raise ValueError(
                f"page {p} is out of range — '{pdf_name}' has {n_pages} page(s); "
                f"pass page numbers between 1 and {n_pages} (pages are 1-based)"
            )
        selected.append(p)
    if not selected:
        raise ValueError(
            "pages=[] selects nothing — pass at least one 1-based page number, "
            "or pages=None to render every page"
        )
    return selected


def _validate_crop(crop: Sequence[float]) -> tuple[float, float, float, float]:
    if len(crop) != 4:
        raise ValueError(
            f"crop must be a 4-tuple (x0, y0, x1, y1) in page points with the origin "
            f"at the bottom-left, got {tuple(crop)!r}"
        )
    try:
        x0, y0, x1, y1 = (float(v) for v in crop)
    except (TypeError, ValueError):
        raise ValueError(
            f"crop values must be numbers (page points), got {tuple(crop)!r} — "
            f"pass crop=(x0, y0, x1, y1) with the origin at the bottom-left"
        ) from None
    if not (x0 < x1 and y0 < y1):
        raise ValueError(
            f"crop (x0, y0, x1, y1) needs x0 < x1 and y0 < y1, got {tuple(crop)!r} — "
            f"coordinates are in page points with the origin at the bottom-left"
        )
    return x0, y0, x1, y1


def render_pdf(
    pdf_path: str | Path,
    out_dir: str | Path,
    *,
    pages: Sequence[int] | None = None,
    dpi: float = DEFAULT_DPI,
    crop: tuple[float, float, float, float] | None = None,
) -> list[RenderedPage]:
    """Render PDF pages to PNG files; returns one :class:`RenderedPage` per page.

    Args:
        pdf_path: the PDF to rasterize.
        out_dir: directory for the PNGs (created if missing). Files are named
            ``<pdf stem>_page<NNN>.png``; re-rendering the same page into the
            same directory overwrites the previous artifact.
        pages: 1-based page numbers to render, in the order given;
            ``None`` renders every page in document order.
        dpi: output resolution; the pixel scale factor is ``dpi / 72``.
            Default 170 per the dev plan's vision-review pass.
        crop: optional ``(x0, y0, x1, y1)`` rectangle in page points (origin
            bottom-left) applied to every rendered page — useful for zooming
            the vision pass onto a suspect region. Must lie within the page.

    Returns:
        Ordered list of :class:`RenderedPage` (page number, PNG path, pixel
        dimensions), matching the order of ``pages``.

    Raises:
        FileNotFoundError: ``pdf_path`` does not exist.
        ValueError: out-of-range/malformed page numbers, malformed crop,
            or non-positive dpi — every message says what to fix.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    if not pdf_path.is_file():
        raise FileNotFoundError(
            f"PDF not found at {pdf_path} — render the file fill_form wrote, "
            f"or fix the path"
        )
    if dpi <= 0:
        raise ValueError(
            f"dpi must be a positive number, got {dpi!r} — the project default "
            f"is {DEFAULT_DPI} (dev plan section 10)"
        )
    crop_rect = _validate_crop(crop) if crop is not None else None

    out_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72  # PDF canvas units are 1/72 inch

    if crop_rect is not None:
        x0, y0, x1, y1 = crop_rect
        if (x1 - x0) * scale < 1 or (y1 - y0) * scale < 1:
            # pdfium would fail with a misleading "Crop exceeds page dimensions".
            raise ValueError(
                f"crop {crop_rect} is {x1 - x0:g} x {y1 - y0:g} points — smaller than "
                f"one pixel at dpi {dpi:g}; widen the crop or raise dpi so the cropped "
                f"region is at least {72 / dpi:g} points on each side"
            )

    try:
        doc = pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as exc:
        # pdfium says "Failed to load document (PDFium: Data format error)."
        # with no next step; tell the agent what to do.
        raise ValueError(
            f"{pdf_path} could not be opened as a PDF ({exc}) — the file is corrupt "
            f"or not a PDF; re-create it (e.g. re-run fill_form) and render again"
        ) from exc
    try:
        try:
            # Draw form-field values (filled returns carry NeedAppearances;
            # pdfium's form layer regenerates the appearances at render time).
            doc.init_forms()
        except Exception:
            # No form layer available — page content still renders fine.
            pass
        n_pages = len(doc)
        selected = _validate_pages(pages, n_pages, pdf_path.name)

        results: list[RenderedPage] = []
        for p in selected:
            page = doc[p - 1]
            margins = (0.0, 0.0, 0.0, 0.0)
            if crop_rect is not None:
                x0, y0, x1, y1 = crop_rect
                page_w, page_h = page.get_size()
                if x0 < 0 or y0 < 0 or x1 > page_w + 1e-6 or y1 > page_h + 1e-6:
                    raise ValueError(
                        f"crop {crop_rect} falls outside page {p} "
                        f"({page_w:g} x {page_h:g} points) — keep "
                        f"0 <= x0 < x1 <= {page_w:g} and 0 <= y0 < y1 <= {page_h:g}"
                    )
                # pypdfium2 takes crop as margins to cut off: (left, bottom, right, top).
                margins = (x0, y0, page_w - x1, page_h - y1)
            bitmap = page.render(
                scale=scale,
                crop=margins,
                may_draw_forms=True,
                rev_byteorder=True,  # RGB byte order for the PNG encoder
            )
            png_path = out_dir / f"{pdf_path.stem}_page{p:03d}.png"
            width_px, height_px = _write_png(png_path, bitmap)
            results.append(
                RenderedPage(page=p, path=png_path, width_px=width_px, height_px=height_px)
            )
        return results
    finally:
        doc.close()
