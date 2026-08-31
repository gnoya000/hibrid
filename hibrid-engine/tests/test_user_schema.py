"""Tests for the V2 user schema.

These assert the schema's *guarantees* rather than its field list: that invalid
data is rejected at construction, that recorded facts cannot be mutated, and
that the whole aggregate survives a serialisation round trip. Field-by-field
tests would only restate the models; these fail if a future edit quietly
weakens a constraint something downstream depends on.
"""

from datetime import date, datetime, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hibrid.user import (
    AvailabilityWindow,
    BiologicalSex,
    BodyComposition,
    BodyRegion,
    Equipment,
    EquipmentAccess,
    ExercisePerformanceRecord,
    FitnessAssessment,
    HealthProfile,
    Injury,
    InjuryStatus,
    MeasurementSource,
    MedicalConsideration,
    MovementPattern,
    ObjectiveWeights,
    PerformedExercise,
    PerformedSet,
    RecoveryReading,
    SessionStatus,
    TrainingEnvironment,
    TrainingGoal,
    TrainingObjective,
    TrainingPreferences,
    TrainingSession,
    User,
    UserProfile,
    Weekday,
    latest_before,
)

USER_ID = uuid4()
OTHER_USER_ID = uuid4()


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        user_id=USER_ID,
        birth_date=date(1990, 5, 17),
        biological_sex=BiologicalSex.MALE,
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture
def strength_bias() -> ObjectiveWeights:
    return ObjectiveWeights.normalised(
        {TrainingObjective.STRENGTH: 3.0, TrainingObjective.MOBILITY: 1.0}
    )


# --- Units, derived values ---------------------------------------------------


def test_age_is_derived_from_birth_date_not_stored(profile: UserProfile) -> None:
    assert "age" not in UserProfile.model_fields
    assert profile.age_years(date(2026, 8, 7)) == pytest.approx(36.23, abs=0.01)
    assert profile.age_years(date(2036, 8, 7)) == pytest.approx(46.23, abs=0.01)


def test_training_age_is_none_without_a_start_date() -> None:
    from hibrid.user import TrainingBackground

    assert TrainingBackground().training_age_years(date(2026, 8, 7)) is None
    background = TrainingBackground(training_start_date=date(2020, 8, 7))
    assert background.training_age_years(date(2026, 8, 7)) == pytest.approx(6.0, abs=0.01)


# --- Objective weights -------------------------------------------------------


def test_objective_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        ObjectiveWeights(
            weights={TrainingObjective.STRENGTH: 0.5, TrainingObjective.POWER: 0.2}
        )


def test_objective_weights_normalise_arbitrary_shares(
    strength_bias: ObjectiveWeights,
) -> None:
    assert strength_bias.weights[TrainingObjective.STRENGTH] == pytest.approx(0.75)
    assert strength_bias.weights[TrainingObjective.MOBILITY] == pytest.approx(0.25)
    assert strength_bias.primary is TrainingObjective.STRENGTH


@pytest.mark.parametrize(
    "raw",
    [{}, {TrainingObjective.STRENGTH: -1.0}, {TrainingObjective.STRENGTH: 0.0}],
)
def test_objective_weights_reject_degenerate_input(raw: dict[TrainingObjective, float]) -> None:
    with pytest.raises(ValueError):
        ObjectiveWeights.normalised(raw)


# --- Recorded facts are immutable and validated ------------------------------


def test_measurement_records_are_immutable() -> None:
    record = BodyComposition(
        user_id=USER_ID, recorded_at=datetime(2026, 8, 1), body_mass_kg=82.5
    )
    with pytest.raises(ValidationError):
        record.body_mass_kg = 99.0


