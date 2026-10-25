"""Offline tests for scripts/check_quotes.py, the quote-verbatim checker (Phase K JK23, 2026-10-24).

Every source here is synthetic text served by a stub download (or the repo's own demo W-2 PDF), so nothing touches
the network; the weekly freshness workflow runs the script itself over the real tree.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import ssl
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("check_quotes", REPO / "scripts" / "check_quotes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_quotes"] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


cq = _load()

URL = "https://example.gov/booklet.html"
OTHER = "https://example.gov/other.html"
SOURCE_SENTENCE = ("Blind worker transportation services credit. You may claim a credit for 50% of the expenses paid. "
                   "The credit may not exceed $1,500 ($3,000 of expenses) per qualifying person.")
SOURCE_HTML = (f"<html><head><title>x</title><script>var a = 'not text';</script></head><body><h1>2025 Booklet</h1>"
               f"<p>{SOURCE_SENTENCE}</p><p>Line 10 tax. The amount is not less than zero.</p></body></html>").encode()
VERBATIM_QUOTE = "credit for 50% of the expenses paid. The credit may not exceed $1,500 ($3,000 of expenses) per qualifying person"
# The seeded paraphrase: the same sentence with one word and one figure re-written, as a drifting note would.
PARAPHRASE = "credit for 50% of the costs paid. The credit cannot exceed $1,500 ($3,000 of expenses) per qualifying person"


def _source(text: str, url: str = URL) -> "cq.Source":
    return cq.Source(url, text=text, sha256="0" * 64, kind="html")


def _cache(tmp_path, pages: dict[str, bytes | Exception], calls: list[str] | None = None, **kw) -> "cq.SourceCache":
    def download(url):
        if calls is not None:
            calls.append(url)
        answer = pages[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return cq.SourceCache(tmp_path / "qcache", download=download, **kw)


def _span(text, urls=(URL,), kind="tax.notes"):
    return cq.Span(kind, "knowledge/states/zz/2025.yaml", 2025, "tax.notes[0]", text, list(urls))


# ── the acceptance: a seeded paraphrase is reported ──────────────────────────────────────────────────────────────


def test_seeded_paraphrase_is_a_mismatch_and_the_verbatim_span_is_verbatim(tmp_path):
    sources = _cache(tmp_path, {URL: SOURCE_HTML}).get_many([URL])
    good = cq.check_span(_span(VERBATIM_QUOTE), sources)
    bad = cq.check_span(_span(PARAPHRASE), sources)
    assert good["status"] == cq.VERBATIM and good["url"] == URL
    assert bad["status"] == cq.MISMATCH and bad["class"] == "wording", bad
    # the closest passage is the source's own sentence, so the fix tranche starts from the right words
    assert "credit for 50% of the expenses paid" in bad["closest"] and bad["closest_url"] == URL
    assert 0.6 < bad["similarity"] < 1.0


def test_the_report_and_strict_mode_over_a_pack(tmp_path, monkeypatch):
    """End to end over a knowledge tree: report mode exits 0 and lists the paraphrase; --strict exits 1."""
    pack = {
        "jurisdiction": "states/zz", "tax_year": 2025,
        "tax": {"notes": [f"Line 15: the instructions allow a '{VERBATIM_QUOTE}'.",
                          f"Seeded: the instructions allow a '{PARAPHRASE}'.",
                          "Line 10 prints 'not less than zero' and the filer's tax is clamped."]},
        "sources": [{"id": "booklet-1", "topic": "forms_and_instructions", "url": URL, "descriptions": ["booklet"]}],
    }
    (tmp_path / "knowledge" / "states" / "zz").mkdir(parents=True)
    (tmp_path / "knowledge" / "states" / "zz" / "2025.yaml").write_text(yaml.safe_dump(pack), encoding="utf-8")
    monkeypatch.setattr(cq._fetch, "_download", lambda url, timeout, **kw: SOURCE_HTML)
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "blanks"))
    args = ["--knowledge", str(tmp_path / "knowledge"), "--cache", str(tmp_path / "qc"), "--json", str(tmp_path / "r.json")]
    assert cq.main(args) == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["totals"] == {"VERBATIM": 2, "MISMATCH": 1, "CLOSED": 0, "UNCHECKED": 0, "spans": 3}
    [mismatch] = [r for r in report["spans"] if r["status"] == "MISMATCH"]
    assert mismatch["span"] == PARAPHRASE and mismatch["where"] == "tax.notes[1]"
    assert report["by_kind_year"] == {"tax.notes 2025": {"VERBATIM": 2, "MISMATCH": 1}}
    assert report["mismatch_classes"] == {"wording": 1}
    assert cq.main([*args, "--strict"]) == 1


# ── normalisation, each way ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("span,source", [
    ("not less than zero", "Line 10   prints\nnot  less than\tzero"),  # whitespace and line breaks
    ("Federal adjusted gross income from Line 11a", "Federal adjusted gross income from Line11a"),  # a PDF's lost space
    ("self-employment income", "your self-employ-\nment income"),  # line-break hyphenation
    ("self-employment income", "your self- employment income"),
    ('enter "0" in the number of dependents box', "enter “0” in the number of dependents box"),  # curly -> straight
    ("enter “0” in the number of dependents box", 'enter "0" in the number of dependents box'),  # straight -> curly
    ("the Department’s web site", "the Department's web site"),
    ("Adjusted gross income — Enter the amount", "Adjusted gross income - Enter the amount"),  # dashes
    ("Adjusted gross income - Enter the amount", "Adjusted gross income–Enter the amount"),
    ("8z Other income. List type and amount: … 9 Total other income", "8z Other income. List type and amount: "
     "8a Gambling 8b Cancellation of debt 9 Total other income"),  # an ellipsis is a gap
    ("Tax ... from the table", "Tax computed from the table"),
    ("Total other income 9", "Total other income . . . . . . . . . 9"),  # dot leaders
    ("Widow[er] with dependent child", "5 Widow(er) with dependent child"),  # an editorial bracket
    ("What's New for Tax Year 2023", "WHAT'S NEW FOR TAX YEAR 2023"),  # the source is ALL-CAPS
    ("The credit may not exceed $1,500", "of expenses paid. the credit may not exceed $1,500"),  # first letter
    ("the credit may not exceed $1,500.", "The credit may not exceed $1,500\nPer person"),  # edge punctuation (a
    # sentence the source goes on with, "... $1,500 per person", is a MISMATCH since JK31: see the sentence-end test)
    ("Multiply Line 5d by $5,100", "MULTIPLY Line 5d by $5,100 (2024 Personal Exemption)"),  # one ALL-CAPS word
    ("married filing jointly", "If your filing status is married fil\ufffeing jointly"),  # pdfium's soft hyphen
    ("Line 3 total", "Line\x023 total"),  # a control character in a PDF text layer
])
def test_normalisation_finds_the_span(span, source):
    found = cq.find_span(span, _source(source))
    assert found is not None and found[0] == "verbatim"


@pytest.mark.parametrize("span,source", [
    ("The credit may not exceed $1,600", "The credit may not exceed $1,500"),  # a figure changed
    ("The credit cannot exceed $1,500", "The credit may not exceed $1,500"),  # a word changed
    ("The credit may exceed $1,500", "The credit may not exceed $1,500"),  # a word dropped
    ("9 Total other income … 8z Other income", "8z Other income 8a Gambling 9 Total other income"),  # gap out of order
    ("Line 1 … Line 9", "Line 1 " + "x" * (cq.ELLIPSIS_GAP + 10) + " Line 9"),  # a gap longer than an ellipsis may be
    ("Widow[er] with dependent child", "5 Widow" + "y" * 80 + " with dependent child"),  # bracket gap too long
    ("50% of the expenses", "5.0% of the expenses"),  # punctuation inside a figure is compared
    ("Multiply line 5d by $5,100", "MULTIPLY Line 5d by $5,100"),  # 'Line' is mixed case in the source
])
def test_normalisation_does_not_hide_a_change(span, source):
    found = cq.find_span(span, _source(source))
    assert found is None or found[0] == "case"


def test_a_case_change_in_a_mixed_case_source_is_a_mismatch_that_says_so(tmp_path):
    sources = {URL: _source("Blind worker transportation services credit is allowed")}
    row = cq.check_span(_span("blind worker TRANSPORTATION services credit"), sources)
    assert row["status"] == cq.MISMATCH and "ignoring case" in row["reason"] and row["class"] == "case"


def test_a_heading_ended_with_a_period_is_a_punctuation_mismatch():
    sources = {URL: _source("Line 1—Federal Adjusted Gross Income\nEnter your 2025 federal adjusted gross income")}
    row = cq.check_span(_span("Line 1—Federal Adjusted Gross Income. Enter your 2025 federal adjusted gross income"),
                        sources)
    assert row["status"] == cq.MISMATCH and row["class"] == "punctuation"
    # a figure's separators are not sentence punctuation: $1,500 against $1.500 stays a wording mismatch
    row = cq.check_span(_span("may not exceed $1,500 per person"), {URL: _source("may not exceed $1.500 per person")})
    assert row["class"] == "wording"


# ── unreadable sources are UNCHECKED, never MISMATCH ─────────────────────────────────────────────────────────────


def test_a_refused_host_is_unchecked_not_mismatch(tmp_path):
    refused = cq._fetch.RefusedFetchError(f"HTTP 403 (Forbidden) for {OTHER} — the server refused the request")
    calls: list[str] = []
    sources = _cache(tmp_path, {URL: SOURCE_HTML, OTHER: refused}, calls).get_many([URL, OTHER])
    assert sources[OTHER].unreadable == "host refused the script (HTTP 403)"
    only_refused = cq.check_span(_span(PARAPHRASE, [OTHER]), sources)
    assert only_refused["status"] == cq.UNCHECKED and "403" in only_refused["unread"][0]
    # not in the readable source either: still not a MISMATCH, the words may be in the refused one
    both = cq.check_span(_span(PARAPHRASE, [URL, OTHER]), sources)
    assert both["status"] == cq.UNCHECKED and both["reason"].startswith("not found in the 1 readable")
    assert both["closest_url"] == URL  # the near miss is still recorded for the fix tranche
    # a span the readable source does print is VERBATIM whatever the other source did
    assert cq.check_span(_span(VERBATIM_QUOTE, [OTHER, URL]), sources)["status"] == cq.VERBATIM


def _tls_failure() -> Exception:
    exc = cq._fetch.OfflineFetchError("could not reach x")
    exc.__cause__ = urllib.error.URLError(ssl.SSLCertVerificationError(1, "unable to get local issuer certificate"))
    return exc


@pytest.mark.parametrize("answer,reason", [
    (cq._fetch.FetchError("HTTP 404 (not found) for x"), "download failed: HTTP 404"),
    (_tls_failure(), "download failed: the host's TLS certificate could not be verified"),
    (b"", "the host answered with an empty body"),
    (cq._fetch.OfflineFetchError("could not reach x"), "download failed: host unreachable"),
    (b"PK\x03\x04 a zip file", "not a PDF or HTML document"),
    (b"%PDF-1.7 truncated", "pdf text extraction failed"),
    (b"<html><body><script>only()</script></body></html>", "the HTML page has no text"),
])
def test_every_unreadable_source_says_why(tmp_path, answer, reason):
    sources = _cache(tmp_path, {URL: answer}).get_many([URL])
    assert sources[URL].unreadable.startswith(reason)
    assert cq.check_span(_span(PARAPHRASE), sources)["status"] == cq.UNCHECKED


def test_a_quarantined_url_is_unchecked_without_a_download(tmp_path):
    calls: list[str] = []
    cache = _cache(tmp_path, {URL: SOURCE_HTML}, calls, quarantined={URL: "JK30, expires 2026-12-15"})
    row = cq.check_span(_span(PARAPHRASE), cache.get_many([URL]))
    assert row["status"] == cq.UNCHECKED and "freshness quarantine (JK30" in row["unread"][0] and calls == []


def test_a_span_without_a_candidate_url_is_unchecked():
    row = cq.check_span(_span(PARAPHRASE, []), {})
    assert row["status"] == cq.UNCHECKED and row["reason"].startswith("no candidate source URL")


# ── the url + sha256 cache ───────────────────────────────────────────────────────────────────────────────────────


def test_each_url_is_fetched_once_and_cached_by_url_and_sha256(tmp_path):
    calls: list[str] = []
    cache = _cache(tmp_path, {URL: SOURCE_HTML}, calls)
    cache.get_many([URL, URL])
    cache.get_many([URL])
    cache.save()
    assert calls == [URL]
    index = json.loads((tmp_path / "qcache" / "index.json").read_text(encoding="utf-8"))
    digest = index[URL]["sha256"]
    assert (tmp_path / "qcache" / "text" / f"{digest}.json").is_file()
    again = _cache(tmp_path, {URL: SOURCE_HTML}, calls).get_many([URL])[URL]  # a new run: read from the cache
    assert calls == [URL] and again.origin == "quote cache" and again.sha256 == digest
    assert _cache(tmp_path, {URL: SOURCE_HTML}, calls, refresh=True).get_many([URL])[URL].origin == "download"
    assert calls == [URL, URL]


def test_a_url_in_the_shared_blank_cache_is_read_from_there(tmp_path):
    pdf = (REPO / "docs" / "samples" / "w2_2025_synthetic.pdf").read_bytes()
    blanks = tmp_path / "blanks"
    blanks.mkdir()
    url = "https://example.gov/w2.pdf"
    cq._fetch._cache_path(blanks, url).write_bytes(pdf)
    source = _cache(tmp_path, {}, blank_cache=blanks).get_many([url])[url]
    assert source.origin == "blank cache" and source.kind == "pdf" and source.pages == [0]
    found = cq.check_span(_span("1 Wages, tips, other compensation", [url]), {url: source})
    assert found["status"] == cq.VERBATIM and found["page"] == 1


def test_offline_reads_only_the_caches(tmp_path):
    calls: list[str] = []
    source = _cache(tmp_path, {URL: SOURCE_HTML}, calls, offline=True).get_many([URL])[URL]
    assert calls == [] and source.unreadable == "not in the cache (offline run)"


# ── span extraction on representative real notes ────────────────────────────────────────────────────────────────

GA_2023 = ("2023 is Georgia's final graduated-rate year; no mid-2023 retroactive rate change applies to tax year 2023. "
           "Per the 2023 IT-511 'What's New' (p.7): 'Effective January 1, 2024, the income tax rate will be 5.39%. "
           "Additionally, personal exemptions have been repealed except for the $4,000 dependent exemption.' Do not "
           "use this 2023 pack for 2024+.")
KS_2025 = ("Claimed as a dependent by another taxpayer: the 2025 instructions zero only the DEPENDENTS box ('enter "
           "\"0\" in the number of dependents box'); like 2024 they print no rule zeroing the filing-status allowance "
           "itself. Confirm the dependent-filer treatment at the DOR (see the pack's unverified list).")
WI_2025 = ("blind worker transportation services credit (Line 15 — the 2025 face prints 'Qualifying expenses .00 x 50% "
           "= 15' and the instructions a 'credit for 50% of the expenses paid. The credit may not exceed $1,500 ($3,000 "
           "of expenses) per qualifying person'), school property tax credit")


@pytest.mark.parametrize("note,spans", [
    (GA_2023, ["What's New", "Effective January 1, 2024, the income tax rate will be 5.39%. Additionally, personal "
               "exemptions have been repealed except for the $4,000 dependent exemption."]),  # two spans, apostrophes
    (KS_2025, ['enter "0" in the number of dependents box']),  # a double-quoted figure nested in a single quote
    (WI_2025, ["Qualifying expenses .00 x 50% = 15", "credit for 50% of the expenses paid. The credit may not exceed "
               "$1,500 ($3,000 of expenses) per qualifying person"]),
    ('Line 1 reads "Federal adjusted gross income" on the face.', ["Federal adjusted gross income"]),
    ("The booklet says “Do not enter any amount on this line.” here.", ["Do not enter any amount on this line."]),
    ("Its heading is ‘Tips on Filing a Paper Return’ (p. 16).", ["Tips on Filing a Paper Return"]),
    ("The taxpayers' own return and the filer's spouse's income.", []),  # apostrophes only: no quote
    ("Georgia's rate is the state's flat rate, the DOR's table.", []),
    ("The face prints the 'z' item.", []),  # one word: a term, not a quote
])
def test_span_extraction(note, spans):
    assert cq.extract_spans(note) == spans


def test_the_extractor_reads_the_real_ga_2023_note():
    """GA_2023 above is a shortened copy: hold the extractor to the pack's own note too."""
    notes = yaml.safe_load((REPO / "knowledge" / "states" / "ga" / "2023.yaml").read_text(encoding="utf-8"))["tax"]["notes"]
    [note] = [n for n in notes if "'What's New' (p.7)" in n]
    spans = cq.extract_spans(note)
    assert spans[0] == "What's New" and spans[1].startswith("Effective January 1, 2024") and len(spans) == 2


