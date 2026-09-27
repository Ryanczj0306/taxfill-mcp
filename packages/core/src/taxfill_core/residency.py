"""Federal residency classification — dev plan sections 3 and 8.

Implements the Substantial Presence Test (SPT), the exempt-individual
calendar-year rules for F/J/M/Q statuses, and the nonresident / resident /
dual-status-candidate classification that scopes which federal returns a
user files (1040 vs 1040-NR, Form 8843).

Every rule below was verified against IRS Publication 519 (U.S. Tax Guide
for Aliens) and the IRS international-taxpayer pages on 2026-06-11:

* **Substantial presence test** — resident when physically present at least
  31 days during the current year AND 183 days during the 3-year window,
  counting "all the days you were present in the current year, and 1/3 of
  the days you were present in the first year before the current year, and
  1/6 of the days you were present in the second year before the current
  year." Pub 519's worked example: 120 days present in each of three years
  counts 120 + 40 + 20 = 180 -> NOT a resident. Fractions are kept exact
  (``fractions.Fraction``) and never rounded.
  https://www.irs.gov/individuals/international-taxpayers/substantial-presence-test

* **Exempt individual — students (F/J/M/Q)** — "You will not be an exempt
  individual as a student if you have been exempt as a teacher, trainee,
  student, Exchange Visitor, or Cultural Exchange Visitor on an 'F', 'J',
  'M', or 'Q' visa for any part of more than 5 calendar years": a LIFETIME
  total of 5 calendar years, where any partial calendar year consumes a
  whole year. A calendar year with ZERO days of US presence consumes
  nothing: an exempt individual is someone temporarily IN the United
  States, so with no presence there was no part of the year in which the
  person was exempt — the year counts toward neither the student 5-year
  limit nor the teacher/trainee 2-of-6 lookback. (The beyond-5-years
  carve-out for taxpayers who establish to the IRS that they do not intend
  to reside permanently in the US is NOT modeled in v1 — results say so
  when the limit bites.)
  https://www.irs.gov/individuals/international-taxpayers/exempt-individual-who-is-a-student

* **Exempt individual — teachers and trainees (J/Q non-students)** — "You
  will not be an exempt individual as a teacher or trainee if you were
  exempt as a teacher, trainee, or student for any part of 2 of the 6
  calendar years preceding the current year." (The foreign-employer
  compensation exception that stretches this to 3-of-6 is NOT modeled in
  v1 — results say so when the limit bites.)
  https://www.irs.gov/individuals/international-taxpayers/exempt-individuals-teachers-and-trainees

* **Residency starting date / dual status** — "If you meet the substantial
  presence test for a calendar year, your residency starting date is
  generally the first day you are present in the United States during that
  calendar year"; an exempt individual "is not considered to be present in
  the United States", so the starting date may be later than arrival — the
  classic mid-year split (e.g. F-1 -> H-1B). The engine FLAGS dual-status
  candidates with a plain-language explanation; the agent + user decide.
  https://www.irs.gov/individuals/international-taxpayers/residency-starting-and-ending-dates

* **Residency in the preceding year** (JF5b, P-018; IRC 7701(b), Treas. Reg.
  301.7701(b)-4 and Pub 519 (2025) ch. 1 read 2026-09-27) — "An alien
  individual who was a United States resident during any part of the preceding
  calendar year and who is a United States resident for any part of the current
  year will be considered to be taxable as a resident at the beginning of the
  current year" (Treas. Reg. 301.7701(b)-4(e)(1)), so ``prior_year_resident=True``
  with the SPT met is a full-year resident (no arrival split). The fact is the
  return filed for the prior year (PriorFilings.return_forms on a profile —
  :func:`prior_year_resident_from_return_forms`); the form is evidence, not the
  test, so True with the SPT NOT met is a flagged CONTRADICTION, never definitive.

* **Green card test** — a lawful permanent resident at any time during the
  calendar year is a resident for tax purposes regardless of the SPT.
  https://www.irs.gov/individuals/international-taxpayers/alien-residency-green-card-test

* **§6013(g)/(h) election** (P-018; Pub 519 (2025) ch. 1, Pub 501 (2025)
  and IRC 6013(g)/(h) read 2026-09-25) — "If you make this choice, you and
  your spouse are treated for income tax purposes as residents for your
  entire tax year", so ``section_6013_election=True`` returns ``resident``
  with no dual-status flag and keeps the day-count answer as
  ``classification_without_election``: the election covers "chapter 1 for
  all of such taxable year" and chapter 24 wage withholding only, so FICA
  (chapter 21) and the election's own precondition still follow the SPT
  answer. They are two choices — 6013(g) (a nonresident spouse at year end;
  it continues into later years) and 6013(h) (the year a nonresident becomes
  a resident, both spouses residents at year end; one year only, a different
  statement) — and :func:`section_6013_texts` quotes the one that applies.
  https://www.irs.gov/publications/p519

* **Closer connection exception** — someone who meets the SPT but was
  present fewer than 183 countable days in the current year (exempt-
  individual days are not days of presence under IRC 7701(b)), keeps a tax
  home in a foreign country, and has a closer connection to it can still be
  a nonresident (Form 8840). Mentioned in ``reasons`` where relevant; never
  computed in v1.
  https://www.irs.gov/individuals/international-taxpayers/closer-connection-exception-to-the-substantial-presence-test

Scope notes (v1):

* Substantial compliance with visa requirements is assumed; the agent must
  confirm it with the user.
* Foreign government-related individuals (A/G visas other than A-3/G-5) are
  exempt with NO year limit and are not modeled — a prescriptive error tells
  the caller how to handle them. Professional athletes at charitable events
  and medical-condition days are likewise out of scope and simply count, as
  are the other don't-count day categories (Canada/Mexico commuters,
  under-24-hour transit, foreign-vessel crew) — exclude those days when
  building ``days_by_year``.
* Dependents (F-2/J-2/...) share the principal's category: describe the
  status so the category is visible, e.g. ``"J-2 (dependent of J-1
  researcher)"``.
* The visa timeline is assumed complete: every day counted in
  ``days_by_year`` falls inside some declared period (add a ``"B-2
  visitor"`` period for tourist stays). ``classify`` rejects day counts in
  years with no covering period.

Module coupling: mostly standalone by design. ``days_by_year`` arrives as
plain input (conceptually produced by ``calc.presence_days`` from I-94
history in a later milestone) and ``visa_periods`` rows are
shape-compatible with ``schemas/profile.py`` ``VisaPeriod`` (``status`` /
``start`` / ``end``, where ``end=None`` while the period is ongoing) — this
module imports neither, so the integrator wires them later. The one shared
import is the :class:`~taxfill_core.knowledge.Citation` model (source +
url), so residency results cite Pub 519 in exactly the same shape calc
results cite the knowledge packs (dev plan section 8).
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from fractions import Fraction
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import Citation

ExemptCategory = Literal["student", "teacher_trainee"]
ExemptCoverage = Literal["full_year", "partial_year"]
Classification = Literal["nonresident", "resident", "dual_status_candidate"]

CITATION_SPT = Citation(
    source="IRS Pub. 519 (U.S. Tax Guide for Aliens), 'Substantial Presence Test'",
    url="https://www.irs.gov/individuals/international-taxpayers/substantial-presence-test",
)
CITATION_EXEMPT_STUDENT = Citation(
    source="IRS Pub. 519, 'Exempt individual — who is a student'",
    url="https://www.irs.gov/individuals/international-taxpayers/exempt-individual-who-is-a-student",
)
CITATION_EXEMPT_TEACHER = Citation(
    source="IRS Pub. 519, 'Exempt individuals: teachers and trainees'",
    url="https://www.irs.gov/individuals/international-taxpayers/exempt-individuals-teachers-and-trainees",
)
CITATION_RESIDENCY_DATES = Citation(
    source="IRS Pub. 519, 'Residency starting and ending dates'",
    url="https://www.irs.gov/individuals/international-taxpayers/residency-starting-and-ending-dates",
)
CITATION_GREEN_CARD = Citation(
    source="IRS Pub. 519, 'Green card test'",
    url="https://www.irs.gov/individuals/international-taxpayers/alien-residency-green-card-test",
)
CITATION_CLOSER_CONNECTION = Citation(
    source="IRS Pub. 519, 'Closer connection exception to the substantial presence test' (Form 8840)",
    url=(
        "https://www.irs.gov/individuals/international-taxpayers/"
        "closer-connection-exception-to-the-substantial-presence-test"
    ),
)
CITATION_SECTION_6013 = Citation(
    source=(
        "IRS Pub. 519, ch. 1 'Nonresident Spouse Treated as a Resident' (IRC 6013(g)) / "
        "'Choosing Resident Alien Status' (IRC 6013(h))"
    ),
    url="https://www.irs.gov/publications/p519",
)

# The §6013(g)/(h) election's effect, quoted (P-018). Read 2026-09-25 on Pub 519
# (2025) ch. 1 (irs.gov/publications/p519), Pub 501 (2025) and IRC 6013(g)/(h) on
# uscode.house.gov. They are TWO choices with different rules, so they are two
# texts: IRC 6013(g) — at year end one spouse is a nonresident alien and the other
# a U.S. citizen or resident ("Nonresident Spouse Treated as a Resident"; it
# continues into later years) — and IRC 6013(h) — the year a nonresident alien
# becomes a resident, both spouses U.S. citizens or residents at year end
# ("Choosing Resident Alien Status"; one year only, a different statement). One
# text per choice, so the residency tool, the estimator and intake say the same
# thing, and section_6013_texts() picks which one applies from the no-election
# residency answers.
SECTION_6013G_EFFECT = (
    "IRC 6013(g) — Pub 519 ch. 1, Nonresident Spouse Treated as a Resident: \"If you make this choice, you "
    "and your spouse are treated for income tax purposes as residents for your entire tax year. Neither you "
    "nor your spouse can claim under any tax treaty not to be a U.S. resident. You are both taxed on "
    "worldwide income. You must file a joint income tax return for the year you make the choice, but you "
    "and your spouse can file joint or separate returns in later years.\" And: \"If you file a joint "
    "return under this provision, the special instructions and restrictions for dual-status taxpayers in "
    "chapter 6 do not apply to you.\""
)
SECTION_6013G_PRECONDITION = (
    "The IRC 6013(g) choice needs a spouse who is a U.S. citizen or resident at year end — Pub 519 ch. 1: "
    "\"If, at the end of your tax year, you are married and one spouse is a U.S. citizen or a resident alien "
    "and the other spouse is a nonresident alien, you can choose to treat the nonresident spouse as a U.S. "
    "resident. This includes situations in which one spouse is a nonresident alien at the beginning of the "
    "tax year, but a resident alien at the end of the year, and the other spouse is a nonresident alien at "
    "the end of the year.\" Two spouses who are both nonresident aliens at year end cannot MAKE it. An "
    "election made in an EARLIER year that remains in effect is tested differently — IRC 6013(g)(3): it "
    "\"shall not apply for any taxable year if neither spouse is a citizen or resident of the United States "
    "at any time during such year\" (Pub 519, Suspending the Choice)."
)
SECTION_6013G_STATEMENT = (
    "How to make the IRC 6013(g) choice (Pub 519 ch. 1, How To Make the Choice): \"check the box in the "
    "Filing Status section of Form 1040 or 1040-SR and enter the name of the nonresident spouse in the entry "
    "space, and attach a statement, signed by both spouses, to your joint return for the first tax year for "
    "which the choice applies\", containing \"A declaration that one spouse was a nonresident alien and the "
    "other spouse a U.S. citizen or resident alien on the last day of your tax year, and that you choose to "
    "be treated as U.S. residents for the entire tax year\" and \"The name, address, and TIN of each "
    "spouse\"; in a later year: \"Also, check the box and enter their name if you and your nonresident "
    "spouse made the choice to be treated as residents in a prior year and the choice remains in effect.\""
)
SECTION_6013H_EFFECT = (
    "IRC 6013(h), the year a nonresident alien becomes a resident — Pub 519 ch. 1, Choosing Resident Alien "
    "Status: \"You and your spouse are treated as U.S. residents for the entire year for income tax "
    "purposes.\" \"You and your spouse are taxed on worldwide income.\" \"You and your spouse must file a "
    "joint return for the year of the choice.\" \"Neither you nor your spouse can make this choice for any "
    "later tax year, even if you are separated, divorced, or remarried.\" \"The special instructions and "
    "restrictions for dual-status taxpayers in chapter 6 do not apply to you.\" Pub 501: \"You can only make "
    "this choice for 1 year, and it doesn't apply to any future years.\" Unless an IRC 6013(g) election made "
    "in an earlier year remains in effect — Pub 519's Note: \"If you previously made that choice and it is "
    "still in effect, you do not need to make the choice explained here\" (IRC 6013(g)(3): it applies \"to "
    "all subsequent taxable years until terminated\"); this year is then a later year of that election, "
    "which may be filed jointly or separately."
)
SECTION_6013H_PRECONDITION = (
    "The IRC 6013(h) choice — Pub 519 ch. 1, Choosing Resident Alien Status: \"If you are a dual-status "
    "alien, you can choose to be treated as a U.S. resident for the entire year if all of the following "
    "apply\": \"You were a nonresident alien at the beginning of the year.\" \"You are a resident alien or "
    "U.S. citizen at the end of the year.\" \"You are married to a U.S. citizen or resident alien at the end "
    "of the year.\" \"Your spouse joins you in making the choice.\" \"This includes situations in which both "
    "you and your spouse were nonresident aliens at the beginning of the tax year and both of you are "
    "resident aliens at the end of the tax year.\""
)
SECTION_6013H_STATEMENT = (
    "How to make the IRC 6013(h) choice (Pub 519 ch. 1, Choosing Resident Alien Status — Making the choice): "
    "\"check the box in the Filing Status section of the Form 1040 or 1040-SR and enter the name of the "
    "dual-status spouse(s) in the entry space, and attach a statement signed by both spouses to your joint "
    "return for the year of the choice\", containing \"A declaration that you both qualify to make the "
    "choice and that you choose to be treated as U.S. residents for the entire tax year\" and \"The name, "
    "address, and TIN (social security number (SSN) or individual taxpayer identification number (ITIN)) of "
    "each spouse\". No new statement when an earlier IRC 6013(g) election remains in effect (Pub 519's Note: "
    "\"If you previously made that choice and it is still in effect, you do not need to make the choice "
    "explained here\") — then \"check the box and enter their name if you and your nonresident spouse made "
    "the choice to be treated as residents in a prior year and the choice remains in effect\"."
)
SECTION_6013_FICA = (
    "The election does NOT reach FICA: IRC 6013(g)(1) treats the electing nonresident as a resident \"(A) "
    "for purposes of chapter 1 for all of such taxable year, and (B) for purposes of chapter 24 (relating "
    "to wage withholding)\" (IRC 6013(h)(1) says the same of the dual-status year) — social security and "
    "Medicare tax is chapter 21, where IRC 3121(b)(19) still excludes \"Service which is performed by a "
    "nonresident alien individual for the period he is temporarily present in the United States as a "
    "nonimmigrant under subparagraph (F), (J), (M), or (Q) of section 101(a)(15) of the Immigration and "
    "Nationality Act, as amended, and which is performed to carry out the purpose specified in subparagraph "
    "(F), (J), (M), or (Q), as the case may be\" — service that carries out the visa's purpose. So an F/J/M/Q "
    "exempt individual's FICA exemption is unchanged: pass the classification WITHOUT the election "
    "(classification_without_election) to calc op employee_fica."
)

# What declining the choice leaves (Pub 501 (2025), Considered Unmarried, read
# 2026-09-25): no joint return — but head of household stays open to the citizen or
# resident spouse who has another qualifying person.
SECTION_6013_DECLINE = (
    "Declining the election means no joint return — the nonresident spouse, if required to file (Pub 519 ch. 7: "
    "\"Nonresident aliens who are required to file an income tax return should use Form 1040-NR\"), files Form "
    "1040-NR (married filing separately; in a dual-status year, the dual-status return and statement Pub 519 "
    "ch. 6 describes), and the "
    "U.S. citizen or resident spouse files married filing separately, or head of "
    "household with another qualifying person (Pub 501, Considered Unmarried: \"You are considered unmarried "
    "for head of household purposes if your spouse was a nonresident alien at any time during the year and "
    "you don't choose to treat your nonresident spouse as a resident alien. However, your spouse isn't a "
    "qualifying person for head of household purposes.\")."
)

# Without the election there is no joint return with a nonresident alien (Pub 519 (2025),
# Frequently Asked Questions, read 2026-09-26) — the text a joint status that the facts
# rule out is answered with (P-018).
SECTION_6013_NO_JOINT = (
    "Pub 519, Frequently Asked Questions: \"Generally, you cannot file as married filing jointly if either "
    "spouse was a nonresident alien at any time during the tax year. However, nonresident aliens married to "
    "U.S. citizens or residents can choose to be treated as U.S. residents and file joint returns.\""
)

# The election has no effect in a year NEITHER spouse is a U.S. citizen or resident at any
# time (IRC 6013(g)(3) on uscode.house.gov and Pub 519 (2025) ch. 1, Suspending the
# Choice, read 2026-09-26). Worded on the facts RECORDED: a green card held for part of the
# year, or presence the timeline leaves out, can hide part-year residency. A taxpayer whose
# prior-year return (PriorFilings.return_forms) reads as a resident is never a CERTAIN
# nonresident (certain_nonresident), so this text never answers one (JF5b).
SECTION_6013_SUSPENDED = (
    "On the facts recorded here NEITHER spouse is a U.S. citizen or resident at any time in the year (each "
    "classifies nonresident on their own visa timeline and day counts), and then the election is NOT "
    "available — a new one cannot be made (Pub 519 ch. 1: the choice needs \"one spouse is a U.S. citizen or "
    "a resident alien\" at the end of the year), and one made in an earlier year does not apply: IRC "
    "6013(g)(3), \"any such election shall not apply for any taxable year if neither spouse is a citizen or "
    "resident of the United States at any time during such year\"; Pub 519 ch. 1, Suspending the Choice: "
    "\"The choice to be treated as a resident alien is suspended for any tax year (after the tax year you "
    "made the choice) if neither spouse is a U.S. citizen or resident alien at any time during the tax "
    "year. This means each spouse must file a separate return as a nonresident alien for that year if either "
    "meets the filing requirements for nonresident aliens discussed in chapter 7\". So it is NOT applied: "
    "married filing separately, each spouse who meets the nonresident filing requirements on Form 1040-NR. "
    "If either of you was a U.S. "
    "resident for part of the year on facts not recorded here — a green card held for part of it, or U.S. "
    "presence the visa timeline or day counts leave out — the election may still apply: record the full "
    "visa timeline and days in the US, and the return you (the taxpayer) filed for the prior year "
    "(prior_filings.return_forms: a prior-year resident is never treated as a certain nonresident here — the "
    "spouse's prior-year return is not yet a recorded fact), and rerun."
)

# Which choice a couple is making, from each spouse's residency WITHOUT the election:
# 'us' (a declared U.S. citizen or green-card holder), 'resident', 'nonresident'
# (full year), 'dual_status_candidate' (this classifier flags a dual-status year only
# when the SPT is met with a nonresident part BEFORE the residency starting date — an
# arrival year) or None (unknown).
Section6013Kind = Literal["g", "h", "either"]


def section_6013_kind(taxpayer: str | None, spouse: str | None, *, recorded: bool = False) -> Section6013Kind:
    """'g', 'h', or 'either' (not decidable from the facts on file) — P-018.

    IRC 6013(g) when either spouse is a nonresident alien for the whole year (so at
    year end); IRC 6013(h) when one spouse's year is a dual-status arrival year and
    the other is a U.S. citizen or resident (or also arrived) — both residents at
    year end, one nonresident at the start; otherwise 'either'.

    ``recorded``: the election is a RECORDED answer (true = elect, or an earlier
    election remains in effect). Facts that point to 6013(h) then give 'either': a
    6013(g) election made in an earlier year continues (IRC 6013(g)(3)) and Pub 519's
    Note says "If you previously made that choice and it is still in effect, you do
    not need to make the choice explained here". The prior-year return is recorded in
    PriorFilings.return_forms (a '1040_with_6013_election' entry shows an election made
    earlier), but this function takes residency answers only and does not read it, so a
    recorded election on (h) facts stays 'either' and the texts give both readings.
    """
    if taxpayer == "nonresident" or spouse == "nonresident":
        return "g"
    at_year_end_us = ("us", "resident", "dual_status_candidate")
    if (taxpayer == "dual_status_candidate" and spouse in at_year_end_us) or (
        spouse == "dual_status_candidate" and taxpayer in at_year_end_us
    ):
        return "either" if recorded else "h"
    return "either"


def section_6013_texts(kind: Section6013Kind) -> tuple[str, str, str]:
    """The (effect, precondition, statement) texts for ``kind`` — both, conditionally, for 'either'."""
    if kind == "g":
        return SECTION_6013G_EFFECT, SECTION_6013G_PRECONDITION, SECTION_6013G_STATEMENT
    if kind == "h":
        return SECTION_6013H_EFFECT, SECTION_6013H_PRECONDITION, SECTION_6013H_STATEMENT
    g_if = "If on the last day of the year one of you is a nonresident alien, it is the IRC 6013(g) choice: "
    h_if = (
        "If you are both U.S. citizens or residents on the last day and one of you was a nonresident alien on "
        "the first day (a dual-status year), it is the IRC 6013(h) choice instead: "
    )
    return (
        f"{g_if}{SECTION_6013G_EFFECT} {h_if}{SECTION_6013H_EFFECT}",
        f"{SECTION_6013G_PRECONDITION} {SECTION_6013H_PRECONDITION}",
        f"{g_if}{SECTION_6013G_STATEMENT} {h_if}{SECTION_6013H_STATEMENT}",
    )


def section_6013_effect_quote(kind: Section6013Kind) -> str:
    """The one-sentence Pub 519 effect quote for ``kind`` (both, joined by 'or', for 'either')."""
    g_quote = (
        "'you and your spouse are treated for income tax purposes as residents for your entire tax year' "
        "(Pub 519 ch. 1, Nonresident Spouse Treated as a Resident — IRC 6013(g))"
    )
    h_quote = (
        "'You and your spouse are treated as U.S. residents for the entire year for income tax purposes' "
        "(Pub 519 ch. 1, Choosing Resident Alien Status — IRC 6013(h))"
    )
    return g_quote if kind == "g" else h_quote if kind == "h" else f"{g_quote}, or {h_quote}"


# Back-compatible names: the 'either' texts, for surfaces that know neither spouse's facts.
SECTION_6013_EFFECT, SECTION_6013_PRECONDITION, SECTION_6013_STATEMENT = section_6013_texts("either")

# Residency in the PRECEDING year (JF5b, P-018). Read 2026-09-27: IRC 7701(b) on
# uscode.house.gov ("in effect on September 26, 2026"), Treas. Reg. 301.7701(b)-4 on
# ecfr.gov, and Pub 519 (2025) ch. 1. The partial-year (dual-status arrival) rule reaches
# only an alien who was NOT a resident at any time in the preceding year; anyone else who
# is a resident for any part of the current year is a resident from January 1.
PRIOR_YEAR_RESIDENCY_LAW = (
    "Treas. Reg. 301.7701(b)-4(e)(1), Residency in prior year: \"An alien individual who was a United States "
    "resident during any part of the preceding calendar year and who is a United States resident for any part "
    "of the current year will be considered to be taxable as a resident at the beginning of the current year. "
    "For purposes of this paragraph (e)(1), it is immaterial whether an individual is considered to be a "
    "resident under the substantial presence test or the green card test.\" Pub 519 ch. 1, Residency during "
    "the preceding year: \"If you were a U.S. resident during any part of the preceding calendar year and you "
    "are a U.S. resident for any part of the current year, you will be considered a U.S. resident at the "
    "beginning of the current year.\" The partial-year rule of IRC 7701(b)(2)(A)(i) applies only to an alien "
    "who \"was not a resident of the United States at any time during the preceding calendar year\"."
)
# IRC 7701(b)(4)(A)(ii): the First-Year Choice needs an individual who "was not a resident of
# the United States under paragraph (1)(A) with respect to the calendar year immediately
# preceding the election year".
FIRST_YEAR_CHOICE_BARRED = (
    "Pub 519's First-Year Choice is not open to a prior-year resident: IRC 7701(b)(4)(A)(ii) requires that the "
    "individual \"was not a resident of the United States under paragraph (1)(A) with respect to the calendar "
    "year immediately preceding the election year\"."
)
# IRC 7701(b)(1)(A)/(B): residency comes from the tests alone ("if (and only if)"), so the
# form a prior-year return was filed on is evidence, never the test.
_RESIDENT_IF_AND_ONLY_IF = (
    "IRC 7701(b)(1)(A): an alien \"shall be treated as a resident of the United States with respect to any "
    "calendar year if (and only if)\" the green card test, the substantial presence test or the first-year "
    "election is met"
)

# The prior year's return (PriorFilings.return_forms[target_year - 1]) as the prior-year
# residency fact classify() takes. '1040' is a resident's return for the year and
# 'dual_status' a split year (a resident "during any part of the preceding calendar year"
# is enough); '1040-NR' is a nonresident's; 'not_filed' says nothing; and a joint Form 1040
# under the §6013(g)/(h) election is NOT read as residency — the election treats the
# spouse as a resident "for purposes of chapter 1" (IRC 6013(g)(1)), while IRC 7701(b)(1)
# defines residency by the three tests, and no text read says which one the carryover
# follows (a labeled judgment: prior_year_election_reason).
PRIOR_RETURN_RESIDENT: dict[str, bool | None] = {
    "1040": True,
    "dual_status": True,
    "1040-NR": False,
    "not_filed": None,
    "1040_with_6013_election": None,
}


def prior_year_return_form(return_forms: Mapping[Any, Any] | None, target_year: int) -> str | None:
    """The return recorded for ``target_year - 1`` (a plain value or an Answer's ``.value``), or None."""
    if not return_forms:
        return None
    entry = None
    for key, value in return_forms.items():
        try:
            if int(key) == target_year - 1:
                entry = value
                break
        except (TypeError, ValueError):
            continue
    value = getattr(entry, "value", entry)
    return str(value) if value is not None else None


def prior_year_resident_from_return_forms(return_forms: Mapping[Any, Any] | None, target_year: int) -> bool | None:
    """The prior-year residency fact from PriorFilings.return_forms — the entry for
    ``target_year - 1`` ONLY (IRC 7701(b)(2)(A)(i) and Treas. Reg. 301.7701(b)-4(e)(1) look
    at "the preceding calendar year"); a missing entry, 'not_filed' and
    '1040_with_6013_election' are None (unknown). Never inferred from filed_years."""
    form = prior_year_return_form(return_forms, target_year)
    return PRIOR_RETURN_RESIDENT.get(form) if form is not None else None


def prior_year_election_reason(target_year: int) -> str:
    """Why a prior-year joint Form 1040 under the §6013(g)/(h) election is not read as
    prior-year residency — a labeled judgment, with what to record instead."""
    prior = target_year - 1
    return (
        f"Your {prior} return is recorded as a joint Form 1040 under the §6013(g)/(h) election "
        f"(prior_filings.return_forms). It is NOT read here as residency in {prior} — a judgment, because the law "
        f"read does not settle it: the election treats the spouse as a resident \"for purposes of chapter 1 for "
        f"all of such taxable year\" (IRC 6013(g)(1)), while IRC 7701(b)(1) defines residency by the tests alone "
        f"({_RESIDENT_IF_AND_ONLY_IF}), and the rule that makes a prior-year resident a resident from January 1 "
        f"(Treas. Reg. 301.7701(b)-4(e)(1)) does not say which one it follows. Whether {prior} was a resident "
        f"year WITHOUT the election decides it: record the days in the U.S. for {prior}, {prior - 1} and "
        f"{prior - 2} and the visa timeline covering them, so {prior} can be classified on its own facts."
    )

# When the weighted total falls short of 183 but lands at or above this
# value, the nonresident result reminds the user to recount days and that
# the closer-connection exception exists (dev plan: the engine flags, the
# agent + user decide). 165 weighted days ~= within 10% of the threshold.
_NEAR_183_WEIGHTED = 165

# F and M visas are always students for the exempt-individual rules.
_FM_STATUS_RE = re.compile(r"^[fm](?:\d|\b)")
# J and Q visas split into students vs teachers/trainees by program category.
_JQ_STATUS_RE = re.compile(r"^[jq](?:\d|\b)")
# WORK AUTHORIZATIONS users routinely type in place of the visa status. OPT /
# STEM OPT / cap-gap / CPT are periods OF F-1 (or M-1) student status — the
# person's exempt-individual category is unchanged while working. Before this
# guard existed, a period entered as bare 'OPT' matched no prefix, its days
# silently counted toward the SPT, and classify() flipped nonresident→resident
# on a wording difference ('F-1 OPT' vs 'OPT', identical facts). "practical
# training" catches the spelled-out forms (Optional/Curricular Practical
# Training); \b keeps 'opt' from firing inside ordinary words.
_WORK_AUTH_RE = re.compile(r"\b(?:opt|cpt|cap[- ]gap|practical training)\b")
# Foreign government-related A/G visas (exempt with no year limit; v1 rejects
# them prescriptively, except A-3/G-5 which are NOT exempt and count normally).
_AG_STATUS_RE = re.compile(r"^([ag])\s*-?\s*([1-5])\b")

# DS-2019 box-4 program categories that Pub 519 buckets as teachers/trainees.
_TEACHER_TRAINEE_KEYWORDS = (
    "teacher",
    "trainee",
    "researcher",
    "research scholar",
    "scholar",
    "professor",
    "intern",
    "physician",
    "specialist",
    "au pair",
    "camp counselor",
    "summer work",
)


class _Period(NamedTuple):
    """A normalized visa period plus its exempt-individual category (None = days count)."""

    status: str
    start: date
    end: date | None  # None while the period is still ongoing
    category: ExemptCategory | None


class SPTResult(BaseModel):
    """Outcome of the substantial presence test for one target year."""

    model_config = ConfigDict(extra="forbid")

    target_year: int
    meets_spt: bool = Field(description="True when BOTH the 31-day and the 183-weighted-day prongs are met.")
    meets_31_day_test: bool
    meets_183_day_test: bool
    days_current_year: int
    days_first_preceding_year: int
    days_second_preceding_year: int
    weighted_days: float = Field(description="Exact weighted total as a float, for display only.")
    weighted_days_exact: str = Field(description="Exact weighted total, e.g. '180' or '182 2/3' — never rounded.")
    inputs: dict[str, Any] = Field(description="Echo of the inputs this result was computed from.")
    work: str = Field(description="The day-count arithmetic, shown step by step.")
    citations: list[Citation]


class ExemptYearRecord(BaseModel):
    """One calendar year's exempt-individual evaluation."""

    model_config = ConfigDict(extra="forbid")

    year: int
    exempt: bool
    categories: list[ExemptCategory] = Field(
        default_factory=list,
        description="Categories under which the exemption applies this year (empty when exempt=False).",
    )
    coverage: ExemptCoverage | None = Field(
        default=None,
        description=(
            "'full_year' when exempt periods cover the entire declared status timeline for the year "
            "(all days present are excluded); 'partial_year' when only part is covered; None when not exempt."
        ),
    )
    reason: str


class ExemptYearsResult(BaseModel):
    """Which calendar years' presence days are excluded from the SPT, and why."""

    model_config = ConfigDict(extra="forbid")

    target_year: int
    records: list[ExemptYearRecord] = Field(
        description="One record per calendar year with any F/J/M/Q-category period, earliest through target_year."
    )
    fully_exempt_years: list[int] = Field(
        description="Years whose presence days are excluded entirely from the SPT."
    )
    partially_exempt_years: list[int] = Field(
        description="Years where only days inside the exempt period(s) are excluded — per-year totals cannot be split."
    )
    exempt_period_days: dict[int, int] = Field(
        default_factory=dict,
        description=(
            "For each exempt calendar year, how many calendar days the qualifying exempt period(s) cover — "
            "the rest of the year is the most that can count toward the SPT (partial-year cap)."
        ),
    )
    inputs: dict[str, Any] = Field(description="Echo of the inputs this result was computed from.")
    work: str
    citations: list[Citation]


class ClassificationResult(BaseModel):
    """Federal residency classification candidate — the engine flags, the agent + user decide."""

    model_config = ConfigDict(extra="forbid")

    target_year: int
    classification: Classification
    reasons: list[str]
    inputs: dict[str, Any] = Field(description="Echo of the inputs this classification was computed from.")
    work: str = Field(description="Exempt-year narration, day exclusions, and the SPT arithmetic.")
    citations: list[Citation]
    spt: SPTResult
    exempt_years: ExemptYearsResult
    is_lawful_permanent_resident: bool
    section_6013_election: bool = Field(
        default=False,
        description=(
            "True when the §6013(g)/(h) election was applied: the classification is then 'resident' for the "
            "ENTIRE year (Pub 519 ch. 1), whatever the substantial presence test says."
        ),
    )
    nonresident_may_flip: bool = Field(
        default=False,
        description=(
            "True when the (no-election) answer is 'nonresident' only because a preceding lookback year the "
            "visa timeline covers is missing from days_by_year and counted as 0, AND real presence in it could "
            "bring the weighted total to 183 (the 'may be WRONG' reason). Such an answer is never asserted — "
            "e.g. by the IRC 6013(g)(3) gate on the §6013(g)/(h) election (P-018)."
        ),
    )
    classification_without_election: Classification | None = Field(
        default=None,
        description=(
            "Under the §6013(g)/(h) election, the answer the visa timeline and day counts give WITHOUT it "
            "(None when no facts were given, or when no election was applied). The election reaches "
            "chapter 1 and chapter 24 only (IRC 6013(g)(1)), so THIS is the classification calc op "
            "employee_fica takes, and it decides the election's precondition (a U.S. citizen or resident "
            "spouse at year end)."
        ),
    )
    prior_year_resident: bool | None = Field(
        default=None,
        description=(
            "The prior-year residency fact this classification used (JF5b, P-018): True = a U.S. resident "
            "during any part of target_year - 1, False = not, None = unknown. On a profile it comes from "
            "PriorFilings.return_forms[target_year - 1] ('1040' / 'dual_status' True, '1040-NR' False, "
            "otherwise None). True with the substantial presence test met = resident from January 1, no "
            "dual-status arrival split (Treas. Reg. 301.7701(b)-4(e)(1)); True with it NOT met = 'nonresident' "
            "with a first-position CONTRADICTION reason, never called definitive."
        ),
    )


def _fmt_fraction(value: Fraction) -> str:
    """Render a non-negative Fraction as '40', '2/3', or '182 2/3' (never rounded)."""
    if value.denominator == 1:
        return str(value.numerator)
    whole, remainder = divmod(value.numerator, value.denominator)
    if whole == 0:
        return f"{remainder}/{value.denominator}"
    return f"{whole} {remainder}/{value.denominator}"


def _validate_target_year(target_year: Any) -> int:
    if isinstance(target_year, bool) or not isinstance(target_year, int):
        raise ValueError(
            f"target_year must be an int calendar year like 2024, got {type(target_year).__name__} — "
            f"pass the tax year being classified"
        )
    if not 1900 <= target_year <= 2100:
        raise ValueError(
            f"target_year {target_year} is outside 1900..2100 — pass the 4-digit tax year being classified"
        )
    return target_year


def _coerce_year_key(key: Any) -> int:
    if isinstance(key, bool):
        raise ValueError(f"days_by_year key {key!r} is not a calendar year — use int years like 2024")
    if isinstance(key, int):
        year = key
    elif isinstance(key, str) and key.strip().isdigit():
        year = int(key.strip())
    else:
        raise ValueError(
            f"days_by_year key {key!r} is not a calendar year — use int years like 2024 "
            f"(digit strings such as '2024' are also accepted)"
        )
    if not 1900 <= year <= 2100:
        raise ValueError(f"days_by_year year {year} is outside 1900..2100 — use 4-digit calendar years")
    return year


def _normalize_days(days_by_year: Any) -> dict[int, int]:
    if not isinstance(days_by_year, Mapping):
        raise ValueError(
            f"days_by_year must be a mapping of calendar year -> whole days present, e.g. {{2024: 120}} — "
            f"got {type(days_by_year).__name__}"
        )
    out: dict[int, int] = {}
    for key, value in days_by_year.items():
        year = _coerce_year_key(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"days_by_year[{year}] must be a whole number of days (int), got {value!r} — "
                f"any partial day of presence counts as a full day (IRS Pub. 519); "
                f"recount whole days from I-94 travel history"
            )
        max_days = 366 if calendar.isleap(year) else 365
        if not 0 <= value <= max_days:
            raise ValueError(
                f"days_by_year[{year}] = {value} is outside 0..{max_days} — {year} has {max_days} days; "
                f"recount days present from I-94 travel history"
            )
        if year in out:
            raise ValueError(
                f"days_by_year has duplicate entries for year {year} (mixed int and string keys) — keep one"
            )
        out[year] = value
    return out


def _coerce_date(value: Any, where: str, *, required: bool) -> date | None:
    if value is None:
        if required:
            raise ValueError(f"{where} is required — provide a datetime.date or an ISO 'YYYY-MM-DD' string")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{where} = {value!r} is not an ISO date — use 'YYYY-MM-DD' (e.g. '2020-01-15')"
            ) from None
    raise ValueError(
        f"{where} must be a datetime.date or an ISO 'YYYY-MM-DD' string, got {type(value).__name__}"
    )


