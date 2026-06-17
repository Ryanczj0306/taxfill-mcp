"""The last mile — dev plan section 9 (file & pay, first-class).

``file_and_pay(manifest)`` turns the final set of returns into a personalized,
human-readable checklist: how to pay, what to sign, how to assemble, where to
mail, what to keep, and the deadlines (due dates incl. the abroad automatic
2-month extension and Form 4868, plus the refund statute of limitations — the
later of 3 years from filing or 2 years from payment). Every jurisdiction/
payment fact comes from the cited knowledge pack (mailing addresses, payment
options, deadlines) — never invented.

v1 is federal-only (state where-to-file and portals ship with the state packs
in M5); a non-federal item returns a clear "ships in M5" note rather than a
guess.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import Citation, load_knowledge

__all__ = ["FilingManifestItem", "ReturnInstructions", "FilingInstructions", "file_and_pay"]


class FilingManifestItem(BaseModel):
    """One finished return in the filing."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. '1040', '1040-NR'.")
    tax_year: int
    jurisdiction: str = Field(default="federal", description="'federal' (v1) or 'states/<xx>' (M5).")
    bottom_line: int = Field(description="Signed: positive = refund, negative = amount owed, 0 = balanced.")
    paid_online: bool = Field(default=False, description="True if an owed balance was already paid electronically.")
    state: str | None = Field(default=None, description="Taxpayer's state (resolves the 1040 where-to-file address).")
    filing_jointly: bool = Field(default=False, description="MFJ — both spouses must sign.")
    direct_deposit: bool = Field(default=False, description="Refund requested by direct deposit.")
    attached_forms: list[str] = Field(default_factory=list, description="Forms attached to this return (e.g. ['8843']) — NOT separately signed.")


class ReturnInstructions(BaseModel):
    """The checklist for one return."""

    model_config = ConfigDict(extra="forbid")

    form: str
    jurisdiction: str
    tax_year: int
    bottom_line: str
    payment: list[str] = Field(default_factory=list)
    mailing_address: str | None = None
    sign: list[str] = Field(default_factory=list)
    assemble: list[str] = Field(default_factory=list)
    mail: list[str] = Field(default_factory=list)
    records: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FilingInstructions(BaseModel):
    """The whole filing's last-mile checklist."""

    model_config = ConfigDict(extra="forbid")

    returns: list[ReturnInstructions] = Field(default_factory=list)
    overall_notes: list[str] = Field(default_factory=list)


def _plus_years(iso: str, years: int) -> str:
    d = date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28).isoformat()


def _money(amount: int) -> str:
    return f"${abs(amount):,}"


