"""Print-only ("hand-fill") form packs — the C3 fallback for forms with no widgets.

Some state returns ship as flat print-only PDFs: no AcroForm widgets and no XFA (e.g.
CT-1040, SC1040, HI N-11 for 2023 — introspect finds 0 fillable fields). They cannot be
filled programmatically. Instead of an AcroForm field map, a hand-fill pack is a LINE
MANIFEST: the form's printed lines in order, each with a human label, a type, and an
optional ``compute`` expression (the same arithmetic grammar the verifier uses for
relations). The engine (:func:`taxfill_core.handfill.hand_fill_worksheet`) computes every
derivable line from the taxpayer's confirmed inputs and emits a line->value worksheet the
filer transcribes onto the printed blank. No new dependency, and it never touches the
AcroForm pipeline (a hand-fill pack lives in its own ``handfill.yaml`` file).

OVERLAY COORDINATES (the ROADMAP C3 "positioned overlay filler", 2026-09). A line may
additionally carry an ``overlay`` block giving the printed entry box's position on the
blank. With coordinates, :func:`taxfill_core.overlay.stamp_overlay` draws the worksheet
value straight onto the page (base-14 Helvetica, merged over the flat blank); without
them the line stays a hand-written worksheet row. Coordinates are **PDF points in the
page's user space, origin bottom-left** — exactly the frame a content stream's ``Td``
uses and the frame ``taxfill locate`` reports label positions in (pdfium char boxes are
already in that space, unrotated even on a ``/Rotate`` page). They are authored from
``taxfill locate`` anchors and then vision-verified by rendering the stamped output;
``page`` is validated against the blank's page count at FILL time, not load time,
because the blank may not be cached when the pack loads.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core.schemas.formpack import Mailing

HandFillType = Literal["money", "text", "checkbox"]
OverlayAlign = Literal["left", "right"]

# Overlay rendering defaults (the values the CONVENTIONS document quotes).
DEFAULT_OVERLAY_FONT_SIZE = 9.0
DEFAULT_MONEY_ALIGN: OverlayAlign = "right"


class OverlayBox(BaseModel):
    """Where one line's value is stamped on the print blank (PDF points, origin bottom-left)."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page of the blank. Checked against the blank's page count at fill time.")
    x: float = Field(description="Left edge of the entry box, in PDF points from the page's left edge (user space).")
    y: float = Field(
        description=(
            "Text BASELINE, in PDF points from the page's bottom edge (user space, origin bottom-left — "
            "the same y a content stream's 'x y Td' takes). For a printed line label, 'taxfill locate' "
            "reports the label's tight box; its bottom (y0) IS the baseline for glyphs without descenders."
        )
    )
    w: float = Field(gt=0, description="Width of the entry box in points; right-aligned values end at x + w.")
    h: float | None = Field(
        default=None, gt=0,
        description="Optional box height in points (authoring aid for the vision check; not used to size text).",
    )
    align: OverlayAlign | None = Field(
        default=None,
        description="left|right. Default: money lines use the manifest's overlay_defaults.money_align (right); text/checkbox left.",
    )
    font_size: float | None = Field(
        default=None, gt=0,
        description="Point size (default: overlay_defaults.font_size, else 9). Shrinks toward a 6pt floor when the value is wider than w.",
    )
    comb: float | None = Field(
        default=None, gt=0,
        description=(
            "Cell pitch in points for per-character boxes (SSN/EIN/ZIP combs): character i is centred in "
            "[x + i*comb, x + (i+1)*comb]. Separators (spaces, hyphens) are dropped — a comb has no cell for "
            "them (pitfall P-001) — and a value with more characters than w/comb cells warns."
        ),
    )
    cells: list[float] | None = Field(
        default=None, min_length=1,
        description=(
            "Left edges (points) of per-character cells whose spacing is NOT uniform — an SSN printed 3-2-4 "
            "around pre-printed dashes, an MM-DD-YYYY date, digits either side of a pre-printed decimal point, "
            "a scanned form's one-character boxes: character i is centred in [cells[i], cells[i] + cell_w]. "
            "Separators (spaces, hyphens, slashes, points) are dropped — the form prints its own — and a value "
            "with more characters than cells warns. Needs cell_w; excludes comb; every cell lies in x .. x + w "
            "(Phase J JS4c)."
        ),
    )
    cell_w: float | None = Field(default=None, gt=0, description="Width of each `cells` cell, in points.")

    @model_validator(mode="after")
    def _cells_are_well_formed(self) -> "OverlayBox":
        if self.cells is None:
            if self.cell_w is not None:
                raise ValueError("overlay: cell_w is set without cells — give the cell left edges too")
            return self
        if self.comb is not None:
            raise ValueError("overlay: cells and comb are exclusive — cells lists uneven cells, comb a uniform pitch")
        if self.cell_w is None:
            raise ValueError("overlay: cells needs cell_w, the width of each cell")
        if any(b <= a for a, b in zip(self.cells, self.cells[1:])):
            raise ValueError(f"overlay: cells must be strictly increasing left edges, got {self.cells}")
        if self.cells[0] < self.x - 1e-6 or self.cells[-1] + self.cell_w > self.x + self.w + 1e-6:
            raise ValueError(
                f"overlay: the cells [{self.cells[0]:g} .. {self.cells[-1] + self.cell_w:g}] must lie inside the "
                f"declared box [{self.x:g} .. {self.x + self.w:g}] — the verdict reads that box"
            )
        return self


