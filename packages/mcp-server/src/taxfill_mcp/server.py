"""TaxFill MCP server — dev plan section 8.

A thin MCP wrapper (official ``mcp`` python-sdk, FastMCP) over the tested
``taxfill_core`` engine. The agent does interviewing/judgment; these tools do
all the deterministic PDF/calc work. Design commitments hold: 100% local, no
telemetry; the only outbound traffic is downloading blank forms (``fetch_blank``)
from the tax agencies' own sites (or an exact, digest-checked Internet Archive
copy when a state site blocks scripts). Every output is a review draft — the human signs
and files.

Tools take agent-friendly arguments (``form``/``year``, not raw FormPack
objects) and load packs internally. ``render_form`` returns MCP image content so
the calling agent can vision-review every page (the mandatory verify gate).
"""
from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field, ValidationError

from taxfill_core import (
    additional_medicare_tax as _additional_medicare_tax,
    child_tax_credit as _child_tax_credit,
    dependent_care_credit as _dependent_care_credit,
    education_credits as _education_credits,
    eitc as _eitc,
    estimate_refund as _estimate_refund,
    excess_ss as _excess_ss,
    file_and_pay as _file_and_pay,
    fill_form as _fill_form,
    filing_summary as _filing_summary,
    get_sources as _get_sources,
    intake_checklist as _intake_checklist,
    niit as _niit,
    ptc_annual as _ptc_annual,
    ptc_monthly as _ptc_monthly,
    render_pdf as _render_pdf,
    se_tax as _se_tax,
    standard_deduction as _standard_deduction,
    state_scope as _state_scope,
    annualize_ytd as _annualize_ytd,
    charitable_deduction as _charitable_deduction,
    contribution_limits as _contribution_limits,
    elective_deferral_room as _elective_deferral_room,
    ira_net_income_attributable as _ira_net_income_attributable,
    ira_recharacterization as _ira_recharacterization,
    ira_contribution_eligibility as _ira_contribution_eligibility,
    hsa_deduction as _hsa_deduction,
    espp_disposition as _espp_disposition,
    capital_loss_limitation as _capital_loss_limitation,
    foreign_tax_credit_election as _foreign_tax_credit_election,
    foreign_asset_reporting as _foreign_asset_reporting,
    ira_pro_rata as _ira_pro_rata,
    roth_conversion as _roth_conversion,
    magi_ladder as _magi_ladder,
    marginal_dollar_savings as _marginal_dollar_savings,
    employee_fica as _employee_fica,
    estimated_tax_safe_harbor as _estimated_tax_safe_harbor,
    schedule_1a_deductions as _schedule_1a_deductions,
    state_tax as _state_tax,
    student_loan_interest_deduction as _student_loan_interest_deduction,
    tax_from_taxable_income as _tax,
    tax_with_preferential_rates as _tax_with_preferential_rates,
    taxable_social_security as _taxable_social_security,
    treaty_benefit as _treaty_benefit,
    verify_filing as _verify_filing,
    verify_form as _verify_form,
)
from taxfill_core.datadir import user_path
from taxfill_core.discovery import get_form_map as _get_form_map, list_forms as _list_forms, load_form_pack
from taxfill_core.extract import extract_document as _extract_document, list_document_kinds as _list_document_kinds
from taxfill_core.fetch import fetch_pack_blank as _fetch_pack_blank
from taxfill_core.handfill import (
    hand_fill_pack_path,
    hand_fill_worksheet as _hand_fill_worksheet,
    load_hand_fill_pack,
    load_hand_fill_pack_for,
)
from taxfill_core.schemas.handfill import HandFillPack
from taxfill_core.knowledge import provisional_marker
from taxfill_core.estimate import IncomeSnapshot
from taxfill_core.file_and_pay import DRAFT_NOTICE, FilingManifestItem
from taxfill_core.residency import classify as _classify
from taxfill_core.scenarios import compare_scenarios as _compare_scenarios
from taxfill_core.schemas.profile import Profile
from taxfill_core.verify import FilingItem, VerifyReport, hand_written_amounts
from taxfill_core.workspace import Position, Workspace, default_workspace_root

from taxfill_mcp import __version__

# Resolved through the shared resolver (env var -> existing ./taxfill-workspace
# -> ~/taxfill-workspace) so the server, the CLI and `taxfill purge` always
# agree on where the SSN-bearing workspace lives. A bare relative default here
# used to mean "wherever the MCP client launched from".
WORKSPACE_ROOT = str(default_workspace_root())


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

mcp = FastMCP(
    "taxfill",
    instructions=(
        "Deterministic tax-prep execution layer. You interview the user and decide positions; "
        "these tools fill, verify, render, and compute — never do tax arithmetic yourself, and "
        "never invent a value (unknown stays a gap). Always treat output as a review draft: the "
        "user reviews, signs, and files. Full flow (workspace_load first when resuming): "
        "intake_checklist -> extract_document (+ user confirms each value) -> workspace_save -> "
        "estimate_refund -> residency (visa/day-count filers) -> state_scope (which states must "
        "file) -> decide positions + workspace_record_position (each with its authority) -> "
        "list_forms/get_form_map -> fetch_blank -> fill_form -> verify_form/verify_filing "
        "(pass `independent` calc results so the independent recompute runs; loop until ok) -> "
        "render_form (vision-review every page) -> filing_summary (user approves) -> "
        "file_and_pay -> workspace_reconcile. "
        "A form with no pack (list_forms has none): tell the user so up front, then fetch_blank -> get_form_map -> "
        "fill_form -> verify_form with form='unmapped' (source_url from the agency's .gov site, then the "
        "blank_sha256 fetch_blank returns). The output is an unverified draft, never filing-grade (grade "
        "unmapped_draft, stamped on every page): keep that label, show get_form_map's sweep page with render_form "
        "before the user confirms any box, render_form every page, and hand-write the hand_write entries."
    ),
)
# FastMCP 1.x takes no version, and the low-level server it wraps then reports the
# mcp SDK's own version as serverInfo.version, so clients saw "1.30.0" (Phase K
# JK5). Report this package's release instead.
mcp._mcp_server.version = __version__


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def _report_summary(report: VerifyReport, *, recompute_ran: bool = True) -> dict:
    """Compact, agent-actionable view of a VerifyReport (ok + per-section failures).

    ``recompute_ran=False`` (the caller supplied no ``independent`` set) stamps the
    recompute section with an explicit not-run note, so ok:true is never mistaken
    for "the numbers were independently recomputed" — checked:0 alone is ambiguous.
    """
    sections: dict[str, Any] = {}
    for name in ("assertions", "relations", "recompute", "clipping", "checkboxes", "identity", "cross_form"):
        checks = getattr(report, name) or []
        fails = [c.detail for c in checks if getattr(c, "status", None) == "FAIL"]
        sections[name] = {"checked": len(checks), "failed": len(fails), "failures": fails}
        # Phase K JK28: a SKIPPED check never flips ok (a relation whose `unless` box is checked, a cross_form rule
        # whose form is not in the filing, a per-person identity field), so the summary lists what went unchecked.
        skipped = [c.detail for c in checks if getattr(c, "status", None) == "SKIPPED"]
        if skipped:
            sections[name]["skipped"] = skipped
    if not recompute_ran:
        sections["recompute"]["note"] = (
            "not run — pass `independent` ({line: calc result}, e.g. line 16 tax from "
            "taxable_income/filing_status/year; keyed per form_key for verify_filing) to enable "
            "the independent recompute; without it this report proves internal consistency only"
        )
    return {
        "ok": report.ok,
        "form_keys": report.form_keys,
        "sections": sections,
        "pitfalls": [{"id": p.id, "status": p.status, "detail": p.detail} for p in report.pitfall_checks],
    }


def _overlay_report_summary(report, *, recompute_ran: bool = True) -> dict:
    """The OVERLAY verdict (an ``overlay.OverlayVerifyReport``) in the same top-level shape as ``_report_summary``.

    A stamped print-only form has no AcroForm fields to diff, so the sections differ:
    ``overlay`` reads each line's DECLARED box for exactly the stamped value, ``recompute`` is
    the same independent recompute the AcroForm path runs (over the worksheet's money lines).
    ``limits`` spells out what the verdict cannot see, so ``ok: true`` is never read as "the
    page looks right" — render_form + vision remain the gate.
    """
    fails = [c.detail for c in report.checks if c.status == "FAIL"]
    rc_fails = [c.detail for c in report.recompute if c.status == "FAIL"]
    sections: dict[str, Any] = {
        "overlay": {"checked": len(report.checks), "failed": len(fails), "failures": fails},
        "recompute": {"checked": len(report.recompute), "failed": len(rc_fails), "failures": rc_fails},
    }
    if not recompute_ran:
        sections["recompute"]["note"] = (
            "not run — pass `independent` ({line: calc result}) to compare the worksheet's computed "
            "money lines against the calc engine; without it this verdict proves only that the stamps "
            "landed where the pack says"
        )
    return {
        "ok": report.ok,
        "verdict": report.verdict,
        "form_keys": report.form_keys,
        "page_count": report.page_count,
        "sections": sections,
        "hand_written_lines": [_dump(ln) for ln in report.hand_written_lines],
        "limits": report.limits,
    }


def _load_any_pack(form: str, year: int, jurisdiction: str):
    """An AcroForm pack, or — when only a ``handfill.yaml`` ships for the key — the hand-fill pack.

    The print-only manifests (CT ct1040, HI n11, NM pit1, SC sc1040, and WV it140 for TY2025,
    whose return is a flat booklet page) and the FBAR carry no
    ``pack.yaml``; routing them here lets fetch_blank / fill_form / verify_form serve a
    hand-fill pack that carries overlay coordinates without a 24th tool.
    """
    try:
        return load_form_pack(form, year, jurisdiction)
    except FileNotFoundError:
        path = hand_fill_pack_path(form, year, jurisdiction)
        if not path.is_file():
            raise
        return load_hand_fill_pack(path)


def _validation_problems(exc: ValidationError) -> str:
    """PII-safe one-liner for a pydantic ValidationError: field paths + messages only.

    Input values are never echoed (``include_input=False``) — a wrong-shaped call can
    still carry SSNs/wages, and tool errors travel back through the agent transcript.
    """
    problems = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(part) for part in err["loc"]) or "(top level)"
        problems.append(f"{loc}: {err['msg']}")
    return "; ".join(problems)


# ── the no-pack fallback: form="unmapped" (Phase K JK16b, 2026-10-25; ADR-0002) ─────────────────────────────────
#
# fetch_blank, get_form_map, fill_form and verify_form take form="unmapped" (the only switch, routing rule 1): each
# tests it first and returns from its own unmapped branch before _load_any_pack / _get_form_map runs, so the pack
# branch keeps its code (scripts/golden_pack_path.py pins its output, the KG8 gate). The branches import the core
# modules lazily (rule 8). Every new parameter defaults to None and is refused with a pack key (rule 3). Every
# unmapped response carries grade "unmapped_draft", limits and next_step at its top level (rule 4), and every step
# after the fetch names the blank by blank_sha256 (rule 5). A refusal is a ValueError that says no PDF was written,
# names a pointer, and never echoes a value or the data directory's absolute path (rule 6).

UNMAPPED_FORM = "unmapped"
_SourceUrl = Annotated[str | None, Field(description=(
    "Only with form='unmapped' (a form with no pack): the form's official https PDF URL on the agency's own .gov "
    "site. Refused with a pack key."))]
_BlankSha = Annotated[str | None, Field(description=(
    "Only with form='unmapped': the sha256 fetch_blank returned for this blank; every step after the fetch names "
    "the blank by it. Refused with a pack key."))]
_UNMAPPED_GRADE = "unmapped_draft"
_FEDERAL_FORMS_PAGE = "https://www.irs.gov/forms-pubs"
_STATE_AGENCIES_PAGE = "https://www.irs.gov/businesses/small-businesses-self-employed/state-government-websites"
_UNSIGNED_TOKEN_LIMIT = (
    "verified_at is not signed: it names this file's sha256 and the time this verify ran, so it proves nothing on its "
    "own; keep the verify response itself, and any later change to the file voids it."
)


def _refuse_unmapped_params(tool: str, form: str, **params: Any) -> None:
    """Routing rule 3: a parameter of the unmapped path is refused with a pack key, never ignored."""
    given = [name for name, value in params.items() if value is not None]
    if given:
        names = ", ".join(given)
        raise ValueError(
            f"{tool}: {names} {'is' if len(given) == 1 else 'are'} only for form='unmapped' — '{form}' is a pack "
            "key, "
            f"which fills and checks from its own pack; drop {names}, or pass form='unmapped' for a form with no "
            f"pack. Nothing was fetched, written or verified."
        )


def _unmapped_pointer(source_url: str | None, jurisdiction: str) -> str:
    """The official place to go next: the form's own https .gov URL when it is one, else the agencies' forms pages."""
    from urllib.parse import urlparse

    from taxfill_core.knowledge import is_official_gov_host

    parsed = urlparse(source_url or "")
    if parsed.scheme == "https" and is_official_gov_host((parsed.hostname or "").lower()):
        return f"The form's official source: {source_url}"
    if jurisdiction == "federal":
        return f"Find the form on the IRS forms page: {_FEDERAL_FORMS_PAGE}"
    return (f"Find the form on the state tax agency's own forms page (the IRS lists every agency: "
            f"{_STATE_AGENCIES_PAGE})")


def _scrub_local_paths(text: str) -> str:
    """Rule 6 (JK27): no absolute path of the data directory, the blank cache or the workspace in a refusal."""
    from taxfill_core.datadir import data_root, home_display
    from taxfill_core.fetch import default_cache_dir

    for path, name in ((default_cache_dir(), "<blank cache>"), (Path(WORKSPACE_ROOT), "<workspace>"),
                       (data_root(), "<data directory>")):
        for spelling in sorted({str(path), str(path.resolve()), home_display(path)}, key=len, reverse=True):
            if spelling and spelling not in (".", "~", "/"):
                text = text.replace(spelling, name)
    return text


def _unmapped_refusal(tool: str, exc: BaseException, *, source_url: str | None, jurisdiction: str,
                      wrote: str = "No PDF was written") -> ValueError:
    """Routing rule 6: a core refusal as the ValueError text an agent reads."""
    text = _scrub_local_paths(str(exc)).replace("fetch_unmapped_blank", "fetch_blank with form='unmapped'")
    # the core's argument name, as fetch_blank spells it (Phase K JK19 pilot, 2026-10-25)
    text = text.replace("pass it as expected_title", "pass it as form_title")
    text = text.rstrip(". ")
    if "no pdf was written" not in text.lower() or wrote != "No PDF was written":
        text = f"{text}. {wrote}"
    return ValueError(f"{tool} (form='unmapped') refused: {text}. {_unmapped_pointer(source_url, jurisdiction)}")


def _unmapped_call(tool: str, call, *, source_url: str | None, jurisdiction: str, wrote: str = "No PDF was written"):
    """Run one unmapped core call; its refusals (UnmappedBlankRefused, UnmappedFillRefused, UnmappedVerifyRefused,
    StampRefused, a missing local_blank, a bad year or digest) surface as rule 6's ValueError."""
    from http.client import HTTPException

    from pypdf.errors import PyPdfError

    from taxfill_core.fetch import FetchError

    try:
        return call()
    except (FetchError, ValueError, OSError, HTTPException, PyPdfError) as exc:  # a truncated download, a bad PDF too
        raise _unmapped_refusal(tool, exc, source_url=source_url, jurisdiction=jurisdiction, wrote=wrote) from None


def _require(tool: str, jurisdiction: str, pointer_url: str | None, **required: Any) -> None:
    missing = [name for name, value in required.items() if value is None or value == ""]
    if missing:
        raise ValueError(
            f"{tool} with form='unmapped' needs {', '.join(missing)} — "
            + ("the form's official https URL and its printed name (e.g. 'SD 100'); "
               if tool == "fetch_blank" else "the source_url and the blank_sha256 fetch_blank returned; ")
            + f"nothing was fetched or written. {_unmapped_pointer(pointer_url, jurisdiction)}"
        )


def _graded(response: dict, next_step: str | None = None) -> dict:
    """Rule 4: grade first, limits and next_step at the top level (the core builds them; this asserts it)."""
    out = {"grade": _UNMAPPED_GRADE, **{k: v for k, v in response.items() if k != "grade"}}
    if next_step is not None:
        out["next_step"] = next_step
    missing = [k for k in ("limits", "next_step") if k not in out]
    if missing or response.get("grade") not in (None, _UNMAPPED_GRADE):
        raise RuntimeError(f"an unmapped response lacks {missing} or carries another grade — a taxfill bug")
    return out


def _unmapped_fetch(year: int, jurisdiction: str, source_url: str | None, form_title: str | None,
                    local_blank: str | None) -> dict:
    from taxfill_core.fetch import fetch_unmapped_blank
    from taxfill_core.unmapped import LIMITS

    _require("fetch_blank", jurisdiction, source_url, source_url=source_url, form_title=form_title)
    blank = _unmapped_call(
        "fetch_blank",
        lambda: fetch_unmapped_blank(source_url, tax_year=year, expected_title=form_title, local_blank=local_blank,
                                     jurisdiction=jurisdiction, workspace_root=WORKSPACE_ROOT),
        source_url=source_url, jurisdiction=jurisdiction, wrote="Nothing was stored and no PDF was written")
    first = blank.first_page
    return _graded({
        "path": str(blank.path), "source_url": blank.source_url, "sha256": blank.sha256, "pinned": False,
        "origin": blank.origin, "fetched_at": blank.fetched_at, "jurisdiction": blank.jurisdiction,
        "tax_year": blank.tax_year,
        "first_page": {"page": first.page, "printed_year": first.printed_year, "title_found": first.title_found},
        "page_count": blank.page_count, "kind": blank.kind, "limits": list(LIMITS),
    }, next_step=(
        f"This blank has no pack, so anything filled from it is an unverified draft, never filing-grade. Call "
        f"get_form_map with form='unmapped', this source_url and blank_sha256='{blank.sha256}' to see its fields, "
        f"then show the sweep page with render_form before any value is written."
    ))


