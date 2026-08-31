import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.models import DistanceDose, DurationDose, RepsDose
from hibrid.objective_strategy import (
    STRATEGIES_BY_OBJECTIVE,
    HypertrophyStrategy,
    Invariant,
    MuscularEnduranceStrategy,
    StrengthStrategy,
)
from hibrid.routine_io import load_routine
from hibrid.user.enums import TrainingObjective
from hibrid.variation import vary_routine

EXAMPLE_PPL = "routines/example_ppl.yaml"
EXAMPLE_MIXED = "routines/example_mixed.yaml"


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


@pytest.fixture(scope="module")
def routine():
    return load_routine(EXAMPLE_PPL)


@pytest.fixture(scope="module")
def mixed_routine():
    return load_routine(EXAMPLE_MIXED)


@pytest.mark.parametrize("strategy", [StrengthStrategy(), HypertrophyStrategy(), MuscularEnduranceStrategy()])
def test_candidate_rep_schemes_excludes_original_and_stays_in_range(strategy):
    schemes = strategy.candidate_rep_schemes(4, 8)
    assert (4, 8) not in schemes
    min_sets, max_sets = strategy.set_range
    min_reps, max_reps = strategy.rep_range
    assert all(min_sets <= s <= max_sets and min_reps <= r <= max_reps for s, r in schemes)


def test_registry_keys_match_each_strategys_own_objective():
    for objective, strategy in STRATEGIES_BY_OBJECTIVE.items():
        assert strategy.objective is objective


def test_strength_prefers_fewer_reps_than_muscular_endurance():
    assert StrengthStrategy().rep_range[1] < MuscularEnduranceStrategy().rep_range[0]


@pytest.mark.parametrize("seed", range(10))
def test_strength_objective_keeps_varied_entries_within_its_rep_range(routine, db, seed):
    strategy = StrengthStrategy()
    varied = vary_routine(routine, db, objective=strategy, seed=seed, substitution_prob=0.0).routine
    min_reps, max_reps = strategy.rep_range
    for original, new in zip(routine.entries, varied.entries):
        if isinstance(new.dose, RepsDose) and new.dose != original.dose:
            assert min_reps <= new.dose.reps <= max_reps


@pytest.mark.parametrize("objective", [TrainingObjective.STRENGTH, TrainingObjective.MUSCULAR_ENDURANCE])
def test_non_resistance_entries_pass_through_unchanged_regardless_of_objective(mixed_routine, db, objective):
    strategy = STRATEGIES_BY_OBJECTIVE[objective]
    varied = vary_routine(mixed_routine, db, objective=strategy, seed=1, substitution_prob=0.0).routine
    for original, new in zip(mixed_routine.entries, varied.entries):
        if isinstance(original.dose, (DistanceDose, DurationDose)):
            assert new.dose == original.dose


# --- The variation policy -------------------------------------------------


def test_every_strategy_declares_a_variation_policy():
    """The policy is what the whole objective-aware variation rests on, so a
    strategy added later must not be able to forget it and silently inherit
    hypertrophy's behaviour."""
    for strategy in STRATEGIES_BY_OBJECTIVE.values():
        policy = strategy.variation_policy
        assert isinstance(policy.preserved_invariant, Invariant)
        assert 0.0 <= policy.max_substitution_prob <= 1.0


def test_only_strength_preserves_intensity():
    """The split that matters. Proximity to maximum is what strength adapts to;
    total work is what hypertrophy and local endurance adapt to."""
    assert StrengthStrategy().variation_policy.preserved_invariant is Invariant.INTENSITY
    assert HypertrophyStrategy().variation_policy.preserved_invariant is Invariant.LOAD_VOLUME
    assert (
        MuscularEnduranceStrategy().variation_policy.preserved_invariant
        is Invariant.LOAD_VOLUME
    )


def test_strength_bounds_substitution_far_below_the_others():
    """Strength is a movement-specific skill and TrainingMemory is keyed on the
    exercise, so rotation costs both the adaptation and the history progression
    reads. The other two objectives are deliberately not bounded here."""
    strength = StrengthStrategy().variation_policy.max_substitution_prob
    assert strength < HypertrophyStrategy().variation_policy.max_substitution_prob
    assert strength < MuscularEnduranceStrategy().variation_policy.max_substitution_prob


def test_strength_still_allows_some_substitution():
    """Not zero, deliberately: a hard zero would make a contraindicated lift
    unsubstitutable, and the constraint layer must always be able to replace an
    exercise the user must not perform."""
    assert StrengthStrategy().variation_policy.max_substitution_prob > 0.0
