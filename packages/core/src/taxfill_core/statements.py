"""Return statements the IRA rules require — written in the element order of the IRS's own examples
(Phase J JR2a). [NAME] and [SSN] stay placeholders: calc output never carries a person's identity.

* ``recharacterization_statement`` — the Instructions for Form 8606 (2025), Reporting recharacterizations:
  "You attach a statement to your return explaining the recharacterization. The statement indicates that
  you contributed $4,000 to a traditional IRA on May 27, 2025; recharacterized $3,000 of that contribution
  on February 24, 2026, by transferring $3,000 plus $300 of related earnings from your traditional IRA to a
  Roth IRA in a trustee-to-trustee transfer; and deducted the remaining traditional IRA contribution of
  $1,000 on your 2025 Form 1040."
* ``returned_contribution_statement`` — the same instructions, Return of IRA Contributions ("You attach a
  statement to your tax return explaining the distribution").
* ``ira_line_4b_statement`` — the Instructions for Form 1040 (2025), line 4c: "If more than one exception
  applies, check a box for each exception and include a statement showing the amount of each exception, for
  example, 'Line 4b – $1,000 Rollover and $500 HFD.'"

A statement made after a timely return under the automatic 6-month extension is headed as Pub 590-A
directs: an amended return with "Filed pursuant to section 301.9100-2" written at the top.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from taxfill_core.knowledge import form_line

__all__ = ["ira_line_4b_statement", "recharacterization_statement", "returned_contribution_statement"]

_LATE_HEADER = "Filed pursuant to section 301.9100-2"
_HEAD = "[NAME]  [SSN]"


def _usd(x: int | float | Decimal | str) -> str:
    d = Decimal(str(x))
    return f"${d:,.0f}" if d == d.to_integral_value() else f"${d:,.2f}"


def _day(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d:%B} {d.day}, {d.year}"


def recharacterization_statement(
    *,
    tax_year: int,
    contributed: int | float | Decimal | str,
    first_ira: str,
    contribution_date: date | str,
    recharacterized: int | float | Decimal | str,
    second_ira: str,
    recharacterization_date: date | str,
    earnings: int | float | Decimal | str | None = None,
    transferred_balance: int | float | Decimal | str | None = None,
    new_first_ira: bool = False,
    deducted: int | float | Decimal | str | None = None,
    late: bool = False,
    conversion_note: str | None = None,
) -> str:
    """The statement a recharacterization needs (JR2a), element by element as in the i8606 examples:
    what was contributed, to which IRA, when; what was recharacterized, when, and what was transferred
    (the amount plus its earnings, or the whole balance) from which IRA to which, trustee to trustee; and
    the traditional-IRA deduction taken. ``conversion_note`` is an OPTIONAL extra sentence (labeled so)."""
    whole = Decimal(str(recharacterized)) == Decimal(str(contributed))
    first = f"{'new ' if new_first_ira else ''}{first_ira} IRA"
    parts = [f"I contributed {_usd(contributed)} to a {first} on {_day(contribution_date)};"]
    what = "that contribution" if whole else f"{_usd(recharacterized)} of that contribution"
    if transferred_balance is not None:
        moved = f"{_usd(transferred_balance)}, the balance in the {first_ira} IRA,"
        parts.append(f"recharacterized {what} on {_day(recharacterization_date)}, by transferring {moved} to a "
                     f"{second_ira} IRA in a trustee-to-trustee transfer;")
    else:
        e = Decimal(str(earnings or 0))
        rel = (f"plus {_usd(e)} of related earnings" if e >= 0 else f"less {_usd(-e)} of related loss")
        parts.append(f"recharacterized {what} on {_day(recharacterization_date)}, by transferring "
                     f"{_usd(recharacterized)} {rel} from my {first_ira} IRA to a {second_ira} IRA in a "
                     f"trustee-to-trustee transfer;")
    if deducted is not None:
        remaining = "the remaining " if not whole else "the "
        parts.append(f"and deducted {remaining}traditional IRA contribution of {_usd(deducted)} on my {tax_year} "
                     "Form 1040.")
    else:
        parts[-1] = parts[-1].rstrip(";") + "."
    body = " ".join(parts)
    lines = ([_LATE_HEADER] if late else []) + [_HEAD, f"Statement explaining an IRA recharacterization ({tax_year})",
                                                  body]
    if conversion_note:
        lines.append(f"(Optional) {conversion_note}")
    return "\n".join(lines)


def returned_contribution_statement(
    *,
    tax_year: int,
    contributed: int | float | Decimal | str,
    ira: str,
    contribution_date: date | str,
    returned: int | float | Decimal | str,
    earnings: int | float | Decimal | str,
    return_date: date | str,
    deducted: int | float | Decimal | str | None = None,
    late: bool = False,
) -> str:
    """The statement explaining a contribution returned with its net income before the due date (IRC
    408(d)(4)) — the i8606 example's elements: the contribution, the amount returned with its earnings
    (the total withdrawn), the date, and the deduction kept."""
    e = Decimal(str(earnings))
    total = Decimal(str(returned)) + e
    rel = f"plus {_usd(e)} of earnings" if e >= 0 else f"less {_usd(-e)} of loss"
    body = (f"I contributed {_usd(contributed)} to my {ira} IRA on {_day(contribution_date)}; on {_day(return_date)} "
            f"{_usd(returned)} of that contribution was returned to me with its net income — {_usd(total)} withdrawn "
            f"({_usd(returned)} contribution {rel}) — under section 408(d)(4)"
            + (f"; I deducted the remaining contribution of {_usd(deducted)} on my {tax_year} return." if deducted
               is not None else "."))
    return "\n".join(([_LATE_HEADER] if late else []) + [_HEAD, f"Statement explaining a returned IRA contribution "
                                                                f"({tax_year})", body])


def ira_line_4b_statement(tax_year: int, exceptions: dict[str, int | float | Decimal | str], *,
                          knowledge_dir: str | Path | None = None) -> str:
    """The statement when more than one exception applies to the IRA distribution lines (the line 4c
    instructions' example 'Line 4b – $1,000 Rollover and $500 HFD.'), the line read off the year's face."""
    if len(exceptions) < 2:
        raise ValueError("the statement is for MORE than one exception; one exception needs only its box")
    items = [f"{_usd(v)} {k}" for k, v in exceptions.items()]
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return f"Line {form_line(tax_year, 'f1040.ira_taxable', base_dir=knowledge_dir)} – {joined}."
