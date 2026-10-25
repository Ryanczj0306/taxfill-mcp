"""Pack-blind anchoring: which printed line does each widget of a blank sit on? (Phase K JK15, 2026-10-24)

The no-pack fallback (ADR-0002) has only the blank PDF. This module reads the blank's own text layer and pairs
every AcroForm widget with the line-number token printed for its row and the caption beside or above it. It is
**blind**: it never imports a form pack, a pack schema or pack discovery, and never reads a ``pack.yaml``
(test_anchor.py fails on such an import). Its inputs are the PDF and, for the tier gate, the committed benchmark
table.

Signals, each recorded in a widget's ``evidence``:

- ``beside:<n>`` — a line-number token printed immediately left of the box on its row (the IRS amount-column
  number, Maine's ``21.``), or ``in_box:<n>`` at the box's own left edge. A number that follows caption words
  ("Add lines 1 through 9", "see page 12", "Form 940") is caption text, never a designator.
- ``gutter:<n>`` — the token that starts the row's caption in an aligned gutter column (``gutter_sub`` when the
  row prints only a letter, ``b.``, under a numbered head; ``gutter_head`` when the caption starts one printed line
  above the box). ``same_row_as:<field>`` — a second amount column on a row whose first box is anchored.
- ``tu_line:<n>`` / ``tu_other_line:<n>`` — the /TU tooltip (or, with no /TU, a ``Line16``-style field name)
  names the same / a different line; ``tu_words_other_row`` — the /TU (or a worded field name such as
  "1040ME Total tax") matches another row's caption better than its own (pitfall P-032's rotated names).
- ``ambiguous:<a>,<b>`` — two different designators on the row band.
- ``multi_column_row`` — the row band holds another fillable text box of a different field with no caption words
  between the two (amount columns: Delaware's Column A for the spouse and Column B for everyone else, each with
  "1." before it). A row designator does not identify a box on a multi-column row, so these boxes never reach the
  top tier, whether or not the neighbour got a line of its own.
- ``repeated_line:<n>`` — one designator is the line of two or more different fields' boxes on one page (Alabama
  40NR page 2 prints "2" once in each Part). Without its Part the designator does not identify the box, so these
  boxes never reach the top tier either.
- ``shared_row:<field>`` — the row-identification invariant failed (below) because of that other field's box.
- ``same_line:<field>`` — the one-to-one rule failed (below): that other field's box on the page also relates to
  the widget's designator.

The row-identification invariant (Phase K JK15 round 3, 2026-10-24). A printed designator names a ROW; a fill by
line number needs it to name a BOX. A widget may reach the top tier only when the designator identifies its box:

  (i)  no fillable text box (kind ``text``, ``choice`` or ``unknown``) of any other field shares its row band, or
  (ii) every fillable text box in that row band, the widget's own included, carries its own ``printed_line``, all
       of them distinct, and each read from the designator printed immediately before that box (``beside:<n>``
       evidence; a gutter number, a /TU or a field name alone does not count) — the 1040 "2a [box] b ... 2b [box]"
       layout.

Two boxes share a row band when their vertical extents overlap by at least half the shorter box's height. Any
other widget is capped at ``"med"`` (score at most CAP_SHARED_ROW, and :func:`tier_for` never gives the top tier to
a widget carrying a cap's evidence), with one ``shared_row:<field>`` entry per neighbour field. Caption words
between the two boxes do not lift the cap: Georgia 500 line 14 prints "Enter the number from Line 7c" and a count box
before the line-14 amount box, and the 1040-X line 23 prints a "(enter year)" box before its amount; the row's
designator names neither box alone. The caps above (``multi_column_row``, ``repeated_line``) still apply.

The one-to-one rule (Phase K JK15 round 4, 2026-10-24). The row band is not the only place a line's second box can
sit: Wisconsin Form 1 line 30 prints its qualifying-children count box on the designator's own printed line and the
line-30 amount box two printed lines lower, with "30" repeated beside it; Form 2555 lines 20b-23 print a description
box on the designator line and the amount box one line lower. The designator must map to ONE box on the page. A
widget keeps a top-tier score only when no fillable box of another field on the same page (kind ``text``,
``choice`` or ``unknown``: an unknown kind counts, failing closed)

  (a) carries the same ``printed_line``, at any score or tier (a capped or conflicting box is still a rival);
  (b) has that designator printed immediately before it (the nearest non-leader token left of the box in its own
      band, within BESIDE_GAP, or BESIDE_FAR after a dot leader, or a lone designator at the box's left edge), even
      when that box got no line (Wisconsin 2023 line 15a's credit box); or
  (c) names that line through its /TU or its ``Line16``-style field name (either one, even under a /TU that
      names no line: "L4_DATE1").

Known limits (the fourth review, 2026-10-24). A designator that a second schedule on the page prints again with no
box beside that copy is not a rival: Wisconsin Form 1 page 4 prints Schedule 1 lines 1-9 and Schedule 2 lines 1-8,
where Schedule 2's line 7 and Schedule 1's line 8 are preprinted rates, so ``sch1-7`` and ``sch2-8`` keep the top
tier. A widget hidden by its annotation flags (/F Hidden or NoView) is anchored like any other; the pack-less fill
(JK16) must refuse it. Text outside a page's crop box is read as if printed.

Any other widget with a printed_line is capped at ``"med"`` (score at most CAP_SAME_LINE; :func:`tier_for` never
gives the top tier to a widget carrying ``same_line:``), with one ``same_line:<field>`` entry per rival field. A
designator printed once per Part (``repeated_line``) is the same rule's case (a).

Option boxes (Phase K JK15b, 2026-10-25; docs/dev/JK19-PILOT.md D3 and D5). Checkbox and radio widgets get two passes
after every cap above, and they touch option boxes only, so no text widget's anchor moves:

- Their own caption (D3): a row that prints each option's caption right of its box ("1. [ ] Single 2. [ ] Married
  filing jointly") left every box but the first labelled with the previous option's caption. The row band's option
  boxes vote for the side whose caption sits closer (a tied band follows its last box; a caption ending "check here"
  keeps the left), and a box reading right takes the caption printed on its right (``label_right``), stopping at the
  next box, at the next option's designator and at a gap wider than a word space; a heading in large type is never
  a caption.
- Yes/No pairs (D5): a "Yes" box and a "No" box (by their own caption, or by a "Yes"/"No" column header straight
  above) side by side in one band or stacked in one column form a pair. A box with no printed_line takes its
  partner's (``pair_of:<field>``) or, when neither has one, the designator of the question above the pair
  (``pair_head:<line>``; it must stand in the gutter column of designators, where a single upper-case letter counts:
  Schedule H's A, B and C). Both boxes are labelled "Yes"/"No" and carry ``yes_no_pair:<partner field>``, a cap: one
  designator names two boxes, so neither reaches the top tier (score at most CAP_PAIR).

What was measured (method jk15-v5, TEST run 5, finalized 2026-10-25). The benchmark scores ``printed_line`` only:
its text numbers are those of jk15-v4 (scored top-tier text 1086/1086 after the blind adjudication, per-form rate
0/36, unscored sample 48/48), so the table passes and licenses the ``text`` group (jk15-v6, TEST run 6, the JK15b fix
wave: the same scored numbers and disagreements; the unscored sample redrew, 30 of its 48 awaiting verdicts); top-tier checkboxes measured 9/10,
below the 0.99 gate, so ``top_tier_kinds`` stays ``[text]`` and every option box caps at ``"med"``
(``top_kind_not_licensed:checkbox``). The labels are measured apart, in knowledge/anchor/labels.yaml
(scripts/anchor_label_check.py; a measurement that licenses nothing): an option box's label names its own option on
63.5% of the shipped packs' 3,196 named option boxes (14.1% under jk15-v4), 75.8% of Yes/No boxes (7.4%) and 82.3% of
filing-status boxes (5.7%). The JK19 pilot's blanks are held by test_anchor_jk19_pilot.py (network) and the synthetic
cases in test_anchor.py. A box still anchored ``"none"`` is refused by the pack-less fill, and its ``hand_write``
entry names the box by page and position (taxfill_core.unmapped).

Tiers (``confidence``), best first:

- ``"anchored (unverified line map)"`` — the top tier. The string ``"high"`` is never emitted: even a top-tier
  anchor is a measured guess about the printed row, not a verified line map, and every unmapped fill still needs
  the rendered-page vision check (KG6).
- ``"med"`` — fewer or weaker agreeing signals. Until the user sets a floor from the measured ``med`` precision,
  the fallback treats it like ``low``.
- ``"low"`` — a printed line or caption was found, but the signals conflict or are thin; the user confirms it.
- ``"none"`` — nothing printed could be associated with the box.

The tier thresholds are read from the committed benchmark table (``knowledge/anchor/benchmark.yaml``, written by
scripts/anchor_benchmark.py). With no table, or a table whose ``passed`` is false, nothing above ``"low"`` is
emitted; :func:`anchor_basis` says which. A field's confidence is the lowest of its widgets'.

Coordinates: every box is PDF user space, origin bottom-left, the frame ``overlay.locate_labels`` reports. On a
page whose text runs vertically the geometry is read in the text's own reading frame and reported back in user
space.
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from taxfill_core.datadir import data_root, home_display, knowledge_dir, user_path
from taxfill_core.packbuild import extract_fields

__all__ = [
    "TOP", "MED", "LOW", "NONE", "TIERS", "METHOD", "TextRun", "WidgetAnchor", "AnchorMap", "text_runs",
    "anchor_widgets", "anchor_basis", "load_table", "table_path", "normalize_line", "raw_anchors", "tier_for",
]

TOP = "anchored (unverified line map)"
MED = "med"
LOW = "low"
NONE = "none"
TIERS = (TOP, MED, LOW, NONE)  # best first
_RANK = {t: i for i, t in enumerate(TIERS)}

# The anchoring method's name; the benchmark table records which method it measured, and a table measured on a
# different method does not license tiers for this one.
# jk15-v2 (Phase K JK15, 2026-10-24): multi-column rows are capped by their neighbour box, not only by a shared line;
# a cents token (".00") separates a second column's designator; a designator repeated on one page is capped.
# jk15-v3 (Phase K JK15 round 3, 2026-10-24): the row-identification invariant (module doc) caps every widget whose
# row band holds another field's fillable text box, unless every such box has its own distinct beside designator.
# jk15-v4 (Phase K JK15 round 4, 2026-10-24): the one-to-one rule (module doc) caps a widget whose designator also
# relates to another field's fillable box anywhere on its page (same printed_line, the token printed before that box,
# or that box's /TU or name), so an auxiliary box on the designator's line no longer keeps the top tier.
# jk15-v5 (Phase K JK15b, 2026-10-25): option boxes (checkbox, radio) read their label from their own caption, on the
# right where the row prints captions right of their boxes (JK19 pilot D3), and the boxes of a Yes/No pair anchor to
# their question's designator labelled "Yes"/"No", capped below the top tier (D5); text widgets are unchanged.
# jk15-v6 (Phase K JK15b fix wave, 2026-10-25): a sub-letter row hangs from a joined lettered head above it ("47a"
# over "b" is 47b; it hung from the line before, "46b", and pair_of lent that to the "No" box at med); a capital word
# starting a sentence ("I authorize") is not a Yes/No pair's gutter letter; a pair's head keeps a flush sub-letter.
METHOD = "jk15-v6"
TABLE_RELPATH = Path("anchor") / "benchmark.yaml"

# ── signal weights (the method; the TIER thresholds live in the committed table) ──
W_BESIDE = 2.0
W_GUTTER = 2.0
W_BOTH_AGREE = 1.0       # beside and gutter name the same line
W_ALIGNED = 0.5          # the token stands in a column of designators
W_TU_SAME = 1.0
CAP_CONFLICT = 0.5       # a conflicting signal caps the score here (always below any top/med threshold)
CAP_MULTI_COLUMN = 2.0   # boxes sharing one printed row (amount columns) never reach the top tier
CAP_REPEATED_LINE = 2.0  # one designator on boxes of different fields on one page (one per Part) never does either
CAP_SHARED_ROW = 2.0     # a widget the row-identification invariant does not license (module doc) caps at med
CAP_SAME_LINE = 2.0      # a widget whose designator also relates to another field's box on the page caps at med
CAP_PAIR = 2.0           # the two boxes of a Yes/No pair share their question's designator: never the top tier
# option boxes (Phase K JK15b, 2026-10-25): their label is read from their own caption, and Yes/No pairs anchor together
_OPTION_KINDS = frozenset({"checkbox", "radio"})
OPTION_GAP = 10.0        # pt: an option's caption starts this close to its box (or OPTION_GAP_H font heights)
OPTION_GAP_H = 1.5
OPTION_WORD_GAP_H = 0.8  # font heights: a wider gap inside a caption starts the next caption
PAIR_SIDE_GAP = 150.0    # pt: furthest apart the two boxes of a side-by-side Yes/No pair may stand
PAIR_STACK_GAP = 48.0    # pt: furthest apart (centre to centre) the two boxes of a stacked Yes/No pair may stand
PAIR_X_TOL = 3.0         # pt: the left edges of a stacked pair agree this closely
PAIR_HEAD_ROWS = 4.5     # font heights: furthest above the pair's top box its question's designator may stand
PAIR_LETTER_GAP_H = 0.6  # font heights: a bare capital letter followed this closely is a word ("I"), not a gutter
_YES_NO = {"yes": "Yes", "no": "No"}
_CHECK_HERE = {"here", "check"}
OPTION_TALL = 1.8        # a word this many times the page's median font height is a heading, never an option caption
_UPPER = re.compile(r"^[A-Z]\.?$")
# the fillable boxes the invariant and the one-to-one rule count; "unknown" (no /FT) counts too, failing closed
_ENTRY_KINDS = frozenset({"text", "choice", "unknown"})
# evidence that keeps a widget below the top tier
_NEVER_TOP = ("multi_column_row", "repeated_line:", "shared_row:", "same_line:", "yes_no_pair:")
BESIDE_GAP = 30.0        # pt: furthest a "beside" token's right edge may sit from the box
_ALIGN_TOL = 1.6         # pt: two designators share a column when x0 or x1 agree this closely
_MIN_COLUMN = 3          # designators that make a column (the token itself included)


# ── text runs ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TextRun:
    """One printed word on a page: its text and tight box in PDF user space (origin bottom-left)."""

    page: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class _Word:
    text: str
    x0: float   # reading frame (equal to user space on an upright page)
    y0: float
    x1: float
    y1: float
    h: float    # loose (font) height
    run: TextRun

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def _rotate(q: int, x: float, y: float) -> tuple[float, float]:
    """User space -> the reading frame of text whose baseline runs at q * 90 degrees."""
    if q == 1:
        return y, -x
    if q == 2:
        return -x, -y
    if q == 3:
        return -y, x
    return x, y


def _rotate_box(q: int, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    a = _rotate(q, x0, y0)
    b = _rotate(q, x1, y1)
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def _page_words(page: pdfium.PdfPage, page_no: int) -> tuple[list[_Word], int]:
    """Every word on the page in its dominant reading frame, and that frame's quarter-turn ``q``."""
    tp = page.get_textpage()
    try:
        chars = []
        for i in range(tp.count_chars()):
            if pdfium_c.FPDFText_IsGenerated(tp.raw, i) == 1:
                continue
            ch = chr(pdfium_c.FPDFText_GetUnicode(tp.raw, i))
            angle = pdfium_c.FPDFText_GetCharAngle(tp.raw, i)
            # pdfium measures the angle clockwise; q counts counter-clockwise quarter turns of the baseline
            q = (-int(round(math.degrees(angle) / 90.0))) % 4 if angle >= 0 else 0
            obj = pdfium_c.FPDFText_GetTextObject(tp.raw, i)
            chars.append((ch, q, tp.get_charbox(i, loose=True), tp.get_charbox(i),
                          ctypes.cast(obj, ctypes.c_void_p).value if obj else None))
    finally:
        tp.close()
    chars = _drop_shadow_objects(chars)
    letters = Counter(q for ch, q, *_ in chars if ch.strip())
    if not letters:
        return [], 0
    dominant = letters.most_common(1)[0][0]
    placed = []
    for ch, q, loose, tight, _ in chars:
        if q != dominant:
            continue
        lx0, ly0, lx1, ly1 = _rotate_box(q, *loose)
        placed.append((ch, lx0, ly0, lx1, ly1, tight))
    placed = _dedupe(placed)
    # rows: chars whose loose centres agree within 30% of the taller
    placed.sort(key=lambda c: -(c[2] + c[4]) / 2)
    rows: list[list] = []
    ref_cy = ref_h = None
    for c in placed:
        cy, h = (c[2] + c[4]) / 2, c[4] - c[2]
        if rows and abs(ref_cy - cy) <= 0.3 * max(h, ref_h):
            rows[-1].append(c)
        else:
            rows.append([c])
            ref_cy, ref_h = cy, h
    words: list[_Word] = []
    for row in rows:
        cur: list = []
        for c in sorted(row, key=lambda c: c[1]):
            if not c[0].strip():
                _flush(cur, words, page_no)
                cur = []
                continue
            if cur and c[0] == cur[-1][0] and _overlap_x(c, cur[-1]) > 0.5:
                continue  # the same glyph drawn twice, offset (a fake-bold face: "1100" for "10")
            if cur and c[1] - max(x[3] for x in cur) > 0.15 * max(c[4] - c[2], 1.0):
                _flush(cur, words, page_no)
                cur = []
            cur.append(c)
        _flush(cur, words, page_no)
    return words, dominant


