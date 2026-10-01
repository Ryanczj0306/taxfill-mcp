"""Hand-fill worksheet engine for print-only forms (C3 fallback).

A print-only state form (no AcroForm widgets — see :mod:`taxfill_core.schemas.handfill`)
can't be filled programmatically. This module turns the form's line manifest plus the
taxpayer's confirmed inputs into an ordered **line -> value worksheet**: every derivable
line is computed (via the shared relation-grammar evaluator), the rest are shown as
entered or left blank, and the filer transcribes the values onto the printed blank.

This is deliberately a SEPARATE path from the AcroForm filler — it produces a worksheet,
never a filled PDF — so it adds no risk to the fillable-form pipeline and no new deps.
Since 2026-09 a manifest line may also carry ``overlay`` coordinates; then
:mod:`taxfill_core.overlay` stamps THIS worksheet's values onto the blank (it reuses
:func:`hand_fill_worksheet` rather than forking the evaluator), and the lines without
coordinates remain hand-written rows.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.redact import redact
from taxfill_core.schemas.handfill import HandFillLine, HandFillPack
from taxfill_core.verify import evaluate_expression

# The SAME yes/no vocabulary the AcroForm filler accepts (taxfill_core.filler's
# _checkbox_state), so a checkbox answer means one thing whichever pipeline the form goes
# through. A copy, not an import — this path never touches the filler (module docstring)
# — and test_handfill pins the two sets and their bool/0/1 handling equal so they cannot
# drift. Anything else is refused rather than guessed at: until 2026-09 any non-empty
# answer — "no", False, "0" — came back as a ticked "X", so a filer who answered no was
# told to tick the box on the printed state return, or on the FBAR keyed into the BSA
# E-Filing System.
_CHECKBOX_ON_WORDS = frozenset({"yes", "y", "true", "on", "x", "1", "checked"})
_CHECKBOX_OFF_WORDS = frozenset({"no", "n", "false", "off", "0", "unchecked", ""})

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
            f"no hand-fill pack for form '{form}', {jurisdiction} {year} — looked for {path}. "
            f"Hand-fill packs exist only where there is no fillable AcroForm to write into: the "
            f"print-only state returns (ct1040, n11, pit1, sc1040) and FinCEN Form 114, the FBAR "
            f"('fincen114', jurisdiction 'federal'), which is e-file only and has no PDF blank at "
            f"all."
        )
    return load_hand_fill_pack(path)


def _fmt_money(value: Decimal, *, grouped: bool = True) -> str:
    """Whole dollars (IRS lines round to whole dollars), comma-grouped unless the pack's money_style is plain."""
    whole = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if whole == 0:
        whole = abs(whole)  # Decimal('-0') would print as '-0'
    return f"{whole:,}" if grouped else f"{whole}"


class _OperandRecorder(dict):
    """The values mapping a compute is evaluated against, recording every line the evaluator resolved —
    the operands come from the evaluator's own lookups, never from a second tokenizer (P-029)."""

    def __init__(self, values: Mapping[str, Decimal]) -> None:
        super().__init__(values)
        self.seen: set[str] = set()

    def get(self, key, default=None):  # noqa: ANN001 - Mapping.get signature
        self.seen.add(key)
        return super().get(key, default)


def _checkbox_checked(ln: HandFillLine, provided: object) -> bool:
    """Interpret a checkbox answer; True = tick ('X'), False = leave the box empty."""
    if isinstance(provided, bool):
        return provided
    if isinstance(provided, int) and provided in (0, 1):
        return bool(provided)
    if isinstance(provided, str):
        word = provided.strip().lower()
        if word in _CHECKBOX_ON_WORDS:
            return True
        if word in _CHECKBOX_OFF_WORDS:
            return False
    raise ValueError(
        f"line {ln.line} ({ln.label!r}) is a checkbox — answer yes|no (or true|false); got "
        f"{redact(repr(provided))}. Omit the line to leave the box blank."
    )


def worksheet_money_values(ws: Worksheet, pack: HandFillPack | None = None) -> dict[str, Decimal]:
    """The worksheet's non-blank money lines as Decimals (for the independent recompute).

    With a ``pack`` whose ``blank_zero_computes`` is set, a computed money line the worksheet left
    blank (every operand blank — the form's tips forbid a 0 there) is reported as 0, so an
    independent recompute of 0 agrees with it instead of asking the caller to stamp the 0."""
    out: dict[str, Decimal] = {}
    computed = {ln.line for ln in pack.lines if ln.compute} if pack is not None and pack.blank_zero_computes else set()
    for ln in ws.lines:
        if ln.type == "money" and ln.value != "":
            out[ln.line] = Decimal(ln.value.replace(",", ""))
        elif ln.type == "money" and ln.line in computed:
            out[ln.line] = Decimal(0)  # blank by the form's rule, which means 0
    return out


