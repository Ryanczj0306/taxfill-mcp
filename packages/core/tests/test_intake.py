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
    PriorFilings,
    Profile,
    Provenance,
    ResidencyFacts,
    Spouse,
    StateFootprintYear,
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


def test_residency_days_question_asks_all_three_lookback_years():
    # FIX: the SPT weighs the tax year AND the two preceding years — the question
    # must ask for all three up front (a missing year silently counts as 0 and can
    # misclassify a resident as nonresident).
    profile = Profile(identity=Identity(us_person=_ans(False)))
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "residency.days_in_us")
    assert "2021, 2022, 2023" in q.prompt
    assert "0 for a year spent entirely outside" in q.prompt
    assert "treated as 0" in q.why and "misclassify" in q.why


def test_residency_days_followup_when_preceding_years_missing():
    # Finding repro (H-1B frequent traveler): the target year is on file but the
    # two preceding period-covered years are not — intake must follow up, not
    # report the section complete.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2020, 2, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(150)}),
    )
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "residency.days_in_us")
    assert "2021, 2022" in q.prompt
    assert "2023" not in q.prompt  # already on file — only the gaps are asked


def test_residency_days_followup_covers_exempt_category_years():
    # Finding repro (F-1 dead-end): classify() demands a count for EVERY F/J/M/Q
    # calendar year; intake used to return zero residency questions here while
    # classify raised — the interview could never supply 2019-2022.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", start=date(2019, 8, 20), end=date(2023, 9, 30), provenance=US),
            VisaPeriod(status="H-1B", start=date(2023, 10, 1), provenance=US),
        ]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(365)}),
    )
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "residency.days_in_us")
    assert "2019, 2020, 2021, 2022" in q.prompt


def test_no_residency_days_followup_when_all_needed_years_known():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2021, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(150), 2022: _ans(300), 2023: _ans(300)}),
    )
    assert "residency.days_in_us" not in _ids(intake_checklist(profile, tax_year=2023))


def test_nonresident_note_hedged_while_covered_prior_years_missing():
    # Amplifier from the finding: a 'nonresident' computed from a days map missing
    # period-covered preceding years is NOT trustworthy — the MFJ/HOH restriction
    # must stay CONDITIONAL (real 2021/2022 counts could flip this filer to resident).
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2020, 2, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(150)}),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(profile, tax_year=2023)
    assert not any("cannot use married-filing-jointly" in n for n in cl.notes)
    assert any("if your residency result is nonresident" in n.lower() for n in cl.notes)


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


def test_confirmed_nra_asserts_status_restriction_unconditionally():
    # M3-RES-2: a visa holder who FAILS the Substantial Presence Test is a confirmed
    # nonresident alien (classify()=='nonresident'). The highest-stakes branch: the
    # 1040-NR status restriction is asserted as FACT (unconditionally), not hedged.
    # F-1 since Aug 2023 with only 120 days present -> the student exemption makes 2023
    # fully exempt -> 0 countable days -> SPT fails -> nonresident.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(
            visa_timeline=[VisaPeriod(status="F-1", start=date(2023, 8, 1), provenance=US)]
        ),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(120)}),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(profile, tax_year=2023)
    # The UNCONDITIONAL restriction note IS present (asserted as fact).
    assert any(
        "cannot use married-filing-jointly or head of household" in n for n in cl.notes
    )
    # ... and the residency-unknown CONDITIONAL hedge copy is ABSENT (this is the
    # confirmed-NRA branch, not the conditional one).
    assert not any("if your residency result is nonresident" in n.lower() for n in cl.notes)


