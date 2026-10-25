"""The pack-less fill (Phase K JK16, 2026-10-25): describe_unmapped and fill_unmapped on synthetic demo blanks.

KG5 (the grade and a content-stream stamp on every page, no switch), KG6 (no passing anchor table: worksheet only),
KG7 (ReadOnly, pushbutton, viewer-guard, signature, calculated and hidden widgets are never written; every value is
labelled "agent-computed, unverified"), KG11 (none refused; low and med refused unless confirmed) and ADR-0002 rules
1, 10, 13 and 14. Each binding reading of an ADR-0002 open question is flipped once to show it is one constant.
Offline: synthetic demo returns built by pdf_fixtures.make_demo_return; demo values only.
"""
from __future__ import annotations

import inspect
import io
import json
import re

import pytest
import yaml
from pypdf import PdfReader, PdfWriter

from taxfill_core import anchor as A
from taxfill_core import unmapped as U
from taxfill_core.fetch import UnmappedBlankRefused, fetch_unmapped_blank, load_unmapped_blank
from taxfill_core.filler import UNMAPPED_STAMP
from taxfill_core.stamp import stamp_check
from taxfill_core.unmapped import UnmappedFillRefused, describe_unmapped, fill_unmapped

from pdf_fixtures import DEMO_BOX_X, demo_rows, make_demo_return

JUR = "states/sd"
YEAR = 2025
CALC_TOTAL = {"aa": {"C": "AFSimple_Calculate('SUM', new Array('wages', 'interest'));"}}
FORMAT_ONLY = {"aa": {"F": "AFNumber_Format(2, 0, 0, 0, '', true);"}}
CUSTOM_FORMAT = {"aa": {"F": "event.value = util.printf('%.2f', event.value * 12);"}}


def _url(n: int) -> str:
    return f"https://www.tax.example.gov/forms/{YEAR}/demo-{n}.pdf"


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": True,
                                    "thresholds": {"top": 3.0, "med": 2.0}, "top_tier_kinds": ["text"]}),
                    encoding="utf-8")
    return path


@pytest.fixture
def failing_table(tmp_path):
    path = tmp_path / "failing.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "method": A.METHOD, "passed": False,
                                    "thresholds": {"top": 3.0, "med": 2.0}}), encoding="utf-8")
    return path


class Env:
    """One stored blank and the calls that use it (the local-blank route: no network)."""

    def __init__(self, tmp_path, pdf, n: int, title: str):
        self.tmp = tmp_path
        self.kw = {"workspace_root": tmp_path / "ws", "cache_dir": tmp_path / "cache"}
        self.blank = fetch_unmapped_blank(_url(n), tax_year=YEAR, expected_title=title, local_blank=pdf,
                                          jurisdiction=JUR, **self.kw)
        self.out = tmp_path / "drafts" / f"demo-{n}.pdf"

    def describe(self, table, **kw):
        loaded = load_unmapped_blank(self.blank.sha256, tax_year=YEAR, source_url=self.blank.source_url,
                                     jurisdiction=JUR, **self.kw)
        return describe_unmapped(loaded, anchor_table=table, **kw)

    def fill(self, table, values, **kw):
        return fill_unmapped(self.blank.sha256, source_url=self.blank.source_url, tax_year=YEAR, jurisdiction=JUR,
                             values=values, out_path=kw.pop("out_path", self.out), anchor_table=table, **self.kw, **kw)


def _fields(pdf) -> dict[str, str]:
    """Every field holding a value (not empty, not /Off)."""
    fields = (PdfReader(str(pdf)).get_fields() or {}).items()
    return {k: str(v.get("/V")) for k, v in fields if v.get("/V") is not None and str(v.get("/V")) not in ("", "/Off")}


def _reasons(result) -> dict[str, str]:
    return {h["field"]: h["reason"] for h in result["hand_write"]}


# ── demo forms ────────────────────────────────────────────────────────────────


