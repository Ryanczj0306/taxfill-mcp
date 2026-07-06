"""Document extraction — dev plan section 2 ("extract & confirm"), section 8 tool.

The agent reads a tax document (W-2, 1099, 1098-T, 1042-S, …) with its own vision
and passes the box→value reading here. This module does NOT do OCR; it is the
*structuring + validation* half of "extract & confirm":

* it knows the official box layout of each supported document (cited to the form
  on irs.gov), so it can label, type-check, and order the agent's reading;
* it attaches per-field **provenance** (the source file + page) to every value;
* it never invents a value — a box the agent did not read stays ``None`` and is
  reported as a gap; a value that fails its type is surfaced as ``invalid``, not
  silently dropped;
* it returns a confirm-table the user reviews before any figure is used.

The hard rule from section 2 is preserved end to end: *missing means blank, never
guessed.* The box layouts encoded here are the documented structure of the
official forms (not dollar amounts) and each spec cites its irs.gov form page.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.schemas.profile import Provenance

__all__ = [
    "FieldType",
    "BoxSpec",
    "DocSpec",
    "DOC_SPECS",
    "ExtractedField",
    "ExtractedDocument",
    "list_document_kinds",
    "extract_document",
]

FieldType = Literal["money", "int", "text", "code", "ein", "ssn", "tin", "state", "checkbox"]


class BoxSpec(BaseModel):
    """One documented box on an official form."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable box identifier, e.g. '1' or '12a' or 'employee_ssn'.")
    label: str = Field(description="Human label as printed on the form.")
    type: FieldType = "text"
    required: bool = Field(default=False, description="True for the boxes a return almost always needs from this doc.")


