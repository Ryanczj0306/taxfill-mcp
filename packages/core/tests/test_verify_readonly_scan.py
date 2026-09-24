"""The ReadOnly clipping blind spot (engine debt recorded 2026-08-20) — closed.

verify.py's text-widget collector used to skip EVERY ReadOnly text widget
(/Ff bit 1) on the premise "the filler never writes them". That premise is
false: packs keep over a thousand ReadOnly bindings MAPPED on purpose — a
state DOR sets the bit on cells its own JavaScript owns (running totals, the
page-2/3/4 name + SSN mirror cells) and taxfill never runs that JavaScript,
so unmapped they file BLANK (P-007 class 4, pinned per pack by
test_readonly_widget_mapping.py's STATE_COMPUTED_READONLY). The P-001
clipping scan was therefore structurally blind to exactly the field shape it
exists for: WI Form 1's ReadOnly maxlen-3/2/4 SSN mirror cells.

The corrected rule, exercised here end to end: a ReadOnly text widget IS
scanned when the pack's field map binds its qualified name (the filler could
have written it) and is skipped otherwise — an unmapped ReadOnly widget holds
a value baked into the blank (NC D-400's fixed-18pt "PRINT" margin banner,
IL-1040's "Help" tooltip) that the user can neither change nor see clipped,
and those false positives are why the skip was added in the first place.

Binding alone over-reached, and that is the second half of this file. A pack
that maps a ReadOnly widget whose value the DOR BAKED INTO THE BLANK (AL-40
2023's twelve instruction panels, MO-1040's five checkbox captions) made the
widened scan FAIL P-001 on every real one-line fill, over text the filer
never wrote — while the round-trip tests stayed green because their sentinel
values overwrite every mapped widget. So verify_form / verify_filing also
compare each mapped ReadOnly widget with the pack's sha-pinned blank (read
from the local blank cache, never downloaded) and skip it while its value is
still the blank's own; without a cached blank every mapped ReadOnly widget is
scanned and each such FAIL says so. The repo-wide version of this check, on
the real blanks, is test_verify_readonly_sweep.py.

Every PDF here is synthetic (pdf_fixtures.make_acroform_pdf) with the
ReadOnly bit flipped by the test itself, and every value is written with
pypdf directly — never the filler — so verification stays an independent
pass (the filler would also refuse the over-long values on purpose). The
blank cache is redirected to an empty per-test directory, so nothing here
depends on what the developer happens to have cached.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject, TextStringObject

from pdf_fixtures import make_acroform_pdf
from taxfill_core.fetch import CACHE_DIR_ENV, _cache_path, compute_sha256
from taxfill_core.schemas.formpack import FormPack
from taxfill_core.verify import (
    FilingItem,
    VerifyReport,
    bound_widget_names,
    clipping_scan,
    read_text_widgets,
    verify_filing,
    verify_form,
)

# Flat state-style AcroForm (empty acroform_root): the shape WI/AL/GA/MO use.
MIRROR = "ss3pg2"  # WI Form 1's page-2 SSN mirror cell: ReadOnly, comb, MaxLen 3
TOTAL = "it140_totex5"  # a DOR-computed total: ReadOnly, no MaxLen, 10pt, 30pt wide
BANNER = "PRINT"  # NC D-400's margin banner: ReadOnly, 18pt, baked-in value, UNMAPPED
EDITABLE = "fname"  # an ordinary editable text widget

MIRROR_OVERLONG = "9998"  # 4 digits into a 3-cell comb -> MaxLen overflow
TOTAL_OVERLONG = "1234567"  # 7 x 0.5 x 10pt = 35pt into a 30pt box -> width overflow
BANNER_VALUE = "DO NOT MAIL THIS PAGE"  # 21 x 0.5 x 18pt = 189pt into 40pt: would "clip"


@pytest.fixture(autouse=True)
def empty_blank_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the shared blank cache at an empty directory for every test here.

    verify_form / verify_filing look up the pack's pinned blank in that cache;
    tests that need one pin it explicitly with :func:`_pin_blank`.
    """
    cache = tmp_path / "blank-cache"
    monkeypatch.setenv(CACHE_DIR_ENV, str(cache))
    return cache


