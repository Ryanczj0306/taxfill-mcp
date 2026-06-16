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
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Source", "SourcesResult", "get_sources"]

_JURISDICTION_RE = re.compile(r"^(federal|states/[a-z]{2})$")
# Words too generic to be useful for keyword matching against topic text.
_STOPWORDS = frozenset({"the", "and", "for", "a", "an", "of", "to", "tax", "in", "on", "or"})


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


def _tokens(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _STOPWORDS}


def _rank_topics(by_topic: dict, topic: str) -> list[str]:
    """Topic keys whose name or answers match the query, exact-key first."""
    query = topic.strip().lower()
    query_tokens = _tokens(topic)
    scored: list[tuple[int, str]] = []
    for key, entries in by_topic.items():
        key_norm = key.lower()
        if key_norm == query:
            scored.append((100, key))
            continue
        score = 0
        if query and (query in key_norm or key_norm in query):
            score += 50
        score += 10 * len(query_tokens & _tokens(key_norm))
        answers_text = " ".join(str(e.get("answers", "")) for e in (entries or []))
        score += len(query_tokens & _tokens(answers_text))
        if score:
            scored.append((score, key))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [key for _, key in scored]


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
