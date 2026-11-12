"""scripts/repin_final.py (Phase J JT6): the compare, its verdicts and the --write path — offline.

Two layers. The synthetic one always runs: a draft (cover sheet, DRAFT banners, tooltips) and its finals are built
with reportlab into tmp_path, in a tmp repo and a tmp blank cache. The cached one reads the six real draft / final
pairs the ledger records from the blank cache and skips cleanly when a blank is not there (CI has no cache).
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pytest
import yaml
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from pdf_fixtures import make_acroform_pdf
from repins import REPO, ledger, repin_final as R
from taxfill_core.fetch import cached_blank_path, seed_blank
from taxfill_core.schemas.formpack import load_pack

ROOT = "topmostSubform[0]"
DRAFT_URL = "https://www.irs.gov/pub/irs-dft/ftest--dft.pdf"
FINAL_URL = "https://www.irs.gov/pub/irs-prior/ftest--2026.pdf"
PID = "federal/2026/ftest"

COVER = ("Note: The draft you are looking for begins on the next page. Caution: DRAFT—NOT FOR FILING This is an "
         "early release draft of an IRS tax form, instructions, or publication, which the IRS is providing for "
         "your information. Do not file draft forms.").split(". ")
FACE = [(72, 700, "Form TEST (2026) Statement of Synthetic Amounts"),
        (72, 640, "1 Wages, salaries and tips from the synthetic employer"),
        (72, 600, "2 Taxable interest from the synthetic bank"),
        (72, 560, "3 Check here if the synthetic statement is attached"),
        (72, 100, "For Paperwork Reduction Act Notice, see the instructions.")]
BANNERS = [(72, 760, "TREASURY/IRS AND OMB USE ONLY DRAFT"), (300, 740, "DRAFT — DO NOT FILE"),
           (300, 60, "DRAFT — DO NOT FILE")]


def _fields(page: int, *, x1: float = 400, rename: str | None = None, maxlen: int = 9, tooltip: bool = False):
    spec = [
        {"name": f"{ROOT}.Page1[0].f1_1[0]", "kind": "text", "page": page, "x": x1, "y": 636, "maxlen": maxlen,
         "hierarchical": True},
        {"name": f"{ROOT}.Page1[0].{rename or 'f1_2[0]'}", "kind": "text", "page": page, "x": 400, "y": 596,
         "hierarchical": True},
        {"name": f"{ROOT}.Page1[0].c1_1[0]", "kind": "checkbox", "page": page, "x": 400, "y": 556, "on_value": "/1",
         "hierarchical": True},
    ]
    return [s | {"tooltip": s["name"]} for s in spec] if tooltip else spec


def _draft(path: Path, created: str = "4/24/26") -> bytes:
    texts = [(1, 72, 700 - 20 * i, line) for i, line in enumerate(COVER)]
    texts += [(2, x, y, t) for x, y, t in FACE + BANNERS] + [(2, 400, 100, f"Created {created}")]
    make_acroform_pdf(path, _fields(2, tooltip=True), texts=texts, draw_labels=False)
    return path.read_bytes()


def _final(path: Path, *, created: str = "4/24/26", face=FACE, **fields) -> bytes:
    texts = [(1, x, y, t) for x, y, t in face] + [(1, 400, 100, f"Created {created}")]
    make_acroform_pdf(path, _fields(1, **fields), texts=texts, draw_labels=False)
    return path.read_bytes()


PACK = f"""\
# ftest 2026 — a synthetic drafts-first pack (test_repin_final.py). Its header prose stays as written.
form: "TEST"
jurisdiction: federal
tax_year: 2026
source_url: {DRAFT_URL}
pdf_sha256: "DRAFT_SHA"
source_status: draft
draft_created: "4/24/26"
acroform_root: "{ROOT}"
fields:
  - {{ line: "1", field: "Page1[0].f1_1[0]", type: money, maxlen: 9 }}   # a hand-written comment
  - {{ line: "2", field: "Page1[0].f1_2[0]", type: money }}
  - {{ line: "3", field: "Page1[0].c1_1[0]", type: checkbox, on_state: "/1" }}