def _demo1(tmp_path):
    """One page: six numbered amount rows (line 5 a calculated total), a name row captioned above its boxes, a
    checkbox captioned beside it, a numbered checkbox row, and a box with nothing printed near it."""
    texts, fields = demo_rows([
        ("1", "Wages, salaries, tips", "wages"),
        ("2", "Taxable interest", "interest"),
        ("3", "Ordinary dividends", "dividends"),
        ("4", "Other income", "other"),
        ("5", "Total income. Add lines 1 through 4", "total"),
        ("6", "Withholding", "withholding"),
        ("7", "Demo filer checked the box for this line", None),
    ])
    texts += [(1, 60, 690, "Your first name and middle initial", 7), (1, 300, 690, "Last name", 7),
              (1, 60, 470, "Check here if you are a demo filer", 9)]
    fields += [{"name": "first_name", "x": 60, "y": 672, "width": 200, "height": 14},
               {"name": "last_name", "x": 300, "y": 672, "width": 200, "height": 14},
               {"name": "demo_check", "kind": "checkbox", "x": 250, "y": 466, "size": 10, "on_value": "1"},
               {"name": "line7_check", "kind": "checkbox", "x": DEMO_BOX_X, "y": 492 - 2, "size": 10,
                "on_value": "1"},
               {"name": "stray", "x": 300, "y": 200, "width": 90, "height": 14}]
    return make_demo_return(tmp_path / "demo1.pdf", form="DEMO-1", texts=texts, fields=fields,
                            edits={"total": CALC_TOTAL})


def _demo2(tmp_path):
    """Two pages: a state choice box, a filing-status radio group, a 9-cell comb, a name printed in each page's header
    (one field, two widgets), an id box on both pages whose page-2 widget has nothing printed near it, and numbered
    rows on page 2."""
    t2, f2 = demo_rows([("8", "Demo credit", "credit"), ("9", "Demo payments", "payments")], page=2, top=600)
    texts = [(1, 60, 690, "Name shown on return", 7), (1, 60, 650, "State", 7), (1, 200, 650, "Demo id number", 7),
             (1, 60, 610, "Filing status", 9), (1, 120, 594, "Single", 8), (1, 200, 594, "Joint", 8),
             (2, 60, 720, "Name shown on return", 7), *t2]
    fields = [{"name": "hdr_name", "page": 1, "x": 60, "y": 672, "width": 200, "height": 14},
              {"name": "hdr_name", "page": 2, "x": 60, "y": 702, "width": 200, "height": 14},
              {"name": "state", "page": 1, "x": 60, "y": 632, "width": 60, "height": 14},
              {"name": "demo_id", "page": 1, "x": 200, "y": 632, "width": 120, "height": 14, "maxlen": 9, "comb": True},
              {"name": "hdr_id", "page": 1, "x": 340, "y": 672, "width": 100, "height": 14},
              {"name": "hdr_id", "page": 2, "x": 300, "y": 300, "width": 100, "height": 14},
              {"name": "status", "kind": "radio", "page": 1, "x": 104, "y": 592, "size": 10, "on_value": "/1"},
              {"name": "status", "kind": "radio", "page": 1, "x": 184, "y": 592, "size": 10, "on_value": "/2"},
              *f2]
    texts.append((1, 300, 690, "Demo id", 7))
    return make_demo_return(tmp_path / "demo2.pdf", form="DEMO-2", pages=2, texts=texts, fields=fields,
                            edits={"hdr_name": {"merge": True}, "hdr_id": {"merge": True},
                                   "state": {"options": ["SD", "ND", "MN"]}})


def _demo3(tmp_path, *, guard: bool = True):
    """One page of widgets that are never written (KG7), each on a numbered row, and one plain amount row."""
    texts, fields = demo_rows([
        ("10", "Amount the form fills itself", "ro_amount", {}),
        ("11", "Hidden amount", "hidden_amount"),
        ("12", "Screen-hidden amount", "noview_amount"),
        ("13", "Print this form", "print_button"),
        ("14", "Signature", "signature"),
        ("15", "Formatted amount", "format_only"),
        ("16", "Plain amount", "plain"),
        ("17", "Rescaled amount", "custom_format"),
    ])
    edits = {"ro_amount": {"ff": 1}, "hidden_amount": {"f": 2}, "noview_amount": {"f": 32 | 4},
             "print_button": {"ft": "/Btn", "ff": 1 << 16}, "signature": {"ft": "/Sig"}, "format_only": FORMAT_ONLY,
             "custom_format": CUSTOM_FORMAT}
    if guard:  # MO-1040's shape: a ReadOnly text panel over the whole page
        fields.append({"name": "viewer_panel", "x": 0, "y": 0, "width": 612, "height": 792})
        edits["viewer_panel"] = {"ff": 1}
    return make_demo_return(tmp_path / "demo3.pdf", form="DEMO-3", texts=texts, fields=fields, edits=edits)