def _set_read_only(writer: PdfWriter, names: set[str], *, da: dict[str, str] | None = None) -> None:
    """Flip /Ff bit 1 on the named flat widgets (and optionally rewrite /DA)."""
    flipped: set[str] = set()
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            title = annot.get("/T")
            if title is None or str(title) not in names:
                continue
            existing = int(annot.get("/Ff", 0))
            annot[NameObject("/Ff")] = NumberObject(existing | 1)
            if da and str(title) in da:
                annot[NameObject("/DA")] = TextStringObject(da[str(title)])
            flipped.add(str(title))
    assert flipped == names, f"fixture did not expose {names - flipped} to flag"


def _write_values(writer: PdfWriter, values: dict[str, str]) -> None:
    """Write /V directly on flat widgets — the independent (non-filler) path.

    pypdf's update_page_form_field_values is not used because a ReadOnly field
    is exactly the case a form-filling helper might decline; setting /V on the
    field dict is what the filler's own write reduces to.
    """
    written: set[str] = set()
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            title = annot.get("/T")
            if title is not None and str(title) in values:
                annot[NameObject("/V")] = TextStringObject(values[str(title)])
                written.add(str(title))
    assert written == set(values), f"fixture did not expose {set(values) - written}"


@pytest.fixture()
def read_only_pdf(tmp_path: Path) -> Path:
    """Filled flat AcroForm: two mapped ReadOnly cells that clip, one unmapped banner."""
    blank = make_acroform_pdf(
        tmp_path / "blank.pdf",
        [
            {"name": MIRROR, "kind": "text", "maxlen": 3, "comb": True, "width": 40},
            {"name": TOTAL, "kind": "text", "width": 30},
            {"name": BANNER, "kind": "text", "width": 40, "value": BANNER_VALUE},
            {"name": EDITABLE, "kind": "text", "width": 200},
        ],
    )
    writer = PdfWriter(clone_from=str(blank))
    _set_read_only(
        writer,
        {MIRROR, TOTAL, BANNER},
        da={TOTAL: "/Helv 10 Tf 0 g", BANNER: "/Helv 18 Tf 0 g"},
    )
    _write_values(writer, {MIRROR: MIRROR_OVERLONG, TOTAL: TOTAL_OVERLONG, EDITABLE: "Pat"})
    out = tmp_path / "filled.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    return out


def _flat_pack(fields: list[dict]) -> FormPack:
    return FormPack.model_validate(
        {
            "form": "WI-1",
            "tax_year": 2023,
            "jurisdiction": "states/wi",
            "source_url": "https://www.revenue.wi.gov/TaxForms2023/2023-Form1f.pdf",
            "pdf_sha256": "0" * 64,
            "acroform_root": "",
            "fields": fields,
        }
    )


def mapping_pack() -> FormPack:
    """Maps the two ReadOnly cells (as WI/WV do) and the editable name; NOT the banner."""
    return _flat_pack(
        [
            {"line": "identifying_number.pg2_first3", "field": MIRROR, "type": "text", "maxlen": 3,
             "comb": True, "format": "ssn_digits_only"},
            {"line": "exemptions.e", "field": TOTAL, "type": "text"},
            {"line": "name", "field": EDITABLE, "type": "text"},
        ]
    )


def banner_free_pack() -> FormPack:
    """Maps only the editable widget — the NC/IL shape where every ReadOnly widget is unmapped."""
    return _flat_pack([{"line": "name", "field": EDITABLE, "type": "text"}])


# ---------------------------------------------------------------------------
# The reader: bound names decide which ReadOnly widgets are collected
# ---------------------------------------------------------------------------


def test_reader_without_bound_names_skips_every_read_only_widget(read_only_pdf):
    # No pack in scope -> the reader cannot tell a mirror from a banner, so
    # it keeps the pre-2026-09-11 behaviour: every ReadOnly widget is skipped.
    names = {w.name for w in read_text_widgets(read_only_pdf)}
    assert EDITABLE in names
    assert names.isdisjoint({MIRROR, TOTAL, BANNER})


