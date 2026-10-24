"""State knowledge schema v2: pointer-first state packs (Phase K JK24, 2026-10-24).

WHY. ADR-0001 (docs/dev/adr/ADR-0001-pointer-first.md): "New text is a verbatim quote with a source ref, or a
pointer (ref + page). Figures go in only if a calc op reads them." The v1 shape (:class:`StateKnowledge`) types a
handful of blocks and leaves the rest (forms, credits, mailing addresses, deadlines, payment, amended return) as
untyped extras, with an inline ``{source, url}`` citation copied into every block. v2 types every block, cites by
reference into the pack's ``sources`` table (JK20), caps quotes, and says what the pack does not cover.

WHO WRITES v2. TY2026 state packs from the JK25 scaffold. TY2023 and TY2024 are frozen in v1 and the loader refuses
v2 for them; TY2025 stays v1 until JK26 migrates it (no earlier than 2027-04-16, after the KG8 freeze).

HOW TODAY'S CONSUMERS READ IT. :func:`taxfill_core.knowledge.load_state_knowledge` is dual-version: a v2 file
validates as :class:`StateKnowledgeV2` and is returned as :meth:`StateKnowledgeV2.to_v1`, a v1
:class:`StateKnowledge` carrying exactly the fields and extras calc.state_tax, state_scope, file_and_pay,
filing_summary and the source registry read, so a v2 pack that lands before JK26 rewrites the consumers works
through them unchanged. The v2 model rides on the projection as ``.schema_v2``, and
:func:`taxfill_core.knowledge.load_state_knowledge_v2` returns it directly. The registry builder
(taxfill_core.state_sources.state_block) reads raw YAML, so it projects a v2 mapping through :func:`v1_mapping`.

THE SHAPE (``extra="forbid"`` throughout; key: what the v1 projection makes of it)::

    schema_version: 2                  # absent or 1 = v1
    jurisdiction, tax_year, income_tax
    citation: SourceRef                # -> citation (the pack's primary authority)
    treaty: {conforms_to_federal_treaties, note: Statement}      # -> conforms_to_federal_treaties, treaty_note
    base_line: {form, line, quote: Quote}   # the line the state computation starts from (no v1 field)
    tax: StateTaxParams with citation: SourceRef, and its disclosures as caveats: [Caveat]
                                       # -> tax (caveats -> tax.notes, printed by calc.state_tax in order)
    credits: {caveat, items: [{name, line, type: refundable|nonrefundable, eligibility: Statement, ref, unverified}]}
                                       # pointers, no amounts
                                       # -> credits (claimed_on <- line), credits_verification <- caveat
    law_changes: {changes: [{description, quotes: [Quote], status, lookup_path, source_topic, affects, modeled,
                  ref}], checked: {checked, finding, ref}}   # -> effective_law_changes, law_changes_checked
                                       # (one of the two is required: the JS2 rule for TY2024+)
    convenience_rule: {summary, trigger, exceptions, ref}  # -> convenience_rule
    forms: {resident, part_year_or_nonresident, schedule, refs: {resident|part_year|nonresident: [SourceRef]}}
                                       # -> forms (refs -> forms.citations)
    logistics: {mailing, deadlines, payment, amended_return}  # -> mailing_addresses, deadlines, payment,
                                       #    amended_return: the fields file_and_pay and filing_summary read
    gaps: [{about, detail}]            # what the pack knowingly does not cover or carry (no v1 field)
    sources: [StateSourceEntry]        # -> sources (unchanged; the registry is built from it)

THE KINDS OF TEXT (ADR-0001: "New text is a verbatim quote with a source ref, or a pointer").

* :class:`Quote` ``{quote, ref}``: a verbatim span (at most QUOTE_MAX_CHARS characters; the JK23 checker holds it to
  the cached source) with the :class:`SourceRef` it was copied from.
* :class:`SourceRef` ``{id, description, pinpoint}`` alone is a pointer: a ``sources`` row id, which of that row's
  descriptions the citation used, and an optional page or section pinpoint.
* :class:`NotModeled` ``{not_modeled, ref}``: a tax caveat in the tool's own words naming what calc.state_tax does not
  compute, printed ``Not modeled: <it>``; short (NOT_MODELED_MAX_CHARS), cited, and with no figure in it (in signs or
  in words; a form or line designator is not a figure: see :class:`NotModeled`).
* :class:`Wording` ``{text, ref?}``: v1 prose a TY2025 CONVERSION carries unchanged so today's tools print the same
  thing (tax notes, the treaty note, credit eligibility). Capped at MIGRATED_WORDING_MAX_CHARS (the longest TY2025
  note), and a pack that carries any must say so in a ``gaps`` entry with ``about: migration``.

ENFORCED, not advised: a TY2026+ (POINTER_ONLY_FIRST_TAX_YEAR) pack that carries a Wording anywhere is refused, with the
path of each one. So a new pack's printed text is a Quote wherever a :class:`Statement` is asked for (the treaty
note, a credit's eligibility) and a Quote or a NotModeled in ``tax.caveats``; a figure gets in only inside the
source's own words. The kinds are told apart by their text key (``quote`` / ``not_modeled`` / ``text``), so a
refusal names the kind the author wrote.

v2 LEAVES OUT, on purpose: the never-read v1 blocks JK22 dropped (residency, filing_requirement, starts_from, credit
amounts and income limits), ``all_citations`` (every one of its URLs is a ``sources`` row) and ``unverified`` (its
items are ``gaps`` with ``about: unverified``). It keeps, as plain uncapped strings for now, the text a consumer
prints that is neither a quote nor a pointer: ``tax.tax_line``, exemption notes, ``tax.exemption_credits`` notes,
``credits.caveat``, law-change descriptions and the checked finding, the convenience-rule summary, the logistics
verification notes and the amended-return checklist lines (each quoting its source inline since JK27), and the
``sources`` row descriptions (StateSourceEntry, reused unchanged). JK26 decides their final types and caps when it
rewrites the consumers; until then they are the remaining prose channel a reviewer reads.

SourceRef -> Citation. The projection prints a reference as ``Citation(source=<row.descriptions[description]>,
url=<row.url>)``, plus `` — <pinpoint>`` when a pinpoint is set, so a v1 pack converted with every inline citation
mapped to its row and description index (scripts/convert_state_pack_v2.py) projects back byte for byte. The index is
positional: inserting or reordering a row's descriptions re-points every reference after it, and only an index past
the end is refused. Append descriptions; never insert or reorder them (a stable key is a JK26 item).
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator

from taxfill_core.knowledge import (
    QUOTE_MAX_CHARS,
    STATE_V2_FIRST_TAX_YEAR,
    Citation,
    StateExemptionCredits,
    StateKnowledge,
    StateSourceEntry,
    StateTaxParams,
    check_printed_designator,
    check_quote_text,
    check_sources_rows,
    check_state_jurisdiction,
)

__all__ = [
    "MIGRATED_WORDING_MAX_CHARS",
    "NOT_MODELED_MAX_CHARS",
    "POINTER_ONLY_FIRST_TAX_YEAR",
    "QUOTE_MAX_CHARS",
    "SCHEMA_VERSION",
    "BaseLine",
    "Caveat",
    "Gap",
    "NotModeled",
    "Quote",
    "SourceRef",
    "StateKnowledgeV2",
    "Statement",
    "Wording",
    "v1_mapping",
]

SCHEMA_VERSION = 2
_PINPOINT_MAX_CHARS = 120
# Phase K JK24 (2026-10-24) fix wave. From this tax year on a v2 pack's printed text is a Quote or a pointer (ADR-0001);
# Wording is refused. TY2025 is the conversion year: JK26 migrates it, and until then Wording carries its v1 notes.
POINTER_ONLY_FIRST_TAX_YEAR = 2026
# Wording is sized to the conversion it serves, not to authoring: the longest TY2025 text a converted pack carries
# as {text} is the AZ treaty_note, 2,272 characters (test_the_wording_cap_holds_every_ty2025_note).
MIGRATED_WORDING_MAX_CHARS = 2400
# A not-modeled caveat names what calc.state_tax does not compute; it is not the place for the rule itself.
NOT_MODELED_MAX_CHARS = 200
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A figure in the pack's own words (Phase K JK24 fix round 2, 2026-10-24: in signs or in words): a dollar amount
# ($ or the fullwidth ＄, "USD 300", "300 USD", "300 dollars", "20 thousand"), a percentage (% or ％, "80 percent",
# "80 per cent") or a number with thousands separators. _bare_figure catches the rest: a decimal or a number of 4+
# digits that is not a designator.
_FIGURE_RE = re.compile(
    r"[$＄]\s*\d+(?:[.,]\d+)*|\bUSD\s*\d+(?:[.,]\d+)*|\d{1,3}(?:,\d{3})+"
    r"|\d+(?:[.,]\d+)*\s*(?:[%％]|per\s*cent|dollars?\b|USD\b|thousand\b|million\b|billion\b)",
    re.IGNORECASE,
)
# A number is a designator, not a figure, when it is part of a letter-number code (IT-201, TY2026, 1040-X, 15b,
# 540NR) or follows a word that names a form, line or provision ("Line 1234", "Form 8949", "Section 290.0131").
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)*")
_DESIGNATOR_WORD_RE = re.compile(
    r"(?:\b(?:lines?|forms?|schedules?|parts?|sections?|sec\.|worksheets?|pages?|p\.|columns?|boxes|box|items?|steps?|"
    r"chapters?|articles?|art\.|publications?|pub\.?|no\.)|§§?)\s*$",
    re.IGNORECASE,
)
_CODE_BEFORE_RE = re.compile(r"[^\W\d_][^\W_]*(?:-[^\W_]+)*-?$")
_CODE_AFTER_RE = re.compile(r"^-?[^\W\d_]")


def _bare_figure(value: str) -> str | None:
    """The first decimal or 4+ digit number in ``value`` that is not a designator, else None."""
    for number in _NUMBER_RE.finditer(value):
        token = number.group(0)
        if "." not in token and len(token) < 4:
            continue
        before, after = value[: number.start()], value[number.end():]
        if _CODE_BEFORE_RE.search(before) or _CODE_AFTER_RE.match(after) or _DESIGNATOR_WORD_RE.search(before):
            continue
        return token
    return None


def _nonempty(value: str, what: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{what} must not be empty — write it, or leave the field out")
    return value


# ── the text units ──────────────────────────────────────────────────────────────


class SourceRef(BaseModel):
    """A pointer into the pack's ``sources`` table: the row id, which description, and an optional pinpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", description="A ``sources`` row id, e.g. 'logistics-1'.")
    description: int = Field(
        default=0, ge=0, description="Which of the row's descriptions this citation uses (0 = the first)."
    )
    pinpoint: str | None = Field(
        default=None,
        max_length=_PINPOINT_MAX_CHARS,
        description="Page, section or line within the document, e.g. 'p. 7' or 'Line 16'.",
    )

    @field_validator("pinpoint")
    @classmethod
    def _pinpoint_nonempty(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value, "pinpoint")


