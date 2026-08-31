"""M5, one session: generation from a time budget, muscles and a difficulty.

The tests that matter most here are the invariant ones. A generated session's
whole contract is that its three input parameters survive -- including surviving
a user re-rolling blocks repeatedly, which is the one path where the adaptive
load multiplier can compound if it is applied twice.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.models import Difficulty, Equipment, Modality, Muscle, RepsDose
from hibrid.objective_strategy import (
    HypertrophyStrategy,
    MuscularEnduranceStrategy,
    StrengthStrategy,
)
from hibrid.progression import ProgressionDecision
from hibrid.session_generation import (
    MAX_BLOCKS_PER_MUSCLE,
    TIME_BUDGET_TOLERANCE,
    StartingLoadPolicy,
    StartingLoadSource,
    UnmetConstraintKind,
    _within_skill_ceiling,
    generate_session,
    summarise_skill_filter,
    vary_block,
)
from hibrid.training_memory import MAX_ESTIMABLE_REPS, TrainingMemory
from hibrid.user.enums import ExperienceLevel, SessionStatus, TrainingEnvironment
from hibrid.user.health import HealthProfile, Injury
from hibrid.user.enums import BodyRegion, InjuryStatus
from hibrid.user.history import PerformedExercise, PerformedSet, TrainingSession
from hibrid.user.preferences import EquipmentAccess, TrainingPreferences
from hibrid.user.profile import TrainingBackground
from hibrid.variation import pct_diff
from hibrid.variation_context import SessionIntent, VariationContext

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


# --- The time budget ---------------------------------------------------------


@pytest.mark.parametrize("minutes", [30, 45, 60, 75])
@pytest.mark.parametrize("objective", [StrengthStrategy(), HypertrophyStrategy()])
def test_the_session_lands_inside_its_time_budget(db, minutes, objective):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS],
        duration_minutes=minutes,
        db=db,
        objective=objective,
        body_mass_kg=80.0,
        seed=7,
    )
    assert pct_diff(minutes * 60, session.total_time_seconds) <= TIME_BUDGET_TOLERANCE
    assert session.report.fits_time_budget


@pytest.mark.parametrize("minutes", [10, 20, 30, 45, 60, 75, 90, 120])
@pytest.mark.parametrize(
    "objective", [StrengthStrategy(), HypertrophyStrategy(), MuscularEnduranceStrategy()]
)
def test_the_report_never_lies_about_the_time_fit(db, minutes, objective):
    """The contract that has to hold at every budget, not just the plausible
    ones. Muscular endurance genuinely cannot fill 90 minutes for two muscles --
    short rest and a four-set ceiling cap a block near seven minutes, and the
    per-muscle block ceiling caps the count -- so what matters is that the miss
    is declared rather than absorbed."""
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS],
        duration_minutes=minutes,
        db=db,
        objective=objective,
        body_mass_kg=80.0,
        seed=7,
    )
    fits = pct_diff(minutes * 60, session.total_time_seconds) <= TIME_BUDGET_TOLERANCE
    assert session.report.fits_time_budget is fits
    if not fits:
        assert {c.kind for c in session.report.unmet_constraints} & {
            UnmetConstraintKind.TIME_BUDGET_OVERSHOT,
            UnmetConstraintKind.TIME_BUDGET_UNDERFILLED,
        }


def test_a_longer_budget_buys_more_blocks_not_longer_blocks(db):
    short = generate_session(muscles=[Muscle.QUADS], duration_minutes=25, db=db, body_mass_kg=80.0, seed=1)
    long = generate_session(muscles=[Muscle.QUADS], duration_minutes=75, db=db, body_mass_kg=80.0, seed=1)
    assert len(long.blocks) > len(short.blocks)


def test_a_budget_too_short_for_one_block_per_muscle_reports_the_overshoot(db):
    """A requested muscle is never dropped to save time -- the miss is reported."""
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS, Muscle.QUADS],
        duration_minutes=8,
        db=db,
        body_mass_kg=80.0,
        seed=1,
    )
    assert len(session.blocks) == 3
    assert not session.report.fits_time_budget
    assert {c.kind for c in session.report.unmet_constraints} == {
        UnmetConstraintKind.TIME_BUDGET_OVERSHOT
    }
    assert not session.report.muscles_uncovered


def test_a_budget_beyond_the_block_ceiling_reports_the_underfill(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS], duration_minutes=300, db=db, body_mass_kg=80.0, seed=1
    )
    assert len(session.blocks) == MAX_BLOCKS_PER_MUSCLE
    assert UnmetConstraintKind.TIME_BUDGET_UNDERFILLED in {
        c.kind for c in session.report.unmet_constraints
    }


def test_an_empty_session_does_not_also_report_a_time_miss(db):
    """The reason it is empty is the whole explanation; a budget it could never
    fill adds nothing."""
    session = generate_session(
        muscles=[Muscle.CARDIOVASCULAR_SYSTEM], duration_minutes=30, db=db, seed=1
    )
    assert not session.blocks
    assert {c.kind for c in session.report.unmet_constraints} == {
        UnmetConstraintKind.MODALITY_NOT_SUPPORTED
    }


def test_the_scheme_sits_inside_the_objectives_own_ranges(db):
    objective = StrengthStrategy()
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=60, db=db, objective=objective, body_mass_kg=80.0, seed=2
    )
    min_sets, max_sets = objective.set_range
    min_reps, max_reps = objective.rep_range
    min_rest, max_rest = objective.rest_range_seconds
    for block in session.blocks:
        dose = block.entry.dose
        assert isinstance(dose, RepsDose)
        assert min_sets <= dose.sets <= max_sets
        assert min_reps <= dose.reps <= max_reps
        assert min_rest <= block.entry.rest_seconds <= max_rest
        assert dose.rep_seconds == objective.rep_seconds


def test_the_scheme_is_not_decided_by_seconds_of_rest_rounding(db):
    """Exact time fit used to pick a double over a triple on a 10-second
    difference. Ties inside one granularity bucket fall through to the middle of
    the objective's ranges instead."""
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, objective=StrengthStrategy(),
        body_mass_kg=80.0, seed=3,
    )
    assert all(block.entry.dose.reps >= 3 for block in session.blocks)