def _unmapped_describe(year: int, jurisdiction: str, source_url: str | None, blank_sha256: str | None) -> dict:
    from taxfill_core.fetch import load_unmapped_blank
    from taxfill_core.unmapped import NEXT_STEP_DESCRIBE, describe_unmapped

    _require("get_form_map", jurisdiction, source_url, source_url=source_url, blank_sha256=blank_sha256)

    def run() -> dict:
        blank = load_unmapped_blank(blank_sha256, tax_year=year, source_url=source_url, jurisdiction=jurisdiction,
                                    workspace_root=WORKSPACE_ROOT)
        return describe_unmapped(blank)

    result = _unmapped_call("get_form_map", run, source_url=source_url, jurisdiction=jurisdiction)
    return _graded(result, next_step=(
        f"{NEXT_STEP_DESCRIBE} Then call fill_form with form='unmapped', the same source_url and "
        f"blank_sha256='{result['blank_sha256']}', values keyed by these field names and confirmed_fields for the "
        f"boxes the user confirmed."
    ))


def _unmapped_fill(year: int, jurisdiction: str, values: dict[str, Any], out_path: str, source_url: str | None,
                   blank_sha256: str | None, money_fields: list[str] | None, provenance: dict[str, str] | None,
                   confirmed_fields: list[str] | None) -> dict:
    from taxfill_core.unmapped import fill_unmapped

    _require("fill_form", jurisdiction, source_url, source_url=source_url, blank_sha256=blank_sha256)
    out = user_path(out_path).absolute()
    result = _unmapped_call(
        "fill_form",
        lambda: fill_unmapped(blank_sha256, source_url=source_url, tax_year=year, jurisdiction=jurisdiction,
                              values=values, out_path=out, money_fields=money_fields, provenance=provenance,
                              confirmed_fields=confirmed_fields, workspace_root=WORKSPACE_ROOT),
        source_url=source_url, jurisdiction=jurisdiction)
    return _graded({**result, "notice": DRAFT_NOTICE})


def _unmapped_verify(year: int, jurisdiction: str, pdf_path: str, expected: dict[str, Any] | None,
                     independent: dict[str, float] | None, source_url: str | None, blank_sha256: str | None,
                     declared_relations: list[str] | None) -> dict:
    from taxfill_core.unmapped_verify import verify_unmapped

    _require("verify_form", jurisdiction, source_url, source_url=source_url, blank_sha256=blank_sha256,
             expected=expected)
    result = _unmapped_call(
        "verify_form",
        lambda: verify_unmapped(pdf_path, blank_sha256=blank_sha256, source_url=source_url, tax_year=year,
                                jurisdiction=jurisdiction, expected=expected, independent=independent,
                                declared_relations=declared_relations, workspace_root=WORKSPACE_ROOT),
        source_url=source_url, jurisdiction=jurisdiction, wrote="Nothing was verified and no PDF was written")
    limits = list(result["limits"])
    limits.insert(len(limits) - 1, _UNSIGNED_TOKEN_LIMIT)  # the "never filing-grade" entry stays last
    return _graded({**result, "limits": limits})


def _refuse_unmapped_draft(pdf_path: Any, what: str) -> None:
    """Rule 15: the pack path never runs its checks on fallback output. Reads only the /Info record (pypdf), never
    raises on a file it cannot read (the pack path's own error text stands for it)."""
    from taxfill_core.unmapped_verify import is_unmapped_draft

    if isinstance(pdf_path, (str, Path)) and is_unmapped_draft(pdf_path):
        raise ValueError(
            f"{what} is an unmapped draft (its /Info carries the /TaxfillUnmapped record), so a pack's checks never "
            f"run on it — verify it with verify_form(form='unmapped', source_url=..., blank_sha256=..., expected=the "
            f"written map fill_form returned). An unmapped draft is never filing-grade. Nothing was verified."
        )


# ── discovery ────────────────────────────────────────────────────────────────


@mcp.tool()
def list_forms(jurisdiction: str | None = None, year: int | None = None) -> list[dict]:
    """List available form packs (optionally filtered by jurisdiction/year).

    `source_status: draft` marks a pack mapped from an IRS early-release draft (the TY2026 packs):
    fill_form refuses its planning-only year until the final posts and the pack is re-pinned.
    """
    return [_dump(s) for s in _list_forms(jurisdiction, year)]


@mcp.tool()
def get_form_map(form: str, year: int, jurisdiction: str = "federal", source_url: _SourceUrl = None,
                 blank_sha256: _BlankSha = None) -> dict:
    """Return one pack's line->field map, relations, and cross-form refs.

    `form` is the form KEY (e.g. 'f1040', 'sched_c'). Use list_forms to discover keys.
    A relation ending in ' unless <line>' names a checkbox line: verify skips it (SKIPPED) while that box is checked.
    `mirrors` maps each page-header mirror line to the template fill_form builds it from when you
    leave it out (e.g. CA Form 540's Sides 2-6 `name.full`); `mirror_abbreviations` lists, per
    mirror, the placeholders a header may shorten to an initial or leave out when the full name is
    too wide for its box (fill_form does that itself; every other placeholder stays whole).
    `unfillable_lines` (line -> why; empty on most packs) lists printed lines the blank cannot take:
    a re-issued blank that binds two printed rows to one field (AZ Form 140 2025, lines 16 and 27).
    Tell the user BEFORE filling: fill_form refuses a value on one, the filer hand-writes that row
    on the printed return, and every total that adds the line must still include the amount.

    NO PACK (form='unmapped', with source_url and blank_sha256 from fetch_blank): every AcroForm field of that blank
    with its kind, flags, options, whether it may ever be filled, and each box's pack-blind anchor (a printed line and
    a confidence, never a verified line map), plus `hand_write` (boxes never filled), `sweep_path` (a stamped copy
    numbering each fillable field's boxes: show it with render_form so the user can confirm boxes) and the grade
    "unmapped_draft", `limits` and `next_step`.
    """
    if form == UNMAPPED_FORM:
        return _unmapped_describe(year, jurisdiction, source_url, blank_sha256)
    _refuse_unmapped_params("get_form_map", form, source_url=source_url, blank_sha256=blank_sha256)
    return _dump(_get_form_map(form, year, jurisdiction))


# ── fetch / fill / verify / render ─────────────────────────────────────────────


@mcp.tool()
def fetch_blank(
    form: str,
    year: int,
    jurisdiction: str = "federal",
    source_url: _SourceUrl = None,
    form_title: Annotated[str | None, Field(description=(
        "Only with form='unmapped': the form's printed name as its first page prints it, e.g. 'SD 100'; the first "
        "page must print it and the tax year. Refused with a pack key."))] = None,
    local_blank: Annotated[str | None, Field(description=(
        "Only with form='unmapped', optional: a PDF the user saved from source_url in a browser (for a host that "
        "refuses scripts); it passes the same checks and is kept under the year's workspace. Refused with a pack "
        "key."))] = None,
) -> dict:
    """Download the official blank PDF (checksum-verified for a pack) and return its local path.

    Also serves the print-only hand-fill packs (CT/HI/NM/SC): their blank is what
    `taxfill locate <blank.pdf> --page N <label>...` reads overlay anchors from.

    NO PACK (form='unmapped', with source_url and form_title; local_blank optional): downloads over https from an
    official .gov host only (every redirect hop checked), records the bytes' sha256 (not pinned: nothing reviewed
    them) and checks that the form's first page prints the tax year and form_title. A form a shipped pack covers, an
    IRS early-release draft, a revision-dated, XFA-only, scanned or locked blank is refused. Returns `sha256` (pass it
    as blank_sha256 to every later step), `first_page`, `kind`, and the grade "unmapped_draft", `limits` and
    `next_step`.
    """
    if form == UNMAPPED_FORM:
        return _unmapped_fetch(year, jurisdiction, source_url, form_title, local_blank)
    _refuse_unmapped_params("fetch_blank", form, source_url=source_url, form_title=form_title,
                            local_blank=local_blank)
    pack = _load_any_pack(form, year, jurisdiction)
    if isinstance(pack, HandFillPack) and pack.efile_only:
        from taxfill_core.overlay import efile_only_refusal

        raise ValueError(efile_only_refusal(pack))
    path = _fetch_pack_blank(pack)
    return {"path": str(path), "source_url": pack.source_url, "sha256": pack.pdf_sha256}


@mcp.tool()
def fill_form(
    form: str,
    year: int,
    values: dict[str, Any],
    out_path: str,
    jurisdiction: str = "federal",
    source_url: _SourceUrl = None,
    blank_sha256: _BlankSha = None,
    money_fields: Annotated[list[str] | None, Field(description=(
        "Only with form='unmapped': the field names whose values get IRS whole-dollar rendering (no other field is "
        "rounded). Refused with a pack key."))] = None,
    provenance: Annotated[dict[str, str] | None, Field(description=(
        "Only with form='unmapped': field name -> 'from a document' or 'from the user', recorded beside the label "
        "'agent-computed, unverified' (it never removes it). Refused with a pack key."))] = None,
    confirmed_fields: Annotated[list[str] | None, Field(description=(
        "Only with form='unmapped': the fields whose boxes the user confirmed on the rendered sweep page "
        "(get_form_map's sweep_path); a field anchored 'low' or 'med' is written only when listed here. Refused "
        "with a pack key."))] = None,
) -> dict:
    """Deterministically fill a form. `values` maps line ids (per get_form_map) to values.

    Downloads/uses the official blank, writes the filled PDF to out_path ("~/..." works; the
    result's `out_path` is the absolute path written), and returns the written lines + any
    warnings, the `notice` to relay to the user (a review draft, not tax
    advice, for paper filing only), plus `guards_hidden` (P-027): the page-covering viewer-guard
    widgets the filler set Hidden so the return prints in any viewer (AL Form 40's "use Adobe
    Reader" panel and white print lids, MO-1040's print lids); every written widget is made
    viewable and printable. `mirrored` lists the page-header mirror lines it filled itself: a pack
    whose later pages repeat the filer's name and SSN (CA Form 540 / 540NR "Your name:" and "Your
    SSN or ITIN:" on Sides 2-6) declares them, and a mirror you leave out is built from the lines
    you gave (get_form_map's `mirrors` shows each template), measured against its box at the box's
    font (the narrowest widget, less 1 pt on each side). A name too wide for it is abbreviated as
    the pack's `mirror_abbreviations` allow ("A Q WASHINGTON" for "ALEXANDRA Q WASHINGTON", else
    "A WASHINGTON") with an informational warning; one too wide even then is left BLANK, with a
    warning to hand-write it in the box after printing. A value you pass for a mirror is written
    as given (verify_form measures it), and a built value the box refuses for its form (comb
    digits, 'NRA') is left blank with a warning saying so. `combs_aligned` (P-033) lists each
    written comb widget whose cells crossed the separators printed in its box (the IRS 1040 /
    1040-X SSN dots) and that fill_form narrowed to the printed grid, as '<field> (page N): x
    <old> -> <new>'; nothing to do, it is reported so a reviewer knows the widget moved.
    Rejects unknown lines and comb/length violations, and a value on a line get_form_map lists
    under `unfillable_lines` (the blank prints one field on two rows): leave that line out, tell the
    user to hand-write it on the printed return, fill every total that adds it WITH the amount
    counted, and give verify_form the amount in `expected`. No
    identifying-number or comb line takes the literal 'NRA' (P-026): an MFS filer whose
    nonresident-alien spouse has no SSN/ITIN (and needs none) writes 'NRA' in the MFS ENTRY
    SPACE (the Instructions for Form 1040: "enter 'NRA' in the entry space") —
    `filing_status.spouse_or_qualifying_person_name` on the 2023/2024 1040 packs,
    `filing_status.mfs_spouse_name` on 2025 and the 2026 draft — and leaves `spouse.identifying_number` blank.

    PRINT-ONLY (hand-fill) packs — CT ct1040, HI n11, NM pit1, SC sc1040: when the pack carries
    overlay coordinates the worksheet values are STAMPED onto the blank and the result is
    `render_mode: "hand_fill_overlay"` with stamped_lines, hand_written_lines (values that still
    must be hand-written), warnings and the full worksheet; verify_form then needs `expected` =
    this same `values`. A hand-fill pack with no coordinates is refused with a pointer to
    hand_fill_worksheet.

    NO PACK (form='unmapped', with source_url and blank_sha256): `values` is keyed by the qualified field names
    get_form_map returned for that blank. ReadOnly, calculated, signature, pushbutton, viewer-guard and hidden boxes
    are never written, and a field anchored 'none' (or 'low'/'med' unless in confirmed_fields) is not written either:
    each comes back in `hand_write` with its reason. An unknown name, a choice not offered, or a /MaxLen or comb
    violation refuses the whole call. Every page is stamped "UNMAPPED DRAFT — NOT FILING-GRADE" in its content
    stream (no parameter turns it off), every value is labelled "agent-computed, unverified", and the response
    carries `status` "unverified_draft", a `worksheet`, the grade "unmapped_draft", `limits` and `next_step`. With no
    passing anchor benchmark, or for a blank with no fillable field, no PDF is written (`status` "worksheet_only").
    """
    if form == UNMAPPED_FORM:
        return _unmapped_fill(year, jurisdiction, values, out_path, source_url, blank_sha256, money_fields,
                              provenance, confirmed_fields)
    _refuse_unmapped_params("fill_form", form, source_url=source_url, blank_sha256=blank_sha256,
                            money_fields=money_fields, provenance=provenance, confirmed_fields=confirmed_fields)
    pack = _load_any_pack(form, year, jurisdiction)
    if isinstance(pack, HandFillPack) and pack.efile_only:
        from taxfill_core.overlay import efile_only_refusal

        raise ValueError(efile_only_refusal(pack))
    if isinstance(pack, HandFillPack) and not pack.has_overlay_coordinates:
        raise ValueError(
            f"'{form}' ({jurisdiction} {year}) is a print-only HAND-FILL pack with no overlay coordinates, so "
            f"fill_form has nothing to stamp — call hand_fill_worksheet('{form}', {year}, '{jurisdiction}', "
            f"values) for the line->value worksheet and hand-write it onto the printed blank "
            f"({pack.source_url})"
        )
    blank = _fetch_pack_blank(pack)
    # Phase K JK28: out_path may be "~/..." (a JSON argument is never shell-expanded). The result names the ABSOLUTE
    # path written — the agent hands it to its own file tools, many of which take only absolute paths.
    out = user_path(out_path).absolute()
    result = _fill_form(pack, values, blank, out)
    if isinstance(pack, HandFillPack):
        return {
            "render_mode": "hand_fill_overlay",
            **_dump(result),
            "worksheet": _dump(_hand_fill_worksheet(pack, values)),
            "notice": DRAFT_NOTICE,
        }
    return {"out_path": str(out), "written": result.written, "warnings": result.warnings,
            "guards_hidden": result.guards_hidden, "mirrored": result.mirrored,
            "combs_aligned": result.combs_aligned, "notice": DRAFT_NOTICE}


@mcp.tool()
def verify_form(
    form: str,
    year: int,
    pdf_path: str,
    expected: dict[str, Any] | None = None,
    independent: dict[str, float] | None = None,
    jurisdiction: str = "federal",
    source_url: _SourceUrl = None,
    blank_sha256: _BlankSha = None,
    declared_relations: Annotated[list[str] | None, Field(description=(
        "Only with form='unmapped': relations over field names that you declare (e.g. 'line3 == line1 + line2'); "
        "each is checked and labelled 'agent-declared, not of record'. Refused with a pack key."))] = None,
) -> dict:
    """Verify a filled form against its pack (form='unmapped': against its blank): assertions, relation math +
    independent recompute, clipping scan, required-checkbox audit, and the pitfall registry. Returns ok + failures.

    The identity section checks each page-header mirror the pack declares (e.g. CA Form 540's
    Sides 2-6 name and SSN) against what fill_form would write from the form's own lines, measured
    against the header's box: a failure, naming the value to write, when the header is blank,
    different, cut off by its box, or abbreviated although the full name fits. A number compares
    by its digits (dashes or not). An abbreviation get_form_map's `mirror_abbreviations` allow
    passes only when the full name does not fit and it does; a header left blank because nothing
    allowed fits is not a failure (fill_form's warning says to hand-write it after printing).

    A line get_form_map lists under `unfillable_lines` is hand-written, so the PDF cannot show it:
    in `expected`, its amount is not compared (the assertion reads SKIPPED and says to hand-write
    it) but IS counted by the relations that add the line — without it, a relation whose printed
    sum includes the line fails and says so. A value found in the shared field itself fails.

    `independent` maps line id -> the amount YOU recomputed via the calc tool over the versioned
    tables (never copied from the form or from your own fill values) — e.g. {"16": 36036, "12": 27700}
    where 36036 came from calc(op="tax", args={"taxable_income": 205150, "filing_status":
    "married_filing_jointly", "year": 2023}) and 27700 from calc(op="standard_deduction", ...).
    This is the no-LLM-arithmetic backstop for the table-lookup lines no relation covers
    (1040 lines 12/16/19/27, 1040-NR 16). When omitted, the recompute does NOT run and the
    report's recompute section says so — relation math alone only proves internal consistency.

    OVERLAY-STAMPED print-only forms (a fill_form result with render_mode "hand_fill_overlay") have
    no AcroForm fields to diff, so the report is the OVERLAY verdict: the worksheet is recomputed
    from `expected` (REQUIRED here — pass the same `values` you gave fill_form), and each line's
    declared box must hold exactly its stamped value (a blank line's box nothing); `independent`
    runs the same recompute over the worksheet's money lines. Read `limits` — it cannot see printed art.

    NO PACK (form='unmapped', with source_url, blank_sha256 and `expected` = fill_form's `written` map; `independent`
    keyed by field name): the UNMAPPED verdict. `ok` is true only when every section passes (the draft's record, a
    round trip of exactly the written fields, nothing else changed from the blank, clipping, flags, the stamp on
    every page, the anchors and their confirmations, the recompute, declared_relations); then `verified_at` names the
    file's sha256 and the time (unsigned; any change to the file voids it). Even with `ok` true the draft is never
    filing-grade: the grade stays "unmapped_draft", every value stays in `unverified_values` with its label, and
    `limits` says what was not checked. A pack's verify_form and verify_filing refuse an unmapped draft.
    """
    if form == UNMAPPED_FORM:
        return _unmapped_verify(year, jurisdiction, pdf_path, expected, independent, source_url, blank_sha256,
                                declared_relations)
    _refuse_unmapped_params("verify_form", form, source_url=source_url, blank_sha256=blank_sha256,
                            declared_relations=declared_relations)
    pack = _load_any_pack(form, year, jurisdiction)
    _refuse_unmapped_draft(pdf_path, "The PDF at pdf_path")
    if isinstance(pack, HandFillPack):
        if expected is None:
            raise ValueError(
                f"verify_form on the print-only '{form}' ({jurisdiction} {year}) needs `expected` — the same "
                f"values dict you passed to fill_form; the worksheet is recomputed from it and each stamped "
                f"value is checked in the PDF's text layer (there are no AcroForm fields to read back)"
            )
        from taxfill_core.overlay import verify_overlay  # lazy: pypdfium2 text layer only on this path

        overlay_report = verify_overlay(pack, pdf_path, expected, independent=independent)
        return _overlay_report_summary(overlay_report, recompute_ran=independent is not None)
    report = _verify_form(pack, pdf_path, expected=expected, independent=independent)
    return _report_summary(report, recompute_ran=independent is not None)


