"""TaxFill MCP server — dev plan section 8.

A thin MCP wrapper (official ``mcp`` python-sdk, FastMCP) over the tested
``taxfill_core`` engine. The agent does interviewing/judgment; these tools do
all the deterministic PDF/calc work. Design commitments hold: 100% local, no
telemetry; the only outbound traffic is downloading blank forms from official
.gov URLs (``fetch_blank``). Every output is a review draft — the human signs
and files.

Tools take agent-friendly arguments (``form``/``year``, not raw FormPack
objects) and load packs internally. ``render_form`` returns MCP image content so
the calling agent can vision-review every page (the mandatory verify gate).
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from taxfill_core import (
    additional_medicare_tax as _additional_medicare_tax,
    education_credits as _education_credits,
    estimate_refund as _estimate_refund,
    excess_ss as _excess_ss,
    file_and_pay as _file_and_pay,
    fill_form as _fill_form,
    filing_summary as _filing_summary,
    get_sources as _get_sources,
    intake_checklist as _intake_checklist,
    niit as _niit,
    ptc_annual as _ptc_annual,
    render_pdf as _render_pdf,
    se_tax as _se_tax,
    standard_deduction as _standard_deduction,
    state_scope as _state_scope,
    student_loan_interest_deduction as _student_loan_interest_deduction,
    tax_from_taxable_income as _tax,
    tax_with_preferential_rates as _tax_with_preferential_rates,
    taxable_social_security as _taxable_social_security,
    verify_filing as _verify_filing,
    verify_form as _verify_form,
)
from taxfill_core.discovery import get_form_map as _get_form_map, list_forms as _list_forms, load_form_pack
from taxfill_core.extract import extract_document as _extract_document, list_document_kinds as _list_document_kinds
from taxfill_core.fetch import fetch_blank as _fetch_blank
from taxfill_core.handfill import hand_fill_worksheet as _hand_fill_worksheet, load_hand_fill_pack_for
from taxfill_core.estimate import IncomeSnapshot
from taxfill_core.file_and_pay import FilingManifestItem
from taxfill_core.residency import classify as _classify
from taxfill_core.schemas.profile import Profile
from taxfill_core.verify import FilingItem, VerifyReport
from taxfill_core.workspace import Position, Workspace

WORKSPACE_ROOT = "taxfill-workspace"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

mcp = FastMCP(
    "taxfill",
    instructions=(
        "Deterministic tax-prep execution layer. You interview the user and decide positions; "
        "these tools fill, verify, render, and compute — never do tax arithmetic yourself, and "
        "never invent a value (unknown stays a gap). Always treat output as a review draft: the "
        "user reviews, signs, and files. Typical flow: intake_checklist -> (extract+confirm) -> "
        "estimate_refund -> list_forms/get_form_map -> fetch_blank -> fill_form -> verify_form/"
        "verify_filing (loop until ok) -> render_form (vision-review every page) -> filing_summary "
        "(approve) -> file_and_pay."
    ),
)


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def _report_summary(report: VerifyReport) -> dict:
    """Compact, agent-actionable view of a VerifyReport (ok + per-section failures)."""
    sections: dict[str, Any] = {}
    for name in ("assertions", "relations", "recompute", "clipping", "checkboxes", "identity", "cross_form"):
        checks = getattr(report, name) or []
        fails = [c.detail for c in checks if getattr(c, "status", None) == "FAIL"]
        sections[name] = {"checked": len(checks), "failed": len(fails), "failures": fails}
    return {
        "ok": report.ok,
        "form_keys": report.form_keys,
        "sections": sections,
        "pitfalls": [{"id": p.id, "status": p.status, "detail": p.detail} for p in report.pitfall_checks],
    }


# ── discovery ────────────────────────────────────────────────────────────────


@mcp.tool()
def list_forms(jurisdiction: str | None = None, year: int | None = None) -> list[dict]:
    """List available form packs (optionally filtered by jurisdiction/year)."""
    return [_dump(s) for s in _list_forms(jurisdiction, year)]


@mcp.tool()
def get_form_map(form: str, year: int, jurisdiction: str = "federal") -> dict:
    """Return one pack's line->field map, relations, and cross-form refs.

    `form` is the form KEY (e.g. 'f1040', 'sched_c'). Use list_forms to discover keys.
    """
    return _dump(_get_form_map(form, year, jurisdiction))


# ── fetch / fill / verify / render ─────────────────────────────────────────────


@mcp.tool()
def fetch_blank(form: str, year: int, jurisdiction: str = "federal") -> dict:
    """Download the official blank PDF (checksum-verified) and return its local path."""
    pack = load_form_pack(form, year, jurisdiction)
    path = _fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    return {"path": str(path), "source_url": pack.source_url, "sha256": pack.pdf_sha256}


@mcp.tool()
def fill_form(form: str, year: int, values: dict[str, Any], out_path: str, jurisdiction: str = "federal") -> dict:
    """Deterministically fill a form. `values` maps line ids (per get_form_map) to values.

    Downloads/uses the official blank, writes the filled PDF to out_path, and returns the
    written lines + any warnings. Rejects unknown lines and comb/length violations.
    """
    pack = load_form_pack(form, year, jurisdiction)
    blank = _fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    result = _fill_form(pack, values, blank, Path(out_path))
    return {"out_path": out_path, "written": result.written, "warnings": result.warnings}


@mcp.tool()
def verify_form(
    form: str, year: int, pdf_path: str, expected: dict[str, Any] | None = None, jurisdiction: str = "federal"
) -> dict:
    """Verify a filled form against its pack: assertions, relation math + independent recompute,
    clipping scan, required-checkbox audit, and the pitfall registry. Returns ok + failures."""
    pack = load_form_pack(form, year, jurisdiction)
    report = _verify_form(pack, pdf_path, expected=expected)
    return _report_summary(report)


@mcp.tool()
def verify_filing(items: list[dict]) -> dict:
    """Verify a whole filing across forms: cross-form identity + inter-form relations.

    Each item: {form, year, pdf_path, jurisdiction?, form_key?}. form_key (defaults to `form`)
    is the key other forms' cross_form rules reference (e.g. 'sched_1', 'sched_oi').
    """
    filing_items = []
    for it in items:
        pack = load_form_pack(it["form"], it["year"], it.get("jurisdiction", "federal"))
        filing_items.append(
            FilingItem(form_key=it.get("form_key", it["form"]), pack=pack, pdf_path=Path(it["pdf_path"]))
        )
    return _report_summary(_verify_filing(filing_items))


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


@mcp.tool()
def calc(op: str, args: dict[str, Any]) -> dict:
    """Deterministic tax math. op in {tax, tax_with_preferential_rates, standard_deduction, se_tax,
    additional_medicare_tax, niit, taxable_social_security, excess_ss, student_loan_interest_deduction,
    education_credits, ptc_annual}; every result shows its work and cites the data pack.

    - tax: args {taxable_income, filing_status, year} (ORDINARY line 16 only — with qualified
      dividends or capital gains use tax_with_preferential_rates instead, even below $100,000)
    - tax_with_preferential_rates: args {taxable_income, qualified_dividends, net_long_term_gain?,
      net_short_term_gain?, filing_status, year} (Qualified Dividends and Capital Gain Tax Worksheet)
    - standard_deduction: args {filing_status, year, age_65_plus?, blind?}
    - se_tax: args {net_profit, year, w2_ss_wages?} (w2_ss_wages = W-2 box 3+7, Schedule SE lines 8a-9)
    - additional_medicare_tax: args {medicare_wages, filing_status, year, se_net_profit?} (Form 8959)
    - niit: args {net_investment_income, magi, filing_status, year} (Form 8960; NRAs exempt)
    - taxable_social_security: args {benefits, other_income, tax_exempt_interest?, filing_status,
      year, mfs_lived_with_spouse?} (SS Benefits Worksheet -> Form 1040 line 6b)
    - excess_ss: args {withheld_by_employer: [per-employer W-2 box 4, ONE person], year}
      (Schedule 3 excess-SS credit; multiple employers only)
    - student_loan_interest_deduction: args {interest_paid, magi, filing_status, year} (MFS gets $0)
    - education_credits: args {aotc_expenses_per_student: [...], llc_expenses?, magi, filing_status,
      year} (Form 8863 AOTC + LLC; MFS gets $0)
    - ptc_annual: args {household_income, household_size, annual_premiums, annual_slcsp, annual_aptc?,
      filing_status, year, state?} (Form 8962 annual method; state in other|alaska|hawaii; 2023-2024 only)
    """
    if op == "tax":
        return _dump(_tax(**args))
    if op == "tax_with_preferential_rates":
        return _dump(_tax_with_preferential_rates(**args))
    if op == "standard_deduction":
        return _dump(_standard_deduction(**args))
    if op == "se_tax":
        return _dump(_se_tax(**args))
    if op == "additional_medicare_tax":
        return _dump(_additional_medicare_tax(**args))
    if op == "niit":
        return _dump(_niit(**args))
    if op == "taxable_social_security":
        return _dump(_taxable_social_security(**args))
    if op == "excess_ss":
        return _dump(_excess_ss(**args))
    if op == "student_loan_interest_deduction":
        return _dump(_student_loan_interest_deduction(**args))
    if op == "education_credits":
        return _dump(_education_credits(**args))
    if op == "ptc_annual":
        return _dump(_ptc_annual(**args))
    raise ValueError(
        f"unknown calc op {op!r} — supported: tax, tax_with_preferential_rates, standard_deduction, "
        f"se_tax, additional_medicare_tax, niit, taxable_social_security, excess_ss, "
        f"student_loan_interest_deduction, education_credits, ptc_annual"
    )


@mcp.tool()
def residency(
    visa_periods: list[dict], days_by_year: dict[str, int], target_year: int, is_lawful_permanent_resident: bool = False
) -> dict:
    """Federal residency (NRA/RA/dual-status) via the Substantial Presence Test + exempt years.

    visa_periods: [{status, start, end?}]; days_by_year: {year: days_present}. Shows the day-count work.
    """
    days = {int(k): v for k, v in days_by_year.items()}
    return _dump(_classify(visa_periods, days, target_year, is_lawful_permanent_resident=is_lawful_permanent_resident))


# ── intake / estimate / sources / summary / file&pay ───────────────────────────


@mcp.tool()
def intake_checklist(profile: dict | None = None, tax_year: int | None = None) -> dict:
    """Next interview questions + required documents for a (partial) profile. Empty profile = start."""
    prof = Profile.model_validate(profile) if profile else None
    return _dump(_intake_checklist(prof, tax_year=tax_year))


@mcp.tool()
def list_document_kinds() -> list[dict]:
    """Supported tax-document types and their official box layouts (W-2, 1099-*, 1098-*, 1042-S).

    Read this first, then read the actual document with your own vision and pass the boxes you
    see to extract_document. Each kind cites the form's irs.gov layout page.
    """
    return _list_document_kinds()


@mcp.tool()
def extract_document(path: str, kind: str, fields: dict[str, Any], page: int | None = None) -> dict:
    """Structure + validate YOUR reading of one tax document into provenance-tagged fields.

    This does NOT do OCR — you read the document (image/PDF) with your own vision and pass the
    box->value map in `fields` (keys from list_document_kinds). The tool type-checks each value,
    tags it with document provenance (file + page), flags required boxes you didn't read as `gaps`,
    surfaces unreadable values as `invalid`, and returns a confirm-table. Never invent a box: any
    box you omit stays null. `kind` is e.g. "W-2", "1099-INT", "1042-S".
    """
    return _dump(_extract_document(path, kind, fields, page=page))


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

    A position with no `citation` is stored as `unverified` (never `decided`) — the return
    is not ready while any remain. Recording the same `topic` again replaces it (corrections).
    """
    ws = Workspace.open(root, year, now=_now())
    saved = ws.record_position(Position.model_validate(position), now=_now())
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
    """Early bottom-line ESTIMATE (a range) from a partial profile + confirmed income amounts.

    income fields: wages, federal_withholding, interest, dividends, self_employment_net,
    other_income, itemized_deductions? (all whole dollars, optional).
    """
    return _dump(_estimate_refund(Profile.model_validate(profile), year, IncomeSnapshot.model_validate(income)))


