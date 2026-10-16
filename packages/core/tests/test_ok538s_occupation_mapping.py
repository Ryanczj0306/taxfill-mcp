"""Oklahoma Form 538-S occupations (JK27, 2026-10-16): bound only where the widget sits in the "Occupation" box.

Form 538-S (the Sales Tax Relief claim filed with Form 511, PDF page 51 of the 511 packet) prints a two-row box under
"Under penalty of perjury ...": "Taxpayer's Signature and Date" / "Spouse's Signature and Date" on top and
"Occupation" / "Occupation" below. On the 2023 and 2024 blanks the only widgets in that box, "538-S Taxpayer
Occupation" and "538-S Spouse Occupation" (both /Rect y 159.43-178.37), sit in the SIGNATURE row: they lie wholly
above the rule at y 155.2-156.2 that separates the rows, a sentinel render printed both values inside the signature
boxes, and the Occupation row carries no widget at all. The 2023 pack nevertheless mapped f538s.taxpayer_occupation /
f538s.spouse_occupation onto them, which put the occupation where the filer signs; the 2024 pack already left both
unmapped. The 2025 blank moved the widgets under "Occupation", but gave "538-S Spouse Occupation" a second widget in
the "Preparer's PTIN" box, so only the taxpayer line is mapped there.

Each box prints its caption at its top-left, so the caption printed just above a widget names the box it is in. The
network layer reads that caption for every widget of each occupation field and requires: mapped exactly when every
widget of the field is headed "Occupation". The offline layer pins the adjudicated binding per year, and that the
Form 511 page-44 occupation lines (their own widgets, which do sit in the "Occupation" boxes) stay mapped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.filler import fill_form, rehearsal_only
from taxfill_core.schemas.formpack import load_pack

FORMPACKS = Path(__file__).resolve().parents[3] / "formpacks"
OK_FORM511_PACKS = sorted(FORMPACKS.glob("states/ok/*/form511/pack.yaml"))

# line -> the 538-S widget it may bind
OCCUPATION_WIDGETS = {
    "f538s.taxpayer_occupation": "538-S Taxpayer Occupation",
    "f538s.spouse_occupation": "538-S Spouse Occupation",
}

# (pack, line) -> True when the line is mapped to its widget, False when it is deliberately unmapped (written by hand)
ADJUDICATED: dict[tuple[str, str], bool] = {
    # 2023: both widgets sit in the "Signature and Date" row (unmapped JK27, 2026-10-16)
    ("states/ok/2023/form511/pack.yaml", "f538s.taxpayer_occupation"): False,
    ("states/ok/2023/form511/pack.yaml", "f538s.spouse_occupation"): False,
    # 2024: the same rects as 2023 (unmapped at the 2024 port)
    ("states/ok/2024/form511/pack.yaml", "f538s.taxpayer_occupation"): False,
    ("states/ok/2024/form511/pack.yaml", "f538s.spouse_occupation"): False,
    # 2025: moved under "Occupation"; the spouse field's second widget sits in the "Preparer's PTIN" box
    ("states/ok/2025/form511/pack.yaml", "f538s.taxpayer_occupation"): True,
    ("states/ok/2025/form511/pack.yaml", "f538s.spouse_occupation"): False,
}

# The Form 511 (page 44) occupation lines are separate widgets in the "Taxpayer's / Spouse's Occupation" boxes.
FORM511_OCCUPATIONS = {
    "signature.taxpayer_occupation": "511 Taxpayer Occupation",
    "signature.spouse_occupation": "511 Spouse Occupation",
}


def _key(pack_path: Path) -> str:
    return str(pack_path.relative_to(FORMPACKS))


def _pack_id(pack_path: Path) -> str:
    return _key(pack_path).removesuffix("/pack.yaml").replace("/", "-")


def test_every_ok_form511_pack_is_adjudicated():
    """A new Form 511 year must decide its 538-S occupation binding from its own blank."""
    keys = {_key(path) for path in OK_FORM511_PACKS}
    adjudicated = {pack for pack, _ in ADJUDICATED}
    assert keys == adjudicated, (
        f"OK Form 511 packs without a 538-S occupation adjudication: {sorted(keys - adjudicated)}; stale rows: "
        f"{sorted(adjudicated - keys)}. Read the caption above each '538-S ... Occupation' widget on the new blank "
        f"(and render a sentinel) before adding the rows"
    )
    assert {line for _, line in ADJUDICATED} == set(OCCUPATION_WIDGETS)


@pytest.mark.parametrize("row", sorted(ADJUDICATED), ids=lambda row: f"{row[0].split('/')[2]}-{row[1]}")
def test_538s_occupation_binding_matches_the_adjudication(row: tuple[str, str], tmp_path: Path):
    pack_key, line = row
    pack = load_pack(FORMPACKS / pack_key)
    by_line = {pf.line: pf.field for pf in pack.fields}
    widget = OCCUPATION_WIDGETS[line]
    if ADJUDICATED[row]:
        assert by_line.get(line) == widget, f"{pack_key}: '{line}' must bind '{widget}', got {by_line.get(line)!r}"
        return
    assert line not in by_line, (
        f"{pack_key} maps '{line}' -> '{by_line[line]}' again, but on this blank '{widget}' does not sit (only) in the "
        f"538-S 'Occupation' box: a value written there prints in the signature box (2023 / 2024) or in the "
        f"'Preparer's PTIN' box too (2025). Leave the occupation for the filer to write by hand"
    )
    rebound = sorted(pf.line for pf in pack.fields if pf.field == widget)
    assert not rebound, f"{pack_key} binds '{widget}' under {rebound}; it must stay unmapped (see {line})"
    with pytest.raises(ValueError, match=r"unknown line key"):
        fill_form(pack, {line: "ENGINEER"}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf",
                  rehearsal=rehearsal_only(pack))


@pytest.mark.parametrize("pack_path", OK_FORM511_PACKS, ids=_pack_id)
def test_form511_page44_occupations_stay_mapped(pack_path: Path):
    """Over-reach guard: only the 538-S widgets come out; the Form 511 occupation boxes are their own widgets."""
    by_line = {pf.line: pf.field for pf in load_pack(pack_path).fields}
    for line, widget in FORM511_OCCUPATIONS.items():
        assert by_line.get(line) == widget, f"{_key(pack_path)}: '{line}' must stay mapped to '{widget}'"


def _heading_captions(blank: Path, field: str) -> list[str]:
    """The printed caption just above each widget of ``field`` — the heading of the box the widget sits in.

    A 14 pt band on the widget's top edge, starting 8 pt left of it: a box caption sits at the box's top-left, which
    can begin a few points left of the widget (the 2025 spouse box), and 14 pt stops short of the
    "Under penalty of perjury" line above the 2023 / 2024 signature row.
    """
    import pypdfium2 as pdfium  # noqa: PLC0415
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(blank))
    document = pdfium.PdfDocument(str(blank))
    captions: list[str] = []
    for index, page in enumerate(reader.pages):
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            parent = annot.get("/Parent")
            name = annot.get("/T") or (parent.get_object().get("/T") if parent is not None else None)
            if annot.get("/Subtype") != "/Widget" or str(name) != field:
                continue
            x0, y0, x1, y1 = (float(value) for value in annot["/Rect"])
            top = max(y0, y1)
            raw = document[index].get_textpage().get_text_bounded(
                left=min(x0, x1) - 8.0, bottom=top, right=max(x0, x1), top=top + 14.0)
            captions.append(" ".join(raw.split()))
    return captions


@pytest.mark.network
@pytest.mark.parametrize("pack_path", OK_FORM511_PACKS, ids=_pack_id)
def test_538s_occupation_is_mapped_exactly_when_every_widget_sits_in_an_occupation_box(pack_path: Path):
    pack = load_pack(pack_path)
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    by_line = {pf.line: pf.field for pf in pack.fields}
    for line, widget in OCCUPATION_WIDGETS.items():
        captions = _heading_captions(Path(blank), widget)
        assert captions, f"{_key(pack_path)}: the blank has no '{widget}' widget — re-derive the 538-S binding"
        in_occupation_box = all("Occupation" in caption and "Signature" not in caption for caption in captions)
        assert (by_line.get(line) == widget) == in_occupation_box, (
            f"{_key(pack_path)}: '{line}' is {'mapped' if line in by_line else 'unmapped'}, but the captions above "
            f"the '{widget}' widget(s) read {captions}. Map the line only when every widget of the field sits under "
            f"a printed 'Occupation' caption; a widget in the 'Signature and Date' or 'Preparer's PTIN' box would "
            f"print the occupation there"
        )
