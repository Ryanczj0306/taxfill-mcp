"""Phase K JK10 (2026-10-24): the label-adjacency gate — every numbered key equals the line printed beside its widget.

scripts/label_adjacency.py runs the pack-blind anchor (taxfill_core.anchor) on each shipped pack's own blank and
compares the line it reads beside every widget with the pack's numbered key, after the column conventions of
formpacks/column_keys.yaml. A disagreement fails unless formpacks/label_adjacency_exceptions.yaml lists it with its
adjudicated reason. P-031 (AL Form 40 2023 one line high) and P-032 (ME 1040ME 2023 lines 21-23 rotated) are the two
base-pack mis-binds this exists for: both are caught on their historical maps, and their dedicated gutter reads live
here as the network half of test_al40_line_designators.py and test_me1040_lines_21_23.py (whose offline pinned maps
stay there).

Fixer round 2 (Phase K JK10, 2026-10-24): key families in other shapes are declared in formpacks/key_shapes.yaml
(each checked on its packs' faces), and formpacks/label_adjacency_coverage.yaml holds every pack's checked and
line-bearing key counts — the gate fails on a regression or a stale row, and names every pack below the floor.

Fixer round 3 (Phase K JK10, 2026-10-24): the ledger's denominator is not circular — a key is line-bearing when it
carries a line-like token (label_adjacency.line_like) outside the ledger's short not_lines list, or when a rule maps
it — so a pack keyed mostly in an undeclared shape falls below the floor instead of reporting "OK 26/26".

Fixer round 4 (Phase K JK10, 2026-10-24): a DARK key family (5+ undeclared keys, or 5+ line-bearing keys none of
which is checked) puts its pack below the floor whatever the fraction, so a whole schedule left unmapped (OH Schedule
of Business Income, MT 2023's EHRC / UPINT) can no longer hide a planted 3-cycle behind an OK verdict.

Fixer round 5 (Phase K JK10, 2026-10-24): THE DECLARE-ME RULE — an undeclared key the anchor reads a printed line
beside puts its pack below the floor whatever its family's size (AZ 140's seven-key charitable worksheet, each key its
own round-4 family, and MT 2023's four LTC-rent rows had reported OK with planted 3-cycles passing); families are
built by prefix (the key up to its first line token); the ledger names the declare families and counts the keys the
anchor reads no line beside (``unread``, the residue no line check sees).

Fixer round 6 (Phase K JK10, 2026-10-24): what the gate cannot see is one counted list — (a) a same-row column swap
(``same_row``), (b) a box the anchor reads no line beside (``unread``), (c) a swap between sections that print the
same line number (``cross_section``) and (d) a descriptive key beside whose box the anchor reads a line
(``descriptive``) — each exact per pack in the ledger, a stale count failing the gate; MT Form 2 2023's lettered
exemption rows are no longer a not_lines family, and the pack reads PARTIAL with the reason.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def _load():
    if "label_adjacency" in sys.modules:
        return sys.modules["label_adjacency"]
    spec = importlib.util.spec_from_file_location("label_adjacency", REPO / "scripts" / "label_adjacency.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["label_adjacency"] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()
A = L.A
PACK_IDS = L.all_pack_ids()
CONVENTIONS = L.load_conventions()


# ── offline: the key rule, the conventions and the exceptions table ─────────


@pytest.mark.parametrize(("pack", "key", "line", "via"), [
    # Delaware PIT-RES: "Na"/"Nb" are line N, Column A (spouse) / Column B
    ("states/de/2025/pit_res", "1a", "1", "de-pit-res-2024"),
    ("states/de/2025/pit_res", "59b", "59", "de-pit-res-2024"),
    ("states/de/2025/pit_res", "26b", "26", "de-pit-res-2024"),
    ("states/de/2023/pit_res", "26b", "26b", None),          # 2023 prints a real sub-line 26b
    ("states/de/2025/pit_res", "8a", "8a", None),            # so do both years' line 8a / 8b
    ("states/de/2025/pit_res", "27a", "27a", None),
    ("states/de/2023/pit_non", "7a", "7a", None),
    ("states/de/2023/pit_non", "29b", "29", "de-pit-non-2023"),
    # Form 8962's Part II monthly columns and Part V's alternative entries; 8a is a printed sub-line
    ("federal/2025/f8962", "11f", "11", "f8962-part2-columns"),
    ("federal/2026/f8962", "23a", "23", "f8962-part2-columns"),
    ("federal/2025/f8962", "36d", "36", "f8962-part5-columns"),
    ("federal/2025/f8962", "8a", "8a", None),
    # Schedule NEC's rate columns; line 10's 10a/10b are printed sub-lines; 1a.a is a box of line 1a (fixer round 3)
    ("federal/2025/sched_nec", "3e", "3", "sched-nec-rate-columns"),
    ("federal/2025/sched_nec", "10a", "10a", None),
    ("federal/2025/sched_nec", "1a.a", "1a", "line-boxes"),
    # a convention covers only its own packs
    ("states/al/2025/al40", "5a", "5a", None),
    ("states/de/2025/pit_res", "line_21", "21", None),
    # Phase K JK10 (2026-10-24), fixer round 2: the declared key shapes of formpacks/key_shapes.yaml
    ("states/ny/2025/it203", "1_wages_fed", "1", "ny-it203-line-boxes"),
    ("states/ny/2023/it203", "52a_subtract_52_from_51", "52a", "ny-it203-line-boxes"),
    ("states/ny/2025/it203", "dep0_ssn", None, None),
    ("states/nj/2025/nj1040", "line19_d01", "19", "nj1040-amount-digit-cells"),
    ("states/nj/2025/nj1040", "13_total_exemption_amount_d07", "13", "nj1040-amount-digit-cells"),
    ("states/nj/2025/nj1040", "line44_credit_other_jurisdictions_code_d1", "44", "line-boxes"),  # line 44's code
    ("states/ca/2025/sched_ca_540nr", "A1a_A", "1a", "ca-sched-ca-540nr-columns"),
    ("states/ca/2025/sched_ca_540nr", "C19b_ssn1", None, None),
    ("states/ca/2025/sched_ca_540", "II5a_B", "5a", "ca-sched-ca-540-columns"),
    ("federal/2025/f2210", "ai.1.d", "1", "f2210-installment-columns"),
    ("federal/2025/sched_e", "22.b", "22", "sched-e-property-columns"),
    ("federal/2025/sched_e", "34b.c", "34b", "line-boxes"),       # Part III: not a property column, a box of 34b
    ("states/oh/2025/it1040_oh", "schedC_12", "12", "oh-it1040-schedule-lines"),
    ("states/ga/2023/ga500", "s3.10a", "10a", "ga500-schedule-lines"),
    ("states/ny/2025/it201", "1_wages_fed", "1", "line-boxes"),   # NY's shape lists IT-203 only; line-boxes IT-201
    ("states/ny/2025/it201", "dep0_ssn", None, None),
    # fixer round 3: the shapes the non-circular denominator called for
    ("states/ms/2025/f80105", "13.a", "13a", "ms-80-105-columns"),    # the face labels the box "13A"
    ("states/ky/2025/form740", "5_b", "5", "ky-740-columns"),
    ("states/ar/2025/ar1000f", "18b.b", "18b", "ar-1000-columns"),
    ("states/mt/2023/form2", "sub.3.b", "3", "mt-form2-2023-columns"),
    ("states/mt/2023/form2", "16a.a", None, None),   # exemption row a (a letter-only line no shape expresses)
    ("states/mo/2025/mo1040", "line27Y", "27y", "mo-1040-yourself-spouse"),
    ("states/wv/2024/it140", "sch_m.29a", "29", "wv-it140-schedule-m-columns"),
    ("states/ia/2025/ia1040", "s1.1b.cents", "1", "ia-1040-schedule-1-columns"),
    ("federal/2025/f1040", "4c.rollover", "4c", "line-boxes"),
    ("federal/2025/f8843", "1.cont2", None, None),                     # a continuation row: not_lines
])
def test_a_key_claims_its_line_after_the_column_conventions(pack, key, line, via):
    assert L.claim_line(pack, key, CONVENTIONS) == (line, via)


def test_line_ranges_parse_and_refuse_nonsense():
    assert L.parse_lines("1-3, 5, 7-8") == {1, 2, 3, 5, 7, 8}
    for bad in ("", "3-1", "a-b", "0-2", "1-2-3"):
        with pytest.raises(ValueError):
            L.parse_lines(bad)


def test_every_convention_names_shipped_packs_cites_a_header_and_maps_a_key():
    assert {c.id for c in CONVENTIONS} >= {"de-pit-res-2023", "de-pit-res-2024", "de-pit-non-2023",
                                          "f8962-part2-columns", "sched-nec-rate-columns"}
    from taxfill_core.schemas.formpack import load_pack

    for conv in CONVENTIONS:
        assert conv.header and all(h.strip() for h in conv.header), conv.id
        for pid in conv.packs:
            assert pid in PACK_IDS, f"{conv.id}: {pid} is not a shipped pack"
            keys = [f.line for f in load_pack(REPO / "formpacks" / pid / "pack.yaml").fields]
            assert any(conv.covers(pid, k) for k in keys), f"{conv.id} maps no key of {pid}"


def test_two_conventions_never_cover_the_same_key():
    for pid in PACK_IDS:
        mine = [c for c in CONVENTIONS if pid in c.packs]
        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                assert not (a.lines & b.lines and set(a.letters) & set(b.letters)), (pid, a.id, b.id)


def test_the_exceptions_table_names_real_widgets_of_shipped_packs_by_their_key_lines():
    """Phase K JK10 (2026-10-24): each row names one widget the pack binds under keys of exactly the row's lines."""
    exceptions = L.load_exceptions()
    # 128 anchor misreads + 3 al40 carry-forwards; round 2: 5 misreads + 3 NJ mirror twins the key shapes brought in;
    # round 3: 312 widgets the new shapes brought in (the r3-* families; one more was a pack defect, re-keyed);
    # round 4: 9 anchor misreads the round-4 shapes brought in (RI Schedule E 4b/4c, CA 540NR 19b); round 5: 5 the
    # declare-me rule's shapes brought in (GA Schedule 4 specify boxes, AZ 140NR's Savings box beside code "98");
    # Phase K JK15b (2026-10-25): 63 rows cleared themselves when the anchor (jk15-v6) read the key's own line (a
    # sub-letter row under a joined head: f8843 3b/4b, Form 1040 35d, Schedule 1 2b/19b/19c, Form 2555 12b/15b ...)
    assert len(exceptions) == 402
    from taxfill_core.schemas.formpack import load_pack

    packs: dict[str, object] = {}
    for exc in exceptions.values():
        assert exc.pack in PACK_IDS, f"{exc.id}: {exc.pack} is not a shipped pack"
        pack = packs.setdefault(exc.pack, load_pack(REPO / "formpacks" / exc.pack / "pack.yaml"))
        root = pack.acroform_root or ""
        lines = {L.claim_line(exc.pack, f.line, CONVENTIONS)[0] for f in pack.fields
                 if (f"{root}.{f.field}" if root else f.field) == exc.field} - {None}
        assert lines == set(exc.lines), f"{exc.id}: the pack binds lines {sorted(lines)}, the row says {exc.lines}"
        assert exc.anchor not in exc.lines
        assert len(exc.reason.split()) >= 5, f"{exc.id}: say what the adjudicator saw"


