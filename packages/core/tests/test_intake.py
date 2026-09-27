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
    # classify raised — the interview could never supply 2018-2021.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", start=date(2018, 8, 24), end=date(2022, 9, 30), provenance=US),
            VisaPeriod(status="H-1B", start=date(2022, 10, 1), provenance=US),
        ]),
        residency_facts=ResidencyFacts(days_in_us={2022: _ans(365)}),
    )
    q = next(q for q in intake_checklist(profile, tax_year=2022).next_questions if q.id == "residency.days_in_us")
    assert "2018, 2019, 2020, 2021" in q.prompt


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
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2020, 8, 1), provenance=US)]),
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
        # 'no foreign accounts' — the I4 elicitation (income_documents.foreign_accounts)
        # repeats until the inventory records an answer in SOME status, exactly as the
        # 1095-A question above does, so a terminating interview has to carry both NOs.
        IncomeDocument(kind="foreign account statement", status="not_applicable", provenance=US),
    ]
    profile.prior_filings = PriorFilings(filed_years=_ans([2022]))
    cl = intake_checklist(profile, tax_year=2023)
    assert cl.ready_to_fill is True
    assert cl.next_questions == []  # banking stays None (no direct deposit) and nothing repeats


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
        IncomeDocument(kind="foreign account statement", status="not_applicable", provenance=US),
    ]
    complete.prior_filings = PriorFilings(filed_years=_ans([2022]))
    assert "banking.account" not in _ids(intake_checklist(complete, tax_year=2023))


def test_banking_question_does_not_offer_a_paper_refund_check():
    # TY26-15: irs.gov/ModernPayments announces the phase-out of paper refund checks,
    # so the optional banking question must not suggest a mailed check as the fallback.
    q = next(q for q in intake_checklist().next_questions if q.id == "banking.account")
    assert "you can also get a paper check" not in q.disambiguation
    assert "phase out of paper tax refund checks beginning Sept. 30, 2025" in q.disambiguation


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
    # P-018: the election is a residency FACT, recorded where the estimator and the
    # residency tool read it — no longer only implied by the chosen status.
    assert el.answers_into == "residency_facts.section_6013_election"
    assert "compare_scenarios" in (el.disambiguation or "")
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
    # F-1 ends May 17, H-1B starts Oct 1 — the uncovered months are exactly where
    # residency day counts and FICA flip, so the gap must be surfaced, not skipped.
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", sub_status="student", start=date(2022, 8, 24), end=date(2024, 5, 17), provenance=US),
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2024, 10, 1), provenance=US),
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
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2025, 10, 1), provenance=US),
        ]),
    )
    notes = intake_checklist(profile).notes
    assert any("no end" in n and "I-797" in n for n in notes)


def test_contiguous_timeline_gets_no_gap_note():
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status="F-1", sub_status="opt", start=date(2024, 6, 1), end=date(2025, 9, 30), provenance=US),
            VisaPeriod(status="H-1B", sub_status="employment", start=date(2025, 10, 1), provenance=US),
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
                      note="NRA (J-1 research scholar), files 1040-NR", provenance=US),
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
    # The label invites the wrong conclusion "married ⇒ the §871(i) exclusion is
    # gone"; the note must state the distinction unprompted.
    profile = Profile(
        household=Household(
            marital_status=_ans("married"),
            spouse=Spouse(name=_ans("Spouse S"), us_person=_ans(False)),
        )
    )
    notes = intake_checklist(profile).notes
    assert any("ELECTION, not the marriage" in n and "871(i)" in n for n in notes)
    assert any("FICA" in n and "STATUS-based" in n for n in notes)


# ── N-8 / pitfall P-013: the nonresident's 1099-INT — deposit or not? ──────────
# The estimator excludes a nonresident's US bank-deposit interest (IRC
# 871(i)(2)(A)) only when it is CHARACTERIZED, so intake asks the character once,
# for a CONFIRMED nonresident whose inventory holds an uncharacterized 1099-INT.

_INTEREST_Q = "income_documents.interest_character"


def _confirmed_nra(*docs: IncomeDocument) -> Profile:
    # Sample F-1 arriving in 2020: 2023 is an exempt year, so the SPT fails -> nonresident.
    return Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2020, 8, 24), provenance=US)]),
        residency_facts=ResidencyFacts(
            days_in_us={y: _ans(d) for y, d in {2020: 130, 2021: 330, 2022: 330, 2023: 330}.items()}
        ),
        income_documents=list(docs),
    )


def _doc(kind: str, status: str = "have") -> IncomeDocument:
    return IncomeDocument(kind=kind, status=status, provenance=US)


def test_p013_confirmed_nonresident_with_a_1099_int_is_asked_its_character():
    # P-013: every spelling that names the FORM triggers the question.
    for kind in ("1099-INT", "1099INT", "Form 1099-INT (Chase)"):
        cl = intake_checklist(_confirmed_nra(_doc("W-2"), _doc(kind)), tax_year=2023)
        q = next((q for q in cl.next_questions if q.id == _INTEREST_Q), None)
        assert q is not None, kind
        assert q.section == "income_documents"
        assert "NONRESIDENT" in q.prompt and "DEPOSIT" in q.prompt
        assert "871(i)(2)(A)" in q.why and "Pub 519 ch. 3" in q.why and "Exception 3" in q.why
        assert "ENDS the exclusion; the marriage itself does not" in q.why   # N-14 / rule (c)
        assert "871(h)" in q.why   # non-deposit interest is not ALWAYS taxed — portfolio interest
        # The disambiguation records the answer (either way) and maps it onto the estimator.
        assert "'1099-INT (bank deposit)'" in q.disambiguation
        assert "'1099-INT (not a deposit" in q.disambiguation
        assert "bank_deposit_interest" in q.disambiguation and "BOTH `interest`" in q.disambiguation
    # A still-MISSING 1099-INT is asked too; a not_applicable one, and a
    # different form, are not.
    assert _INTEREST_Q in _ids(intake_checklist(_confirmed_nra(_doc("1099-INT", "missing")), tax_year=2023))
    assert _INTEREST_Q not in _ids(intake_checklist(_confirmed_nra(_doc("1099-INT", "not_applicable")), tax_year=2023))
    assert _INTEREST_Q not in _ids(intake_checklist(_confirmed_nra(_doc("1099-DIV")), tax_year=2023))


