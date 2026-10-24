"""Offline tests for scripts/check_quotes.py, the quote-verbatim checker (Phase K JK23, 2026-10-24).

Every source here is synthetic text served by a stub download (or the repo's own demo W-2 PDF), so nothing touches
the network; the weekly freshness workflow runs the script itself over the real tree.
"""
from __future__ import annotations

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
    assert report["totals"] == {"VERBATIM": 2, "MISMATCH": 1, "UNCHECKED": 0, "spans": 3}
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
    ("the credit may not exceed $1,500.", "The credit may not exceed $1,500 per person"),  # edge punctuation
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