class OverlayDefaults(BaseModel):
    """Manifest-level overlay defaults (every OverlayBox may override them)."""

    model_config = ConfigDict(extra="forbid")

    font_size: float = Field(default=DEFAULT_OVERLAY_FONT_SIZE, gt=0)
    money_align: OverlayAlign = Field(default=DEFAULT_MONEY_ALIGN)


class PrintingRule(BaseModel):
    """One printing or legibility rule the tax agency publishes for this paper form, quoted verbatim (JS4b)."""

    model_config = ConfigDict(extra="forbid")

    quote: str = Field(description="The agency's own words, verbatim (whitespace normalised).")
    source: str = Field(description="Where it is printed, e.g. 'Form CT-1040 (Rev. 12/23), page 1'.")
    url: str = Field(description="The official document the quote was read from.")


class HandFillLine(BaseModel):
    """One printed line of a print-only form (no AcroForm widget to fill)."""

    model_config = ConfigDict(extra="forbid")

    line: str = Field(description="Logical line key (same grammar as pack fields), e.g. '1', '4b', 'name'.")
    label: str = Field(description="Human-readable printed line label the filer sees on the paper form.")
    type: HandFillType = Field(default="money")
    compute: str | None = Field(
        default=None,
        description=(
            "Arithmetic expression over OTHER line ids in the relation grammar "
            "(+ - * /, parentheses, max()/min()/sum(1a..1h)), e.g. 'max(0, 4 - 5)'. "
            "When set, the engine derives this line's value from earlier lines; when "
            "None, it is a value the taxpayer enters. Money lines only."
        ),
    )
    note: str | None = Field(default=None, description="Optional guidance shown next to the line on the worksheet.")
    overlay: OverlayBox | list[OverlayBox] | None = Field(
        default=None,
        description=(
            "Where to stamp this line's value on the print blank (see OverlayBox) — or a LIST of boxes when the "
            "form prints the same value in several places (the CT-1040's SSN in every page header): the value "
            "is stamped, and verified, in each. None = the line is hand-written from the worksheet; "
            "stamp_overlay lists it under hand_written_lines."
        ),
    )


    @property
    def boxes(self) -> list[OverlayBox]:
        """Every placement of this line (empty when it is hand-written)."""
        if self.overlay is None:
            return []
        return list(self.overlay) if isinstance(self.overlay, list) else [self.overlay]


