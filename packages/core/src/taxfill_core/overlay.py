"""Overlay filler for print-only forms — the ROADMAP C3 "positioned overlay filler".

A print-only blank (CT-1040, HI N-11, NM PIT-1, SC1040) has no AcroForm widgets, so the
AcroForm filler has nothing to write into. It DOES have a text layer, and its printed
entry boxes sit at fixed positions. This module stamps the hand-fill worksheet's values
onto those positions:

1. :func:`stamp_overlay` computes the worksheet EXACTLY as
   :func:`taxfill_core.handfill.hand_fill_worksheet` does (it calls it — the evaluator is
   not forked), then for every line whose manifest entry carries ``overlay`` coordinates
   it draws the rendered value onto the page with the base-14 Helvetica font (a bare
   ``/Type1`` font resource — nothing is embedded) and merges one overlay page per touched
   page onto the blank with pypdf. Lines WITHOUT coordinates come back in
   ``hand_written_lines`` so the worksheet stays complete.
2. :func:`verify_overlay` is the mandatory gate's OVERLAY verdict: there are no AcroForm
   fields to diff, so it recomputes the worksheet from the pack + values and reads, from the
   stamped PDF's text layer (pypdfium2), exactly the glyphs drawn in the stamp font inside
   each line's DECLARED box — they must equal the value, and a blank line's box must hold
   none. See the function docstring for exactly what that does and does not prove.
3. :func:`locate_labels` is the AUTHORING helper (``taxfill locate``): it reads the printed
   positions of line-number labels straight out of the blank's text layer, so coordinates
   are anchored to the form instead of guessed — the ROADMAP's "OCR-positioned" idea with
   no OCR and no new dependency.

Coordinate frame (binding, see formpacks/CONVENTIONS.md): PDF points in the page's USER
SPACE, origin bottom-left — the frame a content stream's ``x y Td`` uses. pdfium's char
boxes are already in that frame (verified: a label drawn at ``100 700 Td`` locates at
left 100.7 / bottom 700.0), and they stay in the unrotated user space on a ``/Rotate``
page, so ``locate`` output and stamping never disagree about the frame.

Zero new dependencies: pypdf (write) and pypdfium2 (read) only — both already required.
"""
from __future__ import annotations

import ctypes
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PageObject, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, RectangleObject

from taxfill_core.handfill import (
    Worksheet,
    WorksheetLine,
    WorksheetSource,
    hand_fill_worksheet,
    worksheet_money_values,
)
from taxfill_core.knowledge import assert_filing_grade
from taxfill_core.redact import redact
from taxfill_core.schemas.handfill import (
    DEFAULT_MONEY_ALIGN,
    DEFAULT_OVERLAY_FONT_SIZE,
    HandFillLine,
    HandFillPack,
    OverlayBox,
)
from taxfill_core.verify import FAIL, PASS, RecomputeCheck, Status, independent_recompute

__all__ = [
    "MIN_FONT_SIZE",
    "Box",
    "OverlayCheck",
    "OverlayResult",
    "OverlayVerifyReport",
    "StampedLine",
    "efile_only_refusal",
    "locate_labels",
    "page_geometry",
    "stamp_overlay",
    "text_width",
    "verify_overlay",
]

#: Smallest point size shrink-to-fit will go to before it gives up and warns only.
MIN_FONT_SIZE = 6.0

_FONT_KEY = "/F1"
_BASE_FONT = "/Helvetica"
# WinAnsi so accented Latin-1 letters in a name stamp as themselves; the base-14
# Helvetica has glyphs for the whole WinAnsi set, and cp1252 IS WinAnsiEncoding.
_ENCODING = "/WinAnsiEncoding"
_CODEC = "cp1252"

StampAlign = Literal["left", "right", "center", "comb", "cells"]

# Helvetica advance widths in 1/1000 em for printable ASCII — copied from the Adobe Core
# 14 AFM (Helvetica.afm) as shipped in pypdf 6.13's ``_codecs/core_font_metrics.py``, and
# cross-checked against it by test_overlay.py whenever the installed pypdf exposes that
# (private) module. It is the fallback for a pypdf that does not; digits (556) are the
# widths that matter for right-aligned money.
_HELVETICA_WIDTHS_COMPACT: dict[str, int] = {
    ' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667, "'": 191,
    '(': 333, ')': 333, '*': 389, '+': 584, ',': 278, '-': 333, '.': 278, '/': 278,
    '0': 556, '1': 556, '2': 556, '3': 556, '4': 556, '5': 556, '6': 556, '7': 556,
    '8': 556, '9': 556, ':': 278, ';': 278, '<': 584, '=': 584, '>': 584, '?': 556,
    '@': 1015, 'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778,
    'H': 722, 'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778,
    'P': 667, 'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944,
    'X': 667, 'Y': 667, 'Z': 611, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556,
    '`': 333, 'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278, 'g': 556,
    'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556, 'o': 556,
    'p': 556, 'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556, 'v': 500, 'w': 722,
    'x': 500, 'y': 500, 'z': 500, '{': 334, '|': 260, '}': 334, '~': 584,
}
# The AFM table's own default (pypdf uses the same figure): a digit-width guess for any
# character outside the table, conservative for money.
_HELVETICA_DEFAULT_WIDTH = 556


