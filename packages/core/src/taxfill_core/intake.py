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

import re

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core import residency
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


def _marital(profile: Profile) -> str | None:
    """The closed marital-status fact ('married' / 'unmarried' / 'widowed'), or None."""
    hh = profile.household
    if hh is None or not _has(hh.marital_status):
        return None
    return str(hh.marital_status.value)


def _classification_from_facts(imm, rf, tax_year: int | None) -> str | None:
    """Best-effort federal residency classification from explicit facts, or None.

    Works on any person's immigration + residency facts (the taxpayer's, or the
    spouse's own facts on the §6013(g)/(h) path). Returns 'nonresident' /
    'resident' / 'dual_status_candidate' only when both a visa timeline and
    per-year day counts (and a target year) are present; otherwise None so
    callers gate conditionally rather than asserting a result.

    A 'nonresident' result that rests on treating a MISSING preceding lookback year as
    0 days (the visa timeline covers tax_year-1/tax_year-2 but days_in_us lacks them)
    is NOT asserted — real counts for those years could flip it to resident, so this
    returns None and intake keeps the conditional framing plus the follow-up question.
    """
    if tax_year is None:
        return None
    if imm is None or not imm.visa_timeline or rf is None or not rf.days_in_us:
        return None
    days_by_year = {y: a.value for y, a in rf.days_in_us.items() if a is not None and a.value is not None}
    if not days_by_year:
        return None
    try:
        classification = residency.classify(imm.visa_timeline, days_by_year, tax_year).classification
    except (ValueError, AssertionError):
        # Incomplete or contradictory inputs — cannot classify yet; gate conditionally.
        return None
    if classification == "nonresident" and any(
        y not in days_by_year and y in _covered_years_from(imm, tax_year)
        for y in (tax_year - 1, tax_year - 2)
    ):
        return None
    return classification


def _residency_classification(profile: Profile, tax_year: int | None) -> str | None:
    """The TAXPAYER's best-effort federal residency classification (see
    :func:`_classification_from_facts` for the trust rules)."""
    return _classification_from_facts(profile.immigration, profile.residency_facts, tax_year)


def _spouse_classification(profile: Profile, tax_year: int | None) -> str | None:
    """The SPOUSE's own best-effort residency classification, or None.

    Runs on the spouse's OWN visa timeline and day counts (Spouse.immigration /
    Spouse.residency_facts) — whether the couple even needs the §6013(g)/(h)
    election is decided by the spouse's classification, never the taxpayer's.
    """
    hh = profile.household
    sp = hh.spouse if hh is not None else None
    if sp is None:
        return None
    return _classification_from_facts(sp.immigration, sp.residency_facts, tax_year)


def _has_f1_period(profile: Profile) -> bool:
    """True when the visa timeline declares an F-1 (student) period."""
    imm = profile.immigration
    if imm is None:
        return False
    return any(p.status.strip().upper().replace("-", "").startswith("F1") for p in imm.visa_timeline)


def _has_fj_period(profile: Profile) -> bool:
    """True when the visa timeline declares any F or J status period (FICA-exempt categories)."""
    imm = profile.immigration
    if imm is None:
        return False
    return any(p.status.strip().upper().startswith(("F", "J")) for p in imm.visa_timeline)


def _covered_years_from(imm, tax_year: int) -> set[int]:
    """Calendar years up to ``tax_year`` overlapped by ANY declared status period."""
    if imm is None:
        return set()
    years: set[int] = set()
    for p in imm.visa_timeline:
        end_year = min(p.end.year if p.end else tax_year, tax_year)
        years.update(range(p.start.year, end_year + 1))
    return years


