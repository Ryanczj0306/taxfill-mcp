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
    ResidencePeriod,
    ResidencyFacts,
    Spouse,
    StateFootprintYear,
    VisaPeriod,
    WorkPeriod,
)

# A complete single-state footprint: the modal filer LIVES and WORKS somewhere.
# The old shortcut `StateFootprintYear()` (an empty entry) only passed for
# "answered" because of the short-circuit bug this suite now guards against —
# an empty entry would make state_scope report NO state returns for a filer who
# plainly has one.
def _one_state_footprint(year, state="CA"):
    from datetime import date
    return StateFootprintYear(
        lived=[ResidencePeriod(state=state, start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)],
        worked=[WorkPeriod(state=state, start=date(year, 1, 1), end=date(year, 12, 31), provenance=US)],
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
    assert cl.progress == "0 of 9 sections started"


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
    # Visa facts captured as date-range periods, SEGMENT BY SEGMENT (P-004 + H1):
    # the question carries a worked F-1→OPT→H-1B example, the sub_status
    # vocabulary, and the I-797 disambiguation for the H-1B start date.
    assert "SEGMENT BY SEGMENT" in visa_q.prompt and "start/end dates" in visa_q.prompt
    assert visa_q.disambiguation and "Worked example" in visa_q.disambiguation
    assert "I-797" in visa_q.disambiguation and "stem_opt" in visa_q.disambiguation


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
    # no_other_taxpayers answers the H2 household question (an unmarried filer is
    # asked who else in the household files their own return, until answered).
    household_kwargs.setdefault("no_other_taxpayers", _ans(True))
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
    profile.state_footprint = {2023: _one_state_footprint(2023)}
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
    complete.state_footprint = {2023: _one_state_footprint(2023)}
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


# ── Phase G item G2: the dependent-care (Form 2441) question ───────────────────


def _parent_profile(**doc_kwargs):
    docs = doc_kwargs.pop("income_documents", [])
    return Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(
            marital_status=_ans("unmarried"), hoh_qualifying_person=_ans(True),
            filing_status=_ans("head_of_household"),
            dependents=[Dependent(name="Kid", relationship="child", dob=date(2018, 1, 1),
                                  has_ssn=True, provenance=US)],
        ),
        income_documents=docs,
    )


def test_dependent_care_question_fires_when_dependents_exist():
    cl = intake_checklist(_parent_profile(), tax_year=2023)
    q = next(q for q in cl.next_questions if q.id == "household.dependent_care")
    assert "pay anyone to care" in q.prompt and "work" in q.prompt
    assert "Form 2441" in q.why
    d = q.disambiguation or ""
    # The answer is recorded through the document inventory (1095-A pattern):
    # a yes adds a provider-statement entry; a no records 'not_applicable'.
    assert "dependent care provider statement" in d
    assert "TIN" in d                      # Form 2441 Part I needs the provider TIN
    assert "dependent_care_credit" in d    # the calc op is named
    assert "not_applicable" in d
    assert q.answers_into == "income_documents"


def test_dependent_care_question_names_both_spouses_when_married():
    profile = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(
            marital_status=_ans("married"), filing_status=_ans("married_filing_jointly"),
            spouse=Spouse(name=_ans("Spouse Q."), tax_id=_ans("123-45-6789"), us_person=_ans(True)),
            dependents=[Dependent(name="Kid", relationship="child", dob=date(2018, 1, 1),
                                  has_ssn=True, provenance=US)],
        ),
    )
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions
             if q.id == "household.dependent_care")
    assert "(both spouses)" in q.prompt


def test_dependent_care_question_stops_once_recorded_any_status():
    # A recorded entry in ANY status stops the question — including the
    # 'not_applicable' no (and any kind wording mentioning dependent care/2441).
    for kind, status in (
        ("dependent care provider statement", "have"),
        ("Form 2441 provider info", "missing"),
        ("childcare receipts", "not_applicable"),
    ):
        profile = _parent_profile(
            income_documents=[IncomeDocument(kind=kind, status=status, provenance=US)]
        )
        assert "household.dependent_care" not in _ids(intake_checklist(profile, tax_year=2023)), kind


def test_dependent_care_question_absent_without_dependents():
    no_deps = Profile(
        identity=Identity(us_person=_ans(True)),
        household=Household(marital_status=_ans("unmarried"), filing_status=_ans("single")),
    )
    assert "household.dependent_care" not in _ids(intake_checklist(no_deps, tax_year=2023))


# ── Phase G item G6: the FICA note asks about employer refusal (843 + 8316) ────


def test_fica_note_asks_the_employer_refusal_question_with_the_claim_amount():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2023, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(120)}),
    )
    note = next(n for n in intake_checklist(profile, tax_year=2023).notes if "FICA" in n)
    # The follow-up question and the concrete claim-amount rule.
    assert "did your employer refuse or fail to refund" in note
    assert "box 4 + box 6" in note
    # The 843+8316 path is named, with 8316 as the employer-refusal statement
    # and the file_and_pay manifest shape.
    assert "Form 8316 serves as" in note
    assert "attached_forms" in note and "'843'" in note and "'8316'" in note


