# Releasing TaxFill v0.1

This is the mechanical runbook for shipping a release. The packaging is already
proven self-contained (CI `packaging` job builds, installs into a clean venv
outside the repo, and exercises the loaders), so a release is: bump → build →
verify → upload → tag → bundle.

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

## 1. Bump the version

Set the same version in both packages (they release together):

- `packages/core/pyproject.toml` → `version`
- `packages/mcp-server/pyproject.toml` → `version`

For the first real release, drop the `.dev0` suffix → `0.1.0`. Also flip the
"not yet published to PyPI" notes in both package `README.md`s and
`packages/mcp-server/README.md`'s quickstart from the source-checkout form to
`uvx taxfill-mcp`, and the status lines in the root `pyproject.toml`.

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

Then the self-contained smoke test (this is exactly what CI's `packaging` job
runs — do it locally too before uploading):

```bash
TMP="$(mktemp -d)"
uv venv "$TMP/venv" --python 3.11
uv pip install --python "$TMP/venv/bin/python" --find-links dist/ "$(ls dist/taxfill_mcp-*.whl)"
( cd "$TMP" && env -u TAXFILL_DATA_DIR "$TMP/venv/bin/python" -c "
import asyncio, taxfill_mcp.server as s
from taxfill_core.datadir import data_root
from taxfill_core import load_state_knowledge
assert 'site-packages' in str(data_root())
assert load_state_knowledge('ca', 2023).jurisdiction == 'states/ca'
assert len(asyncio.run(s.mcp.list_tools())) == 15
print('self-contained OK')
" )
```

Optional dry run against TestPyPI first:

```bash
uvx twine upload --repository testpypi dist/*
uvx --from taxfill-mcp --index https://test.pypi.org/simple/ taxfill-mcp   # smoke the published copy
```

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

Now that `uvx taxfill-mcp` works, follow [`bundle/README.md`](../bundle/README.md):

```bash
cd bundle
mcpb init && mcpb validate && mcpb pack   # produces taxfill.mcpb
```

Use the manifest values listed in that file (launch via `uvx taxfill-mcp`; the 15
tools; outbound-network-to-.gov + local-file permissions; the README disclaimer).

## 7. Demo GIF

Record the ≤60-second screen capture per [`DEMO.md`](DEMO.md) and drop it at the
path the README references.

## Post-release checklist

- [ ] `uvx taxfill-mcp` works on a machine that never had the repo.
- [ ] One-click `.mcpb` installs in Claude Desktop and the tools appear.
- [ ] README quickstart no longer says "not yet published".
- [ ] Tag pushed; GitHub release notes drafted.
- [ ] A non-developer reaches a filled sample form in <20 min from the README
      alone (the §13 acceptance test — see [`ACCEPTANCE.md`](ACCEPTANCE.md)).
