import pytest

from hibrid.exercise_db import ExerciseDB, UnknownExerciseError
from hibrid.models import DistanceDose, RepsDose, Routine, RoutineEntry
from hibrid.objective_strategy import MuscularEnduranceStrategy, StrengthStrategy
from hibrid.routine_io import load_routine
from hibrid.variation import (
    SUBSTITUTE_SCORE_BAND,
    DoseOutcome,
    best_matches,
    pct_diff,
    round_to_increment,
    vary_routine,
)

EXAMPLE_ROUTINE = "routines/example_ppl.yaml"


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


@pytest.fixture(scope="module")
def routine():
    return load_routine(EXAMPLE_ROUTINE)


def test_round_to_increment():
    assert round_to_increment(81.3, 2.5) == 82.5
    assert round_to_increment(83.0, 2.5) == 82.5


def test_pct_diff():
    assert pct_diff(100, 105) == pytest.approx(0.05)
    assert pct_diff(0, 0) == 0.0


@pytest.mark.parametrize("seed", range(10))
def test_total_volume_and_time_stay_within_tolerance(routine, db, seed):
    varied = vary_routine(routine, db, seed=seed).routine
    assert pct_diff(varied.total_volume, routine.total_volume) <= 0.075 + 1e-9
    assert pct_diff(varied.total_time_seconds, routine.total_time_seconds) <= 0.10 + 1e-9


@pytest.mark.parametrize("seed", range(10))
def test_substitutions_respect_movement_pattern(routine, db, seed):
    varied = vary_routine(routine, db, seed=seed, substitution_prob=1.0).routine
    for original_entry, new_entry in zip(routine.entries, varied.entries):
        original_exercise = db[original_entry.exercise_id]
        new_exercise = db[new_entry.exercise_id]
        assert new_exercise.target is original_exercise.target
        # Pattern is only a constraint where both sides declare one; it is
        # derived heuristically at import and legitimately absent for some.
        if new_exercise.movement_pattern and original_exercise.movement_pattern:
            assert new_exercise.movement_pattern is original_exercise.movement_pattern


@pytest.mark.parametrize("seed", range(10))
def test_substitutions_never_swap_loaded_for_bodyweight(routine, db, seed):
    """The engine solves weight from volume, so an implied load for a true
    bodyweight movement would be meaningless. With 1,125 bodyweight exercises in
    the library this is now a common path, not a corner case."""
    varied = vary_routine(routine, db, seed=seed, substitution_prob=1.0).routine
    for original_entry, new_entry in zip(routine.entries, varied.entries):
        assert db[new_entry.exercise_id].is_bodyweight == db[original_entry.exercise_id].is_bodyweight


def test_best_matches_keeps_only_the_top_scoring_band(db):
    source = db["dumbbell-lateral-raise"]
    candidates = db.find_substitutes(source.id)
    band = best_matches(source, candidates)

    best = max(source.similarity(ex) for ex in candidates)
    assert band
    assert len(band) < len(candidates)
    assert all(source.similarity(ex) >= best - SUBSTITUTE_SCORE_BAND for ex in band)


def test_best_matches_never_truncates_a_tie(db):
    """The anti-truncation guarantee. Muscle tags are coarse, so candidates tie
    at the top score; taking a fixed top-N off the ranked list would drop tied
    candidates purely because their ids sort later. Every exercise scoring the
    maximum must survive into the band."""
    source = db["dumbbell-lateral-raise"]
    candidates = db.find_substitutes(source.id)
    band = best_matches(source, candidates)

    best = max(source.similarity(ex) for ex in candidates)
    tied = {ex.id for ex in candidates if source.similarity(ex) == best}
    assert tied
    assert tied <= {ex.id for ex in band}


def test_best_matches_is_selective(db):
    """The band must be a real filter, not a pass-through -- if enrichment stops
    discriminating, this catches the whole candidate pool being returned."""
    source = db["dumbbell-lateral-raise"]
    candidates = db.find_substitutes(source.id)
    band = best_matches(source, candidates)
    assert len(band) < len(candidates) / 4


def test_variation_actually_varies_something(routine, db):
    changed = False
    for seed in range(20):
        varied = vary_routine(routine, db, seed=seed, substitution_prob=0.5).routine
        for old, new in zip(routine.entries, varied.entries):
            if (old.exercise_id, old.dose) != (new.exercise_id, new.dose):
                changed = True
    assert changed


# --- Why an entry did or did not move -------------------------------------


def test_entry_variations_are_parallel_to_the_varied_routine(routine, db):
    variation = vary_routine(routine, db, seed=1)
    assert len(variation.entry_variations) == len(routine.entries)
    for entry_variation, entry in zip(variation.entry_variations, variation.routine.entries):
        assert entry_variation.entry is entry


