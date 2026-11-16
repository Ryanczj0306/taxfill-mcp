"""Guard (Phase K JK32): every tool description fits the client's cut, and nothing calc lost is out of reach.

Claude Code shows a client only the first 4,096 characters of a tool description when tools load upfront (and
the same 4,096 of the server instructions). Before JK32 calc's description was 46,848 characters and
estimate_refund's 14,672, so most of both was never read. Both now keep upfront the op list, the PROVISIONAL rule
and the sentences that prevent a wrong number; each op's former per-op bullet, and estimate_refund's former
docstring, are served by calc(op="describe"). The two fixtures are those docstrings as of 75a72e2, frozen: an
intentional later edit to an op's notes edits the fixture too.
"""

from __future__ import annotations

import re
from pathlib import Path

import anyio
import pytest

from taxfill_mcp import server
from taxfill_mcp.server import calc, mcp

FIXTURES = Path(__file__).parent / "fixtures"
OLD_CALC = (FIXTURES / "calc_description_75a72e2.txt").read_text(encoding="utf-8").rstrip("\n")
OLD_ESTIMATE = (FIXTURES / "estimate_refund_description_75a72e2.txt").read_text(encoding="utf-8").rstrip("\n")
OLD_BULLETS = dict(re.findall(r"^- ([a-z0-9_]+): (.*?)(?=\n- [a-z0-9_]+: |\Z)", OLD_CALC, flags=re.S | re.M))
LIMIT = 4096


def _flat(text: str) -> str:
    return " ".join(text.split())


def _descriptions() -> dict[str, str]:
    return {t.name: t.description or "" for t in anyio.run(mcp.list_tools)}


def _dispatch_ops() -> set[str]:
    return set(re.findall(r'if op == "([a-z0-9_]+)"', Path(server.__file__).read_text(encoding="utf-8")))


def test_every_tool_description_and_the_instructions_fit_the_client_cut():
    long = {name: len(text) for name, text in _descriptions().items() if len(text) > LIMIT}
    assert not long, f"over {LIMIT} characters (the client drops the rest): {long}"
    assert len(mcp.instructions or "") <= LIMIT


def test_calc_upfront_keeps_every_op_and_the_provisional_rule():
    desc = _descriptions()["calc"]
    listed = {op.strip() for op in re.search(r"op in \{([^}]*)\}", desc).group(1).split(",")}
    assert listed == _dispatch_ops(), f"calc's op list: missing {_dispatch_ops() - listed}, not an op {listed - _dispatch_ops()}"
    provisional = OLD_CALC[OLD_CALC.index("A result computed off a PROVISIONAL"):OLD_CALC.index("\n\n- tax:")]
    assert _flat(provisional) in _flat(desc)
    assert 'calc(op="describe", args={"op": "<name>"})' in desc


def test_the_registry_is_the_dispatch_and_the_old_bullets_verbatim():
    assert set(server._CALC_OP_DOCS) == _dispatch_ops() == set(OLD_BULLETS)
    for op, bullet in OLD_BULLETS.items():
        assert server._CALC_OP_DOCS[op] == bullet, op           # byte-exact against the 75a72e2 docstring


@pytest.mark.parametrize("op", sorted(OLD_BULLETS))
def test_describe_returns_the_whole_former_bullet(op):
    out = calc("describe", {"op": op})
    assert out["op"] == op and _flat(OLD_BULLETS[op]) in _flat(out["text"])   # whitespace-normalized
    assert out["args"] and out["args"].startswith("{") and out["args"] in _flat(OLD_BULLETS[op])


def test_describe_without_an_op_lists_them_and_estimate_refund_returns_its_former_docstring():
    listing = calc("describe", {})
    assert set(listing["ops"]) == _dispatch_ops() and "estimate_refund" in listing["also"]
    assert server._ESTIMATE_REFUND_GUIDE == OLD_ESTIMATE
    assert _flat(calc("describe", {"op": "estimate_refund"})["text"]) == _flat(OLD_ESTIMATE)
    assert 'calc(op="describe", args={"op": "estimate_refund"})' in _descriptions()["estimate_refund"]
    with pytest.raises(ValueError, match="describe: unknown calc op 'bogus'"):
        calc("describe", {"op": "bogus"})


def test_a_wrong_argument_names_the_ops_argument_list():
    with pytest.raises(TypeError) as exc:
        calc("tax", {"income": 50_000, "filing_status": "single", "year": 2025})
    text = str(exc.value)
    assert "unexpected keyword argument 'income'" in text
    assert "takes args {taxable_income, filing_status, year}" in text and '"op": "tax"' in text
    with pytest.raises(ValueError, match="unknown calc op 'bogus'") as exc:
        calc("bogus", {})
    assert all(op in str(exc.value) for op in _dispatch_ops()) and "describe" in str(exc.value)


def test_a_refusal_passes_through_unchanged():
    # Only the signature TypeError gains the argument list; an op's own refusal text is untouched
    # (the state_tax goldens store it).
    with pytest.raises(ValueError) as exc:
        calc("state_tax", {"state": "zz", "taxable_base": 1_000, "year": 2025})
    assert "takes args" not in str(exc.value)
