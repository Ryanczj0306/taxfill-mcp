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
from pypdf.generic import ArrayObject, DecodedStreamObject, FloatObject, NameObject, TextStringObject

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


def _fields(page: int, *, x1: float = 400, y1: float = 636, yc: float = 556, swap: bool = False,
            rename: str | None = None, maxlen: int = 9, tooltip: bool = False):
    """Two text boxes (144 x 18 pt, rows 40 pt apart) and a 14 pt checkbox; ``swap``: the two text boxes trade
    rectangles."""
    spec = [
        {"name": f"{ROOT}.Page1[0].f1_1[0]", "kind": "text", "page": page, "x": x1, "y": 596 if swap else y1,
         "maxlen": maxlen, "hierarchical": True},
        {"name": f"{ROOT}.Page1[0].{rename or 'f1_2[0]'}", "kind": "text", "page": page, "x": 400,
         "y": 636 if swap else 596, "hierarchical": True},
        {"name": f"{ROOT}.Page1[0].c1_1[0]", "kind": "checkbox", "page": page, "x": 400, "y": yc, "on_value": "/1",
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


@pytest.mark.parametrize("change, out_of_place", [
    ({"y1": 636 - 18}, ["f1_1[0]"]),                       # one box height down: on the next row of an IRS face
    ({"y1": 636 - 6}, ["f1_1[0]"]),                        # a third of its height: 67% left, under three quarters
    ({"y1": 636 + 40}, ["f1_1[0]"]),                       # a whole synthetic row up
    ({"x1": 400 + 94.6}, ["f1_1[0]"]),                     # into another column
    ({"swap": True}, ["f1_1[0]", "f1_2[0]"]),              # two boxes trade rectangles: same names, wrong lines
    ({"yc": 556 - 14}, ["c1_1[0]"]),                       # a checkbox one box lower
])
def test_a_box_that_left_its_draft_rectangle_needs_a_remap_and_no_acknowledgement_writes_it(
        repo, tmp_path, capsys, change, out_of_place):
    root, cache, _draft_bytes = repo
    c = _compare(repo, _final(tmp_path / "final.pdf", **change))
    assert c.verdict == "needs_remap" and len(c.moved) == len(c.displaced) == len(out_of_place)
    assert [row.split(":")[0].rsplit(".", 1)[1] for row in c.displaced] == out_of_place
    assert not (c.added or c.removed or c.changed or c.words_changed or c.mapped_missing or c.problems)
    assert R.report(c).count("OUT OF PLACE: ") == len(out_of_place) and c.as_json()["rects_displaced"] == c.displaced
    before = _snapshot(root)
    assert _main(repo, tmp_path / "final.pdf", "--write", "--moved-read", "ftest") == 1
    assert "--write refused, nothing edited" in capsys.readouterr().err
    assert _snapshot(root) == before and not (root / R.LEDGER).exists()
    assert cached_blank_path(FINAL_URL, c.final.sha256, cache_dir=cache) is None


def test_a_box_moved_inside_its_draft_rectangle_is_geometry_moved_up_to_a_quarter_of_its_extent(repo, tmp_path):
    c = _compare(repo, _final(tmp_path / "final.pdf", y1=636 - 4, x1=400 + 30))        # 78% and 79% shared
    assert (c.verdict, len(c.moved), c.displaced) == ("geometry_moved", 1, [])
    assert R._shared((0, 0, 100, 10), (25, 0, 125, 10)) == (R.KEEP_SHARE, 1.0)       # the bound itself is in place
    assert R._shared((0, 0, 100, 10), (0, 10, 100, 20)) == (1.0, 0.0)                # touching rows share nothing
    assert R._shared((0, 0, 100, 10), (0, -15, 100, 25)) == (1.0, 0.25)              # a box grown over three rows
    assert 0.5 < R.KEEP_SHARE <= 0.9          # above one half (no two boxes can swap), below Schedule 8812's 0.908


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


def test_a_geometry_moved_write_needs_the_operators_moved_read(repo, tmp_path, capsys, monkeypatch):
    """A moved form is written only on --moved-read STEM: never unacknowledged, never in the call that renders,
    never in the default batch."""
    root, cache, _draft_bytes = repo
    final = _final(tmp_path / "final.pdf", x1=400.75)
    sha = hashlib.sha256(final).hexdigest()
    before = _snapshot(root)

    def refused(code: int, needle: str) -> None:
        assert code == 1 and needle in capsys.readouterr().err
        assert _snapshot(root) == before and not (root / R.LEDGER).exists()
        assert cached_blank_path(FINAL_URL, sha, cache_dir=cache) is None

    refused(_main(repo, tmp_path / "final.pdf", "--write"), "then --write --moved-read ftest")
    refused(_main(repo, tmp_path / "final.pdf", "--write", "--moved-read", "ftest", "--render", str(tmp_path / "png")),
            "a render this call makes has not been read")
    assert not (tmp_path / "png").exists()                      # refused before a page was rendered
    refused(_main(repo, tmp_path / "final.pdf", "--moved-read", "ftest"), "--moved-read is said with --write")
    refused(_main(repo, tmp_path / "final.pdf", "--write", "--moved-read", "fother"), "then --write --moved-read ftest")

    monkeypatch.setattr(R, "posted_stems", lambda year, say=print: ["ftest"])        # the default batch: no stem named
    monkeypatch.setattr(R, "fetch_twice", lambda url: final)
    refused(R.main(["--year", "2026", "--write"], repo=root, cache_dir=cache, regen=False),
            "then --write --moved-read ftest")
    refused(R.main(["--year", "2026", "--write", "--moved-read", "ftest"], repo=root, cache_dir=cache, regen=False),
            "the default batch never writes a geometry_moved form")

    assert _main(repo, tmp_path / "final.pdf", "--write", "--moved-read", "ftest", "--date", "2026-12-01") == 0
    assert "written on --moved-read ftest" in capsys.readouterr().out
    [row] = R.load_ledger(root).values()
    assert (row["verdict"], row["rects_moved"], row["largest_rect_delta"]) == ("geometry_moved", 1, 0.75)
    assert load_pack(root / "formpacks" / PID / "pack.yaml").pdf_sha256 == sha
    assert "(the render was read)" not in (root / R.LEDGER).read_text()   # the ledger cannot know; it says who said so
    assert "--moved-read STEM" in R.LEDGER_HEADER and "--moved-read STEM" in (REPO / R.LEDGER).read_text()


def test_moved_read_for_a_form_that_did_not_move_is_refused(repo, tmp_path, capsys):
    root, _cache, _draft_bytes = repo
    _final(tmp_path / "final.pdf")
    before = _snapshot(root)
    assert _main(repo, tmp_path / "final.pdf", "--write", "--moved-read", "ftest") == 1
    assert "not a geometry_moved form of this batch" in capsys.readouterr().err and _snapshot(root) == before


def test_write_is_refused_when_the_final_brings_a_new_label_adjacency_disagreement(repo, tmp_path, capsys, monkeypatch):
    """Whatever the verdict: the print can move under boxes that stayed, and the gate's preview sees it BEFORE the
    write. (The preview itself runs on real packs only; here it is replaced, the cached layer runs the real one.)"""
    root, cache, _draft_bytes = repo
    final = _final(tmp_path / "final.pdf")
    c = _compare(repo, final)
    assert c.verdict == "identical" and R.write_refusals([c], []) == []
    c.unexcused = [f"{PID}:p1:{ROOT}.Page1[0].f1_2[0]:w0 anchor=3 keys=['2']"]
    [reason] = R.write_refusals([c], [])
    assert "1 label-adjacency disagreement(s) the draft did not have" in reason and "anchor=3 keys=['2']" in reason
    with pytest.raises(R.RepinError, match="new label-adjacency disagreement"):
        R.plan_write(c, Path("formpacks") / PID / "pack.yaml", final, R.Tree(root), date="2026-12-01")

    monkeypatch.setattr(R, "REPO", root)                       # main previews the gate only in its own repo
    monkeypatch.setattr(R, "label_adjacency_preview",
                        lambda c, pack, final: (setattr(c, "clearing", []), setattr(c, "unexcused", ["x anchor=3"])))
    before = _snapshot(root)
    assert R.main(["--year", "2026", "--final", f"ftest={tmp_path / 'final.pdf'}", "--write"], repo=root,
                  cache_dir=cache) == 1
    assert "label-adjacency disagreement(s) the draft did not have (x anchor=3)" in capsys.readouterr().err
    assert _snapshot(root) == before and not (root / R.LEDGER).exists()
    assert cached_blank_path(FINAL_URL, c.final.sha256, cache_dir=cache) is None


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


def test_a_batch_is_written_whole_or_not_at_all(repo, tmp_path, capsys):
    """Two finals in one --write: the second form's caption is not on its final, so the first is not written either."""
    root, cache, draft = repo
    seed_blank(tmp_path / "ftest--dft.pdf", "https://www.irs.gov/pub/irs-dft/fother--dft.pdf",
               hashlib.sha256(draft).hexdigest(), cache_dir=cache)
    other = root / "formpacks" / "federal" / "2026" / "fother" / "pack.yaml"
    other.parent.mkdir()
    other.write_text((root / "formpacks" / PID / "pack.yaml").read_text().replace("ftest--dft", "fother--dft"))
    _final(tmp_path / "final.pdf")
    before = _snapshot(root)
    argv = ["--year", "2026", "--final", f"ftest={tmp_path / 'final.pdf'}", "--final", f"fother={tmp_path / 'final.pdf'}"]
    assert R.main([*argv, "--write"], repo=root, cache_dir=cache, regen=False) == 1
    assert "other.form" in capsys.readouterr().err and _snapshot(root) == before
    # With the caption corrected to what the face prints, the same batch is written, both packs.
    path = root / "knowledge/federal/2026.yaml"
    path.write_text(path.read_text().replace('line: "9"', 'line: "2"').replace(
        "9 Some other line of some other form", "2 Taxable interest from the synthetic bank"))
    assert R.main([*argv, "--write"], repo=root, cache_dir=cache, regen=False) == 0
    assert set(R.load_ledger(root)) == {PID, "federal/2026/fother"}
    assert {load_pack(p).source_status for p in (other, root / "formpacks" / PID / "pack.yaml")} == {"final"}


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

    argv = ["--year", "2026", "--final", f"{row['stem']}={final_path}", "--write"]
    if row["verdict"] == "geometry_moved":                    # Schedule 8812: refused until its render is said read
        before = _snapshot(root)
        assert R.main(argv, repo=root, regen=False) == 1 and _snapshot(root) == before
        argv += ["--moved-read", row["stem"]]
    argv += ["--date", row["repinned"]]
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


# ── adversarial finals cut from the real ones (the verifier's cases, 2026-11-13) ──────────────────────────────


def _edited(final: bytes, edit, tmp_path: Path) -> bytes:
    """The real final with ``edit(writer, find)`` applied; ``find(suffix)`` is the widget whose name ends with it."""
    import io

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(final)))

    def find(suffix: str):
        for page in writer.pages:
            for ref in page.get("/Annots", []):
                annot = ref.get_object()
                if annot.get("/Subtype") == "/Widget" and R._qualified_name(annot).endswith(suffix):
                    return annot
        raise KeyError(suffix)

    edit(writer, find)
    with (tmp_path / "edited.pdf").open("wb") as fh:
        writer.write(fh)
    return (tmp_path / "edited.pdf").read_bytes()


