"""M3 pass 2: strain, read against the user's own baseline.

The single claim these tests exist to defend is that *nothing here is an
absolute threshold*. Every other property (freshness, thin baselines, the
direction of each metric) is a way that claim can quietly stop being true.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from hibrid.readiness import (
    MIN_BASELINE_READINGS,
    ReadinessAssessment,
    ReadinessFlag,
    ReadinessMetric,
    ReadinessState,
)
from hibrid.user.biometrics import RecoveryReading, WellnessCheckIn

USER_ID = uuid4()
NOW = datetime(2026, 8, 9, 7, 0, tzinfo=timezone.utc)


def recovery(days_ago: float, *, hrv: float | None = None, rhr: int | None = None) -> RecoveryReading:
    return RecoveryReading(
        user_id=USER_ID,
        recorded_at=NOW - timedelta(days=days_ago),
        hrv_rmssd_ms=hrv,
        resting_heart_rate_bpm=rhr,
    )


def wellness(days_ago: float, **fields: object) -> WellnessCheckIn:
    return WellnessCheckIn(user_id=USER_ID, recorded_at=NOW - timedelta(days=days_ago), **fields)


def hrv_baseline(values: list[float]) -> list[RecoveryReading]:
    """One reading per day going back from yesterday, newest first."""
    return [recovery(days_ago=day + 1, hrv=value) for day, value in enumerate(values)]


#: A fortnight of unremarkable HRV, mean 60, SD ~3.2.
STEADY_HRV = [58.0, 62.0, 59.0, 61.0, 57.0, 63.0, 60.0, 58.0, 62.0, 61.0, 59.0, 60.0, 64.0, 56.0]


# --- The headline: baseline-relative, never absolute ------------------------


def test_the_same_reading_is_suppressed_for_one_user_and_normal_for_another():
    """The claim the whole module rests on, stated as a test.

    An identical 45 ms HRV is a crash for someone who normally runs at 60 and
    an ordinary Tuesday for someone who normally runs at 45. Any absolute
    threshold gets exactly one of these two people wrong."""
    high_baseline = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0), *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    low_baseline = ReadinessAssessment.assess(
        recovery=[
            recovery(days_ago=0.2, hrv=45.0),
            *hrv_baseline([value - 15.0 for value in STEADY_HRV]),
        ],
        as_of=NOW,
    )

    assert high_baseline.state is ReadinessState.SUPPRESSED
    assert high_baseline.suppressing_metrics == (ReadinessMetric.HRV_RMSSD,)
    assert low_baseline.state is ReadinessState.NORMAL
    assert low_baseline.load_multiplier == 1.0


# --- Absent, thin and stale data ------------------------------------------


def test_no_readings_is_unknown_rather_than_normal():
    assessment = ReadinessAssessment.assess(as_of=NOW)
    assert assessment.state is ReadinessState.UNKNOWN
    assert assessment.load_multiplier == 1.0
    assert not assessment.modulates_load
    assert "NOT the same as having checked" in assessment.state.reason


def test_a_baseline_too_thin_to_mean_anything_is_unknown():
    """One bad night against three prior readings is noise, not evidence."""
    thin = hrv_baseline(STEADY_HRV[: MIN_BASELINE_READINGS - 1])
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=30.0), *thin], as_of=NOW
    )
    assert assessment.state is ReadinessState.UNKNOWN
    assert assessment.comparisons == ()


def test_a_stale_reading_says_nothing_about_today():
    """A wearable last worn a week ago has no opinion about this session, even
    though it recorded a dramatic crash when it was worn."""
    older = [recovery(days_ago=8 + day, hrv=value) for day, value in enumerate(STEADY_HRV)]
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=7, hrv=30.0), *older], as_of=NOW
    )
    assert assessment.state is ReadinessState.UNKNOWN


def test_readings_after_the_planning_moment_are_not_used():
    """Explaining a past prescription with later readings is target leakage:
    tomorrow's crash must not colour today's decision."""
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=-1, hrv=20.0), *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    assert assessment.state is ReadinessState.NORMAL
    assert [c.latest for c in assessment.comparisons] == [STEADY_HRV[0]]


def test_the_latest_reading_is_excluded_from_its_own_baseline():
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0), *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    comparison = assessment.comparisons[0]
    assert comparison.sample_size == len(STEADY_HRV)
    assert comparison.latest == 45.0


def test_readings_older_than_the_window_do_not_count_toward_the_baseline():
    old = [recovery(days_ago=40 + day, hrv=value) for day, value in enumerate(STEADY_HRV)]
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0), *old], as_of=NOW
    )
    assert assessment.state is ReadinessState.UNKNOWN


# --- Direction of each metric ---------------------------------------------


def test_a_raised_resting_heart_rate_is_suppression_not_improvement():
    """The one place a sign error would silently invert the whole decision:
    HRV falling and resting heart rate rising are the same event."""
    baseline = [recovery(days_ago=day + 1, rhr=50 + (day % 3)) for day in range(14)]
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, rhr=60), *baseline], as_of=NOW
    )
    assert assessment.suppressing_metrics == (ReadinessMetric.RESTING_HEART_RATE,)


def test_more_soreness_is_suppression():
    baseline = [wellness(days_ago=day + 1, soreness=2 + (day % 3)) for day in range(14)]
    assessment = ReadinessAssessment.assess(
        wellness=[wellness(days_ago=0.2, soreness=9), *baseline], as_of=NOW
    )
    assert assessment.suppressing_metrics == (ReadinessMetric.SORENESS,)


def test_readings_better_than_baseline_never_increase_the_load():
    """Prescribing *more* work on a good day is progressive overload (M8),
    which needs training-load history this layer deliberately does not read."""
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=85.0), *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    assert assessment.state is ReadinessState.NORMAL
    assert assessment.load_multiplier == 1.0


# --- Aggregation ----------------------------------------------------------


def test_two_agreeing_signals_cut_harder_than_one():
    both = [
        recovery(days_ago=day + 1, hrv=value, rhr=50 + (day % 3))
        for day, value in enumerate(STEADY_HRV)
    ]
    one_signal = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0, rhr=51), *both], as_of=NOW
    )
    two_signals = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0, rhr=60), *both], as_of=NOW
    )
    assert one_signal.state is ReadinessState.SUPPRESSED
    assert two_signals.state is ReadinessState.STRONGLY_SUPPRESSED
    assert two_signals.load_multiplier < one_signal.load_multiplier < 1.0


def test_objective_and_subjective_signals_stay_distinguishable():
    """Both channels can fire, and which one did has to survive aggregation --
    'HRV is down' and 'they feel terrible' warrant different follow-ups."""
    subjective_baseline = [wellness(days_ago=day + 1, energy=7 + (day % 2)) for day in range(14)]
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0), *hrv_baseline(STEADY_HRV)],
        wellness=[wellness(days_ago=0.2, energy=2), *subjective_baseline],
        as_of=NOW,
    )
    fired = assessment.suppressing_metrics
    assert {metric.is_objective for metric in fired} == {True, False}
    assert assessment.state is ReadinessState.STRONGLY_SUPPRESSED


def test_illness_needs_no_baseline_to_count():
    """Illness is not a z-score -- a user has no normal amount of fever to
    deviate from, so the flag stands on its own with no history at all."""
    assessment = ReadinessAssessment.assess(
        wellness=[wellness(days_ago=0.2, illness_reported=True)], as_of=NOW
    )
    assert assessment.state is ReadinessState.STRONGLY_SUPPRESSED
    assert assessment.flags == frozenset({ReadinessFlag.ILLNESS_REPORTED})
    assert "illness_reported" in assessment.explain()


def test_an_old_illness_report_does_not_still_bind():
    assessment = ReadinessAssessment.assess(
        wellness=[wellness(days_ago=10, illness_reported=True)], as_of=NOW
    )
    assert assessment.state is ReadinessState.UNKNOWN
    assert assessment.flags == frozenset()


# --- Deliberate exclusions ------------------------------------------------


def test_the_vendor_readiness_score_is_not_read():
    """Pinned because it is the tempting shortcut: it is an opaque function of
    the same HRV and heart-rate inputs already read, so counting it too would
    double-weight one piece of physiology."""
    crashed_vendor_score = RecoveryReading(
        user_id=USER_ID,
        recorded_at=NOW - timedelta(hours=5),
        hrv_rmssd_ms=60.0,
        readiness_score=3.0,
        strain_score=99.0,
    )
    assessment = ReadinessAssessment.assess(
        recovery=[crashed_vendor_score, *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    assert assessment.state is ReadinessState.NORMAL


def test_a_flat_baseline_is_not_treated_as_infinite_deviation():
    flat = [recovery(days_ago=day + 1, hrv=60.0) for day in range(14)]
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=59.0), *flat], as_of=NOW
    )
    assert assessment.state is ReadinessState.UNKNOWN


def test_naive_timestamps_are_read_as_utc_rather_than_crashing():
    """Device exports routinely arrive without a timezone, and one naive record
    in an otherwise-aware history must not raise from inside the maths."""
    naive = RecoveryReading(
        user_id=USER_ID, recorded_at=(NOW - timedelta(hours=6)).replace(tzinfo=None), hrv_rmssd_ms=45.0
    )
    assessment = ReadinessAssessment.assess(
        recovery=[naive, *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    assert assessment.state is ReadinessState.SUPPRESSED


def test_the_explanation_names_the_evidence():
    assessment = ReadinessAssessment.assess(
        recovery=[recovery(days_ago=0.2, hrv=45.0), *hrv_baseline(STEADY_HRV)], as_of=NOW
    )
    explanation = assessment.explain()
    assert "hrv_rmssd" in explanation
    assert "45.0" in explanation
    assert "baseline of 60" in explanation
