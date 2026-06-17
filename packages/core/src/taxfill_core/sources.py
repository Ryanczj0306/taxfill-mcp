"""Authoritative-source registry access — dev plan section 7 (freshness protocol).

``get_sources(topic, year, jurisdiction)`` reads ``knowledge/sources.yaml`` and
returns the ranked official URLs that resolve a topic, plus the change-channels
the agent must watch for anything newer than the shipped knowledge packs. It is
the server half of the freshness protocol: for any year newer than the newest
pack, or any benefit a pack does not cover, the agent resolves the number from
these .gov URLs and cites it — and refuses to fill a line it cannot cite.

The registry is intentionally NOT year-specific (one URL family per topic across
years); ``year`` shapes the retrieval hint (prior-year revisions live under
``irs.gov/pub/irs-prior/<form>--<year>.pdf``) and is echoed back for the caller.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from taxfill_core.knowledge import validate_gov_url

__all__ = ["Source", "SourcesResult", "get_sources"]

_JURISDICTION_RE = re.compile(r"^(federal|states/[a-z]{2})$")
# Words too generic to be useful for keyword matching against topic text.
_STOPWORDS = frozenset({"the", "and", "for", "a", "an", "of", "to", "tax", "in", "on", "or"})
# Tokens that name a whole family of topics rather than a specific one, so an
# incidental overlap on them must NOT promote an unrelated topic to matched
# (e.g. "credit" appears in EITC, CTC, energy, dependent-care answers alike —
# without this, get_sources("energy credit") would false-match the EITC entry).
# They are ignored when scoring answers text; the distinctive token ("energy",
# "child") is what disambiguates. They still count for topic-KEY matching.
_GENERIC_TOKENS = frozenset({"credit", "credits", "deduction", "deductions", "income", "form", "forms"})
# A topic must clear this score to be returned as a match. Exact-key (1000),
# key-substring (100) and key-token (30/token) matches clear it on their own; a
# lone incidental answers-token (1) does not — so a single shared word is a
# clean miss, not a wrong (matched=True) citation that suppresses the fallback.
_MATCH_THRESHOLD = 2


def _repo_knowledge_dir() -> Path:
    # packages/core/src/taxfill_core/sources.py -> repo root is parents[4].
    return Path(__file__).resolve().parents[4] / "knowledge"


class Source(BaseModel):
    """One registry entry: where truth lives, what it answers, how often it changes."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="Official source URL (.gov / treasury.gov only).")
    answers: str = Field(description="What questions this source resolves.")
    cadence: str = Field(description="When/how often it updates.")
    topic: str | None = Field(default=None, description="The by_topic key this came from (None for change_channels).")

    @field_validator("url")
    @classmethod
    def _url_is_gov(cls, value: str) -> str:
        return validate_gov_url(value)


class SourcesResult(BaseModel):
    """The freshness-protocol answer for one topic lookup."""

    model_config = ConfigDict(extra="forbid")

    topic: str
    jurisdiction: str
    year: int
    matched: bool = Field(description="True when the topic resolved to at least one registry source.")
    sources: list[Source] = Field(default_factory=list, description="Ranked sources for the topic (best first).")
    change_channels: list[Source] = Field(
        default_factory=list,
        description="Always returned: the official channels that signal a shipped pack may be stale.",
    )
    available_topics: list[str] = Field(
        default_factory=list, description="Every by_topic key for this jurisdiction — pick one of these."
    )
    retrieval_hint: str = Field(description="How to use these for the requested year (prior-year archive, cite-or-refuse).")
    notes: list[str] = Field(default_factory=list)


def _load_registry(base_dir: str | Path | None) -> dict:
    base = Path(base_dir) if base_dir is not None else _repo_knowledge_dir()
    path = base / "sources.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"source registry not found: {path} — pass base_dir=<repo knowledge/ dir> "
            f"(the default only works from a source checkout)"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: sources.yaml must be a YAML mapping, got {type(raw).__name__}")
    return raw


def _jurisdiction_block(registry: dict, jurisdiction: str) -> dict:
    if jurisdiction == "federal":
        return registry.get("federal") or {}
    state_code = jurisdiction.split("/", 1)[1]
    return (registry.get("states") or {}).get(state_code) or {}


def _tokens(text: str) -> list[str]:
    """Order-preserving content tokens (stopwords dropped); used for matching."""
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _STOPWORDS]


def _longest_contiguous_phrase(query_seq: list[str], answers_seq: list[str]) -> int:
    """Length of the longest run of >=2 contiguous query tokens that also appears
    contiguously in the answers token sequence.

    A topic whose answers literally contain a multi-word query phrase is the
    better fit than one that merely shares the words scattered: "earned income
    credit" appears contiguously in the EITC answers but not in the dependent-care
    answers ("earned income rule"), so this breaks ties the per-token count cannot.
    """
    best = 0
    n = len(query_seq)
    for i in range(n):
        for j in range(i + 2, n + 1):  # phrases of length >= 2
            phrase = query_seq[i:j]
            if len(phrase) <= best:
                continue
            if any(answers_seq[k : k + len(phrase)] == phrase for k in range(len(answers_seq) - len(phrase) + 1)):
                best = len(phrase)
    return best


