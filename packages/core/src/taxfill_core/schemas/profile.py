"""Guided-intake profile schema — dev plan section 4.

The profile is the resumable record of everything the interview learns about
one taxpayer. Two design rules from the dev plan:

1. **Incremental by design.** Filing realistically spans days while users
   hunt for documents, so every section is optional; ``intake_checklist``
   (M3) looks at a partial profile and returns the *next* questions and
   required documents. An empty ``Profile()`` is valid.

2. **Every leaf answer carries provenance** — ``user_stated``,
   ``document(file, page)``, or ``computed``. Hard rule: never invent a
   value; unknown stays absent and is reported as a gap.

Disambiguation by design (section 4): the identity mailing address is the
address where the user receives mail TODAY — never a historical address.
Historical addresses live under the state footprint (they drive state
scoping), and are never auto-copied into the return's address box.
Treaty-relevant facts (visa status) are date-range *periods*, never a single
"what's your status" answer: an F-1 to H-1B transition year can still claim
a student-article treaty benefit on income earned during the student period
(see pitfall P-004 in knowledge/pitfalls.yaml).
"""

from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taxfill_core.calc import FilingStatusInput, is_valid_routing_number

T = TypeVar("T")

ProvenanceKind = Literal["user_stated", "document", "computed"]
DocumentStatus = Literal["have", "missing", "not_applicable"]
# Whose income a document reports. On a joint return each W-2/1099 belongs to
# the taxpayer or the spouse who earned it; the default is the taxpayer.
DocumentOwner = Literal["taxpayer", "spouse"]


class Provenance(BaseModel):
    """Where an answer came from: the user, a document (file + page), or a computation."""

    model_config = ConfigDict(extra="forbid")

    kind: ProvenanceKind
    file: str | None = Field(default=None, description="Workspace-relative document path (kind='document' only).")
    page: int | None = Field(default=None, ge=1, description="1-based page within the document (kind='document' only).")

    @model_validator(mode="after")
    def _check_kind_payload(self) -> "Provenance":
        if self.kind == "document":
            if not self.file:
                raise ValueError(
                    "provenance kind 'document' requires 'file' (the source document path); "
                    "add 'page' too when known"
                )
        elif self.file is not None or self.page is not None:
            raise ValueError(
                f"provenance kind '{self.kind}' must not carry 'file' or 'page' — "
                f"those belong to 'document' provenance only"
            )
        return self

    @classmethod
    def user_stated(cls) -> "Provenance":
        return cls(kind="user_stated")

    @classmethod
    def document(cls, file: str, page: int | None = None) -> "Provenance":
        return cls(kind="document", file=file, page=page)

    @classmethod
    def computed(cls) -> "Provenance":
        return cls(kind="computed")


class Answer(BaseModel, Generic[T]):
    """A leaf answer: the value plus where it came from."""

    model_config = ConfigDict(extra="forbid")

    value: T
    provenance: Provenance


class DateRange(BaseModel):
    """A closed or ongoing date range; ``end`` is None while the period is still ongoing."""

    model_config = ConfigDict(extra="forbid")

    start: date
    end: date | None = None

    @model_validator(mode="after")
    def _check_order(self) -> "DateRange":
        if self.end is not None and self.end < self.start:
            raise ValueError(f"date range end {self.end} is before start {self.start} — swap or fix the dates")
        return self


VisaSubStatus = Literal["student", "opt", "stem_opt", "cap_gap", "employment", "dependent", "other"]


