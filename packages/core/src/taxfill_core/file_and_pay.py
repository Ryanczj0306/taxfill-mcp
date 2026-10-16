"""The last mile — dev plan section 9 (file & pay, first-class).

``file_and_pay(manifest)`` turns the final set of returns into a personalized,
human-readable checklist: how to pay, what to sign, how to assemble, where to
mail, what to keep, and the deadlines (due dates incl. the abroad automatic
2-month extension and Form 4868, plus the refund statute of limitations — the
later of 3 years from filing or 2 years from payment). Every jurisdiction/
payment fact comes from the cited knowledge pack (mailing addresses, payment
options, deadlines) — never invented.

A state item (``jurisdiction='states/<xx>'``) gets its checklist from that state's
knowledge pack, with a confirm-at-the-DOR note on its logistics figures; a state
with no knowledge pack for the year gets a note to confirm where and how to file
(or, with no income tax, that there is no return to file), rather than a guess.

Special federal items with their own paths: a standalone Form 8843 (information
return, fixed Austin address), a return filed WITH Form W-7 (the Austin ITIN
Operation), and — Phase G item G6 — a Form 843 FICA withheld-in-error claim
(form '843' with attached_forms ['8316']): a separate mailing to the Ogden
service center per the current Pub 519 ch. 8, never attached to the 1040-NR.

Amended returns (Phase K JK27) have their own model, because nothing about the
original return's mailing carries over: a Form 1040-X follows the CURRENT Form
1040-X instructions (a continuous-use form) for its address, payment, attachments
and timing, whatever year it amends; a state amended return follows the state
pack's ``amended_return`` block, and a state pack without one gets a pointer to
the DOR instead of the original return's address and due date.
"""
from __future__ import annotations

import re
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


def _is_8938(name: str) -> bool:
    """True for a Form 8938 attachment, however the caller spelled it."""
    return "8938" in re.sub(r"[^0-9A-Za-z]", "", name)


def _is_843(form: str) -> bool:
    """True for Form 843 in any spelling ('843', 'f843', 'Form 843')."""
    return form.upper().replace(" ", "").replace("-", "") in ("843", "F843", "FORM843")


def _is_8316(name: str) -> bool:
    """True for Form 8316 in any spelling ('8316', 'f8316', 'Form 8316')."""
    return name.upper().replace(" ", "").replace("-", "") in ("8316", "F8316", "FORM8316")


# Unicode hyphens and dashes a pasted form name may carry ("1040‑X", "1040–X").
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")
# Words a caller may put before the form number: "Form 1040-X", "IRS 1040-X", "Federal Form 1040-X", "U.S. 1040-X".
_NAME_PREFIXES = frozenset({"form", "irs", "federal", "us", "state"})
_STATE_CODES = frozenset(code.lower() for code in _STATE_NAMES)


def _form_number(name: str) -> str:
    """The form-number part of a form name: the text before the first comma, without the leading words above or a
    leading two-letter state code ('Form 1040-X, Amended ...' -> '1040-X'; 'IA 1040X' -> '1040X')."""
    head = name.translate(_DASHES).split(",", 1)[0]
    tokens = [t.strip(".;:()") for t in head.split()]
    while tokens and re.sub(r"[^a-z]", "", tokens[0].lower()) in _NAME_PREFIXES:
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[0].lower() in _STATE_CODES:
        tokens = tokens[1:]
    return " ".join(tokens)


def _form_token(name: str) -> str:
    """The first token of the form number: 'Form 1040-NR, U.S. ...' -> '1040-NR'."""
    number = _form_number(name)
    return number.split()[0] if number else ""


def _norm_form(name: str) -> str:
    """'Form 1040-X' / 'f1040x' / '1040 X' / 'IRS 1040-X' -> '1040x': the form number, lower-case letters and digits,
    a leading pack-key 'f' dropped."""
    f = re.sub(r"[^0-9a-z]", "", _form_number(name).lower())
    if f.startswith("f") and f[1:2].isdigit():
        return f[1:]
    return f


def _is_1040x(name: str) -> bool:
    """True for Form 1040-X in any spelling ('1040-X', '1040X', 'f1040x', 'Form 1040-X', 'IRS 1040 X')."""
    return _norm_form(name) == "1040x"


def _is_individual_return(name: str) -> bool:
    """True for the return a Form 1040-X corrects: Form 1040, 1040-SR, 1040-NR or 1040-NR-EZ, in any spelling."""
    return _norm_form(name) in ("1040", "1040sr", "1040nr", "1040nrez")


# An amended form number: digits (or a letter word and a hyphen) right before an X, then at most a revision suffix:
# '1040-X', '1040 X', '500X', 'IT-201-X', 'M1X', 'MI-1040X-12', 'PIT-X', Nebraska's '1040XN', 'RI-1040X-R'. A letter between the digits and the X does
# not count ('511-TX' is Oklahoma's credit for tax paid to another state). The whole number part is read, never the
# descriptive words after a comma: "Form M1, Individual Income Tax" ends in an x too, and the first cut of this rule
# (2026-10-16) read every Minnesota return as amended until the JK21 golden caught it; the final JK27 review then
# found names the first-token rule missed ('MI-1040X-12', 'IA 1040X', 'DR 0104X', '1040 X').
_AMENDED_NUMBER = re.compile(r"(?i)(?:^|[\s-])(?:[a-z]*-?\d+\s?-?x|[a-z]{2,}-x)(?:-\d{1,2}|n|-r|-nr)?$")


def _is_amended(item: "FilingManifestItem") -> bool:
    """An amended return: the manifest says so, or (when it is silent) the form number ends in X ('1040-X', '500X').

    Pass ``amended: true`` for every amended item: a state amended on its original form with a box, or a name this
    rule does not read, is otherwise checked as an original return.
    """
    if item.amended is not None:
        return item.amended
    return bool(_AMENDED_NUMBER.search(_form_number(item.form)))


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


def _unpublished_address_note(item: "FilingManifestItem", form: str, enclosing_check: bool) -> str:
    """JT2b: a planning year whose instructions have not printed this address yet — say so, never guess."""
    kind = "with-payment" if enclosing_check else "no-payment (refund / no check enclosed)"
    return (
        f"The {kind} {form} mailing address for {item.tax_year} is not published yet — it prints in the "
        f"{item.tax_year} {form} instructions, which are not posted. It is never carried from another year (the "
        f"2025 table moved every domestic box), so read it off the final instructions before mailing."
    )


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

