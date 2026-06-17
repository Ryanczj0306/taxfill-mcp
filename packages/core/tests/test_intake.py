"""intake_checklist tests (dev plan section 4). All data synthetic."""

from datetime import date

from taxfill_core.intake import IntakeChecklist, intake_checklist
from taxfill_core.schemas.profile import (
    Answer,
    Dependent,
    Household,
    Identity,
    Immigration,
    IncomeDocument,
    Profile,
    Provenance,
    ResidencyFacts,
    Spouse,
    VisaPeriod,
)

US = Provenance.user_stated()


def _ans(value):
    return Answer(value=value, provenance=US)


def _ids(checklist: IntakeChecklist) -> set[str]:
    return {q.id for q in checklist.next_questions}


def test_empty_profile_opens_with_identity_questions():
    cl = intake_checklist()
    ids = _ids(cl)
    assert {"identity.name", "identity.tax_id", "identity.us_person", "identity.mailing_address"} <= ids
    assert cl.ready_to_fill is False
    assert cl.progress == "0 of 8 sections started"


def test_mailing_address_carries_the_p002_disambiguation():
    q = next(q for q in intake_checklist().next_questions if q.id == "identity.mailing_address")
    assert q.disambiguation and "TODAY" in q.disambiguation
    assert "lived during the tax year" in q.disambiguation


def test_questions_already_answered_drop_off():
    profile = Profile(identity=Identity(name=_ans("Jordan Q Taxpayer")))
    assert "identity.name" not in _ids(intake_checklist(profile))


def test_us_person_skips_immigration_and_residency():
    profile = Profile(identity=Identity(us_person=_ans(True)))
    ids = _ids(intake_checklist(profile))
    assert not any(i.startswith(("immigration.", "residency.")) for i in ids)
    # No nonresident status restriction note for a US person.
    assert not any("1040-NR" in n for n in intake_checklist(profile).notes)


def test_nonresident_gets_immigration_and_residency_questions():
    profile = Profile(identity=Identity(us_person=_ans(False)))
    ids = _ids(intake_checklist(profile))
    assert "immigration.visa_timeline" in ids
    assert "residency.days_in_us" in ids
    visa_q = next(q for q in intake_checklist(profile).next_questions if q.id == "immigration.visa_timeline")
    # Visa facts captured as date-range periods (part of the treaty-mis-scoping
    # countermeasure; the full per-period treaty logic + eval remain deferred).
    assert visa_q.disambiguation and "date ranges" in visa_q.disambiguation


def test_tax_year_targets_the_residency_day_count():
    profile = Profile(identity=Identity(us_person=_ans(False)))
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "residency.days_in_us")
    assert "2023" in q.prompt


def test_marital_status_asked_before_filing_status():
    profile = Profile(household=Household())
    ids = _ids(intake_checklist(profile))
    assert "household.marital_status" in ids
    # filing_status depends on the marital answer, so it is NOT offered yet
    assert "household.filing_status" not in ids


def test_married_path_asks_jointly_or_separately_and_spouse_identity():
    profile = Profile(household=Household(marital_status=_ans("married")))
    cl = intake_checklist(profile)
    ids = _ids(cl)
    assert {"household.filing_status", "household.spouse.name", "household.spouse.tax_id"} <= ids
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "jointly" in fs.prompt and fs.disambiguation and "jointly liable" in fs.disambiguation


def test_nra_married_surfaces_6013_election_and_status_restriction():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(profile)
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "6013" in (fs.disambiguation or "")
    # Residency not yet computable (no day counts): the restriction is framed
    # CONDITIONALLY ("if your residency result is nonresident alien ...") rather
    # than asserted as fact.
    assert any("1040-NR" in n and "head-of-household" in n for n in cl.notes)
    assert any("if your residency result is nonresident" in n.lower() for n in cl.notes)


def test_unmarried_with_dependents_asks_head_of_household_determination():
    profile = Profile(
        household=Household(
            marital_status=_ans("unmarried"),
            dependents=[Dependent(name="Kid", relationship="child", provenance=US)],
        )
    )
    # The HOH qualifying-person test lands in its own FACT field, not filing_status.
    fs = next(q for q in intake_checklist(profile).next_questions if q.id == "household.hoh_qualifying_person")
    assert fs.answers_into == "household.hoh_qualifying_person"
    assert "qualifying person" in fs.prompt
    assert "head of household" in (fs.disambiguation or "")


def test_required_documents_for_f1_student():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2019, 8, 1), provenance=US)]),
        income_documents=[
            IncomeDocument(kind="W-2", status="have", provenance=US),
            IncomeDocument(kind="1098-T", status="missing", provenance=US),
        ],
    )
    docs = {d.kind: d.status for d in intake_checklist(profile).required_documents}
    assert {"passport_id_page", "visa", "I-94", "I-20"} <= set(docs)
    assert docs["W-2"] == "have" and docs["1098-T"] == "missing"