def test_p013_interest_character_is_silent_for_a_resident():
    # P-013: a resident's interest is all taxable — there is nothing to ask.
    citizen = Profile(identity=Identity(us_person=_ans(True)), income_documents=[_doc("1099-INT")])
    assert _INTEREST_Q not in _ids(intake_checklist(citizen, tax_year=2023))
    # A computed RESIDENT alien (an F-1 past the exempt window) is silent too.
    resident_f1 = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-1", start=date(2017, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(330) for y in range(2017, 2024)}),
        income_documents=[_doc("1099-INT")],
    )
    assert _INTEREST_Q not in _ids(intake_checklist(resident_f1, tax_year=2023))


def test_p013_interest_character_stops_once_the_kind_records_it():
    # P-013: either recorded answer spells DEPOSIT, so either one stops the question.
    for kind in ("1099-INT (bank deposit)", "1099-INT (not a deposit — brokerage/bond interest)",
                 "1099-INT Chase savings DEPOSIT account"):
        assert _INTEREST_Q not in _ids(intake_checklist(_confirmed_nra(_doc(kind)), tax_year=2023)), kind
    # ...but only per entry: a second, uncharacterized 1099-INT still asks.
    both = _confirmed_nra(_doc("1099-INT (bank deposit)"), _doc("1099-INT (Acme Brokerage)"))
    assert _INTEREST_Q in _ids(intake_checklist(both, tax_year=2023))


def test_p013_an_account_number_in_the_kind_never_records_the_character():
    # P-013, with P-012's rule applied to this matcher: the "recorded" token is a WORD, so an
    # account or routing number an agent writes into `kind` — even one full of the
    # form's own digits — can never silence the question.
    for kind in ("1099-INT acct 10990023", "1099-INT acct 1099 INT 4410", "1099-INT routing 021000021"):
        assert _INTEREST_Q in _ids(intake_checklist(_confirmed_nra(_doc(kind)), tax_year=2023)), kind


# ── P-018 (Phase J JF5a): the §6013(g)/(h) election is a residency FACT ────────
# Pub 519 (2025) ch. 1: "If you make this choice, you and your spouse are treated
# for income tax purposes as residents for your entire tax year." Intake records it
# once, as residency_facts.section_6013_election on the taxpayer, and — once it is
# recorded on a confirmed marriage — treats both spouses as residents, while the
# F/J FICA note keeps following the day counts (IRC 6013(g)(1): chapters 1 and 24).

_FACT_Q = "household.section_6013_election"


def _married_confirmed_nra(**household_kwargs) -> Profile:
    profile = _confirmed_nra()
    profile.household = Household(marital_status=_ans("married"), **household_kwargs)
    return profile


def _with_election(profile: Profile, value: bool) -> Profile:
    profile.residency_facts.section_6013_election = _ans(value)
    return profile


def test_p018_choosing_mfj_with_a_nonresident_asks_for_the_election_fact():
    # A joint return with a nonresident alien exists only under the election, so a
    # chosen MFJ status is not left to imply it: intake asks for the FACT.
    profile = _married_confirmed_nra(filing_status=_ans("married_filing_jointly"))
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == _FACT_Q)
    assert q.answers_into == "residency_facts.section_6013_election"
    assert "exists only under the §6013(g)/(h) election" in q.prompt
    assert "treated for income tax purposes as residents for your entire tax year" in q.why
    d = q.disambiguation or ""
    assert "signed by both spouses" in d and "compare_scenarios" in d
    assert "one spouse is a U.S. citizen or a resident alien" in d            # the precondition
    # Either answer stops it — a recorded fact is never re-asked.
    for value in (True, False):
        answered = _with_election(_married_confirmed_nra(filing_status=_ans("married_filing_jointly")), value)
        assert _FACT_Q not in _ids(intake_checklist(answered, tax_year=2023)), value
    # Not asked where no nonresident is involved, nor before MFJ is chosen.
    citizens = Profile(identity=Identity(us_person=_ans(True)),
                       household=Household(marital_status=_ans("married"),
                                           filing_status=_ans("married_filing_jointly"),
                                           spouse=Spouse(us_person=_ans(True))))
    assert _FACT_Q not in _ids(intake_checklist(citizens, tax_year=2023))
    assert _FACT_Q not in _ids(intake_checklist(_married_confirmed_nra(), tax_year=2023))
    # The citizen taxpayer's NRA-spouse direction asks it too.
    spouse_direction = _citizen_married(Spouse(us_person=_ans(False)))
    spouse_direction.household.filing_status = _ans("married_filing_jointly")
    assert _FACT_Q in _ids(intake_checklist(spouse_direction, tax_year=2023))