# --- The muscles -------------------------------------------------------------


def test_every_requested_muscle_gets_at_least_one_block(db):
    muscles = [Muscle.PECTORALS, Muscle.LATS, Muscle.QUADS, Muscle.BICEPS]
    session = generate_session(
        muscles=muscles, duration_minutes=80, db=db, body_mass_kg=80.0, seed=5
    )
    assert set(session.report.muscles_covered) == set(muscles)
    assert not session.report.muscles_uncovered
    for muscle in muscles:
        assert any(block.target is muscle for block in session.blocks)


def test_every_block_actually_targets_the_muscle_it_claims(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=6
    )
    for block in session.blocks:
        assert db[block.entry.exercise_id].target is block.target


def test_a_muscle_listed_twice_is_trained_once(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.PECTORALS], duration_minutes=40, db=db, body_mass_kg=80.0, seed=1
    )
    assert session.report.muscles_requested == (Muscle.PECTORALS,)


def test_no_exercise_is_prescribed_twice_in_one_session(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS, Muscle.TRICEPS], duration_minutes=90, db=db,
        body_mass_kg=80.0, seed=4,
    )
    ids = [block.entry.exercise_id for block in session.blocks]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("seed", range(6))
def test_blocks_for_one_muscle_are_not_near_duplicates(db, seed):
    """Four cable fly variants is not a chest session. Movement pattern, or
    equipment where the pattern is unknown, has to differ."""
    session = generate_session(
        muscles=[Muscle.PECTORALS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=seed
    )
    keys = [
        db[b.entry.exercise_id].movement_pattern or db[b.entry.exercise_id].equipment
        for b in session.blocks
    ]
    assert len(keys) == len(set(keys))


def test_compound_movements_come_before_isolation_ones(db):
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=8
    )
    ranks = {"compound": 0, None: 1, "isolation": 2}
    seen = [
        ranks[db[b.entry.exercise_id].mechanics.value if db[b.entry.exercise_id].mechanics else None]
        for b in session.blocks
    ]
    assert seen == sorted(seen)


