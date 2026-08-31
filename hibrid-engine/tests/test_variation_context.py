"""M3: the user schema finally constrains the engine.

Pass 1 is the three filtering tiers (inviolable / hard / soft). Pass 2 is the
adaptive tier -- today's strain, which changes how much work the permitted
exercises carry rather than which exercises those are.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.models import Equipment, MovementPattern, RepsDose, Routine, RoutineEntry
from hibrid.readiness import ReadinessState
from hibrid.user.biometrics import RecoveryReading, WellnessCheckIn
from hibrid.user.enums import (
    BodyRegion,
    InjuryStatus,
    TrainingEnvironment,
    UnitSystem,
)
from hibrid.user.health import HealthProfile, Injury, MedicalConsideration
from hibrid.user.preferences import EquipmentAccess, TrainingPreferences
from hibrid.user.profile import UserProfile
from hibrid.user.user import User
from hibrid.variation import DoseOutcome, ExerciseOutcome, pct_diff, vary_routine
from hibrid.variation_context import SessionIntent, VariationContext, summarise_filter

USER_ID = uuid4()
NOW = datetime(2026, 8, 9, 7, 0, tzinfo=timezone.utc)

#: A fortnight of unremarkable HRV for one person: mean 60, SD ~3.2.
STEADY_HRV = [58.0, 62.0, 59.0, 61.0, 57.0, 63.0, 60.0, 58.0, 62.0, 61.0, 59.0, 60.0, 64.0, 56.0]


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


def shoulder_injury() -> Injury:
    """An active shoulder injury contraindicating overhead pressing."""
    return Injury(
        body_region=BodyRegion.SHOULDER,
        status=InjuryStatus.ACTIVE,
        severity=6,
        contraindicated_movement_patterns=frozenset({MovementPattern.VERTICAL_PUSH}),
    )


def dumbbells_only() -> TrainingPreferences:
    return TrainingPreferences(
        equipment_access=(
            EquipmentAccess(
                environment=TrainingEnvironment.HOME_GYM,
                available_equipment=frozenset({Equipment.DUMBBELL}),
                is_default=True,
            ),
        )
    )


# --- The milestone test ----------------------------------------------------


def test_shoulder_injury_and_dumbbells_only_never_yields_an_overhead_barbell_press(db):
    """The roadmap's M3 milestone test, stated literally.

    The input routine deliberately prescribes exactly what this user must not
    receive: a barbell overhead press. Both tiers have to bind at once -- the
    injury rules out the movement pattern, the equipment rules out the barbell.
    """
    context = VariationContext.from_parts(
        health=HealthProfile(injuries=(shoulder_injury(),)), preferences=dumbbells_only()
    )
    routine = Routine(
        name="Overhead day",
        entries=[
            RoutineEntry(
                exercise_id="barbell-overhead-press",
                dose=RepsDose(sets=4, reps=8, weight=50),
            )
        ],
    )

    for seed in range(20):
        variation = vary_routine(routine, db, context=context, seed=seed)
        prescribed = db[variation.routine.entries[0].exercise_id]
        assert prescribed.movement_pattern is not MovementPattern.VERTICAL_PUSH
        assert prescribed.equipment is Equipment.DUMBBELL
        assert not variation.entry_variations[0].is_unsafe


def test_the_same_routine_is_left_alone_without_a_context(db):
    """Control for the test above: absent a context, nothing forces the swap.
    Otherwise the milestone test could pass for the wrong reason."""
    routine = Routine(
        name="Overhead day",
        entries=[
            RoutineEntry(
                exercise_id="barbell-overhead-press",
                dose=RepsDose(sets=4, reps=8, weight=50),
            )
        ],
    )
    variation = vary_routine(routine, db, seed=1, substitution_prob=0.0)
    assert variation.routine.entries[0].exercise_id == "barbell-overhead-press"
    assert variation.entry_variations[0].exercise_outcome is ExerciseOutcome.KEPT


# --- Inviolable tier -------------------------------------------------------


def test_a_blocked_exercise_is_replaced_even_with_substitution_disabled(db):
    """Safety is not subject to the novelty dial."""
    context = VariationContext(blocked_exercise_ids=frozenset({"barbell-bench-press"}))
    routine = Routine(
        name="Bench",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )
    variation = vary_routine(routine, db, context=context, seed=1, substitution_prob=0.0)
    assert variation.routine.entries[0].exercise_id != "barbell-bench-press"
    assert variation.entry_variations[0].exercise_outcome is ExerciseOutcome.SUBSTITUTED_FOR_CONSTRAINT


def test_blocked_movement_pattern_is_never_prescribed(db):
    context = VariationContext(
        blocked_movement_patterns=frozenset({MovementPattern.HORIZONTAL_PUSH})
    )
    routine = Routine(
        name="Bench",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )
    for seed in range(10):
        variation = vary_routine(routine, db, context=context, seed=seed)
        chosen = db[variation.routine.entries[0].exercise_id]
        assert chosen.movement_pattern is not MovementPattern.HORIZONTAL_PUSH


def test_impossible_constraints_are_reported_not_silently_satisfied(db):
    """When nothing legal exists the contraindicated exercise stays in the
    output -- variation cannot drop an entry -- but it must say so loudly."""
    context = VariationContext(available_equipment=frozenset())
    routine = Routine(
        name="Bench",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )
    variation = vary_routine(routine, db, context=context, seed=1)
    entry_variation = variation.entry_variations[0]
    assert entry_variation.exercise_outcome is ExerciseOutcome.BLOCKED_NO_LEGAL_ALTERNATIVE
    assert entry_variation.is_unsafe
    assert "must not be prescribed" in entry_variation.exercise_outcome.reason


def test_resolved_injuries_do_not_constrain(db):
    """Prior injury is kept in the schema for risk modelling, but a resolved
    injury must not still be blocking movements."""
    resolved = Injury(
        body_region=BodyRegion.SHOULDER,
        status=InjuryStatus.RESOLVED,
        resolved_date=date(2025, 1, 1),
        contraindicated_movement_patterns=frozenset({MovementPattern.VERTICAL_PUSH}),
    )
    context = VariationContext.from_parts(health=HealthProfile(injuries=(resolved,)))
    assert context.blocked_movement_patterns == frozenset()


def test_inactive_medical_considerations_do_not_constrain(db):
    inactive = MedicalConsideration(
        condition="historical hypertension",
        is_active=False,
        contraindicated_movement_patterns=frozenset({MovementPattern.SQUAT}),
    )
    context = VariationContext.from_parts(
        health=HealthProfile(medical_considerations=(inactive,))
    )
    assert context.blocked_movement_patterns == frozenset()


# --- Hard tier -------------------------------------------------------------


def test_only_available_equipment_is_prescribed(db):
    context = VariationContext.from_parts(preferences=dumbbells_only())
    routine = Routine(
        name="Bench",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )
    for seed in range(10):
        variation = vary_routine(routine, db, context=context, seed=seed)
        assert db[variation.routine.entries[0].exercise_id].equipment is Equipment.DUMBBELL


def test_unknown_environment_denies_equipment_rather_than_falling_back(db):
    """Naming an environment the user has no record for must not quietly hand
    back their home-gym inventory."""
    context = VariationContext.from_parts(
        preferences=dumbbells_only(), environment=TrainingEnvironment.HOTEL_GYM
    )
    assert context.available_equipment == frozenset()


def test_named_environment_selects_its_own_inventory(db):
    preferences = TrainingPreferences(
        equipment_access=(
            EquipmentAccess(
                environment=TrainingEnvironment.HOME_GYM,
                available_equipment=frozenset({Equipment.DUMBBELL}),
                is_default=True,
            ),
            EquipmentAccess(
                environment=TrainingEnvironment.COMMERCIAL_GYM,
                available_equipment=frozenset({Equipment.BARBELL, Equipment.CABLE}),
            ),
        )
    )
    context = VariationContext.from_parts(
        preferences=preferences, environment=TrainingEnvironment.COMMERCIAL_GYM
    )
    assert context.available_equipment == frozenset({Equipment.BARBELL, Equipment.CABLE})


def test_max_load_caps_the_solved_weight(db):
    """A 20kg dumbbell rack cannot deliver a volume-preserving 60kg solution."""
    preferences = TrainingPreferences(
        equipment_access=(
            EquipmentAccess(
                environment=TrainingEnvironment.HOME_GYM,
                available_equipment=frozenset({Equipment.DUMBBELL}),
                max_load_kg=20.0,
                is_default=True,
            ),
        )
    )
    context = VariationContext.from_parts(preferences=preferences)
    routine = Routine(
        name="Heavy",
        entries=[
            RoutineEntry(
                exercise_id="dumbbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=60)
            )
        ],
    )
    variation = vary_routine(routine, db, context=context, seed=1, substitution_prob=0.0)
    entry_variation = variation.entry_variations[0]
    assert entry_variation.dose_outcome is DoseOutcome.UNVARIED_LOAD_EXCEEDS_EQUIPMENT
    assert entry_variation.entry.dose == routine.entries[0].dose


def test_hard_exclusions_from_preferences_are_enforced(db):
    context = VariationContext.from_parts(
        preferences=TrainingPreferences(
            excluded_movement_patterns=frozenset({MovementPattern.HORIZONTAL_PUSH})
        )
    )
    exercise = db["barbell-bench-press"]
    assert not context.permits(exercise)


# --- Soft tier -------------------------------------------------------------


def test_a_dislike_is_a_cost_not_an_exclusion(db):
    """Disliked exercises stay legal -- that is the whole distinction."""
    disliked = db["barbell-bench-press"]
    context = VariationContext(disliked_exercise_ids=frozenset({disliked.id}))
    assert context.permits(disliked)
    assert context.preference_score(disliked) < 0


def test_disliked_substitutes_drop_out_of_the_tied_top_band(db):
    """The precise claim: the dislike penalty exceeds the tie band, so among
    candidates that would otherwise tie, a disliked one is no longer drawn.

    Deliberately *not* claiming a disliked exercise can never be chosen. A
    dislike is a cost, so a markedly more suitable disliked candidate can still
    outrank a mediocre liked one -- that is the design, not a leak."""
    from hibrid.variation import best_matches

    source = db["dumbbell-lateral-raise"]
    candidates = db.find_substitutes(source.id)
    tied_band = frozenset(ex.id for ex in best_matches(source, candidates))
    assert len(tied_band) > 3, "need a real tie to make this test meaningful"

    disliked_ids = frozenset(sorted(tied_band)[:3])
    context = VariationContext(disliked_exercise_ids=disliked_ids)

    routine = Routine(
        name="Raises",
        entries=[RoutineEntry(exercise_id=source.id, dose=RepsDose(sets=3, reps=12, weight=10))],
    )
    chosen = set()
    for seed in range(25):
        variation = vary_routine(routine, db, context=context, seed=seed, substitution_prob=1.0)
        chosen.add(variation.routine.entries[0].exercise_id)
    assert chosen
    assert not (chosen & disliked_ids)


def test_preferred_exercises_are_favoured(db):
    source = db["dumbbell-lateral-raise"]
    assert VariationContext(preferred_exercise_ids=frozenset({source.id})).preference_score(source) > 0


def test_novelty_preference_drives_substitution_probability(db):
    """The schema names novelty_preference as the dial substitution_prob should
    come from rather than a hard-coded constant."""
    routine = Routine(
        name="Raises",
        entries=[
            RoutineEntry(exercise_id="dumbbell-lateral-raise", dose=RepsDose(sets=3, reps=12, weight=10))
        ],
    )
    never = VariationContext.from_parts(
        preferences=TrainingPreferences(novelty_preference=0.0)
    )
    always = VariationContext.from_parts(
        preferences=TrainingPreferences(novelty_preference=1.0)
    )
    for seed in range(10):
        assert not vary_routine(routine, db, context=never, seed=seed).entry_variations[0].exercise_substituted
        assert vary_routine(routine, db, context=always, seed=seed).entry_variations[0].exercise_substituted


def test_an_explicit_substitution_prob_overrides_novelty_preference(db):
    routine = Routine(
        name="Raises",
        entries=[
            RoutineEntry(exercise_id="dumbbell-lateral-raise", dose=RepsDose(sets=3, reps=12, weight=10))
        ],
    )
    context = VariationContext.from_parts(preferences=TrainingPreferences(novelty_preference=1.0))
    variation = vary_routine(routine, db, context=context, seed=1, substitution_prob=0.0)
    assert not variation.entry_variations[0].exercise_substituted


# --- Adaptive tier: strain (pass 2) ----------------------------------------


def suppressed_recovery() -> tuple[RecoveryReading, ...]:
    """A fortnight of steady HRV, then a reading well below this user's own
    normal. The absolute values are irrelevant -- the gap is what binds."""
    baseline = [
        RecoveryReading(user_id=USER_ID, recorded_at=NOW - timedelta(days=day + 1), hrv_rmssd_ms=value)
        for day, value in enumerate(STEADY_HRV)
    ]
    latest = RecoveryReading(
        user_id=USER_ID, recorded_at=NOW - timedelta(hours=4), hrv_rmssd_ms=45.0
    )
    return (latest, *baseline)


def bench_routine() -> Routine:
    return Routine(
        name="Bench",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )


def test_suppressed_recovery_lightens_the_session_without_shortening_it(db):
    """The M3 pass 2 milestone test.

    Strain is the only tier that changes *how much* work rather than *which*
    work. Time is deliberately not scaled with it: a session's length comes
    from the user's calendar, not their HRV."""
    context = VariationContext.from_parts(recovery=suppressed_recovery(), as_of=NOW)
    routine = bench_routine()

    variation = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)
    entry_variation = variation.entry_variations[0]

    assert variation.readiness is not None
    assert variation.readiness.state is ReadinessState.SUPPRESSED
    assert entry_variation.dose_outcome is DoseOutcome.VARIED_FOR_STRAIN
    assert variation.routine.total_volume < routine.total_volume
    assert pct_diff(variation.routine.total_time_seconds, routine.total_time_seconds) <= 0.10