class Quote(BaseModel):
    """A verbatim span of an official document (at most QUOTE_MAX_CHARS characters) and where it was copied from.

    The general form of :class:`taxfill_core.knowledge.FormLineEntry`'s ``printed`` + ``url``: both are checked by
    :func:`taxfill_core.knowledge.check_quote_text`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    quote: str = Field(description=f"The source's own words, exactly, at most {QUOTE_MAX_CHARS} characters.")
    ref: SourceRef

    @field_validator("quote")
    @classmethod
    def _is_a_quote(cls, value: str) -> str:
        return check_quote_text(value)

    @property
    def printed(self) -> str:
        return self.quote


class Wording(BaseModel):
    """The pack's own words a consumer prints: never presented as the state's text. TY2025 CONVERSIONS ONLY.

    A v1 TY2025 pack's tax notes, treaty note and credit eligibility are prose that nobody has checked to be the
    state's words, and the conversion carries them unchanged so today's tools print the same thing. That is all
    Wording is for: :class:`StateKnowledgeV2` refuses it in a TY2026+ (POINTER_ONLY_FIRST_TAX_YEAR) pack and requires a
    TY2025 pack that carries it to say so in a ``gaps`` entry with ``about: migration``. Capped at
    MIGRATED_WORDING_MAX_CHARS, the longest TY2025 note (JK26 triages every one).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    ref: SourceRef | None = Field(default=None, description="The source the wording rests on, where one does.")

    @field_validator("text")
    @classmethod
    def _text_nonempty(cls, value: str) -> str:
        _nonempty(value, "text")
        if len(value) > MIGRATED_WORDING_MAX_CHARS:
            raise ValueError(
                f"text is {len(value)} characters; the pack's own wording holds at most {MIGRATED_WORDING_MAX_CHARS} "
                f"characters (the longest TY2025 note): quote the source ({{quote, ref}}, at most {QUOTE_MAX_CHARS}) "
                f"and point at the rest with the ref's pinpoint"
            )
        return value

    @property
    def printed(self) -> str:
        return self.text