def hand_fill_worksheet(
    pack: HandFillPack, values: Mapping[str, object] | None = None
) -> Worksheet:
    """Build the line->value worksheet from a print-only pack + the filer's inputs.

    ``values`` maps line ids to entered values (money as number-like, text as str,
    checkbox as yes/no — a bool, 0/1, or one of the filler's yes/no words; 'no' leaves
    the box empty and anything unrecognised raises, never truthiness). A line that is
    omitted or None is left blank. Money lines with a ``compute`` expression and no
    entered value are derived from earlier lines (blank refs count as 0, IRS-style; with the pack's
    ``blank_zero_computes`` a compute whose referenced lines are all blank and whose result is 0
    stays blank, and ``money_style: plain`` drops the thousands separators — P-029).
    Lines are emitted in the pack's printed order; a ``compute`` may reference any
    earlier resolved line.
    """
    values = values or {}
    line_names = frozenset(ln.line for ln in pack.lines)
    resolved: dict[str, Decimal] = {}  # money values available to compute exprs
    out: list[WorksheetLine] = []
    grouped = pack.money_style == "grouped"

    for ln in pack.lines:
        provided = values.get(ln.line)
        if ln.type == "money":
            if provided is not None and str(provided).strip() != "":
                raw = str(provided).strip()
                try:
                    num = Decimal(raw)
                except InvalidOperation:
                    raise ValueError(
                        f"line {ln.line} ({ln.label!r}) expects a money amount, got {redact(repr(raw))} — "
                        f"enter a number (or omit it to leave the line blank)"
                    )
                resolved[ln.line] = num
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value=_fmt_money(num, grouped=grouped), source="entered", note=ln.note))
            elif ln.compute:
                # Always evaluated (a malformed compute must raise when the worksheet is built from {}).
                probe = _OperandRecorder(resolved)
                num = evaluate_expression(ln.compute, probe, line_names=line_names)
                if pack.blank_zero_computes and num == 0 and not (probe.seen & resolved.keys()):
                    # Every line the compute looked at is blank and the result is 0: the form's tips want the
                    # line left blank, not a 0 (WV IT-140). Not added to `resolved`, so a later compute sees
                    # this line as blank too; a non-zero result (a literal term) still prints.
                    out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                             value="", source="blank", note=ln.note))
                else:
                    resolved[ln.line] = num
                    out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                             value=_fmt_money(num, grouped=grouped), source="computed", note=ln.note))
            else:
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="", source="blank", note=ln.note))
        elif ln.type == "checkbox":  # never computed: yes -> 'X', no/omitted -> empty box
            if provided is not None and _checkbox_checked(ln, provided):
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="X", source="entered", note=ln.note))
            else:
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="", source="blank", note=ln.note))
        else:  # text — never computed, just echoed
            if provided is not None and str(provided).strip() != "":
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value=str(provided), source="entered", note=ln.note))
            else:
                out.append(WorksheetLine(line=ln.line, label=ln.label, type=ln.type,
                                         value="", source="blank", note=ln.note))

    kwargs: dict[str, object] = {}
    if pack.instructions is not None:
        # A pack whose form cannot be printed and filed (the FBAR) supplies its own
        # instruction text; the class default is correct for the print-only state forms.
        kwargs["instructions"] = pack.instructions
    if pack.source_pages:
        # The blank lives inside a booklet or packet: say which pages are the form (JS5).
        pages = ", ".join(str(p) for p in pack.source_pages)
        kwargs["instructions"] = (
            f"The form is page(s) {pages} of the PDF at print_url (a booklet); print only those pages — "
            f"fill_form's stamped output holds just them. " + str(kwargs.get("instructions", Worksheet.model_fields["instructions"].default))
        )
    if pack.money_style == "plain" or pack.blank_zero_computes:
        # The form's own filing tips shape the worksheet: say so, so nobody "corrects" it by hand.
        tips = []
        if pack.money_style == "plain":
            tips.append("dollar amounts are printed WITHOUT commas")
        if pack.blank_zero_computes:
            tips.append("a computed line whose inputs are all blank is left blank, not 0 (leave out a line with no "
                        "amount rather than entering 0)")
        kwargs["instructions"] = (
            "As this form's filing tips require, " + " and ".join(tips) + ". "
            + str(kwargs.get("instructions", Worksheet.model_fields["instructions"].default))
        )
    return Worksheet(
        form=pack.form, jurisdiction=pack.jurisdiction, tax_year=pack.tax_year,
        print_url=pack.source_url, lines=out, signature_note=pack.signature_note,
        **kwargs,
    )
