"""Bottom-line approval gate — dev plan section 2 (step 8) and section 12 (UX 1).

``filing_summary(manifest)`` produces the plain-language per-jurisdiction bottom
line — refund or owed, by when, with deadline + 3-year refund statute-of-
limitations status — that the user APPROVES before anything is printed (step 8).
It is deliberately concise and decision-focused; the how-to-pay / assemble /
mail detail is ``file_and_pay`` (step 9, after approval). Both take the same
:class:`FilingManifestItem` list so the agent passes one structure to both.

This is a review-draft summary: the human approves the bottom line, then signs
and files. Deadline status is computed against ``today`` (override for tests).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.file_and_pay import FilingManifestItem, _plus_years
from taxfill_core.knowledge import Citation, load_knowledge, load_state_knowledge

__all__ = ["FilingSummaryItem", "FilingSummary", "filing_summary"]


class FilingSummaryItem(BaseModel):
    """The bottom line for one return."""

    model_config = ConfigDict(extra="forbid")

    form: str
    jurisdiction: str
    tax_year: int
    headline: str = Field(description="Plain-language bottom line, e.g. 'Federal 2023: refund $1,600'.")
    refund: int = Field(default=0, ge=0)
    owed: int = Field(default=0, ge=0)
    plain_explanation: str = Field(description="One-sentence why, for a non-expert.")
    deadline_status: str = Field(description="Due date / refund statute-of-limitations status vs today.")
    citations: list[Citation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FilingSummary(BaseModel):
    """The whole filing's bottom line, for user approval before printing."""

    model_config = ConfigDict(extra="forbid")

    label: str = "REVIEW DRAFT — approve the bottom line before printing"
    items: list[FilingSummaryItem] = Field(default_factory=list)
    approval_prompt: str = Field(
        default=(
            "Review each bottom line above. This is a draft you approve, sign, and file yourself — "
            "nothing is printed or sent until you say so."
        )
    )


def _money(n: int) -> str:
    return f"${abs(n):,}"


def _federal_item(item: FilingManifestItem, today: date, knowledge_dir) -> FilingSummaryItem:
    try:
        pack = load_knowledge("federal", item.tax_year, knowledge_dir)
    except FileNotFoundError:
        pack = None
    citations: list[Citation] = []
    notes: list[str] = []
    refund = item.bottom_line if item.bottom_line > 0 else 0
    owed = -item.bottom_line if item.bottom_line < 0 else 0

    if refund:
        how = " (direct deposit)" if item.direct_deposit else " (paper check)"
        headline = f"Federal {item.tax_year}: refund {_money(refund)}{how}"
        plain = "You get money back because more tax was withheld/paid during the year than you actually owe."
    elif owed:
        headline = f"Federal {item.tax_year}: you owe {_money(owed)}"
        plain = "You owe because the tax withheld/paid during the year did not cover your total tax."
        if item.paid_online:
            notes.append("Already paid online — keep the confirmation number.")
    else:
        headline = f"Federal {item.tax_year}: balanced — no refund, nothing owed"
        plain = "Your withholding/payments matched your tax almost exactly."

    deadline_status = ""
    if pack is not None and pack.deadlines is not None:
        d = pack.deadlines
        citations.append(d.citation)
        due = d.filing_due_date
        if refund:
            sol = d.refund_statute_of_limitations
            expiry = _plus_years(due, sol.years_from_filing)
            if today.isoformat() <= expiry:
                deadline_status = (
                    f"Original due date {due}. Refund claim window is open until ~{expiry} "
                    f"({sol.years_from_filing}-year statute of limitations); file before then or the refund is forfeited."
                )
            else:
                deadline_status = (
                    f"⚠ Refund statute of limitations CLOSED ~{expiry} ({sol.authority}); a refund for "
                    f"{item.tax_year} is likely forfeited — confirm before relying on it."
                )
        else:
            if today.isoformat() <= due:
                deadline_status = f"Due {due}."
            else:
                deadline_status = (
                    f"Past the {due} due date — late-filing/late-payment penalties and interest accrue "
                    f"from then and the IRS will bill them separately (expect that letter)."
                )
    else:
        notes.append(
            f"Deadline/statute-of-limitations data for {item.tax_year} is not in the knowledge pack — "
            f"confirm dates on irs.gov."
        )

    return FilingSummaryItem(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, headline=headline,
        refund=refund, owed=owed, plain_explanation=plain, deadline_status=deadline_status,
        citations=citations, notes=notes,
    )


def filing_summary(
    manifest: list[FilingManifestItem],
    *,
    today: date | None = None,
    knowledge_dir: str | Path | None = None,
) -> FilingSummary:
    """Produce the per-jurisdiction bottom line for user approval before printing.

    Args:
        manifest: one :class:`FilingManifestItem` per finished return (same input
            as ``file_and_pay``).
        today: date used for deadline/statute-of-limitations status; defaults to
            the current date. Pass explicitly for deterministic output/tests.
        knowledge_dir: override the knowledge directory.

    Returns:
        A :class:`FilingSummary`: one concise bottom line per return + an
        approval prompt. Federal items resolve deadlines from the cited pack;
        non-federal items get a plain bottom line and a note (state in M5).

    Raises:
        ValueError: an empty manifest.
    """
    if not manifest:
        raise ValueError("filing_summary needs at least one return in the manifest")
    today = today or date.today()
    items: list[FilingSummaryItem] = []
    for item in manifest:
        if item.jurisdiction == "federal":
            items.append(_federal_item(item, today, knowledge_dir))
        else:
            items.append(_state_item(item, knowledge_dir))
    return FilingSummary(items=items)


def _state_item(item: FilingManifestItem, knowledge_dir) -> FilingSummaryItem:
    refund = item.bottom_line if item.bottom_line > 0 else 0
    owed = -item.bottom_line if item.bottom_line < 0 else 0
    state = item.jurisdiction.split("/", 1)[1].upper() if "/" in item.jurisdiction else item.jurisdiction
    head = (f"{state} {item.tax_year}: refund {_money(refund)}" if refund
            else (f"{state} {item.tax_year}: you owe {_money(owed)}" if owed else f"{state} {item.tax_year}: balanced"))
    code = item.jurisdiction.split("/", 1)[1] if "/" in item.jurisdiction else ""
    citations, notes, deadline_status = [], [], "Confirm the state deadline at the state DOR."
    try:
        sk = load_state_knowledge(code, item.tax_year, knowledge_dir)
        dl = getattr(sk, "deadlines", None) or {}
        if dl.get("filing_due_date"):
            deadline_status = f"Due {dl['filing_due_date']}."
            if dl.get("verification"):
                notes.append(f"Deadline: {dl['verification']}")
            if dl.get("citation"):
                citations.append(Citation(**dl["citation"]))
        if not sk.conforms_to_federal_treaties:
            notes.append(f"{state} does not conform to federal tax treaties — federally treaty-exempt income is still taxable here.")
    except FileNotFoundError:
        notes.append(f"No '{item.jurisdiction}' knowledge pack for {item.tax_year} yet — confirm the bottom line and deadline at the state DOR.")
    return FilingSummaryItem(
        form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year, headline=head,
        refund=refund, owed=owed, plain_explanation="State bottom line — review against your state return.",
        deadline_status=deadline_status, citations=citations, notes=notes,
    )
