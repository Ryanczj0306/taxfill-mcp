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

Special federal items with their own paths: a standalone Form 8843 (information
return, fixed Austin address), a return filed WITH Form W-7 (the Austin ITIN
Operation), and — Phase G item G6 — a Form 843 FICA withheld-in-error claim
(form '843' with attached_forms ['8316']): a separate mailing to the Ogden
service center per the current Pub 519 ch. 8, never attached to the 1040-NR.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from taxfill_core.knowledge import Citation, load_knowledge, load_state_knowledge

__all__ = ["FilingManifestItem", "ReturnInstructions", "FilingInstructions", "file_and_pay"]

# USPS two-letter codes -> full names (50 states + DC). The where-to-file tables
# in the knowledge packs key on full names, but the rest of the product (profile,
# state_scope) standardizes on two-letter codes — accept both.
_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _expand_state(state: str) -> str:
    """Map a USPS two-letter code to the full name the where-to-file table uses;
    anything else passes through unchanged (full names already match)."""
    return _STATE_NAMES.get(state.strip().upper(), state)


def _is_nr_form(form: str) -> bool:
    """True for a Form 1040-NR item ('1040-NR', '1040NR', or the pack key 'f1040nr')."""
    f = form.upper().replace(" ", "").replace("-", "")
    if f.startswith("F1040NR"):
        f = f[1:]
    return f.startswith("1040NR")


def _is_w7(name: str) -> bool:
    """True for Form W-7 in any spelling ('W-7', 'W7', or the pack key 'fw7')."""
    return name.upper().replace(" ", "").replace("-", "") in ("W7", "FW7", "FORMW7")


def _filing_includes_w7(item: "FilingManifestItem") -> bool:
    """Form W-7 anywhere in the package: attached to the return, or as the item itself."""
    return _is_w7(item.form) or any(_is_w7(f) for f in item.attached_forms)


def _is_standalone_8843(item: "FilingManifestItem") -> bool:
    """A Form 8843 filed by ITSELF (information only — no return, no tax bottom line)."""
    f = item.form.upper().replace(" ", "").replace("-", "")
    return f in ("8843", "F8843", "FORM8843") and not item.bottom_line


def _is_843(form: str) -> bool:
    """True for Form 843 in any spelling ('843', 'f843', 'Form 843')."""
    return form.upper().replace(" ", "").replace("-", "") in ("843", "F843", "FORM843")


def _is_8316(name: str) -> bool:
    """True for Form 8316 in any spelling ('8316', 'f8316', 'Form 8316')."""
    return name.upper().replace(" ", "").replace("-", "") in ("8316", "F8316", "FORM8316")


def _pack_address_entry(pack, key: str) -> tuple[str | None, Citation | None]:
    """Read a fixed-address extra entry ({address, citation}) from the pack's
    mailing_addresses block. These entries (ITIN Operation, standalone 8843) are
    open extras on the schema, so they arrive as raw dicts — validate the citation
    here and degrade to None rather than crash on a malformed pack."""
    if pack is None or pack.mailing_addresses is None:
        return None, None
    entry = getattr(pack.mailing_addresses, key, None)
    if not isinstance(entry, dict) or not entry.get("address"):
        return None, None
    citation = None
    raw = entry.get("citation")
    if isinstance(raw, dict):
        try:
            citation = Citation(**raw)
        except ValidationError:
            citation = None
    return str(entry["address"]), citation


def _deadline_citation(d, is_nr: bool) -> Citation:
    """Deadlines citation for the item's form family: the pack's primary citation
    (the year's Form 1040 instructions) for a plain 1040; the 1040-NR instructions
    (``citation_1040nr``, an open extra on the deadlines block) for 1040-NR items.
    Falls back to the primary citation when a pack has no NR-specific one."""
    if is_nr:
        raw = getattr(d, "citation_1040nr", None)
        if isinstance(raw, dict):
            try:
                return Citation(**raw)
            except ValidationError:
                pass
    return d.citation


