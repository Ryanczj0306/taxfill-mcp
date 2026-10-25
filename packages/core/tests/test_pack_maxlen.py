"""Phase J JEa — a pack's ``maxlen`` tracks its widget's own /MaxLen (formpacks/CONVENTIONS.md, "maxlen").

The filler enforces the PACK maxlen. A pack maxlen ABOVE the widget's /MaxLen lets a value through that the PDF then
silently truncates — the NY IT-203 2025 line-35 box held 4 characters under a pack maxlen of 10 until this gate.
A pack maxlen BELOW the widget's is a deliberate budget only when the printed box cannot hold the widget's count (a
one-character account cell with a DOR /MaxLen of 10); each such row is adjudicated below with the measured box, and
the table self-clears. A text line whose widget has a /MaxLen but whose pack declares none is left to verify's hard
MaxLen check. Network-marked like the ReadOnly sweeps: it reads each pinned blank (cache or download).

A widget with NO /MaxLen is invisible to that sweep, so a budget measured on a probe render of its box is pinned in
MEASURED_WITHOUT_MAXLEN with the box it was measured on and the probe it was measured with (JK27 / JK28, 2026-10-16):
digits for a numeric box, capitals for a name or code box, the date shape for a Helvetica date box, the legible size
for an auto-size box. The pack must carry the pinned budget, the probe's font metrics must agree with the render, one
box carries one budget in every year, and the network layer re-reads the box so a re-issue forces a re-measure.
"""
from __future__ import annotations

import re
import string
from pathlib import Path
from typing import NamedTuple

import pytest

from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.overlay import text_width
from taxfill_core.schemas.formpack import load_pack
from taxfill_core.verify import bound_widget_names, read_text_widgets
from taxfill_core.textfit import _RSB_COURIER, CUT_TOLERANCE_PT, DEFAULT_FONT_SIZE, ink_extent

FORMPACKS = Path(__file__).resolve().parents[3] / "formpacks"
PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))

