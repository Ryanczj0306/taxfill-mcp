"""Jurisdiction knowledge loader — dev plan sections 3, 7 and 10.

Per-year tax math data (rate schedules, Tax Table parameters, standard
deduction, SE tax) lives in knowledge packs under
``knowledge/<jurisdiction>/<year>.yaml`` as DATA with citations, never
hardcoded in engine code (the no-LLM-arithmetic rule, dev plan section 10).
This module loads and validates those packs; :mod:`taxfill_core.calc`
consumes them.

Freshness protocol (dev plan section 7): a missing pack is not a silent
fallback. For any tax year newer than the newest shipped pack the agent must
resolve numbers via the official sources in ``knowledge/sources.yaml``
(irs.gov only), cite them, and author a pack — the loader's error message
says exactly that.

Validation errors are intentionally prescriptive (dev plan section 11):
every failure tells the pack author exactly what to fix.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from taxfill_core.datadir import knowledge_dir


_STATE_GOV_US_RE = re.compile(r"\.state\.[a-z]{2}\.us$")


def is_official_gov_host(hostname: str) -> bool:
    """True only for official US government hosts.

    Accepted: ``.gov``, ``.mil``, and the STATE-GOVERNMENT ``.us`` namespace
    (``*.state.<xx>.us``, e.g. revenue.state.mn.us — several state Departments
    of Revenue publish there). Bare second-level ``.us`` hosts are REJECTED:
    .us is an open registry anyone can buy into (evil.us), so it is not a
    government signal by itself.
    """
    h = (hostname or "").lower()
    if h == "gov" or h.endswith(".gov") or h == "mil" or h.endswith(".mil"):
        return True
    return bool(_STATE_GOV_US_RE.search(h))


def validate_gov_url(value: str) -> str:
    """Validate a citation/source URL: http(s) scheme AND an official US gov host.

    Knowledge data and the source registry cite official government documents
    only: federal ``.gov`` (irs.gov, congress.gov, treasury.gov, ...), ``.mil``,
    and the state-government ``.us`` namespace (e.g. revenue.state.mn.us).
    Blogs/commercial sites are never authority. Scheme and host failures raise
    distinct messages.
    """
    if not value.startswith(("https://", "http://")):
        raise ValueError(
            "url must be the full official document URL starting with https:// "
            "(knowledge data is cited to official government sources only)"
        )
    hostname = (urlparse(value).hostname or "").lower()
    if not is_official_gov_host(hostname):
        raise ValueError(
            f"url must point to an official US government host — a federal/.gov site "
            f"(irs.gov, treasury.gov), a .mil site, or a state-government .us host "
            f"(*.state.<xx>.us, e.g. revenue.state.mn.us), got host {hostname!r}. "
            f"Bare .us domains are an open registry and blogs/commercial sites are "
            f"never authority for tax data."
        )
    return value

# The four federal filing statuses every tax block must cover. (A qualifying
# surviving spouse uses the married_filing_jointly column — the alias is
# resolved in calc.py, not stored in packs.)
FilingStatus = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
]

FILING_STATUSES: tuple[str, ...] = (
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
)

_JURISDICTION_RE = re.compile(r"^(federal|states/[a-z]{2})$")


def _repo_knowledge_dir() -> Path:
    """Default pack location: the repo ``knowledge/`` (checkout) or the
    wheel-packaged ``_data/knowledge`` — see :mod:`taxfill_core.datadir`."""
    return knowledge_dir()


def _as_exact_decimal(value: object) -> object:
    """Convert YAML floats to Decimal via str() so 0.22 stays exactly 0.22."""
    if isinstance(value, float):
        return Decimal(str(value))
    return value


class Citation(BaseModel):
    """Pinpoint citation to the official document a data block came from."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        description="Document title plus pinpoint (section / table / page / line), e.g. 'Rev. Proc. 2022-38, Section 3.01, Tables 1-4'."
    )
    url: str = Field(description="Official document URL (irs.gov / .gov only; see knowledge/sources.yaml).")

    @field_validator("url")
    @classmethod
    def _url_is_gov(cls, value: str) -> str:
        return validate_gov_url(value)


