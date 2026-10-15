# Releasing TaxFill v0.1

This is the mechanical runbook for shipping a release. The packaging is already
proven self-contained (CI `packaging` job builds, installs into a clean venv
outside the repo, and exercises the loaders), so a release is: bump → build →
verify → upload → tag → bundle → flip the repo-only docs.

> **Two steps are intentionally manual** — they are outward-facing and need
> credentials, so a human runs them, not CI or an agent:
> 1. the actual `twine upload` to PyPI (irreversible — a version cannot be
>    re-uploaded), and
> 2. recording the demo GIF (see [`DEMO.md`](DEMO.md)).

## 0. Prerequisites

- Maintainer access to the `taxfill-core` and `taxfill-mcp` PyPI projects (and a
  PyPI API token in `~/.pypirc` or `TWINE_*` env vars).
- `uv` installed. `uvx twine` and `uvx` are used below (no global installs).
- A clean working tree on `main`, CI green.

## 1. Version policy and the release commit

**`.dev0` between releases.** `main` carries the NEXT version with a `.dev0`
suffix between releases (for example `0.1.1.dev0` right after v0.1.0), so a
build from an untagged commit never carries a released version number. The
release commit drops the suffix; the first commit after the tag bumps to the
next `.dev0`. The first release is the exception (decided 2026-10-15): nothing
has been published yet, so `main` carries `0.1.0` itself and v0.1.0 is tagged
from it as is (the release workflow checks that the tag equals every site); the
suffix cycle starts with the first commit after that tag, which changes all the
sites below together. The bundle manifest follows the suffix like every
other site: `mcpb validate` does not check the version's format (on 2026-10-15
`@anthropic-ai/mcpb` 2.1.2, the latest on npm, passed the manifest with
`0.1.0`, with `0.1.0.dev0` and with `banana`), and a bundle is only built from
a release commit, which carries no suffix.

The version lives in four sites, plus the core pin and the bundle manifest:

- `packages/core/pyproject.toml` → `version`
- `packages/mcp-server/pyproject.toml` → `version`
- `packages/core/src/taxfill_core/__init__.py` → `__version__`
- `packages/mcp-server/src/taxfill_mcp/__init__.py` → `__version__`
- `packages/mcp-server/pyproject.toml` → `dependencies` pin `taxfill-core==<version>`
  (in lock-step so `uvx taxfill-mcp` resolves the matching core)
- `packages/mcp-server/bundle/manifest.json` → `version`

`packages/mcp-server/tests/test_release_surfaces.py` fails unless all six agree,
so a release commit that bumps one and forgets another fails CI, not PyPI. Run
`uv lock` after the bump so `uv.lock` records the new workspace versions
(it lists both packages with their version).

**CHANGELOG.** In the release commit, give the release its own section in
`CHANGELOG.md` (the version and the date) holding everything merged since the
previous tag; the GitHub release notes for the tag are that section. This step
applies once `CHANGELOG.md` exists (Phase J JA1 part C adds it); before that,
draft the release notes from `git log` since the previous tag.

**The PyPI-immutable surfaces.** Once a version is on PyPI these can never be
corrected without a new version number:

- `packages/core/pyproject.toml` → `description` (the PyPI summary line)
- `packages/mcp-server/pyproject.toml` → `description`
- `packages/mcp-server/README.md` (the rendered long description; it once said
  14 tools against a 22-tool server and would have shipped that way)
- `packages/core/README.md` (same, for the core package)
- the module docstrings inside the wheels (`taxfill_core/__init__.py`,
  `taxfill_mcp/__init__.py`)
- everything in the two sdists (`tar tzf dist/*.tar.gz`): `pyproject.toml`
  with its comments, `README.md`, `src/` (in the core sdist with the staged
  `_data/`, plus `hatch_build.py`) and `tests/`. The `.mcpb` recipe
  (`packages/mcp-server/bundle/`) is excluded from the `taxfill-mcp` sdist
  (`[tool.hatch.build.targets.sdist]`), so it stays a repo-only surface.

They already carry the release wording, and `test_release_surfaces.py` holds
them: no count and no pre-release phrase on any of the six text surfaces, the
release-status sentences and the same outbound-traffic sentence on the four
long ones, no "`.gov` URLs only" claim. `scripts/release_smoke.py --dist`
(step 3) fails if an sdist carries `bundle/`. Re-read them anyway before every
upload, against the code, not memory.

