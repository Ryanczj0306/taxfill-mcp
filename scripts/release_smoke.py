#!/usr/bin/env python
"""Smoke-test an INSTALLED taxfill-mcp wheel against the checkout it was built from (Phase J JA1).

The CI packaging job and docs/dev/PUBLISHING.md both run this after installing the built wheel into a clean venv
outside the repo. Every expectation is derived from the checkout, never typed: before JA1 the job asserted a
hand-written federal 2023 form set and a literal tool count, so a pack added after the list was written could go
missing from the wheel unnoticed. It checks that:

1. the installed packages and ``data_root()`` live inside the venv's site-packages (not the checkout), with
   ``TAXFILL_DATA_DIR`` unset;
2. ``list_forms(jurisdiction, year)`` returns, for every jurisdiction-year in the checkout's ``formpacks/``, exactly
   the form keys that have a ``pack.yaml`` there;
3. every YAML / Markdown file under the checkout's ``knowledge/`` and ``formpacks/`` (what scripts/stage_data.py
   stages) is in the wheel byte for byte, and the wheel carries no other;
4. every federal and state knowledge pack loads through the installed models;
5. every state knowledge year has one pack per state jurisdiction (42: the directories under
   ``knowledge/states/``), in the checkout and in the wheel;
6. the server registers exactly the tools ``packages/mcp-server/tests/test_server_e2e.py`` pins (``EXPECTED_TOOLS``
   and its ``assert len(names) == N``);
7. with ``--dist <dir>``: the directory holds one sdist per package, and no sdist carries a repo-only surface
   (``bundle/``: the .mcpb recipe, built from the repo at release time — PyPI freezes the sdist as it freezes the
   wheel, so its pre-upload wording and repo-relative links must not ship in it).

Run it with the INSTALLED interpreter, from outside the checkout (CI does exactly this):

    REPO="$PWD" && TMP="$(mktemp -d)" && uv venv "$TMP/venv" --python 3.11
    uv pip install --python "$TMP/venv/bin/python" --no-cache --find-links dist/ "$(ls dist/taxfill_mcp-*.whl)"
    (cd "$TMP" && env -u TAXFILL_DATA_DIR "$TMP/venv/bin/python" "$REPO/scripts/release_smoke.py" --repo "$REPO" \
        --dist "$REPO/dist")

The checkout can also be given as ``TAXFILL_RELEASE_REPO``. A quick self-check in the repo's own venv (no wheel:
the editable install reads the checkout, so checks 1 and 3 are trivially about the checkout itself):

    uv run python scripts/release_smoke.py --repo . --checkout
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import sys
import sysconfig
import tarfile
from pathlib import Path

REPO_ENV = "TAXFILL_RELEASE_REPO"
DATA_TREES = ("knowledge", "formpacks")
DATA_SUFFIXES = {".yaml", ".yml", ".md"}  # what scripts/stage_data.py copies into taxfill_core/_data/
E2E_TEST = Path("packages") / "mcp-server" / "tests" / "test_server_e2e.py"
SDIST_PACKAGES = ("taxfill_core", "taxfill_mcp")  # the sdist file-name prefixes `uv build` writes
SDIST_REPO_ONLY = ("bundle/",)  # sdist paths (below the top directory) that are repo-only surfaces

FormSets = dict[tuple[str, int], set[str]]


# ── expectations, read from the checkout ─────────────────────────────────────


def repo_form_sets(formpacks: Path) -> FormSets:
    """{(jurisdiction, year): form keys} from ``<jurisdiction>/<year>/<key>/pack.yaml`` (hand-fill packs are
    ``handfill.yaml`` and are not listed by ``list_forms``; check 3 covers them)."""
    out: FormSets = {}
    for pack in formpacks.rglob("pack.yaml"):
        parts = pack.relative_to(formpacks).parts
        if parts[0] == "federal" and len(parts) == 4:
            jurisdiction, year, key = "federal", parts[1], parts[2]
        elif parts[0] == "states" and len(parts) == 5:
            jurisdiction, year, key = f"states/{parts[1]}", parts[2], parts[3]
        else:
            raise ValueError(f"unexpected form-pack path {pack} — the layout is <jurisdiction>/<year>/<key>/pack.yaml")
        out.setdefault((jurisdiction, int(year)), set()).add(key)
    return out


def data_digests(root: Path) -> dict[str, str]:
    """{relative path: sha256} of every staged data file under ``root``'s knowledge/ and formpacks/."""
    out = {}
    for tree in DATA_TREES:
        for path in (root / tree).rglob("*"):
            if path.is_file() and path.suffix.lower() in DATA_SUFFIXES:
                out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def state_knowledge_counts(knowledge: Path) -> tuple[int, dict[int, int]]:
    """(state jurisdictions, {year: packs}) from ``knowledge/states/<st>/<year>.yaml``."""
    states = [d for d in (knowledge / "states").iterdir() if d.is_dir()]
    counts: dict[int, int] = {}
    for d in states:
        for pack in d.glob("[0-9][0-9][0-9][0-9].yaml"):
            counts[int(pack.stem)] = counts.get(int(pack.stem), 0) + 1
    return len(states), dict(sorted(counts.items()))