def test_a_routine_varied_under_strain_says_so(db):
    """A routine whose loads came back lighter with no explanation reads as a
    bug. The evidence has to travel with the result."""
    context = VariationContext.from_parts(recovery=suppressed_recovery(), as_of=NOW)
    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)

    assert variation.readiness is not None
    assert "hrv_rmssd" in variation.readiness.explain()
    assert variation.entry_variations[0].dose_outcome.is_varied
    assert "readiness" in variation.entry_variations[0].dose_outcome.reason


def test_a_deload_reaches_an_entry_the_scheme_search_will_not_touch(db):
    """An entry outside the objective's rep range yields no candidate schemes
    at all -- by design, the search does not chase the range. A deload still
    has to land on it, as the same scheme at a lighter load."""
    context = VariationContext.from_parts(recovery=suppressed_recovery(), as_of=NOW)
    routine = Routine(
        name="High rep bench",
        entries=[
            RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=30, weight=20))
        ],
    )

    unstrained = vary_routine(routine, db, seed=3, substitution_prob=0.0)
    assert unstrained.entry_variations[0].dose_outcome is DoseOutcome.UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE

    strained = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)
    varied_dose = strained.routine.entries[0].dose
    assert strained.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_STRAIN
    assert (varied_dose.sets, varied_dose.reps) == (4, 30)
    assert varied_dose.weight < 20


