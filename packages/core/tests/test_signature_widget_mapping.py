"""Repo-wide invariant (JK27, 2026-10-16): no pack line binds a digital-signature (/FT /Sig) field.

Some DOR blanks put an /FT /Sig widget on an ink-signature line (WV IT-140's "Preparer’s Signature",
AR1000F's and AR1000NR's Signature1 / Signature2 / Signature3). fill_form does not refuse one: it writes the
string as the field's /V and counts it in ``written``, with no warning, and pypdf logs only "Signature forms
not implemented yet". A sentinel filled into each of those widgets did not render at all, while the
ordinary text box beside it (the WV preparer "Telephone Number", the AR "Telephone") did. So a /Sig
binding is a key that accepts a value which never prints, and it leaves a non-signature /V in a signature
field of the filed PDF.

The repo's treatment, and the one this file enforces: leave the widget UNMAPPED. The filer (and a paid
preparer) signs that line by hand, exactly as on the many forms whose signature lines carry no widget at
all; the pack-level ``signature: {page: N}`` block is what tells the filer where to sign in ink. The WV 2024
pack and the AR1000NR 2023 pack already did this. The JK27 sweep found 10 bindings that did not: WV IT-140
2023 ``preparer.signature`` and AR1000F 2023 / 2024 / 2025 ``signature.primary`` / ``signature.spouse`` /
``preparer.signature``. All 10 are dropped.

Out of scope here: an ink-signature line whose widget is an ordinary /Tx field (KS K-40, KY 740, MO-1040,
IL-1040 2025). A typed value there does print, so whether it belongs on the line is a question for the printed
face and instructions, not for the field type.

Layers, following test_readonly_widget_mapping.py:

- **offline** (always run): the reader is proven on a synthetic PDF (the /FT can sit on the terminal field
  dict a /T-less widget inherits from, or on a merged field-widget), and the table of dropped keys is pinned
  against the packs: each key is absent, fill_form refuses it, the /Sig widget is not re-bound under any
  other key, and the neighbouring Date / Telephone / EIN lines on the same row are still mapped.
- **@pytest.mark.network**: the blanks. Every pack's own blank, read from the cache (fetch_pack_blank returns
  the cached copy without touching the network) or downloaded, and skipped when neither works: no mapped
  field may be, or be a parent of, a /Sig widget. Each table row's widget must still be /Sig in its blank,
  so the table clears itself when a revision turns one into a text field.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from pdf_fixtures import make_acroform_pdf
from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import load_pack

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMPACKS = REPO_ROOT / "formpacks"
ALL_PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))


def _key(pack_path: Path) -> str:
    """Pack identity used by the table: path relative to formpacks/ ("states/wv/2023/it140/pack.yaml")."""
    return str(pack_path.relative_to(FORMPACKS))


def _pack_id(pack_path: Path) -> str:
    return _key(pack_path).removesuffix("/pack.yaml").replace("/", "-")


def _sig_widget_names(pdf_path: Path) -> set[str]:
    """Fully qualified names of every widget whose field type, own or inherited, is /Sig.

    Deliberately independent of taxfill_core.verify's helpers (the readers this file audits never look at
    /FT /Sig at all). The type is inherited: on a hierarchical form the widget carries no /T and no /FT of
    its own and takes both from the terminal field dict up its /Parent chain.
    """
    from pypdf import PdfReader  # noqa: PLC0415

    def inherited(node, key):
        hops = 0
        while node is not None and hops < 64:
            if key in node:
                return node[key]
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return None

    def qualified_name(node) -> str:
        parts: list[str] = []
        hops = 0
        while node is not None and hops < 64:
            title = node.get("/T")
            if title:
                parts.append(str(title))
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return ".".join(reversed(parts))

    names: set[str] = set()
    for page in PdfReader(str(pdf_path)).pages:
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") == "/Widget" and inherited(annot, "/FT") == "/Sig":
                names.add(qualified_name(annot))
    return names


def _binds(mapped: str, sig_names: set[str]) -> bool:
    """A mapped field binds a /Sig widget when it IS one, or is a parent field whose kids include one."""
    return mapped in sig_names or any(name.startswith(mapped + ".") for name in sig_names)


# ---------------------------------------------------------------------------
# The dropped keys
# ---------------------------------------------------------------------------


class SignatureUnmapped(NamedTuple):
    """A /Sig widget a pack once bound under ``lines``, now deliberately unmapped."""

    pack: str  # path relative to formpacks/
    widget: str  # the /Sig field's name as a pack's `field:` would spell it (acroform_root NOT prefixed)
    lines: tuple[str, ...]  # the keys that bound it; they must not exist
    survivors: tuple[str, ...]  # the ordinary text boxes on the same printed row, which stay mapped
    why: str


_AR_SIG_WHY = (
    "AR1000F page 3 {label}: an /FT /Sig widget. The base pack (2023) mapped it as text and the 2024 / 2025 "
    "ports inherited the binding as a recorded caveat; a sentinel filled into it never rendered, while the "
    "Telephone box beside it did. Dropped in all three years (JK27, 2026-10-16); signed by hand"
)

SIGNATURE_LINES_UNMAPPED: tuple[SignatureUnmapped, ...] = (
    SignatureUnmapped(
        "states/wv/2023/it140/pack.yaml",
        "Preparer’s Signature",
        ("preparer.signature",),
        ("preparer.id_number", "preparer.telephone"),
        'IT-140 page 2 "Signature of preparer other than above": an /FT /Sig widget (/Rect 189.7,146.0 - '
        "319.0,168.4) mapped as text until JK27 (2026-10-16); a sentinel filled into it never rendered, while "
        "the preparer telephone beside it did. Signed by hand, as the 2024 pack already had it",
    ),
    SignatureUnmapped(
        "states/wv/2024/it140/pack.yaml",
        "Preparer’s Signature",
        ("preparer.signature",),
        ("preparer.id_number", "preparer.telephone"),
        "the same /Sig widget on the 2024 face (moved to /Rect 38.7,119.9 - 168.0,136.5); the 2024 re-map "
        "dropped the key (JS5/JS6 recovery, 2026-10-15). Signed by hand",
    ),
    *(
        row
        for year in (2023, 2024, 2025)
        for row in (
            SignatureUnmapped(
                f"states/ar/{year}/ar1000f/pack.yaml",
                "Signature1",
                ("signature.primary",),
                ("signature.primary_date", "signature.primary_phone"),
                _AR_SIG_WHY.format(label="\"Primary's signature\""),
            ),
            SignatureUnmapped(
                f"states/ar/{year}/ar1000f/pack.yaml",
                "Signature2",
                ("signature.spouse",),
                ("signature.spouse_date", "signature.spouse_phone"),
                _AR_SIG_WHY.format(label="\"Spouse's signature\""),
            ),
            SignatureUnmapped(
                f"states/ar/{year}/ar1000f/pack.yaml",
                "Signature3",
                ("preparer.signature",),
                ("preparer.ptin",),
                _AR_SIG_WHY.format(label="\"Paid preparer's signature\""),
            ),
        )
    ),
)


def _row_id(row: SignatureUnmapped) -> str:
    return f"{_pack_id(FORMPACKS / row.pack)}-{row.lines[0]}"


# ---------------------------------------------------------------------------
# Offline layer
# ---------------------------------------------------------------------------


def test_sig_reader_sees_the_field_type_on_the_field_tree_and_on_a_merged_widget(tmp_path: Path):
    """Prove the mechanism the network layer depends on, offline.

    Two real shapes: a hierarchical field whose /FT sits on the terminal field dict (the widget has no /T
    and no /FT), and a flat field whose field and widget are one merged dict (the WV and AR blanks). A
    reader that looked only at the annotation would miss the first and report an empty set for every
    hierarchical blank, turning every network assertion below into a silent pass.
    """
    from pypdf import PdfWriter  # noqa: PLC0415
    from pypdf.generic import NameObject  # noqa: PLC0415

    root = "topmostSubform[0]"
    blank = make_acroform_pdf(
        tmp_path / "sig_probe.pdf",
        [
            {"name": f"{root}.Page1[0].f1_1[0]", "hierarchical": True},
            {"name": f"{root}.Page1[0].f1_2[0]", "hierarchical": True},
            {"name": "Signature1"},
            {"name": "Telephone"},
        ],
    )
    writer = PdfWriter(clone_from=str(blank))
    for page in writer.pages:
        for annot_ref in page.get("/Annots", []):
            annot = annot_ref.get_object()
            parent = annot.get("/Parent")
            terminal = parent.get_object() if parent is not None else None
            if terminal is not None and str(terminal.get("/T")) == "f1_1[0]":
                assert "/FT" not in annot, "the hierarchical fixture should leave /FT on the terminal field only"
                terminal[NameObject("/FT")] = NameObject("/Sig")
            elif str(annot.get("/T")) == "Signature1":
                annot[NameObject("/FT")] = NameObject("/Sig")
    probe = tmp_path / "sig_probe_typed.pdf"
    with probe.open("wb") as handle:
        writer.write(handle)

    names = _sig_widget_names(probe)
    assert names == {f"{root}.Page1[0].f1_1[0]", "Signature1"}, (
        f"the /Sig reader returned {sorted(names)} — it must resolve /FT up the /Parent chain (the "
        f"hierarchical shape), read it off a merged field-widget too (the WV / AR shape), report FULLY "
        f"QUALIFIED names (what acroform_root + the pack's `field:` is compared against), and leave the "
        f"/Tx siblings out. Every network assertion in this file rests on it"
    )
    assert _binds(f"{root}.Page1[0].f1_1[0]", names) and _binds(f"{root}.Page1[0]", names)
    assert not _binds(f"{root}.Page1[0].f1_2[0]", names) and not _binds("Signature", names)


@pytest.mark.parametrize("row", SIGNATURE_LINES_UNMAPPED, ids=_row_id)
def test_dropped_signature_key_stays_unmapped_and_the_filler_refuses_it(row: SignatureUnmapped, tmp_path: Path):
    """JK27: the /Sig keys must not exist, the widget must not come back under another key, and fill_form refuses them."""
    pack_path = FORMPACKS / row.pack
    assert pack_path.is_file(), f"SIGNATURE_LINES_UNMAPPED names {row.pack}, which does not exist — delete the row"
    pack = load_pack(pack_path)
    by_line = {pf.line: pf.field for pf in pack.fields}
    for line in row.lines:
        assert line not in by_line, (
            f"{row.pack} maps '{line}' -> '{by_line[line]}' again. '{row.widget}' is an /FT /Sig "
            f"(digital-signature) field: fill_form writes the string as its /V and counts it written, but the "
            f"value never prints. Leave the line for an ink signature — {row.why}"
        )
    rebound = sorted(pf.line for pf in pack.fields if pf.field == row.widget)
    assert not rebound, (
        f"{row.pack} binds the /Sig widget '{row.widget}' under {rebound} — a value written there never prints; "
        f"leave it unmapped ({row.why})"
    )
    for line in row.survivors:
        assert line in by_line, (
            f"{row.pack} lost '{line}' — over-reach: only the /Sig signature box comes out of the map; the "
            f"Date / Telephone / EIN / PTIN boxes on the same row are ordinary text fields and stay mapped"
        )
    # fill_form validates line keys before it opens the blank, so no PDF is needed.
    from taxfill_core.filler import rehearsal_only  # noqa: PLC0415

    rehearsal = rehearsal_only(pack)
    for line in row.lines:
        with pytest.raises(ValueError, match=r"unknown line key"):
            fill_form(pack, {line: "SIGNED"}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf",
                      rehearsal=rehearsal)


def test_every_table_row_carries_a_justification_and_rows_are_unique():
    seen: set[tuple[str, str]] = set()
    for row in SIGNATURE_LINES_UNMAPPED:
        assert row.why.strip() and row.lines, f"{row}: every row needs its dropped keys and a justification"
        assert (row.pack, row.widget) not in seen, f"duplicate SIGNATURE_LINES_UNMAPPED row {row.pack} {row.widget}"
        seen.add((row.pack, row.widget))


# ---------------------------------------------------------------------------
# Network layer — the blanks themselves
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_pack_maps_no_digital_signature_widget(pack_path: Path):
    """JK27, repo-wide: no mapped field is, or is a parent of, an /FT /Sig widget in the pack's own blank."""
    pack = load_pack(pack_path)
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    sig_names = _sig_widget_names(Path(blank))
    hits = sorted(f"line {pf.line!r} -> {prefix + pf.field}" for pf in pack.fields if _binds(prefix + pf.field, sig_names))
    assert not hits, (
        f"{_key(pack_path)} maps digital-signature (/FT /Sig) widget(s):\n  " + "\n  ".join(hits)
        + "\n\nfill_form writes the string as the /Sig field's /V and counts it written, but no viewer renders "
        "it (pypdf: 'Signature forms not implemented yet') — the line prints BLANK. Drop the line key and "
        "leave the box for an ink signature (the pack's `signature:` block says where to sign), with a comment "
        "naming the widget; then add a SIGNATURE_LINES_UNMAPPED row so the key cannot come back"
    )


@pytest.mark.network
@pytest.mark.parametrize("row", SIGNATURE_LINES_UNMAPPED, ids=_row_id)
def test_every_unmapped_signature_row_still_names_a_sig_widget(row: SignatureUnmapped):
    """The table self-clears: a revision that turns the box into a text field must re-adjudicate the row."""
    pack = load_pack(FORMPACKS / row.pack)
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    assert prefix + row.widget in _sig_widget_names(Path(blank)), (
        f"{row.pack}: '{row.widget}' is no longer an /FT /Sig widget in the pinned blank. Re-read the printed "
        f"row: a text field on an ink-signature line still prints what is typed, so decide from the face "
        f"whether to map it, and delete this row ({row.why})"
    )