# ── collection ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_form_lines_carry_their_own_url():
    pack = yaml.safe_load((REPO / "knowledge" / "federal" / "2025.yaml").read_text(encoding="utf-8"))
    spans = cq.collect_federal_pack(pack, "knowledge/federal/2025.yaml")
    assert len(spans) == len(pack["form_lines"])
    [other] = [s for s in spans if s.where == "form_lines.sched1.other_income"]
    assert other.kind == "form_lines" and other.urls == ["https://www.irs.gov/pub/irs-prior/f1040s1--2025.pdf"]
    assert "…" in other.text  # the ellipsis is a gap the matcher honours


def test_v2_quotes_point_at_their_sources_row():
    """A knowledge_v2.Quote is checked whole against the row its ref names (a TY2026+ pack's caveats are quotes)."""
    pack = {
        "schema_version": 2, "jurisdiction": "states/zz", "tax_year": 2026,
        "base_line": {"form": "Form 1", "line": "1", "quote": {"quote": "Federal adjusted gross income",
                                                                "ref": {"id": "forms-1", "pinpoint": "Line 1"}}},
        "tax": {"citation": {"id": "rates-1"},
                "caveats": [{"quote": "The credit may not exceed $1,500", "ref": {"id": "rates-1"}},
                            {"not_modeled": "the county tax", "ref": {"id": "rates-1"}}]},
        "sources": [{"id": "forms-1", "topic": "forms_and_instructions", "url": URL, "descriptions": ["d"]},
                    {"id": "rates-1", "topic": "rates", "url": OTHER, "descriptions": ["d"]}],
    }
    spans = [s for s in cq.collect_state_pack(pack, "zz.yaml") if s.kind == "v2.quote"]
    assert [(s.where, s.text, s.urls) for s in spans] == [
        ("base_line.quote", "Federal adjusted gross income", [URL]),
        ("tax.caveats[0]", "The credit may not exceed $1,500", [OTHER]),
    ]