@mcp.tool()
def verify_filing(items: list[dict], independent: dict[str, dict[str, float]] | None = None) -> dict:
    """Verify a whole filing across forms: cross-form identity + inter-form relations.

    Each item: {form, year, pdf_path, jurisdiction?, form_key?}. form_key (defaults to `form`)
    is the key other forms' cross_form rules reference (e.g. 'sched_1', 'sched_oi'). Each form's
    page-header mirrors (e.g. CA Form 540's Sides 2-6 name and SSN) are checked against that
    form's own lines, in the identity section under its form_key.

    `independent` is keyed form_key -> {line id: amount YOU recomputed via the calc tool}, e.g.
    {"f1040": {"16": 36036}} — the per-form shape matches verify_form's `independent`. It is the
    no-LLM-arithmetic backstop for table-lookup lines (1040 line 16 etc.); when omitted, the
    recompute does NOT run and the report's recompute section says so.

    A print-only state return stamped by fill_form (CT ct1040, HI n11, NM pit1, SC sc1040 — a
    `render_mode: "hand_fill_overlay"` result) goes in the same list with one more key,
    `expected`: the values dict given to fill_form. It gets the OVERLAY verdict (verify_form's,
    per item, under the `overlay` section) instead of the AcroForm checks; the filing is ok only
    when every AcroForm item and every stamped item is. A hand-fill form has no fields to read
    back, so it takes no part in the cross-form identity and cross_form checks (`limits` says so).
    An AcroForm item may carry `expected` too, for one purpose: the amounts hand-written on lines
    its get_form_map lists under `unfillable_lines` ({line: amount}), which that form's relations
    then count (verify_form's rule). Each declared amount comes back in `assertions.skipped`
    ("hand-write ..."): relay it, and remember that a declared amount is taken on your word.

    An item whose form is 'unmapped' is refused: an unmapped draft takes no part in a filing's checks — verify it
    alone with verify_form(form='unmapped', ...). A PDF that is an unmapped draft is refused under any form key.
    """
    filing_items, overlay_items = [], []
    for it in items:
        if it.get("form") == UNMAPPED_FORM:
            raise ValueError(
                f"verify_filing item '{it.get('form_key', it['form'])}' has form 'unmapped': an unmapped draft takes "
                f"no part in a filing's pack checks or its cross-form identity checks — verify it alone with "
                f"verify_form(form='unmapped', source_url=..., blank_sha256=..., expected=...) and compare it with "
                f"the other forms on the rendered pages. It is never filing-grade. Nothing was verified."
            )
        jurisdiction = it.get("jurisdiction", "federal")
        pack = _load_any_pack(it["form"], it["year"], jurisdiction)
        form_key = it.get("form_key", it["form"])
        _refuse_unmapped_draft(it.get("pdf_path"), f"verify_filing item '{form_key}' (its pdf_path)")
        if isinstance(pack, HandFillPack):
            if it.get("expected") is None:
                raise ValueError(
                    f"verify_filing item '{form_key}' is the print-only '{it['form']}' ({jurisdiction} {it['year']}) — "
                    f"add `expected`: the values dict you passed to fill_form (a stamped form has no fields to read back)"
                )
            overlay_items.append((form_key, pack, it))
            continue
        # P-036: an AcroForm item's `expected` declares the amounts hand-written on the pack's unfillable lines
        # (get_form_map's `unfillable_lines`), so the relations that add such a line count them.
        item_expected = it.get("expected")
        if item_expected is not None and not isinstance(item_expected, dict):
            raise ValueError(
                f"verify_filing item '{form_key}': `expected` must be a dict of line -> amount (the amounts "
                f"hand-written on the lines get_form_map lists under `unfillable_lines`), got "
                f"{type(item_expected).__name__}"
            )
        declared = {line: float(amount) for line, amount in hand_written_amounts(pack, item_expected).items()}
        filing_items.append(FilingItem(form_key=form_key, pack=pack, pdf_path=Path(it["pdf_path"]), values=declared))
    if not filing_items:
        raise ValueError(
            "verify_filing needs at least one fillable (AcroForm) form — for print-only forms alone, call verify_form "
            "on each stamped PDF"
        )
    acro_keys = {fi.form_key for fi in filing_items}
    stray = sorted(set(independent or {}) - acro_keys - {k for k, _, _ in overlay_items})
    if stray:
        raise ValueError(
            f"independent recompute references unknown form_key(s) {stray} — valid keys are this filing's items' "
            f"form_key values {sorted(acro_keys | {k for k, _, _ in overlay_items})}"
        )
    acro_independent = {k: v for k, v in independent.items() if k in acro_keys} if independent is not None else None
    report = _verify_filing(filing_items, independent=acro_independent)
    summary = _report_summary(report, recompute_ran=independent is not None)
    if overlay_items:
        from taxfill_core.overlay import verify_overlay  # lazy: pypdfium2 text layer only on this path

        checked, fails, limits = 0, [], []
        for form_key, pack, it in overlay_items:
            verdict = verify_overlay(pack, it["pdf_path"], it["expected"], independent=(independent or {}).get(form_key))
            checked += len(verdict.checks) + len(verdict.recompute)
            fails += [f"{form_key}: {c.detail}" for c in verdict.checks if c.status == "FAIL"]
            fails += [f"{form_key}: {c.detail}" for c in verdict.recompute if c.status == "FAIL"]
            limits = verdict.limits
            summary["form_keys"] = [*summary["form_keys"], form_key]
        summary["sections"]["overlay"] = {"checked": checked, "failed": len(fails), "failures": fails}
        summary["ok"] = summary["ok"] and not fails
        summary["limits"] = [
            *limits,
            f"The stamped print-only form(s) {[k for k, _, _ in overlay_items]} took no part in the cross-form identity "
            f"and cross_form checks: a stamped page has no fields to read back — compare their names, SSNs and "
            f"carried amounts against the other forms on the rendered pages.",
        ]
    return summary


@mcp.tool(structured_output=False)
def render_form(pdf_path: str, pages: list[int] | None = None, dpi: float = 170) -> list[Image]:
    """Render PDF pages to PNG images (returned as MCP image content) for vision review.

    `pages` is 1-based; omit to render every page. Vision-review every page before 'done'.
    """
    # Render into a temp dir, return the PNG bytes INLINE, and delete the files on the way
    # out: a filled return's pages are full PII (SSN, wages, address) and must not pile up in
    # the shared temp dir (the 100%-local / no-PII-scatter guarantee). FastMCP base64-embeds
    # the bytes into the response either way, so the on-disk copy is pure residue.
    with tempfile.TemporaryDirectory(prefix="taxfill_render_") as out_dir:
        rendered = _render_pdf(pdf_path, Path(out_dir), pages=pages, dpi=dpi)
        return [Image(data=Path(p.path).read_bytes(), format="png") for p in rendered]


# ── calc / residency ───────────────────────────────────────────────────────────


def _stamp_provisional(result: Any, args: dict[str, Any]) -> Any:
    """Attach the planning-only marker to any result computed off a provisional pack.

    Without this, `calc {op: standard_deduction, year: 2026}` returns $16,100 with a
    Rev. Proc. citation and NOTHING telling the agent it is projection-grade — the
    number is shaped exactly like a filing-grade one. fill_form/verify_form now refuse
    outright (taxfill_core.knowledge.assert_filing_grade), but calc must NOT refuse:
    projections are the whole point of a planning pack. So it answers, and says what
    it answered with.
    """
    if not isinstance(result, dict):
        return result
    year = args.get("year")
    if not isinstance(year, int):
        return result
    jurisdiction = "federal"
    if isinstance(args.get("state"), str):
        jurisdiction = f"states/{args['state'].strip().lower()}"
    marker = provisional_marker(jurisdiction, year)
    if marker is None:
        return result
    result["provisional"] = {
        "status": marker.status,
        "authored": marker.authored,
        "meaning": (
            f"PROJECTION-GRADE ONLY. The {jurisdiction} {year} knowledge pack was authored before "
            f"that year's forms, instructions and Tax Table published, and some blocks are "
            f"deliberately ABSENT (calc fails closed on those rather than inventing figures) — so "
            f"a bottom line built on this year can omit real items (credits, worksheets) that a "
            f"filing-grade year would include. Check the result's assumptions for 'NOT ESTIMATED' "
            f"entries before comparing it against another year. Never put this figure on a filed "
            f"return — fill_form and verify_form refuse it. Label it a PROJECTION to the user."
        ),
        "still_assumed": marker.still_assumed,
    }
    return result