def _table(tmp_path, families):
    path = tmp_path / "x.yaml"
    path.write_text(yaml.safe_dump({"families": families}))
    return path


ROW = {"pack": "states/zz/2025/f1", "field": "rotated", "widget": 0, "line": "22", "anchor": "21"}
FAM = {"family": "zz", "reason": "the box sits on printed line 22", "adjudication": "a blind read", "rows": [ROW]}


def test_the_exceptions_table_refuses_a_row_it_cannot_match_exactly(tmp_path):
    assert set(L.load_exceptions(_table(tmp_path, [FAM]))) == {("states/zz/2025/f1", "rotated", 0)}
    for bad, match in (({**FAM, "reason": ""}, "reason"),
                       ({**FAM, "rows": []}, "rows"),
                       ({**FAM, "rows": [{k: v for k, v in ROW.items() if k != "anchor"}]}, "anchor"),
                       ({**FAM, "rows": [{k: v for k, v in ROW.items() if k != "widget"}]}, "widget"),
                       ({**FAM, "rows": [{**ROW, "anchor": "22"}]}, "agrees")):
        with pytest.raises(ValueError, match=match):
            L.load_exceptions(_table(tmp_path, [bad]))
    # a duplicate: the same widget twice, even in two families with different lines
    with pytest.raises(ValueError, match="duplicate"):
        L.load_exceptions(_table(tmp_path, [FAM, {**FAM, "family": "zz2", "rows": [{**ROW, "line": "23"}]}]))


def _row(pack, field, printed, claims, page=1, index=0):
    w = A.WidgetAnchor(field=field, widget_index=index, page=page, rect=[0, 0, 1, 1], kind="text",
                       printed_line=printed)
    return L.Row(pack=pack, blank=Path("b.pdf"), widget=w, claims=claims)


def test_a_row_excuses_exactly_one_disagreement_and_goes_stale_when_it_stops_matching(tmp_path):
    pack = "states/zz/2025/f1"
    rows = [
        _row(pack, "ok", "21", {"21": "21"}),
        _row(pack, "rotated", "21", {"22": "22"}),                  # the P-032 shape
        _row(pack, "two_keys", "7", {"8": "8", "line_8": "8"}),
        _row(pack, "column", "1", {"1a": "1"}),                     # a convention-mapped key that agrees
        _row(pack, "rotated", "21", {"22": "22"}, index=1),         # a second widget of the same field
    ]
    res = L.Result(pack=pack, blank=Path("b.pdf"), rows=rows)
    assert [r.id for r in res.disagreements] == [f"{pack}:p1:rotated:w0", f"{pack}:p1:two_keys:w0",
                                                 f"{pack}:p1:rotated:w1"]
    table = L.load_exceptions(_table(tmp_path, [{**FAM, "rows": [
        ROW, {**ROW, "field": "two_keys", "line": "8", "anchor": "7"},
        {**ROW, "pack": "other/pack", "field": "x"}]}]))
    assert [r.id for r in res.unexcused(table)] == [f"{pack}:p1:rotated:w1"]   # a row names ONE widget
    assert res.stale(table) == []                                                # other packs' rows are theirs

    def stale_after(row: L.Row) -> list[str]:
        changed = L.Result(pack=pack, blank=Path("b.pdf"), rows=[row, *rows[2:4]])
        return changed.stale(table)

    # the pack re-keyed the widget to the anchor's line: it agrees, and its row must go
    assert stale_after(_row(pack, "rotated", "21", {"21": "21"})) == [f"{pack}:rotated:w0"]
    # the pack re-keyed it to yet another line, or the anchor now reads another line: the row no longer names it
    for moved in (_row(pack, "rotated", "21", {"23": "23"}), _row(pack, "rotated", "20", {"22": "22"})):
        assert stale_after(moved) == [f"{pack}:rotated:w0"]
        assert [r.id for r in L.Result(pack=pack, blank=Path("b.pdf"), rows=[moved]).unexcused(table)] == [
            f"{pack}:p1:rotated:w0"]


def test_the_shipped_exceptions_table_has_no_duplicate_widget():
    """The loader refuses a duplicate; the raw rows say the same, so no dict key was silently merged."""
    raw = yaml.safe_load(L.EXCEPTIONS.read_text(encoding="utf-8"))
    ids = [(r["pack"], r["field"], int(r["widget"])) for fam in raw["families"] for r in fam["rows"]]
    assert len(ids) == len(set(ids)) == len(L.load_exceptions())


# ── offline: declared key shapes (formpacks/key_shapes.yaml), fixer round 2 ──

SHAPES = L.load_shapes()


def test_every_key_shape_names_shipped_packs_and_maps_their_keys():
    from taxfill_core.schemas.formpack import load_pack

    assert {s.id for s in SHAPES} >= {"ny-it203-line-boxes", "nj1040-amount-digit-cells", "ca-sched-ca-540nr-columns"}
    for shape in SHAPES:
        for pid in shape.packs:
            assert pid in PACK_IDS, f"{shape.id}: {pid} is not a shipped pack"
            keys = [f.line for f in load_pack(REPO / "formpacks" / pid / "pack.yaml").fields]
            assert any(shape.covers(pid, k) for k in keys), f"{shape.id} maps no key of {pid}"
            # a shape never claims a key a column convention or another shape already maps; only the generic
            # line-boxes shape (fixer round 3, the last one tried) may overlap a pack's own shape, which wins
            for k in keys:
                if shape.covers(pid, k):
                    assert not any(c.covers(pid, k) for c in CONVENTIONS), (shape.id, pid, k)
                    claims = [s.id for s in SHAPES if s.covers(pid, k)]
                    assert len([c for c in claims if c != "line-boxes"]) <= 1, (pid, k, claims)
                    assert L.claim_line(pid, k, CONVENTIONS)[1] == claims[0]
    assert SHAPES[-1].id == "line-boxes"


def _shapes(tmp_path, row):
    path = tmp_path / "key_shapes.yaml"
    path.write_text(yaml.safe_dump({"shapes": [row]}))
    return path


GOOD_SHAPE = {"id": "zz", "packs": ["states/zz/2025/f1"], "pattern": r"^0*(?P<n>\d{1,3})(?P<x>[a-z])?_fed$",
              "means": "line N's federal column", "examples": {"5a_fed": "5a"}}


def test_the_shape_table_refuses_a_shape_it_cannot_trust(tmp_path):
    assert L.load_shapes(_shapes(tmp_path, GOOD_SHAPE))[0].covers("states/zz/2025/f1", "21_fed") == "21"
    # fixer round 4: a named block (keys with no line number of their own) gives its one printed line
    block = dict(GOOD_SHAPE, pattern=r"^age65_blind\.(?:taxpayer|spouse)_blind$", line="8",
                 examples={"age65_blind.spouse_blind": "8"})
    assert L.load_shapes(_shapes(tmp_path, block))[0].covers("states/zz/2025/f1", "age65_blind.taxpayer_blind") == "8"
    for bad, why in ((dict(GOOD_SHAPE, means=""), "lacks"),
                     (dict(GOOD_SHAPE, pattern=r"^(?P<line>\d+)_fed$"), "named groups"),
                     (dict(GOOD_SHAPE, pattern=r"^(?P<n>\d+)(?P<col>[a-z])_fed$"), "named groups"),
                     (dict(GOOD_SHAPE, examples={"5a_fed": "5"}), "maps to '5a'"),
                     (dict(block, line="8x1"), "named block"),
                     (dict(GOOD_SHAPE, line="8"), "named block"),
                     (dict(block, examples={"age65_blind.spouse_blind": "9"}), "maps to '8'")):
        with pytest.raises(ValueError, match=why):
            L.load_shapes(_shapes(tmp_path, bad))


# ── offline: the coverage ledger (formpacks/label_adjacency_coverage.yaml), fixer round 2 ──

LEDGER = L.load_ledger()


@pytest.mark.parametrize(("checked", "lines", "verdict"), [
    (0, 0, "UNCHECKED (0/0 line-bearing keys checked)"),
    (0, 22, "UNCHECKED (0/22 line-bearing keys checked)"),
    (12, 47, "PARTIAL 12/47 (line-bearing keys checked; floor 70%)"),
    (6, 9, "PARTIAL 6/9 (line-bearing keys checked; floor 70%)"),
    (7, 10, "OK (7/10 line-bearing keys checked)"),
])
def test_the_coverage_verdict_is_never_ok_below_the_floor(checked, lines, verdict):
    assert LEDGER.floor == 0.7
    assert L.coverage_verdict(checked, lines, LEDGER.floor) == verdict