def test_a_converted_v2_pack_has_its_wording_spans_checked():
    """The JK24 parity fixtures carry the TY2025 prose as {text, ref} wordings: their quoted spans are checked too."""
    path = REPO / "packages" / "core" / "tests" / "fixtures" / "state_knowledge_v2" / "ga_2025.yaml"
    pack = yaml.safe_load(path.read_text(encoding="utf-8"))
    spans = cq.collect_state_pack(pack, "ga_2025.yaml")
    rows = {row["id"]: row["url"] for row in pack["sources"]}
    [treaty] = [s for s in spans if s.where == "treaty.note.text" and s.text.startswith("Federal adjusted")]
    assert treaty.text == "Federal adjusted gross income (From Federal Form 1040)" and treaty.urls[0] in rows.values()
    notes = [s for s in spans if s.kind == "tax.notes"]
    assert notes and all(set(s.urls) == set(rows.values()) for s in notes)


def test_state_candidates_own_citation_first_then_the_pack():
    pack = {
        "jurisdiction": "states/zz", "tax_year": 2024,
        "citation": {"source": "the 'Main Booklet' title", "url": URL},
        "treaty_note": "The return 'starts from federal AGI' per the booklet.",
        "credits": [{"name": "X", "eligibility": "Allowed 'for each qualifying child'",
                     "citation": {"source": "s", "url": OTHER}}],
        "tax": {"notes": ["A note quoting 'two words here' only."], "citation": {"source": "s", "url": OTHER}},
    }
    spans = {s.kind: s for s in cq.collect_state_pack(pack, "zz.yaml")}
    assert spans["credits"].urls == [OTHER] and spans["credits"].elsewhere == [URL]  # its own citation alone
    assert spans["tax.notes"].urls == [OTHER, URL]  # tax.citation first, then every URL the pack cites
    assert spans["other"].urls == [URL, OTHER] and spans["other"].where == "treaty_note"
    assert len(spans) == 3  # citation descriptions are not checked


