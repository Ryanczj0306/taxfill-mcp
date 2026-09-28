"""Form Pack schema — the ``pack.yaml`` spec from dev plan section 5.

A *form pack* is versioned DATA describing one tax form for one jurisdiction
and one tax year: the AcroForm line-to-field map, math relations enforced by
the verifier, cross-form consistency rules, identity fields that must match
across the whole filing, signature placement, and official mailing addresses.

Key principle (dev plan section 3): the engine is jurisdiction- and
form-agnostic. Federal and state forms use this same schema; coverage grows
by adding packs under ``formpacks/``, never by changing engine code.

Blank PDFs are downloaded at runtime from the official ``source_url`` and
verified against ``pdf_sha256`` — never vendored in the repo.

Validation errors are intentionally prescriptive (dev plan section 11):
every failure tells the pack author exactly what to fix.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The three field types the filler knows how to write (dev plan section 5).
FieldType = Literal["text", "checkbox", "money"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JURISDICTION_RE = re.compile(r"^(federal|states/[a-z]{2})$")
_SHA256_PLACEHOLDER = "..."  # authoring placeholder; fetch_blank refuses to verify against it


def _require_http_url(value: str, key: str) -> str:
    if not value.startswith(("https://", "http://")):
        raise ValueError(
            f"{key} must be a full official URL starting with https:// "
            f"(blank forms and verify pages come from .gov sites only)"
        )
    return value


class PackField(BaseModel):
    """One line of the form mapped to one AcroForm field."""

    model_config = ConfigDict(extra="forbid")

    line: str = Field(description="Logical line key, e.g. '1a', 'identifying_number', 'filing_status.single'.")
    field: str = Field(description="AcroForm field name relative to acroform_root, e.g. 'Page1[0].f1_7[0]'.")
    type: FieldType
    maxlen: int | None = Field(default=None, ge=1, description="Maximum characters (e.g. comb cell count).")
    comb: bool = Field(default=False, description="True for comb fields (one character per cell).")
    format: str | None = Field(
        default=None,
        description="Input normalization hint for the filler, e.g. 'ssn_digits_only' (dashes overflow comb cells).",
    )
    on_state: str | None = Field(
        default=None,
        description="Checkbox export value to set, e.g. '/1' (pypdf needs both /V and widget /AS).",
    )
    required: bool = Field(
        default=False,
        description=(
            "True when the line must be answered on every filing; drives the "
            "unanswered-required checkbox audit (pitfall P-003)."
        ),
    )
    reserved: bool = Field(
        default=False,
        description=(
            "True for a printed 'Reserved for future use' row kept mapped so a relation can name it (the "
            "RESERVED_LINE_KEEPS table): fill_form warns when a value lands on it and audit_pack skips it (JEa)."
        ),
    )
    group: str | None = Field(
        default=None,
        description=(
            "Checkbox group id — the yes/no boxes of one question share a group "
            "(e.g. 'line12'); a required group must have at least one member "
            "checked. Valid on checkbox fields only."
        ),
    )

    @model_validator(mode="after")
    def _check_options_match_type(self) -> "PackField":
        if self.type == "checkbox":
            if self.on_state is None:
                raise ValueError(
                    f"field '{self.line}': checkbox fields require 'on_state' "
                    f"(the PDF export value, e.g. \"/1\") — dump the blank PDF's "
                    f"field states to find it"
                )
            if self.comb or self.maxlen is not None or self.format is not None:
                raise ValueError(
                    f"field '{self.line}': 'maxlen', 'comb' and 'format' apply only to "
                    f"text and money fields — remove them from this checkbox"
                )
        else:
            if self.on_state is not None:
                raise ValueError(
                    f"field '{self.line}': 'on_state' applies only to checkbox fields — "
                    f"remove it or change the field type to checkbox"
                )
            if self.group is not None:
                raise ValueError(
                    f"field '{self.line}': 'group' applies only to checkbox fields "
                    f"(the yes/no boxes of one question share a group id) — "
                    f"remove it or change the field type to checkbox"
                )
            if self.comb and self.maxlen is None:
                raise ValueError(
                    f"field '{self.line}': comb fields require 'maxlen' "
                    f"(the number of comb cells) so the clipping scan can catch overflow"
                )
        return self


class Signature(BaseModel):
    """Where the human signs (dev plan section 9: exact signature locations)."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page number carrying the signature block.")
    standalone_only: bool = Field(
        default=False,
        description="True when the form is signed only if filed alone (e.g. Form 8843 attached to a 1040-NR is NOT separately signed).",
    )


