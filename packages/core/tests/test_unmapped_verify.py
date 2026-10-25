"""The pack-less verify (Phase K JK17, 2026-10-25): verify_unmapped on drafts fill_unmapped wrote, and on drafts
changed after the fill.

KG5 (the grade "unmapped_draft" is unconditional, ok never implies filing-grade, a stamp-stripped page fails), KG7
(every written value keeps its label; a recompute match changes none), KG11 (the anchors re-derived per widget at
verify), ADR-0002's verify_form sections, the verified_at token and rule 15's probe. Each section has a test that
changes one thing in a passing draft and sees that section fail. Offline: synthetic demo returns built by
pdf_fixtures; demo values only.
"""
from __future__ import annotations

import inspect
import io
import json
import re

import pytest
import yaml
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject

from taxfill_core import anchor as A
from taxfill_core import unmapped as U
from taxfill_core import unmapped_verify as V
from taxfill_core.filler import UNMAPPED_STAMP  # noqa: F401
from taxfill_core.packbuild import _qualified_name
from taxfill_core.unmapped_verify import (
    UnmappedVerifyRefused,
    is_unmapped_draft,
    read_unmapped_record,
    verified_at_holds,
    verify_unmapped,
)

from test_unmapped_fill import JUR, YEAR, Env, _demo1, _demo2, _demo3

VALUES = {"wages": 52000, "interest": 120, "first_name": "Demo", "line7_check": True}
FILL_KW = {"money_fields": ["wages", "interest"], "confirmed_fields": ["first_name", "line7_check"],
           "provenance": {"wages": "from a document"}}


@pytest.fixture
def table(tmp_path):
    """A passing anchor benchmark table (KG6), as test_unmapped_fill's."""
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": True,
                                    "thresholds": {"top": 3.0, "med": 2.0}, "top_tier_kinds": ["text"]}),
                    encoding="utf-8")
    return path


def _verify(env, table, expected, **kw):
    return verify_unmapped(kw.pop("out", env.out), blank_sha256=env.blank.sha256,
                           source_url=kw.pop("source_url", env.blank.source_url), tax_year=kw.pop("tax_year", YEAR),
                           jurisdiction=JUR, expected=expected, anchor_table=table, **env.kw, **kw)


def _failed(result) -> set[str]:
    return {name for name, s in result["sections"].items() if s["failed"]}


@pytest.fixture
def draft(tmp_path, table):
    """A passing draft of demo form 1: (env, the fill's written map)."""
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    result = env.fill(table, VALUES, **FILL_KW)
    assert result["written"] == {"wages": "52000", "interest": "120", "first_name": "Demo", "line7_check": "/1"}
    return env, result["written"]


def _rewrite(path, *, values=None, clear=(), record=None, page_edit=None, annot_edit=None) -> None:
    """Change a draft after its fill, as a person or another tool could: write or clear values (by qualified name),
    edit the /Info record, a page or an annotation; everything else is copied as it stands."""
    writer = PdfWriter(clone_from=str(path))
    if values:
        U._write_text_fields(writer, values)
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") == "/Widget" and _qualified_name(annot) in clear:
                U._terminal(annot).pop(NameObject("/V"), None)
            if annot_edit is not None:
                annot_edit(annot)
    if record is not None:
        rec = json.loads(writer.metadata[U.RECORD_KEY])
        record(rec)
        writer.add_metadata({U.RECORD_KEY: json.dumps(rec, sort_keys=True)})
    if page_edit is not None:
        page_edit(writer)
    buf = io.BytesIO()
    writer.write(buf)
    path.write_bytes(buf.getvalue())


def _strip_stamp(writer, index: int = 0) -> None:
    page = writer.pages[index]
    content = page.get_contents()
    content.set_data(re.sub(rb"\(UNMAPPED DRAFT[^)]*\) Tj", b"() Tj", content.get_data()))
    page.replace_contents(content)


# ── a passing draft, on three demo forms ──────────────────────────────────────