# ── The state-footprint short-circuit (Stage 0 correctness fix) ────────────────
# The old logic returned early whenever ANY footprint entry existed, so three
# real configurations produced ZERO state questions for the asked year — and
# state_scope then ran on a footprint the user never gave. Reproduced 2026-08-07.


def _footprint_qs(profile, tax_year):
    return [q for q in intake_checklist(profile, tax_year=tax_year).next_questions if q.section == "state_footprint"]


def test_a_different_years_footprint_never_silences_the_asked_year():
    profile = Profile(state_footprint={2023: _one_state_footprint(2023)})
    qs = _footprint_qs(profile, 2025)
    assert qs, "a 2023 answer must not pass for a 2025 one"
    # The question names the asked year and warns that the stale year does not carry.
    assert "2025" in qs[0].prompt
    assert "2023" in qs[0].why and "never carries over" in qs[0].why


def test_an_empty_footprint_entry_is_not_an_answer():
    profile = Profile(state_footprint={2025: StateFootprintYear()})
    assert _footprint_qs(profile, 2025), "an empty entry is 'not asked yet', not 'none'"


def test_lived_without_worked_keeps_asking_for_the_missing_dimension():
    lived_only = StateFootprintYear(lived=_one_state_footprint(2025).lived)
    qs = _footprint_qs(Profile(state_footprint={2025: lived_only}), 2025)
    assert qs
    assert "WORKED" in qs[0].prompt and "LIVED" not in qs[0].prompt  # only the missing half is re-asked


def test_the_explicit_none_sentinels_terminate_the_question():
    # Someone with no US job (or abroad all year) must still be able to FINISH
    # the interview — an explicit 'none' ends the question; an empty list never does.
    lived_no_work = StateFootprintYear(lived=_one_state_footprint(2025).lived, no_us_work=True)
    assert not _footprint_qs(Profile(state_footprint={2025: lived_no_work}), 2025)
    abroad = StateFootprintYear(no_us_residence=True, no_us_work=True)
    assert not _footprint_qs(Profile(state_footprint={2025: abroad}), 2025)


# ── Phase H (H1): segment-by-segment visa elicitation + contiguity ─────────────


def test_visa_timeline_gap_between_periods_gets_a_contiguity_note():
    # F-1 ends May 15, H-1B starts Oct 1 — the uncovered months are exactly where
    # residency day counts and FICA flip, so the gap must be surfaced, not skipped.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", sub_status="student", start=date(2021, 8, 20), end=date(2025, 5, 15), provenance=US),
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2025, 10, 1), provenance=US),
        ]),
    )
    notes = intake_checklist(profile).notes
    assert any("Visa timeline gap" in n and "F-1" in n and "H-1B" in n for n in notes)


def test_visa_period_with_no_end_before_a_later_period_gets_a_note():
    # An open-ended earlier period with a successor is a data error: the boundary
    # date IS the tax answer (I-797 start for an F-1→H-1B change).
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", sub_status="opt", start=date(2024, 6, 1), provenance=US),
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2026, 10, 1), provenance=US),
        ]),
    )
    notes = intake_checklist(profile).notes
    assert any("no end" in n and "I-797" in n for n in notes)


def test_contiguous_timeline_gets_no_gap_note():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", sub_status="opt", start=date(2024, 6, 1), end=date(2026, 9, 30), provenance=US),
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2026, 10, 1), provenance=US),
        ]),
    )
    assert not any("gap" in n.lower() for n in intake_checklist(profile).notes)


def test_sub_status_alone_marks_an_f1_period():
    # _has_f1_period must prefer the H1 vocabulary: OPT recorded with a bare
    # status string still counts as an F-1 posture via sub_status.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="Optional Practical Training", sub_status="opt", start=date(2025, 6, 1), provenance=US),
        ]),
    )
    docs = {d.kind for d in intake_checklist(profile).required_documents}
    # The NRA-student document seeding keys on _has_f1_period.
    assert {"W-2", "1098-T"} <= docs


# ── Phase H (H2): other taxpayers in the household ─────────────────────────────


def test_unmarried_filer_is_asked_who_else_files_until_answered():
    profile = _single_filer_core(no_other_taxpayers=None)
    q = next(q for q in intake_checklist(profile).next_questions if q.id == "household.other_taxpayers")
    assert "file their own tax return" in q.prompt
    assert q.disambiguation and "no_other_taxpayers" in q.disambiguation
    # The sentinel ends it; an empty list does not.
    answered = _single_filer_core()  # helper sets no_other_taxpayers=True
    assert "household.other_taxpayers" not in _ids(intake_checklist(answered))


def test_married_filer_is_not_asked_about_other_taxpayers():
    profile = Profile(household=Household(marital_status=_ans("married")))
    assert "household.other_taxpayers" not in _ids(intake_checklist(profile))