def test_a_dark_family_makes_the_verdict_partial_whatever_the_fraction():
    """Fixer round 4: OH IT 1040 measured 121/152 (OK) with its Schedule of Business Income (22 keys) undeclared."""
    assert L.coverage_verdict(121, 152, 0.7) == "OK (121/152 line-bearing keys checked)"
    assert L.coverage_verdict(121, 152, 0.7, ("schedITbus_#", "schedITbus_#_neg")) == (
        "PARTIAL 121/152 (line-bearing keys checked; floor 70%; undeclared, wholly unchecked: schedITbus_#, "
        "schedITbus_#_neg)")
    assert L.below_floor(121, 152, 0.7, ("schedITbus_#",)) and not L.below_floor(121, 152, 0.7)


def test_an_undeclared_key_the_anchor_reads_makes_the_verdict_partial_whatever_its_family_size():
    """Fixer round 5, the declare-me rule: AZ 140 2023 measured 249/292 (OK) with ws3_1c..ws3_7c undeclared."""
    assert L.coverage_verdict(249, 292, 0.7, (), ("ws#_#",)) == (
        "PARTIAL 249/292 (line-bearing keys checked; floor 70%; undeclared keys the anchor reads a line beside "
        "(declare them): ws#_#)")
    assert L.below_floor(249, 292, 0.7, (), ("ltc.#",)) and not L.below_floor(249, 292, 0.7, (), ())
    assert L.declare_families({"ws3_1c_gifts_cash_or_check": ("1c",), "ws3_7c_multiply_by_31pct": ("7c",),
                               "ltc.2": ("2",)}) == ("ltc.#", "ws#_#")


def test_dark_families_are_five_undeclared_keys_or_five_keys_none_checked():
    undeclared = {f"schedITbus_{n}" for n in range(1, 17)} | {"ehrc.1", "ehrc.2", "ehrc.3", "ehrc.4"}
    # 16 undeclared keys of one family are dark; 4 of another are not
    assert L.dark_families(undeclared) == ("schedITbus_#",)
    # fixer round 5: a family is the key up to its first line token, the descriptive tail dropped
    assert L.key_family("sch_m.34a.c") == "sch_m.#" and L.key_family("schedITbus_2_neg") == "schedITbus_#"
    assert L.tail_family("sch_m.34a.c") == "sch_m.#.c" and L.key_family("name.first") == "name.first"
    ws3 = {"ws3_1c_gifts_cash_or_check", "ws3_2c_other", "ws3_3c_carryover", "ws3_4c_add_1c_3c",
           "ws3_5c_credit_contributions", "ws3_6c_subtract_5c_from_4c", "ws3_7c_multiply_by_31pct"}
    assert {L.key_family(k) for k in ws3} == {"ws#_#"} and len({L.tail_family(k) for k in ws3}) == 7
    assert L.dark_families(ws3) == ("ws#_#",)     # round 4 saw seven one-key families and no dark one
    # five declared keys none of which the gate checks are dark too; one checked key clears the family
    declared = {f"{n}.no" for n in (7, 8, 9, 10, 11)}
    assert L.dark_families(set(), declared, set()) == ("#",)
    assert L.dark_families(set(), declared, {"9.no"}) == ()
    # a uniform-tail family none of whose keys is checked is dark inside a prefix family whose other keys are
    assert L.dark_families(set(), declared | {"1", "2"}, {"1"}) == ("#.no",)
    assert L.dark_families({"ehrc.5"}, {"ehrc.1", "ehrc.2", "ehrc.3", "ehrc.4"}, set()) == ("ehrc.#",)
    assert L.recorded_dark(121, 152, 0.7, ("b#", "a#")) == ("a#", "b#")
    assert L.recorded_dark(12, 152, 0.7, ("a#",)) == ()        # already below the floor: the reason stands


def test_the_ledger_has_exactly_one_row_per_shipped_pack_and_names_every_pack_below_the_floor():
    assert set(LEDGER.rows) == set(PACK_IDS)
    below = {p for p, r in LEDGER.rows.items()
             if L.below_floor(r.checked, r.lines, LEDGER.floor, r.dark, r.declare)}
    assert below == {p for p, r in LEDGER.rows.items() if r.reason}
    assert set(LEDGER.reasons) == {"no-text-layer", "anchor-reads-no-designators", "shape-not-declared",
                                   "no-line-designators"}
    # the verifier's zero-coverage tier-1 / JS7a bases now check most of their line-bearing keys
    for y in (2023, 2024, 2025):
        for pid in (f"states/ny/{y}/it203", f"states/ca/{y}/sched_ca_540"):
            assert pid not in below and LEDGER.rows[pid].checked > 100, pid
        # fixer round 5: CA 540NR's nine entry boxes 9b1-9b3 (columns B, D, E) are one prefix family the anchor
        # reads no line beside — dark, so PARTIAL, though 356+ of its keys are checked
        row = LEDGER.rows[f"states/ca/{y}/sched_ca_540nr"]
        assert row.checked > 300 and row.dark == ("B##",) and row.reason == "anchor-reads-no-designators"
        assert LEDGER.rows[f"states/nj/{y}/nj1040"].checked > 150
    # and the packs still below the floor are named with their reason
    assert LEDGER.rows["states/dc/2023/d40"].reason == "anchor-reads-no-designators"
    assert LEDGER.rows["states/ut/2025/tc40"].reason == "no-text-layer"
    assert LEDGER.rows["federal/2025/fw7"].reason == "shape-not-declared"


BLIND0 = {"same_row": 0, "cross_section": 0, "descriptive": 0}   # fixer round 6: no blind spot counted


def _ledger(tmp_path, packs, floor=0.7, blind=True):
    """A ledger file holding ``packs`` (pack -> its flow-mapping row); with ``blind`` a row that does not spell its
    fixer-round-6 blind-spot counts gets zeros for them."""
    text = (REPO / "formpacks" / "label_adjacency_coverage.yaml").read_text().partition("\npacks:\n")[0]
    text = text.replace("floor: 0.7", f"floor: {floor}")
    if blind:
        packs = {p: row if "same_row" in row else row[:-1] + ", same_row: 0, cross_section: 0, descriptive: 0}"
                 for p, row in packs.items()}
    path = tmp_path / "coverage.yaml"
    path.write_text(text + "\npacks:\n" + "".join(f"  {p}: {row}\n" for p, row in packs.items()))
    return path


def test_the_ledger_refuses_a_row_it_cannot_trust(tmp_path):
    ok = L.load_ledger(_ledger(tmp_path, {"a/1/x": "{checked: 9, lines: 10, mapped: 10, unread: 1}",
                                          "a/1/y": "{checked: 0, lines: 4, mapped: 4, unread: 4, "
                                                   "reason: no-text-layer, note: page 2}"}))
    assert ok.rows["a/1/y"].reason == "no-text-layer"
    for row, why in (("{checked: 1, lines: 4, mapped: 4, unread: 0}", "below the floor"),
                     ("{checked: 1, lines: 4, mapped: 4, unread: 0, reason: unknown, note: x}", "below the floor"),
                     ("{checked: 1, lines: 4, mapped: 4, unread: 0, reason: no-text-layer}", "below the floor"),
                     ("{checked: 9, lines: 10, mapped: 10, unread: 0, reason: no-text-layer, note: x}",
                      "remove its reason"),
                     ("{checked: 5, lines: 4, mapped: 4, unread: 0}", "checked"),
                     ("{checked: 3, lines: 4, mapped: 2, unread: 0}", "mapped"),
                     ("{checked: 3, lines: 4, mapped: 5, unread: 0}", "mapped"),
                     ("{checked: 3, lines: 4, unread: 0}", "lacks mapped"),
                     # fixer round 4: a dark family needs a reason and a note; a dark list is kept only while it
                     # alone puts the pack below the floor; a family is spelled with "#"
                     ('{checked: 9, lines: 10, mapped: 10, unread: 0, dark: ["a.#"]}', "below the floor"),
                     ('{checked: 1, lines: 4, mapped: 4, unread: 0, dark: ["a.#"], reason: no-text-layer, note: x}',
                      "remove its dark list"),
                     ('{checked: 9, lines: 10, mapped: 10, unread: 0, dark: [a.1]}', "dark lists key families"),
                     # fixer round 5: a declare family (an undeclared key the anchor reads) needs a reason and a
                     # note at any fraction; every row counts its unread keys, at most lines - checked
                     ('{checked: 9, lines: 10, mapped: 9, unread: 0, declare: ["ws#_#"]}', "below the floor"),
                     ('{checked: 9, lines: 10, mapped: 9, unread: 0, declare: [ws3_1c]}',
                      "declare lists key families"),
                     ("{checked: 9, lines: 10, mapped: 10}", "lacks unread"),
                     ("{checked: 9, lines: 10, mapped: 10, unread: 2}", "unread")):
        with pytest.raises(ValueError, match=why):
            L.load_ledger(_ledger(tmp_path, {"a/1/x": row}))
    dark = L.load_ledger(_ledger(tmp_path, {"a/1/x": '{checked: 9, lines: 10, mapped: 10, unread: 0, '
                                                     'dark: ["a.#"], reason: shape-not-declared, note: a.1-a.5}'}))
    assert dark.rows["a/1/x"].dark == ("a.#",) and L.below_floor(9, 10, 0.7, dark.rows["a/1/x"].dark)
    declare = L.load_ledger(_ledger(tmp_path, {"a/1/x": '{checked: 9, lines: 10, mapped: 9, unread: 0, '
                                                        'declare: ["ws#_#"], reason: shape-not-declared, note: x}'}))
    row = declare.rows["a/1/x"]
    assert row.declare == ("ws#_#",) and row.unread == 0 and L.below_floor(9, 10, 0.7, row.dark, row.declare)
    with pytest.raises(ValueError, match="floor"):
        L.load_ledger(_ledger(tmp_path, {}, floor=0))


def test_the_ledger_refuses_a_row_without_its_blind_spot_counts(tmp_path):
    """Fixer round 6: every row counts each blind spot — same_row and cross_section at most its checked keys."""
    full = "{checked: 9, lines: 10, mapped: 10, unread: 1, same_row: 2, cross_section: 3, descriptive: 4}"
    row = L.load_ledger(_ledger(tmp_path, {"a/1/x": full}, blind=False)).rows["a/1/x"]
    assert (row.unread, row.same_row, row.cross_section, row.descriptive) == (1, 2, 3, 4)
    for col in ("same_row", "cross_section", "descriptive"):
        lacking = re.sub(rf", {col}: \d+", "", full)
        with pytest.raises(ValueError, match=f"lacks {col}"):
            L.load_ledger(_ledger(tmp_path, {"a/1/x": lacking}, blind=False))
    for bad in ("same_row: 10", "cross_section: 10", "descriptive: -1"):
        col = bad.partition(":")[0]
        with pytest.raises(ValueError, match="same_row .* <= checked"):
            L.load_ledger(_ledger(tmp_path, {"a/1/x": re.sub(rf"{col}: \d+", bad, full)}, blind=False))