def test_unknown_fields_are_rejected_not_silently_dropped() -> None:
    """Guards against a device integration renaming a field and the value
    vanishing without anyone noticing."""
    with pytest.raises(ValidationError):
        RecoveryReading(
            user_id=USER_ID,
            recorded_at=datetime(2026, 8, 1),
            hrv_rmsdd_ms=45.0,  # deliberate typo of hrv_rmssd_ms
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rpe", 12.0),
        ("rpe", 0.0),
        ("load_kg", -5.0),
        ("reps_completed", -1),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        PerformedSet(exercise_id="bench_press", set_index=0, **{field: value})


def test_performed_set_volume_requires_both_reps_and_load() -> None:
    loaded = PerformedSet(
        exercise_id="bench_press", set_index=0, reps_completed=8, load_kg=80.0
    )
    assert loaded.volume_load_kg == pytest.approx(640.0)

    timed = PerformedSet(exercise_id="plank", set_index=0, duration_seconds=60.0)
    assert timed.volume_load_kg is None


def test_performed_exercise_rejects_sets_for_a_different_exercise() -> None:
    with pytest.raises(ValidationError):
        PerformedExercise(
            exercise_id="back_squat",
            order_index=0,
            sets=(PerformedSet(exercise_id="bench_press", set_index=0),),
        )


def test_warmup_sets_excluded_from_working_volume() -> None:
    exercise = PerformedExercise(
        exercise_id="bench_press",
        order_index=0,
        sets=(
            PerformedSet(
                exercise_id="bench_press",
                set_index=0,
                reps_completed=10,
                load_kg=40.0,
                is_warmup=True,
            ),
            PerformedSet(
                exercise_id="bench_press", set_index=1, reps_completed=8, load_kg=80.0
            ),
        ),
    )
    assert len(exercise.working_sets) == 1
    assert exercise.total_volume_load_kg == pytest.approx(640.0)


def test_session_load_is_rpe_times_minutes() -> None:
    session = TrainingSession(
        user_id=USER_ID,
        performed_at=datetime(2026, 8, 1, 18, 0),
        session_rpe=8.0,
        duration_seconds=3600.0,
    )
    assert session.session_load == pytest.approx(480.0)


def test_session_load_is_none_without_rpe() -> None:
    session = TrainingSession(
        user_id=USER_ID, performed_at=datetime(2026, 8, 1), duration_seconds=3600.0
    )
    assert session.session_load is None


def test_skipped_session_is_representable() -> None:
    """Absence of a session and a deliberately skipped one are different facts."""
    session = TrainingSession(
        user_id=USER_ID,
        performed_at=datetime(2026, 8, 1),
        status=SessionStatus.SKIPPED,
    )
    assert session.status is SessionStatus.SKIPPED
    assert session.total_volume_load_kg == 0.0


def test_substitution_is_recorded_as_a_deviation() -> None:
    exercise = PerformedExercise(
        exercise_id="incline_dumbbell_press",
        order_index=0,
        substituted_from_exercise_id="bench_press",
        substitution_reason="bench occupied",
    )
    assert exercise.substituted_from_exercise_id == "bench_press"


# --- Health constraints ------------------------------------------------------


def test_resolved_injury_requires_a_resolution_date() -> None:
    with pytest.raises(ValidationError):
        Injury(body_region=BodyRegion.KNEE, status=InjuryStatus.RESOLVED)


def test_injury_dates_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Injury(
            body_region=BodyRegion.KNEE,
            status=InjuryStatus.RESOLVED,
            onset_date=date(2026, 5, 1),
            resolved_date=date(2026, 1, 1),
        )


@pytest.mark.parametrize(
    ("status", "limiting"),
    [
        (InjuryStatus.ACTIVE, True),
        (InjuryStatus.RECOVERING, True),
        (InjuryStatus.CHRONIC, True),
        (InjuryStatus.RESOLVED, False),
    ],
)
def test_only_unresolved_injuries_constrain_programming(
    status: InjuryStatus, limiting: bool
) -> None:
    injury = Injury(
        body_region=BodyRegion.KNEE,
        status=status,
        resolved_date=date(2026, 1, 1) if status is InjuryStatus.RESOLVED else None,
    )
    assert injury.is_limiting is limiting


def test_health_profile_unions_contraindications_from_all_sources() -> None:
    health = HealthProfile(
        injuries=(
            Injury(
                body_region=BodyRegion.LOWER_BACK,
                status=InjuryStatus.ACTIVE,
                contraindicated_movement_patterns=frozenset({MovementPattern.HINGE}),
                contraindicated_exercise_ids=frozenset({"deadlift"}),
            ),
            Injury(
                body_region=BodyRegion.KNEE,
                status=InjuryStatus.RESOLVED,
                resolved_date=date(2025, 1, 1),
                contraindicated_movement_patterns=frozenset({MovementPattern.SQUAT}),
            ),
        ),
        medical_considerations=(
            MedicalConsideration(
                condition="hypertension",
                limits_valsalva_or_breath_holding=True,
                contraindicated_movement_patterns=frozenset(
                    {MovementPattern.VERTICAL_PUSH}
                ),
            ),
        ),
    )
    # The resolved knee injury must not still be blocking squats.
    assert health.blocked_movement_patterns == frozenset(
        {MovementPattern.HINGE, MovementPattern.VERTICAL_PUSH}
    )
    assert health.blocked_exercise_ids == frozenset({"deadlift"})
    assert len(health.active_injuries) == 1


# --- Preferences -------------------------------------------------------------


def test_exercise_cannot_be_both_preferred_and_excluded() -> None:
    with pytest.raises(ValidationError):
        TrainingPreferences(
            preferred_exercise_ids=frozenset({"bench_press"}),
            excluded_exercise_ids=frozenset({"bench_press"}),
        )


def test_max_session_duration_must_not_undercut_the_preferred_one() -> None:
    with pytest.raises(ValidationError):
        TrainingPreferences(
            preferred_session_duration_minutes=90.0,
            max_session_duration_minutes=45.0,
        )


def test_availability_window_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        AvailabilityWindow(
            weekday=Weekday.MONDAY,
            earliest_start=time(18, 0),
            latest_end=time(9, 0),
        )


def test_weekday_values_match_stdlib_date_weekday() -> None:
    assert Weekday(date(2026, 8, 3).weekday()) is Weekday.MONDAY
    assert Weekday(date(2026, 8, 7).weekday()) is Weekday.FRIDAY


def test_equipment_vocabulary_is_shared_with_the_exercise_library() -> None:
    """The user schema must not fork its own equipment enum."""
    from hibrid.models import Equipment as ModelsEquipment

    assert Equipment is ModelsEquipment
    access = EquipmentAccess(
        environment=TrainingEnvironment.HOME_GYM,
        available_equipment=frozenset({Equipment.DUMBBELL}),
        max_load_kg=32.0,
    )
    assert Equipment.DUMBBELL in access.available_equipment


# --- Aggregate integrity -----------------------------------------------------


def test_user_rejects_records_belonging_to_someone_else(profile: UserProfile) -> None:
    with pytest.raises(ValidationError):
        User(
            profile=profile,
            sessions=(
                TrainingSession(user_id=OTHER_USER_ID, performed_at=datetime(2026, 8, 1)),
            ),
        )


def test_user_rejects_mismatched_exercise_record_key(profile: UserProfile) -> None:
    with pytest.raises(ValidationError):
        User(
            profile=profile,
            exercise_records={
                "back_squat": ExercisePerformanceRecord(
                    user_id=USER_ID,
                    exercise_id="bench_press",
                    computed_at=datetime(2026, 8, 1),
                )
            },
        )


def test_current_body_mass_skips_records_that_omit_it(profile: UserProfile) -> None:
    """The newest body-composition record may be girths-only, so the lookup has
    to scan back rather than read the latest record blindly."""
    user = User(
        profile=profile,
        body_composition_history=(
            BodyComposition(
                user_id=USER_ID, recorded_at=datetime(2026, 6, 1), body_mass_kg=84.0
            ),
            BodyComposition(
                user_id=USER_ID, recorded_at=datetime(2026, 7, 1), body_mass_kg=82.5
            ),
            BodyComposition(
                user_id=USER_ID,
                recorded_at=datetime(2026, 8, 1),
                girths_cm={BodyRegion.CHEST: 104.0},
            ),
        ),
    )
    assert user.current_body_mass_kg == pytest.approx(82.5)


def test_history_order_does_not_affect_latest_lookups(profile: UserProfile) -> None:
    out_of_order = (
        RecoveryReading(user_id=USER_ID, recorded_at=datetime(2026, 8, 3), hrv_rmssd_ms=55.0),
        RecoveryReading(user_id=USER_ID, recorded_at=datetime(2026, 8, 1), hrv_rmssd_ms=40.0),
        RecoveryReading(user_id=USER_ID, recorded_at=datetime(2026, 8, 2), hrv_rmssd_ms=48.0),
    )
    user = User(profile=profile, recovery_history=out_of_order)
    latest = user.latest_recovery()
    assert latest is not None
    assert latest.hrv_rmssd_ms == pytest.approx(55.0)


def test_point_in_time_lookup_ignores_later_records(profile: UserProfile) -> None:
    """Reconstructing what was known at a past moment is what keeps future model
    training free of target leakage."""
    history = (
        RecoveryReading(user_id=USER_ID, recorded_at=datetime(2026, 8, 1), hrv_rmssd_ms=40.0),
        RecoveryReading(user_id=USER_ID, recorded_at=datetime(2026, 8, 5), hrv_rmssd_ms=60.0),
    )
    at_cutoff = latest_before(history, datetime(2026, 8, 3))
    assert at_cutoff is not None
    assert at_cutoff.hrv_rmssd_ms == pytest.approx(40.0)
    assert latest_before(history, datetime(2025, 1, 1)) is None


def test_primary_goal_picks_highest_priority(
    profile: UserProfile, strength_bias: ObjectiveWeights
) -> None:
    endurance = ObjectiveWeights.normalised(
        {TrainingObjective.CARDIOVASCULAR_ENDURANCE: 1.0}
    )
    user = User(
        profile=profile,
        goals=(
            TrainingGoal(name="maintain", objectives=endurance, priority=2),
            TrainingGoal(name="focus", objectives=strength_bias, priority=9),
            TrainingGoal(name="old", objectives=endurance, priority=10, is_active=False),
        ),
    )
    primary = user.primary_goal
    assert primary is not None
    assert primary.name == "focus"
    assert len(user.active_goals) == 2


# --- Serialisation -----------------------------------------------------------


def test_user_survives_a_json_round_trip(
    profile: UserProfile, strength_bias: ObjectiveWeights
) -> None:
    """Round-tripping is what a graph/feature-store projection will rely on."""
    original = User(
        profile=profile,
        goals=(TrainingGoal(objectives=strength_bias),),
        health=HealthProfile(
            injuries=(Injury(body_region=BodyRegion.SHOULDER, status=InjuryStatus.ACTIVE),)
        ),
        recovery_history=(
            RecoveryReading(
                user_id=USER_ID,
                recorded_at=datetime(2026, 8, 1),
                hrv_rmssd_ms=52.0,
                source=MeasurementSource.WHOOP,
            ),
        ),
        fitness_assessments=(
            FitnessAssessment(
                user_id=USER_ID,
                recorded_at=datetime(2026, 8, 1),
                overall_score=68.0,
                component_scores={TrainingObjective.STRENGTH: 74.0},
            ),
        ),
        sessions=(
            TrainingSession(
                user_id=USER_ID,
                performed_at=datetime(2026, 8, 1, 18, 0),
                exercises=(
                    PerformedExercise(
                        exercise_id="bench_press",
                        order_index=0,
                        sets=(
                            PerformedSet(
                                exercise_id="bench_press",
                                set_index=0,
                                reps_completed=8,
                                load_kg=80.0,
                                rpe=8.0,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    restored = User.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.current_body_mass_kg is None
    assert restored.sessions[0].total_volume_load_kg == pytest.approx(640.0)


def test_json_schema_is_exportable() -> None:
    """The generated schema is the contract for future ingestion endpoints."""
    schema = User.model_json_schema()
    assert schema["type"] == "object"
    assert "profile" in schema["properties"]