def test_a_muscle_only_trained_outside_resistance_is_named_as_a_perimeter_gap(db):
    """Not the same failure as 'this user is not allowed any of them', and the
    two need different fixes from the caller."""
    session = generate_session(
        muscles=[Muscle.CARDIOVASCULAR_SYSTEM, Muscle.PECTORALS], duration_minutes=40, db=db,
        body_mass_kg=80.0, seed=1,
    )
    assert session.report.muscles_uncovered == (Muscle.CARDIOVASCULAR_SYSTEM,)
    gap = next(c for c in session.report.unmet_constraints)
    assert gap.kind is UnmetConstraintKind.MODALITY_NOT_SUPPORTED
    assert "MET" in gap.detail
    assert not session.report.is_prescribable


def test_a_muscle_with_no_permitted_exercise_is_a_constraint_problem(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS],
        duration_minutes=40,
        db=db,
        context=VariationContext(available_equipment=frozenset()),
        body_mass_kg=80.0,
        seed=1,
    )
    assert not session.blocks
    assert {c.kind for c in session.report.unmet_constraints} == {
        UnmetConstraintKind.NO_PERMITTED_EXERCISE
    }


def test_generation_never_prescribes_a_non_resistance_exercise(db):
    session = generate_session(
        muscles=[Muscle.ABS, Muscle.QUADS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=9
    )
    for block in session.blocks:
        assert db[block.entry.exercise_id].modality is Modality.RESISTANCE


def test_requesting_no_muscles_yields_an_empty_session_rather_than_an_error(db):
    session = generate_session(muscles=[], duration_minutes=60, db=db, seed=1)
    assert session.blocks == ()
    assert session.report.starting_load_policy is StartingLoadPolicy.NONE_NEEDED


# --- The difficulty ----------------------------------------------------------


def test_difficulty_moves_volume_and_leaves_session_time_alone(db):
    volumes = {}
    times = {}
    for intent in SessionIntent:
        session = generate_session(
            muscles=[Muscle.QUADS],
            duration_minutes=60,
            db=db,
            context=VariationContext(session_intent=intent),
            body_mass_kg=80.0,
            seed=11,
        )
        volumes[intent] = session.total_volume
        times[intent] = session.total_time_seconds
    assert volumes[SessionIntent.LIGHT] < volumes[SessionIntent.MODERATE] < volumes[SessionIntent.CHALLENGING]
    assert len(set(times.values())) == 1


def test_difficulty_does_not_change_which_exercises_are_chosen(db):
    """Difficulty is how much work, not what kind. Changing selection with it
    would make the three levels incomparable."""
    chosen = {
        intent: [
            b.entry.exercise_id
            for b in generate_session(
                muscles=[Muscle.LATS], duration_minutes=45, db=db,
                context=VariationContext(session_intent=intent), body_mass_kg=80.0, seed=12,
            ).blocks
        ]
        for intent in SessionIntent
    }
    assert chosen[SessionIntent.LIGHT] == chosen[SessionIntent.CHALLENGING]


def test_the_report_carries_the_multiplier_the_loads_were_built_with(db):
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db,
        context=VariationContext(session_intent=SessionIntent.LIGHT), body_mass_kg=80.0, seed=1,
    )
    assert session.report.session_intent_load_multiplier == pytest.approx(0.85)


# --- Starting load -----------------------------------------------------------


def test_with_no_history_loads_come_from_a_conservative_body_mass_fraction(db):
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=13
    )
    assert session.report.starting_load_policy is StartingLoadPolicy.CONSERVATIVE
    loaded = [b for b in session.blocks if not db[b.entry.exercise_id].is_bodyweight]
    assert loaded
    for block in loaded:
        assert block.load_source is StartingLoadSource.CONSERVATIVE_BODYWEIGHT_FRACTION
        # Deliberately light: never more than half a beginner's body mass on any
        # single movement, which is the direction the bias has to run.
        assert 0 < block.entry.dose.weight <= 0.5 * 80.0