def test_nra_partner_household_gets_the_three_guard_notes():
    from taxfill_core.schemas.profile import OtherTaxpayer

    profile = _single_filer_core(other_taxpayers=[
        OtherTaxpayer(name="Partner P", relationship="unmarried_partner", us_person=False,
                      note="NRA on OPT, files 1040-NR", provenance=US),
    ])
    notes = intake_checklist(profile).notes
    assert any("file SEPARATELY" in n for n in notes)                       # two returns, no MFJ
    assert any("§152(b)(3)" in n for n in notes)                            # no dependent claim for an NRA partner
    assert any("compare_scenarios" in n and "6013" in n for n in notes)     # price the marry-in-year branch


def test_us_person_partner_skips_the_dependent_guard():
    from taxfill_core.schemas.profile import OtherTaxpayer

    profile = _single_filer_core(other_taxpayers=[
        OtherTaxpayer(name="Partner P", relationship="unmarried_partner", us_person=True, provenance=US),
    ])
    notes = intake_checklist(profile).notes
    assert any("file SEPARATELY" in n for n in notes)
    assert not any("§152(b)(3)" in n for n in notes)


# ── Phase H (H3): segment loop, triggers, remote employer follow-up ────────────


def test_state_footprint_question_is_segment_shaped_with_the_trigger_checklist():
    qs = _footprint_qs(Profile(), 2023)
    q = qs[0]
    assert "SEGMENTS" in q.prompt
    d = q.disambiguation or ""
    # The 7-trigger checklist from the worksheet's Part 4.
    for marker in ("moved across state lines", "REMOTELY", "~30 days", "internship",
                   "W-2 Box 15", "outside the US", "WA/TX/FL/NV/SD/WY/AK/TN/NH"):
        assert marker in d, f"missing trigger: {marker}"
    assert "no_us_residence" in d  # the sentinels stay explained


def test_remote_segment_without_employer_state_gets_a_followup():
    fp = StateFootprintYear(
        lived=[ResidencePeriod(state="WA", start=date(2025, 1, 1), end=date(2025, 12, 31), provenance=US)],
        worked=[WorkPeriod(state="WA", start=date(2025, 1, 1), end=date(2025, 12, 31), remote=True, provenance=US)],
    )
    qs = _footprint_qs(Profile(state_footprint={2025: fp}), 2025)
    assert [q.id for q in qs] == ["state_footprint.remote_employer_state"]
    assert "convenience-of-the-employer" in qs[0].why


def test_employer_state_answer_ends_the_remote_followup():
    fp = StateFootprintYear(
        lived=[ResidencePeriod(state="WA", start=date(2025, 1, 1), end=date(2025, 12, 31), provenance=US)],
        worked=[WorkPeriod(state="WA", start=date(2025, 1, 1), end=date(2025, 12, 31), remote=True,
                           employer_state="WA", provenance=US)],
    )
    assert not _footprint_qs(Profile(state_footprint={2025: fp}), 2025)


def test_non_remote_segments_get_no_employer_followup():
    assert not _footprint_qs(Profile(state_footprint={2025: _one_state_footprint(2025)}), 2025)


# ── Phase H (N-11): the Roth/pre-tax deferral split, planning years only ───────


def test_planning_year_asks_for_the_deferral_split():
    q = next(q for q in intake_checklist(Profile(), tax_year=2026).next_questions
             if q.id == "retirement.deferral_split")
    assert "TAX CHARACTER" in q.prompt
    assert q.disambiguation and "402(g)" in q.disambiguation and "6%" in q.disambiguation


def test_closed_year_does_not_ask_for_the_deferral_split():
    # For a closed year the split is a W-2 box 12 fact — re-asking collects a
    # worse copy of a document.
    assert "retirement.deferral_split" not in _ids(intake_checklist(Profile(), tax_year=2023))


def test_answered_deferral_split_stops_the_question_and_counts_as_a_section():
    from taxfill_core.schemas.profile import RetirementContributionsYear

    rc = RetirementContributionsYear(pretax_401k=_ans(12000), roth_401k=_ans(6000))
    profile = Profile(retirement_contributions={2026: rc})
    cl = intake_checklist(profile, tax_year=2026)
    assert "retirement.deferral_split" not in _ids(cl)
    assert cl.progress == "1 of 9 sections started"


def test_recorded_roth_ira_amount_gets_the_excise_pointer_note():
    from taxfill_core.schemas.profile import RetirementContributionsYear

    rc = RetirementContributionsYear(roth_ira=_ans(7000))
    cl = intake_checklist(Profile(retirement_contributions={2026: rc}), tax_year=2026)
    assert any("ira_contribution_eligibility" in n and "6%" in n and "YEAR-END" in n for n in cl.notes)


# ── Phase H (N-14): the election-not-the-marriage push-back ────────────────────


def test_nra_spouse_note_distinguishes_the_election_from_the_marriage():
    # Two real sessions concluded "married ⇒ the §871(i) exclusion is gone" straight
    # from the label; the note must state the distinction unprompted.
    profile = Profile(
        household=Household(
            marital_status=_ans("married"),
            spouse=Spouse(name=_ans("Spouse S"), us_person=_ans(False)),
        )
    )
    notes = intake_checklist(profile).notes
    assert any("ELECTION, not the marriage" in n and "871(i)" in n for n in notes)
    assert any("FICA" in n and "STATUS-based" in n for n in notes)