def _rect(annot) -> list[float]:
    return [float(v) for v in annot["/Rect"]]


def _set_rect(annot, rect) -> None:
    annot[NameObject("/Rect")] = ArrayObject([FloatObject(v) for v in rect])


def _shift(suffix: str, dx: float, dy: float):
    def edit(_writer, find) -> None:
        x0, y0, x1, y1 = _rect(find(suffix))
        _set_rect(find(suffix), [x0 + dx, y0 + dy, x1 + dx, y1 + dy])
    return edit


def _swap(first: str, second: str):
    def edit(_writer, find) -> None:
        a, b = _rect(find(first)), _rect(find(second))
        _set_rect(find(first), b)
        _set_rect(find(second), a)
    return edit


@pytest.mark.parametrize("key, edit, out_of_place", [
    ("f8606", _shift("Page1[0].f1_12[0]", 0, -12), 1),                    # line 2's box on line 3's row
    ("f8606", _shift("Page1[0].f1_12[0]", 0, -24), 1),
    ("f8606", _shift("Page1[0].f1_12[0]", 0, -3), 1),                     # a quarter of a row is already too far
    ("f8606", _shift("Page1[0].f1_19[0]", 94.6, 0), 1),                   # into the outer amount column
    ("f8606", _swap("Page1[0].f1_12[0]", "Page1[0].f1_13[0]"), 2),        # two rows trade boxes
    ("f8606", _swap("Page1[0].f1_20[0]", "Page1[0].f1_21[0]"), 2),        # two boxes of one row trade places
    ("sched_8812", _swap("Page1[0].c1_1[0]", "Page1[0].c1_1[1]"), 2),     # two checkboxes, among the 35 real moves
], ids=["row_down", "two_rows_down", "quarter_row", "other_column", "rows_swapped", "same_row_swapped",
        "checkboxes_swapped"])