def test_us_person_has_no_immigration_documents():
    profile = Profile(identity=Identity(us_person=_ans(True)))
    kinds = {d.kind for d in intake_checklist(profile).required_documents}
    assert "I-94" not in kinds and "passport_id_page" not in kinds


def test_ready_to_fill_when_core_facts_present():
    profile = Profile(
        identity=Identity(
            name=_ans("Jordan Q Taxpayer"), tax_id=_ans("999001234"),
            us_person=_ans(True), mailing_address=_ans("500 Market St, San Jose CA 95113"),
        ),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        income_documents=[IncomeDocument(kind="W-2", status="have", provenance=US)],
    )
    cl = intake_checklist(profile)
    assert cl.ready_to_fill is True


def test_not_ready_to_fill_without_a_held_income_document():
    profile = Profile(
        identity=Identity(
            name=_ans("Jordan Q Taxpayer"), tax_id=_ans("999001234"),
            us_person=_ans(True), mailing_address=_ans("500 Market St"),
        ),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
        income_documents=[IncomeDocument(kind="W-2", status="missing", provenance=US)],
    )
    assert intake_checklist(profile).ready_to_fill is False


def test_questions_are_ordered_by_section_flow():
    profile = Profile(identity=Identity(us_person=_ans(False)))
    sections = [q.section for q in intake_checklist(profile).next_questions]
    order = ["identity", "immigration", "residency", "household", "state_footprint", "income_documents", "banking", "prior_filings"]
    ranks = [order.index(s) for s in sections]
    assert ranks == sorted(ranks)


def test_unmarried_nonresident_is_not_recommended_head_of_household():
    # M3-HOH-2: an unmarried NRA must NOT be steered to head of household
    # (Form 1040-NR has no HOH box) — the advice agrees with the gating note.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        household=Household(marital_status=_ans("unmarried")),
    )
    cl = intake_checklist(profile, tax_year=2023)
    hoh_q = next(q for q in cl.next_questions if q.id == "household.hoh_qualifying_person")
    # The disambiguation tells the NRA filer HOH is not an option for them.
    text = (hoh_q.disambiguation or "").lower()
    assert "no head-of-household box" in text or "cannot use head of household" in text
    # And it offers the 1040-NR-consistent statuses instead.
    assert "married-filing-separately" in text or "qualifying surviving spouse" in text


def test_qss_routed_for_widowed_filer_with_dependent_child():
    # M3-QSS-5: a widowed filer with a dependent child is asked the QSS-determining
    # questions, landing in the new Household fact fields.
    profile = Profile(
        household=Household(
            marital_status=_ans("widowed"),
            dependents=[Dependent(name="Kid", relationship="child", provenance=US)],
        )
    )
    cl = intake_checklist(profile)
    ids = _ids(cl)
    assert "household.spouse_death_year" in ids
    assert "household.maintained_home_for_dependent_child" in ids
    qss_q = next(q for q in cl.next_questions if q.id == "household.maintained_home_for_dependent_child")
    assert qss_q.answers_into == "household.maintained_home_for_dependent_child"
    assert "surviving spouse" in (qss_q.disambiguation or "").lower()


def test_bare_f1_student_checklist_seeds_w2_and_1098t_missing():
    # M3-DOC-4: an NRA student (us_person False + an F-1 period) with no declared
    # income documents gets W-2 and 1098-T seeded as honest gaps (status="missing").
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2022, 8, 1), provenance=US)]),
    )
    docs = {d.kind: d.status for d in intake_checklist(profile).required_documents}
    assert docs.get("W-2") == "missing"
    assert docs.get("1098-T") == "missing"
    # F-1 student status documents are still in the checklist too.
    assert {"passport_id_page", "visa", "I-94", "I-20"} <= set(docs)


def test_resident_alien_passing_spt_keeps_mfj_and_hoh_available():
    # M3-RES-1: a visa holder who PASSES the Substantial Presence Test is a resident
    # alien who CAN use MFJ/HOH — the 1040-NR restriction note must NOT be asserted.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(
            visa_timeline=[VisaPeriod(status="H-1B", start=date(2021, 1, 1), provenance=US)]
        ),
        residency_facts=ResidencyFacts(
            days_in_us={
                2021: _ans(365),
                2022: _ans(365),
                2023: _ans(365),
            }
        ),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(profile, tax_year=2023)
    # No nonresident restriction; instead an affirmative "all statuses available" note.
    assert not any("cannot use married-filing-jointly" in n for n in cl.notes)
    assert any("resident alien" in n.lower() and "all filing statuses" in n.lower() for n in cl.notes)
    # The §6013 election does NOT arise for a resident alien.
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "6013" not in (fs.disambiguation or "")