class VisaPeriod(DateRange):
    """One period of the visa status timeline (eligibility is per-period, not per-year).

    ``sub_status`` is the H1 vocabulary the bare status string cannot carry: OPT,
    STEM OPT and cap-gap are all F-1 — the prefix rules for exempt-individual
    residency are unchanged — but they are the periods where the filer is WORKING
    full-time, whose end date sets the H-1B boundary, and whose FICA answer a
    planning session turns on. An H-1B period's start is the I-797 approval
    start date, never the offer or onboarding date.
    """

    status: str = Field(description="Immigration status during the period, e.g. 'F-1', 'H-1B', 'J-1'.")
    sub_status: VisaSubStatus | None = Field(
        default=None,
        description=(
            "What the person was DOING inside the status: student / opt / stem_opt / cap_gap "
            "(all F-1; work authorization changes, residency prefix rules do not) / employment "
            "(H-1B etc.) / dependent / other. None = not asked (older profiles load unchanged)."
        ),
    )
    provenance: Provenance

    def fica_exempt_hint(self) -> tuple[bool | None, str]:
        """(hint, why): whether this period's wages are typically FICA-exempt.

        DERIVED, never stored, so it cannot contradict the timeline. The rule is
        STATUS-based (IRC 3121(b)(19); Pub 519): F/J student periods — including
        OPT / STEM OPT / cap-gap, which are still F-1 — are exempt WHILE the
        person is a nonresident exempt individual; employment statuses are not,
        and FICA starts at the status boundary (the I-797 start date). The
        residency half of the test is classify()'s job — this hint plus that
        result feed calc op employee_fica's per-segment fica_exempt input.
        """
        f_or_j = self.status.strip().upper().startswith(("F", "J"))
        if self.sub_status in ("student", "opt", "stem_opt", "cap_gap") or (
            self.sub_status is None and f_or_j
        ):
            if f_or_j:
                return True, (
                    "F/J student-category period (incl. OPT/STEM OPT/cap-gap — still F-1): wages are "
                    "FICA-exempt while a nonresident exempt individual (IRC 3121(b)(19); Pub 519). The "
                    "exemption is STATUS-based, not marital — a §6013(g) election does not end it. "
                    "Confirm the residency half with classify()."
                )
        if self.sub_status == "employment" or self.status.strip().upper().startswith("H"):
            return False, (
                "Employment status: FICA applies from the status boundary — for H-1B that is the I-797 "
                "approval start date, never the offer or onboarding date."
            )
        return None, (
            "No FICA rule derivable from this status/sub_status alone — decide per Pub 15/Pub 519 and "
            "pass the judgment to calc op employee_fica explicitly."
        )


class Immigration(BaseModel):
    """Immigration facts (only when applicable)."""

    model_config = ConfigDict(extra="forbid")

    visa_timeline: list[VisaPeriod] = Field(
        default_factory=list,
        description="Exact date-range periods; mid-year status changes matter for treaty eligibility (P-004).",
    )
    first_us_entry: Answer[date] | None = None