def _exempt_category_years_from(imm, tax_year: int) -> set[int]:
    """Calendar years up to ``tax_year`` overlapped by an F/J/M/Q exempt-category period.

    residency.classify() rejects the call unless days_in_us has an entry for every
    one of these years, so intake must ask for exactly this set (plus the SPT's
    three lookback years) — otherwise the interview dead-ends on a classify error.
    Takes the Immigration facts directly so the same rule covers the taxpayer AND
    the spouse (whose own classification drives the §6013(g)/(h) path).
    """
    if imm is None:
        return set()
    years: set[int] = set()
    for p in imm.visa_timeline:
        if not residency.is_exempt_category_status(p.status):
            continue
        end_year = min(p.end.year if p.end else tax_year, tax_year)
        years.update(range(p.start.year, end_year + 1))
    return years


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
    days_why = ("The Substantial Presence Test weighs THREE years — all of the tax year's days plus 1/3 of the "
                "first preceding year's and 1/6 of the second's — and every F/J/M/Q year needs a count too. A "
                "year left unanswered is treated as 0 days, which can misclassify a resident as nonresident.")
    days_disambiguation = ("Give a count for EVERY listed year — 0 is a valid answer for a year spent entirely "
                           "outside the U.S. If you can share your I-94 travel history we compute the days for "
                           "you; exact dates beat a guess.")
    if tax_year is not None:
        # classify() needs the tax year, its two preceding years, and every calendar
        # year an F/J/M/Q exempt-category period overlaps — ask for exactly that set,
        # following up on whichever years the profile still lacks.
        needed = {tax_year, tax_year - 1, tax_year - 2} | _exempt_category_years_from(profile.immigration, tax_year)
        missing = sorted(y for y in needed if y not in years_known)
        if missing:
            year_list = ", ".join(str(y) for y in missing)
            out.append(_q("residency.days_in_us", "residency",
                          f"How many days were you physically present in the U.S. in each of these years: "
                          f"{year_list}? (One count per year; answer 0 for a year spent entirely outside the U.S.)",
                          days_why,
                          "residency_facts.days_in_us",
                          disambiguation=days_disambiguation))
    elif rf is None or not years_known:
        out.append(_q("residency.days_in_us", "residency",
                      "How many days were you physically present in the U.S. in the tax year AND in each of the "
                      "two preceding years (plus any year you held F/J/M/Q status)?",
                      days_why,
                      "residency_facts.days_in_us",
                      disambiguation=days_disambiguation))
    if rf is None or not _has(rf.home_country_address):
        out.append(_q("residency.home_country_address", "residency", "What is your home-country address?",
                      "Nonresident returns and some treaty claims require it.", "residency_facts.home_country_address"))


