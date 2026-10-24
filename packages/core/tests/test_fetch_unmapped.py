"""The pack-less (unmapped) fetch — Phase K JK14 (2026-10-24).

A form with no pack has no reviewed digest. fetch_unmapped_blank therefore downloads only over https from an
official host (every redirect hop checked before it is requested), always downloads (never the pack cache: with
sha256=None fetch_blank returns any file cached under the URL, and several state URLs are rotating "current"
slots), stores the bytes in its own namespace keyed by sha256 with a (url, sha256, fetched_at) record, and checks
the form's first page: the tallest year printed in the title block must be printed at title size (not a body
date) and be the requested tax year, a revision date is refused for every tax year, and expected_title must be
printed there. A PINNED_ONLY host and a host that answers 401/403 are refused with a pointer
to local_blank (no Wayback mirror without a digest). XFA-only, /NeedsRendering, scanned and locked blanks are
refused. load_unmapped_blank re-runs the checks on a stored copy, so a wrong-year blank in the namespace is refused.

Offline: synthetic PDFs drawn with reportlab and a monkeypatched opener. The network-marked tests read real 2025
pack blanks from the shared cache (TAXFILL_BLANKS_CACHE).
"""
from __future__ import annotations

import email.message
import hashlib
import io
import json
import urllib.error
import urllib.request
import urllib.response
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, DictionaryObject, NameObject
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from taxfill_core import fetch as fetch_mod
from taxfill_core.fetch import (
    PINNED_ONLY_BLANK_HOSTS,
    OfflineFetchError,
    UnmappedBlankRefused,
    _cache_path,
    _OfficialRedirectHandler,
    fetch_pack_blank,
    fetch_unmapped_blank,
    inspect_unmapped_blank,
    load_unmapped_blank,
)

REPO = Path(__file__).resolve().parents[3]
URL = "https://www.tax.example.gov/forms/2025/demo-1.pdf"
NM_HOST = next(iter(PINNED_ONLY_BLANK_HOSTS))
NM_URL = f"https://{NM_HOST}/prod/forms/demo.pdf"