class ResidencyFacts(BaseModel):
    """Inputs to the Substantial Presence Test and exempt-individual analysis (M1)."""

    model_config = ConfigDict(extra="forbid")

    days_in_us: dict[int, Answer[int]] = Field(
        default_factory=dict,
        description="Days physically present in the US, keyed by calendar year; computed from I-94 history when provided.",
    )
    home_country_address: Answer[str] | None = None
    section_6013_election: Answer[bool] | None = Field(
        default=None,
        description=(
            "The §6013(g)/(h) election to treat a nonresident-alien spouse as a U.S. resident (P-018). "
            "True = the couple makes it for this tax year, or made it earlier and it remains in effect; "
            "False = declined; None = not asked. Pub 519 ch. 1, Nonresident Spouse Treated as a Resident: "
            "'If you make this choice, you and your spouse are treated for income tax purposes as "
            "residents for your entire tax year' — so the residency answer becomes RESIDENT for BOTH "
            "spouses whatever the visa timeline and day counts say (IRC 6013(g)(1): 'for purposes of "
            "chapter 1 for all of such taxable year, and ... for purposes of chapter 24 (relating to wage "
            "withholding)' — not FICA, so an F/J exempt individual's social security and Medicare "
            "exemption is unchanged). The choice is JOINT and needs a spouse at year end ('If, at the end "
            "of your tax year, you are married and one spouse is a U.S. citizen or a resident alien and "
            "the other spouse is a nonresident alien, you can choose ...'), so it is recorded ONCE, here "
            "on the taxpayer's residency facts, never on Spouse.residency_facts, and it is applied only "
            "when the household is married for the year — household.marital_status 'married', or "
            "'widowed' with spouse_death_year in the tax year (Pub 519, Ending the Choice: 'The death of "
            "either spouse ends the choice, beginning with the first tax year following the year the "
            "spouse died') — or, marital status unanswered, a confirmed married_filing_jointly or "
            "married_filing_separately status (Pub 501: 'You can choose married filing separately as your "
            "filing status if you are married'); never onto a single or head-of-household figure; and never "
            "when the recorded facts show neither spouse a U.S. citizen or resident at any time in the year "
            "(IRC 6013(g)(3): the election 'shall not apply for any taxable year if neither spouse is a "
            "citizen or resident of the United States at any time during such year'; Pub 519, Suspending "
            "the Choice). "
            "Two choices share this fact: IRC 6013(g) (a nonresident spouse at year end) — 'You must file "
            "a joint income tax return for the year you make the choice, but you and your spouse can file "
            "joint or separate returns in later years' — and IRC 6013(h) (the dual-status year: both "
            "spouses U.S. citizens or residents at year end, one a nonresident at the start) — 'You and "
            "your spouse must file a joint return for the year of the choice' and 'Neither you nor your "
            "spouse can make this choice for any later tax year' (Pub 519 ch. 1, Choosing Resident Alien "
            "Status), so True in a later year means a continuing 6013(g) election."
        ),
    )


class Identity(BaseModel):
    """Who is filing."""

    model_config = ConfigDict(extra="forbid")

    name: Answer[str] | None = None
    tax_id: Answer[str] | None = Field(default=None, description="SSN or ITIN.")
    dob: Answer[date] | None = None
    us_person: Answer[bool] | None = Field(
        default=None,
        description=(
            "True if a U.S. citizen or lawful permanent resident (green-card holder) — always a "
            "U.S. tax resident, so the immigration/visa timeline and Substantial Presence Test do "
            "not apply and all filing statuses are available. False routes to the immigration "
            "section and residency determination. None means not yet asked (intake gates on it)."
        ),
    )
    citizenship_country: Answer[str] | None = Field(
        default=None,
        description=(
            "Country of citizenship (e.g. 'China', 'India') — drives the per-country tax-treaty "
            "benefit lookup (knowledge/treaties/) and the estimate's treaty cross-check. Treaty "
            "eligibility technically follows RESIDENCE in the treaty country immediately before "
            "US entry, which usually matches citizenship for students/scholars — confirm with "
            "the user when the two differ. None means not yet asked."
        ),
    )
    mailing_address: Answer[str] | None = Field(
        default=None,
        description=(
            "The address where the user receives mail TODAY — not where they lived "
            "during the tax year; the IRS sends bills and notices here (pitfall P-002). "
            "Historical addresses belong in state_footprint."
        ),
    )


