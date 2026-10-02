# Form packs

One directory per form per tax year — `federal/<year>/<form>/` and `states/<st>/<year>/<form>/` — holding either a
`pack.yaml` (a fillable AcroForm) or a `handfill.yaml` (a print-and-hand-fill manifest for a form with no fillable
PDF). Each pack is pure data: the official blank's URL and SHA-256, the line → field map, the verifier's math
relations and cross-form rules, identity fields, the signature location and the mailing addresses. Federal and state
forms share one schema (`packages/core/src/taxfill_core/schemas/formpack.py`), so coverage grows by adding packs here,
never by changing engine code.

- **What ships today:** [docs/COVERAGE.md](../docs/COVERAGE.md), generated from this directory.
- **The binding authoring rules,** and the test that enforces each: [CONVENTIONS.md](CONVENTIONS.md).
- **Adding a form or a year:** the [pack-authoring guide](../docs/dev/CONTRIBUTING-PACKS.md) and the schema spec in
  [DEV_PLAN §5](../docs/dev/DEV_PLAN.md).

Packs contain only metadata. Blank PDFs are downloaded at runtime from official `.gov` URLs and checksum-verified —
they are never committed to this repo.