def pinned_tools(test_file: Path) -> tuple[set[str], int | None]:
    """(EXPECTED_TOOLS, the N in ``assert len(names) == N``) as test_server_e2e.py pins them, read without
    importing it (pytest is not in the clean venv)."""
    source = test_file.read_text(encoding="utf-8")
    names: set[str] | None = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "EXPECTED_TOOLS" for t in node.targets):
            names = set(ast.literal_eval(node.value))
    if names is None:
        raise ValueError(f"{test_file} defines no EXPECTED_TOOLS set")
    literal = re.findall(r"assert len\(names\) == (\d+)", source)
    return names, (int(literal[0]) if len(literal) == 1 else None)


# ── the checks (pure: observed vs expected -> failure lines) ─────────────────


def check_forms(expected: FormSets, observed: FormSets) -> list[str]:
    out = []
    for jy in sorted(set(expected) | set(observed)):
        want, got = expected.get(jy, set()), observed.get(jy, set())
        if want != got:
            out.append(f"list_forms{jy}: {len(got)} packs in the wheel, {len(want)} in the checkout"
                       + (f"; missing {sorted(want - got)}" if want - got else "")
                       + (f"; not in the checkout {sorted(got - want)}" if got - want else ""))
    return out


def check_data_files(expected: dict[str, str], observed: dict[str, str]) -> list[str]:
    out = []
    missing, extra = sorted(set(expected) - set(observed)), sorted(set(observed) - set(expected))
    changed = sorted(p for p in set(expected) & set(observed) if expected[p] != observed[p])
    for label, paths in (("missing from the wheel (re-run scripts/stage_data.py)", missing),
                         ("in the wheel but not the checkout", extra),
                         ("differ from the checkout (stale staging)", changed)):
        if paths:
            out.append(f"{len(paths)} data file(s) {label}: {paths[:10]}{' …' if len(paths) > 10 else ''}")
    return out


def check_state_knowledge(jurisdictions: int, repo_counts: dict[int, int], wheel_counts: dict[int, int]) -> list[str]:
    out = []
    if repo_counts != wheel_counts:
        out.append(f"state knowledge packs per year: wheel {wheel_counts} != checkout {repo_counts}")
    if not repo_counts:
        out.append("the checkout has no state knowledge year at all")
    for year, n in sorted(wheel_counts.items()):
        if n != jurisdictions:
            out.append(f"state knowledge {year}: {n} packs, expected one per state jurisdiction ({jurisdictions})")
    return out