signature:
  page: 2                                   # PDF page 2 of the draft (page 1 is the IRS cover sheet)
mailing: null
"""
KNOWLEDGE = f"""\
# A hand-written header the re-pin must leave alone.
tax_year: 2026
form_lines:
  ftest.wages:
    line: "1"
    line_source: "draft Created 4/24/26"
    url: "{DRAFT_URL}"
    read: "2026-09-24"
    printed: "1 Wages, salaries and tips from the synthetic employer"
  other.form:   # another form's entry
    line: "9"
    line_source: "draft Created 8/19/26"
    url: "https://www.irs.gov/pub/irs-dft/fother--dft.pdf"
    read: "2026-09-24"
    printed: "9 Some other line of some other form"
sources: []
"""
SELECTION = f"""\
dev:
- family: federal/fother
  pack: federal/2026/fother
  year: 2026
  pdf_sha256: {'ab' * 32}
  scorable: 3
- family: federal/ftest
  pack: {PID}
  year: 2026
  pdf_sha256: DRAFT_SHA
  scorable: 2
"""
ADJUDICATIONS = f"""\
items:
- id: {PID}:p2:{ROOT}.Page1[0].c1_1[0]:w0   # a hand comment
  verdict: pack_right
- id: federal/2026/fother:p2:{ROOT}.Page1[0].c1_1[0]:w0
  verdict: pack_right