# (pack, line) -> why the pack budget is tighter than the widget's /MaxLen. The box width and /DA font are the
# pinned blank's; "fits" is what verify's width check holds. Rows written before Phase K JEe (2026-10-24) measured it
# edge to edge (width / (0.5 x font size), 0.6 for Courier); since JEe the value's ink must end inside the border the
# viewer draws (1 pt a side), so a budget that filled its box exactly was cut by one glyph (the AL Courier cells, ID
# preparer.state, MA 43a). test_every_tighter_budget_fits_its_box_by_the_ink_model re-checks every budget.
TIGHTER_THAN_WIDGET: dict[tuple[str, str], str] = {
    **{(f"states/ar/{y}/ar1000f/pack.yaml", "direct_deposit_2.account.17"):
       "the 17th one-character account-number cell (14.6 pt at 9 pt, fits 3); cells 1-16 carry /MaxLen 1, this "
       "one the DOR's 10" for y in (2023, 2024, 2025)},
    ("states/al/2024/al40/pack.yaml", "FIRSTNAME"):
        "the taxpayer's first-name box (98.6 pt at Courier 12 fits 13); the widget says 20",
    ("states/al/2024/al40/pack.yaml", "SPOUSEFIRSTNAME"):
        "the spouse's first-name box (98.6 pt at Courier 12 fits 13); the widget says 20",
    ("states/al/2024/al40/pack.yaml", "SCHHBCPTILINE2"):
        "Schedule HBC line 2 Date Account Opened (147.8 pt at Courier 10 fits 24); the widget says 30",
    ("states/al/2024/al40/pack.yaml", "SCHHBCPTILINE5"):
        "Schedule HBC line 5 Financial Institution Name, a short box on a full-width row (128.0 pt at Courier 8 "
        "fits 26); the widget says 30",
    ("states/al/2024/al40/pack.yaml", "SCHHBCPTILINE6"):
        "Schedule HBC line 6 Date Account Opened (147.9 pt at Courier 10 fits 24); the widget says 30",
    ("states/al/2024/al40/pack.yaml", "SCHOCLINE1PC"):
        "Schedule OC line C1 Department of Education certification number (117.5 pt at Courier 10 fits 19); the widget says 20",
    ("states/al/2024/al40/pack.yaml", "SCHOCLINE2CPL"):
        "Schedule OC line L2's second address-row cell (54.0 pt at Courier 10 fits 8 inside its border); the widget says 15",
    ("states/al/2024/al40/pack.yaml", "SCHAATCLN6"):
        "Schedule AATC line 6 date of enrollment (147.8 pt at Courier 10 fits 24); the widget says 30",
    **{("states/al/2024/al40/pack.yaml", k): f"a Schedule AAC Part I / II row cell ({w} pt at Courier 9 fits {n}); the widget says {m}"
       for k, w, n, m in (
           ("SCHAACPRTILN1", 116.7, 21, 30),
           ("SCHAACPRTILN3", 81.7, 14, 30),
           ("SCHAACPRTILN4", 118.6, 21, 30),
           ("SCHAACPRTILN5", 149.6, 27, 30),
           ("SCHAACPRTILN6", 180.8, 33, 60),
           ("SCHAACPRTILN7", 116.7, 21, 30),
           ("SCHAACPRTILN9", 81.7, 14, 30),
           ("SCHAACPRTILN10", 118.6, 21, 30),
           ("SCHAACPRTILN11", 149.6, 27, 30),
           ("SCHAACPRTILN12", 180.8, 33, 60),
           ("SCHAACPRTILN13", 116.7, 21, 30),
           ("SCHAACPRTILN15", 81.7, 14, 60),
           ("SCHAACPRTILN16", 118.6, 21, 30),
           ("SCHAACPRTILN17", 149.6, 27, 30),
           ("SCHAACPRTILN18", 180.8, 33, 60),
           ("SCHAACPRTILN19", 116.7, 21, 30),
           ("SCHAACPRTILN22", 118.6, 21, 30),
           ("SCHAACPRTILN23", 149.6, 27, 30),
           ("SCHAACPRTILN24", 180.8, 33, 60),
           ("SCHAACPRTILN25", 116.7, 21, 30),
           ("SCHAACPRTILN28", 118.6, 21, 30),
           ("SCHAACPRTILN29", 149.6, 27, 30),
           ("SCHAACPRTILN30", 180.8, 33, 60),
           ("SCHAACPRTIILN1", 116.6, 21, 30),
           ("SCHAACPRTIILN3", 81.7, 14, 30),
           ("SCHAACPRTIILN4", 118.6, 21, 30),
           ("SCHAACPRTIILN5", 149.6, 27, 30),
           ("SCHAACPRTIILN6", 180.8, 33, 60),
           ("SCHAACPRTIILN7", 116.6, 21, 30),
           ("SCHAACPRTIILN9", 81.7, 14, 30),
           ("SCHAACPRTIILN10", 118.6, 21, 30),
           ("SCHAACPRTIILN11", 149.6, 27, 30),
           ("SCHAACPRTIILN12", 180.8, 33, 60),
           ("SCHAACPRTIILN13", 116.6, 21, 30),
           ("SCHAACPRTIILN15", 81.7, 14, 60),
           ("SCHAACPRTIILN16", 118.6, 21, 30),
           ("SCHAACPRTIILN17", 149.6, 27, 30),
           ("SCHAACPRTIILN18", 180.8, 33, 60),
           ("SCHAACPRTIILN19", 116.6, 21, 30),
           ("SCHAACPRTIILN22", 118.6, 21, 30),
           ("SCHAACPRTIILN23", 149.6, 27, 30),
           ("SCHAACPRTIILN24", 180.8, 33, 60),
           ("SCHAACPRTIILN25", 116.6, 21, 30),
           ("SCHAACPRTIILN28", 118.6, 21, 30),
           ("SCHAACPRTIILN29", 149.6, 27, 30),
           ("SCHAACPRTIILN30", 180.8, 33, 60))},
    **{("states/al/2024/al40/pack.yaml", f"SCHRSILN{i}"): "Schedule RS Part I column I Reason Exempt (111.9 pt at Courier 8 fits 22 inside its border); the widget says 30"
       for i in range(1, 8)},
    ("states/ar/2023/ar1000nr/pack.yaml", "7b.count"):
        "the 7B dependent count (13.3 pt box, auto-size font); the 7A count box ARNR-49 carries /MaxLen 2, this one "
        "the DOR's 10",
    ("states/ca/2025/form540nr/pack.yaml", "7.count"): "a one-digit exemption count (14.0 pt at Helv 10 fits 2); the widget says 11",
    ("states/id/2023/form40/pack.yaml", "preparer.state"): "31.5 pt at Arial 10 fits 4 capitals inside its border; the widget says 10",
    ("states/ks/2023/k40/pack.yaml", "42.school_district_number"): "42 pt at Courier 12 fits 5; the widget says 10",
    ("states/ks/2023/k40/pack.yaml", "43.historic_site_number"): "42 pt at Courier 12 fits 5; the widget says 10",
    ("states/ks/2024/k40/pack.yaml", "42.school_district_number"): "42.0 pt at Courier 12 (7.2 pt a glyph) fits 5; budget 5 as in 2023; the widget says 10",
    ("states/ks/2024/k40/pack.yaml", "43.historic_site_number"): "42.0 pt at Courier 12 fits 5; budget 5 as in 2023 (the same box and /MaxLen); the widget says 10",
    ("states/ks/2025/k40/pack.yaml", "41.school_district_number"):
        "43.3 pt at Courier 12 (7.2 pt a glyph) fits 6 edge to edge with no inset; budget 5 as in 2023; the widget says 10",
    ("states/ks/2025/k40/pack.yaml", "42.historic_site_number"):
        "42.0 pt at Courier 12 fits 5 (the widget is still named '43 Historic Site number'); the widget says 10",
    ("states/ma/2023/form1/pack.yaml", "43a"): "12.5 pt at Helv 12 fits 1 digit inside its border (a count of EIC children); the widget says 10",
    ("states/ma/2025/form1/pack.yaml", "43a"): "12.5 pt at Helv 12 fits 1 digit inside its border; the widget says 10 (the same box as 2023)",
    ("states/md/2023/md502/pack.yaml", "mailing_state"): "a two-letter state code (19.3 pt at Courier 10 fits 3)",
    ("states/md/2025/md502/pack.yaml", "mailing_state"): "a two-letter state code (17.2 pt at Courier 10 fits 3); the widget says 10",
    ("states/md/2025/md502/pack.yaml", "spouse_middle_initial"): "a middle initial (14.3 pt at Courier 10 fits 2); the widget says 10",
    ("states/md/2025/md502/pack.yaml", "local_tax_rate"):
        "the digits after the printed '.0' of a local rate (.0320 -> 320); 21.6 pt at Courier 10 holds 3 glyphs of 6 pt "
        "(the 0.5-em budget says 4); the widget says 10",
    ("states/md/2025/md502/pack.yaml", "military_income_amount_cents"):
        "the two-digit cents cell after the printed decimal point (16.6 pt at Courier 10 fits 3); the widget says 10",
    ("states/me/2023/f1040me/pack.yaml", "tax_period.begin.month"): "a two-digit month (25.7 pt at 10 pt fits 5)",
    ("states/me/2023/f1040me/pack.yaml", "tax_period.begin.day"): "a two-digit day (25.6 pt at 10 pt fits 5)",
    ("states/me/2024/f1040me/pack.yaml", "tax_period.begin.month"): "a two-digit month; the widget says 10",
    ("states/me/2024/f1040me/pack.yaml", "tax_period.begin.day"): "a two-digit day; the widget says 10",
    ("states/me/2025/f1040me/pack.yaml", "tax_period.begin.month"): "a two-digit month (25.7 pt at 10 pt fits 5)",
    ("states/me/2025/f1040me/pack.yaml", "tax_period.begin.day"): "a two-digit day (25.6 pt at 10 pt fits 5)",
    ("states/me/2025/f1040me/pack.yaml", "mailing_address.zip"):
        "a ZIP or ZIP+4, 10 glyphs; 72.1 pt at Arial 10 fits 14; the widget says 15 (5 in 2023)",
    ("states/ne/2025/f1040n/pack.yaml", "64b"):
        '64b "Type of Account" takes one digit ("1 = Checking 2 = Savings"); the box is 18.5 pt wide, cut into 10 comb '
        "cells of 1.85 pt (the digit lands on cell 1); the widget says 10",
    ("states/ms/2025/f80105/pack.yaml", "preparer.address"): "107.6 pt at Courier 10 fits 17; the widget says 25",
    ("states/ms/2025/f80105/pack.yaml", "preparer.city"): "83.0 pt at Courier 12 fits 11; the widget says 21",
    **{("states/oh/2025/it1040_oh/pack.yaml", f"schedJ_dep{i}_dob"):
       "a dependent's date of birth printed (MM-DD-YYYY), 10 glyphs; the box (75.5 pt on page 9, 75.3 pt on "
       "page 10, at Courier 12) fits 10; the widget says 15" for i in range(1, 16)},
    ("states/oh/2023/it1040_oh/pack.yaml", "preparer_printed_name"):
        "the preparer's printed-name box (153.6 pt at Courier New Bold 12: 7.2 pt a glyph) fits 21 — a 600 dpi probe "
        "render cuts the 22nd 1 pt inside the right edge (JK28); the widget says 25, and the 2024 / 2025 box, the same "
        "rect and /DA without a /MaxLen, is pinned in MEASURED_WITHOUT_MAXLEN",
    ("states/vt/2024/in111/pack.yaml", "15.whole"):
        'the digits left of line 15\'s printed decimal point ("100.0000%"); 32.3 pt at Courier 12 fits 4; the widget says 9',
    ("states/vt/2024/in111/pack.yaml", "15.decimal"):
        "the four digits right of that decimal point; 39.4 pt at Courier 12 fits 5; the widget says 9",
    ("states/vt/2024/in111/pack.yaml", "physical_address.street"):
        "the 911/physical street box, 203.7 pt at Courier 12 fits 28; the widget says 36 (same rect and /MaxLen as 2023)",
    ("states/vt/2024/in111/pack.yaml", "foreign_country"):
        "the Foreign Country box, 203.7 pt at Courier 12 fits 28; the widget says 32 (same rect and /MaxLen as 2023)",
    **{("states/vt/2024/in111/pack.yaml", k):
       'a "Date (MMDDYYYY)" box, 8 digits; the two signature-date boxes are 67.6 pt at Courier 12 (fit 9), the DOB and '
       "preparer-date boxes 81.3 pt (fit 11); the widget says 10"
       for k in ("signature.taxpayer_date", "signature.taxpayer_dob", "signature.spouse_date",
                 "signature.spouse_dob", "preparer.date")},
    ("states/vt/2025/in111/pack.yaml", "15.whole"):
        'the digits left of line 15\'s printed decimal point ("100.0000%"); 32.3 pt at Courier 12 fits 4; the widget says 9',
    ("states/vt/2025/in111/pack.yaml", "15.decimal"):
        "the four digits right of that decimal point; 39.4 pt at Courier 12 fits 5; the widget says 9",
    ("states/vt/2025/in111/pack.yaml", "physical_address.street"):
        "the 911/physical street box, 203.7 pt at Courier 12 fits 28; the widget says 36 (same rect and /MaxLen as 2023)",
    ("states/vt/2025/in111/pack.yaml", "foreign_country"):
        "the Foreign Country box, 203.7 pt at Courier 12 fits 28; the widget says 32 (same rect and /MaxLen as 2023)",
    **{("states/vt/2025/in111/pack.yaml", k):
       'a "Date (MMDDYYYY)" box, 8 digits; the two signature-date boxes are 67.6 pt at Courier 12 (fit 9), the DOB and '
       "preparer-date boxes 81.3 pt (fit 11); the widget says 10"
       for k in ("signature.taxpayer_date", "signature.taxpayer_dob", "signature.spouse_date",
                 "signature.spouse_dob", "preparer.date")},
    ("states/ms/2024/f80105/pack.yaml", "preparer.address"): "107.6 pt at Courier 10 fits 17; the widget says 25",
    ("states/ms/2024/f80105/pack.yaml", "preparer.city"): "83.0 pt at Courier 12 fits 11; the widget says 21",
    **{("states/mt/2024/form2/pack.yaml", k):
       "a page-2 printed-name box, 323.9 pt at Courier 10 fits 53; the widget says 55"
       for k in ("preparer.name", "third_party_designee.name")},
    ("states/wv/2023/it140/pack.yaml", "name.suffix"): "a name suffix (JR / III); 25.5 pt at Courier 10 fits 4",
    ("states/wv/2024/it140/pack.yaml", "name.suffix"):
        "a name suffix (JR / III); the 2024 widget is the 2023 one (/MaxLen 6, 25.5 pt at Courier 10 fits 4)",
    ("states/ia/2025/ia1040/pack.yaml", "21.fish_wildlife"):
        "the line-21 Fish/Wildlife contribution dollars box, 15.8 pt at Calibri 10; the filler clips 2 pt inside each side, so 3 digits clip on render and 2 fit; the widget says 4 (2023: 27.3 pt)",
    ("states/ia/2025/ia1040/pack.yaml", "21.child_abuse"):
        "the line-21 Child Abuse Prevention contribution dollars box, 15.1 pt at Calibri 10; the filler clips 2 pt inside each side, so 3 digits clip on render and 2 fit; the widget says 4 (2023: 27.4 pt)",
    # the same three one-digit cells on the 2023 and 2024 blanks (identical rects and /DA; tightened 2026-10-02
    # when the 2025 port's verifier found them)
    **{(f"states/nj/{y}/nj1040/pack.yaml", k): (
        f"the thousands digit, one printed cell ({w} pt at 9 pt, fits 3); its row neighbours carry /MaxLen 1, this "
        "comb widget the DOR's 2")
       for y in (2023, 2024)
       for k, w in (("line63_pass_through_business_alt_income_tax_credit_d05", "15.6"),
                    ("line64_child_dependent_care_credit_d01", "16.0"), ("line65_nj_child_tax_credit_d01", "14.9"))},
    ("states/nj/2025/nj1040/pack.yaml", "line63_pass_through_business_alt_income_tax_credit_d05"):
        "the thousands digit, one printed cell (15.6 pt at 9 pt, fits 3); its row neighbours carry /MaxLen 1, this "
        "comb widget the DOR's 2",
    ("states/nj/2025/nj1040/pack.yaml", "line64_child_dependent_care_credit_d01"):
        "the thousands digit, one printed cell (16.0 pt at 9 pt, fits 3); its row neighbours carry /MaxLen 1, this "
        "comb widget the DOR's 2",
    ("states/nj/2025/nj1040/pack.yaml", "line65_nj_child_tax_credit_d01"):
        "the thousands digit, one printed cell (14.9 pt at 9 pt, fits 3); its row neighbours carry /MaxLen 1, this "
        "comb widget the DOR's 2",
    # AL Form 40NR 2023 (JS5, a NEW pack): Courier boxes too narrow for the DOR's /MaxLen; the budget is verify's 0.6-em
    # Courier metric, width / (0.6 x font size).
    ("states/al/2023/al40nr/pack.yaml", "FIRSTNAME"): "the page-1 first name, 98.6 pt at Courier 12 fits 13; the widget says 20",
    ("states/al/2023/al40nr/pack.yaml", "LASTNAME"): "the page-1 last name, 135.6 pt at Courier 12 fits 18; the widget says 20",
    ("states/al/2023/al40nr/pack.yaml", "SPOUSEFIRSTNAME"): "the page-1 spouse's first name, 98.6 pt at Courier 12 fits 13; the widget says 20",
    ("states/al/2023/al40nr/pack.yaml", "SPOUSELASTNAME"): "the page-1 spouse's last name, 135.6 pt at Courier 12 fits 18; the widget says 30",
    ("states/al/2023/al40nr/pack.yaml", "SCHOCLINE1PC"): "a Schedule OC (page 7) text box, 117.5 pt at Courier 10 fits 19; the widget says 20",
    ("states/al/2023/al40nr/pack.yaml", "SCHOCLINE2CPL"): "a Schedule OC (page 9) text box, 54.0 pt at Courier 10 fits 8 inside its border; the widget says 15",
    ("states/al/2023/al40nr/pack.yaml", "SCHAATCLN6"): "a Schedule AATC (page 14) text box, 147.8 pt at Courier 10 fits 24; the widget says 30",
    # the Schedule AAC (page 15) Part I / II adoptee grid (Courier 9, centred): one glyph under verify's budget (two in
    # column C) so the centred text clears the printed bullet at each cell's left edge on the render
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column A, 116.6 pt at Courier 9 fits 21, held to 20 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTILN1", "SCHAACPRTILN7", "SCHAACPRTILN13", "SCHAACPRTILN19", "SCHAACPRTILN25")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column C, 81.7 pt at Courier 9 fits 15, held to 13 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTILN3", "SCHAACPRTILN9")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column C, 81.7 pt at Courier 9 fits 15, held to 13 to clear the bullet; the widget says 60"
       for k in ("SCHAACPRTILN15",)},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column D, 118.6 pt at Courier 9 fits 21, held to 20 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTILN4", "SCHAACPRTILN10", "SCHAACPRTILN16", "SCHAACPRTILN22", "SCHAACPRTILN28")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column E, 149.6 pt at Courier 9 fits 27, held to 26 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTILN5", "SCHAACPRTILN11", "SCHAACPRTILN17", "SCHAACPRTILN23", "SCHAACPRTILN29")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part I column F, 180.8 pt at Courier 9 fits 33, held to 32 to clear the bullet; the widget says 60"
       for k in ("SCHAACPRTILN6", "SCHAACPRTILN12", "SCHAACPRTILN18", "SCHAACPRTILN24", "SCHAACPRTILN30")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column A, 116.6 pt at Courier 9 fits 21, held to 20 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTIILN1", "SCHAACPRTIILN7", "SCHAACPRTIILN13", "SCHAACPRTIILN19", "SCHAACPRTIILN25")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column C, 81.7 pt at Courier 9 fits 15, held to 13 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTIILN3", "SCHAACPRTIILN9")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column C, 81.7 pt at Courier 9 fits 15, held to 13 to clear the bullet; the widget says 60"
       for k in ("SCHAACPRTIILN15",)},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column D, 118.6 pt at Courier 9 fits 21, held to 20 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTIILN4", "SCHAACPRTIILN10", "SCHAACPRTIILN16", "SCHAACPRTIILN22", "SCHAACPRTIILN28")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column E, 149.6 pt at Courier 9 fits 27, held to 26 to clear the bullet; the widget says 30"
       for k in ("SCHAACPRTIILN5", "SCHAACPRTIILN11", "SCHAACPRTIILN17", "SCHAACPRTIILN23", "SCHAACPRTIILN29")},
    **{("states/al/2023/al40nr/pack.yaml", k): "Part II column F, 180.8 pt at Courier 9 fits 33, held to 32 to clear the bullet; the widget says 60"
       for k in ("SCHAACPRTIILN6", "SCHAACPRTIILN12", "SCHAACPRTIILN18", "SCHAACPRTIILN24", "SCHAACPRTIILN30")},
    **{("states/al/2023/al40nr/pack.yaml", f"SCHRSILN{i}"): (
       "Schedule RS Part I (page 32) \"Reason Exempt\", 111.9 pt at Courier 8 fits 23, held to 22: the box is right-aligned "
       "and its printed bullet (x 658.5-664.7) overlaps the box's left edge (x 662.4), so a 23rd glyph lands on it; the widget says 30")
       for i in range(1, 8)},
}

