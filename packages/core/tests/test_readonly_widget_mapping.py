"""Repo-wide P-007 invariant: which packs may bind an AcroForm ReadOnly widget.

Pitfall P-007 started as one pack's bug (Schedule D mapped the two shaded
no-adjustment (g) cells) and the fix shipped two sched_d-shaped tests. This
file is the generic version: it sweeps **every** discovered pack — federal
AND state, 172 of them (111 federal + 61 state) — reads each pack's own blank,
and asserts that a mapped field binds a ReadOnly widget (/Ff bit 1) only where
an explicit, per-entry-justified table says it may.

Why a flag scan is not enough, and why the tables carry prose. "ReadOnly"
means four different things on real tax PDFs, and only the printed row text
tells them apart (P-007's DISCRIMINATOR):

1. **The widget already HOLDS the form's own printed constant.** Schedule SE
   lines 7 and 14 ship the wage base and the optional-method cap ($176,100 /
   $7,240 for 2025) inside the widget; Form 1040-ES's four voucher rows ship
   the printed due dates. Mapping one would let the filler OVERWRITE an
   IRS-printed figure. Never mapped, never allowlisted.
2. **The printed text makes a correct entry impossible.** Schedule D rows
   1a/8a print "...leave this line blank and go to line 1b" right where
   column (g) sits; Schedule E's four "Totals" rows are read by a following
   line that names only the *other* columns; Schedule NEC's loss cells print
   "Losses aren't allowed". No value can be right, so the LINE KEY must not
   exist — fill_form has to raise instead of writing a locked grey box.
   Pinned by ``RESERVED_LINES_UNMAPPED`` here and, for sched_d/sched_e, by
   the form-specific tests in test_formpacks_federal.py.
3. **A printed, numbered line that merely reads "Reserved for future use".**
   Both treatments are defensible and the repo ships BOTH, which is why the
   tables below are two-sided. Keeping the key addressable is what makes the
   revision where the line goes live a widget swap instead of an API change
   (f1040 line 30 became "Refundable adoption credit" in 2025; f1040-X line
   4a became the QBI deduction in Rev. 12-2025 — and the IRS CLEARED the
   ReadOnly bit on the very same widgets both times). What is never
   defensible is the flag-only rationale "the widget is ReadOnly, so it is
   intentionally unfillable": that is the premise P-007 overturned, and
   several pack headers still state it.
4. **A state DOR field whose value the form's own JavaScript owns.** The
   majority of this repo's ReadOnly bindings by far. taxfill never executes
   that JavaScript, so a running total, a page-2/3/4 name+SSN mirror or a
   carried subtotal that the pack does NOT map ships BLANK on the filed
   return. Those bindings are correct and there are 1,140 of them across 10
   packs, so they are pinned per pack by COUNT (``STATE_COMPUTED_READONLY``)
   rather than per widget — a per-widget list of 1,140 names would be a
   rubber stamp, while the count still fails the moment a port grows it.
   Note that not every row is a *computed* field, and the mechanism is not
   always JavaScript:

   - the OH rows include ReadOnly bits Ohio set on boxes its own printed face
     tells the filer to complete, plus a THIRD sub-shape worth naming — a
     ReadOnly bit that is a JS-GATED UI DEFAULT rather than a computed value
     or an authoring slip. IT 1040 lines 17/19 are filer-entry cells the
     form's own script UNLOCKS on ``CHK_AMD == "Yes"`` while simultaneously
     LOCKING lines 25/26a-g, matching the printed "Amended return only" vs
     "Original return only" captions. The discriminator: look for
     ``getField("<name>").readonly = false`` in the document JavaScript, and
     compare the widget's ``/AA`` against an UNFLAGGED neighbour on an
     adjacent printed line (L17/L19 are identical to L18/L20).
   - the RI rows are not JavaScript at all. RI-1040 is an XFA form whose
     identity mirrors propagate by declarative ``<bind match="global"/>`` with
     ZERO ``<script>`` elements; the per-page ``access="protected"`` attribute
     is what LiveCycle emits as the ReadOnly bit. The renderer's pdfium build
     has no XFA support, so no XFA form's bindings will ever propagate in this
     pipeline — a durable reason, not a per-form one.

   What never settles the question is the flag, or a JavaScript *count*:
   ``pdfinfo``'s "JavaScript: yes" is satisfied by ``AFNumber_Format`` /
   ``AFSpecial_Keystroke`` FORMATTING scripts and says nothing about whether a
   form computes. Only an ``/AA /C`` action or membership in a DISCRIMINATING
   AcroForm ``/CO`` does — and see the OH 2024 row for why ``/CO`` membership
   often discriminates nothing at all.

Layers, following the house pattern (test_formpacks_federal.py):

- **offline** (always run): the tables are pinned against the packs
  themselves — every keep row really is mapped to the widget it names, every
  unmapped row really is absent and fill_form really refuses it, the two
  tables agree about which years keep and which exclude a line, and the flag
  reader is proven on a synthetic PDF.
- **@pytest.mark.network**: the blanks. Reads the pack's own blank from the
  shared cache (fetch_blank returns the cached copy without touching the
  network), asserts the mapped-∩-ReadOnly set equals the table exactly, and
  re-reads the PRINTED ROW TEXT of every keep row so the allowlist stays an
  adjudication rather than a rubber stamp: when the IRS un-reserves the line,
  the row is forced out.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from pdf_fixtures import make_acroform_pdf
from taxfill_core.fetch import OfflineFetchError, fetch_blank
from taxfill_core.filler import fill_form
from taxfill_core.schemas.formpack import load_pack

from test_formpacks_federal import _read_only_widget_names

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMPACKS = REPO_ROOT / "formpacks"
ALL_PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))
FEDERAL_PACK_PATHS = [path for path in ALL_PACK_PATHS if path.parts[-4] == "federal"]
STATE_PACK_PATHS = [path for path in ALL_PACK_PATHS if "states" in path.parts]

RESERVED_TEXT = "Reserved for future use"


def _key(pack_path: Path) -> str:
    """Pack identity used by every table here: path relative to formpacks/.

    Same key shape as tests/fixtures/filer_address_lines.json, e.g.
    "federal/2025/sched_a/pack.yaml", "states/wi/2023/wi_form1/pack.yaml".
    """
    return str(pack_path.relative_to(FORMPACKS))


def _pack_id(pack_path: Path) -> str:
    return _key(pack_path).removesuffix("/pack.yaml").replace("/", "-")


# ---------------------------------------------------------------------------
# Table 1 — reserved printed lines that are deliberately KEPT MAPPED
# ---------------------------------------------------------------------------


class ReservedKeep(NamedTuple):
    """One mapped field that legitimately binds a ReadOnly widget."""

    pack: str  # path relative to formpacks/
    line: str  # the pack's line id
    widget: str  # the pack's `field:` value (acroform_root NOT prefixed)
    why: str  # per-entry justification — read this before adding a row


# Every one of these prints "Reserved for future use" on a NUMBERED or
# LETTERED line of the form's own ladder, carries /Ff = 8388609
# (DoNotScroll|ReadOnly), and is mapped with a leave-blank comment in its
# pack. Verified against each pack's sha-pinned blank on 2026-08-20 by the
# repo-wide sweep this file automates: those 13 bindings are the COMPLETE
# federal set — no other federal pack maps a ReadOnly widget.
#
# Adding a row is an adjudication, not a formality: read the row's printed
# text off the blank, confirm no printed instruction makes the cell
# necessarily blank (that is case 2 in the module docstring — exclude
# instead), and write down what the line becomes when it goes live.
RESERVED_LINE_KEEPS: tuple[ReservedKeep, ...] = (
    # Schedule 1 line 22 — reserved in every shipped year. The printed line-26
    # sum ("Add lines 11 through 23, and 25") ENUMERATES 22, so the key must
    # stay addressable for the relation to evaluate it blank-as-zero.
    ReservedKeep("federal/2022/sched_1/pack.yaml", "22", "Page2[0].f2_14[0]", "named by the printed line-26 sum"),
    ReservedKeep("federal/2023/sched_1/pack.yaml", "22", "Page2[0].f2_14[0]", "named by the printed line-26 sum"),
    ReservedKeep("federal/2024/sched_1/pack.yaml", "22", "Page2[0].f2_14[0]", "named by the printed line-26 sum"),
    ReservedKeep("federal/2025/sched_1/pack.yaml", "22", "Page2[0].f2_14[0]", "named by the printed line-26 sum"),
    # Form 1040 line 30 — the load-bearing proof of the keep rationale: the
    # 2025 revision un-reserved this exact line ("Refundable adoption credit
    # from Form 8839, line 13"), cleared the ReadOnly bit, and named it in
    # "32 == 27a + 28 + 29 + 30 + 31". Keeping the key made that a widget
    # swap instead of a namespace change.
    ReservedKeep("federal/2023/f1040/pack.yaml", "30", "Page2[0].f2_19[0]", "went live in the 2025 revision"),
    ReservedKeep("federal/2024/f1040/pack.yaml", "30", "Page2[0].f2_19[0]", "went live in the 2025 revision"),
    # Form 1040-NR 2025 — four reserved rows of the printed income/payments
    # ladders. Line 6 has been reserved since at least 2022 (the NR has no
    # social-security line; SSA benefits are Schedule NEC income) and 27 is
    # the EIC line a nonresident can never claim, but both are printed and
    # numbered, and their neighbour line 30 went live in this same revision.
    ReservedKeep("federal/2025/f1040nr/pack.yaml", "1i", "Page1[0].f1_51[0]", "printed row of the 1a-1z wage ladder"),
    ReservedKeep("federal/2025/f1040nr/pack.yaml", "1j", "Page1[0].f1_52[0]", "printed row of the 1a-1z wage ladder"),
    ReservedKeep("federal/2025/f1040nr/pack.yaml", "6", "Page1[0].f1_65[0]", "printed row of the income ladder"),
    ReservedKeep("federal/2025/f1040nr/pack.yaml", "27", "Page2[0].f2_29[0]", "printed row of the payments ladder"),
    # Schedule 2 2025 line 10 — ENUMERATED by the printed line-21 sum
    # ("Add lines 4, 7 through 16, 18, and 19"), same shape as sched_1 22.
    ReservedKeep("federal/2025/sched_2/pack.yaml", "10", "Page1[0].f1_21[0]", "named by the printed line-21 sum"),
    # Schedule 8812 2025 line 15 — printed, numbered, reserved. Note the
    # 2023/2024 packs have a line "15" too, but it is an ordinary checkbox on a
    # different face; there is no cross-year split here.
    ReservedKeep(
        "federal/2025/sched_8812/pack.yaml",
        "15",
        "Page2[0].f2_1[0]",
        "printed numbered line of Part II-A, reserved in this revision only",
    ),
    # Schedule A 2025 line 8d — printed LETTERED line of the line-8
    # mortgage-interest ladder. Note the 2023/2024 packs EXCLUDE the same
    # line: that split is recorded in RESERVED_LINES_UNMAPPED below.
    ReservedKeep("federal/2025/sched_a/pack.yaml", "8d", "Page1[0].f1_19[0]", "printed lettered line of the line-8 ladder"),
)


# ---------------------------------------------------------------------------
# Table 2 — ReadOnly widgets whose LINE KEY must not exist at all
# ---------------------------------------------------------------------------


class ReservedUnmapped(NamedTuple):
    """One line id that must stay out of a pack's map, and why."""

    pack: str  # path relative to formpacks/
    lines: tuple[str, ...]  # line ids (all columns/suffixes) that must be absent
    survivors: tuple[str, ...]  # neighbouring lines that must SURVIVE (over-reach guard)
    contested_with: str | None  # form_key whose OTHER year keeps this line, or None
    why: str


