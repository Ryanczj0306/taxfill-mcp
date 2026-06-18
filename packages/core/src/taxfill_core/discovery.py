"""Form-pack discovery — dev plan section 8 (`list_forms`, `get_form_map`).

Thin, read-only views over ``formpacks/<jurisdiction>/<year>/<form_key>/pack.yaml``
so an MCP client can discover which packs exist and fetch one pack's line→field
map + relations without knowing the on-disk layout. No PDF work happens here;
filling/verifying/rendering are separate tools.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from taxfill_core.datadir import formpacks_dir
from taxfill_core.schemas.formpack import FormPack, load_pack

__all__ = ["FormSummary", "LineMap", "FormMap", "list_forms", "get_form_map", "load_form_pack"]


def _repo_formpacks_dir() -> Path:
    return formpacks_dir()


def _pack_path(form: str, year: int, jurisdiction: str, base_dir: str | Path | None) -> Path:
    base = Path(base_dir) if base_dir is not None else _repo_formpacks_dir()
    return base / jurisdiction / str(year) / form / "pack.yaml"


def load_form_pack(
    form: str,
    year: int,
    jurisdiction: str = "federal",
    *,
    base_dir: str | Path | None = None,
) -> FormPack:
    """Load the :class:`FormPack` for a (form_key, year, jurisdiction).

    The agent-facing counterpart to :func:`get_form_map`: tools that fetch/fill/
    verify need the pack object (source_url, sha, fields), not just its map.

    Raises:
        FileNotFoundError: no pack at the resolved path; lists available keys.
    """
    path = _pack_path(form, year, jurisdiction, base_dir)
    if not path.is_file():
        available = sorted(s.form_key for s in list_forms(jurisdiction, year, base_dir=base_dir))
        raise FileNotFoundError(
            f"no form pack for form '{form}', {jurisdiction} {year} — looked for {path}. "
            f"Available form keys for {jurisdiction} {year}: {available or 'none'}. Use list_forms()."
        )
    return load_pack(path)


class FormSummary(BaseModel):
    """One discoverable pack (what ``list_forms`` returns per entry)."""

    model_config = ConfigDict(extra="forbid")

    jurisdiction: str
    tax_year: int
    form_key: str = Field(description="Directory/key name, e.g. 'f1040nr' — the id get_form_map and fill_form take.")
    form: str = Field(description="The pack's printed form name, e.g. '1040-NR'.")
    source_url: str
    num_fields: int
    has_relations: bool
    has_cross_form: bool


class LineMap(BaseModel):
    """One line→field mapping entry."""

    model_config = ConfigDict(extra="forbid")

    line: str
    field: str
    type: str
    required: bool
    group: str | None = None


class FormMap(BaseModel):
    """One pack's full line→field map + math, for an agent to fill against."""

    model_config = ConfigDict(extra="forbid")

    form: str
    form_key: str
    jurisdiction: str
    tax_year: int
    source_url: str
    acroform_root: str
    lines: list[LineMap]
    relations: list[str]
    cross_form: list[str]
    identity_fields: list[str]


def list_forms(
    jurisdiction: str | None = None,
    year: int | None = None,
    *,
    base_dir: str | Path | None = None,
) -> list[FormSummary]:
    """List the available form packs, optionally filtered by jurisdiction/year.

    Args:
        jurisdiction: ``'federal'`` or ``'states/<xx>'``; None lists all.
        year: a tax year; None lists all years.
        base_dir: override the ``formpacks/`` directory (installed-wheel use).

    Returns:
        Ordered list of :class:`FormSummary` (jurisdiction, year, form_key, ...).
    """
    base = Path(base_dir) if base_dir is not None else _repo_formpacks_dir()
    if not base.is_dir():
        raise FileNotFoundError(
            f"formpacks directory not found: {base} — pass base_dir=<repo formpacks/ dir> "
            f"(the default only works from a source checkout)"
        )
    out: list[FormSummary] = []
    for path in sorted(base.glob("**/pack.yaml")):
        pack = load_pack(path)
        if jurisdiction is not None and pack.jurisdiction != jurisdiction:
            continue
        if year is not None and pack.tax_year != year:
            continue
        out.append(
            FormSummary(
                jurisdiction=pack.jurisdiction,
                tax_year=pack.tax_year,
                form_key=path.parent.name,
                form=pack.form,
                source_url=pack.source_url,
                num_fields=len(pack.fields),
                has_relations=bool(pack.relations),
                has_cross_form=bool(pack.cross_form),
            )
        )
    return out


def get_form_map(
    form: str,
    year: int,
    jurisdiction: str = "federal",
    *,
    base_dir: str | Path | None = None,
) -> FormMap:
    """Return one pack's line→field map, relations, and cross-form refs.

    Args:
        form: the form KEY (directory name, e.g. ``'f1040'``, ``'sched_c'``).
        year: tax year.
        jurisdiction: ``'federal'`` (default) or ``'states/<xx>'``.
        base_dir: override the ``formpacks/`` directory.

    Returns:
        A :class:`FormMap`.

    Raises:
        FileNotFoundError: no pack at ``<base>/<jurisdiction>/<year>/<form>/pack.yaml``;
            the message lists the available form keys for that jurisdiction/year.
    """
    base = Path(base_dir) if base_dir is not None else _repo_formpacks_dir()
    path = base / jurisdiction / str(year) / form / "pack.yaml"
    if not path.is_file():
        available = sorted(s.form_key for s in list_forms(jurisdiction, year, base_dir=base_dir))
        raise FileNotFoundError(
            f"no form pack for form '{form}', {jurisdiction} {year} — looked for {path}. "
            f"Available form keys for {jurisdiction} {year}: {available or 'none'}. "
            f"Use list_forms() to discover packs."
        )
    pack = load_pack(path)
    return FormMap(
        form=pack.form,
        form_key=path.parent.name,
        jurisdiction=pack.jurisdiction,
        tax_year=pack.tax_year,
        source_url=pack.source_url,
        acroform_root=pack.acroform_root,
        lines=[
            LineMap(line=f.line, field=f.field, type=f.type, required=bool(f.required), group=f.group)
            for f in pack.fields
        ],
        relations=list(pack.relations),
        cross_form=list(pack.cross_form),
        identity_fields=list(pack.identity_fields),
    )