def test_p018_a_recorded_election_makes_both_spouses_residents_in_intake():
    profile = _with_election(_married_confirmed_nra(), True)
    profile.income_documents = [_doc("1099-INT")]
    cl = intake_checklist(profile, tax_year=2023)
    note = next(n for n in cl.notes if n.startswith("The §6013(g)/(h) election is recorded"))
    assert "RESIDENTS for the whole year" in note and "standard deduction" in note
    assert "treated for income tax purposes as residents for your entire tax year" in note
    assert "one spouse is a U.S. citizen or a resident alien" in note
    # The 1040-NR status restriction no longer applies, and the filing-status question
    # carries the first-year-joint rule instead of the nonresident rider.
    assert not any("Nonresident-alien filers (Form 1040-NR) cannot use" in n for n in cl.notes)
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    assert "You must file a joint income tax return for the year you make the choice" in (fs.disambiguation or "")
    # The 871(i)(2)(A) character question is moot under the election (the interest is taxed).
    assert _INTEREST_Q not in _ids(cl)
    assert _INTEREST_Q in _ids(intake_checklist(_confirmed_nra(_doc("1099-INT")), tax_year=2023))   # control
    # FICA is NOT reached by the election: the F-1's exemption note stays, and says why.
    fica = next(n for n in cl.notes if "FICA" in n and "Form 843" in n)
    assert "does not change this" in fica and "chapter 24 (relating to wage withholding)" in fica


def test_p018_intake_and_the_estimate_agree_on_a_recorded_election_with_an_unanswered_marital_status():
    # The estimator applies a recorded election when marital_status is unanswered and
    # married-filing-jointly is confirmed (MFJ is itself a statement of marriage).
    # Intake must read the same fact the same way: before this fix it still classified
    # the filer nonresident there and asked the 871(i)(2)(A) interest-character question,
    # which is moot under the election (the interest is taxed whatever its character).
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund

    profile = _with_election(_confirmed_nra(_doc("1099-INT")), True)
    profile.household = Household(filing_status=_ans("married_filing_jointly"))
    assert _INTEREST_Q not in _ids(intake_checklist(profile, tax_year=2023))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert est.residency_caveat is not None and est.residency_caveat.startswith("A §6013(g)/(h) election is recorded")
    # Without the confirmed joint status there is no marriage on file: neither applies it.
    bare = _with_election(_confirmed_nra(_doc("1099-INT")), True)
    assert _INTEREST_Q in _ids(intake_checklist(bare, tax_year=2023))


def test_p018_a_recorded_election_without_a_marriage_is_not_applied():
    profile = _with_election(_confirmed_nra(), True)
    profile.household = Household(marital_status=_ans("unmarried"))
    cl = intake_checklist(profile, tax_year=2023)
    assert any("NOT applied" in n and "section_6013_election" in n for n in cl.notes)
    assert not any(n.startswith("The §6013(g)/(h) election is recorded") for n in cl.notes)
    assert any("cannot use married-filing-jointly or head of household" in n for n in cl.notes)


def test_p018_the_spouse_election_question_stops_on_the_recorded_fact():
    for value in (True, False):
        profile = _citizen_married(Spouse(us_person=_ans(False)))
        profile.residency_facts = ResidencyFacts(section_6013_election=_ans(value))
        ids = _ids(intake_checklist(profile, tax_year=2023))
        assert "household.spouse.section_6013_election" not in ids, value
        assert _FACT_Q not in ids, value
    # The question itself is a decision, answered into the fact.
    q = next(q for q in intake_checklist(_citizen_married(Spouse(us_person=_ans(False))), tax_year=2023)
             .next_questions if q.id == "household.spouse.section_6013_election")
    assert "Are you making the §6013(g)/(h) election" in q.prompt and "or declining it" in q.prompt


def test_p018_the_interest_character_question_follows_the_payee():
    # The 871(i)(2)(A) exclusion belongs to the PAYEE (P-013 rule (e), P-018): a
    # spouse-owned 1099-INT is asked about on the SPOUSE's own classification.
    nra_spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="F-2", start=date(2022, 8, 1), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2021: _ans(0), 2022: _ans(140), 2023: _ans(330)}),
    )
    spouse_doc = IncomeDocument(kind="1099-INT", status="have", owner="spouse", provenance=US)
    profile = _citizen_married(nra_spouse)
    profile.income_documents = [spouse_doc]
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == _INTEREST_Q)
    assert q.prompt.startswith("Your spouse's residency result is NONRESIDENT alien")
    # The citizen's OWN 1099-INT is never asked about.
    own = _citizen_married(nra_spouse)
    own.income_documents = [_doc("1099-INT")]
    assert _INTEREST_Q not in _ids(intake_checklist(own, tax_year=2023))
    # Under the election the spouse is a resident too — nothing to ask.
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    assert _INTEREST_Q not in _ids(intake_checklist(profile, tax_year=2023))
    # A nonresident taxpayer's US-citizen spouse's 1099-INT is not asked about either.
    nra_taxpayer = _married_confirmed_nra(spouse=Spouse(us_person=_ans(True)))
    nra_taxpayer.income_documents = [spouse_doc]
    assert _INTEREST_Q not in _ids(intake_checklist(nra_taxpayer, tax_year=2023))


def test_p018_the_spouse_tin_question_keeps_the_w7_note_under_the_election():
    # Recording the election makes the spouse a resident for income tax, but the spouse
    # still needs a TIN on the joint return — Pub 519 FAQ: "your nonresident spouse needs
    # an SSN or ITIN". The W-7 last mile follows the NO-election residency.
    profile = _citizen_married(Spouse(us_person=_ans(False)))
    profile.residency_facts = ResidencyFacts(section_6013_election=_ans(True))
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == "household.spouse.tax_id")
    assert "Form W-7" in (q.disambiguation or "") and "ITIN Operation in Austin" in (q.disambiguation or "")