# The exclusions this pitfall's adjudication shipped or confirmed, plus the
# pre-existing ones that share the same printed facts. `contested_with` is the
# open debt: a non-None value means another year of the SAME form keeps the
# line mapped, so the repo currently answers one printed face two ways.
#
# sched_d (1a.g/8a.g) and sched_e (its nine "Totals" cells) are the same class
# but already have dedicated tests in test_formpacks_federal.py — they are
# deliberately not duplicated here.
RESERVED_LINES_UNMAPPED: tuple[ReservedUnmapped, ...] = (
    # Form 1040-X, Rev. 2-2024 (pinned by BOTH the 2023 and 2024 packs — one
    # blank, sha256 a4bed38a..., so one verdict). Line 4a prints "Reserved for
    # future use" and NOTHING names it: printed line 5 is "Subtract line 4b
    # from line 3", the pack's relation is "5 == max(0, 3 - 4b)", and no calc
    # op, cross_form rule or extractor in the repo produces or consumes it.
    # The mapping was an internal contradiction — the same packs already
    # excluded lines 9/24/26/28/29, which print the identical sentence.
    # NOT contested: the 2025 pack maps 4a because Rev. 12-2025 RELABELLED
    # that line "Qualified business income deduction" and CLEARED the ReadOnly
    # bit on the same three widgets. (P-007 once claimed "the 2025 f1040x
    # already excludes 4a" — it never did; test_reserved_line_tables_agree
    # below is what now makes that claim uncheckable-in-prose impossible.)
    ReservedUnmapped(
        "federal/2023/f1040x/pack.yaml",
        ("4a", "4a.original", "4a.net_change"),
        ("4b", "4b.original", "4b.net_change", "5", "3"),
        None,
        "Rev. 2-2024 prints 4a 'Reserved for future use' and no printed sum, relation or "
        "extractor names it; Rev. 12-2025 relabelled it QBI and cleared the flag",
    ),
    ReservedUnmapped(
        "federal/2024/f1040x/pack.yaml",
        ("4a", "4a.original", "4a.net_change"),
        ("4b", "4b.original", "4b.net_change", "5", "3"),
        None,
        "same pinned Rev. 2-2024 blank as the 2023 pack — one blank, one verdict",
    ),
    # Form 1040-X lines 9/24/26/28/29, all three columns each, in ALL years
    # (15 widgets in Rev. 12-2025, 18 with the 4a trio in Rev. 2-2024). Each
    # prints "Reserved for future use" and none is named by a printed sum.
    *(
        ReservedUnmapped(
            f"federal/{year}/f1040x/pack.yaml",
            tuple(
                f"{line}{suffix}"
                for line in ("9", "24", "26", "28", "29")
                for suffix in ("", ".original", ".net_change")
            ),
            ("5", "10", "11"),
            None,
            "five printed 'Reserved for future use' lines, no printed sum names any of them",
        )
        for year in (2023, 2024, 2025)
    ),
    # Schedule 3 line 6e, every shipped year. Printed "Reserved for future
    # use"; the printed line-7 instruction is the RANGE "Add lines 6a through
    # 6z", which already tolerates gaps, and the pack's "7 == sum(6a..6z)"
    # evaluates unmapped letters blank-as-zero. CONTESTED: sched_a 2025 keeps
    # its own reserved LETTERED line (8d) under the opposite rule, and this
    # pack's stated rationale ("its amount box is ReadOnly ... so it is
    # intentionally unfillable") is the flag-only premise P-007 overturned.
    *(
        ReservedUnmapped(
            f"federal/{year}/sched_3/pack.yaml",
            ("6e",),
            ("6d", "6f", "7"),
            None,
            "range sum 'Add lines 6a through 6z' tolerates the gap; rationale in the pack "
            "header is still the overturned flag-only one and needs rewording",
        )
        for year in (2023, 2024, 2025)
    ),
    # Schedule 2 2023 line 19 — reserved and excluded. contested_with stays
    # None because that field means strictly "another year keeps THIS line",
    # and 2023 line 19 is not 2025 line 10. The inconsistency is real all the
    # same and is the wider debt recorded in P-007: the SAME form answers the
    # same printed sentence one way in 2023 (exclude line 19) and the other in
    # 2025 (keep line 10).
    ReservedUnmapped(
        "federal/2023/sched_2/pack.yaml",
        ("19",),
        ("18", "20", "21"),
        None,
        "reserved printed line excluded here, while sched_2 2025 keeps its own reserved "
        "line 10 mapped — same form, same printed sentence, opposite treatment",
    ),
    # Schedule C 2022 line 27b — reserved and excluded.
    ReservedUnmapped(
        "federal/2022/sched_c/pack.yaml",
        ("27b",),
        ("27a", "28"),
        None,
        "reserved printed line, no other shipped sched_c year keeps it",
    ),
    # Form 1040-NR 2022/2023/2024 — the SAME printed reserved rows the 2025
    # pack keeps mapped, excluded here under headings that additionally call
    # these ReadOnly widgets "fillable". By the discriminator the earlier
    # years are the deviants. Reproduced: fill_form(f1040nr 2023, {"1i": 111})
    # raises "unknown line key" while the 2025 pack writes f1_51[0].
    ReservedUnmapped(
        "federal/2022/f1040nr/pack.yaml",
        ("1i", "6", "27"),
        ("1h", "1z", "5b", "8", "9"),
        "f1040nr",
        "f1040nr 2025 keeps the same printed reserved rows mapped — cross-year split",
    ),
    *(
        ReservedUnmapped(
            f"federal/{year}/f1040nr/pack.yaml",
            ("1i", "1j", "6", "27"),
            ("1h", "1z", "5b", "8", "9"),
            "f1040nr",
            "f1040nr 2025 keeps the same printed reserved rows mapped — cross-year split",
        )
        for year in (2023, 2024)
    ),
    # Schedule A 2023/2024 line 8d — excluded on the explicitly flag-only
    # rationale "the PDF field is read-only (/Ff bit 1 set) and the printed
    # line takes no entry", which is exactly the premise P-007 overturned,
    # while the 2025 pack keeps the identical printed line.
    *(
        ReservedUnmapped(
            f"federal/{year}/sched_a/pack.yaml",
            ("8d",),
            ("8a", "8b", "8c", "8e"),
            "sched_a",
            "sched_a 2025 keeps the identical printed reserved line — cross-year split, and "
            "the stated rationale here is the overturned flag-only one",
        )
        for year in (2023, 2024)
    ),
)