def test_contradictory_timeline_falls_back_to_conditional_framing():
    # M3-RES-3: day counts are present but the visa timeline cannot cover them
    # (F-1 starts 2025, yet 120 days are reported for 2023) so classify() raises.
    # intake must NOT crash and must NOT assert the restriction as fact — it falls
    # back to the CONDITIONAL framing. This exercises the classify()-raising fallback,
    # distinct from test_nra_married_surfaces_6013 which has NO day counts at all.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(
            visa_timeline=[VisaPeriod(status="F-1", start=date(2025, 1, 1), provenance=US)]
        ),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(120)}),
        household=Household(marital_status=_ans("married")),
    )
    cl = intake_checklist(profile, tax_year=2023)
    # Conditional framing surfaced (the hedge), restriction NOT asserted as fact.
    assert any("if your residency result is nonresident" in n.lower() for n in cl.notes)
    assert not any(
        "cannot use married-filing-jointly or head of household" in n for n in cl.notes
    )


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


# ── FIX-3: the unmarried path must be able to reach ready_to_fill ──────────────


def _single_filer_core(**household_kwargs) -> Profile:
    return Profile(
        identity=Identity(
            name=_ans("Jordan Q Taxpayer"), tax_id=_ans("999001234"), dob=_ans(date(1990, 1, 1)),
            us_person=_ans(True), mailing_address=_ans("500 Market St, San Jose CA 95113"),
        ),
        household=Household(marital_status=_ans("unmarried"), **household_kwargs),
    )


def test_unmarried_filer_gets_filing_status_confirmation_after_hoh_answer():
    # Regression (finding): filing_status was never asked on the unmarried path, so
    # ready_to_fill was unreachable through the interview alone.
    profile = _single_filer_core(hoh_qualifying_person=_ans(False))
    cl = intake_checklist(profile)
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert fs.answers_into == "household.filing_status"
    assert "single" in fs.prompt


def test_unmarried_hoh_filer_is_offered_head_of_household():
    profile = _single_filer_core(hoh_qualifying_person=_ans(True))
    fs = next(q for q in intake_checklist(profile).next_questions if q.id == "household.filing_status")
    assert "head of household" in fs.prompt


def test_unmarried_confirmed_nra_is_confirmed_single_not_hoh():
    # Confirmed nonresident: the confirmation must steer to single (no HOH box on 1040-NR).
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2023, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(120)}),
        household=Household(marital_status=_ans("unmarried"), hoh_qualifying_person=_ans(True)),
    )
    fs = next(q for q in intake_checklist(profile, tax_year=2023).next_questions
              if q.id == "household.filing_status")
    assert "single" in fs.prompt and "head-of-household" in fs.prompt  # names the 1040-NR restriction


def test_widowed_filer_gets_filing_status_confirmation():
    # The widowed path must also produce a filing_status once its facts are in.
    profile = Profile(
        household=Household(
            marital_status=_ans("widowed"),
            spouse_death_year=_ans(2022),
            maintained_home_for_dependent_child=_ans(True),
        )
    )
    fs = next(q for q in intake_checklist(profile, tax_year=2023).next_questions
              if q.id == "household.filing_status")
    assert "surviving spouse" in fs.prompt


def test_interview_terminates_for_single_paper_check_filer():
    # Finding repro: the modal filer (single, childless, W-2, no direct deposit)
    # must reach ready_to_fill with ZERO questions left — the naive ask-resubmit
    # loop terminates instead of re-asking dependents/banking forever.
    profile = _single_filer_core(hoh_qualifying_person=_ans(False), filing_status=_ans("single"))
    profile.state_footprint = {2023: StateFootprintYear()}
    profile.income_documents = [
        IncomeDocument(kind="W-2", status="have", provenance=US),
        IncomeDocument(kind="1095-A", status="not_applicable", provenance=US),  # 'no marketplace coverage'
    ]
    profile.prior_filings = PriorFilings(filed_years=_ans([2022]))
    cl = intake_checklist(profile, tax_year=2023)
    assert cl.ready_to_fill is True
    assert cl.next_questions == []  # banking stays None ('paper check') and nothing repeats