"""


@pytest.fixture
def repo(tmp_path: Path):
    """A tmp repo holding one synthetic draft pack, its draft seeded in a tmp blank cache."""
    root, cache = tmp_path / "repo", tmp_path / "cache"
    draft = _draft(tmp_path / "ftest--dft.pdf")
    sha = hashlib.sha256(draft).hexdigest()
    seed_blank(tmp_path / "ftest--dft.pdf", DRAFT_URL, sha, cache_dir=cache)
    for rel, text in ((f"formpacks/{PID}/pack.yaml", PACK), ("knowledge/federal/2026.yaml", KNOWLEDGE),
                      ("knowledge/anchor/selection.yaml", SELECTION),
                      ("knowledge/anchor/adjudications.yaml", ADJUDICATIONS)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text.replace("DRAFT_SHA", sha), encoding="utf-8")
    return root, cache, draft


def _snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.yaml"))}


def _compare(repo, final: bytes):
    root, _cache, draft = repo
    pack = load_pack(root / "formpacks" / PID / "pack.yaml")
    return R.compare("ftest", PID, pack, draft, final, draft_url=DRAFT_URL, final_url=FINAL_URL)


def _main(repo, final_path: Path, *extra: str) -> int:
    root, cache, _draft_bytes = repo
    return R.main(["--year", "2026", "--final", f"ftest={final_path}", *extra], repo=root, cache_dir=cache,
                  regen=False)


# ── the compare, on synthetic blanks ──────────────────────────────────────────


def test_a_final_that_only_lost_the_cover_sheet_and_the_banners_is_identical(repo, tmp_path):
    c = _compare(repo, _final(tmp_path / "final.pdf"))
    assert (c.verdict, c.offset, c.cover_sheet_dropped) == ("identical", 1, True)
    assert (c.draft.pages, c.final.pages, len(c.final.widgets)) == (2, 1, 3)
    assert (c.draft.tooltips, c.final.tooltips) == (3, 0)            # tooltips never enter the verdict
    assert c.banner_words == 16 and c.footer is None and c.words_changed == []
    assert (c.draft.created, c.final.created) == ("4/24/26", "4/24/26")
    assert not (c.added or c.removed or c.changed or c.moved or c.nudged or c.mapped_missing) and c.unmapped == 0
    assert "verdict: identical" in R.report(c) and "cover sheet dropped" in R.report(c)


def test_a_moved_box_is_geometry_moved_and_a_new_footer_date_is_expected(repo, tmp_path):
    c = _compare(repo, _final(tmp_path / "final.pdf", x1=400.75, created="8/18/26"))
    assert c.verdict == "geometry_moved" and c.footer == ("4/24/26", "8/18/26") and c.words_changed == []
    [moved] = c.moved
    assert moved["name"] == f"{ROOT}.Page1[0].f1_1[0]" and moved["page"] == 1
    assert moved["delta"] == [0.75, 0, 0.75, 0] and c.largest_delta == 0.75
    assert "READ" in R.report(c)


def test_an_edge_under_the_move_threshold_is_a_nudge_not_a_move(repo, tmp_path):
    c = _compare(repo, _final(tmp_path / "final.pdf", x1=400.05))
    assert (c.verdict, c.moved, len(c.nudged), c.largest_delta) == ("identical", [], 1, 0.05)
    assert R.RECT_NOISE < 0.05 < R.MOVE_THRESHOLD


@pytest.mark.parametrize("change, finding", [
    ({"rename": "f1_9[0]"}, "added"),                      # a renamed widget: one removed, one added, a mapped one gone
    ({"maxlen": 11}, "changed"),
    ({"face": FACE[:2] + [(72, 600, "2 Tax-exempt interest from the synthetic bank")] + FACE[3:]}, "words_changed"),
])
def test_a_renamed_widget_a_new_maxlen_or_new_words_need_a_remap(repo, tmp_path, change, finding):
    c = _compare(repo, _final(tmp_path / "final.pdf", **change))
    assert c.verdict == "needs_remap" and getattr(c, finding)
    if finding == "added":
        assert c.removed == [f"p2 {ROOT}.Page1[0].f1_2[0]"] and c.mapped_missing == [f"{ROOT}.Page1[0].f1_2[0]"]
    if finding == "words_changed":
        assert c.words_changed == [{"page": 1, "draft": "Taxable", "final": "Tax-exempt"}]


def test_a_page_count_no_cover_sheet_explains_needs_a_remap(repo, tmp_path):
    root, _cache, draft = repo
    writer = PdfWriter(clone_from=PdfReader(str(tmp_path / "ftest--dft.pdf")))
    writer.add_blank_page(612, 792)
    with (tmp_path / "longer.pdf").open("wb") as fh:
        writer.write(fh)
    c = _compare(repo, (tmp_path / "longer.pdf").read_bytes())
    assert c.verdict == "needs_remap" and "does not explain" in c.problems[0]
    # A final that IS the draft (cover sheet and banners still there) is not explained either way.
    same = _compare(repo, draft)
    assert (same.offset, same.cover_sheet_dropped, same.verdict) == (0, False, "needs_remap")
    assert any("still prints a DRAFT banner" in p for p in same.problems)


# ── --write, in a tmp repo ────────────────────────────────────────────────────


def test_write_repins_the_pack_and_every_dependent_file_and_is_idempotent(repo, tmp_path, capsys):
    root, cache, _draft_bytes = repo
    final = _final(tmp_path / "final.pdf")
    sha = hashlib.sha256(final).hexdigest()
    before = _snapshot(root)
    assert _main(repo, tmp_path / "final.pdf") == 0 and _snapshot(root) == before      # the compare writes nothing
    assert _main(repo, tmp_path / "final.pdf", "--write", "--date", "2026-12-01") == 0
    out = capsys.readouterr().out
    assert "anchor_benchmark.py --test" in out and "anchor_benchmark.py --finalize" in out   # printed, never run

    pack = load_pack(root / "formpacks" / PID / "pack.yaml")
    assert (pack.source_url, pack.pdf_sha256, pack.source_status, pack.draft_created) == (FINAL_URL, sha, "final", None)
    assert pack.signature.page == 1                                    # the cover sheet is gone
    text = (root / "formpacks" / PID / "pack.yaml").read_text()
    assert text.startswith("# RE-PINNED TO THE IRS FINAL 2026-12-01, verdict identical (scripts/repin_final.py; ")
    assert "# ftest 2026 — a synthetic drafts-first pack" in text and "# a hand-written comment" in text
    assert len([line for line in text.splitlines() if "RE-PINNED" in line]) == 1
    assert cached_blank_path(FINAL_URL, sha, cache_dir=cache) is not None            # seeded for the tools

    selection = yaml.safe_load((root / "knowledge/anchor/selection.yaml").read_text())["dev"]
    assert [row["pdf_sha256"] for row in selection] == ["ab" * 32, sha]
    adjudications = (root / "knowledge/anchor/adjudications.yaml").read_text()
    assert f"- id: {PID}:p1:{ROOT}.Page1[0].c1_1[0]:w0   # a hand comment" in adjudications
    assert "- id: federal/2026/fother:p2:" in adjudications                       # another pack's id stays
    knowledge = (root / "knowledge/federal/2026.yaml").read_text()
    lines = yaml.safe_load(knowledge)["form_lines"]
    assert (lines["ftest.wages"]["line_source"], lines["ftest.wages"]["url"], lines["ftest.wages"]["read"]) == (
        "final", FINAL_URL, "2026-12-01")
    assert lines["other.form"]["line_source"] == "draft Created 8/19/26"
    assert knowledge.startswith("# A hand-written header") and "# another form's entry" in knowledge

    [row] = R.load_ledger(root).values()
    assert row == {
        "pack": PID, "stem": "ftest", "draft_url": DRAFT_URL, "draft_sha256": before[f"formpacks/{PID}/pack.yaml"]
        .split('pdf_sha256: "')[1][:64], "draft_created": "4/24/26", "draft_pages": 2, "final_url": FINAL_URL,
        "final_sha256": sha, "final_posted": row["final_posted"], "final_created": "4/24/26", "pages": 1,
        "widgets": 3, "unmapped": 0, "cover_sheet_dropped": True, "rects_moved": 0, "largest_rect_delta": 0.0,
        "words_changed": 0, "exceptions_cleared": 0, "verdict": "identical", "repinned": "2026-12-01"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["final_posted"])

    after = _snapshot(root)
    assert _main(repo, tmp_path / "final.pdf", "--write", "--date", "2027-01-15") == 0   # a second --write, later
    assert _snapshot(root) == after
    assert "wrote nothing (already re-pinned)" in capsys.readouterr().out


def test_write_refuses_a_final_with_a_renamed_widget_and_edits_nothing(repo, tmp_path, capsys):
    """The task's synthetic case: one widget of the final renamed with pypdf."""
    root, cache, _draft_bytes = repo
    _final(tmp_path / "final.pdf")
    writer = PdfWriter(clone_from=PdfReader(str(tmp_path / "final.pdf")))
    for annot in writer.pages[0]["/Annots"]:
        parent = annot.get_object()["/Parent"].get_object()
        if parent.get("/T") == "f1_2[0]":
            parent[NameObject("/T")] = TextStringObject("f1_2_renamed[0]")
    with (tmp_path / "renamed.pdf").open("wb") as fh:
        writer.write(fh)
    c = _compare(repo, (tmp_path / "renamed.pdf").read_bytes())
    assert c.verdict == "needs_remap"
    assert c.removed == [f"p2 {ROOT}.Page1[0].f1_2[0]"] and c.added == [f"p1 {ROOT}.Page1[0].f1_2_renamed[0]"]
    before = _snapshot(root)
    assert _main(repo, tmp_path / "renamed.pdf", "--write") == 1
    assert _snapshot(root) == before and not (root / R.LEDGER).exists()
    assert "--write refused, nothing edited" in capsys.readouterr().err
    assert cached_blank_path(FINAL_URL, c.final.sha256, cache_dir=cache) is None