def check_tools(observed: set[str], pinned: set[str], pinned_len: int | None) -> list[str]:
    out = []
    if pinned_len is not None and pinned_len != len(pinned):
        out.append(f"test_server_e2e.py disagrees with itself: EXPECTED_TOOLS has {len(pinned)} names, "
                   f"assert len(names) == {pinned_len}")
    if observed != pinned:
        out.append(f"the installed server registers {len(observed)} tools, test_server_e2e.py pins {len(pinned)}"
                   + (f"; unexpected {sorted(observed - pinned)}" if observed - pinned else "")
                   + (f"; missing {sorted(pinned - observed)}" if pinned - observed else ""))
    return out


def sdist_members(dist: Path) -> dict[str, list[str]]:
    """{sdist file name: member paths below its top directory} for every ``*.tar.gz`` in ``dist``."""
    out = {}
    for sdist in sorted(dist.glob("*.tar.gz")):
        with tarfile.open(sdist, "r:gz") as tar:
            out[sdist.name] = sorted(m.name.split("/", 1)[1] for m in tar.getmembers() if "/" in m.name)
    return out


def check_sdists(members: dict[str, list[str]]) -> list[str]:
    out = []
    for package in SDIST_PACKAGES:
        found = [name for name in members if name.startswith(f"{package}-")]
        if len(found) != 1:
            out.append(f"expected one {package}-*.tar.gz sdist in --dist, found {found}")
    for name, paths in sorted(members.items()):
        leaked = [p for p in paths if p.startswith(SDIST_REPO_ONLY)]
        if leaked:
            out.append(f"{name} carries repo-only files PyPI would freeze: {leaked[:10]} — exclude them in "
                       f"[tool.hatch.build.targets.sdist]")
    return out


def check_location(data_root: Path, package_files: list[Path], site_dirs: list[Path], repo: Path,
                   env_override: str | None) -> list[str]:
    out = []
    if env_override:
        out.append(f"TAXFILL_DATA_DIR is set ({env_override}) — unset it, or the wheel's own data is never read")

    def inside(path: Path, parents: list[Path]) -> bool:
        return any(path.resolve().is_relative_to(p.resolve()) for p in parents)

    if not inside(data_root, site_dirs):
        out.append(f"data_root() is {data_root}, not inside site-packages {[str(p) for p in site_dirs]} — the data "
                   "is not packaged (or the venv sits inside the checkout and the resolver found the repo root)")
    if inside(data_root, [repo]):
        out.append(f"data_root() {data_root} is inside the checkout {repo}")
    for f in package_files:
        if not inside(f, site_dirs):
            out.append(f"{f} is imported from outside site-packages (an editable or PYTHONPATH copy, not the wheel)")
    return out


# ── observation of the installed packages ────────────────────────────────────


def observe(form_keys: list[tuple[str, int]]) -> dict[str, object]:
    import asyncio

    import taxfill_core
    import taxfill_mcp
    import taxfill_mcp.server as server
    from taxfill_core import load_knowledge, load_state_knowledge
    from taxfill_core.datadir import data_root
    from taxfill_core.discovery import list_forms

    root = data_root()
    forms: FormSets = {}
    for jurisdiction, year in form_keys:
        keys = {f.form_key for f in list_forms(jurisdiction, year)}
        if keys:
            forms[(jurisdiction, year)] = keys
    # a jurisdiction-year the wheel has but the checkout lacks
    for jy in repo_form_sets(root / "formpacks"):
        if jy not in forms:
            forms[jy] = {f.form_key for f in list_forms(*jy)}
    load_errors = []
    for pack in sorted((root / "knowledge" / "federal").glob("[0-9][0-9][0-9][0-9].yaml")):
        try:  # report every broken pack, not only the first
            if load_knowledge("federal", int(pack.stem)).tax_year != int(pack.stem):
                raise ValueError("tax_year does not match the file name")
        except Exception as exc:
            load_errors.append(f"load_knowledge('federal', {pack.stem}): {type(exc).__name__}: {exc}")
    for pack in sorted((root / "knowledge" / "states").glob("*/[0-9][0-9][0-9][0-9].yaml")):
        st, year = pack.parent.name, int(pack.stem)
        try:
            if load_state_knowledge(st, year).jurisdiction != f"states/{st}":
                raise ValueError("jurisdiction does not match the directory")
        except Exception as exc:
            load_errors.append(f"load_state_knowledge({st!r}, {year}): {type(exc).__name__}: {exc}")
    return {
        "data_root": root,
        "package_files": [Path(taxfill_core.__file__), Path(taxfill_mcp.__file__)],
        "versions": (taxfill_core.__version__, taxfill_mcp.__version__),
        "forms": forms,
        "digests": data_digests(root),
        "state_knowledge": state_knowledge_counts(root / "knowledge"),
        "load_errors": load_errors,
        "tools": {t.name for t in asyncio.run(server.mcp.list_tools())},
    }