def _household_questions(
    profile: Profile, out: list[IntakeQuestion], notes: list[str], tax_year: int | None
) -> None:
    hh = profile.household
    ident = profile.identity
    visa_holder = ident is not None and _has(ident.us_person) and ident.us_person.value is False
    # Gate the 1040-NR status restriction on the COMPUTED residency result (a true
    # NRA), not on us_person — a visa holder who passes the Substantial Presence Test
    # is a RESIDENT ALIEN who CAN use MFJ/HOH and needs no §6013 election. When residency
    # cannot be computed yet, frame the restriction conditionally.
    classification = _residency_classification(profile, tax_year)
    is_nonresident = classification == "nonresident"
    is_resident = classification == "resident"
    # The nonresident path applies if confirmed NRA, or if a visa holder whose residency
    # is not yet computable (conditional framing) — but never for a confirmed resident.
    nonresident_path = is_nonresident or (visa_holder and classification is None)
    residency_unknown = visa_holder and classification is None

    if hh is None or not _has(hh.marital_status):
        out.append(_q("household.marital_status", "household",
                      "Were you married, unmarried, or widowed on December 31 of the tax year?",
                      "Marital status on the last day of the year sets which filing statuses you may use.",
                      "household.marital_status",
                      disambiguation="Answer 'married', 'unmarried', or 'widowed'. This is a fact about Dec 31 — being "
                                     "married is NOT itself a filing status; married couples still choose between "
                                     "filing jointly or separately. Answer 'widowed' only if your spouse died in a "
                                     "recent year (it can open the qualifying-surviving-spouse status)."))
        return  # filing-status question depends on the answer; ask it next round.

    marital = _marital(profile)
    married = marital == "married"
    widowed = marital == "widowed"

    # The SPOUSE's own residency direction (§6013(g)/(h) path): a declared
    # non-US-person spouse whose own facts do NOT classify resident is (or may
    # be) a nonresident alien — a joint return then requires the election.
    sp = hh.spouse
    spouse_non_us = married and sp is not None and _has(sp.us_person) and sp.us_person.value is False
    spouse_class = _spouse_classification(profile, tax_year) if spouse_non_us else None
    spouse_nra_path = spouse_non_us and spouse_class != "resident"

    if married:
        if not _has(hh.filing_status):
            note = ("Married couples choose married-filing-jointly (one combined return, usually lower tax, but both "
                    "spouses are jointly liable) or married-filing-separately. We can compute it both ways and show "
                    "the dollar difference.")
            if nonresident_path:
                note += (" If a spouse is a nonresident alien, filing jointly requires the §6013(g)/(h) election to "
                         "treat them as a U.S. resident — which makes their worldwide income taxable.")
            elif spouse_nra_path:
                note += (" Your spouse is (or may be) a nonresident alien: filing jointly requires the §6013(g)/(h) "
                         "election to treat them as a U.S. resident — which makes their worldwide income taxable; "
                         "without the election you file married-filing-separately.")
            out.append(_q("household.filing_status", "household",
                          "Do you want to file jointly with your spouse or separately?",
                          "It changes your brackets, standard deduction, and credit eligibility.",
                          "household.filing_status", disambiguation=note))
        # Spouse as a second taxpayer on a married path.
        if sp is None or not _has(sp.name):
            out.append(_q("household.spouse.name", "household", "What is your spouse's full legal name?",
                          "A joint (or separate) return needs the spouse's identity.", "household.spouse.name"))
        if sp is None or not _has(sp.tax_id):
            if spouse_nra_path:
                # A possible-NRA spouse may hold NEITHER an SSN nor an ITIN — the plain
                # "what is it?" phrasing is a dead end there; say what each path needs.
                out.append(_q("household.spouse.tax_id", "household",
                              "Does your spouse have an SSN or ITIN? If so, what is it?",
                              "Both taxpayers are identified on the return.", "household.spouse.tax_id",
                              disambiguation="If your spouse has NEITHER an SSN nor an ITIN: filing jointly (the "
                                             "§6013(g)/(h) election) requires applying for an ITIN — Form W-7 is "
                                             "filed WITH the return, and the whole package (return, Form W-7, and "
                                             "the applicant's identity documents) mails to the IRS ITIN Operation "
                                             "in Austin, TX, not the normal where-to-file address. For married-"
                                             "filing-separately you may instead write 'NRA' in the spouse-SSN box — "
                                             "answer 'NRA' here to record that."))
            else:
                out.append(_q("household.spouse.tax_id", "household", "What is your spouse's SSN or ITIN?",
                              "Both taxpayers are identified on the return.", "household.spouse.tax_id"))
        _spouse_residency_questions(profile, out, notes, tax_year)
    elif widowed:
        # Qualifying-surviving-spouse routing: a recent widow(er) with a dependent child
        # may file as a qualifying surviving spouse — symmetric to the HOH routed question.
        if not _has(hh.spouse_death_year):
            out.append(_q("household.spouse_death_year", "household",
                          "In what year did your spouse die?",
                          "Qualifying surviving spouse is available for the two tax years AFTER the year of death.",
                          "household.spouse_death_year",
                          disambiguation="The year of death itself is normally a joint-return year; the surviving-"
                                         "spouse status applies to the next two tax years."))
        if not _has(hh.maintained_home_for_dependent_child):
            out.append(_q("household.maintained_home_for_dependent_child", "household",
                          "Did you pay more than half the cost of keeping up a home that was the main home of your "
                          "dependent child all year?",
                          "It is the key test for the qualifying-surviving-spouse status.",
                          "household.maintained_home_for_dependent_child",
                          disambiguation="If yes (and your spouse died within the prior two tax years), you may file "
                                         "as a qualifying surviving spouse (the lower married-filing-jointly tax). "
                                         "If no, you file as single."))
        elif _has(hh.spouse_death_year) and not _has(hh.filing_status):
            # Both QSS facts answered -> confirm the filing status so the interview can
            # actually complete (ready_to_fill requires household.filing_status).
            death_year = hh.spouse_death_year.value
            maintained = bool(hh.maintained_home_for_dependent_child.value)
            if tax_year is not None and death_year == tax_year:
                suggestion = ("your spouse died during the tax year, which is normally still a joint-return year "
                              "— married filing jointly")
            elif maintained and (tax_year is None or death_year in (tax_year - 1, tax_year - 2)):
                suggestion = ("you likely qualify as a qualifying surviving spouse (taxed at the "
                              "married-filing-jointly rates)")
            else:
                suggestion = "you likely file as single"
            out.append(_q("household.filing_status", "household",
                          f"Based on your answers, {suggestion} — please confirm your filing status.",
                          "A confirmed filing status is required before a draft return can start — it sets your "
                          "brackets, standard deduction, and credit eligibility.",
                          "household.filing_status",
                          disambiguation="Qualifying surviving spouse requires a spouse death in one of the two "
                                         "prior tax years AND keeping up the main home of your dependent child; "
                                         "otherwise an unmarried filer files single (or head of household with a "
                                         "qualifying person)."))
        if nonresident_path:
            notes.append("If your residency result is nonresident alien, Form 1040-NR has a qualifying-surviving-"
                         "spouse box but no head-of-household box.")
    else:
        # Unmarried. Branch the HOH-vs-single advice on the nonresident condition so it
        # agrees with the gating note: Form 1040-NR has no head-of-household box, so do
        # NOT recommend head of household on the nonresident path.
        if not _has(hh.hoh_qualifying_person):
            if nonresident_path:
                prompt = ("Did you support a qualifying person (e.g. a child or relative) who lived with you, and "
                          "pay more than half the cost of keeping up their home?")
                disamb = ("This records the head-of-household fact. Note: if your residency result is nonresident "
                          "alien, Form 1040-NR has no head-of-household box, so your options are single, married-"
                          "filing-separately, or qualifying surviving spouse — not head of household."
                          if residency_unknown else
                          "Form 1040-NR has no head-of-household box, so even if you support a qualifying person "
                          "your options as a nonresident alien are single, married-filing-separately, or "
                          "qualifying surviving spouse.")
            else:
                has_dependents = bool(hh.dependents)
                prompt = ("Did you pay more than half the cost of keeping up a home for a qualifying person (e.g. "
                          "your child)?" if has_dependents else
                          "Do you support a qualifying person (e.g. a child or relative) who lived with you?")
                disamb = ("If yes, you likely file head of household (lower tax than single); if no, single. A "
                          "recent widow(er) with a dependent child may instead qualify as a surviving spouse.")
            out.append(_q("household.hoh_qualifying_person", "household", prompt,
                          ("An unmarried taxpayer with a qualifying person may file head of household (lower tax "
                           "than single)." if not nonresident_path else
                           "It records the qualifying-person fact, though a nonresident alien cannot use head of "
                           "household."),
                          "household.hoh_qualifying_person", disambiguation=disamb))
        elif not _has(hh.filing_status):
            # The HOH fact is in: confirm the derived filing status so the unmarried
            # path can actually reach ready_to_fill through the interview alone.
            hoh_fact = bool(hh.hoh_qualifying_person.value)
            if is_nonresident:
                prompt = ("Please confirm your filing status: as an unmarried nonresident alien you file as "
                          "single (Form 1040-NR has no head-of-household box).")
                disamb = "Answer 'single' to confirm, or correct any earlier answer that is wrong."
            elif hoh_fact and residency_unknown:
                prompt = ("Based on your answers you may qualify for head of household — please confirm your "
                          "filing status: head of household or single?")
                disamb = ("Head of household usually means lower tax than single — but if your residency result "
                          "comes back nonresident alien, Form 1040-NR has no head-of-household box and you file "
                          "single. Confirm residency first if it is still open.")
            elif hoh_fact:
                prompt = ("Based on your answers you likely qualify for head of household — please confirm your "
                          "filing status: head of household or single?")
                disamb = ("Head of household usually means lower tax than single; it requires paying more than "
                          "half the cost of keeping up the home of a qualifying person who lived with you more "
                          "than half the year.")
            else:
                prompt = "Based on your answers you file as single — please confirm your filing status."
                disamb = ("Answer 'single' to confirm — or, if you actually did keep up a home for a qualifying "
                          "person, say so and we revisit head of household.")
            out.append(_q("household.filing_status", "household", prompt,
                          "A confirmed filing status is required before a draft return can start — it sets your "
                          "brackets, standard deduction, and credit eligibility.",
                          "household.filing_status", disambiguation=disamb))

    # Residency-gated status restriction note (conditional when not yet computable).
    if not _has(hh.filing_status):
        if is_nonresident:
            notes.append("Nonresident-alien filers (Form 1040-NR) cannot use married-filing-jointly or head of "
                         "household; the available statuses are single, married-filing-separately, or qualifying "
                         "surviving spouse.")
        elif is_resident and not spouse_nra_path:
            notes.append("Your residency result is resident alien, so all filing statuses are available — "
                         "married-filing-jointly and head of household included.")
        elif is_resident and spouse_nra_path:
            # "All statuses available" would be wrong law here: §6013(a)(1) bars a
            # joint return when EITHER spouse is a nonresident alien, absent the
            # election — the spouse-direction note below carries the restriction.
            pass
        elif residency_unknown:
            notes.append("If your residency result is nonresident alien, Form 1040-NR has no married-filing-jointly "
                         "or head-of-household box — the available statuses would be single, married-filing-"
                         "separately, or qualifying surviving spouse. If you are a resident alien, all statuses are "
                         "available. Confirm residency to finalize.")

    # An empty dependents list cannot distinguish "no dependents" from "not asked yet"
    # (the schema has no None sentinel), so the question is asked only until the
    # filing status is confirmed — the last household gate — instead of forever.
    if not hh.dependents and not _has(hh.filing_status):
        out.append(_q("household.dependents", "household",
                      "Do you have any dependents to claim? If so, list each one (name and relationship); "
                      "answer 'none' if you have no dependents.",
                      "Dependents drive the child tax credit, credit for other dependents, and EITC.",
                      "household.dependents",
                      disambiguation="We follow up per dependent for date of birth and SSN — those facts gate "
                                     "the credits."))

    # Per-dependent follow-ups: a name-only dependent cannot be evaluated for the
    # CTC/ODC/EITC (the estimator EXCLUDES dependents with no DOB), so ask until
    # every listed dependent has a date of birth and an SSN answer.
    for i, dep in enumerate(hh.dependents):
        if dep.dob is None:
            out.append(_q(f"household.dependents[{i}].dob", "household",
                          f"What is {dep.name}'s date of birth?",
                          "Age gates the Child Tax Credit (under 17), the credit for other dependents, and the "
                          "EITC — a dependent with no date of birth on file is EXCLUDED from these credits.",
                          f"household.dependents[{i}].dob"))
        if dep.has_ssn is None:
            out.append(_q(f"household.dependents[{i}].has_ssn", "household",
                          f"Does {dep.name} have a work-eligible Social Security number?",
                          "The Child Tax Credit and EITC require the dependent to have a work-eligible SSN; a "
                          "dependent with an ITIN/ATIN instead still gets the $500 credit for other dependents.",
                          f"household.dependents[{i}].has_ssn",
                          disambiguation="Answer yes for an SSN that is valid for employment (most SSNs are); "
                                         "answer no if the dependent has an ITIN or ATIN instead of an SSN."))