def test_a_strength_deload_takes_sets_away_and_leaves_the_bar_alone(db):
    """The taper shape. Expressing every adjustment as a multiplier on the
    volume target meant a tapering or deloading strength athlete got a lighter
    bar, when the entire point of both is to keep touching near-maximal loads on
    less total work.

    Under an intensity-preserving objective the multiplier still moves the
    volume target, but the load is pinned to the reference -- so the adjustment
    lands on the set and rep count instead, which is the shape a real taper
    has."""
    from hibrid.objective_strategy import StrengthStrategy

    routine = Routine(
        name="Heavy bench",
        entries=[
            RoutineEntry(
                exercise_id="barbell-bench-press",
                dose=RepsDose(sets=5, reps=5, weight=100.0, rep_seconds=2.5),
                rest_seconds=180,
            )
        ],
    )
    context = VariationContext.from_parts(session_intent=SessionIntent.LIGHT)
    assert context.load_multiplier < 1.0

    variation = vary_routine(
        routine, db, objective=StrengthStrategy(), context=context, seed=2,
        substitution_prob=0.0,
    )
    dose = variation.routine.entries[0].dose

    assert dose.weight == 100.0, "the bar must not move on a deload"
    assert dose.load_volume < routine.entries[0].dose.load_volume, "the work must"