def _flush(cur: list, words: list[_Word], page_no: int) -> None:
    """Close a word; dot leaders glued to it ("payments.)......25b.") become their own word."""
    if not cur:
        return
    text = "".join(c[0] for c in cur)
    if len(cur) > 3:
        parts = [m.span() for m in re.finditer(r"[.·…_]{3,}", text)]
        if parts and parts != [(0, len(text))]:
            start = 0
            for a, b in parts:
                if a > start:
                    _emit(cur[start:a], words, page_no)
                _emit(cur[a:b], words, page_no)
                start = b
            if start < len(cur):
                _emit(cur[start:], words, page_no)
            return
    _emit(cur, words, page_no)


def _drop_shadow_objects(chars: list) -> list:
    """Drop a text object whose glyphs repeat an earlier object's, each within a few points (a drop-shadow face).

    North Dakota's ND-1 draws every caption twice, the copy shifted about 3 pt, so a plain reading gives
    "Federall adjjustted" and "1004400" for "1040".
    """
    objs: dict[int, list] = {}
    for c in chars:
        if c[4] is not None and c[0].strip():
            objs.setdefault(c[4], []).append(c)
    boxes = {}
    for key, cs in objs.items():
        boxes[key] = (min(c[2][0] for c in cs), min(c[2][1] for c in cs), max(c[2][2] for c in cs),
                      max(c[2][3] for c in cs))
    keys = sorted(objs, key=lambda k: boxes[k][0])
    drop: set[int] = set()
    for i, ka in enumerate(keys):
        if ka in drop or len(objs[ka]) < 3:
            continue
        a = boxes[ka]
        index: dict[str, list] = {}
        for c in objs[ka]:
            index.setdefault(c[0], []).append(c[2])
        for kb in keys[i + 1:]:
            b = boxes[kb]
            if b[0] > a[0] + 6.0:
                break
            if kb in drop or abs(len(objs[kb]) - len(objs[ka])) > 2 or abs(b[1] - a[1]) > 2.0:
                continue
            hits = sum(1 for c in objs[kb] if any(abs(c[2][0] - o[0]) < 4.0 and abs(c[2][1] - o[1]) < 1.0
                                                  for o in index.get(c[0], ())))
            if hits >= 0.9 * min(len(objs[kb]), len(objs[ka])):
                drop.add(kb)
    return [c for c in chars if c[4] not in drop] if drop else chars