def _spouse_residency_questions(
    profile: Profile, out: list[IntakeQuestion], notes: list[str], tax_year: int | None
) -> None:
    """The NRA-spouse §6013(g)/(h) battery (married path only).

    A joint return generally requires both spouses to be U.S. persons or
    residents (§6013(a)(1)); whether the couple needs the §6013(g)/(h) election
    is decided by the SPOUSE'S own residency, so intake asks, in dependency
    order and without ever looping (each answered fact stops its question):

    - household.spouse.us_person (the gate — mirrors identity.us_person);
    - the spouse's own visa timeline + per-year day counts (enough for
      residency.classify on the spouse's own facts) when the spouse is not a
      US person;
    - whether the couple wants to evaluate the §6013(g)/(h) election when the
      spouse is (or may be) a nonresident alien — the answer IS the filing-
      status choice, so the question stops once household.filing_status is set.
    """
    hh = profile.household
    sp = hh.spouse
    if sp is None or not _has(sp.us_person):
        out.append(_q("household.spouse.us_person", "household",
                      "Is your spouse a U.S. citizen or lawful permanent resident (green-card holder)?",
                      "A joint return generally requires both spouses to be U.S. persons or residents — a "
                      "nonresident-alien spouse changes the filing-status options (§6013(g)/(h)).",
                      "household.spouse.us_person",
                      disambiguation="Answer yes only for citizens and green-card holders. A spouse on an "
                                     "F/J/H/L/etc. visa — or living abroad with no U.S. immigration status — "
                                     "answers no; we then check the spouse's own residency by their days in "
                                     "the U.S."))
        return  # the rest of the battery depends on this answer; ask it first.
    if sp.us_person.value is not False:
        return  # a US-person spouse needs no residency check and no election.

    imm = sp.immigration
    if imm is None or not imm.visa_timeline:
        out.append(_q("household.spouse.visa_timeline", "household",
                      "List each U.S. immigration status your spouse has held and its exact start/end dates "
                      "(if your spouse has never held U.S. status — e.g. lives abroad — say so).",
                      "The spouse's own residency (their visa periods plus days in the U.S.) decides whether a "
                      "joint return needs the §6013(g)/(h) election.",
                      "household.spouse.immigration.visa_timeline",
                      disambiguation="Use date ranges, not a single 'current status' — mid-year changes matter, "
                                     "exactly as for your own timeline (pitfall P-004)."))

    rf = sp.residency_facts
    years_known = set(rf.days_in_us) if rf else set()
    spouse_days_why = ("The Substantial Presence Test runs on the SPOUSE'S own days — it decides whether they "
                       "are already a U.S. resident (no election needed to file jointly) or a nonresident alien "
                       "(joint filing then needs the §6013(g)/(h) election).")
    spouse_days_disambiguation = ("Give a count for EVERY listed year — 0 is a valid answer for a year your "
                                  "spouse spent entirely outside the U.S. Their I-94 travel history gives exact "
                                  "dates; exact dates beat a guess.")
    if tax_year is not None:
        needed = {tax_year, tax_year - 1, tax_year - 2} | _exempt_category_years_from(imm, tax_year)
        missing = sorted(y for y in needed if y not in years_known)
        if missing:
            year_list = ", ".join(str(y) for y in missing)
            out.append(_q("household.spouse.days_in_us", "household",
                          f"How many days was your spouse physically present in the U.S. in each of these years: "
                          f"{year_list}? (One count per year; answer 0 for a year spent entirely outside the U.S.)",
                          spouse_days_why,
                          "household.spouse.residency_facts.days_in_us",
                          disambiguation=spouse_days_disambiguation))
    elif rf is None or not years_known:
        out.append(_q("household.spouse.days_in_us", "household",
                      "How many days was your spouse physically present in the U.S. in the tax year AND in each "
                      "of the two preceding years (plus any year they held F/J/M/Q status)?",
                      spouse_days_why,
                      "household.spouse.residency_facts.days_in_us",
                      disambiguation=spouse_days_disambiguation))

    classification = _spouse_classification(profile, tax_year)
    if classification == "resident":
        notes.append("Your spouse's own residency result is RESIDENT alien (they pass the Substantial Presence "
                     "Test), so a joint return is available without a §6013(g)/(h) election.")
        return
    if _has(hh.filing_status):
        return  # the election decision is recorded as the chosen filing status — stop asking.
    confirmed = classification == "nonresident"
    lead = ("Your spouse's residency result is NONRESIDENT alien."
            if confirmed else
            "Your spouse may be a nonresident alien (their residency is not confirmed yet).")
    out.append(_q("household.spouse.section_6013_election", "household",
                  f"{lead} Do you want to evaluate the §6013(g)/(h) election — treating your spouse as a U.S. "
                  f"resident so you can file jointly?",
                  "A joint return with a nonresident-alien spouse is only valid WITH the election (§6013(a)(1) "
                  "bars it otherwise); the choice changes the tax, whose income is taxed, and what must be "
                  "attached to the return.",
                  "household.filing_status",
                  disambiguation="Electing under §6013(g)/(h) treats the nonresident spouse as a U.S. RESIDENT: "
                                 "you file married-filing-jointly on your combined WORLDWIDE income — the "
                                 "spouse's foreign income becomes taxable too — and the election statement "
                                 "(signed by BOTH spouses) is attached to the first joint return. Declining "
                                 "means married-filing-separately: write 'NRA' in the spouse-SSN box if your "
                                 "spouse has no SSN or ITIN."))
    notes.append(
        ("Your spouse's residency result is nonresident alien: " if confirmed else
         "If your spouse is a nonresident alien: ")
        + "a joint return is only available by electing under §6013(g)/(h) to treat them as a U.S. resident "
          "(their worldwide income becomes taxable); without the election a married couple with a "
          "nonresident-alien spouse files married-filing-separately."
    )


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