# (pack, line) -> the budget of a text line whose widget has NO /MaxLen, measured on a probe render of its box (JK27
# measured the CA address rows; JK28 the tier-1 TY2025 packs and the same boxes in their 2023 / 2024 packs, 2026-10-16).
# fill_form writes probe strings of growing length into the cached blank (the pack's maxlen lifted), render.py draws the
# box at 600 dpi, and each render is compared with the same string in a copy of the box widened so nothing clips. The
# renderer's form layer (pdfium, render.py init_forms) regenerates the appearance and draws the value from the 1 pt
# border inward, clipping 1 pt inside the edge, so a value whose advance fits the box width less 2 pt renders whole (a
# centred box overflows at both ends, a left-aligned one at the right). The probe follows what the box holds:
#   "digits"    a numeric box (SSN, FEIN, ZIP, apartment number, a one-digit cell): every Helvetica digit advances
#               0.556 em, every Courier glyph 0.6 em;
#   "capitals"  a name, initial or state-code box: a cycle of the capitals A-Z, because an all-caps entry is the widest
#               realistic case (mixed case fits more), checked against Helvetica's own capital widths (Adobe's Core-14
#               AFM, overlay.text_width), which hold one or two capitals fewer than digits in the same box;
#   "MM/DD/YY"  a Helvetica date box: the date shape, with its two 0.278 em slashes, renders whole where 8 bare digits do
#               not, so the budget is the shape's 8 characters and `why` says how many bare digits fit (the engine has
#               no date format to refuse "MMDDYYYY"). A Courier date box needs no shape: digits and separators are all
#               0.6 em, so its digit count is exact.
# An auto-size box (/DA "0 Tf", size 0) never cuts: the viewer shrinks the text (the MA 43c probes drew at 10, 9.3, 6.3 and 4.2 pt), so its
# fit is the longest probe still drawn at LEGIBLE_PT or more. `fits` is the fit when the pack keeps a tighter budget (a
# one-character cell, a dashed SSN); None means the budget is the fit. A fit counts advances, and the render confirms it
# whole; the render can draw one glyph more when the side bearings absorb a sub-glyph overflow (NC's 143.0 pt Courier
# box draws a 17th digit whose advance overruns by 1.8 pt), a margin another glyph or viewer need not leave.
class Measured(NamedTuple):
    """One box's probe-render budget (a text widget with no /MaxLen)."""

    budget: int  # the pack maxlen
    width: float  # the box width, pt (the narrowest widget when the field repeats on several pages)
    size: float  # the /DA font size, pt; 0 = auto-size
    why: str
    probe: str = "digits"  # "digits", "capitals" or a date shape such as "MM/DD/YY"
    face: str = "Helvetica"  # the /DA font's metrics: "Helvetica" (Helv, Arial) or "Courier" (Cour, Courier New)
    fits: int | None = None  # the probe count the box holds, when the pack keeps a tighter budget