def _federal_return(item: FilingManifestItem, knowledge_dir) -> ReturnInstructions:
    # Degrade gracefully for years whose knowledge pack isn't shipped yet (e.g.
    # back-filing 2019-2022 when only 2023 ships): the generic sign/assemble/
    # mail/records steps still apply; only address/payment/deadlines need the pack.
    try:
        pack = load_knowledge("federal", item.tax_year, knowledge_dir)
    except FileNotFoundError:
        pack = None
    citations: list[Citation] = []
    notes: list[str] = []
    if pack is None:
        notes.append(
            f"No federal knowledge pack for {item.tax_year} yet — the exact mailing address, payment wording, and "
            f"deadlines below could not be auto-resolved; confirm them on irs.gov (prior-year instructions at "
            f"https://www.irs.gov/pub/irs-prior/) before mailing."
        )
    is_nr = item.form.upper().replace(" ", "").startswith("1040-NR") or item.form.upper().replace(" ", "") == "1040NR"
    owes = item.bottom_line < 0
    refund = item.bottom_line > 0
    enclosing_check = owes and not item.paid_online

    # Bottom line (plain language).
    if refund:
        bottom = f"Refund of {_money(item.bottom_line)}" + (" by direct deposit." if item.direct_deposit else " by paper check.")
    elif owes:
        bottom = f"You owe {_money(item.bottom_line)}." + (" Already paid online." if item.paid_online else "")
    else:
        bottom = "Balanced — no refund and nothing owed."

    # Payment.
    payment: list[str] = []
    if owes and item.paid_online:
        payment.append("Balance already paid electronically — keep the confirmation number; do NOT enclose a check.")
    elif owes and pack is not None and pack.payment_options is not None:
        po = pack.payment_options
        citations.append(po.citation)
        free = [p.name for p in po.electronic if not p.fee]
        paid = [p.name for p in po.electronic if p.fee]
        if free:
            payment.append(f"Fastest/free: pay online via {', '.join(free)} (no processing fee).")
        if paid:
            payment.append(f"Card/digital wallet ({', '.join(paid)}) works but the processor charges a fee.")
        payment.append(
            f"By check or money order: make it payable to \"{po.check.payee}\". {po.check.memo}"
        )
        payment.append("Verify before sending: the tax year, the amount, and your SSN on the payment.")
    elif refund and item.direct_deposit:
        payment.append("Refund by direct deposit — double-check the routing and account numbers before filing; a wrong digit misroutes the refund.")

    # Mailing address (resolved from knowledge).
    mailing_address = None
    if pack is not None and pack.mailing_addresses is not None:
        ma = pack.mailing_addresses
        citations.append(ma.citation)
        if is_nr:
            mailing_address = ma.f1040nr.with_payment if enclosing_check else ma.f1040nr.no_payment
        elif item.state:
            try:
                pair = ma.f1040_for_state(item.state)
                mailing_address = pair.with_payment if enclosing_check else pair.no_payment
            except KeyError:
                notes.append(f"State {item.state!r} not found in the where-to-file table — confirm the address on irs.gov.")
        else:
            notes.append("No state given — the 1040 mailing address depends on your state; provide it to resolve the exact address.")

    # Sign.
    sign = ["Print the form pages and sign and date the return in ink."]
    if item.filing_jointly:
        sign.append("This is a joint return — BOTH spouses must sign and date it; a missing signature voids the filing.")
    for attached in item.attached_forms:
        sign.append(f"Form {attached} is attached to this return — do NOT sign it separately.")

    # Assemble.
    assemble = [
        "Print only the form pages (not the instruction pages), single-sided.",
        "Attach your W-2 and any 1099s that show federal withholding to the front.",
        "Order attachments by their 'Attachment Sequence No.' (top-right of each schedule).",
        "Do NOT staple; use a single paper clip if needed.",
    ]
    if enclosing_check:
        assemble.append("Put Form 1040-V and the check on top — do not attach the payment to the return.")

    # Mail.
    mail = [
        "Use one envelope per return (don't combine multiple years).",
        "Send by USPS Certified Mail with Return Receipt (PS Form 3800) and ask for a postmark — that receipt is your proof of timely filing; the IRS won't otherwise confirm receipt.",
    ]
    if mailing_address and mailing_address.strip().lower().find("p.o. box") != -1:
        mail.append("This is a P.O. Box address — it must go by USPS (private couriers like FedEx/UPS can't deliver to a PO box).")

    # Records.
    records = [
        "Photograph every signed page before mailing.",
        "Keep the certified-mail receipt and tracking number, plus any payment confirmation.",
        "Keep a copy of the return and your RECONCILIATION.md (your audit trail) for at least 3 years.",
    ]

    # Deadlines + refund statute of limitations.
    deadlines: list[str] = []
    if pack is not None and pack.deadlines is not None:
        d = pack.deadlines
        citations.append(d.citation)
        deadlines.append(f"Original due date for tax year {item.tax_year}: {d.filing_due_date}.")
        # A 1040-NR filer with no US-withholding wages is due the 15th day of the
        # 6th month (data-driven; the manifest may not flag "no US wages", so
        # frame it conditionally). Guarded by getattr — older packs may omit it.
        if is_nr:
            nonwage_due = getattr(d, "nonwage_1040nr_due_date", None)
            if nonwage_due:
                deadlines.append(
                    f"If you are a 1040-NR filer with no US-withholding wages, the return is due the 15th day of the "
                    f"6th month instead — for {item.tax_year} that is {nonwage_due}."
                )
        # Taxpayers abroad on the regular due date get an automatic 2-month
        # extension to file (interest still accrues from the April due date).
        abroad_date = getattr(d, "abroad_automatic_extension_date", None)
        if abroad_date:
            deadlines.append(
                f"If you are a taxpayer living/working abroad on the regular due date, you get an automatic 2-month "
                f"extension to file — to {abroad_date}; interest still accrues from the {d.filing_due_date} due date."
            )
        # Form 4868 extends the time to FILE, not the time to PAY.
        deadlines.append(
            "Need more time to file? Form 4868 (Application for Automatic Extension of Time To File) extends the time "
            "to FILE, NOT the time to PAY — pay any estimated balance by the original due date to avoid interest."
        )
        sol = d.refund_statute_of_limitations
        if refund:
            expiry = _plus_years(d.filing_due_date, sol.years_from_filing)
            years_from_payment = getattr(sol, "years_from_payment", None)
            later_of = (
                f"the later of {sol.years_from_filing} years from filing or {years_from_payment} years from payment"
                if years_from_payment is not None
                else f"{sol.years_from_filing} years from filing"
            )
            line = (
                f"Refund statute of limitations ({sol.authority}): claim within {later_of}. The {expiry} expiry shown "
                f"assumes on-time filing — a return filed before the due date is treated as filed on the due date. "
                f"File before then or the refund is forfeited."
            )
            note = getattr(sol, "note", None)
            if note:
                line += f" Note: {note}"
            deadlines.append(line)
        elif owes:
            # Scope the penalty warning to a balance owed (it is over-broad on a
            # balanced/on-time return). No invented dollar amounts.
            deadlines.append(
                "Filed late or paying late? Late-filing and late-payment penalties plus interest accrue from the due "
                "date; the IRS will bill these separately — expect that letter, it is not a scam."
            )

    # De-dup citations.
    seen, uniq = set(), []
    for c in citations:
        key = (c.source, c.url)
        if key not in seen:
            seen.add(key)
            uniq.append(c)

    return ReturnInstructions(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, bottom_line=bottom,
        payment=payment, mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail,
        records=records, deadlines=deadlines, citations=uniq, notes=notes,
    )