def _helvetica_widths() -> tuple[Mapping[str, int], int, str]:
    """``(widths, default, provenance)`` — pypdf's Core-14 AFM table when the installed
    pypdf exposes it (a private module, present from pypdf 6.x), else the compact copy."""
    try:
        from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS  # type: ignore[import-not-found]

        widths = CORE_FONT_METRICS["Helvetica"].character_widths
        return widths, int(widths.get("default", _HELVETICA_DEFAULT_WIDTH)), "pypdf"
    except Exception:  # ImportError, KeyError, AttributeError on an older/newer pypdf
        return _HELVETICA_WIDTHS_COMPACT, _HELVETICA_DEFAULT_WIDTH, "compact"


def text_width(text: str, font_size: float) -> float:
    """Advance width of ``text`` set in Helvetica at ``font_size`` points (AFM metrics)."""
    widths, default, _ = _helvetica_widths()
    return sum(widths.get(ch, default) for ch in text) / 1000.0 * font_size


# ── result models ────────────────────────────────────────────────────────────


class StampedLine(BaseModel):
    """One value drawn onto the blank: what, where, and how large."""

    model_config = ConfigDict(extra="forbid")

    line: str
    label: str
    type: str
    value: str = Field(description="The text actually stamped (comb lines: separators dropped; checkbox: 'X').")
    source: WorksheetSource
    page: int = Field(ge=1)
    x: float = Field(description="Left edge of the stamped text, PDF points (user space, origin bottom-left).")
    y: float = Field(description="Baseline of the stamped text, PDF points.")
    font_size: float
    align: StampAlign


class OverlayResult(BaseModel):
    """What :func:`stamp_overlay` produced — the overlay counterpart of ``FillResult``."""

    model_config = ConfigDict(extra="forbid")

    out_path: str
    form: str
    jurisdiction: str
    tax_year: int
    page_count: int = Field(description="Pages in the blank (every overlay page number was checked against it).")
    stamped_lines: list[StampedLine]
    hand_written_lines: list[WorksheetLine] = Field(
        description="Worksheet lines with a value but NO coordinates — the filer still hand-writes these."
    )
    blank_lines: list[str] = Field(description="Line ids with nothing to write (blank value), coordinates or not.")
    warnings: list[str] = Field(default_factory=list)
    printing_guidance: list[str] = Field(
        default_factory=list,
        description="The agency's own printing rules for this paper form, verbatim with their source (JS4b).",
    )
    instructions: str = (
        "The stamped PDF is a review draft: render_form every page and vision-check that each "
        "stamped value sits in its printed box (verify_form gives the text-layer OVERLAY verdict, "
        "which cannot see the printed art). Hand-write every hand_written_lines value onto the "
        "printed pages, then sign and date in ink before mailing."
    )


class OverlayCheck(BaseModel):
    """One stamped value looked up in the output PDF's text layer at its declared box."""

    model_config = ConfigDict(extra="forbid")

    line: str
    label: str
    value: str
    page: int
    status: Status
    detail: str


class OverlayVerifyReport(BaseModel):
    """The OVERLAY verdict of ``verify_form`` for a stamped print-only form."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["OVERLAY"] = "OVERLAY"
    ok: bool
    form_keys: list[str]
    pdf_path: str
    page_count: int
    checks: list[OverlayCheck]
    recompute: list[RecomputeCheck] = Field(
        default_factory=list,
        description="independent_recompute of the worksheet's money lines against caller-supplied calc results.",
    )
    hand_written_lines: list[WorksheetLine] = Field(
        description="Lines without coordinates — nothing on the PDF to check; the filer hand-writes them."
    )
    limits: list[str]


#: What the OVERLAY verdict does NOT prove — returned on every report so no agent reads
#: ``ok: true`` as more than it is.
OVERLAY_VERDICT_LIMITS: list[str] = [
    "Proves that the glyphs drawn in the stamp font (unembedded base-14 Helvetica) inside each "
    "line's DECLARED box spell exactly that line's value, and that a blank line's "
    "box holds none. It cannot see the printed art, so a value stamped over shading, a pre-printed "
    "'00' or a wrong (but plausible) box still passes — render_form + vision review remains mandatory.",
    "Checks against the PACK's coordinates. Wrong coordinates (the box of a different line) "
    "verify clean; only 'taxfill locate' anchoring and the rendered vision check catch them.",
    "A blank that prints its OWN text in unembedded Helvetica inside a declared box reads as "
    "stamped and FAILs (the safe direction) — narrow that box. The CT, HI and SC blanks embed "
    "every font they print.",
    "Lines without coordinates (hand_written_lines) are not on the PDF and are not checked.",
]


class Box(BaseModel):
    """A located text run on a blank page — PDF points, user space, origin bottom-left."""

    model_config = ConfigDict(extra="forbid")

    text: str
    page: int = Field(ge=1)
    x0: float = Field(description="left")
    y0: float = Field(description="bottom (the baseline for glyphs without descenders)")
    x1: float = Field(description="right")
    y1: float = Field(description="top")


# ── content-stream helpers ───────────────────────────────────────────────────


def _num(v: float) -> bytes:
    """A PDF numeric operand: fixed-point, no exponent, no trailing zeros, no '-0'."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    if s in ("", "-0", "-"):
        s = "0"
    return s.encode("ascii")


def _pdf_string(text: str) -> tuple[bytes, str | None]:
    """Encode ``text`` as a WinAnsi PDF literal string; returns (bytes, warning-or-None)."""
    warning = None
    try:
        raw = text.encode(_CODEC)
    except UnicodeEncodeError:
        cleaned = text.encode(_CODEC, errors="replace").decode(_CODEC)
        warning = (
            f"characters outside WinAnsi replaced with '?' ({redact(text)!r} -> {redact(cleaned)!r}); "
            f"the base-14 Helvetica font cannot draw them — transliterate the value and re-stamp"
        )
        raw = cleaned.encode(_CODEC)
    out = bytearray()
    for b in raw:
        if b in (0x28, 0x29, 0x5C):  # ( ) \
            out += b"\\" + bytes([b])
        elif b == 0x0D:
            out += b"\\r"
        elif b == 0x0A:
            out += b"\\n"
        else:
            out.append(b)
    return b"(" + bytes(out) + b")", warning