class DocSpec(BaseModel):
    """A supported document type: its title, its citation, and its box layout."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str
    source_url: str = Field(description="Official .gov page documenting this form's layout.")
    boxes: list[BoxSpec]


def _b(key: str, label: str, type_: FieldType = "text", required: bool = False) -> BoxSpec:
    return BoxSpec(key=key, label=label, type=type_, required=required)


# ── Supported documents (box layout cited to the official irs.gov form page) ──
# Only the broadly-needed boxes are modelled; the agent may still pass others
# (they surface under `unexpected`), and more docs can be added the same way.
_SPECS: list[DocSpec] = [
    DocSpec(
        kind="W-2",
        title="Wage and Tax Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-w-2",
        boxes=[
            _b("employee_ssn", "Box a — Employee's SSN", "ssn", required=True),
            _b("employer_ein", "Box b — Employer EIN", "ein", required=True),
            _b("employer_name", "Box c — Employer name/address", "text"),
            _b("employee_name", "Box e — Employee name", "text"),
            _b("1", "Box 1 — Wages, tips, other compensation", "money", required=True),
            _b("2", "Box 2 — Federal income tax withheld", "money", required=True),
            _b("3", "Box 3 — Social Security wages", "money"),
            _b("4", "Box 4 — Social Security tax withheld", "money"),
            _b("5", "Box 5 — Medicare wages and tips", "money"),
            _b("6", "Box 6 — Medicare tax withheld", "money"),
            _b("7", "Box 7 — Social Security tips", "money"),
            _b("10", "Box 10 — Dependent care benefits", "money"),
            _b("11", "Box 11 — Nonqualified plans", "money"),
            _b("12a", "Box 12a — Code/amount", "code"),
            _b("12b", "Box 12b — Code/amount", "code"),
            _b("12c", "Box 12c — Code/amount", "code"),
            _b("12d", "Box 12d — Code/amount", "code"),
            _b("13_statutory", "Box 13 — Statutory employee", "checkbox"),
            _b("13_retirement", "Box 13 — Retirement plan", "checkbox"),
            _b("13_sick_pay", "Box 13 — Third-party sick pay", "checkbox"),
            _b("15_state", "Box 15 — State", "state"),
            _b("16", "Box 16 — State wages, tips, etc.", "money"),
            _b("17", "Box 17 — State income tax", "money"),
            _b("18", "Box 18 — Local wages, tips, etc.", "money"),
            _b("19", "Box 19 — Local income tax", "money"),
            _b("20", "Box 20 — Locality name", "text"),
        ],
    ),
    DocSpec(
        kind="1099-NEC",
        title="Nonemployee Compensation",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-nec",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("payer_name", "Payer's name/address", "text"),
            _b("1", "Box 1 — Nonemployee compensation", "money", required=True),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("5", "Box 5 — State tax withheld", "money"),
            _b("6", "Box 6 — State/Payer's state no.", "text"),
            _b("7", "Box 7 — State income", "money"),
        ],
    ),
    DocSpec(
        kind="1099-INT",
        title="Interest Income",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-int",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1", "Box 1 — Interest income", "money", required=True),
            _b("2", "Box 2 — Early withdrawal penalty", "money"),
            _b("3", "Box 3 — Interest on U.S. Savings Bonds and Treasury obligations", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("8", "Box 8 — Tax-exempt interest", "money"),
        ],
    ),
    DocSpec(
        kind="1099-DIV",
        title="Dividends and Distributions",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-div",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1a", "Box 1a — Total ordinary dividends", "money", required=True),
            _b("1b", "Box 1b — Qualified dividends", "money"),
            _b("2a", "Box 2a — Total capital gain distr.", "money"),
            _b("3", "Box 3 — Nondividend distributions", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("7", "Box 7 — Foreign tax paid", "money"),
        ],
    ),
    DocSpec(
        kind="1099-G",
        title="Certain Government Payments",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-g",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("1", "Box 1 — Unemployment compensation", "money"),
            _b("2", "Box 2 — State or local income tax refunds/credits/offsets", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("11", "Box 11 — State income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1099-MISC",
        title="Miscellaneous Information",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-misc",
        boxes=[
            _b("payer_name", "Payer's name", "text"),
            _b("recipient_tin", "Recipient's TIN", "tin"),
            _b("1", "Box 1 — Rents", "money"),
            _b("2", "Box 2 — Royalties", "money"),
            _b("3", "Box 3 — Other income", "money"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1098-T",
        title="Tuition Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1098-t",
        boxes=[
            _b("filer_name", "Filer's name (school)", "text"),
            _b("student_tin", "Student's TIN", "tin"),
            _b("1", "Box 1 — Payments received for qualified tuition and related expenses", "money", required=True),
            _b("4", "Box 4 — Adjustments made for a prior year", "money"),
            _b("5", "Box 5 — Scholarships or grants", "money"),
            _b("7", "Box 7 — Checkbox: amounts for an academic period beginning Jan–Mar next year", "checkbox"),
        ],
    ),
    DocSpec(
        kind="1098-E",
        title="Student Loan Interest Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1098-e",
        boxes=[
            _b("lender_name", "Lender's name", "text"),
            _b("borrower_tin", "Borrower's TIN", "tin"),
            _b("1", "Box 1 — Student loan interest received by lender", "money", required=True),
        ],
    ),
    DocSpec(
        # NRA-critical: how treaty-exempt income and its withholding are reported.
        kind="1042-S",
        title="Foreign Person's U.S. Source Income Subject to Withholding",
        source_url="https://www.irs.gov/forms-pubs/about-form-1042-s",
        boxes=[
            _b("1", "Box 1 — Income code", "code", required=True),
            _b("2", "Box 2 — Gross income", "money", required=True),
            _b("3a", "Box 3a — Exemption code (chapter 3)", "code"),
            _b("3b", "Box 3b — Tax rate (chapter 3)", "text"),
            _b("4a", "Box 4a — Exemption code (chapter 4)", "code"),
            _b("7a", "Box 7a — Federal tax withheld", "money"),
            _b("12a", "Box 12a — Withholding agent's EIN", "ein"),
            _b("13b", "Box 13b — Recipient's U.S. TIN", "tin"),
            _b("13l", "Box 13l — Recipient's country code", "text"),
        ],
    ),
    DocSpec(
        kind="SSA-1099",
        title="Social Security Benefit Statement",
        source_url="https://www.ssa.gov/manage-benefits/get-tax-form-10991042s",
        boxes=[
            _b("2", "Box 2 — Beneficiary's Social Security number", "ssn", required=True),
            _b("3", "Box 3 — Benefits paid in the year", "money"),
            _b("4", "Box 4 — Benefits repaid to SSA in the year", "money"),
            _b("5", "Box 5 — Net benefits (box 3 minus box 4)", "money", required=True),
            _b("6", "Box 6 — Voluntary federal income tax withheld", "money"),
        ],
    ),
    DocSpec(
        kind="1099-R",
        title="Distributions From Pensions, Annuities, Retirement or Profit-Sharing Plans, IRAs, etc.",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-r",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("1", "Box 1 — Gross distribution", "money", required=True),
            _b("2a", "Box 2a — Taxable amount", "money"),
            _b("2b_not_determined", "Box 2b — Taxable amount not determined", "checkbox"),
            _b("2b_total_distribution", "Box 2b — Total distribution", "checkbox"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("7", "Box 7 — Distribution code(s)", "code", required=True),
            _b("7_ira_sep_simple", "Box 7 — IRA/SEP/SIMPLE", "checkbox"),
        ],
    ),
    DocSpec(
        kind="1099-B",
        title="Proceeds From Broker and Barter Exchange Transactions",
        source_url="https://www.irs.gov/forms-pubs/about-form-1099-b",
        boxes=[
            _b("payer_tin", "Payer's TIN", "tin"),
            _b("recipient_tin", "Recipient's TIN", "tin", required=True),
            _b("1a", "Box 1a — Description of property", "text"),
            _b("1b", "Box 1b — Date acquired", "text"),
            _b("1c", "Box 1c — Date sold or disposed", "text"),
            _b("1d", "Box 1d — Proceeds", "money", required=True),
            _b("1e", "Box 1e — Cost or other basis", "money"),
            _b("1g", "Box 1g — Wash sale loss disallowed", "money"),
            _b("2_short_term", "Box 2 — Short-term gain or loss", "checkbox"),
            _b("2_long_term", "Box 2 — Long-term gain or loss", "checkbox"),
            _b("4", "Box 4 — Federal income tax withheld", "money"),
            _b("5", "Box 5 — Noncovered security", "checkbox"),
        ],
    ),
    DocSpec(
        kind="1095-A",
        title="Health Insurance Marketplace Statement",
        source_url="https://www.irs.gov/forms-pubs/about-form-1095-a",
        boxes=[
            _b("marketplace_state", "Part I line 1 — Marketplace state", "state"),
            _b("policy_number", "Part I line 2 — Marketplace-assigned policy number", "text"),
            # Part III monthly rows (lines 21-32), columns A (premium) / B (SLCSP) / C (APTC).
            *[
                _b(f"{line}{col}", f"Part III line {line}{col.upper()} — {month} {label}", "money")
                for line, month in zip(
                    range(21, 33),
                    ("January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December"),
                )
                for col, label in (
                    ("a", "monthly enrollment premium"),
                    ("b", "SLCSP premium"),
                    ("c", "advance payment of PTC"),
                )
            ],
            _b("33a", "Line 33A — Annual premium total", "money", required=True),
            _b("33b", "Line 33B — Annual SLCSP premium total", "money", required=True),
            _b("33c", "Line 33C — Annual advance PTC total", "money", required=True),
        ],
    ),
]

DOC_SPECS: dict[str, DocSpec] = {s.kind: s for s in _SPECS}


class ExtractedField(BaseModel):
    """One box after structuring: typed value (or None), status, and provenance."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: FieldType
    value: Any = Field(default=None, description="Coerced value, or None when the box was not read.")
    raw: Any = Field(default=None, description="The exact reading the agent passed, before coercion.")
    status: Literal["ok", "missing", "invalid"] = "ok"
    provenance: Provenance