def is_exempt_category_status(status: str) -> bool:
    """True when ``status`` is an F/J/M/Q exempt-category visa string (IRS Pub. 519).

    Unlike the strict categorizer this never raises: a bare ``"J-1"`` (ambiguous
    between student and teacher/trainee limits) still returns True — either way
    its calendar years need day counts before :func:`classify` can run. A bare
    work-authorization string ('OPT', 'STEM OPT', 'cap-gap', 'CPT') also returns
    True: those are periods of F-1/M-1 student status, so intake must collect
    the same day counts — classify() itself will then raise the prescriptive
    rename error rather than silently counting the days.
    """
    normalized = " ".join(status.lower().split())
    return bool(
        _FM_STATUS_RE.match(normalized)
        or _JQ_STATUS_RE.match(normalized)
        or _WORK_AUTH_RE.search(normalized)
    )


def _categorize_status(status: str, *, index: int) -> ExemptCategory | None:
    """Map a visa status string to its exempt-individual category (None = days count normally)."""
    normalized = " ".join(status.lower().split())
    if _FM_STATUS_RE.match(normalized):
        return "student"
    if _JQ_STATUS_RE.match(normalized):
        if "student" in normalized:
            return "student"
        if any(keyword in normalized for keyword in _TEACHER_TRAINEE_KEYWORDS):
            return "teacher_trainee"
        raise ValueError(
            f"visa_periods[{index}] status {status!r} is ambiguous for the exempt-individual rules: J and Q "
            f"visas can be students (up to 5 exempt calendar years, lifetime) or teachers/trainees (the "
            f"2-of-6-preceding-years rule) — IRS Pub. 519. Resubmit with the program category, e.g. "
            f"'J-1 student' or 'J-1 researcher' / 'J-1 teacher' / 'J-1 trainee' "
            f"(printed in box 4 of Form DS-2019)."
        )
    ag = _AG_STATUS_RE.match(normalized)
    if ag:
        letter, visa_class = ag.group(1), ag.group(2)
        if (letter, visa_class) in (("a", "3"), ("g", "5")):
            return None  # A-3 / G-5 holders are NOT exempt individuals (Pub 519) — days count normally.
        raise ValueError(
            f"visa_periods[{index}] status {status!r}: foreign government-related individuals (A/G visas "
            f"other than A-3/G-5) are exempt individuals with NO calendar-year limit (IRS Pub. 519) and are "
            f"not supported in v1 — exclude those days from days_by_year yourself, record the exclusion in "
            f"RECONCILIATION.md, and resubmit without the A/G period."
        )
    if _WORK_AUTH_RE.search(normalized):
        raise ValueError(
            f"visa_periods[{index}] status {status!r} names a WORK AUTHORIZATION, not a visa status: "
            f"OPT / STEM OPT / cap-gap / CPT are periods OF F-1 (or M-1) STUDENT status, and the "
            f"exempt-individual rules (IRS Pub. 519) turn on the status. Treating this period as a "
            f"non-student would silently count its days toward the Substantial Presence Test and can "
            f"flip the classification to resident on a wording difference. Resubmit with the underlying "
            f"visa class in the status, e.g. 'F-1 OPT' or 'F-1 STEM OPT' (the class is printed on the "
            f"I-20; an M-1 student's practical training is 'M-1 OPT')."
        )
    return None


