"""Offline tests for the release path (Phase J JA1.5/JA1.6): scripts/release_notes.py, the CHANGELOG's generated
coverage block (scripts/sync_doc_counts.py), scripts/bundle_probe.py and the shape of .github/workflows/release.yml.

A release tag uploads to PyPI, which can never be undone, so the checks that stop a bad tag must themselves be
right: the tag must equal the one version every site carries and be a public version, the CHANGELOG section must
exist and be dated, and the workflow must keep its order (validate before any upload, taxfill-core before
taxfill-mcp, the bundle after both), its permissions and its SHA pins.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
CHANGELOG = REPO / "docs" / "CHANGELOG.md"
RELEASE_YML = REPO / ".github" / "workflows" / "release.yml"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


notes = _load("release_notes")
sdc = _load("sync_doc_counts")
probe = _load("bundle_probe")

SITES = {"core": "0.1.0", "mcp": "0.1.0", "pin": "0.1.0"}
DATED = """# Changelog

## [Unreleased]

Nothing yet.

## [0.2.0] - 2027-03-01

### Fixed

- something

## [0.1.0] - 2026-11-02

### Added

<!-- BEGIN GENERATED release counts: x -->
- **23 MCP tools**
<!-- END GENERATED release counts -->
- the rest

[Unreleased]: https://example.invalid/compare/v0.2.0...HEAD
[0.1.0]: https://example.invalid/releases/tag/v0.1.0
"""


# ── scripts/release_notes.py: the tag ────────────────────────────────────────


def test_the_repo_version_sites_agree_and_the_tag_must_match_them():
    sites = notes.version_sites()
    assert len(sites) == 6 and len(set(sites.values())) == 1, sites
    version = next(iter(sites.values()))
    assert notes.release_version(f"v{version}", sites) == version
    with pytest.raises(notes.ReleaseError, match="does not match"):
        notes.release_version(f"v{version}.1", sites)
    with pytest.raises(notes.ReleaseError, match="does not match"):
        notes.release_version(version, sites)  # no leading v


@pytest.mark.parametrize("version", ["0.1.0.dev0", "0.1.1.dev3", "0.1.0+local", "0.1"])
def test_a_dev_local_or_short_version_is_never_released(version):
    sites = dict.fromkeys(SITES, version)
    with pytest.raises(notes.ReleaseError, match="not a public release"):
        notes.release_version(f"v{version}", sites)


@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "0.2.0rc1", "0.2.0b2", "0.1.0.post1"])
def test_public_versions_are_released(version):
    assert notes.release_version(f"v{version}", dict.fromkeys(SITES, version)) == version


def test_disagreeing_sites_are_named():
    with pytest.raises(notes.ReleaseError, match="disagree") as exc:
        notes.release_version("v0.1.0", {**SITES, "pin": "0.0.9"})
    assert "pin: 0.0.9" in str(exc.value)


def test_a_missing_or_loose_pin_is_refused(tmp_path):
    for rel in ("packages/core/pyproject.toml", "packages/mcp-server/pyproject.toml",
                "packages/mcp-server/bundle/pyproject.toml", "packages/mcp-server/bundle/manifest.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    assert len(notes.version_sites(tmp_path)) == 6
    bundle = tmp_path / "packages/mcp-server/bundle/pyproject.toml"
    bundle.write_text(re.sub(r'"taxfill-mcp==[^"]+"', '"taxfill-mcp>=0.1"', bundle.read_text(encoding="utf-8")),
                      encoding="utf-8")
    with pytest.raises(notes.ReleaseError, match="must pin taxfill-mcp=="):
        notes.version_sites(tmp_path)


# ── scripts/release_notes.py: the CHANGELOG section ─────────────────────────


def test_the_dated_section_is_the_notes_without_markers_or_link_references():
    date, body = notes.section_notes(DATED, "0.1.0")
    assert date == "2026-11-02"
    assert body == "### Added\n\n- **23 MCP tools**\n- the rest\n"
    date2, body2 = notes.section_notes(DATED, "0.2.0")
    assert (date2, body2) == ("2027-03-01", "### Fixed\n\n- something\n")


def test_hard_wrapped_lines_are_joined_but_lists_headings_and_code_are_kept():
    md = ("Para one\nwraps here.\n\n### Head\n\n- item one\n  wraps.\n- item two\n\n```bash\nuv sync\nuv run\n```\n"
          "| a |\n| b |\n> quote\n> more")
    assert notes.unwrap(md) == ("Para one wraps here.\n\n### Head\n\n- item one wraps.\n- item two\n\n```bash\nuv sync\n"
                                "uv run\n```\n| a |\n| b |\n> quote\n> more")


@pytest.mark.parametrize("text,match", [
    (DATED.replace("## [0.1.0] - 2026-11-02", "## [0.1.0] - Unreleased"), "has no date"),
    (DATED.replace("## [0.1.0] - 2026-11-02", "## [0.1.0]"), "has no date"),
    (DATED.replace("2026-11-02", "2026-13-02"), "not a date"),
    (DATED.replace("## [0.1.0] - 2026-11-02", "## [0.0.9] - 2026-11-02"), "found 0"),
    (DATED + "\n## [0.1.0] - 2026-11-03\n\n- again\n", "found 2"),
    ("# Changelog\n\n## [0.1.0] - 2026-11-02\n\n<!-- only a comment -->\n\n## [0.0.1] - 2026-01-01\n- x\n", "empty"),
])
def test_a_missing_undated_duplicate_or_empty_section_stops_the_release(text, match):
    with pytest.raises(notes.ReleaseError, match=match):
        notes.section_notes(text, "0.1.0")


def test_main_writes_the_notes_for_a_matching_dated_tag(tmp_path, capsys):
    version = next(iter(notes.version_sites().values()))
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(DATED.replace("0.1.0", version), encoding="utf-8")
    out = tmp_path / "notes.md"
    assert notes.main(["--tag", f"v{version}", "--changelog", str(changelog), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("### Added")
    assert notes.main(["--tag", "v9.9.9", "--changelog", str(changelog)]) == 1
    assert "does not match" in capsys.readouterr().err


def test_the_repo_changelog_has_an_unreleased_section_and_one_for_the_current_version():
    """Between releases main carries <next>.dev0 and the CHANGELOG an undated '## [<next>] - Unreleased' section with
    the generated coverage block; the release commit dates it (docs/dev/PUBLISHING.md step 1)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    version = re.sub(r"\.dev\d+$", "", next(iter(notes.version_sites().values())))
    headings = list(notes.HEADING.finditer(text))
    assert headings[0].group(0) == "## [Unreleased]", [h.group(0) for h in headings]
    current = [h for h in headings if h.group("version") == version]
    assert len(current) == 1, f"docs/CHANGELOG.md needs one section for {version}: {[h.group(0) for h in headings]}"
    if notes.DATED.match(current[0].group("rest")):
        notes.section_notes(text, version)  # a dated section must also yield notes
        return
    assert current[0].group(0) == f"## [{version}] - Unreleased", current[0].group(0)
    later = [h.start() for h in headings if h.start() > current[0].start()]
    section = text[current[0].end():later[0] if later else len(text)]
    assert section.count(sdc.CL_BEGIN) == 1 == section.count(sdc.CL_END), "the next release carries the coverage block"