def test_a_draft_as_written_passes_every_section_and_stays_an_unmapped_draft(draft, table):
    env, written = draft
    result = _verify(env, table, written)
    assert result["ok"] is True and _failed(result) == set()
    assert result["grade"] == "unmapped_draft" and result["verdict"] == "UNMAPPED" and "status" not in result
    assert set(result) == {"grade", "verdict", "ok", "output_sha256", "verified_at", "sections", "unverified_values",
                           "hand_write", "limits", "next_step"}
    assert list(result["sections"]) == list(V.SECTIONS)
    assert all(set(s) >= {"checked", "failed", "failures"} for s in result["sections"].values())
    assert result["sections"]["stamp"]["checked"] == 1 and result["sections"]["round_trip"]["checked"] == 4
    # KG7: every written value listed with its label; ok removes none; provenance only beside the label
    assert [(u["field"], u["value"], u["value_label"]) for u in result["unverified_values"]] == [
        ("wages", "52000", "agent-computed, unverified; from a document"),
        ("interest", "120", "agent-computed, unverified"), ("first_name", "Demo", "agent-computed, unverified"),
        ("line7_check", "/1", "agent-computed, unverified")]
    assert {h["field"]: h["reason"] for h in result["hand_write"]} == {"total": "calculated", "stray": "unanchored"}
    assert result["limits"] == V.UNMAPPED_VERDICT_LIMITS and "never filing-grade" in result["limits"][-1]


def test_a_rewrite_that_changes_nothing_still_passes(draft, table):
    """The tamper helper itself changes nothing a section reads: each failure below is the tamper's."""
    env, written = draft
    _rewrite(env.out)
    assert _verify(env, table, written)["ok"] is True


@pytest.mark.parametrize("make, values, kw", [
    (_demo2, {"hdr_name": "Demo Filer", "state": "SD", "status": "/2", "demo_id": "000000000", "credit": 300},
     {"money_fields": ["credit"], "confirmed_fields": ["hdr_name", "state", "status", "demo_id"]}),
    (_demo3, {"plain": "7", "ro_amount": "1"}, {"confirmed_fields": ["plain"]}),  # a viewer guard the fill hid
])
def test_the_other_demo_forms_pass_as_written(tmp_path, table, make, values, kw):
    env = Env(tmp_path, make(tmp_path), 2, "DEMO-2" if make is _demo2 else "DEMO-3")
    result = env.fill(table, values, **kw)
    verdict = _verify(env, table, result["written"])
    assert verdict["ok"] is True, {k: s["failures"] for k, s in verdict["sections"].items() if s["failed"]}
    assert verdict["sections"]["stamp"]["checked"] == (2 if make is _demo2 else 1)


def test_an_action_that_targets_a_page_is_not_a_change(tmp_path, table):
    """A /GoTo action names a page object, whose content holds the stamp: the annotation compare stops at the page
    (MO-1040's page-2 'go to' buttons failed 'unchanged' on a real blank before it did)."""
    pdf = _demo1(tmp_path)
    writer = PdfWriter(clone_from=str(pdf))
    page = writer.pages[0]
    link = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (300, 100, 380, 112)]),
        NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/D"): ArrayObject(
            [page.indirect_reference, NameObject("/Fit")])})})
    page[NameObject("/Annots")].append(writer._add_object(link))
    writer.write(str(pdf))
    env = Env(tmp_path, pdf, 1, "DEMO-1")
    result = env.fill(table, {"wages": 1}, money_fields=["wages"])
    assert _verify(env, table, result["written"])["ok"]


# ── KG5: the grade is unconditional, ok never implies filing-grade ────────────


# The journey guard's claim test (packages/mcp-server/tests/test_journeys.py, KG5), applied to every response: a grade
# other than unmapped_draft, a truthy filing-grade / ready flag, a final status, or the words not negated right before.
_CLAIM_TEXT = re.compile(
    r"filing[\s_-]*grade|ready[\s_-]+(?:to[\s_-]+(?:file|sign|mail)|for[\s_-]+filing)|\bis[\s_-]+final\b", re.IGNORECASE)
_NEGATED = re.compile(r"\b(?:not|never)\s+(?:(?:yet|a|an)\s+)?$", re.IGNORECASE)