def _dedupe(placed: list) -> list:
    """Drop a glyph drawn a second time over itself, slightly offset (a fake-bold or shadowed face prints "1100" for
    "10")."""
    grid: dict[tuple, list] = {}
    out = []
    for c in placed:
        if not c[0].strip():
            out.append(c)
            continue
        gx, gy = int(c[1] // 3), int(c[2] // 3)
        dup = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid.get((c[0], gx + dx, gy + dy), ()):
                    w = min(c[3] - c[1], o[3] - o[1])
                    hgt = min(c[4] - c[2], o[4] - o[2])
                    # the copy sits less than 3/4 of a glyph away; a real double letter ("ll") sits one width away
                    if w > 0 and hgt > 0 and abs(c[1] - o[1]) < 0.75 * w and abs(c[2] - o[2]) < 0.25 * hgt:
                        dup = True
        if not dup:
            grid.setdefault((c[0], gx, gy), []).append(c)
            out.append(c)
    return out


def _overlap_x(a: tuple, b: tuple) -> float:
    width = min(a[3] - a[1], b[3] - b[1])
    return (min(a[3], b[3]) - max(a[1], b[1])) / width if width > 0 else 0.0


_GLUED = re.compile(r"^(\(?\d{1,3}[a-z]?\)?[.:])(?=[A-Z(])")


def _emit(cur: list, words: list[_Word], page_no: int) -> None:
    text = "".join(c[0] for c in cur)
    m = _GLUED.match(text)
    if m and len(text) > m.end():
        # "7a.Amount from line 7": a designator printed with no space before its caption
        _emit(cur[:m.end()], words, page_no)
        _emit(cur[m.end():], words, page_no)
        return
    tx0 = min(c[5][0] for c in cur)
    ty0 = min(c[5][1] for c in cur)
    tx1 = max(c[5][2] for c in cur)
    ty1 = max(c[5][3] for c in cur)
    run = TextRun(page=page_no, text=text, x0=round(tx0, 2), y0=round(ty0, 2), x1=round(tx1, 2), y1=round(ty1, 2))
    words.append(_Word(
        text=text, x0=min(c[1] for c in cur), y0=min(c[2] for c in cur), x1=max(c[3] for c in cur),
        y1=max(c[4] for c in cur), h=max(c[4] - c[2] for c in cur), run=run,
    ))


def _open(pdf_path: str | Path) -> pdfium.PdfDocument:
    path = user_path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"no PDF at {home_display(path)} — pass the blank PDF fetched from the form's source_url")
    try:
        return pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        raise ValueError(f"{home_display(path)} could not be opened as a PDF ({exc}) — pass the official blank") from exc


def text_runs(pdf_path: str | Path) -> list[TextRun]:
    """Every printed word on every page with its box (page, text, x0, y0, x1, y1; user space, origin bottom-left).

    Words are split at spaces and at gaps wider than 15% of the font height, so "1" and "a" printed apart ("1 a
    Total amount") are two runs. A page with no text layer (a scanned image) contributes nothing.
    """
    doc = _open(pdf_path)
    try:
        out: list[TextRun] = []
        for index in range(len(doc)):
            words, _ = _page_words(doc[index], index + 1)
            out.extend(sorted((w.run for w in words), key=lambda r: (-r.y1, r.x0)))
        return out
    finally:
        doc.close()


# ── tokens ───────────────────────────────────────────────────────────────────

_DESIGNATOR = re.compile(r"^[.·•]?\(?(\d{1,3})([a-zA-Z])?\)?[.:]?$")
_SUBLETTER = re.compile(r"^\(?([a-z])\)?[.:]?$")
_LEADER = re.compile(r"^[.·…_\-–—•]+$")
_SKIP_BESIDE = {"$", ":", "|", "►", "▶", "→", "=", "-", "–", "•"}
# Printed between a caption and its designator without making the number caption text ("x $700 = 2c").
_SEPARATORS = {"=", "►", "▶", "→", "•", "|", ":", "$"}
# Words that may stand between two boxes of one row without naming a line: "X $153 =", "x 6%", "÷ 2 =".
# The cents printed after an amount box (".00", "00") end that box, not a caption (Phase K JK15, 2026-10-24).
_CENTS = re.compile(r"^[.,]?0{2}$")
# A caption word: two letters running (a designator's sub-letter "a." or an arithmetic "x" is not one).
_CAPTION_WORD = re.compile(r"[A-Za-z]{2,}")
_ARITHMETIC = re.compile(r"^(?:[xX×÷*+=/]|\$?[\d,]*\.?\d+%?|\(?\.\d+\)?|\$)$")
BESIDE_FAR = 90.0        # pt: a designator right after a dot leader may stand this far from its box (Ohio)
# A number right after one of these words is caption text ("lines 1 through 9", "see page 12", "Form 940").
_REFERENCE_WORDS = {
    "line", "lines", "ln", "page", "pages", "pg", "form", "forms", "schedule", "sch", "sched", "part", "parts",
    "box", "boxes", "column", "col", "step", "worksheet", "ws", "pub", "publication", "section", "sec", "through",
    "thru", "and", "or", "to", "plus", "minus", "from", "of", "times", "x", "×", "less", "than", "by", "item",
    "items", "code", "question", "chapter", "rev", "article", "act", "irc", "§", "under", "over", "age", "ages",
    "&", "+", "/", "per", "on", "in", "at", "if", "is", "see", "enter", "add", "subtract", "multiply", "divide",
    "use", "attach", "include", "with", "w-2", "1099", "tax", "year", "years", "months", "month", "days", "day",
}
_STOP = {
    "the", "and", "for", "from", "with", "your", "you", "this", "that", "line", "lines", "enter", "amount", "see",
    "instructions", "form", "schedule", "here", "not", "are", "any", "all", "add", "subtract", "minus", "plus",
    "attach", "only", "less", "more", "than", "into", "each", "other", "page", "box", "boxes", "check", "yes", "text",
    "field", "if", "of", "or", "to", "on", "in", "is", "be", "a", "an", "as", "by", "it",
}


def _line_key(line: str) -> tuple[int, str]:
    m = re.match(r"^(\d+)(.*)$", line)
    return (int(m.group(1)), m.group(2)) if m else (10**6, line)


def normalize_line(token: str) -> str | None:
    """A printed line designator normalised like "21" or "5a" ("21.", "(5a)", "05A:" too); else None."""
    m = _DESIGNATOR.match(token.strip())
    if not m:
        return None
    number = int(m.group(1))
    if number == 0:
        return None
    return f"{number}{(m.group(2) or '').lower()}"


def _is_leader(text: str) -> bool:
    return bool(_LEADER.match(text)) or _is_symbol(text)


def _is_symbol(text: str) -> bool:
    """Private-use glyphs (dingbat arrows and boxes a font maps outside Unicode's letters)."""
    return bool(text) and all(0xE000 <= ord(ch) <= 0xF8FF for ch in text)


_TU_LINE = (
    re.compile(r"^\s*(?:line|ln|l)\s*[.#:-]?\s*(\d{1,3})([a-z](?![a-z]))?(?!\d)", re.I),
    re.compile(r"^\s*\(?(\d{1,3})([a-z])?\)?(?:[.):]\s*|\s+)(?=[A-Za-z(])", re.I),
)
_NAME_LINE = re.compile(r"^(?:line|ln|l)[_\s.-]?(\d{1,3})([a-z](?![a-z]))?(?!\d)", re.I)


def _tu_line(text: str | None) -> str | None:
    if not text:
        return None
    for pattern in _TU_LINE:
        m = pattern.match(text)
        if m:
            n = int(m.group(1))
            return f"{n}{(m.group(2) or '').lower()}" if n else None
    return None


def _leaf(name: str) -> str:
    return re.sub(r"\[\d+\]", "", name.rsplit(".", 1)[-1]).strip()


def _name_line(name: str) -> str | None:
    m = _NAME_LINE.match(_leaf(name))
    if not m:
        return None
    n = int(m.group(1))
    return f"{n}{(m.group(2) or '').lower()}" if n else None


def _content_words(text: str) -> set[str]:
    out = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z'-]*", text or ""):
        w = raw.lower().strip("'-")
        if len(w) < 3 or w in _STOP:
            continue
        if w.endswith("s") and len(w) > 3:
            w = w[:-1]
        out.add(w)
    return out


