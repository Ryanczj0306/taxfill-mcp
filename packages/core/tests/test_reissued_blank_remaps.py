"""Re-maps onto re-issued blanks (Phase K drift re-map, 2026-10-23).

The weekly freshness run of 2026-10-19 went red on two upstream revisions of pinned blanks:

* Oregon re-issued the 2023 Form OR-40 at the same URL (PDF ModDate 2026-10-14, sha256 6330f72ed7c2d412...).
  The Filing Status radio field ``or-40_p1_33`` and line 54's account-type radio field ``or-40-p6-12`` became
  seven separate checkboxes, ``Check Box1``-``Check Box7``; the old pack's fill of ``filing_status.single``
  raised "field(s) ['or-40_p1_33'] not found" against the re-issue.
* The IRS re-created the 2026 Form 1040-X draft ("Created 10/9/26", sha256 efbdbd1070b300ba...). Page 2 drops
  line 22's direct deposit (22a-22d become "22") and renumbers every widget below it, so names the 8/19/26 map
  bound now name OTHER cells: its ``dependent_1.first_name`` (Row1 ``f2_16``) filled Dependent 3's first-name
  cell and its ``24.original`` (Line24 ``f2_10``) filled line 24's column C, both without a warning.

Each test fills against the RE-ISSUED blank (fetched by its own digest, so the test reads the re-issue whatever
the pack pins), reads the widgets back, and checks each value landed in the box printed beside its caption (and,
for a checkbox set, that no other box of the set is on). Network-marked: the blanks come from the
shared cache, or the network when the cache is empty.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from taxfill_core.fetch import OfflineFetchError, fetch_blank
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import load_pack

REPO = Path(__file__).resolve().parents[3]

OR40_2023 = REPO / "formpacks" / "states" / "or" / "2023" / "or40" / "pack.yaml"
OR40_2023_URL = "https://www.oregon.gov/dor/forms/FormsPubs/form-or-40_101-040_2023.pdf"
OR40_2023_REISSUE_SHA256 = "6330f72ed7c2d412a3c37f1e97181a33236434f90716e2bc3d6b473394416ff0"

F1040X_2026 = REPO / "formpacks" / "federal" / "2026" / "f1040x" / "pack.yaml"
F1040X_DRAFT_URL = "https://www.irs.gov/pub/irs-dft/f1040x--dft.pdf"
F1040X_DRAFT_10_9_26_SHA256 = "efbdbd1070b300ba9a243f9be9f128cc6ee987f8ce39a4aaa9096eef27ff890a"


def _blank(url: str, sha256: str) -> Path:
    try:
        return fetch_blank(url, sha256=sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")


def _widgets(pdf: Path) -> dict[str, list[tuple[int, list[float], str, str]]]:
    """Fully qualified field name -> [(page, rect, /AS, /V)] for every widget of the PDF."""
    out: dict[str, list[tuple[int, list[float], str, str]]] = {}
    for page_no, page in enumerate(PdfReader(pdf).pages, 1):
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            names, value, node = [], None, annot
            while node is not None:
                if "/T" in node:
                    names.append(str(node["/T"]))
                if value is None and "/V" in node:
                    value = str(node["/V"])
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
            out.setdefault(".".join(reversed(names)), []).append(
                (page_no, [float(x) for x in annot["/Rect"]], str(annot.get("/AS", "/Off")), value or ""))
    return out


# (line, page, (x, y) a point inside the box printed beside the caption) — read off a render of the re-issue.
OR40_2023_OPTIONS = {
    "filing_status": [
        ("filing_status.single", 1, (64, 127)),                       # "1. Single"
        ("filing_status.married_filing_jointly", 1, (158, 127)),      # "2. Married filing jointly"
        ("filing_status.married_filing_separately", 1, (296, 127)),   # "3. Married filing separately"
        ("filing_status.head_of_household", 1, (64, 101)),            # "4. Head of household"
        ("filing_status.qualifying_surviving_spouse", 1, (296, 101)),  # "5. Qualifying surviving spouse"
    ],
    "account_type": [
        ("54.account_type.checking", 6, (65, 209)),  # "Checking or"
        ("54.account_type.savings", 6, (65, 184)),   # "Savings"
    ],
}


@pytest.mark.network
@pytest.mark.parametrize("group,line,page,point",
                         [pytest.param(g, *opt, id=opt[0]) for g, opts in OR40_2023_OPTIONS.items() for opt in opts])
def test_or40_2023_reissue_checkbox_lands_beside_its_caption(group, line, page, point, tmp_path):
    pack = load_pack(OR40_2023)
    blank = _blank(OR40_2023_URL, OR40_2023_REISSUE_SHA256)
    filled = tmp_path / "or40.pdf"
    fill_form(pack, {line: True}, blank, filled)

    widgets = _widgets(filled)
    members = {pf.line: pf for pf in pack.fields if pf.group == group}
    assert len(members) == len(OR40_2023_OPTIONS[group])
    chosen = members[line]
    [(w_page, rect, state, _)] = widgets[chosen.field]
    assert (w_page, state) == (page, chosen.on_state)
    x, y = point
    assert rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3], f"{line} binds {chosen.field} at {rect}"
    for other in members.values():
        if other.line != line:
            assert [s for _, _, s, _ in widgets[other.field]] == ["/Off"], f"{other.line} is on with {line}"


def test_or40_2023_pins_the_reissue():
    assert load_pack(OR40_2023).pdf_sha256 == OR40_2023_REISSUE_SHA256


# line -> (value, (x, y) a point inside the cell printed for it) on PDF page 3 (the form's page 2) of the
# Created 10/9/26 draft, read off a render: the line-22/23 boxes, lines 24-25 columns A/B/C, and the dependents
# grid's rows (1)-(4) under the Dependent 1-4 column heads.
_DEP_X = {1: 198, 2: 306, 3: 414, 4: 522}
_DEP_ROW_Y = {"first_name": 564, "last_name": 552, "ssn": 540, "relationship": 528}
F1040X_2026_PAGE2_CELLS = {
    "22": (2201, (540, 684)),                        # "22 Amount of line 21 you want refunded to you"
    "23.estimated_tax_year": ("2027", (306, 672)),     # "applied to your (enter year):"
    "23": (2302, (446, 672)),                        # "estimated tax 23"
    "24.original": (1, (396, 612)), "24.net_change": (2, (468, 612)), "24": (3, (540, 612)),
    "25.original": (4, (396, 600)), "25.net_change": (5, (468, 600)), "25": (6, (540, 600)),
    **{f"dependent_{n}.{cell}": (value, (_DEP_X[n], y))
       for n in _DEP_X
       for cell, y in _DEP_ROW_Y.items()
       for value in [f"99988010{n}" if cell == "ssn" else f"{cell.upper().replace('_', '')}{n}"]},
    "explanation": ("DEMO EXPLANATION", (306, 300)),   # Part II, "Explanation of Changes"
}


@pytest.mark.network
def test_f1040x_2026_reposted_draft_page2_lands_in_the_printed_cells(tmp_path):
    pack = load_pack(F1040X_2026)
    blank = _blank(F1040X_DRAFT_URL, F1040X_DRAFT_10_9_26_SHA256)
    values = {line: value for line, (value, _) in F1040X_2026_PAGE2_CELLS.items()}
    filled = tmp_path / "f1040x.pdf"
    fill_form(pack, values, blank, filled, rehearsal=True)

    widgets = _widgets(filled)
    field_of = {pf.line: f"{pack.acroform_root}.{pf.field}" for pf in pack.fields}
    misplaced = []
    for line, (value, (x, y)) in F1040X_2026_PAGE2_CELLS.items():
        [(page, rect, _, written)] = widgets[field_of[line]]
        inside = page == 3 and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]
        if not inside or written != str(value):
            misplaced.append((line, field_of[line].rsplit(".", 2)[-2:], rect, written))
    assert misplaced == []
    # The direct-deposit row is gone from the face, so no key may survive for it.
    assert {"22a", "22b", "22c.checking", "22c.savings", "22d"}.isdisjoint(field_of)


def test_f1040x_2026_pins_the_reposted_draft():
    pack = load_pack(F1040X_2026)
    assert (pack.pdf_sha256, pack.draft_created) == (F1040X_DRAFT_10_9_26_SHA256, "10/9/26")


# ── Arizona 2025 Form 140, re-issued 2026-11-02 (Phase K re-map 2026-11-05, P-036) ───────────────────────────────

AZ140_2025 = REPO / "formpacks" / "states" / "az" / "2025" / "az140" / "pack.yaml"
AZ140_2025_URL = "https://azdor.gov/sites/default/files/document/FORMS_INDIVIDUAL_2025_140_f.pdf"
AZ140_2025_REISSUE_SHA256 = "2acdda2a07ab46d7f6bd701618e63d1af8d45ac7921c38572a740940437edf84"

# line -> (demo value, the caption azdor's re-issue names the widget by). The re-issue renamed 153 widgets from their
# line number to the row's caption, so the field NAME now states the row; each value must land in a field whose
# name carries the caption, and the six keys renamed on the re-map must sit on the rows their new names say.
AZ140_2025_CAPTIONED = {
    "12": (123456, "Federal adjusted gross income"),
    "home_address": ("1 DEMO ST", "Current Home Address"),
    "29a": (2500, "Exclusion for federal, Arizona state or local government pensions"),
    "oa_C_lump_sum": (10, "Lump-Sum Distributions"),
    "oa_Fa_claim_of_right_prior_years": (11, "Claim of Right Adjustment for Amounts Repaid in Prior Taxable years"),
    "oa_N_amortization_child_care_facility_1990": (12, "Child Care Facility before 1990"),
    "oa_Q_motion_picture_production_costs": (13, "Motion Picture Productions Costs"),
    "os_H_qualified_state_tuition_distributions": (14, "Qualified State Tuition Distributions"),
    "os_J_agricultural_crops_donation": (15, "Agricultural Crops Given to Arizona Charitable Organizations"),
    "os_M_long_term_care_insurance_premiums": (16, "Long-Term Care Insurance Premiums"),
    "ws3_7c_multiply_by_rate": (34, "Multiply line 6C by 34%"),
}
AZ140_2025_IDENTITY = {"tp_first_name_and_initial": "TAYLOR F", "tp_last_name": "DEMO", "tp_ssn": "999887777"}
# the four fields the re-issue gives to TWO printed rows each: never written (P-036)
AZ140_2025_SHARED_FIELDS = ("Partnership Income adjustment", "Married Persons Filing Separate Returns",
                            "Arizona Form 141AZ Schedule K-1 - Fiduciary Adjustment",
                            "Americans with Disabilities Act - Access Expenditures")


def test_az140_2025_pins_the_reissue():
    pack = load_pack(AZ140_2025)
    assert pack.pdf_sha256 == AZ140_2025_REISSUE_SHA256
    assert set(pack.unfillable_lines) == {"16", "27", "oa_A_married_separate", "os_A_married_separate",
                                          "oa_B_141az_k1", "os_B_141az_k1",
                                          "oa_M_disabilities_access", "os_N_americans_disabilities_access"}
    # each entry names the field its row shares, and no line maps one of them
    assert {entry.field for entry in pack.unfillable_lines.values()} == set(AZ140_2025_SHARED_FIELDS)
    assert not {pf.field for pf in pack.fields} & set(AZ140_2025_SHARED_FIELDS)
    # the relation states the printed subtotal (review 2026-11-11): a hand-written line 16 belongs in line 19
    assert "19 == 14 + 15 + 16 + 17 + 18" in pack.relations
    # the signature block's boxes print no number: the old revision's widget names "81".."89" are not keys
    lines = {pf.line for pf in pack.fields}
    assert not lines & {str(n) for n in range(81, 90)}
    assert {"occupation", "spouse_occupation", "preparer_firm_name", "preparer_zip_code", "preparer_phone"} <= lines


@pytest.mark.network
def test_az140_2025_reissue_values_land_in_the_captioned_fields(tmp_path):
    pack = load_pack(AZ140_2025)
    blank = _blank(AZ140_2025_URL, AZ140_2025_REISSUE_SHA256)
    filled = tmp_path / "az140.pdf"
    values = {**AZ140_2025_IDENTITY, "7_filing_status::single": True,
              **{line: value for line, (value, _caption) in AZ140_2025_CAPTIONED.items()}}
    fill_form(pack, values, blank, filled)
    widgets = _widgets(filled)
    field_of = {pf.line: pf.field for pf in pack.fields}
    for line, (value, caption) in AZ140_2025_CAPTIONED.items():
        name = field_of[line]
        assert caption in name, f"{line} binds {name!r}, which does not name {caption!r}"
        [(_page, _rect, _state, on_disk)] = widgets[name]
        assert on_disk.replace(",", "") == str(value), (line, name, on_disk)
    # the filing-status radio's export values are captions now
    [single] = [(st, rect) for _p, rect, st, _v in widgets["Filing Status"] if st != "/Off"]
    assert single[0] == "/Single"
    # the page 2-6 headers mirror the page-1 identity (the shared field could only ever print the last name there)
    assert {v for _p, _r, _s, v in widgets["1c"]} == {"999887777"} and len(widgets["1c"]) == 5
    assert all(v.startswith("T") and v.endswith("DEMO") for _p, _r, _s, v in widgets["1b"]) and len(widgets["1b"]) == 5
    assert widgets["Your Last Name"][0][3] == "DEMO" and widgets["Your SSN"][0][3] == "999887777"
    # the four shared fields stay blank: nothing the pack writes can reach them
    for shared in AZ140_2025_SHARED_FIELDS:
        assert {v for _p, _r, _s, v in widgets[shared]} == {""}, shared


@pytest.mark.network
def test_az140_2025_refuses_a_value_on_a_row_that_shares_its_field(tmp_path):
    pack = load_pack(AZ140_2025)
    blank = _blank(AZ140_2025_URL, AZ140_2025_REISSUE_SHA256)
    with pytest.raises(ValueError, match=r"line\(s\) \['16', 'oa_A_married_separate'\] cannot be written.*hand-write"):
        fill_form(pack, {**AZ140_2025_IDENTITY, "16": 5000, "oa_A_married_separate": 1}, blank, tmp_path / "x.pdf")
    assert not (tmp_path / "x.pdf").exists()



@pytest.mark.network
def test_az140_2025_a_hand_written_line_16_belongs_in_line_19(tmp_path):
    """The review's case (2026-11-11): a filer with a partnership addition. Line 16 is refused, so it is left out
    and hand-written; line 19 ("Add lines 14 through 18") is filled WITH it. verify passes once the amount is
    declared, fails while it is not, and fails a PDF whose shared field was typed into afterwards."""
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

    from taxfill_core.verify import verify_form  # noqa: PLC0415

    pack = load_pack(AZ140_2025)
    blank = _blank(AZ140_2025_URL, AZ140_2025_REISSUE_SHA256)
    filled = tmp_path / "az140.pdf"
    values = {**AZ140_2025_IDENTITY, "7_filing_status::single": True, "12": 100000, "14": 100000, "19": 105000}
    fill_form(pack, values, blank, filled)

    declared = verify_form(pack, filled, expected={**values, "16": 5000, "27": 0})
    line_19 = next(c for c in declared.relations if c.relation.startswith("19 =="))
    assert line_19.status == "PASS" and "16 = 5000" in line_19.detail, line_19.detail
    assert [c.line for c in declared.assertions if c.status == "SKIPPED"] == ["16"]
    assert not [c.detail for c in declared.assertions + declared.relations if c.status == "FAIL"]

    undeclared = verify_form(pack, filled, expected=values)
    line_19 = next(c for c in undeclared.relations if c.relation.startswith("19 =="))
    assert line_19.status == "FAIL" and "line(s) ['16'] cannot be written on this blank" in line_19.detail

    # someone types the amount into the PDF: the one field shows it on line 16 AND line 27
    writer = PdfWriter(clone_from=PdfReader(str(filled)))
    for page in writer.pages:
        writer.update_page_form_field_values(page, {"Partnership Income adjustment": "5000"}, auto_regenerate=False)
    typed = tmp_path / "typed.pdf"
    writer.write(str(typed))
    report = verify_form(pack, typed, expected={**values, "16": 5000})
    shared = [c for c in report.assertions if c.line == "16 / 27"]
    assert not report.ok and len(shared) == 1 and shared[0].status == "FAIL" and shared[0].actual == "5000"