def test_normal_readiness_leaves_the_volume_target_alone(db):
    """Control for the tests above. Readings that exist but sit inside this
    user's own normal variation must not quietly deload them."""
    steady = [
        RecoveryReading(user_id=USER_ID, recorded_at=NOW - timedelta(days=day), hrv_rmssd_ms=value)
        for day, value in enumerate(STEADY_HRV)
    ]
    context = VariationContext.from_parts(recovery=steady, as_of=NOW)
    assert context.load_multiplier == 1.0

    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)
    assert variation.readiness is not None
    assert variation.readiness.state is ReadinessState.NORMAL
    assert variation.entry_variations[0].dose_outcome is not DoseOutcome.VARIED_FOR_STRAIN


def test_a_deload_smaller_than_one_plate_is_reported_not_faked(db):
    """At 5kg with 2.5kg jumps, a 10% cut rounds straight back onto the
    prescribed weight. Reporting that as varied would be a lie about the one
    thing the outcome enum exists to make honest.

    The 30-rep scheme puts this entry outside hypertrophy's range, so the
    rounded-away deload is the only candidate there is."""
    context = VariationContext.from_parts(recovery=suppressed_recovery(), as_of=NOW)
    routine = Routine(
        name="Light raises",
        entries=[
            RoutineEntry(exercise_id="dumbbell-lateral-raise", dose=RepsDose(sets=4, reps=30, weight=5))
        ],
    )
    variation = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)
    entry_variation = variation.entry_variations[0]
    assert entry_variation.dose_outcome is DoseOutcome.UNVARIED_ADJUSTMENT_BELOW_WEIGHT_INCREMENT
    assert not entry_variation.dose_outcome.is_varied
    assert entry_variation.entry.dose == routine.entries[0].dose