def test_the_ledger_fails_a_regression_a_stale_row_and_a_missing_row():
    led = L.Ledger(floor=0.7, reasons={}, rows={"a/1/x": L.LedgerRow(checked=40, lines=50, mapped=45)})
    assert L.ledger_problems("a/1/x", 40, 50, led) == [] == L.ledger_problems("a/1/x", 40, 50, led, 45)
    assert "REGRESSED to 39/50" in L.ledger_problems("a/1/x", 39, 50, led)[0]
    assert "stale" in L.ledger_problems("a/1/x", 41, 50, led)[0]
    assert "stale" in L.ledger_problems("a/1/x", 40, 51, led)[0]
    assert "stale" in L.ledger_problems("a/1/x", 40, 50, led, 46)[0]    # a shape now maps one more key
    assert "no row" in L.ledger_problems("a/1/z", 1, 1, led)[0]
    # fixer round 4: a new dark family fails the row (the gate's half of the dark-family rule); one the row records
    # passes, and a recorded family that went away is a stale row
    assert "a 3-cycle inside would pass" in L.ledger_problems("a/1/x", 40, 50, led, 45, ("schedITbus_#",))[0]
    assert L.ledger_problems("a/1/x", 40, 50, led, 45, ()) == []
    led2 = L.Ledger(floor=0.7, reasons={}, rows={"a/1/x": L.LedgerRow(40, 50, 45, "shape-not-declared", "n",
                                                                       ("schedITbus_#",))})
    assert L.ledger_problems("a/1/x", 40, 50, led2, 45, ("schedITbus_#",)) == []
    assert "stale" in L.ledger_problems("a/1/x", 40, 50, led2, 45, ())[0]
    # fixer round 5: an undeclared key the anchor reads fails the row until it is declared or recorded; a recorded
    # declare family that went away, or a changed unread count, is a stale row
    led3 = L.Ledger(floor=0.7, reasons={}, rows={"a/1/x": L.LedgerRow(40, 50, 45, unread=6)})
    assert "the anchor reads a printed line beside undeclared key family ['ws#_#']" in L.ledger_problems(
        "a/1/x", 40, 50, led3, 45, (), ("ws#_#",), 6)[0]
    assert L.ledger_problems("a/1/x", 40, 50, led3, 45, (), (), 6) == []
    assert "stale" in L.ledger_problems("a/1/x", 40, 50, led3, 45, (), (), 7)[0]
    led4 = L.Ledger(floor=0.7, reasons={}, rows={"a/1/x": L.LedgerRow(40, 50, 45, "shape-not-declared", "n",
                                                                       declare=("ws#_#",), unread=6)})
    assert L.ledger_problems("a/1/x", 40, 50, led4, 45, (), ("ws#_#",), 6) == []
    assert "stale" in L.ledger_problems("a/1/x", 40, 50, led4, 45, (), (), 6)[0]


def test_a_stale_blind_spot_count_fails_the_row():
    """Fixer round 6: the ledger keeps each blind spot's count exact — one more (or one fewer) key the gate cannot
    see than the row records is a stale row, named by its column."""
    led = L.Ledger(floor=0.7, reasons={}, rows={"a/1/x": L.LedgerRow(40, 50, 45, unread=6, same_row=4,
                                                                      cross_section=9, descriptive=2)})
    measured = {"same_row": 4, "unread": 6, "cross_section": 9, "descriptive": 2}
    assert L.ledger_problems("a/1/x", 40, 50, led, 45, (), (), 6, measured) == []
    for col in ("same_row", "cross_section", "descriptive"):
        for delta in (1, -1):
            got = L.ledger_problems("a/1/x", 40, 50, led, 45, (), (), 6, {**measured, col: measured[col] + delta})
            assert len(got) == 1 and "stale" in got[0] and f"({col})" in got[0], got
            assert f"measures {measured[col] + delta}, the row records {measured[col]}" in got[0]
    # an unread count is compared on its own (fixer round 5)
    assert "anchor reads no line" in L.ledger_problems("a/1/x", 40, 50, led, 45, (), (), 7, {**measured,
                                                                                               "unread": 7})[0]


def _box(field, printed, claims, page=1, y=(0, 10), index=0):
    w = A.WidgetAnchor(field=field, widget_index=index, page=page, rect=[0, y[0], 50, y[1]], kind="text",
                       printed_line=printed)
    return L.Row(pack="a/1/x", blank=Path("b.pdf"), widget=w, claims=claims)


def test_same_row_and_cross_section_keys_are_the_checked_keys_a_swap_could_exchange_unseen():
    """Fixer round 6: blind spots (a) and (c) counted on synthetic rows. Keys claiming one line on two fields of one
    printed row are same_row; on another row or page, cross_section; one field's two keys and a lone line are
    neither. A key whose box the anchor reads another line beside (a disagreement: in a passing pack an EXCUSED one)
    takes part like an agreeing key (the final review, 2026-10-25): its exception matches the widget and the lines,
    so another key claiming the same line passes at that box."""
    rows = [
        _box("f_fed", "1", {"1_fed": "1"}, y=(100, 110)),                # (a) federal <-> state columns of line 1
        _box("f_state", "1", {"1_state": "1"}, y=(102, 112)),
        _box("s_a", "1", {"sch_a.1": "1"}, page=2, y=(100, 110)),        # (c) Schedule A's line 1 on page 2
        _box("f_2", "2", {"2": "2", "2.copy": "2"}, y=(80, 90)),         # one field, two keys: no swap
        _box("f_3", "4", {"3": "3"}, y=(60, 70)),                        # off its line: an excused disagreement
        _box("s_3", "3", {"sch_a.3": "3"}, page=2, y=(60, 70)),
        _box("f_5", "5", {"5": "5"}, y=(40, 50)),                        # a lone line 5
        _box("s_5", "5", {"sch_a.5": "5"}, y=(20, 30)),                  # same page, no vertical overlap: (c)
    ]
    res = L.Result(pack="a/1/x", blank=Path("b.pdf"), rows=rows, descriptive={"withholding_w2": ("12",)})
    same, cross = res.shared_line_keys
    assert same == {"1_fed", "1_state"}
    assert cross == {"1_fed", "1_state", "sch_a.1", "3", "sch_a.3", "5", "sch_a.5"}
    assert res.blind == {"same_row": 2, "unread": 0, "cross_section": 7, "descriptive": 1}


def test_a_key_on_an_excused_box_is_counted_with_the_key_it_could_swap_with():
    """The final review's major: Form 1040 2025 line 16's amount box agrees, and the Form 8814 checkbox on the same
    row is an excused disagreement (the anchor reads another line beside it). Swapping the two keys passes the gate,
    so both keys count in same_row; before the fix only agreeing boxes took part and neither was counted."""
    rows = [
        _box("f_16", "16", {"16": "16"}, y=(300, 312)),
        _box("c_8814", "15", {"16.form_8814": "16"}, y=(301, 311)),
    ]
    res = L.Result(pack="federal/2025/f1040", blank=Path("b.pdf"), rows=rows)
    assert res.shared_line_keys[0] == {"16", "16.form_8814"}
    assert res.same_row == 2


def test_write_ledger_updates_counts_and_keeps_a_recorded_reason(tmp_path):
    path = _ledger(tmp_path, {"a/1/x": "{checked: 9, lines: 10, mapped: 10, unread: 1}",
                              "a/1/y": "{checked: 0, lines: 4, mapped: 4, unread: 4, reason: no-text-layer, "
                                       "note: page 2}",
                              "a/1/w": "{checked: 0, lines: 4, mapped: 4, unread: 4, reason: no-text-layer, "
                                       "note: page 2}"})
    changed = L.write_ledger({"a/1/x": (3, 10, 10, "anchor-reads-no-designators", "drafted"),
                              "a/1/y": (1, 4, 4, "anchor-reads-no-designators", "drafted"),
                              "a/1/w": (1, 9, 4, "shape-not-declared", "5 undeclared"),
                              "a/1/z": (5, 5, 5, "", "")}, path)
    led = L.load_ledger(path)
    assert changed == 4
    # (no unread measured: every unchecked key counts; no blind spot measured: none counted)
    assert led.rows["a/1/x"] == L.LedgerRow(3, 10, 10, "anchor-reads-no-designators", "drafted", unread=7, **BLIND0)
    assert led.rows["a/1/y"] == L.LedgerRow(1, 4, 4, "no-text-layer", "page 2", unread=3, **BLIND0)
    # the undeclared count changed (5 more line-like keys no rule maps): the suggestion replaces the old reason
    assert led.rows["a/1/w"] == L.LedgerRow(1, 9, 4, "shape-not-declared", "5 undeclared", unread=8, **BLIND0)
    assert led.rows["a/1/z"] == L.LedgerRow(5, 5, 5, unread=0, **BLIND0)
    assert path.read_text().startswith("# Phase K JK10")
    # fixer round 4: a dark family at an OK fraction is written with its reason; below the fraction floor it is not
    L.write_ledger({"a/1/z": (5, 5, 5, "shape-not-declared", "x5", ("ehrc.#",)),
                    "a/1/x": (3, 10, 10, "anchor-reads-no-designators", "drafted", ("q.#",))}, path)
    led = L.load_ledger(path)
    assert led.rows["a/1/z"] == L.LedgerRow(5, 5, 5, "shape-not-declared", "x5", ("ehrc.#",), unread=0, **BLIND0)
    assert led.rows["a/1/x"].dark == ()
    # fixer round 5: a declare family is written at any fraction, with its reason, and the measured unread count
    L.write_ledger({"a/1/z": (5, 5, 5, "shape-not-declared", "ltc", (), ("ltc.#",), 0),
                    "a/1/x": (3, 10, 10, "anchor-reads-no-designators", "drafted", (), ("q.#",), 2)}, path)
    led = L.load_ledger(path)
    assert led.rows["a/1/z"] == L.LedgerRow(5, 5, 5, "shape-not-declared", "ltc", (), ("ltc.#",), 0, **BLIND0)
    assert (led.rows["a/1/x"].declare, led.rows["a/1/x"].unread) == (("q.#",), 2)
    # fixer round 6: the measured blind-spot counts (same_row, cross_section, descriptive) are written
    L.write_ledger({"a/1/z": (5, 5, 5, "", "", (), (), 0, (2, 3, 4))}, path)
    row = L.load_ledger(path).rows["a/1/z"]
    assert (row.same_row, row.cross_section, row.descriptive) == (2, 3, 4)
    assert "unread: 0, same_row: 2, cross_section: 3, descriptive: 4" in path.read_text()