def _pick(raw: Any, key: str) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(key)
    return getattr(raw, key, None)


def _normalize_periods(visa_periods: Any) -> list[_Period]:
    if isinstance(visa_periods, (str, bytes)) or not isinstance(visa_periods, Iterable):
        raise ValueError(
            f"visa_periods must be a list of periods shaped like "
            f"{{'status': 'F-1', 'start': date(2020, 1, 15), 'end': None}} — got {type(visa_periods).__name__}"
        )
    out: list[_Period] = []
    for index, raw in enumerate(visa_periods):
        status = _pick(raw, "status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError(
                f"visa_periods[{index}] needs a non-empty string 'status' "
                f"(e.g. 'F-1', 'J-1 researcher', 'H-1B') — got {status!r}"
            )
        status = status.strip()
        start = _coerce_date(_pick(raw, "start"), f"visa_periods[{index}].start", required=True)
        end = _coerce_date(_pick(raw, "end"), f"visa_periods[{index}].end", required=False)
        assert start is not None  # required=True guarantees it
        if end is not None and end < start:
            raise ValueError(
                f"visa_periods[{index}] ('{status}') has end {end.isoformat()} before start "
                f"{start.isoformat()} — swap or fix the dates; use end=None while the period is ongoing"
            )
        out.append(_Period(status=status, start=start, end=end, category=_categorize_status(status, index=index)))
    return out