class NotModeled(BaseModel):
    """A tax caveat in the tool's own words that names what calc.state_tax does not compute (Phase K JK24 fix wave).

    Printed as ``Not modeled: <not_modeled>``. It is the only caveat a TY2026+ pack may write in its own words,
    because it speaks about the tool, not about the state's law: short (NOT_MODELED_MAX_CHARS), cited, and with no
    figure — the rule a figure belongs to is a Quote. A figure is a dollar amount or a percentage in signs ($, ＄, %,
    ％) or in words ("USD 300", "300 dollars", "80 percent", "80 per cent"), a number with thousands separators, or a
    decimal or a number of four or more digits that is not a designator. A designator is part of a letter-number code
    ("IT-201", "1040-X", "15b", "TY2026") or follows the word that names it ("Line 1234", "Form 8949", "Schedule 1",
    "Section 290.0131"); a bare "2026" or "20000" is refused (write "TY2026", or leave the figure out).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    not_modeled: str = Field(description="What the calc does not compute, e.g. 'the county income tax'.")
    ref: SourceRef

    @field_validator("not_modeled")
    @classmethod
    def _short_and_figure_free(cls, value: str) -> str:
        _nonempty(value, "not_modeled")
        if len(value) > NOT_MODELED_MAX_CHARS:
            raise ValueError(
                f"not_modeled is {len(value)} characters; it holds at most {NOT_MODELED_MAX_CHARS}: name what the "
                f"calc does not compute and quote the rule itself as a separate {{quote, ref}} caveat"
            )
        match = _FIGURE_RE.search(value)
        figure = match.group(0) if match else _bare_figure(value)
        if figure:
            raise ValueError(
                f"not_modeled states a figure ({figure!r}); a figure goes in only as the source's words — "
                f"write it as a {{quote, ref}} caveat, or leave it out (ADR-0001). A form or line number is not a "
                f"figure: write it after its word ('Line 1234', 'Form 8949', 'Section 290.0131') or as its code "
                f"('IT-201', 'TY2026')"
            )
        return value

    @property
    def printed(self) -> str:
        return f"Not modeled: {self.not_modeled}"


# A field that takes printed text takes a quote ({quote, ref}) or, in a TY2025 conversion only, the pack's own words
# ({text, ref?}); a tax caveat may also be a not-modeled disclosure ({not_modeled, ref}).
# Each kind is told apart by its text key, so a refusal names the one kind the author wrote, not all of them.
_TEXT_KEYS = {"quote": "quote", "not_modeled": "not_modeled", "text": "text"}


def _text_kind(value: Any) -> str | None:
    keys = value.keys() if isinstance(value, dict) else type(value).model_fields if isinstance(value, BaseModel) else ()
    return next((tag for key, tag in _TEXT_KEYS.items() if key in keys), None)


def _tagged(*kinds: tuple[type[BaseModel], str], accepted: str):
    members = tuple(Annotated[model, Tag(tag)] for model, tag in kinds)
    return Annotated[
        Union[members],  # noqa: UP007 — built from a tuple, so no `|` spelling
        Discriminator(
            _text_kind,
            custom_error_type="text_kind",
            custom_error_message=f"printed text must be one of {accepted}",
        ),
    ]


Statement = _tagged((Quote, "quote"), (Wording, "text"), accepted="{quote, ref} or (TY2025 conversions) {text}")
Caveat = _tagged(
    (Quote, "quote"), (NotModeled, "not_modeled"), (Wording, "text"),
    accepted="{quote, ref}, {not_modeled, ref} or (TY2025 conversions) {text}",
)


class BaseLine(BaseModel):
    """The form line the state's computation starts from (e.g. federal AGI on line 8), quoted off the form."""

    model_config = ConfigDict(extra="forbid")

    form: str = Field(description="The form, e.g. 'Form 500'.")
    line: str = Field(description="The bare printed designator, e.g. '8'.")
    quote: Quote

    @model_validator(mode="after")
    def _quote_shows_line(self) -> BaseLine:
        check_printed_designator(self.line, self.quote.quote, what="base_line.quote")
        return self