def test_p018_the_year_of_a_spouses_death_keeps_the_election_and_asks_for_it():
    # Pub 501: "If your spouse died during the year, you are considered married for the
    # whole year for filing status purposes"; Pub 519, Ending the Choice: death ends the
    # choice "beginning with the first tax year following the year the spouse died".
    profile = _confirmed_nra()
    profile.household = Household(marital_status=_ans("widowed"), spouse_death_year=_ans(2023),
                                  filing_status=_ans("married_filing_jointly"),
                                  maintained_home_for_dependent_child=_ans(False))
    assert _FACT_Q in _ids(intake_checklist(profile, tax_year=2023))
    profile.residency_facts.section_6013_election = _ans(True)
    cl = intake_checklist(profile, tax_year=2023)
    assert _FACT_Q not in _ids(cl)
    assert any(n.startswith("The §6013(g)/(h) election is recorded") for n in cl.notes)
    assert not any("NOT applied" in n for n in cl.notes)
    # Two years later the choice has ended, and the note says it was not applied.
    profile.household.spouse_death_year = _ans(2021)
    assert any("NOT applied" in n and "widowed during the year" in n
               for n in intake_checklist(profile, tax_year=2023).notes)


def test_p018_declining_is_worded_as_pub_501_has_it():
    # Declining leaves no joint return, but head of household stays open to the citizen
    # or resident spouse with another qualifying person (Pub 501, Considered Unmarried).
    profile = _married_confirmed_nra(filing_status=_ans("married_filing_jointly"))
    q = next(q for q in intake_checklist(profile, tax_year=2023).next_questions if q.id == _FACT_Q)
    d = q.disambiguation or ""
    assert "Declining the election means no joint return" in d
    assert "head of household with another qualifying person" in d
    battery = next(q for q in intake_checklist(_citizen_married(Spouse(us_person=_ans(False))), tax_year=2023)
                   .next_questions if q.id == "household.spouse.section_6013_election")
    assert "Declining the election means no joint return" in (battery.disambiguation or "")