def test_a_heavier_user_starts_heavier(db):
    def first_load(body_mass):
        session = generate_session(
            muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=body_mass, seed=13
        )
        return max(b.entry.dose.weight for b in session.blocks)

    assert first_load(60.0) < first_load(100.0)


def test_a_bodyweight_block_reports_zero_load_as_correct_not_missing(db):
    session = generate_session(muscles=[Muscle.PECTORALS], duration_minutes=45, db=db, seed=1)
    bodyweight = [b for b in session.blocks if db[b.entry.exercise_id].is_bodyweight]
    assert bodyweight
    for block in bodyweight:
        assert block.load_source is StartingLoadSource.BODYWEIGHT_ONLY
        assert block.load_source.is_prescribable
        assert block.entry.dose.weight == 0.0
        assert not block.is_variable


def test_with_no_load_basis_bodyweight_exercises_are_preferred(db):
    """A 0 kg bodyweight block is a real prescription; a 0 kg barbell block is
    not, so the pool tilts toward the movements that need no number."""
    session = generate_session(muscles=[Muscle.PECTORALS], duration_minutes=45, db=db, seed=2)
    assert all(db[b.entry.exercise_id].is_bodyweight for b in session.blocks)
    assert session.report.is_prescribable


def test_a_loaded_block_with_no_basis_is_reported_and_not_prescribable(db):
    """Guarded rather than guessed: the block names the movement and the scheme
    and says plainly that its load is unknown.

    Barbells only, so the bodyweight preference has nothing to fall back on, and
    neither body mass nor history to derive a number from."""
    session = generate_session(
        muscles=[Muscle.QUADS],
        duration_minutes=45,
        db=db,
        context=VariationContext(available_equipment=frozenset({Equipment.BARBELL})),
        seed=3,
    )
    assert session.blocks
    assert all(b.load_source is StartingLoadSource.NO_BASIS for b in session.blocks)
    assert not any(b.load_source.is_prescribable for b in session.blocks)
    assert not session.report.is_prescribable
    assert UnmetConstraintKind.STARTING_LOAD_UNKNOWN in {
        c.kind for c in session.report.unmet_constraints
    }
    # The scheme and the movement are still real information -- the caller can
    # ask the user for a working weight and prescribe the rest as-is.
    assert all(b.entry.dose.sets > 0 and b.entry.dose.reps > 0 for b in session.blocks)


def test_a_session_that_resolved_nothing_does_not_claim_to_be_conservative(db):
    """`conservative` means "derived, deliberately light". A session where no
    load could be derived at all is a different fact and needs its own word, or
    the client tells the user it started them light when it started them at
    nothing."""
    session = generate_session(
        muscles=[Muscle.QUADS],
        duration_minutes=45,
        db=db,
        context=VariationContext(available_equipment=frozenset({Equipment.BARBELL})),
        seed=3,
    )
    assert session.report.starting_load_policy is StartingLoadPolicy.UNRESOLVED


def test_an_uncovered_muscle_is_not_also_reported_as_a_time_miss(db):
    """The uncovered muscle *is* why the time came up short. Reporting both
    sends the reader hunting for a second cause that does not exist."""
    session = generate_session(
        muscles=[Muscle.CARDIOVASCULAR_SYSTEM, Muscle.PECTORALS],
        duration_minutes=40,
        db=db,
        body_mass_kg=80.0,
        seed=1,
    )
    assert session.blocks  # pectorals was covered
    assert not session.report.fits_time_budget
    assert {c.kind for c in session.report.unmet_constraints} == {
        UnmetConstraintKind.MODALITY_NOT_SUPPORTED
    }


