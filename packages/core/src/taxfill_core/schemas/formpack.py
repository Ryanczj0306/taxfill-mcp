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


class FormPack(BaseModel):
    """A complete ``pack.yaml`` for one form, one jurisdiction, one tax year."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="Form name, e.g. '1040-NR', '8843', '540NR'.")
    jurisdiction: str = Field(description="'federal' or 'states/<two-letter code>', e.g. 'states/ca'.")
    tax_year: int = Field(ge=1990, le=2100)
    source_url: str = Field(description="Official URL of the blank PDF (downloaded at runtime, never vendored).")
    pdf_sha256: str = Field(
        description="SHA-256 of the blank PDF for checksum verification; '...' is allowed only as an authoring placeholder."
    )
    acroform_root: str = Field(
        description="XFA-derived AcroForm root name; varies per form (e.g. 'topmostSubform[0]', Sched OI: 'form1040-NR[0]')."
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
        # official-government-host guarantee at load time too (.gov/.mil/.us — many state DORs
        # publish on .us). Defence-in-depth alongside the fetch-time host allowlist.
        value = _require_http_url(value, "source_url")
        host = (urlparse(value).hostname or "").lower()
        if not any(host == tld or host.endswith("." + tld) for tld in ("gov", "mil", "us")):
            raise ValueError(
                f"source_url must point to an official US government host (.gov/.mil/.us), got "
                f"{host!r} — blank forms are downloaded only from official government sites"
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


def load_pack(path: str | Path) -> FormPack:
    """Parse and validate a ``pack.yaml`` file, returning a :class:`FormPack`.

    Raises :class:`ValueError` when the file is not a YAML mapping and
    :class:`pydantic.ValidationError` when the mapping violates the schema.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: a form pack must be a YAML mapping (key: value pairs), "
            f"got {type(raw).__name__} — see docs/DEV_PLAN.md section 5 for the schema"
        )
    return FormPack.model_validate(raw)
