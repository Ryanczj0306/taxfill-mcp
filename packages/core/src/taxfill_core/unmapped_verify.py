"""The pack-less verify: check a draft fill_unmapped wrote (Phase K JK17, 2026-10-25).

Core only, as JK14 and JK16's core half were: no MCP tool calls this yet (ADR-0002 is Proposed). The MCP wiring of
verify_form with ``form="unmapped"`` will call :func:`verify_unmapped`, whose result is the unmapped verify_form
response ADR-0002's Decision sets out; the pack path's verify_form and verify_filing will call
:func:`is_unmapped_draft`, rule 15's probe.

- :func:`verify_unmapped` — the verdict on one draft: ``grade`` ("unmapped_draft", always: KG5), ``verdict``
  ("UNMAPPED"), ``ok`` (true only when every section passes), ``output_sha256``, ``verified_at`` (only when ok: the
  output's sha256 and the time), ``sections``, ``unverified_values``, ``hand_write``, ``limits``
  (UNMAPPED_VERDICT_LIMITS) and ``next_step``. It carries no ``status``: ``ok`` and ``verified_at`` say what passed,
  and nothing a caller passes lifts the grade. Each section has ``checked``, ``failed`` and ``failures``:

  - ``record``: the output's /Info record (/TaxfillUnmapped) agrees with the call — the blank's sha256, its source
    URL, the tax year, the jurisdiction, the written fields (exactly ``expected``'s names), the grade, the stamp
    text, and a KG7 label on every written field. (This section is an addition to the ADR's list: the record is
    what binds a draft to the blank its anchors are re-derived from.)
  - ``round_trip``: exactly the written names read back, each with exactly the expected value.
  - ``unchanged``: regression_diff against the blank (no other field's value or state changed), and no page or
    annotation changed: page boxes and count; each page's objects, render and text layer equal the blank's once the
    stamp's own text object is set aside; every annotation keeps its keys, except a written widget (its value,
    appearance and flags) and a viewer guard the fill hid (P-027). And (Phase K JK17 fix, 2026-10-25) the whole
    document equals the one the fill's own code (unmapped._build_draft) writes from the blank and ``expected``,
    compared object by object from the catalog: a written widget's appearance, /DA, /MK, /AA and field flags, the
    stamp's text, size and place, every page key, the /AcroForm (/NeedAppearances, /XFA) and document actions all
    have to be the fill's. A draft written by another version of taxfill can fail here: fill it again.
  - ``clipping`` (P-001, verify.clipping_scan over the written text widgets), ``flags`` (P-027,
    verify.widget_flag_problems).
  - ``stamp``: stamp.stamp_check on every page (KG5), and the stamp's box overlaps no annotation that draws.
  - ``anchors``: KG11 re-derived per widget from the blank named by ``blank_sha256``: a written field with a widget
    anchored "none" fails, and one anchored in unmapped.CONFIRM_TIERS fails unless its confirmation is recorded in
    the draft (``confirmed_fields`` can only narrow that set); a written field the fill may never write (KG7) fails.
  - ``recompute``: ``independent`` (field name -> what the agent says calc returned) against the on-disk value, in
    whole dollars; a match is reported here only and changes no label (KG7).
  - ``declared_relations``: relations over field names that the agent declares, each labeled
    DECLARED_RELATION_LABEL; a failure fails verify.

- :func:`verified_at_holds` — whether a ``verified_at`` token still names the file's bytes (any change voids it).

Not authenticated (Phase K JK17, 2026-10-25): the token is the output's sha256 and a time, unsigned, so any caller can
write one for a file verify never saw; and the KG11 confirmations are read from the draft's own /Info record, which a
direct core caller can edit (that gives no more than fill_form's ``confirmed_fields`` already does). So a token proves
nothing on its own: whoever needs "verify_form ran on this sha256" (JK18's evals, the MCP wiring) must keep the
token it got from verify itself, server side, or sign it and the record (an HMAC with a per-install key) when the MCP
wiring lands.
- :func:`is_unmapped_draft` / :func:`read_unmapped_record` — rule 15's probe: the /Info record, read with pypdf
  only; never raises (a PDF it cannot read is not a draft, so today's error text stands on the pack path).

Refusals (:class:`UnmappedVerifyRefused`) follow JK16's: no value is echoed, and the next step is named.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from taxfill_core.datadir import user_path
from taxfill_core.unmapped import (
    CONFIRM_TIERS,
    CONFIRMED_LABEL,
    GRADE,
    PROVENANCE_SOURCES,
    RECORD_KEY,
    VALUE_LABEL,
    _field_states,
    _build_draft,
    _Field,
    _hand_write,
    _read_fields,
    _table_passed,
    value_label,
)

__all__ = [
    "DECLARED_RELATION_LABEL",
    "RECOMPUTE_LABEL",
    "SECTIONS",
    "UNMAPPED_VERDICT_LIMITS",
    "UnmappedVerifyRefused",
    "VERDICT",
    "is_unmapped_draft",
    "read_unmapped_record",
    "verified_at_holds",
    "verify_unmapped",
]

VERDICT = "UNMAPPED"
DECLARED_RELATION_LABEL = "agent-declared, not of record"
RECOMPUTE_LABEL = (f"a match is reported here only and changes no label: every value stays {VALUE_LABEL} (KG7)")
SECTIONS = ("record", "round_trip", "unchanged", "clipping", "flags", "stamp", "anchors", "recompute",
            "declared_relations")

#: What the UNMAPPED verdict does NOT prove — on every response, on the OVERLAY_VERDICT_LIMITS model, so no agent reads
#: ``ok: true`` as more than it is (ADR-0002 Decision, verify_form). The last entry stays last.
UNMAPPED_VERDICT_LIMITS: list[str] = [
    "No line map: each field was tied to a printed line by a pack-blind anchor, an unverified guess; a value in the "
    "wrong box of a plausible line passes every check here — render_form and a check of every page remain mandatory.",
    "No relations of record: no line's arithmetic was checked against the form; declared_relations are the agent's "
    "own, labeled 'agent-declared, not of record'.",
    "No identity or cross_form checks: names, identifying numbers and amounts carried from other forms were not "
    "compared.",
    "No P-003 required-checkbox audit: an unanswered required box is not found.",
    "No revision pin: the blank is named by its sha256 only, and its revision was not reviewed.",
    "Form scripts and XFA bindings did not run: calculated boxes and boxes with a custom format script are not "
    "written (hand_write) and keep whatever the blank prints there, such as a default 0; a box with a standard "
    "Acrobat format holds its value unformatted; nothing the form would compute was checked.",
    f"Every value is {VALUE_LABEL}: ok removes no label, and a recompute match changes none.",
    "ok means only that the checks listed in sections passed on this file; the draft is never filing-grade.",
]
NEXT_STEP_OK = (
    "The listed checks passed, and that is all ok means: this is an unmapped draft, never filing-grade. Render every "
    "page with render_form and check each value against its printed line and the form's instructions; write the "
    "hand_write entries on the printed form by hand. Any change to the file voids verified_at: verify again after it."
)
NEXT_STEP_FAILED = (
    "Fix what each failed section names: refill with fill_form (form='unmapped') from the same blank, or write the "
    "line on the printed form by hand, then verify again. verified_at is given only when every section passes, and "
    "even then this draft is never filing-grade."
)

_RENDER_SCALE = 2.0  # pixels per point for the page-content comparison (the blank's render vs the draft's)
_REF_RE = re.compile(r"\{([^{}]+)\}")
_ALIAS = "taxfill_field_{}"


class UnmappedVerifyRefused(ValueError):
    """The verify cannot run on what it was given; the message names no value and says what to do next."""


# ── rule 15's probe ──────────────────────────────────────────────────────────


def _info_record(pdf: str | Path | bytes) -> tuple[bool, dict | None]:
    """(the /Info record key is present, the record parsed as a JSON object or None). Never raises."""
    try:
        from pypdf import PdfReader  # noqa: PLC0415

        source = io.BytesIO(pdf) if isinstance(pdf, bytes) else str(user_path(pdf))
        info = PdfReader(source).trailer.get("/Info")
        info = info.get_object() if info is not None else None
        if info is None or RECORD_KEY not in info:
            return False, None
        raw = info[RECORD_KEY]
        raw = raw.get_object() if hasattr(raw, "get_object") else raw
        try:
            record = json.loads(str(raw))
        except ValueError:
            return True, None
        return True, record if isinstance(record, dict) else None
    except Exception:  # noqa: BLE001 — rule 15: a PDF the probe cannot read falls through to today's error text
        return False, None


def is_unmapped_draft(pdf: str | Path | bytes) -> bool:
    """Rule 15's probe: True when the PDF's /Info carries the /TaxfillUnmapped record (whatever it holds).

    Reads that /Info key only, with pypdf (no stamp, no pdfium pass). It never raises: a missing, unreadable or
    encrypted file returns False, so the pack path's own error text stands for it.
    """
    return _info_record(pdf)[0]


def read_unmapped_record(pdf: str | Path | bytes) -> dict | None:
    """The draft's /TaxfillUnmapped record as a dict; None when there is none, or it is not a JSON object, or the
    file cannot be read. Never raises."""
    return _info_record(pdf)[1]


# ── the verified_at token ────────────────────────────────────────────────────


def verified_at_holds(token: Mapping | None, pdf: str | Path | bytes) -> bool:
    """Whether ``token`` (a verify response's ``verified_at``) still holds for ``pdf``: the file hashes to the sha256
    it names. Any later change to the file voids it. Never raises (an unreadable file or a malformed token: False).
    The token is not signed (module doc): this says the bytes match a token, not that verify issued it."""
    if not isinstance(token, Mapping):
        return False
    digest = token.get("output_sha256")
    if not isinstance(digest, str) or not isinstance(token.get("time"), str):
        return False
    try:
        data = pdf if isinstance(pdf, bytes) else user_path(pdf).read_bytes()
    except (OSError, TypeError, ValueError):
        return False
    return hashlib.sha256(data).hexdigest() == digest


# ── inputs ───────────────────────────────────────────────────────────────────


def _check_inputs(expected, independent, declared_relations, confirmed_fields):
    if not isinstance(expected, Mapping) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in expected.items()):
        raise UnmappedVerifyRefused(
            "expected must be fill_form's written map (field name -> the rendered value, as strings) for this "
            "output — pass the 'written' map the fill returned; nothing was verified")
    if independent is not None and (
            not isinstance(independent, Mapping)
            or not all(isinstance(k, str) and isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
                       for k, v in independent.items())):
        raise UnmappedVerifyRefused(
            "independent must map field names to plain numbers (what calc returned for that field) — nothing was "
            "verified")
    for name, given in (("declared_relations", declared_relations), ("confirmed_fields", confirmed_fields)):
        if given is not None and (isinstance(given, (str, bytes)) or not all(isinstance(r, str) for r in given)):
            raise UnmappedVerifyRefused(f"{name} must be a list of strings — nothing was verified")
    return (dict(independent or {}), list(declared_relations or []),
            None if confirmed_fields is None else set(confirmed_fields))


def _section(checked: int, failures: list[str], **extra) -> dict:
    return {"checked": checked, "failed": len(failures), "failures": failures, **extra}


# ── record ───────────────────────────────────────────────────────────────────


def _record_section(present: bool, record: dict | None, *, blank_sha256: str, source_url: str, tax_year: int,
                    jurisdiction: str, expected: Mapping[str, str]) -> dict:
    if not present:
        return _section(1, ["the PDF carries no /TaxfillUnmapped record: it is not a draft fill_form wrote in "
                            "unmapped mode (or the record was removed) — fill it again with fill_form"])
    if record is None:
        return _section(1, ["the /TaxfillUnmapped record is not a JSON object: the record was altered — fill the "
                            "draft again with fill_form"])
    failures: list[str] = []
    for key, want in (("grade", GRADE), ("blank_sha256", blank_sha256), ("source_url", source_url),
                      ("tax_year", tax_year), ("jurisdiction", jurisdiction)):
        if record.get(key) != want:
            failures.append(f"the record's {key} does not match this call's: the draft was not filled from the blank, "
                            f"year and jurisdiction named here — verify it with the values its fill was given, or "
                            f"fill again")
    from taxfill_core.filler import UNMAPPED_STAMP  # noqa: PLC0415

    if record.get("stamp") != UNMAPPED_STAMP:
        failures.append("the record does not name the draft stamp: the record was altered — fill the draft again")
    written = record.get("written_fields")
    if not isinstance(written, list) or len(written) != len(set(map(str, written))) or set(written) != set(expected):
        names = set(written) if isinstance(written, list) else set()
        extra, missing = sorted(map(str, names - set(expected))), sorted(set(expected) - names)
        detail = "; ".join(p for p in (
            f"recorded but not in expected: {', '.join(map(repr, extra[:10]))}" if extra else "",
            f"in expected but not recorded: {', '.join(map(repr, missing[:10]))}" if missing else "") if p)
        failures.append("the record's written fields are not exactly expected's names"
                        + (f" ({detail})" if detail else "")
                        + " — pass the 'written' map the fill of this file returned")
    labels = record.get("labels") if isinstance(record.get("labels"), Mapping) else {}
    sources = record.get("sources") if isinstance(record.get("sources"), Mapping) else {}
    unlabeled = sorted(n for n in expected if not str(labels.get(n, "")).startswith(VALUE_LABEL)
                       or labels.get(n) != value_label(sources.get(n)))
    if unlabeled:
        failures.append(f"the record does not carry the KG7 label '{VALUE_LABEL}' on "
                        f"{', '.join(map(repr, unlabeled[:10]))} — the record was altered; fill the draft again")
    confirmed = record.get("confirmed") if isinstance(record.get("confirmed"), Mapping) else {}
    odd = sorted(str(n) for n, v in confirmed.items() if n not in expected or v != CONFIRMED_LABEL)
    if odd:
        failures.append(f"the record's confirmations name {', '.join(map(repr, odd[:10]))}, which the fill did not "
                        f"write as user-confirmed — the record was altered; fill the draft again")
    return _section(7, failures)


# ── round trip and unchanged ─────────────────────────────────────────────────


def _round_trip(after: Mapping[str, tuple], expected: Mapping[str, str], buttons: set[str]) -> dict:
    failures: list[str] = []
    for name, want in expected.items():
        if name not in after:
            failures.append(f"field {name!r} is not in the draft — fill again with the qualified names get_form_map "
                            f"returns")
            continue
        value, states = after[name]
        if name in buttons:
            on = [s for s in states if s not in (None, "/Off")]
            if want == "/Off":
                good = value in (None, "/Off") and not on
            else:
                good = value == want and want in on and all(s == want for s in on)
        else:
            good = value == want
        if not good:
            failures.append(f"field {name!r} does not read back the value fill_form wrote: the file was changed "
                            f"after the fill (or the value never reached it) — fill again and verify the new output")
    return _section(len(expected), failures)


def _canon(obj, depth: int = 0):
    """A comparable form of a PDF object: dictionaries without their back-links (/P, /Parent, /Kids), streams by
    their decoded data, numbers rounded."""
    from pypdf.generic import DictionaryObject, FloatObject, NumberObject, StreamObject  # noqa: PLC0415

    if hasattr(obj, "get_object"):
        obj = obj.get_object()
    if depth > 8:
        return "..."
    if isinstance(obj, StreamObject):
        try:
            data = hashlib.sha256(obj.get_data()).hexdigest()
        except Exception:  # noqa: BLE001 — an undecodable stream compares by its raw bytes
            data = hashlib.sha256(obj._data or b"").hexdigest()
        meta = {k: v for k, v in obj.items() if k not in ("/Length", "/Filter", "/DecodeParms")}
        return ("stream", _canon(DictionaryObject(meta), depth + 1), data)
    if isinstance(obj, dict) and obj.get("/Type") in ("/Page", "/Pages"):
        return "<page>"  # an action's target page: its content holds the stamp, so it is compared on its own
    if isinstance(obj, dict):
        return tuple(sorted((str(k), _canon(v, depth + 1)) for k, v in obj.items()
                            if k not in ("/P", "/Parent", "/Kids")))
    if isinstance(obj, list):
        return tuple(_canon(v, depth + 1) for v in obj)
    if isinstance(obj, (FloatObject, NumberObject)):
        return round(float(obj), 3)
    return str(obj)


def _annotations_changed(blank_reader, out_reader, expected: Mapping[str, str]) -> list[str]:
    from taxfill_core.filler import F_HIDDEN, is_viewer_guard, visible_box  # noqa: PLC0415
    from taxfill_core.packbuild import _qualified_name  # noqa: PLC0415

    failures: list[str] = []
    for index, (bp, op) in enumerate(zip(blank_reader.pages, out_reader.pages), 1):
        for box, read in (("MediaBox", lambda p: _canon(list(p.mediabox))), ("CropBox", lambda p: _canon(list(
                p.cropbox))), ("Rotate", lambda p: p.rotation % 360)):  # the effective boxes (an absent CropBox is
            if read(bp) != read(op):  # the MediaBox; pypdf writes it out when it merges the stamp)
                failures.append(f"page {index}: its {box} changed — fill again from the blank")
        before = [r.get_object() for r in bp.get("/Annots") or []]
        after = [r.get_object() for r in op.get("/Annots") or []]
        if len(before) != len(after):
            failures.append(f"page {index}: annotations were added or removed ({len(before)} on the blank, "
                            f"{len(after)} on the draft)")
            continue
        page_box = visible_box(bp)
        for a, b in zip(before, after):
            name = _qualified_name(a) if a.get("/Subtype") == "/Widget" else ""
            label = f"field {name!r}" if name else f"a {str(a.get('/Subtype', '/?'))[1:]} annotation"
            if (str(a.get("/Subtype")), name, _canon(a.get("/Rect"))) != (
                    str(b.get("/Subtype")), _qualified_name(b) if b.get("/Subtype") == "/Widget" else "",
                    _canon(b.get("/Rect"))):
                failures.append(f"page {index}: {label} was replaced, moved or renamed")
                continue
            if name and name in expected:
                continue  # its value, appearance and flags are the fill's (round_trip and flags check them)
            skip = set()
            if name and is_viewer_guard(a, page_box) and int(b.get("/F", 0)) == F_HIDDEN:
                skip.add("/F")  # P-027: the fill hides a viewer guard
            if _canon({k: v for k, v in a.items() if k not in skip}) != _canon(
                    {k: v for k, v in b.items() if k not in skip}):
                failures.append(f"page {index}: {label} changed though nothing was written to it")
    return failures


def _stamp_objects(page, text: str) -> set[int]:
    """The top-level object indexes of a pdfium page that draw ``text``."""
    import pypdfium2.raw as pdfium_c  # noqa: PLC0415

    from taxfill_core.stamp import _address, _object_indexes  # noqa: PLC0415

    textpage = page.get_textpage()
    try:
        searcher = textpage.search(text, match_case=True)
        handles: set[int] = set()
        while (hit := searcher.get_next()) is not None:
            start, count = hit
            handles |= {_address(pdfium_c.FPDFText_GetTextObject(textpage.raw, i)) for i in range(start, start + count)}
    finally:
        textpage.close()
    handles.discard(0)
    return _object_indexes(page, handles)


def _page_text(page) -> str:
    textpage = page.get_textpage()
    try:
        return textpage.get_text_range()
    finally:
        textpage.close()


def _content_changed(blank: Path, data: bytes) -> list[str]:
    """Per page: the draft's page objects, render and text layer equal the blank's once the stamp is set aside."""
    import pypdfium2 as pdfium  # noqa: PLC0415
    import pypdfium2.raw as pdfium_c  # noqa: PLC0415

    from taxfill_core.filler import UNMAPPED_STAMP  # noqa: PLC0415
    from taxfill_core.stamp import _remove_objects  # noqa: PLC0415

    failures: list[str] = []
    bdoc, odoc = pdfium.PdfDocument(str(blank)), pdfium.PdfDocument(io.BytesIO(data))
    try:
        if len(bdoc) != len(odoc):
            return [f"the draft has {len(odoc)} page(s), the blank {len(bdoc)}: pages were added or removed — fill "
                    f"again from the blank"]
        for index in range(len(bdoc)):
            bpage, opage = bdoc[index], odoc[index]
            stamp = _stamp_objects(opage, UNMAPPED_STAMP)
            _remove_objects(opage, drop=stamp)
            what = f"page {index + 1}: the page's printed content differs from the blank's outside the stamp"
            counts = [pdfium_c.FPDFPage_CountObjects(p.raw) for p in (bpage, opage)]
            if counts[0] != counts[1]:
                failures.append(f"{what} ({counts[1]} drawn objects besides the stamp, the blank {counts[0]}) — "
                                f"fill again from the blank")
                continue
            renders = [bytes(p.render(scale=_RENDER_SCALE, grayscale=True, draw_annots=False,
                                      may_draw_forms=False).buffer) for p in (bpage, opage)]
            if renders[0] != renders[1]:
                failures.append(f"{what} (its render) — fill again from the blank")
                continue
            if _page_text(bpage) != _page_text(opage):
                failures.append(f"{what} (its text layer) — fill again from the blank")
    finally:
        odoc.close()
        bdoc.close()
    return failures


def _replay(blank: Path, fields: Mapping[str, _Field], expected: Mapping[str, str]):
    """The draft fill_form writes from ``blank`` and ``expected`` (unmapped._build_draft, the fill's own code), read
    back as a PdfReader. Only names that are fields of the blank are written (any other fails anchors)."""
    from pypdf import PdfReader  # noqa: PLC0415

    buttons = {n: (n, v) for n, v in expected.items() if n in fields and fields[n].kind in ("checkbox", "radio")}
    text = {n: v for n, v in expected.items() if n in fields and n not in buttons}
    writer, _, _ = _build_draft(blank, text, buttons, {n: v for n, v in expected.items() if n in fields},
                                what="the blank")
    buf = io.BytesIO()
    writer.write(buf)
    return PdfReader(io.BytesIO(buf.getvalue()))


_STREAM_KEYS = frozenset({"/Length", "/Filter", "/DecodeParms"})  # how a stream is stored, not what it holds


def _labels(reader) -> dict[tuple[int, int], str]:
    """Readable names for a draft's objects: its pages, and its widgets and fields by qualified name."""
    from taxfill_core.packbuild import _qualified_name  # noqa: PLC0415

    labels: dict[tuple[int, int], str] = {}
    for index, page in enumerate(reader.pages, 1):
        if page.indirect_reference is not None:
            labels[(page.indirect_reference.idnum, page.indirect_reference.generation)] = f"page {index}"
        for ref in page.get("/Annots") or []:
            annot = ref.get_object()
            node, name = annot, _qualified_name(annot) if annot.get("/Subtype") == "/Widget" else ""
            if name and hasattr(ref, "idnum"):
                labels[(ref.idnum, ref.generation)] = f"field {name!r} (a widget on page {index})"
            while name and node.get("/Parent") is not None:  # the field dicts above it, by their own names
                parent_ref = node["/Parent"]
                node = parent_ref.get_object()
                name = _qualified_name(node)
                if name and hasattr(parent_ref, "idnum"):
                    labels.setdefault((parent_ref.idnum, parent_ref.generation), f"field {name!r}")
    return labels


def _article(kind: str) -> str:
    """"a" or "an" before a kind name ("an array", "a stream")."""
    return "an" if kind[:1] in "aeiou" else "a"


def _graph_diff(draft, replay, limit: int = 10) -> list[str]:
    """Where ``draft``'s document differs from ``replay``'s: both walked in step from the catalog (every page, page
    key, annotation, appearance stream, field dict, the /AcroForm, document actions and scripts), indirect objects
    paired as they are met. Streams compare by their decoded bytes, numbers to 1e-4; the trailer (/Info, /ID) is not
    compared (the record section reads /Info). Phase K JK17 fix (2026-10-25)."""
    from collections import deque  # noqa: PLC0415

    from pypdf.generic import (  # noqa: PLC0415
        BooleanObject,
        DictionaryObject,
        FloatObject,
        IndirectObject,
        NameObject,
        NullObject,
        NumberObject,
        StreamObject,
    )

    diffs: list[str] = []
    labels = _labels(draft)
    d2r: dict[tuple[int, int], tuple[int, int]] = {}
    r2d: dict[tuple[int, int], tuple[int, int]] = {}
    queue: deque = deque()

    def note(where: str, what: str) -> None:
        diffs.append(f"{where}: {what}")

    def pair(a, b, where: str) -> None:
        ka, kb = (a.idnum, a.generation), (b.idnum, b.generation)
        if ka in d2r or kb in r2d:
            if d2r.get(ka) != kb or r2d.get(kb) != ka:
                note(where, "refers to another object than the fill's")
            return
        d2r[ka], r2d[kb] = kb, ka
        queue.append((a.get_object(), b.get_object(), labels.get(ka, where)))

    def kind(v) -> str:
        if isinstance(v, BooleanObject):
            return "bool"
        if isinstance(v, (FloatObject, NumberObject)):
            return "number"
        if isinstance(v, NameObject):
            return "name"
        if isinstance(v, NullObject) or v is None:
            return "null"
        if isinstance(v, StreamObject):
            return "stream"
        if isinstance(v, dict):
            return "dict"
        if isinstance(v, list):
            return "array"
        return "string"

    def stream_bytes(v) -> bytes:
        try:
            return v.get_data()
        except Exception:  # noqa: BLE001 — an undecodable stream compares by its stored bytes
            return v._data or b""

    def same(a, b, where: str) -> None:
        if len(diffs) > limit:
            return
        if isinstance(a, IndirectObject) and isinstance(b, IndirectObject):
            pair(a, b, where)
            return
        a = a.get_object() if isinstance(a, IndirectObject) else a
        b = b.get_object() if isinstance(b, IndirectObject) else b
        ka, kb = kind(a), kind(b)
        if ka != kb:
            note(where, f"{_article(ka)} {ka} where the fill writes {_article(kb)} {kb}")
        elif ka == "stream":
            if stream_bytes(a) != stream_bytes(b):
                note(where, "its stream content differs from the fill's")
            same(DictionaryObject({k: v for k, v in a.items() if k not in _STREAM_KEYS}),
                 DictionaryObject({k: v for k, v in b.items() if k not in _STREAM_KEYS}), where)
        elif ka == "dict":
            extra, missing = sorted(set(a) - set(b)), sorted(set(b) - set(a))
            if extra:
                note(where, f"carries {', '.join(extra[:5])}, which the fill does not write")
            if missing:
                note(where, f"lacks {', '.join(missing[:5])}, which the fill writes")
            for k in sorted(set(a) & set(b)):  # raw_get: a reference stays a reference (pairs, and ends cycles)
                same(a.raw_get(k), b.raw_get(k), f"{where} {k}")
        elif ka == "array":
            if len(a) != len(b):
                note(where, f"holds {len(a)} entries, the fill's {len(b)}")
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    same(x, y, f"{where}[{i}]")
        elif ka == "number":
            if abs(float(a) - float(b)) > 1e-4:
                note(where, f"is {float(a):g}, the fill's {float(b):g}")
        elif ka != "null" and str(a) != str(b):
            note(where, "differs from the fill's")

    same(draft.trailer["/Root"], replay.trailer["/Root"], "the document catalog")
    while queue and len(diffs) <= limit:
        a, b, where = queue.popleft()
        same(a, b, where)
    return diffs


def _as_filled(blank: Path, data: bytes, fields: Mapping[str, _Field], expected: Mapping[str, str]) -> list[str]:
    """The whole document equals the one fill_form writes from the blank and ``expected`` (Phase K JK17 fix,
    2026-10-25): the checks above compare values, annotations other than the written widgets, and page content; this
    one also reaches each written widget's appearance and keys, the stamp's own text, size and place, every page key,
    the catalog and its /AcroForm (/NeedAppearances, /XFA), and document actions and scripts."""
    from pypdf import PdfReader  # noqa: PLC0415

    try:
        replay = _replay(blank, fields, expected)
    except Exception:  # noqa: BLE001 — a value the fill could not have written, or a blank it cannot stamp
        return ["the draft cannot be rebuilt from the blank and expected (the fill would not write these values "
                "this way) — fill again with fill_form and verify the new output"]
    diffs = _graph_diff(PdfReader(io.BytesIO(data)), replay)
    return [f"{d} — the file was changed after the fill (or by another version of taxfill); fill again with fill_form "
            f"and verify the new output" for d in diffs[:10]] + (
        ["and more such differences (the comparison stops after the first ten)"] if len(diffs) > 10 else [])


def _unchanged(blank: Path, out: Path, data: bytes, expected: Mapping[str, str], before, after,
               fields: Mapping[str, _Field]) -> dict:
    from pypdf import PdfReader  # noqa: PLC0415

    from taxfill_core.verify import read_pdf_fields, regression_diff  # noqa: PLC0415

    failures: list[str] = []
    dumps = []
    for pdf in (out, blank):
        try:
            dumps.append(read_pdf_fields(pdf))
        except ValueError:  # no AcroForm field at all
            dumps.append({})
    diff = regression_diff(*dumps)
    changed = {*diff.added, *diff.removed, *diff.changed}
    changed |= {n for n in after.keys() | before.keys() if after.get(n) != before.get(n)}
    stray = sorted(n for n in changed if n not in expected)
    if stray:
        failures.append(f"{len(stray)} field(s) not written by the fill changed ({', '.join(map(repr, stray[:10]))}"
                        + (", ..." if len(stray) > 10 else "") + ") — the file was edited after the fill; fill again "
                        "and verify the new output")
    failures += _annotations_changed(PdfReader(str(blank)), PdfReader(io.BytesIO(data)), expected)
    failures += _content_changed(blank, data)
    failures += _as_filled(blank, data, fields, expected)
    return _section(len(before) + len(PdfReader(str(blank)).pages), failures)


# ── stamp ────────────────────────────────────────────────────────────────────


def _stamp_section(data: bytes) -> dict:
    from pypdf import PdfReader  # noqa: PLC0415

    from taxfill_core.filler import UNMAPPED_STAMP  # noqa: PLC0415
    from taxfill_core.stamp import _obstacles, stamp_check  # noqa: PLC0415

    check = stamp_check(data, UNMAPPED_STAMP)
    failures = [f"page {p['page']}: {p.get('problem', 'the stamp does not print')} (KG5) — fill again with "
                f"fill_form; a draft without the stamp on every page is not verified" for p in check["pages"]
                if not p["ok"]]
    pages = PdfReader(io.BytesIO(data)).pages
    for p in check["pages"]:
        if not p.get("box"):
            continue  # stripped: failed above
        x0, y0, x1, y1 = p["box"]
        if any(r[0] < x1 and x0 < r[2] and r[1] < y1 and y0 < r[3] for r in _obstacles(pages[p["page"] - 1])):
            failures.append(f"page {p['page']}: the stamp lies under an annotation that draws (KG5) — fill again "
                            f"with fill_form")
    if not check["pages"]:
        failures.append("the PDF has no page to carry the stamp")
    return _section(len(check["pages"]), failures, text=UNMAPPED_STAMP)


# ── anchors (KG11) ───────────────────────────────────────────────────────────


def _anchors(fields: Mapping[str, _Field], basis: dict, expected: Mapping[str, str], confirmed: set[str]) -> dict:
    failures: list[str] = []
    checked = 0
    if expected and not _table_passed(basis):
        failures.append("no anchor benchmark table has passed (KG6), so no value may be written into the PDF — "
                        "copy the values onto the printed form by hand")
    for name in expected:
        f = fields.get(name)
        if f is None:
            failures.append(f"field {name!r} is not a field of the blank — fill again with the qualified names "
                            f"get_form_map returns")
            continue
        checked += len(f.widgets)
        refusal = next((w.refusal for w in f.widgets if w.refusal), None)
        if refusal:
            failures.append(f"field {name!r} is never written ({refusal}, KG7) — write it on the printed form by hand")
            continue
        for number, w in enumerate(f.widgets, 1):
            tier = w.anchor.confidence
            where = f"field {name!r}, box {number} of {len(f.widgets)} (page {w.info['page']})"
            if tier == "none":
                failures.append(f"{where} is anchored 'none': no printed line or caption could be tied to it (KG11) — "
                                f"write it on the printed form by hand")
            elif tier in CONFIRM_TIERS and name not in confirmed:
                failures.append(f"{where} is anchored only {tier!r} and the draft records no user confirmation for "
                                f"its field (KG11) — confirm its boxes on the rendered sweep page, refill with it in "
                                f"confirmed_fields, and verify again")
    return _section(checked, failures)


# ── recompute and declared relations ─────────────────────────────────────────


def _disk_value(after: Mapping[str, tuple], name: str) -> str | None:
    value = (after.get(name) or (None,))[0]
    return None if value is None or not str(value).strip() else str(value)


def _recompute(after: Mapping[str, tuple], expected: Mapping[str, str], independent: Mapping) -> dict:
    from taxfill_core.verify import irs_round, parse_money  # noqa: PLC0415

    failures: list[str] = []
    checks: list[dict] = []
    for name, number in independent.items():
        entry = {"field": name, "status": "FAIL", "value_label": VALUE_LABEL}
        try:
            recomputed = irs_round(number)
        except (ValueError, TypeError):
            entry["detail"] = f"field {name!r}: the independent value is not a finite number — pass a plain number"
            failures.append(entry["detail"])
            checks.append(entry)
            continue
        entry["recomputed"] = recomputed
        raw = _disk_value(after, name) if name in expected else None
        parsed = parse_money(raw)
        if name not in expected:
            entry["detail"] = (f"field {name!r} was not written by this fill — drop it from independent, or fill it "
                               f"with the calc result and verify again")
        elif parsed is None:
            entry["detail"] = f"field {name!r} does not hold a number on disk — refill it with the calc result"
        elif irs_round(parsed) != recomputed:
            entry["filled"] = irs_round(parsed)
            entry["detail"] = (f"field {name!r}: the draft holds {entry['filled']}, the independent value is "
                               f"{recomputed} — rerun calc, refill the field and verify again")
        else:
            entry.update(status="PASS", filled=recomputed,
                         detail=f"field {name!r}: the draft matches the independent value; its label is unchanged")
        if entry["status"] == "FAIL":
            failures.append(entry["detail"])
        checks.append(entry)
    return _section(len(checks), failures, label=RECOMPUTE_LABEL, checks=checks)


def _relation_error(relation: str, reason: str) -> str:
    return (f"could not read declared relation {relation!r}: {reason} — write '<expr> == <expr>' with + - * / "
            f"parentheses, max(), min(), and a field name in braces when it is not a plain identifier "
            f"({{topmostSubform[0].f1_01[0]}})")


def _declared(after: Mapping[str, tuple], field_names: set[str], relations: Sequence[str]) -> dict:
    from taxfill_core.verify import _BadOperand, _eval_relation_sides, irs_round, parse_money  # noqa: PLC0415

    failures: list[str] = []
    checks: list[dict] = []
    for relation in relations:
        entry = {"relation": relation, "label": DECLARED_RELATION_LABEL, "status": "FAIL"}
        refs: dict[str, str] = {}

        def alias(match, refs=refs):
            key = _ALIAS.format(len(refs))
            refs[key] = match.group(1).strip()
            return key

        equation = _REF_RE.sub(alias, relation)
        names = {*field_names, *refs}
        unknown: list[str] = []
        blank: list[str] = []
        not_numbers: list[str] = []

        def lookup(token: str, refs=refs, unknown=unknown, blank=blank, not_numbers=not_numbers):
            name = refs.get(token, token)
            if name not in field_names:
                unknown.append(name)
                return None
            raw = _disk_value(after, name)
            if raw is None:
                blank.append(name)
                return None
            parsed = parse_money(raw)
            if parsed is None:
                not_numbers.append(name)
                return 0
            return parsed

        class _Values(dict):
            def get(self, key, default=None):  # noqa: D401 — resolved lazily so blank fields are reported by name
                return lookup(key)

        try:
            lhs, rhs, _ = _eval_relation_sides(equation, _Values(), frozenset(names))
        except (ZeroDivisionError, InvalidOperation, _BadOperand):
            entry["detail"] = (f"declared relation {relation!r} cannot be evaluated: it divides by zero (a blank or "
                               f"zero field) — fix the relation or the field, then verify again")
            failures.append(entry["detail"])
            checks.append(entry)
            continue
        except (ValueError, RecursionError) as exc:
            reason = "too deep"
            if isinstance(exc, ValueError):  # verify._grammar_error's text, less its prefix (which quotes the
                # relation, whose own ': ' a split would cut at) and its pack.yaml advice. Phase K JK17 fix (2026-10-25)
                message, prefix = str(exc), f"could not parse relation '{equation}': "
                reason = message.removeprefix(prefix).split(" — ", 1)[0]
            entry["detail"] = _relation_error(relation, reason)
            failures.append(entry["detail"])
            checks.append(entry)
            continue
        entry["blank_as_zero"] = list(dict.fromkeys(blank))
        if unknown:
            entry["detail"] = (f"declared relation {relation!r} names {', '.join(map(repr, dict.fromkeys(unknown)))}, "
                               f"which is not a field of this form — use the names get_form_map returns")
        elif not_numbers:
            entry["detail"] = (f"declared relation {relation!r}: {', '.join(map(repr, dict.fromkeys(not_numbers)))} "
                               f"does not hold a number on disk")
        else:
            try:
                left, right = irs_round(lhs), irs_round(rhs)
            except ValueError:
                left = right = None
            entry.update(lhs=left, rhs=right)
            if left is None:
                entry["detail"] = f"declared relation {relation!r} evaluates to an amount too large to round"
            elif left == right:
                entry.update(status="PASS", detail=f"{left} == {right} (whole dollars); {DECLARED_RELATION_LABEL}")
            else:
                entry["detail"] = (f"declared relation {relation!r} fails: left side {left}, right side {right} "
                                   f"({DECLARED_RELATION_LABEL}) — fix the field that is wrong, refill and verify "
                                   f"again, or drop the relation if it is not the form's")
        if entry["status"] == "FAIL":
            failures.append(entry["detail"])
        checks.append(entry)
    return _section(len(checks), failures, label=DECLARED_RELATION_LABEL, checks=checks)


# ── verify ───────────────────────────────────────────────────────────────────


def verify_unmapped(
    out_pdf: str | Path,
    *,
    blank_sha256: str,
    source_url: str,
    tax_year: int,
    jurisdiction: str,
    expected: Mapping[str, str],
    independent: Mapping[str, float | int | Decimal] | None = None,
    declared_relations: Sequence[str] | None = None,
    confirmed_fields: Sequence[str] | None = None,
    cache_dir: str | Path | None = None,
    workspace_root: str | Path | None = None,
    anchor_table: str | Path | None = None,
) -> dict:
    """Verify a draft fill_unmapped wrote (ADR-0002 verify_form, ``form="unmapped"``); return the UNMAPPED verdict.

    The blank is loaded by ``blank_sha256`` + ``source_url`` (+ ``jurisdiction``, ``tax_year``) through
    ``fetch.load_unmapped_blank``, which re-runs every fetch check; its anchors are re-derived (KG11). ``expected`` is
    the fill's ``written`` map; ``independent`` and the relations in ``declared_relations`` are keyed by field name.
    ``confirmed_fields`` can only narrow the confirmations the draft records, never add one. The grade is a constant
    and no parameter changes it. Response: module doc. Raises :class:`UnmappedVerifyRefused` (no PDF to read, or
    malformed input) and ``fetch.UnmappedBlankRefused`` (a fetch check).
    """
    from taxfill_core.fetch import load_unmapped_blank  # noqa: PLC0415
    from taxfill_core.verify import clipping_scan, widget_flag_problems  # noqa: PLC0415

    independent, relations, confirmed_narrow = _check_inputs(expected, independent, declared_relations,
                                                             confirmed_fields)
    out = user_path(out_pdf)
    try:
        data = out.read_bytes()
    except OSError:
        raise UnmappedVerifyRefused("no draft PDF at the path given — pass the out_path fill_form returned; nothing "
                                    "was verified") from None
    try:
        from pypdf import PdfReader  # noqa: PLC0415

        reader = PdfReader(io.BytesIO(data))
        after = _field_states(reader)
    except Exception:  # noqa: BLE001 — not a PDF pypdf can read
        raise UnmappedVerifyRefused("the file at the path given is not a PDF this verify can read — pass the "
                                    "out_path fill_form returned; nothing was verified") from None
    output_sha256 = hashlib.sha256(data).hexdigest()
    blank = load_unmapped_blank(blank_sha256, tax_year=tax_year, source_url=source_url, jurisdiction=jurisdiction,
                                cache_dir=cache_dir, workspace_root=workspace_root)
    if blank.kind == "flat":
        raise UnmappedVerifyRefused("the blank has no fillable field (a flat form), so fill_form wrote no PDF for it "
                                    "— its worksheet is the output: copy it onto the printed form by hand")
    blank_path = Path(blank.path)
    fields_list, basis = _read_fields(blank_path, anchor_table)
    fields = {f.name: f for f in fields_list}
    present, record = _info_record(data)
    recorded = set((record or {}).get("confirmed") or {}) if isinstance((record or {}).get("confirmed"), Mapping) \
        else set()
    confirmed = recorded if confirmed_narrow is None else recorded & confirmed_narrow
    buttons = {n for n, f in fields.items() if f.kind in ("checkbox", "radio")}
    before = _field_states(PdfReader(str(blank_path)))

    clip = [c for c in clipping_scan(out) if c.name in expected]
    problems, flag_checked = widget_flag_problems(out, set(expected))
    sections = {
        "record": _record_section(present, record, blank_sha256=blank.sha256, source_url=blank.source_url,
                                  tax_year=blank.tax_year, jurisdiction=blank.jurisdiction or jurisdiction,
                                  expected=expected),
        "round_trip": _round_trip(after, expected, buttons),
        "unchanged": _unchanged(blank_path, out, data, expected, before, after, fields),
        "clipping": _section(len(clip), [c.detail for c in clip if c.status == "FAIL"]),
        "flags": _section(flag_checked, [f"{p} (P-027) — fill again with fill_form" for p in problems]),
        "stamp": _stamp_section(data),
        "anchors": _anchors(fields, basis, expected, confirmed),
        "recompute": _recompute(after, expected, independent),
        "declared_relations": _declared(after, set(after), relations),
    }
    if hashlib.sha256(out.read_bytes()).hexdigest() != output_sha256:
        raise UnmappedVerifyRefused("the draft changed on disk while it was being verified — verify it again once "
                                    "nothing is writing to it")
    ok = all(s["failed"] == 0 for s in sections.values())
    sources = (record or {}).get("sources") if isinstance((record or {}).get("sources"), Mapping) else {}
    unverified = []
    for name, value in expected.items():
        f = fields.get(name)
        source = sources.get(name) if sources.get(name) in PROVENANCE_SOURCES else None
        place = ({"page": f.first.info["page"], "printed_line": f.first.anchor.printed_line} if f is not None
                 else {"page": None, "printed_line": None})
        unverified.append({"field": name, **place, "value": value, "value_label": value_label(source)})
    response = {
        "grade": GRADE,
        "verdict": VERDICT,
        "ok": ok,
        "output_sha256": output_sha256,
        "sections": sections,
        "unverified_values": unverified,
        "hand_write": [_hand_write(f, f.refusal) for f in fields_list if f.refusal is not None],
        "limits": list(UNMAPPED_VERDICT_LIMITS),
        "next_step": NEXT_STEP_OK if ok else NEXT_STEP_FAILED,
    }
    if ok:
        response["verified_at"] = {"output_sha256": output_sha256,
                                   "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return response
