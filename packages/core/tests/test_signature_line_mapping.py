"""Repo-wide invariant (Phase K JK28, 2026-10-16): no pack types a value onto an ink-signature line.

JK27 (test_signature_widget_mapping.py) closed one way a pack key can reach a signature line: an /FT /Sig
widget, where a written value never prints. This file closes the other. Some DOR blanks put an ordinary /Tx
text widget on the rule the filer signs: KS K-40 2023-2025 ("Signature of taxpayer", "Signature of spouse",
"Signature of preparer"), KY 740 2023-2024 ("Signature of Taxpayer", "Signature of Spouse", "Signature of
Preparer") and IL-1040 2025 ("Paid preparers signaturePaid Preparer Use Only"). A typed value DOES print there:
a sentinel filled into each of those 16 boxes rendered on the signature rule. So the mapped key let fill_form
type a name (or the round-trip's synthetic text) on the line the state asks the filer to sign: "Your income
tax return must be signed" (the KS booklets), "Each return must be signed by the taxpayer" (the KY 740
instructions), "the paid preparer must also sign and date your return" (the IL-1040 instructions). None of
the three states says that a typed name counts.

The treatment, as for /Sig: leave the line UNMAPPED, with a comment in the pack that quotes the face and the
instructions, and give the pack a ``signature: {page: N}`` block naming the page the filer signs in ink. The
16 keys are dropped and pinned in INK_SIGNATURE_LINES_UNMAPPED.

The exception is a state whose own face makes an entered name a signature. MO-1040 2023-2025's page-5
declaration reads "By signing or entering my name in the “Signature” field(s) below, I am providing the
Department of Revenue with my signature as required under Section 143.561, RSMo.", so ``t.signature`` and
``t.spousesignature`` stay mapped, allow-listed with that quote in TYPED_SIGNATURE_ALLOWED.

The sweep. A registry pins only the lines someone already found, so every pack is also swept with a
heuristic (``signature_like``): a mapped line whose key or widget label names a signature ("signature", "sig",
"sign" or "signed" as a word, or "signature" run into another word) and NOT one of the ordinary boxes a
signature block prints beside it (date, phone, driver's license, PTIN / EIN / SSN, printed name, occupation,
...) must be on the allow-list. The key and each label are judged on their own, a label's parenthetical is
ignored, and a label that joins the signature to such a box ("Taxpayer signature and date") still names the
signature. Checkboxes are skipped: they cannot carry a typed name (MO's "failtosignYES" / "failtosignNO" ask
whether a paid preparer failed to sign). The word rules are tested below on what trips a plain text search:
IL's "step12-designeesig" (the designee's printed name; "designeesig" is not the word "sig"), the
"signature.dl_number" / "dl_expiration" driver's-license lines of the NM PIT-1 hand-fill worksheet, the FBAR
worksheet's "signature authority" lines, the "minus sign" tooltips on the OH and VT money boxes, MN M1's run-on
date widgets "signaturedate" / "preparersignaturedate", DE PIT-RES's "ppSigEINSSNPTIN" ID box and the PA-40 date
tooltip "... the taxpayer or taxpayer and spouse sign the return ...".

Layers, following test_signature_widget_mapping.py:

- **offline** (always run): the heuristic on known shapes; the registry pinned against the packs (each key
  absent and refused by fill_form, its widget not re-bound under another key, the date / phone / ID boxes on
  the same row still mapped, ``signature.page`` = the widget's page); the allow-list rows still mapped, each pack
  still telling an agent in a comment to leave the line blank unless the filer asks; the widgetless Sign Here
  blocks (IL-1040 2023 and 2024) still naming their page; and the sweep over every pack.yaml (line keys + field
  names) and handfill.yaml (line keys + printed labels).
- **@pytest.mark.network**: the blanks, read from the cache (fetch_pack_blank returns the cached copy without
  touching the network) or downloaded, and skipped when neither works. The sweep runs again with each
  widget's /TU tooltip as one more label, and every table row's widget must still be a /Tx widget on the row's
  page, so the tables clear themselves when a revision drops, moves or retypes the box.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pytest

from taxfill_core.fetch import OfflineFetchError, fetch_pack_blank
from taxfill_core.filler import fill_form, rehearsal_only
from taxfill_core.handfill import load_hand_fill_pack
from taxfill_core.schemas.formpack import load_pack

REPO_ROOT = Path(__file__).resolve().parents[3]
FORMPACKS = REPO_ROOT / "formpacks"
ALL_PACK_PATHS = sorted(FORMPACKS.glob("**/pack.yaml"))
ALL_HANDFILL_PATHS = sorted(FORMPACKS.glob("**/handfill.yaml"))


def _key(pack_path: Path) -> str:
    """Pack identity used by the tables: path relative to formpacks/ ("states/ks/2023/k40/pack.yaml")."""
    return pack_path.relative_to(FORMPACKS).as_posix()


def _pack_id(pack_path: Path) -> str:
    return _key(pack_path).rsplit("/", 1)[0].replace("/", "-")


# ---------------------------------------------------------------------------
# The heuristic
# ---------------------------------------------------------------------------

# A word that names the signature itself ...
_SIGNATURE_WORDS = frozenset({"sig", "signature", "signatures", "sign", "signed", "signer", "signing"})
# ... and the words that mark one of the ordinary boxes a signature block prints BESIDE the signature, or a
# question or authority that merely mentions one. A key or label that carries any of them names that box.
_COMPANION_WORDS = frozenset({
    "date", "day", "month", "year",
    "phone", "telephone", "email",
    "license", "licence", "lic", "drivers", "dl", "id", "number", "expiration", "ptin", "ein", "fein", "ssn", "tin",
    "address", "city", "state", "zip",
    "name", "print", "printed", "firm", "title", "occupation", "dob", "birth",
    "authorize", "discuss", "discussion", "authority",
})
# "sign" is also the arithmetic sign of a money box: "place a minus sign in this box" (OH IT 1040), "Enter negative
# figures with a minus sign (-)" (VT IN-111).
_ARITHMETIC_SIGN_WORDS = frozenset({"minus", "plus", "negative"})
_NOT_THE_SIGNATURE = _COMPANION_WORDS | _ARITHMETIC_SIGN_WORDS
# ID acronyms a widget name runs together in capitals: DE PIT-RES's "ppSigEINSSNPTIN" is the preparer's EIN / SSN /
# PTIN box.
_ID_ACRONYMS = ("FEIN", "ITIN", "PTIN", "EIN", "SSN", "TIN", "DOB", "DL", "ID")
# A parenthetical qualifies the box rather than naming it: "Signature of taxpayer (state ID required)".
_PARENTHETICAL = re.compile(r"\([^)]*\)")
# One box for the signature AND a companion entry: "Taxpayer signature and date", "Name and signature of preparer".
_SIGNATURE_AND = re.compile(r"signatures?\s*(?:and|&)\s|\s(?:and|&)\s*signatures?\b", re.IGNORECASE)


def _acronym_run(run: str) -> list[str]:
    """"EINSSNPTIN" -> ["ein", "ssn", "ptin"] when the whole capital run splits into _ID_ACRONYMS, else []."""
    parts: list[str] = []
    at = 0
    while at < len(run):
        acronym = next((a for a in _ID_ACRONYMS if run.startswith(a, at)), None)
        if acronym is None:
            return []
        parts.append(acronym.lower())
        at += len(acronym)
    return parts


def _words(text: str) -> set[str]:
    """Lower-case words of a line key or widget label, split at punctuation and at camelCase / digit runs, with
    two run-ons opened: a capital run made of ID acronyms, and a word that runs "signature" into another word.

    "740PreparerSigDate" -> {"740", "preparer", "sig", "date"}; "ppSigEINSSNPTIN" -> {"pp", "sig", "einssnptin",
    "ein", "ssn", "ptin"}; "t.spousesignature" -> {"t", "spousesignature", "spouse", "signature"};
    "signaturedate" -> {"signaturedate", "signature", "date"}; "Paid preparers signaturePaid Preparer Use Only"
    -> {"paid", "preparers", "signature", "preparer", "use", "only"}.
    """
    words: set[str] = set()
    for chunk in re.split(r"[^A-Za-z0-9]+", text):
        for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", chunk):
            words.add(word.lower())
            if word.isupper() and len(word) > 3:
                words.update(_acronym_run(word))
    for word in list(words):
        if "signature" in word and word not in ("signature", "signatures"):
            words.add("signature")
            words.update(part for part in word.split("signature") if part and part != "s")
    return words


def _names_a_signature(words: set[str]) -> bool:
    return any(word in _SIGNATURE_WORDS or "signature" in word for word in words)


def _names_the_signature(text: str) -> bool:
    """One line key or label names the signature itself: with any parenthetical dropped, it names a signature
    and either no box beside one, or the signature joined to such a box by "and" / "&"."""
    text = _PARENTHETICAL.sub(" ", text)
    words = _words(text)
    if not _names_a_signature(words):
        return False
    if not words & _NOT_THE_SIGNATURE:
        return True
    return bool(_SIGNATURE_AND.search(re.sub(r"[^A-Za-z0-9&]+", " ", text)))


def signature_like(line: str, labels: Iterable[str] = ()) -> bool:
    """True when a pack line looks like the signature itself rather than a box of the signature block.

    The line key and each label (the field name, the /TU tooltip, a hand-fill printed label) are judged on their
    own, so a key that names a companion box does not hide a widget named for the signature: "preparer.name"
    over "Signature of preparer" is flagged, while "signature.taxpayer_date" over "740TP1SigDate" is not.
    Limits: a companion word joined to the signature by a comma or slash ("Signature, state ID required",
    "Signature / date") still reads as that companion box, and a signature named in another language or only
    by its position is not seen at all; the tables below are what pin the known lines.
    """
    return any(_names_the_signature(text) for text in (line, *labels))


# (line key, labels) pairs seen on this repo's blanks.
SIGNATURE_SHAPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("signature.taxpayer", ("Signature of taxpayer",)),  # KS K-40
    ("preparer.signature", ("Signature of Preparer",)),  # KY 740
    ("preparer_signature", ("Paid preparers signaturePaid Preparer Use Only",)),  # IL-1040 2025
    ("t.spousesignature", ("t.spousesignature",)),  # MO-1040 (allow-listed)
    ("signature.primary", ("Signature1",)),  # AR1000F's /Sig box (JK27)
    ("line_7", ("Text7", "Signature of taxpayer")),  # a key and a name that say nothing, a tooltip that does
    ("sp_sig", ()),  # "sig" as a word
    ("preparer.name", ("Signature of preparer",)),  # a companion key does not hide a label naming the signature
    ("sign_here", ()),  # "sign" as a word
    ("line_9", ("Taxpayer signature and date",)),  # one box for the signature and its date
    ("line_10", ("Signature of taxpayer (state ID required)",)),  # a parenthetical does not name the box
)
COMPANION_SHAPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("signature.taxpayer_date", ("date signed",)),  # KS K-40
    ("preparer.date", ("740PreparerSigDate",)),  # KY 740
    ("signature.taxpayer_drivers_license", ("740DriversLic-TP",)),  # KY 740
    ("signature.daytime_phone", ("740DaytimePhoneNum",)),  # KY 740
    ("your_signature_date", ("date_1", "Date (mm/dd/yyyy)")),  # IL-1040 2025
    ("preparer_name", ("PrintType paid preparers namePaid Preparer Use Only",)),  # IL-1040 2025
    ("third_party_designee_name", ("step12-designeesig", "Third Party Designee Name")),  # IL-1040 2025
    ("designee", ("step12-designeesig",)),  # "designeesig" is not the word "sig"
    ("failtosignYES", ("failtosignYES",)),  # MO-1040's preparer-failed-to-sign question
    ("preparer.ein_ssn_ptin", ("ppSigEINSSNPTIN",)),  # DE PIT-RES
    ("signature.taxpayer.license_state", ("Page2[0].StateP[0]",)),  # RI-1040
    ("signature.dl_number", ('Driver\'s License, State ID No. or enter "NONE" or "DECLINED"',)),  # NM PIT-1 hand-fill
    ("signature.dl_expiration", ("Expiration Date (your driver's license / state ID)",)),  # NM PIT-1 hand-fill
    ("signature.spouse_occupation", ("511 Spouse Occupation",)),  # OK 511
    ("signature.authorize_discussion", ("CheckBox180Days 3",)),  # ID Form 40
    ("1_neg", ("L1_NEG", "If line 1 is a negative amount, place a minus sign in this box.")),  # OH IT 1040
    ("sigauth_16", ("Signature-authority account: Type of account: Bank, Securities, or Other (specify)",)),  # FBAR
    ("1", ("Line1", "Enter negative figures with a minus sign (-) at the beginning of the figure.")),  # VT IN-111
    ("taxpayer_signature_date", ("preparersignaturedate", "date your preparer signed this form")),  # MN M1 2023
    ("preparer_signature_date", ("signaturedate", "date you signed this form")),  # MN M1 2023
    ("signed_date", ("Date", "Enter the date the taxpayer or taxpayer and spouse sign the return in the MM/DD/YY "
                             "format")),  # PA-40
)


@pytest.mark.parametrize(("line", "labels"), SIGNATURE_SHAPES, ids=[line for line, _ in SIGNATURE_SHAPES])
def test_heuristic_flags_the_signature_itself(line: str, labels: tuple[str, ...]):
    assert signature_like(line, labels), (
        f"signature_like({line!r}, {labels!r}) is False: the sweep below would miss a signature line of this shape"
    )


@pytest.mark.parametrize(("line", "labels"), COMPANION_SHAPES, ids=[line for line, _ in COMPANION_SHAPES])
def test_heuristic_passes_the_boxes_beside_a_signature(line: str, labels: tuple[str, ...]):
    assert not signature_like(line, labels), (
        f"signature_like({line!r}, {labels!r}) is True: this is a date / phone / ID / name box, a question or an "
        f"authority, not the signature, and stays mapped"
    )


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------


class InkSignatureUnmapped(NamedTuple):
    """An ink-signature line a pack once mapped onto an ordinary /Tx widget, now deliberately unmapped."""

    pack: str  # path relative to formpacks/
    line: str  # the key that bound it; it must not exist
    widget: str  # the /Tx field's name as a pack's `field:` would spell it (acroform_root NOT prefixed)
    page: int  # 1-based page of the widget; the pack's `signature: {page: N}` must name it
    label: str  # the caption printed on the line
    survivors: tuple[str, ...]  # the ordinary boxes on the same printed row, which stay mapped
    why: str


class TypedSignatureAllowed(NamedTuple):
    """A signature line that stays mapped because the state's own face makes an entered name a signature."""

    pack: str
    line: str
    widget: str
    page: int
    label: str
    why: str