def test_dependents_question_stops_once_filing_status_is_confirmed():
    # Empty-list dependents ('none') is indistinguishable from not-asked in the
    # schema, so the question is gated off once the filing status is confirmed.
    asking = _single_filer_core(hoh_qualifying_person=_ans(False))
    assert "household.dependents" in _ids(intake_checklist(asking))
    confirmed = _single_filer_core(hoh_qualifying_person=_ans(False), filing_status=_ans("single"))
    assert "household.dependents" not in _ids(intake_checklist(confirmed))


def test_banking_question_only_accompanies_other_pending_questions():
    # Declining direct deposit is unrepresentable (Banking checksum-validates), so
    # the optional banking question must never be the lone repeating question.
    assert "banking.account" in _ids(intake_checklist())  # normal interview: asked
    complete = _single_filer_core(hoh_qualifying_person=_ans(False), filing_status=_ans("single"))
    complete.state_footprint = {2023: StateFootprintYear()}
    complete.income_documents = [
        IncomeDocument(kind="W-2", status="have", provenance=US),
        IncomeDocument(kind="1095-A", status="not_applicable", provenance=US),
    ]
    complete.prior_filings = PriorFilings(filed_years=_ans([2022]))
    assert "banking.account" not in _ids(intake_checklist(complete, tax_year=2023))


# ── FIX-4: Phase F facts the estimator depends on (Tier-1 subset) ──────────────


def test_dependent_followups_asked_until_dob_and_ssn_known():
    # A name-only dependent is EXCLUDED from CTC/ODC/EITC by the estimator — intake
    # must chase the two gating facts per dependent.
    profile = Profile(
        household=Household(
            marital_status=_ans("married"),
            dependents=[Dependent(name="Casey Lee", relationship="child", provenance=US)],
        )
    )
    cl = intake_checklist(profile)
    dob_q = next(q for q in cl.next_questions if q.id == "household.dependents[0].dob")
    ssn_q = next(q for q in cl.next_questions if q.id == "household.dependents[0].has_ssn")
    assert "Casey Lee" in dob_q.prompt and "Child Tax Credit" in dob_q.why
    assert "work-eligible" in ssn_q.prompt and "EITC" in ssn_q.why
    assert dob_q.answers_into == "household.dependents[0].dob"


def test_no_dependent_followups_when_facts_complete():
    profile = Profile(
        household=Household(
            marital_status=_ans("married"),
            dependents=[Dependent(name="Casey Lee", relationship="child",
                                  dob=date(2015, 4, 1), has_ssn=True, provenance=US)],
        )
    )
    ids = _ids(intake_checklist(profile))
    assert not any(i.startswith("household.dependents[") for i in ids)


def test_marketplace_coverage_asked_until_a_1095a_entry_exists():
    # The 1095-A is the one document whose omission freezes refunds (Form 8962).
    q = next(q for q in intake_checklist(tax_year=2023).next_questions
             if q.id == "income_documents.marketplace_coverage")
    assert "Marketplace" in q.prompt and "2023" in q.prompt
    assert "8962" in q.why
    assert "not_applicable" in (q.disambiguation or "")  # 'no' is recordable -> no loop
    covered = Profile(income_documents=[IncomeDocument(kind="1095-A", status="have", provenance=US)])
    assert "income_documents.marketplace_coverage" not in _ids(intake_checklist(covered, tax_year=2023))
    declined = Profile(income_documents=[IncomeDocument(kind="1095-A", status="not_applicable", provenance=US)])
    assert "income_documents.marketplace_coverage" not in _ids(intake_checklist(declined, tax_year=2023))


# ── FIX-5: FICA withheld in error on exempt F/J filers ─────────────────────────


def test_confirmed_nra_f1_gets_fica_recovery_note():
    # F-1 exempt individuals owe no Social Security/Medicare; boxes 4/6 on a W-2
    # mean employer error — the Form 843 + 8316 recovery path must be surfaced.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2023, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(120)}),
    )
    cl = intake_checklist(profile, tax_year=2023)
    note = next(n for n in cl.notes if "FICA" in n)
    assert "boxes 4 and 6" in note
    assert "Form 843" in note and "Form 8316" in note
    assert "3121(b)(19)" in note
    assert "separate" in note.lower()  # recovery is NOT part of this return