class RateBracket(BaseModel):
    """One bracket of a section 1(j)(2) rate schedule: over / but_not_over / rate."""

    model_config = ConfigDict(extra="forbid")

    over: int = Field(ge=0, description="Taxable income must exceed this amount (0 for the bottom bracket).")
    but_not_over: int | None = Field(
        default=None,
        description="Upper bound of the bracket (income == bound is still in this bracket); null for the top bracket.",
    )
    rate: Decimal = Field(description="Marginal rate as a decimal fraction, e.g. 0.22.")

    _coerce_rate = field_validator("rate", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_bracket(self) -> "RateBracket":
        if not (Decimal("0") < self.rate < Decimal("1")):
            raise ValueError(
                f"bracket rate must be a fraction strictly between 0 and 1 (e.g. 0.22 for 22%), got {self.rate}"
            )
        if self.but_not_over is not None and self.but_not_over <= self.over:
            raise ValueError(
                f"bracket but_not_over ({self.but_not_over}) must be greater than over ({self.over}) — "
                f"copy the bounds exactly from the published rate table"
            )
        return self


class RateSchedules(BaseModel):
    """Per-filing-status ordered bracket lists, with one citation for the block."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    schedules: dict[FilingStatus, list[RateBracket]]

    @model_validator(mode="after")
    def _check_schedules(self) -> "RateSchedules":
        missing = [s for s in FILING_STATUSES if s not in self.schedules]
        if missing:
            raise ValueError(
                f"rate_schedules.schedules must define all four filing statuses; missing: {', '.join(missing)} — "
                f"add them from the published rate tables (one table per status)"
            )
        for status, brackets in self.schedules.items():
            if not brackets:
                raise ValueError(f"rate_schedules.schedules['{status}'] is empty — add the published brackets")
            if brackets[0].over != 0:
                raise ValueError(
                    f"rate_schedules.schedules['{status}']: the first bracket must start at over=0 "
                    f"('Not over $X' row), got over={brackets[0].over}"
                )
            for i, bracket in enumerate(brackets):
                is_last = i == len(brackets) - 1
                if is_last and bracket.but_not_over is not None:
                    raise ValueError(
                        f"rate_schedules.schedules['{status}']: the last bracket must have but_not_over: null "
                        f"(the published 'Over $X' top row has no upper bound)"
                    )
                if not is_last:
                    if bracket.but_not_over is None:
                        raise ValueError(
                            f"rate_schedules.schedules['{status}']: bracket {i} has but_not_over: null but is not "
                            f"the last bracket — only the top bracket is unbounded"
                        )
                    nxt = brackets[i + 1]
                    if nxt.over != bracket.but_not_over:
                        raise ValueError(
                            f"rate_schedules.schedules['{status}']: bracket {i + 1} must start exactly where "
                            f"bracket {i} ends (over={bracket.but_not_over}), got over={nxt.over} — brackets must "
                            f"be contiguous with no gaps or overlaps"
                        )
        return self


class TaxTableBand(BaseModel):
    """One run of equal-width Tax Table rows, e.g. $50-wide rows from 3,000 to 100,000."""

    model_config = ConfigDict(extra="forbid")

    at_least: int = Field(ge=0, description="Lower bound of the band (inclusive).")
    below: int = Field(description="Upper bound of the band (exclusive).")
    row_width: int = Field(ge=1, description="Width of each row in the band, in whole dollars.")

    @model_validator(mode="after")
    def _check_band(self) -> "TaxTableBand":
        if self.below <= self.at_least:
            raise ValueError(
                f"tax_table band: below ({self.below}) must be greater than at_least ({self.at_least})"
            )
        if (self.below - self.at_least) % self.row_width != 0:
            raise ValueError(
                f"tax_table band [{self.at_least}, {self.below}): span {self.below - self.at_least} is not a "
                f"multiple of row_width {self.row_width} — rows would not tile the band; check the published "
                f"table's row boundaries"
            )
        return self


class TaxTable(BaseModel):
    """Parameters that reproduce the published IRS Tax Table (mandatory below the cutoff)."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    applies_below: int = Field(gt=0, description="The Tax Table is mandatory for taxable income below this amount.")
    rounding: Literal["half_up"] = Field(
        description="Row tax = rate schedule at the row midpoint, rounded to the nearest dollar with 50 cents up."
    )
    row_bands: list[TaxTableBand] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_bands_tile_table(self) -> "TaxTable":
        if self.row_bands[0].at_least != 0:
            raise ValueError(
                f"tax_table.row_bands must start at 0 (the published table's first row is 'at least 0'), "
                f"got at_least={self.row_bands[0].at_least}"
            )
        for i in range(1, len(self.row_bands)):
            prev, cur = self.row_bands[i - 1], self.row_bands[i]
            if cur.at_least != prev.below:
                raise ValueError(
                    f"tax_table.row_bands: band {i} must start exactly where band {i - 1} ends "
                    f"({prev.below}), got at_least={cur.at_least} — bands must tile the table with no gaps"
                )
        if self.row_bands[-1].below != self.applies_below:
            raise ValueError(
                f"tax_table.row_bands must end exactly at applies_below ({self.applies_below}), "
                f"got below={self.row_bands[-1].below} on the last band"
            )
        return self


class TaxComputationWorksheet(BaseModel):
    """The schedule-method region (at/above the Tax Table cutoff)."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    applies_at_or_above: int = Field(gt=0)


class AdditionalAgedOrBlind(BaseModel):
    """Additional standard deduction per 65-or-older / blind condition, per person."""

    model_config = ConfigDict(extra="forbid")

    married: int = Field(gt=0, description="Per condition per person for married statuses (and surviving spouses).")
    unmarried: int = Field(gt=0, description="Per condition for unmarried, not-a-surviving-spouse taxpayers.")


class StandardDeduction(BaseModel):
    """Base standard deduction per filing status plus aged/blind additions."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    amounts: dict[FilingStatus, int]
    additional_aged_or_blind: AdditionalAgedOrBlind

    @model_validator(mode="after")
    def _check_all_statuses(self) -> "StandardDeduction":
        missing = [s for s in FILING_STATUSES if s not in self.amounts]
        if missing:
            raise ValueError(
                f"standard_deduction.amounts must define all four filing statuses; missing: {', '.join(missing)}"
            )
        for status, amount in self.amounts.items():
            if amount <= 0:
                raise ValueError(
                    f"standard_deduction.amounts['{status}'] must be a positive whole-dollar amount, got {amount}"
                )
        return self


class SeTaxParams(BaseModel):
    """Schedule SE parameters (Part I lines 4a-13)."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    net_earnings_factor: Decimal = Field(description="Line 4a factor, 0.9235 (92.35%).")
    ss_rate: Decimal = Field(description="Line 10 social security rate, 0.124 (12.4%).")
    medicare_rate: Decimal = Field(description="Line 11 Medicare rate, 0.029 (2.9%).")
    ss_wage_base: int = Field(gt=0, description="Line 7 maximum earnings subject to social security tax.")
    minimum_net_earnings: int = Field(
        ge=0, description="Line 4c threshold: below this net-earnings amount no SE tax is owed."
    )

    _coerce_decimals = field_validator("net_earnings_factor", "ss_rate", "medicare_rate", mode="before")(
        _as_exact_decimal
    )

    @model_validator(mode="after")
    def _check_fractions(self) -> "SeTaxParams":
        for name in ("net_earnings_factor", "ss_rate", "medicare_rate"):
            value = getattr(self, name)
            if not (Decimal("0") < value < Decimal("1")):
                raise ValueError(
                    f"se_tax.{name} must be a fraction strictly between 0 and 1 (e.g. 0.9235), got {value}"
                )
        return self


# The five threshold keys Forms 8959/8960 use. Qualifying surviving spouse is listed
# EXPLICITLY (not aliased to the MFJ column like the bracket tables) because the two
# forms bucket it differently: Form 8959 groups QSS with single/HoH at $200,000 while
# Form 8960 groups it with MFJ at $250,000 — an alias would silently get one form wrong.
_THRESHOLD_STATUSES: tuple[str, ...] = FILING_STATUSES + ("qualifying_surviving_spouse",)


class _SurtaxParams(BaseModel):
    """Shared shape for the two high-income surtaxes: a flat rate over a status threshold."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    rate: Decimal = Field(description="Flat surtax rate as a fraction, e.g. 0.009 (0.9%) or 0.038 (3.8%).")
    thresholds: dict[str, int] = Field(
        description="Threshold in whole dollars per filing status — all five statuses explicit."
    )

    _coerce_rate = field_validator("rate", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_rate_and_thresholds(self) -> "_SurtaxParams":
        if not (Decimal("0") < self.rate < Decimal("1")):
            raise ValueError(f"rate must be a fraction strictly between 0 and 1 (e.g. 0.009), got {self.rate}")
        missing = [s for s in _THRESHOLD_STATUSES if s not in self.thresholds]
        unknown = [s for s in self.thresholds if s not in _THRESHOLD_STATUSES]
        if missing or unknown:
            raise ValueError(
                f"thresholds must contain exactly the five filing statuses "
                f"{list(_THRESHOLD_STATUSES)} — missing {missing}, unknown {unknown}. "
                f"(qualifying_surviving_spouse is explicit: Form 8959 buckets it at the "
                f"single/$200,000 level, Form 8960 at the MFJ/$250,000 level)"
            )
        bad = {s: v for s, v in self.thresholds.items() if v <= 0}
        if bad:
            raise ValueError(f"thresholds must be positive whole-dollar amounts, got {bad}")
        return self


class AdditionalMedicareTaxParams(_SurtaxParams):
    """Form 8959 parameters: 0.9% Additional Medicare Tax on Medicare wages + SE
    earnings above the filing-status threshold (statutory since 2013, not indexed)."""


class NiitParams(_SurtaxParams):
    """Form 8960 parameters: 3.8% Net Investment Income Tax on the lesser of net
    investment income or MAGI above the filing-status threshold (statutory, not indexed)."""


# ── Phase F tax blocks: preferential rates, SS benefits, adjustments, education
#    credits, PTC. Each block is DATA with a citation; the worksheet mechanics the
#    calc ops must reproduce are recorded in the model docstrings. ──────────────


class CapitalGainsBrackets(BaseModel):
    """Maximum capital gains rate breakpoints (IRC section 1(h), indexed under
    section 1(j)(5)): TAXABLE-INCOME ceilings for the 0% and 15% rates on
    adjusted net capital gain / qualified dividends — 20% applies above the 15%
    ceiling. These are the Qualified Dividends and Capital Gain Tax Worksheet
    line 6 / line 13 amounts (ordinary income stacks first). Post-TCJA they are
    indexed separately from the ordinary brackets and are NOT equal to bracket
    boundaries — never derive them from the rate schedules."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    max_zero_rate_amount: dict[str, int] = Field(
        description="Taxable-income ceiling for the 0% rate, per filing status (all five explicit)."
    )
    max_15_percent_rate_amount: dict[str, int] = Field(
        description="Taxable-income ceiling for the 15% rate, per filing status; 20% applies above it."
    )

    @model_validator(mode="after")
    def _check_statuses_and_ordering(self) -> "CapitalGainsBrackets":
        for name, amounts in (
            ("max_zero_rate_amount", self.max_zero_rate_amount),
            ("max_15_percent_rate_amount", self.max_15_percent_rate_amount),
        ):
            missing = [s for s in _THRESHOLD_STATUSES if s not in amounts]
            unknown = [s for s in amounts if s not in _THRESHOLD_STATUSES]
            if missing or unknown:
                raise ValueError(
                    f"capital_gains_brackets.{name} must contain exactly the five filing statuses "
                    f"{list(_THRESHOLD_STATUSES)} — missing {missing}, unknown {unknown}. "
                    f"(qualifying_surviving_spouse is explicit — every Rev. Proc. section 3.03 groups it "
                    f"with joint returns; estates/trusts amounts do not belong in this block)"
                )
            bad = {s: v for s, v in amounts.items() if v <= 0}
            if bad:
                raise ValueError(f"capital_gains_brackets.{name} must be positive whole-dollar amounts, got {bad}")
        misordered = {
            s: (self.max_zero_rate_amount[s], self.max_15_percent_rate_amount[s])
            for s in _THRESHOLD_STATUSES
            if self.max_zero_rate_amount[s] >= self.max_15_percent_rate_amount[s]
        }
        if misordered:
            raise ValueError(
                f"capital_gains_brackets: max_zero_rate_amount must be strictly below max_15_percent_rate_amount "
                f"for every status, violated for {misordered} — copy both ceilings from the Rev. Proc. "
                f"section 3.03 tables"
            )
        return self


class MagiPhaseoutRange(BaseModel):
    """A linear MAGI phase-out: full benefit at or below ``start``, fully
    eliminated at MAGI >= ``end``, reduced pro rata in between."""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(gt=0, description="MAGI at which the phase-out begins (full benefit at or below this).")
    end: int = Field(gt=0, description="MAGI at or above which the benefit is fully eliminated.")

    @model_validator(mode="after")
    def _check_range(self) -> "MagiPhaseoutRange":
        if self.end <= self.start:
            raise ValueError(
                f"phase-out end ({self.end}) must be greater than start ({self.start}) — "
                f"copy both bounds from the published phase-out range"
            )
        return self


# The taxable-Social-Security worksheet buckets MFS by BEHAVIOR, not just status:
# lived-apart-all-year uses the single thresholds (explicit key below); lived with
# the spouse at any time gets $0 for both tiers (mfs_living_with_spouse_base).
_TAXABLE_SS_STATUSES: tuple[str, ...] = (
    "single",
    "married_filing_jointly",
    "head_of_household",
    "qualifying_surviving_spouse",
    "married_filing_separately_lived_apart_all_year",
)


class TaxableSocialSecurityParams(BaseModel):
    """Social Security Benefits Worksheet parameters (Form 1040 line 6b; line 5b
    in 2019). Statutory under IRC section 86(c), never indexed — identical every
    supported year.

    MFS who lived WITH the spouse at any time during the year is a RULE, not a
    threshold column: both tiers are ``mfs_living_with_spouse_base`` ($0), the
    worksheet skips lines 8-15, and taxable benefits =
    min(0.85 x provisional income, 0.85 x benefits). The published worksheet
    prints the second tier as the line-10 gap (adjusted base minus base:
    $9,000, or $12,000 for MFJ); this block stores the explicit IRC 86(c)(2)
    adjusted base amounts — the two forms are arithmetically identical."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    base_amount: dict[str, int] = Field(
        description="First-tier provisional-income threshold (worksheet line 8), per status."
    )
    adjusted_base_amount: dict[str, int] = Field(
        description="Second-tier threshold (IRC 86(c)(2)); the worksheet encodes it as the line-10 gap."
    )
    mfs_living_with_spouse_base: int = Field(
        default=0,
        ge=0,
        description="Both tiers for MFS who lived with the spouse at any time during the year — $0 by rule.",
    )
    inclusion_rate_tier1: Decimal = Field(description="Worksheet line 2 factor, 0.50.")
    inclusion_rate_tier2: Decimal = Field(description="Worksheet lines 15/17 factor, 0.85.")
    max_taxable_share_of_benefits: Decimal = Field(
        description="Taxable benefits never exceed this share of total benefits (line 17 cap), 0.85."
    )

    _coerce_rates = field_validator(
        "inclusion_rate_tier1", "inclusion_rate_tier2", "max_taxable_share_of_benefits", mode="before"
    )(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_amounts_and_rates(self) -> "TaxableSocialSecurityParams":
        for name, amounts in (
            ("base_amount", self.base_amount),
            ("adjusted_base_amount", self.adjusted_base_amount),
        ):
            missing = [s for s in _TAXABLE_SS_STATUSES if s not in amounts]
            unknown = [s for s in amounts if s not in _TAXABLE_SS_STATUSES]
            if missing or unknown:
                raise ValueError(
                    f"taxable_social_security.{name} must contain exactly {list(_TAXABLE_SS_STATUSES)} — "
                    f"missing {missing}, unknown {unknown}. (MFS living WITH the spouse is not a map key: "
                    f"both of its tiers are $0 by rule — mfs_living_with_spouse_base)"
                )
        misordered = {
            s: (self.base_amount[s], self.adjusted_base_amount[s])
            for s in _TAXABLE_SS_STATUSES
            if self.adjusted_base_amount[s] <= self.base_amount[s]
        }
        if misordered:
            raise ValueError(
                f"taxable_social_security: adjusted_base_amount must exceed base_amount for every status "
                f"(IRC 86(c): 34,000 over 25,000; 44,000 over 32,000), violated for {misordered}"
            )
        for name in ("inclusion_rate_tier1", "inclusion_rate_tier2", "max_taxable_share_of_benefits"):
            value = getattr(self, name)
            if not (Decimal("0") < value <= Decimal("1")):
                raise ValueError(
                    f"taxable_social_security.{name} must be a fraction in (0, 1] (0.50 / 0.85), got {value}"
                )
        return self


class EmployeeSocialSecurityParams(BaseModel):
    """Employee social security (OASDI) withholding parameters — the excess-SS /
    tier 1 RRTA credit on Schedule 3 (line 11 in 2019 and 2021-2024; line 10 on
    the 2020 schedule).

    ``max_withholding`` (rate x wage base, exact to the cent) is PER PERSON: on a
    joint return each spouse's withholding is compared to the cap separately,
    never combined. The credit exists only when MULTIPLE employers together
    over-withheld; a single employer's excess must be adjusted by that employer
    (Form 843 if it refuses) and is never claimable on the return."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    rate: Decimal = Field(description="Employee OASDI rate under IRC 3101(a), 0.062 (6.2%).")
    ss_wage_base: int = Field(gt=0, description="Social security wage base limit for the year.")
    max_withholding: Decimal = Field(
        description="Maximum employee withholding for the year, in dollars and cents (rate x wage base)."
    )

    _coerce_decimals = field_validator("rate", "max_withholding", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_rate_and_cap(self) -> "EmployeeSocialSecurityParams":
        if not (Decimal("0") < self.rate < Decimal("1")):
            raise ValueError(
                f"employee_social_security.rate must be a fraction strictly between 0 and 1 (e.g. 0.062), "
                f"got {self.rate}"
            )
        expected = self.rate * self.ss_wage_base
        if self.max_withholding != expected:
            raise ValueError(
                f"employee_social_security.max_withholding ({self.max_withholding}) must equal "
                f"rate x ss_wage_base ({self.rate} x {self.ss_wage_base} = {expected}) — the published "
                f"per-person cap is exactly that product; fix whichever value was mistranscribed"
            )
        return self


# Statuses that may take the student-loan-interest deduction. MFS is deliberately
# NOT here: the deduction is disallowed entirely for married filing separately.
_SLI_STATUSES: tuple[str, ...] = (
    "single",
    "married_filing_jointly",
    "head_of_household",
    "qualifying_surviving_spouse",
)


class StudentLoanInterestParams(BaseModel):
    """Section 221 student-loan-interest deduction (Schedule 1).

    ``married_filing_separately`` is deliberately ABSENT from ``phaseout``: an
    MFS filer may not take the deduction at all (IRC 221(e)(2)), so the calc op
    treats a status missing from the map as NOT ALLOWED — never as unlimited.
    Reduction = tentative deduction (min(max_deduction, interest paid)) x
    (MAGI - start) / (end - start); the span is $15,000 ($30,000 MFJ) every
    supported year."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    max_deduction: int = Field(
        gt=0, description="Statutory cap (IRC 221(b)(1)), $2,500 — not inflation-indexed."
    )
    phaseout: dict[str, MagiPhaseoutRange]

    @model_validator(mode="after")
    def _check_statuses(self) -> "StudentLoanInterestParams":
        if "married_filing_separately" in self.phaseout:
            raise ValueError(
                "student_loan_interest.phaseout must NOT contain married_filing_separately — the deduction "
                "is disallowed entirely for MFS (IRC 221(e)(2)); a missing status means not-allowed, so "
                "adding a range here would wrongly grant the deduction"
            )
        missing = [s for s in _SLI_STATUSES if s not in self.phaseout]
        unknown = [s for s in self.phaseout if s not in _SLI_STATUSES]
        if missing or unknown:
            raise ValueError(
                f"student_loan_interest.phaseout must contain exactly {list(_SLI_STATUSES)} — "
                f"missing {missing}, unknown {unknown}"
            )
        return self


class MfjOtherPhaseout(BaseModel):
    """Per-status MAGI phase-outs where the source distinguishes only joint
    returns vs everyone else. ``other`` = single / head_of_household /
    qualifying_surviving_spouse; MFS has no key because it is barred from the
    education credits entirely."""

    model_config = ConfigDict(extra="forbid")

    married_filing_jointly: MagiPhaseoutRange
    other: MagiPhaseoutRange


class AotcParams(BaseModel):
    """American opportunity credit: 100% of the first ``first_dollar_cap`` of
    qualified expenses PER STUDENT plus ``second_rate`` of the next
    ``first_dollar_cap``, up to ``per_student_cap``. ``refundable_fraction`` of
    the allowed credit is refundable — unless the Form 8863 line 7 under-age-24
    exception applies, which makes the whole credit nonrefundable."""

    model_config = ConfigDict(extra="forbid")

    per_student_cap: int = Field(gt=0)
    first_dollar_cap: int = Field(gt=0)
    second_rate: Decimal
    refundable_fraction: Decimal
    phaseout: MfjOtherPhaseout

    _coerce_rates = field_validator("second_rate", "refundable_fraction", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_fractions(self) -> "AotcParams":
        for name in ("second_rate", "refundable_fraction"):
            value = getattr(self, name)
            if not (Decimal("0") < value < Decimal("1")):
                raise ValueError(
                    f"education_credits.aotc.{name} must be a fraction strictly between 0 and 1 "
                    f"(0.25 / 0.40), got {value}"
                )
        return self


class LlcParams(BaseModel):
    """Lifetime learning credit: ``rate`` of up to ``per_return_expense_cap`` of
    qualified expenses PER RETURN (regardless of student count); nonrefundable.
    The same student cannot get both the AOTC and the LLC in one year."""

    model_config = ConfigDict(extra="forbid")

    per_return_expense_cap: int = Field(gt=0)
    rate: Decimal
    phaseout: MfjOtherPhaseout

    _coerce_rate = field_validator("rate", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_rate(self) -> "LlcParams":
        if not (Decimal("0") < self.rate < Decimal("1")):
            raise ValueError(
                f"education_credits.llc.rate must be a fraction strictly between 0 and 1 (0.20), got {self.rate}"
            )
        return self


class EducationCreditsParams(BaseModel):
    """Form 8863 education credits (AOTC + LLC).

    married_filing_separately may claim NEITHER credit in any year — a RULE,
    not a phase-out (the calc op returns zero for MFS regardless of MAGI).
    Phase-out is linear: tentative credit x (end - MAGI) / (end - start)."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    aotc: AotcParams
    llc: LlcParams


class PtcApplicablePercentageBand(BaseModel):
    """One row of the Form 8962 Table 2 band table. For integer FPL percentage
    ``p`` with fpl_pct_at_least <= p < fpl_pct_less_than, the applicable figure
    is the linear interpolation from ``initial`` to ``final`` across the band,
    rounded HALF-UP to 4 decimal places (0.07225 -> 0.0723)."""

    model_config = ConfigDict(extra="forbid")

    fpl_pct_at_least: int = Field(ge=0, description="Inclusive lower bound of the band, in integer FPL percent.")
    fpl_pct_less_than: int | None = Field(
        description="Exclusive upper bound; null on the top ('400 or more') band."
    )
    initial: Decimal = Field(description="Applicable figure at the bottom of the band, as a DECIMAL (0.02 = 2%).")
    final: Decimal = Field(description="Applicable figure approached at the top of the band, as a DECIMAL.")

    _coerce_figures = field_validator("initial", "final", mode="before")(_as_exact_decimal)

    @model_validator(mode="after")
    def _check_band(self) -> "PtcApplicablePercentageBand":
        if not (Decimal("0") <= self.initial <= self.final < Decimal("1")):
            raise ValueError(
                f"ptc applicable-percentage band [{self.fpl_pct_at_least}, {self.fpl_pct_less_than}): "
                f"initial/final must be DECIMAL fractions with 0 <= initial <= final < 1 (write 2.00% as 0.02, "
                f"8.5% as 0.085 — normalize the Rev. Proc.'s percent-form numbers), got "
                f"initial={self.initial}, final={self.final}"
            )
        if self.fpl_pct_less_than is not None and self.fpl_pct_less_than <= self.fpl_pct_at_least:
            raise ValueError(
                f"ptc applicable-percentage band: fpl_pct_less_than ({self.fpl_pct_less_than}) must exceed "
                f"fpl_pct_at_least ({self.fpl_pct_at_least})"
            )
        return self


class PtcFplTable(BaseModel):
    """Federal poverty line amounts by household size (1-8), plus the increment
    for each person above 8 (Form 8962 Tables 1-1 / 1-2 / 1-3)."""

    model_config = ConfigDict(extra="forbid")

    household_size: dict[int, int]
    per_additional_person: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_sizes(self) -> "PtcFplTable":
        if sorted(self.household_size) != list(range(1, 9)):
            raise ValueError(
                f"ptc federal_poverty_line household_size must have exactly the keys 1-8 (the published "
                f"tables list sizes 1-8, then a per-additional-person increment), got {sorted(self.household_size)}"
            )
        if any(v <= 0 for v in self.household_size.values()):
            raise ValueError("ptc federal_poverty_line amounts must be positive whole-dollar amounts")
        return self


class PtcFederalPovertyLine(BaseModel):
    """FPL guidelines used on Form 8962 line 4. A tax year uses the PRIOR
    calendar year's HHS guidelines (``guidelines_year``): TY2023 uses the 2022
    guidelines, TY2024 the 2023 guidelines. Taxpayers who lived in both AK/HI
    and elsewhere during the year (or spouses in different states) use the
    table with the HIGHER amounts."""

    model_config = ConfigDict(extra="forbid")

    guidelines_year: int = Field(ge=1990, le=2100)
    contiguous_48_and_dc: PtcFplTable
    alaska: PtcFplTable
    hawaii: PtcFplTable


class PtcRepaymentLimitationRow(BaseModel):
    """One Form 8962 Table 5 row, keyed by line 5 (integer FPL%): the row
    applies when line 5 < ``fpl_band_lt``. The last row (fpl_band_lt: null =
    '400 or more') has null caps: NO limitation — the full excess APTC is
    repaid (line 28 is left blank)."""

    model_config = ConfigDict(extra="forbid")

    fpl_band_lt: int | None = Field(description="Exclusive FPL% upper bound of the row; null = 400 or more.")
    single: int | None
    other: int | None = Field(
        description="Every non-single filing status (MFJ, MFS, HoH, QSS) uses this column."
    )

    @model_validator(mode="after")
    def _check_row(self) -> "PtcRepaymentLimitationRow":
        if self.fpl_band_lt is None:
            if self.single is not None or self.other is not None:
                raise ValueError(
                    "ptc repayment_limitation: the 400-or-more row (fpl_band_lt: null) must have null "
                    "single/other — at 400% FPL or more there is NO repayment limitation (full excess "
                    "APTC is repaid)"
                )
        elif self.single is None or self.other is None or self.single <= 0 or self.other <= 0:
            raise ValueError(
                f"ptc repayment_limitation row for FPL% below {self.fpl_band_lt} must carry positive "
                f"dollar caps in both columns, got single={self.single}, other={self.other}"
            )
        return self


class PtcParams(BaseModel):
    """Form 8962 Premium Tax Credit parameters — the ARPA applicable-percentage
    table as extended to taxable years 2023-2025 by IRA section 12001(a). The
    regime EXPIRES after TY2025: never extrapolate these parameters forward.

    Applicable-figure mechanics the calc op must reproduce exactly (Worksheet 2
    + Table 2): line 5 = household income / FPL x 100 TRUNCATED to an integer
    (drop decimals, never round — 3.997 becomes 399; enter literally 401 when
    over 400%); the figure for the integer is the band's linear interpolation
    rounded HALF-UP to 4 decimals (349 -> 0.0723, 399 -> 0.0848); at or above
    400 the figure stays 0.0850 — there is NO eligibility cliff
    (``no_400_pct_cliff``), but the repayment LIMITATION does vanish at 400%
    (the last ``repayment_limitation`` row). Do not conflate the two."""

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    applicable_percentage_table: list[PtcApplicablePercentageBand] = Field(min_length=1)
    federal_poverty_line: PtcFederalPovertyLine
    repayment_limitation: list[PtcRepaymentLimitationRow] = Field(min_length=1)
    no_400_pct_cliff: bool

    @model_validator(mode="after")
    def _check_tables(self) -> "PtcParams":
        bands = self.applicable_percentage_table
        if bands[0].fpl_pct_at_least != 0:
            raise ValueError(
                "ptc.applicable_percentage_table must start at fpl_pct_at_least: 0 — the 'less than 150%' "
                "row also covers below-100%-FPL filers who qualify through an exception"
            )
        for i, band in enumerate(bands):
            is_last = i == len(bands) - 1
            if is_last and band.fpl_pct_less_than is not None:
                raise ValueError(
                    "ptc.applicable_percentage_table: the last band must have fpl_pct_less_than: null "
                    "(the '400 or more' row has no upper bound)"
                )
            if not is_last:
                if band.fpl_pct_less_than is None:
                    raise ValueError(
                        f"ptc.applicable_percentage_table: band {i} has fpl_pct_less_than: null but is not "
                        f"the last band — only the top band is unbounded"
                    )
                if bands[i + 1].fpl_pct_at_least != band.fpl_pct_less_than:
                    raise ValueError(
                        f"ptc.applicable_percentage_table: band {i + 1} must start exactly where band {i} "
                        f"ends ({band.fpl_pct_less_than}), got {bands[i + 1].fpl_pct_at_least} — bands must "
                        f"be contiguous with no gaps or overlaps"
                    )
        rows = self.repayment_limitation
        if rows[-1].fpl_band_lt is not None:
            raise ValueError(
                "ptc.repayment_limitation must end with the unlimited row (fpl_band_lt: null — 400% FPL "
                "or more repays the full excess APTC)"
            )
        bounds = [row.fpl_band_lt for row in rows[:-1]]
        if any(b is None for b in bounds) or bounds != sorted(bounds):
            raise ValueError(
                "ptc.repayment_limitation rows must be in ascending fpl_band_lt order, with null only on "
                "the last row"
            )
        return self


class TaxKnowledge(BaseModel):
    """The ``tax`` block of a knowledge pack: everything calc.py needs for one year.

    Extra keys are allowed so later milestones can add blocks (EITC/CTC
    phase-outs, credits, ...) without breaking older engine versions.
    """

    model_config = ConfigDict(extra="allow")

    rate_schedules: RateSchedules
    tax_table: TaxTable
    tax_computation_worksheet: TaxComputationWorksheet
    standard_deduction: StandardDeduction
    se_tax: SeTaxParams
    # High-income surtaxes (Schedule 2 lines 11/12). Optional so packs predating the
    # blocks still load; calc raises a prescriptive error when a year lacks them.
    additional_medicare_tax: AdditionalMedicareTaxParams | None = None
    niit: NiitParams | None = None
    # Phase F blocks — also optional so older packs still load; calc raises a
    # prescriptive error when a year lacks a block an operation needs.
    capital_gains_brackets: CapitalGainsBrackets | None = None
    taxable_social_security: TaxableSocialSecurityParams | None = None
    employee_social_security: EmployeeSocialSecurityParams | None = None
    student_loan_interest: StudentLoanInterestParams | None = None
    education_credits: EducationCreditsParams | None = None
    # Premium Tax Credit: shipped only for years whose ARPA/IRA table regime is
    # verified (2023-2024; the regime runs through TY2025 and then expires).
    ptc: PtcParams | None = None

    @model_validator(mode="after")
    def _check_table_worksheet_boundary(self) -> "TaxKnowledge":
        if self.tax_computation_worksheet.applies_at_or_above != self.tax_table.applies_below:
            raise ValueError(
                f"tax_computation_worksheet.applies_at_or_above "
                f"({self.tax_computation_worksheet.applies_at_or_above}) must equal tax_table.applies_below "
                f"({self.tax_table.applies_below}) — the table and the worksheet must meet at one boundary "
                f"with no gap (the IRS boundary is $100,000)"
            )
        return self


# ── M3 blocks: filing logistics & benefits, each cited (dev plan sections 3, 9) ──


class FilingThresholds(BaseModel):
    """Gross-income filing-requirement amounts by status (Pub 501 Chart A).

    Sub-keys vary by status (``under_65`` / ``age_65_or_older`` for single & HoH;
    ``both_under_65`` / ``one_spouse_65_or_older`` / ``both_spouses_65_or_older``
    for MFJ; ``any_age`` for MFS — which is $5 regardless of age), so the inner
    map is left open rather than forced into one shape.
    """

    model_config = ConfigDict(extra="forbid")

    citation: Citation
    # Keyed by status name. The four base FILING_STATUSES are required;
    # 'qualifying_surviving_spouse' may appear too (it uses the MFJ column, so
    # it is an alias in the calc data but a real, distinct row on Chart A).
    amounts: dict[str, dict[str, int]]

    @model_validator(mode="after")
    def _check_statuses(self) -> "FilingThresholds":
        missing = [s for s in FILING_STATUSES if s not in self.amounts]
        if missing:
            raise ValueError(f"filing_thresholds.amounts must cover all statuses; missing: {', '.join(missing)}")
        return self


class CheckPayment(BaseModel):
    """How to pay by check/money order (payee + memo line), per the 1040 instructions."""

    model_config = ConfigDict(extra="forbid")

    payee: str = Field(description="Exact payee — the 2023 instructions say 'United States Treasury'.")
    memo: str = Field(description="What to write on the payment (tax year + form + name/SSN; attach Form 1040-V).")


class ElectronicPayment(BaseModel):
    """One electronic payment channel."""

    model_config = ConfigDict(extra="allow")

    name: str
    fee: bool = Field(description="Whether the channel charges a processing fee (card processors do; Direct Pay/EFTPS do not).")
    url: str


class PaymentOptions(BaseModel):
    """Federal payment channels for a balance due (dev plan section 9)."""

    model_config = ConfigDict(extra="allow")

    citation: Citation
    check: CheckPayment
    electronic: list[ElectronicPayment]


class StateMailingGroup(BaseModel):
    """One where-to-file row: a set of states and their two addresses."""

    model_config = ConfigDict(extra="allow")

    states: list[str]
    no_payment: str = Field(description="Address when requesting a refund / not enclosing payment.")
    with_payment: str = Field(description="Address when enclosing a check or money order.")


class MailingAddressPair(BaseModel):
    """A fixed (non-state-dependent) no-payment / with-payment address pair."""

    model_config = ConfigDict(extra="forbid")

    no_payment: str
    with_payment: str


class MailingAddresses(BaseModel):
    """Where to file paper returns — 1040 is state-dependent, 1040-NR is fixed."""

    model_config = ConfigDict(extra="allow")

    citation: Citation
    f1040_groups: list[StateMailingGroup]
    f1040nr: MailingAddressPair

    def f1040_for_state(self, state: str) -> MailingAddressPair:
        """Resolve the 1040 address pair for a state name (case-insensitive)."""
        want = state.strip().casefold()
        for group in self.f1040_groups:
            if any(s.casefold() == want for s in group.states):
                return MailingAddressPair(no_payment=group.no_payment, with_payment=group.with_payment)
        raise KeyError(
            f"no where-to-file group lists state {state!r} — check the spelling (full state name, "
            f"e.g. 'California'), or use the foreign/territory row"
        )


class RefundStatuteOfLimitations(BaseModel):
    """IRC 6511(a): claim a refund within the later of 3 years of filing / 2 of payment."""

    model_config = ConfigDict(extra="allow")

    years_from_filing: int = Field(gt=0)
    years_from_payment: int = Field(gt=0)
    authority: str


class Deadlines(BaseModel):
    """Filing due dates and the refund statute of limitations for the year."""

    model_config = ConfigDict(extra="allow")

    citation: Citation
    filing_due_date: str = Field(description="ISO date the return is due (e.g. '2024-04-15' for tax year 2023).")
    refund_statute_of_limitations: RefundStatuteOfLimitations


class Credits(BaseModel):
    """Common credits with their parameters/eligibility (CTC, EITC, ...).

    Inner structures are rich and grow per credit, so they are kept open
    (``extra='allow'``) — the citation requirement is the firm contract.
    """

    model_config = ConfigDict(extra="allow")

    citation: Citation


class EffectiveLawChange(BaseModel):
    """One enacted-law delta relevant to the filing year (dev plan section 7(2)).

    Each entry MUST carry a citation (to the enacting public law / official
    guidance) and a status tracking how far the change has matured:
    ``enacted`` (law passed) -> ``irs_guidance_pending`` (no final IRS numbers
    yet) -> ``final_form_published`` (figures are final and citeable).

    Numbers without final IRS guidance are NEVER hardcoded; for a not-yet-final
    figure the entry records ``lookup_path`` (the sources.yaml by_topic key /
    URL to resolve it from) instead of a value — so the pack stores the lookup
    path, not an invented number.
    """

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What changed (e.g. 'OBBBA car-loan interest deduction, effective 2025').")
    citation: Citation
    status: Literal["enacted", "irs_guidance_pending", "final_form_published"] = Field(
        description="Maturity of the change: enacted -> irs_guidance_pending -> final_form_published."
    )
    lookup_path: str | None = Field(
        default=None,
        description="For a figure not yet final: the sources.yaml by_topic key / .gov URL to resolve it from "
        "(never a hardcoded number). Required while status is not final_form_published if a figure is needed.",
    )
    source_topic: str | None = Field(
        default=None, description="Optional sources.yaml by_topic key this change feeds into."
    )


class KnowledgePack(BaseModel):
    """One ``knowledge/<jurisdiction>/<year>.yaml`` file, validated.

    The ``tax`` block (M1) is required; the M3 filing-logistics blocks are
    optional so a year can ship calc data before its logistics data.
    """

    model_config = ConfigDict(extra="allow")

    jurisdiction: str
    tax_year: int = Field(ge=1990, le=2100)
    tax: TaxKnowledge
    filing_thresholds: FilingThresholds | None = None
    payment_options: PaymentOptions | None = None
    mailing_addresses: MailingAddresses | None = None
    deadlines: Deadlines | None = None
    credits: Credits | None = None
    effective_law_changes: list[EffectiveLawChange] = Field(default_factory=list)

    @field_validator("jurisdiction")
    @classmethod
    def _check_jurisdiction(cls, value: str) -> str:
        if not _JURISDICTION_RE.fullmatch(value):
            raise ValueError(
                f"jurisdiction must be 'federal' or 'states/<two-letter lowercase code>' "
                f"(e.g. 'states/ca'), got {value!r}"
            )
        return value


def load_knowledge(
    jurisdiction: str,
    year: int,
    base_dir: str | Path | None = None,
) -> KnowledgePack:
    """Load and validate ``<base_dir>/<jurisdiction>/<year>.yaml``.

    ``base_dir`` defaults to the repo's ``knowledge/`` directory (resolved
    relative to this source file, which assumes a source checkout — pass
    ``base_dir`` explicitly when running from an installed wheel).

    Raises:
        ValueError: bad jurisdiction string, non-mapping YAML, or a pack
            whose declared jurisdiction/tax_year disagrees with its path.
        FileNotFoundError: missing base directory or missing pack, with the
            exact path looked for and the freshness protocol to follow.
        pydantic.ValidationError: the pack violates the schema.
    """
    if not _JURISDICTION_RE.fullmatch(jurisdiction):
        raise ValueError(
            f"jurisdiction must be 'federal' or 'states/<two-letter lowercase code>' "
            f"(e.g. 'states/ca'), got {jurisdiction!r}"
        )
    base = Path(base_dir) if base_dir is not None else _repo_knowledge_dir()
    if not base.is_dir():
        raise FileNotFoundError(
            f"knowledge base directory not found: {base} — pass base_dir=<path to the repo's knowledge/ "
            f"directory> (the default only works from a source checkout of taxfill-mcp)"
        )
    path = base / jurisdiction / f"{year}.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"no knowledge pack for jurisdiction '{jurisdiction}', tax year {year} — looked for {path}. "
            f"If this year should be supported, author that file (copy the schema of knowledge/federal/2023.yaml). "
            f"For a year newer than the newest shipped pack, follow the freshness protocol "
            f"(docs/DEV_PLAN.md section 7): resolve every number from the official sources listed in "
            f"knowledge/sources.yaml (irs.gov only) and cite each block — never fill a line whose authority "
            f"you cannot cite."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: a knowledge pack must be a YAML mapping (key: value pairs), got "
            f"{type(raw).__name__} — see knowledge/federal/2023.yaml for the schema"
        )
    pack = KnowledgePack.model_validate(raw)
    if pack.jurisdiction != jurisdiction or pack.tax_year != year:
        raise ValueError(
            f"{path}: file declares jurisdiction '{pack.jurisdiction}', tax_year {pack.tax_year} but was "
            f"loaded as jurisdiction '{jurisdiction}', year {year} — fix the file's jurisdiction/tax_year "
            f"fields or move the file to knowledge/{pack.jurisdiction}/{pack.tax_year}.yaml"
        )
    return pack


# ── State knowledge (dev plan section 6) ─────────────────────────────────────


class StateKnowledge(BaseModel):
    """One ``knowledge/states/<st>/<year>.yaml`` — a state's filing knowledge.

    Unlike the federal :class:`KnowledgePack`, a state pack has NO mandatory
    ``tax`` computation block (state tax math is not computed in v1 — scoping,
    rules, credits, and logistics are). Extra cited blocks (residency, credits,
    mailing_addresses, payment, deadlines, filing_requirement, forms) are
    allowed and grow per state.

    The one firm, typed contract is ``conforms_to_federal_treaties`` — California
    does NOT, so a treaty-exempt-federally amount is still taxable to CA, which
    must never be silently assumed.
    """

    model_config = ConfigDict(extra="allow")

    jurisdiction: str
    tax_year: int = Field(ge=1990, le=2100)
    income_tax: bool = Field(default=True, description="Whether the state levies a broad personal income tax.")
    conforms_to_federal_treaties: bool = Field(
        description="False means federal treaty-exempt income is still taxable by this state (e.g. California)."
    )
    citation: Citation | None = None

    @field_validator("jurisdiction")
    @classmethod
    def _check_state_jurisdiction(cls, value: str) -> str:
        if not value.startswith("states/") or not _JURISDICTION_RE.fullmatch(value):
            raise ValueError(
                f"state knowledge jurisdiction must be 'states/<two-letter lowercase code>' (e.g. 'states/ca'), got {value!r}"
            )
        return value


def load_state_knowledge(
    state: str,
    year: int,
    base_dir: str | Path | None = None,
) -> StateKnowledge:
    """Load ``<base_dir>/states/<state>/<year>.yaml`` as a :class:`StateKnowledge`.

    Args:
        state: two-letter lowercase code, e.g. ``'ca'``.
        year: tax year.
        base_dir: defaults to the repo's ``knowledge/`` directory.

    Raises:
        ValueError: bad state code or a pack whose declared jurisdiction/year
            disagrees with its path.
        FileNotFoundError: no pack for that state/year (lists the freshness path).
    """
    state = state.lower()
    if not re.fullmatch(r"[a-z]{2}", state):
        raise ValueError(f"state must be a two-letter lowercase code (e.g. 'ca'), got {state!r}")
    base = Path(base_dir) if base_dir is not None else _repo_knowledge_dir()
    path = base / "states" / state / f"{year}.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"no state knowledge pack for '{state}', tax year {year} — looked for {path}. "
            f"State packs ship per dev plan section 6 (CA first); resolve any figure from the state DOR "
            f"(.gov) and cite it — never invent a state rule or amount."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: a state knowledge pack must be a YAML mapping, got {type(raw).__name__}")
    pack = StateKnowledge.model_validate(raw)
    if pack.jurisdiction != f"states/{state}" or pack.tax_year != year:
        raise ValueError(
            f"{path}: file declares jurisdiction '{pack.jurisdiction}', tax_year {pack.tax_year} but was loaded "
            f"as state '{state}', year {year} — fix the file or move it to knowledge/states/{state}/{year}.yaml"
        )
    return pack