def _text_op(x: float, y: float, size: float, text: str) -> tuple[bytes, str | None]:
    literal, warning = _pdf_string(text)
    return (
        b"BT " + _FONT_KEY.encode() + b" " + _num(size) + b" Tf " + _num(x) + b" " + _num(y) + b" Td "
        + literal + b" Tj ET\n"
    ), warning


# Bezier constant for a quarter circle.
_KAPPA = 0.5522847498


def _fill_op(kind: str, x: float, y: float, w: float, h: float) -> bytes:
    """A solid black shape filling (x, y, w, h) as content-stream operators (JS4d).

    ``"rect"`` is the rectangle itself; ``"oval"`` is the oval a scannable form prints — straight sides with round
    ends of radius min(w, h) / 2, so a circle when w == h — which fills the printed oval to its edge where an
    inscribed ellipse would leave its four shoulders unpainted.
    """
    if kind == "rect":
        return b"q 0 g " + b" ".join(_num(v) for v in (x, y, w, h)) + b" re f Q\n"
    r = min(w, h) / 2
    k = r * _KAPPA
    x1, y1 = x + w, y + h
    pts = [
        (b"m", (x + r, y)),
        (b"l", (x1 - r, y)),
        (b"c", (x1 - r + k, y, x1, y + r - k, x1, y + r)),
        (b"l", (x1, y1 - r)),
        (b"c", (x1, y1 - r + k, x1 - r + k, y1, x1 - r, y1)),
        (b"l", (x + r, y1)),
        (b"c", (x + r - k, y1, x, y1 - r + k, x, y1 - r)),
        (b"l", (x, y + r)),
        (b"c", (x, y + r - k, x + r - k, y, x + r, y)),
    ]
    return b"q 0 g " + b" ".join(b" ".join(_num(v) for v in args) + b" " + op for op, args in pts) + b" h f Q\n"


def _mark_rect(box: OverlayBox) -> tuple[float, float, float, float]:
    """The area a 'fill' mark paints: the declared box itself (x, bottom y, w, h)."""
    return box.x, box.y, box.w, float(box.h or 0)


