"""Render the demo-persona sample Form W-2 (tax year 2025) that the user guide's walkthrough, docs/dev/ACCEPTANCE.md
and docs/dev/DEMO.md use: docs/samples/w2_2025_synthetic.pdf and docs/samples/w2_2025_synthetic.png.

Everything on the sample is fictitious: a hypothetical new-grad software engineer ("Jordan Q. Taxpayer") at a
hypothetical large tech company ("Example Tech Corp"), SSN in the 999-88-xxxx demo range (never issued), an EIN with
the never-assigned prefix 00, and ZIP 98000, below Washington's lowest assigned ZIP (98001). A diagonal
"SAMPLE — NOT A REAL DOCUMENT" watermark crosses the form.

PERSONA and PAY below are the single source of truth. The boxes are DERIVED from them, never typed:

* box 5 (Medicare wages) = gross pay - the section 125 (cafeteria plan) premiums;
* box 3 (social security wages) = box 5 capped at the 2025 wage base, read from knowledge/federal/2025.yaml;
* box 1 (wages) = gross pay - the 401(k) deferral - the section 125 premiums; the deferral is checked against the 2025
  IRC 402(g) limit read from the same knowledge pack;
* boxes 4 and 6 come from the calc op employee_fica on the box 5 wages (Pub 15 section 9 via the knowledge pack);
* box 2 is a chosen demo figure: the 2025 knowledge pack carries no Pub 15-T tables, so withholding_projection
  (the 2026 op) cannot derive it, and the script says so instead of pretending.

The SSN is in the 999-88-xxxx demo range, which starts with 9, and the tool's "starts with 9" ITIN heuristics read
such a number as an ITIN (the senior deduction, the 2026 education credits). Nothing in the TY2025 walkthrough
reaches those paths; a scenario that reuses the persona there must state the U.S. citizen's SSN status explicitly.

The PDF keeps its text layer (the watermark is an image, so it never mixes into a box's text) and EMBEDS its fonts
(Bitstream Vera, which ships inside reportlab): a PDF that only names the base-14 fonts is drawn with whatever faces
the host has (the macOS system Courier and Helvetica, pdfium's built-in substitutes on Linux), so its pixels would
depend on the machine. The PNG is the PDF rendered by pypdfium2. packages/core/tests/test_sample_w2.py reads every
box back out of the committed PDF, runs it through extract_document, holds the PNG to a fresh render of the PDF,
checks that every font is embedded, and checks the walkthrough's figures against the docs.

Run from the repo root (reportlab and Pillow come with the dev dependency group, never the wheels):

    uv run python scripts/make_sample_w2.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "samples"
PDF_NAME = "w2_2025_synthetic.pdf"
PNG_NAME = "w2_2025_synthetic.png"
TAX_YEAR = 2025
WATERMARK = "SAMPLE — NOT A REAL DOCUMENT"

# ── The demo persona (fictitious; see the module docstring) ──
PERSONA = {
    "employee_first": "Jordan Q.",
    "employee_last": "Taxpayer",
    "employee_ssn": "999-88-0425",
    "employee_address": ["123 Sample Ave Apt 4", "Seattle, WA 98000"],
    "employer_name": "Example Tech Corp",
    "employer_address": ["500 Demo Plaza", "Seattle, WA 98000"],
    "employer_ein": "00-1234567",
    "control_number": "SAMPLE-0001",
    "state": "WA",  # Washington has no individual income tax: boxes 16-17 stay blank
}

# ── The year's pay (whole dollars) ──
PAY = {
    "salary": 150_800,             # 26 biweekly checks of $5,800
    "bonus": 12_000,               # annual bonus
    "rsu_vest": 30_000,            # restricted stock units vested during 2025 (wages; noted in box 14)
    "deferral_401k": 23_400,       # pre-tax 401(k): $900 a check (box 12 code D)
    "section_125": 1_300,          # pre-tax health premiums: $50 a check (out of boxes 1, 3 and 5)
    "federal_withheld": 30_487,    # box 2: a chosen demo figure (no 2025 withholding op; see the docstring)
    "employer_health_cost": 8_400, # box 12 code DD: cost of employer-sponsored health coverage (informational)
}


def _money(x: Decimal | int) -> str:
    """A W-2 amount as printed: no dollar sign, no commas, two decimals."""
    return f"{Decimal(x):.2f}"


def w2_boxes(knowledge_dir: str | Path | None = None) -> dict[str, str]:
    """The W-2's readings keyed by the W-2 DocSpec's box keys (taxfill_core.extract), as printed on the sample.

    Blank boxes are absent. Box 14 is keyed "14": the 2025 form has one box 14 (the DocSpec's alias of 14a).
    """
    from taxfill_core.calc import employee_fica
    from taxfill_core.knowledge import load_knowledge

    pack = load_knowledge("federal", TAX_YEAR, base_dir=knowledge_dir)
    wage_base = Decimal(pack.tax.employee_social_security.ss_wage_base)
    limit_402g = Decimal(pack.contribution_limits.elective_deferral_402g.limit)
    if PAY["deferral_401k"] > limit_402g:
        raise ValueError(f"the 401(k) deferral {PAY['deferral_401k']} is over the {TAX_YEAR} 402(g) limit {limit_402g}")

    gross = Decimal(PAY["salary"] + PAY["bonus"] + PAY["rsu_vest"])
    box5 = gross - PAY["section_125"]
    box3 = min(box5, wage_base)
    box1 = gross - PAY["deferral_401k"] - PAY["section_125"]
    fica = employee_fica([{"wages": box5, "fica_exempt": False, "label": PERSONA["employer_name"]}], year=TAX_YEAR,
                         residency_classification="resident", filing_status="single", knowledge_dir=knowledge_dir)
    rate = Decimal(str(pack.tax.employee_social_security.rate))
    if Decimal(fica.social_security) != (box3 * rate).quantize(Decimal("0.01")):
        raise ValueError("employee_fica's social security does not equal 6.2% of box 3")
    return {
        "employee_ssn": PERSONA["employee_ssn"],
        "employer_ein": PERSONA["employer_ein"],
        "employer_name": " ".join([PERSONA["employer_name"], *PERSONA["employer_address"]]),
        "employee_name": f"{PERSONA['employee_first']} {PERSONA['employee_last']}",
        "1": _money(box1),
        "2": _money(PAY["federal_withheld"]),
        "3": _money(box3),
        "4": _money(Decimal(fica.social_security)),
        "5": _money(box5),
        "6": _money(Decimal(fica.medicare)),
        "12a": f"D {_money(PAY['deferral_401k'])}",
        "12b": f"DD {_money(PAY['employer_health_cost'])}",
        "13_retirement": "X",
        "14": f"RSU {_money(PAY['rsu_vest'])}",
        "15_state": PERSONA["state"],
    }


# ── Page geometry (PDF points; top-down y here, flipped when drawing) ──
PAGE_W, PAGE_H = 612.0, 396.0  # 8.5 x 5.5 in, the size of one W-2 copy
_L, _LM, _RM, _R = 18.0, 306.0, 450.0, 594.0
_GRID_TOP, _ROW = 62.0, 24.0
_LABEL_BAND = 11.0  # each box's printed label sits in its top band; the value sits below it


def _row(i: int) -> tuple[float, float]:
    return _GRID_TOP + i * _ROW, _GRID_TOP + (i + 1) * _ROW


# Every box: (printed label, x0, top, x1, bottom). Value areas are what the test reads back.
BOXES: dict[str, tuple[str, float, float, float, float]] = {
    "a": ("a  Employee's social security number", _L, 38.0, 200.0, _GRID_TOP),
    "b": ("b  Employer identification number (EIN)", _L, 62.0, _LM, 92.0),
    "c": ("c  Employer's name, address, and ZIP code", _L, 92.0, _LM, 158.0),
    "d": ("d  Control number", _L, 158.0, _LM, 182.0),
    "e_first": ("e  Employee's first name and initial", _L, 182.0, 170.0, 218.0),
    "e_last": ("Last name", 170.0, 182.0, 280.0, 218.0),
    "e_suff": ("Suff.", 280.0, 182.0, _LM, 218.0),
    "f": ("f  Employee's address and ZIP code", _L, 218.0, _LM, 278.0),
    "1": ("1  Wages, tips, other compensation", _LM, _row(0)[0], _RM, _row(0)[1]),
    "2": ("2  Federal income tax withheld", _RM, _row(0)[0], _R, _row(0)[1]),
    "3": ("3  Social security wages", _LM, _row(1)[0], _RM, _row(1)[1]),
    "4": ("4  Social security tax withheld", _RM, _row(1)[0], _R, _row(1)[1]),
    "5": ("5  Medicare wages and tips", _LM, _row(2)[0], _RM, _row(2)[1]),
    "6": ("6  Medicare tax withheld", _RM, _row(2)[0], _R, _row(2)[1]),
    "7": ("7  Social security tips", _LM, _row(3)[0], _RM, _row(3)[1]),
    "8": ("8  Allocated tips", _RM, _row(3)[0], _R, _row(3)[1]),
    "9": ("9", _LM, _row(4)[0], _RM, _row(4)[1]),
    "10": ("10  Dependent care benefits", _RM, _row(4)[0], _R, _row(4)[1]),
    "11": ("11  Nonqualified plans", _LM, _row(5)[0], _RM, _row(5)[1]),
    "12a": ("12a  Code | See instructions for box 12", _RM, _row(5)[0], _R, _row(5)[1]),
    "13": ("13", _LM, _row(6)[0], _RM, _row(6)[1]),
    "12b": ("12b", _RM, _row(6)[0], _R, _row(6)[1]),
    "14": ("14  Other", _LM, _row(7)[0], _RM, _row(8)[1]),
    "12c": ("12c", _RM, _row(7)[0], _R, _row(7)[1]),
    "12d": ("12d", _RM, _row(8)[0], _R, _row(8)[1]),
    "15": ("15  State", _L, 278.0, 50.0, 314.0),
    "15_id": ("Employer's state ID number", 50.0, 278.0, 170.0, 314.0),
    "16": ("16  State wages, tips, etc.", 170.0, 278.0, 262.0, 314.0),
    "17": ("17  State income tax", 262.0, 278.0, 354.0, 314.0),
    "18": ("18  Local wages, tips, etc.", 354.0, 278.0, 446.0, 314.0),
    "19": ("19  Local income tax", 446.0, 278.0, 538.0, 314.0),
    "20": ("20  Locality name", 538.0, 278.0, _R, 314.0),
}
_CODE_W = 30.0  # box 12's code sub-box
_BOX13 = (("13_statutory", "Statutory employee"), ("13_retirement", "Retirement plan"),
          ("13_sick_pay", "Third-party sick pay"))


_BOX13_CENTERS = (37.0, 82.0, 122.0)  # spaced so the three 4-point labels clear "13" and each other


def _box13_square(i: int) -> tuple[float, float, float, float]:
    x0 = _LM + _BOX13_CENTERS[i] - 4.5
    top = _row(6)[0] + 12.0
    return x0, top, x0 + 9.0, top + 9.0


def value_areas() -> dict[str, list[tuple[float, float, float, float]]]:
    """Where each DocSpec box's value is printed: DocSpec key -> list of (left, bottom, right, top) PDF rectangles,
    read in order and joined with a space (box e's two name boxes, box 12's code and amount)."""
    def body(name: str) -> tuple[float, float, float, float]:
        _, x0, top, x1, bottom = BOXES[name]
        return x0 + 1.0, PAGE_H - bottom + 1.0, x1 - 1.0, PAGE_H - top - _LABEL_BAND

    areas: dict[str, list[tuple[float, float, float, float]]] = {
        "employee_ssn": [body("a")], "employer_ein": [body("b")], "employer_name": [body("c")],
        "employee_name": [body("e_first"), body("e_last")], "15_state": [body("15")],
    }
    for key in ("1", "2", "3", "4", "5", "6", "7", "10", "11", "14", "16", "17", "18", "19", "20"):
        areas[key] = [body(key)]
    for key in ("12a", "12b", "12c", "12d"):
        x0, b, x1, t = body(key)
        areas[key] = [(x0, b, x0 + _CODE_W - 2.0, t), (x0 + _CODE_W, b, x1, t)]
    for i, (key, _) in enumerate(_BOX13):
        x0, top, x1, bottom = _box13_square(i)
        areas[key] = [(x0, PAGE_H - bottom, x1, PAGE_H - top)]
    return areas


def _watermark_png() -> bytes:
    """The diagonal watermark as a translucent RGBA image (an image, so the PDF's text layer stays the form's)."""
    import reportlab
    from PIL import Image, ImageDraw, ImageFont

    # Bitstream Vera Bold ships inside reportlab and has the em dash (Pillow's built-in font does not).
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "VeraBd.ttf"), 80)
    left, top, right, bottom = font.getbbox(WATERMARK)
    text = Image.new("RGBA", (right - left + 40, bottom - top + 40), (255, 255, 255, 0))
    ImageDraw.Draw(text).text((20 - left, 20 - top), WATERMARK, font=font, fill=(200, 30, 30, 64))
    rotated = text.rotate(26, expand=True, resample=Image.BICUBIC)
    buf = io.BytesIO()
    rotated.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# Embedded faces (registered from reportlab's own fonts directory): labels in Vera, values and headings in Vera Bold.
SANS, SANS_BOLD = "SampleVera", "SampleVera-Bold"


def _register_fonts() -> None:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, file in ((SANS, "Vera.ttf"), (SANS_BOLD, "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))


def render_pdf(path: Path, boxes: dict[str, str]) -> None:
    from reportlab.lib.colors import Color, black
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    _register_fonts()
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H), invariant=1, initialFontName=SANS)
    c.setTitle(f"SAMPLE Form W-2 ({TAX_YEAR}) - synthetic demo persona, not a real document")
    c.setAuthor("taxfill-mcp demo (synthetic)")
    c.setSubject("Demo W-2 for the TaxFill walkthrough; every name, number and identifier is fictitious")

    def y(top: float) -> float:
        return PAGE_H - top

    c.setFillColor(Color(0.75, 0.1, 0.1))
    c.setFont(SANS_BOLD, 7)
    c.drawString(_L, y(30.0), f"{WATERMARK}  •  synthetic demo persona for the TaxFill walkthrough: every name, "
                              "number and identifier is fictitious")
    c.setFillColor(black)
    c.setFont(SANS, 6)
    c.drawString(210.0, y(52.0), "OMB No. 1545-0029")

    shaded = Color(0.88, 0.88, 0.88)
    c.setLineWidth(0.6)
    for name, (label, x0, top, x1, bottom) in BOXES.items():
        if name == "9":
            c.setFillColor(shaded)
            c.rect(x0, y(bottom), x1 - x0, bottom - top, stroke=1, fill=1)
            c.setFillColor(black)
        else:
            c.rect(x0, y(bottom), x1 - x0, bottom - top, stroke=1, fill=0)
        c.setFont(SANS, 5.5)
        c.drawString(x0 + 2.0, y(top + 7.0), label)
        if name.startswith("12"):  # the code sub-box
            c.line(x0 + _CODE_W, y(bottom), x0 + _CODE_W, y(top + _LABEL_BAND))
    c.setFont(SANS, 4.0)
    for i, (key, label) in enumerate(_BOX13):
        x0, top, x1, bottom = _box13_square(i)
        c.drawCentredString((x0 + x1) / 2, y(top - 1.5), label)
        c.rect(x0, y(bottom), x1 - x0, bottom - top, stroke=1, fill=0)

    # Values in the bold face, set apart from the labels.
    def put(name: str, text: str, line: int = 0) -> None:
        _, x0, top, x1, bottom = BOXES[name]
        c.drawString(x0 + 4.0, y(top + _LABEL_BAND + 9.0 + line * 10.0), text)

    c.setFont(SANS_BOLD, 9)
    put("a", boxes["employee_ssn"])
    put("b", boxes["employer_ein"])
    for i, text in enumerate([PERSONA["employer_name"], *PERSONA["employer_address"]]):
        put("c", text, i)
    put("d", PERSONA["control_number"])
    put("e_first", PERSONA["employee_first"])
    put("e_last", PERSONA["employee_last"])
    for i, text in enumerate(PERSONA["employee_address"]):
        put("f", text, i)
    for key in ("1", "2", "3", "4", "5", "6", "7", "10", "11", "16", "17", "18", "19", "20"):
        if key in boxes:
            put(key, boxes[key])
    put("14", boxes["14"])
    put("15", boxes["15_state"])
    for key in ("12a", "12b", "12c", "12d"):
        if key in boxes:
            code, amount = boxes[key].split(" ", 1)
            _, x0, top, x1, bottom = BOXES[key]
            base = y(top + _LABEL_BAND + 9.0)
            c.drawString(x0 + 4.0, base, code)
            c.drawString(x0 + _CODE_W + 4.0, base, amount)
    for i, (key, _) in enumerate(_BOX13):
        if boxes.get(key) == "X":
            x0, top, x1, bottom = _box13_square(i)
            c.drawString(x0 + 2.0, y(bottom - 2.0), "X")

    # Footer, as on Copy B.
    c.setFont(SANS_BOLD, 13)
    c.drawString(_L, y(334.0), "Form W-2  Wage and Tax Statement")
    c.setFont(SANS_BOLD, 20)
    c.drawString(330.0, y(336.0), str(TAX_YEAR))
    c.setFont(SANS, 6.5)
    c.drawString(400.0, y(330.0), "Department of the Treasury—Internal Revenue Service")
    c.drawString(_L, y(348.0), "Copy B—To Be Filed With Employee's FEDERAL Tax Return.")
    c.drawString(_L, y(357.0), "This information is being furnished to the Internal Revenue Service.")
    c.setFillColor(Color(0.75, 0.1, 0.1))
    c.setFont(SANS_BOLD, 7)
    c.drawString(_L, y(378.0), f"{WATERMARK}. Generated by scripts/make_sample_w2.py for the TaxFill docs; "
                               "not issued by any employer, never file it.")

    mark = ImageReader(io.BytesIO(_watermark_png()))
    mw, mh = mark.getSize()
    scale = 470.0 / mw
    c.drawImage(mark, (PAGE_W - mw * scale) / 2 - 40.0, (PAGE_H - mh * scale) / 2 - 10.0, mw * scale, mh * scale,
                mask="auto")
    c.showPage()
    c.save()


def render_png(pdf_path: Path, png_path: Path, dpi: int = 144) -> None:
    """The PDF's page rendered by pypdfium2, palette-quantized to stay small, tagged with the PDF's sha256."""
    import pypdfium2 as pdfium
    from PIL import PngImagePlugin

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        image = doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()
    info = PngImagePlugin.PngInfo()
    info.add_text("Title", f"SAMPLE Form W-2 ({TAX_YEAR}) - synthetic demo persona, not a real document")
    info.add_text("Source", f"{PDF_NAME} sha256 {hashlib.sha256(pdf_path.read_bytes()).hexdigest()}")
    image.quantize(colors=64).save(png_path, format="PNG", optimize=True, pnginfo=info, dpi=(dpi, dpi))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="where to write the PDF and PNG (default docs/samples)")
    args = ap.parse_args(argv)
    boxes = w2_boxes()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    pdf, png = args.out_dir / PDF_NAME, args.out_dir / PNG_NAME
    render_pdf(pdf, boxes)
    render_png(pdf, png)
    for key, value in boxes.items():
        print(f"  box {key:<14} {value}")
    for p in (pdf, png):
        print(f"wrote {p.relative_to(REPO) if p.is_relative_to(REPO) else p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