def _ordinals_in_year(period: _Period, year: int) -> range:
    """Day ordinals of ``year`` covered by ``period`` (empty range when no overlap)."""
    year_start = date(year, 1, 1).toordinal()
    year_end = date(year, 12, 31).toordinal()
    start = max(period.start.toordinal(), year_start)
    end = min((period.end or date.max).toordinal(), year_end)
    return range(start, end + 1) if end >= start else range(0)


def _union_ordinals(periods: Iterable[_Period], year: int) -> set[int]:
    covered: set[int] = set()
    for period in periods:
        covered.update(_ordinals_in_year(period, year))
    return covered


def _clipped_span(period: _Period, year: int) -> str:
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    start = max(period.start, year_start)
    end = min(period.end or year_end, year_end)
    return f"{start.isoformat()}..{end.isoformat()}"


def _statuses(periods: Iterable[_Period]) -> str:
    return ", ".join(sorted({p.status for p in periods}))


def _year_list(years: Iterable[int]) -> str:
    return ", ".join(str(y) for y in years)


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def _serialize_periods(periods: Iterable[_Period]) -> list[dict[str, Any]]:
    """JSON-clean echo of the visa timeline for result ``inputs``."""
    return [
        {"status": p.status, "start": p.start.isoformat(), "end": p.end.isoformat() if p.end else None}
        for p in periods
    ]


def _dedup_citations(citations: Iterable[Citation]) -> list[Citation]:
    out: list[Citation] = []
    for citation in citations:
        if citation not in out:
            out.append(citation)
    return out