# ---------------------------------------------------------------------------
# Table 3 — state packs: DOR-computed / JS-mirrored ReadOnly fields
# ---------------------------------------------------------------------------


class StateComputed(NamedTuple):
    """Pinned count of mapped ReadOnly widgets in one state pack."""

    pack: str
    count: int  # mapped pack FIELDS whose widget carries /Ff bit 1
    why: str


# State DOR PDFs set ReadOnly on fields whose value the FORM owns rather than
# the filer: running totals, carried subtotals, header mirrors of the filer's
# name and SSN repeated on later pages, and cells the form only unlocks on some
# other answer. taxfill NEVER runs that propagation — no embedded JavaScript,
# and no XFA binding engine either — so the engine computes the numbers itself
# (calc.py) and writes them, and a pack that omitted these would file a return
# with blank totals or a blank page header. Mapping them is correct; what needs
# a gate is DRIFT, hence a pinned count per pack.
#
# Counts are mapped pack FIELDS, measured 2026-08-20 against each pack's
# sha-pinned cached blank, and re-measured 2026-08-21 for the ten-pack state
# tranche (ar 2024/2025, nc/nj/oh/ri/ut/va 2024, or/pa 2025). Two of those ten
# intersect — oh/2024 (6) and ri/2024 (6) — and the other eight measure an
# EMPTY intersection against their own blanks and therefore take no row; nc,
# nj, ut, va, or and pa were each confirmed at zero rather than assumed. The
# same 2026-08-21 sweep also moved two existing rows: oh/2023 2 -> 5 and
# oh/2024 3 -> 6, as the blocking P-007 class-4 fixes landed. Both readers
# agree on every figure below: walking page /Annots and walking the AcroForm
# /Fields tree to its terminals give identical mapped-∩-ReadOnly sets, in both
# cases resolving /Ff up the /Parent chain.
#
# Two OTHER ways of counting the same thing give different numbers, so state the
# metric or the next audit will "fix" a non-bug: distinct WIDGET names run lower
# where several option lines share one /Btn (GA: 193 fields, 191 widgets), and
# raw ANNOTATION counts run higher where a read-only header widget repeats
# across pages under one /T (WV pages 2, 8, 17, 18; and OH's TP_SSN1, which is
# ONE field with 12 widget kids).
#
# Every other state pack is absent from this table and therefore pinned at
# ZERO. One pack could not be measured: states/ms/2023/f80105 — its blank is
# not in .cache/blanks and dor.ms.gov fails certificate verification here, so
# both this test and test_formpacks_states' round-trip SKIP it. It is pinned
# at 0 like the rest; the assertion fires the first time someone caches that
# blank, which is the right moment to adjudicate it.
STATE_COMPUTED_READONLY: tuple[StateComputed, ...] = (
    StateComputed(
        "states/al/2023/al40/pack.yaml",
        580,
        "the pack's own header states it: 'AL marks many running totals ReadOnly, but they "
        "remain mapped so a filer can carry the computed value'. The dominant flag value is "
        "/Ff 12582913 (DoNotScroll|DoNotSpellCheck|ReadOnly)",
    ),
    StateComputed(
        "states/de/2023/pit_res/pack.yaml",
        16,
        "the eight two-column computed lines (4a/4b, 9a/9b, 10a/10b, 16a/16b, 18a/18b, "
        "21a/21b, 22a/22b, 25a/25b) — DE's JS totals; taxfill computes and writes them",
    ),
    StateComputed(
        "states/ga/2023/ga500/pack.yaml",
        193,
        "GA 500's JS-computed totals and mirrors (the ReadOnly SCANLINE voucher barcode and "
        "SSN_COPY mirror are correctly NOT mapped). 193 fields but 191 widgets: the three "
        "s3.10_deduction.* option lines share the radio field CB_DEDUCTION_TYPE, which — "
        "like Ohio's two boxes — carries a bare /Ff = 1 on a selector the printed face "
        "requires the filer to answer",
    ),
    StateComputed(
        "states/mo/2023/mo1040/pack.yaml",
        262,
        "MO-1040's JS-computed totals; the ReadOnly 'do calculations' UI toggles and the "
        "CRP2023 banner are correctly NOT mapped",
    ),
    StateComputed(
        "states/mo/2024/mo1040/pack.yaml",
        260,
        "the 2023 row's JS-computed totals carried over, with the 2024 delta measured "
        "field by field (262 -> 260): MINUS the 20 ReadOnly bindings the re-authored "
        "MO-A Part 3/Part 5 ladder removed with its 25 dead field names; PLUS 2 "
        "survivors newly flagged (/Ff 12582912 -> 12582913, the only /Ff changes on any "
        "surviving field): line44, quoted by name in the 2024 document JS "
        "(getField(\"line44\").value = getField(\"wftc_line10\").value — class 4), and "
        "line20, printed as a reserved line and additionally /F Hidden (mapped but "
        "leave-blank; anything written there is invisible on paper and line 25's "
        "printed sum treats it as 0); PLUS 16 of the 36 new 2024 fields, all mapped: "
        "the Section A/C ladder totals and wftc_line6..10 (each verified by quoted "
        "getField name in the document JS — class 4, taxfill must write the values or "
        "they print blank) and moa_pt5_1y/1s (JS-gated UI defaults unlocked by the "
        "age-62/65 boxes — the OH IT-1040 L17/L19 shape, filer data that must stay "
        "mapped). No surviving field LOST the bit; class 1 ruled out for all 16 new "
        "cells (each /V holds the calculator's factory '0', not a printed constant). "
        "The CRP banner (CRP2024 this year) stays correctly NOT mapped",
    ),
    StateComputed(
        "states/oh/2023/it1040_oh/pack.yaml",
        12,
        "TWELVE widgets, none of them a computed total: the five below plus the SEVEN "
        "page-13 Ohio Universal Payment Coupon filer-data cells mapped 2026-08-24 "
        "(UPC_FName, 40P_MI, UPC_LName, UPC_address1, UPC_CityStateZip, UPC_1st3LName, "
        "UPC_Identifier — the coupon's payer name/address block, first-3-of-last-name box "
        "and 'Taxpayer's SSN' box, each fed in a viewer by an /AA /C copy from the page-1 "
        "return fields that taxfill never runs, so unmapped they mailed a coupon whose "
        "name, address and SSN printed BLANK under their captions and whose city line "
        "printed the junk factory /V ',  '). The coupon's OTHER 53 ReadOnly cells — the "
        "37 scan-line/check-digit cells, 12 hidden carriers and 4 DOR-owned cells — stay "
        "deliberately UNMAPPED; the cell-by-cell mechanism record is the pack header's "
        "OUPC PAGE-13 ADJUDICATION. The original five: (a) CHK_AMD ('AMENDED RETURN - Check "
        "here') and CHK_SP_NON_RES_STMT are /Btn boxes the printed face tells the filer to "
        "CHECK, each carrying a bare /Ff = 1 while its own sibling (CHK_NOL, "
        "CHK_PRIM_NON_RES_STMT) carries no /Ff at all — an asymmetry that reads as a DOR "
        "authoring slip, not an instruction. (b) L17 and L19 are the JS-GATED UI DEFAULT "
        "shape: the document script unlocks both on CHK_AMD == 'Yes' and locks L25/L26A-G "
        "in the same branch, which is exactly what the printed 'Amended return only' vs "
        "'Original return only' captions say, so the bit is the default for an ORIGINAL "
        "return and not an instruction. Their /AA is identical to unflagged L18/L20 "
        "(/F + /K + /V + /C dsRound()), which is the check that tells the shapes apart. "
        "(c) TP_SSN1 is the page-header SSN mirror, a SEPARATE AcroForm field from the "
        "page-1 TP_SSN with 12 widget kids, 11 of them on document pages 2-12 (the 12th "
        "is parented to a /Type /Template object outside the page tree). Every one of "
        "pages 2-12 prints an SSN caption, so unmapped it ships a BLANK header on 11 "
        "pages; its own /AA /C copies TP_SSN in a viewer, which taxfill never runs. All "
        "three (b)/(c) bindings were added 2026-08-21",
    ),
    StateComputed(
        "states/oh/2024/it1040_oh/pack.yaml",
        13,
        "the 2023 row's CHK_AMD, L17, L19 and TP_SSN1 carry over unchanged — and so do "
        "its seven OUPC coupon filer-data cells (mapped 2026-08-24; the page-13 split of "
        "60 ReadOnly non-pushbutton fields into 7 mapped / 53 unmapped is identical in "
        "the 2024 blank, re-verified against it, with the cell-by-cell record in the 2023 "
        "base pack's OUPC PAGE-13 ADJUDICATION) — plus the two "
        "joint-filing-credit cells Ohio newly flagged for 2024 (/Ff 0 -> 1): SchedC_L12 "
        "(/MaxLen 3) and SchedC_L12_JFC (/MaxLen 2). Printed line 12 of the Schedule of "
        "Credits reads 'Joint filing credit (see instructions for table). ___% times line "
        "11, up to $650' — a numbered line a joint filer claiming the credit must "
        "complete, so unmapping either would file a BLANK joint-filing credit. "
        "CHK_SP_NON_RES_STMT LEFT the ReadOnly set in 2024 (/Ff 1 -> 0), which is why the "
        "count is 13 and not 14. CORRECTION, 2026-08-21: this row used to say 'SchedC_L12 is "
        "class 4 exactly: it sits in the AcroForm /CO calculate order and carries an /AA /C "
        "action, i.e. the form's own JavaScript computes it'. The blank does not support "
        "that and the claim is the kind P-007's own history says propagates. Re-measured "
        "against the sha-pinned blanks: /CO holds 325 entries in 2024 (321 in 2023) and "
        "includes L18 and L20 — the UNFLAGGED neighbours — so /CO membership discriminates "
        "nothing; SchedC_L12's /C is only dsRound(), byte-identical to unflagged L18's; and "
        "SchedC_L12_JFC has NO /C at all (only /F + /K) and is absent from /CO in BOTH "
        "years. The real mechanism is the JS-gated unlock that 2024 BROKE: the 2023 "
        "'case \"CHK_FILING_STATUS\"' branch unlocks both cells on value '2' (MFJ) and "
        "re-locks on '1'/'3' — 12 quoted references, 6 per name — while the static /Ff is "
        "absent; for 2024 that branch was rewritten around new hideAndClear()/"
        "showEditable() helpers and every SchedC_L12 line was DELETED (ZERO occurrences of "
        "either name in the whole 2024 JavaScript) while /Ff went absent -> 1. So the 2024 "
        "cells can never be unlocked in a viewer at all: a DOR authoring regression, not a "
        "computation. Either way taxfill must write the rate and the credit itself",
    ),
    StateComputed(
        "states/ri/2023/ri1040/pack.yaml",
        6,
        "the page-2 and page-3 halves of the twelve-widget identity banner mirror "
        "(Page2[0]/Page3[0] PrimFirstName + PrimLastName at /Ff 8388609 = "
        "DoNotScroll|ReadOnly, PrimTaxpayerSSN at /Ff 1). All four pages print "
        "'Name(s) shown on Form RI-1040 or RI-1040NR' + 'Your social security number', so "
        "unmapped they ship a BLANK banner. The mechanism is NOT JavaScript: the XFA "
        "template gives all fifteen instances (page-1 originals + twelve mirrors) exactly "
        "one <bind match=\"global\"/> and ZERO <script> elements, and gives only these six "
        "access=\"protected\" — which is what LiveCycle emits as the ReadOnly bit and why "
        "the Page4/Page5 six are NOT ReadOnly and must NOT appear in this count. taxfill "
        "never runs the XFA binding engine (the renderer's pdfium build is compiled "
        "without XFA support), so every mirror must be written explicitly. Added 2026-08-21",
    ),
    StateComputed(
        "states/ri/2024/ri1040/pack.yaml",
        6,
        "the same six as the 2023 base — byte-identical widget names, /Ff values, XFA "
        "bind/access attributes and printed captions on the 2024 blank",
    ),
    StateComputed(
        "states/wi/2023/wi_form1/pack.yaml",
        15,
        "the page-2/3/4 name + SSN header MIRRORS (fnamepg2..4, lnamepg2..4, "
        "ss3/ss2/ss4 per page) that WI's JS propagates from page 1. Unmapped they would "
        "file blank — and note verify's clipping scan SKIPS ReadOnly widgets, so these "
        "maxlen 3/2/4 SSN cells are invisible to the P-001 check that exists for exactly "
        "this field shape",
    ),
    StateComputed(
        "states/wv/2023/it140/pack.yaml",
        51,
        "IT-140's JS-computed totals and read-only header repeaters; the validate/timestamp "
        "helper fields are correctly NOT mapped",
    ),
)