def test_a_credit_quoted_from_another_pack_source_is_reported_miscited(tmp_path):
    sources = _cache(tmp_path, {URL: SOURCE_HTML, OTHER: b"<html><body><p>" + b"Other words entirely. " * 5
                                + b"</p></body></html>"}).get_many([URL, OTHER])
    span = cq.Span("credits", "zz.yaml", 2025, "credits[0].eligibility", VERBATIM_QUOTE, [OTHER], elsewhere=[URL])
    row = cq.check_span(span, sources)
    assert row["status"] == cq.MISMATCH and row["reason"].startswith("miscited: verbatim in " + URL)
    assert row["class"] == "citation"
    assert row["found_in"] == URL


def test_a_garbled_text_layer_is_unchecked():
    """A font without a Unicode map (DC's D-40 books read "taÝ year" for "tax year") is unreadable, not a mismatch."""
    garbled = "Startinß Üith taÝ Ýear 202x, the Ïistrict has estaÞlisheÏ its oÜn stanÏarÏ ÏeÏuction amounts. " * 3
    assert cq.unreadable_text(garbled, "pdf").startswith("the text layer is garbled")
    assert cq.unreadable_text(SOURCE_SENTENCE + " Café façade résumé.", "pdf") == ""


def test_pack_urls_prefer_the_sources_table():
    pack = {"citation": {"url": URL}, "sources": [{"id": "a-1", "url": OTHER}]}
    assert cq.pack_urls(pack) == [OTHER]
    assert cq.pack_urls({"citation": {"url": URL}, "x": [{"url": OTHER + " (portal)"}]}) == [URL, OTHER]