def substantial_presence_test(days_by_year: Mapping[Any, int], target_year: int) -> SPTResult:
    """Run the substantial presence test for ``target_year`` (IRS Pub. 519).

    ``days_by_year`` maps calendar years to whole days physically present in
    the US (years absent from the mapping count as 0 days — never silently:
    a missing preceding year is called out in ``work``, with a flip warning
    when real counts for it could change a not-met result). The test is met
    when the taxpayer was present at least 31 days during ``target_year``
    AND the weighted 3-year total — all current-year days, plus 1/3 of the
    first preceding year's days, plus 1/6 of the second preceding year's
    days — is at least 183. Fractions are exact and never rounded: Pub 519's
    own example (120 days in each of three years) totals exactly 180 and
    fails the test.

    Days passed here must already exclude exempt-individual days — use
    :func:`classify` to apply the exempt-year rules first.
    """
    year = _validate_target_year(target_year)
    days = _normalize_days(days_by_year)
    current = days.get(year, 0)
    first_preceding = days.get(year - 1, 0)
    second_preceding = days.get(year - 2, 0)
    weighted_first = Fraction(first_preceding, 3)
    weighted_second = Fraction(second_preceding, 6)
    weighted = current + weighted_first + weighted_second
    meets_31 = current >= 31
    meets_183 = weighted >= 183
    meets = meets_31 and meets_183
    work = (
        f"SPT {year}: {current} ({year}) + {first_preceding}/3 = {_fmt_fraction(weighted_first)} ({year - 1}) "
        f"+ {second_preceding}/6 = {_fmt_fraction(weighted_second)} ({year - 2}) "
        f"= {_fmt_fraction(weighted)} weighted days (fractions kept exact, never rounded). "
        f"31-day test: {current} {'>= 31 -> met' if meets_31 else '< 31 -> NOT met'}. "
        f"183-day test: {_fmt_fraction(weighted)} {'>= 183 -> met' if meets_183 else '< 183 -> NOT met'}. "
        f"Substantial presence test {'MET' if meets else 'NOT met'} for {year}."
    )
    # Never treat missing preceding years as 0 SILENTLY: say so in the work, and
    # when the not-met conclusion could flip on those years' real counts, say that.
    missing_preceding = sorted(y for y in (year - 1, year - 2) if y not in days)
    if missing_preceding:
        yl = _year_list(missing_preceding)
        plural = "s" if len(missing_preceding) > 1 else ""
        work += f" NOTE: days for {yl} not provided — treated as 0."
        if meets_31 and not meets_183:
            work += (
                f" If you were present in the US during {yl}, the weighted total is understated and this "
                f"NOT-met result may flip to met (resident) — provide the day count{plural} for {yl} "
                f"(0 is a valid answer for a year spent entirely outside the US)."
            )
        else:
            work += (
                f" Provide the actual count{plural} if you were in the US then "
                f"(0 is a valid answer for a year spent entirely outside the US)."
            )
    return SPTResult(
        target_year=year,
        meets_spt=meets,
        meets_31_day_test=meets_31,
        meets_183_day_test=meets_183,
        days_current_year=current,
        days_first_preceding_year=first_preceding,
        days_second_preceding_year=second_preceding,
        weighted_days=float(weighted),
        weighted_days_exact=_fmt_fraction(weighted),
        inputs={"days_by_year": days, "target_year": year},
        work=work,
        citations=[CITATION_SPT],
    )


def _exempt_individual_years(
    periods: list[_Period],
    target_year: int,
    days_by_year: Mapping[int, int] | None = None,
) -> ExemptYearsResult:
    category_periods = [p for p in periods if p.category is not None]
    has_students = any(p.category == "student" for p in category_periods)
    has_teachers = any(p.category == "teacher_trainee" for p in category_periods)

    records: list[ExemptYearRecord] = []
    fully_exempt: list[int] = []
    partially_exempt: list[int] = []
    exempt_period_days: dict[int, int] = {}
    exempt_year_set: set[int] = set()  # calendar years exempt under ANY category, in chronological order
    work_lines: list[str] = []

    if category_periods:
        first_year = min(p.start.year for p in category_periods)
        for year in range(first_year, target_year + 1):
            students = [
                p for p in category_periods if p.category == "student" and _ordinals_in_year(p, year)
            ]
            teachers = [
                p for p in category_periods if p.category == "teacher_trainee" and _ordinals_in_year(p, year)
            ]
            if not students and not teachers:
                continue

            # Pub 519: an exempt individual is someone temporarily IN the US
            # on an F/J/M/Q visa — with ZERO days of presence the person was
            # never exempt for any part of the year, so it consumes neither
            # the student 5-year limit nor the teacher 2-of-6 lookback.
            if days_by_year is not None:
                statuses_label = _statuses(students + teachers)
                if year not in days_by_year:
                    raise ValueError(
                        f"the visa timeline has an exempt-category period ({statuses_label}) overlapping "
                        f"{year} but days_by_year has no entry for {year} — whether {year} counts toward "
                        f"the exempt-individual limits depends on actual US presence (with zero days "
                        f"present you were never an exempt individual for any part of {year}, IRS Pub. "
                        f"519); add {year} to days_by_year with the days present that year (0 is a valid "
                        f"answer for a year spent entirely outside the US)"
                    )
                if days_by_year[year] == 0:
                    record = ExemptYearRecord(
                        year=year,
                        exempt=False,
                        categories=[],
                        coverage=None,
                        reason=(
                            f"not an exempt-individual year despite the {statuses_label} period(s): "
                            f"days_by_year reports 0 days of US presence in {year}, so you were not an "
                            f"exempt individual for any part of {year} — the year counts toward neither "
                            f"the student lifetime-5 limit nor the teacher/trainee 2-of-6 lookback "
                            f"(IRS Pub. 519: an exempt individual is someone temporarily present in the US)"
                        ),
                    )
                    records.append(record)
                    work_lines.append(f"{record.year}: {record.reason}")
                    continue

            qualifying: list[_Period] = []
            categories: list[ExemptCategory] = []
            reason_bits: list[str] = []

            if students:
                prior = sorted(y for y in exempt_year_set if y < year)
                if len(prior) < 5:
                    qualifying.extend(students)
                    categories.append("student")
                    reason_bits.append(
                        f"student exemption applies ({_statuses(students)}): exempt calendar year "
                        f"#{len(prior) + 1} of the lifetime 5 — any part of a calendar year counts as a "
                        f"whole year (IRS Pub. 519)"
                    )
                else:
                    reason_bits.append(
                        f"student exemption does NOT apply ({_statuses(students)}): already exempt for any "
                        f"part of 5 calendar years ({_year_list(prior)}) — Pub 519 ends the student "
                        f"exemption after 5 calendar years unless the taxpayer establishes to the IRS that "
                        f"they do not intend to reside permanently in the US (not modeled in v1; if claimed, "
                        f"exclude those days from days_by_year yourself and record the position in "
                        f"RECONCILIATION.md)"
                    )
            if teachers:
                lookback = sorted(y for y in exempt_year_set if year - 6 <= y <= year - 1)
                if len(lookback) < 2:
                    qualifying.extend(teachers)
                    categories.append("teacher_trainee")
                    reason_bits.append(
                        f"teacher/trainee exemption applies ({_statuses(teachers)}): exempt for any part of "
                        f"only {len(lookback)} ({_year_list(lookback) or 'none'}) of the 6 preceding "
                        f"calendar years — under the 2-of-6 limit (IRS Pub. 519)"
                    )
                else:
                    reason_bits.append(
                        f"teacher/trainee exemption does NOT apply ({_statuses(teachers)}): exempt as a "
                        f"teacher, trainee, or student for any part of {len(lookback)} of the 6 preceding "
                        f"calendar years ({_year_list(lookback)}) — Pub 519 allows the exemption only when "
                        f"that count is below 2 (a foreign-employer-compensation exception exists but is not "
                        f"modeled in v1; if it applies, exclude those days from days_by_year yourself and "
                        f"record the position in RECONCILIATION.md)"
                    )

            if qualifying:
                exempt_year_set.add(year)
                exempt_days = _union_ordinals(qualifying, year)
                exempt_period_days[year] = len(exempt_days)
                all_period_days = _union_ordinals(periods, year)
                coverage: ExemptCoverage = "full_year" if exempt_days == all_period_days else "partial_year"
                if coverage == "full_year":
                    fully_exempt.append(year)
                    reason_bits.append(
                        f"the exempt period(s) cover the whole declared status timeline in {year}, so ALL "
                        f"days present in {year} are excluded from the SPT"
                    )
                else:
                    partially_exempt.append(year)
                    spans = ", ".join(_clipped_span(p, year) for p in qualifying)
                    reason_bits.append(
                        f"the exempt period(s) cover only part of {year} ({spans}); only days present "
                        f"during the exempt part are excluded from the SPT"
                    )
                record = ExemptYearRecord(
                    year=year, exempt=True, categories=categories, coverage=coverage,
                    reason="; ".join(reason_bits),
                )
            else:
                record = ExemptYearRecord(
                    year=year, exempt=False, categories=[], coverage=None, reason="; ".join(reason_bits)
                )
            records.append(record)
            work_lines.append(f"{record.year}: {record.reason}")

    if not category_periods:
        work = (
            "No F, J, M, or Q exempt-category periods in the visa timeline — no days are excluded from "
            "the SPT as an exempt individual (IRS Pub. 519)."
        )
    else:
        work = "\n".join(
            [f"Exempt-individual analysis through {target_year}:"] + [f"  {line}" for line in work_lines]
        )

    citations: list[Citation] = []
    if has_students:
        citations.append(CITATION_EXEMPT_STUDENT)
    if has_teachers:
        citations.append(CITATION_EXEMPT_TEACHER)

    return ExemptYearsResult(
        target_year=target_year,
        records=records,
        fully_exempt_years=fully_exempt,
        partially_exempt_years=partially_exempt,
        exempt_period_days=exempt_period_days,
        inputs={
            "visa_periods": _serialize_periods(periods),
            "days_by_year": dict(days_by_year) if days_by_year is not None else None,
            "target_year": target_year,
        },
        work=work,
        citations=citations,
    )


def exempt_individual_years(
    visa_periods: Iterable[Any],
    target_year: int,
    days_by_year: Mapping[Any, int] | None = None,
) -> ExemptYearsResult:
    """Determine which calendar years' presence days the SPT must exclude, and why.

    Applies the two Pub 519 exempt-individual limits chronologically from the
    first F/J/M/Q period through ``target_year``:

    * **Students (F/J/M/Q)**: exempt for a LIFETIME total of 5 calendar
      years; any partial calendar year consumes a whole year. Years exempt
      under ANY category (teacher, trainee, or student) count toward the 5.
    * **Teachers/trainees (J/Q non-students)**: exempt unless exempt as a
      teacher, trainee, OR student for any part of 2 of the 6 preceding
      calendar years.

    ``visa_periods`` rows need ``status`` (e.g. ``"F-1"``, ``"J-1
    researcher"``, ``"H-1B"``), ``start``, and ``end`` (``None`` while
    ongoing) — dicts or ``schemas.profile.VisaPeriod``-shaped objects both
    work. Bare ``"J-1"``/``"Q-1"`` is rejected with instructions to add the
    DS-2019 program category, because students and teachers follow
    different limits.

    ``days_by_year`` (optional, recommended): calendar year -> whole days
    physically present in the US. When supplied, a category-period year
    with ZERO days of presence consumes no exempt year (with no US presence
    the person was never an exempt individual for any part of that year —
    Pub 519), and a category-period year MISSING from the mapping is
    rejected with instructions to supply its count (0 is a valid answer).
    Without it, presence is ASSUMED for every category-period year — pass
    the day counts whenever they are known (:func:`classify` always does).
    """
    year = _validate_target_year(target_year)
    periods = _normalize_periods(visa_periods)
    days = _normalize_days(days_by_year) if days_by_year is not None else None
    return _exempt_individual_years(periods, year, days)


def _mid_year_category_changes(periods: list[_Period], target_year: int) -> list[tuple[_Period, _Period]]:
    """Status changes inside target_year that cross an exempt-category boundary."""
    jan1 = date(target_year, 1, 1)
    ordered = sorted(periods, key=lambda p: (p.start, p.end or date.max))
    return [
        (previous, current)
        for previous, current in zip(ordered, ordered[1:])
        if current.start.year == target_year and current.start > jan1 and previous.category != current.category
    ]


