"""Phase K JK15b (2026-10-25): the JK19 pilot's checkbox defects D3 and D5 (docs/dev/JK19-PILOT.md) on the pilot's own
blanks, which no pack ships, so these tests download them (network-marked; each is pinned by its sha256 and skips
when it cannot be fetched or its agency has replaced it). The offline synthetic cases of the same shapes are in
test_anchor.py (``test_an_option_box_is_labelled_by_the_caption_on_its_own_right``,
``test_a_stacked_yes_no_pair_anchors_to_its_questions_designator`` and the side-by-side and inline pair cases) and
test_unmapped_fill.py (``test_jk15b_a_hand_written_checkbox_entry_says_which_box_to_mark``).

- D3: a checkbox's label was the caption printed left of it, the previous option's, where a row prints captions
  right of their boxes (Philadelphia's School Income Tax return 2023, OR-40-N 2023's filing status).
- D5: the second box of an IRS stacked Yes/No pair was anchored "none" (Schedule H 2025's c1_1[1], c1_2[1], c1_3[1]
  and c1_4[0]), so line 9 "Yes" could be neither confirmed nor written, and its hand_write entry said only "/2".
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from taxfill_core import anchor as A

# The pilot's blanks: URL and sha256 as docs/dev/JK19-PILOT.md records them (each fetched in all three pilot runs with
# the same digest).
PHILADELPHIA_SIT_2023 = ("https://www.phila.gov/media/20240102133536/2023-School-Income-Tax-return.pdf",
                         "95afef5a9a96679c83c58db90b50c3e88d8db7dc346209729fdcd5bf34f8e88e")
OR_40_N_2023 = ("https://www.oregon.gov/dor/forms/FormsPubs/form-or-40-n_101-048_2023.pdf",
                "3c8df6a2c139fbbda3377198618033991f05b51918240594b2b48a8915fb73fe")
SCHEDULE_H_2025 = ("https://www.irs.gov/pub/irs-pdf/f1040sh.pdf",  # the final 2025 revision (not irs-dft)
                   "d04de932bd7d960ba09b3a913cde9bf35c1deec34c5c9b51cdff8c0b1bfdf83a")
# Phase K JK15b (2026-10-25), the fix wave: blanks the shipped packs pin (formpacks/federal/2025/sched_c, f2555)
SCHEDULE_C_2025 = ("https://www.irs.gov/pub/irs-prior/f1040sc--2025.pdf",
                   "ddf401dbe060467d39f90ad2abf645df1de31512821a150dc68a3882bbf19716")
FORM_2555_2025 = ("https://www.irs.gov/pub/irs-prior/f2555--2025.pdf",
                  "979a90f0f83723a43f7ae8600f38892d5b8e9d85683d357c7c5e4282654fad6a")
SCHEDULE_B_2026_DRAFT = ("https://www.irs.gov/pub/irs-dft/f1040sb--dft.pdf",  # formpacks/federal/2026/sched_b
                         "aa6272f6b3b8a8c6a2aa6ef9d1069f1edb88fb9df4df60278d198da89cdfd93f")
P1 = "topmostSubform[0].Page1[0]."
P2 = "topmostSubform[0].Page2[0]."


def _blank(url: str, sha: str) -> Path:
    from taxfill_core.fetch import FetchError, fetch_blank

    try:
        return fetch_blank(url, sha256=sha)
    except (FetchError, OSError) as exc:  # offline, or the agency replaced the file (the digest no longer matches)
        pytest.skip(f"blank not available: {exc}")


def _options(path: Path, table=None) -> dict[str, A.WidgetAnchor]:
    return {w.field: w for w in A.anchor_widgets(path, table=table).widgets if w.kind in ("checkbox", "radio")}


@pytest.fixture
def checkbox_table(tmp_path):
    """A passing table that licenses checkboxes for the top tier too, so only a cap can keep a box below it."""
    path = tmp_path / "both.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": True,
                                    "thresholds": {"top": 3.0, "med": 2.0}, "top_tier_kinds": ["text", "checkbox"]}))
    return path


@pytest.mark.network
def test_d3_philadelphia_sit_2023_check_boxes_carry_their_own_captions():
    # the pilot: "Amended Return?" labelled "Address Change", "Final Return?" labelled "Amended Return"
    w = _options(_blank(*PHILADELPHIA_SIT_2023))
    assert w["Address Change?"].label == "Address Change"
    assert w["Amended Return?"].label == "Amended Return"
    assert w["Final Return?"].label.startswith("Final Return")
    assert all("label_right" in w[k].evidence for k in ("Address Change?", "Amended Return?", "Final Return?"))


@pytest.mark.network
def test_d3_or_40_n_2023_filing_status_boxes_carry_their_own_captions():
    # the pilot: Check Box4 (married filing jointly) labelled "Single", Check Box6 labelled "1"
    w = _options(_blank(*OR_40_N_2023))
    got = {k: (w[k].printed_line, w[k].label) for k in ("Check Box3", "Check Box4", "Check Box5", "Check Box6",
                                                         "Check Box7")}
    assert got == {
        "Check Box3": ("1", "Single"),
        "Check Box4": ("2", "Married filing jointly"),
        "Check Box5": ("3", "Married filing separately (enter spouse information above)"),
        "Check Box6": ("4", "Head of household (with qualifying dependent)"),
        "Check Box7": ("5", "Qualifying surviving spouse"),
    }
    assert w["or-40-n-p6-12"].label == "Blind" and w["or-40-n-p6-11"].label == "65 or older"  # line 38's age boxes


@pytest.mark.network
def test_d5_schedule_h_2025_stacked_yes_no_pairs_anchor_to_their_question(checkbox_table):
    w = _options(_blank(*SCHEDULE_H_2025), table=checkbox_table)
    pairs = {  # Yes box, No box, the question's printed designator
        "A": (P1 + "c1_1[0]", P1 + "c1_1[1]"),
        "B": (P1 + "c1_2[0]", P1 + "c1_2[1]"),
        "C": (P1 + "c1_3[1]", P1 + "c1_3[0]"),  # question C prints "No." above "Yes."
        "9": (P1 + "c1_4[0]", P1 + "c1_4[1]"),  # line 9 too: the pilot's "Yes" box c1_4[0] was anchored none
        "27": (P2 + "c2_5[0]", P2 + "c2_5[1]"),
    }
    for line, (yes, no) in pairs.items():
        assert (w[yes].printed_line, w[yes].label) == (line, "Yes"), (yes, w[yes])
        assert (w[no].printed_line, w[no].label) == (line, "No"), (no, w[no])
        for box, partner in ((yes, no), (no, yes)):
            assert f"yes_no_pair:{partner}" in w[box].evidence
            # anchored, so it can be confirmed on the sweep and written; never the top tier (one line, two boxes)
            assert w[box].confidence not in (A.NONE, A.TOP), (box, w[box])
    # page 2's side-by-side pairs under the "Yes  No" column header: lines 10-12
    for i, line in ((1, "10"), (2, "11"), (3, "12")):
        prefix = P2 + ("Line10[0]." if i == 1 else "")
        yes, no = w[f"{prefix}c2_{i}[0]"], w[f"{prefix}c2_{i}[1]"]
        assert (yes.printed_line, yes.label, no.printed_line, no.label) == (line, "Yes", line, "No")
        assert A.TOP not in (yes.confidence, no.confidence)


@pytest.mark.network
def test_d5_schedule_h_2025_line_9_yes_hand_write_entry_names_its_box(tmp_path):
    """End to end through the pack-less fill, under the committed benchmark table: line 9 "Yes" is anchored now, so
    it comes back for the sweep confirmation (not refused), and the entry says which box: page 1, line 9, "Yes", the
    lower box of the pair, its sweep number. Confirmed, it is written."""
    from taxfill_core.fetch import fetch_unmapped_blank
    from taxfill_core.unmapped import describe_unmapped, fill_unmapped

    url, sha = SCHEDULE_H_2025
    kw = {"workspace_root": tmp_path / "ws", "cache_dir": tmp_path / "cache"}
    blank = fetch_unmapped_blank(url, tax_year=2025, jurisdiction="federal", local_blank=_blank(url, sha), **kw)
    yes = P1 + "c1_4[0]"
    desc = describe_unmapped(blank, sweep_path=tmp_path / "sweep.pdf")
    assert yes not in {h["field"] for h in desc["hand_write"]}  # the pilot: refused "unanchored"
    index = next(f["index"] for f in desc["fields"] if f["name"] == yes)
    common = {"source_url": blank.source_url, "tax_year": 2025, "jurisdiction": "federal", **kw}
    result = fill_unmapped(blank.sha256, values={yes: "yes"}, out_path=tmp_path / "draft.pdf", **common)
    [entry] = result["hand_write"]
    assert (entry["field"], entry["reason"], entry["page"], entry["printed_line"], entry["label"]) == (
        yes, "needs_confirmation", 1, "9", "Yes")
    assert entry["sweep_index"] == index and f"#{index}" in entry["mark"]
    [box] = entry["boxes"]
    assert box["page"] == 1 and box["on_state"] == entry["value"]
    no_box = next(f for f in desc["fields"] if f["name"] == P1 + "c1_4[1]")["widgets"][0]["rect"]
    assert box["rect"][1] < no_box[1] and box["from_top_pct"] > 0  # "Yes" is the lower box of line 9's pair
    confirmed = fill_unmapped(blank.sha256, values={yes: "yes"}, out_path=tmp_path / "draft2.pdf",
                              confirmed_fields=[yes], **common)
    assert confirmed["hand_write"] == [] and confirmed["written"] == {yes: entry["value"]}


@pytest.mark.network
@pytest.mark.parametrize(("blank", "page", "pairs"), [
    # Schedule C 47a / b: "b" hung from line 46 ("46b") because the joined "47a" ends right of it
    (SCHEDULE_C_2025, P2, {"47a": ("c2_7[0]", "c2_7[1]"), "47b": ("c2_8[0]", "c2_8[1]")}),
    # Form 2555 13a / b the same way ("11b"), and 15c / 15d gain their lines
    (FORM_2555_2025, P1, {"13b": ("c1_19[0]", "c1_19[1]"), "15c": ("c1_21[0]", "c1_21[1]"),
                          "15d": ("c1_23[0]", "c1_23[1]")}),
], ids=["schedule_c_2025", "f2555_2025"])
def test_jk15b_a_yes_no_pair_under_a_joined_head_takes_its_own_sub_line(blank, page, pairs):
    """Phase K JK15b (2026-10-25), the verifier's finding: the "No" box borrowed its "Yes" partner's wrong line at med
    (pair_of), so a fill asked the user to confirm "line 46b" for Schedule C's 47b. Both boxes now carry the printed
    sub-line, and the text widgets of those rows take it too (Form 2555 line 12b, not 11b)."""
    w = {x.field: x for x in A.anchor_widgets(_blank(*blank)).widgets}
    for line, (yes, no) in pairs.items():
        assert (w[page + yes].printed_line, w[page + yes].label) == (line, "Yes"), w[page + yes]
        assert (w[page + no].printed_line, w[page + no].label) == (line, "No"), w[page + no]
    if blank is FORM_2555_2025:
        assert w[P1 + "f1_17[0]"].printed_line == "12b"


@pytest.mark.network
def test_jk15b_schedule_b_2026_draft_line_7a_pair_keeps_its_sub_letter():
    """Phase K JK15b (2026-10-25): the draft's "7" and "a" touch with the "a" a hair left of the "7"'s edge, and the
    line 7a Yes/No pair took "7" (pair_head:7) while 2023 and 2025 came out 7a."""
    sub = P1 + "TagcorrectingSubform[0]."
    w = {x.field: x for x in A.anchor_widgets(_blank(*SCHEDULE_B_2026_DRAFT)).widgets}
    yes, no = w[sub + "c1_1[0]"], w[sub + "c1_1[1]"]
    assert (yes.printed_line, yes.label, no.printed_line, no.label) == ("7a", "Yes", "7a", "No"), (yes, no)
