"""Whether a value fits its AcroForm text box: one measure for fill_form and verify (Phase K JK28, 2026-10-16).

fill_form builds a page-header mirror (``FormPack.mirrors``) and verify checks it, and both must agree on whether a
value fits the box it lands in. CA Form 540's Sides 2-6 "Your name:" box is 125.9-127.0 pt wide at Helv 10, and
"ALEXANDRA Q WASHINGTON" (142.8 pt) printed cut off while fill_form said nothing and verify passed it: P-001's
estimate of 0.5 em a character (110 pt) is too low for capitals. This module is the arithmetic both sides call. It
reads no PDF: fill_form measures the widgets of the blank it opens, verify the widgets it reads off the filled PDF,
and verify still never imports the filler.

The model is the one the JK28 probe renders pin in ``packages/core/tests/test_pack_maxlen.py``:

* a value's ADVANCE at the widget's /DA font and size: Helvetica (/Helv) and Arial with Adobe's Core-14 Helvetica AFM
  widths, :func:`taxfill_core.overlay.text_width` (a capital is 0.278-0.944 em, a digit 0.556), and Courier and
  Courier New at exactly 0.6 em a glyph. Any other face is measured as Helvetica. That is a stand-in, not a metric:
  the blanks the packs map set their boxes in Helv, Arial or Courier;
* against the widget's width LESS 2 pt, because the renderer's form layer (pdfium) draws the value from the 1 pt
  border inward and clips 1 pt inside the far edge;
* a field with a widget on several pages fits only when it fits each of them, in practice its narrowest;
* an auto-size /DA (``0 Tf``) always fits, because the viewer shrinks the text. A widget with no /DA is measured at
  10 pt Helvetica (verify's P-001 assumption). A multiline widget wraps, so one line's advance says nothing about it,
  and a widget with no width cannot be measured: neither counts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

__all__ = ["BORDER_PT", "COURIER_EM", "DEFAULT_FONT_SIZE", "Fit", "WidgetBox", "advance", "fit", "is_courier",
           "widget_box"]

COURIER_EM = 0.6  # every Courier and Courier New glyph advances 600/1000 em
BORDER_PT = 1.0  # pdfium draws from the 1 pt border inward and clips 1 pt inside the far edge
DEFAULT_FONT_SIZE = 10.0  # a widget with no /DA: verify's P-001 assumption
_EPSILON = 1e-6  # an advance equal to the room fits (float noise aside)
_DA_FONT_RE = re.compile(r"/([^\s/()<>\[\]{}%]+)\s+(\d+(?:\.\d+)?)\s+Tf")
_DA_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s+Tf")
_COURIER_ALIASES = frozenset({"Cour", "CoBo", "CoOb", "CoBO"})  # Acrobat's /DR names for the four Courier faces


class WidgetBox(NamedTuple):
    """One widget of a text field, as the fit measure needs it."""

    width: float  # the widget rectangle's width, pt (0 when unknown)
    size: float  # the /DA font size, pt; 0 means auto-size
    font: str = ""  # the /DA font resource name ('Helv'), for messages; '' when the /DA names none
    courier: bool = False  # a Courier face: 0.6 em a glyph
    multiline: bool = False  # /Ff bit 13: the viewer wraps the text

    @property
    def room(self) -> float:
        """How far a value may advance before pdfium cuts it: the width less 1 pt on each side."""
        return self.width - 2 * BORDER_PT


def is_courier(font: str, base_fonts: Mapping[str, str] | None = None) -> bool:
    """Whether a /DA font resource is a Courier face.

    ``base_fonts`` maps the AcroForm /DR font names to their /BaseFont (both without the slash). A resolved
    /BaseFont decides; an unresolved name is Courier when it is one of Acrobat's aliases or names Courier itself.
    The same rule as verify's clipping scan (``verify._da_is_monospace``).
    """
    base = (base_fonts or {}).get(font)
    if base:
        return "courier" in base.lower()
    return font in _COURIER_ALIASES or "courier" in font.lower()


def widget_box(
    width: float,
    da: str | None,
    *,
    courier: bool | None = None,
    base_fonts: Mapping[str, str] | None = None,
    multiline: bool = False,
) -> WidgetBox:
    """A :class:`WidgetBox` from a widget's width and its /DA string ('/Helv 10 Tf 0 g').

    ``courier`` is the caller's own reading of the face (verify's ``TextWidget.monospace``); None reads it from the
    /DA font name and ``base_fonts`` (:func:`is_courier`). A /DA with no ``<size> Tf`` is measured at 10 pt.
    """
    match = _DA_FONT_RE.search(da or "")
    if match is not None:
        font, size = match.group(1), float(match.group(2))
    else:
        sized = _DA_SIZE_RE.search(da or "")
        font, size = "", float(sized.group(1)) if sized else DEFAULT_FONT_SIZE
    if courier is None:
        courier = is_courier(font, base_fonts)
    return WidgetBox(float(width), size, font, courier, multiline)


def advance(text: str, size: float, *, courier: bool = False) -> float:
    """The advance of ``text`` set at ``size`` pt: 0.6 em a glyph in Courier, Helvetica's AFM widths otherwise."""
    if courier:
        return COURIER_EM * len(text) * size
    # Imported here, not at the top: overlay imports verify, and verify imports this module.
    from taxfill_core.overlay import text_width  # noqa: PLC0415

    return text_width(text, size)


class Fit(NamedTuple):
    """Whether a value fits a field's box, with the measurement in words for a warning or a check's detail."""

    fits: bool | None  # None: no widget could be measured (and the maxlen, when there is one, holds the value)
    detail: str


def fit(text: str, boxes: Sequence[WidgetBox], *, maxlen: int | None = None, comb: bool = False) -> Fit:
    """Whether ``text`` fits a field whose widgets are ``boxes``, as written (no further formatting).

    ``maxlen`` is the field's character budget (the pack's maxlen), checked first. A ``comb`` field prints one
    character a cell across its width, so its width is not measured here: its maxlen and digits-only rules are the
    filler's own refusals. Otherwise the value must advance no further than every widget's width less 2 pt
    (:class:`WidgetBox`); an auto-size widget always holds it. ``fits`` is None when no widget can be measured.
    """
    if comb:
        return Fit(True, "a comb box, one character a cell: its width is not measured")
    if maxlen is not None and len(text) > maxlen:
        return Fit(False, f"{len(text)} characters, and the box takes at most {maxlen}")
    single = [box for box in boxes if not box.multiline]
    fixed = [box for box in single if box.size > 0 and box.width > 0]
    if not fixed:
        if any(box.size == 0 for box in single):
            return Fit(True, "an auto-size box (/DA 0 Tf): the viewer shrinks the text to fit")
        return Fit(None, "no single-line widget of the field with a width and a font size to measure")
    # The widget the value overruns most (or clears least) decides: with one /DA on every widget, the narrowest.
    used, box = max(((advance(text, b.size, courier=b.courier), b) for b in fixed), key=lambda m: m[0] - m[1].room)
    fits = used - box.room <= _EPSILON
    if len(fixed) == 1:
        which = "its box"
    else:
        kind = "narrowest" if box.width <= min(b.width for b in fixed) else "tightest"
        which = f"the {kind} of its {len(fixed)} widgets"
    return Fit(fits, (
        f"{used:.1f} pt at {box.font or 'Helvetica'} {box.size:g}, {'within' if fits else 'wider than'} the "
        f"{box.room:.1f} pt inside {which}: {box.width:.1f} pt wide, less 1 pt on each side"
    ))
