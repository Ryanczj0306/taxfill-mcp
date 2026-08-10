"""PII redaction for error text — one implementation, every surface.

Tool errors travel: a CLI prints to stderr a shell agent may capture, and an
MCP tool's exception lands verbatim in the agent transcript, which clients may
log or sync. A wrong-shaped input is still an input — '000-00-0000-99' in a
comb-overflow error is an SSN with a typo — so any error that echoes a value
must redact identifier-shaped content first.

Until Stage 1 this lived as a private helper in the CLI only: the README
promised masking, the MCP path had none, and the filler's own comb error —
the one error SSNs hit most — echoed the digits back (the skill even quoted it
with an SSN-shaped value as the canonical example). Now the CLI, the filler
and anything else that echoes user values import :func:`redact` from here.

Deliberately narrow: SSN/ITIN-shaped ids and long digit runs (account/routing
numbers). Names and addresses are not pattern-redactable and must simply never
be echoed — the PII-safe convention verify.py already follows.
"""

from __future__ import annotations

import re

__all__ = ["redact"]

# 9-digit id with optional group separators (SSN/ITIN/EIN-shaped).
_SSN_RE = re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b")
# Any 6+ digit run: account numbers, routing numbers, document ids.
_LONGNUM_RE = re.compile(r"\b\d{6,}\b")


def redact(text: str) -> str:
    """Mask identifier-shaped content in ``text`` before it leaves the process."""
    return _LONGNUM_RE.sub("[redacted-number]", _SSN_RE.sub("[redacted-id]", text))
