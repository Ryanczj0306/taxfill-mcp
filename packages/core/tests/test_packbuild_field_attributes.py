"""extract_fields reads every attribute the pack-less fallback needs (Phase K JK14, 2026-10-24).

Before JK14, extract_fields read /FT, /MaxLen, /AP and /Rect only and called every non-/Btn field "text"
(docs/dev/adr/ADR-0002-fallback-surface.md, refusal rule 12). JK16 refuses ReadOnly, pushbutton, signature and
calculated widgets (KG7) and enforces /MaxLen, the comb bit and /Opt (rule 14), so it needs the field kind, the
/Ff bits, /Opt, /TU, /DA, /Q and the /AA actions — read up the /Parent chain.

Offline tests build synthetic blanks the way pdf_fixtures does and edit the field dicts with pypdf. The
network-marked tests read real 2025 pack blanks from the shared cache (TAXFILL_BLANKS_CACHE) and pin one widget
per kind and flag by name.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pdf_fixtures import make_acroform_pdf
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.packbuild import build_skeleton, extract_fields
from taxfill_core.schemas.formpack import FormPack, load_pack

REPO = Path(__file__).resolve().parents[3]
ROOT = "topmostSubform[0]"


def _edit(pdf: Path, edits: dict[str, dict]) -> Path:
    """Apply raw key edits to the field dict whose /T is a key of ``edits`` (a widget merged with its field)."""
    writer = PdfWriter(clone_from=str(pdf))
    for page in writer.pages:
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            node = annot if annot.get("/T") is not None else annot["/Parent"].get_object()
            for key, value in edits.get(str(node.get("/T")), {}).items():
                if value is None:
                    del node[NameObject(key)]
                else:
                    node[NameObject(key)] = value
    with pdf.open("wb") as fh:
        writer.write(fh)
    return pdf


def _js(code: str) -> DictionaryObject:
    action = DictionaryObject()
    action[NameObject("/S")] = NameObject("/JavaScript")
    action[NameObject("/JS")] = TextStringObject(code)
    return action


def _aa(**triggers: str) -> DictionaryObject:
    aa = DictionaryObject()
    for trigger, code in triggers.items():
        aa[NameObject(f"/{trigger}")] = _js(code)
    return aa


@pytest.fixture
def synthetic(tmp_path) -> dict[str, dict]:
    pdf = make_acroform_pdf(tmp_path / "blank.pdf", [
        {"name": "ssn", "maxlen": 9, "comb": True},
        {"name": "notes"},
        {"name": "locked"},
        {"name": "total"},
        {"name": "datefmt"},
        {"name": "customfmt"},
        {"name": "keystroke_only"},
        {"name": "state"},
        {"name": "listbox"},
        {"name": "sig"},
        {"name": "print_btn", "kind": "checkbox"},
        {"name": "agree", "kind": "checkbox", "on_value": "/1"},
        {"name": "status", "kind": "radio", "on_value": "/1"},
        {"name": "status", "kind": "radio", "on_value": "/2"},
        {"name": f"{ROOT}.Page1[0].f1_1[0]", "maxlen": 9, "hierarchical": True},
    ])
    opt = ArrayObject([
        ArrayObject([TextStringObject("GA"), TextStringObject("GEORGIA")]),
        TextStringObject("AL"),
    ])
    _edit(pdf, {
        "ssn": {"/TU": TextStringObject("Your social security number"), "/Q": NumberObject(1)},
        "notes": {"/Ff": NumberObject(1 << 12 | 1 << 23), "/DA": TextStringObject("/TiRo 9 Tf 0 g")},
        "locked": {"/Ff": NumberObject(1 | 2)},
        "total": {"/AA": _aa(C='AFSimple_Calculate("SUM", new Array ("a", "b"));')},
        "datefmt": {"/AA": _aa(F='AFDate_FormatEx("mm/dd/yyyy");')},
        "customfmt": {"/AA": _aa(F='event.value = util.printf("%.2f", event.value * 12);')},
        "keystroke_only": {"/AA": _aa(K="AFNumber_Keystroke(2, 0, 0, 0, '', true);")},
        "state": {"/FT": NameObject("/Ch"), "/Ff": NumberObject(1 << 17), "/Opt": opt},
        "listbox": {"/FT": NameObject("/Ch"), "/Ff": NumberObject(0), "/Opt": ArrayObject([TextStringObject("A")])},
        "sig": {"/FT": NameObject("/Sig")},
        "print_btn": {"/Ff": NumberObject(1 << 16), "/A": _js("this.print();")},
    })
    # The hierarchical terminal field carries the flags; its /T-less kid widget inherits them.
    _edit(pdf, {"f1_1[0]": {"/Ff": NumberObject(1 << 24 | 1), "/AA": _aa(C="event.value = 1;")}})
    return {f["name"]: f for f in extract_fields(pdf)}


def test_field_kinds(synthetic):
    kinds = {name: f["kind"] for name, f in synthetic.items()}
    assert kinds["ssn"] == "text" and kinds["notes"] == "text"
    assert kinds["agree"] == "checkbox"
    assert kinds["status"] == "radio"
    assert kinds["print_btn"] == "pushbutton"
    assert kinds["state"] == "choice" and kinds["listbox"] == "choice"
    assert kinds["sig"] == "signature"


def test_type_stays_checkbox_or_text_for_the_skeleton_writer(synthetic):
    # build_skeleton keys on `type`: every /Btn is "checkbox", everything else "text" (unchanged by JK14).
    assert {f["type"] for f in synthetic.values()} == {"checkbox", "text"}
    assert synthetic["print_btn"]["type"] == "checkbox" and synthetic["status"]["type"] == "checkbox"
    assert synthetic["state"]["type"] == "text" and synthetic["sig"]["type"] == "text"


def test_flags_are_named_booleans(synthetic):
    ssn, notes, locked = synthetic["ssn"], synthetic["notes"], synthetic["locked"]
    assert ssn["comb"] and ssn["maxlen"] == 9 and not ssn["multiline"] and not ssn["read_only"]
    assert notes["multiline"] and notes["do_not_scroll"] and not notes["comb"]
    assert locked["read_only"] and locked["required"]
    status = synthetic["status"]
    assert status["radio"] and status["no_toggle_to_off"] and not status["pushbutton"]
    assert synthetic["print_btn"]["pushbutton"] and not synthetic["print_btn"]["radio"]
    # a bit the field's type does not define reads False: bit 17 on a text field is not "pushbutton"
    assert not synthetic["notes"]["pushbutton"] and not synthetic["status"]["comb"]


def test_tooltip_da_and_quadding(synthetic):
    assert synthetic["ssn"]["tooltip"] == "Your social security number"
    assert synthetic["ssn"]["quadding"] == 1
    assert synthetic["notes"]["da_font"] == "TiRo" and synthetic["notes"]["da_size"] == 9.0
    assert synthetic["locked"]["tooltip"] is None and synthetic["locked"]["quadding"] == 0


def test_choice_options_and_type(synthetic):
    state = synthetic["state"]
    assert state["choice_type"] == "combo"
    assert state["options"] == [{"export": "GA", "display": "GEORGIA"}, {"export": "AL", "display": "AL"}]
    assert synthetic["listbox"]["choice_type"] == "list"
    assert synthetic["ssn"]["choice_type"] is None and synthetic["ssn"]["options"] == []


def test_calculate_and_custom_format_actions_mark_a_field_calculated(synthetic):
    # KG7 as amended 2026-10-25 (ADR-0002 Open question 1): /AA /C, or an /AA /F that is not one standard Acrobat
    # format call, makes the field calculated, ReadOnly or not; a standard format call or a keystroke-only /AA does not.
    assert synthetic["total"]["calculated"] and not synthetic["total"]["read_only"]
    assert not synthetic["datefmt"]["calculated"] and synthetic["datefmt"]["format_action"]
    assert synthetic["customfmt"]["calculated"] and synthetic["customfmt"]["format_action"]
    assert not synthetic["total"]["format_action"]
    assert not synthetic["keystroke_only"]["calculated"] and synthetic["keystroke_only"]["javascript"]
    assert not synthetic["ssn"]["calculated"] and not synthetic["ssn"]["javascript"]
    # an /A JavaScript action (a print button) is JavaScript, not a calculation
    assert synthetic["print_btn"]["javascript"] and not synthetic["print_btn"]["calculated"]


def test_flags_and_actions_inherit_through_parent(synthetic):
    kid = synthetic[f"{ROOT}.Page1[0].f1_1[0]"]
    assert kid["comb"] and kid["read_only"] and kid["calculated"] and kid["maxlen"] == 9


def test_pushbutton_stream_on_states(tmp_path):
    # A pushbutton's /AP /N is one stream; its keys (/BBox, /Matrix ...) were reported as on-states before JK14.
    pdf = make_acroform_pdf(tmp_path / "b.pdf", [{"name": "btn", "kind": "checkbox"}])
    writer = PdfWriter(clone_from=str(pdf))
    annot = writer.pages[0]["/Annots"][0].get_object()
    stream = annot["/AP"]["/N"].get_object()["/Yes"]
    annot["/AP"].get_object()[NameObject("/N")] = stream  # one stream, as a real pushbutton's /N is
    annot[NameObject("/Ff")] = NumberObject(1 << 16)
    with (tmp_path / "b.pdf").open("wb") as fh:
        writer.write(fh)
    (field,) = extract_fields(tmp_path / "b.pdf")
    assert field["kind"] == "pushbutton"
    assert field["on_states"] == []


def test_skeleton_output_is_unchanged_by_the_new_keys(tmp_path):
    pdf = make_acroform_pdf(tmp_path / "s.pdf", [
        {"name": f"{ROOT}.Page1[0].f1_7[0]", "maxlen": 9, "comb": True},
        {"name": f"{ROOT}.Page1[0].c1_1[0]", "kind": "checkbox", "on_value": "/1"},
    ])
    skel = build_skeleton(pdf, form="X", jurisdiction="federal", tax_year=2025,
                          source_url="https://www.irs.gov/pub/irs-pdf/fx.pdf")
    assert skel["fields"] == [
        {"line": "f1_7[0]", "field": "f1_7[0]", "type": "text", "maxlen": 9},
        {"line": "c1_1[0]::/1", "field": "c1_1[0]", "type": "checkbox", "on_state": "/1"},
    ]


def test_skeleton_skips_pushbuttons_with_one_todo(tmp_path):
    # Phase K JK14 (2026-10-24): a pushbutton holds no value. Before, the skeleton carried it as a checkbox
    # (on_state "/1" plus a no-on-state TODO); now it gets no fields entry and one TODO lists every pushbutton.
    pdf = make_acroform_pdf(tmp_path / "b.pdf", [
        {"name": f"{ROOT}.Page1[0].f1_1[0]", "maxlen": 9},
        {"name": f"{ROOT}.Page1[0].PrintButton[0]", "kind": "checkbox"},
        {"name": f"{ROOT}.Page1[0].ClearButton[0]", "kind": "checkbox"},
    ])
    writer = PdfWriter(clone_from=str(pdf))
    for annot in writer.pages[0]["/Annots"][1:]:
        annot = annot.get_object()
        annot["/AP"].get_object()[NameObject("/N")] = annot["/AP"]["/N"].get_object()["/Yes"]
        annot[NameObject("/Ff")] = NumberObject(1 << 16)
    with (tmp_path / "b.pdf").open("wb") as fh:
        writer.write(fh)
    skel = build_skeleton(tmp_path / "b.pdf", form="X", jurisdiction="federal", tax_year=2025,
                          source_url="https://www.irs.gov/pub/irs-pdf/fx.pdf")
    todo = skel.pop("_todo")
    assert skel["fields"] == [{"line": "f1_1[0]", "field": "f1_1[0]", "type": "text", "maxlen": 9}]
    assert todo == ["pushbutton, not fillable — skipped 2: PrintButton[0], ClearButton[0]"]
    FormPack.model_validate(skel)


# ── real 2025 pack blanks (network-marked: read from the shared cache) ────────────────────────────────────────


def _fields(pack_rel: str) -> dict[str, dict]:
    pack = load_pack(REPO / "formpacks" / pack_rel / "pack.yaml")
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    out: dict[str, dict] = {}
    for f in extract_fields(blank):
        out.setdefault(f["name"], f)
    return out


@pytest.mark.network
def test_f1040_2025_ssn_comb_checkbox_and_multiline():
    fields = _fields("federal/2025/f1040")
    ssn = fields["topmostSubform[0].Page1[0].f1_16[0]"]  # "Your social security number"
    assert (ssn["kind"], ssn["comb"], ssn["maxlen"], ssn["read_only"]) == ("text", True, 9, False)
    assert ssn["da_font"] == "HelveticaLTStd-Bold" and ssn["da_size"] == 8.0
    multiline = fields["topmostSubform[0].Page2[0].f2_37[0]"]
    assert multiline["multiline"] and not multiline["comb"]
    checkboxes = [f for f in fields.values() if f["kind"] == "checkbox"]
    assert checkboxes and all(f["type"] == "checkbox" and f["on_states"] for f in checkboxes)
    assert not any(f["calculated"] or f["javascript"] for f in fields.values())


@pytest.mark.network
def test_f1040es_2025_read_only_and_pushbutton():
    fields = _fields("federal/2025/f1040es")
    date = fields["topmostSubform[0].Page9[0].Table_RecordEstimated[0].Line1[0].Date1[0]"]
    assert date["read_only"] and date["kind"] == "text" and date["quadding"] == 1
    button = fields["topmostSubform[0].Page10[0].LinkActivator[0]"]
    assert button["kind"] == "pushbutton" and button["pushbutton"] and button["on_states"] == []


@pytest.mark.network
def test_f8316_2025_radio_group():
    fields = _fields("federal/2025/f8316")
    radio = fields["A"]
    assert radio["kind"] == "radio" and radio["radio"] and radio["no_toggle_to_off"]
    assert radio["on_states"] == ["/1"]


@pytest.mark.network
def test_ga500_2025_choice_field_and_calculated_total():
    fields = _fields("states/ga/2025/ga500")
    state = fields["STATELIST"]
    assert state["kind"] == "choice" and state["choice_type"] == "combo"
    assert {"export": "GA", "display": "GEORGIA"} in state["options"]
    assert state["tooltip"] == "Select State that issued your Driver's License/State ID"
    total = fields["L7C"]  # AFSimple_Calculate("SUM", new Array ("L7A", "L7B"))
    assert total["calculated"] and total["javascript"]


@pytest.mark.network
def test_de_pit_res_2025_calculated_totals():
    fields = _fields("states/de/2025/pit_res")
    total = fields["ln04ColA"]  # line 4 = lines 1 + 2 + 3, computed by the form's /AA /C script
    assert total["calculated"] and total["javascript"]
    calculated = [f for f in fields.values() if f["calculated"]]
    assert any(not f["read_only"] for f in calculated)  # KG7: calculated whether ReadOnly or not


@pytest.mark.network
def test_ar1000f_2025_signature_widget():
    fields = _fields("states/ar/2025/ar1000f")
    sig = fields["Signature1"]
    assert sig["kind"] == "signature" and sig["type"] == "text"


@pytest.mark.network
def test_skeleton_of_f1040es_2025_skips_its_four_pushbuttons():
    # Phase K JK14 (2026-10-24): the 2025 Form 1040-ES carries four LinkActivator pushbuttons (pages 10-11).
    pack = load_pack(REPO / "formpacks" / "federal/2025/f1040es" / "pack.yaml")
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    widgets = extract_fields(blank)
    buttons = [f["name"] for f in widgets if f["kind"] == "pushbutton"]
    assert len(buttons) == 4 and all("LinkActivator" in name for name in buttons)
    skel = build_skeleton(blank, form="1040-ES", jurisdiction="federal", tax_year=2025, source_url=pack.source_url)
    todo = skel.pop("_todo")
    assert len(skel["fields"]) == len(widgets) - 4
    assert not any("LinkActivator" in f["field"] for f in skel["fields"])
    mentions = [t for t in todo if "LinkActivator" in t]
    assert len(mentions) == 1 and mentions[0].startswith("pushbutton, not fillable — skipped 4: ")
    assert all(name.removeprefix(skel["acroform_root"] + ".") in mentions[0] for name in buttons)
    FormPack.model_validate(skel)