def site_dirs() -> list[Path]:
    paths = sysconfig.get_paths()
    return sorted({Path(paths["purelib"]), Path(paths["platlib"])})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=os.environ.get(REPO_ENV),
                        help=f"the checkout the wheel was built from (default: ${REPO_ENV})")
    parser.add_argument("--checkout", action="store_true",
                        help="self-check in the repo's own (editable) venv: skip the site-packages checks")
    parser.add_argument("--dist", help="the dist/ directory `uv build` wrote: also check the sdists' file lists")
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error(f"pass --repo <checkout> or set {REPO_ENV}")
    repo = Path(args.repo).resolve()
    if not (repo / E2E_TEST).is_file():
        parser.error(f"{repo} is not a taxfill-mcp checkout (no {E2E_TEST})")

    expected_forms = repo_form_sets(repo / "formpacks")
    pinned, pinned_len = pinned_tools(repo / E2E_TEST)
    jurisdictions, repo_state_counts = state_knowledge_counts(repo / "knowledge")
    seen = observe(sorted(expected_forms))

    failures: list[str] = []
    if args.checkout:
        print("--checkout: site-packages checks skipped; this does NOT test the packaging")
        if os.environ.get("TAXFILL_DATA_DIR"):
            failures.append("TAXFILL_DATA_DIR is set — unset it")
    else:
        failures += check_location(seen["data_root"], seen["package_files"], site_dirs(), repo,
                                   os.environ.get("TAXFILL_DATA_DIR"))
    failures += check_forms(expected_forms, seen["forms"])
    failures += check_data_files(data_digests(repo), seen["digests"])
    failures += seen["load_errors"]
    wheel_jurisdictions, wheel_state_counts = seen["state_knowledge"]
    if wheel_jurisdictions != jurisdictions:
        failures.append(f"state knowledge jurisdictions: wheel {wheel_jurisdictions} != checkout {jurisdictions}")
    failures += check_state_knowledge(jurisdictions, repo_state_counts, wheel_state_counts)
    failures += check_tools(seen["tools"], pinned, pinned_len)
    sdists = sdist_members(Path(args.dist)) if args.dist else {}
    if args.dist:
        failures += check_sdists(sdists)

    packs = sum(len(v) for v in expected_forms.values())
    print(f"taxfill-core {seen['versions'][0]} / taxfill-mcp {seen['versions'][1]}; data_root() = {seen['data_root']}",
          flush=True)
    print(f"checkout: {packs} form packs across {len(expected_forms)} jurisdiction-years, "
          f"{len(data_digests(repo))} data files, state knowledge {repo_state_counts} of {jurisdictions} jurisdictions, "
          f"{len(pinned)} pinned tools | installed: {len(seen['digests'])} data files, "
          f"state knowledge {wheel_state_counts}, {len(seen['tools'])} tools"
          + (f" | sdists: {', '.join(f'{k} ({len(v)} files)' for k, v in sdists.items())}" if args.dist else ""),
          flush=True)
    if failures:
        print(f"FAIL — {len(failures)} problem(s):", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print("OK — the installed wheel matches the checkout" + (" (checkout mode)" if args.checkout else ""))
    return 0


if __name__ == "__main__":
    # never import from scripts/ (run as a script, sys.path[0] is this directory); only here, so a test that
    # calls main() in-process leaves its own sys.path alone
    _here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _here]
    raise SystemExit(main())