def test_p018_a_dual_status_arrival_with_a_citizen_spouse_may_be_a_continuing_6013g():
    # Both U.S. residents or citizens at year end, the taxpayer a nonresident on Jan 1: a
    # NEW choice is IRC 6013(h) ("Neither you nor your spouse can make this choice for any
    # later tax year"), but a RECORDED true cannot tell it from an IRC 6013(g) election made
    # earlier that remains in effect (IRC 6013(g)(3); Pub 519's Note: "If you previously
    # made that choice and it is still in effect, you do not need to make the choice
    # explained here") — so intake gives both readings, never a bare "(h) only".
    profile = Profile(
        identity=Identity(us_person=_ans(False)),
        immigration=Immigration(visa_timeline=[VisaPeriod(status="H-1B", start=date(2025, 6, 2), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={2023: _ans(0), 2024: _ans(0), 2025: _ans(213)},
                                       section_6013_election=_ans(True)),
        household=Household(marital_status=_ans("married"), spouse=Spouse(us_person=_ans(True))),
    )
    cl = intake_checklist(profile, tax_year=2025)
    note = next(n for n in cl.notes if n.startswith("The §6013(g)/(h) election is recorded"))
    assert "IRC 6013(h)" in note and "you both qualify to make the choice" in note
    assert "If you previously made that choice and it is still in effect" in note
    fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
    d = fs.disambiguation or ""
    assert "must file a joint return for the year of the choice" in d
    assert "unless an IRC 6013(g) election made in an earlier year remains in effect" in d


# P-018, the second verify round (2026-09-26): after a recorded DECLINE the status
# question offers no joint return; an election neither spouse can use is not offered
# (IRC 6013(g)(3)); a confirmed MFS status is a marriage; a true answer covers a
# continuing election. Hypothetical demo fixtures only.

_FAQ = "Generally, you cannot file as married filing jointly if either spouse was a nonresident alien"


def _nra_spouse_facts() -> Spouse:
    return Spouse(us_person=_ans(False), immigration=Immigration(
        visa_timeline=[VisaPeriod(status="F-2", start=date(2020, 8, 24), provenance=US)]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in
                                                   {2020: 130, 2021: 330, 2022: 330, 2023: 330}.items()}))


def test_p018_after_a_recorded_decline_the_status_question_offers_no_joint_return():
    citizen = _citizen_married(_nra_spouse_facts())
    citizen.residency_facts = ResidencyFacts(section_6013_election=_ans(False))
    fs = next(q for q in intake_checklist(citizen, tax_year=2023).next_questions if q.id == "household.filing_status")
    assert fs.prompt.startswith("Without the §6013(g)/(h) election there is no joint return (it is recorded as declined)")
    assert "head of household" in fs.prompt and "jointly with your spouse" not in fs.prompt
    d = fs.disambiguation or ""
    assert "Declining the election means no joint return" in d and _FAQ in d
    # A nonresident taxpayer (Form 1040-NR) is not offered head of household.
    nra = _with_election(_married_confirmed_nra(), False)
    fs = next(q for q in intake_checklist(nra, tax_year=2023).next_questions if q.id == "household.filing_status")
    assert "no joint return" in fs.prompt and "head of household" not in fs.prompt


def test_p018_intake_does_not_offer_an_election_neither_spouse_can_use():
    both = _married_confirmed_nra(spouse=_nra_spouse_facts())
    cl = intake_checklist(both, tax_year=2023)
    assert "household.spouse.section_6013_election" not in _ids(cl)
    note = next(n for n in cl.notes if n.startswith("The §6013(g)/(h) election is not asked about."))
    assert "shall not apply for any taxable year if neither spouse is a citizen or resident" in note
    both.household.filing_status = _ans("married_filing_jointly")
    assert _FACT_Q not in _ids(intake_checklist(both, tax_year=2023))
    # Recorded anyway: NOT applied, and the interest-character question is live again.
    recorded = _with_election(_married_confirmed_nra(spouse=_nra_spouse_facts()), True)
    recorded.income_documents = [_doc("1099-INT")]
    cl = intake_checklist(recorded, tax_year=2023)
    assert any(n.startswith("residency_facts.section_6013_election is recorded, but it is NOT applied") and
               "Suspending the Choice" in n for n in cl.notes)
    assert not any(n.startswith("The §6013(g)/(h) election is recorded") for n in cl.notes)
    assert _INTEREST_Q in _ids(cl)


def test_p018_intake_counts_a_confirmed_mfs_status_as_the_marriage():
    # Pub 501: "You can choose married filing separately as your filing status if you are
    # married." Intake and the estimate read the same fact the same way.
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund

    profile = _with_election(_confirmed_nra(_doc("1099-INT")), True)
    profile.household = Household(filing_status=_ans("married_filing_separately"), spouse=Spouse(us_person=_ans(True)))
    assert _INTEREST_Q not in _ids(intake_checklist(profile, tax_year=2023))
    est = estimate_refund(profile, 2023, IncomeSnapshot(wages=60_000, federal_withholding=6_000))
    assert est.residency_caveat.startswith("A §6013(g)/(h) election is recorded")
    # A head-of-household status exists only without the election (Pub 501, Considered Unmarried).
    hoh = _with_election(_married_confirmed_nra(filing_status=_ans("head_of_household"),
                                                spouse=Spouse(us_person=_ans(True))), True)
    note = next(n for n in intake_checklist(hoh, tax_year=2023).notes if "NOT applied" in n)
    assert "exists only WITHOUT the election" in note and "not married for the year" not in note


def test_p018_a_true_answer_covers_a_continuing_election_and_names_the_taxpayer_path():
    q = next(q for q in intake_checklist(_married_confirmed_nra(filing_status=_ans("married_filing_jointly")),
                                         tax_year=2023).next_questions if q.id == _FACT_Q)
    assert "the taxpayer's, never the spouse's" in q.prompt
    d = q.disambiguation or ""
    assert "FIRST joint return" in d and "OR if an election made in an earlier year remains in effect" in d
    assert "no new statement" in d
    battery = next(q for q in intake_checklist(_citizen_married(Spouse(us_person=_ans(False))), tax_year=2023)
                   .next_questions if q.id == "household.spouse.section_6013_election")
    assert battery.answers_into == "residency_facts.section_6013_election"
    assert "not household.spouse's" in battery.prompt


# P-018, the third verify round (2026-09-26). Hypothetical demo fixtures only.

def test_p018_two_nonresidents_get_the_suspended_text_never_the_decline_text():
    # Neither spouse a citizen or resident: nothing to decline and no citizen side, and a
    # recorded decline is never answered with "To reopen a joint return ... as true".
    for value in (None, False, True):
        profile = _married_confirmed_nra(spouse=_nra_spouse_facts())
        if value is not None:
            profile = _with_election(profile, value)
        cl = intake_checklist(profile, tax_year=2023)
        fs = next(q for q in cl.next_questions if q.id == "household.filing_status")
        d = fs.disambiguation or ""
        assert "Declining the election means" not in d and "U.S. citizen or resident spouse" not in d
        assert "To reopen a joint return" not in d
        assert "if either meets the filing requirements for nonresident aliens" in d


def test_p018_intake_names_a_confirmed_joint_status_that_a_decline_rules_out():
    citizen = _citizen_married(_nra_spouse_facts())
    citizen.residency_facts = ResidencyFacts(section_6013_election=_ans(False))
    citizen.household.filing_status = _ans("married_filing_jointly")
    cl = intake_checklist(citizen, tax_year=2023)
    note = next(n for n in cl.notes if n.startswith("CONTRADICTION"))
    assert _FAQ in note and "recorded as FALSE (declined)" in note


def test_p018_after_a_decline_the_spouse_tin_question_leads_with_the_separate_return():
    citizen = _citizen_married(_nra_spouse_facts())
    citizen.residency_facts = ResidencyFacts(section_6013_election=_ans(False))
    q = next(q for q in intake_checklist(citizen, tax_year=2023).next_questions if q.id == "household.spouse.tax_id")
    assert (q.disambiguation or "").startswith(
        "On a married-filing-separately return, if your spouse doesn't have and isn't required to have an SSN or "
        "ITIN, enter 'NRA' in the entry space below the filing status checkboxes (Pub 501")
    assert "Form W-7" not in (q.disambiguation or "")


def test_p018_the_year_of_death_with_a_confirmed_status_gets_the_6013g3_reason():
    # Widowed in the tax year, a confirmed MFS, two certain nonresidents, a recorded election:
    # the reason is IRC 6013(g)(3), never "confirm married_filing_jointly to price the election".
    profile = _with_election(_married_confirmed_nra(spouse=_nra_spouse_facts()), True)
    profile.household.marital_status = _ans("widowed")
    profile.household.spouse_death_year = _ans(2023)
    profile.household.filing_status = _ans("married_filing_separately")
    note = next(n for n in intake_checklist(profile, tax_year=2023).notes if "NOT applied" in n)
    assert "shall not apply for any taxable year" in note and "confirm married_filing_jointly" not in note


# ── P-018 / JF5b part 1: the prior-year return is the prior-year residency fact ─────
# Treas. Reg. 301.7701(b)-4(e)(1): a resident "during any part of the preceding calendar
# year" who "is a United States resident for any part of the current year will be
# considered to be taxable as a resident at the beginning of the current year".
# Hypothetical timelines only.

_TRUNCATED_F1 = [("F-1", date(2021, 8, 20), date(2025, 9, 30)), ("H-1B", date(2025, 10, 1), None)]
_SWITCH_APRIL = [("F-1", date(2021, 8, 20), date(2025, 3, 31)), ("H-1B", date(2025, 4, 1), None)]
_DAYS = {2025: 365, 2024: 366, 2023: 365, 2022: 365, 2021: 130}


def _visa(periods, days=_DAYS, *, prior=None, us_person=False) -> Profile:
    return Profile(
        identity=Identity(us_person=_ans(us_person)) if us_person is not None else None,
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in periods
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in days.items()}),
        prior_filings=PriorFilings(return_forms={y: _ans(f) for y, f in prior.items()}) if prior is not None else None,
    )