class HandFillPack(BaseModel):
    """A print-only form's line manifest (a ``handfill.yaml``), one form/jurisdiction/year."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. 'N-11', 'CT-1040', 'SC1040'.")
    jurisdiction: str = Field(description="'states/<two-letter code>', e.g. 'states/hi'.")
    tax_year: int = Field(ge=1990, le=2100)
    render_mode: Literal["hand_fill"] = Field(
        default="hand_fill",
        description="Marks this as a print-only, hand-filled form (no AcroForm widgets to fill).",
    )
    source_url: str = Field(description="Official URL of the blank PDF to PRINT (never filled — flat/print-only).")
    pdf_sha256: str = Field(description="SHA-256 of the print blank (watched by the drift job like any pack).")
    lines: list[HandFillLine] = Field(min_length=1, description="The form's printed lines, in printed order.")
    mailing: Mailing | None = Field(default=None, description="Where-to-file (or None to defer to the knowledge layer).")
    signature_note: str | None = Field(
        default=None, description="Reminder that the printed form must be signed/dated in ink before mailing."
    )
    instructions: str | None = Field(
        default=None,
        description=(
            "Overrides the worksheet's default 'print the blank and hand-write the values' text. "
            "Needed for a pack whose form CANNOT be printed and filed: FinCEN Form 114 (the FBAR) is "
            "e-file only through the BSA E-Filing System, and irs.gov states that 'IRS will not "
            "accept paper filings on TD F 90-22.1 (obsolete) or a printed FinCEN Form 114 (for "
            "e-filing only)' — so the default instruction would tell a filer to do something that "
            "gets rejected. Leave unset for a print-only STATE form, where the default is correct."
        ),
    )
    printing_guidance: list[PrintingRule] = Field(
        default_factory=list,
        description=(
            "The agency's published rules for entries on the paper form (ink colour, one character per box, "
            "machine-printed entries), quoted verbatim with their source. stamp_overlay returns them with every "
            "stamp, so the agent checks the printed result against the agency's words (Phase J JS4b)."
        ),
    )
    min_font_size: float | None = Field(
        default=None, gt=0,
        description=(
            "The agency's minimum point size for machine-printed entries, when it publishes one: the overlay never "
            "shrinks a value below it. None of CT, HI, NM or SC publishes one for 2023 (JS4b)."
        ),
    )
    efile_only: bool = Field(
        default=False,
        description=(
            "The form is filed ONLY electronically — FinCEN Form 114 through the BSA E-Filing System — so its "
            "source_url is a reference document (FinCEN's line-item filing instructions), NOT a blank to print or "
            "stamp: fetch_blank and fill_form refuse it (Phase J JS4b). Requires `instructions`, which says where "
            "to file. Leave false for a print-only state form."
        ),
    )
    overlay_defaults: OverlayDefaults | None = Field(
        default=None,
        description="Manifest-wide overlay defaults (font_size, money_align); each line's overlay block may override.",
    )

    @model_validator(mode="after")
    def _efile_only_says_where_to_file(self) -> "HandFillPack":
        if self.efile_only and not self.instructions:
            raise ValueError(
                f"{self.form} {self.tax_year}: efile_only packs must set `instructions` — the worksheet's default "
                f"'print the blank and hand-write the values' text is wrong for a form that cannot be printed"
            )
        if self.efile_only and self.has_overlay_coordinates:
            raise ValueError(f"{self.form} {self.tax_year}: an efile_only pack has nothing to stamp — drop its overlay blocks")
        return self

    @property
    def has_overlay_coordinates(self) -> bool:
        """True when at least one line carries an ``overlay`` block (the fill_form routing test)."""
        return any(ln.overlay is not None for ln in self.lines)

    @property
    def overlay_lines(self) -> list[HandFillLine]:
        """The lines that will be stamped (those carrying coordinates), in printed order."""
        return [ln for ln in self.lines if ln.overlay is not None]