def test_write_stops_when_a_form_lines_caption_is_not_verbatim_on_the_final(repo, tmp_path, capsys):
    root, _cache, _draft_bytes = repo
    path = root / "knowledge/federal/2026.yaml"
    path.write_text(path.read_text().replace("tips from the synthetic employer", "tips from your employer"))
    _final(tmp_path / "final.pdf")
    before = _snapshot(root)
    assert _main(repo, tmp_path / "final.pdf", "--write") == 1
    err = capsys.readouterr().err
    assert "ftest.wages" in err and "not VERBATIM on the final" in err
    assert _snapshot(root) == before


def test_a_final_pack_without_a_ledger_row_or_with_another_final_is_refused(repo, tmp_path, capsys):
    root, _cache, _draft_bytes = repo
    _final(tmp_path / "final.pdf")
    assert _main(repo, tmp_path / "final.pdf", "--write") == 0
    capsys.readouterr()
    _final(tmp_path / "revised.pdf", x1=420)
    assert _main(repo, tmp_path / "revised.pdf") == 1
    assert "the IRS revised a final" in capsys.readouterr().err
    (root / R.LEDGER).unlink()
    assert _main(repo, tmp_path / "final.pdf") == 1
    assert "has no row for it" in capsys.readouterr().err


def test_the_ledger_refuses_a_row_with_a_missing_key(tmp_path):
    (tmp_path / R.LEDGER).parent.mkdir(parents=True)
    (tmp_path / R.LEDGER).write_text("repins:\n- pack: federal/2026/x\n  stem: fx\n")
    with pytest.raises(R.RepinError, match="must carry exactly"):
        R.load_ledger(tmp_path)


