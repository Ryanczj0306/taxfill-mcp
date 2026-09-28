"""Phase J JS2b — a TY-Y state knowledge pack cites Y's documents, not the year it was copied from.

The JS2 sweep found three packs rolled forward from 2023 with only part of the text updated. WV 2024/2025 cited
``…/PIT/2024/it140.2023.pdf``-style URLs (the directory year changed, the file year did not — all 404s), and carried
2023's credit limits and line numbers. VT 2024's credits cited the 2023 IN-112 and said 'A 2023 Vermont income tax
return must be filed'. These gates catch both shapes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKS = sorted(p for p in (REPO / "knowledge" / "states").glob("*/*.yaml") if p.stem.isdigit() and int(p.stem) >= 2024)

# (pack, url) -> why a citation to an earlier year's file is right for this year.
OLDER_FILE_ADJUDICATED: dict[tuple[str, str], str] = {
    ("mn/2024", "https://www.revenue.state.mn.us/press-release/2023-12-12/minnesota-income-tax-brackets-standard-"
                "deduction-and-dependent-exemption"): "the Department announces the next year's indexed brackets each December",
    ("mn/2025", "https://www.revenue.state.mn.us/press-release/2024-12-16/minnesota-income-tax-brackets-standard-"
                "deduction-and-dependent-exemption"): "the Department announces the next year's indexed brackets each December",
    ("sc/2024", "https://dor.sc.gov/forms-site/Forms/TC60_2023.pdf"):
        "the pack records that the 2024 TC-60 revision was not retrievable (TC60_2024.pdf still 404s, 2026-09-28)",
}
_EXEMPT_URL = re.compile(r"legis|/bills/|Sessions|statute|/code|/law|/acts?/|notice|bulletin|memos|/legal/", re.I)


def _urls(text: str) -> set[str]:
    return set(re.findall(r"https?://[^\s'\")\],]+", text))


def _file_years(url: str) -> list[int]:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return [int(y) for y in re.findall(r"(?<!\d)(20[12]\d)(?!\d)", name)]


@pytest.mark.parametrize("path", PACKS, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_no_citation_points_at_an_earlier_years_file(path: Path):
    year, key = int(path.stem), f"{path.parent.name}/{path.stem}"
    stale = []
    for url in sorted(_urls(path.read_text(encoding="utf-8"))):
        years = _file_years(url)
        dir_years = [int(y) for y in re.findall(r"/(20[12]\d)/", url)]
        in_year_dir = year in dir_years
        if years and max(years) < year and (in_year_dir or not _EXEMPT_URL.search(url)):
            if (key, url) not in OLDER_FILE_ADJUDICATED:
                stale.append(url)
    assert not stale, (f"{key} cites earlier years' files — point each at the {year} document (and re-verify what it "
                       f"backs), or adjudicate it in OLDER_FILE_ADJUDICATED: {stale}")


@pytest.mark.parametrize("path", PACKS, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_no_carried_over_prior_year_phrasing(path: Path):
    year = int(path.stem)
    body = "\n".join(line for line in path.read_text(encoding="utf-8").split("\n") if not line.lstrip().startswith("#"))
    body = re.sub(r"\s+", " ", body)
    prior = year - 1
    patterns = [rf"\bA {prior} [A-Z][a-z]+(?: [A-Z][a-z]+)? income tax return must be filed", rf"\bfor {prior}: \(1\)",
                rf"include {prior} Form", rf"born \d{{4}} through {prior} for tax year {prior}",
                rf"\b{prior} (?:Form|Schedule) [A-Z0-9-]+ \((?:Homestead|Personal|Form IT|Modifications)",
                rf"due date April 15,? {year}\b"]
    hits = [m.group(0) for pat in patterns for m in re.finditer(pat, body)]
    assert not hits, f"{path.parent.name}/{year} still carries {prior}'s text: {hits}"


def test_the_adjudicated_rows_are_still_cited():
    for (key, url), why in OLDER_FILE_ADJUDICATED.items():
        text = (REPO / "knowledge" / "states" / f"{key}.yaml").read_text(encoding="utf-8")
        assert url in text and why, f"{key} no longer cites {url} — delete the row"
