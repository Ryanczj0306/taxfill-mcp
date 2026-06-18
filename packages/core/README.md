# taxfill-core

The pure-Python core of [TaxFill](https://github.com/Ryanczj0306/taxfill-mcp):
form-pack and intake-profile schemas plus the deterministic calculation
primitives. No MCP dependency — the [`taxfill-mcp`](https://pypi.org/project/taxfill-mcp/)
server wraps this for AI clients.

Every number this library produces comes from a versioned, **cited** knowledge
pack (`knowledge/<jurisdiction>/<year>.yaml`); it never invents a figure and
refuses to fill a line it cannot cite. The knowledge packs (federal 2019–2024;
all 50 states + DC) and form-pack field maps ship inside the wheel, so an
installed copy is self-contained — no network access except to download **blank**
official forms from `.gov` URLs on demand.

## Not tax advice

This is engine code for producing a **reviewable draft** for paper filing. It is
not tax advice and not a tax preparer. See the
[project README](https://github.com/Ryanczj0306/taxfill-mcp) for the full
disclaimer.

MIT licensed.