# ── calc describe (Phase K JK32) ───────────────────────────────────────────────
# Claude Code shows a client only the first 4,096 characters of a tool description, so calc's
# description keeps the op list, the PROVISIONAL rule and the rules that change a number; each
# op's argument list and full notes (its former per-op docstring bullet, verbatim) are served by
# calc(op="describe", args={"op": "<name>"}). estimate_refund's former docstring is served the same
# way under the name "estimate_refund". The keys are the dispatch's ops (a test holds them equal).
_CALC_OP_DOCS: dict[str, str] = {
    "tax": (
        "args {taxable_income, filing_status, year} (ORDINARY line 16 only — with qualified\n"
        "  dividends or capital gains use tax_with_preferential_rates instead, even below $100,000)"
    ),
    "tax_with_preferential_rates": (
        "args {taxable_income, qualified_dividends, net_long_term_gain?,\n"
        "  net_short_term_gain?, filing_status, year} (Qualified Dividends and Capital Gain Tax Worksheet)"
    ),
    "standard_deduction": (
        "args {filing_status, year, age_65_plus?, blind?}"
    ),
    "se_tax": (
        "args {net_profit, year, w2_ss_wages?} (w2_ss_wages = W-2 box 3+7, Schedule SE lines 8a-9)"
    ),
    "additional_medicare_tax": (
        "args {medicare_wages, filing_status, year, se_net_profit?} (Form 8959)"
    ),
    "niit": (
        "args {net_investment_income, magi, filing_status, year} (Form 8960; NRAs exempt)"
    ),
    "taxable_social_security": (
        "args {benefits, other_income, tax_exempt_interest?, filing_status,\n"
        "  year, mfs_lived_with_spouse?} (SS Benefits Worksheet -> the Form 1040 taxable-benefits line, named in the work)"
    ),
    "excess_ss": (
        "args {withheld_by_employer: [per-employer W-2 box 4, ONE person], year}\n"
        "  (Schedule 3 excess-SS credit; multiple employers only)"
    ),
    "student_loan_interest_deduction": (
        "args {interest_paid, magi, filing_status, year} (MFS gets $0)"
    ),
    "education_credits": (
        "args {aotc_expenses_per_student: [...], llc_expenses?, magi, filing_status,\n"
        "  year} (Form 8863 AOTC + LLC; MFS gets $0)"
    ),
    "ptc_annual": (
        "args {household_income, household_size, annual_premiums, annual_slcsp, annual_aptc?,\n"
        "  filing_status, year, state?, mfs_relief_exception?} (Form 8962 annual method; state in\n"
        "  other|alaska|hawaii; 2023-2026 — 2026 brings the 400% CLIFF back (over 400% FPL: no PTC) and NO repayment\n"
        "  limitation at any income (JT1a). MFS gets PTC $0 by rule — IRC 36B(c)(1)(C) — unless\n"
        "  mfs_relief_exception claims the domestic-abuse/abandonment relief; below-100%-FPL with no APTC\n"
        "  also gets $0)"
    ),
    "ptc_monthly": (
        "args {household_income, household_size, monthly: [12 x {premium, slcsp, aptc}],\n"
        "  filing_status, year, state?, annual_aptc?, mfs_relief_exception?} (Form 8962 MONTHLY method —\n"
        "  the lines 12-23 grid for part-year/month-varying coverage; monthly rows are the 1095-A lines\n"
        "  21-32 columns A/B/C, EXACTLY 12 entries with uncovered months as zeros; annual_aptc (line 33C)\n"
        "  is an optional cross-check. Same eligibility gates and years as ptc_annual)"
    ),
    "child_tax_credit": (
        "args {qualifying_children_ssn, other_dependents, magi, income_tax_before_credits,\n"
        "  earned_income, filing_status, year, children_under_6?} (Schedule 8812: nonrefundable CTC/ODC for\n"
        "  1040 line 19 + refundable ACTC for line 28; income_tax_before_credits = the Credit Limit Worksheet\n"
        "  amount, i.e. line 18 tax minus earlier Schedule 3 credits; 2021 uses the ARPA expanded\n"
        "  fully-refundable rules with children_under_6 driving the $3,600 tier)"
    ),
    "eitc": (
        "args {earned_income, agi, qualifying_children, filing_status, year, investment_income?}\n"
        "  (the EIC Table's figure: every cell of the printed 2019-2026 tables reproduces)\n"
        "  (earned income credit for 1040 line 27 by the Rev. Proc. formula; investment-income and MFS\n"
        "  gates; phases out on the GREATER of AGI or earned income; the printed EIC table's $50 bands can\n"
        "  differ by ~$27)"
    ),
    "dependent_care_credit": (
        "args {expenses, qualifying_persons, earned_income, spouse_earned_income?,\n"
        "  agi, filing_status, year, employer_benefits?} (Form 2441 -> Schedule 3's dependent-care line: caps\n"
        "  $3,000/$6,000 by persons count (2021: $8,000/$16,000), minus employer benefits (W-2 box 10),\n"
        "  limited by the LOWER earned income — spouse_earned_income REQUIRED for MFJ; the AGI slide\n"
        "  35%->20% (2021: 50%->20%->0%, zero over $438,000; 2026: 50%->35%->20%, the second leg over $150,000\n"
        "  in $4,000 steps joint / over $75,000 in $2,000 steps otherwise); MFS gets $0 by rule; refundable for 2021\n"
        "  only if the US-abode test is met — that test and the deemed $250/$500 student/disabled-spouse\n"
        "  income are YOUR judgment, per the work string)"
    ),
    "treaty_benefit": (
        "args {country, income_class, amount, visa_periods?, year?, years_in_status?,\n"
        "  resident_alien?} (validate a tax-treaty exemption from the per-country\n"
        "  treaty packs — china, india, korea, canada, mexico; income_class in student_wages | scholarship |\n"
        "  payments_from_abroad | teacher_wages | other_income. Student wage limits are treaty-fixed (China\n"
        "  $5,000/yr, Korea $2,000/yr; India gets Art. 21(2) standard-deduction parity instead — no exclusion;\n"
        "  Canada/Mexico have no student wage benefit, only the researched employment de-minimis / 183-day\n"
        "  shapes). teacher_wages requires years_in_status (India's 2-year window is a RETROACTIVE clawback\n"
        "  — exceed it and the whole visit's exemption is lost). other_income answers the bank-bonus /\n"
        "  1099-MISC box 3 corner from the verbatim Other Income article: in ALL five treaties US-arising\n"
        "  other income stays US-taxable — Schedule NEC at the statutory 30%, no treaty reduction (Korea\n"
        "  verifiably has NO other-income article; Art. 4's source rule applies). Returns the exempt/taxable\n"
        "  split + article + citation; final eligibility (visa period, purpose, saving clause) stays YOUR\n"
        "  judgment — record the position with the returned citation. WHERE the exempt amount is reported\n"
        "  turns on residency (P-016), so pass resident_alien: false -> Schedule OI item L and the Form\n"
        "  1040-NR treaty-exempt line; true -> a resident alien's saving-clause claim, entered in\n"
        "  parentheses on Schedule 1's other-income line with 'Exempt income', the country and the article\n"
        "  (Pub 519 ch. 9), paired with the income on its usual line when an information return reported it\n"
        "  as taxable; omitted -> both, conditionally. When the applied article has NO saving-clause\n"
        "  exception in the pack (Canada Art. XV's de-minimis), the work says a resident generally cannot\n"
        "  claim it. The work names the year's line numbers; year only picks them — a year with no form_lines\n"
        "  keeps the split and names the line in words)"
    ),
    "schedule_1a_deductions": (
        "args {magi, filing_status?, year?, qualified_tips?, qualified_overtime?,\n"
        "  car_loan_interest?, seniors_qualifying?} (the four OBBBA Schedule 1-A deductions, TY2025-2028 —\n"
        "  the Schedule 1-A total -> the Form 1040 / 1040-NR Schedule 1-A line (each read off the year's face and\n"
        "  named in the work), reduces taxable income whether itemizing or not.\n"
        "  ONE MAGI (AGI + PR-excluded income + Form 2555 lines 45/50 + Form 4563 line 15) feeds all four\n"
        "  parts. TRAPS the op enforces: tips/overtime/senior are FORFEITED on married-filing-separately\n"
        "  (car-loan interest is NOT); the tips $25,000 cap is PER RETURN (a joint return does not double\n"
        "  it); the phase-out rounding is ASYMMETRIC (tips/overtime $100 per $1,000 of excess rounded DOWN,\n"
        "  car loan $200 per $1,000 rounded UP, senior 6% of excess per person); qualifying surviving spouse\n"
        "  takes the OTHER thresholds (each statute keys on 'a joint return'). qualified_overtime is the FLSA\n"
        "  premium HALF only, never the whole overtime wage. Eligibility stays YOUR judgment, quoted in the\n"
        "  work: tipped-occupation list, new-vehicle/US-assembly/VIN rules, valid SSNs, seniors 65 by year end\n"
        "  (the year's senior_deduction.born_before: born before January 2 of year - 64). 2025 and 2026 ship)"
    ),
    "charitable_deduction": (
        "args {year, filing_status, gifts: [{amount, cash?, donee?, teos_code?,\n"
        "  donee_170b1a?, donor_advised_fund?, benefit? (none|membership|token_items|recognition_only|goods_or_services),\n"
        "  benefit_value?, written_acknowledgment?}...], agi, other_itemized?, standard_deduction_amount?} (JF9, 2026\n"
        "  onward: IRC 170(p) for a non-itemizer — cash to a 170(b)(1)(A) organization (TEOS PC/POF/FED), never a\n"
        "  509(a)(3) supporting organization (SO/SONFI/SOUNK) or a donor advised fund, capped $1,000 / $2,000 joint, no\n"
        "  floor — and the 170(b)(1)(I) 0.5%-of-AGI floor for an itemizer; returns each gift's deductible amount, the\n"
        "  substantiation duties (the 170(f)(8) acknowledgment at $250, the 170(f)(17) record) and the better path.\n"
        "  P-022 characterization: recognition only is no benefit; a membership for $75 or less is disregarded; token\n"
        "  items and benefits within 2% or $139 are insubstantial; otherwise the benefit's value comes off, and a\n"
        "  payment over $75 whose benefit value you do not state is REFUSED — ask for the organization's IRC 6115\n"
        "  statement)"
    ),
    "withholding_projection": (
        "args {employers: [{label, pay_frequency, wages_per_period, pay_dates? |\n"
        "  first_pay_date?, employment_end?, first_period_wages?, fica_wages_per_period?, w4?: {form (2020_or_later |\n"
        "  pre_2020), filing_status, step2_checkbox, step3_credits, step4a_other_income, step4b_deductions,\n"
        "  step4c_extra_per_period, allowances, marital_pre_2020, additional_pre_2020, exempt}, nonresident_alien?,\n"
        "  withheld_prior_year?, supplemental?: [{date, amount, concurrent_with_regular?, separately_stated?}],\n"
        "  fica_exempt?, method? (percentage | cumulative | part_year), written_request?, ...}], year} (JP1c, 2026:\n"
        "  Pub 15-T Worksheet 1A check by check, counted by PAY DATE; a bonus under Treas. Reg. 31.3402(g)-1 — the flat\n"
        "  22% only when not concurrent-or-separately-stated AND tax was withheld on regular wages this year or last,\n"
        "  else the aggregate procedure; both as a range when a fact is unknown or the reading is interpretive; 37%\n"
        "  over $1,000,000; box 4 / box 6 per employer. Returns w2s ready for estimate_refund's IncomeSnapshot.w2s)"
    ),
    "employee_fica": (
        "args {wage_segments: [{wages, fica_exempt, label?, employer?, visa_status?,\n"
        "  exempt_basis?}...], year?, residency_classification?, filing_status?} (JP1a: two layers —\n"
        "  WITHHOLDING per employer (each applies its own wage base and IRC 3102(f)(1)'s 0.9% on \"wages from\n"
        "  the employer in excess of $200,000\"; segments without an employer are one employer's) and, with\n"
        "  filing_status, the person's LIABILITY (one base; the 0.9% over the Form 8959 status threshold);\n"
        "  excess_ss_credit and additional_medicare_reconciliation are the differences. Employee-side payroll\n"
        "  FICA across STATUS periods — the\n"
        "  projection op for a year where FICA switches on mid-year, e.g. F-1 OPT (a NONRESIDENT exempt\n"
        "  individual, NO FICA) -> H-1B (FICA from the I-797 start date). fica_exempt is YOUR status judgment\n"
        "  per segment; the traps the work quotes: the F/J exemption is STATUS-based, not marital — a\n"
        "  §6013(g) election does NOT start FICA on an exempt F/J spouse's wages — and it is a NONRESIDENT\n"
        "  exemption: Pub 519 ch. 8, FICA is withheld \"if you are considered a resident alien ... even though\n"
        "  your nonimmigrant classification (\"F,\" \"J,\" \"M,\" or \"Q\") remains the same\". Pass\n"
        "  residency_classification (resident | nonresident | dual_status_candidate, from the residency\n"
        "  tool — under a §6013(g)/(h) election pass its classification_without_election, since the\n"
        "  election reaches chapter 1 and chapter 24 only, IRC 6013(g)(1)): for 'resident', a fica_exempt F/J/M/Q segment (visa_status, or a label naming it as F-1/J-1/OPT)\n"
        "  is REFUSED unless exempt_basis names a different exemption (student_employed_by_school —\n"
        "  Pub 519's tip for a student enrolled and regularly attending classes at the school it works for —\n"
        "  or totalization_agreement). Enforces the SS wage base across one employer's segments in order,\n"
        "  Medicare with no base, and the 0.9% Additional Medicare withholding over $200,000 per employer)"
    ),
    "estimated_tax_safe_harbor": (
        "args {projected_tax, expected_withholding, filing_status?, year?,\n"
        "  prior_year_agi?, prior_year_total_tax?, excess_ss_credit?, additional_medicare_withheld?,\n"
        "  refundable_credits?, prior_year_refundable_credits?, remaining_pay_dates? (JP1a: returns\n"
        "  step_4c_per_check, the Form W-4 Step 4(c) amount per remaining paycheck that reaches the required\n"
        "  payment)} (JF4: the excess-SS credit counts as\n"
        "  withholding, IRC 31(b)(1); refundable credits (the prior year's too, off prior_year_total_tax, per\n"
        "  the Form 2210 instructions) and the Additional Medicare Tax withheld come off the tax, IRC\n"
        "  6654(f)(4) and (m) — so\n"
        "  pass expected_withholding WITHOUT that box-6 excess; the work quotes 6654(g)(1)'s ratable\n"
        "  deeming of withholding. IRC 6654(d): required annual payment = min(90% of the\n"
        "  current year's tax, 100% of the prior year's — 110% when PRIOR-year AGI > $150,000/$75,000-MFS,\n"
        "  the status test keyed on the CURRENT year). Supply prior_year_agi AND prior_year_total_tax\n"
        "  together (the prior return's AGI and total-tax lines, named in the work — intake stores them on\n"
        "  prior_filings) or omit both; the\n"
        "  prior prong needs a 12-month prior return (your judgment). Reports the $1,000 de-minimis, the\n"
        "  shortfall and the quarterly installment; the work quotes the supplemental-wage (bonus) trap WITH\n"
        "  its precondition (P-017): the flat 22% is the employer's OPTION only when Treas. Reg.\n"
        "  31.3402(g)-1(a)(7)(i) holds — the bonus is not paid concurrently with regular wages or is separately\n"
        "  stated on the payroll records, AND income tax was withheld from regular wages this calendar year\n"
        "  or last; otherwise the aggregate procedure is required (Pub 15: \"use method 1b\" — bonus + regular\n"
        "  wages withheld as one payment under the W-4); 37% is mandatory only on supplemental wages over\n"
        "  $1,000,000. Hire status is not the test; project the bonus withholding by the method the employer\n"
        "  actually uses — at the flat rate a higher-bracket filer under-withholds on every bonus)"
    ),
    "underpayment_penalty": (
        "args {required_installments? (the four Form 2210 line-10 amounts) |\n"
        "  required_annual_payment? (25% each, IRC 6654(d)(1)(A) — take it from estimated_tax_safe_harbor),\n"
        "  payments?: [{date, amount}] (estimated payments, a prior-year overpayment dated the first due date,\n"
        "  the balance paid with the return), withholding? (deemed paid in equal parts on the four due dates,\n"
        "  IRC 6654(g)(1)) | withholding_dates?: [{date, amount}] (the actual-dates election, all amounts),\n"
        "  tax_after_withholding? (under $1,000 = the 6654(e)(1) exception), return_filed?,\n"
        "  paid_in_full_with_return? (by January 31 = no 4th-installment penalty, 6654(h)), annualized? (JP5b,\n"
        "  Schedule AI: {filing_status, agi: [4 cumulative periods], standard_deduction, itemized?, qbi?,\n"
        "  additional_deductions? (Schedule 1-A), se_net_earnings? (line 28), ss_wages?, other_taxes?, credits?,\n"
        "  period_tax?} — with required_annual_payment; prices both methods and reports regular_method_penalty),\n"
        "  year} (JP5a: Form\n"
        "  2210 Part III regular method — payments credited to the earliest unpaid installment (6654(b)(3)),\n"
        "  each late portion priced per day to the payment date or April 15 at the rate period's IRC 6621\n"
        "  underpayment rate over 365 (the year's knowledge calendar; April 1-15 keeps the Q1 rate, 6621(b)(2)(B));\n"
        "  a period whose rate is not announced yet FAILS CLOSED. Returns the Section A columns, the priced\n"
        "  pieces and line 19)"
    ),
    "paystub_to_w2": (
        "args {stub: the extract_document('paystub') reading, employment: the Profile.employment\n"
        "  record (employer, end?, pay_frequency, first_pay_date, gross_per_period, deductions_per_period), year,\n"
        "  remaining_pay_dates?} (JP3b: the stub's YTD actuals plus the checks still to be PAID on or before\n"
        "  December 31 — \"The entries on Form W-2 must be based on wages paid during the calendar year\", so a check\n"
        "  paid January 1 is next year's; an ended job adds nothing, nothing is annualized. Box 1 = gross - pre-tax\n"
        "  401(k) - the cafeteria-plan reductions (IRC 125 premiums, HSA code W, health and dependent care FSA,\n"
        "  132(f)); boxes 3/5 exclude only the cafeteria-plan reductions, box 3 capped at the wage base; boxes 4/6\n"
        "  at this employer's own rates; box 10; box 12 D/AA/W. Returns w2 ready for estimate_refund's\n"
        "  IncomeSnapshot.w2s)"
    ),
    "claim_of_right_repayment": (
        "args {repaid, year, prior_year, taxable_income (this year, WITHOUT the\n"
        "  deduction), prior_taxable_income (as filed, WITH the item), filing_status?, prior_filing_status?,\n"
        "  income_type? (wages | unemployment | other_nonbusiness | business | capital_gain),\n"
        "  included_under_claim_of_right?, taxable_income_with_deduction?, and the four tax overrides\n"
        "  tax_without_deduction? / tax_with_deduction? / prior_tax_as_filed? / prior_tax_refigured?} (JP4, pitfall\n"
        "  P-025: IRC 1341 / Pub 525 Methods 1 and 2 — the lesser tax; nothing at $3,000 or less; a business or\n"
        "  capital repayment goes on its own schedule. Returns the destination line (Schedule A / Schedule 3, read\n"
        "  per year) and the payroll-tax notes: FICA back from the employer or Form 843, Additional Medicare Tax\n"
        "  only on a prior-year Form 1040-X)"
    ),
    "annualize_ytd": (
        "args {ytd_amount, through, year} (project a YTD paystub figure to full-year by\n"
        "  calendar-day proration — the deterministic home for the one arithmetic step every projection\n"
        "  needs. ASSUMES LEVEL PAY: annualize each status segment separately, never annualize one-time\n"
        "  amounts like bonuses/RSU vests)"
    ),
    "ira_net_income_attributable": (
        "args {amount, purpose (recharacterization | returned_contribution),\n"
        "  opening_fmv, contributions_during (every contribution INTO the IRA in the period, the one being moved\n"
        "  included), closing_fmv, distributions_during?, whole_account?} (JR2a: Treas. Reg. 1.408A-5 A-2(c) /\n"
        "  1.408-11 — net income = amount x (adjusted closing - adjusted opening) / adjusted opening, divided\n"
        "  EXACTLY and also with Pub 590-A's three-place ratio; negative after a loss; the whole-account rule)"
    ),
    "ira_recharacterization": (
        "args {direction (roth_to_traditional | traditional_to_roth), amount,\n"
        "  contribution_year, contribution_date, contributed_total?, transfer_date?, source_kind?, deducted?, the NIA\n"
        "  inputs (opening_fmv, contributions_during, closing_fmv, distributions_during?, whole_account?),\n"
        "  extension_filed?, return_filed_date?, magi?, filing_status?, covered_by_employer_plan?,\n"
        "  elect_nondeductible?, readings?, then_convert?} (JR2b, P-021: the fix for an ineligible contribution.\n"
        "  REFUSES a conversion (408A(d)(6)(B)(iii)), a rollover (A-4), SEP/SIMPLE employer money (A-5) and a\n"
        "  deducted amount; returns the net income, the deadline status (timely / late under 301.9100-2 with an\n"
        "  amended return / too late), 1099-R code N (moved in the contribution year: the Form 1040 IRA-distribution line) or R (later:\n"
        "  the statement only), the second IRA's limit check, the Form 8606 line 1/4/6 inputs (net income is never\n"
        "  basis), the i8606 statement, the expected 1099-R/5498 boxes with a +/- $1 reconciliation, the A-6(a)\n"
        "  trustee notice, the 408(d)(4) alternative (no 10% additional tax on its earnings: 72(t)(2)(A)(ix)) and\n"
        "  then_convert priced by roth_conversion with the new basis)"
    ),
    "elective_deferral_room": (
        "args {deferrals: [{employer, elective_deferrals, employer_contributions?,\n"
        "  after_tax_contributions?}...], year?, age? (at year end), remaining_pay_dates?, per_check_compensation?,\n"
        "  plan_increment_percent?, prior_year_fica_wages?, current_employer?} (JP2: the IRC 402(g) room left\n"
        "  ACROSS EVERY EMPLOYER — a job-changer's new plan cannot see the old plan's deferrals — with the\n"
        "  414(v) catch-up by age (50+; the higher 60-63 amount), the per-check dollars and percent rounded DOWN\n"
        "  so the last check never overshoots, any excess with its April 15 correction deadline (\"not postponed\n"
        "  by extending the filing\") and the double tax if it stays, the SECURE 2.0 Roth catch-up wage test\n"
        "  (414(v)(7)(A)), and each plan's 415(c) annual-additions room)"
    ),
    "contribution_limits": (
        "args {year?} (every tax-advantaged bucket WITH ITS SCOPING — the real\n"
        "  answer to \"is the 401(k) limit one per person?\": 402(g) per PERSON across all employers with\n"
        "  traditional+Roth sharing it; 415(c) per EMPLOYER PLAN (the mega-backdoor door); IRA per person\n"
        "  across both kinds; HSA per COVERAGE TIER (two self-only holders can beat one family plan);\n"
        "  125(i) FSA per employee per employer; 132(f) commuter monthly. Quote the scoping strings)"
    ),
    "ira_contribution_eligibility": (
        "args {magi, filing_status?, year?, ira_type?: roth|\n"
        "  traditional_deduction, contributed?, age_50_plus?, covered_by_employer_plan?,\n"
        "  spouse_covered_by_employer_plan?, mfs_lived_apart_all_year?, roth_ira_dec31_value?} (the Pub\n"
        "  590-A reduced-limit worksheet: round UP to $10, $200 floor while partially phased. Run it\n"
        "  BEFORE any IRA contribution is recorded — it catches the 6%/yr-excise error (IRC 4973) and\n"
        "  shows the year-end-status rule: the same MAGI can be excess under one status and compliant\n"
        "  under another (e.g. MFS vs MFJ), because eligibility follows the Dec 31 filing status. The\n"
        "  deduction path needs the employer-plan coverage facts; no coverage anywhere = no phase-out.\n"
        "  On that path `allowed` is the most that can be deducted and the result splits the contribution\n"
        "  into `deductible` and `nondeductible` (Form 8606 line 1 basis): a traditional contribution\n"
        "  within the limit is never an excess — IRC 4973(b) ignores the 219(g) phase-out — so `excess` is\n"
        "  only the amount over the contribution limit, which recharacterizing cannot cure. A separate\n"
        "  filer passes spouse_covered_by_employer_plan too, or mfs_lived_apart_all_year (IRC 219(g)(4):\n"
        "  the single rules).\n"
        "  roth_ira_dec31_value (Roth only: all Roth IRAs' Dec 31 value, that year's contributions made\n"
        "  the next year included) applies IRC 4973(a)'s cap — the excise \"shall not exceed 6 percent of\n"
        "  the value of the account\" — so excise = 6% x min(excess, value). The work names the fix's\n"
        "  deadline: withdraw the excess plus its net income by the return's due date INCLUDING\n"
        "  extensions (IRC 408(d)(4)) — the year's April due date, or October 15 with a Form 4868\n"
        "  extension — and, for a return filed on time without it, the Form 5329 instructions' 6 months\n"
        "  after the due date excluding extensions, on an amended return \"Filed pursuant to section\n"
        "  301.9100-2\")"
    ),
    "marginal_dollar_savings": (
        "args {taxable_income, ss_wages + medicare_wages (W-2 boxes 3 + 7 and\n"
        "  box 5; the older one-figure `wages` stands in for both, disclosed), filing_status?, year?} (\"where does one\n"
        "  more pre-tax dollar save the most\": payroll HSA/FSA/commuter dollars avoid income tax AND FICA;\n"
        "  401(k)/deductible-IRA dollars avoid income tax only; ABOVE the SS wage base the FICA saving is\n"
        "  1.45%+0.9% over $200k, never 7.65%. Federal only — state rates stack; Roth saves $0 today by\n"
        "  design)"
    ),
    "magi_ladder": (
        "args {agi, filing_status?, year?, medicare_wages? (W-2 box 5, the 8959 row; the older\n"
        "  wages? stands in, disclosed), foreign_earned_income_exclusion?,\n"
        "  excluded_puerto_rico_income?} (every MAGI test the year's packs carry, one table — because MAGI\n"
        "  is not one number: NIIT adds back the FEIE, Additional Medicare is a WAGE test that AGI cannot\n"
        "  move, Schedule 1-A / Roth-IRA / deductible-IRA each define their own. Show it when the user asks\n"
        "  why their MAGI differs from their salary; every planning lever moves a number on this ladder.\n"
        "  A qualifying surviving spouse buckets differently on the two surtaxes: Form 8959's $200,000\n"
        "  (\"Single, Head of household, or Qualifying surviving spouse\"), NIIT's joint $250,000 (IRC\n"
        "  1411(b)(1): \"a surviving spouse (as defined in section 2(a))\"))"
    ),
    "ira_pro_rata": (
        "args {dec31_total_value, amount_converted?, other_distributions?,\n"
        "  nondeductible_basis_carryforward?, nondeductible_contributions_this_year?,\n"
        "  contributions_made_after_year_end?, year?} (Form 8606 Part I / IRC 408(d)(2): ALL traditional +\n"
        "  SEP + SIMPLE IRAs are ONE contract and a year's distributions ONE distribution, so a\n"
        "  conversion's taxable share is set by the POOL's pretax/basis mix, never by which dollars moved.\n"
        "  THE TRAP: the DENOMINATOR is line 9 = line 6 (Dec-31 value of every such IRA, measured AFTER the\n"
        "  conversion left) + line 7 (distributions not converted) + line 8 (the amount converted) — it\n"
        "  ADDS THE CONVERSION BACK, so converting more never shrinks it. dec31_total_value is the whole\n"
        "  answer to \"where can my old 401(k) go?\": rolled into a traditional IRA it lands on line 6\n"
        "  whenever in the year it arrives and makes every future backdoor Roth mostly taxable. Basis is\n"
        "  per PERSON (the form is filed separately per spouse), and line 4 — a contribution made Jan\n"
        "  1-Apr 15 of the NEXT year — is basis that carries forward but cannot be used in this year's\n"
        "  ratio. Returns the taxable/nontaxable split, the basis applied and carried, the ratio, and every\n"
        "  8606 line)"
    ),
    "roth_conversion": (
        "args {source: plan_to_roth_ira|traditional_ira_to_roth, amount,\n"
        "  taxable_income_before, magi_before, filing_status?, year?, net_investment_income?,\n"
        "  plan_after_tax_basis?, dec31_total_value?, nondeductible_basis_carryforward?,\n"
        "  nondeductible_contributions_this_year?, other_distributions?,\n"
        "  contributions_made_after_year_end?} (price a conversion on the ONE path the money takes — the\n"
        "  two paths are taxed differently and get conflated. plan_to_roth_ira = a DIRECT rollover from a\n"
        "  401(k)/403(b)/governmental 457(b) to a Roth IRA (Notice 2008-30): taxable is the pretax portion,\n"
        "  pro-rata NEVER applies because no traditional IRA is involved, it is reported on 1040 line 5a/5b\n"
        "  not Form 8606 — this is the path that clears an old plan WITHOUT poisoning future backdoor\n"
        "  Roths; pass plan_after_tax_basis from 1099-R box 5 (the plan's own allocation under Notice\n"
        "  2014-54, never your estimate). traditional_ira_to_roth = pro-rata applies and the split is\n"
        "  delegated to ira_pro_rata, which needs dec31_total_value. Supplying IRA args on the plan path is\n"
        "  REFUSED — that conflation is the whole reason the op makes you choose. Beyond the taxable\n"
        "  amount it returns BRACKET HEADROOM (room below the current bracket's top, and exactly which\n"
        "  dollars spill into higher rates, from the year's rate_schedules) and the NIIT CROSSING (IRC\n"
        "  1411(c)(5): the conversion is NEVER net investment income, but it raises MAGI and can drag\n"
        "  OTHER investment income over the 1411 threshold — computed by reusing the niit op). The work\n"
        "  carries the WITHHOLDING warning: tax withheld is not converted, it is lost Roth space and the\n"
        "  10% additional tax can reach it under 59 1/2 — pay from OUTSIDE funds; plus the\n"
        "  no-recharacterization-after-2017 irreversibility and the per-conversion 5-year clock)"
    ),
    "hsa_deduction": (
        "args {coverage: self_only|family (or monthly_coverage: 12 entries, January\n"
        "  first, each self_only|family|none), year?, months_eligible?, age_55_plus?, married?,\n"
        "  spouse_has_separate_hsa?, your_share_of_family_limit?, personal_contributions?,\n"
        "  employer_contributions?, qualified_hsa_funding_distribution?, archer_msa_contributions?,\n"
        "  medicare_start_month?, health_fsa?, claimed_as_dependent_by_another?, testing_period_failed?,\n"
        "  funding_distribution_testing_period_failed?, distributions_total?, distributions_rolled_over?,\n"
        "  qualified_medical_expenses?, distributions_excepted_from_20_percent?, ss_wages?, medicare_wages?,\n"
        "  filing_status? (the payroll half: W-2 boxes 3 + 7 and 5, the 0.9% tier on the filing status's Form\n"
        "  8959 threshold; the older wages? stands in for both boxes), wages?} (Form 8889 /\n"
        "  IRC 223 — the op that makes an HSA contribution FILEABLE, not just plannable. FOUR TRAPS it\n"
        "  enforces. (1) The limit is MONTHLY: 223(b)(1)-(2) tests eligibility on the FIRST DAY of each\n"
        "  month and allows 1/12 of the tier amount per eligible month, so a mid-year HDHP start gets the\n"
        "  Line 3 Limitation Chart, never the annual figure — pass monthly_coverage whenever the tier\n"
        "  changed or the eligible months are not the closing ones. (2) THE LAST-MONTH RULE (223(b)(8)) is\n"
        "  automatic, not an election: eligible on December 1 makes line 3 the GREATER of the chart and\n"
        "  December's full annual tier amount, and it starts a 13-MONTH TESTING PERIOD (Dec 1 through Dec\n"
        "  31 of the FOLLOWING year). Losing eligibility inside it — new job, spouse's non-HDHP plan,\n"
        "  Medicare; only death or disability is excused — pulls the extra contributions into income PLUS\n"
        "  a 10% additional tax. The result always reports at_risk_if_testing_period_fails, so quote it\n"
        "  before anyone contributes the bigger number. (3) EMPLOYER MONEY IS NOT A SECOND DEDUCTION: W-2\n"
        "  box 12 code W is the employer's contributions AND the employee's own cafeteria-plan payroll\n"
        "  deferrals, all already excluded from box 1 — it goes in employer_contributions (line 9), where\n"
        "  it SUBTRACTS room; only DIRECT contributions (line 2 = 5498-SA box 2 minus code W minus any\n"
        "  funding distribution) reach Schedule 1's HSA-deduction line. Deducting code W as well is the most\n"
        "  common HSA filing error. (4) A GENERAL-PURPOSE HEALTH FSA — INCLUDING ONE FROM THE SPOUSE'S\n"
        "  EMPLOYER (Rev. Rul. 2004-45) — is disqualifying coverage; health_fsa='general_purpose' is\n"
        "  REFUSED with the fix, while 'limited_purpose' (dental/vision) and 'post_deductible' are fine.\n"
        "  Also: 223(b)(7) zeroes every month from the first month of Medicare entitlement onward\n"
        "  (retroactive enrollment included); the $1,000 age-55 catch-up is statutory, PER PERSON and not\n"
        "  allocable, so a couple needs TWO HSAs for two catch-ups and it rides line 7 (not line 3) once a\n"
        "  married filer has ANY family coverage in the year; excess contributions carry the IRC 4973 6%\n"
        "  excise EVERY year until withdrawn (plus earnings) by the due date INCLUDING extensions. Part II\n"
        "  distributions (1099-SA box 1) and their 20% additional tax and Part III recapture are modelled;\n"
        "  pass wages to get the payroll-vs-direct FICA half, where above the SS wage base the saving is\n"
        "  1.45%, or 2.35% over $200k — never 7.65%)"
    ),
    "espp_disposition": (
        "args {shares, grant_date, purchase_date, sale_date, grant_date_fmv_per_share,\n"
        "  purchase_date_fmv_per_share, purchase_price_per_share, sale_price_per_share,\n"
        "  grant_date_exercise_price_per_share?, broker_reported_basis?, broker_reported_basis_to_irs?,\n"
        "  selling_expenses?, employed_through_exercise?} (ONE lot of section 423 ESPP stock, sold —\n"
        "  Form 3922 boxes 1-8 in, the Form 8949 row out. THE TWO DISPOSITIONS ARE TAXED COMPLETELY\n"
        "  DIFFERENTLY and conflating them is the point of the op. QUALIFYING (sold MORE than 2 years\n"
        "  after grant AND more than 1 year after purchase, IRC 423(a)(1)): ordinary income is the LESSER\n"
        "  of the discount measured on the GRANT-date price (423(c)(2)) and the actual gain (423(c)(1)) —\n"
        "  so a sale at a LOSS recognises ZERO ordinary income. DISQUALIFYING (anything else, same-day\n"
        "  sale included): ordinary income is the FULL spread at purchase, exercise-date FMV minus the\n"
        "  price paid, REGARDLESS of the sale price — Pub 525, 'This ordinary income isn't limited to your\n"
        "  gain from the sale of the stock' — so a filer who sold below the purchase-date FMV still\n"
        "  recognises it and takes a capital LOSS on top. THE BASIS CORRECTION IS THE HIGHEST-DOLLAR PART:\n"
        "  the 1099-B reports box 1e as the DISCOUNTED PURCHASE PRICE ONLY (Instructions for Form 8949,\n"
        "  'For compensatory options granted after 2013, the basis information reported to you ... won't\n"
        "  reflect any amount you included in income'), so a filer who trusts it pays tax on the discount\n"
        "  TWICE. The op returns the corrected basis (price paid + ordinary income), the adjustment, and\n"
        "  the exact Form 8949 row: CODE B in column (f), with the wrong basis left in column (e) and the\n"
        "  correction in column (g) as a negative when the basis WAS reported to the IRS (box A/D), or the\n"
        "  correct basis straight into column (e) with -0- in (g) when it was not (box B/E). THE LOOKBACK:\n"
        "  under a lookback the price paid is the discount off the LOWER of the two FMVs, but 423(c)(2) is\n"
        "  computed on the GRANT-date price — Form 3922 BOX 8, a different number whenever the stock fell.\n"
        "  Pass grant_date_exercise_price_per_share whenever box 8 is filled in; a price below 85% of the\n"
        "  grant-date FMV with no box 8 is REFUSED, because only a lookback can produce it. Nothing is\n"
        "  withheld on any of this income (IRC 423(c) and 421(b) both say so, and IRC 3121(a)(22) keeps it\n"
        "  out of FICA) — plan the cash. NOT modelled and named in `not_modeled`: ISO/AMT (Form 3921,\n"
        "  Form 6251 line 2i, and 422(c)(2)'s realised-gain cap that section 423 has no counterpart for),\n"
        "  section 83(b), RSU vesting, wash sales, state tax, multiple lots)"
    ),
    "capital_loss_limitation": (
        "args {short_term, long_term, taxable_income_before_capital_loss,\n"
        "  filing_status?, year?, short_term_carryover_in?, long_term_carryover_in?, following_years?}\n"
        "  (IRC 1211(b)/1212(b) and the Schedule D Capital Loss Carryover Worksheet. Short and long are\n"
        "  netted SEPARATELY first (lines 7 and 15, IRC 1222) and only then against each other (line 16);\n"
        "  a net loss is deductible against ordinary income only up to $3,000 ($1,500 MFS), statutory and\n"
        "  NOT indexed; everything left carries forward INDEFINITELY and KEEPS ITS CHARACTER — a\n"
        "  short-term carryover stays short-term (1212(b)(1)(A)) and lands on next year's Schedule D line\n"
        "  6, a long-term one on line 14. THE SUBTLETY THAT IS NOT THE ONE CALLERS EXPECT: taxable income\n"
        "  does NOT shrink the $3,000 deduction, it shrinks how much of the LOSS POOL the year consumes.\n"
        "  Worksheet line 4 = min(the deduction, taxable income + the deduction) is IRC 1212(b)(2)(A)'s\n"
        "  lesser-of, so a filer with $1,000 of taxable income deducts $3,000 and still burns only $1,000\n"
        "  — the carryover is $2,000 LARGER than 'loss minus $3,000'. Read `loss_absorbed` and\n"
        "  `deduction_not_absorbed`, not just `deduction`. Pass taxable_income_before_capital_loss WITHOUT\n"
        "  the line 21 deduction subtracted (negative is fine and the worksheet wants it that way); the op\n"
        "  derives worksheet line 1 and prints it so you can tie it to the filed Form 1040 taxable income. Prior\n"
        "  carryovers go in short_term_carryover_in / long_term_carryover_in as POSITIVE amounts, the way\n"
        "  Schedule D lines 6 and 14 are printed. `following_years` rolls the chain forward one mapping\n"
        "  per later year ({short_term, long_term, taxable_income_before_capital_loss, filing_status?,\n"
        "  year?}) and THREADS THE CARRYOVERS ITSELF — re-entering them by hand is how the character split\n"
        "  gets lost, so unknown keys are refused. NOT modelled: wash sales, section 1256 and its 1212(c)\n"
        "  carryback, section 1244 ordinary loss, collectibles/unrecaptured 1250, and state rules)"
    ),
    "foreign_tax_credit_election": (
        "args {creditable_foreign_taxes, all_foreign_income_passive,\n"
        "  all_reported_on_payee_statement, year?, filing_status?, elect?, entity?, regular_tax?,\n"
        "  reduction_in_foreign_taxes?, excess_credit_if_form_1116?} (IRC 904(j) — THE BRANCH THAT DECIDES\n"
        "  WHETHER FORM 1116 IS NEEDED AT ALL, and for a holder of a total-international index fund the\n"
        "  answer is usually no. Foreign tax withheld on fund dividends arrives in FORM 1099-DIV BOX 7\n"
        "  (interest: 1099-INT box 6), and while creditable foreign taxes stay at or under $300 ($600 in\n"
        "  the case of a JOINT RETURN — 904(j)(2)(B), statutory and never indexed) 904(j) lets the whole\n"
        "  credit be claimed as ONE NUMBER on Schedule 3's foreign-tax-credit line, with no Form 1116,\n"
        "  no three-country column grid and no 904(a) limitation fraction. Run this BEFORE authoring\n"
        "  formpacks/federal/<year>/f1116. THREE THINGS IT REFUSES TO GUESS, because each one silently\n"
        "  decides the election: all_foreign_income_passive (904(j)(2)(A) needs the ENTIRE foreign-source\n"
        "  gross income to be qualified passive income — one dollar of foreign wages, foreign\n"
        "  self-employment income, foreign rent or a 951A inclusion ends it for the WHOLE YEAR no matter\n"
        "  how small the tax); all_reported_on_payee_statement (904(j)(3)(A)/(B) need the income AND the\n"
        "  tax shown on a payee statement — 1099-DIV, 1099-INT, Schedule K-1 (1041), Schedule K-3 (1065),\n"
        "  Schedule K-3 (1120-S) or a substitute; foreign tax on a foreign bank account with no US\n"
        "  information return fails it); and `elect` (904(j)(2)(C) is the taxpayer's own act, so\n"
        "  election_available and election_made are reported SEPARATELY — a filer who qualifies may still\n"
        "  prefer Form 1116). ESTATES AND TRUSTS ARE EXCLUDED OUTRIGHT (904(j)(3)(D)). QUOTE THE COST, it\n"
        "  is never free: 904(j)(1)(B)/(C) forfeit the 904(c) 1-year-back / 10-year-forward carryover in\n"
        "  BOTH directions for the election year, so pass regular_tax (Form 1116 line 20 = the Form 1040 tax\n"
        "  plus the Schedule 2 amount the year's 1116 instructions name, less any Form 4972 tax; the work names\n"
        "  both lines, read off the year's faces) to get both the amount claimed — \"the smaller\n"
        "  of (a) your total foreign tax, or (b) your regular tax\" — and credit_lost_to_regular_tax_cap,\n"
        "  foreign tax that exceeds regular tax and is therefore lost PERMANENTLY. The election does NOT\n"
        "  waive creditability (IRC 901/903, including 901(k)'s minimum holding period on dividend\n"
        "  withholding) nor the Form 1116 line 12 reduction, which reduction_in_foreign_taxes subtracts\n"
        "  BEFORE the $300/$600 test. ONE TRAP THE FILING-STATUS COLUMN HIDES: only married filing jointly\n"
        "  is \"a joint return\", so a QUALIFYING SURVIVING SPOUSE gets $300, not $600 — it borrows the\n"
        "  joint RATE schedule under IRC 1(a)(2)/2(a) but does not file a joint return; MFS is $300 too)"
    ),
    "foreign_asset_reporting": (
        "args {year?, filing_status?, us_person?, lives_abroad?,\n"
        "  specified_asset_value_year_end?, specified_asset_value_max?,\n"
        "  foreign_account_value_max_aggregate?, has_foreign_account_signature_authority?, filer_type?}\n"
        "  (DOES THIS FILER HAVE TO REPORT A FOREIGN ACCOUNT? — IRC 6038D's Form 8938 and 31 U.S.C.\n"
        "  5314's FBAR, answered TOGETHER because answering one and stopping is the standard error: \"The\n"
        "  Form 8938 filing requirement does not replace or otherwise affect a taxpayer's obligation to\n"
        "  file FinCEN Form 114\" (IRS, Comparison of Form 8938 and FBAR requirements). NOT a tax\n"
        "  calculation — both duties exist even when the account produced no income and no tax is owed\n"
        "  (Treas. Reg. 1.6038D-2(a)(8)), which is exactly why a refund-shaped interview never surfaces\n"
        "  them: ASK, do not wait to be told. THE TWO THRESHOLDS ARE NOTHING ALIKE. **Form 8938** (Treas.\n"
        "  Reg. 1.6038D-2(a)(1)-(4), measured over the TAXABLE year): more than $50,000 on the LAST DAY or\n"
        "  more than $75,000 AT ANY TIME for a filer in the US who is not filing jointly, $100,000 /\n"
        "  $150,000 married filing JOINTLY, and 4x those figures ($200,000/$300,000 and $400,000/$600,000)\n"
        "  only for an IRC 911(d)(1) QUALIFIED INDIVIDUAL — a bona fide foreign resident for a full tax\n"
        "  year, or 330 full days abroad in 12 consecutive months, with a foreign tax home; living\n"
        "  overseas without meeting that test keeps the in-US figures. EITHER test alone triggers the\n"
        "  filing, so emptying the account before December 31 does not help. **A QUALIFYING SURVIVING\n"
        "  SPOUSE TAKES $50,000/$75,000, NOT the joint figures** — (a)(2)/(a)(4) are keyed to filers who\n"
        "  \"file a joint annual return\" and a QSS does not, even though it borrows the joint rate\n"
        "  schedule. **FBAR** (31 CFR 1010.306(c), measured over the CALENDAR year): a flat $10,000 that\n"
        "  FILING STATUS DOES NOT MOVE, and it is an AGGREGATE across every foreign financial account and\n"
        "  a MAXIMUM-VALUE test — two accounts whose combined balance touched $10,001 for one day are BOTH\n"
        "  reportable even if each stayed under $10,000 and both were empty at year end. THE OP REFUSES TO\n"
        "  GUESS: any fact it needs and does not have comes back as required=None plus a `must_ask`\n"
        "  question naming the authority, because a silent \"no\" here is the most expensive wrong answer in\n"
        "  the repo. Read `must_ask` and `any_duty_undecided` before quoting a verdict. WHERE THEY GO:\n"
        "  Form 8938 attaches to the return (formpacks/federal/<year>/f8938); the FBAR is filed with\n"
        "  FinCEN, e-file ONLY through the BSA E-Filing System, and irs.gov states \"IRS will not accept\n"
        "  paper filings on TD F 90-22.1 (obsolete) or a printed FinCEN Form 114 (for e-filing only)\" —\n"
        "  so there is no fillable pack, only hand_fill_worksheet('fincen114', <year>, 'federal'), and it\n"
        "  is due April 15 with an AUTOMATIC extension to October 15 that needs no request (P.L. 114-41\n"
        "  sec. 2006(b)(11); 31 CFR 1010.306(c)'s printed \"June 30\" was never conformed to the statute and\n"
        "  is WRONG). SCOPES DIFFER IN BOTH DIRECTIONS: signature authority over someone else's account\n"
        "  and an account at a foreign BRANCH of a US bank are FBAR-only; foreign stock held outside an\n"
        "  account, a foreign partnership interest and a foreign hedge fund are Form 8938-only. PENALTY\n"
        "  EXPOSURE, quoted in the result: IRC 6038D(d) $10,000 plus $10,000 per 30 days after IRS notice\n"
        "  to a $60,000 year maximum, and IRC 6662(j)(3) raises the accuracy-related rate to 40% on an\n"
        "  underpayment tied to an undisclosed foreign asset; 31 U.S.C. 5321(a)(5) non-willful up to\n"
        "  $10,000 — inflation-adjusted to $16,536 for penalties assessed on or after 2025-01-17 (31 CFR\n"
        "  1010.821) and accruing PER REPORT, not per account (Bittner v. United States, 598 U.S. 85\n"
        "  (2023)) — with willful exposure the greater of $100,000 (adjusted $165,353) or 50% of the\n"
        "  account balance, which IS per account. NOT modelled and named in the work: the Part IV\n"
        "  excepted-asset rules, joint-ownership valuation, the FBAR's account exceptions, and PART-YEAR\n"
        "  specified-individual status (Treas. Reg. 1.6038D-2(a)(9)) — segment an F-1-to-H-1B year's\n"
        "  values yourself before passing them)"
    ),
    "state_tax": (
        "args {state, taxable_base, year?, exemptions_count?, dependents_count?, filing_status?,\n"
        "  exemption_credit_counts?, federal_agi?}\n"
        "  (the STATE income-tax line for ALL 42 income-tax jurisdictions (41 states + DC) for tax years\n"
        "  2023, 2024 and 2025 (42/42 each). The PACK decides the shape: flat-rate states\n"
        "  multiply, graduated states apply the per-filing-status marginal schedule bracket by bracket and\n"
        "  the work string shows each bracket's contribution. Do NOT assume which shape a state is and do\n"
        "  NOT carry a roster forward — the split moves by year (GA converted to flat for 2024; IA and LA\n"
        "  for 2025). taxable_base is the STATE's OWN base, already adjusted for the state's\n"
        "  additions/subtractions: IL = IL-1040 Line 9 base income (fed AGI ± IL mods); CO = fed TAXABLE\n"
        "  income ± CO mods (DR 0104 Line 10); PA = the eight-class PA-source income (PA-40 Line 11 — no\n"
        "  exemptions, no deduction, a loss in one class never offsets another); the fed-AGI states = their\n"
        "  form's state-AGI line, named in each pack's tax_line/notes. The op subtracts only the pack's\n"
        "  verified personal/dependent exemptions x your counts and the state's standard deduction where the\n"
        "  state ships one — age-65/blind and other exemption kinds are disclosed, not applied, and the\n"
        "  credit-exemption states (ca, ar, de, ia, ne, or) REFUSE exemptions_count/dependents_count because\n"
        "  their per-person amounts are credits, not exemptions. EXEMPTION CREDITS: where the pack ships them\n"
        "  (ca 2023-2025: Form 540 lines 7-11 and 32-33; for 2025 also ar AR1000F 7A-7C/34, de PIT-RES\n"
        "  27a-27b, ia IA 1040 Step 3/line 8, ne 1040N line 4/18, or OR-40 6a-6e/25), pass\n"
        "  exemption_credit_counts keyed by the pack's kinds (ca {personal, blind, senior, dependent}, the\n"
        "  line 7-10 box numbers; the not-applied work string and the refusals list every pack's kinds) and,\n"
        "  for ca and or, federal_agi (ca: Form 540 line 13, which the line 32 AGI limitation reads; or:\n"
        "  OR-40 line 7, above whose per-status ceiling a kind is denied — agi_ceilings); the result's\n"
        "  `exemption_credits` then carries each line's credit, exemption_amount, limitation_reduction,\n"
        "  total (the credits taken; de's line 32 is limited to the tax, tax_limit_reduction) and\n"
        "  tax_after_credits, with `lines` naming the form lines. `tax` stays\n"
        "  the tax line either way; without counts exemption_credits.applied is false; a count above the\n"
        "  form's own maximum is refused. A state without the block refuses nonzero exemption_credit_counts.\n"
        "  Form 540NR prorates the credits on its own lines 38-40, so a 540NR return takes only\n"
        "  exemption_amount from here.\n"
        "  County/city add-on taxes (IN counties, MI cities, MD counties, OH school districts) and other\n"
        "  state credits are NOT modeled. Out-of-schedule surcharges and recaptures are\n"
        "  disclosed in the work string, not computed — CA's 1% Mental Health Services Tax over $1M and NY's\n"
        "  recapture worksheets above $107,650 NY AGI are cases where plain bracket math is WRONG. Unknown\n"
        "  state or a state without the block errors, listing the supported states)"
    ),
}