def test_p018_intake_asks_a_visa_filer_which_return_was_filed_for_the_prior_year():
    cl = intake_checklist(_visa(_SWITCH_APRIL), tax_year=2025)
    q = next(q for q in cl.next_questions if q.id == "prior_filings.return_form")
    assert q.section == "prior_filings" and q.prompt == "Which federal return did you file for 2024?"
    assert q.answers_into == "prior_filings.return_forms.2024"
    for value in ("'1040'", "'1040-NR'", "'dual_status'", "'1040_with_6013_election'", "'not_filed'"):
        assert value in q.disambiguation
    assert "301.7701(b)-4(e)(1)" in q.why
    # Unanswered us_person with a visa timeline is asked too; a U.S. person, no timeline, or no year is not.
    assert "prior_filings.return_form" in _ids(intake_checklist(_visa(_SWITCH_APRIL, us_person=None), tax_year=2025))
    assert "prior_filings.return_form" not in _ids(intake_checklist(_visa(_SWITCH_APRIL, us_person=True), tax_year=2025))
    assert "prior_filings.return_form" not in _ids(intake_checklist(Profile(), tax_year=2025))
    assert "prior_filings.return_form" not in _ids(intake_checklist(_visa(_SWITCH_APRIL)))
    # It stops once answered — any of the five values, for THAT year only.
    for form in ("1040", "1040-NR", "dual_status", "1040_with_6013_election", "not_filed"):
        answered = _visa(_SWITCH_APRIL, prior={2024: form})
        assert "prior_filings.return_form" not in _ids(intake_checklist(answered, tax_year=2025)), form
    other_year = _visa(_SWITCH_APRIL, prior={2023: "1040"})
    assert "prior_filings.return_form" in _ids(intake_checklist(other_year, tax_year=2025))


def test_p018_intake_reads_a_prior_1040_as_residency_from_january_1():
    from taxfill_core.intake import _residency_classification

    assert _residency_classification(_visa(_SWITCH_APRIL), 2025) == "dual_status_candidate"
    carried = _visa(_SWITCH_APRIL, prior={2024: "1040"})
    assert _residency_classification(carried, 2025) == "resident"
    # _fica_exemption_note is suppressed for the resident (hedged without the fact).
    assert any("FICA" in n for n in intake_checklist(_visa(_SWITCH_APRIL), tax_year=2025).notes)
    # 2024 is an exempt F-1 year on this timeline, so the note survives only behind the CHECK's reading (b).
    fica = [n for n in intake_checklist(carried, tax_year=2025).notes if "FICA" in n]
    assert fica and all(n.startswith("If the CHECK THE PRIOR-YEAR RETURN note's reading (b) holds") for n in fica)


def test_p018_intake_never_asserts_a_nonresident_answer_the_prior_year_contradicts():
    from taxfill_core.intake import _certain_nonresident, _residency_classification

    assert _residency_classification(_visa(_TRUNCATED_F1), 2025) == "nonresident"
    contradicted = _visa(_TRUNCATED_F1, prior={2024: "1040"})
    assert _residency_classification(contradicted, 2025) is None           # unknown, never asserted
    note = next(n for n in intake_checklist(contradicted, tax_year=2025).notes if n.startswith("CONTRADICTION"))
    assert "NOT definitive" in note and "prior_filings.return_forms" in note
    imm, rf = contradicted.immigration, contradicted.residency_facts
    assert _certain_nonresident(imm, rf, 2025) is True
    assert _certain_nonresident(imm, rf, 2025, prior_year_resident=True) is False
    # The FICA note stays conditional: the answer is not settled.
    fica = next(n for n in intake_checklist(contradicted, tax_year=2025).notes if "FICA" in n)
    assert fica.startswith("If your residency result is nonresident")


def test_p018_intake_notes_a_prior_year_election_return_as_a_judgment():
    profile = _visa(_TRUNCATED_F1, prior={2024: "1040_with_6013_election"})
    note = next(n for n in intake_checklist(profile, tax_year=2025).notes if n.startswith("Your 2024 return"))
    assert "NOT read here as residency in 2024 — a judgment" in note


def test_p018_the_taxpayers_prior_year_return_never_reaches_the_spouse():
    from taxfill_core.intake import _spouse_classification

    spouse = Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in _SWITCH_APRIL
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in _DAYS.items()}),
    )
    profile = _visa(_SWITCH_APRIL, prior={2024: "1040"})
    profile.household = Household(marital_status=_ans("married"), spouse=spouse)
    assert _spouse_classification(profile, 2025, honor_election=False) == "dual_status_candidate"


def test_p018_answering_the_prior_year_return_still_leaves_the_filing_history_question():
    from taxfill_core.schemas.profile import PriorFilings  # noqa: PLC0415
    profile = _confirmed_nra()
    profile.prior_filings = PriorFilings(return_forms={2022: _ans("1040-NR")})
    ids = _ids(intake_checklist(profile, tax_year=2023))
    assert "prior_filings.history" in ids and "prior_filings.return_form" not in ids


# ── P-013 rule (f) / P-018 (JF5b part 2): the dual-status year's deposit interest ─────
# Treas. Reg. 1.871-13(a)(1): the year is figured "under two different sets of rules, one
# relating to resident aliens for the period of residence and the other relating to
# nonresident aliens for the period of nonresidence" — so the character AND the part received
# before the residency starting date are asked of a dual-status owner. Hypothetical data only.

_PERIOD_Q = "income_documents.interest_period"


