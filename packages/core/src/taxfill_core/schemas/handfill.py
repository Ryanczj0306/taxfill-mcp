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
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.schemas.formpack import Mailing

HandFillType = Literal["money", "text", "checkbox"]


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
