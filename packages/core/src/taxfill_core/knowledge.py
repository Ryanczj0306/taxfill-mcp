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

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """Default pack location: ``<repo root>/knowledge`` in a source checkout."""
    return Path(__file__).resolve().parents[4] / "knowledge"


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
    def _url_is_http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError(
                "citation.url must be the full official document URL starting with https:// "
                "(knowledge data is cited to .gov sources only — see knowledge/sources.yaml)"
            )
        return value


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


class KnowledgePack(BaseModel):
    """One ``knowledge/<jurisdiction>/<year>.yaml`` file, validated.

    Extra top-level blocks are allowed: M3 adds filing thresholds, payment
    options, mailing addresses, sources, and effective_law_changes.
    """

    model_config = ConfigDict(extra="allow")

    jurisdiction: str
    tax_year: int = Field(ge=1990, le=2100)
    tax: TaxKnowledge

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
