"""M8c: the block, not the session.

Two claims under test. First, that a week's training is judged against this
user's own previous four weeks -- and that the engine refuses to judge at all
when the comparison would be dishonest, which is where the acute:chronic ratio
is most often misused. Second, that a dated event pulls volume down as it
approaches without shortening the sessions.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.load_management import (
    MIN_CHRONIC_SESSIONS,
    PEAK_VOLUME_FRACTION,
    TAPER_WINDOW_DAYS,
    LoadManagementAssessment,
    LoadMetric,
    TaperPlan,
    WorkloadState,
    next_target_event,
)
from hibrid.models import RepsDose, Routine, RoutineEntry
from hibrid.readiness import ReadinessState
from hibrid.user.biometrics import RecoveryReading
from hibrid.user.enums import SessionStatus, TrainingObjective
from hibrid.user.history import PerformedExercise, PerformedSet, TrainingSession
from hibrid.user.objectives import ObjectiveWeights, TargetEvent, TrainingGoal
from hibrid.user.profile import UserProfile
from hibrid.user.user import User
from hibrid.variation import DoseOutcome, pct_diff, vary_routine
from hibrid.variation_context import SessionIntent, VariationContext

USER_ID = uuid4()
NOW = datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc)
BENCH = "barbell-bench-press"

#: One steady session's worth of sRPE load: RPE 7 for 60 minutes.
SESSION_LOAD = 7.0 * 60.0

#: Three sessions a week, spaced evenly. The spacing matters: at exactly
#: 7/3 days apart the acute window holds three sessions and the four-week
#: window holds twelve, so a steady trainee lands on a ratio of exactly 1.0
#: and any deviation in these tests is the thing being tested.
STEADY_SPACING_DAYS = 7 / 3


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


def session(
    days_ago: float,
    *,
    rpe: float | None = 7.0,
    minutes: float | None = 60.0,
    status: SessionStatus = SessionStatus.COMPLETED,
    reps: int | None = None,
    load: float | None = None,
) -> TrainingSession:
    """One logged session, sRPE by default and volume-load on request."""
    exercises: tuple[PerformedExercise, ...] = ()
    if reps is not None and load is not None:
        exercises = (
            PerformedExercise(
                exercise_id=BENCH,
                order_index=0,
                sets=(
                    PerformedSet(exercise_id=BENCH, set_index=i, reps_completed=reps, load_kg=load)
                    for i in range(3)
                ),
            ),
        )
    return TrainingSession(
        user_id=USER_ID,
        performed_at=NOW - timedelta(days=days_ago),
        status=status,
        session_rpe=rpe,
        duration_seconds=minutes * 60.0 if minutes is not None else None,
        exercises=exercises,
    )


def steady_log(weeks: int = 6, **kwargs: object) -> list[TrainingSession]:
    """Three sessions a week for ``weeks`` weeks, ending yesterday."""
    return [
        session(1 + index * STEADY_SPACING_DAYS, **kwargs)  # type: ignore[arg-type]
        for index in range(weeks * 3)
    ]


def assess(
    sessions: list[TrainingSession],
    *,
    event: TargetEvent | None = None,
    metric: LoadMetric = LoadMetric.SESSION_RPE,
) -> LoadManagementAssessment:
    return LoadManagementAssessment.from_sessions(
        sessions, as_of=NOW, event=event, metric=metric
    )


def event_in(days: int, *, name: str = "Regional meet", importance: int = 8) -> TargetEvent:
    return TargetEvent(
        name=name, event_date=NOW.date() + timedelta(days=days), importance=importance
    )


def profile() -> UserProfile:
    return UserProfile(
        user_id=USER_ID,
        display_name="Test",
        birth_date=date(1990, 5, 1),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def bench_routine() -> Routine:
    return Routine(
        name="Bench day",
        entries=[RoutineEntry(exercise_id=BENCH, dose=RepsDose(sets=4, reps=8, weight=80.0))],
    )


# --- The ratio itself ------------------------------------------------------


def test_steady_training_sits_at_a_ratio_of_one():
    """The whole scale depends on this. If a steady trainee did not land near
    1.0, every threshold below would be a private invention rather than the
    published one."""
    workload = assess(steady_log()).workload

    assert workload is not None
    assert workload.acute_chronic_ratio == pytest.approx(1.0)
    assert workload.state is WorkloadState.OPTIMAL
    assert workload.load_multiplier == 1.0


def test_the_chronic_load_is_a_weekly_average_not_a_four_week_total():
    """The field is named ``chronic_load_28d`` and holds a weekly figure, which
    is exactly the sort of thing that gets 'corrected' by a later reader. It is
    normalised so the ratio means what the literature means by it; a raw total
    would put steady training at 0.25."""
    summary = assess(steady_log()).workload.summary

    assert summary is not None
    assert summary.acute_load_7d == pytest.approx(3 * SESSION_LOAD)
    assert summary.chronic_load_28d == pytest.approx(3 * SESSION_LOAD)
    # The raw four-week total, for contrast -- four times what is stored.
    assert summary.chronic_load_28d * 4 == pytest.approx(12 * SESSION_LOAD)


def test_a_doubled_week_is_a_spike_and_backs_the_dose_off():
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    workload = assess(doubled).workload

    assert workload is not None
    assert workload.acute_chronic_ratio is not None and workload.acute_chronic_ratio >= 1.5
    assert workload.state is WorkloadState.SPIKE
    assert workload.load_multiplier == 0.75


def test_a_moderately_heavy_week_is_elevated_rather_than_a_spike():
    """Two tiers, so the response is proportionate. A week 40% up on the
    average is not the same event as a week 100% up on it."""
    heavier = steady_log() + [session(days) for days in (0.5, 2.5)]
    workload = assess(heavier).workload

    assert workload is not None
    assert workload.state is WorkloadState.ELEVATED
    assert workload.load_multiplier == 0.90


def test_an_easy_week_is_reported_but_never_adds_work():
    """The asymmetry the whole design rests on. Being *under* the average is a
    reason to progress, which M8b already does one increment at a time against
    measured effort -- adding a second upward push here would double-count it."""
    rested = [s for s in steady_log() if s.performed_at < NOW - timedelta(days=7)]
    workload = assess(rested).workload

    assert workload is not None
    assert workload.state is WorkloadState.UNDERLOADED
    assert workload.load_multiplier == 1.0


# --- Refusing to judge -----------------------------------------------------


def test_a_log_that_does_not_reach_back_four_weeks_is_unknown_not_a_spike():
    """The standard criticism of this ratio, and the reason it is guarded. A
    two-week-old log has an artificially small four-week average, so an
    entirely ordinary week reads as a spike -- for a reason that has nothing to
    do with this user."""
    new_user = [session(1 + index * STEADY_SPACING_DAYS) for index in range(9)]
    workload = assess(new_user).workload

    assert workload is not None
    assert workload.state is WorkloadState.UNKNOWN
    assert workload.load_multiplier == 1.0


def test_returning_from_a_layoff_is_unknown_rather_than_an_infinite_spike():
    """Someone whose four-week window is nearly empty is not overreaching by
    training this week; there is simply nothing to compare against."""
    returning = [session(200 + index * 3) for index in range(20)] + [
        session(days) for days in (1, 3, 5)
    ]
    workload = assess(returning).workload

    assert workload is not None
    assert workload.state is WorkloadState.UNKNOWN


def test_too_few_sessions_in_the_window_is_unknown():
    sparse = [session(1 + index * 8) for index in range(MIN_CHRONIC_SESSIONS - 1)]
    workload = assess(sparse).workload

    assert workload is not None
    assert workload.state is WorkloadState.UNKNOWN


def test_unknown_is_not_optimal():
    """"We did not look" and "we looked and it was fine" must not read the
    same, exactly as ``ReadinessState.UNKNOWN`` is not ``NORMAL``. Both leave
    the dose alone; only one of them is a judgement."""
    assert WorkloadState.UNKNOWN is not WorkloadState.OPTIMAL
    assert WorkloadState.UNKNOWN.load_multiplier == WorkloadState.OPTIMAL.load_multiplier
    assert "NOT the same" in WorkloadState.UNKNOWN.reason


def test_no_sessions_at_all_yields_no_workload_assessment():
    assert assess([]).workload is None
    assert assess([]).load_multiplier == 1.0


# --- The metric ------------------------------------------------------------


def test_the_two_metrics_never_fall_back_to_each_other():
    """A ratio built from a mix of sRPE and kilograms is meaningless rather
    than approximate, so a log the chosen metric cannot read yields no
    assessment instead of a silently substituted one."""
    volume_only = steady_log(rpe=None, minutes=None, reps=8, load=100.0)

    assert assess(volume_only, metric=LoadMetric.SESSION_RPE).workload.state is WorkloadState.UNKNOWN
    assert assess(volume_only, metric=LoadMetric.VOLUME_LOAD).workload.state is WorkloadState.OPTIMAL


def test_a_skipped_session_carries_no_load_but_still_counts_against_adherence():
    log = steady_log()
    log[0] = session(1, status=SessionStatus.SKIPPED)
    summary = assess(log).workload.summary

    assert summary is not None
    assert summary.acute_load_7d == pytest.approx(2 * SESSION_LOAD)
    assert summary.sessions_prescribed == 12
    assert summary.sessions_completed == 11


def test_an_aborted_session_still_cost_the_body_something():
    """Deliberately diverging from M8a's ``PERFORMED_STATUSES``: an abandoned
    session is not evidence about what the user can lift, but the work done
    before abandoning it still accumulated."""
    log = steady_log()
    log[0] = session(1, status=SessionStatus.ABORTED)
    summary = assess(log).workload.summary

    assert summary is not None
    assert summary.acute_load_7d == pytest.approx(3 * SESSION_LOAD)


def test_a_log_mixing_two_users_raises():
    """A blended log is the error that stays silent until someone's training
    data has been mixed with a stranger's."""
    stranger = TrainingSession(user_id=uuid4(), performed_at=NOW - timedelta(days=1))
    with pytest.raises(ValueError, match="more than one user"):
        assess(steady_log() + [stranger])