def test_fica_note_hedged_while_residency_unknown_and_absent_for_others():
    # No day counts yet: the note is framed conditionally.
    unknown = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="J-1 researcher", start=date(2023, 1, 1), provenance=US)]),
    )
    note = next(n for n in intake_checklist(unknown, tax_year=2023).notes if "FICA" in n)
    assert note.startswith("If your residency result is nonresident")
    # US persons and non-F/J visa holders get no FICA note.
    assert not any("FICA" in n for n in intake_checklist(Profile(identity=Identity(us_person=_ans(True)))).notes)
    h1b_only = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2022, 1, 1), provenance=US)]),
    )
    assert not any("FICA" in n for n in intake_checklist(h1b_only, tax_year=2023).notes)
    # A computed RESIDENT alien (H-1B passing the SPT would be caught above; an F-1
    # past the exempt window) is generally FICA-liable -> no note either.
    resident_f1 = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2017, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(330) for y in range(2017, 2024)}),
    )
    assert not any("FICA" in n for n in intake_checklist(resident_f1, tax_year=2023).notes)


# ── Tier-2: the NRA-spouse §6013(g)/(h) battery (finding: Spouse.us_person/
# immigration/residency_facts were dead fields — the election never surfaced for
# a US-person filer with a nonresident spouse) ─────────────────────────────────


def _citizen_married(spouse=None) -> Profile:
    return Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married"), spouse=spouse),
    )


def test_married_path_asks_spouse_us_person_first():
    cl = intake_checklist(_citizen_married(), tax_year=2023)
    q = next(q for q in cl.next_questions if q.id == "household.spouse.us_person")
    assert q.answers_into == "household.spouse.us_person"
    assert "6013" in q.why
    assert "green-card" in (q.disambiguation or "")
    # The deeper battery waits for the gate answer (mirrors identity.us_person gating).
    ids = _ids(cl)
    assert "household.spouse.visa_timeline" not in ids
    assert "household.spouse.days_in_us" not in ids
    assert "household.spouse.section_6013_election" not in ids


def test_us_person_spouse_ends_the_battery():
    cl = intake_checklist(_citizen_married(Spouse(us_person=_ans(True))), tax_year=2023)
    ids = _ids(cl)
    assert "household.spouse.us_person" not in ids       # answered — never re-asked
    assert "household.spouse.visa_timeline" not in ids
    assert "household.spouse.days_in_us" not in ids
    assert "household.spouse.section_6013_election" not in ids
    assert not any("6013" in n for n in cl.notes)


def test_nra_spouse_battery_asks_visa_days_and_election():
    cl = intake_checklist(_citizen_married(Spouse(us_person=_ans(False))), tax_year=2023)
    ids = _ids(cl)
    assert {"household.spouse.visa_timeline", "household.spouse.days_in_us",
            "household.spouse.section_6013_election"} <= ids
    visa_q = next(q for q in cl.next_questions if q.id == "household.spouse.visa_timeline")
    assert visa_q.answers_into == "household.spouse.immigration.visa_timeline"
    assert "date ranges" in (visa_q.disambiguation or "")   # reuses the P-004 pattern
    days_q = next(q for q in cl.next_questions if q.id == "household.spouse.days_in_us")
    assert days_q.answers_into == "household.spouse.residency_facts.days_in_us"
    assert "2021, 2022, 2023" in days_q.prompt              # the SPT lookback set, spouse's own facts
    el = next(q for q in cl.next_questions if q.id == "household.spouse.section_6013_election")
    assert el.answers_into == "household.filing_status"     # deciding the election IS the status choice
    assert "may be a nonresident alien" in el.prompt        # conditional — residency not computable yet
    d = el.disambiguation or ""
    assert "WORLDWIDE" in d and "'NRA'" in d and "signed by BOTH spouses" in d
    # The filing-status disambiguation carries the spouse-direction §6013 rider too.
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "6013" in (fs.disambiguation or "") and "worldwide income" in fs.disambiguation


