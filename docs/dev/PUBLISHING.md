# Releasing TaxFill v0.1

This is the mechanical runbook for shipping a release. The packaging is already
proven self-contained (CI `packaging` job builds, installs into a clean venv
outside the repo, and exercises the loaders), so a release is: the release
commit (version + CHANGELOG) → an optional local dry run → **the tag push**,
after which `.github/workflows/release.yml` builds, verifies and packs the
bundle, uploads to PyPI, launches the bundle against the upload and creates the
GitHub release → flip the repo-only docs.

> **Three steps are intentionally the user's** — they are outward-facing, so a
> human does them, not CI or an agent:
> 1. the one-time PyPI Trusted Publisher setup (step 0),
> 2. **pushing the release tag** (step 4): the workflow it starts uploads to
>    PyPI, which is irreversible — a version can never be uploaded twice, and
> 3. recording the demo GIF (see [`DEMO.md`](DEMO.md)).

What the agent half (Phase J JA1) prepared, so that the tag push is the only
outward act: `release.yml` and `scripts/release_notes.py` (the tag, version and
CHANGELOG checks that run before any upload), `docs/CHANGELOG.md`, the bundle's
uv runtime and its CI check, `scripts/release_smoke.py`,
`scripts/bundle_probe.py`, and the tests that hold them
(`test_release_surfaces.py`, `test_release_workflow.py`,
`test_release_smoke.py`).

## 0. Prerequisites

- **PyPI Trusted Publishing, set up once by the user** (no API token anywhere).
  On pypi.org, add a GitHub publisher for EACH of the two projects — before the
  first upload as a *pending* publisher (Your account → Publishing → Add a new
  pending publisher), afterwards under the project's Manage → Publishing —
  with exactly these values (the header comment of `release.yml` repeats them):

  | Field | taxfill-core | taxfill-mcp |
  |---|---|---|
  | PyPI Project Name | `taxfill-core` | `taxfill-mcp` |
  | Owner | `Ryanczj0306` | `Ryanczj0306` |
  | Repository name | `taxfill-mcp` | `taxfill-mcp` |
  | Workflow name | `release.yml` | `release.yml` |
  | Environment name | `pypi` | `pypi` |

  Then, in the GitHub repo, Settings → Environments → New environment `pypi`.
  Adding yourself as a required reviewer there makes each of the two upload jobs
  wait for your approval in the Actions tab — a last look before the
  irreversible step.
- `uv` installed. `uvx twine` and `uvx` are used below (no global installs);
  `npx` (Node.js) for the optional local `mcpb` check.
- A clean working tree on `main`, CI green. `release.yml` refuses a tag that
  does not point at a commit on `main`.

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
- `packages/mcp-server/bundle/pyproject.toml` → `version` and the
  `taxfill-mcp==<version>` pin (the bundle installs exactly this release)

`packages/mcp-server/tests/test_release_surfaces.py` fails unless all eight
agree, so a release commit that bumps one and forgets another fails CI, not
PyPI; `scripts/release_notes.py` checks the same sites against the tag before
`release.yml` builds anything. Run `uv lock` after the bump so `uv.lock` records
the new workspace versions (it lists both packages with their version).

**CHANGELOG.** [`docs/CHANGELOG.md`](../CHANGELOG.md) (Keep a Changelog; it
lives under `docs/` because the repo root is held at 13 entries). Between
releases the next version's section reads `## [<version>] - Unreleased` and
collects what is merged; its coverage bullets sit between GENERATED markers and
`scripts/sync_doc_counts.py --write` keeps them equal to the packs (CI's
`--check` fails when they drift). In the release commit:

1. change the heading to `## [<version>] - <YYYY-MM-DD>` (the release date):
   from then on `sync_doc_counts` leaves that section alone, so the coverage
   lines freeze as released;
2. re-read the hand-written bullets against what is merged since the previous
   tag (`git log v<previous>..HEAD`) and against the code;
3. check it the way the workflow will:
   `uv run python scripts/release_notes.py --tag v<version>` prints the notes,
   or says why the tag would be refused.