def file_and_pay(
    manifest: list[FilingManifestItem],
    *,
    knowledge_dir: str | Path | None = None,
) -> FilingInstructions:
    """Build the per-return last-mile checklist for a finished filing.

    Args:
        manifest: one :class:`FilingManifestItem` per finished return.
        knowledge_dir: override the knowledge directory (installed-wheel use).

    Returns:
        :class:`FilingInstructions` with a :class:`ReturnInstructions` per item.
        Federal items are fully resolved from the cited knowledge pack; a
        non-federal item returns a single note that state support ships in M5.

    Raises:
        ValueError: an empty manifest.
    """
    if not manifest:
        raise ValueError("file_and_pay needs at least one return in the manifest")

    returns: list[ReturnInstructions] = []
    for item in manifest:
        if item.jurisdiction == "federal":
            returns.append(_federal_return(item, knowledge_dir))
        else:
            returns.append(
                ReturnInstructions(
                    form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year,
                    bottom_line=("Refund of " + _money(item.bottom_line)) if item.bottom_line > 0
                    else (("You owe " + _money(item.bottom_line)) if item.bottom_line < 0 else "Balanced."),
                    notes=[f"State filing instructions for '{item.jurisdiction}' ship with the state knowledge pack (M5)."],
                )
            )

    overall: list[str] = [
        "This is a review draft — you are the filer: review every number, then sign and mail it yourself.",
    ]
    if len(manifest) > 1:
        overall.append("Mail each return in its OWN envelope, even if they go to the same address.")
    return FilingInstructions(returns=returns, overall_notes=overall)
