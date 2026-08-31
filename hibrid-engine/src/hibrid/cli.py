from __future__ import annotations

import argparse

from hibrid.exercise_db import ExerciseDB
from hibrid.models import Routine
from hibrid.objective_strategy import STRATEGIES_BY_OBJECTIVE
from hibrid.routine_io import dump_routine, load_routine
from hibrid.user.enums import TrainingObjective
from hibrid.variation import DEFAULT_OBJECTIVE, DoseOutcome, RoutineVariation, vary_routine
from hibrid.variation_context import SessionIntent, VariationContext


NAME_WIDTH = 44


def print_comparison(original: Routine, variation: RoutineVariation, db: ExerciseDB) -> None:
    varied = variation.routine
    print(f"{'Exercise':<{NAME_WIDTH}}{'Sets x Reps @ Weight':<24}{'Volume':>10}{'Time(s)':>10}")
    print("-" * (NAME_WIDTH + 44))
    unvaried: list[DoseOutcome] = []
    for old, entry_variation in zip(original.entries, variation.entry_variations):
        new = entry_variation.entry
        # Imported names run to 67 chars; truncate rather than break the columns.
        old_name = db[old.exercise_id].name[: NAME_WIDTH - 2]
        new_name = db[new.exercise_id].name[: NAME_WIDTH - 6]
        old_scheme = old.dose.describe()
        new_scheme = new.dose.describe()
        print(f"{old_name:<{NAME_WIDTH}}{old_scheme:<24}{old.volume:>10.0f}{old.time_seconds:>10.0f}")
        if entry_variation.exercise_substituted:
            print(
                f"{'  -> ' + new_name:<{NAME_WIDTH}}{new_scheme:<24}"
                f"{new.volume:>10.0f}{new.time_seconds:>10.0f}"
            )
        else:
            print(f"{'':<{NAME_WIDTH}}{new_scheme:<24}{new.volume:>10.0f}{new.time_seconds:>10.0f}")
        if not entry_variation.dose_outcome.is_varied:
            print(f"{'  (scheme unchanged: ' + entry_variation.dose_outcome.value + ')':<{NAME_WIDTH}}")
            unvaried.append(entry_variation.dose_outcome)
    print("-" * (NAME_WIDTH + 44))
    print(
        f"{'TOTAL':<{NAME_WIDTH}}{'':<24}"
        f"{original.total_volume:>10.0f}{original.total_time_seconds:>10.0f}"
    )
    print(f"{'':<{NAME_WIDTH}}{'':<24}{varied.total_volume:>10.0f}{varied.total_time_seconds:>10.0f}")

    # A routine whose totals came back deliberately lighter or heavier must say
    # so. Without this the volume column looks like the engine missing its own
    # invariant rather than hitting a target that moved on purpose.
    if variation.load_multiplier != 1.0:
        print(
            f"\nvolume target x{variation.load_multiplier:.2f}: "
            f"{variation.session_intent.reason}"
        )
        if variation.readiness is not None and variation.readiness.modulates_load:
            print(f"  {variation.readiness.explain()}")

    # An unchanged scheme is almost never "already optimal" -- it usually means
    # no candidate was considered at all. Say why, rather than leaving the
    # caller to guess from an identical-looking row.
    for outcome in dict.fromkeys(unvaried):
        print(f"\n{outcome.value}: {outcome.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vary an existing routine while holding volume/time constant.")
    parser.add_argument("routine", help="Path to routine YAML file")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--substitution-prob", type=float, default=0.3)
    parser.add_argument(
        "--objective",
        choices=[objective.value for objective in STRATEGIES_BY_OBJECTIVE],
        default=DEFAULT_OBJECTIVE.objective.value,
        help="Which training objective's rep scheme, rest and tempo to vary toward.",
    )
    parser.add_argument(
        "--intent",
        choices=[intent.value for intent in SessionIntent],
        default=SessionIntent.MODERATE.value,
        help="How hard this session should be. Scales the volume target; session length is held.",
    )
    parser.add_argument("--out", help="Write the varied routine YAML to this path")
    args = parser.parse_args()

    db = ExerciseDB.load()
    original = load_routine(args.routine)
    objective = STRATEGIES_BY_OBJECTIVE[TrainingObjective(args.objective)]
    context = VariationContext(session_intent=SessionIntent(args.intent))
    variation = vary_routine(
        original,
        db,
        objective=objective,
        context=context,
        seed=args.seed,
        substitution_prob=args.substitution_prob,
    )

    print_comparison(original, variation, db)

    if args.out:
        with open(args.out, "w") as f:
            f.write(dump_routine(variation.routine))
        print(f"\nWrote varied routine to {args.out}")


if __name__ == "__main__":
    main()