_KS_WHY = (
    'K-40 page 2 prints the line under "I declare under the penalties of perjury that to the best of my '
    'knowledge this is a true, correct, and complete return."; the {year} booklet ({booklet}, Page {page}, '
    'SIGNATURE(S)): "Signature: Your income tax return must be signed. You will not receive your refund if your '
    "return is not signed. Both taxpayers must sign a joint return even if only one had income. If the return is "
    'prepared by someone other than you, the preparer should also sign in the space provided." Nothing makes a '
    "typed name a signature. Dropped in 2023, 2024 and 2025 (Phase K JK28, 2026-10-16); signed by hand"
)
_KS_BOOKLET = {2023: ("ip23.pdf", 10), 2024: ("ip24.pdf", 11), 2025: ("ip25.pdf", 10)}
_KS_PREPARER_LABEL = {
    2023: "SIGNATURE OF PREPARER OTHER THAN TAXPAYER",
    2024: "SIGNATURE OF PREPARER OTHER THAN TAXPAYER",
    2025: "Signature of preparer other than taxpayer",
}


def _ks_why(year: int) -> str:
    booklet, page = _KS_BOOKLET[year]
    return _KS_WHY.format(year=year, booklet=booklet, page=page)


_KY_WHY = (
    'Form 740 page 3 prints the line under "I, the undersigned, declare under penalties of perjury that I have '
    'examined this return, ..."; the {year} instructions ("{packet}", page 16, SIGN RETURN): "Be sure to sign on '
    "page 3 after completion of your return. Each return must be signed by the taxpayer. Joint and combined "
    'returns must be signed by both taxpayer and spouse." The 2025 blank prints the same caption with no widget '
    "on it. Dropped in 2023 and 2024 (Phase K JK28, 2026-10-16); signed by hand"
)
_KY_PACKET = {2023: "740 Packet Instructions 2023.pdf", 2024: "740 instructions packet (2024).pdf"}