def _dual_with(*docs: IncomeDocument, us_person=False, prior=None) -> Profile:
    profile = _visa(_SWITCH_APRIL, us_person=us_person, prior=prior)
    profile.income_documents = list(docs)
    return profile


def _dual_spouse() -> Spouse:
    return Spouse(
        us_person=_ans(False),
        immigration=Immigration(visa_timeline=[
            VisaPeriod(status=s, start=start, end=end, provenance=US) for s, start, end in _SWITCH_APRIL
        ]),
        residency_facts=ResidencyFacts(days_in_us={y: _ans(d) for y, d in _DAYS.items()}),
    )


def test_p013_dual_status_owner_is_asked_the_interest_character():
    for us_person in (False, None):
        cl = intake_checklist(_dual_with(_doc("1099-INT"), us_person=us_person), tax_year=2025)
        q = next(q for q in cl.next_questions if q.id == _INTEREST_Q)
        assert q.prompt.startswith("Your residency result is a DUAL-STATUS year"), us_person
        assert "1.871-13(a)(1)" in q.why and "only the part received before the residency starting date" in q.why
        assert "bank_deposit_interest_nonresident_period" in q.disambiguation
    # A full-year nonresident's question is unchanged (no dual-status sentence).
    nra = next(q for q in intake_checklist(_confirmed_nra(_doc("1099-INT")), tax_year=2023).next_questions
               if q.id == _INTEREST_Q)
    assert "DUAL-STATUS" not in nra.why and "nonresident_period" not in nra.disambiguation
    # A prior-year resident is a resident from January 1: nothing to ask.
    resident = _dual_with(_doc("1099-INT"), prior={2024: "1040"})
    assert _INTEREST_Q not in _ids(intake_checklist(resident, tax_year=2025))


def test_p013_dual_status_deposit_1099_int_is_asked_the_period():
    cl = intake_checklist(_dual_with(_doc("1099-INT (bank deposit)")), tax_year=2025)
    q = next(q for q in cl.next_questions if q.id == _PERIOD_Q)
    assert q.section == "income_documents" and q.answers_into == "income_documents"
    assert q.prompt.startswith("Your residency result is a DUAL-STATUS year for 2025")
    assert "BEFORE the residency starting date" in q.prompt and "IRC 7701(b)(3)(D)" in q.prompt
    assert "1.871-13(a)(1)" in q.why and "871(i)(2)(A)" in q.why and "Without the amount the estimate taxes all" in q.why
    assert "does not apply to alien individuals treated as residents" in q.why          # the election ends it
    assert "`bank_deposit_interest_nonresident_period`" in q.disambiguation
    assert "never prorate" in q.disambiguation and "0 is a valid answer" in q.disambiguation
    assert _INTEREST_Q not in _ids(cl)                                                  # the character is on file
    # Recorded — either amount — stops it; the words are the token, never digits (P-012).
    for kind in ("1099-INT (bank deposit; $120 before the residency starting date)",
                 "1099-INT (bank deposit; none before the residency start date)"):
        assert _PERIOD_Q not in _ids(intake_checklist(_dual_with(_doc(kind)), tax_year=2025)), kind
    assert _PERIOD_Q in _ids(intake_checklist(_dual_with(_doc("1099-INT (bank deposit) acct 20250401")), tax_year=2025))
    # Not a deposit, uncharacterized, or not applicable: no period to ask.
    for kind, status in (("1099-INT (not a deposit — brokerage/bond interest)", "have"), ("1099-INT", "have"),
                         ("1099-INT (bank deposit)", "not_applicable")):
        assert _PERIOD_Q not in _ids(intake_checklist(_dual_with(_doc(kind, status)), tax_year=2025)), kind


def test_p013_the_period_question_is_only_for_a_dual_status_owner():
    # A full-year nonresident's whole deposit interest is excluded, and a resident's is taxed.
    assert _PERIOD_Q not in _ids(intake_checklist(_confirmed_nra(_doc("1099-INT (bank deposit)")), tax_year=2023))
    resident = _dual_with(_doc("1099-INT (bank deposit)"), prior={2024: "1040"})
    assert _PERIOD_Q not in _ids(intake_checklist(resident, tax_year=2025))
    # Under the §6013(g)/(h) election 1.871-13 does not apply — nothing to ask.
    elected = _dual_with(_doc("1099-INT (bank deposit)"))
    elected.household = Household(marital_status=_ans("married"), spouse=Spouse(us_person=_ans(True)))
    assert _PERIOD_Q in _ids(intake_checklist(elected, tax_year=2025))
    elected.residency_facts.section_6013_election = _ans(True)
    assert _PERIOD_Q not in _ids(intake_checklist(elected, tax_year=2025))


def test_p018_dual_status_spouse_deposit_is_asked_on_the_spouses_own_year():
    profile = _citizen_married(_dual_spouse())
    profile.income_documents = [IncomeDocument(kind="1099-INT (bank deposit)", status="have", owner="spouse",
                                                provenance=US)]
    q = next(q for q in intake_checklist(profile, tax_year=2025).next_questions if q.id == _PERIOD_Q)
    assert q.prompt.startswith("Your spouse's residency result is a DUAL-STATUS year")
    assert "the spouse's goes in the spouse snapshot" in q.disambiguation
    # The citizen's own deposit 1099-INT is never asked about.
    own = _citizen_married(_dual_spouse())
    own.income_documents = [_doc("1099-INT (bank deposit)")]
    assert _PERIOD_Q not in _ids(intake_checklist(own, tax_year=2025))
    # An uncharacterized spouse 1099-INT gets the character question with the dual-status wording.
    profile.income_documents = [IncomeDocument(kind="1099-INT", status="have", owner="spouse", provenance=US)]
    q = next(q for q in intake_checklist(profile, tax_year=2025).next_questions if q.id == _INTEREST_Q)
    assert q.prompt.startswith("Your spouse's residency result is a DUAL-STATUS year")