# ── the six real pairs, from the blank cache ──────────────────────────────────

FIRST_SIX = ("sched_c", "sched_se", "f2555", "f8843", "sched_8812", "f8606")


def _cached_pair(key: str) -> tuple[dict, bytes, bytes]:
    row = ledger()[f"federal/2026/{key}"]
    draft = cached_blank_path(row["draft_url"], row["draft_sha256"])
    final = cached_blank_path(row["final_url"], row["final_sha256"])
    if draft is None or final is None:
        pytest.skip(f"{key}: its draft or final is not in the blank cache (TAXFILL_BLANKS_CACHE)")
    return row, draft.read_bytes(), final.read_bytes()


@pytest.mark.parametrize("key", FIRST_SIX)
def test_the_compare_reproduces_the_ledger_row_of_each_hand_repinned_pack(key: str):
    row, draft, final = _cached_pair(key)
    pack = load_pack(REPO / "formpacks" / "federal" / "2026" / key / "pack.yaml")
    c = R.compare(row["stem"], row["pack"], pack, draft, final, draft_url=row["draft_url"], final_url=row["final_url"])
    assert c.ledger_row(row["repinned"], row["exceptions_cleared"]) == row      # the ledger was never typed
    assert c.words_changed == [] and c.banner_words >= 16 and c.final.tooltips == 0 and c.final.xfa
    assert c.draft.tooltips == len(c.draft.widgets)
    if key == "sched_8812":
        assert (c.verdict, c.cover_sheet_dropped, c.footer) == ("geometry_moved", False, ("4/24/26", "8/18/26"))
        kinds = {w.key: w.ft for w in c.final.widgets}
        assert len(c.moved) == 35 and {kinds[(m["name"], m["index"])] for m in c.moved} == {"/Tx"}
        assert sum(1 for ft in kinds.values() if ft == "/Btn") == 6               # the six checkboxes stayed
    else:
        assert (c.verdict, c.cover_sheet_dropped, c.moved, c.footer) == ("identical", True, [], None)