def _grade_claims(obj, where: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            k = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if k == "grade" and value != "unmapped_draft":
                found.append(f"{where}.{key} = {value!r}")
            elif k in {"filinggrade", "filingready", "readytofile", "readyforfiling"} and value:
                found.append(f"{where}.{key} = {value!r}")
            elif k == "status" and isinstance(value, str) and (value.lower() in ("final", "ready")
                                                               or _CLAIM_TEXT.search(value)):
                found.append(f"{where}.{key} = {value!r}")
            found += _grade_claims(value, f"{where}.{key}")
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            found += _grade_claims(value, f"{where}[{i}]")
    elif isinstance(obj, str):
        found += [f"{where}: {obj[max(0, m.start() - 60):m.end()]}" for m in _CLAIM_TEXT.finditer(obj)
                  if not _NEGATED.search(obj[max(0, m.start() - 40):m.start()])]
    return found


def test_no_response_claims_filing_grade_or_carries_a_status(draft, table, tmp_path):
    env, written = draft
    passing = _verify(env, table, written)
    _rewrite(env.out, values={"wages": "1"})
    failing = _verify(env, table, written)
    assert passing["ok"] and not failing["ok"]
    for result in (passing, failing):
        assert result["grade"] == "unmapped_draft" and "status" not in result
        assert _grade_claims(result) == []
        assert "filing-grade" in result["next_step"] and "never filing-grade" in result["next_step"]
    assert _grade_claims({"x": "this draft is filing-grade"}) and _grade_claims({"grade": "final"})  # it finds them
    # no parameter lifts the grade, and the fill's and describe's responses claim nothing either
    params = set(inspect.signature(verify_unmapped).parameters)
    assert not [p for p in params if re.search(r"stamp|grade|draft|label|filing|status|ok", p)], params
    fill = env.fill(table, VALUES, **FILL_KW)
    assert fill["status"] == "unverified_draft" and _grade_claims(fill) == [] and _grade_claims(env.describe(table)) == []


def test_a_stamp_stripped_page_fails_verify(tmp_path, table):
    env = Env(tmp_path, _demo2(tmp_path), 2, "DEMO-2")
    written = env.fill(table, {"credit": 300}, money_fields=["credit"])["written"]
    assert _verify(env, table, written)["ok"]
    _rewrite(env.out, page_edit=lambda w: _strip_stamp(w, 1))
    result = _verify(env, table, written)
    assert not result["ok"] and "verified_at" not in result
    stamp = result["sections"]["stamp"]
    assert stamp["checked"] == 2 and stamp["failed"] == 1 and stamp["failures"][0].startswith("page 2:")
    assert "KG5" in stamp["failures"][0]


@pytest.mark.parametrize("drawn", [True, False])
def test_a_stamp_under_an_annotation_that_draws_fails(draft, table, drawn):
    """A printing /Square over the stamp: drawn, the print-path check fails it; with an empty appearance (nothing
    drawn, so the stamp is still legible) the box-overlap check does (KG5: the stamp lies under no visible annotation)."""
    env, written = draft
    box = env.fill(table, VALUES, **FILL_KW)["stamp"]["placements"][0]["rect"]  # the same draft, written again

    def cover(writer):
        from pypdf.generic import StreamObject

        square = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject(
            "/Square"), NameObject("/Rect"): ArrayObject([FloatObject(v) for v in box]),
            NameObject("/F"): NumberObject(4)})
        if not drawn:
            empty = StreamObject()
            empty.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                          NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(1),
                                                            FloatObject(1)])})
            square[NameObject("/AP")] = DictionaryObject({NameObject("/N"): writer._add_object(empty)})
        writer.pages[0][NameObject("/Annots")].append(writer._add_object(square))

    _rewrite(env.out, page_edit=cover)
    stamp = _verify(env, table, written)["sections"]["stamp"]
    assert stamp["failed"] >= 1
    if not drawn:
        assert any("under an annotation that draws" in f for f in stamp["failures"]), stamp


# ── round_trip and unchanged ──────────────────────────────────────────────────


def test_a_value_changed_after_the_fill_fails_round_trip(draft, table):
    env, written = draft
    _rewrite(env.out, values={"wages": "52001"})
    result = _verify(env, table, written)
    assert _failed(result) == {"round_trip", "unchanged"}  # unchanged: its appearance is not the fill's (JK17 fix)
    for failure in (result["sections"]["round_trip"]["failures"][0], *result["sections"]["unchanged"]["failures"]):
        assert "'wages'" in failure and "52001" not in failure and "52000" not in failure  # no value echoed


