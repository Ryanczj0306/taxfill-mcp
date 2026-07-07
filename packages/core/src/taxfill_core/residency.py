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

* **Green card test** — a lawful permanent resident at any time during the
  calendar year is a resident for tax purposes regardless of the SPT.
  https://www.irs.gov/individuals/international-taxpayers/alien-residency-green-card-test

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

# When the weighted total falls short of 183 but lands at or above this
# value, the nonresident result reminds the user to recount days and that
# the closer-connection exception exists (dev plan: the engine flags, the
# agent + user decide). 165 weighted days ~= within 10% of the threshold.
_NEAR_183_WEIGHTED = 165

# F and M visas are always students for the exempt-individual rules.
_FM_STATUS_RE = re.compile(r"^[fm](?:\d|\b)")
# J and Q visas split into students vs teachers/trainees by program category.
_JQ_STATUS_RE = re.compile(r"^[jq](?:\d|\b)")
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
                f"{where} = {value!r} is not an ISO date — use 'YYYY-MM-DD' (e.g. '2019-08-20')"
            ) from None
    raise ValueError(
        f"{where} must be a datetime.date or an ISO 'YYYY-MM-DD' string, got {type(value).__name__}"
    )


def is_exempt_category_status(status: str) -> bool:
    """True when ``status`` is an F/J/M/Q exempt-category visa string (IRS Pub. 519).

    Unlike the strict categorizer this never raises: a bare ``"J-1"`` (ambiguous
    between student and teacher/trainee limits) still returns True — either way
    its calendar years need day counts before :func:`classify` can run.
    """
    normalized = " ".join(status.lower().split())
    return bool(_FM_STATUS_RE.match(normalized) or _JQ_STATUS_RE.match(normalized))


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
    return None


def _pick(raw: Any, key: str) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(key)
    return getattr(raw, key, None)


def _normalize_periods(visa_periods: Any) -> list[_Period]:
    if isinstance(visa_periods, (str, bytes)) or not isinstance(visa_periods, Iterable):
        raise ValueError(
            f"visa_periods must be a list of periods shaped like "
            f"{{'status': 'F-1', 'start': date(2019, 8, 20), 'end': None}} — got {type(visa_periods).__name__}"
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
    """
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
        if triggers:
            classification = "dual_status_candidate"
            reasons.append(
                f"The substantial presence test is met for {year}, but {year} looks like a SPLIT year: you "
                f"were likely a nonresident for the early part of {year} and a resident from your residency "
                f"starting date (generally the first day you were present in the US not as an exempt "
                f"individual — IRS Pub. 519, 'Residency starting and ending dates'). This is a flag, not a "
                f"determination — you and your agent decide. Note: if you were also a US resident during "
                f"any part of {year - 1}, you are a resident from January 1 of {year} instead."
            )
            reasons.extend(triggers)
            citations.append(CITATION_RESIDENCY_DATES)
        else:
            classification = "resident"
            reasons.append(
                f"Substantial presence test met for {year}: at least 31 days present in {year} and the "
                f"weighted 3-year total ({spt.weighted_days_exact}) is at least 183 (IRS Pub. 519)."
            )
            # A mid-year category change in a NON-exempt target year does not
            # split the year (the earlier status' days already counted), so it
            # was not flagged as a dual-status trigger — explain why instead.
            for previous, current in _mid_year_category_changes(periods, year):
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
                reasons.insert(
                    0,
                    f"IMPORTANT — this nonresident result may be WRONG: {base}. You were present "
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
                reasons.append(
                    f"Note: {base}. Even the maximum possible presence in {yl} could not bring the "
                    f"weighted total to 183, so this nonresident result stands — still, {provide} for a "
                    f"complete record (IRS Pub. 519)."
                )
        else:
            reasons.append(
                f"Note: {base}. A {classification.replace('_', '-')} conclusion is safe on that score "
                f"(more presence days only push toward residency), but {provide} for a complete record "
                f"(IRS Pub. 519)."
            )

    return ClassificationResult(
        target_year=year,
        classification=classification,
        reasons=reasons,
        inputs={
            "visa_periods": _serialize_periods(periods),
            "days_by_year": days,
            "target_year": year,
            "is_lawful_permanent_resident": is_lawful_permanent_resident,
        },
        work="\n".join(work_lines),
        citations=_dedup_citations(citations),
        spt=spt,
        exempt_years=exempt,
        is_lawful_permanent_resident=is_lawful_permanent_resident,
    )