_ESTIMATE_REFUND_GUIDE = (
    "Early bottom-line range from a partial profile + confirmed income amounts — labeled ESTIMATE for a closed\n"
    "year and PROJECTION for a planning year (a provisional knowledge pack, today TY2026).\n"
    "\n"
    "`income` fields (whole dollars, W-2 boxes as printed; every field optional, defaults 0; unknown fields\n"
    "rejected):\n"
    "- income: wages (W-2 box 1), federal_withholding (withheld + estimated payments), interest,\n"
    "  bank_deposit_interest (the DEPOSIT subset of interest — US bank / savings institution /\n"
    "  insurance-company deposit, not effectively connected; excluded for a nonresident under\n"
    "  IRC 871(i)(2)(A), taxed under a §6013(g)/(h) election, joint or separate),\n"
    "  bank_deposit_interest_nonresident_period (the part of bank_deposit_interest RECEIVED before the\n"
    "  residency starting date of a dual-status year, from the account statements - never prorated;\n"
    "  only that part is excluded on a dual-status payee's return, Treas. Reg. 1.871-13(a)(1), and the\n"
    "  rest is taxed), dividends (1099-DIV 1a), qualified_dividends (1b subset), capital_gain_long (signed),\n"
    "  capital_gain_short (signed), self_employment_net (signed), retirement_income_taxable (the\n"
    "  TAXABLE amount, not simply 1099-R box 2a: a traditional-IRA distribution or Roth conversion shows\n"
    "  the GROSS amount in 2a with 2b checked, so a filer with basis runs calc op ira_pro_rata and\n"
    "  enters its taxable figure; box 7 codes N/R and H are $0, code G is $0 except a Roth-bound\n"
    "  direct rollover from a pre-tax plan (to a Roth IRA, or an in-plan Roth rollover) and designated\n"
    "  Roth employer contributions, where box 2a is the taxable amount) — OR, instead of that figure,\n"
    "  retirement_distributions (JR3a): each 1099-R as read {gross, taxable_amount (2a), taxable_not_determined,\n"
    "  total_distribution, codes (box 7 / 7a), ira_sep_simple, rolled_over?, taxable_override?,\n"
    "  early_exception_amount?, federal_withholding? (informational), label?}, priced per code (Q/N/R $0, G/H\n"
    "  box 2a, P excluded as a prior-year item); never both. A traditional-IRA 1099-R with box 2b checked\n"
    "  (JR3b) is priced through Form 8606 Part I with THAT PERSON's ira_pool {basis_carryforward (line 2; 0 =\n"
    "  the explicit no-basis answer), nondeductible_contributions_this_year?, contributions_made_after_year_end?,\n"
    "  dec31_total_value (line 6, needed with basis)} — required then, and a spouse's pool never merges;\n"
    "  mark each conversion converted_to_roth. JR3c prices the 72(t) additional tax per 1099-R (codes 1/J 10%,\n"
    "  S 25%, early_exception_amount off the base, code 8 corrective earnings exempt) and the 4973 excise from\n"
    "  traditional_ira_excess / roth_ira_excess (Form 5329 lines 16/24) capped at traditional_ira_dec31_value /\n"
    "  roth_ira_dec31_value,\n"
    "  social_security_benefits (SSA-1099 box 5), other_income\n"
    "- adjustments: student_loan_interest_paid (1098-E), pre_agi_adjustments (confirmed-eligible\n"
    "  above-the-line), treaty_exempt_income (1042-S box 2 — agent-confirmed treaty amount; the\n"
    "  assumption names where it is reported for the profile's residency: Schedule OI for a\n"
    "  nonresident, in parentheses on Schedule 1's other-income line for a resident alien),\n"
    "  itemized_deductions? (only if itemizing; else standard deduction — NRAs itemize only),\n"
    "  other_state_local_taxes? (JW2a: state and local taxes paid beyond W-2 box 17 — box 14 disability or\n"
    "  family leave, box 19, state estimated payments, real estate tax, a value-based vehicle fee; never priced\n"
    "  alone), foreign_tax_paid? (1099-DIV box 7; named in the roadmap, the credit is NOT estimated)\n"
    "- Schedule 1-A (JF7, P.L. 119-21, TY2025-2028 — BELOW AGI, after the deduction; never pre_agi_adjustments\n"
    "  or itemized_deductions): qualified_tips, qualified_overtime_premium (the FLSA premium half only),\n"
    "  car_loan_interest; the senior deduction is derived from the profile's date of birth and SSN\n"
    "  (senior_taxpayer / senior_spouse override it). MFS forfeits tips, overtime and the senior deduction,\n"
    "  not car-loan interest; a year whose pack lacks the block reports it in missing_blocks\n"
    "- w2s (JT4a): each Form W-2 as printed, cents allowed {employer?, box1..box7, box10, box12: [{code,\n"
    "  amount}], box14b?, box17? (state income tax)} — the\n"
    "  aggregates (wages, ss_wages, medicare_wages, the box 4 / box 6 lists, dependent_care_benefits from box 10,\n"
    "  qualified_overtime_premium from code TT) derive from them, and an aggregate also given must agree; the\n"
    "  assumptions flag a 402(g) excess across employers and a code W figure deducted again\n"
    "- W-2 boxes beyond box 1 (JF3): medicare_wages (box 5 total — what Form 8959 prices; box 1 stands in\n"
    "  when omitted), ss_wages (boxes 3 + 7 total — what Schedule SE subtracts from the wage base),\n"
    "  medicare_tax_withheld [box 6 per employer — the excess over 1.45% of box 5 is credited; needs\n"
    "  medicare_wages; never also in federal_withholding]\n"
    "- credit inputs: ss_withheld_by_employer [W-2 box 4 per employer], aotc_qualified_expenses\n"
    "  [per eligible student] with aotc_students_ssn_ok [per student, 2026 onward (P-024): True for you, your\n"
    "  spouse or a dependent issued a valid SSN before the due date; False for an ITIN/ATIN-only dependent; a\n"
    "  missing answer leaves that student's credit NOT ESTIMATED — the filer's own SSN comes from the profile's\n"
    "  tax_id, one spouse's enough on a joint return], dependent_care_expenses + dependent_care_persons (Form 2441 —\n"
    "  qualified care expenses paid so you/both spouses could work, and how many qualifying persons)\n"
    "- ACA (Form 1095-A line 33): aca_premiums, aca_slcsp, aca_aptc\n"
    "- spouse: nested income object with the spouse's OWN amounts (same fields; enables a true\n"
    "  two-return MFS comparison — otherwise amounts are couple-combined)\n"
    "\n"
    "Itemizing (JW2a): with no itemized_deductions, result.itemizing_comparison weighs the state and local tax\n"
    "given (box 17 + other_state_local_taxes, after the year's limit) against the standard deduction — over it,\n"
    "the range includes the itemized outcome; at least half of it, the result lists what else to collect.\n"
    "result.roadmap.returns_and_forms lists the LIKELY schedules and forms the inputs imply (not exhaustive) and\n"
    "the state return(s) the state footprint requires; every dollar figure is the federal return only.\n"
    "\n"
    "Schedule 3-A (JT1c, 2026 onward, P-023): the refunded portion of the EIC, the ACTC and the refundable\n"
    "AOTC — the part over the subtitle A tax — is a PRWORA \"Federal public benefit\" under the PROPOSED rule\n"
    "REG-119882-25. When no one on the return is recorded as a U.S. citizen, U.S. national or qualified\n"
    "alien (8 U.S.C. 1641 — not tax residency: an H-1B or F-1 resident alien is not one), the LOW end of\n"
    "the range holds it back and the point keeps it while the rule is proposed. Record\n"
    "profile identity.qualified_alien_status (and household.spouse's): a joint return needs one spouse\n"
    "who qualifies, and the answer is the one on the date the return is filed.\n"
    "\n"
    "Residency (P-018): record the §6013(g)/(h) election as profile residency_facts.section_6013_election\n"
    "(true = elected or still in effect) — it makes both spouses residents for the whole year, so the\n"
    "standard deduction, preferential rates and NIIT apply and the deposit exclusion is off, while\n"
    "FICA keeps following the day counts. It applies on a figure with a spouse (married for the\n"
    "year, or a confirmed MFJ/MFS status), never onto single/HOH, and never when the recorded facts\n"
    "show neither spouse a U.S. citizen or resident (IRC 6013(g)(3) - then separate Form 1040-NRs, one\n"
    "for each spouse who meets the nonresident filing requirements). A confirmed\n"
    "married_filing_jointly status for a filer whose own residency is nonresident is read as the election (a joint return with a nonresident exists only under it) unless the election\n"
    "is recorded as DECLINED (false): a decline drops MFJ for a couple with a nonresident in it, and\n"
    "a confirmed MFJ those facts rule out is priced MFS with the contradiction as the FIRST\n"
    "assumption. result.residency_caveat carries the election's text — IRC 6013(g) or 6013(h),\n"
    "whichever the facts point to (a recorded election in a dual-status year gives both: it may be\n"
    "an earlier 6013(g) election still in effect - unless the taxpayer's prior-year return is recorded\n"
    "as '1040_with_6013_election', which makes it IRC 6013(g): IRC 6013(g)(3), the election applies \"to\n"
    "all subsequent taxable years until terminated\", and 6013(h)(2) bars a second 6013(h); with that\n"
    "prior-year return and NO answer recorded for the year the election is NOT applied from that return\n"
    "alone (a confirmed joint status of a nonresident or dual-status taxpayer is still read as the\n"
    "election, JF5a) - an assumption\n"
    "and intake's household.section_6013_election ask whether it is still in effect). With no answer\n"
    "recorded and no status confirmed, a married taxpayer whose own residency is nonresident or a\n"
    "dual-status year keeps married_filing_jointly as a CANDIDATE (JF5b part 3b), as the reverse couple\n"
    "does: the figure IF the couple makes the election, priced on resident rules for both spouses\n"
    "(IRC 6013(h) for an arrival year with a U.S. spouse), behind the no-election MFS primary - with\n"
    "the worldwide-income, statement, FICA and NIIT notes worded as a candidate, and, when the\n"
    "spouse's residency is not on file, the precondition named as not judged (record\n"
    "household.spouse.us_person or the spouse's visa timeline and days). Never after a recorded\n"
    "decline, a confirmed status, or on facts ruling the election out (IRC 6013(g)(3)). A dual-status\n"
    "year's route (ii) names that joint candidate. Each spouse's separate MFS return\n"
    "follows that spouse's OWN classification (a US-citizen spouse's Form 1040 keeps the standard\n"
    "deduction unless the couple itemizes: IRC 63(c)(6)(A) — both methods are priced and the better\n"
    "total is kept); a spouse whose residency is unknown is priced both ways in the range.\n"
    "NIIT under the election (JF5b part 3a): the chapter-1 election does not reach NIIT (chapter 2A),\n"
    "so with a spouse snapshot every election figure prices the Treas. Reg. 1.1411-2(a)(2)(iii)(A) /\n"
    "(iv)(A) DEFAULT - each spouse's own snapshot under the MFS rules against $125,000, and under\n"
    "IRC 6013(g) $0 for the spouse who is a nonresident without the election - against the second\n"
    "(chapter 2A) election's combined-income figure ($250,000): under 6013(g) the joint point is the\n"
    "default and the range adds the combined figure only when the U.S. spouse owes NIIT on their own\n"
    "figures (otherwise the second election is not available that year, (iii)(B)(2)); under 6013(h)\n"
    "the point is the lower of the two (no first-year condition; the arriving spouse's resident-period\n"
    "income is not recorded, so the default is bounded); a kind the facts leave open keeps the\n"
    "combined figure with both readings in the range; a separate return prices the nonresident spouse\n"
    "at $0 with the resident-rules figure in the range for a definite IRC 6013(g) (an open kind keeps\n"
    "resident rules at the point, $0 in the range); a couple with no nonresident or arriving spouse on\n"
    "their own facts has no default at all. One combined snapshot cannot be split: the\n"
    "combined figure stays and the NIIT note names income.spouse.\n"
    "The taxpayer's return for the prior year (profile prior_filings.return_forms[year - 1]: '1040',\n"
    "'1040-NR', 'dual_status', '1040_with_6013_election', 'not_filed') is the prior-year residency\n"
    "fact (JF5b): a prior-year resident who meets the SPT is priced as a resident from January 1\n"
    "(standard deduction, no arrival split; only the start of the year is settled - a departure caveat\n"
    "names the IRC 7701(b)(2)(B) ending-date rule when the last status period ends before Dec 31), with\n"
    "a FIRST CHECK THE PRIOR-YEAR RETURN judgment when the recorded timeline makes that prior year a\n"
    "fully exempt year; one who fails the SPT gets the classifier's CONTRADICTION reason as the FIRST\n"
    "assumption. A nonresident answer that may flip (a lookback year missing from the day\n"
    "counts - classify's \"may be WRONG\") or that contradicts the prior year is priced on Form 1040-NR\n"
    "rules with the RESIDENT reading bracketed in the range and the reason first; a spouse's own\n"
    "answer that may flip brackets the spouse-resident reading of the two-return MFS pair.\n"
    "A DUAL-STATUS year with no election (JF5b part 2) prices Pub 519 ch. 6's restrictions for the\n"
    "point - no standard deduction (itemized or $0), no EITC, no education credits, no joint return\n"
    "or HOH, MFS rates if married and single rates otherwise (an inference - ch. 6 names the rate column only for a married filer) - as one whole-year snapshot (NIIT on\n"
    "the whole year's investment income may be overstated: Treas. Reg. 1.1411-2(a)(2)(ii) counts\n"
    "resident-period income only); the range's other end is the same-status full-year-resident\n"
    "figure when a prior-year residency is not ruled out (route (i)), while for a married filer the\n"
    "election's route (ii) is its own married-filing-jointly CANDIDATE, priced under the election\n"
    "(or the same-status resident figure when no joint candidate is priced); it collapses to the\n"
    "point for an unmarried filer whose prior year is a recorded 1040-NR. Only bank_deposit_interest_nonresident_period is excluded on a dual-status\n"
    "payee's return (the spouse's separate return by the spouse's own year), with a disclosure\n"
    "naming the amount - or, without the split, the amount taxed in full and what to record. A\n"
    "dual-status SPOUSE's own separate return (no election) is priced the same way at the point (Pub\n"
    "519 ch. 6: no standard deduction, no EITC or education credit, MFS rates), and the range prices\n"
    "that return for the whole year under resident rules and under Form 1040-NR rules.\n"
    "\n"
    "The result's `composition` is a reconciling LEDGER: each line carries a stable `slot`, a\n"
    "`role`, and an `effect` (its signed contribution to the bottom line; the effects sum EXACTLY\n"
    "to `point`). When >=2 statuses were computed, `comparison.delta_lines` itemizes WHERE the\n"
    "best-vs-worst difference comes from, largest first, summing exactly to `comparison.delta` —\n"
    "show that table when the user asks which status wins and why. `missing_blocks` lists any\n"
    "input that engaged a block the year's pack does not carry (planning years): each names the\n"
    "unpriced item and the direction of the error — surface those before comparing years."
)