def test_p018_dual_status_prior_year_question_says_what_the_answer_decides():
    q = next(q for q in intake_checklist(_visa(_SWITCH_APRIL), tax_year=2025).next_questions
             if q.id == "prior_filings.return_form")
    assert "Your 2025 result is a DUAL-STATUS year, which takes no standard deduction" in q.why
    assert "a 2024 Form 1040-NR rules that route out" in q.why
    # A full-year nonresident's question is unchanged.
    nra = next(q for q in intake_checklist(_confirmed_nra(), tax_year=2023).next_questions
               if q.id == "prior_filings.return_form")
    assert "DUAL-STATUS" not in nra.why


# ── P-018 / JF5b part 3b: a prior-year election return — the election CONTINUES ─────
# IRC 6013(g)(3): "An election under this subsection shall apply to the taxable year for which
# made and to all subsequent taxable years until terminated under paragraph (4) or (5)"; IRC
# 6013(h)(2): "such 2 individuals shall be ineligible to make an election under this subsection
# for any subsequent taxable year". Hypothetical timelines only.

def _married_visa(prior=None, spouse=None, **household_kwargs) -> Profile:
    profile = _visa(_SWITCH_APRIL, prior=prior)
    profile.household = Household(marital_status=_ans("married"), spouse=spouse or Spouse(us_person=_ans(True)),
                                  **household_kwargs)
    return profile


def test_p018_a_prior_year_election_return_asks_whether_the_election_continues():
    profile = _married_visa(prior={2024: "1040_with_6013_election"})
    cl = intake_checklist(profile, tax_year=2025)
    q = next(q for q in cl.next_questions if q.id == _FACT_Q)
    assert q.prompt.startswith("Your 2024 return is recorded as a joint Form 1040 under the §6013(g)/(h) election. "
                               "Is that election still in effect for 2025?")
    assert q.answers_into == "residency_facts.section_6013_election"
    assert "it never applies the election from the prior-year return alone" in q.why
    assert "shall apply to the taxable year for which made and to all subsequent taxable years until terminated" in (
        q.disambiguation)
    assert "Once made, the choice to be treated as a resident applies to all later years" in q.disambiguation
    # Asked whatever the status (a confirmed MFS too), once — never the spouse battery's copy as well.
    assert [q.id for q in cl.next_questions].count(_FACT_Q) == 1
    mfs = _married_visa(prior={2024: "1040_with_6013_election"}, filing_status=_ans("married_filing_separately"))
    assert _FACT_Q in _ids(intake_checklist(mfs, tax_year=2025))
    nra_spouse = _married_visa(prior={2024: "1040_with_6013_election"}, spouse=_nra_spouse_facts())
    ids = [q.id for q in intake_checklist(nra_spouse, tax_year=2025).next_questions]
    assert ids.count(_FACT_Q) == 1 and "household.spouse.section_6013_election" not in ids
    note = next(n for n in cl.notes if "no election is recorded for 2025" in n)
    assert "IRC 6013(g)(3)" in note and "This choice remains in effect in subsequent years until terminated." in note
    assert "true if the election is still in effect" in note and "false if it was ended" in note
    # Either answer stops the question and the note; without the prior-year return nothing is asked.
    for value in (True, False):
        answered = _married_visa(prior={2024: "1040_with_6013_election"})
        answered.residency_facts.section_6013_election = _ans(value)
        cl2 = intake_checklist(answered, tax_year=2025)
        assert _FACT_Q not in _ids(cl2) and not any("no election is recorded for 2025" in n for n in cl2.notes)
    assert _FACT_Q not in _ids(intake_checklist(_married_visa(prior={2024: "1040"}), tax_year=2025))


def test_p018_a_prior_year_election_return_makes_the_kind_a_continuing_6013g():
    from taxfill_core.intake import _section_6013_kind

    # A dual-status arrival year with a U.S.-citizen spouse: a recorded election is 'either' (an
    # earlier 6013(g) election may continue) until the prior-year return shows one — then 'g'.
    assert _section_6013_kind(_married_visa(), 2025) == "either"
    assert _section_6013_kind(_married_visa(prior={2024: "1040_with_6013_election"}), 2025) == "g"
    assert _section_6013_kind(_married_visa(prior={2023: "1040_with_6013_election"}), 2025) == "either"   # year-1 only
    elected = _married_visa(prior={2024: "1040_with_6013_election"})
    elected.residency_facts.section_6013_election = _ans(True)
    note = next(n for n in intake_checklist(elected, tax_year=2025).notes if n.startswith("The §6013(g)/(h) election "
                                                                                              "is recorded"))
    assert "IRC 6013(g) — Pub 519 ch. 1, Nonresident Spouse Treated as a Resident" in note
    assert "IRC 6013(h), the year a nonresident alien becomes a resident" not in note


def test_p018_intake_reads_a_confirmed_joint_status_as_the_continuing_election_like_the_estimate():
    from taxfill_core.estimate import IncomeSnapshot, estimate_refund  # noqa: PLC0415
    from taxfill_core.schemas.profile import PriorFilings  # noqa: PLC0415
    profile = _married_confirmed_nra(filing_status=_ans("married_filing_jointly"), spouse=Spouse(us_person=_ans(True)))
    profile.prior_filings = PriorFilings(return_forms={2022: _ans("1040_with_6013_election")})
    notes = " ".join(intake_checklist(profile, tax_year=2023).notes)
    est = " ".join(estimate_refund(profile, 2023, IncomeSnapshot(wages=40_000, federal_withholding=5_000)).assumptions)
    for text in (notes, est):
        assert "read as that election continuing" in text and "NOT applied here" not in text