def test_a_field_cleared_after_the_fill_fails_round_trip(draft, table):
    env, written = draft
    _rewrite(env.out, clear={"interest"})
    result = _verify(env, table, written)
    assert "round_trip" in _failed(result) and "'interest'" in result["sections"]["round_trip"]["failures"][0]


def test_an_extra_field_written_after_the_fill_fails_unchanged(draft, table):
    env, written = draft
    _rewrite(env.out, values={"dividends": "75"})
    result = _verify(env, table, written)
    assert _failed(result) == {"unchanged"}
    assert "'dividends'" in result["sections"]["unchanged"]["failures"][0]


def test_a_value_set_on_a_parent_field_alone_fails_unchanged(tmp_path, table):
    """A /V set on a field dict above its widgets, with no appearance: no annotation changes, so only the field-level
    regression_diff against the blank sees it."""
    from pypdf.generic import TextStringObject

    env = Env(tmp_path, _demo2(tmp_path), 2, "DEMO-2")
    written = env.fill(table, {"credit": 300}, money_fields=["credit"])["written"]

    def set_parent(annot):
        parent = annot.get("/Parent")
        if parent is not None and parent.get_object().get("/T") == "hdr_name":
            parent.get_object()[NameObject("/V")] = TextStringObject("Demo Filer")

    _rewrite(env.out, annot_edit=set_parent)
    result = _verify(env, table, written)
    assert _failed(result) == {"unchanged"} and "'hdr_name'" in result["sections"]["unchanged"]["failures"][0]


def test_page_content_edited_outside_the_stamp_fails_unchanged(draft, table):
    env, written = draft
    from taxfill_core.overlay import _overlay_page

    def draw(writer):
        page = writer.pages[0]
        page.merge_page(_overlay_page(page, b"q 0 g 300 300 40 12 re f Q\n"))

    _rewrite(env.out, page_edit=draw)
    result = _verify(env, table, written)
    assert _failed(result) == {"unchanged"}
    assert "printed content differs from the blank's outside the stamp" in result["sections"]["unchanged"][
        "failures"][0]


def test_an_annotation_changed_on_a_field_not_written_fails_unchanged(draft, table):
    env, written = draft

    def move(annot):
        if _qualified_name(annot) == "dividends":
            annot[NameObject("/MK")] = DictionaryObject({NameObject("/BG"): ArrayObject([FloatObject(0)])})

    _rewrite(env.out, annot_edit=move)
    result = _verify(env, table, written)
    assert _failed(result) == {"unchanged"}
    assert "'dividends' changed though nothing was written to it" in result["sections"]["unchanged"]["failures"][0]


# ── clipping and flags ────────────────────────────────────────────────────────


def test_a_clipped_value_fails_clipping(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    written = env.fill(table, {"dividends": "Demo dividends from a demo fund held all year"})["written"]
    result = _verify(env, table, written)
    assert _failed(result) == {"clipping"} and "P-001" in result["sections"]["clipping"]["failures"][0]


def test_a_written_widget_hidden_after_the_fill_fails_flags(draft, table):
    env, written = draft

    def hide(annot):
        if _qualified_name(annot) == "wages":
            annot[NameObject("/F")] = NumberObject(2 | 4)

    _rewrite(env.out, annot_edit=hide)
    result = _verify(env, table, written)
    assert _failed(result) == {"flags", "unchanged"}
    assert "'wages'" in result["sections"]["flags"]["failures"][0] and "Hidden" in result["sections"]["flags"][
        "failures"][0]
    assert any("field 'wages'" in f and "/F" in f for f in result["sections"]["unchanged"]["failures"])


# ── the draft is the fill's own document (Phase K JK17 fix, 2026-10-25) ───────
# verify rebuilds the draft with the fill's own code (unmapped._build_draft) and compares the file with it object by
# object: a written widget's appearance and keys, the stamp's text, size and place, every page key, the catalog and
# its /AcroForm. Each edit below passed verify with verified_at before the fix, and each changes what prints or how a
# viewer draws it.


def _widget(writer, name):
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            if annot.get("/Subtype") == "/Widget" and _qualified_name(annot) == name:
                return annot
    raise AssertionError(name)


def _set_need_appearances(writer, on: bool) -> None:
    from pypdf.generic import BooleanObject

    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(on)


def _edit_ap(writer, name: str, edit) -> None:
    ap = _widget(writer, name)["/AP"]["/N"].get_object()
    ap.set_data(edit(ap.get_data()))


def _ap_prints_another_amount(writer):
    _edit_ap(writer, "wages", lambda d: d.replace(b"52000", b"99999"))
    _set_need_appearances(writer, False)  # a viewer then draws the edited appearance, not /V


def _ap_white(writer):
    from pypdf.generic import TextStringObject

    _edit_ap(writer, "wages", lambda d: re.sub(rb"0 g|[\d.]+ [\d.]+ [\d.]+ rg", b"1 g", d))
    _widget(writer, "wages")[NameObject("/DA")] = TextStringObject("/Helv 9 Tf 1 g")


def _mk_black(writer):
    _widget(writer, "wages")[NameObject("/MK")] = DictionaryObject({NameObject("/BG"): ArrayObject([NumberObject(0)])})
    _edit_ap(writer, "wages", lambda d: b"0 g 0 0 90 14 re f\n" + d)


def _ap_removed(writer):
    _widget(writer, "wages").pop(NameObject("/AP"))
    _set_need_appearances(writer, False)


def _js(script: str) -> DictionaryObject:
    from pypdf.generic import TextStringObject

    return DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject(script)})