def _dual_status_triggers(periods: list[_Period], target_year: int, exempt: ExemptYearsResult) -> list[str]:
    """Plain-language facts suggesting target_year splits into NRA + resident parts."""
    triggers: list[str] = []
    jan1 = date(target_year, 1, 1)
    target_exempt = (
        target_year in exempt.partially_exempt_years or target_year in exempt.fully_exempt_years
    )
    if target_year in exempt.partially_exempt_years:
        triggers.append(
            f"You were an exempt individual for part of {target_year}: days while exempt do not count as US "
            f"presence, so residency would start on the first day you were present in the US after the "
            f"exempt period ended — the part of {target_year} before that date is a nonresident period. "
            f"(If a recount of the non-exempt-part days ends up failing the SPT, Pub 519's First-Year "
            f"Choice may still allow electing residency from your first day of presence when the following "
            f"year's SPT is met — review with your agent; not computed in v1.)"
        )
    if periods:
        earliest = min(p.start for p in periods)
        if earliest.year == target_year and earliest > jan1:
            triggers.append(
                f"Your first US status period starts {earliest.isoformat()}, partway through {target_year}: "
                f"residency under the SPT starts on the first day of presence, so the part of {target_year} "
                f"before arrival is a nonresident period."
            )
        # A mid-year category change can split the year only when some days of
        # target_year were actually exempt. When the year is exempt under NO
        # category (e.g. an F-1 -> H-1B change after the student exemption is
        # used up), the earlier status' days already count toward the SPT, so
        # the change alone cannot split the year — classify() explains this in
        # the resident reasons instead of over-flagging dual status.
        if target_exempt:
            for previous, current in _mid_year_category_changes(periods, target_year):
                triggers.append(
                    f"Your status changed from {previous.status} to {current.status} on "
                    f"{current.start.isoformat()}, partway through {target_year} — a mid-year change between "
                    f"an exempt-category status and a non-exempt status is the classic dual-status pattern "
                    f"(e.g. F-1 -> H-1B). Whether {target_year} actually splits depends on whether any "
                    f"{previous.status} days were still exempt and on your residency starting date — you and "
                    f"your agent decide."
                )
    return triggers