def _keeps_by_pack() -> dict[str, dict[str, ReservedKeep]]:
    by_pack: dict[str, dict[str, ReservedKeep]] = {}
    for row in RESERVED_LINE_KEEPS:
        by_pack.setdefault(row.pack, {})[row.line] = row
    return by_pack


def _state_counts() -> dict[str, StateComputed]:
    return {row.pack: row for row in STATE_COMPUTED_READONLY}


# ---------------------------------------------------------------------------
# Offline layer — the tables pinned against the packs themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", RESERVED_LINE_KEEPS, ids=lambda row: f"{_pack_id(FORMPACKS / row.pack)}-{row.line}")
def test_reserved_keep_row_is_really_mapped_to_the_widget_it_names(row: ReservedKeep):
    """P-007: every allowlist row must still describe the pack, or be deleted.

    This is what makes the allowlist self-clearing. A row survives only while
    the pack really maps that line to that widget: unmap the line (or move it
    to another widget) and this fails, forcing the stale row out.
    """
    pack_path = FORMPACKS / row.pack
    assert pack_path.is_file(), (
        f"RESERVED_LINE_KEEPS names {row.pack}, which does not exist — the pack was "
        f"renamed or removed, so delete the row (P-007)"
    )
    pack = load_pack(pack_path)
    by_line = {pf.line: pf.field for pf in pack.fields}
    assert row.line in by_line, (
        f"{row.pack} no longer maps line '{row.line}'. If that was deliberate — the line "
        f"stopped being a printed line, or you decided to EXCLUDE it — delete this "
        f"RESERVED_LINE_KEEPS row and add the pack/line to RESERVED_LINES_UNMAPPED with "
        f"the printed-text reason instead. Kept here because: {row.why} (P-007)"
    )
    assert by_line[row.line] == row.widget, (
        f"{row.pack} line '{row.line}' now binds '{by_line[row.line]}', not the "
        f"allowlisted '{row.widget}'. Re-read the blank's /Ff for the NEW widget before "
        f"trusting this row: a revision can move a reserved line onto an ordinary "
        f"fillable widget (Form 1040 line 30 did exactly that in 2025), in which case the "
        f"row belongs deleted, not updated (P-007)"
    )


