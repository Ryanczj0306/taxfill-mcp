# Form packs

This directory will hold **form packs**: versioned YAML data files
(`pack.yaml`) that describe one tax form for one jurisdiction and one tax
year — the AcroForm field map, math relations for the verifier, cross-form
consistency rules, signature placement, and official mailing addresses.

The schema is defined in [`docs/DEV_PLAN.md`](../docs/DEV_PLAN.md) (section 5)
and implemented as a pydantic model in
`packages/core/src/taxfill_core/schemas/formpack.py`. Federal and state forms
use the same schema; coverage grows by adding packs here, never by changing
engine code.

Planned layout:

```
formpacks/
├── federal/2023/f1040/pack.yaml
├── federal/2022/f1040nr/  f8843/  sched_1/  sched_c/  sched_oi/  ...
└── states/ca/2023/form540nr/pack.yaml
```

**Status: empty by design.** Federal packs (f8843 2019-2024, f1040nr +
schedules 2022-2023, f1040 + schedules 2023-2024) are delivered in
**milestone M2**; California packs follow in **M5**.

Note: packs contain only metadata. Blank PDFs are downloaded at runtime from
official .gov URLs and checksum-verified — they are never vendored in this
repo.
