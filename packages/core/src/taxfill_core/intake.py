"""Guided-intake interview engine — dev plan section 4.

``intake_checklist(profile)`` looks at a *partial* :class:`Profile` and returns
the next questions to ask and the documents to collect, so any agent can run a
consistent interview without rediscovering the flow. It is the server's half of
the "INTAKE" step (section 2): the server supplies the structure (what to ask,
in what order, with which built-in clarifications); the agent supplies the UI.

Design rules enforced here:

- **Incremental.** Every profile section is optional; the checklist returns only
  what is still needed for the current state. An empty profile yields the first
  batch; a complete one yields ``ready_to_fill=True`` with no questions.
- **Never invent.** The checklist asks; it never fills. Unknown stays a gap.
- **Disambiguation by design.** Questions users predictably get wrong ship with a
  built-in clarification (``disambiguation``): the mailing address is where mail
  arrives TODAY (P-002), visa facts are date-range *periods* not a single status
  (P-004), and "married" is not a filing status — the couple elects MFJ or MFS.
- **Residency-gated.** Citizens/green-card holders skip the immigration section
  and may use any filing status; visa holders get the immigration + residency
  questions, and a nonresident-alien result removes married-filing-jointly and
  head-of-household (Form 1040-NR has no such box).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.schemas.profile import Answer, Profile

__all__ = ["IntakeQuestion", "RequiredDocument", "IntakeChecklist", "intake_checklist"]

# Section order = the §2 interview flow. Questions are returned in this order.
SECTIONS = (
    "identity",
    "immigration",
    "residency",
    "household",
    "state_footprint",
    "income_documents",
    "banking",
    "prior_filings",
)


class IntakeQuestion(BaseModel):
    """One thing to ask the user, with the clarification and the reason baked in."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable dotted id, e.g. 'identity.mailing_address' — agents key answers off this.")
    section: str = Field(description="Which profile section this fills.")
    prompt: str = Field(description="The question to ask the user, in plain language.")
    why: str = Field(description="One-line reason the return needs this — shown to anxious users.")
    disambiguation: str | None = Field(
        default=None,
        description="Built-in clarification for a predictably-misanswered question (P-002/P-004/filing status).",
    )
    answers_into: str = Field(description="Profile path the answer populates, e.g. 'identity.mailing_address'.")


class RequiredDocument(BaseModel):
    """A document the filing needs, with its current have/missing/N-A status."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="Document kind, e.g. 'W-2', 'passport_id_page', 'I-94', 'I-20', '1098-T'.")
    why: str = Field(description="Why the filing needs it.")
    status: str = Field(default="missing", description="have | missing | not_applicable — from the profile when known.")


class IntakeChecklist(BaseModel):
    """The server's answer to 'what next?': questions, documents, and readiness."""

    model_config = ConfigDict(extra="forbid")

    next_questions: list[IntakeQuestion] = Field(default_factory=list)
    required_documents: list[RequiredDocument] = Field(default_factory=list)
    ready_to_fill: bool = Field(
        default=False,
        description="True when the minimum facts to begin a draft return are present (more may still sharpen it).",
    )
    progress: str = Field(default="", description="Human-readable progress, e.g. '3 of 8 sections started'.")
    notes: list[str] = Field(default_factory=list, description="Gating explanations and assumptions surfaced to the user.")


# ── helpers ──────────────────────────────────────────────────────────────────


def _has(answer: Answer | None) -> bool:
    """True when an Answer is present with a non-None value (a real answer, not a gap)."""
    return answer is not None and getattr(answer, "value", None) is not None


def _q(qid, section, prompt, why, answers_into, disambiguation=None) -> IntakeQuestion:
    return IntakeQuestion(
        id=qid, section=section, prompt=prompt, why=why, answers_into=answers_into, disambiguation=disambiguation
    )


# ── section handlers: each appends the questions still needed ─────────────────