INK_SIGNATURE_LINES_UNMAPPED: tuple[InkSignatureUnmapped, ...] = (
    *(
        row
        for year in (2023, 2024, 2025)
        for row in (
            InkSignatureUnmapped(
                f"states/ks/{year}/k40/pack.yaml", "signature.taxpayer", "Signature of taxpayer", 2,
                "Taxpayer Signature", ("signature.taxpayer_date",), _ks_why(year),
            ),
            InkSignatureUnmapped(
                f"states/ks/{year}/k40/pack.yaml", "signature.spouse", "Signature of spouse", 2,
                "Spouse Signature (If married filing joint)", ("signature.spouse_date",), _ks_why(year),
            ),
            InkSignatureUnmapped(
                f"states/ks/{year}/k40/pack.yaml", "preparer.signature", "Signature of preparer", 2,
                _KS_PREPARER_LABEL[year], ("preparer.phone", "preparer.id_number"), _ks_why(year),
            ),
        )
    ),
    *(
        row
        for year in (2023, 2024)
        for row in (
            InkSignatureUnmapped(
                f"states/ky/{year}/form740/pack.yaml", "signature.taxpayer", "Signature of Taxpayer", 3,
                "Signature of Taxpayer",
                ("signature.taxpayer_drivers_license", "signature.taxpayer_date", "signature.daytime_phone"),
                _KY_WHY.format(year=year, packet=_KY_PACKET[year]),
            ),
            InkSignatureUnmapped(
                f"states/ky/{year}/form740/pack.yaml", "signature.spouse", "Signature of Spouse", 3,
                "Signature of Spouse", ("signature.spouse_drivers_license", "signature.spouse_date"),
                _KY_WHY.format(year=year, packet=_KY_PACKET[year]),
            ),
            InkSignatureUnmapped(
                f"states/ky/{year}/form740/pack.yaml", "preparer.signature", "Signature of Preparer", 3,
                "Signature of Preparer", ("preparer.date",),
                _KY_WHY.format(year=year, packet=_KY_PACKET[year]),
            ),
        )
    ),
    InkSignatureUnmapped(
        "states/il/2025/il1040/pack.yaml", "preparer_signature", "Paid preparers signaturePaid Preparer Use Only", 2,
        "Paid preparer’s signature", ("preparer_name", "preparer_signature_date", "preparer_ptin"),
        'IL-1040 page 2 prints "Paid preparer’s signature" beside its own "Print/Type paid preparer’s name" box '
        '(preparer_name); the 2025 instructions (il-1040-instr.pdf, page 16, "Paid preparer"): "If you pay '
        "someone to prepare your return, the paid preparer must also sign and date your return, provide a phone "
        'number, and enter their Preparer Tax Identification Number (PTIN) issued by the IRS." The widget is new in '
        "2025; the 2023 and 2024 blanks have none on that line. Dropped (Phase K JK28, 2026-10-16); signed by hand",
    ),
)

