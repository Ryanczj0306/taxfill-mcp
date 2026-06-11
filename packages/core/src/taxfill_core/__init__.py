"""taxfill-core — pure-Python core for TaxFill (no MCP dependency).

Single source of truth: ``docs/DEV_PLAN.md`` at the repo root.

Status: v0.1 is IN DEVELOPMENT. M0 ships the schemas (form packs, intake
profile) and the routing-number checksum; the fill/verify/render engine
arrives in M1, form packs in M2, the MCP server in M4.

TaxFill is the execution layer for AI tax prep. It is NOT tax advice and NOT
a tax preparer: every output is a review draft, and the human reviews, signs,
and files (paper print-and-mail by design — no e-filing). Everything runs
100% locally with no telemetry; the only outbound traffic (in later
milestones) is downloading blank forms from official .gov URLs.
"""

from taxfill_core.calc import aba_checksum_ok, is_valid_routing_number
from taxfill_core.schemas.formpack import FormPack, load_pack
from taxfill_core.schemas.profile import Answer, Profile, Provenance

__version__ = "0.1.0.dev0"

__all__ = [
    "Answer",
    "FormPack",
    "Profile",
    "Provenance",
    "__version__",
    "aba_checksum_ok",
    "is_valid_routing_number",
    "load_pack",
]
