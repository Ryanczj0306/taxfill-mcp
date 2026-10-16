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

from taxfill_core.file_and_pay import (
    _F1040X_CITATION,
    FilingManifestItem,
    _as_list,
    _deadline_citation,
    _is_1040x,
    _is_amended,
    _is_individual_return,
    _is_nr_form,
    _is_standalone_8843,
    _pack_address_entry,
    _plus_years,
    _amended_pointer_citations,
    _refund_window_anchor,
    _STATE_REVENUE_SITES,
)
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
    household_rollup: list[str] = Field(
        default_factory=list,
        description=(
            "H2/N-2: when the manifest labels returns for 2+ taxpayers (an unmarried household is "
            "two taxpayers, one budget), per-person subtotals + the household net + the "
            "two-returns framing. Empty for a single-taxpayer filing."
        ),
    )
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
    if _is_standalone_8843(item):
        return _standalone_8843_item(item, today, pack)
    if _is_amended(item) and (_is_1040x(item.form) or _is_individual_return(item.form)):
        return _amended_federal_item(item, today, pack)
    citations: list[Citation] = []
    notes: list[str] = []
    refund = item.bottom_line if item.bottom_line > 0 else 0
    owed = -item.bottom_line if item.bottom_line < 0 else 0

    if refund:
        # No paper-check promise: the IRS is phasing paper refund checks out
        # (irs.gov/ModernPayments; file_and_pay carries the full note and citation).
        how = (
            " (direct deposit)"
            if item.direct_deposit
            else " (no direct deposit requested — paper refund checks are being phased out; see file_and_pay)"
        )
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
        citations.append(_deadline_citation(d, _is_nr_form(item.form)))
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


def _amended_federal_item(item: FilingManifestItem, today: date, pack) -> FilingSummaryItem:
    """Form 1040-X (Phase K JK27): the change in the bottom line, and the amended-return time limits.

    Before JK27 an amended item read as an original return: "you owe because the tax withheld did not cover your
    total tax", and "Past the <original> due date — late-filing/late-payment penalties" for a timely original.
    """
    y = item.tax_year
    refund = item.bottom_line if item.bottom_line > 0 else 0
    owed = -item.bottom_line if item.bottom_line < 0 else 0
    citations: list[Citation] = [_F1040X_CITATION]
    notes: list[str] = []
    due = pack.deadlines.filing_due_date if pack is not None and pack.deadlines is not None else None
    if refund:
        headline = f"Federal {y}, amended (Form 1040-X): a further refund of {_money(refund)} (by check if filed on paper)"
        plain = f"The corrected {y} return comes out more in your favor, so the IRS refunds the difference, with any interest it figures."
        deadline_status = (
            "Refund claim window: file Form 1040-X within 3 years after the original return was filed or 2 years "
            "after the tax was paid, whichever is later (Form 1040-X instructions, When To File)."
        )
        # An original filed early or on time "is considered filed on the due date (generally April 15)" (Form
        # 1040-X instructions, When To File): April 15, unless a postponement moved the due date itself.
        expiry = _plus_years(_refund_window_anchor(y, due), 3)
        if today.isoformat() <= expiry:
            deadline_status += f" For an original filed on time that is ~{expiry}."
        else:
            deadline_status = (
                f"⚠ For an original filed on time the 3-year window closed ~{expiry}; the refund survives only "
                f"if the original was filed later or the tax was paid within the last 2 years — confirm before "
                f"relying on it. " + deadline_status
            )
    elif owed:
        headline = f"Federal {y}, amended (Form 1040-X): you owe {_money(owed)} more"
        plain = f"The corrected {y} return leaves you owing more; you owe the difference."
        since = f" from the original {due} due date" if due else ""
        if due:
            citations.append(pack.deadlines.citation)
        until = "until it was paid (you paid online)." if item.paid_online else (
            "until it is paid (Form 1040-X instructions, Interest and Penalties); pay with the amended return or sooner.")
        deadline_status = f"Interest on the additional tax runs{since} {until}"
        if item.paid_online:
            notes.append("Already paid online — keep the confirmation number.")
    else:
        headline = f"Federal {y}, amended (Form 1040-X): no change in the amount owed or refunded"
        plain = "The correction does not change the amount you owe or are refunded."
        deadline_status = "No refund or balance due changes; file Form 1040-X to put the corrected return on record."
    return FilingSummaryItem(
        form=item.form, jurisdiction="federal", tax_year=y, headline=headline, refund=refund, owed=owed,
        plain_explanation=plain, deadline_status=deadline_status, citations=citations, notes=notes,
    )