def test_outcome_is_varied_when_the_scheme_moves(routine, db):
    variation = vary_routine(routine, db, seed=3, substitution_prob=0.0)
    for entry_variation, original in zip(variation.entry_variations, routine.entries):
        moved = entry_variation.entry.dose != original.dose
        assert (entry_variation.dose_outcome is DoseOutcome.VARIED) == moved


def test_non_reps_dose_reports_why_it_was_left_alone(db):
    routine = Routine(
        name="Cardio",
        entries=[RoutineEntry(exercise_id="run", dose=DistanceDose(distance_m=1000, duration_seconds=300))],
    )
    variation = vary_routine(routine, db, seed=1, substitution_prob=0.0)
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.UNVARIED_NOT_REPS_DOSE


def test_modality_mismatch_is_distinguished_from_a_failed_search(db):
    """A cardio exercise carrying a rep dose is refused by the modality guard,
    not by the tolerance search -- the two must not look alike."""
    routine = Routine(
        name="Cardio with a rep dose",
        entries=[RoutineEntry(exercise_id="burpee", dose=RepsDose(sets=4, reps=10, weight=0))],
    )
    variation = vary_routine(routine, db, seed=1, substitution_prob=0.0)
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.UNVARIED_MODALITY_MISMATCH


def test_scheme_far_outside_the_objective_range_reports_no_scheme_in_range(db):
    """The search deliberately stays near the current scheme, so an 8-rep entry
    cannot reach muscular endurance's 15-25 window. That must be reported as
    "no candidate existed", never as a silent no-op."""
    routine = Routine(
        name="Far from the range",
        entries=[RoutineEntry(exercise_id="barbell-bench-press", dose=RepsDose(sets=4, reps=8, weight=80))],
    )
    variation = vary_routine(
        routine, db, objective=MuscularEnduranceStrategy(), seed=1, substitution_prob=0.0
    )
    entry_variation = variation.entry_variations[0]
    assert entry_variation.dose_outcome is DoseOutcome.UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE
    assert entry_variation.entry.dose == routine.entries[0].dose


def test_tolerance_of_zero_reports_a_failed_search_not_an_empty_one(db):
    """Schemes existed; none satisfied the tolerances. Distinct from having no
    schemes to try at all."""
    routine = Routine(
        name="Impossible tolerances",
        entries=[
            RoutineEntry(
                exercise_id="barbell-bench-press",
                dose=RepsDose(sets=4, reps=8, weight=80),
                rest_seconds=120,
            )
        ],
    )
    variation = vary_routine(
        routine, db, seed=1, substitution_prob=0.0, volume_tolerance=0.0, time_tolerance=0.0
    )
    assert variation.entry_variations[0].dose_outcome is DoseOutcome.UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE


def test_substitution_is_tracked_independently_of_the_dose_outcome(db):
    """A cardio entry can have its exercise swapped while its dose passes
    through untouched -- the two axes must not be conflated."""
    routine = Routine(
        name="Cardio, substitution on",
        entries=[RoutineEntry(exercise_id="run", dose=DistanceDose(distance_m=1000, duration_seconds=300))],
    )
    variation = vary_routine(routine, db, seed=1, substitution_prob=1.0)
    entry_variation = variation.entry_variations[0]
    assert entry_variation.exercise_substituted
    assert entry_variation.entry.exercise_id != "run"
    assert entry_variation.dose_outcome is DoseOutcome.UNVARIED_NOT_REPS_DOSE
    assert entry_variation.entry.dose == routine.entries[0].dose


def test_no_substitution_reports_false(routine, db):
    variation = vary_routine(routine, db, seed=1, substitution_prob=0.0)
    assert not any(ev.exercise_substituted for ev in variation.entry_variations)


# --- Holding intensity rather than volume ---------------------------------


def strength_entry(sets=4, reps=4, weight=100.0, rest=180):
    return Routine(
        name="Strength",
        entries=[
            RoutineEntry(
                exercise_id="barbell-bench-press",
                dose=RepsDose(sets=sets, reps=reps, weight=weight, rep_seconds=2.5),
                rest_seconds=rest,
            )
        ],
    )


@pytest.mark.parametrize("seed", range(25))
def test_strength_variation_never_moves_the_bar_weight(db, seed):
    """The defect this policy exists for. Solving load from a volume target let
    a 4x4 at 100 kg come back as anything from 6x6 at 45 kg to 3x1 at 532.5 kg
    -- every one of them volume- and time-preserving, and none of them the same
    session. Under an intensity-preserving objective the bar is what is held."""
    routine = strength_entry()
    varied = vary_routine(
        routine, db, objective=StrengthStrategy(), seed=seed, substitution_prob=0.0
    ).routine
    assert varied.entries[0].dose.weight == 100.0