# The CA "Apt. no/ste. no." and "PMB/private mailbox" boxes keep one rect and /DA (Helv 10) in 2023-2025 on the 540 and
# the 540NR alike, yet the 540NR packs budgeted 14 (2023), 12 (2024) and 13 (2025): a 600 dpi probe of every blank
# renders 12 digits whole and cuts the 13th 1 pt inside the right edge (its ink 29 px in the Apt. box, 33 px in the PMB
# box, against 39 px for the same digit whole), and a 14th never shows. (An all-caps entry fits 11, 11 and 10:
# CAPITALS_AND_DIGITS_ON_THE_RENDER below.)
_CA_BOX_WHY = "{w} pt at Helv 10: 12 digits (66.7 pt) render whole, the 13th is cut 1 pt inside the right edge"
_NJ_CELL_WHY = "a one-digit cell ({w} pt at Helv 9): 2 digits render whole, a third is cut; budget 1"
MEASURED_WITHOUT_MAXLEN: dict[tuple[str, str], Measured] = {
    **{(f"states/ca/{y}/form540nr/pack.yaml", "mailing_address.apt_no"): Measured(12, 72.5, 10.0, _CA_BOX_WHY.format(w=72.5))
       for y in (2023, 2024, 2025)},
    # the 2023 540NR PMB box (and every 2023 540 address box) still carried a /MaxLen, which the sweep above tracks
    **{(f"states/ca/{y}/form540nr/pack.yaml", "mailing_address.pmb"): Measured(12, 73.0, 10.0, _CA_BOX_WHY.format(w=73.0))
       for y in (2024, 2025)},
    **{(f"states/ca/{y}/form540/pack.yaml", "mailing_address.apt_no"): Measured(12, 72.5, 10.0, _CA_BOX_WHY.format(w=72.5))
       for y in (2024, 2025)},
    **{(f"states/ca/{y}/form540/pack.yaml", "mailing_address.pmb"): Measured(12, 73.0, 10.0, _CA_BOX_WHY.format(w=73.0))
       for y in (2024, 2025)},
    **{(f"states/ca/{y}/form540/pack.yaml", "principal_residence.apt_no"):
       Measured(12, 70.7, 10.0, _CA_BOX_WHY.format(w=70.7)) for y in (2024, 2025)},
    # --- JK28: the tier-1 TY2025 packs, and the same box (rect and /DA) in their 2023 / 2024 packs ---
    **{(f"states/ga/{y}/ga500/pack.yaml", "voucher.state"): Measured(
        2, 18.78, 8.5, "the payment voucher's STATE box, a ReadOnly mirror the pack maps (18.8 pt, centred, at "
        "Courier 8.5): 3 capitals render whole, a 4th is cut at both ends; budget 2, the state code",
        "capitals", "Courier", fits=3) for y in (2023, 2024, 2025)},
    # IL-1040 2025 re-drew its step 1 boxes in Arial 9 (Helvetica's metrics) without the /MaxLen the 2023 / 2024 Helv 8
    # boxes carry
    **{("states/il/2025/il1040/pack.yaml", k): Measured(
        11, 117.36, 9.0, f"the {who} SSN box (117.4 pt at Arial 9): 23 digits render whole, the 24th is cut 1 pt "
        "inside the right edge; budget 11, a dashed SSN", fits=23)
       for k, who in (("tp_ssn", "taxpayer's"), ("spouse_ssn", "spouse's"))},
    ("states/il/2025/il1040/pack.yaml", "zip_or_postal_code"): Measured(
        10, 79.56, 9.0, "the ZIP or postal code box (79.6 pt at Arial 9): 15 digits render whole (an all-caps postal "
        "code 13), the 16th is cut; budget 10, a ZIP+4", fits=15),
    ("states/il/2025/il1040/pack.yaml", "preparer_firm_fein"): Measured(
        10, 127.44, 9.0, "the paid preparer's firm FEIN box (127.4 pt at Helv 9): 25 digits render whole, the 26th is "
        "cut; budget 10, a dashed FEIN", fits=25),
    **{(f"states/ma/{y}/form1/pack.yaml", k): Measured(
        8, 53.61, 12.0, "53.6 pt at Helv 12, the box printing its own '/ /': MM/DD/YY (46.7 pt) renders whole on "
        "them; 8 bare digits (53.4 pt) print over the slashes and lose the 8th; 7 fit", "MM/DD/YY")
       for y in (2023, 2025) for k in ("tp_signature_date", "spouse_signature_date")},
    **{(f"states/ma/{y}/form1/pack.yaml", "43_multiplier"): Measured(
        3, 18.0, 0.0, "line 43c's rate blank (18.0 pt, auto-size Helv): pdfium draws 1-2 digits at 10 pt, 3 at 9 pt, "
        "4 at 6 pt and 5 at 4 pt, so 4 stay legible; budget 3 ('40%' draws at 6 pt)", fits=4) for y in (2023, 2025)},
    **{(f"states/mi/{y}/mi1040/pack.yaml", k): Measured(
        1, 18.66, 10.0, "a middle-initial box (18.7 pt, centred, at Helv 10): 2 capitals render whole, a third is "
        "cut at both ends; budget 1, the initial", "capitals", fits=2)
       for y in (2023, 2024, 2025) for k in ("filer_middle_initial", "spouse_middle_initial")},
    **{(f"states/nc/{y}/d400/pack.yaml", "tp_ssn"): Measured(
        11, 143.0, 14.0, "the SSN on page 2 (158.7 pt) and in the page-3 header (143.0 pt), centred at Courier 14 "
        "(8.4 pt a glyph): the narrower box holds 16 digits (the render even draws a 17th whole, its side bearings "
        "absorbing the 1.8 pt overflow); budget 11, a dashed SSN", face="Courier", fits=16)
       for y in (2023, 2024, 2025)},
    **{(f"states/nc/{y}/d400/pack.yaml", "spouse_ssn"): Measured(
        11, 164.33, 14.0, "the spouse's SSN on page 2 (164.3 pt, centred, at Courier 14): 19 digits render whole, the "
        "20th is cut at both ends; budget 11, a dashed SSN", face="Courier", fits=19) for y in (2023, 2024, 2025)},
    **{(f"states/nc/{y}/d400/pack.yaml", "preparer_signature_date"): Measured(
        8, 50.99, 9.0, "the preparer's date (51.0 pt, centred, at Courier 9: 5.4 pt a glyph, digits and separators "
        "alike): 9 render whole, MM/DD/YYYY's 10 are cut at both ends; budget 8, MM-DD-YY", face="Courier", fits=9)
       for y in (2023, 2024, 2025)},
    # the 2023 / 2024 fiscal-month (13.2 pt) and veteran-count (15.8 pt) cells are other boxes, not measured here
    ("states/nj/2025/nj1040/pack.yaml", "fiscal_year_end_month_d2"): Measured(
        1, 14.42, 9.0, _NJ_CELL_WHY.format(w=14.4), fits=2),
    ("states/nj/2025/nj1040/pack.yaml", "exemption_9_veteran_count"): Measured(
        1, 14.7, 9.0, _NJ_CELL_WHY.format(w=14.7), fits=2),
    **{(f"states/nj/{y}/nj1040/pack.yaml", k): Measured(1, 14.75, 9.0, _NJ_CELL_WHY.format(w=14.75), fits=2)
       for y in (2023, 2024, 2025)
       for k in ("line42_nj_taxable_income_d05", "line42_nj_taxable_income_d06", "line56_property_tax_credit_d01")},
    # the 2023 box is the same box size and /DA with a /MaxLen 25 the box cannot hold: TIGHTER_THAN_WIDGET pins its 21
    **{(f"states/oh/{y}/it1040_oh/pack.yaml", "preparer_printed_name"): Measured(
        21, 153.59, 12.0, "the preparer's printed-name box (153.6 pt at Courier New Bold 12: 7.2 pt a glyph): 21 "
        "capitals render whole, the 22nd is cut 1 pt inside the right edge (the 2024 pack said 25 until JK28)",
        "capitals", "Courier") for y in (2024, 2025)},
    **{(f"states/va/{y}/va760/pack.yaml", "your_signature_date"): Measured(
        8, 43.9, 10.0, "43.9 pt at Helv 10: MM/DD/YY (38.9 pt) renders whole; 8 bare digits (44.5 pt) lose the 8th; "
        "7 fit", "MM/DD/YY") for y in (2023, 2024, 2025)},
    **{(f"states/va/{y}/va760/pack.yaml", "spouse_signature_date"): Measured(
        8, 46.1, 10.0, "46.1 pt at Helv 10: MM/DD/YY (38.9 pt) renders whole; 8 bare digits (44.5 pt) overrun the "
        "44.1 pt inside the box (the render keeps the 8th only by its side bearing); 7 fit", "MM/DD/YY")
       for y in (2023, 2024, 2025)},
}
HELVETICA_DIGIT_EM = 0.556  # every Helvetica digit advances 556/1000 em
COURIER_EM = 0.6  # every Courier glyph advances 600/1000 em
LEGIBLE_PT = 6.0  # an auto-size box holds the longest probe still drawn at 6 pt or more
# Capitals and digits the JK28 probe renders drew whole in Helvetica boxes whose rows pin digits or keep a tighter
# budget: (box width pt, /DA size pt, capitals A-Z, digits). The capital and digit arithmetic must give both counts,
# so a capitals row is checked with capital widths, never a digit's.
CAPITALS_AND_DIGITS_ON_THE_RENDER = (
    (72.5, 10.0, 11, 12),  # CA 540 / 540NR mailing "Apt. no/ste. no."
    (73.0, 10.0, 11, 12),  # CA 540 / 540NR "PMB/private mailbox"
    (70.7, 10.0, 10, 12),  # CA 540 principal-residence "Apt. no/ste. no."
    (79.56, 9.0, 13, 15),  # IL-1040 2025 ZIP or postal code (Arial 9)
)
_DATE_SHAPE = re.compile(r"(MM|DD|YY|YYYY)([/-](MM|DD|YY|YYYY)){2}")
_FACES = {"Helv": "Helvetica", "Arial": "Helvetica"}  # /DA font names drawn with Helvetica's metrics