def test_per_block_constraints_are_reported_once_not_once_per_block(db):
    session = generate_session(
        muscles=[Muscle.QUADS],
        duration_minutes=45,
        db=db,
        context=VariationContext(max_load_kg=10.0),
        body_mass_kg=100.0,
        seed=14,
    )
    capped = [
        c for c in session.report.unmet_constraints
        if c.kind is UnmetConstraintKind.LOAD_CAPPED_BY_EQUIPMENT
    ]
    assert len(capped) == 1
    assert sum(1 for b in session.blocks if b.load_capped_by_equipment) > 1
    # The count is in the message, and the per-block flag carries which.
    assert "block(s)" in capped[0].detail


def test_a_hypertrophy_session_can_still_read_a_returning_users_history(db):
    """Regression: hypertrophy's mid-range scheme is 11 reps and
    MAX_ESTIMABLE_REPS is 10, so the scheme solver used to land one rep past the
    point where a remembered load can be resolved -- silently starting every
    returning user on the beginner fractions for the most common objective."""
    user_id = uuid4()
    baseline = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=15
    )
    target = next(b for b in baseline.blocks if not db[b.entry.exercise_id].is_bodyweight)
    memory = TrainingMemory.from_sessions(
        [_session_log(target.entry.exercise_id, 100.0, 7.0, user_id)],
        user_id=user_id,
        as_of=NOW,
    )
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, memory=memory,
        objective=HypertrophyStrategy(), body_mass_kg=80.0, seed=15,
    )
    assert all(b.entry.dose.reps <= MAX_ESTIMABLE_REPS for b in session.blocks)
    block = next(b for b in session.blocks if b.entry.exercise_id == target.entry.exercise_id)
    assert block.load_source is StartingLoadSource.REMEMBERED


def test_preferring_an_estimable_rep_count_never_costs_the_time_budget(db):
    """The history tie-break sits after time fit in the key, so it can only ever
    decide between schemes that fit the budget equally well."""
    user_id = uuid4()
    memory = TrainingMemory.from_sessions(
        [_session_log("x", 100.0, 7.0, user_id)], user_id=user_id, as_of=NOW
    )
    for minutes in (30, 45, 60):
        with_history = generate_session(
            muscles=[Muscle.QUADS], duration_minutes=minutes, db=db, memory=memory,
            body_mass_kg=80.0, seed=1,
        )
        without = generate_session(
            muscles=[Muscle.QUADS], duration_minutes=minutes, db=db, body_mass_kg=80.0, seed=1
        )
        assert with_history.report.fits_time_budget == without.report.fits_time_budget


def test_a_load_beyond_the_users_equipment_is_capped_and_reported(db):
    session = generate_session(
        muscles=[Muscle.QUADS],
        duration_minutes=45,
        db=db,
        context=VariationContext(max_load_kg=10.0),
        body_mass_kg=100.0,
        seed=14,
    )
    capped = [b for b in session.blocks if b.load_capped_by_equipment]
    assert capped
    for block in capped:
        assert block.entry.dose.weight <= 10.0
    assert UnmetConstraintKind.LOAD_CAPPED_BY_EQUIPMENT in {
        c.kind for c in session.report.unmet_constraints
    }


def _session_log(exercise_id, load_kg, rpe, user_id):
    return TrainingSession(
        user_id=user_id,
        performed_at=NOW - timedelta(days=3),
        status=SessionStatus.COMPLETED,
        exercises=(
            PerformedExercise(
                exercise_id=exercise_id,
                order_index=0,
                sets=tuple(
                    PerformedSet(
                        exercise_id=exercise_id,
                        set_index=i,
                        reps_completed=8,
                        load_kg=load_kg,
                        rpe=rpe,
                    )
                    for i in range(3)
                ),
            ),
        ),
    )