@pytest.mark.parametrize("seed", range(25))
def test_hypertrophy_still_solves_the_load_from_volume(routine, db, seed):
    """The other half of the same guarantee: nothing about the intensity path
    may leak into the objective that was already correct."""
    varied = vary_routine(routine, db, seed=seed, substitution_prob=0.0).routine
    assert pct_diff(varied.total_volume, routine.total_volume) <= 0.075 + 1e-9


def test_strength_varies_the_scheme_at_a_fixed_load(db):
    """Holding the bar is not the same as holding everything -- the scheme may
    still wave around it, which is how a strength block varies at all."""
    schemes = {
        tuple(
            (e.dose.sets, e.dose.reps, e.dose.weight)
            for e in vary_routine(
                strength_entry(), db, objective=StrengthStrategy(), seed=seed,
                substitution_prob=0.0,
            ).routine.entries
        )
        for seed in range(25)
    }
    assert len(schemes) > 1, "the scheme must still move"
    assert all(weight == 100.0 for scheme in schemes for _, _, weight in scheme)


def test_a_held_strength_prescription_says_it_is_holding_deliberately(db):
    """A repeated prescription is the *correct* answer for strength, so it must
    not report the same "no candidate found" as a genuinely failed search --
    an app rendering it as a failure would be lying about the programme."""
    # 3x3 has no volume-equivalent partner inside strength's set range at a
    # fixed bar weight, so the search legitimately exhausts.
    variation = vary_routine(
        strength_entry(sets=3, reps=3), db, objective=StrengthStrategy(),
        seed=1, substitution_prob=0.0,
    )
    outcome = variation.entry_variations[0].dose_outcome
    assert outcome is DoseOutcome.UNVARIED_HOLDING_INTENSITY
    assert not outcome.is_varied


def test_an_undeliverable_adjustment_is_not_reported_as_a_deliberate_hold(db):
    """The other side of UNVARIED_HOLDING_INTENSITY. When nothing moved the
    target, holding is the intended outcome. When a deload *did* move it and no
    scheme could express it at this bar, holding is a failure to deliver what
    was asked for -- and claiming it was deliberate would be the same lie in the
    opposite direction."""
    from hibrid.variation_context import SessionIntent, VariationContext

    context = VariationContext.from_parts(session_intent=SessionIntent.LIGHT)

    held = vary_routine(
        strength_entry(sets=3, reps=3), db, objective=StrengthStrategy(), seed=1,
        substitution_prob=0.0,
    )
    assert held.entry_variations[0].dose_outcome is DoseOutcome.UNVARIED_HOLDING_INTENSITY

    # A tolerance tight enough that no scheme can carry the deloaded volume at
    # this bar weight. The deload was requested and not delivered.
    asked = vary_routine(
        strength_entry(sets=5, reps=5), db, objective=StrengthStrategy(),
        context=context, seed=1, substitution_prob=0.0, volume_tolerance=0.01,
    )
    assert (
        asked.entry_variations[0].dose_outcome
        is DoseOutcome.UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE
    ), "an undelivered deload must not claim the hold was deliberate, nor blame " \
       "a weight increment that was never the adjustment's target"


def test_the_objective_caps_substitution_whatever_the_caller_asked_for(db):
    """Novelty is a preference; how often a movement may rotate and still be
    trainable is a property of the objective. An explicit caller argument does
    not outrank it, and the capped value is reported rather than silently
    applied."""
    variation = vary_routine(
        strength_entry(), db, objective=StrengthStrategy(), seed=1, substitution_prob=1.0
    )
    assert variation.substitution_prob == pytest.approx(0.10)


def test_the_cap_does_not_touch_an_objective_that_declines_to_bound_novelty(db):
    variation = vary_routine(strength_entry(), db, seed=1, substitution_prob=1.0)
    assert variation.substitution_prob == pytest.approx(1.0)


def test_every_outcome_has_a_human_reason():
    for outcome in DoseOutcome:
        assert outcome.reason


def test_unknown_exercise_id_raises_a_typed_error(db):
    routine = Routine(
        name="Typo",
        entries=[RoutineEntry(exercise_id="no-such-exercise", dose=RepsDose(sets=3, reps=8, weight=80))],
    )
    with pytest.raises(UnknownExerciseError) as excinfo:
        vary_routine(routine, db, objective=StrengthStrategy(), seed=1, substitution_prob=0.0)
    assert excinfo.value.exercise_id == "no-such-exercise"