def _overlay_page(base: PageObject, content: bytes) -> PageObject:
    """A one-off page carrying ``content`` + the Helvetica resource, sized to ``base``'s MediaBox.

    pypdf's ``merge_page`` clips the merged content to the OVERLAY page's MediaBox and
    renames a colliding ``/F1`` resource on the base page, so the overlay must share the
    base MediaBox exactly (an offset or oversized base box would otherwise clip stamps).
    """
    mb = base.mediabox
    overlay = PageObject.create_blank_page(width=float(mb.width), height=float(mb.height))
    overlay[NameObject("/MediaBox")] = RectangleObject(
        [float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)]
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject(_BASE_FONT),
            NameObject("/Encoding"): NameObject(_ENCODING),
        }
    )
    overlay[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject(_FONT_KEY): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(content)
    overlay[NameObject("/Contents")] = stream
    return overlay


# ── layout ───────────────────────────────────────────────────────────────────


class _Segment(BaseModel):
    """One ``Tj`` run: text at (x, baseline y) in ``size`` points."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    size: float
    text: str

    @property
    def width(self) -> float:
        return text_width(self.text, self.size)


_COMB_SEPARATORS = re.compile(r"[\s\-]")
# Uneven cells (JS4c) sit around the form's OWN separators — the printed dashes of an SSN, the
# dashes of an MM-DD-YYYY date, a pre-printed decimal point — so every separator is dropped.
_CELL_SEPARATORS = re.compile(r"[\s\-/.]")


def _stamp_text(ln: HandFillLine, value: str, box: OverlayBox | None = None) -> str:
    """The characters that go on the page for a worksheet value, in ``box`` (default: the line's first)."""
    if ln.type == "checkbox":
        return "X"
    box = box if box is not None else (ln.boxes[0] if ln.boxes else None)
    if ln.type == "money" and box is not None and box.minus is not None:
        value = value.lstrip("-")  # the loss is shown by shading the minus box, not by a sign
    if box is not None and box.cells is not None:
        if ln.type == "money":
            # digit boxes print their own grouping; a loss is shown by the minus box, never by a cell
            return _CELL_SEPARATORS.sub("", value.replace(",", "").lstrip("-"))
        return _CELL_SEPARATORS.sub("", value)
    if box is not None and box.comb is not None:
        # A comb has one cell per character and no cell for a separator: writing the
        # dash of '123-45-6789' into a digit cell is the P-001 clipping class.
        return _COMB_SEPARATORS.sub("", value)
    return value


def _layout(
    ln: HandFillLine, box: OverlayBox, pack: HandFillPack, value: str
) -> tuple[list[_Segment], float, StampAlign, list[str]]:
    """Place ``value`` in ``box``; returns (segments, font_size, align, warnings). Deterministic
    in (pack, value) so :func:`verify_overlay` can rebuild the exact region to inspect."""
    defaults = pack.overlay_defaults
    size = box.font_size or (defaults.font_size if defaults else DEFAULT_OVERLAY_FONT_SIZE)
    money_align = defaults.money_align if defaults else DEFAULT_MONEY_ALIGN
    floor = max(MIN_FONT_SIZE, pack.min_font_size or 0.0)  # the agency's published minimum, when it sets one
    warnings: list[str] = []
    text = _stamp_text(ln, value, box)
    who = f"line '{ln.line}' ({ln.label!r}) on page {box.page}"

    if box.cells is not None:
        cells, cw = box.cells, box.cell_w
        if len(text) > len(cells):
            warnings.append(
                f"{who}: {redact(text)!r} has {len(text)} characters but the box has {len(cells)} cells — the extra "
                f"characters are stamped past the last cell, NOT clipped; check the value's format against the "
                f"printed cells"
            )
        widest = max((text_width(ch, size) for ch in text), default=0.0)
        if widest > cw:
            shrunk = max(floor, size * cw / widest)
            warnings.append(f"{who}: a {size:g}pt glyph is wider than the {cw:g}pt cell — font shrunk to {shrunk:.1f}pt")
            size = shrunk
        lefts = list(cells) + [cells[-1] + cw * (k + 1) for k in range(max(0, len(text) - len(cells)))]
        right = box.align == "right" or (box.align is None and ln.type == "money" and money_align == "right")
        if right and len(text) <= len(cells):
            lefts = lefts[len(cells) - len(text):]  # a number fills the LAST cells, ones digit in the last one
        segments = [
            _Segment(x=lefts[i] + (cw - text_width(ch, size)) / 2, y=box.y, size=size, text=ch)
            for i, ch in enumerate(text)
        ]
        return segments, size, "cells", warnings

    if box.comb is not None:
        pitch = box.comb
        cells = int(math.floor(box.w / pitch + 1e-6))
        if len(text) > cells:
            warnings.append(
                f"{who}: comb value {redact(text)!r} has {len(text)} characters but the box holds "
                f"{cells} cells of {pitch:g}pt in w={box.w:g}pt — the extra characters are stamped "
                f"past the box edge, NOT clipped; shorten the value or fix the pack's w/comb"
            )
        widest = max((text_width(ch, size) for ch in text), default=0.0)
        if widest > pitch:
            shrunk = max(floor, size * pitch / widest)
            warnings.append(
                f"{who}: a {size:g}pt glyph is wider than the {pitch:g}pt comb cell — font shrunk to {shrunk:.1f}pt"
            )
            size = shrunk
        segments = [
            _Segment(x=box.x + i * pitch + (pitch - text_width(ch, size)) / 2, y=box.y, size=size, text=ch)
            for i, ch in enumerate(text)
        ]
        return segments, size, "comb", warnings

    width = text_width(text, size)
    if width > box.w + 1e-9:
        shrunk = max(floor, size * box.w / width)
        if shrunk < size:
            warnings.append(
                f"{who}: {redact(text)!r} is {width:.1f}pt wide at {size:g}pt but the box is {box.w:g}pt — "
                f"font shrunk to {shrunk:.1f}pt to fit"
            )
            size = shrunk
            width = text_width(text, size)
        if width > box.w + 1e-9:
            warnings.append(
                f"{who}: {redact(text)!r} still overflows the {box.w:g}pt box by {width - box.w:.1f}pt at the "
                f"{floor:g}pt floor — it is stamped in full (never clipped) and WILL spill past the "
                f"box; abbreviate the value or widen w in the pack"
            )

    if ln.type == "checkbox":
        align: StampAlign = box.align or "center"
    elif ln.type == "money":
        align = box.align or money_align
    else:
        align = box.align or "left"
    if align == "right":
        x = box.x + box.w - width
    elif align == "center":
        x = box.x + (box.w - width) / 2
    else:
        x = box.x
    return [_Segment(x=x, y=box.y, size=size, text=text)], size, align, warnings


# ── stamping ─────────────────────────────────────────────────────────────────


def efile_only_refusal(pack: HandFillPack) -> str:
    """Why an e-file-only manifest (the FBAR) has no blank to fetch, print or stamp (JS4b)."""
    return (
        f"{pack.form} ({pack.tax_year}) is filed ELECTRONICALLY ONLY — FinCEN Form 114 goes through FinCEN's BSA "
        f"E-Filing System (https://bsaefiling.fincen.treas.gov/main.html), and a printed copy is not accepted. Its "
        f"source_url is FinCEN's line-item filing instructions, not a blank, so there is nothing to fetch, print or "
        f"stamp: call hand_fill_worksheet for the value-gathering sheet and enter those values in the BSA E-Filing System"
    )


def _form_pages(blank: Path, pack: HandFillPack) -> PdfWriter:
    """A writer holding only the pack's ``source_pages`` of ``blank``, in the pack's order.

    An agency may publish the blank only inside a booklet or packet (NM's 2025 PIT-1 is pages 57-58 of the
    PIT packet). The stamped output is then just the form, so the manifest's page numbers count within it and
    the filer prints nothing else (Phase J JS5).
    """
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(blank))
    if reader.is_encrypted:
        # WV's booklet is AES-encrypted with an empty user password (change and annotation "disallowed"):
        # the pages read and copy; the stamped output is a plain PDF.
        reader.decrypt("")
    total = len(reader.pages)
    beyond = [p for p in (pack.source_pages or []) if p > total]
    if beyond:
        raise ValueError(
            f"{blank.name} has {total} page(s) but the {pack.form} {pack.tax_year} hand-fill pack names source "
            f"page(s) {beyond} — the agency re-paginated its booklet, or the pack's source_pages are wrong; re-read "
            f"the booklet and fix source_pages (and re-pin pdf_sha256 if the file changed)"
        )
    writer = PdfWriter()
    for page_no in pack.source_pages or []:
        writer.add_page(reader.pages[page_no - 1])
    return writer


def _check_pages(pack: HandFillPack, n_pages: int, blank_name: str) -> None:
    bad = [(ln.line, box.page) for ln in pack.overlay_lines for box in ln.boxes if box.page > n_pages]
    if bad:
        shown = ", ".join(f"'{line}' -> page {page}" for line, page in bad[:8])
        raise ValueError(
            f"{blank_name} has {n_pages} page(s) but the {pack.form} {pack.tax_year} hand-fill pack places "
            f"{len(bad)} line(s) beyond it ({shown}{', ...' if len(bad) > 8 else ''}) — overlay.page is 1-based; "
            f"fix the pack's coordinates (re-run 'taxfill locate' on this blank) or re-fetch the blank from "
            f"{pack.source_url} if a revision changed its page count"
        )


def stamp_overlay(
    blank_pdf_path: str | Path,
    pack: HandFillPack,
    values: Mapping[str, object] | None,
    out_path: str | Path,
) -> OverlayResult:
    """Stamp the hand-fill worksheet's values onto the print blank; write ``out_path``.

    Args:
        blank_pdf_path: the official print-only blank (fetched and checksum-verified upstream).
        pack: the hand-fill manifest; at least one line must carry ``overlay`` coordinates.
        values: line id -> entered value, exactly as for :func:`hand_fill_worksheet`
            (money number-like, text str, checkbox yes/no). Unknown line ids are refused —
            a typo would otherwise vanish silently instead of landing on the page.
        out_path: where to write the stamped PDF (parents are created).

    Returns:
        :class:`OverlayResult`: ``stamped_lines`` (value, page, position, size),
        ``hand_written_lines`` (values with no coordinates — the worksheet remainder),
        ``blank_lines``, ``page_count`` and ``warnings`` (font shrunk to fit, overflow at the
        6pt floor, comb overflow, non-WinAnsi characters). Nothing is ever clipped silently.

    Raises:
        ValueError: no coordinates in the pack, unknown line ids, an overlay page beyond the
            blank's page count (checked HERE, at fill time — the blank may not be cached when
            the pack loads), or an unparsable blank. Every message says what to do next.
        FileNotFoundError: ``blank_pdf_path`` does not exist.
        ProvisionalPackError: the year's knowledge pack is planning-only (same rule as fill_form).
    """
    assert_filing_grade(pack.jurisdiction, pack.tax_year, action="fill a form")
    blank = Path(blank_pdf_path)
    out = Path(out_path)
    values = dict(values or {})

    if pack.efile_only:
        raise ValueError(efile_only_refusal(pack))
    if not pack.has_overlay_coordinates:
        raise ValueError(
            f"the {pack.form} {pack.tax_year} ({pack.jurisdiction}) hand-fill pack carries no overlay "
            f"coordinates, so there is nothing to stamp — use hand_fill_worksheet for the line->value "
            f"worksheet and hand-write it onto the printed blank, or author 'overlay:' blocks from "
            f"'taxfill locate' anchors (formpacks/CONVENTIONS.md, hand-fill section)"
        )
    by_line = {ln.line: ln for ln in pack.lines}
    unknown = sorted(k for k in values if k not in by_line)
    if unknown:
        raise ValueError(
            f"unknown line key(s) {unknown} for form {pack.form} ({pack.tax_year}) — valid line ids: "
            f"{sorted(by_line)}; fix the key(s) or add the line to the hand-fill pack"
        )
    if not blank.is_file():
        raise FileNotFoundError(
            f"blank PDF not found at {blank} — download it first from the pack's source_url "
            f"({pack.source_url}) via fetch_blank and pass that path"
        )

    worksheet = hand_fill_worksheet(pack, values)

    try:
        writer = _form_pages(blank, pack) if pack.source_pages else PdfWriter(clone_from=str(blank))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"{blank} could not be parsed as a PDF ({exc}) — the download is corrupt or not a PDF; "
            f"re-fetch the blank from the pack's source_url ({pack.source_url}) via fetch_blank and retry"
        ) from exc
    n_pages = len(writer.pages)
    _check_pages(pack, n_pages, blank.name)

    warnings: list[str] = []
    stamped: list[StampedLine] = []
    hand_written: list[WorksheetLine] = []
    blank_lines: list[str] = []
    per_page: dict[int, bytearray] = {}

    for wl in worksheet.lines:
        ln = by_line[wl.line]
        if wl.value == "":
            blank_lines.append(wl.line)
            continue
        if not ln.boxes:
            hand_written.append(wl)
            continue
        for box in ln.boxes:  # one placement per box: a header SSN repeats on every page
            chunk = per_page.setdefault(box.page, bytearray())
            if ln.type == "checkbox" and box.mark == "fill":
                chunk += _fill_op("oval", *_mark_rect(box))  # 'Fill in ovals completely' (HI N-11)
                stamped.append(StampedLine(
                    line=wl.line, label=wl.label, type=wl.type, value="(filled)", source=wl.source, page=box.page,
                    x=round(box.x, 3), y=round(box.y, 3), font_size=0.0, align="center",
                ))
                continue
            negative = ln.type == "money" and wl.value.startswith("-")
            if negative and (box.cells is not None or box.comb is not None) and box.minus is None:
                kind = "digit cells" if box.cells is not None else "a comb"
                raise ValueError(
                    f"line '{ln.line}' is a loss ({redact(wl.value)}) but its box on page {box.page} is {kind} with "
                    f"no minus box — the sign would silently vanish; add overlay.minus (the printed box the form "
                    f"shades for a loss) to the pack, or hand-write this line"
                )
            if negative and box.minus is not None:
                m = box.minus
                chunk += _fill_op("rect", m.x, m.y, m.w, m.h)
            segments, size, align, warns = _layout(ln, box, pack, wl.value)
            warnings.extend(warns)
            for seg in segments:
                op, enc_warning = _text_op(seg.x, seg.y, seg.size, seg.text)
                if enc_warning:
                    warnings.append(f"line '{ln.line}' on page {box.page}: {enc_warning}")
                chunk += op
            stamped.append(
                StampedLine(
                    line=wl.line, label=wl.label, type=wl.type, value=_stamp_text(ln, wl.value, box),
                    source=wl.source, page=box.page, x=round(segments[0].x, 3), y=round(box.y, 3),
                    font_size=round(size, 3), align=align,
                )
            )

    for page_no, content in sorted(per_page.items()):
        base = writer.pages[page_no - 1]
        base.merge_page(_overlay_page(base, bytes(content)))

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        writer.write(fh)
    return OverlayResult(
        out_path=str(out), form=pack.form, jurisdiction=pack.jurisdiction, tax_year=pack.tax_year,
        page_count=n_pages, stamped_lines=stamped, hand_written_lines=hand_written,
        blank_lines=blank_lines, warnings=warnings,
        printing_guidance=[f"{r.source}: \"{r.quote}\"" for r in pack.printing_guidance],
    )