def _name_words(name: str) -> set[str]:
    """Content words of a worded field name ("1040ME Total tax"); a coded name (f1_47, Line16) has none."""
    leaf = _leaf(name)
    if not re.search(r"[A-Za-z]{3,}[\s_]+[A-Za-z]{3,}", leaf):
        return set()
    return _content_words(re.sub(r"[_]+", " ", leaf))


# ── widgets ──────────────────────────────────────────────────────────────────


@dataclass
class WidgetAnchor:
    """One widget's anchor. ``rect`` is the widget's /Rect (user space); ``printed_line`` is the designator
    printed for its row ("21", "5a") or None; ``label`` the nearest printed caption; ``score`` the method's
    signal sum, which the committed table's thresholds turn into ``confidence``."""

    field: str
    widget_index: int
    page: int
    rect: list[float]
    kind: str
    printed_line: str | None = None
    label: str | None = None
    confidence: str = NONE
    evidence: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class AnchorMap:
    widgets: list[WidgetAnchor]
    fields: dict[str, str]          # field -> its lowest widget confidence
    basis: dict


@dataclass
class _Box:
    info: dict
    index: int
    x0: float
    y0: float
    x1: float
    y1: float
    anchor: WidgetAnchor | None = None

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def _in_band(w: _Word, b: _Box) -> bool:
    return abs(w.cy - b.cy) <= max(b.h, w.h) / 2 + 1.0