_MO_WHY = (
    'MO-1040 page 5 declaration: "By signing or entering my name in the “Signature” field(s) below, I am '
    'providing the Department of Revenue with my signature as required under Section 143.561, RSMo." Section '
    '143.561.1 RSMo has a return "signed in accordance with regulations or instructions prescribed by the '
    'director of revenue". An entered name is a signature on this form, so the line stays mapped. The default '
    "is still the ink signature: writing a name signs the return under penalties of perjury, so an agent leaves "
    "the box blank unless the signer asks for their name to be entered (the pack comment's AGENT RULE). The "
    "\"Preparer’s Signature\" line carries no widget. Kept (Phase K JK28, 2026-10-16)"
)

TYPED_SIGNATURE_ALLOWED: tuple[TypedSignatureAllowed, ...] = tuple(
    row
    for year in (2023, 2024, 2025)
    for row in (
        TypedSignatureAllowed(
            f"states/mo/{year}/mo1040/pack.yaml", "t.signature", "t.signature", 5, "Signature", _MO_WHY,
        ),
        TypedSignatureAllowed(
            f"states/mo/{year}/mo1040/pack.yaml", "t.spousesignature", "t.spousesignature", 5,
            "Spouse’s Signature (If filing combined, BOTH must sign)", _MO_WHY,
        ),
    )
)