def _form_aware_memo(memo: str, item: "FilingManifestItem") -> str:
    """The pack's check memo quotes the plain-1040 wording (e.g. 'Write "2023 Form
    1040" (or "2023 Form 1040-SR")'). A 1040-NR filer must write "<year> Form
    1040-NR" on the payment (Form 1040-V instructions) — substitute the actual
    form; if a pack's phrasing is unrecognized, append an explicit correction
    rather than silently keeping the wrong form name."""
    if not _is_nr_form(item.form):
        return memo
    y = item.tax_year
    target = f'"{y} Form 1040-NR"'
    for pattern in (
        f'"{y} Form 1040" (or "{y} Form 1040-SR")',
        f'"{y} Form 1040" or "{y} Form 1040-SR"',
        f'"{y} Form 1040"',
    ):
        if pattern in memo:
            return memo.replace(pattern, target)
    return memo + f" You are filing Form 1040-NR — write {target} on the payment, not \"Form 1040\"."


# The §6013(g)/(h) election last mile. The page is the IRS's own "how to make the
# choice" instruction set (verified live before pinning); it is cited inline in the
# checklist string too, since text-only guidance must remain followable on its own.
_SECTION_6013_URL = "https://www.irs.gov/individuals/international-taxpayers/nonresident-spouse"
_SECTION_6013_CITATION = Citation(
    source="IRS — Nonresident spouse (how to make the §6013(g)/(h) election, 'Attach a statement')",
    url=_SECTION_6013_URL,
)

# The FICA-withheld-in-error claim last mile (G6, Forms 843 + 8316). The address
# was VERIFIED LIVE against the current Pub 519 (2025 edition, HTTP 200, text
# extracted) before pinning: chapter 8, "Refund of Taxes Withheld in Error",
# prints an unconditional "Send Form 843 (with attachments) to:" followed by the
# Ogden service center — the older where-you-filed-the-return rule is GONE from
# the current edition, so the address is a fixed value, not a conditional one.
# Refund claims follow the CURRENT procedures regardless of the tax period
# claimed; the checklist still tells the filer to re-confirm in Pub 519 ch. 8
# because the IRS revises the publication annually.
_FICA_CLAIM_ADDRESS = "Department of the Treasury, Internal Revenue Service Center, Ogden, UT 84201-0038"
_FICA_CLAIM_CITATION = Citation(
    source=(
        "IRS Publication 519 (2025), ch. 8, 'Refund of Taxes Withheld in Error' — send Form 843 with "
        "attachments to the Ogden service center; attachment list (W-2 copy, visa, I-94, I-20/DS-2019, "
        "employer statement or Form 8316) from the same section (verified live before pinning)"
    ),
    url="https://www.irs.gov/pub/irs-pdf/p519.pdf",
)

# The dual-status last mile (G5). The page is the IRS's own dual-status filing
# instruction set — the "Dual-Status Return"/"Dual-Status Statement" annotations,
# the no-standard-deduction rule, and the sign-the-return rule (verified live,
# HTTP 200, before pinning); cited inline in the checklist strings too.
_DUAL_STATUS_URL = "https://www.irs.gov/individuals/international-taxpayers/taxation-of-dual-status-individuals"
_DUAL_STATUS_CITATION = Citation(
    source=(
        "IRS — Taxation of dual-status individuals (write 'Dual-Status Return' across the top, attach "
        "the statement marked 'Dual-Status Statement', no standard deduction)"
    ),
    url=_DUAL_STATUS_URL,
)


def _dedupe_citations(citations: list[Citation]) -> list[Citation]:
    seen, uniq = set(), []
    for c in citations:
        key = (c.source, c.url)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


