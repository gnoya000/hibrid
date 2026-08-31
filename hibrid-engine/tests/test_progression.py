"""M8b: variation becomes programming.

The claim under test is that the *routine's* weight stops being the reference
once history exists. Everything else here defends the ways that can go wrong --
ratcheting a user down after a deload, progressing on silence, or reading one
exercise's history onto another.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.models import RepsDose, Routine, RoutineEntry
from hibrid.objective_strategy import HypertrophyStrategy
from hibrid.progression import ProgressionDecision, ProgressionPlan
from hibrid.training_memory import MAX_ESTIMABLE_REPS, OneRepMaxFormula, TrainingMemory
from hibrid.user.enums import SessionStatus
from hibrid.user.history import PerformedExercise, PerformedSet, TrainingSession
from hibrid.variation import DoseOutcome, vary_routine
from hibrid.variation_context import SessionIntent, VariationContext

USER_ID = uuid4()
NOW = datetime(2026, 8, 9, 7, 0, tzinfo=timezone.utc)
BENCH = "barbell-bench-press"
HYPERTROPHY = HypertrophyStrategy()


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


def bench_set(
    index: int = 0,
    reps: int = 8,
    load: float = 100.0,
    *,
    rpe: float | None = None,
    prescribed_reps: int | None = None,
    form_breakdown: bool = False,
    pain: bool = False,
) -> PerformedSet:
    return PerformedSet(
        exercise_id=BENCH,
        set_index=index,
        reps_completed=reps,
        load_kg=load,
        rpe=rpe,
        prescribed_reps=prescribed_reps,
        form_breakdown=form_breakdown,
        pain_reported=pain,
    )


def bench_session(*sets: PerformedSet, days_ago: float = 3) -> TrainingSession:
    return TrainingSession(
        user_id=USER_ID,
        performed_at=NOW - timedelta(days=days_ago),
        status=SessionStatus.COMPLETED,
        exercises=(PerformedExercise(exercise_id=BENCH, order_index=0, sets=sets),),
    )


def memory_of(*sessions: TrainingSession) -> TrainingMemory:
    return TrainingMemory.from_sessions(sessions, user_id=USER_ID, as_of=NOW)


def bench_routine(sets: int = 4, reps: int = 8, weight: float = 80.0) -> Routine:
    """Deliberately stale: the user in these tests benches 100, not 80."""
    return Routine(
        name="Bench day",
        entries=[RoutineEntry(exercise_id=BENCH, dose=RepsDose(sets=sets, reps=reps, weight=weight))],
    )


def plan_for(memory: TrainingMemory, reps: int = 8, increment: float = 2.5) -> ProgressionPlan:
    return ProgressionPlan.build(
        memory,
        objective=HYPERTROPHY,
        prescribed_reps={BENCH: reps},
        weight_increment=increment,
    )


# --- The rep-max inverse ---------------------------------------------------


def test_the_estimator_and_its_inverse_round_trip():
    """A load derived from history passes through both directions, so any
    disagreement would make it drift a little further every session."""
    for formula in OneRepMaxFormula:
        for reps in range(1, MAX_ESTIMABLE_REPS + 1):
            one_rm = formula.estimate(100.0, reps)
            assert one_rm is not None
            assert formula.load_for_reps(one_rm, reps) == pytest.approx(100.0)


def test_the_inverse_refuses_where_the_estimator_does():
    assert OneRepMaxFormula.EPLEY.load_for_reps(120.0, MAX_ESTIMABLE_REPS + 1) is None
    assert OneRepMaxFormula.EPLEY.load_for_reps(0.0, 5) is None


def test_a_remembered_load_is_rescaled_to_the_reps_being_prescribed():
    """The whole reason history cannot be read as a bare weight: this engine
    changes the rep scheme every session on purpose, and 100kg for a triple is
    not 100kg for a set of ten."""
    memory = memory_of(bench_session(bench_set(reps=5, load=100.0)))
    at_five = memory.working_load(BENCH, 5)
    at_ten = memory.working_load(BENCH, 10)

    assert at_five == pytest.approx(100.0)
    assert at_ten is not None and at_ten < at_five


# --- The headline ----------------------------------------------------------


def test_history_outranks_the_weight_written_in_the_routine(db):
    """Six weeks of progression must not be undone by re-reading the YAML.

    The routine still says 80kg. The user benches 100. Before M8b every
    variation dragged them back to the file's number."""
    memory = memory_of(bench_session(bench_set(reps=8, load=100.0, rpe=8.0)))
    routine = bench_routine(weight=80.0)

    varied = vary_routine(routine, db, memory=memory, seed=3, substitution_prob=0.0)
    entry = varied.entry_variations[0]

    assert entry.progression is not None
    assert entry.progression.decision is ProgressionDecision.HELD
    assert entry.progression.reference_load_kg == pytest.approx(100.0)
    # The target is built from 4x8x100, not 4x8x80.
    assert varied.routine.total_volume > routine.total_volume
    assert varied.routine.total_volume == pytest.approx(3200.0, rel=0.075)
    assert entry.dose_outcome is DoseOutcome.VARIED_AT_REMEMBERED_LOAD


