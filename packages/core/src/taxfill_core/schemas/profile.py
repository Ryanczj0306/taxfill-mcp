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

from taxfill_core.calc import is_valid_routing_number

T = TypeVar("T")

ProvenanceKind = Literal["user_stated", "document", "computed"]
DocumentStatus = Literal["have", "missing", "not_applicable"]


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


class VisaPeriod(DateRange):
    """One period of the visa status timeline (eligibility is per-period, not per-year)."""

    status: str = Field(description="Immigration status during the period, e.g. 'F-1', 'H-1B', 'J-1'.")
    provenance: Provenance


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


class Identity(BaseModel):
    """Who is filing."""

    model_config = ConfigDict(extra="forbid")

    name: Answer[str] | None = None
    tax_id: Answer[str] | None = Field(default=None, description="SSN or ITIN.")
    dob: Answer[date] | None = None
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
    provenance: Provenance


class Household(BaseModel):
    """Filing-status facts and dependents."""

    model_config = ConfigDict(extra="forbid")

    marital_status: Answer[str] | None = None
    dependents: list[Dependent] = Field(default_factory=list)


class ResidencePeriod(DateRange):
    """Where the user LIVED for a date range (drives state residency classification)."""

    state: str = Field(description="Two-letter state/territory code, e.g. 'CA', or 'ABROAD'.")
    provenance: Provenance


class WorkPeriod(DateRange):
    """Where the user WORKED for a date range; remote vs on-site matters for state sourcing."""

    state: str = Field(description="Two-letter state/territory code, e.g. 'CA', or 'ABROAD'.")
    remote: bool | None = Field(default=None, description="True if the work was performed remotely.")
    provenance: Provenance


class StateFootprintYear(BaseModel):
    """Lived/worked date ranges for one tax year."""

    model_config = ConfigDict(extra="forbid")

    lived: list[ResidencePeriod] = Field(default_factory=list)
    worked: list[WorkPeriod] = Field(default_factory=list)


class IncomeDocument(BaseModel):
    """One entry of the income document inventory (W-2, 1099-NEC, 1098-T, K-1, ...)."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="Document kind, e.g. 'W-2', '1099-NEC', '1099-INT', '1098-T', 'K-1'.")
    status: DocumentStatus
    file: str | None = Field(default=None, description="Workspace-relative path once the document is collected.")
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


class PriorFilings(BaseModel):
    """Which years were filed before, plus late-filing context."""

    model_config = ConfigDict(extra="forbid")

    filed_years: Answer[list[int]] | None = None
    late_filing_context: Answer[str] | None = None


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
    banking: Banking | None = None
    prior_filings: PriorFilings | None = None
