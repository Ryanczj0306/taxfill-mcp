"""`taxfill` CLI — local workspace management + a shell gateway to the MCP tools.

Subcommands:

    taxfill status <year>        show what's in the workspace
    taxfill reconcile <year>     regenerate RECONCILIATION.md + CHECKLIST.md
    taxfill purge <year>         securely wipe a year's workspace (overwrite + delete)
    taxfill introspect <pdf>     emit a skeleton pack.yaml from a blank AcroForm PDF
    taxfill tools                list the callable MCP tools (name, description, args)
    taxfill call <name> [json]   invoke one MCP tool and print its JSON result

The `tools`/`call` pair is a thin shell gateway over the same FastMCP tool
registry the stdio server exposes — so an agent that can run a shell command but
does not speak MCP (Codex CLI, a script, CI) can call every tool. It dispatches
through the live registry, so it always covers all tools with no per-tool code:

    taxfill call list_forms '{"jurisdiction": "federal", "year": 2023}'
    echo '{"year": 2023, "profile": {...}}' | taxfill call intake_checklist --stdin
    taxfill call render_form '{"form": "1040", "year": 2023, ...}' --out-dir ./pages

`call` prints the tool's structured JSON on stdout (image output — `render_form`
— is written to files and their paths returned). The workspace lives under
``./taxfill-workspace`` by default (``--root`` to override). `purge` is
destructive and PII-bearing, so it confirms interactively unless ``--yes`` is given.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import tempfile
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


def _server_mcp():
    """Lazily import the FastMCP server object (keeps status/purge/introspect light)."""
    from taxfill_mcp.server import mcp

    return mcp


def _cmd_tools(args) -> int:
    mcp = _server_mcp()
    tools = sorted(asyncio.run(mcp.list_tools()), key=lambda t: t.name)
    if args.json:
        payload = [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in tools
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0
    for t in tools:
        schema = t.inputSchema or {}
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        params = ", ".join(f"{k}*" if k in required else f"{k}?" for k in props) or "(none)"
        desc = (t.description or "").strip().splitlines()[0] if t.description else ""
        print(f"{t.name} — {desc}")
        print(f"    args: {params}")
    print(f"\n{len(tools)} tools ( * = required ). Invoke one with:")
    print("    taxfill call <name> '<json-args>'      (or pipe JSON with --stdin)")
    return 0


def _cmd_call(args) -> int:
    mcp = _server_mcp()
    # 1. resolve the JSON arguments (positional string, --stdin, or none)
    try:
        if args.stdin:
            raw = sys.stdin.read().strip()
            call_args = json.loads(raw) if raw else {}
        elif args.args_json:
            call_args = json.loads(args.args_json)
        else:
            call_args = {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": "invalid JSON arguments", "detail": str(e)}), file=sys.stderr)
        return 2
    if not isinstance(call_args, dict):
        print(json.dumps({"error": "arguments must be a JSON object"}), file=sys.stderr)
        return 2

    # 2. validate the tool name against the live registry (nice error + discovery)
    names = [t.name for t in asyncio.run(mcp.list_tools())]
    if args.name not in names:
        print(
            json.dumps({"error": "unknown tool", "tool": args.name, "available": sorted(names)}),
            file=sys.stderr,
        )
        return 2

    # 3. invoke; a tool that raises (bad args, unmet precondition) -> stderr + exit 1
    try:
        res = asyncio.run(mcp.call_tool(args.name, call_args))
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "detail": str(e)}), file=sys.stderr)
        return 1
    content, structured = res if isinstance(res, tuple) else (res, None)

    # 4. peel off image blocks (render_form) -> write to disk, return their paths
    out_dir = Path(args.out_dir) if args.out_dir else None
    images: list[str] = []
    texts: list[str] = []
    for i, block in enumerate(content or []):
        btype = getattr(block, "type", None)
        if btype == "image":
            if out_dir is None:
                out_dir = Path(tempfile.mkdtemp(prefix="taxfill-render-"))
            out_dir.mkdir(parents=True, exist_ok=True)
            ext = {"image/png": "png", "image/jpeg": "jpg"}.get(getattr(block, "mimeType", ""), "png")
            path = out_dir / f"{args.name}_{i:02d}.{ext}"
            path.write_bytes(base64.b64decode(block.data))
            images.append(str(path))
        elif btype == "text":
            texts.append(block.text)

    # 5. unwrap FastMCP's {"result": X} envelope (used for non-dict returns)
    payload = structured
    if isinstance(structured, dict) and list(structured.keys()) == ["result"]:
        payload = structured["result"]
    if payload is None and texts and not images:  # older SDK: no structured content
        try:
            payload = json.loads(texts[0])
        except (json.JSONDecodeError, IndexError):
            payload = {"text": texts}

    if images:
        base = payload if isinstance(payload, dict) else ({} if payload is None else {"result": payload})
        out = {**base, "images": images}
    else:
        out = payload if payload is not None else {}
    indent = None if args.indent is not None and args.indent < 0 else args.indent
    print(json.dumps(out, indent=indent, ensure_ascii=False, default=str))
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

    tp = sub.add_parser("tools", help="list the callable MCP tools (name, description, args)")
    tp.add_argument("--json", action="store_true", help="emit the full tool list + JSON input schemas")
    tp.set_defaults(_fn=_cmd_tools)

    cp = sub.add_parser("call", help="invoke one MCP tool and print its JSON result")
    cp.add_argument("name", help="tool name (see `taxfill tools`)")
    cp.add_argument("args_json", nargs="?", help="tool arguments as a JSON object string")
    cp.add_argument("--stdin", action="store_true", help="read the JSON arguments from stdin instead")
    cp.add_argument("--out-dir", dest="out_dir", help="dir for image output (render_form); default: a temp dir")
    cp.add_argument("--indent", type=int, default=2, help="JSON indent (default 2; negative = compact one line)")
    cp.set_defaults(_fn=_cmd_call)

    args = p.parse_args(argv)
    return args._fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
