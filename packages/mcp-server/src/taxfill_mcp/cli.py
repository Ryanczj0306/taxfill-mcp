"""`taxfill` CLI — local workspace management (dev plan section 2).

Subcommands:

    taxfill status <year>        show what's in the workspace
    taxfill reconcile <year>     regenerate RECONCILIATION.md + CHECKLIST.md
    taxfill purge <year>         securely wipe a year's workspace (overwrite + delete)

The workspace lives under ``./taxfill-workspace`` by default (``--root`` to
override). `purge` is destructive and PII-bearing, so it confirms interactively
unless ``--yes`` is given.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

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
    args = p.parse_args(argv)
    return args._fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