def test_no_readings_at_all_leaves_readiness_unassessed(db):
    """Distinct from an UNKNOWN assessment: nobody even looked."""
    context = VariationContext.from_parts(preferences=dumbbells_only())
    assert context.readiness is None
    assert context.load_multiplier == 1.0
    assert vary_routine(bench_routine(), db, seed=3).readiness is None


def test_strain_cannot_relax_a_health_block(db):
    """The tiers do not trade against each other. Being well-recovered is not
    a reason to prescribe a contraindicated movement."""
    context = VariationContext.from_parts(
        health=HealthProfile(injuries=(shoulder_injury(),)), recovery=suppressed_recovery(), as_of=NOW
    )
    assert context.load_multiplier < 1.0
    assert not context.permits(db["barbell-overhead-press"])


# --- Adaptive tier: session intent -----------------------------------------


def test_intent_moves_the_volume_target_in_both_directions(db):
    """The whole point of a directive rather than a measurement: the user can
    ask for more, which readiness alone is never allowed to do."""
    routine = bench_routine()
    volumes = {}
    for intent in SessionIntent:
        context = VariationContext(session_intent=intent)
        variation = vary_routine(routine, db, context=context, seed=3, substitution_prob=0.0)
        volumes[intent] = variation.routine.total_volume

    assert volumes[SessionIntent.LIGHT] < volumes[SessionIntent.MODERATE]
    assert volumes[SessionIntent.CHALLENGING] > volumes[SessionIntent.MODERATE]