def _standalone_8843_item(item: FilingManifestItem, today: date, pack) -> FilingSummaryItem:
    """Form 8843 filed by itself: an information return — no tax due, no refund,
    and NO monetary late penalties. The stake of filing late is losing the
    exempt-individual day exclusion the form documents (Form 8843 instructions),
    so the summary must not threaten late-payment penalties or interest."""
    citations: list[Citation] = []
    notes: list[str] = []
    headline = f"Federal {item.tax_year}: Form 8843 — information return, no tax due"
    plain = (
        "Form 8843 documents your exempt-individual days (it reports information only) — there is no tax to pay "
        "and no refund to claim."
    )
    # The pack's standalone-8843 entry carries the Form 8843 instructions citation.
    _, addr_citation = _pack_address_entry(pack, "f8843_standalone")
    if addr_citation:
        citations.append(addr_citation)
    deadline_status = ""
    if pack is not None and pack.deadlines is not None:
        d = pack.deadlines
        citations.append(_deadline_citation(d, is_nr=True))
        due = getattr(d, "nonwage_1040nr_due_date", None) or d.filing_due_date
        if today.isoformat() <= due:
            deadline_status = f"File by {due} — a standalone Form 8843 follows the Form 1040-NR due date."
        else:
            deadline_status = (
                f"Past the {due} due date — no tax is due on this information return, so there are no late-filing/"
                f"late-payment penalties or interest; file it as soon as possible, because filing late can cost "
                f"you the exempt-individual day exclusion it claims (Form 8843 instructions)."
            )
    else:
        notes.append(
            f"Deadline data for {item.tax_year} is not in the knowledge pack — a standalone Form 8843 follows "
            f"the Form 1040-NR due date; confirm it on irs.gov."
        )
    return FilingSummaryItem(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, headline=headline,
        refund=0, owed=0, plain_explanation=plain, deadline_status=deadline_status,
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
        a state item gets its bottom line plus the deadline and notes from its
        state knowledge pack (a confirm-at-the-DOR note where the pack has none).

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
    return FilingSummary(items=items, household_rollup=_household_rollup(manifest))


def _household_rollup(manifest: list[FilingManifestItem]) -> list[str]:
    """H2/N-2: per-person subtotals + the household net, when returns are labeled.

    The modal international-student household is an unmarried couple: TWO
    taxpayers, two returns, one budget. The roll-up is the household budget
    view, with the framing that stops the wrong conclusions: each person signs
    and files only their own return, and one person's refund never nets against
    the other's balance due at the IRS."""
    labeled = [m for m in manifest if m.taxpayer]
    people = sorted({m.taxpayer for m in labeled})
    if len(people) < 2:
        return []
    lines: list[str] = []
    for person in people:
        theirs = [m for m in labeled if m.taxpayer == person]
        subtotal = sum(m.bottom_line for m in theirs)
        parts = ", ".join(f"{m.form} {m.tax_year} ({m.jurisdiction}) {_signed(m.bottom_line)}" for m in theirs)
        lines.append(f"{person}: {parts} -> subtotal {_signed(subtotal)}")
    unlabeled = [m for m in manifest if not m.taxpayer]
    if unlabeled:
        lines.append(
            f"{len(unlabeled)} return(s) carry no taxpayer label and are EXCLUDED from the roll-up — "
            f"label every return when you want the household view."
        )
    household = sum(m.bottom_line for m in labeled)
    lines.append(f"HOUSEHOLD net (labeled returns): {_signed(household)}")
    lines.append(
        "One budget, TWO taxpayers: each person signs and files only their own return(s), and a "
        "refund on one return never offsets a balance due on the other person's — pay each balance "
        "due in full; the household net is a budgeting number, not an IRS position."
    )
    return lines


def _signed(n: int) -> str:
    return f"+{_money(n)} refund" if n > 0 else (f"-{_money(n)} owed" if n < 0 else "$0 balanced")


def _state_item(item: FilingManifestItem, knowledge_dir) -> FilingSummaryItem:
    refund = item.bottom_line if item.bottom_line > 0 else 0
    owed = -item.bottom_line if item.bottom_line < 0 else 0
    state = item.jurisdiction.split("/", 1)[1].upper() if "/" in item.jurisdiction else item.jurisdiction
    head = (f"{state} {item.tax_year}: refund {_money(refund)}" if refund
            else (f"{state} {item.tax_year}: you owe {_money(owed)}" if owed else f"{state} {item.tax_year}: balanced"))
    code = item.jurisdiction.split("/", 1)[1] if "/" in item.jurisdiction else ""
    citations, notes, deadline_status = [], [], "Confirm the state deadline at the state DOR."
    amended = _is_amended(item)
    if amended:
        head = head.replace(f"{state} {item.tax_year}:", f"{state} {item.tax_year}, amended ({item.form}):", 1)
        site = _STATE_REVENUE_SITES.get(state)
        where = f" on the {state} revenue department's site ({site})" if site else ""
        deadline_status = (
            f"An amended return's time limit is not the original due date: confirm it in the {state} instructions "
            f"for amended returns{where}."
        )
    try:
        sk = load_state_knowledge(code, item.tax_year, knowledge_dir)
        am = getattr(sk, "amended_return", None) or {}
        dl = {} if amended else (getattr(sk, "deadlines", None) or {})
        if amended and not am:
            citations.extend(_amended_pointer_citations(state))
        if amended and am:
            timing = _as_list(am.get("timing"))
            if timing:
                deadline_status = " ".join(timing)
            for raw in [am.get("citation"), *(am.get("citations") or [])]:
                if isinstance(raw, dict):
                    citations.append(Citation(**raw))
        if dl.get("filing_due_date"):
            deadline_status = f"Due {dl['filing_due_date']}."
            if dl.get("verification"):
                notes.append(f"Deadline: {dl['verification']}")
            if dl.get("citation"):
                citations.append(Citation(**dl["citation"]))
        if not sk.conforms_to_federal_treaties:
            notes.append(f"If any income was exempt from federal tax under a treaty: {state} does not conform to "
                         f"federal tax treaties — that income is still taxable to {state}.")
    except FileNotFoundError:
        from taxfill_core.statescope import _load_no_income_tax

        no_tax, _ = _load_no_income_tax(knowledge_dir)
        if code.upper() in no_tax:
            deadline_status = f"{state} levies no personal income tax — no state return to file."
            notes.append(deadline_status)
        else:
            notes.append(f"No '{item.jurisdiction}' knowledge pack for {item.tax_year} yet — confirm the bottom line and deadline at the state DOR.")
    return FilingSummaryItem(
        form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year, headline=head,
        refund=refund, owed=owed, plain_explanation="State bottom line — review against your state return.",
        deadline_status=deadline_status, citations=citations, notes=notes,
    )