def test_a_real_final_with_a_box_on_another_line_needs_a_remap(key: str, edit, out_of_place: int, tmp_path: Path):
    row, draft, final = _cached_pair(key)
    pack = load_pack(REPO / "formpacks" / "federal" / "2026" / key / "pack.yaml")
    c = R.compare(row["stem"], row["pack"], pack, draft, _edited(final, edit, tmp_path), draft_url=row["draft_url"],
                  final_url=row["final_url"])
    assert c.verdict == "needs_remap" and len(c.displaced) == out_of_place
    assert len(c.moved) == out_of_place + row["rects_moved"]              # Schedule 8812's own 35 are still in place
    assert not (c.added or c.removed or c.changed or c.words_changed or c.mapped_missing or c.problems)
    assert f"{row['stem']}: verdict needs_remap, a re-map by hand" in R.write_refusals([c], [row["stem"]])


def test_print_shifted_under_unmoved_boxes_is_identical_and_still_refused_by_the_label_adjacency_preview(tmp_path):
    """Every printed mark of Form 8606's page 1 moved 12 pt down, no widget touched: the compare reads words, not
    their places, so the verdict stays identical; the gate's preview lists the boxes that left their lines and
    --write stops on it."""
    row, draft, final = _cached_pair("f8606")
    pack = load_pack(REPO / "formpacks" / "federal" / "2026" / "f8606" / "pack.yaml")

    def edit(writer, _find) -> None:
        page = writer.pages[0]
        stream = DecodedStreamObject()
        stream.set_data(b"q 1 0 0 1 0 -12 cm\n" + page.get_contents().get_data() + b"\nQ\n")
        page[NameObject("/Contents")] = writer._add_object(stream)

    shifted = _edited(final, edit, tmp_path)
    c = R.compare(row["stem"], row["pack"], pack, draft, shifted, draft_url=row["draft_url"], final_url=row["final_url"])
    assert c.verdict == "identical" and c.unexcused is None
    R.label_adjacency_preview(c, pack, shifted)
    assert len(c.unexcused) >= 4 and all(item.startswith("federal/2026/f8606:p1:") for item in c.unexcused)
    [reason] = R.write_refusals([c], [])
    assert "label-adjacency disagreement(s) the draft did not have" in reason
    real = R.compare(row["stem"], row["pack"], pack, draft, final, draft_url=row["draft_url"], final_url=row["final_url"])
    R.label_adjacency_preview(real, pack, final)
    assert real.unexcused == [] and R.write_refusals([real], []) == []     # the real final passes the same gate