_ALLOWED = frozenset((row.pack, row.line) for row in TYPED_SIGNATURE_ALLOWED)

# Packs whose signature block carries no widget under any signature caption: nothing to drop, but the pack still
# names the page the filer signs in ink. IL-1040 2023 and 2024 print the same page-2 "Sign Here" / "Paid Preparer Use
# Only" block as 2025 (rendered 2026-10-16), without 2025's preparer widget: "Your signature", "Spouse’s signature"
# and "Paid preparer’s signature" have no box under them. Their instructions (il-1040-instr.pdf, page 16, "Sign and
# date"): "You, and your spouse if filing jointly, must sign and date your return."
INK_ONLY_SIGNATURE_PAGES: tuple[tuple[str, int], ...] = (
    ("states/il/2023/il1040/pack.yaml", 2),
    ("states/il/2024/il1040/pack.yaml", 2),
)


def _row_id(row: InkSignatureUnmapped | TypedSignatureAllowed) -> str:
    return f"{_pack_id(FORMPACKS / row.pack)}-{row.line}"


# ---------------------------------------------------------------------------
# Offline layer
# ---------------------------------------------------------------------------


def test_tables_are_well_formed_and_disjoint():
    seen: set[tuple[str, str]] = set()
    for row in (*INK_SIGNATURE_LINES_UNMAPPED, *TYPED_SIGNATURE_ALLOWED):
        assert (FORMPACKS / row.pack).is_file(), f"{row.pack} does not exist — delete the row"
        assert row.why.strip() and row.label.strip(), f"{row}: every row needs the printed label and a justification"
        assert (row.pack, row.line) not in seen, f"{row.pack} {row.line} sits in the tables twice"
        seen.add((row.pack, row.line))


