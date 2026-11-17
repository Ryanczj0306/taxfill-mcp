"""Form 8995, the qualified business income deduction by the simplified computation (Phase K JW2d).

``qbi_deduction`` is the calc op for the 2025 Form 8995, walkthrough finding P1-01: a filer whose only QBI item
was a fund's section 199A dividends (Form 1099-DIV box 5) got an unmapped draft and no number. The op works the
face line by line, in whole dollars, each line from the rounded lines above it (the form is a whole-dollar form,
and the f8995 pack's relations compare whole dollars after IRS rounding, so a cents-exact chain could fail its own
``10 == 5 + 9``):

* Form 8995 (2025): "Use this form if your taxable income, before your qualified business income deduction, is
  at or below $197,300 ($394,600 if married filing jointly), and you aren't a patron of an agricultural or
  horticultural cooperative." Both figures and the 20% are read from the year's knowledge pack
  (``tax.qbi_deduction``), never typed here. Above the threshold, or for a cooperative patron, the op REFUSES and
  names Form 8995-A, which taxfill neither computes nor maps.
* Instructions for Form 8995 (2025), Exception 1: "If your 2025 taxable income before the QBI deduction is less
  than or equal to $394,600 if married filing jointly, and $197,300 for all others, your SSTB is treated as a
  qualified trade or business." So a specified service trade or business is no bar at or below the threshold;
  above it the threshold refusal applies whatever the business.
* The four boxes the face prints inside "( )" (the prior-year loss carryforwards and this year's carryforwards)
  are written as positive amounts: the parentheses are printed, and a minus sign inside them would read as a
  double negative. The pack's relations read each as its absolute value.

Every printed line number comes from the year's ``form_lines`` block (P-015), and the line-1 table's keys from the
f8995 pack itself, so the result's ``lines`` are the pack's own keys: ``fill_form(form="f8995", values=lines)``
takes them as they are, and ``independent`` (the money lines) is what ``verify_form`` compares in its recompute.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.knowledge import Citation, FormLineError, KnowledgePack, form_line, form_line_entry, load_knowledge

FORM_KEY = "f8995"
_STATUSES = ("single", "married_filing_jointly", "married_filing_separately", "head_of_household",
             "qualifying_surviving_spouse")
# form_lines roles of the Form 8995 lines this op computes, in face order (the designators live in the YAML).
_ROLES = ("qbi_total", "qbi_loss_carryforward", "qbi_net", "qbi_component", "reit_ptp", "reit_ptp_loss_carryforward",
          "reit_ptp_net", "reit_ptp_component", "before_limit", "taxable_income", "net_capital_gain", "limit_base",
          "income_limitation", "deduction", "qbi_carryforward", "reit_ptp_carryforward")
# The boxes printed inside "( )": left blank when zero (a blank reads as zero in the relations and the recompute).
_LOSS_BOXES = ("qbi_loss_carryforward", "reit_ptp_loss_carryforward", "qbi_carryforward", "reit_ptp_carryforward")

_HOLDING_PERIOD = (
    "Qualified REIT dividends (Form 1099-DIV box 5) count only if the holding period is met. The Instructions for "
    "Form 1099-DIV (Rev. January 2024): \"a qualified REIT dividend does not include any REIT dividend received "
    "with respect to any share of REIT stock that is held for 45 days or less during the 91-day period beginning on "
    "the date that is 45 days before the date on which such share became ex-dividend with respect to the dividend\"; "
    "for a fund (RIC), \"certain shareholders of the RIC that meet holding period requirements may treat [section "
    "199A dividends] as qualified REIT dividends\" (Regulations section 1.199A-3(d)); and box 5 may include REIT "
    "dividends \"for which it is impractical for the REIT to determine whether the recipient has met the holding "
    "period requirement\". Confirm the shares were held long enough before entering box 5 on Form 8995."
)


class QbiDeductionResult(BaseModel):
    """Result of :func:`qbi_deduction`: Form 8995 (simplified computation), every line."""

    model_config = ConfigDict(extra="forbid")

    deduction: int = Field(description="Form 8995's deduction line (form_lines f8995.deduction) -> the return's QBI "
                                       "deduction line (f1040.qbi_deduction, or f1040nr.qbi_deduction).")
    lines: dict[str, int | str] = Field(
        description="Every line to fill, keyed by the f8995 pack's own line keys: the line 1 table rows used "
                    "(business name, TIN, QBI) and the computed lines. A loss box printed inside '( )' carries the "
                    "loss as a positive amount and is left out when zero. Pass to fill_form(form='f8995') with the "
                    "filer's name and identifying_number."
    )
    independent: dict[str, int] = Field(
        description="The money lines of `lines`: verify_form's `independent` for the f8995 pack (the recompute)."
    )
    qbi_loss_carryforward: int = Field(description="The total qualified business (loss) carryforward to next year "
                                                   "(f8995.qbi_carryforward), as a positive amount.")
    reit_ptp_loss_carryforward: int = Field(description="The total qualified REIT dividends and PTP (loss) "
                                                        "carryforward to next year (f8995.reit_ptp_carryforward), "
                                                        "as a positive amount.")
    income_limited: bool = Field(description="True when the income limitation (f8995.income_limitation) is below "
                                             "the deduction before it (f8995.before_limit) and so sets the deduction.")
    threshold: int = Field(description="The year's taxable-income threshold for the filing status, at or below "
                                       "which Form 8995 may be used.")
    statement_businesses: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Businesses past the rows the face prints: attach a statement naming each, with its TIN; their "
                    "QBI is in the total line.",
    )
    confirm: list[str] = Field(default_factory=list, description="Facts the filer must confirm before filing.")
    inputs: dict[str, Any]
    work: str
    citation: Citation
    citations: list[Citation]


def _amount(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not {value!r}")
    try:
        number = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _dollars(value: Decimal) -> int:
    """IRS whole-dollar rounding: 50 cents or more rounds away from zero."""
    from taxfill_core.verify import irs_round  # noqa: PLC0415

    return irs_round(value)


def _fmt(n: int) -> str:
    return f"-${-n:,}" if n < 0 else f"${n:,}"


def _pack_table(year: int) -> tuple[list[str], dict[str, dict[str, str]]]:
    """The line-1 table of the year's f8995 pack: its rows in printed order and, per row, the key of its name, TIN
    and amount boxes (told apart by the pack's own types: the TIN is the text box with an SSN/TIN format)."""
    from taxfill_core.datadir import formpacks_dir  # noqa: PLC0415
    from taxfill_core.schemas.formpack import load_pack  # noqa: PLC0415

    path = formpacks_dir() / "federal" / str(year) / FORM_KEY / "pack.yaml"
    if not path.is_file():
        raise ValueError(f"qbi_deduction: no Form 8995 pack ships for {year}, so its lines have no keys to fill")
    rows: list[str] = []
    cells: dict[str, dict[str, str]] = {}
    for f in load_pack(path).fields:
        parts = f.line.split(".")
        if len(parts) != 3:
            continue
        row = parts[1]
        if row not in cells:
            rows.append(row)
            cells[row] = {}
        role = "qbi" if f.type == "money" else ("tin" if f.format else "name")
        cells[row][role] = f.line
    return rows, cells


def _line(pack: KnowledgePack, role: str) -> str:
    return form_line(pack, f"{FORM_KEY}.{role}")


def qbi_deduction(
    taxable_income_before_qbi: Any,
    filing_status: str = "single",
    year: int = 2025,
    businesses: list[dict[str, Any]] | None = None,
    qbi_loss_carryforward: Any = 0,
    qualified_reit_dividends: Any = 0,
    ptp_income: Any = 0,
    reit_ptp_loss_carryforward: Any = 0,
    qualified_dividends: Any = 0,
    net_capital_gain: Any = None,
    schedule_d_long_term: Any = None,
    schedule_d_net: Any = None,
    sstb: bool = False,
    cooperative_patron: bool = False,
    knowledge_dir: str | Path | None = None,
) -> QbiDeductionResult:
    """Form 8995, line by line. See the module docstring for the rules and their sources.

    Args:
        taxable_income_before_qbi: Form 8995's taxable-income line (its instructions: for Form 1040 filers, AGI
            minus the standard or itemized deduction and the Schedule 1-A deductions).
        businesses: one entry per trade, business or aggregation: {name, tin?, qbi} (qbi signed; a loss is
            negative). Rows past the face's table go on an attached statement and into the total.
        qbi_loss_carryforward / reit_ptp_loss_carryforward: last year's carryforward lines (the sign is ignored:
            the face prints them in parentheses).
        qualified_reit_dividends: the total of Form 1099-DIV box 5. ptp_income: qualified PTP income (signed).
        qualified_dividends: Form 1040's qualified-dividends line. Net capital gain: either ``net_capital_gain``
            (Form 1040's capital-gain line when no Schedule D is required) or both Schedule D lines
            (``schedule_d_long_term`` and ``schedule_d_net``), never both.
        sstb: the filer owns a specified service trade or business. cooperative_patron: a patron of a specified
            agricultural or horticultural cooperative (Form 8995-A only).
    """
    if isinstance(year, bool) or not isinstance(year, int):
        raise ValueError(f"year must be an int tax year, got {year!r}")
    if filing_status not in _STATUSES:
        raise ValueError(f"unknown filing_status {filing_status!r} — use one of: {', '.join(_STATUSES)}")
    try:
        pack = load_knowledge("federal", year, base_dir=knowledge_dir)
    except FileNotFoundError:
        raise ValueError(f"qbi_deduction: no federal knowledge pack for {year}") from None
    params = pack.tax.qbi_deduction
    if params is None:
        raise ValueError(
            f"qbi_deduction: the {year} federal knowledge pack carries no Form 8995 block (tax.qbi_deduction); "
            f"it ships for TY2025 only. Read the {year} Form 8995 and its instructions before computing one."
        )
    threshold = params.thresholds[filing_status]
    rate = params.rate
    ti = _dollars(_amount(taxable_income_before_qbi, "taxable_income_before_qbi"))

    if cooperative_patron:
        raise ValueError(
            "qbi_deduction REFUSED: Form 8995 is only for a filer who is not a patron of an agricultural or "
            "horticultural cooperative (\"and you aren't a patron of an agricultural or horticultural cooperative\"; "
            "the instructions: \"Otherwise, use Form 8995-A\"). Form 8995-A is not computed by calc and no taxfill "
            "pack maps it: prepare it from its own instructions."
        )
    if ti > threshold:
        why = (" For a specified service trade or business (SSTB) above the threshold the instructions (Exception "
               "2) send the filer to Schedule A (Form 8995-A).") if sstb else ""
        raise ValueError(
            f"qbi_deduction REFUSED: taxable income before the QBI deduction {_fmt(ti)} is above the {year} Form "
            f"8995 threshold of {_fmt(threshold)} for {filing_status} (\"Use this form if your taxable income, before "
            f"your qualified business income deduction, is at or below\" it; the instructions: \"Otherwise, use Form "
            f"8995-A\"; on the W-2 wages and UBIA of qualified property limits: \"If your income is more than the "
            f"threshold, you must use Form 8995-A\").{why} Form 8995-A is not computed by calc and no taxfill pack "
            f"maps it: no number is given here."
        )

    if net_capital_gain is not None and (schedule_d_long_term is not None or schedule_d_net is not None):
        raise ValueError("pass net_capital_gain (no Schedule D) OR the two Schedule D lines, not both")
    if (schedule_d_long_term is None) != (schedule_d_net is None):
        raise ValueError("pass both schedule_d_long_term and schedule_d_net (the instructions take the smaller)")

    rows, cells = _pack_table(year)
    biz_in = list(businesses or [])
    lines: dict[str, int | str] = {}
    biz_amounts: list[int] = []
    statement: list[dict[str, Any]] = []
    for i, b in enumerate(biz_in):
        if not isinstance(b, dict) or "qbi" not in b:
            raise ValueError(f"businesses[{i}] must be a mapping with at least 'qbi' (and 'name', 'tin'), got {b!r}")
        unknown = set(b) - {"name", "tin", "qbi"}
        if unknown:
            raise ValueError(f"businesses[{i}] has unknown keys {sorted(unknown)}; use name, tin, qbi")
        amount = _dollars(_amount(b["qbi"], f"businesses[{i}].qbi"))
        biz_amounts.append(amount)
        name = str(b.get("name") or "").strip()
        tin = "".join(ch for ch in str(b.get("tin") or "") if ch.isdigit())
        if i < len(rows):
            row = cells[rows[i]]
            if name and "name" in row:
                lines[row["name"]] = name
            if tin and "tin" in row:
                lines[row["tin"]] = tin
            lines[row["qbi"]] = amount
        else:
            statement.append({"name": name, "tin": tin, "qbi": amount})

    key = {role: form_line_entry(pack, f"{FORM_KEY}.{role}").line for role in _ROLES}
    v: dict[str, int] = {}
    v["qbi_total"] = sum(biz_amounts)
    v["qbi_loss_carryforward"] = abs(_dollars(_amount(qbi_loss_carryforward, "qbi_loss_carryforward")))
    v["qbi_net"] = max(0, v["qbi_total"] - v["qbi_loss_carryforward"])
    v["qbi_component"] = _dollars(Decimal(v["qbi_net"]) * rate)
    reit = _dollars(_amount(qualified_reit_dividends, "qualified_reit_dividends"))
    if reit < 0:
        raise ValueError("qualified_reit_dividends is the total of Form 1099-DIV box 5 and cannot be negative")
    ptp = _dollars(_amount(ptp_income, "ptp_income"))
    v["reit_ptp"] = reit + ptp
    v["reit_ptp_loss_carryforward"] = abs(_dollars(_amount(reit_ptp_loss_carryforward, "reit_ptp_loss_carryforward")))
    v["reit_ptp_net"] = max(0, v["reit_ptp"] - v["reit_ptp_loss_carryforward"])
    v["reit_ptp_component"] = _dollars(Decimal(v["reit_ptp_net"]) * rate)
    v["before_limit"] = v["qbi_component"] + v["reit_ptp_component"]
    v["taxable_income"] = ti
    qd = _dollars(_amount(qualified_dividends, "qualified_dividends"))
    if qd < 0:
        raise ValueError("qualified_dividends cannot be negative")
    if schedule_d_long_term is not None:
        lt = _dollars(_amount(schedule_d_long_term, "schedule_d_long_term"))
        net = _dollars(_amount(schedule_d_net, "schedule_d_net"))
        ncg = min(lt, net) if lt > 0 and net > 0 else 0
        ncg_text = (f"the smaller of Schedule D line {form_line(pack, 'sched_d.long_term')} ({_fmt(lt)}) and line "
                    f"{form_line(pack, 'sched_d.net')} ({_fmt(net)})"
                    + ("" if ncg else ", nothing because one is zero or less"))
    else:
        cg = _dollars(_amount(net_capital_gain or 0, "net_capital_gain"))
        ncg = max(0, cg)
        ncg_text = (f"Form 1040 line {form_line(pack, 'f1040.capital_gain')} ({_fmt(cg)}; no Schedule D)"
                    if net_capital_gain is not None else "none passed")
    v["net_capital_gain"] = qd + ncg
    v["limit_base"] = max(0, ti - v["net_capital_gain"])
    v["income_limitation"] = _dollars(Decimal(v["limit_base"]) * rate)
    v["deduction"] = min(v["before_limit"], v["income_limitation"])
    v["qbi_carryforward"] = max(0, v["qbi_loss_carryforward"] - v["qbi_total"])
    v["reit_ptp_carryforward"] = max(0, v["reit_ptp_loss_carryforward"] - v["reit_ptp"])

    for role in _ROLES:
        if role in _LOSS_BOXES and v[role] == 0:
            continue
        lines[key[role]] = v[role]
    money_keys = {cells[r]["qbi"] for r in rows} | {key[r] for r in _ROLES}
    independent = {k: val for k, val in lines.items() if k in money_keys and isinstance(val, int)}

    pct = f"{rate * 100:.0f}%"
    ln = {role: _line(pack, role) for role in _ROLES}
    try:
        dest = (f"Form 1040 line {form_line(pack, 'f1040.qbi_deduction')} (Form 1040-NR line "
                f"{form_line(pack, 'f1040nr.qbi_deduction')})")
    except FormLineError:
        dest = "the return's qualified business income deduction line"
    work = (
        f"Form 8995 ({year}), {filing_status}: taxable income before the QBI deduction {_fmt(ti)} is at or below "
        f"the {_fmt(threshold)} threshold, so the simplified form applies"
        + (" (an SSTB is treated as a qualified trade or business at or below it: Exception 1)" if sstb else "")
        + f". Line {ln['qbi_total']}: QBI {_fmt(v['qbi_total'])} from {len(biz_in)} business(es)"
        + (f" ({len(statement)} on an attached statement)" if statement else "")
        + f"; line {ln['qbi_loss_carryforward']}: prior-year loss ({_fmt(v['qbi_loss_carryforward'])}); line "
        f"{ln['qbi_net']} = {_fmt(v['qbi_net'])}; line {ln['qbi_component']} = {pct} = {_fmt(v['qbi_component'])}. "
        f"Line {ln['reit_ptp']}: qualified REIT dividends {_fmt(reit)} + PTP {_fmt(ptp)} = {_fmt(v['reit_ptp'])}; "
        f"line {ln['reit_ptp_loss_carryforward']}: prior-year loss ({_fmt(v['reit_ptp_loss_carryforward'])}); line "
        f"{ln['reit_ptp_net']} = {_fmt(v['reit_ptp_net'])}; line {ln['reit_ptp_component']} = {pct} = "
        f"{_fmt(v['reit_ptp_component'])}. Line {ln['before_limit']} = {_fmt(v['before_limit'])}. Line "
        f"{ln['taxable_income']} = {_fmt(ti)}; line {ln['net_capital_gain']} = qualified dividends {_fmt(qd)} + net "
        f"capital gain {_fmt(ncg)} ({ncg_text}) = {_fmt(v['net_capital_gain'])}; line {ln['limit_base']} = "
        f"{_fmt(v['limit_base'])}; line {ln['income_limitation']} = {pct} = {_fmt(v['income_limitation'])}. Line "
        f"{ln['deduction']}: the smaller of lines {ln['before_limit']} and {ln['income_limitation']} = "
        f"{_fmt(v['deduction'])} -> {dest}."
        + (f" Carry forward to next year: line {ln['qbi_carryforward']} ({_fmt(v['qbi_carryforward'])})"
           if v["qbi_carryforward"] else "")
        + (f"{';' if v['qbi_carryforward'] else ' Carry forward to next year:'} line {ln['reit_ptp_carryforward']} "
           f"({_fmt(v['reit_ptp_carryforward'])})" if v["reit_ptp_carryforward"] else "")
        + ("." if v["qbi_carryforward"] or v["reit_ptp_carryforward"] else "")
        + " Whole dollars, each line from the rounded lines above it."
    )
    confirm: list[str] = []
    if reit > 0:
        confirm.append(_HOLDING_PERIOD)
    if statement:
        confirm.append(
            f"More businesses than the face's {len(rows)} rows: the instructions for line {ln['qbi_total']}: \"If you "
            "have more than five trades or businesses, attach a statement with the name and taxpayer identification "
            "number of the trade(s) or business(es) and include the income and loss from those trade(s) or "
            "business(es) in the total\" — statement_businesses lists them."
        )
    inputs = {
        "taxable_income_before_qbi": ti, "filing_status": filing_status, "year": year,
        "businesses": [{"name": str(b.get("name") or ""), "qbi": biz_amounts[i]} for i, b in enumerate(biz_in)],
        "qbi_loss_carryforward": v["qbi_loss_carryforward"], "qualified_reit_dividends": reit, "ptp_income": ptp,
        "reit_ptp_loss_carryforward": v["reit_ptp_loss_carryforward"], "qualified_dividends": qd,
        "net_capital_gain": ncg, "sstb": sstb, "cooperative_patron": cooperative_patron,
    }
    face = Citation(
        source=f"Form 8995 ({year}), Qualified Business Income Deduction Simplified Computation, lines 1-17",
        url=f"https://www.irs.gov/pub/irs-prior/f8995--{year}.pdf",
    )
    return QbiDeductionResult(
        deduction=v["deduction"],
        lines=lines,
        independent=independent,
        qbi_loss_carryforward=v["qbi_carryforward"],
        reit_ptp_loss_carryforward=v["reit_ptp_carryforward"],
        income_limited=v["income_limitation"] < v["before_limit"],
        threshold=threshold,
        statement_businesses=statement,
        confirm=confirm,
        inputs=inputs,
        work=work,
        citation=params.citation,
        citations=[params.citation, face],
    )