# ── offline: the non-circular denominator (fixer round 3) ───────────────────


@pytest.mark.parametrize(("key", "like"), [
    ("21", True), ("5a", True), ("line_21", True), ("13.a", True), ("1.cents", True), ("7.2019", True),
    ("sched1.5", True), ("sch_511a.3", True), ("moa_12y", True), ("12-Y", True), ("line19_d01", True),
    ("SCHAACPRTILN5", True), ("mailing_address_line1", True), ("6b.self_over_65", True), ("1_wages_fed", True),
    ("you_65_or_older", False), ("spouse_over_65", False), ("f1s.age_65", False), ("d01", False),
    ("name.first", False), ("PROP12", False), ("w2_wages", False), ("form_8949", False), ("1040", False),
    ("qh12", False), ("sched3", False),
    # fixer round 4: a line glued to its section letter (CA Schedule CA "B9b1_B" = Section B line 9b1)
    ("B9b1_B", True), ("A1a_A", True), ("W2", False), ("age65_blind.taxpayer_blind", False),
])
def test_the_token_rule(key, like):
    assert L.line_like(key) is like


def test_the_not_lines_list_is_short_and_every_family_leaves_out_shipped_keys():
    """Each not_lines family names its reason and leaves out at least one line-like key of a shipped pack; the list
    stays short (identity, household members, positional rows) — a family of main lines belongs in a shape."""
    families = L.load_not_lines()
    assert [f.id for f in families] == ["identity", "household-members", "positional-rows",
                                        # fixer round 5: the declare-me rule's non-line keys, each vision-read
                                        "check-off-amounts", "direct-deposit-529", "positional-codes",
                                        "filing-status-reference"]
    hit = {f.id: 0 for f in families}
    for pid in PACK_IDS:
        pack = L.B.load_pack(REPO / "formpacks" / pid / "pack.yaml")
        for k in L.B.pack_keys(pack):
            key = str(k["key"])
            if L.line_like(key) and (fam := L.not_line_family(key, pack=pid)):
                hit[fam] += 1
    assert all(hit.values()), hit
    # no main line hides in the list: a bare "N" / "Na" key, or N.a / N_b columns, matches no family
    for key in ("21", "5a", "13.a", "5_b", "sched1.5", "sub.3.b", "moa_12y", "s1.7a"):
        assert L.not_line_family(key) is None, key
    # fixer round 6: MT Form 2 2023's exemption rows a-d are lines (the face prints a-d in the line gutter, row d
    # reads "Add lines a through c"); no family hides them any more, so the pack reads PARTIAL (see the MT test)
    assert L.not_line_family("16a.a", pack="states/mt/2023/form2") is None
    # the reasons say where the check-off boxes and the 529 items sit on the face
    by_reason = {f.id: f.reason for f in families}
    assert "lettered rows 1a-1d of line 1" in by_reason["check-off-amounts"]
    assert "the face prints N as the direct-deposit item number" in by_reason["direct-deposit-529"]
    # fixer round 4: the bare "account" / "dependent" patterns hid lines that NAME an account or dependents (MT
    # Schedule I line 3, NJ-1040 exemption lines 11-12); each family's not_examples hold the anchored patterns
    by_id = {f.id: f for f in families}
    assert {"sched3.8.cgr_account_id", "sched1.3.medical_savings_account"} <= set(by_id["identity"].not_examples)
    assert "exemption_11_other_dependents_amount" in by_id["household-members"].not_examples
    for fam in families:
        assert all(L.not_line_family(k) is None for k in fam.not_examples), fam.id


def test_a_not_lines_family_that_hides_a_line_bearing_key_is_refused(tmp_path):
    text = (REPO / "formpacks" / "label_adjacency_coverage.yaml").read_text().partition("\npacks:\n")[0]
    path = tmp_path / "coverage.yaml"
    for broad in ("account", "dependent"):        # round 3's bare patterns
        bad = text.replace("(?:^|\\.)account(?:_number|_type|\\.\\d|$)", broad) if broad == "account" else \
            text.replace("(?<![a-z])dependent_?\\d|(?<![a-z])dependents?$", broad)
        assert bad != text, broad
        path.write_text(bad + "\npacks:\n")
        with pytest.raises(ValueError, match="hides it"):
            L.load_not_lines(path)


def _census(pid: str) -> tuple[set[str], set[str]]:
    """(keys a rule or shape maps, line-like keys none maps outside not_lines) — the ledger's mapped and
    lines - mapped, computed from the pack alone."""
    pack = L.B.load_pack(REPO / "formpacks" / pid / "pack.yaml")
    mapped, undeclared = set(), set()
    for k in L.B.pack_keys(pack):
        key = str(k["key"])
        if L.claim_line(pid, key, CONVENTIONS)[0] is not None:
            mapped.add(key)
        elif L.line_like(key) and L.not_line_family(key, pack=pid) is None:
            undeclared.add(key)
    return mapped, undeclared


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_the_ledger_denominator_counts_every_line_like_key(pack_id):
    mapped, undeclared = _census(pack_id)
    row = LEDGER.rows[pack_id]
    assert (row.mapped, row.lines) == (len(mapped), len(mapped) + len(undeclared)), (
        f"{pack_id}: the ledger row says {row.mapped} mapped / {row.lines} line-bearing, the keys give "
        f"{len(mapped)} / {len(mapped) + len(undeclared)} — run scripts/label_adjacency.py --pack {pack_id} "
        "--write-ledger")


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_no_row_at_or_above_the_floor_holds_a_dark_undeclared_family(pack_id):
    """Fixer round 4: a family of 5+ undeclared keys (computed from the pack alone) puts the pack below the floor —
    its row lists the family, with a reason — so no OK row hides a whole unmapped schedule."""
    _, undeclared = _census(pack_id)
    dark = L.dark_families(undeclared)
    row = LEDGER.rows[pack_id]
    if L.below_floor(row.checked, row.lines, LEDGER.floor):
        return
    assert set(dark) <= set(row.dark), (
        f"{pack_id}: undeclared famil(ies) {sorted(set(dark) - set(row.dark))} of {L.DARK_FAMILY_MIN}+ keys the gate "
        "compares on no widget, yet the row is OK — declare the shape (key_shapes.yaml) or record the family")
    if row.dark:
        assert row.reason and L.below_floor(row.checked, row.lines, LEDGER.floor, row.dark)


def test_the_round_three_verifiers_dark_schedules_are_declared_or_named():
    for y in (2023, 2024, 2025):
        assert LEDGER.rows[f"states/oh/{y}/it1040_oh"].dark == ()
        assert not L.dark_families(_census(f"states/oh/{y}/it1040_oh")[1])
        assert not L.dark_families(_census(f"states/ri/{y}/ri1040")[1])
    assert not L.dark_families(_census("states/mt/2025/form2")[1]) and LEDGER.rows["states/mt/2025/form2"].dark == ()
    # fixer round 6: MT 2023's EHRC and UPINT schedules stay declared; its only undeclared keys are the seven
    # letter-only exemption rows, whose family ("#") is dark and named in the row (PARTIAL with the reason)
    und = _census("states/mt/2023/form2")[1]
    assert und == {"16a.a", "16b.a", "16b.b", "16c.a", "16c.b", "16d.a", "16d.b"}
    assert L.dark_families(und) == ("#",) == LEDGER.rows["states/mt/2023/form2"].dark
    # WV Schedule M's item (b) boxes and the recap's state boxes are declared, but the anchor reads no line beside
    # any of them: the row names them and the pack is PARTIAL (a 3-cycle among them cannot hide behind OK)
    for y in (2023, 2024):
        row = LEDGER.rows[f"states/wv/{y}/it140"]
        assert row.dark == ("recap.#.state_#", "sch_m.#.b") and row.reason == "anchor-reads-no-designators"
        assert not L.dark_families(_census(f"states/wv/{y}/it140")[1])


def test_no_row_at_or_above_the_floor_has_more_undeclared_keys_than_checked_ones():
    over = {p: (r.checked, r.lines - r.mapped) for p, r in LEDGER.rows.items()
            if not L.below_floor(r.checked, r.lines, LEDGER.floor, r.dark) and r.lines - r.mapped > r.checked}
    assert not over, f"(checked, undeclared) of packs whose line-like keys are mostly undeclared yet OK: {over}"
    # the round-2 verifier's circular-denominator packs: their main lines are now declared and checked
    for pid in ("states/ms/2025/f80105", "states/ky/2025/form740", "states/ar/2025/ar1000f",
                "states/mt/2023/form2"):
        row = LEDGER.rows[pid]
        assert not L.below_floor(row.checked, row.lines, LEDGER.floor) and row.lines - row.mapped < 0.2 * row.lines
    # and a pack whose line-like keys stay mostly undeclared is below the floor, named shape-not-declared
    for y in (2023, 2024, 2025):
        row = LEDGER.rows[f"states/al/{y}/al40"]
        assert row.reason == "shape-not-declared" and row.lines - row.mapped > 1000