_DESCRIBE_OP = "describe"  # not an `if op == "..."` literal: the op counters (tests, sync scripts) read those


def _reflow(text: str) -> str:
    """Join a docstring's wrapped lines; keep its paragraphs and its "- " bullets on lines of their own."""
    blocks: list[list[str]] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            blocks.append([])
        elif stripped.startswith("- ") or not blocks or not blocks[-1]:
            blocks.append([stripped])
        else:
            blocks[-1].append(stripped)
    return "\n".join(" ".join(b) for b in blocks if b)


def _args_spec(op: str) -> str | None:
    """The `args {...}` list at the head of an op's notes (balanced braces), or None."""
    text = " ".join(_CALC_OP_DOCS.get(op, "").split())
    start = text.find("args {")
    if start < 0:
        return None
    depth = 0
    for pos in range(start + 5, len(text)):
        depth += {"{": 1, "}": -1}.get(text[pos], 0)
        if depth == 0:
            return text[start + 5:pos + 1]
    return None


def _calc_describe(args: dict[str, Any]) -> dict:
    name = (args or {}).get("op")
    if name is None:
        return {"ops": list(_CALC_OP_DOCS), "also": ["estimate_refund"],
                "usage": 'calc(op="describe", args={"op": "<name>"}) returns that op\'s arguments and full notes'}
    if name == "estimate_refund":
        return {"tool": "estimate_refund", "text": _reflow(_ESTIMATE_REFUND_GUIDE)}
    if name not in _CALC_OP_DOCS:
        raise ValueError(f"describe: unknown calc op {name!r} — supported: {', '.join(_CALC_OP_DOCS)}, "
                         f"and 'estimate_refund' for that tool's input guide")
    return {"op": name, "args": _args_spec(name), "text": _reflow(_CALC_OP_DOCS[name])}


