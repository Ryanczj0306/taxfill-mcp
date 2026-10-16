# MCPB bundle (`taxfill.mcpb`) — build recipe

The **MCPB bundle** is meant as the install path for non-technical Claude
Desktop / Cowork users: download `taxfill.mcpb` and double-click it. It uses
mcpb's **experimental** uv runtime, so on a Claude Desktop build without that
runtime the user installs uv first, and a build that only knows manifest 0.3 or
older may refuse the bundle (see "The runtime" below). It is **publish-gated**:
the bundle carries no server code, only a launcher that installs the published
`taxfill-mcp` from PyPI, so `.github/workflows/release.yml` packs it before the
upload but attaches it to the GitHub release only after the published version
starts from the bundle (docs/dev/PUBLISHING.md step 6). Nobody needs to pack it
by hand.

## What is in the bundle

| File | Role |
|---|---|
| `manifest.json` | `manifest_version` **0.4**, `server.type` **`"uv"`**, the tool list a one-click install shows |
| `pyproject.toml` | the launcher project: `dependencies = ["taxfill-mcp==<version>"]`, `requires-python >=3.11` |
| `src/server.py` | `server.entry_point`: imports `taxfill_mcp.server.main` and runs it over stdio |
| `.mcpbignore` | keeps this README (a repo-only recipe), `.venv/` and `uv.lock` out of the packed file |

`manifest.json`'s calc entry is rewritten from the live server by
`scripts/sync_bundle_manifest.py` (`packages/mcp-server/tests/test_readme_sync.py`
fails if the tool names drift), and the version in `manifest.json` and in
`pyproject.toml` (its `version` and the `taxfill-mcp==` pin) moves with every
release: `packages/mcp-server/tests/test_release_surfaces.py` fails unless they
equal the packages' version.

## The runtime: `server.type "uv"` (decided 2026-10-15)

The question was whether the bundle can bootstrap Python for a user who has
nothing installed. The answer, from the schemas that `@anthropic-ai/mcpb` 2.1.2
(the latest on npm on 2026-10-15) ships for manifest versions 0.1-0.4:

- `server.type` is `python | node | binary` in 0.1, 0.2 and 0.3, in the strict
  schemas and in the loose ones (`dist/schemas_loose/0.3.js` also has only
  those three); manifest **0.4 adds `uv`**. The spec (MANIFEST.md on mcpb's
  `main` branch, read 2026-10-15) still calls 0.3 the current version and
  describes `uv` as a "Python server using UV runtime (v0.4+)": dependencies are
  declared in the bundle's `pyproject.toml` "and installed by the host
  application using UV", with "No user Python installation required", and for
  this type "`mcp_config` is optional (host manages execution)". The CLI's
  README marks the uv runtime **"Experimental - v0.4+"**.
- The spec text and the 2.1.2 schema disagree on `mcp_config`: the strict 0.4
  schema in 2.1.2 still **requires** it, so this manifest keeps one to pass
  `mcpb validate`. It is the command of the `examples/hello-world-uv` manifest on
  mcpb's `main` branch (2026-10-15), `uv run --directory ${__dirname}
  src/server.py`; that example's manifest at the `v2.1.2` tag has no
  `mcp_config` at all.

So the manifest uses `server.type "uv"`. What that means for a user is
**untested on any host** so far:

- **A Claude Desktop build that implements the uv runtime** should install
  Python and `taxfill-mcp` itself (the spec says the host manages execution),
  with nothing to install first. Not yet observed.
- **A build that accepts manifest 0.4 but does not run `uv` bundles itself**
  could start the `mcp_config` command, which needs `uv` on `PATH`; for those
  users step 0 is installing uv
  (https://docs.astral.sh/uv/getting-started/installation/), and uv then
  installs Python. Without uv the launch fails, because `uv` is not on `PATH`.
- **An older build that validates against the 0.3 (or earlier) schema** would
  most likely refuse the manifest outright (`manifest_version` 0.4 and
  `server.type "uv"` are both outside that schema), and installing uv does not
  help. Those users run `uvx taxfill-mcp` instead (the connect steps in the
  top-level README).

The previous manifest (0.2, `server.type "binary"`, command `uvx taxfill-mcp`)
needed uv on `PATH` in every host but fits every schema version. To go back to
it, set `manifest_version` to `"0.2"` and `server` to `{"type": "binary",
"entry_point": "taxfill-mcp", "mcp_config": {"command": "uvx", "args":
["taxfill-mcp"]}}`, then delete `pyproject.toml`, `src/` and the bundle checks
in test_release_surfaces.py, scripts/release_notes.py, ci.yml's packaging job
and release.yml's build and github-release jobs (`scripts/bundle_probe.py`
reads the command from the manifest, so it works for either).

What is proven is the manifest's own command, not a host: the packed bundle,
unzipped outside the repo, answers MCP `initialize` and `tools/list` with
exactly the manifest's tools when started with its `uv run --directory <bundle>
src/server.py` (`scripts/bundle_probe.py`). Before the first upload that was run
locally against locally built wheels; `release.yml` runs it again against the
published `taxfill-mcp` before it attaches the bundle. What a given Claude
Desktop build does with the bundle is checked after the first upload, on a
machine with uv, one without uv, and an older Desktop build (the post-release
checklist in docs/dev/PUBLISHING.md).

## Build (CI and release)

CI's `packaging` job validates and packs on every push. `release.yml` packs
`taxfill.mcpb` in its read-only `build` job (same file-list check, plus a byte
comparison of each packed file with the checkout), and its `github-release` job
attaches that same file once the published version resolves from PyPI and the
bundle starts from it. The same commands by hand, from the repo root:

```bash
npx --yes @anthropic-ai/mcpb@2.1.2 validate packages/mcp-server/bundle/manifest.json
npx --yes @anthropic-ai/mcpb@2.1.2 pack packages/mcp-server/bundle taxfill.mcpb
```

The packed file holds exactly `manifest.json`, `pyproject.toml` and
`src/server.py` (CI checks that list). After any server tool change, run
`uv run python scripts/sync_bundle_manifest.py --write`.

## Manifest values

- **name:** `taxfill` · **display_name:** `TaxFill` · **version:** the release
  version · **license:** MIT
- **tools:** every tool the server exposes (see
  [`packages/mcp-server/src/taxfill_mcp/server.py`](../src/taxfill_mcp/server.py)
  and the table in [docs/TOOLS.md](../../../docs/TOOLS.md#mcp-tools)).
- **Permissions / network:** the manifest schema has no permissions field — Claude
  Desktop asks at install time for outbound network (blank forms from
  the tax agencies' own sites, or their exact Internet Archive copies, and the
  one-time install of `taxfill-mcp` from PyPI) and local file access (where
  filled PDFs are written). No telemetry, no accounts.
- Reuse the disclaimer from the top-level README: not tax advice, not a
  preparer, review-draft only, paper filing — no e-file.

## Without the bundle

If a Claude Desktop build refuses the bundle, connect `uvx taxfill-mcp` directly: see the
[README quickstart](../../../README.md#quickstart).