def test_reader_scans_mapped_read_only_widgets_and_skips_unmapped_banners(read_only_pdf):
    widgets = {w.name: w for w in read_text_widgets(read_only_pdf, bound_names=bound_widget_names(mapping_pack()))}
    assert MIRROR in widgets and TOTAL in widgets  # the filler could have written these
    assert BANNER not in widgets  # baked into the blank; never scanned
    assert widgets[MIRROR].read_only is True and widgets[MIRROR].max_len == 3
    assert widgets[MIRROR].value == MIRROR_OVERLONG  # /V is read even though the flag is set
    assert widgets[TOTAL].read_only is True and widgets[TOTAL].rect_width == pytest.approx(30.0)
    assert widgets[EDITABLE].read_only is False


def test_bound_widget_names_carries_both_spellings_lookup_raw_tolerates():
    rooted = FormPack.model_validate(
        {
            "form": "1040-NR",
            "tax_year": 2025,
            "jurisdiction": "federal",
            "source_url": "https://www.irs.gov/pub/irs-pdf/f1040nr.pdf",
            "pdf_sha256": "0" * 64,
            "acroform_root": "topmostSubform[0]",
            "fields": [{"line": "1a", "field": "Page1[0].f1_7[0]", "type": "money"}],
        }
    )
    assert bound_widget_names(rooted) == frozenset({"topmostSubform[0].Page1[0].f1_7[0]", "Page1[0].f1_7[0]"})
    # Flat state AcroForm: the bare field IS the qualified name.
    assert bound_widget_names(mapping_pack()) == frozenset({MIRROR, TOTAL, EDITABLE})


def test_clipping_scan_path_entry_forwards_bound_names(read_only_pdf):
    unaware = {check.name for check in clipping_scan(read_only_pdf)}
    assert unaware.isdisjoint({MIRROR, TOTAL, BANNER})
    aware = {check.name: check for check in clipping_scan(read_only_pdf, bound_names=bound_widget_names(mapping_pack()))}
    assert aware[MIRROR].status == "FAIL" and aware[TOTAL].status == "FAIL"
    assert BANNER not in aware


# ---------------------------------------------------------------------------
# verify_form / verify_filing: the blind spot, end to end
# ---------------------------------------------------------------------------


def test_verify_form_flags_clipping_in_the_read_only_widgets_the_pack_maps(read_only_pdf):
    # (a) A mapped ReadOnly widget with an over-wide value IS flagged — both
    # the hard /MaxLen overflow (the P-001 SSN incident shape on a mirror
    # cell) and the width heuristic (a DOR-computed total in a 30pt box).
    report = verify_form(mapping_pack(), str(read_only_pdf))
    by_name = {check.name: check for check in report.clipping}

    mirror = by_name[MIRROR]
    assert mirror.status == "FAIL"
    assert "MaxLen is 3" in mirror.detail
    assert "ReadOnly widget the pack maps" in mirror.detail  # the agent learns WHY a locked box is flagged
    assert MIRROR_OVERLONG not in mirror.detail  # PII-safe: the SSN digits never appear

    total = by_name[TOTAL]
    assert total.status == "FAIL"
    assert "exceeds the widget width 30.0pt" in total.detail
    assert "ReadOnly widget the pack maps" in total.detail

    assert by_name[EDITABLE].status == "PASS"
    assert report.ok is False
    assert {check.id: check.status for check in report.pitfall_checks}["P-001"] == "FAIL"