# ── the OVERLAY verdict ──────────────────────────────────────────────────────


def _open_pdfium(pdf_path: Path, what: str) -> pdfium.PdfDocument:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"no PDF at {pdf_path} — {what}")
    try:
        return pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as exc:
        raise ValueError(f"{pdf_path} could not be opened as a PDF ({exc}) — {what}") from exc


_WS = re.compile(r"\s+")
# The stamp font's base name as pdfium reports it; stamps are never embedded (see _overlay_page).
_STAMP_BASE_FONT = _BASE_FONT.lstrip("/")
# A glyph belongs to a box when its char-box centre lies inside the box's text band: the
# declared x..x+w, and from a descender below the baseline to the cap height above it.
_DESCENT_RATIO = 0.3


def _stamped_glyphs(tp: pdfium.PdfTextPage) -> list[tuple[float, float, float, str]]:
    """``(centre_x, centre_y, font_size, char)`` for every glyph on the page drawn in the stamp font.

    The stamp font is unembedded base-14 Helvetica (:func:`_overlay_page`); a blank's own text
    uses embedded fonts, so the font — not the text — separates what was stamped from what was
    printed (PJ-01: a substring search over mixed text let '14,000' verify as '4,000').
    Characters pdfium generates (inter-word spaces, line breaks) carry no text object and are
    skipped.
    """
    out: list[tuple[float, float, float, str]] = []
    buf = ctypes.create_string_buffer(128)
    for i in range(tp.count_chars()):
        obj = pdfium_c.FPDFText_GetTextObject(tp.raw, i)
        if not obj:
            continue
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        if not font or pdfium_c.FPDFFont_GetIsEmbedded(font):
            continue
        pdfium_c.FPDFFont_GetBaseFontName(font, buf, len(buf))
        if buf.value.decode("latin-1", "replace") != _STAMP_BASE_FONT:
            continue
        ch = chr(pdfium_c.FPDFText_GetUnicode(tp.raw, i))
        if not ch.strip():
            continue
        left, bottom, right, top = tp.get_charbox(i)
        out.append(((left + right) / 2, (bottom + top) / 2, float(pdfium_c.FPDFText_GetFontSize(tp.raw, i)), ch))
    return out