def _font_size(da: str | None) -> float:
    """The /DA font size (0 = auto-size); a widget with no /DA is measured at 10 pt, as verify does."""
    match = re.search(r"(\d+(?:\.\d+)?)\s+Tf", da or "")
    return float(match.group(1)) if match else DEFAULT_FONT_SIZE


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


@pytest.mark.network
@pytest.mark.parametrize("row", sorted(TIGHTER_THAN_WIDGET), ids=lambda r: f"{r[0].removesuffix('/pack.yaml')}-{r[1]}")
def test_every_tighter_budget_fits_its_box_by_the_ink_model(row: tuple[str, str]):
    """Phase K JEe (2026-10-24): a budget of digits must END inside the box's border, not merely fill its width.

    Before JEe the rows were measured edge to edge, and nine Courier-10 glyphs exactly fill AL Schedule OC's 54.0 pt
    cell: the render cuts the ninth. Each budget is checked the way verify now checks a value (textfit.ink_extent
    against the width less the border on each side), on every widget of the line, at the pack line's font_size when
    it sets one (Phase K JEe2: the size fill_form writes); an auto-size, multiline or comb widget is not measured, as
    verify does not measure it.
    """
    pack_path = FORMPACKS / row[0]
    pack = load_pack(pack_path)
    field = next(f for f in pack.fields if f.line == row[1])
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError:
        pytest.skip(f"{row[0]}: its pinned blank is not cached")
    name = f"{pack.acroform_root}.{field.field}" if pack.acroform_root else field.field
    boxes = [w for w in read_text_widgets(blank, bound_names=bound_widget_names(pack)) if w.name == name]
    assert boxes, f"{row}: no text widget named {name!r} on the blank"
    for box in boxes:
        size = _font_size(box.da)
        if size and field.font_size is not None:  # Phase K JEe2: fill_form writes the box at the pack's font_size
            size = min(size, field.font_size)
        if size == 0 or box.multiline or (box.comb and box.max_len is not None) or box.rect_width <= 0:
            continue
        # Courier: every glyph advances 0.6 em, so end on the glyph whose ink reaches furthest right (the smallest
        # bearing in the table) and the budget holds for ANY text. Helvetica: digits — a text budget there is a cap
        # on typical content, and verify measures the actual value.
        last = min(_RSB_COURIER, key=_RSB_COURIER.__getitem__) if box.monospace else "0"
        probe = "0" * (field.maxlen - 1) + last
        ink = ink_extent(probe, size, courier=bool(box.monospace))
        room = box.rect_width - 2 * box.inset
        assert ink <= room + CUT_TOLERANCE_PT, (
            f"{row}: {field.maxlen} characters ({probe[-1]!r} last) reach {ink:.2f} pt, past the {room:.2f} pt inside the {box.rect_width:.2f} pt "
            f"box ({box.inset:g} pt border a side) — lower the pack maxlen to what renders whole and update the row")