# --- The taper -------------------------------------------------------------


def test_the_taper_deepens_as_the_event_approaches():
    depths = [TaperPlan.for_event(event_in(days), as_of=NOW).load_multiplier for days in (14, 7, 0)]

    assert depths[0] == 1.0
    assert depths[1] == pytest.approx(1.0 - (1.0 - PEAK_VOLUME_FRACTION) / 2)
    assert depths[2] == pytest.approx(PEAK_VOLUME_FRACTION)
    assert depths == sorted(depths, reverse=True)


def test_an_event_outside_the_window_is_reported_but_changes_nothing():
    """Silence would read as the feature being missing. Saying "your event is
    40 days away and nothing was changed for it" does not."""
    plan = TaperPlan.for_event(event_in(TAPER_WINDOW_DAYS + 26), as_of=NOW)

    assert plan.load_multiplier == 1.0
    assert not plan.is_tapering
    assert "outside" in plan.describe()


def test_a_past_event_changes_nothing():
    """What to do after a race depends on how it went, which the log cannot
    say yet."""
    passed = TargetEvent(name="Last month's meet", event_date=NOW.date() - timedelta(days=3))
    plan = TaperPlan.for_event(passed, as_of=NOW)

    assert plan.load_multiplier == 1.0
    assert plan.days_until_event == -3


