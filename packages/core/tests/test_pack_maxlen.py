"""Phase J JEa — a pack's ``maxlen`` tracks its widget's own /MaxLen (formpacks/CONVENTIONS.md, "maxlen").

The filler enforces the PACK maxlen. A pack maxlen ABOVE the widget's /MaxLen lets a value through that the PDF then
silently truncates — the NY IT-203 2025 line-35 box held 4 characters under a pack maxlen of 10 until this gate.
A pack maxlen BELOW the widget's is a deliberate budget only when the printed box cannot hold the widget's count (a
one-character account cell with a DOR /MaxLen of 10); each such row is adjudicated below with the measured box, and
the table self-clears. A text line whose widget has a /MaxLen but whose pack declares none is left to verify's hard
MaxLen check. Network-marked like the ReadOnly sweeps: it reads each pinned blank (cache or download).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import read_text_widgets

FORMPACKS = Path(__file__).resolve().parents[3] / "formpacks"
PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))

# (pack, line) -> why the pack budget is tighter than the widget's /MaxLen. The box width and /DA font are the
# pinned blank's; "fits" is verify's clipping budget, width / (0.5 x font size).
TIGHTER_THAN_WIDGET: dict[tuple[str, str], str] = {
    **{(f"states/ar/{y}/ar1000f/pack.yaml", "direct_deposit_2.account.17"):
       "the 17th one-character account-number cell (14.6 pt at 9 pt, fits 3); cells 1-16 carry /MaxLen 1, this "
       "one the DOR's 10" for y in (2023, 2024, 2025)},
    ("states/id/2023/form40/pack.yaml", "preparer.state"): "31.5 pt at 10 pt fits 6; the widget says 10",
    ("states/ks/2023/k40/pack.yaml", "42.school_district_number"): "42 pt at 12 pt fits 6; the widget says 10",
    ("states/ks/2023/k40/pack.yaml", "43.historic_site_number"): "42 pt at 12 pt fits 6; the widget says 10",
    ("states/ma/2023/form1/pack.yaml", "43a"): "12.5 pt at 12 pt fits 2; the widget says 10",
    ("states/md/2023/md502/pack.yaml", "mailing_state"): "a two-letter state code (19.3 pt at 10 pt fits 3)",
    ("states/me/2023/f1040me/pack.yaml", "tax_period.begin.month"): "a two-digit month (25.7 pt at 10 pt fits 5)",
    ("states/me/2023/f1040me/pack.yaml", "tax_period.begin.day"): "a two-digit day (25.6 pt at 10 pt fits 5)",
    ("states/wv/2023/it140/pack.yaml", "name.suffix"): "a name suffix (JR / III); 25.5 pt at 10 pt fits 5",
}


def _key(pack_path: Path) -> str:
    return str(pack_path.relative_to(FORMPACKS))


def _widget_maxlens(pack_path: Path) -> tuple[object, dict[str, int]]:
    pack = load_pack(pack_path)
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    return pack, {w.name: w.max_len for w in read_text_widgets(Path(blank)) if w.max_len}


@pytest.mark.network
@pytest.mark.parametrize("pack_path", PACK_PATHS, ids=lambda p: _key(p).removesuffix("/pack.yaml").replace("/", "-"))
def test_pack_maxlen_never_exceeds_the_widget_and_tracks_it(pack_path: Path):
    pack, maxlens = _widget_maxlens(pack_path)
    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    over, tighter = [], []
    for f in pack.fields:
        widget = maxlens.get(prefix + f.field)
        if f.type == "checkbox" or f.maxlen is None or widget is None:
            continue
        if f.maxlen > widget:
            over.append(f"{f.line}: pack maxlen {f.maxlen} > widget /MaxLen {widget}")
        elif f.maxlen < widget and (_key(pack_path), f.line) not in TIGHTER_THAN_WIDGET:
            tighter.append(f"{f.line}: pack maxlen {f.maxlen} < widget /MaxLen {widget}")
    assert not over, f"{_key(pack_path)}: the PDF would clip what the filler lets through — set maxlen to the " \
                     f"widget's /MaxLen: {over}"
    assert not tighter, f"{_key(pack_path)}: set maxlen to the widget's /MaxLen, or adjudicate the budget in " \
                        f"TIGHTER_THAN_WIDGET with the measured box: {tighter}"


@pytest.mark.network
@pytest.mark.parametrize("row", sorted(TIGHTER_THAN_WIDGET), ids=lambda r: f"{r[0].removesuffix('/pack.yaml')}-{r[1]}")
def test_every_tighter_budget_row_is_still_tighter(row: tuple[str, str]):
    pack_path = FORMPACKS / row[0]
    assert pack_path.is_file(), f"TIGHTER_THAN_WIDGET names {row[0]}, which no longer exists — delete the row"
    pack, maxlens = _widget_maxlens(pack_path)
    field = next((f for f in pack.fields if f.line == row[1]), None)
    assert field is not None, f"{row}: the line is gone — delete the row"
    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    widget = maxlens.get(prefix + field.field)
    assert field.maxlen is not None and widget is not None and field.maxlen < widget, (
        f"{row}: no longer a tighter budget (pack {field.maxlen}, widget {widget}) — delete the row")