def test_moderate_is_exactly_the_old_volume_preserving_behaviour(db):
    """The default has to compose to a no-op, or every caller that never
    surfaces the control silently changes behaviour."""
    assert VariationContext().load_multiplier == 1.0
    assert VariationContext(session_intent=SessionIntent.MODERATE).load_multiplier == 1.0

    routine = bench_routine()
    with_default = vary_routine(routine, db, seed=3, substitution_prob=0.0)
    with_moderate = vary_routine(
        routine,
        db,
        context=VariationContext(session_intent=SessionIntent.MODERATE),
        seed=3,
        substitution_prob=0.0,
    )
    assert with_default.routine.entries == with_moderate.routine.entries
    assert with_default.entry_variations[0].dose_outcome is DoseOutcome.VARIED


def test_intent_works_on_day_one_with_no_history_at_all(db):
    """The reason a directive beats a self-reported score: no baseline needed.
    A 1-10 knob says nothing until it has ~7 sessions to compare against."""
    context = VariationContext(session_intent=SessionIntent.LIGHT)
    assert context.readiness is None
    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)
    assert variation.load_multiplier < 1.0
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_SESSION_INTENT


def test_intent_never_lengthens_the_session(db):
    """'Harder' means more work in the same window, not a longer workout --
    session length comes from the user's calendar."""
    routine = bench_routine()
    variation = vary_routine(
        routine,
        db,
        context=VariationContext(session_intent=SessionIntent.CHALLENGING),
        seed=3,
        substitution_prob=0.0,
    )
    assert pct_diff(variation.routine.total_time_seconds, routine.total_time_seconds) <= 0.10


# --- The two adaptive inputs composing -------------------------------------


def test_strain_scales_an_ambitious_request_down_without_discarding_it(db):
    """Neither input silently wins. A user who asks for a hard session while
    suppressed gets less than they asked for, but still more than LIGHT would
    have given them -- and the response says both things happened."""
    suppressed = suppressed_recovery()
    challenging_ill = VariationContext.from_parts(
        recovery=suppressed, as_of=NOW, session_intent=SessionIntent.CHALLENGING
    )
    light_ill = VariationContext.from_parts(
        recovery=suppressed, as_of=NOW, session_intent=SessionIntent.LIGHT
    )

    assert challenging_ill.load_multiplier <= 1.0, "readiness must still bind"
    assert challenging_ill.load_multiplier > light_ill.load_multiplier, "intent must still register"


def test_a_suppressed_user_never_gets_above_baseline_however_they_answered(db):
    """The case plain multiplication gets wrong: CHALLENGING 1.15 against a
    merely SUPPRESSED 0.90 is 1.035, which would hand an under-recovered user
    MORE work than normal. A binding readiness caps the result at 1.0."""
    for intent in SessionIntent:
        context = VariationContext.from_parts(
            recovery=suppressed_recovery(), as_of=NOW, session_intent=intent
        )
        assert context.readiness is not None
        assert context.readiness.modulates_load
        assert context.load_multiplier <= 1.0, intent

    routine = bench_routine()
    variation = vary_routine(
        routine,
        db,
        context=VariationContext.from_parts(
            recovery=suppressed_recovery(), as_of=NOW, session_intent=SessionIntent.CHALLENGING
        ),
        seed=3,
        substitution_prob=0.0,
    )
    assert variation.routine.total_volume <= routine.total_volume


def test_the_cap_preserves_the_ordering_between_intents(db):
    """Capping must not flatten the choice into "your answer was ignored" --
    a suppressed user's three options still differ from each other."""
    multipliers = [
        VariationContext.from_parts(
            recovery=suppressed_recovery(), as_of=NOW, session_intent=intent
        ).load_multiplier
        for intent in (SessionIntent.LIGHT, SessionIntent.MODERATE, SessionIntent.CHALLENGING)
    ]
    assert multipliers == sorted(multipliers)
    assert len(set(multipliers)) == 3