def _open_action(writer):
    writer._root_object[NameObject("/OpenAction")] = _js("this.getField('wages').value = '99999';")


def _xfa(writer):
    writer._root_object["/AcroForm"][NameObject("/XFA")] = writer._add_object(DictionaryObject())


def _format_script(writer):
    U._terminal(_widget(writer, "wages"))[NameObject("/AA")] = DictionaryObject(
        {NameObject("/F"): _js("event.value = '99999';")})


def _read_only(writer):
    U._terminal(_widget(writer, "wages"))[NameObject("/Ff")] = NumberObject(1)


def _user_unit(writer):
    writer.pages[0][NameObject("/UserUnit")] = NumberObject(3)


@pytest.mark.parametrize("edit, where", [
    (_ap_prints_another_amount, "field 'wages' (a widget on page 1) /AP /N"),
    (_ap_prints_another_amount, "the document catalog /AcroForm /NeedAppearances"),
    (_ap_white, "field 'wages' (a widget on page 1) /DA"),
    (_ap_white, "field 'wages' (a widget on page 1) /AP /N"),
    (_mk_black, "field 'wages' (a widget on page 1)"),
    (_ap_removed, "field 'wages' (a widget on page 1): lacks /AP"),
    (_open_action, "the document catalog: carries /OpenAction"),
    (_xfa, "the document catalog /AcroForm: carries /XFA"),
    (_format_script, "field 'wages' (a widget on page 1): carries /AA"),
    (_read_only, "field 'wages' (a widget on page 1) /Ff"),
    (_user_unit, "page 1: carries /UserUnit"),
])
def test_an_edit_the_fill_did_not_make_fails_unchanged(draft, table, edit, where):
    env, written = draft
    _rewrite(env.out, page_edit=edit)
    result = _verify(env, table, written)
    assert result["ok"] is False and "verified_at" not in result and "unchanged" in _failed(result)
    failures = result["sections"]["unchanged"]["failures"]
    assert any(f.startswith(where) for f in failures), failures
    assert not any("99999" in f or "52000" in f for f in failures)  # no value echoed


def _stamp_stream(writer):
    """The page-1 content stream that draws the stamp, edited in place (the page keeps its content array)."""
    for part in writer.pages[0].get_object().raw_get("/Contents").get_object():
        stream = part.get_object()
        if b"UNMAPPED DRAFT" in stream.get_data():
            return stream
    raise AssertionError("no stamp stream")


def _stamp_carries_an_amount(writer):
    stream = _stamp_stream(writer)
    stream.set_data(re.sub(rb"\((UNMAPPED DRAFT[^)]*)\) Tj", rb"[(\1) -20000 (99999)] TJ", stream.get_data()))


def _white_stamp_copy(writer):
    stream = _stamp_stream(writer)
    stream.set_data(stream.get_data() + b"\nq 1 1 1 rg BT /F1-0 48 Tf 0.3 0 0 4 20 500 Tm "
                                        b"(UNMAPPED DRAFT \\227 NOT FILING\\055GRADE) Tj ET Q\n")