# Phase K JK10 (2026-10-24), fixer round 2: keys the declared shapes found off the printed line, re-keyed
SHAPE_RE_KEYED = {
    **{f"states/ny/{y}/it203": ({"74_electronic_funds_withdrawal_date": "electronic funds withdrawal"},
                                {"73_electronic_funds_withdrawal_date"}) for y in (2023, 2024, 2025)},
    "states/ga/2023/ga500": ({"s3.10a": "S3L10",                      # the 2023 face prints "10a." on that row
                              # fixer round 5: the deduction-type boxes of that same row
                              **{f"s3.10a_deduction.{t}": "CB_DEDUCTION_TYPE" for t in ("itemized", "standard",
                                                                                       "georgia")}},
                             {"s3.10", "s3.10_deduction.itemized", "s3.10_deduction.standard",
                              "s3.10_deduction.georgia"}),
    # fixer round 3: the 2023 Schedule 1 prints this row "8p Section 461(l) excess business loss adjustment"
    "states/mt/2023/form2": ({"sch1.8p.a": "Schedule 1 Col A Line 8o", "sch1.8p.b": "Schedule 1 Col B Line 8o"},
                             {"sch1.8o.a", "sch1.8o.b"}),
}


@pytest.mark.parametrize("pack_id", sorted(SHAPE_RE_KEYED))
def test_keys_the_declared_shapes_found_off_their_printed_line_are_re_keyed(pack_id):
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    field_of = {f.line: f.field for f in pack.fields}
    now, gone = SHAPE_RE_KEYED[pack_id]
    assert {k: field_of.get(k) for k in now} == now
    assert not gone & set(field_of)
    refs = " ".join([*pack.relations, *pack.cross_form])
    assert not set(re.findall(r"[\w.]+", refs)) & gone


# Phase K JK10 (2026-10-24), P-031: a box of line N the face does not number is keyed "N.<what>", never "Na"; the box
# the face numbers N keeps "N". The blind adjudication found these five packs' keys off the printed designator.
RE_KEYED = {
    "states/ok/2023/form511": {"4": "511 Part 1 4b", "4.description": "511 Part 1 4a",
                               "40.penalty": "511 Part 5 40a", "40.interest": "511 Part 5 40b"},
    "states/ok/2024/form511": {"4": "511 Part 1 4b", "4.description": "511 Part 1 4a",
                               "41.penalty": "511 Part 5 41a", "41.interest": "511 Part 5 41b"},
    "states/ok/2025/form511": {"4": "511 Part 1 4b", "4.description": "511 Part 1 4a",
                               "41a": "511 Part 5 41a", "41b": "511 Part 5 41b"},   # 2025 prints 41(a) / 41(b)
    **{f"states/va/{y}/va760": {"17": "17a Spouse Tax Adjustment Dollar Amount",
                                "17.spouse_vagi": "17. Spouse Tax Adjustment"} for y in (2023, 2024, 2025)},
    "states/wi/2023/wi_form1": {"14": "14a", "14.federal_credit": "14"},
}
GONE = {"states/ok/2023/form511": {"4a", "4b", "40a", "40b"}, "states/ok/2024/form511": {"4a", "4b", "41a", "41b"},
        "states/ok/2025/form511": {"4a", "4b"}, **{f"states/va/{y}/va760": {"17a"} for y in (2023, 2024, 2025)},
        "states/wi/2023/wi_form1": {"14a"}}


@pytest.mark.parametrize("pack_id", sorted(RE_KEYED))
def test_p031_unnumbered_boxes_of_a_line_are_keyed_by_what_they_hold(pack_id):
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    field_of = {f.line: f.field for f in pack.fields}
    assert {k: field_of.get(k) for k in RE_KEYED[pack_id]} == RE_KEYED[pack_id]
    assert not GONE[pack_id] & set(field_of), f"{pack_id} still keys {sorted(GONE[pack_id] & set(field_of))}"
    refs = " ".join([*pack.relations, *pack.cross_form])
    assert not set(re.findall(r"[\w.]+", refs)) & GONE[pack_id]


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_va760_line_18_subtracts_the_sta_amount_now_keyed_17(year):
    """Phase K JK10 (2026-10-24): with the STA amount box keyed "17", line 18 is declared as the face prints it,
    "18. Net Amount of Tax - Subtract Line 17 from Line 16" (no floor printed); the inline VAGI box
    (17.spouse_vagi) takes no part."""
    from taxfill_core.schemas.formpack import load_pack
    from taxfill_core.verify import relations

    pack = load_pack(REPO / "formpacks" / f"states/va/{year}/va760" / "pack.yaml")
    rel = "18 == 16 - 17"
    assert rel in pack.relations
    status = {c.relation: c.status for c in relations(pack, {"16": 2400, "17": 150, "17.spouse_vagi": 30000,
                                                             "18": 2250})}
    assert status[rel] == "PASS"
    assert {c.relation: c.status for c in relations(pack, {"16": 2400, "17": 150, "18": 2400})}[rel] == "FAIL"


@pytest.mark.network
@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_va760_the_face_prints_line_18_as_declared(year):
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    text = L.face_text(fetch_pack_blank(load_pack(REPO / "formpacks" / f"states/va/{year}/va760" / "pack.yaml")))
    line18 = text[text.index("18. Net Amount of Tax"):][:120]
    assert line18.startswith("18. Net Amount of Tax - Subtract Line 17 from Line 16")
    assert not re.search(r"zero|less than|enter 0|-0-", line18[:60], re.I)


# ── network: the gate on every shipped pack ─────────────────────────────────


@pytest.mark.network
@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_every_numbered_key_equals_the_line_printed_beside_its_widget(pack_id):
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    blank = fetch_pack_blank(load_pack(REPO / "formpacks" / pack_id / "pack.yaml"))
    res = L.check_pack(pack_id, blank, CONVENTIONS)
    exceptions = L.load_exceptions()
    bad = [f"{r.id}: the anchor reads {r.widget.printed_line!r} beside it; the pack binds {r.claims} "
           f"(evidence {r.widget.evidence})" for r in res.unexcused(exceptions)]
    stale = res.stale(exceptions)
    checked, lines = res.coverage
    cover = L.ledger_problems(pack_id, checked, lines, L.load_ledger(), res.mapped, res.dark, res.declare,
                              res.unread, res.blind)
    assert not cover, cover[0]
    assert not bad and not stale, (
        f"{pack_id}: {len(bad)} numbered key(s) off the line printed beside the widget (P-031/P-032). Re-key or "
        f"re-bind the pack to the printed row, or, when a blind check of the row finds the key right, add a row "
        f"naming the widget (pack, field, widget, line, anchor) to a family of "
        f"formpacks/label_adjacency_exceptions.yaml (scripts/label_adjacency.py --pack {pack_id} --out <scratch dir> "
        f"writes the crops):\n" + "\n".join(bad)
        + (f"\nstale exception rows (they match no live disagreement any more; remove them): {stale}" if stale
           else ""))


@pytest.mark.network
@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_no_ok_row_holds_an_undeclared_key_the_anchor_can_read(pack_id):
    """Fixer round 5, THE DECLARE-ME RULE as an invariant over every pack: a row at or above the floor holds no
    undeclared line-like key beside whose widget the anchor reads a printed line (the gate could compare it and
    compares nothing), and every row's declare list names exactly the families of such keys."""
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    res = L.check_pack(pack_id, fetch_pack_blank(load_pack(REPO / "formpacks" / pack_id / "pack.yaml")),
                       CONVENTIONS)
    row = LEDGER.rows[pack_id]
    assert row.declare == res.declare
    if not L.below_floor(row.checked, row.lines, LEDGER.floor, row.dark, row.declare):
        assert not res.readable, (
            f"{pack_id} reads OK, yet the anchor reads a printed line beside undeclared keys {res.readable}: declare "
            "their shape in formpacks/key_shapes.yaml (checked on the face) or list them in the ledger's not_lines "
            "with the reason they name no line")


@pytest.mark.network
def test_without_its_shape_a_readable_worksheet_puts_the_pack_below_the_floor(monkeypatch):
    """The round-4 verifier's MAJOR: AZ 140 2023's ws3_1c..ws3_7c (the anchor reads 1c..7c beside them) were
    undeclared yet the pack read OK and a planted 3-cycle passed. Without the shape the declare-me rule now names
    the family and the verdict is PARTIAL; with it, a 3-cycle is caught (PLANTED)."""
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pid = "states/az/2023/az140"
    blank = fetch_pack_blank(load_pack(REPO / "formpacks" / pid / "pack.yaml"))
    monkeypatch.setattr(L, "SHAPES", [s for s in SHAPES if s.id != "az140-charitable-worksheet"])
    res = L.check_pack(pid, blank, CONVENTIONS)
    checked, lines = res.coverage
    assert not checked < LEDGER.floor * lines                         # the fraction alone reads OK ...
    assert res.declare == ("ws#_#",) and res.readable["ws3_4c_add_1c_3c"] == ("4c",)
    assert "ws#_#" in res.dark      # and the seven keys are one prefix family now, so the dark rule names it too
    verdict = L.coverage_verdict(checked, lines, LEDGER.floor, res.dark, res.declare)
    assert verdict.startswith("PARTIAL") and "ws#_#" in verdict     # ... and the declare-me rule says PARTIAL


def test_the_ledger_counts_the_boxes_the_anchor_reads_no_line_beside():
    """Fixer round 5: the residue no line check sees — a box the anchor reads no line beside, in any family — is
    counted per pack (Form 8962's monthly table, AZ 140's page-4/5 rows)."""
    assert all(r.unread is not None and 0 <= r.unread <= r.lines - r.checked for r in LEDGER.rows.values())
    for pid in ("federal/2025/f8962", "states/az/2023/az140"):
        assert LEDGER.rows[pid].unread >= 20, pid


