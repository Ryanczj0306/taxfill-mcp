"""Intake profile schema tests (dev plan section 4). All data is synthetic."""

from datetime import date

import pytest
from pydantic import ValidationError

from taxfill_core.schemas.profile import (
    Answer,
    Banking,
    DateRange,
    Dependent,
    Household,
    Identity,
    Immigration,
    IncomeDocument,
    PriorFilings,
    Profile,
    Provenance,
    ResidencyFacts,
    ResidencePeriod,
    Spouse,
    StateFootprintYear,
    VisaPeriod,
    WorkPeriod,
)


def synthetic_profile() -> Profile:
    """A profile exercising every section and all three provenance kinds."""
    return Profile(
        identity=Identity(
            name=Answer[str](value="Test Taxpayer", provenance=Provenance.user_stated()),
            tax_id=Answer[str](value="000000000", provenance=Provenance.user_stated()),
            dob=Answer[date](value=date(1999, 1, 1), provenance=Provenance.document(file="documents/passport.jpg", page=1)),
            mailing_address=Answer[str](
                value="123 Example St Apt 1, Springfield, ZZ 00000",
                provenance=Provenance.user_stated(),
            ),
        ),
        immigration=Immigration(
            visa_timeline=[
                VisaPeriod(
                    status="F-1",
                    start=date(2019, 8, 15),
                    end=date(2023, 6, 30),
                    provenance=Provenance.document(file="documents/i94_history.pdf", page=1),
                ),
                VisaPeriod(
                    status="H-1B",
                    start=date(2023, 7, 1),
                    end=None,  # ongoing
                    provenance=Provenance.user_stated(),
                ),
            ],
            first_us_entry=Answer[date](
                value=date(2019, 8, 15),
                provenance=Provenance.document(file="documents/i94_history.pdf", page=1),
            ),
        ),
        residency_facts=ResidencyFacts(
            days_in_us={
                2022: Answer[int](value=365, provenance=Provenance.computed()),
                2023: Answer[int](value=350, provenance=Provenance.computed()),
            },
            home_country_address=Answer[str](
                value="1 Sample Road, Exampleville, Testland",
                provenance=Provenance.user_stated(),
            ),
        ),
        household=Household(
            marital_status=Answer[str](value="unmarried", provenance=Provenance.user_stated()),
            # Unmarried taxpayer with a qualifying person + dependent child files as head of household.
            hoh_qualifying_person=Answer[bool](value=True, provenance=Provenance.user_stated()),
            filing_status=Answer[str](value="head_of_household", provenance=Provenance.user_stated()),
            dependents=[
                Dependent(name="Test Child", relationship="child", dob=date(2020, 5, 5), provenance=Provenance.user_stated()),
            ],
        ),
        state_footprint={
            2023: StateFootprintYear(
                lived=[
                    ResidencePeriod(state="CA", start=date(2023, 1, 1), end=date(2023, 6, 30), provenance=Provenance.user_stated()),
                    ResidencePeriod(state="WA", start=date(2023, 7, 1), end=date(2023, 12, 31), provenance=Provenance.user_stated()),
                ],
                worked=[
                    WorkPeriod(state="CA", start=date(2023, 1, 1), end=date(2023, 12, 31), remote=True, provenance=Provenance.user_stated()),
                ],
            ),
        },
        income_documents=[
            IncomeDocument(kind="W-2", status="have", file="documents/w2_2023.pdf", provenance=Provenance.document(file="documents/w2_2023.pdf")),
            IncomeDocument(kind="1099-NEC", status="missing", provenance=Provenance.user_stated()),
            IncomeDocument(kind="1098-T", status="not_applicable", provenance=Provenance.user_stated()),
        ],
        banking=Banking(
            routing_number=Answer[str](value="123123123", provenance=Provenance.user_stated()),  # synthetic, checksum-valid
            account_number=Answer[str](value="000123456780", provenance=Provenance.user_stated()),
            account_type="checking",
        ),
        prior_filings=PriorFilings(
            filed_years=Answer[list[int]](value=[2021, 2022], provenance=Provenance.user_stated()),
            late_filing_context=Answer[str](value="2020 never filed; back-filing planned", provenance=Provenance.user_stated()),
        ),
    )