class Dependent(BaseModel):
    """One dependent (household section)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    relationship: str | None = None
    dob: date | None = None
    has_ssn: bool | None = Field(
        default=None,
        description=(
            "True when the dependent has a work-eligible SSN (required for the Child Tax "
            "Credit and to count as an EITC qualifying child); False for ITIN/ATIN "
            "dependents (still eligible for the $500 ODC); None = not asked."
        ),
    )
    is_us_citizen_national_or_resident: bool | None = Field(
        default=None,
        description=(
            "The §152(b)(3) gate: a dependent must be a U.S. citizen, national or resident (or a "
            "resident of Canada/Mexico) — an NRA partner or relative abroad CANNOT be claimed no "
            "matter how much support was paid, which is exactly the mistake a no-experience filer "
            "makes after reading 'qualifying relative'. False = fails the gate (excluded from every "
            "credit with a disclosure); None = not asked (counted as before)."
        ),
    )
    provenance: Provenance


class Spouse(BaseModel):
    """The spouse as a full second taxpayer (married-filing-jointly or -separately).

    A joint return is two people on one form: the spouse has their own identity
    (name, SSN/ITIN, DOB), their own income documents (tagged ``owner='spouse'``
    in ``income_documents``), and — when an NRA spouse is involved — their own
    immigration and residency facts. Treating an NRA spouse as a U.S. resident to
    file jointly is the §6013(g)/(h) election (worldwide income becomes taxable).
    The election is a joint choice that makes BOTH spouses residents, so it is
    recorded once, on the taxpayer's ``Profile.residency_facts.section_6013_election``
    (P-018) — a copy on ``Spouse.residency_facts`` is refused, never a second
    source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    name: Answer[str] | None = None
    tax_id: Answer[str] | None = Field(
        default=None,
        description=(
            "Spouse's SSN or ITIN. The answer 'NRA' records a spouse who has no SSN or ITIN and "
            "needs none (a married-filing-separately return); on the FORM that literal goes in "
            "the MFS entry space below the filing status checkboxes, never in the spouse-SSN box "
            "(P-026: the filler refuses it on every identifying-number line)."
        ),
    )
    dob: Answer[date] | None = None
    us_person: Answer[bool] | None = Field(
        default=None,
        description=(
            "True if the spouse is a U.S. citizen or lawful permanent resident — mirrors "
            "Identity.us_person. Gates whether the spouse needs the Substantial Presence Test / "
            "visa path at all and whether a §6013(g)/(h) election (treating an NRA spouse as a "
            "U.S. resident to file jointly) even arises. None means not yet asked."
        ),
    )
    immigration: Immigration | None = Field(
        default=None, description="Spouse's visa timeline — drives the NRA-spouse §6013(g)/(h) decision."
    )
    residency_facts: ResidencyFacts | None = None

    @model_validator(mode="after")
    def _election_lives_on_the_taxpayer(self) -> "Spouse":
        if self.residency_facts is not None and self.residency_facts.section_6013_election is not None:
            raise ValueError(
                "household.spouse.residency_facts.section_6013_election is not where the §6013(g)/(h) "
                "election is recorded — the choice is joint and makes BOTH spouses residents for the whole "
                "year (Pub 519 ch. 1), so record it once as residency_facts.section_6013_election on the "
                "taxpayer's profile and leave the spouse's copy unset"
            )
        return self