def test_history_outranks_the_conservative_fraction(db):
    """A returning user is not started from a beginner's table."""
    user_id = uuid4()
    # Pick a loaded quads exercise the generator will actually choose.
    baseline = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=15
    )
    target = next(b for b in baseline.blocks if not db[b.entry.exercise_id].is_bodyweight)
    memory = TrainingMemory.from_sessions(
        [_session_log(target.entry.exercise_id, 120.0, 7.0, user_id)],
        user_id=user_id,
        as_of=NOW,
    )
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, memory=memory, body_mass_kg=80.0, seed=15
    )
    block = next(b for b in session.blocks if b.entry.exercise_id == target.entry.exercise_id)
    assert block.load_source is StartingLoadSource.REMEMBERED
    assert block.entry.dose.weight > target.entry.dose.weight
    assert session.report.starting_load_policy in (
        StartingLoadPolicy.FROM_HISTORY,
        StartingLoadPolicy.MIXED,
    )


def test_an_easy_last_session_progresses_the_generated_load(db):
    user_id = uuid4()
    baseline = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=15
    )
    target = next(b for b in baseline.blocks if not db[b.entry.exercise_id].is_bodyweight)

    def load_at(rpe):
        memory = TrainingMemory.from_sessions(
            [_session_log(target.entry.exercise_id, 100.0, rpe, user_id)],
            user_id=user_id,
            as_of=NOW,
        )
        session = generate_session(
            muscles=[Muscle.QUADS], duration_minutes=45, db=db, memory=memory,
            body_mass_kg=80.0, seed=15,
        )
        return next(b for b in session.blocks if b.entry.exercise_id == target.entry.exercise_id)

    easy, hard = load_at(5.0), load_at(10.0)
    assert easy.progression.decision is ProgressionDecision.PROGRESSED
    assert hard.progression.decision is ProgressionDecision.BACKED_OFF
    assert easy.entry.dose.weight > hard.entry.dose.weight


def test_progression_is_absent_when_no_log_is_supplied(db):
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=1
    )
    assert all(block.progression is None for block in session.blocks)


# --- Constraints, reused wholesale from M3 -----------------------------------


def test_a_health_contraindication_is_never_prescribed(db):
    health = HealthProfile(
        injuries=(
            Injury(
                body_region=BodyRegion.KNEE,
                status=InjuryStatus.ACTIVE,
                contraindicated_movement_patterns=frozenset({"squat", "lunge", "isolation_knee"}),
            ),
        )
    )
    context = VariationContext.from_parts(health=health)
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, context=context, body_mass_kg=80.0, seed=16
    )
    for block in session.blocks:
        assert context.permits(db[block.entry.exercise_id])


def test_equipment_access_bounds_selection(db):
    preferences = TrainingPreferences(
        equipment_access=(
            EquipmentAccess(
                environment=TrainingEnvironment.HOME_GYM,
                available_equipment=frozenset({"dumbbell"}),
                is_default=True,
            ),
        )
    )
    session = generate_session(
        muscles=[Muscle.PECTORALS],
        duration_minutes=45,
        db=db,
        context=VariationContext.from_parts(preferences=preferences),
        body_mass_kg=80.0,
        seed=17,
    )
    assert session.blocks
    for block in session.blocks:
        assert db[block.entry.exercise_id].equipment.value == "dumbbell"


def test_a_beginners_skill_ceiling_excludes_expert_movements(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS, Muscle.QUADS],
        duration_minutes=90,
        db=db,
        background=TrainingBackground(experience_level=ExperienceLevel.UNTRAINED),
        body_mass_kg=80.0,
        seed=18,
    )
    for block in session.blocks:
        difficulty = db[block.entry.exercise_id].difficulty
        # Undeclared difficulty fails open, matching how find_substitutes treats
        # an undeclared movement pattern.
        if difficulty is not None:
            assert difficulty.rank <= Difficulty.BEGINNER.rank