def _stamp_shrunk(writer):
    stream = _stamp_stream(writer)
    stream.set_data(re.sub(rb"/(\S+) 10 Tf", rb"/\1 4 Tf", stream.get_data(), count=1))


@pytest.mark.parametrize("edit", [_stamp_carries_an_amount, _white_stamp_copy, _stamp_shrunk])
def test_a_stamp_that_carries_more_or_is_shrunk_fails_though_the_stamp_still_prints(draft, table, edit):
    """The page compare sets the stamp's own text objects aside; the stamp section only asks that it prints. A stamp
    object that also prints an amount, a second stamp copy painted white over the amount rows, and a stamp shrunk
    to 4 pt each pass both; the rebuilt draft names the stamp's stream."""
    env, written = draft
    _rewrite(env.out, page_edit=edit)
    result = _verify(env, table, written)
    assert result["sections"]["stamp"]["failed"] == 0  # it still prints: the stamp check alone cannot see these
    assert _failed(result) == {"unchanged"} and "verified_at" not in result
    assert any(f.startswith("page 1 /Contents[") and "stream content differs" in f
               for f in result["sections"]["unchanged"]["failures"])


# ── anchors (KG11 re-derived at verify) ───────────────────────────────────────


def _forge(env, written: dict, name: str, value: str, *, confirm: bool = False) -> dict:
    """Write a field the fill refused straight into the draft and enter it in the record, as a direct core caller
    could: every other section then passes, so only the anchors re-check stands between it and a pass."""
    def record(rec):
        rec["written_fields"].append(name)
        rec["labels"][name] = U.VALUE_LABEL
        if confirm:
            rec["confirmed"][name] = U.CONFIRMED_LABEL

    _rewrite(env.out, values={name: value}, record=record)
    return {**written, name: value}


def test_a_written_field_anchored_none_fails_anchors_even_when_confirmed(draft, table):
    env, written = draft
    result = _verify(env, table, _forge(env, written, "stray", "A", confirm=True))
    assert _failed(result) == {"anchors"}
    assert "anchored 'none'" in result["sections"]["anchors"]["failures"][0]


def test_an_unconfirmed_low_or_med_field_fails_anchors(tmp_path, table, monkeypatch):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    written = env.fill(table, {"wages": 1}, money_fields=["wages"])["written"]
    forged = _forge(env, written, "first_name", "Demo")  # low, with no recorded confirmation
    result = _verify(env, table, forged)
    assert _failed(result) == {"anchors"} and "only 'low'" in result["sections"]["anchors"]["failures"][0]
    # med is refused like low until the user sets a floor (Open question 13): one constant
    monkeypatch.setattr(V, "CONFIRM_TIERS", frozenset({"med"}))
    assert _verify(env, table, forged)["ok"]


def test_confirmed_fields_at_verify_can_narrow_the_recorded_confirmations_never_add_one(draft, table):
    env, written = draft
    narrowed = _verify(env, table, written, confirmed_fields=["first_name"])
    assert _failed(narrowed) == {"anchors"} and "'line7_check'" in narrowed["sections"]["anchors"]["failures"][0]
    assert "only 'med'" in narrowed["sections"]["anchors"]["failures"][0]
    forged = _forge(env, written, "dividends", "75")  # top tier: no confirmation needed
    assert _verify(env, table, forged)["ok"]
    forged = _forge(env, forged, "last_name", "Filer")  # low; named at verify only, not recorded
    assert _failed(_verify(env, table, forged, confirmed_fields=["first_name", "line7_check", "last_name"])) == {
        "anchors"}


def test_a_field_the_fill_never_writes_fails_anchors(draft, table):
    env, written = draft
    result = _verify(env, table, _forge(env, written, "total", "52120"))
    assert "anchors" in _failed(result) and "calculated, KG7" in result["sections"]["anchors"]["failures"][0]


# ── record ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key, value", [("tax_year", YEAR - 1), ("blank_sha256", "0" * 64),
                                        ("source_url", "https://www.tax.example.gov/other.pdf"),
                                        ("jurisdiction", "states/nd"), ("grade", "final"),
                                        ("stamp", "DRAFT")])