def test_verify_form_never_flags_the_unmapped_banner(read_only_pdf):
    # (b) The unmapped ReadOnly banner (18pt "DO NOT MAIL THIS PAGE" in a 40pt
    # box — 189pt of text by the heuristic) is NOT flagged, under either pack:
    # its value is baked into the blank, not written by the filler.
    for pack in (mapping_pack(), banner_free_pack()):
        report = verify_form(pack, str(read_only_pdf))
        assert all(BANNER not in check.name for check in report.clipping), pack.fields
    # And with no ReadOnly widget mapped at all (the NC D-400 / IL-1040 shape),
    # the widened scan changes nothing: the report is clean.
    clean = verify_form(banner_free_pack(), str(read_only_pdf))
    assert clean.ok is True
    assert {check.name for check in clean.clipping} == {EDITABLE}
    assert {check.id: check.status for check in clean.pitfall_checks}["P-001"] == "PASS"


def test_scanned_read_only_widget_supersedes_the_pack_maxlen_check(read_only_pdf):
    # Before the fix the mirror cell was reached only by the dump-based pack
    # maxlen check (a "(line ...)"-suffixed entry). Now the widget itself is
    # scanned, so exactly ONE clipping entry names it — no double report.
    report = verify_form(mapping_pack(), str(read_only_pdf))
    mirror_entries = [check for check in report.clipping if MIRROR in check.name]
    assert len(mirror_entries) == 1
    assert mirror_entries[0].name == MIRROR  # the widget entry, not the pack fallback


def test_verify_filing_threads_each_items_pack_into_the_scan(read_only_pdf):
    report = verify_filing(
        [FilingItem(form_key="wi_form1", pack=mapping_pack(), pdf_path=str(read_only_pdf))]
    )
    by_name = {check.name: check for check in report.clipping}
    assert by_name[f"wi_form1: {MIRROR}"].status == "FAIL"
    assert by_name[f"wi_form1: {TOTAL}"].status == "FAIL"
    assert all(BANNER not in name for name in by_name)
    assert report.ok is False
    assert {check.id: check.status for check in report.pitfall_checks}["P-001"] == "FAIL"


# ---------------------------------------------------------------------------
# A MAPPED banner: text the DOR baked into the blank is not this fill's
# ---------------------------------------------------------------------------

BLANK_URL = "https://www.revenue.wi.gov/TaxForms2023/2023-Form1f.pdf"  # _flat_pack's source_url
BANNER_LINE = "instructions"


def _pin_blank(blank: Path, cache: Path) -> str:
    """Install ``blank`` where fetch_blank caches BLANK_URL; return its sha256 (the pack's pin)."""
    target = _cache_path(cache, BLANK_URL)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blank.read_bytes())
    return compute_sha256(target)


@pytest.fixture()
def banner_case(tmp_path: Path) -> tuple[Path, Path]:
    """(blank, filled) for a pack that maps a ReadOnly banner as a line.

    The blank has what a real DOR blank has: ReadOnly bits set, the banner's
    text baked into its /V, nothing a filler writes. The "fill" then writes an
    over-long SSN mirror and a name and leaves the banner alone — exactly what
    fill_form does to any line it is not given.
    """
    raw = make_acroform_pdf(
        tmp_path / "raw.pdf",
        [
            {"name": MIRROR, "kind": "text", "maxlen": 3, "comb": True, "width": 40},
            {"name": BANNER, "kind": "text", "width": 40, "value": BANNER_VALUE},
            {"name": EDITABLE, "kind": "text", "width": 200},
        ],
    )
    writer = PdfWriter(clone_from=str(raw))
    _set_read_only(writer, {MIRROR, BANNER}, da={BANNER: "/Helv 18 Tf 0 g"})
    blank = tmp_path / "banner_blank.pdf"
    with blank.open("wb") as fh:
        writer.write(fh)
    writer = PdfWriter(clone_from=str(blank))
    _write_values(writer, {MIRROR: MIRROR_OVERLONG, EDITABLE: "Pat"})
    filled = tmp_path / "banner_filled.pdf"
    with filled.open("wb") as fh:
        writer.write(fh)
    return blank, filled