def _form_pdf(
    *,
    year: str | None = "2025",
    title: str = "Form DEMO-1",
    small: str = "Due April 15, 2026",
    rival: str | None = None,
    widget: bool = True,
    text: bool = True,
    invisible_text: bool = False,
    cover_year: str | None = None,
    year_size: int = 28,
    art_year: str | None = None,
    period: str | None = None,
    before_year: str | None = None,
) -> bytes:
    """A one-form demo blank: title + big year in the top third, a small due date, one text widget.

    ``cover_year`` prepends an instructions page (no widget) printing that year large, as a packet does.
    ``art_year`` draws a year as an image (no text layer), as a logo or vector-art title year is; ``period`` adds a
    tax-period line at the title line's body size; ``before_year`` prints small text right before the year.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    if cover_year:
        c.setFont("Helvetica-Bold", 30)
        c.drawString(72, 720, f"{cover_year} Instructions")
        c.showPage()
    if text:
        c.setFont("Helvetica", 12)
        c.drawString(72, 750, f"{title}  Demo Individual Income Tax Return")
        if period:
            c.drawString(72, 735, period)
        if before_year:
            c.setFont("Helvetica", 8)
            c.drawString(340, 722, before_year)
        if year:
            c.setFont("Helvetica-Bold", year_size)
            c.drawString(420, 720, year)
        if rival:
            c.setFont("Helvetica-Bold", 28)
            c.drawString(300, 720, rival)
        c.setFont("Helvetica", 8)
        c.drawString(72, 700, small)
        c.drawString(72, 420, "1  Wages")
    elif invisible_text:
        t = c.beginText(72, 720)
        t.setTextRenderMode(3)
        t.setFont("Helvetica", 28)
        t.textLine(f"{title} {year}")
        c.drawText(t)
    if art_year:
        from PIL import Image, ImageDraw

        art = Image.new("L", (120, 40), 255)
        ImageDraw.Draw(art).text((4, 4), art_year, fill=0, font_size=30)
        c.drawInlineImage(art, 480, 715, width=90, height=30)
    c.rect(72, 600, 400, 60)  # a drawn path, as a scan or a vector page carries
    if widget:
        c.acroForm.textfield(name="line1", x=220, y=410, width=144, height=18, fieldFlags="")
    c.showPage()
    c.save()
    return buf.getvalue()


def _edit_catalog(data: bytes, *, xfa_only: bool = False, needs_rendering: bool = False,
                  password: str | None = None) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(data))
    if xfa_only:
        acroform = DictionaryObject()
        acroform[NameObject("/Fields")] = ArrayObject()
        acroform[NameObject("/XFA")] = ArrayObject()
        writer._root_object[NameObject("/AcroForm")] = acroform
    if needs_rendering:
        writer._root_object[NameObject("/NeedsRendering")] = BooleanObject(True)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner-demo")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class _Opener:
    """Stands in for the per-hop-checking opener: serves scripted answers per URL and records every request."""

    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.seen: list[str] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.seen.append(url)
        answer = self.answers[url].pop(0) if len(self.answers.get(url, [])) > 1 else self.answers[url][0]
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(answer)


@pytest.fixture
def opener(monkeypatch):
    def install(answers: dict[str, list]) -> _Opener:
        fake = _Opener(answers)
        monkeypatch.setattr(fetch_mod, "_unmapped_open", fake)
        return fake
    monkeypatch.setattr(fetch_mod, "_sleep", lambda s: None)
    # a stray real urlopen would mean the pack path (or an unchecked opener) ran
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("plain urlopen used"))
    return install


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


def _refused(reason: str, fn, *args, **kwargs) -> UnmappedBlankRefused:
    with pytest.raises(UnmappedBlankRefused) as info:
        fn(*args, **kwargs)
    assert info.value.reason == reason, str(info.value)
    return info.value


# ── a good fetch: recorded, its own namespace, never the pack cache ───────────────────────────────────────────


def test_fetch_records_url_sha_and_time_in_its_own_namespace(opener, cache):
    data = _form_pdf()
    opener({URL: [data]})
    blank = fetch_unmapped_blank(URL, tax_year=2025, expected_title="DEMO-1", cache_dir=cache)
    digest = hashlib.sha256(data).hexdigest()
    assert blank.sha256 == digest and blank.pinned is False and blank.origin == "download"
    assert blank.path == cache / "unmapped" / f"{digest}.pdf" and blank.path.read_bytes() == data
    assert (blank.first_page.page, blank.first_page.printed_year, blank.first_page.title_found) == (1, 2025, True)
    assert blank.kind == "acroform" and blank.page_count == 1
    record = json.loads((cache / "unmapped" / f"{digest}.json").read_text())
    (entry,) = record["fetches"]
    assert (entry["source_url"], entry["sha256"], entry["fetched_at"]) == (URL, digest, blank.fetched_at)
    assert not _cache_path(cache, URL).exists()  # the pack cache entry for the URL is never written
    assert blank.to_dict()["path"] == str(blank.path)


def test_fetch_always_downloads_and_rechecks_a_rotating_url(opener, cache):
    # A "current" slot served the 2025 form, then rolls over to 2026: the cached 2025 copy is not served instead.
    fake = opener({URL: [_form_pdf(year="2025"), _form_pdf(year="2026", small="Due April 15, 2027")]})
    fetch_unmapped_blank(URL, tax_year=2025, cache_dir=cache)
    _refused("wrong_year", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache)
    assert fake.seen == [URL, URL]


def test_fetch_never_reads_the_pack_cache(opener, cache):
    # fetch_blank(url) with sha256=None would return this file without a request; the unmapped fetch downloads.
    pack_entry = _cache_path(cache, URL)
    pack_entry.parent.mkdir(parents=True)
    cached = _form_pdf(year="2025")
    pack_entry.write_bytes(cached)
    fake = opener({URL: [_form_pdf(year="2024", small="Due April 15, 2025")]})
    _refused("wrong_year", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache)
    assert fake.seen == [URL]
    assert pack_entry.read_bytes() == cached  # untouched


# ── the year and title on the form's first page ──────────────────────────────────────────────────────────────


def test_a_wrong_year_blank_is_refused_and_not_stored(opener, cache):
    opener({URL: [_form_pdf(year="2024", small="Due April 15, 2025")]})
    err = _refused("wrong_year", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache)
    assert "is the 2024 form, not 2025" in str(err) and "agency's forms page" in str(err)
    assert not (cache / "unmapped").exists()


def test_a_wrong_year_blank_already_in_the_namespace_is_refused(opener, cache):
    data = _form_pdf(year="2024", small="Due April 15, 2025")
    opener({URL: [data]})
    stored = fetch_unmapped_blank(URL, tax_year=2024, cache_dir=cache)  # right for 2024: stored
    assert load_unmapped_blank(stored.sha256, tax_year=2024, cache_dir=cache).first_page.printed_year == 2024
    err = _refused("wrong_year", load_unmapped_blank, stored.sha256, tax_year=2025, cache_dir=cache)
    assert "is the 2024 form, not 2025" in str(err)


def test_a_stored_copy_is_rehashed_and_tied_to_its_url(opener, cache):
    opener({URL: [_form_pdf()]})
    stored = fetch_unmapped_blank(URL, tax_year=2025, cache_dir=cache)
    _refused("record_mismatch", load_unmapped_blank, stored.sha256, tax_year=2025,
             source_url="https://www.tax.example.gov/forms/other.pdf", cache_dir=cache)
    stored.path.write_bytes(_form_pdf(year="2024"))
    _refused("stored_copy_changed", load_unmapped_blank, stored.sha256, tax_year=2025, cache_dir=cache)
    _refused("not_stored", load_unmapped_blank, "0" * 64, tax_year=2025, cache_dir=cache)


def test_small_dates_do_not_count_but_a_rival_year_at_title_size_does():
    # the due date "April 15, 2026" prints small: not a rival
    assert inspect_unmapped_blank(_form_pdf(), tax_year=2025)[2].printed_year == 2025
    _refused("ambiguous_printed_year", inspect_unmapped_blank, _form_pdf(rival="2026"), tax_year=2025)


def test_revision_dated_and_yearless_blanks_are_refused():
    revised = _form_pdf(year=None, title="Form DEMO-9 (Rev. December 2024)")
    err = _refused("revision_dated", inspect_unmapped_blank, revised, tax_year=2025)
    assert "'Rev. December 2024'" in str(err) and err.revision_year == 2024
    _refused("no_printed_year", inspect_unmapped_blank, _form_pdf(year=None, small="Due on the 15th"), tax_year=2025)


def test_a_revision_date_is_refused_the_same_for_every_tax_year():
    # Phase K JK14 (2026-10-24): before, "Rev. December 2025" passed for tax year 2025 (the revision year) and was
    # refused as revision_dated for every other year. A revision date is now classified before any year comparison.
    revised = _form_pdf(year=None, title="Form DEMO-9 (Rev. December 2025)")
    for tax_year in (2024, 2025, 2026):
        err = _refused("revision_dated", inspect_unmapped_blank, revised, tax_year=tax_year)
        assert err.revision_year == 2025
        assert "continuous-use revision" in str(err) and "no override" in str(err)
        assert "which tax years the 2025 revision serves" in str(err)


def test_a_print_code_before_the_title_year_is_not_a_revision_date():
    # VA 760 2025 prints "Rev. 04/26 WEB 2025": a revision code, then the title year. "Rev." governs 04/26 only.
    data = _form_pdf(before_year="Rev. 04/26 WEB")
    assert inspect_unmapped_blank(data, tax_year=2025)[2].printed_year == 2025


def test_the_year_must_be_printed_at_title_size():
    # Phase K JK14 (2026-10-24): with the title year drawn as an image, the tallest year in the text layer is a body
    # date. Before, the due date's 2026 passed this prior-year (2025) blank for tax year 2026.
    art = _form_pdf(year=None, art_year="2025")  # small: "Due April 15, 2026"
    err = _refused("no_printed_year", inspect_unmapped_blank, art, tax_year=2026)
    assert "no year at title size" in str(err) and "(2026)" in str(err)
    _refused("no_printed_year", inspect_unmapped_blank, art, tax_year=2025)
    # The NY IT-201/IT-203 shape: vector-art logo year, and the tax period printed at body size.
    period = _form_pdf(year=None, art_year="2025", period="For the year January 1, 2025, through December 31, 2025")
    _refused("no_printed_year", inspect_unmapped_blank, period, tax_year=2025)
    # A year at the body type's size is not a title; a modestly larger one (MO-1040's shape) is.
    _refused("no_printed_year", inspect_unmapped_blank, _form_pdf(year_size=12), tax_year=2025)
    assert inspect_unmapped_blank(_form_pdf(year_size=15), tax_year=2025)[2].printed_year == 2025


def test_the_first_page_is_the_first_page_with_a_widget():
    # a packet opening with an instructions page that prints another year large
    data = _form_pdf(cover_year="2024")
    pages, kind, first = inspect_unmapped_blank(data, tax_year=2025)
    assert (pages, first.page, first.printed_year) == (2, 2, 2025)
    # with no widget at all, page 1 is read and the blank is "flat" (nothing to fill; rule 10 refuses later)
    assert inspect_unmapped_blank(_form_pdf(widget=False), tax_year=2025)[1] == "flat"


def test_expected_title_must_be_printed_as_whole_tokens():
    data = _form_pdf(title="Form DEMO-10")
    assert inspect_unmapped_blank(data, tax_year=2025, expected_title="demo 10")[2].title_found is True
    assert inspect_unmapped_blank(data, tax_year=2025, expected_title="Form DEMO10")[2].title_found is True
    err = _refused("title_not_found", inspect_unmapped_blank, data, tax_year=2025, expected_title="DEMO-1")
    assert "render page 1" in str(err)
    _refused("title_not_found", inspect_unmapped_blank, data, tax_year=2025, expected_title="EMO-10")


# ── blanks an AcroForm filler cannot use ─────────────────────────────────────────────────────────────────────


def test_xfa_only_and_needs_rendering_blanks_are_refused():
    err = _refused("xfa_only", inspect_unmapped_blank, _edit_catalog(_form_pdf(widget=False), xfa_only=True),
                   tax_year=2025)
    assert "Adobe Reader" in str(err) and "forms page" in str(err)
    _refused("needs_rendering", inspect_unmapped_blank, _edit_catalog(_form_pdf(), needs_rendering=True),
             tax_year=2025)


def test_a_hybrid_xfa_blank_with_widgets_is_accepted():
    writer = PdfWriter(clone_from=io.BytesIO(_form_pdf()))
    writer._root_object["/AcroForm"].get_object()[NameObject("/XFA")] = ArrayObject()
    out = io.BytesIO()
    writer.write(out)
    assert inspect_unmapped_blank(out.getvalue(), tax_year=2025)[1] == "acroform_xfa_hybrid"


def test_scanned_blanks_are_refused():
    err = _refused("scanned", inspect_unmapped_blank, _form_pdf(text=False), tax_year=2025)
    assert "no text layer" in str(err) and "by hand" in str(err)
    # only an invisible OCR layer (render mode 3) over the page: still a scan
    _refused("scanned", inspect_unmapped_blank, _form_pdf(text=False, invisible_text=True), tax_year=2025)


def test_a_password_locked_blank_is_refused_and_an_empty_password_opens():
    _refused("locked", inspect_unmapped_blank, _edit_catalog(_form_pdf(), password="demo-secret"), tax_year=2025)
    assert inspect_unmapped_blank(_edit_catalog(_form_pdf(), password=""), tax_year=2025)[2].printed_year == 2025


# ── hosts: https, official, every hop; PINNED_ONLY and 401/403 refused with a pointer ───────────────────────


def test_only_https_on_an_official_host(opener, cache):
    fake = opener({})
    _refused("not_https", fetch_unmapped_blank, URL.replace("https:", "http:"), tax_year=2025, cache_dir=cache)
    _refused("not_https", fetch_unmapped_blank, "file:///tmp/demo.pdf", tax_year=2025, cache_dir=cache)
    _refused("not_official_host", fetch_unmapped_blank, "https://forms.example.com/demo.pdf", tax_year=2025,
             cache_dir=cache)
    _refused("not_official_host", fetch_unmapped_blank, "https://demo.us/demo.pdf", tax_year=2025, cache_dir=cache)
    assert fake.seen == []


def test_a_pinned_only_host_is_refused_with_a_pointer(opener, cache):
    fake = opener({NM_URL: [_form_pdf()]})
    err = _refused("pinned_only_host", fetch_unmapped_blank, NM_URL, tax_year=2025, cache_dir=cache)
    assert "local_blank" in str(err) and "in a browser" in str(err) and "New Mexico" in str(err)
    assert fake.seen == []  # never requested


def test_a_403_host_is_refused_with_a_pointer_and_no_mirror(opener, cache):
    forbidden = urllib.error.HTTPError(URL, 403, "Forbidden", None, io.BytesIO())
    fake = opener({URL: [forbidden]})
    err = _refused("host_refused", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache)
    assert "HTTP 403" in str(err) and "local_blank" in str(err) and "no mirror" in str(err)
    assert fake.seen == [URL]  # one request; no Wayback snapshot tried
    assert not (cache / "unmapped").exists()


def test_other_http_errors_and_offline_say_what_to_do(opener, cache):
    opener({URL: [urllib.error.HTTPError(URL, 404, "Not Found", None, io.BytesIO())]})
    assert "forms page" in str(_refused("http_error", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache))
    opener({URL: [urllib.error.URLError("no route")]})
    with pytest.raises(OfflineFetchError, match="local_blank"):
        fetch_unmapped_blank(URL, tax_year=2025, cache_dir=cache)
    opener({URL: [b"<html>not a pdf</html>"]})
    _refused("not_pdf", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=cache)


def test_every_redirect_hop_is_checked_before_it_is_requested():
    handler = _OfficialRedirectHandler()
    req = urllib.request.Request(URL)
    for target in ("https://forms.example.com/demo.pdf", "http://www.tax.example.gov/demo.pdf",
                   f"https://{NM_HOST}/demo.pdf"):
        _refused("redirect_off_official", handler.redirect_request, req, None, 302, "Found", {}, target)
    follow = handler.redirect_request(req, None, 302, "Found", {}, "https://www.irs.gov/pub/irs-pdf/f1040.pdf")
    assert follow.full_url == "https://www.irs.gov/pub/irs-pdf/f1040.pdf"


def test_the_real_opener_refuses_an_off_host_redirect(monkeypatch):
    # An end-to-end hop through urllib's machinery: the redirect is answered by a stub HTTPS handler.
    class _Redirecting(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, req):
            headers = email.message.Message()
            headers["Location"] = "https://forms.example.com/x.pdf"
            resp = urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
            resp.msg = "Found"
            return resp

    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: real_build(*h, _Redirecting))
    monkeypatch.setattr(fetch_mod, "_sleep", lambda s: None)
    _refused("redirect_off_official", fetch_unmapped_blank, URL, tax_year=2025, cache_dir=Path("/nonexistent"))


# ── a user-supplied local blank ──────────────────────────────────────────────────────────────────────────────


def test_a_local_blank_for_a_pinned_only_host_passes_the_same_checks(opener, tmp_path):
    fake = opener({})
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(_form_pdf())
    root = tmp_path / "workspaces"
    blank = fetch_unmapped_blank(NM_URL, tax_year=2025, expected_title="DEMO-1", local_blank=saved,
                                 workspace_root=root, cache_dir=tmp_path / "cache")
    assert blank.origin == "local_blank" and blank.first_page.printed_year == 2025
    assert blank.path.parent == root / "2025" / "unmapped_blanks"  # under the year's workspace, not the cache
    assert not (tmp_path / "cache").exists() and fake.seen == []
    assert load_unmapped_blank(blank.sha256, tax_year=2025, workspace_root=root, cache_dir=tmp_path / "cache")
    from taxfill_core.workspace import Workspace
    Workspace(root, 2025).purge()
    assert not blank.path.exists()  # `taxfill purge` removes it with the year's drafts


def test_a_local_blank_is_refused_like_a_download(tmp_path):
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(_form_pdf(year="2024", small="Due April 15, 2025"))
    kw = {"tax_year": 2025, "local_blank": saved, "workspace_root": tmp_path / "ws"}
    _refused("wrong_year", fetch_unmapped_blank, URL, **kw)
    _refused("not_official_host", fetch_unmapped_blank, "https://forms.example.com/demo.pdf", **kw)
    _refused("not_https", fetch_unmapped_blank, URL.replace("https:", "http:"), **kw)
    saved.write_bytes(b"<html>the page around the form</html>")
    _refused("not_pdf", fetch_unmapped_blank, URL, **kw)
    saved.write_bytes(_edit_catalog(_form_pdf(widget=False), xfa_only=True))
    _refused("xfa_only", fetch_unmapped_blank, URL, **kw)
    with pytest.raises(FileNotFoundError, match="in a browser"):
        fetch_unmapped_blank(URL, tax_year=2025, local_blank=tmp_path / "missing.pdf")
    assert not (tmp_path / "ws").exists()


def test_a_local_blank_header_may_follow_a_small_prefix(tmp_path):
    # Phase K JK14 (2026-10-24): ADR-0002 rule 5 — %PDF anywhere in the first 1024 bytes, as seed_blank checks.
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(b"\r\n<!-- saved by a browser -->\r\n" + _form_pdf())
    kw = {"tax_year": 2025, "local_blank": saved, "workspace_root": tmp_path / "ws"}
    assert fetch_unmapped_blank(URL, **kw).first_page.printed_year == 2025
    saved.write_bytes(_form_pdf().replace(b"%PDF", b"%XYZ", 1))
    err = _refused("not_pdf", fetch_unmapped_blank, URL, **kw)
    assert "save the form itself" in str(err)


def test_tax_year_is_checked():
    with pytest.raises(ValueError, match="four-digit year"):
        fetch_unmapped_blank(URL, tax_year="2025")  # type: ignore[arg-type]


# ── real 2025 pack blanks (network-marked: read from the shared cache) ────────────────────────────────────────


def _pack_bytes(rel: str) -> tuple[bytes, str]:
    from taxfill_core.schemas.formpack import load_pack

    pack = load_pack(REPO / "formpacks" / rel / "pack.yaml")
    try:
        return Path(fetch_pack_blank(pack)).read_bytes(), pack.source_url
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")


@pytest.mark.network
@pytest.mark.parametrize("rel, title", [
    ("federal/2025/f1040", "1040"),
    ("federal/2025/sched_a", "Schedule A (Form 1040)"),
    ("states/ga/2025/ga500", "Form 500"),
    ("states/oh/2025/it1040_oh", "IT 1040"),
    ("states/nc/2025/d400", "D-400"),
])
def test_real_2025_blanks_pass_and_are_refused_for_2024(rel, title):
    data, _ = _pack_bytes(rel)
    _, _, first = inspect_unmapped_blank(data, tax_year=2025, expected_title=title)
    assert first.printed_year == 2025 and first.title_found
    _refused("wrong_year", inspect_unmapped_blank, data, tax_year=2024)


@pytest.mark.network
def test_a_real_2024_blank_in_the_namespace_is_refused_for_2025(opener, cache):
    data, url = _pack_bytes("federal/2024/f1040")
    opener({url: [data]})
    stored = fetch_unmapped_blank(url, tax_year=2024, expected_title="1040", cache_dir=cache)
    err = _refused("wrong_year", load_unmapped_blank, stored.sha256, tax_year=2025, source_url=url, cache_dir=cache)
    assert "is the 2024 form, not 2025" in str(err)


@pytest.mark.network
def test_a_real_revision_dated_blank_is_refused():
    data, _ = _pack_bytes("federal/2025/fw7")
    _refused("revision_dated", inspect_unmapped_blank, data, tax_year=2025)


@pytest.mark.network
@pytest.mark.parametrize("rel", ["federal/2023/f1040x", "federal/2024/f1040x"])
@pytest.mark.parametrize("tax_year", [2025, 2024])
def test_the_real_1040x_revision_is_refused_for_every_tax_year(rel, tax_year):
    # Phase K JK14 (2026-10-24): both packs pin the Rev. December 2025 blank; before, it passed for tax year 2025.
    data, _ = _pack_bytes(rel)
    err = _refused("revision_dated", inspect_unmapped_blank, data, tax_year=tax_year)
    assert err.revision_year == 2025 and "'Rev. December 2025'" in str(err)
    assert "continuous-use revision" in str(err) and "no override" in str(err)


@pytest.mark.network
@pytest.mark.parametrize("rel", [
    "states/mo/2025/mo1040",     # the smallest title-size year measured (1.13)
    "states/co/2023/dr0104pn",   # a third of its title block's capitals print at title size or larger
    "states/va/2025/va760",      # prints "Rev. 04/26 WEB 2025": a print code, then the title year
])
def test_real_title_years_near_the_size_limit_still_pass(rel):
    data, _ = _pack_bytes(rel)
    year = int(rel.split("/")[2])
    assert inspect_unmapped_blank(data, tax_year=year)[2].printed_year == year


@pytest.mark.network
@pytest.mark.parametrize("rel", [f"states/ny/{y}/{f}" for y in (2023, 2024, 2025) for f in ("it201", "it203")])
def test_a_real_body_size_tax_period_is_not_a_title_year(rel):
    # NY draws its title year as vector art; the text year is the body-size "For the (full) year" line. NY IT-201
    # sets its capitals in two body sizes about equally, so a median reference would pass 2023 and 2024 (1.20).
    data, _ = _pack_bytes(rel)
    _refused("no_printed_year", inspect_unmapped_blank, data, tax_year=int(rel.split("/")[2]))