def test_pack_option_checks_only_the_named_packs(tmp_path):
    federal = REPO / "knowledge" / "federal" / "2025.yaml"
    spans = cq.collect(REPO / "knowledge", [federal])
    assert spans and {s.pack for s in spans} == {"knowledge/federal/2025.yaml"} and {s.kind for s in spans} == {"form_lines"}


# ── CI: networked report mode in freshness.yml, offline tests only in ci.yml ─────────────────────────────────────


def test_freshness_runs_the_checker_in_report_mode_and_ci_stays_offline():
    workflows = REPO / ".github" / "workflows"
    freshness = yaml.safe_load((workflows / "freshness.yml").read_text(encoding="utf-8"))
    job = freshness["jobs"]["quotes"]
    [step] = [s for s in job["steps"] if "check_quotes.py" in s.get("run", "")]
    assert step["continue-on-error"] is True and "--strict" not in step["run"]
    assert "quotes" not in freshness["jobs"]["report"]["needs"]  # a quote mismatch never opens a freshness-red issue
    assert "check_quotes.py" not in (workflows / "ci.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("span,source,verbatim", [
    ("line 1-4", "Enter the total of line 14 here", False),        # a range must not merge into another number
    ("pages 38-43", "see pages 3843 of the booklet", False),
    ("pages 38\u201343", "see pages 38-43 of the booklet", True),  # en dash and hyphen are the same separator
    ("lines 1 - 4", "add lines 1-4 together", True),               # spaces around the dash do not matter
    ("self-employment tax", "self\u2010employment tax", True),     # a dash between letters is still dropped
])
def test_a_dash_between_digits_is_a_separator_not_a_merge(span, source, verbatim):
    """JK23 review (2026-10-24): normalisation keeps a dash between two digits, so figures cannot merge."""
    found = cq.find_span(span, _source(source))
    assert (found is not None and found[0] == "verbatim") is verbatim