def _identity_questions(profile: Profile, out: list[IntakeQuestion]) -> None:
    ident = profile.identity
    if ident is None or not _has(ident.name):
        out.append(_q("identity.name", "identity", "What is your full legal name (as on your SSN/ITIN)?",
                      "It must match IRS records and appear identically on every form.", "identity.name"))
    if ident is None or not _has(ident.tax_id):
        out.append(_q("identity.tax_id", "identity", "What is your SSN or ITIN?",
                      "Every return is filed under your taxpayer ID.", "identity.tax_id"))
    if ident is None or not _has(ident.dob):
        out.append(_q("identity.dob", "identity", "What is your date of birth?",
                      "It affects the standard deduction (age 65+) and some credits.", "identity.dob"))
    if ident is None or not _has(ident.us_person):
        out.append(_q("identity.us_person", "identity",
                      "Are you a U.S. citizen or lawful permanent resident (green-card holder)?",
                      "It decides whether the Substantial Presence Test and a nonresident return apply.",
                      "identity.us_person",
                      disambiguation="Answer yes only for citizens and green-card holders. People on F/J/H/L/etc. "
                                     "visas answer no — we then check residency by your days in the U.S."))
    if ident is None or not _has(ident.mailing_address):
        out.append(_q("identity.mailing_address", "identity", "What is your current mailing address?",
                      "The IRS mails bills, notices, and any paper refund here.", "identity.mailing_address",
                      disambiguation="Give the address where you receive mail TODAY — NOT where you lived during the "
                                     "tax year. Where you lived that year is asked separately (it drives state filing)."))


def _immigration_questions(profile: Profile, out: list[IntakeQuestion], notes: list[str]) -> None:
    ident = profile.identity
    # Gated: only for non-US-persons. If citizenship is unknown, the identity
    # question above asks it first; if they are a US person, skip entirely.
    if ident is None or not _has(ident.us_person) or ident.us_person.value is True:
        return
    imm = profile.immigration
    if imm is None or not imm.visa_timeline:
        out.append(_q("immigration.visa_timeline", "immigration",
                      "List each U.S. immigration status you have held and its exact start/end dates.",
                      "Treaty benefits and residency are decided per visa period, not per year.",
                      "immigration.visa_timeline",
                      disambiguation="Use date ranges, not a single 'current status'. Mid-year changes matter: an "
                                     "F-1→H-1B year can still claim a student-period treaty benefit on income earned "
                                     "while you were the student (pitfall P-004)."))
    if imm is None or not _has(imm.first_us_entry):
        out.append(_q("immigration.first_us_entry", "immigration", "When did you first enter the U.S.?",
                      "It anchors the exempt-individual count in the Substantial Presence Test.",
                      "immigration.first_us_entry"))


def _residency_questions(profile: Profile, out: list[IntakeQuestion], tax_year: int | None) -> None:
    ident = profile.identity
    if ident is None or not _has(ident.us_person) or ident.us_person.value is True:
        return
    rf = profile.residency_facts
    years_known = set(rf.days_in_us) if rf else set()
    need_year = tax_year is not None and tax_year not in years_known
    if rf is None or not years_known or need_year:
        yr = f" in {tax_year}" if tax_year else " for each relevant year"
        out.append(_q("residency.days_in_us", "residency",
                      f"How many days were you physically present in the U.S.{yr}?",
                      "The Substantial Presence Test counts these days to set resident vs nonresident status.",
                      "residency_facts.days_in_us",
                      disambiguation="If you can share your I-94 travel history we compute the days for you — exact "
                                     "dates beat a guess."))
    if rf is None or not _has(rf.home_country_address):
        out.append(_q("residency.home_country_address", "residency", "What is your home-country address?",
                      "Nonresident returns and some treaty claims require it.", "residency_facts.home_country_address"))