_SIGNATURE_ERROR = re.compile(r"unexpected keyword argument|missing \d+ required|argument after \*\* must be a mapping")


@mcp.tool()
def calc(op: str, args: dict[str, Any]) -> dict:
    """Deterministic tax math; every result shows its work and cites the data pack. op in {tax,
    tax_with_preferential_rates, standard_deduction, se_tax, additional_medicare_tax, niit, taxable_social_security,
    excess_ss, student_loan_interest_deduction, education_credits, ptc_annual, ptc_monthly, child_tax_credit, eitc,
    dependent_care_credit, treaty_benefit, schedule_1a_deductions, charitable_deduction, withholding_projection,
    employee_fica, estimated_tax_safe_harbor, underpayment_penalty, paystub_to_w2, claim_of_right_repayment,
    annualize_ytd, ira_net_income_attributable, ira_recharacterization, elective_deferral_room, contribution_limits,
    ira_contribution_eligibility, marginal_dollar_savings, magi_ladder, ira_pro_rata, roth_conversion,
    hsa_deduction, espp_disposition, capital_loss_limitation, foreign_tax_credit_election, foreign_asset_reporting,
    state_tax}.

    ARGUMENTS: calc(op="describe", args={"op": "<name>"}) returns an op's arguments and full notes; read it
    before an op's first use ("estimate_refund" there returns that tool's full input guide).

    A result computed off a PROVISIONAL (planning-only) knowledge pack — a current year
    authored before its forms published, e.g. federal 2026 — carries an extra `provisional`
    key. When you see it, call the number a PROJECTION to the user and never place it on a
    return: fill_form and verify_form refuse that year outright.

    Rules that change the number:
    - tax: ORDINARY income only — with qualified dividends or capital gains use tax_with_preferential_rates
      instead, even below $100,000. niit: NRAs exempt. excess_ss: ONE person, multiple employers only.
    - MFS gets $0: student_loan_interest_deduction, education_credits, dependent_care_credit, ptc_annual and
      ptc_monthly (unless mfs_relief_exception). eitc phases out on the GREATER of AGI or earned income.
    - treaty_benefit: pass resident_alien — false: Schedule OI and the Form 1040-NR treaty-exempt line; true: in
      parentheses on Schedule 1's other-income line.
    - schedule_1a_deductions: tips, overtime and senior are FORFEITED on MFS (car-loan interest is not); the tips
      cap is per RETURN; qualified_overtime is the FLSA premium half only.
    - employee_fica: the F/J/M/Q exemption is a NONRESIDENT one (Pub 519 ch. 8: a resident alien's wages bear
      FICA) — pass residency_classification (under a §6013(g)/(h) election, classification_without_election).
    - estimated_tax_safe_harbor: expected_withholding WITHOUT the box-6 excess; a bonus gets the flat 22% only
      when Treas. Reg. 31.3402(g)-1(a)(7)(i) holds, else the aggregate procedure. withholding_projection counts
      checks by PAY DATE; paystub_to_w2 adds only checks PAID by December 31. annualize_ytd ASSUMES LEVEL PAY:
      never annualize a bonus or RSU vest.
    - IRAs: run ira_contribution_eligibility BEFORE recording a contribution; ira_pro_rata pools ALL
      traditional/SEP/SIMPLE IRAs per PERSON, its denominator adding the conversion back; roth_conversion
      prices ONE path — plan_to_roth_ira never uses pro-rata.
    - elective_deferral_room: 402(g) is per person ACROSS EVERY EMPLOYER.
    - hsa_deduction: the limit is MONTHLY; W-2 code W is employer money (employer_contributions), never deducted
      again; a general-purpose health FSA, the spouse's too, disqualifies. Above the SS wage base a payroll
      dollar saves 1.45% FICA (2.35% over $200k), never 7.65%.
    - espp_disposition: ONE lot; the 1099-B basis leaves out the ordinary income — use the returned basis.
    - capital_loss_limitation: $3,000 ($1,500 MFS); carryovers keep their character.
    - foreign_tax_credit_election: no Form 1116 up to $300, $600 only on a joint return (never QSS).
    - foreign_asset_reporting: Form 8938 and FBAR together; read must_ask.
    - state_tax: taxable_base is the STATE's own base; the pack decides flat or graduated — never assume.
    """
    if op == _DESCRIBE_OP:
        return _calc_describe(args)
    try:
        return _calc_dispatch(op, args)
    except TypeError as exc:
        if op not in _CALC_OP_DOCS or not _SIGNATURE_ERROR.search(str(exc)):
            raise
        raise TypeError(f"{exc} — calc op {op!r} takes args {_args_spec(op)}; full notes: "
                        f'calc(op="describe", args={{"op": "{op}"}})') from None


def _calc_dispatch(op: str, args: dict[str, Any]) -> dict:
    if op == "tax":
        return _stamp_provisional(_dump(_tax(**args)), args)
    if op == "tax_with_preferential_rates":
        return _stamp_provisional(_dump(_tax_with_preferential_rates(**args)), args)
    if op == "standard_deduction":
        return _stamp_provisional(_dump(_standard_deduction(**args)), args)
    if op == "se_tax":
        return _stamp_provisional(_dump(_se_tax(**args)), args)
    if op == "additional_medicare_tax":
        return _stamp_provisional(_dump(_additional_medicare_tax(**args)), args)
    if op == "niit":
        return _stamp_provisional(_dump(_niit(**args)), args)
    if op == "taxable_social_security":
        return _stamp_provisional(_dump(_taxable_social_security(**args)), args)
    if op == "excess_ss":
        return _stamp_provisional(_dump(_excess_ss(**args)), args)
    if op == "student_loan_interest_deduction":
        return _stamp_provisional(_dump(_student_loan_interest_deduction(**args)), args)
    if op == "education_credits":
        return _stamp_provisional(_dump(_education_credits(**args)), args)
    if op == "ptc_annual":
        return _stamp_provisional(_dump(_ptc_annual(**args)), args)
    if op == "ptc_monthly":
        return _stamp_provisional(_dump(_ptc_monthly(**args)), args)
    if op == "child_tax_credit":
        return _stamp_provisional(_dump(_child_tax_credit(**args)), args)
    if op == "eitc":
        return _stamp_provisional(_dump(_eitc(**args)), args)
    if op == "dependent_care_credit":
        return _stamp_provisional(_dump(_dependent_care_credit(**args)), args)
    if op == "treaty_benefit":
        return _stamp_provisional(_dump(_treaty_benefit(**args)), args)
    if op == "schedule_1a_deductions":
        return _stamp_provisional(_dump(_schedule_1a_deductions(**args)), args)
    if op == "charitable_deduction":
        return _stamp_provisional(_dump(_charitable_deduction(**args)), args)
    if op == "employee_fica":
        return _stamp_provisional(_dump(_employee_fica(**args)), args)
    if op == "withholding_projection":
        from taxfill_core.withholding import withholding_projection as _withholding_projection  # noqa: PLC0415

        return _stamp_provisional(_dump(_withholding_projection(**args)), args)
    if op == "estimated_tax_safe_harbor":
        return _stamp_provisional(_dump(_estimated_tax_safe_harbor(**args)), args)
    if op == "claim_of_right_repayment":
        from taxfill_core.repayment import claim_of_right_repayment as _claim_of_right  # noqa: PLC0415

        return _stamp_provisional(_dump(_claim_of_right(**args)), args)
    if op == "paystub_to_w2":
        from taxfill_core.paystub import paystub_to_w2 as _paystub_to_w2  # noqa: PLC0415

        return _stamp_provisional(_dump(_paystub_to_w2(**args)), args)
    if op == "underpayment_penalty":
        from taxfill_core.penalty import underpayment_penalty as _underpayment_penalty  # noqa: PLC0415

        return _stamp_provisional(_dump(_underpayment_penalty(**args)), args)
    if op == "annualize_ytd":
        return _dump(_annualize_ytd(**args))
    if op == "contribution_limits":
        return _stamp_provisional(_dump(_contribution_limits(**args)), args)
    if op == "ira_net_income_attributable":
        return _dump(_ira_net_income_attributable(**args))
    if op == "ira_recharacterization":
        return _stamp_provisional(_dump(_ira_recharacterization(**args)), {**args, "year": args.get("contribution_year")})
    if op == "elective_deferral_room":
        return _stamp_provisional(_dump(_elective_deferral_room(**args)), args)
    if op == "ira_contribution_eligibility":
        return _stamp_provisional(_dump(_ira_contribution_eligibility(**args)), args)
    if op == "marginal_dollar_savings":
        return _stamp_provisional(_dump(_marginal_dollar_savings(**args)), args)
    if op == "magi_ladder":
        return _stamp_provisional(_dump(_magi_ladder(**args)), args)
    if op == "ira_pro_rata":
        return _stamp_provisional(_dump(_ira_pro_rata(**args)), args)
    if op == "roth_conversion":
        return _stamp_provisional(_dump(_roth_conversion(**args)), args)
    if op == "hsa_deduction":
        return _stamp_provisional(_dump(_hsa_deduction(**args)), args)
    if op == "espp_disposition":
        return _stamp_provisional(_dump(_espp_disposition(**args)), args)
    if op == "capital_loss_limitation":
        return _stamp_provisional(_dump(_capital_loss_limitation(**args)), args)
    if op == "foreign_tax_credit_election":
        return _stamp_provisional(_dump(_foreign_tax_credit_election(**args)), args)
    if op == "foreign_asset_reporting":
        return _stamp_provisional(_dump(_foreign_asset_reporting(**args)), args)
    if op == "state_tax":
        return _stamp_provisional(_dump(_state_tax(**args)), args)
    raise ValueError(
        f"unknown calc op {op!r} — supported: {', '.join(_CALC_OP_DOCS)}; "
        f'calc(op="describe", args={{"op": "<name>"}}) gives an op\'s arguments'
    )


@mcp.tool()
def residency(
    visa_periods: list[dict],
    days_by_year: dict[str, int],
    target_year: int,
    is_lawful_permanent_resident: bool = False,
    section_6013_election: bool = False,
    prior_year_resident: bool | None = None,
) -> dict:
    """Federal residency (NRA/RA/dual-status) via the Substantial Presence Test + exempt years.

    visa_periods: [{status, start, end?}]; days_by_year: {year: days_present}. Shows the day-count work.

    section_6013_election: true when the couple makes (or has in effect) the §6013(g)/(h) election
    (P-018). Pub 519 ch. 1: "you and your spouse are treated for income tax purposes as residents
    for your entire tax year", so the classification is 'resident' with no dual-status split,
    whatever the SPT says; the day-count answer comes back as classification_without_election.
    The election reaches chapter 1 and chapter 24 only (IRC 6013(g)(1)), so pass THAT answer to
    calc op employee_fica (FICA is chapter 21), and use it to check the precondition. Two choices:
    IRC 6013(g) - at year end one spouse a nonresident alien, the other a U.S. citizen or resident;
    it continues into later years - and IRC 6013(h) - the dual-status year, both U.S. citizens or
    residents at year end, one a nonresident at the start; one year only, a different statement.

    prior_year_resident (JF5b, P-018): the return filed for target_year - 1 — true for a Form 1040
    or a dual-status return, false for a Form 1040-NR, omitted/null when not filed, unknown, or a
    joint 1040 under the election (not read as residency: unsettled). On a profile it is
    prior_filings.return_forms. Treas. Reg. 301.7701(b)-4(e)(1): a resident "during any part of the
    preceding calendar year" who "is a United States resident for any part of the current year will be
    considered to be taxable as a resident at the beginning of the current year" - so true with the
    SPT met is 'resident' from January 1 (no arrival split, no First-Year Choice; a first-position
    CHECK THE PRIOR-YEAR RETURN judgment when the recorded timeline cannot support a resident year
    for target_year - 1); true with the SPT NOT met stays 'nonresident' (IRC 7701(b)(1)(A): a resident
    "if (and only if)" a test is met) with a FIRST CONTRADICTION reason - a judgment naming three
    readings (an incomplete timeline, e.g. exempt years past the student limit; a prior return on the
    wrong form; a genuine departure or return to exempt status, then a full-year nonresident year),
    never definitive. result.prior_year_resident echoes it.
    """
    days = {int(k): v for k, v in days_by_year.items()}
    return _dump(_classify(
        visa_periods, days, target_year,
        is_lawful_permanent_resident=is_lawful_permanent_resident,
        section_6013_election=section_6013_election,
        prior_year_resident=prior_year_resident,
    ))


# ── intake / estimate / sources / summary / file&pay ───────────────────────────