def classify(
    visa_periods: Iterable[Any],
    days_by_year: Mapping[Any, int],
    target_year: int,
    *,
    is_lawful_permanent_resident: bool = False,
    section_6013_election: bool = False,
    prior_year_resident: bool | None = None,
) -> ClassificationResult:
    """Classify federal residency for ``target_year``: nonresident, resident, or dual-status candidate.

    Pipeline (IRS Pub. 519): (1) evaluate exempt-individual years from the
    visa timeline AND the per-year day counts — a category-period year with
    ZERO days of US presence consumes no exempt year (nobody is "exempt for
    any part of" a year they never set foot in the US), and a
    category-period year missing from ``days_by_year`` is rejected with
    instructions (0 is a valid answer); (2) zero out presence days for
    fully exempt years among the target year and its two preceding years;
    (3) run the substantial presence test on the adjusted day counts;
    (4) flag dual-status candidates (partial-year exemption, a mid-year
    exempt/non-exempt status change while some days were still exempt, or
    first arrival partway through the target year) when the SPT is met.
    The green card test overrides everything:
    ``is_lawful_permanent_resident=True`` -> resident regardless of the SPT.

    The engine flags; the agent + user decide. Every result carries its
    inputs, the day-count work, and Pub 519 citations. Partially exempt
    years cannot be split with per-year day totals, so the MAXIMUM possible
    non-exempt-part days are counted: min(reported days, calendar days
    outside the exempt period) — conservative toward residency. When even
    that ceiling fails the SPT, the nonresident answer is definitive and
    the reasons say so (no recount needed); otherwise a reason explains how
    to recount and tighten the answer.

    The visa timeline must cover every year with counted presence days —
    add a period (e.g. ``"B-2 visitor"``) for stays under other statuses,
    or the call is rejected with instructions. Conversely, a preceding
    lookback year (target-1 / target-2) that a declared period covers but
    ``days_by_year`` lacks is counted as 0 WITH an explicit warning — made
    prominent when a nonresident answer could flip to resident on the real
    counts. Supply all three lookback years (0 is a valid answer).

    ``section_6013_election=True`` applies the §6013(g)/(h) election (P-018):
    the couple are "treated for income tax purposes as residents for your
    entire tax year" (Pub 519 ch. 1), so the classification is ``resident``
    with no dual-status flag, whatever the SPT says. The day-count analysis
    still runs and its answer is kept as ``classification_without_election``
    (None when no timeline or day counts were given): the election reaches
    chapter 1 and chapter 24 only (IRC 6013(g)(1)), so that answer is the one
    FICA follows, and it decides the election's precondition — a U.S.
    citizen or resident spouse at year end.

    ``prior_year_resident`` (JF5b, P-018) is the prior-year residency fact —
    True when the individual was a U.S. resident during any part of
    ``target_year - 1`` (a Form 1040 or a dual-status return for that year),
    False when not, None when unknown (today's reading; False reads the same).
    Treas. Reg. 301.7701(b)-4(e)(1): such an individual "who is a United
    States resident for any part of the current year will be considered to be
    taxable as a resident at the beginning of the current year", and the
    partial-year rule of IRC 7701(b)(2)(A)(i) reaches only an alien who "was
    not a resident of the United States at any time during the preceding
    calendar year". So True with the SPT met is ``resident`` from January 1:
    the arrival-type dual-status triggers and the First-Year Choice pointers
    (IRC 7701(b)(4)(A)(ii)) do not apply, and the departure note is kept.
    True with the SPT NOT met stays ``nonresident`` — residency comes from the
    tests "if (and only if)" (IRC 7701(b)(1)(A)) — but the FIRST reason is a
    CONTRADICTION, labeled a judgment about whether the facts are complete,
    naming the three readings (an incomplete timeline, a prior return on the
    wrong form, a genuine departure or return to exempt status) and what to
    record; nothing calls that answer definitive.
    """
    if prior_year_resident is not None and not isinstance(prior_year_resident, bool):
        raise ValueError(
            f"prior_year_resident must be true, false or null (unknown), not {prior_year_resident!r} — true when "
            f"you were a U.S. resident during any part of the preceding year (a Form 1040 or a dual-status return "
            f"for it), false when not (a Form 1040-NR)"
        )
    year = _validate_target_year(target_year)
    days = _normalize_days(days_by_year)
    periods = _normalize_periods(visa_periods)
    # A lawful permanent resident is a resident regardless of the SPT, so the
    # exempt analysis is informational there — do not demand day counts for
    # every category year (assume presence, the legacy reading) and never
    # block a green-card holder on an incomplete I-94 history.
    exempt = _exempt_individual_years(periods, year, None if is_lawful_permanent_resident else days)

    lookback_years = (year, year - 1, year - 2)
    if not is_lawful_permanent_resident:
        # The green card test skips this: a lawful permanent resident is a
        # resident regardless of the SPT and has no visa timeline to declare.
        if not periods and any(days.get(y, 0) > 0 for y in lookback_years):
            reported = next(y for y in lookback_years if days.get(y, 0) > 0)
            raise ValueError(
                f"visa_periods is empty but days_by_year reports {days[reported]} day(s) present in "
                f"{reported} — supply the full status timeline (e.g. status 'F-1', 'H-1B', or 'B-2 "
                f"visitor' with start/end dates) so the exempt-individual rules can be applied; for a "
                f"lawful permanent resident with no visa timeline, pass is_lawful_permanent_resident=True"
            )
        for y in lookback_years:
            if days.get(y, 0) > 0 and not any(_ordinals_in_year(p, y) for p in periods):
                raise ValueError(
                    f"days_by_year reports {days[y]} day(s) present in {y} but the visa timeline has no "
                    f"status period covering {y} — add the missing period to visa_periods (e.g. status "
                    f"'B-2 visitor' or 'H-1B' with its start/end dates) so the exempt-individual rules can "
                    f"be applied, or correct the day count"
                )

    reasons: list[str] = []
    work_lines: list[str] = [exempt.work]
    citations: list[Citation] = [CITATION_SPT, *exempt.citations]

    # Preceding lookback years that a declared status period covers but days_by_year
    # lacks: the SPT can only treat them as 0, which is monotone-safe for a resident
    # conclusion but NOT for a nonresident one — flag them, never stay silent.
    missing_prior: list[int] = (
        []
        if is_lawful_permanent_resident
        else sorted(
            y
            for y in (year - 1, year - 2)
            if y not in days and any(_ordinals_in_year(p, y) for p in periods)
        )
    )

    adjusted: dict[int, int] = {}
    partial_capped: list[int] = []  # partially exempt lookback years, counted at the maximum possible
    for y in lookback_years:
        if y != year and y not in days:
            # Leave the year absent (not a silent 0) so the SPT work flags it explicitly.
            continue
        n = days.get(y, 0)
        if y in exempt.fully_exempt_years and n > 0:
            work_lines.append(
                f"{y}: {n} day(s) present excluded from the SPT — exempt-individual year covering the whole "
                f"declared timeline (Pub 519: an exempt individual is not considered present in the US)."
            )
            n = 0
        elif y in exempt.partially_exempt_years and n > 0:
            # The non-exempt part of the year is a known calendar span, so the
            # countable days can never exceed it — count min(reported, span):
            # the maximum possible, still conservative toward residency.
            ceiling = _days_in_year(y) - exempt.exempt_period_days.get(y, 0)
            capped = min(n, ceiling)
            if capped < n:
                reasons.append(
                    f"{y} was an exempt-individual year for only PART of the year: only days present during "
                    f"the non-exempt part count toward the SPT, but a per-year day total cannot be split. "
                    f"The non-exempt part of {y} spans {ceiling} calendar day(s), so at most {ceiling} of "
                    f"the {n} reported day(s) can count — {ceiling} day(s) were counted (the maximum "
                    f"possible; conservative toward residency)."
                )
                work_lines.append(
                    f"{y}: counted min({n} reported, {ceiling} non-exempt calendar days) = {capped} day(s)."
                )
            else:
                reasons.append(
                    f"{y} was an exempt-individual year for only PART of the year: only days present during "
                    f"the non-exempt part count toward the SPT, but a per-year day total cannot be split, "
                    f"so all {n} day(s) were counted (the maximum possible; conservative toward residency)."
                )
            partial_capped.append(y)
            n = capped
        adjusted[y] = n

    spt = substantial_presence_test(adjusted, year)
    work_lines.append(spt.work)

    if partial_capped and not is_lawful_permanent_resident:
        if spt.meets_spt:
            reasons.append(
                f"To tighten the answer, recount days present during the non-exempt part of "
                f"{_year_list(partial_capped)} from I-94 history and resubmit those counts."
            )
        elif prior_year_resident is True:
            # JF5b: a prior-year resident who fails the SPT is a contradiction to flag, never
            # a definitive answer — and the First-Year Choice is closed (IRC 7701(b)(4)(A)(ii)).
            reasons.append(
                f"The counted day(s) for {_year_list(partial_capped)} already assume presence on every possible "
                f"non-exempt day of the visa timeline AS RECORDED, and even then the SPT is not met — so no recount "
                f"of those days changes it on this timeline. The timeline itself is what the prior-year residency "
                f"calls into question (see the CONTRADICTION reason). If you were in fact a U.S. resident during "
                f"{year - 1}, Pub 519's First-Year Choice is closed (IRC 7701(b)(4)(A)(ii)); under reading (2) — a "
                f"prior-year Form 1040 filed in error — it may still be open: review with your agent."
            )
        else:
            reasons.append(
                f"This nonresident answer is definitive despite the partial-year exemption: the counted "
                f"day(s) for {_year_list(partial_capped)} already assume presence on every possible "
                f"non-exempt day, and even then the SPT is not met — no recount can change it. (An "
                f"election still can: Pub 519's First-Year Choice can make someone arriving late in the "
                f"year a resident from their first day of presence when the following year's SPT is met — "
                f"review with your agent; not computed in v1.)"
            )

    if is_lawful_permanent_resident:
        classification: Classification = "resident"
        reasons.insert(
            0,
            f"Green card test: a lawful permanent resident at any time during {year} is a resident for tax "
            f"purposes regardless of the substantial presence test (IRS Pub. 519). If permanent residence "
            f"was granted partway through {year} and you were not already a resident under the SPT, the "
            f"first year can be dual-status (resident from the residency starting date) — review with your "
            f"agent; not computed in v1.",
        )
        citations.append(CITATION_GREEN_CARD)
        if prior_year_resident is True:
            reasons.append(
                f"You were also a U.S. resident during {year - 1} (the prior-year residency fact), so {year} is a "
                f"resident year from January 1 — no dual-status first year. {PRIOR_YEAR_RESIDENCY_LAW}"
            )
            citations.append(CITATION_RESIDENCY_DATES)
        if days.get(year, 0) < 31:
            # A green-card holder living abroad often assumes absence ends US tax
            # residency — it does not. Flag abandonment and the treaty tie-breaker.
            reasons.append(
                f"You report only {days.get(year, 0)} day(s) of US presence in {year}, but living abroad does "
                f"NOT end green-card residency: lawful-permanent-resident status persists for tax purposes "
                f"until it is formally abandoned (Form I-407 or a final administrative or judicial "
                f"determination), and worldwide income remains reportable on Form 1040 in the meantime "
                f"(IRS Pub. 519, 'Green card test'). If you are treated as a tax resident of a country with a "
                f"US income-tax treaty, you MAY take a treaty tie-breaker position to be taxed as a "
                f"nonresident (disclosed on Form 8833) — that position has green-card/immigration and "
                f"expatriation-tax consequences (Form 8854 can apply to long-term residents). Not computed "
                f"in v1 — review IRS Pub. 519 with your agent before relying on either path."
            )
    elif spt.meets_spt:
        triggers = _dual_status_triggers(periods, year, exempt)
        if triggers and prior_year_resident is not True:
            classification = "dual_status_candidate"
            prior_note = (
                f"Your {year - 1} return is recorded as Form 1040-NR (the prior-year residency fact); if "
                f"{year - 1} was in fact not a resident year, the partial-year rule of IRC 7701(b)(2)(A)(i) applies."
                if prior_year_resident is False
                else f"Note: if you were also a US resident during any part of {year - 1}, you are a resident "
                f"from January 1 of {year} instead."
            )
            reasons.append(
                f"The substantial presence test is met for {year}, but {year} looks like a SPLIT year: you "
                f"were likely a nonresident for the early part of {year} and a resident from your residency "
                f"starting date (generally the first day you were present in the US not as an exempt "
                f"individual — IRS Pub. 519, 'Residency starting and ending dates'). This is a flag, not a "
                f"determination — you and your agent decide. {prior_note}"
            )
            reasons.extend(triggers)
            citations.append(CITATION_RESIDENCY_DATES)
        else:
            classification = "resident"
            reasons.append(
                f"Substantial presence test met for {year}: at least 31 days present in {year} and the "
                f"weighted 3-year total ({spt.weighted_days_exact}) is at least 183 (IRS Pub. 519)."
            )
            if prior_year_resident is True:
                # JF5b: no residency starting date falls inside the year — the arrival
                # triggers and the First-Year Choice pointers do not apply.
                carried = (
                    f"Resident from January 1 of {year}: you were a U.S. resident during {year - 1} (the "
                    f"prior-year residency fact — a resident's or a dual-status return for {year - 1}) and you are "
                    f"a resident for {year} under the substantial presence test, so no residency starting date "
                    f"falls inside {year}. {PRIOR_YEAR_RESIDENCY_LAW}"
                )
                if triggers:
                    carried += (
                        f" The visa timeline alone would flag {year} as a split (dual-status) year — an "
                        f"exempt-individual period, a first arrival or a status change partway through {year} — "
                        f"but that partial-year rule does not reach a prior-year resident, so there is no arrival "
                        f"split in {year}. {FIRST_YEAR_CHOICE_BARRED}"
                    )
                reasons.append(carried)
                citations.append(CITATION_RESIDENCY_DATES)
                # Only where the prior-year fact changed the answer (it removed an arrival split)
                # and the recorded timeline makes year-1 a FULLY exempt year — which neither the
                # SPT nor the First-Year Choice (IRC 7701(b)(4): exempt days are not days of
                # presence) can make a resident year.
                conflict = _prior_year_conflict(periods, days, year, exempt, exempt_only=True) if triggers else ""
                if conflict:
                    # The form is evidence, never the test (IRC 7701(b)(1)(A)): a recorded prior-year
                    # return the recorded timeline cannot support is flagged FIRST, as a judgment.
                    reasons.insert(0, _prior_year_check_reason(year, conflict))
            # A mid-year category change in a NON-exempt target year does not
            # split the year (the earlier status' days already counted), so it
            # was not flagged as a dual-status trigger — explain why instead.
            # (With triggers suppressed for a prior-year resident the year WAS
            # exempt, so that explanation would be wrong — the carryover covers it.)
            for previous, current in [] if triggers else _mid_year_category_changes(periods, year):
                reasons.append(
                    f"Your status changed from {previous.status} to {current.status} on "
                    f"{current.start.isoformat()}, but your {previous.status} days in {year} already "
                    f"counted toward the SPT ({year} was not an exempt-individual year — the exemption was "
                    f"used up or never applied), so the status change does not split the year: you are a "
                    f"full-year resident if you were present from January 1 of {year} (IRS Pub. 519, the "
                    f"residency starting date is the first day of presence)."
                )
                citations.append(CITATION_RESIDENCY_DATES)
        # IRC 7701(b)(5)/Pub 519: exempt-individual days are not 'days of
        # presence', so the Form 8840 fewer-than-183-days screen uses the
        # SPT-countable (adjusted) current-year count, not raw presence.
        if adjusted[year] < 183:
            reasons.append(
                f"Closer-connection exception exists: you were present {adjusted[year]} countable day(s) in "
                f"{year} (fewer than 183 — for this test, exempt-individual days do not count as days of "
                f"presence). Someone who meets the SPT can still be treated as a nonresident "
                f"by keeping a tax home in a foreign country for the entire year and a closer connection to "
                f"it than to the US (claimed on Form 8840) — but NOT if they applied for, or took steps "
                f"toward, lawful permanent resident status (a green card) during {year}. Not computed in v1 "
                f"— review IRS Pub. 519 'Closer connection exception' and decide with your agent."
            )
            citations.append(CITATION_CLOSER_CONNECTION)
        latest_period_end = max(((p.end or date.max) for p in periods), default=date.max)
        if latest_period_end < date(year, 12, 31):
            reasons.append(
                f"Your last declared status period ends {latest_period_end.isoformat()}, before the end of "
                f"{year}. By default the residency ending date is still December 31 of {year}; it can be "
                f"your last day of presence only if, for the rest of the year, you were not present in the "
                f"US, had a closer connection to a foreign country, were not a US resident during any part "
                f"of {year + 1}, and you attach the required statement (IRS Pub. 519, 'Residency starting "
                f"and ending dates'). Not computed in v1 — decide with your agent."
            )
            citations.append(CITATION_RESIDENCY_DATES)
    else:
        classification = "nonresident"
        reasons.append(
            f"Substantial presence test NOT met for {year} — see the day-count work; classification: "
            f"nonresident alien for {year}."
        )
        if spt.meets_183_day_test:
            reasons.append(
                f"Your weighted total ({spt.weighted_days_exact}) is at least 183, but you were present only "
                f"{adjusted[year]} day(s) in {year}, below the 31-day minimum, so the SPT is not met. "
                f"Double-check the {year} day count from I-94 history. For reference, even when the SPT is "
                f"met, the closer-connection exception (Form 8840) can preserve nonresident status — not "
                f"computed in v1."
            )
            citations.append(CITATION_CLOSER_CONNECTION)
        elif spt.weighted_days >= _NEAR_183_WEIGHTED:
            reasons.append(
                f"Your weighted total ({spt.weighted_days_exact}) is close to the 183-day threshold — "
                f"recount days present from I-94 history before relying on nonresident status. If a recount "
                f"crosses 183, the closer-connection exception (Form 8840) may still preserve nonresident "
                f"status — not computed in v1; review IRS Pub. 519 'Closer connection exception'."
            )
            citations.append(CITATION_CLOSER_CONNECTION)

    may_flip = False
    if missing_prior:
        yl = _year_list(missing_prior)
        those = "that year" if len(missing_prior) == 1 else "those years"
        base = (
            f"days_by_year has no entry for {yl} even though your declared status timeline covers {those} — "
            f"{those} counted as 0 days in the SPT"
        )
        provide = f"provide day counts for {yl} (0 is a valid answer for a year spent entirely outside the US)"
        if classification == "nonresident":
            # Could real presence in the missing years flip the result? Only when the
            # 31-day current-year prong holds AND maximal presence could reach 183.
            potential = (
                Fraction(spt.days_current_year)
                + Fraction(spt.days_first_preceding_year, 3)
                + Fraction(spt.days_second_preceding_year, 6)
                + sum(Fraction(_days_in_year(y), 3 if y == year - 1 else 6) for y in missing_prior)
            )
            if spt.meets_31_day_test and potential >= 183:
                # A nonresident answer that rests on missing-years-as-zero is NOT
                # monotone-safe: make the caveat the first thing the caller reads.
                may_flip = True
                reasons.insert(
                    0,
                    f"{MAY_FLIP_PREFIX}: {base}. You were present "
                    f"{adjusted[year]} day(s) in {year} (at least 31), so if you were in the US during {yl} "
                    f"the weighted 3-year total could reach 183 and the classification would FLIP to "
                    f"resident (worldwide income on Form 1040, not Form 1040-NR) — {provide} and "
                    f"reclassify before relying on this result (IRS Pub. 519, substantial presence test).",
                )
            elif not spt.meets_31_day_test:
                reasons.append(
                    f"Note: {base}. This nonresident result does not turn on {those}: with "
                    f"{adjusted[year]} day(s) present in {year} the 31-day minimum is not met, and "
                    f"prior-year days cannot change that — still, {provide} for a complete record "
                    f"(IRS Pub. 519)."
                )
            else:
                stands = (
                    f"so {those} cannot change this answer on {'its' if len(missing_prior) == 1 else 'their'} own "
                    f"(see the CONTRADICTION reason)"
                    if prior_year_resident is True else "so this nonresident result stands"
                )
                reasons.append(
                    f"Note: {base}. Even the maximum possible presence in {yl} could not bring the "
                    f"weighted total to 183, {stands} — still, {provide} for a "
                    f"complete record (IRS Pub. 519)."
                )
        else:
            reasons.append(
                f"Note: {base}. A {classification.replace('_', '-')} conclusion is safe on that score "
                f"(more presence days only push toward residency), but {provide} for a complete record "
                f"(IRS Pub. 519)."
            )

    if prior_year_resident is True and classification == "nonresident" and not is_lawful_permanent_resident:
        # JF5b: made the FIRST reason (ahead of any "may be WRONG" caveat) — a labeled
        # judgment about whether the facts are complete, never a definitive answer.
        reasons.insert(0, _prior_year_contradiction_reason(periods, days, year, exempt))
        citations.append(CITATION_RESIDENCY_DATES)

    without_election: Classification | None = None
    if section_6013_election:
        # P-018: the election overrides the SPT answer for income tax, and only for
        # income tax — the day-count answer is kept, never discarded. Which choice it
        # is follows from that answer: a full-year nonresident is the 6013(g) spouse;
        # otherwise the spouse's facts (not given here) decide between (g) and (h).
        no_facts = not periods and not days and not is_lawful_permanent_resident
        without_election = None if no_facts else classification
        effect, precondition, _statement = section_6013_texts(
            section_6013_kind(without_election, None, recorded=True)
        )
        lead = (
            f"§6013(g)/(h) election applied: RESIDENT for all of {year}, whatever the substantial presence "
            f"test says, and no dual-status split. {effect} {precondition} {SECTION_6013_FICA}"
        )
        if no_facts:
            reasons = [
                lead,
                "No visa timeline or day counts were given, so the answer WITHOUT the election is not computed "
                "(classification_without_election is None) — record them to check the precondition and FICA.",
            ]
        else:
            reasons = [
                lead,
                f"Without the election the visa timeline and day counts give "
                f"'{without_election}' for {year} (classification_without_election); the reasons below "
                f"explain that answer, which still decides the precondition above and FICA.",
                *reasons,
            ]
        classification = "resident"
        citations.append(CITATION_SECTION_6013)

    return ClassificationResult(
        target_year=year,
        classification=classification,
        reasons=reasons,
        inputs={
            "visa_periods": _serialize_periods(periods),
            "days_by_year": days,
            "target_year": year,
            "is_lawful_permanent_resident": is_lawful_permanent_resident,
            "section_6013_election": section_6013_election,
            "prior_year_resident": prior_year_resident,
        },
        work="\n".join(work_lines),
        citations=_dedup_citations(citations),
        spt=spt,
        exempt_years=exempt,
        is_lawful_permanent_resident=is_lawful_permanent_resident,
        section_6013_election=section_6013_election,
        classification_without_election=without_election,
        nonresident_may_flip=may_flip,
        prior_year_resident=prior_year_resident,
    )