def banner_mapping_pack(sha256: str = "0" * 64, *, banner_maxlen: int | None = None) -> FormPack:
    """Maps the banner AS A LINE — the pre-2026-09-23 AL-40 / MO-1040 shape — plus the mirror."""
    banner: dict = {"line": BANNER_LINE, "field": BANNER, "type": "text"}
    if banner_maxlen is not None:
        banner["maxlen"] = banner_maxlen
    pack = _flat_pack(
        [
            {"line": "identifying_number.pg2_first3", "field": MIRROR, "type": "text", "maxlen": 3,
             "comb": True, "format": "ssn_digits_only"},
            banner,
            {"line": "name", "field": EDITABLE, "type": "text"},
        ]
    )
    return pack.model_copy(update={"pdf_sha256": sha256})


def _both_reports(pack: FormPack, pdf: Path) -> list[tuple[str, VerifyReport]]:
    """The verify_form report and the verify_filing report of one PDF, with each's name prefix."""
    return [
        ("", verify_form(pack, str(pdf))),
        ("al40: ", verify_filing([FilingItem(form_key="al40", pack=pack, pdf_path=str(pdf))])),
    ]


def test_mapped_banner_still_holding_the_blanks_text_is_not_flagged(banner_case, empty_blank_cache):
    # The PJ-02 regression, synthetically: AL-40 2023 mapped twelve DOR
    # instruction banners and a real FIRSTNAME-only fill FAILed P-001 twelve
    # times. With the pinned blank in the cache, the banner's /V is still the
    # blank's own, so it is not this fill's clipping — in BOTH verify paths.
    blank, filled = banner_case
    pack = banner_mapping_pack(_pin_blank(blank, empty_blank_cache))
    for prefix, report in _both_reports(pack, filled):
        by_name = {check.name: check for check in report.clipping}
        assert f"{prefix}{BANNER}" not in by_name, by_name.keys()
        # What the fill DID write is still caught, with no "blank missing" hedge.
        mirror = by_name[f"{prefix}{MIRROR}"]
        assert mirror.status == "FAIL" and "MaxLen is 3" in mirror.detail
        assert "fetch_blank" not in mirror.detail
        assert by_name[f"{prefix}{EDITABLE}"].status == "PASS"


def test_a_mapped_read_only_widget_the_fill_rewrote_is_scanned_again(banner_case, empty_blank_cache, tmp_path):
    # The skip is "unchanged from the blank", never "mapped banner": once a
    # fill writes a different value into the same ReadOnly widget, it is the
    # filler's text and the scan judges it.
    blank, filled = banner_case
    pack = banner_mapping_pack(_pin_blank(blank, empty_blank_cache))
    writer = PdfWriter(clone_from=str(filled))
    _write_values(writer, {BANNER: "PAT Q TAXPAYER AND SPOUSE"})  # 25 x 0.5 x 18pt = 225pt into 40pt
    rewritten = tmp_path / "banner_rewritten.pdf"
    with rewritten.open("wb") as fh:
        writer.write(fh)
    for prefix, report in _both_reports(pack, rewritten):
        banner = {check.name: check for check in report.clipping}[f"{prefix}{BANNER}"]
        assert banner.status == "FAIL"
        assert "ReadOnly widget the pack maps" in banner.detail
        assert "fetch_blank" not in banner.detail


def test_without_the_pinned_blank_every_mapped_read_only_widget_is_scanned_and_says_why(
    banner_case, empty_blank_cache
):
    # Fail loud, not blind: with no usable blank the verifier cannot tell the
    # DOR's text from the filler's, so it scans every mapped ReadOnly widget
    # and each such FAIL names the fix. Two ways to have no usable blank:
    blank, filled = banner_case
    # (1) nothing cached under the pack's source_url at all;
    uncached = banner_mapping_pack()
    # (2) a file IS cached there but its sha256 is not the pack's pin — a stale
    #     or foreign file is treated as absent, never trusted.
    _pin_blank(blank, empty_blank_cache)
    stale = banner_mapping_pack("f" * 64)
    for pack in (uncached, stale):
        for prefix, report in _both_reports(pack, filled):
            by_name = {check.name: check for check in report.clipping}
            banner = by_name[f"{prefix}{BANNER}"]
            assert banner.status == "FAIL"
            assert "not in the local blank cache" in banner.detail and "run fetch_blank" in banner.detail
            assert "not in the local blank cache" in by_name[f"{prefix}{MIRROR}"].detail
            assert "fetch_blank" not in by_name[f"{prefix}{EDITABLE}"].detail  # editable widgets never carry it