class Gap(BaseModel):
    """One thing the pack knowingly does not cover, verify or carry."""

    model_config = ConfigDict(extra="forbid")

    about: Literal[
        "base_line", "tax", "treaty", "credits", "law_changes", "convenience_rule", "forms", "logistics",
        "sources", "unverified", "migration",
    ] = Field(description="The block it concerns; 'unverified' for an unconfirmed figure, 'migration' for v1 text "
                          "a conversion could not carry as typed v2 data.")
    detail: str

    @field_validator("detail")
    @classmethod
    def _detail_nonempty(cls, value: str) -> str:
        return _nonempty(value, "gaps detail")


# ── the blocks ──────────────────────────────────────────────────────────────────


class TreatyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conforms_to_federal_treaties: bool = Field(
        description="False means federal treaty-exempt income is still taxable by this state (e.g. California)."
    )
    note: Statement | None = Field(default=None, description="state_scope prints it after the conformity line.")


class StateExemptionCreditsV2(StateExemptionCredits):
    """``tax.exemption_credits`` as v1 types it, cited by reference."""

    citation: SourceRef  # type: ignore[assignment]


class StateTaxParamsV2(StateTaxParams):
    """The v1 ``tax`` block (every figure calc.state_tax applies), cited by reference, its notes typed as caveats."""

    citation: SourceRef  # type: ignore[assignment]
    exemption_credits: StateExemptionCreditsV2 | None = None  # type: ignore[assignment]
    caveats: list[Caveat] = Field(
        default_factory=list,
        description="The disclosures calc.state_tax prints after the tax line, in order (v1 tax.notes): not-modeled "
        "add-ons, surcharges, recaptures, form-computed amounts, special rules.",
    )

    @model_validator(mode="after")
    def _no_v1_notes(self) -> StateTaxParamsV2:
        if self.notes:
            raise ValueError(
                "a v2 tax block carries its disclosures as tax.caveats (each {quote, ref} or {not_modeled, ref}), "
                "not tax.notes — move every note there, in order"
            )
        return self