def _household_questions(profile: Profile, out: list[IntakeQuestion], notes: list[str]) -> None:
    hh = profile.household
    ident = profile.identity
    nonresident_path = ident is not None and _has(ident.us_person) and ident.us_person.value is False

    if hh is None or not _has(hh.marital_status):
        out.append(_q("household.marital_status", "household",
                      "Were you married on December 31 of the tax year?",
                      "Marital status on the last day of the year sets which filing statuses you may use.",
                      "household.marital_status",
                      disambiguation="This is a fact about Dec 31 — being married is NOT itself a filing status; "
                                     "married couples still choose between filing jointly or separately."))
        return  # filing-status question depends on the answer; ask it next round.

    married = str(hh.marital_status.value).strip().lower() in {"married", "yes", "true", "married_filing_jointly", "married_filing_separately"}

    if not _has(hh.filing_status):
        if married:
            note = ("Married couples choose married-filing-jointly (one combined return, usually lower tax, but both "
                    "spouses are jointly liable) or married-filing-separately. We can compute it both ways and show "
                    "the dollar difference.")
            if nonresident_path:
                note += (" If a spouse is a nonresident alien, filing jointly requires the §6013(g)/(h) election to "
                         "treat them as a U.S. resident — which makes their worldwide income taxable.")
            out.append(_q("household.filing_status", "household",
                          "Do you want to file jointly with your spouse or separately?",
                          "It changes your brackets, standard deduction, and credit eligibility.",
                          "household.filing_status", disambiguation=note))
        else:
            has_dependents = bool(hh.dependents)
            prompt = ("Did you pay more than half the cost of keeping up a home for a qualifying person (e.g. your "
                      "child)?" if has_dependents else
                      "Do you support a qualifying person (e.g. a child or relative) who lived with you?")
            out.append(_q("household.filing_status", "household", prompt,
                          "An unmarried taxpayer with a qualifying person may file head of household (lower tax than single).",
                          "household.filing_status",
                          disambiguation="If yes, you likely file head of household; if no, single. A recent widow(er) "
                                         "with a dependent child may qualify as a surviving spouse."))
        if nonresident_path:
            notes.append("Nonresident-alien filers (Form 1040-NR) cannot use married-filing-jointly or head of "
                         "household; the available statuses are single, married-filing-separately, or qualifying "
                         "surviving spouse — confirm residency to finalize.")

    # Spouse as a second taxpayer, once a married/joint path is chosen.
    if married:
        sp = hh.spouse
        if sp is None or not _has(sp.name):
            out.append(_q("household.spouse.name", "household", "What is your spouse's full legal name?",
                          "A joint (or separate) return needs the spouse's identity.", "household.spouse.name"))
        if sp is None or not _has(sp.tax_id):
            out.append(_q("household.spouse.tax_id", "household", "What is your spouse's SSN or ITIN?",
                          "Both taxpayers are identified on the return.", "household.spouse.tax_id"))

    if hh is None or not hh.dependents:
        out.append(_q("household.dependents", "household", "Do you have any dependents to claim? If so, list them.",
                      "Dependents drive the child tax credit, credit for other dependents, and EITC.",
                      "household.dependents"))


def _state_footprint_questions(profile: Profile, out: list[IntakeQuestion], tax_year: int | None) -> None:
    if tax_year is not None and tax_year in profile.state_footprint:
        return
    if profile.state_footprint:
        return
    out.append(_q("state_footprint.lived_worked", "state_footprint",
                  "For the tax year, where did you LIVE and where did you WORK, with date ranges?",
                  "It determines which state returns (if any) you must file and how income is sourced.",
                  "state_footprint",
                  disambiguation="List the states and the dates for each — moving mid-year or working remotely across "
                                 "state lines changes which states you file in."))


def _income_document_questions(profile: Profile, out: list[IntakeQuestion]) -> None:
    if not profile.income_documents:
        out.append(_q("income_documents.inventory", "income_documents",
                      "What income documents did you receive (W-2, 1099-NEC/INT/DIV/B, 1098-T, K-1, …)?",
                      "Every income document maps to lines on the return; missing ones leave gaps.",
                      "income_documents",
                      disambiguation="Include 'have', 'still need', and 'not applicable' for each — we file from "
                                     "documents, never from memory."))


def _banking_questions(profile: Profile, out: list[IntakeQuestion]) -> None:
    if profile.banking is None:
        out.append(_q("banking.account", "banking",
                      "For a refund by direct deposit (or to pay electronically), what are your bank routing and account numbers?",
                      "Direct deposit is the fastest refund; we checksum-validate the routing number.",
                      "banking",
                      disambiguation="Optional — you can also get a paper check or pay by check. Read the routing "
                                     "number from the bottom-left of a check, not the deposit slip."))


