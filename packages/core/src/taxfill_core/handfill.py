"""Hand-fill worksheet engine for print-only forms (C3 fallback).

A print-only state form (no AcroForm widgets — see :mod:`taxfill_core.schemas.handfill`)
can't be filled programmatically. This module turns the form's line manifest plus the
taxpayer's confirmed inputs into an ordered **line -> value worksheet**: every derivable
line is computed (via the shared relation-grammar evaluator), the rest are shown as
entered or left blank, and the filer transcribes the values onto the printed blank.

This is deliberately a SEPARATE path from the AcroForm filler — it produces a worksheet,
never a filled PDF — so it adds no risk to the fillable-form pipeline and no new deps.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.schemas.handfill import HandFillPack
from taxfill_core.verify import evaluate_expression

WorksheetSource = Literal["entered", "computed", "blank"]


class WorksheetLine(BaseModel):
    """One line of the hand-fill worksheet: what the filer writes on that printed line."""

    model_config = ConfigDict(extra="forbid")

    line: str
    label: str
    type: str
    value: str = Field(description="The value to hand-write ('' when blank/not applicable).")
    source: WorksheetSource = Field(description="'entered' (from your input), 'computed' (derived), or 'blank'.")
    note: str | None = None


class Worksheet(BaseModel):
    """A print-and-hand-fill worksheet for one print-only form."""

    model_config = ConfigDict(extra="forbid")

    label: str = "HAND-FILL WORKSHEET"
    form: str
    jurisdiction: str
    tax_year: int
    print_url: str = Field(description="Print this official blank and copy the values below onto it.")
    lines: list[WorksheetLine]
    signature_note: str | None = None
    instructions: str = (
        "This form has no fillable fields, so it cannot be filled electronically. "
        "Print the blank at print_url and hand-write each value below onto its line. "
        "'computed' values were derived from your confirmed inputs; verify before mailing."
    )


def load_hand_fill_pack(path: str | Path) -> HandFillPack:
    """Load and validate a print-only ``handfill.yaml`` pack from a file path."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return HandFillPack.model_validate(data)


def hand_fill_pack_path(form: str, year: int, jurisdiction: str, base_dir: str | Path | None = None) -> Path:
    """Resolve ``formpacks/<jurisdiction>/<year>/<form>/handfill.yaml`` (a print-only pack
    lives beside where an AcroForm ``pack.yaml`` would, under a different filename)."""
    from taxfill_core.datadir import formpacks_dir

    base = Path(base_dir) if base_dir is not None else formpacks_dir()
    return base / jurisdiction / str(year) / form / "handfill.yaml"


def load_hand_fill_pack_for(
    form: str, year: int, jurisdiction: str, *, base_dir: str | Path | None = None
) -> HandFillPack:
    """Load a print-only pack by (form, year, jurisdiction). Raises FileNotFoundError if none."""
    path = hand_fill_pack_path(form, year, jurisdiction, base_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"no hand-fill (print-only) pack for form '{form}', {jurisdiction} {year} — looked for {path}. "
            f"Hand-fill packs exist only for print-only state forms (no fillable AcroForm)."
        )
    return load_hand_fill_pack(path)


def _fmt_money(value: Decimal) -> str:
    """Whole-dollar, comma-grouped (IRS lines round to whole dollars)."""
    whole = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{whole:,}"


def hand_fill_worksheet(
    pack: HandFillPack, values: Mapping[str, object] | None = None
) -> Worksheet:
    """Build the line->value worksheet from a print-only pack + the filer's inputs.

    ``values`` maps line ids to entered values (money as number-like, text as str,
    checkbox as truthy). Money lines with a ``compute`` expression and no entered value
    are derived from earlier lines (blank refs count as 0, IRS-style). Lines are emitted
    in the pack's printed order; a ``compute`` may reference any earlier resolved line.
    """
    values = values or {}
    line_names = frozenset(ln.line for ln in pack.lines)
    resolved: dict[str, Decimal] = {}  # money values available to compute exprs
    out: list[WorksheetLine] = []

    for ln in pack.lines:
        provided = values.get(ln.line)
        if ln.type == "money":
            if provided is not None and str(provided).strip() != "":
                num = Decimal(str(provided).strip())
                resolved[ln.line] = num
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value=_fmt_money(num), source="entered", note=ln.note))
            elif ln.compute:
                num = evaluate_expression(ln.compute, resolved, line_names=line_names)
                resolved[ln.line] = num
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value=_fmt_money(num), source="computed", note=ln.note))
            else:
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="", source="blank", note=ln.note))
        else:  # text / checkbox — never computed, just echoed
            if provided is not None and str(provided).strip() != "":
                shown = "X" if ln.type == "checkbox" else str(provided)
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value=shown, source="entered", note=ln.note))
            else:
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="", source="blank", note=ln.note))

    return Worksheet(
        form=pack.form, jurisdiction=pack.jurisdiction, tax_year=pack.tax_year,
        print_url=pack.source_url, lines=out, signature_note=pack.signature_note,
    )