def test_what_the_gate_cannot_see_is_one_list_in_three_places_and_counted_in_every_row():
    """Fixer round 6: the four blind spots are listed in the ledger header, CONVENTIONS.md and the script's
    docstring, and every ledger row counts each of them (the network gate keeps the counts exact)."""
    header = (REPO / "formpacks" / "label_adjacency_coverage.yaml").read_text().partition("\npacks:\n")[0]
    conventions = (REPO / "formpacks" / "CONVENTIONS.md").read_text()
    for text in (header, conventions, L.__doc__):
        assert "cannot see" in text.lower()
        for col in ("same_row", "unread", "cross_section", "descriptive"):
            assert col in text, col
        assert "same-row column swap" in text.lower() and "same line number" in text.lower()
        assert "section-aware" in text            # the open item is named
    assert "all 11 misses were same-row column swaps" not in conventions
    for r in LEDGER.rows.values():
        assert None not in (r.same_row, r.cross_section, r.descriptive)
        assert r.same_row <= r.checked and r.cross_section <= r.checked
    # the re-verifier's cross-section packs and descriptive keys are counted
    for pid in SAMENUM:
        assert LEDGER.rows[pid].cross_section >= 3, pid
    for pid in ("states/ut/2024/tc40", "states/ia/2023/ia1040", "states/ny/2025/it203", "states/va/2025/va760"):
        assert LEDGER.rows[pid].descriptive >= 1, pid


def test_mt_2023_form2_reads_partial_with_its_reason():
    """Fixer round 6: MT Form 2 2023's exemption rows a-d (16a.a ... 16d.b) are lines the face prints only as letters
    — no not_lines family hides them, so the pack is PARTIAL and its row says why."""
    row = LEDGER.rows["states/mt/2023/form2"]
    assert L.below_floor(row.checked, row.lines, LEDGER.floor, row.dark, row.declare)
    assert row.declare == ("#",) and row.reason == "shape-not-declared"
    assert "cannot express a line that is only a letter" in row.note and "65a" in row.note
    assert "Add lines a through c" in row.note


@pytest.mark.network
@pytest.mark.parametrize("conv", CONVENTIONS, ids=lambda c: c.id)
def test_each_column_convention_holds_on_its_own_blanks(conv):
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    for pid in conv.packs:
        blank = fetch_pack_blank(load_pack(REPO / "formpacks" / pid / "pack.yaml"))
        assert L.convention_problems(conv, blank) == [], pid
        res = L.check_pack(pid, blank, CONVENTIONS)
        mapped = [r for r in res.rows if conv.id in r.via.values()]
        assert mapped and all(r.agrees for r in mapped), f"{conv.id} on {pid}: {len(mapped)} mapped widgets"


@pytest.mark.network
def test_the_convention_face_check_refuses_a_real_sub_line_and_an_unprinted_header():
    import dataclasses

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    conv = next(c for c in CONVENTIONS if c.id == "de-pit-res-2023")
    blank = fetch_pack_blank(load_pack(REPO / "formpacks" / "states/de/2023/pit_res" / "pack.yaml"))
    wide = dataclasses.replace(conv, lines=L.parse_lines("1-58"), header=(*conv.header, "COLUMN Z"))
    problems = L.convention_problems(wide, blank)
    assert any("'COLUMN Z'" in p for p in problems)
    assert any("'8a', '8b', '26a', '26b'" in p for p in problems)


@pytest.mark.network
@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.id)
def test_each_key_shape_holds_on_its_own_blanks(shape):
    """Phase K JK10 (2026-10-24), fixer round 2: every line a declared shape maps a key to is printed on that pack's
    face, and the widgets it brings into the gate agree (or are adjudicated in the exceptions table)."""
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    exceptions = L.load_exceptions()
    for pid in shape.packs:
        pack = load_pack(REPO / "formpacks" / pid / "pack.yaml")
        blank = fetch_pack_blank(pack)
        assert L.shape_problems(shape, pid, blank, [f.line for f in pack.fields]) == [], pid
        res = L.check_pack(pid, blank, CONVENTIONS)
        mapped = [r for r in res.rows if shape.id in r.via.values()]
        assert mapped, f"{shape.id}: the gate compares none of {pid}'s widgets"
        assert not [r.id for r in res.unexcused(exceptions) if r in mapped]


@pytest.mark.network
def test_the_shape_face_check_refuses_a_line_the_face_does_not_print():
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    shape = next(s for s in SHAPES if s.id == "ny-it203-line-boxes")
    blank = fetch_pack_blank(load_pack(REPO / "formpacks" / "states/ny/2025/it203" / "pack.yaml"))
    assert L.shape_problems(shape, "states/ny/2025/it203", blank, ["1_wages_fed", "999_fake_fed"]) == [
        "ny-it203-line-boxes maps keys of states/ny/2025/it203 to lines the blank does not print: ['999'] "
        "(e.g. ['999_fake_fed'])"]
    assert L.shape_problems(shape, "states/ny/2025/it203", blank, ["dep0_ssn"]) == [
        "ny-it203-line-boxes maps no key of states/ny/2025/it203"]
    # fixer round 3: a column shape's headings must be printed on the face
    import dataclasses

    ms = next(s for s in SHAPES if s.id == "ms-80-105-columns")
    ms_blank = fetch_pack_blank(load_pack(REPO / "formpacks" / "states/ms/2025/f80105" / "pack.yaml"))
    assert L.shape_problems(ms, "states/ms/2025/f80105", ms_blank, ["13.a", "13.b"]) == []
    wrong = dataclasses.replace(ms, header=(*ms.header, "Column C (Dependent)"))
    assert L.shape_problems(wrong, "states/ms/2025/f80105", ms_blank, ["13.a"]) == [
        "ms-80-105-columns: header 'Column C (Dependent)' is not printed on states/ms/2025/f80105's blank"]


PLANTED = {  # three line-bearing keys per pack the gate checked on NO widget before their shape was declared
    "states/ny/2025/it203": ("1_wages_fed", "2_taxable_interest_fed", "3_ordinary_dividends_fed"),
    "states/nj/2025/nj1040": ("line15_d01", "line16a_d01", "line17_d01"),
    "states/ca/2025/sched_ca_540nr": ("B3_A", "B4_A", "B5_A"),
    # fixer round 3: the round-2 verifier's plants, which passed with verdict OK under the circular denominator
    "states/ms/2025/f80105": ("13.a", "14.a", "15.a"),
    "states/ky/2025/form740": ("5.a", "6.a", "7.a"),
    "states/ar/2025/ar1000f": ("8.a", "10.a", "11.a"),
    "states/mt/2023/form2": ("7.a", "8.a", "9.a"),
    # fixer round 4: the round-3 verifier's plants inside wholly undeclared schedules, which passed with verdict OK
    "states/oh/2023/it1040_oh": ("schedITbus_3", "schedITbus_2", "schedITbus_13"),
    "states/oh/2025/it1040_oh": ("schedITbus_1", "schedITbus_2", "schedITbus_14"),
    "states/mt/2023/form2#ehrc": ("ehrc.15", "ehrc.16", "ehrc.18"),
    "states/mt/2023/form2#upint": ("upint.1", "upint.2", "upint.5"),
    # fixer round 5: the round-4 verifier's plants among undeclared keys the anchor reads (each its own round-4
    # family, or a family under the 5-key threshold), which passed with verdict OK
    "states/az/2023/az140#ws3": ("ws3_1c_gifts_cash_or_check", "ws3_2c_other", "ws3_4c_add_1c_3c"),
    "states/az/2023/az140py#ws3": ("ws3_3c_carryover", "ws3_5c_credit_contributions", "ws3_7c_multiply_by_31pct"),
    "states/az/2025/az140#ws3": ("ws3_1c_gifts_cash_or_check", "ws3_5c_credit_contributions",
                                 "ws3_6c_subtract_5c_from_4c"),
    "states/mt/2023/form2#ltc": ("ltc.1", "ltc.2", "ltc.3"),
    "states/mt/2023/form2#status2a": ("status2a.1.b", "status2a.2.b", "status2a.4.b"),
    "states/ny/2025/it201": ("D2_2_months_you_in_yonkers", "D2_3_months_spouse_in_yonkers", "F_1_months_you_in_nyc"),
    # (MD 502's filing status boxes are one radio field told apart by on_state, and f8863's questions print only
    # (2) and (3) on both 22a and 22b, so a 3-cycle there always pairs two boxes of one designator: not planted)
}


@pytest.mark.network
@pytest.mark.parametrize("pack_id", sorted(PLANTED))
def test_a_planted_three_cycle_among_newly_shaped_keys_is_caught(pack_id):
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    a, b, c = PLANTED[pack_id]
    pack_id = pack_id.partition("#")[0]
    pack = load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    blank = fetch_pack_blank(pack)
    keys = L.B.pack_keys(pack)
    field_of = {str(k["key"]): k["field"] for k in keys}
    rot = {a: field_of[b], b: field_of[c], c: field_of[a]}
    planted = [dict(k, field=rot.get(str(k["key"]), k["field"])) for k in keys]
    res = L.check_blank(pack_id, blank, planted, pack.acroform_root or "", CONVENTIONS)
    flagged = {k for r in res.unexcused(L.load_exceptions()) for k in r.claims}
    assert {a, b, c} <= flagged
    # without their shape the keys name no line, which is how the same rotation passed unseen before
    assert all(L.claim_line(pack_id, k, CONVENTIONS, shapes=[]) == (None, None) for k in (a, b, c))


@pytest.mark.network
def test_mt_2023_form2_exemption_rows_are_read_beside_65a_65b_and_name_the_declare_family():
    """Fixer round 6: on the face, the anchor reads "65a" / "65b" (the "65 or older" box text) beside exemption rows a
    and b, so the declare-me rule names their family and the verdict is PARTIAL."""
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pid = "states/mt/2023/form2"
    res = L.check_pack(pid, fetch_pack_blank(load_pack(REPO / "formpacks" / pid / "pack.yaml")), CONVENTIONS)
    assert {"16a.a", "16b.a", "16b.b"} <= set(res.readable) and res.readable["16a.a"] == ("65a",)
    assert {f"16{r}.{c}" for r in "bcd" for c in "ab"} | {"16a.a"} <= res.undeclared
    assert res.declare == ("#",)
    checked, lines = res.coverage
    assert L.coverage_verdict(checked, lines, LEDGER.floor, res.dark, res.declare).startswith("PARTIAL")