@pytest.mark.parametrize("key", FIRST_SIX)
def test_write_from_the_draft_state_reproduces_todays_pins_and_is_idempotent(key: str, tmp_path: Path):
    """Each hand re-pin, replayed: the repo files a re-pin edits are copied to tmp_path and put back in their draft
    state from the ledger row; --write with the cached final must restore exactly today's pins, then change nothing."""
    row, _draft, _final_bytes = _cached_pair(key)
    final_path = cached_blank_path(row["final_url"], row["final_sha256"])
    root = tmp_path / "repo"
    shutil.copytree(REPO / "formpacks" / "federal" / "2026", root / "formpacks" / "federal" / "2026")
    for rel in ("knowledge/federal/2026.yaml", "knowledge/anchor/selection.yaml", "knowledge/anchor/adjudications.yaml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    committed = _snapshot(root)
    up = 1 if row["cover_sheet_dropped"] else 0

    pack_path = root / "formpacks" / "federal" / "2026" / key / "pack.yaml"
    text = pack_path.read_text()
    text = text.replace(f"source_url: {row['final_url']}", f"source_url: {row['draft_url']}")
    text = text.replace(row["final_sha256"], row["draft_sha256"])
    text = text.replace("\nsource_status: final\n", f"\nsource_status: draft\ndraft_created: \"{row['draft_created']}\"\n")
    text = re.sub(r"(?m)^(signature:[^\n]*\n?[ \t]*\{?[ \t]*page:[ \t]*)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + up}", text)
    pack_path.write_text(text)
    assert load_pack(pack_path).source_status == "draft"
    for rel in ("knowledge/anchor/selection.yaml", "knowledge/anchor/adjudications.yaml", "knowledge/federal/2026.yaml"):
        text = (root / rel).read_text().replace(row["final_sha256"], row["draft_sha256"])
        text = re.sub(rf"\b{re.escape(row['pack'])}:p(\d+):", lambda m: f"{row['pack']}:p{int(m.group(1)) + up}:", text)
        text = text.replace(f'    line_source: final\n    url: "{row["final_url"]}"\n    read: "{row["repinned"]}"',
                            f'    line_source: "draft Created {row["draft_created"]}"\n    url: "{row["draft_url"]}"\n'
                            '    read: "2026-09-24"')
        (root / rel).write_text(text)
    others = [r for r in ledger().values() if r["pack"] != row["pack"]]
    (root / R.LEDGER).write_text(R.ledger_text(R.LEDGER_HEADER, others))
    assert _snapshot(root) != committed

    argv = ["--year", "2026", "--final", f"{row['stem']}={final_path}", "--write", "--date", row["repinned"]]
    assert R.main(argv, repo=root, regen=False) == 0
    after = _snapshot(root)
    ledger_rel = R.LEDGER.as_posix()
    pack_rel = pack_path.relative_to(root).as_posix()
    for rel, was in committed.items():
        if rel == pack_rel:                       # the same pack but for the one header line the script adds
            assert _sans_page_comment(after[rel].split("\n", 1)[1]) == _sans_page_comment(was)
        elif rel != ledger_rel:
            assert after[rel] == was, rel
    repinned = load_pack(pack_path)
    today = load_pack(REPO / "formpacks" / "federal" / "2026" / key / "pack.yaml")
    assert repinned == today
    assert R.load_ledger(root)[row["pack"]] == row | {"exceptions_cleared": 0}   # the gate is not run in a tmp repo
    assert R.main([*argv[:-1], "2027-02-02"], repo=root, regen=False) == 0
    assert _snapshot(root) == after


def _sans_page_comment(text: str) -> str:
    """A pack's text without the comment beside signature.page: the hand re-pins wrote their own there."""
    return re.sub(r"(?m)^(signature:[ \t]*\{[^}\n]*\}|[ \t]+page:[ \t]*\d+)[ \t]*#[^\n]*$", r"\1", text)
