"""The freshness quarantine (Phase J JT0c): known reds behind an expiring allowlist.

``scripts/freshness_quarantine.yaml`` names each known red of the weekly freshness job. The root
``conftest.py`` marks a quarantined network test xfail on a fetch failure only, and
``scripts/check_drift.py`` reports a quarantined URL's drift without failing. An expired entry
fails the drift job, so a quarantine cannot quietly become permanent.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

QUARANTINE_FILE = Path(__file__).resolve().with_name("freshness_quarantine.yaml")
MAX_DAYS = 200
_KINDS = ("network_test", "drift")


@dataclass(frozen=True)
class Entry:
    kind: str
    target: str  # the pytest node id (network_test) or the URL (drift)
    added: dt.date
    expires: dt.date
    fixed_by: str
    why: str

    def expired(self, today: dt.date) -> bool:
        return today > self.expires

    def label(self) -> str:
        return f"{self.kind} {self.target} (expires {self.expires}, fixed by {self.fixed_by})"


def _date(raw: object, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ValueError(f"{where}: {raw!r} is not an ISO date (YYYY-MM-DD)") from exc


def load(path: str | Path | None = None) -> list[Entry]:
    """Parse and validate the quarantine file (``$TAXFILL_FRESHNESS_QUARANTINE`` overrides the path)."""
    path = Path(path or os.environ.get("TAXFILL_FRESHNESS_QUARANTINE") or QUARANTINE_FILE)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[Entry] = []
    for i, row in enumerate(raw.get("entries") or []):
        where = f"{path.name} entry {i}"
        kind = row.get("kind")
        if kind not in _KINDS:
            raise ValueError(f"{where}: kind must be one of {_KINDS}, got {kind!r}")
        target = row.get("id") if kind == "network_test" else row.get("url")
        if not target:
            raise ValueError(f"{where}: a {kind} entry names its {'id' if kind == 'network_test' else 'url'}")
        added, expires = _date(row.get("added"), where), _date(row.get("expires"), where)
        if not added < expires <= added + dt.timedelta(days=MAX_DAYS):
            raise ValueError(f"{where}: expires must fall within {MAX_DAYS} days after added ({added} -> {expires})")
        fixed_by, why = row.get("fixed_by"), row.get("why")
        if not fixed_by or not why:
            raise ValueError(f"{where}: every entry names the tranche that fixes it (fixed_by) and why")
        entries.append(Entry(kind, str(target), added, expires, str(fixed_by), " ".join(str(why).split())))
    return entries


def quarantine_items(items, entries: list[Entry], today: dt.date, fetch_error: type[BaseException]) -> list[str]:
    """Mark each collected item an ACTIVE network_test entry names xfail on ``fetch_error`` only.

    An expired entry marks nothing, so its test fails as it would without the quarantine. Returns the
    node ids that were marked.
    """
    import pytest  # noqa: PLC0415

    active = {e.target: e for e in entries if e.kind == "network_test" and not e.expired(today)}
    marked: list[str] = []
    for item in items:
        entry = active.get(item.nodeid)
        if entry is None:
            continue
        item.add_marker(pytest.mark.xfail(
            raises=fetch_error, strict=False,
            reason=f"freshness quarantine until {entry.expires} ({entry.fixed_by}): {entry.why}",
        ))
        marked.append(item.nodeid)
    return marked


def split_drift(drift: list[str], entries: list[Entry], today: dt.date) -> tuple[list[str], list[str]]:
    """(still failing, quarantined) for check_drift's drift items; an expired entry is itself a failure."""
    failing: list[str] = []
    quarantined: list[str] = []
    active = [e for e in entries if e.kind == "drift" and not e.expired(today)]
    for item in drift:
        entry = next((e for e in active if e.target in item), None)
        if entry is None:
            failing.append(item)
        else:
            quarantined.append(f"{item} [quarantined until {entry.expires}, fixed by {entry.fixed_by}]")
    failing.extend(
        f"freshness quarantine entry EXPIRED on {e.expires}: {e.label()} — fix it ({e.fixed_by}) and delete the "
        f"row, or renew it in scripts/freshness_quarantine.yaml with a reason"
        for e in entries if e.expired(today)
    )
    return failing, quarantined