def test_empty_profile_is_valid():
    # Intake fills the profile incrementally; an empty profile is a legal start state.
    profile = Profile()
    assert profile.identity is None
    assert profile.state_footprint == {}
    assert profile.income_documents == []


def test_profile_json_roundtrip_preserves_everything():
    original = synthetic_profile()
    restored = Profile.model_validate_json(original.model_dump_json())
    assert restored == original

    # Spot-check provenance survived the roundtrip on each kind.
    assert restored.identity.name.provenance.kind == "user_stated"
    assert restored.identity.dob.provenance.kind == "document"
    assert restored.identity.dob.provenance.file == "documents/passport.jpg"
    assert restored.identity.dob.provenance.page == 1
    assert restored.residency_facts.days_in_us[2023].provenance.kind == "computed"

    # Int dict keys (years) survive JSON serialization.
    assert set(restored.residency_facts.days_in_us) == {2022, 2023}
    assert set(restored.state_footprint) == {2023}

    # Visa timeline stays an ordered list of date-range periods.
    timeline = restored.immigration.visa_timeline
    assert [p.status for p in timeline] == ["F-1", "H-1B"]
    assert timeline[0].end == date(2023, 6, 30)
    assert timeline[1].end is None  # ongoing period


def test_document_provenance_requires_file():
    with pytest.raises(ValidationError, match="file"):
        Provenance(kind="document")


def test_non_document_provenance_must_not_carry_file_or_page():
    with pytest.raises(ValidationError, match="document"):
        Provenance(kind="user_stated", file="documents/w2.pdf")
    with pytest.raises(ValidationError, match="document"):
        Provenance(kind="computed", page=2)


def test_unknown_provenance_kind_rejected():
    with pytest.raises(ValidationError):
        Provenance(kind="guessed")  # never invent a value


def test_invalid_document_status_rejected():
    with pytest.raises(ValidationError):
        IncomeDocument(kind="W-2", status="lost", provenance=Provenance.user_stated())


def test_date_range_end_before_start_rejected():
    with pytest.raises(ValidationError, match="before start"):
        DateRange(start=date(2023, 6, 1), end=date(2023, 1, 1))


def test_banking_rejects_bad_routing_number():
    with pytest.raises(ValidationError, match="ABA"):
        Banking(
            routing_number=Answer[str](value="123456789", provenance=Provenance.user_stated()),
            account_number=Answer[str](value="000123456780", provenance=Provenance.user_stated()),
        )


def test_banking_error_message_does_not_echo_the_routing_number():
    # PII-safe errors: the message we control must not repeat the bad value.
    # (Pydantic's own diagnostics may show the raw input; redact.py handles
    # log scrubbing in M1 — here we guarantee our message stays clean.)
    try:
        Banking(
            routing_number=Answer[str](value="999999999", provenance=Provenance.user_stated()),
            account_number=Answer[str](value="000123456780", provenance=Provenance.user_stated()),
        )
    except ValidationError as exc:
        messages = [err["msg"] for err in exc.errors()]
        assert messages, "expected at least one validation error"
        assert all("999999999" not in msg for msg in messages)
    else:
        pytest.fail("expected ValidationError for an invalid routing number")


def test_unknown_profile_section_rejected():
    with pytest.raises(ValidationError):
        Profile.model_validate({"crypto_wallet": {}})


def test_household_filing_status_roundtrips():
    restored = Profile.model_validate_json(synthetic_profile().model_dump_json())
    assert restored.household.filing_status.value == "head_of_household"
    assert restored.household.filing_status.provenance.kind == "user_stated"


def test_invalid_filing_status_rejected():
    # 'married' is NOT a filing status — the couple elects MFJ or MFS.
    with pytest.raises(ValidationError):
        Household(filing_status=Answer[str](value="married", provenance=Provenance.user_stated()))


def test_marital_status_rejects_out_of_domain_string():
    # marital_status is a closed, machine-checkable fact — 'single' (a filing status)
    # and other free text are rejected (mirror test_invalid_filing_status_rejected).
    for bad in ("single", "head_of_household", "yes", ""):
        with pytest.raises(ValidationError):
            Household(marital_status=Answer[str](value=bad, provenance=Provenance.user_stated()))
    # The three legal facts are accepted.
    for good in ("married", "unmarried", "widowed"):
        Household(marital_status=Answer[str](value=good, provenance=Provenance.user_stated()))


