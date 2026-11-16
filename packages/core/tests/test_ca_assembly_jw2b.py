"""California's assembly steps and federal-copy rule in file_and_pay (Phase K-W JW2b, walkthrough finding P1-03).

Before JW2b every state return got one generic assembly line, so the walkthrough's California checklist never said
to attach the federal return, though its federal Form 1040 carried eight forms other than Schedule A or B. The 2025
Form 540 booklet, p. 23, "Attachments to your tax return": "Other than Schedule A (Form 1040) or Schedule B (Form
1040), Interest and Ordinary Dividends, did you attach any federal forms or schedules to your federal Form 1040 or
1040-SR?" ... "If Yes, attach a copy of your federal Form 1040 or 1040-SR return and all supporting federal forms and
schedules to Form 540." The TY2025 California pack's ``assembly`` block carries that rule and the other steps;
file_and_pay answers the question from the federal item of the same manifest. A state without the block keeps the
generic line, byte for byte.
"""
from __future__ import annotations

import pytest

from taxfill_core.file_and_pay import (
    _GENERIC_STATE_ASSEMBLE,
    FilingManifestItem,
    _federal_pack_key,
    _schedule_letter,
    file_and_pay,
)

YEAR = 2025
QUESTION = ("Other than Schedule A (Form 1040) or Schedule B (Form 1040), Interest and Ordinary Dividends, did you "
            "attach any federal forms or schedules to your federal Form 1040 or 1040-SR?")
IF_YES = ("If Yes, attach a copy of your federal Form 1040 or 1040-SR return and all supporting federal forms and "
          "schedules to Form 540.")
IF_NO = "If No, do not attach a copy of your federal Form 1040 or 1040-SR return to Form 540."


def _federal(*attached: str, **kw) -> FilingManifestItem:
    return FilingManifestItem(form=kw.pop("form", "1040"), tax_year=kw.pop("tax_year", YEAR), bottom_line=-100,
                              state="CA", attached_forms=list(attached), **kw)


def _ca(**kw) -> FilingManifestItem:
    return FilingManifestItem(form="540", tax_year=kw.pop("tax_year", YEAR), jurisdiction="states/ca",
                              bottom_line=50, **kw)


def _assemble(*manifest: FilingManifestItem) -> list[str]:
    return next(r for r in file_and_pay(list(manifest)).returns if r.jurisdiction == "states/ca").assemble


def _federal_copy(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("Federal return copy:"))


def test_the_walkthrough_filer_is_told_to_attach_the_federal_return():
    lines = _assemble(_federal("Schedule 1", "Schedule D", "8949", "8889"), _ca())
    line = _federal_copy(lines)
    assert line.startswith("Federal return copy: Yes.") and QUESTION in line and IF_YES in line
    assert "Put behind your CA schedules: Form 1040, Schedule 1, Schedule D, Form 8949, Form 8889." in line
    assert IF_NO not in line
    # the other cited steps: W-2 placement, all six sides, where Schedule CA goes, the order
    text = "\n".join(lines)
    assert "to the lower front of your tax return" in text
    assert "you must send all six sides" in text
    assert "Attach this schedule behind Form 540, Side 6 as a supporting California schedule." in text
    assert "Behind the supporting forms or schedules, put a copy of your federal tax return" in text
    assert _GENERIC_STATE_ASSEMBLE not in lines


def test_the_federal_attachment_list_passes_through_in_its_own_order_with_schedule_a_and_b():
    line = _federal_copy(_assemble(_federal("Schedule B", "8889", "Schedule A"), _ca()))
    assert "lists Form 8889, so:" in line
    assert "Put behind your CA schedules: Form 1040, Schedule B, Form 8889, Schedule A." in line


@pytest.mark.parametrize("attached", [(), ("Schedule A",), ("Schedule A (Form 1040)", "Schedule B, Interest and "
                                                                                       "Ordinary Dividends")])
def test_only_schedule_a_or_b_means_no_federal_copy(attached):
    line = _federal_copy(_assemble(_federal(*attached), _ca()))
    assert line.startswith("Federal return copy: No.") and IF_NO in line and IF_YES not in line
    assert "Put behind" not in line


@pytest.mark.parametrize("name", ["Schedule 1-A", "sched_a_nr", "Schedule 8812"])
def test_a_name_that_only_looks_like_schedule_a_counts(name):
    assert _schedule_letter(name) not in ("A", "B")
    assert _federal_copy(_assemble(_federal("Schedule A", name), _ca())).startswith("Federal return copy: Yes.")


@pytest.mark.parametrize("other", [
    {"tax_year": 2024}, {"taxpayer": "Partner P"}, {"amended": True}, {"form": "1040-NR"},
])
def test_without_a_matching_federal_return_the_question_is_left_to_the_filer(other):
    # another year, another taxpayer, an amended return, or a return the booklet's question does not name
    lines = _assemble(_federal("Schedule D", **other), _ca())
    line = _federal_copy(lines)
    assert "cannot answer it" in line and QUESTION in line and IF_YES in line and IF_NO in line
    assert not line.startswith(("Federal return copy: Yes", "Federal return copy: No"))


def test_the_exception_the_manifest_cannot_decide_is_printed_not_dropped():
    lines = _assemble(_federal("Schedule A"), _ca())
    assert any(line.startswith("Whether this applies is not in the manifest: Exception: If you did not itemize")
               for line in lines)


def test_an_attached_form_with_no_pack_must_be_copied_onto_the_official_blank():
    assert _federal_pack_key("8995") == "f8995" and _federal_pack_key("Schedule D") == "sched_d"
    lines = _assemble(_federal("Schedule D", "8949", "8995"), _ca())
    drafts = [line for line in lines if "UNMAPPED DRAFT" in line]
    assert len(drafts) == 1 and drafts[0].startswith("Form 8995: no TaxFill form pack ships for it in 2025")
    assert "copy its values onto the official blank before attaching it" in drafts[0]
    # every form here has a 2025 pack: nothing is said
    assert not any("UNMAPPED DRAFT" in line for line in _assemble(_federal("Schedule D", "8949", "8889"), _ca()))
    # a name of no known shape is never called pack-less
    assert _federal_pack_key("FinCEN 114") is None


def test_the_california_citations_name_the_assembly_sources():
    ret = next(r for r in file_and_pay([_federal("8889"), _ca()]).returns if r.jurisdiction == "states/ca")
    urls = {c.url for c in ret.citations}
    assert {"https://www.ftb.ca.gov/forms/2025/2025-540-booklet.html", "https://www.ftb.ca.gov/forms/2025/2025-540.pdf",
            "https://www.ftb.ca.gov/forms/2025/2025-540-ca.pdf"} <= urls


@pytest.mark.parametrize("jurisdiction, form, year", [
    ("states/ny", "IT-201", 2025), ("states/ga", "500", 2025), ("states/ca", "540", 2024), ("states/ca", "540", 2023),
])
def test_a_state_without_the_block_keeps_the_generic_line(jurisdiction, form, year):
    item = FilingManifestItem(form=form, tax_year=year, jurisdiction=jurisdiction, bottom_line=10)
    ret = file_and_pay([_federal("Schedule D", tax_year=year), item]).returns[1]
    assert ret.assemble == [_GENERIC_STATE_ASSEMBLE]
