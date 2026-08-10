"""The shared PII redaction (Stage 1, release item P4).

Before this module existed, redaction lived as a private CLI helper with zero
tests, while the README promised masking and the engine's own comb-overflow
error — the error SSNs hit most, quoted in the skill as the canonical example —
echoed the digits back verbatim into the agent transcript.
"""

from __future__ import annotations

import pytest

from taxfill_core.redact import redact


def test_ssn_shapes_are_masked():
    assert redact("value '000-00-0000' overflowed") == "value '[redacted-id]' overflowed"
    assert redact("id 000 00 0000 given") == "id [redacted-id] given"
    assert redact("bare 000000000 run") == "bare [redacted-id] run"


def test_long_digit_runs_are_masked():
    assert redact("account 12345678 at bank") == "account [redacted-number] at bank"
    assert redact("routing 123456789...") == "routing [redacted-id]..."  # 9 digits = id-shaped first


def test_ordinary_error_text_survives():
    msg = "line '1z': value is 12 characters but the field allows at most 9"
    assert redact(msg) == msg  # short numbers (line ids, lengths, years) untouched
    assert redact("tax year 2026, $1,234 due") == "tax year 2026, $1,234 due"


def test_the_filler_comb_error_no_longer_echoes_the_ssn():
    # The canonical leak: an SSN with a typo overflows the 9-cell comb, and the
    # prescriptive error used to echo it. The message stays prescriptive — the
    # length and the fix are named — but the digits never leave the process.
    from taxfill_core.schemas.formpack import PackField

    from taxfill_core.filler import _enforce_length

    pf = PackField(line="identifying_number", field="f1", type="text", maxlen=9, comb=True)
    with pytest.raises(ValueError) as exc:
        _enforce_length(pf, "00000000099")  # 11 digits: a mistyped SSN, dashes pre-stripped
    msg = str(exc.value)
    assert "00000000099" not in msg
    assert "[redacted-" in msg and "resubmit digits only" in msg and "11 characters" in msg