def _measured_id(row: tuple[str, str]) -> str:
    return f"{row[0].removesuffix('/pack.yaml')}-{row[1]}"


def _probe_text(probe: str, n: int) -> str:
    """The n-character probe string; a date shape is its own length, its date slots digits."""
    if probe == "digits":
        return "0" * n
    if probe == "capitals":
        return (string.ascii_uppercase * (n // 26 + 1))[:n]
    return re.sub(r"[MDY]", "0", probe)


def _advance(text: str, face: str, size: float) -> float:
    """The text's advance in pt: Courier is 0.6 em a glyph, Helvetica each glyph's Core-14 AFM width (a capital
    0.278-0.944 em, a digit 0.556, '/' 0.278, '-' 0.333)."""
    return COURIER_EM * len(text) * size if face == "Courier" else text_width(text, size)


def _fit(probe: str, face: str, size: float, inner: float) -> int:
    """How many characters of a digits or capitals probe advance within ``inner`` pt."""
    assert probe in ("digits", "capitals"), probe
    n = 0
    while _advance(_probe_text(probe, n + 1), face, size) <= inner:
        n += 1
    return n


@pytest.mark.parametrize("row", sorted(MEASURED_WITHOUT_MAXLEN), ids=_measured_id)
def test_measured_budget_without_a_widget_maxlen_is_the_pack_maxlen(row: tuple[str, str]):
    """JK27 / JK28: the pack carries the budget measured on its box, and the probe's font metrics agree with the render."""
    m = MEASURED_WITHOUT_MAXLEN[row]
    pack_path = FORMPACKS / row[0]
    assert pack_path.is_file(), f"MEASURED_WITHOUT_MAXLEN names {row[0]}, which no longer exists — delete the row"
    field = next((f for f in load_pack(pack_path).fields if f.line == row[1]), None)
    assert field is not None, f"{row}: the line is gone — delete the row"
    assert field.maxlen == m.budget, (
        f"{row}: pack maxlen {field.maxlen}, but the box was measured at {m.budget} ({m.why}). A higher budget lets the "
        f"filler write what the render cuts off: the filler checks only the budget, and verify fails it after the fill")
    assert m.face in ("Helvetica", "Courier"), f"{row}: face {m.face!r} — the arithmetic knows Helvetica and Courier"
    inner = m.width - 2.0  # drawn from the 1 pt border inward, clipped 1 pt inside the far edge
    size = m.size or LEGIBLE_PT  # an auto-size box: the smallest size still legible
    if _DATE_SHAPE.fullmatch(m.probe):
        shape = _advance(_probe_text(m.probe, 0), m.face, size)
        assert m.fits is None and m.budget == len(m.probe) and shape <= inner, (
            f"{row}: a {m.probe} row budgets the shape's {len(m.probe)} characters, which must fit the {inner:.1f} pt "
            f"inside the {m.width} pt box ({shape:.1f} pt) — re-measure the row")
        return
    assert m.probe in ("digits", "capitals"), f"{row}: probe {m.probe!r} — digits, capitals or a date shape"
    assert m.fits is None or m.fits > m.budget, f"{row}: fits {m.fits} — None when the budget is the fit"
    fits = m.budget if m.fits is None else m.fits
    advance = _fit(m.probe, m.face, size, inner)
    assert advance == fits, (
        f"{row}: the render holds {fits} {m.probe} at {size:g} pt {m.face}, but {advance} advance within the "
        f"{inner:.1f} pt inside the {m.width} pt box — re-measure the row")


def test_one_box_carries_one_measured_budget_in_every_year():
    """The defect JK27 fixed: the same CA box budgeted 14 / 12 / 13 in three years. A budget belongs to the box."""
    by_box: dict[tuple[str, float, float], set[tuple[int, int | None, str]]] = {}
    for (_pack, line), m in MEASURED_WITHOUT_MAXLEN.items():
        by_box.setdefault((line, m.width, m.size), set()).add((m.budget, m.fits, m.probe))
    split = {box: budgets for box, budgets in by_box.items() if len(budgets) > 1}
    assert not split, f"one box, several budgets: {split} — re-measure on a probe render and use one"


@pytest.mark.parametrize(("width", "size", "capitals", "digits"), CAPITALS_AND_DIGITS_ON_THE_RENDER)
def test_the_capital_and_digit_arithmetic_reproduce_the_render(width: float, size: float, capitals: int, digits: int):
    """JK28: the Helvetica arithmetic gives the capitals and the digits a probe render drew whole in the same box."""
    inner = width - 2.0
    assert (_fit("capitals", "Helvetica", size, inner), _fit("digits", "Helvetica", size, inner)) == (capitals, digits)


def test_the_probe_faces_share_the_metrics_they_are_checked_with():
    """Digit rows keep the 0.556 em digit; Arial rows are checked with Helvetica's widths and Courier New rows with
    Courier's 0.6 em, so pypdf's Core-14 tables must agree on every probe glyph (overlay.text_width's own table is
    cross-checked in test_overlay.py)."""
    assert {text_width(d, 1.0) for d in string.digits} == {HELVETICA_DIGIT_EM}
    # a private pypdf module, imported directly so a move fails loudly instead of skipping the cross-check
    from pypdf._codecs.core_font_metrics import CORE_FONT_METRICS as core  # noqa: PLC0415

    glyphs = string.ascii_uppercase + string.digits + "/-"
    assert all(core["Arial"].character_widths[ch] == core["Helvetica"].character_widths[ch] for ch in glyphs)
    assert {core[face].character_widths[ch] / 1000 for face in ("Courier", "CourierNew", "CourierNew,Bold")
            for ch in glyphs} == {COURIER_EM}


@pytest.mark.network
@pytest.mark.parametrize("row", sorted(MEASURED_WITHOUT_MAXLEN), ids=_measured_id)
def test_every_measured_budget_row_still_describes_its_widget(row: tuple[str, str]):
    """The table self-clears: a widget that gains a /MaxLen, or a box that changes, must be re-measured."""
    m = MEASURED_WITHOUT_MAXLEN[row]
    pack = load_pack(FORMPACKS / row[0])
    field = next(f for f in pack.fields if f.line == row[1])
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    name = (f"{pack.acroform_root}." if pack.acroform_root else "") + field.field
    # bound_names: a ReadOnly mirror the pack maps (GA 500's voucher STATE box) is read like any other box
    widgets = [w for w in read_text_widgets(Path(blank), bound_names=bound_widget_names(pack)) if w.name == name]
    assert widgets, f"{row}: no text widget '{name}' in the blank — re-derive the binding"
    capped = sorted({w.max_len for w in widgets if w.max_len is not None})
    assert not capped, f"{row}: the widget now carries /MaxLen {capped}; the sweep above tracks it — delete the row"
    box = min(widgets, key=lambda w: w.rect_width)  # a field repeated on several pages: the narrowest box governs
    fonts = set()
    for w in widgets:
        font = re.search(r"/(\S+)\s+([\d.]+)\s+Tf", w.da or "")
        face = "Courier" if w.monospace else _FACES.get(font.group(1), font.group(1)) if font else None
        fonts.add((face, float(font.group(2)) if font else None))
    assert abs(box.rect_width - m.width) < 0.05 and fonts == {(m.face, m.size)}, (
        f"{row}: the box is now {box.rect_width:.2f} pt with /DA {box.da!r} ({sorted(fonts, key=str)}), not the "
        f"{m.width} pt at {m.face} {m.size:g} pt the budget of {m.budget} was measured on — probe-fill the new box, "
        f"read the render and update the row")