def _mentions_1095a(kind: str) -> bool:
    return "1095A" in re.sub(r"[^0-9A-Z]", "", kind.upper())


def _income_document_questions(profile: Profile, out: list[IntakeQuestion], tax_year: int | None) -> None:
    if not profile.income_documents:
        out.append(_q("income_documents.inventory", "income_documents",
                      "What income documents did you receive (W-2, 1099-NEC/INT/DIV/B, 1098-T, K-1, …)?",
                      "Every income document maps to lines on the return; missing ones leave gaps.",
                      "income_documents",
                      disambiguation="Include 'have', 'still need', and 'not applicable' for each — we file from "
                                     "documents, never from memory."))
    # Marketplace coverage is the one document users predictably forget to volunteer,
    # and the one whose omission freezes refunds (Form 8962 reconciliation is
    # mandatory when advance premium tax credit was paid) — ask explicitly until a
    # 1095-A entry exists in ANY status ('not_applicable' records a 'no').
    if not any(_mentions_1095a(d.kind) for d in profile.income_documents):
        yr = str(tax_year) if tax_year is not None else "the tax year"
        out.append(_q("income_documents.marketplace_coverage", "income_documents",
                      f"Did you (or anyone on your return) have health insurance through the Marketplace — "
                      f"healthcare.gov or a state exchange — at any point in {yr}?",
                      "Marketplace coverage comes with Form 1095-A; if advance premium tax credit was paid, the "
                      "return MUST reconcile it on Form 8962 — omitting it gets the refund frozen (IRS letter 12C).",
                      "income_documents",
                      disambiguation="If yes, add a 1095-A entry to the document inventory (status 'have', or "
                                     "'missing' until you find it). If no, add a 1095-A entry with status "
                                     "'not_applicable' so the interview records the answer and stops asking."))