def test_without_memory_the_routines_own_weight_still_stands(db):
    """The control, and the compatibility guarantee: every caller that supplies
    no history sees exactly the pre-M8b behaviour."""
    routine = bench_routine(weight=80.0)
    varied = vary_routine(routine, db, seed=3, substitution_prob=0.0)

    assert varied.progression.is_empty
    assert varied.entry_variations[0].progression is None
    assert varied.entry_variations[0].dose_outcome is DoseOutcome.VARIED
    assert varied.routine.total_volume == pytest.approx(routine.total_volume, rel=0.075)


def test_a_deload_does_not_ratchet_the_user_down(db):
    """The failure mode that reading last session's *weight* would cause.

    Strain cut last week to 85kg and it felt easy. Reading that forward as the
    new normal would compound the loss every session. An e1RM is a
    best-over-history figure, so the light week leaves it untouched."""
    memory = memory_of(
        bench_session(bench_set(reps=8, load=100.0, rpe=8.0), days_ago=10),
        bench_session(bench_set(reps=8, load=85.0, rpe=6.0), days_ago=3),
    )
    plan = plan_for(memory)
    progression = plan.for_exercise(BENCH)

    assert progression is not None
    assert progression.reference_load_kg == pytest.approx(100.0), "the deload is not the new normal"
    # The easy session is still read as a reason to progress, from the real
    # reference rather than from the reduced one.
    assert progression.decision is ProgressionDecision.PROGRESSED
    assert progression.working_load_kg == pytest.approx(102.5)


# --- The decision ----------------------------------------------------------