def test_a_familiar_movement_overrides_the_skill_ceiling(db):
    """The ceiling is a proxy for "can they do this safely";
    `familiar_exercise_ids` is direct evidence of it, and the schema names the
    field for exactly this. A proxy must not overrule the measurement."""
    hard = next(
        exercise
        for exercise in db.all()
        if exercise.target is Muscle.QUADS
        and exercise.difficulty is not None
        and exercise.difficulty.rank > Difficulty.NOVICE.rank
    )
    beginner = TrainingBackground(experience_level=ExperienceLevel.BEGINNER)
    assert not _within_skill_ceiling(hard, beginner)
    told = TrainingBackground(
        experience_level=ExperienceLevel.BEGINNER,
        familiar_exercise_ids=frozenset({hard.id}),
    )
    assert _within_skill_ceiling(hard, told)


def test_the_skill_ceiling_narrowing_is_reported_not_invisible(db):
    """`context_filter` only knows about health, equipment and preferences, so a
    session drawn from a third of the library would otherwise look unfiltered."""
    session = generate_session(
        muscles=[Muscle.QUADS],
        duration_minutes=45,
        db=db,
        background=TrainingBackground(experience_level=ExperienceLevel.UNTRAINED),
        body_mass_kg=80.0,
        seed=1,
    )
    assert session.report.skill_ceiling is Difficulty.BEGINNER
    assert session.report.skill_filter is not None
    assert session.report.skill_filter.permitted < session.report.skill_filter.total


def test_the_ceiling_applies_with_no_background_and_says_so(db):
    """Beginner is the safe direction to default, but defaulting silently to a
    62%-of-library pool is the kind of narrowing that has to be declared."""
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=1
    )
    assert session.report.skill_ceiling is Difficulty.NOVICE
    assert session.report.skill_filter is not None
    assert 0.0 < session.report.skill_filter.permitted_fraction < 1.0


def test_a_wider_ceiling_permits_at_least_as_much(db):
    ordered = [
        ExperienceLevel.UNTRAINED,
        ExperienceLevel.BEGINNER,
        ExperienceLevel.NOVICE,
        ExperienceLevel.INTERMEDIATE,
        ExperienceLevel.ADVANCED,
        ExperienceLevel.ELITE,
    ]
    permitted = [
        summarise_skill_filter(TrainingBackground(experience_level=level), db).permitted
        for level in ordered
    ]
    assert permitted == sorted(permitted)
    assert permitted[-1] == len(db.all())


def test_an_advanced_user_reaches_movements_a_beginner_cannot(db):
    def hardest(level):
        session = generate_session(
            muscles=[Muscle.PECTORALS, Muscle.LATS, Muscle.QUADS],
            duration_minutes=90,
            db=db,
            background=TrainingBackground(experience_level=level),
            body_mass_kg=80.0,
            seed=19,
        )
        ranks = [
            db[b.entry.exercise_id].difficulty.rank
            for b in session.blocks
            if db[b.entry.exercise_id].difficulty is not None
        ]
        return max(ranks) if ranks else -1

    assert hardest(ExperienceLevel.ELITE) >= hardest(ExperienceLevel.UNTRAINED)


def test_a_dislike_costs_a_candidate_without_excluding_it(db):
    plain = generate_session(
        muscles=[Muscle.LATS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=20
    )
    disliked = frozenset(b.entry.exercise_id for b in plain.blocks)
    avoided = generate_session(
        muscles=[Muscle.LATS],
        duration_minutes=45,
        db=db,
        context=VariationContext(disliked_exercise_ids=disliked),
        body_mass_kg=80.0,
        seed=20,
    )
    assert not disliked & {b.entry.exercise_id for b in avoided.blocks}
    assert len(avoided.blocks) == len(plain.blocks)


# --- Determinism -------------------------------------------------------------


def test_the_same_seed_reproduces_the_same_session(db):
    def build(seed):
        session = generate_session(
            muscles=[Muscle.PECTORALS, Muscle.LATS], duration_minutes=60, db=db,
            body_mass_kg=80.0, seed=seed,
        )
        return [(b.entry.exercise_id, b.entry.dose.describe(), b.entry.rest_seconds) for b in session.blocks]

    assert build(42) == build(42)
    assert build(42) != build(43)


def test_blocks_and_routine_entries_are_the_same_objects(db):
    session = generate_session(
        muscles=[Muscle.PECTORALS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=1
    )
    for index, block in enumerate(session.blocks):
        assert block.entry is session.routine.entries[index]
        assert block.index == index


# --- Re-rolling a block: the invariant --------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_a_re_rolled_block_holds_its_volume_and_time(db, seed):
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=seed
    )
    for block in session.blocks:
        variation = vary_block(block, db, seed=seed, substitution_prob=1.0)
        assert variation.volume_preserved
        assert variation.time_preserved
        assert variation.target_preserved
        assert variation.block.index == block.index


def test_re_rolling_does_not_re_apply_the_difficulty_multiplier(db):
    """The failure this guards against is silent and compounding: a challenging
    session climbing 15% per re-roll until the numbers are absurd."""
    context = VariationContext(session_intent=SessionIntent.CHALLENGING)
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, context=context, body_mass_kg=80.0, seed=21
    )
    block = next(b for b in session.blocks if b.is_variable)
    start = block.volume
    for i in range(8):
        variation = vary_block(block, db, context=context, seed=i, substitution_prob=1.0)
        block = variation.block
        assert variation.volume_preserved
    assert pct_diff(start, block.volume) <= 0.30