def _in_box(glyphs: Sequence[tuple[float, float, float, str]], box: OverlayBox, size: float) -> str:
    """The stamped characters inside ``box``'s text band, left to right (the declared box, never the value's)."""
    left, right = box.x - 1.0, box.x + box.w + 1.0
    bottom, top = box.y - _DESCENT_RATIO * size, box.y + size
    return "".join(ch for _, ch in sorted((x, ch) for x, y, _, ch in glyphs if left <= x <= right and bottom <= y <= top))


# A painted mark reads as present when at least this share of its inner area is dark, absent below the second.
_FILLED_AT, _EMPTY_BELOW = 0.6, 0.2


def _darkness(doc, page_no: int, rect: tuple[float, float, float, float], cache: dict, *, inset: float = 0.2) -> float:
    """Share of dark pixels (< 128 grey) in the inner part of ``rect`` (x, bottom y, w, h) on a render of the page."""
    if page_no not in cache:
        page = doc[page_no - 1]
        left, bottom, right, top = page.get_mediabox()
        cache[page_no] = (page.render(scale=3, grayscale=True).to_pil().convert("L"), left, top)
    img, left, top = cache[page_no]
    x, y, w, h = rect
    x0, x1 = (x + w * inset - left) * 3, (x + w * (1 - inset) - left) * 3
    y0, y1 = (top - (y + h * (1 - inset))) * 3, (top - (y + h * inset)) * 3
    crop = img.crop((int(x0), int(y0), max(int(x1), int(x0) + 1), max(int(y1), int(y0) + 1)))
    hist = crop.histogram()  # 256 grey levels
    return sum(hist[:128]) / max(1, sum(hist))