class FilingManifestItem(BaseModel):
    """One finished return in the filing."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. '1040', '1040-NR'.")
    tax_year: int
    jurisdiction: str = Field(default="federal", description="'federal' (v1) or 'states/<xx>' (M5).")
    bottom_line: int = Field(description="Signed: positive = refund, negative = amount owed, 0 = balanced.")
    paid_online: bool = Field(default=False, description="True if an owed balance was already paid electronically.")
    state: str | None = Field(default=None, description="Taxpayer's state — two-letter USPS code ('CA') or full name ('California'); resolves the 1040 where-to-file address.")
    filing_jointly: bool = Field(default=False, description="MFJ — both spouses must sign.")
    direct_deposit: bool = Field(default=False, description="Refund requested by direct deposit.")
    attached_forms: list[str] = Field(default_factory=list, description="Forms attached to this return (e.g. ['8843', 'W-7']; ['8316'] on a Form 843 FICA claim). Most attachments are not separately signed; Form W-7 IS — the applicant signs its own Sign Here block — and so is Form 8316 (its own page-1 signature area).")
    section_6013_election: bool = Field(
        default=False,
        description=(
            "True when this joint return carries a §6013(g)/(h) election (a nonresident-alien spouse treated "
            "as a U.S. resident): the FIRST joint return under the election must have the election statement "
            "— signed by BOTH spouses, with each spouse's name, address, and SSN/ITIN — attached."
        ),
    )
    dual_status: bool = Field(
        default=False,
        description=(
            "True when this is a DUAL-STATUS return (a split residency year): the assembly checklist then "
            "leads with writing 'Dual-Status Return' across the top of the return, attaching the other-status "
            "return (1040-NR for a 1040 return, 1040 for a 1040-NR return) marked 'Dual-Status Statement', "
            "the no-standard-deduction reminder, and the sign-the-RETURN-not-the-statement rule. "
            "MUTUALLY EXCLUSIVE with section_6013_election (the election makes the couple full-year "
            "residents — an ordinary joint 1040; a dual-status return cannot be joint)."
        ),
    )

    @model_validator(mode="after")
    def _dual_status_and_6013_are_alternatives(self) -> "FilingManifestItem":
        if self.dual_status and self.section_6013_election:
            raise ValueError(
                "dual_status and section_6013_election cannot both be set on one return: the "
                "§6013(g)/(h) election treats BOTH spouses as U.S. residents for the ENTIRE year, "
                "so the return is an ordinary full-year joint Form 1040 (drop dual_status and keep "
                "the election), while a true dual-status year cannot be a joint return at all "
                "(Pub 519 ch. 6 restrictions) — pick the one that matches the recorded position"
            )
        return self


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
    if _is_standalone_8843(item):
        return _standalone_8843_return(item, pack, notes)
    if _is_843(item.form):
        return _form_843_return(item, pack, notes)
    is_nr = _is_nr_form(item.form)
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
            f"By check or money order: make it payable to \"{po.check.payee}\". {_form_aware_memo(po.check.memo, item)}"
        )
        payment.append("Verify before sending: the tax year, the amount, and your SSN on the payment.")
    elif refund and item.direct_deposit:
        payment.append("Refund by direct deposit — double-check the routing and account numbers before filing; a wrong digit misroutes the refund.")
    elif owes and pack is not None and pack.payment_options is None:
        # Pack loaded but the payment-options block is absent (a partial pack):
        # don't silently emit empty payment guidance — point to irs.gov.
        notes.append(
            f"The federal payment options (check payee wording and online-payment details) for {item.tax_year} are not "
            f"in the knowledge pack — confirm them on irs.gov (prior-year instructions at "
            f"https://www.irs.gov/pub/irs-prior/) before paying."
        )

    # Mailing address (resolved from knowledge). A return filed WITH a Form W-7
    # overrides the whole table: the package (return + W-7 + the applicant's
    # identity documents) goes to the Austin ITIN Operation, regardless of the
    # filer's state and regardless of payment (Form W-7 instructions).
    mailing_address = None
    if _filing_includes_w7(item):
        itin_address, itin_citation = _pack_address_entry(pack, "itin_w7_with_return")
        if itin_address:
            mailing_address = itin_address
            if itin_citation:
                citations.append(itin_citation)
            notes.append(
                "Form W-7 is filed with this return, so mail the WHOLE package — return, Form W-7, and the "
                "applicant's original (or certified) identity documents — to the IRS ITIN Operation in Austin. "
                "Returns with a W-7 attached go there regardless of your state and whether a payment is enclosed "
                "(Form W-7 instructions); do NOT use the normal where-to-file address."
            )
        else:
            notes.append(
                "This filing includes Form W-7: mail it to the IRS ITIN Operation in Austin, NOT the normal "
                "where-to-file address — the ITIN Operation address is not in this year's knowledge pack, so "
                "confirm it in the Form W-7 instructions (https://www.irs.gov/instructions/iw7) before mailing."
            )
    elif pack is not None and pack.mailing_addresses is not None:
        ma = pack.mailing_addresses
        citations.append(ma.citation)
        if is_nr:
            mailing_address = ma.f1040nr.with_payment if enclosing_check else ma.f1040nr.no_payment
        elif item.state:
            try:
                pair = ma.f1040_for_state(_expand_state(item.state))
                mailing_address = pair.with_payment if enclosing_check else pair.no_payment
            except KeyError:
                notes.append(
                    f"State {item.state!r} not found in the where-to-file table — pass the two-letter USPS code "
                    f"(e.g. 'CA') or the full state name (e.g. 'California'); for a foreign address, U.S. "
                    f"territory, or APO/FPO use the foreign/territory row, or confirm the address on irs.gov."
                )
        else:
            notes.append("No state given — the 1040 mailing address depends on your state; provide it to resolve the exact address.")
    elif pack is not None and pack.mailing_addresses is None:
        # Pack loaded but the where-to-file block is absent (a partial pack):
        # don't silently return mailing_address=None with no explanation.
        notes.append(
            f"The where-to-file mailing address for {item.tax_year} is not in the knowledge pack — confirm it on "
            f"irs.gov (prior-year instructions at https://www.irs.gov/pub/irs-prior/) before mailing."
        )

    # Sign.
    sign = ["Print the form pages and sign and date the return in ink."]
    if item.filing_jointly:
        sign.append("This is a joint return — BOTH spouses must sign and date it; a missing signature voids the filing.")
    for attached in item.attached_forms:
        if _is_w7(attached):
            # Form W-7 is the exception among attachments: its own 'Sign Here'
            # block MUST be signed by the ITIN applicant even when the W-7 rides
            # attached to the return (an unsigned W-7 is rejected by the ITIN
            # unit, which holds up the whole return).
            sign.append(
                f"Form {attached} IS signed separately even though it is attached: the ITIN applicant must sign "
                f"and date the W-7's own 'Sign Here' block in ink (and include a daytime phone number) — an "
                f"unsigned W-7 is rejected by the ITIN unit and holds up the whole return."
            )
        else:
            sign.append(f"Form {attached} is attached to this return — do NOT sign it separately.")

    # Assemble.
    attach_docs = (
        "Attach a copy of every Form W-2, 1042-S, and any 1099s that show federal withholding to the front — "
        "the 1040-NR requires the 1042-S copies attached (they also substantiate any treaty claim)."
        if is_nr
        else "Attach your W-2 and any 1099s that show federal withholding to the front."
    )
    assemble = [
        "Print only the form pages (not the instruction pages), single-sided.",
        attach_docs,
        "Order attachments by their 'Attachment Sequence No.' (top-right of each schedule).",
        "Do NOT staple; use a single paper clip if needed.",
    ]
    if enclosing_check:
        assemble.append("Put Form 1040-V and the check on top — do not attach the payment to the return.")

    # §6013(g)/(h) election statement — the compliance item that makes the joint
    # election valid at all: a joint return with a nonresident-alien spouse mailed
    # WITHOUT the signed statement is not a valid joint return, so it leads the
    # assembly checklist rather than hiding among the generic steps.
    if item.section_6013_election:
        assemble.insert(0, (
            "ATTACH THE §6013(g)/(h) ELECTION STATEMENT — required on the first joint return under the "
            "election: a statement, SIGNED BY BOTH SPOUSES, declaring that on the last day of the tax year "
            "one spouse was a nonresident alien and the other a U.S. citizen or resident, and that both "
            "choose to be treated as U.S. residents for the entire tax year, with each spouse's full name, "
            f"address, and SSN/ITIN ({_SECTION_6013_URL}). A joint return with a nonresident-alien spouse "
            "is NOT a valid joint return without this statement."
        ))
        sign.append(
            "The §6013(g)/(h) election statement is signed by BOTH spouses too — sign it in ink along with "
            "the return itself."
        )
        citations.append(_SECTION_6013_CITATION)

    # Dual-status year (G5): the split-year annotations LEAD the assembly checklist —
    # a dual-status package without them is processed as an ordinary return, which is
    # exactly the error the annotations exist to prevent. The statement is the
    # OTHER-status return: 1040-NR statement on a 1040 return (arrival year), 1040
    # statement on a 1040-NR return (departure year).
    if item.dual_status:
        statement_form = "Form 1040" if is_nr else "Form 1040-NR"
        statement_part = "resident" if is_nr else "nonresident"
        assemble[0:0] = [
            f'Write "Dual-Status Return" across the top of the Form {item.form} — it marks the split '
            f"residency year for IRS processing ({_DUAL_STATUS_URL}).",
            f'Attach {statement_form} as the DUAL-STATUS STATEMENT for the {statement_part} part of the '
            f'year, with "Dual-Status Statement" written across its top.',
            "Reminder: NO standard deduction on a dual-status return — deductions must be itemized; "
            "double-check the deduction line before printing (Pub 519 ch. 6).",
        ]
        sign.append(
            f'Sign the Form {item.form} (the dual-status RETURN) only — the attached {statement_form} '
            f'marked "Dual-Status Statement" is NOT signed separately; your signature on the return '
            f"covers the whole filing."
        )
        citations.append(_DUAL_STATUS_CITATION)

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
        citations.append(_deadline_citation(d, is_nr))
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
    elif pack is not None and pack.deadlines is None:
        # Pack loaded but the deadlines block is absent (a partial pack): don't
        # silently return an empty deadlines list with no due date or SOL window.
        notes.append(
            f"The filing due date, abroad extension, and refund statute-of-limitations window for {item.tax_year} are "
            f"not in the knowledge pack — confirm them on irs.gov (prior-year instructions at "
            f"https://www.irs.gov/pub/irs-prior/) before filing."
        )

    return ReturnInstructions(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, bottom_line=bottom,
        payment=payment, mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail,
        records=records, deadlines=deadlines, citations=_dedupe_citations(citations), notes=notes,
    )


def _standalone_8843_return(item: FilingManifestItem, pack, notes: list[str]) -> ReturnInstructions:
    """Form 8843 filed by ITSELF (no income-tax return required): an information
    return. Nothing is due and nothing is refunded, the mailing address is the
    fixed Austin service center (never state-dependent), the form IS signed when
    filed standalone, and late filing carries no monetary penalty — the risk is
    losing the exempt-individual day exclusion the form documents."""
    citations: list[Citation] = []
    bottom = "Form 8843 is an information return — no tax due and no refund; it documents your exempt-individual days."

    mailing_address, addr_citation = _pack_address_entry(pack, "f8843_standalone")
    if mailing_address:
        if addr_citation:
            citations.append(addr_citation)
        notes.append(
            "A standalone Form 8843 always mails to the Austin service center — the address does not depend on "
            "your state (Form 8843 instructions, 'When and Where To File')."
        )
    elif pack is not None:
        notes.append(
            f"The standalone Form 8843 mailing address for {item.tax_year} is not in the knowledge pack — confirm "
            f"it in the Form 8843 instructions (https://www.irs.gov/forms-pubs/about-form-8843) before mailing."
        )

    sign = [
        "Print Form 8843 and sign and date it in ink at the bottom of page 2 — the signature IS required when the "
        "8843 is filed by itself (it is only skipped when the 8843 rides attached to a Form 1040-NR)."
    ]
    assemble = [
        "Print only the form pages (not the instruction pages), single-sided.",
        "Nothing else goes in the envelope — a standalone Form 8843 has no payment and no income documents to attach.",
    ]
    mail = [
        "Use one envelope per return (don't combine multiple years).",
        "Send by USPS Certified Mail with Return Receipt (PS Form 3800) and ask for a postmark — that receipt is "
        "your proof of timely filing; the IRS won't otherwise confirm receipt.",
    ]
    records = [
        "Photograph every signed page before mailing.",
        "Keep the certified-mail receipt and tracking number.",
        "Keep a copy of the form and your RECONCILIATION.md (your audit trail) for at least 3 years.",
    ]

    deadlines: list[str] = []
    if pack is not None and pack.deadlines is not None:
        d = pack.deadlines
        citations.append(_deadline_citation(d, is_nr=True))
        due_line = f"File by the Form 1040-NR due date for tax year {item.tax_year}: {d.filing_due_date}"
        nonwage_due = getattr(d, "nonwage_1040nr_due_date", None)
        if nonwage_due:
            due_line += f" — or {nonwage_due} if you had no US-withholding wages (the usual case for a standalone 8843)"
        deadlines.append(due_line + ".")
        deadlines.append(
            "No tax is due with Form 8843, so filing late brings no late-payment penalty or interest — but it can "
            "cost you the exempt-individual day exclusion the form claims (Form 8843 instructions), so file it "
            "even if the due date has passed."
        )
    elif pack is not None:
        notes.append(
            f"The filing due date for {item.tax_year} is not in the knowledge pack — a standalone Form 8843 "
            f"follows the Form 1040-NR due date; confirm it on irs.gov before filing."
        )

    return ReturnInstructions(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, bottom_line=bottom,
        payment=[], mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail,
        records=records, deadlines=deadlines, citations=_dedupe_citations(citations), notes=notes,
    )


def _form_843_return(item: FilingManifestItem, pack, notes: list[str]) -> ReturnInstructions:
    """Form 843 claim — the FICA-withheld-in-error refund path (G6).

    An exempt F/J/M nonresident whose employer withheld Social Security/Medicare
    in error and will not refund it claims the money back on Form 843, with
    Form 8316 serving as the employer-refusal statement (Pub 519 ch. 8, 'Refund
    of Taxes Withheld in Error'). The claim is a SEPARATE filing: its own
    envelope, its own fixed address (the Ogden service center per the current
    Pub 519 — verified live before pinning), never attached to the 1040-NR.
    Both forms are signed (Form 843 on page 2 of the Rev. 12-2024 revision;
    Form 8316 in its own signature area at the bottom of page 1) — per the
    shipped f843/f8316 pack signature blocks.
    """
    citations: list[Citation] = [_FICA_CLAIM_CITATION]
    has_8316 = any(_is_8316(f) for f in item.attached_forms)

    claim = f" of {_money(item.bottom_line)}" if item.bottom_line > 0 else ""
    bottom = (
        f"Form 843 claim{claim} — refund of Social Security/Medicare (FICA) tax withheld in error"
        + (" (Form 8316 attached as the employer-refusal statement)." if has_8316 else ".")
    )
    if item.bottom_line <= 0:
        notes.append(
            "No claim amount in the manifest — Form 843 line 2 carries the amount to be refunded: "
            "W-2 box 4 (Social Security) + box 6 (Medicare) from each affected W-2, less anything "
            "the employer already repaid."
        )

    if has_8316:
        mailing_address = _FICA_CLAIM_ADDRESS
        notes.append(
            "A FICA withheld-in-error claim mails to the Ogden service center — the CURRENT Pub 519 "
            "(2025 edition), ch. 8 'Refund of Taxes Withheld in Error', prints this address "
            "unconditionally ('Send Form 843 (with attachments) to: ... Ogden, UT 84201-0038'); "
            "refund claims follow the current procedures regardless of the tax year claimed. The IRS "
            "revises Pub 519 annually — re-confirm the address in the current edition's ch. 8 before "
            "mailing (https://www.irs.gov/pub/irs-pdf/p519.pdf)."
        )
    else:
        mailing_address = None
        notes.append(
            "Where to file Form 843 depends on the CLAIM TYPE (Form 843 instructions, 'Where To "
            "File') — no address was resolved because this item does not carry Form 8316. For the "
            "FICA withheld-in-error employee claim, the current Pub 519 ch. 8 says the Ogden service "
            f"center ({_FICA_CLAIM_ADDRESS}), and an F/J/M visa holder attaches Form 8316 as the "
            "employer-refusal statement (add '8316' to attached_forms). For any OTHER Form 843 claim "
            "type, determine the address from the Form 843 instructions for that claim — never guess."
        )

    sign = [
        "Print Form 843 and sign and date it in ink on PAGE 2 (the Rev. 12-2024 revision's signature "
        "block; joint-return claims need BOTH spouses' signatures).",
    ]
    for attached in item.attached_forms:
        if _is_8316(attached):
            sign.append(
                "Form 8316 IS signed separately even though it rides in the same envelope: sign and "
                "date its own signature area at the bottom of page 1 in ink."
            )
        else:
            sign.append(f"Form {attached} is attached to this claim — do NOT sign it separately.")

    assemble = [
        "DO NOT attach this claim to your Form 1040-NR (or any income-tax return) — it is a SEPARATE "
        "claim, mailed in its own envelope to its own address.",
        "Check the Form 843 reason box for 'Refund to employee of social security, Medicare, or RRTA "
        "tax withheld in error ... employer will not adjust' (the pack line "
        "reason.ss_medicare_rrta_in_error), type of tax 'Employment' (line 4a), the tax period on "
        "line 1, the claimed amount (box 4 + box 6) on line 2, and explain the FICA exemption + the "
        "computation on line 8.",
        "Attach a copy of each Form W-2 showing the Social Security/Medicare tax withheld in error "
        "(it proves the amounts claimed).",
        "Attach a copy of your visa, and Form I-94 (or other documentation of your arrival/departure "
        "dates).",
        "F-1 or M-1 visa: attach a complete copy of Form I-20; J-1 visa: attach a copy of Form "
        "DS-2019; on OPT (optional practical training): attach Form I-766.",
        "Attach the employer's statement of any reimbursement paid and any credit/refund claimed or "
        "authorized — if you cannot get that statement, Form 8316 (or your own statement explaining "
        "why) serves in its place, saying the employer will not issue the refund.",
        "If you were FICA-exempt for only part of the year, attach pay statements covering the "
        "exempt period.",
    ]
    mail = [
        "Use its own envelope — never in the same envelope as a tax return (and one envelope per "
        "claim: prepare a separate Form 843 for each tax period).",
        "Send by USPS Certified Mail with Return Receipt (PS Form 3800) and ask for a postmark — "
        "that receipt is your proof of timely filing; the IRS won't otherwise confirm receipt.",
    ]
    records = [
        "Photograph every signed page (Form 843 AND Form 8316) before mailing.",
        "Keep copies of the whole claim package — the forms, the W-2s, and the visa/I-94/I-20 "
        "attachments — plus the certified-mail receipt and tracking number.",
        "Keep a copy with your RECONCILIATION.md (your audit trail) for at least 3 years.",
    ]

    deadlines: list[str] = []
    sol = pack.deadlines.refund_statute_of_limitations if pack is not None and pack.deadlines is not None else None
    if sol is not None:
        citations.append(pack.deadlines.citation)
        deadlines.append(
            f"Refund claim statute of limitations ({sol.authority}): file the claim within the later "
            f"of {sol.years_from_filing} years from when the related return was filed or "
            f"{getattr(sol, 'years_from_payment', 2)} years from when the tax was paid — after that "
            f"the refund is forfeited."
        )
    else:
        notes.append(
            f"The refund statute-of-limitations parameters for {item.tax_year} are not in the "
            f"knowledge pack — confirm the IRC 6511 claim window on irs.gov before assuming the "
            f"claim is still timely."
        )
    deadlines.append(
        "Do NOT use Form 843 for Additional Medicare Tax withheld in error — that is recovered on "
        "the income-tax return via Form 8959 (or an amended return), per Pub 519 ch. 8."
    )

    return ReturnInstructions(
        form=item.form, jurisdiction="federal", tax_year=item.tax_year, bottom_line=bottom,
        payment=[], mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail,
        records=records, deadlines=deadlines, citations=_dedupe_citations(citations), notes=notes,
    )


def _state_return(item: FilingManifestItem, knowledge_dir) -> ReturnInstructions:
    """Last-mile checklist for a state return, from the state knowledge pack.

    Logistics figures carry the pack's verification caveat (some state data could
    not be independently re-confirmed); they are surfaced with a 'confirm at the
    DOR' note rather than presented as fully verified.
    """
    state = item.jurisdiction.split("/", 1)[1] if "/" in item.jurisdiction else item.jurisdiction
    refund, owes = item.bottom_line > 0, item.bottom_line < 0
    bottom = (f"Refund of {_money(item.bottom_line)}" if refund
              else (f"You owe {_money(item.bottom_line)}." + (" Already paid." if item.paid_online else "")) if owes
              else "Balanced.")
    try:
        sk = load_state_knowledge(state, item.tax_year, knowledge_dir)
    except FileNotFoundError:
        from taxfill_core.statescope import _load_no_income_tax

        no_tax, _ = _load_no_income_tax(knowledge_dir)
        if state.upper() in no_tax:
            return ReturnInstructions(
                form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year, bottom_line=bottom,
                notes=[f"{state.upper()} levies no personal income tax — there is no state return to file or mail."],
            )
        return ReturnInstructions(
            form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year, bottom_line=bottom,
            notes=[f"No '{item.jurisdiction}' knowledge pack for {item.tax_year} yet — confirm where/how to "
                   f"file and the deadline at the state DOR (state support grows per dev plan section 6)."],
        )

    enclosing_check = owes and not item.paid_online
    citations: list[Citation] = []
    payment, mailing_address, deadlines, notes = [], None, [], []

    pay = getattr(sk, "payment", None) or {}
    if owes and item.paid_online:
        payment.append("Balance already paid — keep the confirmation; do not enclose a check.")
    elif owes and pay:
        if pay.get("web_pay_url"):
            payment.append(f"Pay online via {state.upper()} Web Pay: {pay['web_pay_url']} (no processor fee).")
        if pay.get("check_payee"):
            payment.append(f"By check: make it payable to \"{pay['check_payee']}\"; write the tax year, form, and your SSN on it.")

    ma = getattr(sk, "mailing_addresses", None) or {}
    if ma:
        mailing_address = ma.get("with_payment") if enclosing_check else ma.get("refund_or_no_payment")
        if ma.get("verification"):
            notes.append(f"Mailing address: {ma['verification']}")
        if ma.get("citation"):
            citations.append(Citation(**ma["citation"]))

    dl = getattr(sk, "deadlines", None) or {}
    if dl:
        if dl.get("filing_due_date"):
            deadlines.append(f"Due {dl['filing_due_date']}.")
        if dl.get("automatic_extension"):
            deadlines.append(dl["automatic_extension"])
        if dl.get("verification"):
            notes.append(f"Deadlines: {dl['verification']}")
        if dl.get("citation"):
            citations.append(Citation(**dl["citation"]))

    if not sk.conforms_to_federal_treaties:
        # Conditional wording (the manifest doesn't carry treaty status, unlike
        # state_scope which gates this on the profile) — true and useful whether
        # or not this filer actually has a treaty position.
        notes.append(f"If any of your income was exempt from federal tax under a treaty: {state.upper()} does not "
                     f"conform to federal tax treaties, so that income is still taxable to {state.upper()} — do not "
                     f"carry the federal exclusion onto the state return.")

    sign = ["Print the form pages, sign and date the return in ink."]
    if item.filing_jointly:
        sign.append("Joint return — BOTH spouses must sign.")
    return ReturnInstructions(
        form=item.form, jurisdiction=item.jurisdiction, tax_year=item.tax_year, bottom_line=bottom,
        payment=payment, mailing_address=mailing_address, sign=sign,
        assemble=["Print only the form pages (not instructions), single-sided; attach state copies of W-2/1099."],
        mail=["Use a separate envelope from the federal return.",
              "Certified Mail with Return Receipt gives you proof of timely filing."],
        records=["Photograph the signed pages; keep a copy and the mailing receipt."],
        deadlines=deadlines, citations=citations, notes=notes,
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
        Federal and supported-state items are resolved from the cited knowledge
        pack (state logistics carry a 'confirm at the DOR' caveat where the data
        could not be independently re-verified); an unsupported state returns a
        note to confirm at the state DOR.

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
            returns.append(_state_return(item, knowledge_dir))

    overall: list[str] = [
        "This is a review draft — you are the filer: review every number, then sign and mail it yourself.",
    ]
    if len(manifest) > 1:
        overall.append("Mail each return in its OWN envelope, even if they go to the same address.")
    return FilingInstructions(returns=returns, overall_notes=overall)