def test_re_rolling_still_honours_health_constraints(db):
    """The adaptive tier is dropped on a re-roll. The inviolable one is not."""
    health = HealthProfile(
        injuries=(
            Injury(
                body_region=BodyRegion.SHOULDER,
                status=InjuryStatus.ACTIVE,
                contraindicated_movement_patterns=frozenset({"vertical_push", "horizontal_push"}),
            ),
        )
    )
    context = VariationContext.from_parts(health=health)
    session = generate_session(
        muscles=[Muscle.PECTORALS], duration_minutes=45, db=db, context=context, body_mass_kg=80.0, seed=22
    )
    for block in session.blocks:
        varied = vary_block(block, db, context=context, seed=1, substitution_prob=1.0).block
        assert context.permits(db[varied.entry.exercise_id])


def test_a_re_rolled_block_reports_where_its_load_came_from(db):
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, body_mass_kg=80.0, seed=23
    )
    block = next(b for b in session.blocks if b.is_variable)
    variation = vary_block(block, db, seed=1, substitution_prob=1.0)
    assert variation.block.load_source is StartingLoadSource.PRESERVED_FROM_BLOCK
    assert variation.original.load_source is block.load_source


def test_a_bodyweight_block_keeps_its_dose_but_can_change_exercise(db):
    session = generate_session(muscles=[Muscle.PECTORALS], duration_minutes=45, db=db, seed=24)
    block = next(b for b in session.blocks if not b.is_variable)
    variation = vary_block(block, db, seed=1, substitution_prob=1.0)
    assert not variation.dose_outcome.is_varied
    assert variation.volume_preserved and variation.time_preserved


def test_re_rolling_keeps_the_block_inside_the_users_equipment(db):
    context = VariationContext(max_load_kg=40.0)
    session = generate_session(
        muscles=[Muscle.QUADS], duration_minutes=45, db=db, context=context, body_mass_kg=70.0, seed=25
    )
    for block in session.blocks:
        varied = vary_block(block, db, context=context, seed=2, substitution_prob=1.0).block
        assert varied.entry.dose.weight <= 40.0


def test_the_session_total_survives_re_rolling_every_block(db):
    """The point of blocks: the three requested parameters hold however many
    times the user presses the button."""
    session = generate_session(
        muscles=[Muscle.PECTORALS, Muscle.LATS], duration_minutes=60, db=db, body_mass_kg=80.0, seed=26
    )
    rerolled = [vary_block(b, db, seed=i, substitution_prob=1.0).block for i, b in enumerate(session.blocks)]
    assert pct_diff(session.total_volume, sum(b.volume for b in rerolled)) <= 0.075
    assert pct_diff(session.total_time_seconds, sum(b.time_seconds for b in rerolled)) <= 0.10
    assert [b.target for b in rerolled] == [b.target for b in session.blocks]