def _check_box(ln, wl, box: OverlayBox, pack: HandFillPack, doc, n_pages: int, glyphs_by_page: dict,
               default_size: float, path: Path, renders: dict | None = None) -> OverlayCheck:
    """The OVERLAY verdict for ONE placement of one worksheet line (see :func:`verify_overlay`)."""
    renders = {} if renders is None else renders
    if box.page <= n_pages and ln.type == "checkbox" and box.mark == "fill":
        dark = _darkness(doc, box.page, _mark_rect(box), renders)
        want = wl.value != ""
        ok = dark >= _FILLED_AT if want else dark < _EMPTY_BELOW
        state = "painted" if dark >= _FILLED_AT else "empty" if dark < _EMPTY_BELOW else "partly painted"
        return OverlayCheck(
            line=wl.line, label=wl.label, value="(filled)" if want else "", page=box.page, status=PASS if ok else FAIL,
            detail=(f"line '{wl.line}': its oval on page {box.page} is {state} ({dark:.0%} dark), as the value says"
                    if ok else f"line '{wl.line}': expected the oval on page {box.page} to be "
                    f"{'painted' if want else 'empty'}, but it is {state} ({dark:.0%} dark) — re-run fill_form from "
                    f"these values"),
        )
    if box.page <= n_pages and ln.type == "money" and box.minus is not None:
        m = box.minus
        dark = _darkness(doc, box.page, (m.x, m.y, m.w, m.h), renders)
        want = wl.value.startswith("-")
        if (dark >= _FILLED_AT) != want or (not want and dark >= _EMPTY_BELOW):
            return OverlayCheck(
                line=wl.line, label=wl.label, value=wl.value, page=box.page, status=FAIL,
                detail=(f"line '{wl.line}': the minus box on page {box.page} is {dark:.0%} dark but the value "
                        f"{'IS' if want else 'is NOT'} a loss — the sign on the page disagrees with the worksheet; "
                        f"re-run fill_form from these values"),
            )
    if box.page > n_pages:
        return OverlayCheck(
            line=wl.line, label=wl.label, value=wl.value, page=box.page, status=FAIL,
            detail=f"line '{wl.line}' is placed on page {box.page} but {path.name} has {n_pages} page(s) — "
                   f"fix the pack's overlay.page or re-fetch the blank",
        )
    if box.page not in glyphs_by_page:
        tp = doc[box.page - 1].get_textpage()
        try:
            glyphs_by_page[box.page] = _stamped_glyphs(tp)
        finally:
            tp.close()
    glyphs = glyphs_by_page[box.page]
    if wl.value == "":
        found = _in_box(glyphs, box, box.font_size or default_size)
        where = f"[{box.x:.1f}, {box.y:.1f}] w={box.w:g} on page {box.page}"
        return OverlayCheck(
            line=wl.line, label=wl.label, value="", page=box.page, status=FAIL if found else PASS,
            detail=(f"line '{wl.line}' is blank but its box {where} holds stamped {redact(found)!r} — a stale "
                    f"or misplaced stamp; re-run fill_form from these values and verify that output"
                    if found else f"line '{wl.line}' is blank and its box {where} holds no stamped glyphs"),
        )
    expected = _WS.sub("", _stamp_text(ln, wl.value, box))
    _, size, _, _ = _layout(ln, box, pack, wl.value)
    found = _in_box(glyphs, box, size)
    where = f"box [{box.x:.1f}, {box.y:.1f}] w={box.w:g} on page {box.page}"
    if found == expected:
        return OverlayCheck(
            line=wl.line, label=wl.label, value=expected, page=box.page, status=PASS,
            detail=f"line '{wl.line}': {redact(expected)!r} is exactly what is stamped in its {where}",
        )
    if not found:
        elsewhere = expected in "".join(ch for _, _, _, ch in glyphs)
        hint = (
            "the value IS stamped elsewhere on the page — the stamp or the pack's coordinates moved; re-run "
            "fill_form from the current pack"
            if elsewhere
            else "nothing is stamped there — this PDF was not stamped from these values (or the blank was "
            "re-rendered without the overlay); re-run fill_form and verify that output"
        )
    else:
        hint = ("the box holds a DIFFERENT stamped value — the PDF was stamped from other values, or a "
                "neighbouring stamp spills into this box; re-run fill_form from these values")
    return OverlayCheck(
        line=wl.line, label=wl.label, value=expected, page=box.page, status=FAIL,
        detail=f"line '{wl.line}': expected exactly {redact(expected)!r} in its {where}, found stamped "
               f"{redact(found)!r}; {hint}",
    )


