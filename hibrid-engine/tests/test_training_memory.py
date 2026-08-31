"""M8a: the engine finally reads what the user actually did.

The claims worth defending here are mostly about *refusing* to produce a
number -- an invented 1RM is worse than an absent one, because everything
downstream would treat it as measured.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hibrid.training_memory import (
    MAX_ESTIMABLE_REPS,
    OneRepMaxFormula,
    TrainingMemory,
)
from hibrid.user.enums import SessionStatus, UnitSystem
from hibrid.user.history import PerformedExercise, PerformedSet, TrainingSession
from hibrid.user.profile import UserProfile
from hibrid.user.user import User

USER_ID = uuid4()
NOW = datetime(2026, 8, 9, 7, 0, tzinfo=timezone.utc)
BENCH = "barbell-bench-press"


def performed_set(
    reps: int | None = 5,
    load: float | None = 100.0,
    *,
    index: int = 0,
    rpe: float | None = None,
    warmup: bool = False,
    exercise_id: str = BENCH,
) -> PerformedSet:
    return PerformedSet(
        exercise_id=exercise_id,
        set_index=index,
        reps_completed=reps,
        load_kg=load,
        rpe=rpe,
        is_warmup=warmup,
    )


def session(
    *sets: PerformedSet,
    days_ago: float = 1,
    status: SessionStatus = SessionStatus.COMPLETED,
    exercise_id: str = BENCH,
) -> TrainingSession:
    return TrainingSession(
        user_id=USER_ID,
        performed_at=NOW - timedelta(days=days_ago),
        status=status,
        exercises=(PerformedExercise(exercise_id=exercise_id, order_index=0, sets=sets),),
    )


def memory(*sessions: TrainingSession, **kwargs: object) -> TrainingMemory:
    return TrainingMemory.from_sessions(sessions, user_id=USER_ID, as_of=NOW, **kwargs)


# --- The estimator ---------------------------------------------------------


def test_a_completed_single_is_not_estimated_at_all():
    """A completed single IS a one-rep max -- there is nothing to estimate.

    Pinned because Epley does not do this naturally: w x (1 + 1/30) reports
    103.3 kg for a genuinely measured 100 kg single, a 3.3% overstatement that
    would propagate into every load solved from it. Brzycki happens to be exact
    here, so without the special case correctness would depend on which formula
    the caller picked."""
    for formula in OneRepMaxFormula:
        assert formula.estimate(100.0, 1) == pytest.approx(100.0)


def test_epley_and_brzycki_disagree_on_the_same_set():
    """The reason the schema records which estimator produced a number: a bare
    kilogram figure is uninterpretable without it."""
    epley = OneRepMaxFormula.EPLEY.estimate(100.0, 8)
    brzycki = OneRepMaxFormula.BRZYCKI.estimate(100.0, 8)
    assert epley is not None and brzycki is not None
    assert epley != brzycki


def test_no_estimate_beyond_the_validated_rep_range():
    """A 20-rep set says far more about endurance than maximal strength, and
    both formulas are extrapolating well past their fit by then."""
    assert OneRepMaxFormula.EPLEY.estimate(100.0, MAX_ESTIMABLE_REPS) is not None
    assert OneRepMaxFormula.EPLEY.estimate(100.0, MAX_ESTIMABLE_REPS + 1) is None
    assert OneRepMaxFormula.BRZYCKI.estimate(100.0, 20) is None


def test_no_estimate_from_an_unloaded_set():
    """A bodyweight set has no external load to extrapolate from. Returning 0
    would read downstream as 'this user can lift nothing'."""
    assert OneRepMaxFormula.EPLEY.estimate(0.0, 5) is None


def test_no_estimate_from_a_zero_rep_set():
    assert OneRepMaxFormula.EPLEY.estimate(100.0, 0) is None


# --- Building records ------------------------------------------------------


def test_the_best_estimate_wins_not_the_heaviest_set():
    """5x100 estimates higher than 1x110 under Epley. Taking the heaviest load
    would understate a user who trains in moderate rep ranges."""
    result = memory(session(performed_set(reps=1, load=110.0), performed_set(reps=5, load=100.0, index=1)))
    record = result.record_for(BENCH)

    assert record is not None
    assert (record.best_set_reps, record.best_set_load_kg) == (5, 100.0)
    assert record.estimated_one_rep_max_kg == pytest.approx(100.0 * (1 + 5 / 30))


def test_the_formula_always_travels_with_the_estimate():
    record = memory(session(performed_set())).record_for(BENCH)
    assert record is not None
    assert record.estimated_one_rep_max_kg is not None
    assert record.one_rep_max_formula == OneRepMaxFormula.EPLEY.value


def test_no_estimate_leaves_no_orphan_formula_name():
    """A formula attached to no value is as uninterpretable as the reverse."""
    record = memory(session(performed_set(reps=30, load=40.0))).record_for(BENCH)
    assert record is not None
    assert record.estimated_one_rep_max_kg is None
    assert record.one_rep_max_formula is None


def test_choosing_brzycki_changes_the_number_and_says_so():
    result = memory(session(performed_set(reps=8)), formula=OneRepMaxFormula.BRZYCKI)
    record = result.record_for(BENCH)
    assert record is not None
    assert record.one_rep_max_formula == "brzycki"
    assert record.estimated_one_rep_max_kg == pytest.approx(100.0 * 36 / 29)


def test_warmups_do_not_count():
    """A 20kg warm-up is not evidence of anything, and counting it in volume or
    set totals would inflate both."""
    record = memory(
        session(performed_set(load=20.0, warmup=True), performed_set(load=100.0, index=1))
    ).record_for(BENCH)

    assert record is not None
    assert record.total_working_sets == 1
    assert record.volume_load_last_7d_kg == pytest.approx(500.0)


def test_skipped_and_aborted_sessions_are_not_evidence_of_strength():
    """They stay in history as the adherence signal -- which is exactly why
    they must not silently become performance data too."""
    for status in (SessionStatus.SKIPPED, SessionStatus.ABORTED):
        assert BENCH not in memory(session(performed_set(), status=status))


def test_sessions_after_the_planning_moment_are_not_read():
    """Explaining a prescription with work done after it is target leakage."""
    assert BENCH not in memory(session(performed_set(), days_ago=-1))


def test_records_are_keyed_on_what_was_done_not_what_was_prescribed():
    """A user who swapped in a dumbbell press produced evidence about the
    dumbbell press."""
    swapped = TrainingSession(
        user_id=USER_ID,
        performed_at=NOW - timedelta(days=1),
        exercises=(
            PerformedExercise(
                exercise_id="dumbbell-bench-press",
                order_index=0,
                sets=(performed_set(exercise_id="dumbbell-bench-press"),),
                substituted_from_exercise_id=BENCH,
            ),
        ),
    )
    result = TrainingMemory.from_sessions((swapped,), user_id=USER_ID, as_of=NOW)
    assert "dumbbell-bench-press" in result
    assert BENCH not in result


# --- Rolling windows -------------------------------------------------------


def test_volume_windows_are_measured_back_from_as_of():
    result = memory(
        session(performed_set(reps=10, load=100.0), days_ago=2),
        session(performed_set(reps=10, load=100.0), days_ago=20),
        session(performed_set(reps=10, load=100.0), days_ago=40),
    )
    record = result.record_for(BENCH)

    assert record is not None
    assert record.volume_load_last_7d_kg == pytest.approx(1000.0)
    assert record.volume_load_last_28d_kg == pytest.approx(2000.0)
    assert record.total_working_sets == 3, "the 40-day-old set is still history"


def test_sessions_are_counted_once_however_many_sets_they_hold():
    result = memory(
        session(performed_set(), performed_set(index=1), performed_set(index=2)),
        session(performed_set(), days_ago=3),
    )
    record = result.record_for(BENCH)
    assert record is not None
    assert record.total_sessions == 2
    assert record.total_working_sets == 4


def test_average_rpe_ignores_sets_that_did_not_report_one():
    record = memory(
        session(performed_set(rpe=8.0), performed_set(rpe=10.0, index=1), performed_set(index=2))
    ).record_for(BENCH)
    assert record is not None
    assert record.average_rpe == pytest.approx(9.0)


def test_the_best_estimate_date_is_when_it_was_first_achieved():
    """Repeating an old best is not the day the user got stronger."""
    result = memory(
        session(performed_set(reps=5, load=100.0), days_ago=30),
        session(performed_set(reps=5, load=100.0), days_ago=1),
    )
    record = result.record_for(BENCH)
    assert record is not None
    assert record.best_estimated_1rm_date == NOW - timedelta(days=30)


# --- Absence, and the User path -------------------------------------------


def test_never_performed_is_none_rather_than_zero():
    """A never-attempted lift and a badly-performed one need different
    starting-load decisions, so they must not collapse to the same value."""
    result = memory()
    assert result.record_for(BENCH) is None
    assert result.estimated_one_rep_max(BENCH) is None
    assert BENCH not in result


def test_a_bodyweight_history_yields_a_record_but_no_estimate():
    """The record still carries real volume and exposure counts -- only the
    1RM is unknowable."""
    record = memory(session(performed_set(reps=20, load=0.0))).record_for(BENCH)
    assert record is not None
    assert record.estimated_one_rep_max_kg is None
    assert record.total_working_sets == 1


def test_naive_timestamps_do_not_crash_the_walk():
    """Same rule as readiness: an import that arrives without a timezone must
    not raise from inside a comparison."""
    naive = TrainingSession(
        user_id=USER_ID,
        performed_at=(NOW - timedelta(days=1)).replace(tzinfo=None),
        exercises=(PerformedExercise(exercise_id=BENCH, order_index=0, sets=(performed_set(),)),),
    )
    assert BENCH in TrainingMemory.from_sessions((naive,), user_id=USER_ID, as_of=NOW)


def test_from_user_recomputes_rather_than_trusting_the_cached_records():
    """`User.exercise_records` is a cache of this computation. Reading it back
    would make "the session log is the source of truth" a comment rather than
    a behaviour."""
    user = User(
        profile=UserProfile(
            display_name="Test",
            unit_system=UnitSystem.METRIC,
            user_id=USER_ID,
            birth_date=date(1990, 5, 1),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        sessions=(session(performed_set(reps=5, load=100.0)),),
    )
    # The aggregate carries no cached records at all; the memory is built anyway.
    assert user.exercise_records == {}
    record = TrainingMemory.from_user(user, as_of=NOW).record_for(BENCH)
    assert record is not None
    assert record.user_id == user.user_id
    assert record.estimated_one_rep_max_kg == pytest.approx(100.0 * (1 + 5 / 30))


def test_rebuilt_records_satisfy_the_aggregate_they_are_stored_on():
    """The output has to be loadable back into `User.exercise_records`, which
    validates ownership and key-matching."""
    built = memory(session(performed_set()))
    user = User(
        profile=UserProfile(
            display_name="Test",
            unit_system=UnitSystem.METRIC,
            user_id=USER_ID,
            birth_date=date(1990, 5, 1),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        exercise_records=built.records,
    )
    assert user.exercise_records[BENCH].exercise_id == BENCH