# Fixer round 6: the round-5 re-verifier's 3-cycles among CHECKED keys of sections that print the same line number
# (each passed the gate in a pack that reads OK). Blind spot (c): the plant still passes — and its keys are counted.
SAMENUM = {
    "federal/2026/sched_1a": ("1", "28b.original_use.yes", "28a.original_use.yes"),
    "states/ca/2023/sched_ca_540": ("B7_A", "7_A", "II7_A"),
    "states/ca/2024/sched_ca_540": ("B7_A", "7_A", "II7_A"),
    "states/mt/2023/form2": ("3a.a", "pension.3a.a", "liability.3a.a"),
    "states/mt/2024/form2": ("1", "tax_calc.1", "sched1_part2.1"),
    "states/mt/2025/form2": ("2", "tax_calc.2", "sched1_part2.2"),
    "states/ny/2023/it201": ("F_2_months_spouse_in_nyc", "E_2_days_in_nyc", "D2_2_months_you_in_yonkers"),
    "states/ny/2025/it201": ("F_2_months_spouse_in_nyc", "E_2_days_in_nyc", "D2_2_months_you_in_yonkers"),
    "states/oh/2024/it1040_oh": ("1_neg", "schedA_1", "schedITbus_1"),
    "states/oh/2025/it1040_oh": ("3", "schedA_3", "schedITbus_3"),
    "states/ok/2023/form511": ("2", "sch_511b.2", "sch_511a.2"),
    "states/ok/2025/form511": ("1", "sch_511b.1", "sch_511a.1"),
    "states/wi/2024/wi_form1": ("1", "sch2_1_yourself", "sch1_1"),
    "states/wi/2025/wi_form1": ("2", "sch2_2_yourself", "sch1_2"),
}


@pytest.mark.network
@pytest.mark.parametrize("pack_id", sorted(SAMENUM))
def test_a_planted_cross_section_swap_passes_and_is_counted(pack_id):
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    a, b, c = SAMENUM[pack_id]
    pack = load_pack(REPO / "formpacks" / pack_id / "pack.yaml")
    blank = fetch_pack_blank(pack)
    keys = L.B.pack_keys(pack)
    field_of = {str(k["key"]): k["field"] for k in keys}
    rot = {a: field_of[b], b: field_of[c], c: field_of[a]}
    res = L.check_blank(pack_id, blank, [dict(k, field=rot.get(str(k["key"]), k["field"])) for k in keys],
                        pack.acroform_root or "", CONVENTIONS)
    flagged = {k for r in res.unexcused(L.load_exceptions()) for k in r.claims}
    assert not {a, b, c} & flagged                      # the line check cannot see it ...
    assert {a, b, c} <= res.shared_line_keys[1]         # ... and the cross_section column counts all three
    assert res.cross_section == LEDGER.rows[pack_id].cross_section     # (a swap leaves the count unchanged)


@pytest.mark.network
@pytest.mark.parametrize("year", [2023, 2024])
def test_a_planted_three_cycle_inside_a_dark_family_leaves_the_pack_partial(year):
    """Fixer round 4: WV Schedule M's item (b) boxes are declared but the anchor reads no line beside them, so a
    3-cycle among them is not caught — and the pack's verdict says so (PARTIAL, the family named), never OK."""
    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pid = f"states/wv/{year}/it140"
    pack = load_pack(REPO / "formpacks" / pid / "pack.yaml")
    blank = fetch_pack_blank(pack)
    keys = L.B.pack_keys(pack)
    field_of = {str(k["key"]): k["field"] for k in keys}
    trio = sorted(k for k in field_of if L.tail_family(k) == "sch_m.#.b")[:3]
    a, b, c = trio
    rot = {a: field_of[b], b: field_of[c], c: field_of[a]}
    res = L.check_blank(pid, blank, [dict(k, field=rot.get(str(k["key"]), k["field"])) for k in keys], "",
                        CONVENTIONS)
    checked, lines = res.coverage
    assert "sch_m.#.b" in res.dark
    verdict = L.coverage_verdict(checked, lines, LEDGER.floor, res.dark)
    assert verdict.startswith("PARTIAL") and "sch_m.#.b" in verdict


# ── network: the two historical rotations (KG6 fixtures, knowledge/anchor/mandatory) ──

MUST_FLAG = {
    "me_1040me_2023": {"21", "22", "23"},
    "al_form40_2023": {"20_amount", "21_amount", "34_total_donations", *(str(n) for n in range(22, 34))},
}


@pytest.mark.network
@pytest.mark.parametrize("case", sorted(MUST_FLAG))
def test_the_gate_catches_both_historical_base_pack_rotations(case):
    from taxfill_core.fetch import fetch_blank

    fixture = yaml.safe_load((REPO / "knowledge" / "anchor" / "mandatory" / f"{case}.yaml").read_text())
    assert set(fixture["must_flag"]) == MUST_FLAG[case]
    blank = fetch_blank(fixture["source_url"], sha256=fixture["pdf_sha256"])
    result, verdict = L.check_mandatory(fixture, blank)
    assert verdict["missed"] == [] and set(verdict["flagged"]) == MUST_FLAG[case], verdict
    # and the same keys, as the corrected pack binds them today, pass
    today = {"me_1040me_2023": "states/me/2023/f1040me", "al_form40_2023": "states/al/2023/al40"}[case]
    fixed = L.check_pack(today, blank, CONVENTIONS)
    assert not [r for r in fixed.rows if not r.agrees and set(r.claims) & {"21", "22", "23", "20a", "20b"}]


# ── network: P-031 / P-032's dedicated gutter reads (folded in from the per-form tests) ──

AL40_PACKS = sorted((REPO / "formpacks" / "states" / "al").glob("*/al40/pack.yaml"))
ME_PACKS = sorted((REPO / "formpacks" / "states" / "me").glob("*/f1040me/pack.yaml"))
AL_NUMBERED = re.compile(r"^\d+[ab]?$")


@pytest.mark.network
@pytest.mark.parametrize("path", AL40_PACKS, ids=lambda p: p.parent.parent.name)
def test_p031_page1_keys_equal_the_printed_line_numbers(path: Path):
    import pypdf
    import pypdfium2 as pdfium

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(path)
    blank = fetch_pack_blank(pack)
    keys_of: dict[str, list[str]] = {}
    for f in pack.fields:
        if AL_NUMBERED.match(f.line):
            keys_of.setdefault(f.field, []).append(f.line)
    textpage = pdfium.PdfDocument(str(blank))[0].get_textpage()
    checked, wrong = 0, []
    for annot in pypdf.PdfReader(str(blank)).pages[0].get("/Annots", []) or []:
        annot = annot.get_object()
        name = annot.get("/T") or (annot["/Parent"].get_object().get("/T") if "/Parent" in annot else None)
        for key in keys_of.get(str(name), []):
            x0, y0, _, y1 = (float(v) for v in annot["/Rect"])
            gutter = textpage.get_text_bounded(left=x0 - 28, bottom=y0, right=x0, top=y1)
            printed = re.match(r"\s*(\d+[ab]?)", gutter)
            checked += 1
            if not printed or printed.group(1) != key:
                wrong.append(f"key {key!r} ({name}) sits beside printed {gutter.strip()!r}")
    assert not wrong, "\n".join(wrong)
    assert checked == 33, f"{checked} numbered page-1 keys found; the face prints 33 (5a, 5b, 6-19, 20a, 20b, 21-35)"


@pytest.mark.network
@pytest.mark.parametrize("path", ME_PACKS, ids=lambda p: p.parent.parent.name)
def test_p032_the_number_printed_left_of_each_widget_equals_its_key(path: Path):
    import pypdf
    import pypdfium2 as pdfium

    from taxfill_core.fetch import fetch_pack_blank
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(path)
    blank = fetch_pack_blank(pack)
    field_of = {f.line: f.field for f in pack.fields}
    key_of = {field_of[k]: k for k in ("21", "22", "23")}
    rects: dict[str, tuple[int, list[float]]] = {}
    for page_no, page in enumerate(pypdf.PdfReader(str(blank)).pages):
        for annot in page.get("/Annots", []) or []:
            annot = annot.get_object()
            name = annot.get("/T") or (annot["/Parent"].get_object().get("/T") if "/Parent" in annot else None)
            if str(name) in key_of:
                rects[str(name)] = (page_no, [float(v) for v in annot["/Rect"]])
    assert set(rects) == set(key_of), f"widgets bound to lines 21-23 not all found on the blank: {sorted(rects)}"
    doc = pdfium.PdfDocument(str(blank))
    textpages: dict[int, object] = {}
    wrong = []
    for name, key in key_of.items():
        page_no, (x0, y0, _, y1) = rects[name]
        textpage = textpages.setdefault(page_no, doc[page_no].get_textpage())
        # The right-hand column prints "21." / "22." / "23." in the ~45 pt gutter left of each money box.
        gutter = textpage.get_text_bounded(left=x0 - 45, bottom=y0, right=x0, top=y1)
        printed = re.search(r"(\d+[a-z]?)\.", gutter)
        if not printed or printed.group(1) != key:
            wrong.append(f"key {key!r} -> {name!r} sits beside printed {gutter.strip()!r}")
    assert not wrong, "\n".join(wrong)
    # the generic gate reads the same three rows
    res = L.check_pack(L.B.pack_id(path), blank, CONVENTIONS)
    assert {k for r in res.rows if r.agrees for k in r.claims} >= {"21", "22", "23"}


@pytest.mark.network
def test_a_not_lines_key_beside_a_line_the_anchor_reads_counts_in_descriptive():
    """The final review's second major: MT Form 2 2024 prints '4 Account Type ... 529/529A deposit amount' and the
    anchor reads 4 beside the dd529.4.529 box, while the direct-deposit-529 not_lines family leaves the key out of the
    comparison. A key the gate compares nothing for, beside a line the anchor reads, counts in (d)."""
    from taxfill_core.fetch import fetch_pack_blank  # noqa: PLC0415
    from taxfill_core.schemas.formpack import load_pack  # noqa: PLC0415

    pack_id = "states/mt/2024/form2"
    blank = fetch_pack_blank(load_pack(REPO / "formpacks" / pack_id / "pack.yaml"))
    res = L.check_pack(pack_id, blank, CONVENTIONS)
    assert L.not_line_family("dd529.4.529", pack=pack_id) is not None
    assert "dd529.4.529" in res.descriptive and "4" in res.descriptive["dd529.4.529"]