def _prior_filings_questions(profile: Profile, out: list[IntakeQuestion]) -> None:
    if profile.prior_filings is None:
        out.append(_q("prior_filings.history", "prior_filings",
                      "Which prior years have you filed, and are any years late or unfiled?",
                      "Late filings affect penalties and the 3-year refund statute of limitations.",
                      "prior_filings"))


# ── required-document derivation ──────────────────────────────────────────────


def _required_documents(profile: Profile) -> list[RequiredDocument]:
    docs: list[RequiredDocument] = []
    ident = profile.identity
    nonresident = ident is not None and _has(ident.us_person) and ident.us_person.value is False
    if nonresident:
        docs.append(RequiredDocument(kind="passport_id_page", why="Identity for a nonresident return."))
        docs.append(RequiredDocument(kind="visa", why="Confirms immigration status and dates."))
        docs.append(RequiredDocument(kind="I-94", why="Travel history; the Substantial Presence Test counts these days."))
        statuses = " ".join(p.status.upper() for p in (profile.immigration.visa_timeline if profile.immigration else []))
        if "F-1" in statuses or "F1" in statuses:
            docs.append(RequiredDocument(kind="I-20", why="F-1 student status document."))
        if "J-1" in statuses or "J1" in statuses:
            docs.append(RequiredDocument(kind="DS-2019", why="J-1 exchange-visitor status document."))

    # Reflect the user's declared income-document inventory and its status.
    for d in profile.income_documents:
        docs.append(RequiredDocument(kind=d.kind, why="Reports income that must appear on the return.", status=d.status))
    return docs


def _ready_to_fill(profile: Profile) -> bool:
    """Minimum facts to begin a draft: identity core + a chosen filing status + some income picture."""
    ident = profile.identity
    if ident is None or not (_has(ident.name) and _has(ident.tax_id) and _has(ident.mailing_address) and _has(ident.us_person)):
        return False
    hh = profile.household
    if hh is None or not _has(hh.filing_status):
        return False
    have_income = any(d.status == "have" for d in profile.income_documents)
    return have_income


def intake_checklist(profile: Profile | None = None, *, tax_year: int | None = None) -> IntakeChecklist:
    """Return the next interview questions + required documents for a partial profile.

    Args:
        profile: the partial profile so far; ``None`` (or ``Profile()``) is the
            start state and yields the opening questions.
        tax_year: when given, residency/state-footprint questions target that
            specific year (e.g. asks for days-in-US in 2023, not "each year").

    Returns:
        An :class:`IntakeChecklist`: ``next_questions`` (ordered by the §2 flow),
        ``required_documents`` (derived from known facts + the declared
        inventory), ``ready_to_fill``, ``progress``, and ``notes`` (gating
        explanations such as the 1040-NR status restriction).
    """
    profile = profile or Profile()
    out: list[IntakeQuestion] = []
    notes: list[str] = []

    _identity_questions(profile, out)
    _immigration_questions(profile, out, notes)
    _residency_questions(profile, out, tax_year)
    _household_questions(profile, out, notes)
    _state_footprint_questions(profile, out, tax_year)
    _income_document_questions(profile, out)
    _banking_questions(profile, out)
    _prior_filings_questions(profile, out)

    out.sort(key=lambda q: SECTIONS.index(q.section))

    started = _sections_started(profile)
    return IntakeChecklist(
        next_questions=out,
        required_documents=_required_documents(profile),
        ready_to_fill=_ready_to_fill(profile),
        progress=f"{started} of {len(SECTIONS)} sections started",
        notes=notes,
    )


def _sections_started(profile: Profile) -> int:
    started = 0
    if profile.identity is not None:
        started += 1
    if profile.immigration is not None:
        started += 1
    if profile.residency_facts is not None:
        started += 1
    if profile.household is not None:
        started += 1
    if profile.state_footprint:
        started += 1
    if profile.income_documents:
        started += 1
    if profile.banking is not None:
        started += 1
    if profile.prior_filings is not None:
        started += 1
    return started