CONTRADICTION_PREFIX = "CONTRADICTION"


def _prior_year_conflict(periods: list[_Period], days: dict[int, int], year: int, exempt, *, exempt_only: bool = False) -> str:
    """The clause naming why the recorded facts cannot support a resident's return for year-1, or ''.

    ``exempt_only``: only the fully-exempt-year conflict. The nonresident-year conflict is
    judged only when year-1's days are recorded, and it is worded as the substantial
    presence test's answer — the First-Year Choice (IRC 7701(b)(4)) can still make such a
    year a resident year for its last part."""
    prior = year - 1
    if prior in exempt.fully_exempt_years:
        return (
            f" — and the recorded visa timeline makes {prior} itself a FULLY exempt-individual year (its days do "
            f"not count as U.S. presence), so on these facts {prior} could not have been a substantial-presence "
            f"year, which conflicts with a resident's return for {prior}"
        )
    if exempt_only or prior not in days:
        return ""
    try:
        own = classify(periods, days, prior) if periods else None
    except (ValueError, AssertionError):
        own = None
    if own is not None and own.classification == "nonresident" and not own.nonresident_may_flip:
        return (
            f" — and the same visa timeline and day counts classify {prior} itself as a NONRESIDENT year on the "
            f"substantial presence test, which conflicts with a resident's return for {prior} unless the First-Year "
            f"Choice (IRC 7701(b)(4)) was made for it"
        )
    return ""


PRIOR_YEAR_CHECK_PREFIX = "CHECK THE PRIOR-YEAR RETURN"


def _prior_year_check_reason(year: int, conflict: str) -> str:
    """The first-position judgment when the SPT is met but the recorded facts cannot support the
    recorded prior-year resident's return (JF5b): the classification stands, the flag names why."""
    prior = year - 1
    return (
        f"{PRIOR_YEAR_CHECK_PREFIX} — a judgment about the recorded facts, not a determination: your {prior} return "
        f"is recorded as a resident's (or dual-status) return, so {year} is treated as a resident year from January "
        f"1{conflict}. The form is evidence, never the test — {_RESIDENT_IF_AND_ONLY_IF}. Two readings: (a) the "
        f"visa timeline starts too late or is incomplete (e.g. exempt years really past the student limit), and "
        f"resident from January 1 stands; (b) the {prior} return was filed on the wrong form (a Form 1040 filed by "
        f"an exempt F/J student does not make anyone a resident), so {prior} was not a resident year, and {year}'s "
        f"residency starts on the residency starting date — the first day of presence that is not an "
        f"exempt-individual day (IRC 7701(b)(2)(A)(i), (iii)) — which splits {year} (a dual-status year) unless that "
        f"is January 1. Record the full visa timeline from your FIRST U.S. entry and the days for every year it "
        f"covers, then rerun."
    )


def _prior_year_contradiction_reason(periods: list[_Period], days: dict[int, int], year: int, exempt) -> str:
    """The first-position reason for a prior-year resident whose recorded facts fail the SPT (JF5b)."""
    prior = year - 1
    conflict = _prior_year_conflict(periods, days, year, exempt)
    return (
        f"{CONTRADICTION_PREFIX} — a judgment about whether the recorded facts are complete, not a determination: "
        f"you were a U.S. resident during {prior} (the prior-year residency fact: a resident's or a dual-status "
        f"return for {prior}), but on the visa timeline and day counts recorded here the substantial presence "
        f"test is NOT met for {year}{conflict}. On complete facts that answer would stand — "
        f"{_RESIDENT_IF_AND_ONLY_IF}, and prior-year residency carries to January 1 only for someone who \"is a "
        f"United States resident for any part of the current year\" (Treas. Reg. 301.7701(b)-4(e)(1)) — so the "
        f"classification stays 'nonresident', but it is NOT definitive. Three readings: (1) the visa timeline or "
        f"day counts are incomplete — e.g. a timeline that starts too late marks years as exempt-individual years "
        f"that were really past the student limit (IRC 7701(b)(5)(E)(ii): no student exemption \"For any calendar "
        f"year after the 5th calendar year for which an individual was an exempt individual\", unless the "
        f"individual establishes what it requires), and those days would then count; (2) the {prior} return was "
        f"filed on the wrong form (a Form 1040 filed by an exempt F/J student does not make anyone a resident); "
        f"(3) you genuinely left the United States or became an exempt individual again, so {year} is a full "
        f"nonresident year and {prior}'s residency ended on its residency termination date. Record what settles "
        f"it: the full visa timeline from your FIRST U.S. entry (every F/J/M/Q period), the days in the U.S. for "
        f"every year it covers, and the return you actually filed for {prior} (prior_filings.return_forms) — then "
        f"rerun."
    )


MAY_FLIP_PREFIX = "IMPORTANT — this nonresident result may be WRONG"


def may_flip_reason(result: ClassificationResult) -> str | None:
    """classify's "may be WRONG" reason when ``nonresident_may_flip`` is set, else None (JF5b.6)."""
    if not result.nonresident_may_flip:
        return None
    return next((r for r in result.reasons if r.startswith(MAY_FLIP_PREFIX)), None)


def missing_lookback_years(visa_periods: Iterable[Any], days_by_year: Mapping[Any, int], target_year: int) -> list[int]:
    """The preceding lookback years (target-1 / target-2) a declared period covers but
    ``days_by_year`` lacks — the years classify counts as 0 with a warning."""
    periods = _normalize_periods(visa_periods)
    days = _normalize_days(days_by_year)
    return sorted(
        y for y in (target_year - 1, target_year - 2)
        if y not in days and any(_ordinals_in_year(p, y) for p in periods)
    )


def prior_year_contradiction(result: ClassificationResult) -> str | None:
    """The CONTRADICTION reason of a prior-year resident who fails the SPT, or None (JF5b)."""
    return next((r for r in result.reasons if r.startswith(CONTRADICTION_PREFIX)), None)


def prior_year_check(result: ClassificationResult) -> str | None:
    """The CHECK THE PRIOR-YEAR RETURN judgment (SPT met, the recorded prior-year return unsupported), or None."""
    return next((r for r in result.reasons if r.startswith(PRIOR_YEAR_CHECK_PREFIX)), None)


def nonresident_rests_on_missing_lookback(visa_periods: Iterable[Any], days_by_year: Mapping[Any, int], target_year: int) -> bool:
    """True when a preceding lookback year the visa timeline covers is missing from ``days_by_year``.

    :func:`classify` counts such a year (``target_year - 1`` or ``target_year - 2``)
    as 0 days, with a warning. Intake's classification treats any 'nonresident'
    answer resting on one as unknown and asks for the days (the conservative
    interview rule). The IRC 6013(g)(3) gate uses the narrower
    :func:`certain_nonresident` instead, because there "unknown" applies the
    election.
    """
    periods = _normalize_periods(visa_periods)
    days = _normalize_days(days_by_year)
    covered: set[int] = set()
    for p in periods:
        end_year = min(p.end.year if p.end else target_year, target_year)
        covered.update(range(p.start.year, end_year + 1))
    return any(y not in days and y in covered for y in (target_year - 1, target_year - 2))


def certain_nonresident(
    visa_periods: Iterable[Any], days_by_year: Mapping[Any, int], target_year: int,
    *, prior_year_resident: bool | None = None,
) -> bool:
    """True when the facts classify 'nonresident' and no missing lookback year could flip it.

    The IRC 6013(g)(3) gate on the §6013(g)/(h) election (P-018): the election
    "shall not apply for any taxable year if neither spouse is a citizen or resident
    of the United States at any time during such year", judged on the recorded facts.
    A nonresident answer that real presence in a missing lookback year could turn
    resident (``nonresident_may_flip``) is not certain; one that cannot turn on the
    missing years is. The estimator and intake both call this, so they never
    disagree on whether the election is available. A prior-year resident
    (``prior_year_resident`` True — PriorFilings.return_forms) is never a certain
    nonresident: failing the SPT then contradicts the recorded prior year (JF5b).
    """
    if prior_year_resident is True:
        return False
    try:
        # A missing CURRENT-year count is counted as 0 by classify with no flip test, so it is
        # never certain (the 31-day prong would "fail" on a count nobody recorded).
        if target_year not in _normalize_days(days_by_year):
            return False
        result = classify(visa_periods, days_by_year, target_year)
    except (ValueError, AssertionError):
        return False
    return result.classification == "nonresident" and not result.nonresident_may_flip