_PUB_519_CITATION = Citation(
    source=(
        "IRS Publication 519, ch. 1, 'Amended return' — the §6013(g)/(h) choice made on a joint amended return "
        "(Form 1040-X): attach Form 1040 or 1040-SR, enter 'Amended' across the top, amend any later returns; "
        "file within 3 years of the original or 2 years of payment (read 2026-10-16)"
    ),
    url="https://www.irs.gov/publications/p519",
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


# The paper-refund-check phase-out (TY26-15). Read live 2026-09-25 at
# https://www.irs.gov/ModernPayments (it resolves to the newsroom page "Modernizing
# payments to and from America's bank account"): "In accordance with Executive Order
# 14247 ... This policy shift includes phase out of paper tax refund checks beginning
# Sept. 30, 2025, to the extent permitted by law." The FAQ that page links, FS-2026-02
# (Jan. 2026), Topic A: Q1 — "the IRS generally stopped issuing paper refund checks for
# individual taxpayers after Sept. 30, 2025" — keys the phase-out on when a refund is
# ISSUED, not on the tax year, so a back-filed earlier year gets the note too; Q5 says
# what happens instead (a CP53E notice, a slower refund, a paper check after six weeks
# with no response). A checklist that promises a paper check is wrong words for every
# return it is written for today.
_MODERN_PAYMENTS_URL = "https://www.irs.gov/ModernPayments"
_MODERN_PAYMENTS_CITATION = Citation(
    source=(
        "IRS — Modernizing payments to and from America's bank account (irs.gov/ModernPayments): under "
        "Executive Order 14247, the \"phase out of paper tax refund checks beginning Sept. 30, 2025, to "
        "the extent permitted by law\" (read 2026-09-25)"
    ),
    url=_MODERN_PAYMENTS_URL,
)
_FS_2026_02_URL = "https://www.irs.gov/pub/taxpros/fs-2026-02.pdf"
_FS_2026_02_CITATION = Citation(
    source=(
        "IRS FS-2026-02 (Jan. 2026), Questions and answers about Executive Order 14247, Topic A Q1 and Q5: "
        "paper refund checks generally stopped after Sept. 30, 2025; a refund filed without banking "
        "information gets a CP53E notice and \"could take longer to process\" (read 2026-09-25)"
    ),
    url=_FS_2026_02_URL,
)


_W7_PACKAGE_NOTE = (
    "Form W-7 is filed with this return, so mail the WHOLE package — return, Form W-7, and the "
    "applicant's original (or certified) identity documents — to the IRS ITIN Operation in Austin. "
    "Returns with a W-7 attached go there regardless of your state and whether a payment is enclosed "
    "(Form W-7 instructions); do NOT use the normal where-to-file address."
)
_W7_NO_ADDRESS_NOTE = (
    "This filing includes Form W-7: mail it to the IRS ITIN Operation in Austin, NOT the normal "
    "where-to-file address — the ITIN Operation address is not in this year's knowledge pack, so "
    "confirm it in the Form W-7 instructions (https://www.irs.gov/instructions/iw7) before mailing."
)


def _w7_sign_line(attached: str) -> str:
    """Form W-7 is the exception among attachments: its own 'Sign Here' block MUST be signed by the ITIN applicant
    even when the W-7 rides attached to the return (an unsigned W-7 is rejected by the ITIN unit, which holds up the
    whole return)."""
    return (
        f"Form {attached} IS signed separately even though it is attached: the ITIN applicant must sign "
        f"and date the W-7's own 'Sign Here' block in ink (and include a daytime phone number) — an "
        f"unsigned W-7 is rejected by the ITIN unit and holds up the whole return."
    )


def _w7_mailing(item: "FilingManifestItem", pack, citations: list[Citation], notes: list[str]) -> str | None:
    """A return filed WITH a Form W-7 overrides the whole where-to-file table: the package (return + W-7 + the
    applicant's identity documents) goes to the Austin ITIN Operation, regardless of the filer's state and of payment
    (Form W-7 instructions). Shared by the Form 1040 and the Form 1040-X checklists."""
    itin_address, itin_citation = _pack_address_entry(pack, "itin_w7_with_return")
    if itin_address:
        if itin_citation:
            citations.append(itin_citation)
        notes.append(_W7_PACKAGE_NOTE)
        return itin_address
    notes.append(_W7_NO_ADDRESS_NOTE)
    return None


_SECTION_6013_STATEMENT_STEP = (
    "ATTACH THE §6013(g)/(h) ELECTION STATEMENT — required on the first joint return under the "
    "election: a statement, SIGNED BY BOTH SPOUSES, declaring that on the last day of the tax year "
    "one spouse was a nonresident alien and the other a U.S. citizen or resident, and that both "
    "choose to be treated as U.S. residents for the entire tax year, with each spouse's full name, "
    f"address, and SSN/ITIN ({_SECTION_6013_URL}). A joint return with a nonresident-alien spouse "
    "is NOT a valid joint return without this statement. That is the IRC 6013(g) declaration; for "
    "the IRC 6013(h) choice (both spouses U.S. citizens or residents on the last day of the year, one "
    "a nonresident alien on the first — a dual-status year) the statement instead declares \"that you "
    "both qualify to make the choice and that you choose to be treated as U.S. residents for the "
    "entire tax year\", and the Filing Status entry names the dual-status spouse(s) (Pub 519 ch. 1, "
    "Choosing Resident Alien Status). In a LATER year of an IRC 6013(g) election still in effect no new "
    "statement is attached: \"check the box and enter their name if you and your nonresident spouse made "
    "the choice to be treated as residents in a prior year and the choice remains in effect\" (Pub 519 "
    "ch. 1)."
)
_SECTION_6013_SIGN_LINE = (
    "The §6013(g)/(h) election statement is signed by BOTH spouses too — sign it in ink along with "
    "the return itself."
)


def _paper_refund_note(item: "FilingManifestItem") -> str:
    """The refund-without-direct-deposit note: no paper-check promise, and what happens instead (TY26-15)."""
    return (
        f"No direct deposit is requested for this {_money(item.bottom_line)} refund. The IRS announces "
        f"(irs.gov/ModernPayments, under Executive Order 14247) the \"phase out of paper tax refund checks "
        f"beginning Sept. 30, 2025, to the extent permitted by law\", and its FAQ says the IRS \"generally "
        f"stopped issuing paper refund checks for individual taxpayers after Sept. 30, 2025\" (FS-2026-02, "
        f"Topic A Q1) — that turns on when the refund is issued, so it covers this {item.tax_year} return "
        f"whatever its tax year. What happens instead (FS-2026-02, Q5): \"If taxpayers do not provide this "
        f"information and no exception applies, their refunds could take longer to process\"; the filer "
        f"gets \"a CP53E notice in the mail requesting a response within 30 days, either to provide banking "
        f"information or to explain why such information cannot be provided\", and \"If there is no "
        f"response to the notice and there are no other issues with the tax return, the refund will be "
        f"released as a paper check after six weeks.\" To avoid that delay, before mailing enter the routing "
        f"and account numbers in the return's refund (direct deposit) section — a bank or credit-union "
        f"account, or a mobile app or prepaid debit card that has a routing and account number — and set "
        f"direct_deposit true in the file_and_pay manifest. ModernPayments: \"Taxpayers who file returns "
        f"with valid bank account information will continue to receive direct deposits as the fastest and "
        f"most secure refund method.\" With no account: \"Taxpayers without access to digital payment "
        f"options may be eligible for Treasury-sponsored alternatives that ensure reliable electronic "
        f"delivery. Additional details on these alternatives will be provided as implementation "
        f"progresses.\" (same page).{_international_refund_note(item)} Sources: {_MODERN_PAYMENTS_URL}; "
        f"{_FS_2026_02_URL}"
    )


def _international_refund_note(item: "FilingManifestItem") -> str:
    """A Form 1040-NR filer may have no U.S. account: FS-2026-02 Topic D Q1 is the answer for them."""
    if not item.form.upper().startswith("1040-NR"):
        return ""
    return (
        " For a filer abroad without a U.S. bank account, FS-2026-02 Topic D Q1: \"International taxpayers "
        "should continue to use existing options to file returns, make payments and receive refunds. The IRS "
        "is developing secure alternatives, such as partnerships with international payment providers, to "
        "ensure timely access to refunds abroad.\""
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
    jurisdiction: str = Field(default="federal", description="'federal' or 'states/<xx>'.")
    bottom_line: int = Field(description="Signed: positive = refund, negative = amount owed, 0 = balanced.")
    taxpayer: str | None = Field(
        default=None,
        description=(
            "Whose return this is, for the HOUSEHOLD roll-up (H2/N-2): an unmarried household is "
            "two separate taxpayers — label each person's returns (e.g. 'me', 'Partner P') and "
            "filing_summary adds per-person subtotals + the household net. None = single-taxpayer "
            "filing, no roll-up."
        ),
    )
    paid_online: bool = Field(default=False, description="True if an owed balance was already paid electronically.")
    state: str | None = Field(default=None, description="Taxpayer's state — two-letter USPS code ('CA') or full name ('California'); resolves the 1040 where-to-file address.")
    filing_jointly: bool = Field(default=False, description="MFJ — both spouses must sign.")
    direct_deposit: bool = Field(default=False, description="Refund requested by direct deposit.")
    attached_forms: list[str] = Field(default_factory=list, description="Forms attached to this return (e.g. ['8843', 'W-7']; ['8316'] on a Form 843 FICA claim). Most attachments are not separately signed; Form W-7 IS — the applicant signs its own Sign Here block — and so is Form 8316 (its own page-1 signature area).")
    attached_statements: list[str] = Field(
        default_factory=list,
        description=(
            "Explanatory statements the instructions require with this return (JR2c), e.g. 'recharacterization "
            "statement' (calc op ira_recharacterization's `statement`), 'returned contribution statement', "
            "'line 4b statement' (taxfill_core.statements). The checklist names each one to attach; none is signed "
            "separately."
        ),
    )
    section_6013_election: bool = Field(
        default=False,
        description=(
            "True when this joint return carries a §6013(g)/(h) election (a nonresident-alien spouse treated "
            "as a U.S. resident): the FIRST joint return under the election must have the election statement "
            "— signed by BOTH spouses, with each spouse's name, address, and SSN/ITIN — attached."
        ),
    )
    amended: bool | None = Field(
        default=None,
        description=(
            "True for an AMENDED return: Form 1040-X, a state's amended form, or a state form filed with its "
            "amended-return box checked. Left unset, a form name ending in X ('1040-X', '500X', 'IT-201-X') counts "
            "as amended; set it for a state whose amended return is the original form with a box (and false for "
            "the rare original form whose name ends in X). The checklist then follows the amended-return rules "
            "(its own address, payment, attachments and timing), never the original return's address or due "
            "date. A federal amended item gets the Form 1040-X checklist; list the corrected return that goes "
            "behind it ('1040', '1040-SR' or '1040-NR') in attached_forms."
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


def _federal_return(item: FilingManifestItem, knowledge_dir, today: date | None = None) -> ReturnInstructions:
    # Degrade gracefully for years whose knowledge pack isn't shipped (e.g. a
    # back-filed year older than the oldest shipped pack): the generic sign/assemble/
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
    if any(_is_8938(a) for a in item.attached_forms):
        # THE ENVELOPE TRAP. A filer who has just attached Form 8938 believes the
        # foreign-account job is finished, and it may not be: the FBAR is a
        # different filing, to a different agency, on a different threshold, and
        # it does NOT travel in this envelope. "The Form 8938 filing requirement
        # does not replace or otherwise affect a taxpayer's obligation to file
        # FinCEN Form 114 ... Unlike Form 8938, the FBAR (FinCEN Form 114) is not
        # filed with the IRS" (IRS, Comparison of Form 8938 and FBAR
        # requirements), and irs.gov's FBAR page: "You don't file the FBAR with
        # your federal tax return."
        notes.append(
            f"Form 8938 is attached to this return — but the FBAR is NOT, and CANNOT BE, in this "
            f"envelope. FinCEN Form 114 is a SEPARATE filing to FinCEN (not the IRS), e-file ONLY "
            f"through the BSA E-Filing System at https://bsaefiling.fincen.treas.gov/main.html; a "
            f"printed Form 114 is not accepted. Filing Form 8938 does not satisfy it: the FBAR is "
            f"required once the AGGREGATE maximum value of ALL foreign financial accounts exceeds "
            f"$10,000 at ANY TIME in the CALENDAR year — a much lower bar than Form 8938's, and one "
            f"that filing status does not move — and it reaches accounts you only have SIGNATURE "
            f"AUTHORITY over, which Form 8938 generally does not. It is due April "
            f"15, {item.tax_year + 1} with an AUTOMATIC extension to October 15, {item.tax_year + 1} "
            f"that needs no request (P.L. 114-41 sec. 2006(b)(11)). Check the duty with calc op "
            f"foreign_asset_reporting and gather the values with hand_fill_worksheet('fincen114', "
            f"{item.tax_year}, 'federal'). Non-willful FBAR penalties run to $10,000 per report "
            f"(inflation-adjusted to $16,536 for penalties assessed on or after 2025-01-17; 31 CFR "
            f"1010.821), so do not mail this return believing the foreign-account job is done."
        )
    if _is_standalone_8843(item):
        return _standalone_8843_return(item, pack, notes)
    if _is_843(item.form):
        return _form_843_return(item, pack, notes)
    if _is_amended(item) and (_is_1040x(item.form) or _is_individual_return(item.form)):
        return _form_1040x_return(item, pack, notes, today or date.today())
    is_nr = _is_nr_form(item.form)
    owes = item.bottom_line < 0
    refund = item.bottom_line > 0
    enclosing_check = owes and not item.paid_online

    # Bottom line (plain language). A refund with no direct deposit never promises a
    # paper check: the IRS is phasing them out (irs.gov/ModernPayments; TY26-15).
    if refund:
        if item.direct_deposit:
            bottom = f"Refund of {_money(item.bottom_line)} by direct deposit."
        else:
            bottom = (
                f"Refund of {_money(item.bottom_line)} — no direct deposit requested, and the IRS is phasing out "
                f"paper refund checks: expect a CP53E notice asking for an account, and a slower refund (see "
                f"the note)."
            )
            notes.append(_paper_refund_note(item))
            citations.extend((_MODERN_PAYMENTS_CITATION, _FS_2026_02_CITATION))
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
        mailing_address = _w7_mailing(item, pack, citations, notes)
    elif pack is not None and pack.mailing_addresses is not None:
        ma = pack.mailing_addresses
        citations.append(ma.citation)
        if is_nr:
            mailing_address = ma.f1040nr.with_payment if enclosing_check else ma.f1040nr.no_payment
            if mailing_address is None:
                notes.append(_unpublished_address_note(item, "Form 1040-NR", enclosing_check))
        elif item.state:
            try:
                pair = ma.f1040_for_state(_expand_state(item.state))
                mailing_address = pair.with_payment if enclosing_check else pair.no_payment
                if mailing_address is None:
                    notes.append(_unpublished_address_note(item, "Form 1040", enclosing_check))
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
            sign.append(_w7_sign_line(attached))
        else:
            sign.append(f"Form {attached} is attached to this return — do NOT sign it separately.")
    for statement in item.attached_statements:
        sign.append(f"The {statement} is attached to this return — do NOT sign it separately.")

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
    for statement in item.attached_statements:
        assemble.append(
            f"ATTACH THE {statement.upper()} after the forms — the instructions require the explanation with the "
            f"return (for a recharacterization: \"attach a statement to your return explaining the "
            f"recharacterization\", Instructions for Form 8606).")

    # §6013(g)/(h) election statement — the compliance item that makes the joint
    # election valid at all: a joint return with a nonresident-alien spouse mailed
    # WITHOUT the signed statement is not a valid joint return, so it leads the
    # assembly checklist rather than hiding among the generic steps.
    if item.section_6013_election:
        assemble.insert(0, _SECTION_6013_STATEMENT_STEP)
        sign.append(
            _SECTION_6013_SIGN_LINE
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


# ── Amended returns: Form 1040-X (Phase K JK27) ────────────────────────────────
# Form 1040-X is a continuous-use form ("converted from an annual revision to continuous use in tax year 2021"), so an
# amendment filed today follows the CURRENT instructions whatever year it amends; the instructions' own example of a
# return being amended is a "2024 Form 1040" (p. 2). Everything below is read off the Instructions for Form 1040-X
# (Rev. December 2025), irs.gov/pub/irs-pdf/i1040x.pdf, two downloads digest eed8685fbdbfe362 (read 2026-10-16):
# What's New (p. 1), Which Revision To Use / Interest and Penalties / When To File (p. 3), Tracking Your Amended Return
# (p. 5), Line 20 and Line 22 (p. 10), Sign Your Return and Assembling Your Return (p. 11), Where To File (p. 12).
# A new revision can move any of it (the December 2025 one added the attached-return requirement): re-read the
# instructions when irs.gov/Form1040X posts one, and update this table with them.
_F1040X_INSTRUCTIONS_URL = "https://www.irs.gov/pub/irs-pdf/i1040x.pdf"
_F1040X_CITATION = Citation(
    source=(
        "Instructions for Form 1040-X (Rev. December 2025): What's New, the new attachment requirement (p. 1); "
        "Interest and Penalties and When To File (p. 3); Tracking Your Amended Return (p. 5); Line 20 and Line 22 "
        "(p. 10); Sign Your Return and Assembling Your Return (p. 11); Where To File (p. 12)"
    ),
    url=_F1040X_INSTRUCTIONS_URL,
)
_PAY_BY_CHECK_URL = "https://www.irs.gov/payments/pay-by-check-or-money-order"
_PAY_BY_CHECK_CITATION = Citation(
    source=(
        "IRS — Pay by check or money order: payable to \"U.S. Treasury\"; the check includes your name, address "
        "and phone number, the tax form or notice number, the tax year and your SSN (read 2026-10-16)"
    ),
    url=_PAY_BY_CHECK_URL,
)
_AMENDED_FAQ_URL = "https://www.irs.gov/filing/amended-return-frequently-asked-questions"
_AMENDED_FAQ_CITATION = Citation(
    source=(
        "IRS — Amended return frequently asked questions: Forms 1040, 1040-SR and 1040-NR for the current or two "
        "prior tax periods can be amended electronically; direct deposit only on an electronically filed amended "
        "return (read 2026-10-16)"
    ),
    url=_AMENDED_FAQ_URL,
)
_F1040X_AUSTIN = "Department of the Treasury, Internal Revenue Service, Austin, TX 73301-0052"
_F1040X_OGDEN = "Department of the Treasury, Internal Revenue Service, Ogden, UT 84201-0052"
_F1040X_KANSAS_CITY = "Department of the Treasury, Internal Revenue Service, Kansas City, MO 64999-0052"
# "A foreign country, U.S. territory; or use an APO or FPO address, or file Form 2555 or 4563, or are a dual-status
# alien", and "with Form 1040-NR or 1040-NR-EZ".
_F1040X_AUSTIN_INTERNATIONAL = "Department of the Treasury, Internal Revenue Service, Austin, TX 73301-0215"
_F1040X_BY_STATE: dict[str, str] = {
    **dict.fromkeys(
        ("Alabama", "Arkansas", "Florida", "Georgia", "Louisiana", "Mississippi", "Oklahoma", "Texas"),
        _F1040X_AUSTIN,
    ),
    **dict.fromkeys(
        ("Alaska", "Arizona", "California", "Colorado", "Hawaii", "Idaho", "Iowa", "Kansas", "Michigan", "Montana",
         "Nebraska", "Nevada", "New Mexico", "North Dakota", "Ohio", "Oregon", "South Dakota", "Utah", "Washington",
         "Wyoming"),
        _F1040X_OGDEN,
    ),
    **dict.fromkeys(
        ("Connecticut", "Delaware", "District of Columbia", "Illinois", "Indiana", "Kentucky", "Maine", "Maryland",
         "Massachusetts", "Minnesota", "Missouri", "New Hampshire", "New Jersey", "New York", "North Carolina",
         "Pennsylvania", "Rhode Island", "South Carolina", "Tennessee", "Vermont", "Virginia", "West Virginia",
         "Wisconsin"),
        _F1040X_KANSAS_CITY,
    ),
}


def _refund_window_anchor(year: int, due: str | None) -> str:
    """When an early or on-time original "is considered filed" (Form 1040-X instructions, When To File: "on the due
    date (generally April 15)"). A weekend or holiday moves the due date a day or three, not the anchor; a postponement
    (TY2019 to 2020-07-15, TY2020 to 2021-05-17) moves the due date itself, and the packs record the window moving with
    it."""
    april_15 = date(year + 1, 4, 15)
    if due and date.fromisoformat(due) > date(year + 1, 4, 18):
        return due
    return april_15.isoformat()


def _form_name(name: str) -> str:
    """'Schedule 1' / 'Form 2555' stay as given; a bare number reads 'Form 2555'."""
    return name if re.match(r"(?i)(form|schedule)\b", name.strip()) else f"Form {name}"


def _form_1040x_return(item: FilingManifestItem, pack, notes: list[str], today: date) -> ReturnInstructions:
    """Form 1040-X — an amended federal return, under the CURRENT Form 1040-X instructions (Phase K JK27).

    Before JK27 a 1040-X item fell through to the Form 1040 checklist: the 1040 address (Charlotte, NC for a
    Georgia balance due, where the 1040-X table says Austin), a "Form 1040" check memo, the Form 1040-V voucher, and
    the original return's due date as the deadline. What the Form 1040 checklist does for a Form W-7, a §6013(g)/(h)
    election or a dual-status year carries over here, aimed at the updated return behind the Form 1040-X.
    """
    y = item.tax_year
    citations: list[Citation] = [_F1040X_CITATION]
    corrected = next((a for a in item.attached_forms if _is_individual_return(a)), None)
    if not _is_1040x(item.form):
        if corrected is None and _is_individual_return(item.form):
            corrected = item.form
        notes.append(
            f"A federal return is amended on Form 1040-X, not on another Form {item.form}: \"After the due date for "
            f"an original return has passed, don't file any additional original returns for the same year\" (Form "
            f"1040-X instructions, p. 3). File Form 1040-X with the completed, updated Form {item.form} behind it; "
            f"this checklist is for that Form 1040-X."
        )
    amends_nr = corrected is not None and _is_nr_form(corrected)
    owes, refund = item.bottom_line < 0, item.bottom_line > 0
    enclosing_check = owes and not item.paid_online
    due = pack.deadlines.filing_due_date if pack is not None and pack.deadlines is not None else None
    # "If you filed your original return early (for example, March 1 for a calendar year return), your return is
    # considered filed on the due date (generally April 15)" (When To File, p. 3): the claim window runs from April 15
    # even in a year whose due date a weekend moved.
    deemed_filed = _refund_window_anchor(y, due)
    # "the current or two prior tax periods" (IRS amended-return FAQ): in processing year P, tax years P-1 .. P-3.
    efile_ok = y >= today.year - 3

    if refund:
        bottom = f"Amended {y} return (Form 1040-X): a further refund of {_money(item.bottom_line)}."
    elif owes:
        bottom = f"Amended {y} return (Form 1040-X): you owe {_money(item.bottom_line)} more." + (
            " Already paid online." if item.paid_online else "")
    else:
        bottom = f"Amended {y} return (Form 1040-X): no change in the amount you owe or are refunded."

    payment: list[str] = []
    if owes and item.paid_online:
        payment.append("Balance already paid electronically — keep the confirmation number; do NOT enclose a check.")
    elif owes:
        payment.append(
            "\"The IRS recommends paying the amount due on line 20 electronically whenever possible\": \"Online using "
            "Direct Pay, cash, or your IRS online account; or Online or by phone using the Electronic Federal Tax "
            "Payment System (EFTPS), a debit card, a credit card, or a digital wallet\" (Form 1040-X instructions, "
            "Line 20, p. 10)."
        )
        payment.append(
            f"By check or money order: make it payable to \"U.S. Treasury\" and write on it your name, address and "
            f"phone number, your SSN, the tax year ({y}) and the form (\"{y} Form 1040-X\") (IRS, Pay by check or "
            f"money order). \"If you owe tax and you don't want to pay electronically, enclose (don't attach) your "
            f"check or money order in the envelope with your amended return\" (p. 12). The Form 1040-X instructions "
            f"name no payment voucher: enclose the check by itself."
        )
        citations.append(_PAY_BY_CHECK_CITATION)
    if owes:
        since = f" from the {y} return's original due date ({due})" if due else " from the original due date"
        until = "until it was paid (you paid online)" if item.paid_online else (
            "until it is paid, so pay with the amended return or sooner")
        payment.append(
            f"Interest: \"The IRS will charge you interest on taxes not paid by their due date, even if you had an "
            f"extension of time to file\" (Interest and Penalties, p. 3) — on this additional tax it runs{since} "
            f"{until}."
        )
    if refund:
        payment.append(
            "The refund comes by check: \"You will receive a check for any refund due to you. A refund on a "
            "paper-filed amended return can't be deposited directly to your bank account\"; \"We will figure any "
            "interest and include it in your refund\" (Line 22, p. 10). Only a Form 1040-X filed electronically can "
            "ask for direct deposit (IRS amended-return FAQ)."
        )
        citations.append(_AMENDED_FAQ_CITATION)
        if item.direct_deposit:
            notes.append(
                "direct_deposit is set, but a paper Form 1040-X cannot request it — e-file the amended return through "
                "tax software if you want the refund deposited."
                if efile_ok else
                f"direct_deposit is set, but a paper Form 1040-X cannot request it, and a {y} amendment can no longer "
                f"be filed electronically, so the refund comes by check."
            )

    mailing_address = None
    if _filing_includes_w7(item):
        # The W-7 package goes to the ITIN Operation whatever the return (Form W-7 instructions: "don't use the
        # mailing address in the instructions for your tax return"); it names an amended joint return among its cases.
        mailing_address = _w7_mailing(item, pack, citations, notes)
    elif amends_nr:
        mailing_address = _F1040X_AUSTIN_INTERNATIONAL
        notes.append("This Form 1040-X amends a Form 1040-NR: the Form 1040-X table sends it, \"with Form 1040-NR\", "
                     "to Austin, TX 73301-0215, whatever your state.")
    elif item.dual_status or any(_norm_form(a) in ("2555", "4563") for a in item.attached_forms):
        mailing_address = _F1040X_AUSTIN_INTERNATIONAL
        notes.append("A dual-status alien, or a filer of Form 2555 or 4563, mails Form 1040-X to Austin, TX "
                     "73301-0215 (the Form 1040-X Where To File table).")
    elif item.state:
        wanted = _expand_state(item.state).strip().casefold()
        mailing_address = next((a for st, a in _F1040X_BY_STATE.items() if st.casefold() == wanted), None)
        if mailing_address is None:
            notes.append(
                f"{item.state!r} is not one of the 50 states or DC in the Form 1040-X table. For \"A foreign country, "
                f"U.S. territory; or use an APO or FPO address\" the table gives {_F1040X_AUSTIN_INTERNATIONAL} "
                f"(residents of American Samoa, Puerto Rico, Guam, the U.S. Virgin Islands or the Northern Mariana "
                f"Islands: see Pub. 570); for a state, pass its two-letter code or full name."
            )
    else:
        notes.append("No state given — the Form 1040-X address depends on where you live (Where To File, p. 12); "
                     "provide it to resolve the exact address.")
    notes.append(
        "Filing Form 1040-X in response to a notice you received from the IRS? Mail it to the address shown in the "
        "notice instead (Where To File, p. 12)."
    )
    if efile_ok:
        notes.append(
            "E-file alternative: Forms 1040, 1040-SR and 1040-NR \"for the current or two prior tax periods\" can be "
            "amended electronically with tax software; but \"If amending a prior year return originally filed on paper "
            "during the current processing year, then the amended return must also be filed on paper\" (IRS "
            "amended-return FAQ)."
        )
    else:
        notes.append(
            f"A {y} amendment must be filed on paper: \"Amended returns for those earlier tax years must be filed by "
            f"paper\" — only Forms 1040, 1040-SR and 1040-NR \"for the current or two prior tax periods\" can be "
            f"amended electronically (IRS amended-return FAQ)."
        )
    citations.append(_AMENDED_FAQ_CITATION)

    sign = [
        "Sign and date Form 1040-X in ink and enter your occupation(s): \"Form 1040-X isn't considered a valid return "
        "unless you sign it\", and \"You must handwrite your signature on your return if you file it on paper. "
        "Digital, electronic, or typed-font signatures are not valid signatures for Forms 1040-X filed on paper\" "
        "(Sign Your Return, p. 11).",
    ]
    if item.filing_jointly:
        sign.append("Amended joint return: \"your spouse must also sign\" (p. 11).")
    for attached in item.attached_forms:
        if _is_individual_return(attached):
            continue
        if _is_w7(attached):
            sign.append(_w7_sign_line(attached))
        else:
            sign.append(f"{_form_name(attached)} is attached to this amended return — do NOT sign it separately.")

    behind = f"Form {corrected}" if corrected else "Form 1040, 1040-SR, or 1040-NR"
    assemble = [
        "Print Form 1040-X and complete Part II, Explanation of Changes — the form's own header: \"Attach any "
        "supporting documents and new or changed forms and schedules and complete Part II\".",
        f"Behind the Form 1040-X put a completed and updated {behind} for {y} with your changes — new in the "
        f"December 2025 revision: \"You must place behind your completed paper-filed Form 1040-X a completed and "
        f"updated Form 1040, 1040-SR, or 1040-NR with the changes you are submitting\" (Assembling Your Return, "
        f"p. 11).",
        "Behind that return, \"any new or changed schedules and forms ... in the order of the 'Attachment Sequence "
        "No.'\"; supporting statements last, in the order of the forms they support. \"Don't attach a copy of your "
        "original return, correspondence, or other items unless required to do so.\"",
        "Attach to the FRONT of Form 1040-X a copy of any Form W-2, W-2c or 2439 that supports a change; Form W-2G "
        "or 1099-R only if tax was withheld; any Form 1042-S, SSA-1042S, RRB-1042S or 8288-A that supports a change. "
        "Attach any supporting Form 8805 to the BACK (p. 11-12).",
    ]
    if amends_nr:
        # Resident and nonresident aliens, p. 2: the paper procedure for a Form 1040-NR (and for switching between
        # Form 1040 and Form 1040-NR) replaces the column model.
        assemble.insert(0, (
            "Paper Form 1040-X amending a Form 1040-NR (Form 1040-X instructions, p. 2, \"Resident and nonresident "
            "aliens\"): \"Enter your name, current address, and social security number (SSN) or individual taxpayer "
            "identification number (ITIN) on the front of Form 1040-X\"; \"Don't enter any other information on "
            "page 1. Also don't complete Part I on page 2 of Form 1040-X\"; \"Enter in Part II—Explanation of "
            "Changes the reason you are filing Form 1040-X\"; \"Complete a new or corrected return\"; \"Across the "
            "top of the new or corrected return, write 'Amended.'\"; \"Attach the new or corrected return to the "
            "back of Form 1040-X.\" These steps are for paper filing only: an e-filed Form 1040-X that amends a "
            "Form 1040-NR is completed \"in its entirety\"."
        ))
    else:
        notes.append(
            "Switching between Form 1040 and Form 1040-NR (\"Use Form 1040-X if you should have filed Form 1040 "
            "instead of Form 1040-NR, or vice versa\")? Follow the paper steps under \"Resident and nonresident "
            "aliens\" (Form 1040-X instructions, p. 2) instead of the column model."
        )
    if corrected is None:
        notes.append(
            "attached_forms names no corrected return: list '1040', '1040-SR' or '1040-NR' there — a paper Form "
            "1040-X now needs the completed, updated return behind it."
        )
    if enclosing_check:
        assemble.append("Put the check or money order loose in the envelope — enclosed, not attached.")
    for statement in item.attached_statements:
        assemble.append(f"Attach the {statement} after the forms (supporting statements go last).")

    deadlines: list[str] = []
    if item.section_6013_election:
        # Pub 519 ch. 1, "Amended return": the choice can be made on a joint amended return.
        assemble.insert(0, _SECTION_6013_STATEMENT_STEP)
        assemble.insert(1, (
            "Making the §6013(g)/(h) choice on an amended return (Pub 519 ch. 1, Amended return): \"you can also make "
            "the choice by filing a joint amended return on Form 1040-X. Attach Form 1040 or 1040-SR and enter "
            "'Amended' across the top of the corrected return. If you make the choice with an amended return, you "
            "and your spouse must also amend any returns that you may have filed after the year for which you made "
            "the choice.\""
        ))
        sign.append(_SECTION_6013_SIGN_LINE)
        deadlines.append(
            "\"You must generally file the amended joint return within 3 years from the date you filed your original "
            "U.S. income tax return or 2 years from the date you paid your income tax for that year, whichever is "
            "later\" (Pub 519 ch. 1, Amended return)."
        )
        citations.append(_SECTION_6013_CITATION)
        citations.append(_PUB_519_CITATION)
    if item.dual_status:
        nr_return = corrected is not None and _is_nr_form(corrected)
        statement_form = "Form 1040" if nr_return else "Form 1040-NR"
        statement_part = "resident" if nr_return else "nonresident"
        return_form = f"Form {corrected}" if corrected else "updated return"
        assemble.insert(0, (
            f'The updated {return_form} behind the Form 1040-X is a dual-status return: write "Dual-Status Return" '
            f"across its top, attach {statement_form} as the DUAL-STATUS STATEMENT for the {statement_part} part of "
            f'the year with "Dual-Status Statement" written across its top, and remember that a dual-status return '
            f"takes NO standard deduction (Pub 519 ch. 6; {_DUAL_STATUS_URL})."
        ))
        sign.append(
            f'The {statement_form} marked "Dual-Status Statement" is NOT signed separately; your signature covers the '
            f"whole filing."
        )
        citations.append(_DUAL_STATUS_CITATION)

    mail = [
        "\"File a separate Form 1040-X for each year you are amending\" (p. 2) — one envelope per year, never with "
        "another year's return.",
        "Send by USPS Certified Mail with Return Receipt (PS Form 3800) and ask for a postmark — that receipt is your "
        "proof of timely filing; the IRS won't otherwise confirm receipt.",
        "A private delivery service needs the street address at IRS.gov/PDSStreetAddresses, not the address above "
        "(Where To File, p. 12).",
    ]
    if mailing_address and "p.o. box" in mailing_address.lower():
        mail[2] = ("This is a P.O. Box address — it must go by USPS (private couriers like FedEx/UPS can't deliver to "
                   "a PO box); the Form W-7 instructions give the ITIN Operation's own street address for a private "
                   "delivery service.")
    records = [
        "Photograph every signed page before mailing.",
        "Keep the certified-mail receipt and tracking number, plus any payment confirmation.",
        "Keep a copy of the Form 1040-X, the updated return behind it and your RECONCILIATION.md for at least 3 years.",
        "Track it with Where's My Amended Return on IRS.gov: \"It can take up to 3 weeks from the date you mail it to "
        "show up in our system\"; \"allow 8 to 12 weeks for Form 1040-X to be processed. However, in some cases, "
        "processing could take up to 16 weeks\" (Tracking Your Amended Return, p. 5).",
    ]

    if refund:
        deadlines.append(
            "Refund claim window: \"Generally, for a credit or refund, you must file Form 1040-X within 3 years "
            "(including extensions) after the date you filed your original return or within 2 years after the date "
            "you paid the tax, whichever is later\" (When To File, p. 3). An original filed early or on time \"is "
            f"considered filed on the due date (generally April 15)\", so for it the 3 years run to "
            f"{_plus_years(deemed_filed, 3)}; an original filed later, or tax paid later, moves the date later."
            + (" That date has passed: the refund survives only if the original was filed later or tax was paid "
               "within the last 2 years." if _plus_years(deemed_filed, 3) < today.isoformat() else "")
        )
    elif owes:
        deadlines.append(
            "The Form 1040-X When To File limit (3 years from filing, or 2 from paying) is for \"a credit or "
            "refund\"; on an amendment that adds tax, interest grows until the tax is paid, so file and pay soon."
        )
    if due and owes:
        citations.append(pack.deadlines.citation)

    return ReturnInstructions(
        form=item.form, jurisdiction="federal", tax_year=y, bottom_line=bottom, payment=payment,
        mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail, records=records,
        deadlines=deadlines, citations=_dedupe_citations(citations), notes=notes,
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

    if _is_amended(item):
        return _amended_state_return(item, sk, state)
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


_IRS_STATE_SITES_CITATION = Citation(
    source="IRS — State government websites: every state's tax agency, the way to its amended-return instructions",
    url="https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites",
)


# Each income-tax jurisdiction's revenue department home page, for the pointer an amended state return gets when its pack
# carries no amended-return rules. Read 2026-10-16: each answered HTTP 200 with the department's name in its title, except
# tax.colorado.gov, www.mass.gov and tax.ri.gov, which refuse scripted requests and are the hosts their own packs cite.
# (A first cut took the host of the pack's primary citation, which for many states is a file CDN or a general portal;
# Ohio's resolved to a non-government site. Found by the JK27 re-verification.)
_STATE_REVENUE_SITES: dict[str, str] = {
    "AL": "https://www.revenue.alabama.gov/", "AZ": "https://azdor.gov/", "AR": "https://www.dfa.arkansas.gov/",
    "CA": "https://www.ftb.ca.gov/", "CO": "https://tax.colorado.gov/", "CT": "https://portal.ct.gov/drs",
    "DE": "https://revenue.delaware.gov/", "DC": "https://otr.cfo.dc.gov/", "GA": "https://dor.georgia.gov/",
    "HI": "https://tax.hawaii.gov/", "ID": "https://tax.idaho.gov/", "IL": "https://tax.illinois.gov/",
    "IN": "https://www.in.gov/dor/", "IA": "https://revenue.iowa.gov/", "KS": "https://www.ksrevenue.gov/",
    "KY": "https://revenue.ky.gov/", "LA": "https://revenue.louisiana.gov/", "ME": "https://www.maine.gov/revenue/",
    "MD": "https://www.marylandcomptroller.gov/",
    "MA": "https://www.mass.gov/orgs/massachusetts-department-of-revenue",
    "MI": "https://www.michigan.gov/treasury", "MN": "https://www.revenue.state.mn.us/", "MS": "https://www.dor.ms.gov/",
    "MO": "https://dor.mo.gov/", "MT": "https://revenue.mt.gov/", "NE": "https://revenue.nebraska.gov/",
    "NJ": "https://www.nj.gov/treasury/taxation/", "NM": "https://www.tax.newmexico.gov/", "NY": "https://www.tax.ny.gov/",
    "NC": "https://www.ncdor.gov/", "ND": "https://www.tax.nd.gov/", "OH": "https://tax.ohio.gov/",
    "OK": "https://oklahoma.gov/tax.html", "OR": "https://www.oregon.gov/dor/", "PA": "https://www.pa.gov/agencies/revenue",
    "RI": "https://tax.ri.gov/", "SC": "https://dor.sc.gov/", "UT": "https://tax.utah.gov/",
    "VT": "https://tax.vermont.gov/", "VA": "https://www.tax.virginia.gov/", "WV": "https://tax.wv.gov/",
    "WI": "https://www.revenue.wi.gov/",
}


def _amended_pointer_citations(code: str) -> list[Citation]:
    """Where to read a state's amended-return rules when its pack has none: its revenue department, and the IRS list
    of every state tax agency."""
    cites = []
    site = _STATE_REVENUE_SITES.get(code)
    if site:
        cites.append(Citation(source=f"{code} revenue department home page (read 2026-10-16)", url=site))
    cites.append(_IRS_STATE_SITES_CITATION)
    return cites


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _amended_state_return(item: FilingManifestItem, sk, state: str) -> ReturnInstructions:
    """A state AMENDED return (Phase K JK27): the pack's ``amended_return`` block, or a pointer to the DOR.

    The block (an open extra on the state pack) carries ``form``, the address (``mailing_address``, or
    ``with_payment`` / ``refund_or_no_payment`` where the state splits them), and lists ``payment``, ``assemble``,
    ``timing``, ``mail`` and ``notes``, each quoting its source, plus ``citation`` / ``citations``. Before JK27 a
    Georgia Form 500X balance due got the Form 500 payment address (PO Box 740399), the original return's due date
    and the Form 525-TV voucher, with the 500X box (PO Box 740318) only inside that address string.
    """
    code = state.upper()
    y = item.tax_year
    owes, refund = item.bottom_line < 0, item.bottom_line > 0
    enclosing_check = owes and not item.paid_online
    am = getattr(sk, "amended_return", None) or {}
    form = am.get("form") or _form_name(item.form)
    if refund:
        bottom = f"Amended {code} {y} return ({form}): a further refund of {_money(item.bottom_line)}."
    elif owes:
        bottom = f"Amended {code} {y} return ({form}): you owe {_money(item.bottom_line)} more." + (
            " Already paid." if item.paid_online else "")
    else:
        bottom = f"Amended {code} {y} return ({form}): no change in the amount owed or refunded."

    citations: list[Citation] = []
    payment: list[str] = []
    deadlines: list[str] = []
    notes: list[str] = []
    assemble: list[str] = []
    mailing_address = None
    mail = ["Use a separate envelope from the federal return.",
            "Certified Mail with Return Receipt gives you proof of timely filing."]
    if am:
        mailing_address = (am.get("with_payment") if enclosing_check else am.get("refund_or_no_payment")) or am.get(
            "mailing_address")
        if owes and item.paid_online:
            payment.append("Balance already paid — keep the confirmation; do not enclose a check.")
        elif owes:
            payment.extend(_as_list(am.get("payment")))
        assemble.extend(_as_list(am.get("assemble")))
        deadlines.extend(_as_list(am.get("timing")))
        if am.get("mail"):
            # The state's own mailing advice replaces the generic certified-mail line (Georgia: certified mail "may
            # delay processing your return").
            mail = ["Use a separate envelope from the federal return.", *_as_list(am.get("mail"))]
        notes.extend(_as_list(am.get("notes")))
        for raw in [am.get("citation"), *(am.get("citations") or [])]:
            if isinstance(raw, dict):
                citations.append(Citation(**raw))
    else:
        site = _STATE_REVENUE_SITES.get(code)
        where = f" on the {code} revenue department's site ({site})" if site else ""
        notes.append(
            f"This is an amended {code} return, and the {code} {y} knowledge pack carries no amended-return rules, so "
            f"this checklist gives no mailing address, payment method or deadline. Read them in the {code} "
            f"instructions for amended returns{where} before mailing; do not reuse the original return's address, "
            f"voucher or due date without checking them there."
        )
        citations.extend(_amended_pointer_citations(code))
    if not assemble:
        assemble.append("Print only the form pages (not instructions), single-sided, with the schedules and "
                        "documents the amended form asks for.")

    sign = ["Print the form pages, sign and date the amended return in ink."]
    if item.filing_jointly:
        sign.append("Joint return — BOTH spouses must sign.")
    return ReturnInstructions(
        form=item.form, jurisdiction=item.jurisdiction, tax_year=y, bottom_line=bottom, payment=payment,
        mailing_address=mailing_address, sign=sign, assemble=assemble, mail=mail,
        records=["Photograph the signed pages; keep a copy and the mailing receipt."],
        deadlines=deadlines, citations=_dedupe_citations(citations), notes=notes,
    )


def file_and_pay(
    manifest: list[FilingManifestItem],
    *,
    knowledge_dir: str | Path | None = None,
    today: date | None = None,
) -> FilingInstructions:
    """Build the per-return last-mile checklist for a finished filing.

    Args:
        manifest: one :class:`FilingManifestItem` per finished return.
        knowledge_dir: override the knowledge directory (installed-wheel use).
        today: the date the checklist is for (default: today). It decides whether an amended year can still be
            e-filed and whether a refund-claim window has passed (Phase K JK27).

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
            returns.append(_federal_return(item, knowledge_dir, today))
        else:
            returns.append(_state_return(item, knowledge_dir))

    overall: list[str] = [
        "This is a review draft — you are the filer: review every number, then sign and mail it yourself.",
    ]
    if len(manifest) > 1:
        overall.append("Mail each return in its OWN envelope, even if they go to the same address.")
    return FilingInstructions(returns=returns, overall_notes=overall)