# ── the generated coverage block (scripts/sync_doc_counts.py) ────────────────

C = {"tools": 23, "ops": 40, "doc_kinds": 29, "federal": 3, "federal_by_year": {2025: 2, 2026: 1}, "planning": [2026],
     "state": 2, "state_by_year": {2025: 2}, "handfill_state": 1, "handfill_years": {"ct": [2023, 2024, 2025]},
     "juris_by_year": {2025: 2}, "jurisdictions": 2, "fbar_years": [2025, 2026], "federal_knowledge": [2025, 2026],
     "state_knowledge_counts": {2025: 2}}


def _changelog(heading: str, block: str = "- stale\n") -> str:
    return (f"# Changelog\n\n## [Unreleased]\n\n{heading}\n\n### Added\n\n{sdc.CL_BEGIN}\n{block}{sdc.CL_END}\n"
            "- kept\n\n## [0.0.9] - 2026-01-01\n\n- old\n")


def test_the_block_in_an_undated_section_is_regenerated():
    text, rewritten, frozen = sdc.sync_changelog(_changelog("## [0.1.0] - Unreleased"), C)
    assert (rewritten, frozen) == (1, 0)
    assert "- stale" not in text and "**23 MCP tools**" in text and "TY2025 2; planning year TY2026 1" in text
    assert "CT for 2023–2025" in text and "- kept" in text
    assert sdc.sync_changelog(text, C) == (text, 1, 0)  # idempotent


def test_a_dated_section_is_frozen():
    before = _changelog("## [0.1.0] - 2026-11-02")
    assert sdc.sync_changelog(before, C) == (before, 0, 1)


@pytest.mark.parametrize("text,match", [
    (f"## [0.1.0]\n{sdc.CL_BEGIN}\n- x\n", "unbalanced"),
    (f"{sdc.CL_BEGIN}\n- x\n{sdc.CL_END}\n## [0.1.0]\n", "above every"),
    (f"## [0.1.0]\n{sdc.CL_BEGIN}\n{sdc.CL_BEGIN}\n{sdc.CL_END}\n{sdc.CL_END}\n", "not closed"),
])
def test_broken_markers_are_reported(text, match):
    with pytest.raises(ValueError, match=match):
        sdc.sync_changelog(text, C)


# ── .github/workflows/release.yml ────────────────────────────────────────────

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)@(\S+)(.*)$")