def test_the_nearest_upcoming_event_wins_and_past_ones_are_ignored():
    user = User(
        profile=profile(),
        goals=(
            goal_for(TargetEvent(name="Old race", event_date=NOW.date() - timedelta(days=10))),
            goal_for(event_in(60, name="Nationals")),
            goal_for(event_in(9, name="Regionals")),
        ),
    )

    chosen = next_target_event(user, as_of=NOW)

    assert chosen is not None and chosen.name == "Regionals"


def goal_for(event: TargetEvent) -> TrainingGoal:
    return TrainingGoal(
        objectives=ObjectiveWeights.normalised({TrainingObjective.STRENGTH: 1.0}),
        target_event=event,
    )


# --- Composition -----------------------------------------------------------


def test_a_taper_and_a_spike_take_the_deeper_cut_rather_than_compounding():
    """0.55 x 0.75 is 0.41 -- a session neither input asked for and no coach
    would write."""
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    assessment = assess(doubled, event=event_in(0))

    assert assessment.workload is not None and assessment.workload.load_multiplier == 0.75
    assert assessment.load_multiplier == pytest.approx(PEAK_VOLUME_FRACTION)
    assert assessment.binding_taper
    # The term that did not bind is still visible.
    assert "spike" in assessment.explain() or "far ahead" in assessment.explain()


def test_readiness_and_load_management_multiply_across_modules():
    """Different time scales, both real: how this body woke up, and what the
    last four weeks already cost it. A user who is both acutely wrecked and
    chronically overloaded has earned both reductions."""
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    context = VariationContext.from_parts(
        recovery=suppressed_recovery(), sessions=doubled, as_of=NOW
    )

    assert context.readiness is not None
    assert context.readiness.state is ReadinessState.SUPPRESSED
    assert context.load_multiplier == pytest.approx(0.90 * 0.75)