def _banking_questions(profile: Profile, out: list[IntakeQuestion]) -> None:
    if profile.banking is not None:
        return
    # 'No direct deposit, thanks' is not representable (Banking requires checksum-valid
    # routing/account numbers), so this OPTIONAL question is only ever asked alongside
    # other pending questions — declining it can never loop the interview forever.
    if not out:
        return
    out.append(_q("banking.account", "banking",
                  "For a refund by direct deposit (or to pay electronically), what are your bank routing and account numbers?",
                  "Direct deposit is the fastest refund; we checksum-validate the routing number.",
                  "banking",
                  disambiguation="Optional — you can also get a paper check or pay by check; if you decline, just "
                                 "skip this (the interview will not insist). Read the routing number from the "
                                 "bottom-left of a check, not the deposit slip."))


def _fica_exemption_note(profile: Profile, notes: list[str], tax_year: int | None) -> None:
    """FICA-withheld-in-error note for F/J visa holders (IRC §3121(b)(19)).

    Exempt-individual F/J nonresidents generally owe NO Social Security/Medicare tax,
    yet employers commonly withhold it anyway (W-2 boxes 4/6). The recovery path
    (employer refund, else Form 843 + Form 8316) is separate from the return and
    invisible unless someone says so — intake says so. Skipped for a computed
    RESIDENT (resident-alien F/J holders are generally FICA-liable); hedged
    conditionally while residency is still open.
    """
    ident = profile.identity
    if ident is None or not _has(ident.us_person) or ident.us_person.value is True:
        return
    if not _has_fj_period(profile):
        return
    classification = _residency_classification(profile, tax_year)
    if classification == "resident":
        return
    lead = ("Because your residency result is nonresident alien, your wages as an F/J exempt individual are "
            if classification == "nonresident" else
            "If your residency result is nonresident alien, your wages as an F/J exempt individual are ")
    notes.append(
        lead + "generally EXEMPT from Social Security and Medicare (FICA) taxes (IRC §3121(b)(19)). Check W-2 "
        "boxes 4 and 6: nonzero amounts there were likely withheld in error. Recovery is separate from this "
        "return — ask the employer for a refund first; if the employer will not refund it, file Form 843 with "
        "Form 8316 (mailed separately, NOT attached to the return; IRS Pub. 519, 'Refund of Taxes Withheld "
        "in Error')."
    )


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

    # M3-DOC-4: an NRA student (non-US-person with an F-1 period) who has not yet
    # declared any income documents gets the two income docs the spec's NRA-student
    # example names seeded as honest gaps (status='missing' is a gap marker, NOT
    # invented data — it says "we still need this", never asserts a value).
    if nonresident and _has_f1_period(profile) and not profile.income_documents:
        docs.append(RequiredDocument(kind="W-2", why="Reports wages from on-campus / OPT work that must appear on the return.", status="missing"))
        docs.append(RequiredDocument(kind="1098-T", why="Tuition statement; supports education-related entries for a student.", status="missing"))

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
    _household_questions(profile, out, notes, tax_year)
    _state_footprint_questions(profile, out, tax_year)
    _income_document_questions(profile, out, tax_year)
    _prior_filings_questions(profile, out)
    # Banking last: the optional direct-deposit question only accompanies other
    # pending questions (declining it is unrepresentable, so it must never repeat
    # alone and stall the interview) — the sort below restores the display order.
    _banking_questions(profile, out)
    _fica_exemption_note(profile, notes, tax_year)

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