def test_a_record_that_disagrees_with_the_call_fails_record(draft, table, key, value):
    env, written = draft
    _rewrite(env.out, record=lambda rec: rec.__setitem__(key, value))
    result = _verify(env, table, written)
    assert _failed(result) == {"record"}
    assert result["grade"] == "unmapped_draft"  # a record that says otherwise changes no grade


def test_expected_must_name_exactly_the_recorded_fields(draft, table):
    env, written = draft
    fewer = {k: v for k, v in written.items() if k != "interest"}
    result = _verify(env, table, fewer)
    assert "record" in _failed(result) and "in expected but not recorded" not in result["sections"]["record"][
        "failures"][0]
    assert "recorded but not in expected: 'interest'" in result["sections"]["record"]["failures"][0]
    _rewrite(env.out, record=lambda rec: rec["labels"].__setitem__("wages", "from a document"))
    assert "KG7 label" in " ".join(_verify(env, table, written)["sections"]["record"]["failures"])


def test_a_pdf_with_no_record_fails_record(draft, table):
    env, written = draft

    def drop(writer):
        writer._info.get_object().pop(NameObject(U.RECORD_KEY))

    _rewrite(env.out, page_edit=drop)
    assert not is_unmapped_draft(env.out)
    assert "no /TaxfillUnmapped record" in _verify(env, table, written)["sections"]["record"]["failures"][0]


# ── recompute and declared relations (KG7 labels) ─────────────────────────────


def test_recompute_reports_a_match_and_changes_no_label(draft, table):
    env, written = draft
    result = _verify(env, table, written, independent={"wages": 52000, "interest": 120.4})
    recompute = result["sections"]["recompute"]
    assert result["ok"] and recompute["checked"] == 2 and recompute["failed"] == 0
    assert recompute["label"] == V.RECOMPUTE_LABEL and "changes no label" in recompute["label"]
    assert all(c["status"] == "PASS" and c["value_label"] == "agent-computed, unverified" for c in recompute["checks"])
    labels = {u["field"]: u["value_label"] for u in result["unverified_values"]}
    assert labels["wages"] == "agent-computed, unverified; from a document"  # a match changes no label


def test_a_recompute_mismatch_or_an_unwritten_field_fails_recompute(draft, table):
    env, written = draft
    result = _verify(env, table, written, independent={"wages": 52001, "dividends": 75})
    assert _failed(result) == {"recompute"} and result["sections"]["recompute"]["failed"] == 2
    assert "verified_at" not in result


def test_declared_relations_are_checked_and_labeled_agent_declared(draft, table):
    env, written = draft
    good = ["{wages} + interest == 52120", "max(wages, 1) - {interest} == 51880", "dividends == 0"]
    result = _verify(env, table, written, declared_relations=good)
    section = result["sections"]["declared_relations"]
    assert result["ok"] and section["checked"] == 3 and section["label"] == "agent-declared, not of record"
    assert all(c["label"] == "agent-declared, not of record" and c["status"] == "PASS" for c in section["checks"])
    assert section["checks"][2]["blank_as_zero"] == ["dividends"]
    bad = ["wages == 1", "nope == 1", "wages ==", "first_name == 0"]
    result = _verify(env, table, written, declared_relations=bad)
    section = result["sections"]["declared_relations"]
    assert _failed(result) == {"declared_relations"} and section["failed"] == 4
    assert all(c["label"] == "agent-declared, not of record" for c in section["checks"])
    assert "not a field of this form" in section["checks"][1]["detail"]
    assert "could not read declared relation" in section["checks"][2]["detail"]
    assert "does not hold a number" in section["checks"][3]["detail"]


def test_a_relation_that_does_not_parse_is_named_once_with_the_parser_s_reason(draft, table):
    """Phase K JK17 fix (2026-10-25): the reason was cut at the relation's own ': ', echoing a mangled fragment."""
    env, written = draft
    detail = _verify(env, table, written, declared_relations=["lambda: 1 == 1"])["sections"]["declared_relations"][
        "checks"][0]["detail"]
    assert detail.startswith("could not read declared relation 'lambda: 1 == 1': unexpected character ':' at "
                             "position 6 — write '<expr> == <expr>'"), detail
    assert detail.count("1 == 1") == 1 and "pack.yaml" not in detail