def _workflow(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the bare key `on` as True
    return data


def _uses(path: Path) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := USES.match(line):
            assert re.fullmatch(r"[0-9a-f]{40}", m.group(2)), f"{path.name}: {line.strip()} is not pinned by SHA"
            assert re.fullmatch(r"\s+# v\d+(\.\d+)*", m.group(3)), f"{path.name}: {line.strip()} lacks '# vX.Y.Z'"
            pins.setdefault(m.group(1), set()).add(m.group(2))
    return pins


def test_release_runs_on_version_tags_only_and_reads_by_default():
    wf = _workflow(RELEASE_YML)
    assert wf["on"] == {"push": {"tags": ["v*"]}}
    assert wf["permissions"] == {"contents": "read"}


def test_every_action_is_sha_pinned_and_shares_ci_pins():
    release, ci = _uses(RELEASE_YML), _uses(CI_YML)
    assert set(release) == {"actions/checkout", "astral-sh/setup-uv", "actions/upload-artifact",
                            "actions/download-artifact", "pypa/gh-action-pypi-publish"}
    for action in ("actions/checkout", "astral-sh/setup-uv"):
        assert release[action] == ci[action] and len(ci[action]) == 1, action
    assert all(len(shas) == 1 for shas in release.values()), release
    uv = {v for p in (RELEASE_YML, CI_YML) for v in re.findall(r'^\s+version: "([\d.]+)"', p.read_text(encoding="utf-8"),
                                                                re.M)}
    assert len(uv) == 1, f"release.yml and ci.yml pin different uv versions: {uv}"


def test_the_mcpb_cli_is_one_exact_version_in_both_workflows():
    versions = {v for p in (RELEASE_YML, CI_YML)
                for v in re.findall(r"@anthropic-ai/mcpb@(\S+)", p.read_text(encoding="utf-8"))}
    assert len(versions) == 1 and re.fullmatch(r"\d+\.\d+\.\d+", next(iter(versions))), versions
    assert "@anthropic-ai/mcpb@" in CI_YML.read_text(encoding="utf-8")


def test_the_jobs_run_validate_then_core_then_mcp_then_the_bundle():
    jobs = _workflow(RELEASE_YML)["jobs"]
    assert list(jobs) == ["build", "publish-core", "publish-mcp", "github-release"]
    assert jobs["publish-core"]["needs"] == "build"
    assert jobs["publish-mcp"]["needs"] == "publish-core"
    assert jobs["github-release"]["needs"] == "publish-mcp"
    for name, project in (("publish-core", "taxfill-core"), ("publish-mcp", "taxfill-mcp")):
        job = jobs[name]
        assert job["environment"]["name"] == "pypi", name
        assert job["permissions"] == {"id-token": "write"}, name
        publish = [s for s in job["steps"] if s.get("uses", "").startswith("pypa/gh-action-pypi-publish@")]
        assert len(publish) == 1 and publish[0]["with"]["packages-dir"] == f"release/upload/{project}/", name
        assert "password" not in publish[0]["with"], "Trusted Publishing: no token"
        # A re-run after a partial upload (one of the two files reached PyPI) must not fail on the file PyPI has.
        assert publish[0]["with"].get("skip-existing") is True, name
    assert "id-token" not in str(jobs["build"].get("permissions", "")) + str(jobs["github-release"]["permissions"])
    assert jobs["github-release"]["permissions"] == {"contents": "write"}


def test_the_build_job_checks_the_tag_first_and_packs_and_checks_the_bundle_before_any_upload():
    build = _workflow(RELEASE_YML)["jobs"]["build"]
    steps = [s.get("run", "") for s in build["steps"]]
    order = [next(i for i, run in enumerate(steps) if needle in run)
             for needle in ("scripts/release_notes.py", "scripts/stage_data.py", "twine check",
                            "scripts/release_smoke.py", "mcpb@")]
    assert order == sorted(order), f"build steps out of order: {order}"
    assert "merge-base --is-ancestor" in steps[order[0]]
    # The bundle is packed in the read-only job and checked there: the same file list as ci.yml's packaging job,
    # and every packed file byte-equal to the checkout.
    assert "permissions" not in build, "build runs on the workflow's read-only token"
    bundle = steps[order[-1]]
    assert "validate packages/mcp-server/bundle/manifest.json" in bundle
    assert "pack packages/mcp-server/bundle mcpb/taxfill.mcpb" in bundle
    assert 'test "$FILES" = "manifest.json pyproject.toml src/server.py "' in bundle
    assert 'test "$FILES" = "manifest.json pyproject.toml src/server.py "' in CI_YML.read_text(encoding="utf-8")
    assert 'cmp - "packages/mcp-server/bundle/$f"' in bundle
    upload = next(s for s in build["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert "mcpb/" in upload["with"]["path"].split(), "the packed bundle travels in the 'release' artifact"


def test_the_github_release_waits_for_pypi_launches_the_packed_bundle_and_only_attaches_it():
    job = _workflow(RELEASE_YML)["jobs"]["github-release"]
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "mcpb@" not in runs, "github-release (contents: write) must not pack: build packs and checks the bundle"
    assert (runs.index('--from "taxfill-mcp==$VERSION"') < runs.index("unzip -q release/mcpb/taxfill.mcpb")
            < runs.index("scripts/bundle_probe.py") < runs.index("gh release create"))
    assert "--notes-file release/release-notes.md" in runs and "release/mcpb/taxfill.mcpb release/upload/" in runs
    checkout = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert all(s.get("with", {}).get("persist-credentials") is False for s in checkout), \
        "the write token must not be stored in .git/config"
    token = [s for s in job["steps"] if "GH_TOKEN" in s.get("env", {})]
    assert len(token) == 1 and "gh release create" in token[0]["run"], "only the release step sees the token"


def test_the_trusted_publisher_values_are_written_down():
    text = RELEASE_YML.read_text(encoding="utf-8")
    for line in ("PyPI Project Name:  taxfill-core", "(then a second publisher with: taxfill-mcp)",
                 "Owner:              Ryanczj0306", "Repository name:    taxfill-mcp",
                 "Workflow name:      release.yml", "Environment name:   pypi"):
        assert line in text, line


# ── scripts/bundle_probe.py ──────────────────────────────────────────────────

FAKE_SERVER = textwrap.dedent("""
    import json, sys, time
    mode, tools = sys.argv[1], sys.argv[2].split(",")
    if mode == "die":
        print("boom: cannot install", file=sys.stderr)
        sys.exit(3)
    for line in sys.stdin:
        msg = json.loads(line)
        if mode == "hang":
            time.sleep(30)
        if msg.get("method") == "initialize":
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}), flush=True)
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake"}}
        elif msg.get("method") == "tools/list":
            result = {"tools": [{"name": t, "inputSchema": {}} for t in tools]}
        else:
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
""")


def _fake_bundle(tmp_path: Path, mode: str, serves: str, declares: list[str]) -> Path:
    (tmp_path / "fake_server.py").write_text(FAKE_SERVER, encoding="utf-8")
    manifest = {"server": {"type": "uv", "entry_point": "fake_server.py",
                           "mcp_config": {"command": sys.executable,
                                          "args": ["${__dirname}/fake_server.py", mode, serves]}},
                "tools": [{"name": t} for t in declares]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_the_probe_passes_when_the_bundle_lists_exactly_its_manifest_tools(tmp_path, capsys):
    bundle = _fake_bundle(tmp_path, "ok", "calc,fill_form", ["fill_form", "calc"])
    assert probe.probe(bundle, timeout=60) == {"server": {"name": "fake"}, "tools": ["calc", "fill_form"]}
    assert probe.main([str(bundle), "--timeout", "60"]) == 0
    assert "listed 2 tools, exactly the manifest's" in capsys.readouterr().out


@pytest.mark.parametrize("mode,serves,match", [
    ("ok", "calc", r"missing \['fill_form'\], not declared \[\]"),
    ("ok", "calc,fill_form,extra", r"not declared \['extra'\]"),
    ("die", "calc", r"exited \(code 3\)(.|\n)*boom: cannot install"),
])
def test_the_probe_fails_on_a_tool_mismatch_or_a_server_that_dies(tmp_path, mode, serves, match):
    with pytest.raises(probe.ProbeError, match=match):
        probe.probe(_fake_bundle(tmp_path, mode, serves, ["calc", "fill_form"]), timeout=60)


def test_the_probe_times_out_and_reports_a_missing_launcher(tmp_path, capsys):
    with pytest.raises(probe.ProbeError, match="no answer to request 1 within 1 s"):
        probe.probe(_fake_bundle(tmp_path, "hang", "calc", ["calc"]), timeout=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["server"]["mcp_config"]["command"] = str(tmp_path / "no-such-launcher")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert probe.main([str(tmp_path), "--timeout", "5"]) == 1
    assert "could not start" in capsys.readouterr().err


def test_the_probe_launches_the_repo_bundle_by_its_own_mcp_config():
    """The probe reads the command it runs from the bundle's manifest: the repo bundle's is its uv entry point."""
    cmd, env, declared = probe._command(REPO / "packages" / "mcp-server" / "bundle")
    bundle_dir = str((REPO / "packages" / "mcp-server" / "bundle").resolve())
    assert cmd == ["uv", "run", "--directory", bundle_dir, "src/server.py"] and env == {}
    assert len(declared) == len(json.loads((REPO / "packages/mcp-server/bundle/manifest.json").read_text(
        encoding="utf-8"))["tools"])
