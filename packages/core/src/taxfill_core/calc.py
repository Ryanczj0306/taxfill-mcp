"""Deterministic calculation primitives (dev plan sections 3 and 8).

M0 ships the one real algorithm worth shipping early: the ABA routing-number
checksum used to validate banking details collected at intake (dev plan
section 4: "banking ... checksum-validated"). Tax tables, day counting, and
rounding arrive in M1.

These functions are pure: no I/O, no logging, no side effects. They never
echo the value being validated (routing/account numbers are sensitive; see
the redaction rules in the dev plan, section 8).
"""

from __future__ import annotations

# ABA position weights for the 9-digit routing transit number checksum.
_ABA_WEIGHTS = (3, 7, 1, 3, 7, 1, 3, 7, 1)

# First-two-digit prefixes currently assigned to ACH-eligible institutions:
# 01-12 (Federal Reserve districts) and 21-32 (thrift institutions).
_VALID_PREFIX_RANGES = ((1, 12), (21, 32))


def aba_checksum_ok(routing: str) -> bool:
    """Return True if ``routing`` passes the ABA 3-7-1 checksum.

    The checksum is defined for exactly nine ASCII digits ``d1..d9``:

        (3*d1 + 7*d2 + 1*d3 + 3*d4 + 7*d5 + 1*d6 + 3*d7 + 7*d8 + 1*d9) % 10 == 0

    This is the pure checksum only. It does not check prefix assignment
    ranges — use :func:`is_valid_routing_number` for full validation
    (e.g. the all-zeros string passes the checksum but is not a real
    routing number).
    """
    if not isinstance(routing, str):
        return False
    if len(routing) != 9 or not routing.isascii() or not routing.isdigit():
        return False
    return sum(w * int(d) for w, d in zip(_ABA_WEIGHTS, routing)) % 10 == 0


def is_valid_routing_number(routing: str) -> bool:
    """Validate a US bank routing transit number for direct deposit/debit.

    Checks, in order:

    1. exactly nine ASCII digits (no dashes, no spaces — callers must pass
       the raw digits exactly as printed on a check);
    2. the first two digits fall in an assigned ACH-eligible prefix range
       (01-12 or 21-32), which also rejects the degenerate all-zeros value;
    3. the ABA 3-7-1 checksum (:func:`aba_checksum_ok`).

    Pure predicate: returns a bool, raises nothing, logs nothing.
    """
    if not isinstance(routing, str):
        return False
    if len(routing) != 9 or not routing.isascii() or not routing.isdigit():
        return False
    prefix = int(routing[:2])
    if not any(low <= prefix <= high for low, high in _VALID_PREFIX_RANGES):
        return False
    return aba_checksum_ok(routing)