def test_nra_spouse_tax_id_question_carries_the_w7_route():
    # Finding repro: 'What is your spouse's SSN or ITIN?' was a literal dead end for
    # a spouse with neither — the question must name the W-7-with-the-return path.
    q = next(q for q in intake_checklist(_citizen_married(Spouse(us_person=_ans(False))),
                                         tax_year=2023).next_questions
             if q.id == "household.spouse.tax_id")
    assert "Does your spouse have an SSN or ITIN" in q.prompt
    d = q.disambiguation or ""
    assert "Form W-7" in d and "WITH the return" in d
    assert "ITIN Operation" in d and "Austin" in d
    assert "'NRA'" in d  # the MFS no-TIN spouse-SSN-box literal


def test_spouse_days_followup_asks_only_missing_years():
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-2", start=date(2019, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(300)}),
    )
    q = next(q for q in intake_checklist(_citizen_married(spouse), tax_year=2023).next_questions
             if q.id == "household.spouse.days_in_us")
    assert "2019, 2020, 2021, 2022" in q.prompt  # exempt-category years + SPT lookbacks
    assert "2023" not in q.prompt                # already on file — only the gaps are asked


def test_spouse_resident_by_own_facts_needs_no_election():
    # H-4 spouse present 365 days x3: their OWN facts classify resident — a joint
    # return needs no §6013 election, and intake says so instead of asking.
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-4", start=date(2021, 1, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(365) for y in (2021, 2022, 2023)}),
    )
    cl = intake_checklist(_citizen_married(spouse), tax_year=2023)
    assert "household.spouse.section_6013_election" not in _ids(cl)
    assert any("RESIDENT alien" in n and "without a §6013(g)/(h) election" in n for n in cl.notes)
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "6013" not in (fs.disambiguation or "")


def test_confirmed_nra_spouse_election_is_asserted_not_hedged():
    # F-2 dependent (exempt-individual family): the spouse's own facts classify
    # NONRESIDENT — the election question drops the conditional framing.
    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-2", start=date(2022, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(0), 2022: _ans(140), 2023: _ans(330)}),
    )
    cl = intake_checklist(_citizen_married(spouse), tax_year=2023)
    el = next(q for q in cl.next_questions if q.id == "household.spouse.section_6013_election")
    assert el.prompt.startswith("Your spouse's residency result is NONRESIDENT alien.")
    assert "may be a nonresident alien" not in el.prompt
    assert any(n.startswith("Your spouse's residency result is nonresident alien") for n in cl.notes)


def test_ra_taxpayer_with_nra_spouse_does_not_get_all_statuses_note():
    # Finding repro: an H-1B resident alien married to a declared non-US-person got
    # the unconditional 'all filing statuses are available' note — wrong law when the
    # spouse is an NRA (§6013(a)(1)). The spouse-direction §6013 note replaces it.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2021, 1, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(365) for y in (2021, 2022, 2023)}),
        household=Household(marital_status=_ans("married"), spouse=Spouse(us_person=_ans(False))),
    )
    cl = intake_checklist(profile, tax_year=2023)
    assert not any("all filing statuses" in n.lower() for n in cl.notes)
    assert any("§6013(g)/(h)" in n and "worldwide income" in n for n in cl.notes)


def test_spouse_battery_stops_when_all_facts_answered():
    # No looping: every spouse fact answered + a chosen filing status leaves ZERO
    # spouse questions (the 'NRA' literal records a no-TIN MFS spouse).
    spouse = Spouse(
        name=_ans("Ha-eun Kim"), tax_id=_ans("NRA"), us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-2", start=date(2022, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(0), 2022: _ans(140), 2023: _ans(330)}),
    )
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("married"),
                            filing_status=_ans("married_filing_separately"), spouse=spouse),
    )
    ids = _ids(intake_checklist(profile, tax_year=2023))
    assert not any(i.startswith("household.spouse.") for i in ids)
