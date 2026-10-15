# taxfill-core

The pure-Python core of [TaxFill](https://github.com/Ryanczj0306/taxfill-mcp):
form-pack and intake-profile schemas plus the deterministic calculation
primitives. No MCP dependency — the [`taxfill-mcp`](https://pypi.org/project/taxfill-mcp/)
server wraps this for AI clients.

Every number this library produces comes from a versioned, **cited** knowledge
pack (`knowledge/<jurisdiction>/<year>.yaml`); it never invents a figure and
refuses to fill a line it cannot cite. The knowledge packs (federal 2019–2026,
where 2026 is `provisional: planning_only` — projection math, not for filing;
all 50 states + DC, income-tax packs for 2023–2025) and form-pack field maps
ship inside the wheel, so an
installed copy is self-contained: the only outbound traffic is downloading **blank**
forms on demand from the tax agencies' own sites (or an exact, digest-checked
Internet Archive copy when a state site blocks scripts).

> **Release status.** TY2025 is the newest filing-grade tax year, and stays so until a later
> release re-pins the 2026 packs on the IRS's final 2026 forms. The 2026 packs are provisional:
> most are mapped from the IRS early-release drafts, and they fill only in rehearsal mode, for
> projections and dress rehearsals, never for filing (the exception is the 2026 Form 1040-ES,
> whose vouchers are paid during 2026 and fill normally). A form with no pack is refused today
> (`list_forms` shows which forms have one, except the print-only state forms that
> `hand_fill_worksheet` serves); a later release adds an unmapped draft for such a form, which is
> never filing-grade.

## Not tax advice

This is engine code for producing a **reviewable draft** for paper filing. It is
not tax advice and not a tax preparer. See the
[project README](https://github.com/Ryanczj0306/taxfill-mcp) for the full
disclaimer.

MIT licensed.