@mcp.tool()
def intake_checklist(profile: dict | None = None, tax_year: int | None = None) -> dict:
    """Next interview questions + required documents for a (partial) profile. Empty profile = start.

    The start state (empty profile) also returns `worksheet`: a fill-in-the-blank onboarding
    worksheet (markdown) to hand a no-experience user BEFORE interviewing them — status and
    state facts as date-ranged SEGMENTS, never single words. Record their answers into the
    profile and re-call; the interview then asks only what is still missing.

    The start state also returns `example_profile`: the exact profile shape (a leaf answer is
    {value, provenance}; year-keyed sections), fictitious values. Each question's `answers_into` is
    the exact field path. `ready_to_fill` stays false while a deductions-and-payments question is open
    (`ready_to_fill_blockers`); record each answer in words under deductions_and_payments.<year> —
    "none" and "unknown" are answers.
    """
    try:
        prof = Profile.model_validate(profile) if profile else None
    except ValidationError as exc:
        raise ValueError(
            f"invalid `profile` — {_validation_problems(exc)}. The shape is in `example_profile` (call "
            f"intake_checklist with no profile); each question's `answers_into` names the field path."
        ) from None
    return _dump(_intake_checklist(prof, tax_year=tax_year))


@mcp.tool()
def list_document_kinds() -> list[dict]:
    """Supported tax-document types and their official box layouts (W-2, 1099-*, 1098-*, 1042-S).

    Read this first, then read the actual document with your own vision and pass the boxes you
    see to extract_document. Each kind cites the form's irs.gov layout page.
    """
    return _list_document_kinds()


@mcp.tool()
def extract_document(
    path: str, kind: str, fields: dict[str, Any], page: int | None = None, tax_year: int | None = None,
) -> dict:
    """Structure + validate YOUR reading of one tax document into provenance-tagged fields.

    This does NOT do OCR — you read the document (image/PDF) with your own vision and pass the
    box->value map in `fields` (keys from list_document_kinds). The tool type-checks each value,
    tags it with document provenance (file + page), flags required boxes you didn't read as `gaps`,
    surfaces unreadable values as `invalid`, and returns a confirm-table. Never invent a box: any
    box you omit stays null. `kind` is e.g. "W-2", "1099-INT", "1042-S". Pass `tax_year` (the year the form
    reports): a Form 1099-R's box 7 codes are then read against THAT year's distribution-code table (Y is new
    in 2025, S pairs with J from 2025, N/R/P name years relative to the form's own), and `findings` lists the
    semantic checks — an error keeps the box 'ok' (a payer error is a real reading) and says to request a
    CORRECTED form; `interpretation` says what each code means.
    """
    return _dump(_extract_document(path, kind, fields, page=page, tax_year=tax_year))


@mcp.tool()
def workspace_save(year: int, profile: dict, root: str = WORKSPACE_ROOT) -> dict:
    """Persist the intake profile to the local resumable workspace (taxfill-workspace/<year>/)."""
    ws = Workspace.open(root, year, now=_now())
    ws.save_profile(profile, now=_now())
    return ws.status()


@mcp.tool()
def workspace_load(year: int, root: str = WORKSPACE_ROOT) -> dict:
    """Resume: load the saved profile + status from the local workspace (None profile if new)."""
    ws = Workspace(root, year)
    return {"status": ws.status(), "profile": ws.load_profile()}


@mcp.tool()
def workspace_record_position(year: int, position: dict, root: str = WORKSPACE_ROOT) -> dict:
    """Record one decided position with its authority into the audit trail.

    `position` shape: {topic, value, citation: {source, url}, rationale?, references?, status?}
    — topic: what was decided; value: the figure/decision as it will appear on the return;
    citation: the authoritative source (.gov URL); references?: forms/lines touched, e.g.
    ["f1040.12"]; status?: decided|open|unverified. Example: {"topic": "1040 line 12 — standard
    deduction", "value": "13850", "citation": {"source": "Rev. Proc. 2022-38, Section 3.15",
    "url": "https://www.irs.gov/pub/irs-drop/rp-22-38.pdf"}}.

    A position with no `citation` is stored as `unverified` (never `decided`) — the return
    is not ready while any remain. Recording the same `topic` again replaces it (corrections).
    """
    try:
        pos = Position.model_validate(position)
    except ValidationError as exc:
        raise ValueError(
            f"invalid `position` — {_validation_problems(exc)}. Expected shape: "
            '{"topic": str, "value": str, "citation": {"source": str, "url": ".gov URL"}, '
            '"rationale"?: str, "references"?: ["f1040.12"], "status"?: decided|open|unverified} '
            '— e.g. {"topic": "1040 line 12 — standard deduction", "value": "13850", '
            '"citation": {"source": "Rev. Proc. 2022-38, Section 3.15", '
            '"url": "https://www.irs.gov/pub/irs-drop/rp-22-38.pdf"}}'
        ) from None
    ws = Workspace.open(root, year, now=_now())
    saved = ws.record_position(pos, now=_now())
    return {"recorded": _dump(saved), "status": ws.status()}


@mcp.tool()
def workspace_reconcile(year: int, gaps: list[str] | None = None, root: str = WORKSPACE_ROOT) -> dict:
    """Generate RECONCILIATION.md (positions + authority) and CHECKLIST.md from recorded state."""
    ws = Workspace.open(root, year, now=_now())
    r = ws.write_reconciliation(now=_now())
    c = ws.write_checklist(gaps=gaps, now=_now())
    return {"reconciliation_path": str(r), "checklist_path": str(c), "reconciliation_md": r.read_text(), "status": ws.status()}


@mcp.tool()
def state_scope(profile: dict, year: int) -> dict:
    """Which states require a return for the year, in what role, with forms/benefits/warnings.

    Reads the profile's state_footprint (where the user lived/worked, with dates). No-income-tax
    states resolve to "nothing to file"; a state that doesn't honor federal treaties (California)
    warns that treaty-exempt federal income is still taxable there. Allocation stays your judgment.
    """
    return _dump(_state_scope(Profile.model_validate(profile), year))


@mcp.tool()
def estimate_refund(profile: dict, year: int, income: dict) -> dict:
    """Early bottom-line range from a partial profile + confirmed income amounts — labeled ESTIMATE for a closed
    year and PROJECTION for a planning year (a provisional knowledge pack, today TY2026).

    FULL INPUT GUIDE (every field; the residency, §6013(g)/(h) election, dual-status and NIIT rules):
    calc(op="describe", args={"op": "estimate_refund"}). Read it before pricing a 1099-R, a nonresident or
    dual-status year, or a married couple with a nonresident spouse.

    `income` (whole dollars, W-2 boxes as printed; every field optional, defaults 0; unknown fields rejected):
    wages, federal_withholding (withheld + estimated payments), interest, bank_deposit_interest,
    bank_deposit_interest_nonresident_period, dividends, qualified_dividends, capital_gain_long and
    capital_gain_short (signed), self_employment_net, retirement_income_taxable (the TAXABLE amount, not simply
    1099-R box 2a) OR retirement_distributions (each 1099-R as read, priced per box 7 code; never both; a
    traditional-IRA 1099-R with box 2b checked needs that person's ira_pool, Form 8606 Part I),
    social_security_benefits, other_income; student_loan_interest_paid, pre_agi_adjustments, treaty_exempt_income (Schedule OI for a
    nonresident, in parentheses on Schedule 1's other-income line for a resident alien), itemized_deductions
    (only if itemizing; NRAs itemize only), other_state_local_taxes (state and local taxes beyond W-2 box 17),
    foreign_tax_paid (the credit is NOT estimated); qualified_tips, qualified_overtime_premium (the FLSA premium
    half only), car_loan_interest (Schedule 1-A: BELOW AGI, never in pre_agi_adjustments or
    itemized_deductions; MFS forfeits all but car-loan interest); w2s [{employer?, box1..box7, box10, box12:
    [{code, amount}], box14b?, box17?}] (the aggregates derive from them; one also given must agree);
    medicare_wages, ss_wages, medicare_tax_withheld (never also in federal_withholding),
    ss_withheld_by_employer, aotc_qualified_expenses, aotc_students_ssn_ok, dependent_care_expenses,
    dependent_care_persons, aca_premiums, aca_slcsp, aca_aptc; spouse (the spouse's OWN amounts, same fields —
    a true two-return MFS comparison; otherwise amounts are couple-combined).

    Itemizing (JW2a): with no itemized_deductions, result.itemizing_comparison weighs the state and local tax
    given (box 17 + other_state_local_taxes, after the year's limit) against the standard deduction — over it,
    the range includes the itemized outcome; at least half of it, the result lists what else to collect.
    result.roadmap.returns_and_forms lists the LIKELY schedules and forms the inputs imply (not exhaustive) and
    the state return(s) the state footprint requires; every dollar figure is the federal return only. An
    income document the profile records as not_applicable is an answer, not a gap.

    Residency (P-018): record the §6013(g)/(h) election as profile residency_facts.section_6013_election (true =
    elected or still in effect, false = declined) and each prior-year return in prior_filings.return_forms; the
    result's residency_caveat and its FIRST assumption carry the election and any contradiction — quote them.
    Schedule 3-A (2026 onward): record identity.qualified_alien_status (and household.spouse's); without a
    U.S. citizen, national or qualified alien on the return the LOW end holds back the refunded EIC, ACTC and
    AOTC.

    The result's `composition` is a ledger whose effects sum EXACTLY to `point`; with >=2 statuses,
    comparison.delta_lines itemizes the difference. `missing_blocks` lists items a planning year's pack does
    not price, with the direction of the error — surface those before comparing years.
    """
    try:
        prof = Profile.model_validate(profile)
    except ValidationError as exc:
        raise ValueError(
            f"invalid `profile` — {_validation_problems(exc)}. Top-level profile sections: "
            f"{', '.join(Profile.model_fields)}; build it with intake_checklist (its empty-profile result "
            f"carries `example_profile`, the exact shape) and pass its answers back unchanged."
        ) from None
    try:
        snapshot = IncomeSnapshot.model_validate(income)
    except ValidationError as exc:
        raise ValueError(
            f"invalid `income` — {_validation_problems(exc)}. Valid income fields: "
            f"{', '.join(IncomeSnapshot.model_fields)}. Whole dollars; capital gains go in "
            f"capital_gain_long/capital_gain_short (signed), not 'capital_gains'. Each field's meaning: "
            f'calc(op="describe", args={{"op": "estimate_refund"}}).'
        ) from None
    return _dump(_estimate_refund(prof, year, snapshot))


@mcp.tool()
def compare_scenarios(
    year: int,
    scenarios: list[dict] | None = None,
    income: dict | None = None,
    profile: dict | None = None,
    save_as: str | None = None,
    load: str | None = None,
    income_updates: dict | None = None,
    root: str = WORKSPACE_ROOT,
) -> dict:
    """Run 2+ what-if scenarios and diff each against the FIRST (the baseline), with TWO exact
    attributions per diff: the per-slot ledger view, and a sequential input walk whose steps
    telescope to the headline delta (this is how the delta of a "marry + \u00a76013(g) election"
    scenario decomposes into one line per input change: the year (for a cross-year scenario), then
    the election, then the filing status, then each income override in the order given).

    Each scenario: {name, filing_status (REQUIRED - deterministic, never candidate-selected),
    year? (cross-year what-ifs - the result is labeled PROJECTION when any year's pack is
    provisional, and per-scenario missing_blocks flag what a planning year could not price),
    us_resident_election? (models \u00a76013(g)/(h) as the residency fact
    residency_facts.section_6013_election. OMITTED = follow the profile's recorded fact (a
    continuing election stays in effect); true = elect: both spouses are residents for the whole
    year, so the figure takes RESIDENT rules - standard deduction, NIIT (the Treas. Reg. 1.1411-2(a)(2)(iii)/(iv) default unless the second election applies), no 871(i)(2)(A) deposit
    exclusion - on MFJ and on MFS alike, whatever the visa timeline says; false = NOT electing
    (declined, or revoking a continuing election) for that scenario - it pairs with MFS: false on
    MFJ for a couple with a nonresident in it is NOT a filing option (Pub 519 FAQ), priced as the
    separate returns. A value that overrides the recorded fact is named in the assumptions; every
    scenario that ran under the election - flagged, recorded, or read from a confirmed MFJ status
    of a nonresident - is named, with its residency_caveat on the outcome (worldwide income, FICA,
    the statement, the precondition), and the walk ends on each scenario's own configuration, booking
    a change of the election's reading to the step where it happens. Never `recommended` (None when
    nothing is a filing option): a JOINT scenario seeking an election the recorded facts rule out (a
    separate one, priced without it, stays an option), MFJ with the election declined, MFS under a
    definite 6013(h) choice, or head of household for a nonresident-alien taxpayer (Pub 519 ch. 5)),
    income_overrides? ({IncomeSnapshot field: value};
    'spouse' replaces the whole spouse snapshot; attribution applies them in this order — a subset
    and its parent (interest / bank_deposit_interest / bank_deposit_interest_nonresident_period,
    dividends / qualified_dividends) and dependent_care_expenses / dependent_care_persons move as
    ONE step, in either key order, so no intermediate snapshot is invalid), note?}.

    PERSISTENCE (the "change one fact and re-diff" loop): pass save_as="name" to store the set
    (INPUTS only - results recompute on every load) in the year's workspace; later call with
    load="name" (+ optional income_updates to revise base facts, and/or a new scenarios list) to
    re-run and re-save in one step. Saved sets are listed by workspace_load's status.
    """
    ws = Workspace.open(root, year, now=_now()) if (save_as or load) else None
    if load:
        stored = ws.load_scenario_set(load)
        base_income = {**stored["income"], **(income_updates or {})}
        specs = scenarios if scenarios is not None else stored["scenarios"]
        prof_data = profile if profile is not None else stored.get("profile")
        save_as = save_as or load
    else:
        if income is None or scenarios is None:
            raise ValueError(
                "compute mode needs `income` and `scenarios` (or pass load='name' to re-run a saved "
                "set); the first scenario is the baseline"
            )
        base_income, specs, prof_data = income, scenarios, profile
    try:
        prof = Profile.model_validate(prof_data) if prof_data else Profile()
    except ValidationError as exc:
        raise ValueError(f"invalid `profile` — {_validation_problems(exc)}") from None
    try:
        snapshot = IncomeSnapshot.model_validate(base_income)
    except ValidationError as exc:
        raise ValueError(
            f"invalid income — {_validation_problems(exc)}. Valid income fields: "
            f"{', '.join(IncomeSnapshot.model_fields)}."
        ) from None
    result = _compare_scenarios(prof, year, snapshot, specs)
    if save_as:
        ws.save_scenario_set(save_as, {
            "year": year,
            "income": snapshot.model_dump(mode="json"),
            "scenarios": [s if isinstance(s, dict) else s.model_dump(mode="json") for s in specs],
            "profile": prof_data if isinstance(prof_data, dict) else None,
        }, now=_now())
    out = _dump(result)
    if save_as:
        out["saved_as"] = save_as
    return out


@mcp.tool()
def get_sources(topic: str, year: int, jurisdiction: str = "federal") -> dict:
    """Ranked official .gov sources for a topic + the freshness change-channels (freshness protocol)."""
    return _dump(_get_sources(topic, year, jurisdiction))


@mcp.tool()
def filing_summary(manifest: list[dict]) -> dict:
    """Plain-language bottom line per return (refund/owed + deadline & refund-SOL status) for approval.

    Each manifest item: {form, tax_year, jurisdiction?, bottom_line (signed: +refund/-owed),
    paid_online?, state?, direct_deposit?, filing_jointly?, amended? (an amended return: Form 1040-X, a
    state's amended form, or an original form with its amended box; a form number ending in X counts
    without it), section_6013_election? (adds the
    signed-by-both-spouses NRA-spouse election statement to the assembly checklist),
    taxpayer? (label each return's owner — "me" / "Partner P" — and a 2+-person household gets
    `household_rollup`: per-person subtotals + the household net, framed as one budget across
    TWO taxpayers whose refunds/balances never offset each other at the IRS)}.
    """
    return _dump(_filing_summary([FilingManifestItem.model_validate(m) for m in manifest]))


@mcp.tool()
def file_and_pay(manifest: list[dict]) -> dict:
    """Last-mile checklist per return: pay, sign, assemble, mail, records, deadlines. Same manifest as
    filing_summary, plus `dual_status?` — true for a split-residency-year return makes the assembly
    checklist lead with the "Dual-Status Return"/"Dual-Status Statement" annotations, the
    no-standard-deduction reminder, and the sign-the-return-not-the-statement rule. A FICA
    withheld-in-error claim is its own item: form "843" with attached_forms ["8316"] (bottom_line =
    the claimed W-2 box 4 + box 6 total) — it gets the claim's separate mailing checklist (Ogden per
    the current Pub 519), never attached to the 1040-NR. An amended return gets its own checklist: a
    Form 1040-X (list the corrected '1040' / '1040-NR' in attached_forms) follows the current Form
    1040-X instructions for its address, payment, attachments and time limits; a state amended return
    follows the state pack's amended-return rules, or points to the DOR when the pack has none."""
    return _dump(_file_and_pay([FilingManifestItem.model_validate(m) for m in manifest]))


@mcp.tool()
def hand_fill_worksheet(form: str, year: int, jurisdiction: str, values: dict[str, Any] | None = None) -> dict:
    """Print-only state forms (no fillable AcroForm fields) — CT (ct1040), HI (n11), NM (pit1),
    SC (sc1040), and WV (it140) for TY2025 only. These packs are NOT returned by
    list_forms, so an empty list_forms for those states is expected, not an error: compute a
    line->value worksheet to hand-write onto the printed blank. `values` maps line ids to
    entered amounts/text/checkbox; lines with a compute expression are derived from earlier
    lines (a pack whose form's tips forbid zero-filled lines leaves an all-blank compute blank
    and may print money without commas — read the worksheet's instructions, P-029). Returns
    the ordered worksheet (line, label, value, source) + the print_url of the
    official blank. Only for jurisdictions that ship a print-only pack; use fill_form otherwise."""
    pack = load_hand_fill_pack_for(form, year, jurisdiction)
    return _dump(_hand_fill_worksheet(pack, values or {}))


def main() -> None:
    """Console entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