# ── Phase K JK31 (2026-10-25): shifted text layers, a credit's second source, the false-positive closures ────────


def _font_chars(text: str, font: str) -> list[tuple[str, str]]:
    return [(c, font) for c in text]


def test_a_shifted_subset_font_is_decoded_and_other_fonts_are_not():
    """Arkansas DFA's AR2441 line 10, as pdfium reads it: the subset font numbers each glyph 29 below its letter
    (U+0003 for a space, U+0011 for '.', U+0013..U+001C for 0..9); the line number and the plain font are as is."""
    shifted = "0XOWLSO\\\x03OLQH\x03\x1c\x03E\\\x03\x11\x15\x13\x11\x03(QWHU\x03WKLV\x03DPRXQW"
    chars = (_font_chars("10 ", "ArialMT") + _font_chars(shifted, "MFCFOH+ArialMT")
             + _font_chars(" RETURN AR2441", "ABCDEF+Arial-Black"))
    assert cq.unshift_page(chars) == "10 Multiply line 9 by .20. Enter this amount RETURN AR2441"
    # its ligature and curly-quote codes: "GH\u00bfQHG" defined, "Dependent\u00b6s"
    assert cq.unshift_page(_font_chars("GH\u00bfQHG\x03\x03\x03", "AAAAAA+F")) == "defined   "
    # without the control characters a subset font is read as it is (an all-caps heading is not shifted text)
    assert cq.unshift_page(_font_chars("INCOME TAX RETURN", "AAAAAA+F")) == "INCOME TAX RETURN"


def test_an_old_extraction_in_the_quote_cache_is_read_again(tmp_path):
    cache = _cache(tmp_path, {URL: SOURCE_HTML})
    cache.get_many([URL])
    cache.save()
    row = cache.index[URL]
    stored = tmp_path / "qcache" / "text" / f"{row['sha256']}.json"
    data = json.loads(stored.read_text(encoding="utf-8"))
    assert data["extractor"] == cq.EXTRACTOR
    del data["extractor"]  # written by the JK23 extractor
    stored.write_text(json.dumps(data), encoding="utf-8")
    calls: list[str] = []
    again = _cache(tmp_path, {URL: SOURCE_HTML}, calls)
    again.get_many([URL])
    assert calls == [URL]