# ── verified_at ───────────────────────────────────────────────────────────────


def test_verified_at_only_when_ok_and_any_byte_change_voids_it(draft, table):
    env, written = draft
    result = _verify(env, table, written)
    token = result["verified_at"]
    assert token["output_sha256"] == result["output_sha256"] and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ",
                                                                              token["time"])
    assert verified_at_holds(token, env.out)
    data = env.out.read_bytes()
    env.out.write_bytes(data + b"\n")  # one byte after %%EOF: the file still opens and still verifies
    assert not verified_at_holds(token, env.out)
    again = _verify(env, table, written)
    assert again["ok"] and again["verified_at"]["output_sha256"] != token["output_sha256"]
    env.out.write_bytes(data)
    assert verified_at_holds(token, env.out)
    assert not verified_at_holds(None, env.out) and not verified_at_holds({"output_sha256": 1}, env.out)
    assert not verified_at_holds(token, env.out.with_name("missing.pdf"))


# ── rule 15's probe ───────────────────────────────────────────────────────────


def test_the_rule_15_probe_reads_the_record_and_never_raises(draft, tmp_path):
    env, _ = draft
    assert is_unmapped_draft(env.out) and is_unmapped_draft(env.out.read_bytes())
    assert read_unmapped_record(env.out)["grade"] == "unmapped_draft"
    assert not is_unmapped_draft(env.blank.path) and read_unmapped_record(env.blank.path) is None
    assert not is_unmapped_draft(tmp_path / "missing.pdf")
    (tmp_path / "junk.pdf").write_bytes(b"not a pdf")
    assert not is_unmapped_draft(tmp_path / "junk.pdf") and not is_unmapped_draft(b"")
    _rewrite(env.out, page_edit=lambda w: w.add_metadata({U.RECORD_KEY: "{not json"}))
    assert is_unmapped_draft(env.out) and read_unmapped_record(env.out) is None  # still a draft


# ── refusals ──────────────────────────────────────────────────────────────────


def test_refusals_echo_no_value_and_name_the_next_step(draft, table, tmp_path):
    env, written = draft
    with pytest.raises(UnmappedVerifyRefused, match="no draft PDF at the path given"):
        _verify(env, table, written, out=tmp_path / "missing.pdf")
    (tmp_path / "junk.pdf").write_bytes(b"Demo Filer 52000")
    with pytest.raises(UnmappedVerifyRefused, match="not a PDF") as info:
        _verify(env, table, written, out=tmp_path / "junk.pdf")
    assert "52000" not in str(info.value)
    with pytest.raises(UnmappedVerifyRefused, match="'written' map") as info:
        _verify(env, table, {"wages": 52000})
    assert "52000" not in str(info.value)
    with pytest.raises(UnmappedVerifyRefused, match="plain numbers"):
        _verify(env, table, written, independent={"wages": "52000"})
    with pytest.raises(UnmappedVerifyRefused, match="declared_relations must be a list"):
        _verify(env, table, written, declared_relations="wages == 1")


def test_a_kind_mismatch_is_worded_with_its_article():
    # the JK17 re-verify: "a stream where the fill writes a array"
    from taxfill_core.unmapped_verify import _article

    assert [f"{_article(k)} {k}" for k in ("array", "stream", "dict", "number")] == [
        "an array", "a stream", "a dict", "a number"]


def test_more_than_ten_differences_are_not_given_a_count(monkeypatch, tmp_path):
    # the JK17 re-verify: _graph_diff stops after the first ten, so a count of the rest understated it ("and 1 more")
    import pypdf

    import taxfill_core.unmapped_verify as uv

    monkeypatch.setattr(uv, "_replay", lambda *a, **k: object())
    monkeypatch.setattr(pypdf, "PdfReader", lambda *a, **k: object())
    monkeypatch.setattr(uv, "_graph_diff", lambda draft, replay: [f"page 1 /K{i}: differs" for i in range(11)])
    out = uv._as_filled(tmp_path / "blank.pdf", b"", {}, {})
    assert len(out) == 11 and out[-1] == "and more such differences (the comparison stops after the first ten)"
    assert not any(ch.isdigit() for ch in out[-1])