class ExtractedDocument(BaseModel):
    """A structured, provenance-tagged document reading for the confirm step."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    file: str
    page: int | None = None
    title: str
    citation: dict[str, str]
    fields: list[ExtractedField]
    gaps: list[str] = Field(default_factory=list, description="Required boxes not read (or read as invalid).")
    unexpected: list[str] = Field(default_factory=list, description="Keys the agent passed that aren't on this form.")
    caveat: str


_MONEY_RE = re.compile(r"[,$\s]")
_DIGITS_RE = re.compile(r"\D")


def _coerce(value: Any, type_: FieldType) -> tuple[Any, bool]:
    """Coerce a raw reading to its type. Returns (coerced, ok). Empty → (None, True)."""
    if value is None:
        return None, True
    if isinstance(value, str) and value.strip() == "":
        return None, True
    try:
        if type_ == "money":
            cleaned = _MONEY_RE.sub("", str(value))
            if cleaned in ("", "-", "+"):
                # A non-blank reading that is only currency punctuation ("-", "$", ",")
                # is a misread, not an empty box — flag invalid so it can't masquerade
                # as a confirmed blank and slip past the required-gap check.
                return value, False
            return str(Decimal(cleaned)), True
        if type_ == "int":
            cleaned = _MONEY_RE.sub("", str(value))
            if cleaned in ("", "-", "+"):
                return value, False
            dec = Decimal(cleaned)
            if dec != dec.to_integral_value():
                return value, False  # a fractional reading of an int box is a misread, not a truncation
            return int(dec), True
        if type_ in ("ein", "ssn", "tin"):
            digits = _DIGITS_RE.sub("", str(value))
            if type_ == "ssn" and len(digits) != 9:
                return str(value), False
            if type_ == "ein" and len(digits) != 9:
                return str(value), False
            if type_ == "tin" and len(digits) != 9:
                return str(value), False
            if type_ == "ein":
                return f"{digits[:2]}-{digits[2:]}", True
            return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}", True
        if type_ == "state":
            s = str(value).strip().upper()
            return s, len(s) == 2 and s.isalpha()
        if type_ == "checkbox":
            token = str(value).strip().lower()
            if token in ("x", "true", "yes", "y", "1", "checked", "on"):
                return True, True
            if token in ("false", "no", "n", "0", "off", "unchecked", "blank"):
                return False, True
            # An unrecognized reading is NOT silently treated as unchecked — that
            # would assert a value the agent never read. Surface it as invalid.
            return value, False
        return str(value), True
    except (InvalidOperation, ValueError):
        return value, False


def list_document_kinds() -> list[dict[str, Any]]:
    """The supported document kinds and their box layouts (for the agent to fill)."""
    return [
        {
            "kind": s.kind,
            "title": s.title,
            "source_url": s.source_url,
            "boxes": [{"key": b.key, "label": b.label, "type": b.type, "required": b.required} for b in s.boxes],
        }
        for s in _SPECS
    ]


def extract_document(
    path: str,
    kind: str,
    fields: dict[str, Any],
    page: int | None = None,
) -> ExtractedDocument:
    """Structure + validate an agent's reading of one tax document.

    Args:
        path: workspace-relative path to the source document (becomes provenance).
        kind: one of :data:`DOC_SPECS` (e.g. ``"W-2"``, ``"1099-INT"``, ``"1042-S"``).
        fields: the agent's box→reading map (box key → value); omit / None = not read.
        page: 1-based page of the document the reading came from, when known.

    Returns:
        An :class:`ExtractedDocument`: every documented box, typed and tagged with
        ``document`` provenance, plus the gaps (required boxes not read) and any
        unexpected keys. Nothing is inferred — unread boxes are ``None``.

    Raises:
        ValueError: if ``kind`` is not a supported document type.
    """
    spec = DOC_SPECS.get(kind)
    if spec is None:
        raise ValueError(
            f"unsupported document kind {kind!r}; supported: {sorted(DOC_SPECS)}. "
            "Use list_document_kinds() for each form's box layout."
        )
    if page is not None and page < 1:
        raise ValueError("page must be a 1-based page number (>= 1), or None when unknown")
    fields = fields or {}
    prov = Provenance.document(file=path, page=page)
    out_fields: list[ExtractedField] = []
    gaps: list[str] = []
    known_keys = {b.key for b in spec.boxes}

    for box in spec.boxes:
        raw = fields.get(box.key)
        coerced, ok = _coerce(raw, box.type)
        if coerced is None and (raw is None or (isinstance(raw, str) and raw.strip() == "")):
            status = "missing"
        elif not ok:
            status = "invalid"
        else:
            status = "ok"
        out_fields.append(
            ExtractedField(key=box.key, label=box.label, type=box.type, value=coerced, raw=raw, status=status, provenance=prov)
        )
        if box.required and status != "ok":
            gaps.append(box.key)

    unexpected = sorted(k for k in fields if k not in known_keys)
    caveat = (
        "Extraction structures what was read from the document — confirm every value against the "
        "paper form before it is used. Boxes not read are blank (None), never inferred; a value shown "
        "as 'invalid' did not match the expected type and must be corrected; required boxes that are "
        "blank are listed in 'gaps'."
    )
    return ExtractedDocument(
        kind=spec.kind,
        file=path,
        page=page,
        title=spec.title,
        citation={"source": spec.title + " (box layout)", "url": spec.source_url},
        fields=out_fields,
        gaps=gaps,
        unexpected=unexpected,
        caveat=caveat,
    )