def illness_reported() -> tuple[WellnessCheckIn, ...]:
    """Strong suppression with no baseline at all -- illness is not a z-score."""
    return (
        WellnessCheckIn(
            user_id=USER_ID, recorded_at=NOW - timedelta(hours=4), illness_reported=True
        ),
    )


def test_readiness_is_named_ahead_of_intent_when_both_moved_the_target(db):
    """Being backed off for strain is the safety-relevant fact, so it wins the
    headline even though intent also moved the number. The full breakdown is
    always on the variation itself."""
    context = VariationContext.from_parts(
        wellness=illness_reported(), as_of=NOW, session_intent=SessionIntent.CHALLENGING
    )
    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)

    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED_FOR_STRAIN
    assert variation.session_intent is SessionIntent.CHALLENGING
    assert variation.readiness is not None
    assert variation.load_multiplier == pytest.approx(
        SessionIntent.CHALLENGING.load_multiplier * variation.readiness.load_multiplier
    )


def test_a_cancelled_request_is_still_reported(db):
    """The case that is invisible in the numbers: CHALLENGING against a merely
    SUPPRESSED readiness composes to exactly 1.0, so the dose is honestly
    volume-preserving and every entry reads VARIED. The user still asked for a
    hard session and did not get one, and something has to say so."""
    context = VariationContext.from_parts(
        recovery=suppressed_recovery(), as_of=NOW, session_intent=SessionIntent.CHALLENGING
    )
    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)

    assert variation.load_multiplier == pytest.approx(1.0)
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.VARIED
    assert variation.intent_capped_by_readiness


def test_an_unambitious_request_is_not_reported_as_capped(db):
    """Control: readiness binding is not by itself a cancelled request."""
    context = VariationContext.from_parts(
        recovery=suppressed_recovery(), as_of=NOW, session_intent=SessionIntent.LIGHT
    )
    variation = vary_routine(bench_routine(), db, context=context, seed=3, substitution_prob=0.0)
    assert variation.load_multiplier < 1.0
    assert not variation.intent_capped_by_readiness


def test_intent_is_not_read_from_the_user(db):
    """It is a choice about today, made when a session is generated -- not a
    stored property of the person."""
    user = User(
        profile=UserProfile(
            display_name="Test",
            unit_system=UnitSystem.METRIC,
            birth_date=date(1990, 5, 1),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    assert VariationContext.from_user(user).session_intent is SessionIntent.MODERATE
    assert (
        VariationContext.from_user(user, session_intent=SessionIntent.LIGHT).session_intent
        is SessionIntent.LIGHT
    )


# --- Assembly from a whole User -------------------------------------------


def test_from_user_reads_the_v2_aggregate(db):
    """The headline of M3: a User instance constrains the engine."""
    user = User(
        profile=UserProfile(
            display_name="Test",
            unit_system=UnitSystem.METRIC,
            birth_date=date(1990, 5, 1),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        health=HealthProfile(injuries=(shoulder_injury(),)),
        preferences=dumbbells_only(),
    )
    context = VariationContext.from_user(user)
    assert MovementPattern.VERTICAL_PUSH in context.blocked_movement_patterns
    assert context.available_equipment == frozenset({Equipment.DUMBBELL})


def test_unconstrained_context_permits_the_whole_library(db):
    context = VariationContext.unconstrained()
    report = summarise_filter(context, db)
    assert report.permitted == report.total
    assert report.permitted_fraction == 1.0


def test_summarise_filter_reports_how_much_a_context_rules_out(db):
    context = VariationContext.from_parts(preferences=dumbbells_only())
    report = summarise_filter(context, db)
    assert 0 < report.permitted < report.total
    assert 0.0 < report.permitted_fraction < 1.0


def test_no_equipment_constraint_is_not_the_same_as_no_equipment(db):
    """``None`` means unknown, ``frozenset()`` means genuinely nothing."""
    unknown = VariationContext(available_equipment=None)
    nothing = VariationContext(available_equipment=frozenset())
    exercise = db["barbell-bench-press"]
    assert unknown.permits(exercise)
    assert not nothing.permits(exercise)