class Mailing(BaseModel):
    """Official paper-filing addresses; this project is print-and-mail by design (no e-filing)."""

    model_config = ConfigDict(extra="forbid")

    no_payment: str = Field(description="Mailing address when no payment is enclosed.")
    with_payment: str = Field(description="Mailing address when a payment is enclosed.")
    verify_url: str = Field(
        description="Official where-to-file page to re-verify addresses before mailing (watched by the nightly drift job)."
    )

    @field_validator("verify_url")
    @classmethod
    def _verify_url_is_http(cls, value: str) -> str:
        return _require_http_url(value, "mailing.verify_url")


# JT0c: the forms whose own final revision makes a fill filing-grade in a provisional year, keyed
# (jurisdiction, form). The Form 1040-ES for a year posts final in its January (the 2026 revision is
# irs.gov/pub/irs-prior/f1040es--2026.pdf, Created 2/12/26) and its vouchers fall due during that year.
OWN_FINAL_REVISION_FORMS = frozenset({("federal", "1040-ES")})


class FormPack(BaseModel):
    """A complete ``pack.yaml`` for one form, one jurisdiction, one tax year."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. '1040-NR', '8843', '540NR'.")
    jurisdiction: str = Field(description="'federal' or 'states/<two-letter code>', e.g. 'states/ca'.")
    tax_year: int = Field(ge=1990, le=2100)
    source_url: str = Field(description="Official URL of the blank PDF (downloaded at runtime, never vendored).")
    mirror_urls: list[str] = Field(
        default_factory=list,
        description=(
            "Exact Wayback Machine snapshots of source_url (https://web.archive.org/web/<14-digit ts>id_/<source_url>), "
            "tried ONLY when the official host answers 401/403 and ALWAYS digest-verified against pdf_sha256 (Phase J "
            "JS1b: mass.gov refuses non-browser fetchers)."
        ),
    )
    pdf_sha256: str = Field(
        description="SHA-256 of the blank PDF for checksum verification; '...' is allowed only as an authoring placeholder."
    )
    acroform_root: str = Field(
        description="XFA-derived AcroForm root name; varies per form (e.g. 'topmostSubform[0]', Sched OI: 'form1040-NR[0]')."
    )
    source_status: Literal["final", "draft"] = Field(
        default="final",
        description=(
            "JT0a: 'draft' for a pack authored drafts-first against an irs.gov/pub/irs-dft/ form (the IRS "
            "cover sheet: \"there are never any changes to the last posted draft of the form and the final "
            "revision of the form\"); only a draft pack may use an irs-dft URL, and only in a provisional year."
        ),
    )
    draft_created: str | None = Field(
        default=None, description="The draft's footer stamp, e.g. '8/19/26' (\"Created 8/19/26\"); drafts only."
    )
    filing_grade_basis: Literal["year_knowledge", "own_final_revision"] = Field(
        default="year_knowledge",
        description=(
            "JT0c: what makes a fill of this pack filing-grade. 'year_knowledge' (every pack by default): the "
            "year's knowledge pack must not be provisional. 'own_final_revision': the form's own FINAL revision "
            "is the authority, so it fills in a provisional year. Allowlisted to the estimated-tax voucher "
            "(OWN_FINAL_REVISION_FORMS): the Form 1040-ES for the year in progress is final and due in that year "
            "(the 2026 Q4 voucher on 2027-01-15), long before the year's return forms are."
        ),
    )
    fields: list[PackField] = Field(min_length=1)
    relations: list[str] = Field(
        default_factory=list,
        description="Intra-form math relations enforced by the verifier, e.g. '1z == sum(1a..1h)'.",
    )
    cross_form: list[str] = Field(
        default_factory=list,
        description="Cross-form consistency rules, e.g. '1k == sched_oi.L1e'.",
    )
    identity_fields: list[str] = Field(
        default_factory=list,
        description="Lines that must match across every form in the filing (name, identifying number, address).",
    )
    identity_per_person: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of identity_fields whose value belongs to ONE PERSON rather than to the "
            "filing, so a difference across forms is legitimate rather than an error. Form 8889's "
            "box is printed 'Social security number of HSA beneficiary' and Form 8606's header is "
            "'If married, file a separate form for each spouse required to file' — on a joint "
            "return either can carry the SPOUSE's SSN while the 1040 carries the primary filer's. "
            "verify reports a difference on these as SKIPPED (visible, does not flip ok) with both "
            "values printed, instead of the FAIL that rejected every correct spouse-owned filing."
        ),
    )
    signature: Signature | None = Field(
        default=None,
        description="Omitted for attachment-only schedules that carry no signature block of their own.",
    )
    mailing: Mailing | None = Field(
        default=None,
        description="Omitted for schedules mailed inside a parent return's envelope.",
    )

    @field_validator("jurisdiction")
    @classmethod
    def _check_jurisdiction(cls, value: str) -> str:
        if not _JURISDICTION_RE.fullmatch(value):
            raise ValueError(
                f"jurisdiction must be 'federal' or 'states/<two-letter lowercase code>' "
                f"(e.g. 'states/ca'), got {value!r}"
            )
        return value

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, value: str) -> str:
        # source_url drives the only outbound fetch (see fetch.fetch_blank), so enforce the
        # official-government-host guarantee at load time too — shared rule with
        # knowledge.is_official_gov_host (.gov/.mil/*.state.<xx>.us; bare .us is an open
        # registry and is refused). Defence-in-depth alongside the fetch-time allowlist.
        from taxfill_core.knowledge import is_official_gov_host

        value = _require_http_url(value, "source_url")
        host = (urlparse(value).hostname or "").lower()
        if not is_official_gov_host(host):
            raise ValueError(
                f"source_url must point to an official US government host (.gov, .mil, or "
                f"*.state.<xx>.us), got {host!r} — blank forms are downloaded only from "
                f"official government sites"
            )
        return value

    @field_validator("pdf_sha256")
    @classmethod
    def _check_sha256(cls, value: str) -> str:
        if value == _SHA256_PLACEHOLDER:
            # Allowed while authoring a pack; fetch-time verification refuses
            # to download against a placeholder digest.
            return value
        if not _SHA256_RE.fullmatch(value.lower()):
            raise ValueError(
                "pdf_sha256 must be a 64-character hex SHA-256 digest of the blank PDF "
                "(or the literal '...' placeholder while authoring) — "
                "compute it with: shasum -a 256 blank.pdf"
            )
        return value.lower()

    @model_validator(mode="after")
    def _check_mirror_urls(self) -> "FormPack":
        for mirror in self.mirror_urls:
            match = re.fullmatch(r"https://web\.archive\.org/web/(\d{14})id_/(.+)", mirror)
            if match is None or match.group(2) != self.source_url:
                raise ValueError(
                    f"mirror_urls entry {mirror!r} must be an exact Wayback snapshot of THIS pack's source_url — "
                    f"https://web.archive.org/web/<14-digit timestamp>id_/{self.source_url}"
                )
        if self.mirror_urls and self.pdf_sha256 == _SHA256_PLACEHOLDER:
            raise ValueError("mirror_urls need a real pdf_sha256: a mirror is only ever used digest-verified")
        return self

    @model_validator(mode="after")
    def _check_draft_source(self) -> "FormPack":
        # JT0a: an irs-dft URL is a DRAFT form, so it needs the draft status and its footer stamp; a
        # final pack never points at a draft.
        is_dft = "/pub/irs-dft/" in self.source_url
        if self.source_status == "draft":
            if not self.draft_created:
                raise ValueError("a draft pack records draft_created — the 'Created <date>' stamp in the draft's footer")
        elif is_dft or self.draft_created:
            raise ValueError(
                "a final pack cannot use an irs.gov/pub/irs-dft/ source_url or carry draft_created — set "
                "source_status: draft (drafts-first authoring, docs/CONTRIBUTING-PACKS.md) or point at the final form"
            )
        return self

    @model_validator(mode="after")
    def _check_filing_grade_basis(self) -> "FormPack":
        if self.filing_grade_basis == "own_final_revision":
            if (self.jurisdiction, self.form) not in OWN_FINAL_REVISION_FORMS:
                raise ValueError(
                    f"filing_grade_basis: own_final_revision is allowlisted to {sorted(OWN_FINAL_REVISION_FORMS)}; "
                    f"{self.jurisdiction} {self.form} fills against its year's knowledge pack (year_knowledge)"
                )
            if self.source_status != "final" or "/pub/irs-prior/" not in self.source_url:
                raise ValueError(
                    "filing_grade_basis: own_final_revision rests on the form's FINAL revision — source_status final "
                    "and a source_url under irs.gov/pub/irs-prior/"
                )
        return self

    @model_validator(mode="after")
    def _check_unique_lines(self) -> "FormPack":
        seen: set[str] = set()
        for f in self.fields:
            if f.line in seen:
                raise ValueError(
                    f"duplicate line key '{f.line}' in fields[] — each logical line "
                    f"must map to exactly one AcroForm field"
                )
            seen.add(f.line)
        return self

    @model_validator(mode="after")
    def _check_identity_fields_reference_lines(self) -> "FormPack":
        # identity_fields must be logical line keys (the 'line:' values), NOT AcroForm
        # 'field:' names — the verifier's identity cross-check matches on line key, so a
        # field-name entry never matches and turns every filing FAIL (it also silently
        # disables the name/SSN consistency guarantee for that form).
        lines = {f.line for f in self.fields}
        unknown = [k for k in self.identity_fields if k not in lines]
        if unknown:
            raise ValueError(
                f"identity_fields entries must be logical line keys (the 'line:' values), "
                f"not AcroForm 'field:' names — {unknown} match no line in this pack. "
                f"Use line keys, e.g. [name, identifying_number, mailing_address.street]"
            )
        # A per-person entry only means anything for a field the filing actually
        # compares, so it must be declared as an identity field first.
        not_identity = [k for k in self.identity_per_person if k not in set(self.identity_fields)]
        if not_identity:
            raise ValueError(
                f"identity_per_person entries must also appear in identity_fields — {not_identity} "
                f"do not. The flag RELAXES the cross-form comparison for a field, so a field that is "
                f"not compared in the first place has nothing to relax"
            )
        return self

    @model_validator(mode="after")
    def _check_cross_form_local_refs(self) -> "FormPack":
        # A cross_form operand containing a dot is parsed as '<form_key>.<line>'. A LOCAL
        # line id that itself contains a dot and is digit-led (e.g. '5.b') is misread as
        # form key '5' and the rule is SILENTLY skipped (never PASS/FAIL) — false confidence.
        # Forbid it: rename the line to avoid the dot (e.g. '5_b').
        token_re = re.compile(r"[A-Za-z0-9_.]+")
        for rule in self.cross_form:
            for tok in token_re.findall(rule):
                head, _, rest = tok.partition(".")
                if rest and head.isdigit() and not rest.isdigit():  # digit-led dotted id, not a float literal
                    raise ValueError(
                        f"cross_form rule {rule!r}: operand {tok!r} is a dotted, digit-led local "
                        f"line id — the cross-form parser reads {head!r} as a form key and silently "
                        f"skips the rule. Rename the line to avoid the dot (e.g. {tok.replace('.', '_')!r})."
                    )
        return self


# (resolved path, mtime_ns, size) -> the validated pack. A pack is parsed and validated ONCE per file version
# (Phase J JD2: the suite and list_forms re-parsed every pack.yaml on every call — 3 s per list_forms); every
# caller gets its own deep copy, so no caller can mutate another's pack.
_PACK_CACHE: dict[tuple[str, int, int], FormPack] = {}


def load_pack(path: str | Path) -> FormPack:
    """Parse and validate a ``pack.yaml`` file, returning a :class:`FormPack`.

    Raises :class:`ValueError` when the file is not a YAML mapping and
    :class:`pydantic.ValidationError` when the mapping violates the schema.
    A file whose path, modification time and size are unchanged is served from a cache — as a deep copy.
    """
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _PACK_CACHE.get(key)
    if cached is not None:
        return cached.model_copy(deep=True)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: a form pack must be a YAML mapping (key: value pairs), "
            f"got {type(raw).__name__} — see docs/DEV_PLAN.md section 5 for the schema"
        )
    pack = FormPack.model_validate(raw)
    _PACK_CACHE[key] = pack
    return pack.model_copy(deep=True)