# ── e2e on three demo forms ───────────────────────────────────────────────────


def test_e2e_demo_1_writes_anchored_values_and_hands_back_the_rest(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    values = {"wages": 52000, "interest": 120.4, "dividends": "75", "first_name": "Demo", "total": 52195,
              "stray": "A", "demo_check": "yes"}
    result = env.fill(table, values, money_fields=["wages", "interest", "total"], confirmed_fields=["first_name"],
                      provenance={"wages": "from a document"})
    assert result["grade"] == "unmapped_draft" and result["status"] == "unverified_draft"
    assert result["written"] == {"wages": "52000", "interest": "120", "dividends": "75", "first_name": "Demo"}
    assert _reasons(result) == {"total": "calculated", "stray": "unanchored", "demo_check": "needs_confirmation"}
    total = next(h for h in result["hand_write"] if h["field"] == "total")
    assert total["value"] == "52195" and total["printed_line"] == "5" and total["page"] == 1  # value kept for the user
    assert "agent-computed, unverified" == total["value_label"]
    assert any("rounded 120.4 to 120" in w for w in result["warnings"])
    # KG7 labels: every written value, provenance only beside the label; KG11 confirmations recorded
    assert result["labels"] == {"wages": "agent-computed, unverified; from a document",
                                "interest": "agent-computed, unverified", "dividends": "agent-computed, unverified",
                                "first_name": "agent-computed, unverified"}
    assert result["confirmed"] == {"first_name": "user-confirmed on the rendered page"}
    # the PDF: written once, values read back, nothing else filled, stamped on every page where it prints
    out = env.out
    assert result["out_path"] == str(out) and out.is_file()
    assert _fields(out) == {"wages": "52000", "interest": "120", "dividends": "75", "first_name": "Demo"}
    assert result["stamp"]["text"] == UNMAPPED_STAMP and result["stamp"]["pages"] == [1]
    assert stamp_check(out, UNMAPPED_STAMP)["ok"]
    assert [p for p in env.out.parent.iterdir()] == [out]  # no other file, no temporary copy
    # the worksheet: its own grade, lines ordered by page and printed line, every line labelled
    sheet = result["worksheet"]
    assert sheet["grade"] == "unmapped_draft"
    assert [ln["field"] for ln in sheet["lines"]] == ["wages", "interest", "dividends", "total", "first_name",
                                                      "demo_check", "stray"]
    assert all(ln["value_label"].startswith("agent-computed, unverified") for ln in sheet["lines"])
    assert result["limits"] == U.LIMITS and "verify_form" in result["next_step"]
    assert "never filing-grade" in result["next_step"]


def test_e2e_demo_2_choice_radio_comb_and_a_name_on_two_pages(tmp_path, table):
    env = Env(tmp_path, _demo2(tmp_path), 2, "DEMO-2")
    desc = env.describe(table)
    by = {f["name"]: f for f in desc["fields"]}
    assert len(by["hdr_name"]["widgets"]) == 2 and {w["page"] for w in by["hdr_name"]["widgets"]} == {1, 2}
    assert by["state"]["kind"] == "choice" and [o["export"] for o in by["state"]["options"]] == ["SD", "ND", "MN"]
    assert by["status"]["kind"] == "radio" and by["status"]["on_states"] == ["/1", "/2"]
    assert by["demo_id"]["comb"] and by["demo_id"]["maxlen"] == 9
    values = {"hdr_name": "Demo Filer", "state": "SD", "status": "/2", "demo_id": "000000000", "credit": 300,
              "payments": 410, "hdr_id": "D-1"}
    confirmed = ["hdr_name", "state", "status", "demo_id", "hdr_id"]
    result = env.fill(table, values, money_fields=["credit", "payments"], confirmed_fields=confirmed)
    assert result["written"] == {"hdr_name": "Demo Filer", "state": "SD", "status": "/2", "demo_id": "000000000",
                                 "credit": "300", "payments": "410"}
    # one field, two widgets: anchored on page 1, nothing printed near its page-2 widget — refused as a whole
    assert _reasons(result) == {"hdr_id": "unanchored"}
    hdr_id = next(f for f in desc["fields"] if f["name"] == "hdr_id")
    assert [w["anchor"]["confidence"] for w in hdr_id["widgets"]][1] == "none" and hdr_id["confidence"] == "none"
    reader = PdfReader(str(env.out))
    widgets = [a.get_object() for page in reader.pages for a in page.get("/Annots") or []]
    name_widgets = [w for w in widgets if w.get("/Parent") is not None and w["/Parent"].get("/T") == "hdr_name"]
    assert len(name_widgets) == 2 and all(int(w.get("/F", 0)) & 4 for w in name_widgets)  # both print
    assert _fields(env.out)["hdr_name"] == "Demo Filer" and _fields(env.out)["status"] == "/2"
    check = stamp_check(env.out, UNMAPPED_STAMP)
    assert check["ok"] and [p["page"] for p in check["pages"]] == [1, 2] == result["stamp"]["pages"]
    pages = [ln["page"] for ln in result["worksheet"]["lines"]]
    assert pages == sorted(pages)


def test_e2e_demo_3_never_writes_kg7_widgets_and_goes_on(tmp_path, table):
    env = Env(tmp_path, _demo3(tmp_path), 3, "DEMO-3")
    values = {"ro_amount": "1", "hidden_amount": "2", "noview_amount": "3", "print_button": "4", "signature": "Demo",
              "format_only": "6", "plain": "7", "viewer_panel": "8", "custom_format": "9"}
    # the page-covering guard shares every row band, so the anchor caps each box on the page at med (fail closed)
    result = env.fill(table, values, confirmed_fields=["plain", "format_only", "custom_format"])
    assert _reasons(result) == {"ro_amount": "read_only", "hidden_amount": "hidden", "noview_amount": "hidden",
                                "print_button": "pushbutton", "signature": "signature",
                                "custom_format": "custom_format_script", "viewer_panel": "viewer_guard"}
    # a standard Acrobat format call only formats: the value is written as given (KG7 as amended 2026-10-25)
    assert result["written"] == {"format_only": "6", "plain": "7"}
    assert _fields(env.out) == {"format_only": "6", "plain": "7"}
    assert result["guards_hidden"] == ["viewer_panel (page 1)"]
    assert all(h["why"] for h in result["hand_write"])
    assert stamp_check(env.out, UNMAPPED_STAMP)["ok"]  # the guard the fill hid does not cover the stamp
    # describe lists the same fields as never filled
    desc = env.describe(table)
    assert {h["field"]: h["reason"] for h in desc["hand_write"]} == _reasons(result)
    assert {f["name"] for f in desc["fields"] if f["fillable"]} == {"format_only", "plain"}


# ── KG7 / Open question 1: calculated and format-only widgets ─────────────────


def test_q1_a_calculated_total_and_a_custom_format_are_refused_a_standard_format_is_written(tmp_path, table,
                                                                                           monkeypatch):
    # ADR-0002 Open question 1, decided 2026-10-25: the user accepted the amendment
    assert U.FORMAT_ACTION_IS_CALCULATED is False
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    assert _reasons(env.fill(table, {"total": 1})) == {"total": "calculated"}
    env3 = Env(tmp_path / "three", _demo3(tmp_path, guard=False), 3, "DEMO-3")
    assert env3.fill(table, {"format_only": "6"})["written"] == {"format_only": "6"}
    assert _reasons(env3.fill(table, {"custom_format": "9"})) == {"custom_format": "custom_format_script"}
    # the earlier reading is one constant: any /F then refuses the field as calculated
    monkeypatch.setattr(U, "FORMAT_ACTION_IS_CALCULATED", True)
    assert _reasons(env3.fill(table, {"format_only": "6"})) == {"format_only": "calculated"}
    assert _reasons(env.fill(table, {"total": 1})) == {"total": "calculated"}


def test_kg11_low_and_med_are_refused_unless_confirmed(tmp_path, table, monkeypatch):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    desc = {f["name"]: f for f in env.describe(table)["fields"]}
    assert desc["first_name"]["confidence"] == "low" and desc["line7_check"]["confidence"] == "med"
    assert desc["wages"]["confidence"] == "anchored (unverified line map)"
    assert "high" not in {f["confidence"] for f in desc.values()}
    values = {"first_name": "Demo", "line7_check": True, "wages": 1}
    refused = env.fill(table, values)
    assert _reasons(refused) == {"first_name": "needs_confirmation", "line7_check": "needs_confirmation"}
    assert "'med'" in next(h["why"] for h in refused["hand_write"] if h["field"] == "line7_check")
    assert refused["written"] == {"wages": "1"} and refused["confirmed"] == {}
    written = env.fill(table, values, confirmed_fields=["first_name", "line7_check"])
    assert written["written"] == {"first_name": "Demo", "line7_check": "/1", "wages": "1"}
    assert set(written["confirmed"]) == {"first_name", "line7_check"}
    record = json.loads(PdfReader(str(env.out)).metadata["/TaxfillUnmapped"])
    assert set(record["confirmed"]) == {"first_name", "line7_check"}
    # Open question 13: a floor for med is one constant
    monkeypatch.setattr(U, "CONFIRM_TIERS", frozenset({A.LOW}))
    assert _reasons(env.fill(table, values)) == {"first_name": "needs_confirmation"}


def test_a_planted_unanchorable_widget_is_refused_even_when_confirmed(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    result = env.fill(table, {"stray": "A"}, confirmed_fields=["stray"])
    assert _reasons(result) == {"stray": "unanchored"} and result["written"] == {}
    assert result["hand_write"][0]["value"] == "A"


# ── rule 14: a malformed value refuses the whole call ─────────────────────────


@pytest.mark.parametrize("values, match", [
    ({"wages": 1, "no_such_field": "Demo"}, "unknown field name"),
    ({"state": "Demo-Choice"}, "not one of the 3 choices"),
    ({"status": "/3"}, "names no on-state"),
    ({"status": "yes"}, "yes is ambiguous"),
    ({"hdr_name": "D" * 400}, None),  # no /MaxLen: fits
    ({"demo_id": "1234567890"}, "comb box holds at most 9"),
    ({"credit": "Demo\nFiler"}, "single-line box"),
])
def test_rule_14_writes_no_pdf_and_echoes_no_value(tmp_path, table, values, match):
    env = Env(tmp_path, _demo2(tmp_path), 2, "DEMO-2")
    if match is None:
        assert env.fill(table, values, confirmed_fields=list(values))["written"]
        return
    with pytest.raises(UnmappedFillRefused, match=match) as info:
        env.fill(table, values, confirmed_fields=["hdr_name", "state", "status", "demo_id"])
    message = str(info.value)
    assert "nothing was written" in message and not env.out.exists()
    for value in values.values():
        assert str(value) not in message or str(value) in ("1", "yes")  # "yes" also names the rule


def test_rule_14_maxlen_refuses_a_plain_box(tmp_path, table):
    texts, fields = demo_rows([("1", "Demo code", "code", {"maxlen": 4})])
    env = Env(tmp_path, make_demo_return(tmp_path / "m.pdf", texts=texts, fields=fields), 4, "DEMO-1")
    with pytest.raises(UnmappedFillRefused, match="at most 4 \\(/MaxLen\\)") as info:
        env.fill(table, {"code": "ABCDE"})
    assert "ABCDE" not in str(info.value) and not env.out.exists()
    assert env.fill(table, {"code": "ABCD"})["written"] == {"code": "ABCD"}


def test_unknown_names_in_the_other_lists_refuse_too(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    with pytest.raises(UnmappedFillRefused, match="unknown field name"):
        env.fill(table, {"wages": 1}, confirmed_fields=["nope"])
    with pytest.raises(UnmappedFillRefused, match="provenance"):
        env.fill(table, {"wages": 1}, provenance={"wages": "from a friend"})
    with pytest.raises(UnmappedFillRefused, match="not a text field"):
        env.fill(table, {"wages": 1}, money_fields=["demo_check"])
    assert not env.out.exists()


# ── rule 1: a shipped pack wins, at the fill too ──────────────────────────────


def test_rule_1_the_fill_refuses_a_blank_a_pack_now_covers_and_names_the_pack(tmp_path, table, monkeypatch):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    root = tmp_path / "data"
    (root / "knowledge").mkdir(parents=True)
    pack_dir = root / "formpacks" / "states" / "sd" / str(YEAR) / "demo1"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        f"form: SD Form DEMO-1\njurisdiction: {JUR}\ntax_year: {YEAR}\n"
        f"source_url: https://www.tax.example.gov/other.pdf\npdf_sha256: {'0' * 64}\n", encoding="utf-8")
    monkeypatch.setenv("TAXFILL_DATA_DIR", str(root))
    with pytest.raises(UnmappedBlankRefused, match="form key 'demo1'") as info:
        env.fill(table, {"wages": 1})
    assert info.value.reason == "shipped_pack" and "printed form name" in str(info.value)
    assert not env.out.exists()


# ── KG5: the grade and the stamp ──────────────────────────────────────────────


def test_the_stamp_and_grade_have_no_switch():
    for fn in (fill_unmapped, describe_unmapped):
        params = set(inspect.signature(fn).parameters)
        assert not [p for p in params if re.search(r"stamp|grade|draft|label|filing", p)], params
    assert set(inspect.signature(fill_unmapped).parameters) == {
        "blank_sha256", "source_url", "tax_year", "jurisdiction", "values", "out_path", "money_fields", "provenance",
        "confirmed_fields", "expected_title", "cache_dir", "workspace_root", "anchor_table"}
    assert U.GRADE == "unmapped_draft" and UNMAPPED_STAMP == "UNMAPPED DRAFT \u2014 NOT FILING-GRADE"


def test_the_record_holds_no_values_and_every_page_fails_the_check_once_stripped(tmp_path, table):
    env = Env(tmp_path, _demo2(tmp_path), 2, "DEMO-2")
    result = env.fill(table, {"credit": 300, "hdr_name": "Demo Filer"}, money_fields=["credit"],
                      confirmed_fields=["hdr_name"], provenance={"hdr_name": "from the user"})
    raw = PdfReader(str(env.out)).metadata["/TaxfillUnmapped"]
    record = json.loads(raw)
    assert record["grade"] == "unmapped_draft" and record["written_fields"] == ["credit", "hdr_name"]
    assert record["sources"] == {"hdr_name": "from the user"} and record["blank_sha256"] == env.blank.sha256
    assert "300" not in raw and "Demo Filer" not in raw
    assert result["output_sha256"] == __import__("hashlib").sha256(env.out.read_bytes()).hexdigest()
    writer = PdfWriter(clone_from=str(env.out))
    page = writer.pages[0]
    content = page.get_contents()
    content.set_data(re.sub(rb"\(UNMAPPED DRAFT[^)]*\) Tj", b"() Tj", content.get_data()))
    page.replace_contents(content)
    buf = io.BytesIO()
    writer.write(buf)
    assert stamp_check(buf.getvalue(), UNMAPPED_STAMP)["failed_pages"] == [1]


# ── worksheet only: a flat blank (rule 10) and no passing table (KG6) ─────────


def test_a_flat_blank_gets_a_graded_worksheet_and_no_pdf(tmp_path, table):
    env = Env(tmp_path, make_demo_return(tmp_path / "flat.pdf", texts=[(1, 60, 600, "1 Wages")]), 5, "DEMO-1")
    assert env.blank.kind == "flat"
    result = env.fill(table, {"1": 52000, "2": "75"}, provenance={"1": "from a document"})
    assert result["grade"] == "unmapped_draft" and result["status"] == "worksheet_only"
    assert not env.out.exists() and "out_path" not in result
    assert result["worksheet"]["grade"] == "unmapped_draft" and "no printed line was matched" in result["worksheet"][
        "note"]
    assert [h["printed_line"] for h in result["hand_write"]] == ["1", "2"]
    assert result["labels"] == {"1": "agent-computed, unverified; from a document", "2": "agent-computed, unverified"}


def test_without_a_passing_anchor_table_no_pdf_is_written(tmp_path, table, failing_table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    result = env.fill(failing_table, {"wages": 52000}, money_fields=["wages"])
    assert result["status"] == "worksheet_only" and not env.out.exists()
    assert result["hand_write"][0]["value"] == "52000" and "KG6" in result["hand_write"][0]["why"]
    # rule 14 still applies to field names on a blank with fields
    with pytest.raises(UnmappedFillRefused, match="unknown field name"):
        env.fill(failing_table, {"nope": 1})
    assert env.fill(table, {"wages": 52000}, money_fields=["wages"])["status"] == "unverified_draft"


# ── describe (get_form_map) ───────────────────────────────────────────────────


def test_describe_lists_fields_anchors_hand_write_and_a_stamped_sweep(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    desc = env.describe(table)
    assert desc["grade"] == "unmapped_draft" and desc["form"] == "unmapped" and desc["jurisdiction"] == JUR
    assert desc["blank_sha256"] == env.blank.sha256 and desc["anchor_basis"]["passed"] is True
    wages = next(f for f in desc["fields"] if f["name"] == "wages")
    assert set(wages) == {"index", "name", "kind", "tooltip", "maxlen", "comb", "multiline", "options", "on_states",
                          "fillable", "refusal", "needs_confirmation", "widgets", "confidence"}
    assert wages["widgets"][0]["anchor"] == {"printed_line": "1", "label": "Wages, salaries, tips",
                                             "confidence": "anchored (unverified line map)"}
    assert {h["field"]: h["reason"] for h in desc["hand_write"]} == {"total": "calculated", "stray": "unanchored"}
    sweep = desc["sweep_path"]
    assert sweep.endswith(f"{env.blank.sha256}.sweep.pdf")
    text = PdfReader(sweep).pages[0].extract_text()
    fillable = [f for f in desc["fields"] if f["fillable"]]
    assert all(f"#{f['index']}" in text for f in fillable)
    total = next(f for f in desc["fields"] if f["name"] == "total")
    assert f"#{total['index']} " not in text + " "
    assert stamp_check(sweep, UNMAPPED_STAMP)["ok"]
    assert all(v.get("/V") in (None, "", "/Off") for v in (PdfReader(sweep).get_fields() or {}).values())


# ── the writer writes exactly the fields named (Phase K JK16 verifier fixes, 2026-10-25) ──────────────────────────


def _restructure(pdf, edit) -> None:
    """Apply ``edit(chain)`` to every widget's /Parent chain (widget first, root last), in place."""
    writer = PdfWriter(clone_from=str(pdf))
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            chain = [ref.get_object()]
            while chain[-1].get("/Parent") is not None:
                chain.append(chain[-1]["/Parent"].get_object())
            edit(chain)
    writer.write(str(pdf))


def _states(pdf) -> dict[str, str | None]:
    return {name: value for name, (value, _) in U._field_states(PdfReader(str(pdf))).items()}


def _leaf_collision_blank(tmp_path):
    """Top-level "wages" beside "sub.wages" (its parent "sub" carries /AA /C: calculated) and "grp.wages" (a plain
    field nobody names): both share the terminal /T "wages"."""
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    texts, fields = demo_rows([("1", "Wages, salaries, tips", "wages"), ("2", "Taxable interest", "interest"),
                               ("3", "Demo wages again", "grp.wages", {"hierarchical": True}),
                               ("5", "Total income. Add lines 1 through 4", "sub.wages", {"hierarchical": True})])
    pdf = make_demo_return(tmp_path / "collide.pdf", texts=texts, fields=fields)

    def calc(chain):
        for node in chain:
            if str(node.get("/T")) == "sub":
                node[NameObject("/AA")] = DictionaryObject({NameObject("/C"): DictionaryObject({
                    NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("event.value=1;")})})

    _restructure(pdf, calc)
    return pdf


def test_a_value_reaches_only_the_field_it_names_not_a_leaf_name_twin(tmp_path, table):
    env = Env(tmp_path, _leaf_collision_blank(tmp_path), 6, "DEMO-1")
    assert {f["name"]: f["refusal"] for f in env.describe(table)["fields"]}["sub.wages"] == "calculated"
    before = _states(env.blank.path)
    result = env.fill(table, {"wages": 52000, "interest": 10}, money_fields=["wages", "interest"])
    after = _states(env.out)
    assert after["sub.wages"] == before["sub.wages"] and after["grp.wages"] == before["grp.wages"]
    # written is the PDF's actual contents: every field that changed, and nothing else
    changed = {n: v for n, v in after.items() if v != before.get(n)}
    assert changed == result["written"] == {"wages": "52000", "interest": "10"}
    record = json.loads(PdfReader(str(env.out)).metadata[U.RECORD_KEY])
    assert record["written_fields"] == ["wages", "interest"] and result["hand_write"] == []


def test_a_stray_write_refuses_the_call_before_any_pdf_is_written(tmp_path, table, monkeypatch):
    env = Env(tmp_path, _leaf_collision_blank(tmp_path), 6, "DEMO-1")

    def pypdf_leaf_match(writer, updates):  # the old writer: pypdf's own name matching
        writer.update_page_form_field_values(None, dict(updates), auto_regenerate=False)

    monkeypatch.setattr(U, "_write_text_fields", pypdf_leaf_match)
    with pytest.raises(UnmappedFillRefused, match="not asked for changed \\('grp.wages', 'sub.wages'\\)") as info:
        env.fill(table, {"wages": 52000}, money_fields=["wages"])
    assert "52000" not in str(info.value) and not env.out.exists()


def test_a_field_that_inherits_ft_from_an_ancestor_gets_an_appearance(tmp_path, table):
    from pypdf.generic import NameObject

    texts, fields = demo_rows([("2", "Taxable interest", "grp.ftup", {"hierarchical": True})])
    pdf = make_demo_return(tmp_path / "ft.pdf", texts=texts, fields=fields)

    def hoist_ft(chain):  # /FT only on the root "grp", none on the terminal field "ftup"
        ft = next(n["/FT"] for n in chain if "/FT" in n)
        for node in chain:
            node.pop(NameObject("/FT"), None)
        chain[-1][NameObject("/FT")] = ft

    _restructure(pdf, hoist_ft)
    env = Env(tmp_path, pdf, 7, "DEMO-1")
    result = env.fill(table, {"grp.ftup": "77"})
    assert result["written"] == {"grp.ftup": "77"} and _states(env.out)["grp.ftup"] == "77"
    widget = next(ref.get_object() for ref in PdfReader(str(env.out)).pages[0]["/Annots"]
                  if ref.get_object().get("/Subtype") == "/Widget")
    assert b"(77) Tj" in widget["/AP"]["/N"].get_object().get_data()  # the box prints the value, not only /V


@pytest.mark.parametrize("value", ["日本 Demo", "Demo \U0001F600", "Δημο"])
def test_rule_14_a_value_the_font_cannot_print_is_refused_not_corrupted(tmp_path, table, value):
    texts, fields = demo_rows([("4", "Other income", "note")])
    env = Env(tmp_path, make_demo_return(tmp_path / "n.pdf", texts=texts, fields=fields), 8, "DEMO-1")
    with pytest.raises(UnmappedFillRefused, match="cannot print") as info:
        env.fill(table, {"note": value})
    assert value not in str(info.value) and "Demo" not in str(info.value) and not env.out.exists()
    assert env.fill(table, {"note": "Démo Fïler – €1"})["written"] == {"note": "Démo Fïler – €1"}  # WinAnsi holds these


def test_the_sweep_never_overwrites_the_stored_blank_or_its_record(tmp_path, table):
    env = Env(tmp_path, _demo1(tmp_path), 1, "DEMO-1")
    blank = env.blank.path
    record = blank.with_suffix(".json")
    kept = (blank.read_bytes(), record.read_bytes())
    for target in (blank, record):
        with pytest.raises(UnmappedFillRefused, match="sweep_path is the stored blank"):
            env.describe(table, sweep_path=target)
    assert (blank.read_bytes(), record.read_bytes()) == kept
    assert env.fill(table, {"wages": 1}, money_fields=["wages"])["status"] == "unverified_draft"