def _score_topic(key: str, entries: list, query: str, query_tokens: set[str]) -> int:
    """Relevance of one by_topic key to the query.

    The topic NAME dominates (exact key, substring, then shared key-tokens) so a
    keyworded phrase resolves to its own block; the ``answers`` text only breaks
    ties between specific topics via DISTINCTIVE tokens. Generic family words
    (``credit``, ``deduction``, ...) are ignored in answers scoring so a single
    shared word can never promote an unrelated topic above the match threshold.
    """
    key_norm = key.lower()
    if key_norm == query:
        return 1000
    distinctive = {t for t in query_tokens if t not in _GENERIC_TOKENS}
    # A purely generic query ("deduction", "credit") carries no specific signal:
    # it must be a clean miss, never a substring/answers match on a family word.
    if not distinctive:
        return 0
    score = 0
    if query and (query in key_norm or key_norm in query):
        score += 100
    # Key-token matches count only on DISTINCTIVE tokens, so a generic word in a
    # key name (e.g. the "income" in `investment_income`) cannot incidentally
    # win an unrelated query ("earned income credit").
    score += 30 * len(distinctive & set(_tokens(key_norm)))
    answers_seq = _tokens(" ".join(str(e.get("answers", "")) for e in (entries or [])))
    answers_tokens = set(answers_seq)
    # 10 per distinctive token present (the real signal) + 1 per extra
    # occurrence (a fine tiebreaker: the topic that talks about the distinctive
    # word most is the better fit, e.g. "child" for CTC vs EITC).
    hits = distinctive & answers_tokens
    score += 10 * len(hits)
    score += sum(answers_seq.count(t) - 1 for t in hits)
    # Phrase boost: a topic whose answers literally contain a multi-word run of
    # the query (e.g. "earned income credit") is the better fit than one that
    # only shares the words scattered ("earned income rule") — this is what
    # separates the EITC entry from the dependent-care entry for an EITC query.
    score += 40 * _longest_contiguous_phrase(_tokens(query), answers_seq)
    return score


def _rank_topics(by_topic: dict, topic: str) -> list[str]:
    """Topic keys that match the query, best first — only the best-scoring tier.

    Returns only the topic(s) tied at the top score and clearing the match
    threshold, so an incidental single-word overlap (which never clears the
    threshold) is a clean miss rather than a wrong, fallback-suppressing match.
    """
    query = topic.strip().lower()
    query_tokens = set(_tokens(topic))
    scored = [(_score_topic(key, entries, query, query_tokens), key) for key, entries in by_topic.items()]
    best = max((s for s, _ in scored), default=0)
    if best < _MATCH_THRESHOLD:
        return []
    winners = sorted(key for score, key in scored if score == best)
    return winners


def get_sources(
    topic: str,
    year: int,
    jurisdiction: str = "federal",
    *,
    base_dir: str | Path | None = None,
) -> SourcesResult:
    """Return ranked official sources for ``topic`` plus the freshness change-channels.

    Args:
        topic: the area of law to resolve, e.g. ``"education"``, ``"mortgage
            interest"``, ``"nonresident_and_treaties"``. Matched against the
            registry's by_topic keys and their ``answers`` text, so a natural
            phrase resolves to the right block.
        year: the tax year being worked; shapes the retrieval hint (prior-year
            revisions live under ``irs.gov/pub/irs-prior/``).
        jurisdiction: ``"federal"`` (default) or ``"states/<xx>"``.

    Returns:
        A :class:`SourcesResult`. ``matched`` is False when the topic is not in
        the registry — then ``sources`` is empty, ``available_topics`` lists what
        IS covered, and the notes point to the change-channels and the cite-or-
        refuse rule (the coverage rule: never fill a line whose authority is not
        in this registry).

    Raises:
        ValueError: malformed ``jurisdiction``.
        FileNotFoundError: the registry file is missing.
    """
    if not _JURISDICTION_RE.fullmatch(jurisdiction):
        raise ValueError(
            f"jurisdiction must be 'federal' or 'states/<two-letter lowercase code>', got {jurisdiction!r}"
        )
    registry = _load_registry(base_dir)
    block = _jurisdiction_block(registry, jurisdiction)
    by_topic: dict = block.get("by_topic") or {}
    change_channels = [Source(**c) for c in (block.get("change_channels") or [])]

    ranked = _rank_topics(by_topic, topic)
    sources: list[Source] = []
    for key in ranked:
        for entry in by_topic.get(key) or []:
            sources.append(Source(topic=key, **entry))

    notes: list[str] = []
    if not sources:
        if not by_topic:
            notes.append(
                f"No source registry yet for jurisdiction '{jurisdiction}'. Resolve the figure on the "
                f"official DOR/.gov site and cite it; state blocks ship with each state's knowledge pack."
            )
        else:
            notes.append(
                f"Topic '{topic}' is not in the registry. Pick one of available_topics, or use the "
                f"change_channels + a .gov search and cite the result — never fill a line whose authority "
                f"is not in the registry (the coverage rule)."
            )

    hint = (
        f"For tax year {year}: shipped knowledge packs cover the math; for anything they do not cover, "
        f"open these URLs (irs.gov/.gov only), confirm the figure for {year}, and record the citation in "
        f"RECONCILIATION.md. Prior-year forms and instructions are at "
        f"https://www.irs.gov/pub/irs-prior/<form>--{year}.pdf. Refuse to fill any line you cannot cite."
    )

    return SourcesResult(
        topic=topic,
        jurisdiction=jurisdiction,
        year=year,
        matched=bool(sources),
        sources=sources,
        change_channels=change_channels,
        available_topics=sorted(by_topic),
        retrieval_hint=hint,
        notes=notes,
    )