class OtherTaxpayer(BaseModel):
    """Another taxpayer in the SAME household who files their own return (H2, N-2).

    The modal international-student household is an unmarried couple: two
    returns, one rent, one budget. Modeling the second person is what lets the
    product SAY three things agents otherwise carry in their heads: you file
    separately; an NRA partner cannot be claimed as a dependent (§152(b)(3));
    and marrying mid-plan opens the §6013(g)/(h) election — which
    compare_scenarios can price as a what-if TODAY.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    relationship: Literal["unmarried_partner", "roommate", "relative", "other"]
    us_person: bool | None = Field(
        default=None,
        description="Their own citizen/resident answer (None = not asked); drives the dependent guard note.",
    )
    note: str = Field(default="", description="Free context, e.g. 'NRA (J-1 scholar), files 1040-NR'.")
    provenance: Provenance


class Household(BaseModel):
    """Filing-status facts, the chosen filing status, the spouse, and dependents."""

    model_config = ConfigDict(extra="forbid")

    marital_status: Answer[Literal["married", "unmarried", "widowed"]] | None = Field(
        default=None,
        description=(
            "Marital status on Dec 31 of the tax year — a closed, machine-checkable FACT, not "
            "the filing status. 'married' opens MFJ/MFS; 'unmarried' opens single/HOH; "
            "'widowed' opens the qualifying-surviving-spouse path (with a dependent child and a "
            "recent spouse death)."
        ),
    )
    hoh_qualifying_person: Answer[bool] | None = Field(
        default=None,
        description=(
            "Head-of-household FACT: True when the taxpayer paid more than half the cost of "
            "keeping up a home for a qualifying person (e.g. a child or dependent relative) who "
            "lived with them more than half the year. Gates the head_of_household status; None "
            "means not yet asked."
        ),
    )
    spouse_death_year: Answer[int] | None = Field(
        default=None,
        description=(
            "Qualifying-surviving-spouse FACT: the calendar year the spouse died. QSS is "
            "available for the two tax years AFTER the year of death (the year of death itself "
            "is normally a joint-return year). None means not asked / not applicable."
        ),
    )
    maintained_home_for_dependent_child: Answer[bool] | None = Field(
        default=None,
        description=(
            "Qualifying-surviving-spouse FACT: True when the taxpayer paid more than half the "
            "cost of keeping up the main home of a dependent child for the year. Required (with "
            "spouse_death_year) for the qualifying_surviving_spouse status; None means not asked."
        ),
    )
    spouses_lived_apart_all_year: Answer[bool] | None = Field(
        default=None,
        description=(
            "Separate-return FACT (IRC 86(c)(1)(C)(ii), JF2.5): True when you and your spouse lived apart "
            "at ALL times during the tax year. A married individual who does not file a joint return and "
            "did NOT live apart at all times has a $0 base amount for taxable Social Security; one who did "
            "uses the $25,000 of IRC 86(c)(1)(A). Unanswered, a separate figure assumes you did not."
        ),
    )
    other_taxpayers: list[OtherTaxpayer] = Field(
        default_factory=list,
        description="Other people in the household who file their OWN returns (unmarried partner, roommate).",
    )
    no_other_taxpayers: Answer[bool] | None = Field(
        default=None,
        description=(
            "True = the filer confirmed nobody else in the household files their own return; None = "
            "not asked. The sentinel that lets an empty other_taxpayers list mean 'none' instead of "
            "'never asked' (the same ambiguity StateFootprintYear's sentinels resolve)."
        ),
    )
    filing_status: Answer[FilingStatusInput] | None = Field(
        default=None,
        description=(
            "The CHOSEN federal filing status. 'Married' is not a status: a married couple "
            "elects married_filing_jointly or married_filing_separately (a position with "
            "dollar consequences, decided in the positions step). Nonresident-alien (1040-NR) "
            "filers cannot use married_filing_jointly or head_of_household — the residency "
            "result gates which statuses are offered."
        ),
    )
    spouse: Spouse | None = Field(
        default=None,
        description="The spouse as a second taxpayer; present on a married_filing_jointly or _separately return.",
    )
    dependents: list[Dependent] = Field(default_factory=list)


class ResidencePeriod(DateRange):
    """Where the user LIVED for a date range (drives state residency classification)."""

    state: str = Field(description="Two-letter state/territory code, e.g. 'CA', or 'ABROAD'.")
    provenance: Provenance


class WorkPeriod(DateRange):
    """Where the user WORKED for a date range; remote vs on-site matters for state sourcing."""

    state: str = Field(description="Two-letter state/territory code, e.g. 'CA', or 'ABROAD' — where the WORK was performed.")
    remote: bool | None = Field(default=None, description="True if the work was performed remotely.")
    employer_state: str | None = Field(
        default=None,
        description=(
            "Where the EMPLOYER sits when that differs from where the work was performed — the "
            "remote-work trap: a convenience-of-the-employer state (NY, DE, NE, PA, ...) can source "
            "remote wages to the employer's state, creating a second state return the worked-state "
            "answer alone never reveals. None = same as `state` / not asked."
        ),
    )
    provenance: Provenance


class StateFootprintYear(BaseModel):
    """Lived/worked date ranges for one tax year.

    An empty ``lived`` or ``worked`` list is AMBIGUOUS on its own — it can mean
    "not asked yet" or "genuinely none". The sentinels below resolve it: intake
    keeps asking until each dimension is either populated or explicitly denied,
    so a partial answer can never silently pass for a complete one, and a filer
    with no US residence or no US work can still terminate the interview.
    """

    model_config = ConfigDict(extra="forbid")

    lived: list[ResidencePeriod] = Field(default_factory=list)
    worked: list[WorkPeriod] = Field(default_factory=list)
    no_us_residence: bool | None = Field(
        default=None,
        description=(
            "True = the filer confirmed they had NO US residence at any point in this year "
            "(lived abroad all year); None = not asked. Set it instead of leaving `lived` "
            "ambiguously empty."
        ),
    )
    no_us_work: bool | None = Field(
        default=None,
        description=(
            "True = the filer confirmed NO US work in this year (no job, or worked only "
            "abroad); None = not asked. Set it instead of leaving `worked` ambiguously empty."
        ),
    )

    def is_complete(self) -> bool:
        """Both dimensions answered: each is populated or explicitly denied."""
        return bool(self.lived or self.no_us_residence) and bool(self.worked or self.no_us_work)


class IncomeDocument(BaseModel):
    """One entry of the income document inventory (W-2, 1099-NEC, 1098-T, K-1, ...)."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="Document kind, e.g. 'W-2', '1099-NEC', '1099-INT', '1098-T', 'K-1'.")
    status: DocumentStatus
    file: str | None = Field(default=None, description="Workspace-relative path once the document is collected.")
    owner: DocumentOwner = Field(
        default="taxpayer",
        description="Whose income this document reports — on a joint return each document is tagged to the taxpayer or the spouse who earned it.",
    )
    provenance: Provenance