def test_household_filing_status_facts_roundtrip():
    # The new filing-status FACT fields (hoh_qualifying_person, QSS facts) survive JSON.
    hh = Household(
        marital_status=Answer[str](value="widowed", provenance=Provenance.user_stated()),
        hoh_qualifying_person=Answer[bool](value=True, provenance=Provenance.user_stated()),
        spouse_death_year=Answer[int](value=2024, provenance=Provenance.user_stated()),
        maintained_home_for_dependent_child=Answer[bool](value=True, provenance=Provenance.user_stated()),
    )
    profile = Profile(household=hh)
    restored = Profile.model_validate_json(profile.model_dump_json())
    assert restored.household.hoh_qualifying_person.value is True
    assert restored.household.spouse_death_year.value == 2024
    assert restored.household.maintained_home_for_dependent_child.value is True
    assert restored.household.spouse_death_year.provenance.kind == "user_stated"


def test_spouse_us_person_and_residency_facts_roundtrip():
    # The spouse carries their own us_person flag and residency facts (an NRA spouse
    # needs the SPT/visa path; both must survive a JSON roundtrip).
    profile = Profile(
        household=Household(
            marital_status=Answer[str](value="married", provenance=Provenance.user_stated()),
            filing_status=Answer[str](value="married_filing_jointly", provenance=Provenance.user_stated()),
            spouse=Spouse(
                name=Answer[str](value="Spouse Taxpayer", provenance=Provenance.user_stated()),
                us_person=Answer[bool](value=False, provenance=Provenance.user_stated()),
                residency_facts=ResidencyFacts(
                    days_in_us={2023: Answer[int](value=120, provenance=Provenance.computed())},
                ),
            ),
        ),
    )
    restored = Profile.model_validate_json(profile.model_dump_json())
    assert restored.household.spouse.us_person.value is False
    assert restored.household.spouse.residency_facts.days_in_us[2023].value == 120
    assert restored.household.spouse.residency_facts.days_in_us[2023].provenance.kind == "computed"


def test_income_document_owner_defaults_to_taxpayer_and_accepts_spouse():
    doc = IncomeDocument(kind="W-2", status="have", provenance=Provenance.user_stated())
    assert doc.owner == "taxpayer"  # default: the taxpayer's own income
    spouse_doc = IncomeDocument(kind="W-2", status="have", owner="spouse", provenance=Provenance.user_stated())
    assert spouse_doc.owner == "spouse"
    with pytest.raises(ValidationError):
        IncomeDocument(kind="W-2", status="have", owner="child", provenance=Provenance.user_stated())


def test_joint_return_carries_spouse_as_second_taxpayer():
    # MFJ: two taxpayers, the spouse with their own identity + NRA visa timeline,
    # and a spouse-owned income document.
    profile = Profile(
        household=Household(
            marital_status=Answer[str](value="married", provenance=Provenance.user_stated()),
            filing_status=Answer[str](value="married_filing_jointly", provenance=Provenance.user_stated()),
            spouse=Spouse(
                name=Answer[str](value="Spouse Taxpayer", provenance=Provenance.user_stated()),
                tax_id=Answer[str](value="000000001", provenance=Provenance.user_stated()),
                immigration=Immigration(
                    visa_timeline=[
                        VisaPeriod(status="F-2", start=date(2021, 1, 1), end=None, provenance=Provenance.user_stated()),
                    ],
                ),
            ),
        ),
        income_documents=[
            IncomeDocument(kind="W-2", status="have", owner="taxpayer", provenance=Provenance.user_stated()),
            IncomeDocument(kind="W-2", status="have", owner="spouse", provenance=Provenance.user_stated()),
        ],
    )
    restored = Profile.model_validate_json(profile.model_dump_json())
    assert restored.household.filing_status.value == "married_filing_jointly"
    assert restored.household.spouse.name.value == "Spouse Taxpayer"
    assert restored.household.spouse.immigration.visa_timeline[0].status == "F-2"
    assert [d.owner for d in restored.income_documents] == ["taxpayer", "spouse"]


def test_spouse_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Spouse.model_validate({"middle_name": "x"})