def test_the_offline_sweep_catches_every_table_row():
    """A dropped key that comes back fails the sweep as well as its row; an allow-list row the sweep never flags
    is dead weight. Both rest on the heuristic seeing each row's key and field name as a signature."""
    missed = [
        _row_id(row)
        for row in (*INK_SIGNATURE_LINES_UNMAPPED, *TYPED_SIGNATURE_ALLOWED)
        if not signature_like(row.line, (row.widget,))
    ]
    assert not missed, f"signature_like() does not flag {missed}; widen _SIGNATURE_WORDS or narrow the exclusions"


@pytest.mark.parametrize("row", INK_SIGNATURE_LINES_UNMAPPED, ids=_row_id)
def test_ink_signature_key_stays_unmapped_and_the_filler_refuses_it(row: InkSignatureUnmapped, tmp_path: Path):
    """JK28: the key must not exist, its /Tx widget must not come back under another key, fill_form refuses it,
    and the pack says on which page the filer signs."""
    pack = load_pack(FORMPACKS / row.pack)
    by_line = {pf.line: pf.field for pf in pack.fields}
    assert row.line not in by_line, (
        f"{row.pack} maps '{row.line}' -> '{by_line[row.line]}' again. That box is the printed "
        f"\"{row.label}\" line: a typed value prints on it, where the state asks for a signature. Leave it for an "
        f"ink signature — {row.why}"
    )
    rebound = sorted(pf.line for pf in pack.fields if pf.field == row.widget)
    assert not rebound, (
        f"{row.pack} binds the signature widget '{row.widget}' under {rebound}: leave it unmapped ({row.why})"
    )
    for line in row.survivors:
        assert line in by_line, (
            f"{row.pack} lost '{line}' — over-reach: only the signature box comes out of the map; the date / phone "
            f"/ ID boxes on the same row are ordinary data and stay mapped"
        )
    assert pack.signature is not None and pack.signature.page == row.page, (
        f"{row.pack}: the filer signs \"{row.label}\" in ink on page {row.page}, so the pack must carry "
        f"`signature: {{page: {row.page}}}` (it has {pack.signature})"
    )
    # fill_form validates line keys before it opens the blank, so no PDF is needed.
    with pytest.raises(ValueError, match=r"unknown line key"):
        fill_form(pack, {row.line: "SIGNED"}, tmp_path / "absent-blank.pdf", tmp_path / "out.pdf",
                  rehearsal=rehearsal_only(pack))