`release.yml` publishes that section as the GitHub release notes and stops
before any upload if it is missing, undated or empty. The first commit after the
tag (the `.dev0` bump) adds the next `## [<next>] - Unreleased` section with a
fresh pair of GENERATED markers (`test_release_workflow.py` requires it).

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

## 4. Push the tag — the upload ⚠️ the user, irreversible

Steps 2 and 3 are what the workflow runs; doing them locally first is optional
but cheap. Then, from the release commit on `main`:

```bash
git tag -a v0.1.0 -m "TaxFill v0.1.0" && git push origin v0.1.0
```

This push is the release. It starts `.github/workflows/release.yml`, whose
upload jobs put both packages on PyPI for good: a version number can never be
reused there (a broken upload can only be yanked and superseded by a new
version). If the `pypi` environment has required reviewers, each upload job
waits for your approval in the Actions tab.

## 5. What `release.yml` does, and recovering from a failed run

| Job | What it does | Uploads? |
|---|---|---|
| `build` | checks the tag is on `main`; `scripts/release_notes.py` (tag = `v<version>` for every version site, no `.dev`/local version, a dated non-empty CHANGELOG section); runs `test_release_surfaces.py` + `test_release_workflow.py`; stages data, builds both packages, `twine check`, the clean-venv smoke (`release_smoke.py --dist`); `mcpb validate` + `mcpb pack`, then checks that `taxfill.mcpb` holds exactly `manifest.json`, `pyproject.toml` and `src/server.py`, each byte-equal to the checkout. Read-only token | no |
| `publish-core` | uploads `taxfill-core` (Trusted Publishing, environment `pypi`, `skip-existing`) | **yes** |
| `publish-mcp` | uploads `taxfill-mcp` (it pins `taxfill-core==<version>`, so core goes first; `skip-existing`) | **yes** |
| `github-release` | waits until `uvx --from taxfill-mcp==<version> taxfill tools` resolves from PyPI; unzips the bundle `build` packed and runs `scripts/bundle_probe.py` on it (its own `uv run` command installs the published server and must answer MCP `initialize` + `tools/list` with exactly the manifest's tools); creates the GitHub release from the CHANGELOG section with the bundle and the four distributions attached. Packs nothing; its checkout keeps no token (`persist-credentials: false`) | no |

- **`build` failed:** nothing was uploaded. Delete the tag
  (`git push --delete origin v0.1.0 && git tag -d v0.1.0`), fix on `main`, tag
  again.
- **`publish-core` failed:** nothing was uploaded unless PyPI shows the
  version; fix the cause (usually the Trusted Publisher values in step 0) and
  use "Re-run failed jobs".
- **A partial upload** (PyPI shows one of a project's two files, the wheel or
  the sdist, but not the other): "Re-run failed jobs" as well. Both upload steps
  set `skip-existing: true`, and a re-run re-sends the same `release` artifact,
  so the file PyPI already has is skipped (it is the same file) and only the
  missing one is uploaded. Without that setting PyPI would answer
  `400 File already exists` and the job could never pass.
- **`publish-mcp` or `github-release` failed:** "Re-run failed jobs". Each
  upload is its own job, so a re-run never uploads `taxfill-core` a second
  time. If `github-release` fails in `bundle_probe.py`, the packages are on PyPI
  but the bundle did not start from them: read the probe's stderr tail before
  re-running. If the published version itself is broken, yank it on PyPI and
  release the next patch version; the number is spent.

Verify the public path afterwards:

```bash
uvx taxfill-mcp        # should start the stdio server with data bundled
```

## 6. The MCPB bundle (`taxfill.mcpb`)

Nothing to do by hand: `release.yml`'s read-only `build` job packs
[`packages/mcp-server/bundle/`](../../packages/mcp-server/bundle/README.md) with
`npx --yes @anthropic-ai/mcpb@2.1.2 pack` and checks the packed file list and
bytes; once the published `taxfill-mcp` resolves, `github-release` launches that
bundle with `scripts/bundle_probe.py` and attaches `taxfill.mcpb` to the GitHub
release. CI's `packaging` job validates and packs it on every push (and checks
the packed file holds only `manifest.json`, `pyproject.toml` and
`src/server.py`), so a schema problem shows up long before a tag.