def test_an_easy_session_progresses_the_load():
    """Hypertrophy targets RPE 7-9; coming in at 6 means there was room."""
    plan = plan_for(memory_of(bench_session(bench_set(rpe=6.0))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.PROGRESSED
    assert progression.working_load_kg == pytest.approx(102.5)


def test_a_session_inside_the_target_band_holds():
    plan = plan_for(memory_of(bench_session(bench_set(rpe=8.0))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.HELD
    assert progression.working_load_kg == pytest.approx(100.0)


def test_a_session_harder_than_the_target_band_backs_off():
    plan = plan_for(memory_of(bench_session(bench_set(rpe=9.5))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.BACKED_OFF
    assert progression.working_load_kg == pytest.approx(97.5)


def test_the_target_band_is_the_objectives_own():
    """RPE 6 is 'room to spare' under hypertrophy (7-9) and 'about right'
    under muscular endurance (6-8). This is what finally consumes
    ObjectiveStrategy.target_rpe_range, declared since M2 and read by nothing."""
    from hibrid.objective_strategy import MuscularEnduranceStrategy

    memory = memory_of(bench_session(bench_set(rpe=6.0)))
    hypertrophy = ProgressionPlan.build(
        memory, objective=HYPERTROPHY, prescribed_reps={BENCH: 8}, weight_increment=2.5
    ).for_exercise(BENCH)
    endurance = ProgressionPlan.build(
        memory,
        objective=MuscularEnduranceStrategy(),
        prescribed_reps={BENCH: 8},
        weight_increment=2.5,
    ).for_exercise(BENCH)

    assert hypertrophy is not None and endurance is not None
    assert hypertrophy.decision is ProgressionDecision.PROGRESSED
    assert endurance.decision is ProgressionDecision.HELD


def test_pain_backs_off_whatever_the_effort_said():
    """Low RPE plus pain is a joint that let go, not an easy day."""
    plan = plan_for(memory_of(bench_session(bench_set(rpe=5.0, pain=True))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.BACKED_OFF


def test_form_breakdown_holds_rather_than_backing_off():
    """The schema names this exactly: 'a signal to hold load rather than
    progress it'. Technique failing at a manageable load is a skill problem,
    and stripping weight does not train the skill."""
    plan = plan_for(memory_of(bench_session(bench_set(rpe=6.0, form_breakdown=True))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.HELD


def test_missed_prescribed_reps_hold_the_load():
    plan = plan_for(memory_of(bench_session(bench_set(reps=5, prescribed_reps=8, rpe=6.0))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.HELD


def test_an_unplanned_session_is_not_a_missed_prescription():
    """`met_prescribed_reps` is None when nothing was prescribed. Treating that
    as a miss would hold back every user who trains without a plan."""
    plan = plan_for(memory_of(bench_session(bench_set(reps=5, rpe=6.0))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.PROGRESSED


def test_no_logged_effort_holds_rather_than_progresses():
    """Progressing on silence would add load every session for anyone who
    never logs RPE, which is most people."""
    plan = plan_for(memory_of(bench_session(bench_set(rpe=None))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.HELD
    assert progression.observed_rpe is None


def test_backing_off_never_reaches_zero():
    """A working load of zero is a bodyweight exercise, not a deload, and the
    two must not be confused downstream."""
    plan = plan_for(memory_of(bench_session(bench_set(reps=1, load=2.5, rpe=10.0))), reps=1)
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.working_load_kg is not None
    assert progression.working_load_kg > 0


# --- Absence and boundaries ------------------------------------------------


def test_no_history_for_a_movement_is_reported_not_guessed():
    plan = plan_for(memory_of())
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.NO_HISTORY
    assert progression.working_load_kg is None
    assert plan.load_for(BENCH, reps=8, fallback_kg=80.0) == 80.0


def test_a_bodyweight_history_yields_no_reference_load():
    """The record exists, but a rep-max formula cannot speak about it."""
    plan = plan_for(memory_of(bench_session(bench_set(reps=20, load=0.0, rpe=6.0))))
    progression = plan.for_exercise(BENCH)
    assert progression is not None
    assert progression.decision is ProgressionDecision.NO_HISTORY


def test_a_substituted_exercise_falls_back_to_the_routines_weight(db):
    """Bench history says nothing about a dumbbell press. Carrying the load
    across would be the most dangerous kind of confident wrong answer."""
    memory = memory_of(bench_session(bench_set(reps=8, load=100.0, rpe=6.0)))
    routine = bench_routine(weight=80.0)

    varied = vary_routine(routine, db, memory=memory, seed=1, substitution_prob=1.0)
    entry = varied.entry_variations[0]

    assert entry.exercise_substituted
    assert entry.entry.exercise_id != BENCH
    assert entry.progression is None or entry.progression.decision is ProgressionDecision.NO_HISTORY


def test_one_exercise_listed_twice_is_progressed_once(db):
    """The plan is built per routine, not per entry, so a repeated movement
    cannot compound."""
    memory = memory_of(bench_session(bench_set(rpe=6.0)))
    routine = Routine(
        name="Double bench",
        entries=[
            RoutineEntry(exercise_id=BENCH, dose=RepsDose(sets=4, reps=8, weight=80.0)),
            RoutineEntry(exercise_id=BENCH, dose=RepsDose(sets=3, reps=8, weight=80.0)),
        ],
    )
    varied = vary_routine(routine, db, memory=memory, seed=3, substitution_prob=0.0)

    loads = [
        v.progression.working_load_kg for v in varied.entry_variations if v.progression is not None
    ]
    assert len(loads) == 2
    assert loads == pytest.approx([102.5, 102.5])


# --- Composing with the adaptive tier --------------------------------------


def test_strain_still_scales_a_progressed_target(db):
    """Progression sets the reference; readiness and intent scale it. Both
    apply, in that order."""
    memory = memory_of(bench_session(bench_set(rpe=6.0)))
    routine = bench_routine(weight=80.0)

    plain = vary_routine(routine, db, memory=memory, seed=3, substitution_prob=0.0)
    light = vary_routine(
        routine,
        db,
        memory=memory,
        context=VariationContext(session_intent=SessionIntent.LIGHT),
        seed=3,
        substitution_prob=0.0,
    )
    assert light.routine.total_volume < plain.routine.total_volume


def test_readiness_is_named_ahead_of_progression_in_the_outcome(db):
    """Both moved the target. Being backed off for strain is the
    safety-relevant fact, so it wins the single per-entry label -- the full
    breakdown stays on the entry's `progression`."""
    from hibrid.user.biometrics import WellnessCheckIn

    memory = memory_of(bench_session(bench_set(rpe=6.0)))
    context = VariationContext.from_parts(
        wellness=(
            WellnessCheckIn(
                user_id=USER_ID, recorded_at=NOW - timedelta(hours=4), illness_reported=True
            ),
        ),
        as_of=NOW,
    )
    varied = vary_routine(
        bench_routine(), db, memory=memory, context=context, seed=3, substitution_prob=0.0
    )
    entry = varied.entry_variations[0]

    assert entry.dose_outcome is DoseOutcome.VARIED_FOR_STRAIN
    assert entry.progression is not None
    assert entry.progression.decision is ProgressionDecision.PROGRESSED


def test_progression_is_named_ahead_of_session_intent(db):
    """Progression changed the programme; intent only changed today."""
    memory = memory_of(bench_session(bench_set(rpe=6.0)))
    varied = vary_routine(
        bench_routine(),
        db,
        memory=memory,
        context=VariationContext(session_intent=SessionIntent.CHALLENGING),
        seed=3,
        substitution_prob=0.0,
    )
    assert varied.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_PROGRESSION