@pytest.mark.parametrize("row", TYPED_SIGNATURE_ALLOWED, ids=_row_id)
def test_typed_signature_allowance_row_is_still_mapped(row: TypedSignatureAllowed):
    pack = load_pack(FORMPACKS / row.pack)
    by_line = {pf.line: pf for pf in pack.fields}
    assert row.line in by_line, (
        f"{row.pack} no longer maps '{row.line}'; delete its TYPED_SIGNATURE_ALLOWED row ({row.why})"
    )
    assert (by_line[row.line].field, by_line[row.line].type) == (row.widget, "text"), (
        f"{row.pack} '{row.line}' moved to {by_line[row.line].field!r} ({by_line[row.line].type}); re-read the face "
        f"and re-adjudicate the row ({row.why})"
    )
    assert pack.signature is not None and pack.signature.page == row.page, (
        f"{row.pack}: the signature block is on page {row.page}; the pack must carry "
        f"`signature: {{page: {row.page}}}` (it has {pack.signature})"
    )


@pytest.mark.parametrize(("pack", "page"), INK_ONLY_SIGNATURE_PAGES,
                         ids=[_pack_id(FORMPACKS / pack) for pack, _ in INK_ONLY_SIGNATURE_PAGES])
def test_widgetless_signature_block_still_names_its_page(pack: str, page: int):
    loaded = load_pack(FORMPACKS / pack)
    assert loaded.signature is not None and loaded.signature.page == page, (
        f"{pack}: the filer signs page {page}'s Sign Here block in ink, so the pack must carry "
        f"`signature: {{page: {page}}}` (it has {loaded.signature})"
    )


def _comment_text(path: Path) -> str:
    """A file's ``#`` comment lines joined into one string, so a sentence wrapped across lines reads whole."""
    return " ".join(
        line.split("#", 1)[1].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#")
    )


@pytest.mark.parametrize("pack", sorted({row.pack for row in TYPED_SIGNATURE_ALLOWED}))
def test_typed_signature_pack_tells_the_agent_to_leave_the_line_blank(pack: str):
    """The allowance keeps the line mappable; it does not make typing the filer's name the default. A pack field
    carries no note, and the state filing steps say to sign in ink, so the pack comment is the one place that tells
    an agent to leave the line blank unless the filer asks. A re-map that regenerates the pack would drop it."""
    lines = sorted(row.line for row in TYPED_SIGNATURE_ALLOWED if row.pack == pack)
    rule = f"AGENT RULE: do NOT fill {' or '.join(lines)} unless the filer asks for it"
    assert rule in _comment_text(FORMPACKS / pack), (
        f"{pack} no longer carries the comment {rule!r}. The face lets a typed name sign the return, but the default "
        f"is the ink signature: restore the comment above the lines ({_MO_WHY})"
    )


def _sweep_failure(where: str, hits: list[str]) -> str:
    return (
        f"{where} maps what looks like an ink-signature line:\n  " + "\n  ".join(hits)
        + "\n\nA typed value prints on a /Tx widget, so the filed return would show a typed name where the state "
        "asks for a signature. Read the face and the instructions. If the state does not accept a typed name, drop "
        "the line key, leave a comment quoting both, give the pack `signature: {page: N}`, and add an "
        "INK_SIGNATURE_LINES_UNMAPPED row. If the state's own face or instructions make an entered name a "
        "signature (MO-1040), add a TYPED_SIGNATURE_ALLOWED row with that quote. If it is not the signature at all "
        "(a date, phone, ID or printed-name box), give the key the word that says so (e.g. `_date`, `_phone`), "
        "or teach _COMPANION_WORDS the word"
    )


@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_pack_maps_no_signature_line_outside_the_allow_list(pack_path: Path):
    """JK28, repo-wide over every pack.yaml: line keys and field names."""
    pack = load_pack(pack_path)
    key = _key(pack_path)
    hits = sorted(
        f"line {pf.line!r} -> {pf.field!r}"
        for pf in pack.fields
        if pf.type != "checkbox" and (key, pf.line) not in _ALLOWED and signature_like(pf.line, (pf.field,))
    )
    assert not hits, _sweep_failure(key, hits)