**Runtime (decided 2026-10-15).** The manifest is `manifest_version` 0.4 with
`server.type "uv"`: the bundle ships a `pyproject.toml` pinning
`taxfill-mcp==<version>` and a three-line `src/server.py`, and its
`mcp_config` runs `uv run --directory ${__dirname} src/server.py`. Evidence: the
schemas `@anthropic-ai/mcpb` 2.1.2 ships allow `python | node | binary` up to
0.3 (the loose 0.3 schema too), and 0.4 adds `uv` ("installed by the host
application using UV", "No user Python installation required"; the CLI README
calls it "Experimental - v0.4+", and MANIFEST.md on mcpb's `main` branch still
names 0.3 the current version). That spec text says `mcp_config` is optional
for `uv` ("host manages execution"), but the 2.1.2 strict 0.4 schema requires
it, so the manifest keeps the command of the `hello-world-uv` example on mcpb's
`main` branch (2026-10-15; the example at the `v2.1.2` tag has no
`mcp_config`). What a host does with it is **untested**:

- a host that implements the uv runtime should need nothing installed first;
- a host that accepts 0.4 but only runs `mcp_config` needs uv on `PATH`
  (https://docs.astral.sh/uv/getting-started/installation/), which then
  installs Python; without uv the launch fails because `uv` is not on `PATH`;
- an older host that knows only the 0.3 (or earlier) schema may refuse the 0.4
  manifest outright; installing uv does not help there, and the user runs
  `uvx taxfill-mcp` instead.

Proven so far is the manifest's own command: the packed bundle, unzipped outside
the repo, answers MCP `initialize` and `tools/list` with exactly the manifest's
tools through `scripts/bundle_probe.py` (locally against locally built wheels
before the first upload; in `release.yml` against PyPI on every release). The
host side is the first post-release check below. The bundle README has the
details and the one-edit way back to the old `binary` + `uvx taxfill-mcp`
manifest, which fits every schema version.

The manifest already passes `mcpb validate` (no `permissions` field in the
schema — Claude Desktop prompts for file/network consent at install time).
It declares the **23 tools**; the README disclaimer applies.

## 7. Demo GIF

Record the ≤60-second screen capture per [`DEMO.md`](DEMO.md) and drop it at the
path the README references.

## Post-release checklist

- [ ] `uvx taxfill-mcp` works on a machine that never had the repo.
- [ ] One-click `taxfill.mcpb` (from the GitHub release) installs in Claude
      Desktop and the tools appear — once on a machine WITH uv, once on a
      machine WITHOUT uv (or Python), which proves the host's uv runtime, and
      once in an older Claude Desktop build, which shows whether it refuses a
      0.4 manifest. Record each result in the bundle README and the CHANGELOG.
      If the bundle fails without uv, either keep `server.type "uv"` with uv as
      the documented step 0, or go back to the `binary` manifest (bundle
      README); if older builds refuse it, say which, or go back to `binary`.
- [ ] No pre-release wording is left on the repo-only surfaces (the list in step 1): `grep -n -i -E "pre-release|pre--release|not on pypi yet|not yet (published|on pypi|available on pypi)|nothing is published|coming with v0\.1|once published|once (taxfill is )?installed from pypi|in development|until then" README.md docs/USER_GUIDE.md docs/TOOLS.md .github/CONTRIBUTING.md packages/mcp-server/bundle/README.md pyproject.toml` is empty, and `test_release_surfaces.py::test_no_repo_only_surface_still_reads_pre_release` has lost its xfail marker (the test holds this grep to that test's pattern and file list; the wheel-shipped surfaces are held by the rest of that module).
- [ ] `main` moves to the next `.dev0` version, and `docs/CHANGELOG.md` gains
      the next `## [<next>] - Unreleased` section with the GENERATED markers
      (step 1).
- [ ] The GitHub release for the tag exists, its notes are the CHANGELOG
      section, and it carries `taxfill.mcpb` and the four distributions.
- [ ] A non-developer reaches a filled sample form in <20 min from the README
      and the user guide it links (the §13 acceptance test — see [`ACCEPTANCE.md`](ACCEPTANCE.md)).