def test_a_credit_names_its_second_source_in_citations():
    pack = {
        "jurisdiction": "states/zz", "tax_year": 2025, "citation": {"source": "s", "url": "https://example.gov/c"},
        "credits": [{"name": "X", "claimed_on": "Line 20d ('20d. Historic Home Rehabilitation Credit')",
                     "citation": {"source": "the instructions", "url": URL},
                     "citations": [{"source": "the form face", "url": OTHER}]}],
    }
    [span] = [s for s in cq.collect_state_pack(pack, "zz.yaml") if s.kind == "credits"]
    assert span.urls == [URL, OTHER] and span.elsewhere == ["https://example.gov/c"]


SOURCE_SHA16 = hashlib.sha256(SOURCE_HTML).hexdigest()[:16]


@pytest.mark.parametrize("text, status", [
    ("You may claim a credit for 50% of the expenses.", "MISMATCH"),  # the sentence goes on: "... expenses paid."
    ("You may claim a credit for 50% of the expenses paid.", "VERBATIM"),
    ("You may claim a credit for 50% of the expenses", "VERBATIM"),  # no sentence end claimed
    ("You may claim a credit for 50% of the expenses...", "VERBATIM"),  # an ellipsis says it stops early
    ("Blind worker transportation services credit.", "VERBATIM"),  # the source's next word starts a sentence
])
def test_a_span_that_ends_a_sentence_must_not_drop_the_sources_last_words(tmp_path, text, status):
    # the JK31 review: "If your total MGI is $41,496 or less, you may qualify." read VERBATIM against "... you may
    # qualify for Kentucky Family Size Tax Credit."
    sources = _cache(tmp_path, {URL: SOURCE_HTML}).get_many([URL])
    assert cq.check_span(_span(text), sources)["status"] == getattr(cq, status)


def _closure(**kw):
    return {"pack": "knowledge/states/zz/2025.yaml", "where": "tax.notes[0]", "span": PARAPHRASE,
            "reason": "r", "read": "rendered p.1", "closest_sha256": SOURCE_SHA16} | kw


def test_a_closure_turns_its_mismatch_closed_and_a_stale_one_is_reported(tmp_path):
    sources = _cache(tmp_path, {URL: SOURCE_HTML}).get_many([URL])
    rows = [cq.check_span(_span(PARAPHRASE), sources), cq.check_span(_span(VERBATIM_QUOTE), sources)]
    stale = cq.apply_closures(rows, [_closure(), _closure(span=VERBATIM_QUOTE),
                                     _closure(pack="knowledge/states/yy/2025.yaml")])
    assert [r["status"] for r in rows] == [cq.CLOSED, cq.VERBATIM] and rows[0]["closed_reason"] == "r"
    # the verbatim span's closure is stale; the other pack's was not checked in this run, so it is not
    assert [c["span"] for c in stale] == [VERBATIM_QUOTE]


def test_strict_fails_on_a_stale_closure_and_passes_a_closed_mismatch(tmp_path, monkeypatch):
    pack = {"jurisdiction": "states/zz", "tax_year": 2025,
            "tax": {"notes": [f"Seeded: the instructions allow a '{PARAPHRASE}'."]},
            "sources": [{"id": "booklet-1", "topic": "forms_and_instructions", "url": URL, "descriptions": ["b"]}]}
    (tmp_path / "knowledge" / "states" / "zz").mkdir(parents=True)
    (tmp_path / "knowledge" / "states" / "zz" / "2025.yaml").write_text(yaml.safe_dump(pack), encoding="utf-8")
    monkeypatch.setattr(cq._fetch, "_download", lambda url, timeout, **kw: SOURCE_HTML)
    monkeypatch.setenv("TAXFILL_BLANKS_CACHE", str(tmp_path / "blanks"))
    closed = tmp_path / "closed.yaml"  # outside the repo, a pack is named by its file name ("2025.yaml")
    args = ["--knowledge", str(tmp_path / "knowledge"), "--cache", str(tmp_path / "qc"), "--closed", str(closed),
            "--strict"]
    assert cq.main(args) == 1  # no closure: the MISMATCH fails strict mode
    closed.write_text(yaml.safe_dump([_closure(pack="2025.yaml")]), encoding="utf-8")
    assert cq.main(args) == 0  # closed with its reason
    closed.write_text(yaml.safe_dump([_closure(pack="2025.yaml"), _closure(pack="2025.yaml", where="tax.notes[9]")]),
                      encoding="utf-8")
    assert cq.main(args) == 1  # a closure that matches no MISMATCH is stale