@pytest.mark.parametrize("handfill_path", ALL_HANDFILL_PATHS, ids=_pack_id)
def test_hand_fill_pack_lists_no_signature_line(handfill_path: Path):
    """A hand-fill line is a value the filer copies (or the overlay stamps) onto the print; the signature itself
    belongs in the pack's `signature_note`, never in `lines`."""
    pack = load_hand_fill_pack(handfill_path)
    hits = sorted(
        f"line {ln.line!r} ({ln.label!r})"
        for ln in pack.lines
        if ln.type != "checkbox" and signature_like(ln.line, (ln.label,))
    )
    assert not hits, _sweep_failure(_key(handfill_path), hits)


# ---------------------------------------------------------------------------
# Network layer — the blanks themselves
# ---------------------------------------------------------------------------


class _Widget(NamedTuple):
    field_type: str | None
    tooltip: str | None
    page: int


def _widgets(pdf_path: Path) -> dict[str, _Widget]:
    """Fully qualified widget name -> (/FT, /TU, 1-based page); /FT and /TU are inherited up the /Parent chain."""
    from pypdf import PdfReader  # noqa: PLC0415

    def inherited(node, key):
        hops = 0
        while node is not None and hops < 64:
            if key in node:
                return node[key]
            parent = node.get("/Parent")
            node = parent.get_object() if parent is not None else None
            hops += 1
        return None

    def qualified_name(node) -> str:
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

    widgets: dict[str, _Widget] = {}
    for number, page in enumerate(PdfReader(str(pdf_path)).pages, start=1):
        for annot_ref in page.get("/Annots") or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            field_type = inherited(annot, "/FT")
            tooltip = inherited(annot, "/TU")
            widgets.setdefault(
                qualified_name(annot),
                _Widget(str(field_type) if field_type is not None else None,
                        str(tooltip) if tooltip is not None else None, number),
            )
    return widgets


def _blank_widgets(pack) -> dict[str, _Widget]:
    try:
        blank = fetch_pack_blank(pack)
    except OfflineFetchError as exc:
        pytest.skip(f"cache empty and network unreachable: {exc}")
    return _widgets(Path(blank))


@pytest.mark.network
@pytest.mark.parametrize("pack_path", ALL_PACK_PATHS, ids=_pack_id)
def test_pack_maps_no_signature_line_by_its_tooltip(pack_path: Path):
    """JK28, repo-wide: the sweep again, with each mapped widget's /TU tooltip from the pack's own blank."""
    pack = load_pack(pack_path)
    widgets = _blank_widgets(pack)
    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    key = _key(pack_path)
    hits = []
    for pf in pack.fields:
        if pf.type == "checkbox" or (key, pf.line) in _ALLOWED:
            continue
        widget = widgets.get(prefix + pf.field)
        labels = (pf.field,) + ((widget.tooltip,) if widget is not None and widget.tooltip else ())
        if signature_like(pf.line, labels):
            hits.append(f"line {pf.line!r} -> {pf.field!r} (/TU {labels[1:]})")
    assert not hits, _sweep_failure(key, sorted(hits))


@pytest.mark.network
@pytest.mark.parametrize("row", (*INK_SIGNATURE_LINES_UNMAPPED, *TYPED_SIGNATURE_ALLOWED), ids=_row_id)
def test_every_table_row_still_names_a_text_widget_on_its_page(row: InkSignatureUnmapped | TypedSignatureAllowed):
    """The tables self-clear: a revision that drops, moves or retypes the box must re-adjudicate the row."""
    pack = load_pack(FORMPACKS / row.pack)
    widgets = _blank_widgets(pack)
    prefix = f"{pack.acroform_root}." if pack.acroform_root else ""
    widget = widgets.get(prefix + row.widget)
    assert widget is not None, (
        f"{row.pack}: the pinned blank has no widget '{row.widget}' any more. Re-read the \"{row.label}\" line and "
        f"delete or re-adjudicate the row ({row.why})"
    )
    assert (widget.field_type, widget.page) == ("/Tx", row.page), (
        f"{row.pack}: '{row.widget}' is now {widget.field_type} on page {widget.page} (the row says /Tx on page "
        f"{row.page}). An /FT /Sig box belongs to test_signature_widget_mapping.py's table; re-read the face and "
        f"move or re-adjudicate the row ({row.why})"
    )