def verify_overlay(
    pack: HandFillPack,
    pdf_path: str | Path,
    values: Mapping[str, object] | None,
    *,
    independent: Mapping[str, float | int] | None = None,
) -> OverlayVerifyReport:
    """The OVERLAY verdict: does each declared box hold exactly its stamped value?

    Recomputes the worksheet from ``pack`` + ``values`` (the same dict given to
    :func:`stamp_overlay`), then reads the stamped PDF's text layer (pypdfium2) and keeps
    only the glyphs drawn in the stamp font — unembedded base-14 Helvetica; a blank prints in
    embedded fonts. For every line with coordinates:

    * a line with a value PASSES only when the stamped glyphs inside its DECLARED box
      (``x .. x + w``, the baseline band) read, left to right, exactly as the value
      (whitespace aside). The region is the pack's box, never a layout rebuilt from the
      expected text — that was PJ-01: a substring search inside the expected value's own
      footprint let a stamped '14,000' verify as '4,000', '10' as '0' and '1,200' as '200';
    * a BLANK line's box must hold no stamped glyphs (a stale stamp there FAILS);
    * a line placed beyond the PDF's last page FAILS.

    Unknown line ids in ``values`` are refused, as in :func:`stamp_overlay`. What this still
    cannot see is listed in ``limits`` on every report — the render + vision pass stays
    mandatory.

    ``independent`` (line -> calc result) runs :func:`taxfill_core.verify.independent_recompute`
    over the worksheet's money lines, the same no-LLM-arithmetic backstop verify_form offers
    for AcroForm packs.
    """
    assert_filing_grade(pack.jurisdiction, pack.tax_year, action="verify a form")
    path = Path(pdf_path)
    values = dict(values or {})
    by_line = {ln.line: ln for ln in pack.lines}
    unknown = sorted(k for k in values if k not in by_line)
    if unknown:
        raise ValueError(
            f"unknown line key(s) {unknown} for form {pack.form} ({pack.tax_year}) — valid line ids: "
            f"{sorted(by_line)}; pass exactly the values given to fill_form"
        )
    worksheet = hand_fill_worksheet(pack, values)
    doc = _open_pdfium(path, "pass the stamped PDF fill_form wrote for this hand-fill pack")
    checks: list[OverlayCheck] = []
    hand_written: list[WorksheetLine] = []
    defaults = pack.overlay_defaults
    default_size = defaults.font_size if defaults else DEFAULT_OVERLAY_FONT_SIZE
    try:
        n_pages = len(doc)
        glyphs_by_page: dict[int, list[tuple[float, float, float, str]]] = {}
        renders: dict = {}
        for wl in worksheet.lines:
            ln = by_line[wl.line]
            if not ln.boxes:
                if wl.value != "":
                    hand_written.append(wl)
                continue
            for box in ln.boxes:  # every placement is checked: a repeated header SSN must be in each
                checks.append(_check_box(ln, wl, box, pack, doc, n_pages, glyphs_by_page, default_size, path, renders))
    finally:
        doc.close()

    recompute = (
        independent_recompute(worksheet_money_values(worksheet, pack), independent) if independent is not None else []
    )
    ok = all(c.status == PASS for c in checks) and all(r.status == PASS for r in recompute)
    return OverlayVerifyReport(
        ok=ok, form_keys=[pack.form], pdf_path=str(path), page_count=n_pages, checks=checks,
        recompute=recompute, hand_written_lines=hand_written, limits=list(OVERLAY_VERDICT_LIMITS),
    )


# ── authoring: anchor lookup ─────────────────────────────────────────────────


def page_geometry(pdf_path: str | Path, page: int) -> dict[str, float | int]:
    """MediaBox (user-space frame) and /Rotate of one page: the frame overlay coordinates use."""
    path = Path(pdf_path)
    doc = _open_pdfium(path, "pass the blank PDF fetched from the pack's source_url")
    try:
        n = len(doc)
        if not 1 <= page <= n:
            raise ValueError(f"page {page} is out of range — {path.name} has {n} page(s); pages are 1-based")
        pg = doc[page - 1]
        left, bottom, right, top = pg.get_mediabox()
        return {
            "page": page, "pages": n, "x0": left, "y0": bottom, "x1": right, "y1": top,
            "width": right - left, "height": top - bottom, "rotation": pg.get_rotation(),
        }
    finally:
        doc.close()


def locate_labels(
    blank_pdf_path: str | Path,
    page: int,
    needles: Sequence[str],
    *,
    match_case: bool = False,
    whole_word: bool = True,
) -> dict[str, list[Box]]:
    """Printed positions of ``needles`` (line-number labels, captions) on one page of a blank.

    Uses pypdfium2's text page: ``search`` finds each occurrence, ``get_charbox`` gives every
    matched glyph's tight box, and the union is returned as a :class:`Box` in PDF points,
    user space, origin bottom-left — already the content-stream frame, no conversion (and
    unrotated even on a ``/Rotate`` page). ``whole_word`` (default) keeps '1' from matching
    inside '11' or '2023'. Every needle maps to a (possibly empty) list; a blank with no text
    layer at all (a scanned image) yields empty lists for everything — then coordinates must
    be estimated from a render instead, and this helper cannot help.

    For authors: a label's ``y0`` is its baseline (for glyphs without descenders), so a value
    on the same printed row is stamped at ``y = y0``; its ``x1`` is where the label ends and
    the entry box begins somewhere to the right.
    """
    path = Path(blank_pdf_path)
    doc = _open_pdfium(path, "pass the blank PDF fetched from the pack's source_url")
    out: dict[str, list[Box]] = {}
    try:
        n = len(doc)
        if not 1 <= page <= n:
            raise ValueError(f"page {page} is out of range — {path.name} has {n} page(s); pages are 1-based")
        tp = doc[page - 1].get_textpage()
        try:
            for needle in needles:
                if not needle:
                    raise ValueError("an empty needle matches nothing — pass the printed label text, e.g. '5' or 'Line 5'")
                hits: list[Box] = []
                searcher = tp.search(needle, match_case=match_case, match_whole_word=whole_word)
                try:
                    while True:
                        match = searcher.get_next()
                        if match is None:
                            break
                        index, count = match
                        boxes = [tp.get_charbox(i) for i in range(index, index + count)]
                        hits.append(Box(
                            text=tp.get_text_range(index, count), page=page,
                            x0=round(min(b[0] for b in boxes), 3), y0=round(min(b[1] for b in boxes), 3),
                            x1=round(max(b[2] for b in boxes), 3), y1=round(max(b[3] for b in boxes), 3),
                        ))
                finally:
                    searcher.close()
                out[needle] = hits
        finally:
            tp.close()
    finally:
        doc.close()
    return out


def worksheet_for(pack: HandFillPack, values: Mapping[str, object] | None) -> Worksheet:
    """Convenience re-export so callers of this module need not import handfill separately."""
    return hand_fill_worksheet(pack, values or {})