def test_the_blank_lookup_never_touches_the_network(banner_case, monkeypatch):
    # Verification is an offline pass: a missing blank is reported, not fetched.
    import taxfill_core.fetch as fetch

    def refuse(*args, **kwargs):
        raise AssertionError(f"verify tried to download {args[:1]}")

    monkeypatch.setattr(fetch, "_download", refuse)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", refuse)
    _blank, filled = banner_case
    report = verify_form(banner_mapping_pack(), str(filled))
    assert {check.name: check.status for check in report.clipping}[BANNER] == "FAIL"


def test_a_dropped_banner_does_not_come_back_through_the_pack_maxlen_fallback(banner_case, empty_blank_cache):
    # _pack_maxlen_checks re-reads every maxlen line from the DUMP unless a
    # scanned widget covers it. A banner dropped as blank-owned must stay
    # covered, or a pack maxlen shorter than the DOR's text resurrects the very
    # false FAIL the drop removed (as a "(line instructions)" entry).
    blank, filled = banner_case
    pack = banner_mapping_pack(_pin_blank(blank, empty_blank_cache), banner_maxlen=5)
    for _prefix, report in _both_reports(pack, filled):
        assert all(BANNER not in check.name for check in report.clipping), [c.name for c in report.clipping]


# ---------------------------------------------------------------------------
# The real IRS shape: /Ff lives on the TERMINAL FIELD dict, not the widget
# ---------------------------------------------------------------------------

ROOT = "topmostSubform[0]"
HIER_FIELD = "Page2[0].f2_ssn3[0]"
HIER_NAME = f"{ROOT}.{HIER_FIELD}"


def _hierarchical_read_only_pdf(tmp_path: Path) -> Path:
    pdf = make_acroform_pdf(
        tmp_path / "hier.pdf",
        [{"name": HIER_NAME, "kind": "text", "maxlen": 3, "comb": True, "hierarchical": True}],
    )
    writer = PdfWriter(clone_from=str(pdf))
    done = False
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if "/T" in annot:
                continue  # hierarchical kids carry no /T of their own
            terminal = annot["/Parent"].get_object()
            if str(terminal.get("/T")) != "f2_ssn3[0]":
                continue
            terminal[NameObject("/Ff")] = NumberObject(int(terminal.get("/Ff", 0)) | 1)
            terminal[NameObject("/V")] = TextStringObject(MIRROR_OVERLONG)
            done = True
    assert done, "fixture did not build the parent/kid tree"
    out = tmp_path / "hier_filled.pdf"
    with out.open("wb") as fh:
        writer.write(fh)
    return out


def test_inherited_read_only_flag_on_the_terminal_field_dict_is_honoured(tmp_path):
    pdf = _hierarchical_read_only_pdf(tmp_path)
    assert not read_text_widgets(pdf)  # unbound: the inherited flag still skips it
    widgets = read_text_widgets(pdf, bound_names={HIER_NAME})
    assert [w.name for w in widgets] == [HIER_NAME]
    assert widgets[0].read_only is True and widgets[0].max_len == 3

    pack = FormPack.model_validate(
        {
            "form": "1040-NR",
            "tax_year": 2025,
            "jurisdiction": "federal",
            "source_url": "https://www.irs.gov/pub/irs-pdf/f1040nr.pdf",
            "pdf_sha256": "0" * 64,
            "acroform_root": ROOT,
            "fields": [{"line": "identifying_number.pg2", "field": HIER_FIELD, "type": "text",
                        "maxlen": 3, "comb": True, "format": "ssn_digits_only"}],
        }
    )
    report = verify_form(pack, str(pdf))
    ssn = next(check for check in report.clipping if check.name == HIER_NAME)
    assert ssn.status == "FAIL" and "MaxLen is 3" in ssn.detail