@mcp.tool()
def get_sources(topic: str, year: int, jurisdiction: str = "federal") -> dict:
    """Ranked official .gov sources for a topic + the freshness change-channels (freshness protocol)."""
    return _dump(_get_sources(topic, year, jurisdiction))


@mcp.tool()
def filing_summary(manifest: list[dict]) -> dict:
    """Plain-language bottom line per return (refund/owed + deadline & refund-SOL status) for approval.

    Each manifest item: {form, tax_year, jurisdiction?, bottom_line (signed: +refund/-owed),
    paid_online?, state?, direct_deposit?, filing_jointly?}.
    """
    return _dump(_filing_summary([FilingManifestItem.model_validate(m) for m in manifest]))


@mcp.tool()
def file_and_pay(manifest: list[dict]) -> dict:
    """Last-mile checklist per return: pay, sign, assemble, mail, records, deadlines. Same manifest as filing_summary."""
    return _dump(_file_and_pay([FilingManifestItem.model_validate(m) for m in manifest]))


@mcp.tool()
def hand_fill_worksheet(form: str, year: int, jurisdiction: str, values: dict[str, Any] | None = None) -> dict:
    """Print-only state forms (no fillable AcroForm fields — e.g. HI N-11): compute a
    line->value worksheet to hand-write onto the printed blank. `values` maps line ids to
    entered amounts/text/checkbox; lines with a compute expression are derived from earlier
    lines. Returns the ordered worksheet (line, label, value, source) + the print_url of the
    official blank. Only for jurisdictions that ship a print-only pack; use fill_form otherwise."""
    pack = load_hand_fill_pack_for(form, year, jurisdiction)
    return _dump(_hand_fill_worksheet(pack, values or {}))


def main() -> None:
    """Console entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
