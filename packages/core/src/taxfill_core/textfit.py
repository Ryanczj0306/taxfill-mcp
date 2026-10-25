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
* against the widget's width LESS its border width on each side (:func:`widget_inset`; 1 pt when the widget
  declares none), because the renderer's form layer (pdfium) draws the value from inside the border and clips it
  inside the far one. Phase K JEe (2026-10-24) measured it on renders through fill_form and render_form, the ink of
  an overflowing digit string against the box: about 1 pt on a box with no /BS or a 1 pt one (AR 1000F, CO DR 0104,
  GA 500, KY 740, ND-1), about 2 pt on a 2 pt border (AL Form 40's address, PA-40 line 19b) and about 3 pt on a 3 pt
  one (KY 740 line 5a, PA-40 line 11);
* by where the value's INK ends, not its advance: a glyph's advance includes the blank space right of its ink (its
  right side bearing), and pdfium's clip cuts only ink. :func:`ink_extent` is the advance less the last glyph's
  bearing in the face pdfium draws (``_RSB_HELVETICA`` / ``_RSB_COURIER``). JEe measured the cut by rendering each
  value in its box and in the same box widened: Rhode Island's dependent date of birth (8 Courier New 12 digits in
  57.6 pt) loses 0.58 pt of its last digit, California 540's 13-digit Apt. box (Helv 10, 72.5 pt) 1.33 pt, and the
  ink arithmetic gives 0.64 and 1.32. A cut of at most ``CUT_TOLERANCE_PT`` (0.5 pt, under the thinnest cut a
  reviewer has flagged, RI's 0.58 pt) is not a cut: the IRS's own 4-digit year boxes (21.6 pt at Helvetica-Bold 9,
  draft 2026 Forms 1040 / 1040-NR / 1040-X) lose at most 0.14 pt of their last digit, and a bold glyph whose ink
  starts left of its origin ('A', 'J', 'W' in bold Courier) up to 0.26 pt of its first;
* by the box's alignment (/Q): a left-aligned value starts at the left inset and overruns on the right; a
  right-aligned one ends at the right inset and overruns on the left (its first glyph's LEFT side bearing counts);
  a centred one splits the overrun between both sides. RI-1040's centred middle-initial box is one Courier-12 glyph
  wide (7.2 pt): the 2 pt the border takes splits 1 pt a side and the glyph's own bearings absorb it, so an initial
  renders whole (:func:`ink_overrun`);
* a field with a widget on several pages fits only when it fits each of them, in practice its narrowest;
* an auto-size /DA (``0 Tf``) always fits, because the viewer shrinks the text. A widget with no /DA is measured at
  10 pt Helvetica (verify's P-001 assumption). A multiline widget wraps, so one line's advance says nothing about it,
  and a widget with no width cannot be measured: neither counts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

__all__ = ["BORDER_PT", "COURIER_EM", "CUT_TOLERANCE_PT", "DEFAULT_FONT_SIZE", "Fit", "WidgetBox", "advance", "bearings",
           "fit", "ink_extent", "ink_overrun", "is_bold", "is_courier", "widget_box", "widget_inset"]

COURIER_EM = 0.6  # every Courier and Courier New glyph advances 600/1000 em
CUT_TOLERANCE_PT = 0.5  # under the thinnest cut a reviewer has flagged (RI's date of birth, 0.58 pt measured)
BORDER_PT = 1.0  # a widget with no /BS or /Border: pdfium draws from 1 pt inside the edge and clips 1 pt inside the far one
DEFAULT_FONT_SIZE = 10.0  # a widget with no /DA: verify's P-001 assumption
_EPSILON = 1e-6  # an advance equal to the room fits (float noise aside)
_DA_FONT_RE = re.compile(r"/([^\s/()<>\[\]{}%]+)\s+(\d+(?:\.\d+)?)\s+Tf")
_DA_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s+Tf")
_COURIER_ALIASES = frozenset({"Cour", "CoBo", "CoOb", "CoBO"})  # Acrobat's /DR names for the four Courier faces


# Side bearings (em), (left, right): the blank space either side of each glyph's ink, as pdfium draws the base-14
# faces it substitutes for a form's /DA font. Phase K JEe (2026-10-24): each glyph drawn at 200 pt with reportlab,
# rendered by pypdfium2 at 2 px/pt, ink edge against origin and advance. packages/core/tests/test_textfit_ink.py
# re-measures them. A glyph not listed counts 0 on both sides (its ink is taken to fill its advance).
_BEARINGS: dict[str, dict[str, tuple[float, float]]] = {
    "Helvetica": {
        "0": (0.043, 0.049), "1": (0.11, 0.184), "2": (0.03, 0.054), "3": (0.043, 0.046), "4": (0.013, 0.049),
        "5": (0.043, 0.041), "6": (0.037, 0.046), "7": (0.048, 0.046), "8": (0.04, 0.044), "9": (0.043, 0.044),
        "A": (0, 0), "B": (0.072, 0.052), "C": (0.05, 0.04), "D": (0.077, 0.052), "E": (0.08, 0.055),
        "F": (0.083, 0.046), "G": (0.052, 0.063), "H": (0.08, 0.08), "I": (0.092, 0.091), "J": (0.028, 0.077),
        "K": (0.072, 0.002), "L": (0.072, 0.036), "M": (0.075, 0.075), "N": (0.075, 0.082), "O": (0.048, 0.045),
        "P": (0.077, 0.045), "Q": (0.043, 0.038), "R": (0.077, 0.015), "S": (0.045, 0.052), "T": (0.022, 0.021),
        "U": (0.077, 0.08), "V": (0.005, 0.01), "W": (0.013, 0.012), "X": (0.005, 0.007), "Y": (0.005, 0.01),
        "Z": (0.02, 0.026), "a": (0.035, 0.044), "b": (0.065, 0.041), "c": (0.04, 0.01), "d": (0.035, 0.071),
        "e": (0.037, 0.041), "f": (0.01, -0.034), "g": (0.033, 0.066), "h": (0.065, 0.069), "i": (0.068, 0.067),
        "j": (-0.045, 0.07), "k": (0.068, 0.005), "l": (0.062, 0.07), "m": (0.065, 0.065), "n": (0.065, 0.069),
        "o": (0.033, 0.036), "p": (0.065, 0.041), "q": (0.035, 0.071), "r": (0.065, -0.014), "s": (0.03, 0.037),
        "t": (0.018, 0.008), "u": (0.065, 0.071), "v": (0.013, 0.013), "w": (0.003, 0.01), "x": (0.007, 0.007),
        "y": (0.018, 0.01), "z": (0.02, 0.022), "-": (0.03, 0.031), "/": (0, 0.001), ".": (0.09, 0.086),
        ",": (0.085, 0.088), "(": (0.06, 0.038), ")": (0.062, 0.036), "$": (0.035, 0.046), "%": (0.058, 0.062),
        "#": (0.01, 0.014), "&": (0.043, 0.025), "'": (0.045, 0.046),
    },
    "Helvetica-Bold": {
        "0": (0.043, 0.049), "1": (0.08, 0.164), "2": (0.025, 0.051), "3": (0.037, 0.044), "4": (0.018, 0.024),
        "5": (0.045, 0.031), "6": (0.043, 0.036), "7": (0.043, 0.044), "8": (0.04, 0.046), "9": (0.033, 0.046),
        "A": (0, 0.005), "B": (0.072, 0.05), "C": (0.048, 0.052), "D": (0.072, 0.05), "E": (0.072, 0.05),
        "F": (0.072, 0.046), "G": (0.048, 0.06), "H": (0.072, 0.077), "I": (0.068, 0.066), "J": (0.018, 0.081),
        "K": (0.075, 0.002), "L": (0.077, 0.031), "M": (0.07, 0.07), "N": (0.075, 0.08), "O": (0.043, 0.04),
        "P": (0.072, 0.047), "Q": (0.043, 0.013), "R": (0.072, 0.007), "S": (0.037, 0.05), "T": (0.022, 0.021),
        "U": (0.072, 0.08), "V": (0, 0.002), "W": (0.005, 0.002), "X": (0, 0.002), "Y": (0, 0), "Z": (0.01, 0.018),
        "a": (0.035, 0.034), "b": (0.065, 0.038), "c": (0.043, 0.026), "d": (0.04, 0.063), "e": (0.033, 0.039),
        "f": (0.013, -0.029), "g": (0.04, 0.063), "h": (0.072, 0.068), "i": (0.072, 0.068), "j": (-0.045, 0.073),
        "k": (0.068, 0.011), "l": (0.072, 0.068), "m": (0.062, 0.064), "n": (0.07, 0.068), "o": (0.04, 0.036),
        "p": (0.068, 0.038), "q": (0.045, 0.063), "r": (0.065, -0.014), "s": (0.025, 0.049), "t": (0.015, 0.013),
        "u": (0.07, 0.071), "v": (0.007, 0.014), "w": (0.005, 0), "x": (0.007, 0.011), "y": (0.007, 0.016),
        "z": (0.018, 0.02), "-": (0.055, 0.008), "/": (0, 0.001), ".": (0.072, 0.068), ",": (0.058, 0.073),
        "(": (0.052, 0.033), ")": (0.033, 0.051), "$": (0.035, 0.044), "%": (0.043, 0.047), "#": (0.01, 0.011),
        "&": (0.045, 0.017), "'": (0.045, 0.043),
    },
    "Courier": {
        "0": (0.113, 0.113), "1": (0.113, 0.113), "2": (0.083, 0.12), "3": (0.095, 0.1), "4": (0.105, 0.12),
        "5": (0.095, 0.1), "6": (0.135, 0.087), "7": (0.102, 0.12), "8": (0.113, 0.113), "9": (0.135, 0.09),
        "A": (0.007, 0.007), "B": (0.043, 0.058), "C": (0.062, 0.062), "D": (0.077, 0.043), "E": (0.043, 0.077),
        "F": (0.077, 0.043), "G": (0.062, 0.035), "H": (0.052, 0.045), "I": (0.113, 0.113), "J": (0.083, 0.015),
        "K": (0.043, 0.025), "L": (0.062, 0.058), "M": (0.013, 0.007), "N": (0.022, 0.037), "O": (0.05, 0.05),
        "P": (0.087, 0.055), "Q": (0.05, 0.05), "R": (0.043, 0.007), "S": (0.09, 0.09), "T": (0.07, 0.07),
        "U": (0.04, 0.04), "V": (0.007, 0.007), "W": (0.018, 0.02), "X": (0.04, 0.037), "Y": (0.048, 0.05),
        "Z": (0.105, 0.1), "a": (0.07, 0.058), "b": (0.022, 0.058), "c": (0.083, 0.062), "d": (0.062, 0.018),
        "e": (0.062, 0.077), "f": (0.105, 0.055), "g": (0.06, 0.037), "h": (0.043, 0.048), "i": (0.092, 0.09),
        "j": (0.087, 0.198), "k": (0.092, 0.028), "l": (0.092, 0.09), "m": (0.01, 0.007), "n": (0.052, 0.058),
        "o": (0.07, 0.07), "p": (0.022, 0.058), "q": (0.062, 0.018), "r": (0.083, 0.055), "s": (0.1, 0.1),
        "t": (0.072, 0.07), "u": (0.045, 0.058), "v": (0.03, 0.028), "w": (0.028, 0.028), "x": (0.05, 0.048),
        "y": (0.072, 0.025), "z": (0.115, 0.11), "-": (0.09, 0.09), "/": (0.113, 0.11), ".": (0.225, 0.225),
        ",": (0.145, 0.247), "(": (0.295, 0.14), ")": (0.147, 0.287), "$": (0.113, 0.113), "%": (0.092, 0.09),
        "#": (0.092, 0.092), "&": (0.125, 0.1), "'": (0.235, 0.235),
    },
    "Courier-Bold": {
        "0": (0.083, 0.083), "1": (0.083, 0.08), "2": (0.052, 0.09), "3": (0.065, 0.07), "4": (0.075, 0.09),
        "5": (0.065, 0.07), "6": (0.105, 0.058), "7": (0.075, 0.09), "8": (0.083, 0.08), "9": (0.105, 0.058),
        "A": (-0.022, -0.022), "B": (0.013, 0.028), "C": (0.03, 0.033), "D": (0.015, 0.048), "E": (0.015, 0.048),
        "F": (0.05, 0.013), "G": (0.033, 0.005), "H": (0.022, 0.018), "I": (0.083, 0.083), "J": (0.052, -0.015),
        "K": (0.013, -0.005), "L": (0.033, 0.025), "M": (-0.018, -0.022), "N": (-0.007, 0.007), "O": (0.02, 0.02),
        "P": (0.06, 0.022), "Q": (0.02, 0.02), "R": (0.015, -0.02), "S": (0.062, 0.06), "T": (0.04, 0.043),
        "U": (0.01, 0.01), "V": (-0.022, -0.022), "W": (-0.01, -0.013), "X": (0.01, 0.007), "Y": (0.02, 0.02),
        "Z": (0.072, 0.07), "a": (0.043, 0.025), "b": (-0.01, 0.028), "c": (0.055, 0.033), "d": (0.03, -0.013),
        "e": (0.033, 0.048), "f": (0.072, 0.028), "g": (0.033, 0.005), "h": (0.013, 0.015), "i": (0.062, 0.062),
        "j": (0.085, 0.14), "k": (0.033, 0.025), "l": (0.062, 0.062), "m": (-0.018, -0.025), "n": (0.025, 0.025),
        "o": (0.043, 0.04), "p": (-0.007, 0.028), "q": (0.035, -0.015), "r": (0.052, 0.028), "s": (0.072, 0.07),
        "t": (0.072, 0.01), "u": (0.015, 0.025), "v": (0, -0.005), "w": (-0.003, -0.003), "x": (0.02, 0.018),
        "y": (0.02, 0.018), "z": (0.087, 0.077), "-": (0.09, 0.09), "/": (0.083, 0.083), ".": (0.225, 0.223),
        ",": (0.203, 0.19), "(": (0.265, 0.11), ")": (0.117, 0.258), "$": (0.08, 0.083), "%": (0.077, 0.075),
        "#": (0.06, 0.062), "&": (0.11, 0.052), "'": (0.235, 0.237),
    },
}


def _either_weight(regular: str, bold: str) -> dict[str, tuple[float, float]]:
    """Per glyph, the smaller bearing of the two weights: the measure when the box's weight is unknown."""
    return {ch: (min(lsb, _BEARINGS[bold][ch][0]), min(rsb, _BEARINGS[bold][ch][1]))
            for ch, (lsb, rsb) in _BEARINGS[regular].items()}


_ANY_WEIGHT = {"Helvetica": _either_weight("Helvetica", "Helvetica-Bold"), "Courier": _either_weight("Courier", "Courier-Bold")}
_LSB_HELVETICA = {ch: lr[0] for ch, lr in _ANY_WEIGHT["Helvetica"].items()}
_RSB_HELVETICA = {ch: lr[1] for ch, lr in _ANY_WEIGHT["Helvetica"].items()}
_LSB_COURIER = {ch: lr[0] for ch, lr in _ANY_WEIGHT["Courier"].items()}
_RSB_COURIER = {ch: lr[1] for ch, lr in _ANY_WEIGHT["Courier"].items()}
_BOLD_ALIASES = frozenset({"HeBo", "HeBO", "CoBo", "CoBO", "TiBo", "TiBI"})  # Acrobat's /DR names for bold faces
# a bold weight in a font name: "Bold", Adobe's "-Bd" abbreviation (HelveticaNeueLTStd-Bd on the draft 2026 Form
# 1116), and the heavier and semi-bold weights, which draw at least as wide
_BOLD_NAME_RE = re.compile(r"bold|black|heavy|semibold|demibold|demi\b|-bd\b|bd$", re.IGNORECASE)


def bearings(ch: str, *, courier: bool = False, bold: bool | None = None) -> tuple[float, float]:
    """``ch``'s (left, right) side bearings in em, in the face pdfium draws: Courier or Helvetica, regular or bold;
    ``bold=None`` (the weight is unknown) takes the smaller of the two weights."""
    face = "Courier" if courier else "Helvetica"
    table = _ANY_WEIGHT[face] if bold is None else _BEARINGS[f"{face}-Bold" if bold else face]
    return table.get(ch, (0.0, 0.0))


def is_bold(font: str, base_fonts: Mapping[str, str] | None = None) -> bool:
    """Whether a /DA font resource is a bold face, read like :func:`is_courier`: a resolved /DR /BaseFont decides; an
    unresolved name is bold when it says Bold or is one of Acrobat's bold aliases. A /DA that names no font gets the
    viewer's default face, regular Helvetica."""
    if not font:
        return False
    base = (base_fonts or {}).get(font)
    if base:
        return bool(_BOLD_NAME_RE.search(base))
    return bool(_BOLD_NAME_RE.search(font)) or font in _BOLD_ALIASES


class WidgetBox(NamedTuple):
    """One widget of a text field, as the fit measure needs it."""

    width: float  # the widget rectangle's width, pt (0 when unknown)
    size: float  # the /DA font size, pt; 0 means auto-size
    font: str = ""  # the /DA font resource name ('Helv'), for messages; '' when the /DA names none
    courier: bool = False  # a Courier face: 0.6 em a glyph
    multiline: bool = False  # /Ff bit 13: the viewer wraps the text
    inset: float = BORDER_PT  # pt lost on EACH side to the border the viewer draws (:func:`widget_inset`)
    quadding: int = 0  # /Q: 0 left, 1 centred, 2 right
    bold: bool | None = False  # a bold face (wider glyphs, thinner bearings); None: unknown, the worse of both weights

    @property
    def room(self) -> float:
        """How far a value may advance before pdfium cuts it: the width less the inset on each side."""
        return self.width - 2 * self.inset


def widget_inset(annot: Mapping[str, object]) -> float:
    """The pt a viewer gives up on EACH side of a text widget to its border (Phase K JEe, 2026-10-24).

    ``annot`` is the widget annotation dictionary (pypdf's, or any mapping with PDF keys). The border width is the
    /BS /W entry (1 when /BS omits it), else the third number of a legacy /Border array, else 1; a beveled (/B) or
    inset (/I) style draws a second band inside the border, so it counts twice. Never less than 1 pt: a box that
    declares a thinner border was not measured, and 1 pt is the inset the renders show on a box with none. The
    measurements are in this module's docstring; no shipped pack maps a text box with a beveled or inset border.
    """
    width, style = None, "/S"
    bs = annot.get("/BS")
    bs = bs.get_object() if hasattr(bs, "get_object") else bs
    if isinstance(bs, Mapping):
        width = bs.get("/W", 1)
        style = str(bs.get("/S", "/S"))
    else:
        border = annot.get("/Border")
        border = border.get_object() if hasattr(border, "get_object") else border
        if isinstance(border, (list, tuple)) and len(border) >= 3:
            width = border[2]
    try:
        width = float(width) if width is not None else BORDER_PT
    except (TypeError, ValueError):
        width = BORDER_PT
    if style in ("/B", "/I"):
        width *= 2
    return max(width, BORDER_PT)


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
    inset: float = BORDER_PT,
    quadding: int = 0,
    bold: bool | None = None,
) -> WidgetBox:
    """A :class:`WidgetBox` from a widget's width and its /DA string ('/Helv 10 Tf 0 g').

    ``courier`` is the caller's own reading of the face (verify's ``TextWidget.monospace``); None reads it from the
    /DA font name and ``base_fonts`` (:func:`is_courier`). A /DA with no ``<size> Tf`` is measured at 10 pt.
    ``inset`` is :func:`widget_inset` of the widget: the pt its border takes on each side; ``quadding`` its /Q;
    ``bold`` the caller's reading of the weight (verify's ``TextWidget.bold``), None reading it from the /DA name.
    """
    match = _DA_FONT_RE.search(da or "")
    if match is not None:
        font, size = match.group(1), float(match.group(2))
    else:
        sized = _DA_SIZE_RE.search(da or "")
        font, size = "", float(sized.group(1)) if sized else DEFAULT_FONT_SIZE
    if courier is None:
        courier = is_courier(font, base_fonts)
    if bold is None:
        bold = is_bold(font, base_fonts)
    q = int(quadding) if quadding in (0, 1, 2) else 0
    return WidgetBox(float(width), size, font, courier, multiline, float(inset), q, bold)


def ink_extent(text: str, size: float, *, courier: bool = False, bold: bool | None = None) -> float:
    """How far ``text``'s ink reaches from where it starts, in pt: its advance less its last glyph's right side
    bearing. Trailing spaces carry no ink, so they are not measured; a blank value reaches 0."""
    body = text.rstrip()
    if not body:
        return 0.0
    return advance(body, size, courier=courier, bold=bold) - bearings(body[-1], courier=courier, bold=bold)[1] * size


def ink_overrun(text: str, box: WidgetBox) -> float:
    """How far ``text``'s ink reaches past the room inside ``box`` on its worse side, in pt (<= 0: it renders whole).

    The value is laid out the way pdfium's form layer lays it out: from the left inset (/Q 0), ending at the right
    inset (/Q 2), or centred between them (/Q 1), the whole string's advance placed and only the ink clipped.
    """
    body = text.strip()
    if not body:
        return float("-inf")
    rsb = bearings(body[-1], courier=box.courier, bold=box.bold)[1] * box.size
    lsb = bearings(body[0], courier=box.courier, bold=box.bold)[0] * box.size
    whole = advance(text, box.size, courier=box.courier, bold=box.bold)
    lead = advance(text[: len(text) - len(text.lstrip())], box.size, courier=box.courier, bold=box.bold)
    if box.quadding == 2:
        start = box.room - whole
    elif box.quadding == 1:
        start = (box.room - whole) / 2
    else:
        start = 0.0
    ink_left = start + lead + lsb
    ink_right = start + advance(text.rstrip(), box.size, courier=box.courier, bold=box.bold) - rsb
    return max(-ink_left, ink_right - box.room)


def _helvetica_bold_widths() -> tuple[Mapping[str, int], int] | None:
    """Helvetica-Bold's Core-14 AFM widths from pypdf (a private module, present from pypdf 6.x), or None."""
    try:
        from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS  # noqa: PLC0415

        widths = CORE_FONT_METRICS["Helvetica-Bold"].character_widths
        return widths, int(widths.get("default", 556))
    except Exception:  # noqa: BLE001 — an older or newer pypdf: measure as regular Helvetica
        return None


def advance(text: str, size: float, *, courier: bool = False, bold: bool | None = None) -> float:
    """The advance of ``text`` set at ``size`` pt: 0.6 em a glyph in Courier (either weight), else Helvetica's AFM
    widths in the box's weight: Helvetica-Bold's when ``bold`` (a bold capital is up to a fifth wider; the digits
    are the same), regular when not, and the wider of the two per glyph when the weight is unknown (Phase K JEe:
    a bold name on Form W-7 2025 passed measured in regular widths and printed 4.9 pt cut)."""
    if courier:
        return COURIER_EM * len(text) * size
    # Imported here, not at the top: overlay imports verify, and verify imports this module.
    from taxfill_core.overlay import _helvetica_widths, text_width  # noqa: PLC0415

    heavy = _helvetica_bold_widths() if bold is not False else None
    if heavy is None:
        return text_width(text, size)
    bold_widths, bold_default = heavy
    if bold:
        return sum(bold_widths.get(ch, bold_default) for ch in text) / 1000.0 * size
    widths, default, _ = _helvetica_widths()
    return sum(max(widths.get(ch, default), bold_widths.get(ch, bold_default)) for ch in text) / 1000.0 * size


class Fit(NamedTuple):
    """Whether a value fits a field's box, with the measurement in words for a warning or a check's detail."""

    fits: bool | None  # None: no widget could be measured (and the maxlen, when there is one, holds the value)
    detail: str


def fit(text: str, boxes: Sequence[WidgetBox], *, maxlen: int | None = None, comb: bool = False) -> Fit:
    """Whether ``text`` fits a field whose widgets are ``boxes``, as written (no further formatting).

    ``maxlen`` is the field's character budget (the pack's maxlen), checked first. A ``comb`` field prints one
    character a cell across its width, so its width is not measured here: its maxlen and digits-only rules are the
    filler's own refusals. Otherwise the value's ink (:func:`ink_extent`) must end within every widget's width less its
    border on each side (:class:`WidgetBox`), give or take ``CUT_TOLERANCE_PT``; an auto-size widget always holds it. ``fits`` is None when no widget can be measured.
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
    overs = [(ink_overrun(text, b), b) for b in fixed]
    fits = all(over <= CUT_TOLERANCE_PT + _EPSILON for over, _ in overs)
    if fits:  # name the box with the least slack, measured from the left as JK28 named it
        box = max(fixed, key=lambda b: ink_extent(text, b.size, courier=b.courier, bold=b.bold) - b.room)
        over = ink_overrun(text, box)
    else:
        over, box = max(overs, key=lambda m: m[0])
    used = advance(text, box.size, courier=box.courier, bold=box.bold)
    if len(fixed) == 1:
        which = "its box"
    else:
        kind = "narrowest" if box.width <= min(b.width for b in fixed) else "tightest"
        which = f"the {kind} of its {len(fixed)} widgets"
    ink_note = f" (its ink {'stays inside' if fits else f'overruns by {over:.1f} pt'})" if (used > box.room) == fits else ""
    return Fit(fits, (
        f"{used:.1f} pt at {box.font or 'Helvetica'} {box.size:g}{ink_note}, {'within' if fits else 'wider than'} the "
        f"{box.room:.1f} pt inside {which}: {box.width:.1f} pt wide, less {box.inset:g} pt on each side"
    ))
