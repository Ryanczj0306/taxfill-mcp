"""ABA routing-number checksum tests. All routing numbers are synthetic
(constructed to satisfy or violate the 3-7-1 checksum), never real accounts."""

import pytest

from taxfill_core.calc import aba_checksum_ok, is_valid_routing_number

# Synthetic numbers constructed so that 3-7-1 weighted sum % 10 == 0,
# with prefixes inside the assigned ranges (01-12, 21-32).
KNOWN_GOOD = [
    "111111118",  # 3+7+1+3+7+1+3+7+8 = 40
    "222222226",  # 6+14+2+6+14+2+6+14+6 = 70
    "123123123",  # 3+14+3+3+14+3+3+14+3 = 60
    "011000015",  # 0+7+1+0+0+0+0+7+5 = 20
]

KNOWN_BAD_CHECKSUM = [
    "123456789",  # weighted sum 159 -> 9 mod 10
    "111111119",  # one off from a valid number
    "011000016",  # last-digit typo
    "987654321",
]

MALFORMED = [
    "",  # empty
    "12345678",  # 8 digits
    "1231231234",  # 10 digits
    "12312312a",  # non-digit
    "123-12312",  # dashes are not digits (comb-cell lesson, pitfall P-001)
    "12312312١",  # non-ASCII digit (Arabic-Indic one) must be rejected
    " 23123123",  # leading space
]


@pytest.mark.parametrize("routing", KNOWN_GOOD)
def test_known_good_routing_numbers(routing):
    assert aba_checksum_ok(routing) is True
    assert is_valid_routing_number(routing) is True


@pytest.mark.parametrize("routing", KNOWN_BAD_CHECKSUM)
def test_known_bad_checksums(routing):
    assert aba_checksum_ok(routing) is False
    assert is_valid_routing_number(routing) is False


@pytest.mark.parametrize("routing", MALFORMED)
def test_malformed_inputs_rejected(routing):
    assert aba_checksum_ok(routing) is False
    assert is_valid_routing_number(routing) is False


def test_all_zeros_passes_raw_checksum_but_is_not_valid():
    # Degenerate case: the weighted sum of all zeros is 0 (checksum passes),
    # but 00 is not an ACH-eligible prefix, so full validation rejects it.
    assert aba_checksum_ok("000000000") is True
    assert is_valid_routing_number("000000000") is False


@pytest.mark.parametrize("prefix", ["13", "20", "33", "60", "73", "99"])
def test_unassigned_prefixes_rejected_even_with_valid_checksum(prefix):
    # Brute-force a final digit that satisfies the checksum for this prefix,
    # then confirm full validation still rejects the unassigned prefix range.
    base = prefix + "000000"
    candidate = next(base + d for d in "0123456789" if aba_checksum_ok(base + d))
    assert is_valid_routing_number(candidate) is False


def test_non_string_input_rejected():
    assert aba_checksum_ok(111111118) is False  # type: ignore[arg-type]
    assert is_valid_routing_number(None) is False  # type: ignore[arg-type]
