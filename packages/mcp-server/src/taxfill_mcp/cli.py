"""`taxfill` CLI — local workspace management (dev plan section 2).

Subcommands:

    taxfill status <year>        show what's in the workspace
    taxfill reconcile <year>     regenerate RECONCILIATION.md + CHECKLIST.md
    taxfill purge <year>         securely wipe a year's workspace (overwrite + delete)
    taxfill introspect <pdf>     emit a skeleton pack.yaml from a blank AcroForm PDF

The workspace lives under ``./taxfill-workspace`` by default (``--root`` to
override). `purge` is destructive and PII-bearing, so it confirms interactively
unless ``--yes`` is given.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from taxfill_core.workspace import Workspace

DEFAULT_ROOT = "taxfill-workspace"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _cmd_status(args) -> int:
    ws = Workspace(args.root, args.year)
    st = ws.status()
    if not st["exists"]:
        print(f"No workspace for {args.year} under {args.root!r}.")
        return 0
    print(f"Workspace {args.year} — {st['root']}")
    print(f"  profile: {'yes' if st['has_profile'] else 'no'}")
    print(f"  documents: {len(st['documents'])}  drafts: {len(st['drafts'])}")
    pos = st["positions"]
    print(f"  positions: {pos['total']} (decided {pos['decided']}, unverified {pos['unverified']}, open {pos['open']})")
    print(f"  RECONCILIATION.md: {'present' if st['reconciliation'] else 'not generated'}")
    if pos["unverified"]:
        print(f"  ⚠ {pos['unverified']} position(s) lack a confirmed source — not ready to file.")
    return 0


def _cmd_reconcile(args) -> int:
    ws = Workspace(args.root, args.year)
    if not ws.exists():
        print(f"No workspace for {args.year} under {args.root!r}.", file=sys.stderr)
        return 1
    now = _now()
    r = ws.write_reconciliation(now=now)
    c = ws.write_checklist(now=now)
    print(f"Wrote {r}")
    print(f"Wrote {c}")
    return 0


def _cmd_purge(args) -> int:
    ws = Workspace(args.root, args.year)
    if not ws.exists():
        print(f"No workspace for {args.year} under {args.root!r}.")
        return 0
    if not args.yes:
        print(f"This will PERMANENTLY wipe {ws.root} (profile, documents, drafts — all PII).")
        reply = input("Type the year to confirm: ").strip()
        if reply != str(args.year):
            print("Aborted — confirmation did not match.")
            return 1
    n = ws.purge()
    print(f"Purged {ws.root} ({n} file(s) scrubbed).")
    return 0


def _cmd_introspect(args) -> int:
    import yaml

    from taxfill_core.packbuild import build_skeleton, sentinel_sweep
    from taxfill_core.schemas.formpack import FormPack

    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"No such PDF: {pdf}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else pdf.with_suffix("")
    out.mkdir(parents=True, exist_ok=True)
    skeleton = build_skeleton(pdf, form=args.form, jurisdiction=args.jurisdiction, tax_year=args.year, source_url=args.source_url)
    todo = skeleton.pop("_todo", [])
    # Prove the skeleton is structurally valid before handing it off.
    FormPack.model_validate(skeleton)
    (out / "pack.skeleton.yaml").write_text(
        "# SKELETON — line keys are raw field paths; rename them during vision mapping,\n"
        "# add relations/cross_form/identity_fields, then adversarially audit before shipping.\n"
        + yaml.dump(skeleton, sort_keys=False, allow_unicode=True, width=100)
    )
    (out / "MAPPING_TODO.md").write_text(
        f"# Mapping TODO — {args.form}\n\n"
        f"{len(skeleton['fields'])} fields, acroform_root = {skeleton['acroform_root']!r}.\n\n"
        "1. Rename each `line` from its raw field path to the printed line number/label "
        "(read them off the sentinel sweep render).\n"
        "2. Add `relations`, `cross_form`, `identity_fields`.\n"
        "3. Run the adversarial vision audit, fix, re-audit.\n\n"
        + ("## Needs attention\n" + "\n".join(f"- {t}" for t in todo) if todo else "## Needs attention\n- none detected\n")
    )
    if args.render:
        from taxfill_core.render import render_pdf
        sweep = sentinel_sweep(pdf, out / f"{pdf.stem}_sweep.pdf")
        pages = render_pdf(sweep, out, dpi=170)
        print(f"  sentinel sweep rendered: {len(pages)} page(s)")
    print(f"Skeleton pack for {args.form}: {len(skeleton['fields'])} fields, root={skeleton['acroform_root']!r}")
    if todo:
        print(f"  {len(todo)} field(s) need attention — see MAPPING_TODO.md")
    print(f"  wrote {out}/pack.skeleton.yaml + MAPPING_TODO.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="taxfill", description="TaxFill local workspace management.")
    p.add_argument("--root", default=DEFAULT_ROOT, help=f"workspace root (default: {DEFAULT_ROOT})")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in (
        ("status", _cmd_status, "show what's in the workspace"),
        ("reconcile", _cmd_reconcile, "regenerate RECONCILIATION.md + CHECKLIST.md"),
        ("purge", _cmd_purge, "securely wipe a year's workspace"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("year", type=int)
        if name == "purge":
            sp.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
        sp.set_defaults(_fn=fn)

    ip = sub.add_parser("introspect", help="emit a skeleton pack.yaml from a blank AcroForm PDF")
    ip.add_argument("pdf", help="path to the blank PDF")
    ip.add_argument("--form", required=True, help="form name, e.g. '1040-X' or '511'")
    ip.add_argument("--jurisdiction", default="federal", help="'federal' or 'states/<cc>'")
    ip.add_argument("--year", type=int, required=True)
    ip.add_argument("--source-url", required=True, dest="source_url", help="official URL of the blank PDF")
    ip.add_argument("--out", help="output dir (default: alongside the PDF)")
    ip.add_argument("--render", action="store_true", help="also render the sentinel sweep for vision mapping")
    ip.set_defaults(_fn=_cmd_introspect)

    args = p.parse_args(argv)
    return args._fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