**The repo-only surfaces flip after the upload**, in the follow-up commit, to
the published form (`uvx taxfill-mcp`, the `.mcpb` bundle, a bare `taxfill` on
PATH): the root README's status badge, Quickstart callout and connect steps;
docs/USER_GUIDE.md ("Install and connect", "Coming with v0.1", the
`uv run … taxfill purge` lines and the FAQ "What isn't supported yet?");
docs/TOOLS.md's `uv run taxfill` CLI note; the "Project status" line in
.github/CONTRIBUTING.md; the "Until then" section of
packages/mcp-server/bundle/README.md; and the status lines in the root
`pyproject.toml`. They are not on PyPI, and saying "published" before the
upload would be false. `test_release_surfaces.py::test_no_repo_only_surface_still_reads_pre_release`
holds this list as a strict xfail: the flip commit makes it pass, so it must
drop the marker in the same commit.

**The `mcp<2` decision (2026-10-15).** `taxfill-mcp` depends on
`mcp>=1.2,<2`, and the cap is load-bearing. `server.py` imports
`from mcp.server.fastmcp import FastMCP, Image`, a 1.x module. In the MCP
python-sdk 2.x (2.0.0 released 2026-07-28) FastMCP was renamed to
`mcp.server.mcpserver.MCPServer`, inside the same `mcp` distribution, and other
APIs changed. The wheels show it: 1.30.0 has the `mcp/server/fastmcp/` package
(19 entries) and no `mcpserver`; 2.0.0 and 2.3.0 both carry
`mcp/server/mcpserver/` (21 entries, "MCPServer - A more ergonomic interface
for MCP servers") and no `mcp/server/fastmcp/` package; 2.3.0 adds a one-file
`mcp/server/fastmcp.py` whose import raises `ModuleNotFoundError` ("FastMCP was
renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other
APIs changed ... or pin 'mcp<2' to keep running v1 code"). On 2026-10-15 the
latest 1.x is **1.30.0** (2026-09-07) and the latest 2.x is **2.3.0**
(2026-10-02), resolved with `uvx pip index versions mcp` and the PyPI JSON API
(`https://pypi.org/pypi/mcp/json`); `uv.lock` holds **1.28.0**, which the test
suite runs on. **Recommendation: ship v0.1 on 1.x**, and before v0.2 evaluate
the 2.x port: the server moves to `MCPServer` and the other changed APIs per
the SDK's v2 migration guide (the third-party `fastmcp` package is an
alternative, not the successor). Note what a user actually gets: a fresh
install resolves the newest 1.x under the cap (1.30.0 today), not the locked
1.28.0, which is why the clean-venv smoke in step 3 installs from the index
rather than the lock. Re-run the resolution on release day and update the
figures here.

## 2. Stage data + build

```bash
python scripts/stage_data.py          # copy knowledge/ + formpacks/ into the package
rm -rf dist/
uv build --package taxfill-core       # sdist + wheel, data force-included via [tool.hatch.build] artifacts
uv build --package taxfill-mcp
```

`stage_data.py` copies the repo-root `knowledge/` and `formpacks/` trees (YAML/md
only) into `packages/core/src/taxfill_core/_data/`; the `datadir` resolver finds
them there once installed. The copy is git-ignored and rebuilt every run.

## 3. Verify the artifacts

```bash
uvx twine check dist/*                 # PyPI metadata + README rendering — must PASS
```

Then the self-contained smoke test (exactly what CI's `packaging` job runs; do
it locally too before uploading):

```bash
REPO="$PWD"
TMP="$(mktemp -d)"
uv venv "$TMP/venv" --python 3.11
uv pip install --python "$TMP/venv/bin/python" --no-cache --find-links dist/ "$(ls dist/taxfill_mcp-*.whl)"
( cd "$TMP" && env -u TAXFILL_DATA_DIR "$TMP/venv/bin/python" "$REPO/scripts/release_smoke.py" \
    --repo "$REPO" --dist "$REPO/dist" )
```

[`scripts/release_smoke.py`](../../scripts/release_smoke.py) types no number:
it derives every expectation from the checkout. It checks that the installed
packages and `data_root()` sit inside the venv's site-packages; that
`list_forms()` returns, for every jurisdiction-year, exactly the form keys the
checkout's `formpacks/` holds; that every staged YAML / Markdown file is in the
wheel byte for byte; that every knowledge pack loads; that every state knowledge
year has one pack per state jurisdiction (42); and that the server registers
exactly the tools `packages/mcp-server/tests/test_server_e2e.py` pins
(`EXPECTED_TOOLS`), the same set CI checks; with `--dist`, that `dist/` holds
one sdist per package and neither carries the repo-only `bundle/` recipe. It
prints the counts it compared and exits nonzero on any mismatch. `uv run python scripts/release_smoke.py
--repo . --checkout` is a quick self-check in the repo's own (editable) venv;
it skips the site-packages checks, so it does not test the packaging.

Optional dry run against TestPyPI first (release-time only: it needs the
upload, and a version uploaded to TestPyPI cannot be re-uploaded there either):

```bash
uvx twine upload --repository testpypi dist/*
uvx --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
    --from taxfill-mcp taxfill tools   # smoke the published copy: lists every tool
```

`--index-strategy unsafe-best-match` is needed because TestPyPI carries no
`mcp` 1.x (on 2026-10-15 its only `mcp` release is 0.8.0.dev0): under uv's
default first-index strategy `mcp>=1.2,<2` then resolves from TestPyPI alone
and fails, while with this flag it resolves 1.30.0 from PyPI. The trade-off is
dependency confusion: anyone can upload to TestPyPI, and this strategy takes the
highest version of EVERY dependency from either index, so a squatted name there
could replace a real dependency. Treat the dry run as running untrusted code
(a throwaway VM or container), or skip it.

## 4. Upload to PyPI  ⚠️ manual, irreversible

```bash
uvx twine upload dist/*
```

A given version number can never be reused on PyPI. Upload `taxfill-core` first
(the server depends on it), then `taxfill-mcp` resolves at install time.

Verify the public path:

```bash
uvx taxfill-mcp        # should start the stdio server with data bundled
```

## 5. Tag

```bash
git tag -a v0.1.0 -m "TaxFill v0.1.0" && git push origin v0.1.0
```

## 6. Build the MCPB bundle (publish-gated)

Now that `uvx taxfill-mcp` works, follow [`packages/mcp-server/bundle/README.md`](../../packages/mcp-server/bundle/README.md):

```bash
cd packages/mcp-server/bundle
mcpb validate && mcpb pack   # manifest.json already finalized — just validate + pack -> taxfill.mcpb
```

`packages/mcp-server/bundle/manifest.json` is already finalized and **passes `mcpb validate`** against
the current CLI schema (v0.2): the `$schema_note` draft marker was dropped,
`server.entry_point` added, and the `permissions` block removed (the v0.2/v0.3
schema has no permissions field — Claude Desktop prompts for file/network consent
at install time). It declares the **23 tools**; the README disclaimer applies.

## 7. Demo GIF

Record the ≤60-second screen capture per [`DEMO.md`](DEMO.md) and drop it at the
path the README references.

## Post-release checklist

- [ ] `uvx taxfill-mcp` works on a machine that never had the repo.
- [ ] One-click `.mcpb` installs in Claude Desktop and the tools appear.
- [ ] No pre-release wording is left on the repo-only surfaces (the list in step 1): `grep -n -i -E "pre-release|pre--release|not on pypi yet|not yet (published|on pypi|available on pypi)|nothing is published|coming with v0\.1|once published|once (taxfill is )?installed from pypi|in development|until then" README.md docs/USER_GUIDE.md docs/TOOLS.md .github/CONTRIBUTING.md packages/mcp-server/bundle/README.md pyproject.toml` is empty, and `test_release_surfaces.py::test_no_repo_only_surface_still_reads_pre_release` has lost its xfail marker (the test holds this grep to that test's pattern and file list; the wheel-shipped surfaces are held by the rest of that module).
- [ ] `main` moves to the next `.dev0` version (step 1).
- [ ] Tag pushed; GitHub release notes drafted.
- [ ] A non-developer reaches a filled sample form in <20 min from the README
      and the user guide it links (the §13 acceptance test — see [`ACCEPTANCE.md`](ACCEPTANCE.md)).