class Banking(BaseModel):
    """Direct deposit / payment account; the routing number is checksum-validated at intake."""

    model_config = ConfigDict(extra="forbid")

    routing_number: Answer[str]
    account_number: Answer[str]
    account_type: Literal["checking", "savings"] | None = None

    @model_validator(mode="after")
    def _check_routing(self) -> "Banking":
        # Deliberately does NOT echo the submitted value (PII-safe errors).
        if not is_valid_routing_number(self.routing_number.value):
            raise ValueError(
                "routing_number failed ABA validation (must be exactly 9 digits with a "
                "valid checksum) — re-read it from the bottom-left of a check or the "
                "bank's official website and resubmit digits only"
            )
        return self


# The return filed for an earlier year (PriorFilings.return_forms; JF5b, P-018).
PriorReturnForm = Literal["1040", "1040-NR", "dual_status", "1040_with_6013_election", "not_filed"]


class PriorFilings(BaseModel):
    """Which years were filed before, plus late-filing context.

    ``prior_year_agi`` / ``prior_year_total_tax`` feed the §6654 estimated-tax
    safe harbor (calc op ``estimated_tax_safe_harbor``): the required annual
    payment is the smaller of 90% of the current year's tax and 100% of the
    prior year's (110% when prior AGI is high) — so a mid-year planning session
    cannot answer "am I withholding enough?" without these two figures. Both
    come straight off the prior-year Form 1040 (AGI = line 11; total tax =
    line 24). New fields default None, so profiles saved before they existed
    still load.
    """

    model_config = ConfigDict(extra="forbid")

    filed_years: Answer[list[int]] | None = None
    late_filing_context: Answer[str] | None = None
    prior_year_agi: Answer[int] | None = Field(
        default=None,
        description="The PRIOR year's AGI (that return's Form 1040 line 11) — drives the 110%-vs-100% safe-harbor tier.",
    )
    prior_year_total_tax: Answer[int] | None = Field(
        default=None,
        description="The PRIOR year's total tax (that return's Form 1040 line 24) — the base the safe-harbor percentage applies to.",
    )
    return_forms: dict[int, Answer[PriorReturnForm]] = Field(
        default_factory=dict,
        description=(
            "Which federal return was filed for each earlier year, keyed by that year (JF5b, P-018): '1040' "
            "(a resident's return for the whole year), '1040-NR' (a nonresident's), 'dual_status' (a split year: "
            "a Form 1040 with a Form 1040-NR statement, or the reverse), '1040_with_6013_election' (a joint "
            "Form 1040 made under the §6013(g)/(h) election to treat a nonresident spouse as a resident), or "
            "'not_filed'. The residency classifier reads ONLY the entry for the year before the tax year — "
            "IRC 7701(b)(2)(A)(i) starts residency partway through a year only for an alien who 'was not a "
            "resident of the United States at any time during the preceding calendar year', and Treas. Reg. "
            "301.7701(b)-4(e)(1): 'An alien individual who was a United States resident during any part of "
            "the preceding calendar year and who is a United States resident for any part of the current year "
            "will be considered to be taxable as a resident at the beginning of the current year.' So '1040' "
            "and 'dual_status' read as a prior-year resident, '1040-NR' as not, and 'not_filed' and "
            "'1040_with_6013_election' as unknown (not filing says nothing about residency, and whether an "
            "election year counts for that rule is not settled). The form is evidence, not the test "
            "(IRC 7701(b)(1)(A): a resident 'if (and only if)' a residency test is met). Never inferred from "
            "filed_years."
        ),
    )