@pytest.mark.parametrize(
    "row", RESERVED_LINES_UNMAPPED, ids=lambda row: f"{_pack_id(FORMPACKS / row.pack)}-{row.lines[0]}"
)
def test_reserved_unmapped_row_stays_unmapped_and_the_filler_refuses_it(row: ReservedUnmapped, tmp_path: Path):
    """P-007: the excluded keys must not exist, and fill_form must say so."""
    pack_path = FORMPACKS / row.pack
    assert pack_path.is_file(), f"RESERVED_LINES_UNMAPPED names {row.pack}, which does not exist — delete the row"
    pack = load_pack(pack_path)
    by_line = {pf.line: pf.field for pf in pack.fields}
    for line in row.lines:
        assert line not in by_line, (
            f"{row.pack} now maps '{line}' -> '{by_line[line]}', which this table says must "
            f"stay unmapped because of the PRINTED FACE: {row.why}. If the revision changed "
            f"the printed line (that is exactly what happened to Form 1040-X line 4a in "
            f"Rev. 12-2025), delete this row and add one to RESERVED_LINE_KEEPS quoting the "
            f"new printed text — and re-read the blank's /Ff for the widget while you are "
            f"there, since a line going live usually clears the bit. Never re-map on the "
            f"strength of the flag alone, in either direction (P-007)"
        )
    for line in row.survivors:
        assert line in by_line, (
            f"{row.pack} lost neighbouring line '{line}' — P-007 over-reach. Only the "
            f"specific reserved/shaded cells come out of the map; the rest of the row and "
            f"the lines around it are ordinary fillable boxes"
        )
    # The keys are hard errors now, not silent writes into a locked box.
    # fill_form validates line keys before it opens the blank, so no PDF needed.
    for line in row.lines:
        with pytest.raises(ValueError, match=r"unknown line key"):
            fill_form(pack, {line: 99999}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf")


def test_reserved_line_tables_agree_about_every_contested_line():
    """A `contested_with` claim must be checkable, not prose.

    P-007's own text once asserted that "the 2025 f1040x already excludes line
    4a". It never did — it maps it, correctly, because Rev. 12-2025 un-reserved
    the line. That false claim propagated out of the registry and into an
    agent's task briefing. This test makes the cross-year story data: an
    exclusion row may only claim a split when some OTHER year of the same form
    really does keep that line mapped.
    """
    kept: set[tuple[str, str]] = set()
    for row in RESERVED_LINE_KEEPS:
        form_key = Path(row.pack).parent.name
        kept.add((form_key, row.line))
    for row in RESERVED_LINES_UNMAPPED:
        if row.contested_with is None:
            continue
        form_key = Path(row.pack).parent.name
        assert row.contested_with == form_key, (
            f"{row.pack}: contested_with={row.contested_with!r} but the pack's form is "
            f"{form_key!r} — the split is always between YEARS of one form"
        )
        overlap = sorted(line for line in row.lines if (form_key, line) in kept)
        assert overlap, (
            f"{row.pack} claims lines {list(row.lines)} are a cross-year split, but no "
            f"other year of '{form_key}' keeps any of them in RESERVED_LINE_KEEPS. Either "
            f"the sibling year stopped keeping it (the debt is settled — set "
            f"contested_with=None and say why) or the claim was never true. Do not restate "
            f"a cross-year claim in prose without a row that carries it (P-007)"
        )


def test_reserved_line_tables_are_disjoint_and_free_of_duplicates():
    """No line may be both kept and excluded in the same pack, and no row twice."""
    keep_rows = [(row.pack, row.line) for row in RESERVED_LINE_KEEPS]
    assert len(keep_rows) == len(set(keep_rows)), (
        f"RESERVED_LINE_KEEPS has duplicate (pack, line) rows: "
        f"{sorted({row for row in keep_rows if keep_rows.count(row) > 1})}"
    )
    unmapped_rows = [(row.pack, line) for row in RESERVED_LINES_UNMAPPED for line in row.lines]
    assert len(unmapped_rows) == len(set(unmapped_rows)), (
        f"RESERVED_LINES_UNMAPPED has duplicate (pack, line) rows: "
        f"{sorted({row for row in unmapped_rows if unmapped_rows.count(row) > 1})}"
    )
    both = sorted(set(keep_rows) & set(unmapped_rows))
    assert not both, f"line(s) {both} are listed as BOTH kept and excluded — decide which (P-007)"
    state_packs = [row.pack for row in STATE_COMPUTED_READONLY]
    assert len(state_packs) == len(set(state_packs)), "STATE_COMPUTED_READONLY has duplicate packs"


def test_every_table_row_names_a_discovered_pack_of_the_right_jurisdiction():
    """Stale table rows must surface; and the two tables must not cross lanes."""
    discovered = {_key(path) for path in ALL_PACK_PATHS}
    federal_rows = {row.pack for row in RESERVED_LINE_KEEPS} | {row.pack for row in RESERVED_LINES_UNMAPPED}
    missing = sorted((federal_rows | {row.pack for row in STATE_COMPUTED_READONLY}) - discovered)
    assert not missing, f"table row(s) name packs that no longer exist: {missing} — delete them (P-007)"
    not_federal = sorted(pack for pack in federal_rows if not pack.startswith("federal/"))
    assert not not_federal, (
        f"{not_federal} are state packs in a federal table. State ReadOnly bindings are "
        f"JS-computed fields pinned BY COUNT in STATE_COMPUTED_READONLY, not per widget"
    )
    not_state = sorted(row.pack for row in STATE_COMPUTED_READONLY if not row.pack.startswith("states/"))
    assert not not_state, f"{not_state} are federal packs in STATE_COMPUTED_READONLY"


def test_every_table_row_carries_a_justification():
    """Per-entry justification is the whole point of an allowlist — enforce it."""
    thin = [
        f"{row.pack}:{getattr(row, 'line', None) or row.lines[0]}"
        for row in (*RESERVED_LINE_KEEPS, *RESERVED_LINES_UNMAPPED, *STATE_COMPUTED_READONLY)
        if len(row.why.split()) < 4
    ]
    assert not thin, (
        f"row(s) {thin} have no real justification. An allowlist entry records an "
        f"ADJUDICATION: what the row's printed text says, and why that makes the mapping "
        f"(or the exclusion) right. A flag value is not a reason (P-007)"
    )


def test_readonly_flag_reader_sees_inherited_flags_through_the_field_tree(tmp_path: Path):
    """Prove the mechanism the network layer depends on, offline.

    Real IRS AcroForms keep /Ff on the terminal FIELD dict, not on the widget
    annotation, so a scanner that reads the annotation alone finds nothing —
    and would report an empty ReadOnly set for every pack, turning every
    network assertion in this file into a silent pass.
    """
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, NumberObject

    root = "topmostSubform[0]"
    blank = make_acroform_pdf(
        tmp_path / "readonly_probe.pdf",
        [
            {"name": f"{root}.Page1[0].f1_1[0]", "hierarchical": True},
            {"name": f"{root}.Page1[0].f1_2[0]", "hierarchical": True},
        ],
    )
    # /Ff = 8388609 (DoNotScroll|ReadOnly — the exact value every IRS reserved
    # line carries) on the FIRST field's terminal dict only.
    writer = PdfWriter(clone_from=str(blank))
    for page in writer.pages:
        for annot_ref in page.get("/Annots", []):
            parent = annot_ref.get_object().get("/Parent")
            terminal = parent.get_object() if parent is not None else None
            if terminal is not None and str(terminal.get("/T")) == "f1_1[0]":
                terminal[NameObject("/Ff")] = NumberObject(8388609)
    probe = tmp_path / "readonly_probe_flagged.pdf"
    with probe.open("wb") as handle:
        writer.write(handle)

    names = _read_only_widget_names(probe)
    assert names == {f"{root}.Page1[0].f1_1[0]"}, (
        f"the flag reader returned {sorted(names)} — it must find /Ff bit 1 on the "
        f"TERMINAL FIELD dict by walking /Parent (the real IRS shape), report the FULLY "
        f"QUALIFIED name (that is what gets compared against acroform_root + the pack's "
        f"`field:` value), and must not report the unflagged sibling. Every network "
        f"assertion in this file rests on it"
    )


# ---------------------------------------------------------------------------
# Network layer — the blanks themselves
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize("pack_path", FEDERAL_PACK_PATHS, ids=_pack_id)
def test_federal_pack_maps_no_readonly_widget_outside_the_allowlist(pack_path: Path):
    """P-007, repo-wide: mapped ∩ ReadOnly must equal the allowlist exactly."""
    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    read_only = _read_only_widget_names(Path(blank))
    mapped = {prefix + pf.field: pf.line for pf in pack.fields}
    actual = {name: line for name, line in mapped.items() if name in read_only}

    keeps = _keeps_by_pack().get(_key(pack_path), {})
    expected = {prefix + row.widget: line for line, row in keeps.items()}

    unexpected = sorted(f"line {actual[name]!r} -> {name}" for name in set(actual) - set(expected))
    assert not unexpected, (
        f"{_key(pack_path)} maps ReadOnly widget(s) that no allowlist row covers:\n  "
        + "\n  ".join(unexpected)
        + "\n\nThe flag does NOT settle this — read the row's own printed text off the "
        "blank and pick the class (pitfall P-007):\n"
        "  * the widget already HOLDS an IRS-printed constant (sched_se's wage base, an "
        "f1040es voucher due date) -> never map it; writing would overwrite the form;\n"
        "  * the printed text makes a correct entry IMPOSSIBLE (sched_d 1a/8a 'leave this "
        "line blank and go to line 1b'; sched_e's 'Totals' rows read only by a line that "
        "names the OTHER columns) -> drop the line key so fill_form raises;\n"
        "  * the line is printed and numbered and merely reads 'Reserved for future use' "
        "-> it may stay mapped with a leave-blank comment, so the key survives the "
        "revision that un-reserves it (f1040 line 30 went live in 2025) — then add a row "
        "to RESERVED_LINE_KEEPS quoting the printed text.\n"
        "Also note what will NOT catch a mistake here: fill_form writes ReadOnly widgets "
        "with no warning, and verify's clipping scan SKIPS them on the premise that the "
        "filler never writes them."
    )
    stale = sorted(f"line {expected[name]!r} -> {name}" for name in set(expected) - set(actual))
    assert not stale, (
        f"{_key(pack_path)}: allowlisted widget(s) are no longer ReadOnly in the blank:\n  "
        + "\n  ".join(stale)
        + "\n\nThat is how a reserved line goes LIVE — the IRS clears the bit and gives "
        "the line a real label (Rev. 12-2025 did it to Form 1040-X line 4a). Re-read the "
        "printed row text, wire the line into whatever printed sum now names it, and "
        "DELETE the RESERVED_LINE_KEEPS row (P-007)"
    )
    assert actual == expected, f"{_key(pack_path)}: {actual} != {expected}"


@pytest.mark.network
@pytest.mark.parametrize(
    "row", RESERVED_LINE_KEEPS, ids=lambda row: f"{_pack_id(FORMPACKS / row.pack)}-{row.line}"
)
def test_reserved_keep_rows_still_print_reserved_for_future_use(row: ReservedKeep):
    """The assertion that keeps the allowlist honest: read the printed row.

    A flag-only allowlist is a rubber stamp — it would happily keep a row
    after the IRS turned the line into a real, computed one. So re-extract the
    printed text on the widget's own baseline and require the reserved wording.
    """
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    pack = load_pack(FORMPACKS / row.pack)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    target = prefix + row.widget
    reader = PdfReader(str(blank))
    document = pdfium.PdfDocument(str(blank))
    found: str | None = None
    for index, page in enumerate(reader.pages):
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget" or _qualified_name(annot) != target:
                continue
            rect = [float(value) for value in annot["/Rect"]]
            middle = (min(rect[1], rect[3]) + max(rect[1], rect[3])) / 2
            # A 4pt band on the widget's own baseline. A naive full-rect band
            # straddles two printed rows and mis-attributes the text by one row.
            raw = document[index].get_textpage().get_text_bounded(
                left=0, bottom=middle - 2.0, right=max(rect[0], rect[2]) + 8, top=middle + 2.0
            )
            found = " ".join(raw.split())
            break
        if found is not None:
            break

    assert found is not None, (
        f"{row.pack}: widget '{target}' is not in the blank at all — the revision moved or "
        f"renamed it, so re-derive the binding before trusting this row (P-007)"
    )
    assert RESERVED_TEXT in found, (
        f"{row.pack} line '{row.line}' is allowlisted as a reserved printed line, but its "
        f"printed row now reads {found!r} — it is no longer '{RESERVED_TEXT}'. The line has "
        f"a real meaning now: map it properly, wire it into the printed sum that names it, "
        f"and DELETE the RESERVED_LINE_KEEPS row. Kept until now because: {row.why} (P-007)"
    )


@pytest.mark.network
@pytest.mark.parametrize("pack_path", STATE_PACK_PATHS, ids=_pack_id)
def test_state_pack_readonly_mapped_count_matches_the_pinned_audit(pack_path: Path):
    """State packs: the JS-computed ReadOnly bindings are pinned by count."""
    pack = load_pack(pack_path)
    try:
        blank = fetch_blank(pack.source_url, sha256=pack.pdf_sha256)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")

    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    read_only = _read_only_widget_names(Path(blank))
    hits = sorted(
        f"line {pf.line!r} -> {prefix + pf.field}"
        for pf in pack.fields
        if prefix + pf.field in read_only
    )
    key = _key(pack_path)
    pinned = _state_counts().get(key)
    expected = pinned.count if pinned is not None else 0
    assert len(hits) == expected, (
        f"{key} maps {len(hits)} ReadOnly widget(s); the pinned audit says {expected}.\n"
        + ("sample:\n  " + "\n  ".join(hits[:12]) + "\n" if hits else "")
        + "\nA state DOR sets ReadOnly on fields its own JavaScript owns — running totals "
        "and page-2/3/4 name/SSN mirrors — and taxfill never runs that JavaScript, so "
        "those fields MUST stay mapped or they ship blank. That makes growth here "
        "plausible but never silent: re-run the sweep, confirm each NEW binding is a "
        "computed/mirrored field on a white printed box (not a shaded 'no entry' cell, and "
        "not a widget that already holds a DOR-printed constant), then update the count and "
        "its justification in STATE_COMPUTED_READONLY. Remember verify's clipping scan "
        "SKIPS ReadOnly widgets, so nothing downstream will catch a bad value here "
        "(P-007, and P-001 for the SSN-shaped mirrors)."
    )


def _qualified_name(node) -> str:
    """Fully qualified AcroForm name of a widget, by walking /Parent."""
    parts: list[str] = []
    hops = 0
    while node is not None and hops < 64:
        title = node.get("/T")
        if title:
            parts.append(str(title))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
        hops += 1
    return ".".join(reversed(parts))
