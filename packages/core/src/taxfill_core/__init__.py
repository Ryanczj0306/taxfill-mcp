"""taxfill-core — pure-Python core for TaxFill (no MCP dependency).

Single source of truth: ``docs/DEV_PLAN.md`` at the repo root.

Status: v0.1 is IN DEVELOPMENT. M0 shipped the schemas (form packs, intake
profile) and the routing-number checksum; M1 ships the engine exported here:

* **calc** — deterministic tax math over versioned knowledge packs
  (:func:`tax_from_taxable_income`, :func:`standard_deduction`,
  :func:`se_tax`, :func:`irs_round`, presence-day counting, ABA checksum);
* **residency** — substantial presence test, exempt-individual years, and
  the nonresident/resident/dual-status classification (:func:`classify`);
* **filler** — deterministic AcroForm filling from a pack's line->field map
  (:func:`fill_form`);
* **verify** — the mandatory gate: assertion diff, relation math,
  independent recompute, clipping scan, checkbox audit, regression diff,
  cross-form/identity checks (:func:`verify_form`, :func:`verify_filing`);
* **render** — PDF pages to PNG for the vision-review pass
  (:func:`render_pdf`);
* **knowledge** — the per-year jurisdiction data loader
  (:func:`load_knowledge`).

Form packs arrive in M2, the MCP server in M4.

TaxFill is the execution layer for AI tax prep. It is NOT tax advice and NOT
a tax preparer: every output is a review draft, and the human reviews, signs,
and files (paper print-and-mail by design — no e-filing). Everything runs
100% locally with no telemetry; the only outbound traffic (in later
milestones) is downloading blank forms from official .gov URLs.
"""

from taxfill_core.calc import (
    SeTaxResult,
    StandardDeductionResult,
    TaxResult,
    aba_checksum_ok,
    irs_round,
    is_valid_routing_number,
    presence_days,
    presence_days_by_year,
    se_tax,
    standard_deduction,
    tax_from_taxable_income,
)
from taxfill_core.estimate import CompositionLine, IncomeSnapshot, RefundEstimate, estimate_refund
from taxfill_core.filler import FillResult, fill_form
from taxfill_core.intake import IntakeChecklist, IntakeQuestion, RequiredDocument, intake_checklist
from taxfill_core.knowledge import Citation, KnowledgePack, load_knowledge
from taxfill_core.render import RenderedPage, render_pdf
from taxfill_core.residency import (
    ClassificationResult,
    ExemptYearsResult,
    SPTResult,
    classify,
    exempt_individual_years,
    substantial_presence_test,
)
from taxfill_core.schemas.formpack import FormPack, PackField, load_pack
from taxfill_core.schemas.profile import Answer, Profile, Provenance
from taxfill_core.sources import Source, SourcesResult, get_sources
from taxfill_core.verify import (
    FilingItem,
    TextWidget,
    VerifyReport,
    assertion_diff,
    checkbox_audit,
    clipping_scan,
    independent_recompute,
    read_pdf_fields,
    read_text_widgets,
    regression_diff,
    relations,
    verify_filing,
    verify_form,
)

__version__ = "0.1.0.dev0"

__all__ = [
    "Answer",
    "Citation",
    "ClassificationResult",
    "CompositionLine",
    "ExemptYearsResult",
    "FilingItem",
    "FillResult",
    "FormPack",
    "IncomeSnapshot",
    "IntakeChecklist",
    "IntakeQuestion",
    "KnowledgePack",
    "PackField",
    "Profile",
    "Provenance",
    "RefundEstimate",
    "RenderedPage",
    "RequiredDocument",
    "SPTResult",
    "Source",
    "SourcesResult",
    "SeTaxResult",
    "StandardDeductionResult",
    "TaxResult",
    "TextWidget",
    "VerifyReport",
    "__version__",
    "aba_checksum_ok",
    "assertion_diff",
    "checkbox_audit",
    "classify",
    "clipping_scan",
    "estimate_refund",
    "exempt_individual_years",
    "fill_form",
    "get_sources",
    "independent_recompute",
    "intake_checklist",
    "irs_round",
    "is_valid_routing_number",
    "load_knowledge",
    "load_pack",
    "presence_days",
    "presence_days_by_year",
    "read_pdf_fields",
    "read_text_widgets",
    "regression_diff",
    "relations",
    "render_pdf",
    "se_tax",
    "standard_deduction",
    "substantial_presence_test",
    "tax_from_taxable_income",
    "verify_filing",
    "verify_form",
]