class RetirementContributionsYear(BaseModel):
    """Elective deferrals / contributions for one year, split by TAX CHARACTER (N-11, N-15).

    The Roth-vs-pre-tax split is a fact agents kept carrying in their heads
    ("this portion is Roth and the rest is pre-tax") and re-stating on every
    revision: pre-tax 401(k) dollars lower W-2 box 1 today, Roth dollars do
    not, and the two move every MAGI test differently (calc op ``magi_ladder``).
    The calc ops (``contribution_limits`` / ``ira_contribution_eligibility`` /
    ``marginal_dollar_savings``) take explicit arguments — this section just
    PERSISTS the split so a revised number re-runs scenarios instead of a
    memory. For a CLOSED year the actuals come off the W-2 (box 12 codes D/AA,
    W) — this section is for the planning year's elections.
    """

    model_config = ConfigDict(extra="forbid")

    pretax_401k: Answer[int] | None = Field(
        default=None, description="Traditional (pre-tax) elective deferral for the year (W-2 box 12 code D).")
    roth_401k: Answer[int] | None = Field(
        default=None, description="Roth 401(k) elective deferral for the year (W-2 box 12 code AA) — shares the 402(g) limit with pre-tax.")
    traditional_ira: Answer[int] | None = Field(
        default=None, description="Traditional IRA contribution for the year (deductibility depends on employer-plan coverage + MAGI).")
    roth_ira: Answer[int] | None = Field(
        default=None,
        description=(
            "Roth IRA contribution for the year. Record it only AFTER calc op ira_contribution_eligibility "
            "confirms the MAGI phase-out — an ineligible contribution accrues a 6%-per-year excise until fixed."
        ),
    )
    hsa: Answer[int] | None = Field(
        default=None, description="HSA contribution for the year (limit depends on the COVERAGE TIER — see contribution_limits).")


class Profile(BaseModel):
    """The whole intake profile. Every section is optional — intake fills it incrementally."""

    model_config = ConfigDict(extra="forbid")

    identity: Identity | None = None
    immigration: Immigration | None = None
    residency_facts: ResidencyFacts | None = None
    household: Household | None = None
    state_footprint: dict[int, StateFootprintYear] = Field(
        default_factory=dict,
        description="Lived/worked date ranges keyed by tax year.",
    )
    income_documents: list[IncomeDocument] = Field(default_factory=list)
    retirement_contributions: dict[int, RetirementContributionsYear] = Field(
        default_factory=dict,
        description="Roth/pre-tax deferral split keyed by tax year (planning-year elections; N-11).",
    )
    banking: Banking | None = None
    prior_filings: PriorFilings | None = None