def _columns(words: list[_Word]) -> tuple[list[_Word], set[int]]:
    """Segment-leading designators and the ids of those standing in a column of >= _MIN_COLUMN."""
    buckets: dict[int, list[_Word]] = {}
    for w in words:
        buckets.setdefault(int(w.cy // 4), []).append(w)
    lead: list[_Word] = []
    for w in words:
        if normalize_line(w.text) is None and not _SUBLETTER.match(w.text):
            continue
        k = int(w.cy // 4)
        near = [o for j in (k - 1, k, k + 1) for o in buckets.get(j, ())]
        prev = [o for o in near if o is not w and abs(o.cy - w.cy) <= 0.3 * max(o.h, w.h)
                and o.x1 <= w.x0 + 0.5 and w.x0 - o.x1 < 2.0 * w.h and not _is_leader(o.text)]
        if not prev:
            lead.append(w)
    aligned: set[int] = set()
    for w in lead:
        same = sum(1 for o in lead if abs(o.x0 - w.x0) <= _ALIGN_TOL or abs(o.x1 - w.x1) <= _ALIGN_TOL)
        if same >= _MIN_COLUMN:
            aligned.add(id(w))
    return lead, aligned


def _after_leader(w: _Word, seg: list[_Word]) -> bool:
    before = [o for o in seg if o.x1 <= w.x0 + 0.5 and o is not w]
    return bool(before) and _is_leader(max(before, key=lambda o: o.x1).text) and bool(normalize_line(w.text))


def _beside_ok(w: _Word, seg: list[_Word]) -> bool:
    """A beside token is a designator only when it does not continue caption text."""
    before = [o for o in seg if o.x1 <= w.x0 + 0.5 and o is not w]
    if not before:
        return True
    prev = max(before, key=lambda o: o.x1)
    if _is_leader(prev.text) or prev.text in _SEPARATORS or _is_symbol(prev.text) or _CENTS.match(prev.text):
        return True  # ".00" closes the column to the left; the "1." after it is the next column's own designator
    if prev.text.lower().strip(".,:;()") in _REFERENCE_WORDS or prev.text.endswith(","):
        return False
    return w.x0 - prev.x1 >= 1.0 * w.h


def _label(words: list[str]) -> str | None:
    text = " ".join(t for t in words if not _is_leader(t)).strip()
    text = re.sub(r"\s*\.{2,}\s*", " ", text).strip(" .")
    return text[:160] or None


def _near_chunk(seg: list[_Word], b: _Box, beside_word: _Word | None = None) -> list[_Word]:
    """The words contiguous with the box (or with its beside designator), walking left until a gap wider than four
    font heights (a column break)."""
    chunk: list[_Word] = [beside_word] if beside_word is not None else []
    edge = beside_word.x0 if beside_word is not None else b.x0
    seg = [w for w in seg if w is not beside_word]
    for w in sorted(seg, key=lambda w: -w.x1):
        if edge - w.x1 > max(4.0 * w.h, 30.0):
            break
        chunk.append(w)
        edge = min(edge, w.x0)
    return sorted(chunk, key=lambda w: w.x0)


def _sub(w: _Word | None) -> str | None:
    m = _SUBLETTER.match(w.text) if w is not None else None
    return m.group(1) if m else None


def _row_head(body: list[_Word], beside_word: _Word | None, b: _Box, words: list[_Word], lead_ids: set[int],
              aligned: set[int], boxes: list[_Box], left: float) -> tuple[str | None, str, float, list[_Word]]:
    """The designator that starts the row's caption: (line, evidence kind, score, head-line words)."""
    if not body or body[0] is beside_word:
        return None, "", 0.0, []
    # margin text left of the gutter ("Income", "Attach Form(s) W-2 here") is not the row's start
    for k, w in enumerate(body[1:3], 1):
        if id(w) in aligned and w is not beside_word and id(body[0]) not in aligned:
            body = body[k:]
            break
    first = body[0]
    line = normalize_line(first.text)
    if line is not None and id(first) in lead_ids:
        nxt = body[1] if len(body) > 1 else None
        if (nxt is not None and line.isdigit() and _sub(nxt) and nxt.x0 - first.x1 < 1.5 * first.h
                and nxt is not beside_word):
            line += _sub(nxt)
        if id(first) in aligned:
            return line, "gutter", W_GUTTER + W_ALIGNED, []
        return line, "gutter_unaligned", W_GUTTER - 0.5, []
    if _sub(first):
        # "b. Household employee wages": the letter hangs from the numbered head above; never the bare head
        parent = _parent_above(first, words, lead_ids, left)
        if parent is None:
            return None, "", 0.0, []
        if id(first) in aligned:
            return parent + _sub(first), "gutter_sub", W_GUTTER, []
        return parent + _sub(first), "gutter_sub_unaligned", W_GUTTER - 0.5, []
    if line is None:
        head = _head_above(first, b, words, lead_ids, aligned, boxes, left)
        if head is not None:
            head_words = [w for w in words if abs(w.cy - head.cy) <= 0.3 * head.h and w.x0 >= head.x1
                          and w.x1 <= b.x0]
            return normalize_line(head.text), "gutter_head", W_GUTTER - 0.5, head_words
    return None, "", 0.0, []


def _anchor_page(words: list[_Word], boxes: list[_Box], q: int) -> None:
    lead, aligned = _columns(words)
    lead_ids = {id(w) for w in lead}
    caption_of: dict[int, set[str]] = {}

    def seg_of(b: _Box) -> tuple[list[_Word], float, _Box | None]:
        left, left_box = -1e9, None
        for o in boxes:
            if o is b or o.x1 > b.x0 + 1.0:
                continue
            overlap = min(o.y1, b.y1) - max(o.y0, b.y0)
            if overlap >= 0.5 * min(o.h, b.h) and o.x1 > left:
                left, left_box = o.x1, o
        seg = sorted((w for w in words if _in_band(w, b) and w.x0 >= left - 1.0 and w.x1 <= b.x0 + 2.0),
                     key=lambda w: w.x0)
        return seg, left, left_box

    for b in sorted(boxes, key=lambda b: (b.x0, -b.y1)):
        a = b.anchor
        assert a is not None
        seg, left, left_box = seg_of(b)
        ev = a.evidence
        score = 0.0
        beside = beside_word = None
        # beside: the nearest token left of the box
        cands = [w for w in seg if not _is_leader(w.text) and w.text not in _SKIP_BESIDE]
        near = max(cands, key=lambda w: w.x1) if cands else None
        reach = BESIDE_GAP
        if near is not None and BESIDE_GAP < b.x0 - near.x1 <= BESIDE_FAR and (
                _after_leader(near, seg) or (id(near) in aligned and normalize_line(near.text))):
            reach = BESIDE_FAR  # a designator column standing apart from boxes of varying width (Louisiana)
        if near is not None and b.x0 - near.x1 <= reach and _beside_ok(near, seg):
            if normalize_line(near.text):
                beside, beside_word = normalize_line(near.text), near
                ev.append(f"beside:{beside}")
                score += W_BESIDE + (W_ALIGNED if _aligned_beside(near, words, boxes) else 0.0)
            elif _sub(near) and near is not (cands[0] if cands else None):
                pass  # a letter after caption words ("dependents: a.") is handled below, as a column letter
        if beside is None and near is not None and _sub(near) and b.x0 - near.x1 <= BESIDE_GAP:
            # "a [box]": a lettered entry; its number is the head above it, or the left box's row number
            parent = None
            run = [w for w in _near_chunk([w for w in seg if w.x1 <= near.x0 + 0.5], b, near) if not _is_leader(w.text)]
            row_first = run[0] if run else None
            if (row_first is not None and row_first is not near and id(row_first) in aligned
                    and (normalize_line(row_first.text) or "").isdigit()):
                parent = normalize_line(row_first.text)
                kind = "row_letter"
            elif left_box is not None and left_box.anchor and left_box.anchor.printed_line:
                parent = re.sub(r"[a-z]$", "", left_box.anchor.printed_line)
                kind = "column_letter"
            else:
                parent = _parent_above(near, words, lead_ids, left)
                kind = "beside_sub"
            if parent:
                beside, beside_word = parent + _sub(near), near
                ev.append(f"{kind}:{beside}")
                score += W_BESIDE - 0.5
        if beside is None:
            inside = sorted((w for w in words if _in_band(w, b) and b.x0 - 1.0 <= w.x0 < b.x0 + min(30.0, 0.35 * (b.x1 - b.x0))
                             and w.x1 <= b.x1), key=lambda w: w.x0)
            if inside and normalize_line(inside[0].text) and len(inside) == 1:
                beside, beside_word = normalize_line(inside[0].text), inside[0]
                ev.append(f"in_box:{beside}")
                score += W_BESIDE
        # gutter: the designator that starts the row's caption, contiguous with the box (or across a column gap)
        body = [w for w in seg if not _is_leader(w.text)]
        edge_seg = [w for w in seg if beside_word is None or w.x1 <= beside_word.x0 + 0.5 or w is beside_word]
        chunk = [w for w in _near_chunk(edge_seg, b, beside_word) if not _is_leader(w.text)]
        gutter, kind, g_score, head_words = _row_head(chunk, beside_word, b, words, lead_ids, aligned, boxes, left)
        far = False
        lone_letter = beside is None and near is not None and _sub(near) is not None and b.x0 - near.x1 <= BESIDE_GAP
        if gutter is None and chunk and body and body[0] is not chunk[0] and not lone_letter:
            gutter, kind, g_score, head_words = _row_head(body, beside_word, b, words, lead_ids, aligned, boxes, left)
            far = gutter is not None
        printed = beside or gutter
        if gutter:
            if far:
                # a designator across a column gap only confirms; it never stands or conflicts alone
                if beside == gutter:
                    ev.append(f"{kind}_far:{gutter}")
                    score += W_BOTH_AGREE
                elif beside is None:
                    ev.append(f"{kind}_far:{gutter}")
                    score += 1.0
                else:
                    ev.append(f"far_other:{gutter}")
                    gutter = None
            else:
                ev.append(f"{kind}:{gutter}")
                score += g_score
                if beside and beside != gutter:
                    if beside[-1].isalpha() and beside[:-1] == gutter:
                        ev.append(f"head_of:{gutter}")  # "25. TAX PAYMENTS / a. ... 25a." — the head, not a rival
                        score -= g_score
                    else:
                        ev.append(f"ambiguous:{','.join(sorted({beside, gutter}, key=_line_key))}")
                        score = min(score, CAP_CONFLICT)
                elif beside:
                    score += W_BOTH_AGREE
        # another aligned designator inside the near chunk is a rival
        rivals = {normalize_line(w.text) for w in chunk if id(w) in aligned and normalize_line(w.text)}
        rivals -= {x for x in (beside, gutter) if x}
        rivals -= {re.sub(r"[a-z]$", "", x) for x in (beside, gutter) if x}
        if rivals and printed:
            ev.append(f"ambiguous:{','.join(sorted(rivals | {printed}, key=_line_key))}")
            score = min(score, CAP_CONFLICT)
        # a second amount column on an anchored row, with nothing printed between the two boxes
        if printed is None and left_box is not None and left_box.anchor and left_box.anchor.printed_line:
            if all(_is_leader(w.text) or w.text in _SKIP_BESIDE or _ARITHMETIC.match(w.text) for w in seg):
                printed = left_box.anchor.printed_line
                ev.append(f"same_row_as:{left_box.info['name']}")
                # several boxes share the row's number: the line alone does not say which box (a column does)
                score = min(left_box.anchor.score, CAP_MULTI_COLUMN)
                if "multi_column_row" not in left_box.anchor.evidence:
                    left_box.anchor.evidence.append("multi_column_row")
                    left_box.anchor.score = min(left_box.anchor.score, CAP_MULTI_COLUMN)
        # caption
        ordered = sorted((w for w in body if w is not beside_word), key=lambda w: (-round(w.cy / (0.6 * w.h)), w.x0))
        if ordered and normalize_line(ordered[0].text):
            ordered = ordered[1:]
        caption_words = [w.text for w in sorted(head_words, key=lambda w: w.x0)] + [w.text for w in ordered]
        a.label = _label(caption_words) or _label_above(b, words)
        caption_of[id(b)] = _content_words(" ".join(caption_words))
        # /TU (or a Line16-style name) naming a line
        tip = b.info.get("tooltip")
        named_line = _tu_line(tip) or (None if tip else _name_line(b.info["name"]))
        if named_line and printed:
            if named_line == printed:
                ev.append(f"tu_line:{named_line}")
                score += W_TU_SAME
            else:
                ev.append(f"tu_other_line:{named_line}")
                score = min(score, CAP_CONFLICT)
        elif named_line:
            ev.append(f"tu_names:{named_line}")
        a.printed_line = printed
        a.score = round(score, 3)
    # boxes of different fields on one row that share its printed number: the number alone does not pick the box
    for b in boxes:
        a = b.anchor
        if not a.printed_line or "multi_column_row" in a.evidence:
            continue
        for o in boxes:
            if (o is b or o.info["name"] == b.info["name"] or o.anchor.printed_line != a.printed_line
                    or min(o.y1, b.y1) - max(o.y0, b.y0) < 0.5 * min(o.h, b.h)):
                continue
            for x in (a, o.anchor):
                if "multi_column_row" not in x.evidence:
                    x.evidence.append("multi_column_row")
                x.score = min(x.score, CAP_MULTI_COLUMN)
    _cap_multi_column_rows(words, boxes)
    # /TU words (or a worded name) against the captions of the neighbouring rows
    for b in boxes:
        a = b.anchor
        tip = b.info.get("tooltip")
        tu_words = _content_words(tip) if tip else _name_words(b.info["name"])
        if len(tu_words) < 2 or not a.printed_line:
            continue
        own = len(tu_words & caption_of.get(id(b), set())) / len(tu_words)
        best = 0.0
        for o in boxes:
            if o is b or abs(o.cy - b.cy) > 80 or min(o.x1, b.x1) - max(o.x0, b.x0) <= 0:
                continue
            if o.anchor.printed_line == a.printed_line:
                continue
            best = max(best, len(tu_words & caption_of.get(id(o), set())) / len(tu_words))
        if best >= 0.99 and own < best:
            a.evidence.append("tu_words_other_row")
            a.score = min(a.score, CAP_CONFLICT)
        elif own >= 0.5:
            a.evidence.append("tu_words_same_row")
    _cap_repeated_lines(boxes)
    _cap_shared_rows(boxes)
    _cap_same_lines(words, boxes)
    # Phase K JK15b (2026-10-25): option boxes only, after every cap, so no text widget's anchor can move
    _option_labels(words, boxes)
    _pair_yes_no(words, boxes)


# ── option boxes: their own caption, and Yes/No pairs (Phase K JK15b, 2026-10-25) ──


def _is_option(b: _Box) -> bool:
    return b.info["kind"] in _OPTION_KINDS


def _right_caption(b: _Box, words: list[_Word], boxes: list[_Box]) -> tuple[float, list[_Word]]:
    """The caption printed right of an option box ("[ ] Single"): (the gap to its first word, its words), or (inf, [])
    when no word in the box's band starts within OPTION_GAP of it. A caption wrapped over two printed lines beside one
    box ("[ ] Yes—Stop! / Go to line 31") is read top line first. Each line stops at the next box of the row band, at
    a gap wider than OPTION_WORD_GAP_H font heights, and at a designator printed before the next box ("[ ] Single
    2. [ ]"); a number that is not one starts a caption ("[ ] 65 or older"). A word set over OPTION_TALL times the
    page's median font height is a heading, not a caption (Louisiana IT-540's "2025 LOUISIANA RESIDENT" title beside
    its name-change box)."""
    stop = min((o.x0 for o in boxes if o is not b and _same_band(o, b) and o.x0 >= b.x1 - 1.0), default=math.inf)
    starts = [o.x0 for o in boxes if o is not b and _same_band(o, b) and o.x0 >= b.x1 - 1.0]
    tall = OPTION_TALL * _median_height(words)
    row = [w for w in words if _in_band(w, b) and w.x0 >= b.x1 - 1.0 and w.x1 <= stop + 1.0 and w.h <= tall]

    def next_designator(w: _Word) -> bool:
        return bool(normalize_line(w.text)) and any(0 <= x - w.x1 <= BESIDE_GAP for x in starts)

    out: list[_Word] = []
    gap = math.inf
    seen: set[int] = set()
    for first in sorted(row, key=lambda w: (-w.cy, w.x0)):
        if id(first) in seen:
            continue
        line = sorted((w for w in row if abs(w.cy - first.cy) <= 0.3 * max(w.h, first.h)), key=lambda w: w.x0)
        seen |= {id(w) for w in line}
        head = line[0]
        if (head.x0 - b.x1 > max(OPTION_GAP_H * head.h, OPTION_GAP) or _is_leader(head.text)
                or not re.search(r"[A-Za-z0-9]", head.text) or next_designator(head)):
            continue
        gap = min(gap, head.x0 - b.x1)
        out.append(head)
        edge = head.x1
        for w in line[1:]:
            if w.x0 - edge > max(OPTION_WORD_GAP_H * w.h, 4.0):
                break  # wider than a word space: the next caption ("[ ] Blind   Your spouse was:")
            if next_designator(w):
                break  # the next option's own designator ("[ ] Single  2. [ ]")
            out.append(w)
            edge = w.x1
    return gap, out


def _median_height(words: list[_Word]) -> float:
    hs = sorted(w.h for w in words)
    return hs[len(hs) // 2] if hs else 0.0


def _left_gap(b: _Box, words: list[_Word], boxes: list[_Box]) -> tuple[float, _Word | None]:
    """The gap from the nearest caption word left of an option box (a designator, a leader or a separator is not a
    caption) back to the box, and that word; (inf, None) when the band holds none before the box to its left. A
    caption ending "check here" (a letter or a designator may follow) points at the box: its gap counts as -inf."""
    left = max((o.x1 for o in boxes if o is not b and _same_band(o, b) and o.x1 <= b.x0 + 1.0), default=-math.inf)
    cands = [w for w in words if _in_band(w, b) and w.x1 <= b.x0 + 1.0 and w.x0 >= left - 1.0
             and not _is_leader(w.text) and w.text not in _SKIP_BESIDE and not normalize_line(w.text)]
    if not cands:
        return math.inf, None
    near = max(cands, key=lambda w: w.x1)
    words_before = [w for w in sorted(cands, key=lambda w: -w.x1) if not _SUBLETTER.match(w.text)
                    and not _UPPER.match(w.text)]
    if words_before and words_before[0].text.lower().strip(".,:;()►▶") in _CHECK_HERE:
        return -math.inf, near  # "... check here a. [ ]": the caption is on the left, whatever prints to the right
    return b.x0 - near.x1, near


def _option_labels(words: list[_Word], boxes: list[_Box]) -> None:
    """D3 (docs/dev/JK19-PILOT.md): an option box's label names its OWN option. Where a row prints each option's
    caption right of its box ("[ ] Single [ ] Married filing jointly"), the caption on the left is the previous
    option's, so the label is read from the right. The side is decided per row band: the option boxes of the band
    vote (a box votes right when its right caption sits closer than its left one) and a strict majority decides for
    every box of the band. A tied band of two or more boxes follows its last (rightmost) box: right when that box
    prints a caption to its right ("... [ ] Yes [ ] No", where the "No" box sits nearer "Yes" than "No"), left when it
    prints one only to its left ("Yes [ ] No [ ]"); otherwise the box decides alone, a tie keeping the left reading. A
    box that the side says reads right but prints nothing to its right keeps its left label. Labels only: no score
    moves."""
    opts = [b for b in boxes if _is_option(b)]
    if not opts:
        return
    gaps = {id(b): (_right_caption(b, words, boxes), _left_gap(b, words, boxes)[0]) for b in opts}
    for b in opts:
        (gr, right), gl = gaps[id(b)]
        band = [o for o in opts if _same_band(o, b)]
        votes = Counter("r" if gaps[id(o)][0][0] < gaps[id(o)][1] else "l" if gaps[id(o)][1] < gaps[id(o)][0][0]
                        else "-" for o in band)
        last = max(band, key=lambda o: o.x1)
        if votes["r"] > votes["l"]:
            side = "r"
        elif votes["l"] > votes["r"]:
            side = "l"
        elif len(band) > 1 and gaps[id(last)][0][0] < math.inf:
            side = "r"  # the band's last box prints a caption to its right: "... [ ] Yes [ ] No"
        elif len(band) > 1 and gaps[id(last)][1] < math.inf:
            side = "l"  # nothing right of the last box, a caption left of it: "Yes [ ] No [ ]"
        else:
            side = "r" if gr < gl else "l"
        if side == "r" and right:
            b.anchor.label = _label([w.text for w in right])
            b.anchor.evidence.append("label_right")


def _yes_no(text: str | None) -> str | None:
    """ "Yes" or "No" when the caption's first word is that answer ("Yes.", "No—Go to line 24"; never "Note")."""
    m = re.match(r"[^A-Za-z]*([A-Za-z]+)", text or "")
    return _YES_NO.get(m.group(1).lower()) if m else None


def _option_word(b: _Box, words: list[_Word], boxes: list[_Box]) -> str | None:
    """ "Yes" or "No" when that is the option the box's own caption names: the first word of its label read from the
    right, the caption word printed immediately left of it ("Yes [ ] No [ ]"), or a column header printed straight
    above it with no word between the two in the box's column ("Yes  No" over a column of boxes)."""
    if "label_right" in b.anchor.evidence:
        return _yes_no((b.anchor.label or "").split(" ", 1)[0])
    gl, near = _left_gap(b, words, boxes)
    if near is not None and gl <= max(OPTION_GAP_H * near.h, OPTION_GAP):
        return _yes_no(near.text)
    gr = _right_caption(b, words, boxes)[0]
    if gl < math.inf and gr < math.inf:
        return None  # a caption on either side: not a header-only column
    col = [w for w in words if w.cy > b.y1 and min(w.x1, b.x1) - max(w.x0, b.x0) > 0.5 * min(w.x1 - w.x0, b.x1 - b.x0)]
    if not col:
        return None
    return _yes_no(min(col, key=lambda w: w.cy).text)


def _word_follows(w: _Word, words: list[_Word]) -> bool:
    """A word starts on ``w``'s row within PAIR_LETTER_GAP_H font heights of its right edge, as the next word of a
    sentence does ("I authorize": 0.2); a gutter letter stands apart from its caption (Schedule H's "A  Did": 1.3)."""
    return any(o is not w and abs(o.cy - w.cy) <= 0.3 * max(o.h, w.h) and 0 <= o.x0 - w.x1 < PAIR_LETTER_GAP_H * w.h
               for o in words)


def _pair_head(pair: tuple[_Box, _Box], words: list[_Word], boxes: list[_Box]) -> str | None:
    """The designator of the question a stacked Yes/No pair answers: the nearest row-leading designator above the
    pair's top box, left of the pair, within PAIR_HEAD_ROWS printed lines, with no other box between its row and the
    pair. The designator must stand in a column of at least _MIN_COLUMN designators (the form's gutter), so a single
    upper-case letter counts when it stands in a column of numeric ones (Schedule H prints A, B and C in the column of
    1-9) and stands apart from the next word, or ends in a period (Phase K JK15b, 2026-10-25: the pronoun "I" of "I
    authorize ..." is not one); a number followed by a sub-letter ("7 a") is that sub-line. Returns the line or None."""
    top = max(pair, key=lambda o: o.cy)
    x_left = min(o.x0 for o in pair)
    heads, words_at_start = [], []
    for w in words:
        line = normalize_line(w.text) or (w.text.rstrip(".") if _UPPER.match(w.text) else None)
        if line is None or w.x1 > x_left + 1.0 or w.cy < top.cy - 0.5 * w.h or w.cy - top.cy > PAIR_HEAD_ROWS * w.h:
            continue
        before = [o for o in words if o is not w and abs(o.cy - w.cy) <= 0.3 * max(o.h, w.h) and o.x1 <= w.x0 + 0.5
                  and w.x0 - o.x1 < 2.0 * w.h and not _is_leader(o.text)]
        if before:
            continue  # not the start of its row
        if normalize_line(w.text) is None and not w.text.endswith(".") and _word_follows(w, words):
            words_at_start.append(w)  # a capital word, not a gutter letter: "I authorize ..." (WV IT-140 page 2)
            continue
        heads.append((w, line))
    if not heads:
        return None
    w, line = min(heads, key=lambda t: t[0].cy)
    if any(o.cy <= w.cy for o in words_at_start):
        return None  # the pair's own question is that unnumbered sentence, not the line above it
    numeric = [o for o in words if o is not w and normalize_line(o.text)
               and (abs(o.x0 - w.x0) <= _ALIGN_TOL or abs(o.x1 - w.x1) <= _ALIGN_TOL)]
    if len(numeric) + 1 < _MIN_COLUMN:
        return None  # not a gutter column of designators (Schedule B's margin note "FinCEN Form / 114 may ...")
    if line.isdigit():
        # -0.5: a sub-letter set flush against its number may start a hair left of it (Schedule B 2026 draft's "7a":
        # -0.00002 pt), Phase K JK15b (2026-10-25)
        nxt = [o for o in words if abs(o.cy - w.cy) <= 0.3 * max(o.h, w.h) and -0.5 <= o.x0 - w.x1 < 1.5 * w.h]
        if nxt and _sub(min(nxt, key=lambda o: o.x0)):
            line += _sub(min(nxt, key=lambda o: o.x0))  # "7 a" printed apart: line 7a
    for o in boxes:
        if any(o is x for x in pair):
            continue
        if top.cy < o.cy <= w.cy + 0.5 * w.h or _in_band(w, o):
            return None  # another box sits between the question's row and the pair, or on that row
    return line


def _pair_yes_no(words: list[_Word], boxes: list[_Box]) -> None:
    """D5 (docs/dev/JK19-PILOT.md): the boxes of a Yes/No pair each anchor to their question's designator, labelled
    "Yes" or "No". A pair is a "Yes" box and a "No" box (:func:`_option_word`) side by side in one row band with no
    option box between them, or stacked in one column (left edges within PAIR_X_TOL) less than PAIR_STACK_GAP apart
    with no box between; each box pairs once, nearest first. A box with no printed_line takes its partner's
    (``pair_of:<field>``) or, when neither has one, the question's designator above the pair (``pair_head:<line>``).
    Both boxes carry ``yes_no_pair:<partner field>`` and cap at CAP_PAIR: one designator names two boxes, so neither
    reaches the top tier (the multi-box-row rule)."""
    opts = [b for b in boxes if _is_option(b)]
    word = {id(b): _option_word(b, words, boxes) for b in opts}
    yes = [b for b in opts if word[id(b)] == "Yes"]
    no = [b for b in opts if word[id(b)] == "No"]
    cands = []
    for y in yes:
        for n in no:
            if _same_band(y, n):
                lo, hi = sorted((y, n), key=lambda o: o.x0)
                if any(o is not y and o is not n and _is_option(o) and _same_band(o, y) and lo.x1 <= o.x0 < hi.x0
                       for o in boxes):
                    continue
                dist = hi.x0 - lo.x1
                if dist > PAIR_SIDE_GAP:
                    continue
            elif abs(y.x0 - n.x0) <= PAIR_X_TOL:
                lo_y, hi_y = sorted((y.cy, n.cy))
                dist = hi_y - lo_y
                if dist > PAIR_STACK_GAP or any(o is not y and o is not n and lo_y < o.cy < hi_y
                                                and min(o.x1, y.x1) - max(o.x0, y.x0) > 0 for o in boxes):
                    continue
            else:
                continue
            cands.append((dist, y, n))
    taken: set[int] = set()
    for _, y, n in sorted(cands, key=lambda t: (t[0], t[1].y0, t[1].x0)):
        if id(y) in taken or id(n) in taken:
            continue
        taken |= {id(y), id(n)}
        lines = {o.anchor.printed_line for o in (y, n) if o.anchor.printed_line}
        if len(lines) == 1:
            line = next(iter(lines))
            for o, other in ((y, n), (n, y)):
                if not o.anchor.printed_line:
                    o.anchor.printed_line = line
                    o.anchor.evidence.append(f"pair_of:{other.info['name']}")
                    o.anchor.score = min(other.anchor.score, CAP_PAIR)
        elif not lines:
            head = _pair_head((y, n), words, boxes)
            if head is not None:
                for o in (y, n):
                    o.anchor.printed_line = head
                    o.anchor.evidence.append(f"pair_head:{head}")
                    o.anchor.score = W_GUTTER - 0.5  # a head above the box, as gutter_head scores
        for o, other, label in ((y, n, "Yes"), (n, y, "No")):
            o.anchor.label = label
            o.anchor.evidence.append(f"yes_no_pair:{other.info['name']}")
            o.anchor.score = min(o.anchor.score, CAP_PAIR)


def _same_band(a: _Box, b: _Box) -> bool:
    """Two boxes share a row band: their vertical extents overlap by at least half the shorter box's height."""
    return min(a.y1, b.y1) - max(a.y0, b.y0) >= 0.5 * min(a.h, b.h)


def _cap_shared_rows(boxes: list[_Box]) -> None:
    """The row-identification invariant (module doc; Phase K JK15 round 3, 2026-10-24): a widget whose row band holds
    a fillable text box of another field keeps a top-tier score only when every fillable text box in that band, its
    own included, carries its own distinct printed_line read from a ``beside:`` designator. Every other widget with a
    printed_line is capped at CAP_SHARED_ROW with one ``shared_row:<field>`` entry per neighbour field."""
    for b in boxes:
        a = b.anchor
        if not a.printed_line:
            continue
        others = [o for o in boxes if o.info["name"] != b.info["name"] and o.info["kind"] in _ENTRY_KINDS
                  and _same_band(o, b)]
        if not others:
            continue  # (i): the only fillable text box in its row band
        group = [b, *others]
        lines = [x.anchor.printed_line for x in group]
        if (all(lines) and len(set(lines)) == len(lines)
                and all(f"beside:{x.anchor.printed_line}" in x.anchor.evidence for x in group)):
            continue  # (ii): "2a [box] b ... 2b [box]", each box with its own designator printed before it
        for name in sorted({o.info["name"] for o in others}):
            a.evidence.append(f"shared_row:{name}")
        a.score = min(a.score, CAP_SHARED_ROW)


def _designators_before(b: _Box, words: list[_Word]) -> set[str]:
    """The designator printed immediately before the box, whether or not the box took it as its line (Phase K JK15
    round 4, 2026-10-24): the nearest non-leader token left of the box in its band, within BESIDE_GAP (BESIDE_FAR
    right after a dot leader), and a lone designator standing at the box's own left edge. Caption context is not
    weighed ("from line 30 [box]" counts): the one-to-one rule fails closed."""
    out: set[str] = set()
    band = sorted((w for w in words if _in_band(w, b) and w.x1 <= b.x0 + 2.0 and b.x0 - w.x1 <= BESIDE_FAR),
                  key=lambda w: w.x0)
    cands = [w for w in band if not _is_leader(w.text) and w.text not in _SKIP_BESIDE]
    if cands:
        near = max(cands, key=lambda w: w.x1)
        if b.x0 - near.x1 <= BESIDE_GAP or _after_leader(near, band):
            line = normalize_line(near.text)
            if line:
                out.add(line)
    inside = [w for w in words if _in_band(w, b) and b.x0 - 1.0 <= w.x0 < b.x0 + min(30.0, 0.35 * (b.x1 - b.x0))
              and w.x1 <= b.x1]
    if len(inside) == 1 and normalize_line(inside[0].text):
        out.add(normalize_line(inside[0].text))
    return out


def _named_lines(b: _Box) -> set[str]:
    """The lines a box's /TU and its ``Line16``-style field name name. Both count, even when they disagree or a /TU
    is present (Georgia 500's "L4_DATE1" under a /TU that names no line): the one-to-one rule fails closed."""
    return {x for x in (_tu_line(b.info.get("tooltip")), _name_line(b.info["name"])) if x}


def _cap_same_lines(words: list[_Word], boxes: list[_Box]) -> None:
    """The one-to-one rule (module doc; Phase K JK15 round 4, 2026-10-24): a widget keeps a top-tier score only when
    no other field's fillable box on the page (a) carries the same printed_line, (b) has that designator printed
    immediately before it, or (c) names that line through its /TU or its field name. Every other widget with a
    printed_line is capped at CAP_SAME_LINE with one ``same_line:<field>`` entry per rival field."""
    related: dict[int, set[str]] = {}
    for o in boxes:
        if o.info["kind"] not in _ENTRY_KINDS:
            continue
        lines = _designators_before(o, words)
        if o.anchor.printed_line:
            lines.add(o.anchor.printed_line)
        lines |= _named_lines(o)
        related[id(o)] = lines
    for b in boxes:
        a = b.anchor
        if not a.printed_line:
            continue
        rivals = sorted({o.info["name"] for o in boxes if o.info["name"] != b.info["name"]
                         and a.printed_line in related.get(id(o), ())})
        if not rivals:
            continue
        for name in rivals:
            a.evidence.append(f"same_line:{name}")
        a.score = min(a.score, CAP_SAME_LINE)


def _cap_multi_column_rows(words: list[_Word], boxes: list[_Box]) -> None:
    """Cap every box whose row band holds another fillable text box of a different field with no caption words
    between the two, whether or not that neighbour got a line (Phase K JK15, 2026-10-24).

    Delaware PIT-RES prints "1." before Column A (the spouse, filing status 4 only) and again before Column B: the
    row designator does not say which box is the filer's, so neither box reaches the top tier.
    """
    for i, b in enumerate(boxes):
        for o in boxes[i + 1:]:
            if o.info["name"] == b.info["name"] or "text" not in (b.info["kind"], o.info["kind"]):
                continue
            if min(o.y1, b.y1) - max(o.y0, b.y0) < 0.5 * min(o.h, b.h):
                continue
            left, right = (b, o) if b.x0 <= o.x0 else (o, b)
            between = [w for w in words if w.x0 >= left.x1 - 1.0 and w.x1 <= right.x0 + 1.0
                       and (_in_band(w, left) or _in_band(w, right))]
            if any(_CAPTION_WORD.search(w.text) for w in between):
                continue
            for x, y in ((b, o), (o, b)):
                if y.info["kind"] != "text":
                    continue  # the neighbour that caps x must be a fillable text box
                if "multi_column_row" not in x.anchor.evidence:
                    x.anchor.evidence.append("multi_column_row")
                x.anchor.score = min(x.anchor.score, CAP_MULTI_COLUMN)


def _cap_repeated_lines(boxes: list[_Box]) -> None:
    """One designator on boxes of different fields on one page: cap them all below the top tier (Phase K JK15,
    2026-10-24). Alabama 40NR page 2 prints "2" once in each Part; without its Part the designator does not identify
    the box. Only boxes whose score a cap would lower take part (a capped or conflicting box is not a rival)."""
    by_line: dict[str, list[_Box]] = {}
    for b in boxes:
        if b.anchor.printed_line and b.anchor.score > CAP_REPEATED_LINE:
            by_line.setdefault(b.anchor.printed_line, []).append(b)
    for line, group in by_line.items():
        if len({b.info["name"] for b in group}) < 2:
            continue
        for b in group:
            b.anchor.evidence.append(f"repeated_line:{line}")
            b.anchor.score = min(b.anchor.score, CAP_REPEATED_LINE)


def _aligned_beside(w: _Word, words: list[_Word], boxes: list[_Box]) -> bool:
    """The beside token stands in a column of designators (the IRS amount-number column, Maine's 21./22./23.)."""
    same = 0
    for o in words:
        if normalize_line(o.text) and (abs(o.x0 - w.x0) <= _ALIGN_TOL or abs(o.x1 - w.x1) <= _ALIGN_TOL):
            same += 1
    return same >= _MIN_COLUMN


def _parent_above(letter: _Word, words: list[_Word], lead_ids: set[int], left: float) -> str | None:
    """The numbered head a sub-letter row hangs from: the nearest numeric designator above and left of it. A joined
    lettered head above ("47a" over "b") is that row's own number when its letter comes before the sub-letter (Phase K
    JK15b (2026-10-25): "47a" printed wider than the gutter's "46" used to be skipped, so "b" hung from 46)."""
    best = None
    for w in words:
        if id(w) not in lead_ids or w.cy <= letter.cy + 0.5 * letter.h or w.x0 < left - 1.0:
            continue
        line = normalize_line(w.text)
        if line is None:
            continue
        if w.x1 > letter.x0 + 1.0 and (line.isdigit() or w.x0 >= letter.x0 - 1.0):
            continue
        if letter.x0 - w.x0 > 40:
            continue
        if best is None or w.cy < best.cy:
            best = w
    if best is None or best.cy - letter.cy > 12 * letter.h:
        return None
    line = normalize_line(best.text)
    if not line.isdigit():
        # "25." heads "a." / "b."; a lettered head ("47a") heads a later letter ("b") of its own number only
        num, head_letter = line.rstrip("abcdefghijklmnopqrstuvwxyz"), line[-1]
        sub = _sub(letter)
        return num if num.isdigit() and sub is not None and head_letter < sub else None
    return line


def _head_above(first: _Word, b: _Box, words: list[_Word], lead_ids: set[int], aligned: set[int],
                boxes: list[_Box], left: float) -> _Word | None:
    """A caption that starts one or two printed lines above the box ("20. INCOME TAX ... / ... 20. [box]")."""
    top = b.cy + max(b.h, first.h) / 2 + 1.0
    cands = [w for w in words if id(w) in aligned and normalize_line(w.text) and w.cy > top
             and w.cy <= top + 2.6 * first.h and w.x1 < first.x0 - 1.0 and w.x0 >= left - 1.0]
    if not cands:
        return None
    head = min(cands, key=lambda w: w.cy)
    # the head must not belong to another box's row
    for o in boxes:
        if o is not b and o.x0 >= first.x0 and _in_band(head, o):
            return None
    return head


def _label_above(b: _Box, words: list[_Word]) -> str | None:
    """The printed line nearest above the box, over its width (a name/address caption)."""
    above = [w for w in words if w.cy > b.y1 and w.cy <= b.y1 + 2.6 * w.h
             and w.x1 >= b.x0 - 5.0 and w.x0 <= b.x1 + 5.0]
    if not above:
        return None
    lowest = min(w.cy for w in above)
    row = sorted((w for w in above if abs(w.cy - lowest) <= 0.3 * w.h), key=lambda w: w.x0)
    return _label([w.text for w in row])


def raw_anchors(pdf_path: str | Path) -> list[WidgetAnchor]:
    """Every widget's anchor with its signal ``score`` and NO tier (``confidence`` stays "none").

    For the benchmark only: it measures precision against candidate thresholds before any table licenses them.
    Callers that need tiers use :func:`anchor_widgets`.
    """
    infos = extract_fields(str(user_path(pdf_path)))
    counts: Counter = Counter()
    by_page: dict[int, list[_Box]] = {}
    anchors: list[WidgetAnchor] = []
    doc = _open(pdf_path)
    try:
        page_q: dict[int, tuple[list[_Word], int]] = {}
        for info in infos:
            idx = counts[info["name"]]
            counts[info["name"]] += 1
            rect = [float(v) for v in info["rect"]] if len(info["rect"]) == 4 else [0.0, 0.0, 0.0, 0.0]
            anchor = WidgetAnchor(field=info["name"], widget_index=idx, page=info["page"], rect=rect, kind=info["kind"])
            anchors.append(anchor)
            if info["kind"] in ("pushbutton", "signature") or rect == [0.0, 0.0, 0.0, 0.0]:
                anchor.evidence.append("not_an_entry")
                continue
            if info["page"] not in page_q:
                page_q[info["page"]] = _page_words(doc[info["page"] - 1], info["page"])
            words, q = page_q[info["page"]]
            if not words:
                anchor.evidence.append("no_text_layer")
                continue
            x0, y0, x1, y1 = rect
            rx0, ry0, rx1, ry1 = _rotate_box(q, min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            by_page.setdefault(info["page"], []).append(_Box(info=info, index=idx, x0=rx0, y0=ry0, x1=rx1, y1=ry1,
                                                              anchor=anchor))
        for page_no, boxes in by_page.items():
            words, q = page_q[page_no]
            _anchor_page(words, boxes, q)
    finally:
        doc.close()
    return anchors


# ── tiers and the committed table ────────────────────────────────────────────


def table_path() -> Path:
    """Where the committed benchmark table lives (under the shipped knowledge tree, so a wheel carries it)."""
    return knowledge_dir() / TABLE_RELPATH


def load_table(path: str | Path | None = None) -> dict | None:
    """The committed benchmark table, or None when there is none (a missing or unreadable file)."""
    import yaml  # noqa: PLC0415 — only the gate needs it

    p = Path(path) if path is not None else table_path()
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


_CHECKBOX_KINDS = frozenset({"checkbox", "radio"})


def kind_group(kind: str) -> str:
    """The table's widget groups: "checkbox" (checkbox and radio buttons) or "text" (everything else)."""
    return "checkbox" if kind in _CHECKBOX_KINDS else "text"


def _licensed(table: dict | None) -> dict | None:
    """The table's thresholds when it licenses tiers above "low": passed is exactly True, for this METHOD.

    ``top_kinds`` are the widget groups (:func:`kind_group`) whose scored top-tier precision the table measured at
    >= 0.99 (its ``top_tier_kinds``, Phase K JK15 round 2: the TEST checkboxes measured 10/11, so only text boxes are
    licensed for the top tier); a group left out is capped at "med". Licensing fails closed (round 3): a table of
    this METHOD whose ``top_tier_kinds`` is missing or not a list licenses NO group for the top tier.
    """
    if not table or table.get("passed") is not True or table.get("method") != METHOD:
        return None
    th = table.get("thresholds")
    if not isinstance(th, dict):
        return None
    try:
        out: dict = {"top": float(th["top"]), "med": float(th["med"])}
    except (KeyError, TypeError, ValueError):
        return None
    kinds = table.get("top_tier_kinds")
    out["top_kinds"] = frozenset(str(k) for k in kinds) if isinstance(kinds, list) else frozenset()
    return out


def tier_for(anchor: WidgetAnchor, thresholds: dict | None) -> str:
    """The tier for one widget: top / med only under licensed thresholds; else low (something found) or none."""
    if anchor.printed_line and thresholds is not None:
        if anchor.score >= thresholds["top"]:
            if any(e.startswith(_NEVER_TOP) for e in anchor.evidence):
                return MED  # a cap's evidence keeps the widget below the top tier whatever the thresholds
            kinds = thresholds.get("top_kinds")
            group = kind_group(anchor.kind)
            if kinds is not None and group in kinds:
                return TOP
            note = f"top_kind_not_licensed:{group}"
            if note not in anchor.evidence:
                anchor.evidence.append(note)
            return MED
        if anchor.score >= thresholds["med"]:
            return MED
    if anchor.printed_line or anchor.label:
        return LOW
    return NONE


def _display(p: Path) -> str:
    try:
        return p.resolve().relative_to(data_root().resolve()).as_posix()
    except ValueError:
        return home_display(p)


def anchor_basis(path: str | Path | None = None) -> dict:
    """What the emitted tiers rest on: the committed table (path, sha256 prefix, passed) or that none has passed."""
    p = Path(path) if path is not None else table_path()
    table = load_table(p)
    if table is None:
        return {"table": None, "passed": False, "method": METHOD, "tiers": [LOW, NONE],
                "note": "no anchor benchmark table has passed, so only 'low' and 'none' are emitted"}
    digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    license_ = _licensed(table)
    licensed = license_ is not None
    out = {"table": _display(p), "sha256": digest, "passed": table.get("passed") is True, "method": METHOD,
           "tiers": list(TIERS) if licensed else [LOW, NONE]}
    if not licensed:
        why = ("its passed is false" if table.get("passed") is not True
               else f"it measured method {table.get('method')!r}, not {METHOD!r}")
        out["note"] = f"no anchor benchmark table has passed ({why}), so only 'low' and 'none' are emitted"
    else:
        out["top_tier_kinds"] = sorted(license_["top_kinds"])
        licensed_for = (f"it is licensed for {', '.join(out['top_tier_kinds'])} widgets only, the rest cap at 'med'"
                        if out["top_tier_kinds"] else "it licenses the top tier for no widget group, so all cap at 'med'")
        out["note"] = (f"tiers rest on this table; the top tier is worded {TOP!r} and is still an unverified line map; "
                       f"{licensed_for}")
    return out


def anchor_widgets(pdf_path: str | Path, *, table: str | Path | None = None) -> AnchorMap:
    """Anchor every widget of a blank: printed_line, label, confidence and evidence per widget (see the module doc).

    ``table`` overrides the committed table's path (tests). A field's confidence is the lowest of its widgets'.
    """
    p = Path(table) if table is not None else table_path()
    thresholds = _licensed(load_table(p))
    anchors = raw_anchors(pdf_path)
    fields: dict[str, str] = {}
    for a in anchors:
        a.confidence = tier_for(a, thresholds)
        prev = fields.get(a.field)
        if prev is None or _RANK[a.confidence] > _RANK[prev]:
            fields[a.field] = a.confidence
    return AnchorMap(widgets=anchors, fields=fields, basis=anchor_basis(p))