class CreditPointer(BaseModel):
    """A state credit as a pointer: what it is called, where it is claimed, who qualifies, where it is cited."""

    model_config = ConfigDict(extra="forbid")

    name: str
    line: str | None = Field(default=None, description="Where it is claimed (form, schedule, line).")
    type: Literal["refundable", "nonrefundable"] = Field(description="As the source says (the v1 credits gate's rule).")
    eligibility: Statement | None = Field(default=None, description="state_scope prints it after the name.")
    ref: SourceRef
    unverified: bool = False

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, value: str) -> str:
        return _nonempty(value, "credit name")


class CreditsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caveat: str | None = Field(
        default=None, description="state_scope prints it beside the credit candidates (v1 credits_verification)."
    )
    items: list[CreditPointer] = Field(default_factory=list)


LawChangeStatus = Literal["enacted", "irs_guidance_pending", "final_form_published"]


class LawChangeV2(BaseModel):
    """One enacted-law delta (v1 EffectiveLawChange), cited by reference, with the quotes that state it."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What changed; state_scope prints it for an unmodeled change.")
    quotes: list[Quote] = Field(default_factory=list, description="The source's words for the change.")
    status: LawChangeStatus
    lookup_path: str | None = None
    source_topic: str | None = None
    affects: list[str] = Field(default_factory=list)
    modeled: bool = False
    ref: SourceRef


class LawChangesCheckedV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked: date = Field(description="The date the What's New section was read.")
    finding: str
    ref: SourceRef


class LawChangesV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[LawChangeV2] = Field(default_factory=list)
    checked: LawChangesCheckedV2 | None = Field(
        default=None, description="Which booklet section the sweep read; required when changes is empty (the JS2 rule)."
    )


class ConvenienceRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    trigger: str
    exceptions: str = ""
    ref: SourceRef


FormRole = Literal["resident", "part_year", "nonresident"]


class FormsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resident: str
    part_year_or_nonresident: str | None = None
    schedule: str | None = None
    refs: dict[FormRole, list[SourceRef]] = Field(
        default_factory=dict, description="The role's own instructions and form pages (state_scope cites them)."
    )


class MailingV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refund_or_no_payment: str | None = None
    with_payment: str | None = None
    verification: str | None = None
    ref: SourceRef


class DeadlinesV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing_due_date: str = Field(description="ISO date the return is due.")
    automatic_extension: str | None = None
    verification: str | None = None
    ref: SourceRef

    @field_validator("filing_due_date", mode="before")
    @classmethod
    def _iso_date(cls, value: Any) -> str:
        text = value.isoformat() if hasattr(value, "isoformat") else value
        if not isinstance(text, str) or not _ISO_DATE_RE.fullmatch(text):
            raise ValueError(f"filing_due_date must be an ISO date (YYYY-MM-DD), got {value!r}")
        return text


class PaymentV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_payee: str | None = None
    check_payee_note: str | None = None
    web_pay_url: str | None = None
    note: str | None = None
    ref: SourceRef | None = None


class AmendedReturnV2(BaseModel):
    """The amended-return checklist file_and_pay and filing_summary read (Phase K JK27)."""

    model_config = ConfigDict(extra="forbid")

    form: str
    mailing_address: str | None = None
    with_payment: str | None = None
    refund_or_no_payment: str | None = None
    payment: list[str] = Field(default_factory=list)
    assemble: list[str] = Field(default_factory=list)
    timing: list[str] = Field(default_factory=list)
    mail: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    refs: list[SourceRef] = Field(min_length=1, description="The first is the amended form itself.")


class LogisticsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mailing: MailingV2 | None = None
    deadlines: DeadlinesV2 | None = None
    payment: PaymentV2 | None = None
    amended_return: AmendedReturnV2 | None = None


# ── the pack ────────────────────────────────────────────────────────────────────


def _refs_in(node: Any) -> Iterator[SourceRef]:
    if isinstance(node, SourceRef):
        yield node
    elif isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from _refs_in(getattr(node, name))
    elif isinstance(node, dict):
        for value in node.values():
            yield from _refs_in(value)
    elif isinstance(node, list | tuple):
        for value in node:
            yield from _refs_in(value)


def _wordings_in(node: Any, path: str = "") -> Iterator[str]:
    """The dotted path of every :class:`Wording` in a validated v2 model."""
    if isinstance(node, Wording):
        yield path
    elif isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from _wordings_in(getattr(node, name), f"{path}.{name}" if path else name)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _wordings_in(value, f"{path}.{key}")
    elif isinstance(node, list | tuple):
        for i, value in enumerate(node):
            yield from _wordings_in(value, f"{path}[{i}]")


class StateKnowledgeV2(BaseModel):
    """One ``knowledge/states/<st>/<year>.yaml`` written with ``schema_version: 2`` (see the module docstring)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    jurisdiction: str
    tax_year: int = Field(ge=STATE_V2_FIRST_TAX_YEAR, le=2100)
    income_tax: bool = True
    citation: SourceRef | None = Field(default=None, description="The pack's primary authority.")
    treaty: TreatyV2
    base_line: BaseLine | None = None
    tax: StateTaxParamsV2 | None = None
    credits: CreditsV2 = Field(default_factory=CreditsV2)
    law_changes: LawChangesV2 = Field(default_factory=LawChangesV2)
    convenience_rule: ConvenienceRuleV2 | None = None
    forms: FormsV2 | None = None
    logistics: LogisticsV2 = Field(default_factory=LogisticsV2)
    gaps: list[Gap] = Field(default_factory=list)
    sources: list[StateSourceEntry] = Field(min_length=1)

    @field_validator("tax_year", mode="before")
    @classmethod
    def _not_a_frozen_year(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and value < STATE_V2_FIRST_TAX_YEAR:
            raise ValueError(
                f"TY{value} state packs are frozen in schema v1 (Phase K: TY2023 and TY2024 never migrate) — "
                f"remove `schema_version` and write the v1 shape"
            )
        return value

    @field_validator("jurisdiction")
    @classmethod
    def _check_jurisdiction(cls, value: str) -> str:
        return check_state_jurisdiction(value)

    @model_validator(mode="after")
    def _law_changes_recorded(self) -> StateKnowledgeV2:
        # The JS2 rule (test_state_law_change_sweep.py) binds every TY2024+ pack, so every v2 pack.
        if not self.law_changes.changes and self.law_changes.checked is None:
            raise ValueError(
                "the pack records no law change and no `law_changes.checked` — read the booklet's What's New section "
                "and list each delta under law_changes.changes, or write law_changes.checked {checked, finding, ref} "
                "naming the section read"
            )
        return self

    @model_validator(mode="after")
    def _text_is_quoted_or_pointed(self) -> StateKnowledgeV2:
        wordings = list(_wordings_in(self))
        if not wordings:
            return self
        where = ", ".join(wordings)
        if self.tax_year >= POINTER_ONLY_FIRST_TAX_YEAR:
            raise ValueError(
                f"{where} is the pack's own wording ({{text}}), which only a TY2025 conversion may carry; in a "
                f"TY{self.tax_year} pack quote the source ({{quote, ref}}, at most {QUOTE_MAX_CHARS} characters) or, "
                f"for a tax caveat about what the calc does not compute, write {{not_modeled, ref}} (ADR-0001)"
            )
        if not any(gap.about == "migration" for gap in self.gaps):
            raise ValueError(
                f"the pack carries the pack's own wording ({where}) but no `gaps` entry with about: migration saying "
                f"so — add one (scripts/convert_state_pack_v2.py writes it), or quote the source instead"
            )
        return self

    @model_validator(mode="after")
    def _every_ref_resolves(self) -> StateKnowledgeV2:
        check_sources_rows(self.sources)
        rows = {row.id: row for row in self.sources}
        for ref in _refs_in(self):
            row = rows.get(ref.id)
            if row is None:
                raise ValueError(
                    f"source ref {ref.id!r} names no row of this pack's `sources` table; add the row "
                    f"{{id, topic, url, descriptions}} or fix the id (known: {', '.join(sorted(rows))})"
                )
            if ref.description >= len(row.descriptions):
                raise ValueError(
                    f"source ref {ref.id!r} asks for description {ref.description}, but that row has "
                    f"{len(row.descriptions)}; count from 0"
                )
        return self

    # ── the v1 projection ──

    def citation_for(self, ref: SourceRef) -> Citation:
        """The v1 inline citation a reference stands for."""
        row = next(r for r in self.sources if r.id == ref.id)
        source = row.descriptions[ref.description]
        if ref.pinpoint:
            source = f"{source} — {ref.pinpoint}"
        return Citation(source=source, url=row.url)

    def _cite(self, ref: SourceRef) -> dict:
        return self.citation_for(ref).model_dump()

    def _tax_v1(self) -> dict:
        tax = self.tax
        assert tax is not None
        out = tax.model_dump(exclude={"caveats", "notes", "citation", "exemption_credits"})
        out = {"citation": self._cite(tax.citation), **out, "notes": [c.printed for c in tax.caveats]}
        if tax.exemption_credits is not None:
            block = tax.exemption_credits.model_dump(exclude={"citation"})
            out["exemption_credits"] = {"citation": self._cite(tax.exemption_credits.citation), **block}
        else:
            out["exemption_credits"] = None
        return out

    def to_v1(self) -> StateKnowledge:
        """The v1 :class:`StateKnowledge` today's consumers read, built from this pack (``.schema_v2`` is self)."""
        data: dict[str, Any] = {
            "jurisdiction": self.jurisdiction,
            "tax_year": self.tax_year,
            "income_tax": self.income_tax,
            "conforms_to_federal_treaties": self.treaty.conforms_to_federal_treaties,
        }
        if self.treaty.note is not None:
            data["treaty_note"] = self.treaty.note.printed
        if self.citation is not None:
            data["citation"] = self._cite(self.citation)
        if self.tax is not None:
            data["tax"] = self._tax_v1()
        data["effective_law_changes"] = [
            {
                "description": c.description, "citation": self._cite(c.ref), "status": c.status,
                "lookup_path": c.lookup_path, "source_topic": c.source_topic, "affects": list(c.affects),
                "modeled": c.modeled,
            }
            for c in self.law_changes.changes
        ]
        if self.law_changes.checked is not None:
            ck = self.law_changes.checked
            data["law_changes_checked"] = {"checked": ck.checked, "finding": ck.finding, "citation": self._cite(ck.ref)}
        if self.convenience_rule is not None:
            rule = self.convenience_rule
            data["convenience_rule"] = {
                "summary": rule.summary, "trigger": rule.trigger, "exceptions": rule.exceptions,
                "citation": self._cite(rule.ref),
            }
        data["sources"] = [row.model_dump() for row in self.sources]
        data.update(self._extras_v1())
        pack = StateKnowledge.model_validate(data)
        pack._v2 = self
        return pack

    def _extras_v1(self) -> dict[str, Any]:
        """The untyped v1 extras the consumers read as dict keys, each key present only when v2 carries it."""
        extras: dict[str, Any] = {}
        if self.credits.caveat is not None:
            extras["credits_verification"] = self.credits.caveat
        if self.credits.items:
            credits = []
            for c in self.credits.items:
                entry: dict[str, Any] = {"name": c.name}
                entry["type"] = c.type
                if c.eligibility is not None:
                    entry["eligibility"] = c.eligibility.printed
                if c.line is not None:
                    entry["claimed_on"] = c.line
                entry["citation"] = self._cite(c.ref)
                if c.unverified:
                    entry["unverified"] = True
                credits.append(entry)
            extras["credits"] = credits
        if self.forms is not None:
            forms: dict[str, Any] = {"resident": self.forms.resident}
            if self.forms.part_year_or_nonresident is not None:
                forms["part_year_or_nonresident"] = self.forms.part_year_or_nonresident
            if self.forms.schedule is not None:
                forms["schedule"] = self.forms.schedule
            if self.forms.refs:
                forms["citations"] = {
                    role: [self._cite(r) for r in refs] for role, refs in self.forms.refs.items()
                }
            extras["forms"] = forms
        lg = self.logistics
        if lg.mailing is not None:
            extras["mailing_addresses"] = self._plain(lg.mailing, "citation")
        if lg.payment is not None:
            extras["payment"] = self._plain(lg.payment, "citation")
        if lg.deadlines is not None:
            extras["deadlines"] = self._plain(lg.deadlines, "citation")
        if lg.amended_return is not None:
            am = lg.amended_return
            block = {k: v for k, v in am.model_dump(exclude={"refs"}).items() if v not in (None, [])}
            block["citation"] = self._cite(am.refs[0])
            if len(am.refs) > 1:
                block["citations"] = [self._cite(r) for r in am.refs[1:]]
            extras["amended_return"] = block
        return extras

    def _plain(self, block: BaseModel, cite_key: str) -> dict[str, Any]:
        out = {k: v for k, v in block.model_dump(exclude={"ref"}).items() if v is not None}
        ref = getattr(block, "ref", None)
        if ref is not None:
            out[cite_key] = self._cite(ref)
        return out


def v1_mapping(raw: dict) -> dict:
    """A raw state pack mapping as v1 readers expect it: a v1 mapping unchanged, a v2 one projected (validated).

    For the readers that walk raw YAML instead of calling the loader (the source registry's state_block).
    """
    if raw.get("schema_version") != SCHEMA_VERSION:
        return raw
    return StateKnowledgeV2.model_validate(raw).to_v1().model_dump()