def test_a_closure_holds_only_while_its_source_is_unchanged(tmp_path):
    # the JK31 review: a closure keyed to the span alone kept a reissued source's real MISMATCH closed
    sources = _cache(tmp_path, {URL: SOURCE_HTML}).get_many([URL])
    for digest in ("0123456789abcdef", "none"):  # another document; or "no close passage" while there is one
        rows = [cq.check_span(_span(PARAPHRASE), sources)]
        stale = cq.apply_closures(rows, [_closure(closest_sha256=digest)])
        assert rows[0]["status"] == cq.MISMATCH and "re-read it" in rows[0]["closure_drift"], digest
        assert [c["closest_sha256"] for c in stale] == [digest]


def test_a_closure_names_its_source_digest(tmp_path):
    bad = tmp_path / "closed.yaml"
    for digest in (None, "3ce70e03", "3CE70E0378602D0F", "sha256 3ce70e0378602d0f"):
        entry = _closure() | ({"closest_sha256": digest} if digest else {})
        if digest is None:
            del entry["closest_sha256"]
        bad.write_text(yaml.safe_dump([entry]), encoding="utf-8")
        with pytest.raises(ValueError, match="closest_sha256"):
            cq.load_closures(bad)


def test_a_closure_without_its_reason_is_refused(tmp_path):
    bad = tmp_path / "closed.yaml"
    bad.write_text(yaml.safe_dump([{"pack": "p", "where": "w", "span": "s"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        cq.load_closures(bad)


def test_every_committed_closure_still_names_a_quote_its_pack_makes():
    """Offline half of the self-clearing rule: an edited quote leaves its closure naming nothing, and fails here."""
    closures = cq.load_closures(cq.DEFAULT_CLOSED)
    for c in closures:
        spans = cq.collect(REPO / "knowledge", [REPO / c["pack"]])
        assert any(s.where == c["where"] and s.text == c["span"] for s in spans), c
        assert c["reason"].strip() and c["read"].strip(), c


def test_an_off_gov_document_link_named_in_a_citation_is_a_candidate():
    """New Mexico's 2023/2024 PIT-1 files live on the Department's AWS document host (JK27): the citation's url is the
    .gov page that publishes them and the file link sits in its source text, so the checker reads that link too."""
    aws = "https://klvg4oyd4j.execute-api.us-west-2.amazonaws.com/prod/PublicFiles/x/2024pit-1-ins.pdf"
    page = "https://www.tax.newmexico.gov/forms-publications/"
    pack = {
        "jurisdiction": "states/zz", "tax_year": 2024,
        "tax": {"notes": ["Line 18: 'R = Rate tables' is entered."],
                "citation": {"source": f"2024 PIT-1 instructions (file {aws}); see also https://example.gov/b.pdf", "url": page}},
        "credits": [{"name": "X", "amount": "'The credit is 25% of the Earned Income Credit'",
                     "citation": {"source": f"2024 PIT-1 instructions; file {aws}", "url": page}}],
    }
    assert cq.pack_urls(pack) == [page, aws]  # the .gov link in the text is not added: a .gov document is cited by url
    spans = {s.kind: s for s in cq.collect_state_pack(pack, "zz.yaml")}
    assert spans["credits"].urls == [page, aws]
    assert spans["tax.notes"].urls == [page, aws]


def test_a_partly_garbled_layer_confirms_a_clean_span_and_never_concludes_a_mismatch(tmp_path):
    """DC's D-40 books: some fonts carry no Unicode map ("taÝ Ýear"), others read clean. A span found in the clean
    fonts is VERBATIM; a span not found stays UNCHECKED (its words may be in the garbled fonts)."""
    garbled = "Startinß Üith taÝ Ýear 202x, the Ïistrict has estaÞlisheÏ its oÜn stanÏarÏ ÏeÏuction amounts. " * 3
    page = f"<html><body><p>{garbled}</p><p>Make check or money order payable to: DC Treasurer.</p></body></html>"
    sources = _cache(tmp_path, {URL: page.encode()}).get_many([URL])
    assert sources[URL].unreadable.startswith("the text layer is garbled")
    ok = cq.check_span(_span("Make check or money order payable to: DC Treasurer"), sources)
    assert ok["status"] == cq.VERBATIM and "partly garbled" in ok["note"]
    miss = cq.check_span(_span("the District has established its own standard deduction amounts"), sources)
    assert miss["status"] == cq.UNCHECKED