def test_a_hard_session_asked_for_during_a_taper_is_capped_at_baseline():
    """The invisible case, arriving by M8c's route: challenging (1.15) against
    an elevated workload (0.90) composes to 1.035, handing more work than
    normal to someone the tier exists to hold back."""
    heavier = steady_log() + [session(days) for days in (0.5, 2.5)]
    context = VariationContext.from_parts(
        sessions=heavier, as_of=NOW, session_intent=SessionIntent.CHALLENGING
    )

    assert context.load_multiplier == 1.0

    variation = vary_routine(bench_routine(), ExerciseDB.load(), context=context, seed=3)
    assert variation.intent_capped_by_load_management
    assert not variation.intent_capped_by_readiness


def test_the_ordering_of_the_users_answer_survives_the_cap():
    heavier = steady_log() + [session(days) for days in (0.5, 2.5)]
    multipliers = [
        VariationContext.from_parts(
            sessions=heavier, as_of=NOW, session_intent=intent
        ).load_multiplier
        for intent in (SessionIntent.LIGHT, SessionIntent.MODERATE, SessionIntent.CHALLENGING)
    ]

    assert multipliers == sorted(multipliers)
    assert multipliers[0] < multipliers[-1]


def suppressed_recovery() -> list[RecoveryReading]:
    """A fortnight of steady HRV, then a crash on the morning being planned."""
    steady = [
        RecoveryReading(
            user_id=USER_ID,
            recorded_at=NOW - timedelta(days=day + 1),
            hrv_rmssd_ms=[58.0, 62.0, 59.0, 61.0, 57.0, 63.0, 60.0, 58.0, 62.0, 61.0][day % 10],
        )
        for day in range(14)
    ]
    return steady + [
        RecoveryReading(user_id=USER_ID, recorded_at=NOW - timedelta(hours=2), hrv_rmssd_ms=38.0)
    ]


# --- The engine ------------------------------------------------------------


def test_a_workload_spike_lightens_the_session_without_shortening_it(db):
    """The M8c milestone test.

    Accumulated load is the third thing that scales *how much* work rather than
    *which* work, and like the other two it must not touch the clock: a
    session's length comes from the user's calendar, not from last week's
    tonnage."""
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    context = VariationContext.from_parts(sessions=doubled, as_of=NOW)
    routine = bench_routine()

    variation = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)

    assert variation.load_management is not None
    assert variation.load_management.workload.state is WorkloadState.SPIKE
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_LOAD_MANAGEMENT
    assert variation.routine.total_volume < routine.total_volume
    assert pct_diff(variation.routine.total_time_seconds, routine.total_time_seconds) <= 0.10


def test_a_session_backed_off_for_accumulated_load_says_so(db):
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    context = VariationContext.from_parts(sessions=doubled, as_of=NOW)

    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)

    assert "four-week average" in variation.load_management.explain()
    assert "acute:chronic" in variation.entry_variations[0].dose_outcome.reason


def test_strain_outranks_accumulated_load_in_the_headline(db):
    """Both moved the target; the per-entry outcome names one. Being backed off
    for today's strain is the safety-relevant fact, and the full breakdown is
    on the variation either way."""
    doubled = steady_log() + [session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    context = VariationContext.from_parts(
        recovery=suppressed_recovery(), sessions=doubled, as_of=NOW
    )

    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)

    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_STRAIN
    assert variation.load_management is not None
    assert variation.load_management.modulates_load


def test_a_caller_supplying_no_log_and_no_event_sees_the_original_behaviour(db):
    """Every layer that touches load has to degrade to a no-op independently."""
    context = VariationContext.from_parts(as_of=NOW)
    routine = bench_routine()

    variation = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)

    assert context.load_management is None
    assert variation.load_multiplier == 1.0
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED
    assert pct_diff(variation.routine.total_volume, routine.total_volume) <= 0.075


def test_a_steady_log_changes_nothing_either(db):
    """The state that is *not* UNKNOWN and still does nothing -- the engine
    looked, and this week was ordinary."""
    context = VariationContext.from_parts(sessions=steady_log(), as_of=NOW)

    assert context.load_management is not None
    assert context.load_management.workload.state is WorkloadState.OPTIMAL
    assert context.load_multiplier == 1.0


def test_from_user_reads_the_log_and_the_goals_together():
    user = User(
        profile=profile(),
        goals=(goal_for(event_in(7, name="Regionals")),),
        sessions=tuple(steady_log()),
    )

    context = VariationContext.from_user(user, as_of=NOW)

    assert context.load_management is not None
    assert context.load_management.taper is not None
    assert context.load_management.taper.event_name == "Regionals"
    assert context.load_management.workload.state is WorkloadState.OPTIMAL
    assert context.load_multiplier == pytest.approx(1.0 - (1.0 - PEAK_VOLUME_FRACTION) / 2)
