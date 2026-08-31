"""M5, one session at a time: build a session from scratch rather than vary one.

Everything before this module needed a routine to start from. This one takes
three things a user can answer without owning a programme -- **how long they
have, what they want to train, and how hard they want it** -- and emits a
session. It is the cold-start half of ``docs/roadmap.md`` M5, scoped to a single
session rather than a week: the weekly ``TrainingPlan`` container and the
persistence it implies are separate work, and neither is needed to generate one
session.

The session is a ``Routine`` -- ``docs/api-v1-draft.md`` already fixes that a
``Routine`` *is* one session -- plus a ``SessionBlock`` per entry carrying what
generation decided and why.

**A block is one exercise slot, and it owns its own invariant.** That is what
makes ``vary_block`` safe: re-rolling one block preserves that block's volume
and time, so the session's three input parameters survive untouched no matter
how many times the user re-rolls. ``vary_entry`` already holds volume and time
*per entry* precisely so a variation cannot rob one exercise to pay another;
blocks make that per-entry guarantee addressable from the outside.

How the three inputs are consumed, and by what that already existed:

* **Time** binds the shape. Each block gets a share of the budget, and its
  ``(sets, reps, rest)`` is solved so the block lands on that share, with the
  ranges owned by ``ObjectiveStrategy`` exactly as variation uses them. M3
  deliberately skipped time budgets because variation preserves time by
  construction; generation is where a duration finally binds something.
* **Muscles** bind selection. One or more blocks per requested muscle, drawn
  from ``Exercise.target`` and filtered through ``VariationContext.permits`` --
  the same constraint tiering variation uses, reused wholesale.
* **Difficulty** arrives as ``VariationContext.session_intent`` rather than as a
  parameter of its own, so it composes with readiness and accumulated load
  through ``VariationContext.load_multiplier`` and inherits that property's cap
  at 1.0. A user who asks for a hard session while their own baseline says they
  are under-recovered gets the same protection here as they do in variation.
  Because the block's ``(sets, reps)`` is fixed by the time budget, scaling the
  volume target and scaling the load are the same operation, so the multiplier
  is applied to the load.

**Resistance only, on purpose.** Candidates are filtered to
``objective.preferred_modality``, which is ``RESISTANCE`` for all three
implemented strategies. A requested muscle reachable only through cardio,
mobility or balance work comes back as an explicit
``UnmetConstraintKind.MODALITY_NOT_SUPPORTED`` rather than as a quietly missing
block. Two things would have to land before that changes, and neither is a
decision this module can make: ``vary_entry`` cannot re-solve a
``DurationDose``, ``DistanceDose`` or ``RoundsDose`` at all (roadmap V2, the
binding constraint), and there is no MET column on ``Exercise`` to preserve as
the cross-modality currency -- the roadmap requires sourcing it from the
published Compendium of Physical Activities rather than deriving it, because a
confidently-wrong metabolic cost is worse than an absent one. ``Dose`` already
defines a per-modality currency via ``load_volume``, so the invariant this
module holds generalises; the search it would need does not exist yet.

**Starting load is M5's real problem, and it is answered conservatively.**
In priority order: what the user has actually lifted (``TrainingMemory``, M8b),
then a deliberately light fraction of body mass, then nothing -- and "nothing"
is reported, never guessed at. Every block says which of the three it got, for
the same reason every unvaried entry reports a ``DoseOutcome``: a number the
user cannot interrogate reads as a broken app.

``body_mass_kg`` is health-bucket data. It is accepted **request-scoped and
forgotten** -- never persisted, never logged, and never interpolated into an
error message. See CLAUDE.md's health-data rule.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from hibrid.exercise_db import ExerciseDB
from hibrid.models import (
    BodyPart,
    Difficulty,
    Exercise,
    Mechanics,
    MovementPattern,
    Muscle,
    RepsDose,
    Routine,
    RoutineEntry,
)
from hibrid.objective_strategy import ObjectiveStrategy
from hibrid.progression import ExerciseProgression, ProgressionPlan
from hibrid.training_memory import MAX_ESTIMABLE_REPS, TrainingMemory
from hibrid.user.enums import ExperienceLevel
from hibrid.user.profile import TrainingBackground
from hibrid.variation import (
    DEFAULT_OBJECTIVE,
    SUBSTITUTE_SCORE_BAND,
    DoseOutcome,
    ExerciseOutcome,
    pct_diff,
    round_to_increment,
    vary_routine,
)
from hibrid.variation_context import ContextFilterReport, VariationContext

#: How many blocks one muscle may get in a single session. A ceiling on junk
#: volume rather than a prescription: past roughly five exercises for one muscle
#: in one session the added work stops buying adaptation, and a long time budget
#: should overflow into a report line rather than into a twenty-block session.
#: Same class of number as the readiness multipliers -- named so it can be
#: argued with, not fitted to outcome data.
MAX_BLOCKS_PER_MUSCLE = 5

#: How far the prescribed session time may sit from the requested budget before
#: the report calls it a miss. Matches ``vary_routine``'s default
#: ``time_tolerance``, so a generated session and a varied one are judged
#: against the same slack.
TIME_BUDGET_TOLERANCE = 0.10

#: Selection nudge for a movement the user has already performed with sound
#: technique (``TrainingBackground.familiar_exercise_ids``). Deliberately
#: smaller than ``variation_context.PREFERENCE_BONUS``: "I like this one" is a
#: stated preference, "I have done this one" is weaker evidence about what to
#: prescribe today.
FAMILIARITY_BONUS = 0.05

#: Conservative starting load as a fraction of body mass, per movement pattern,
#: for a user with no history on the movement.
#:
#: These are deliberately light -- roughly half of published novice standards --
#: because M5's mitigation for having no norms table is to start low and let
#: M8b's RPE-driven progression converge upward over two or three sessions. A
#: first prescription 20% too light self-corrects; one 10% too heavy can hurt
#: someone on day one. They are the same class of number as the readiness
#: multipliers: named, inspectable heuristics a human can argue with, not values
#: fitted to outcome data, and explicitly *not* the defensible population-norms
#: table the roadmap describes as research.
#:
#: Expressed as **total external load**, which inherits the known per-hand vs
#: total-bar gap in ``docs/known-gaps.md``: a dumbbell prescription derived from
#: these is a total across both hands, not a per-hand figure.
_CONSERVATIVE_LOAD_FRACTION: dict[MovementPattern, float] = {
    MovementPattern.HORIZONTAL_PUSH: 0.35,
    MovementPattern.VERTICAL_PUSH: 0.20,
    MovementPattern.HORIZONTAL_PULL: 0.30,
    MovementPattern.VERTICAL_PULL: 0.30,
    MovementPattern.SQUAT: 0.40,
    MovementPattern.HINGE: 0.45,
    MovementPattern.LUNGE: 0.20,
    MovementPattern.CORE: 0.10,
    MovementPattern.ISOLATION_ARMS: 0.10,
    MovementPattern.ISOLATION_SHOULDERS: 0.05,
    MovementPattern.ISOLATION_KNEE: 0.15,
    MovementPattern.ISOLATION_SCAPULAR: 0.20,
    MovementPattern.CALF: 0.30,
    MovementPattern.ROTATION: 0.10,
    MovementPattern.ISOMETRIC_HOLD: 0.10,
    MovementPattern.LOADED_CARRY: 0.25,
    MovementPattern.LOCOMOTION: 0.10,
    MovementPattern.ISOLATION_HIP: 0.10,
}

#: The fallback when the exercise declares no movement pattern, keyed on the
#: body part, which is always derivable from the target muscle.
#:
#: A second table rather than one flat default because a single default cannot be
#: both safe and useful: 5% of body mass is a defensible guess for an
#: unclassified shoulder movement and an absurd one for an unclassified press,
#: and prescribing 4 kg for a dumbbell incline press reads as a broken app.
#: Each value is the conservative end of the patterns that body part contains --
#: ``UPPER_LEGS`` takes the leg-curl fraction rather than the squat one, because
#: an unclassified movement might be either and only one of those errors hurts.
_BODY_PART_LOAD_FRACTION: dict[BodyPart, float] = {
    BodyPart.BACK: 0.20,
    BodyPart.CARDIO: 0.05,
    BodyPart.CHEST: 0.20,
    BodyPart.LOWER_ARMS: 0.05,
    BodyPart.LOWER_LEGS: 0.20,
    BodyPart.NECK: 0.02,
    BodyPart.SHOULDERS: 0.05,
    BodyPart.UPPER_ARMS: 0.10,
    BodyPart.UPPER_LEGS: 0.15,
    BodyPart.WAIST: 0.10,
}

#: Last resort, if a body part ever escapes the table above.
_DEFAULT_LOAD_FRACTION = 0.05

#: How closely a candidate scheme has to hit the block's time budget before the
#: difference stops counting. Without it, exact-time fit decides the whole
#: prescription: a strength block solves to 4x2 rather than 4x3 because the
#: double lands 10 seconds closer once rest is rounded to 5-second steps, which
#: is a real change in prescription bought with noise. Inside one bucket the
#: tie-break falls through to the middle of the objective's ranges instead. 30
#: seconds is well within the 10% time tolerance for any block long enough to
#: prescribe.
_SCHEME_TIME_GRANULARITY_SECONDS = 30.0

#: The hardest ``Exercise.difficulty`` each experience level may be prescribed.
#:
#: The library grades skill on eight levels and the user schema declares six, so
#: this is a mapping rather than an identity. Each level is allowed exactly one
#: grade of stretch above its own label: a routine that never asks for anything
#: new does not develop skill, and a routine that asks for a press handstand on
#: day one is a safety problem.
_MAX_DIFFICULTY: dict[ExperienceLevel, Difficulty] = {
    ExperienceLevel.UNTRAINED: Difficulty.BEGINNER,
    ExperienceLevel.BEGINNER: Difficulty.NOVICE,
    ExperienceLevel.NOVICE: Difficulty.INTERMEDIATE,
    ExperienceLevel.INTERMEDIATE: Difficulty.ADVANCED,
    ExperienceLevel.ADVANCED: Difficulty.EXPERT,
    ExperienceLevel.ELITE: Difficulty.LEGENDARY,
}


class StartingLoadSource(str, Enum):
    """Where a block's prescribed weight came from.

    Kept as explicit outcomes rather than left to be inferred from the number,
    on the same principle as ``DoseOutcome``: ``NO_BASIS`` and
    ``BODYWEIGHT_ONLY`` both prescribe 0 kg and mean opposite things -- one is
    correct, the other is a gap the caller has to resolve."""

    REMEMBERED = "remembered"
    CONSERVATIVE_BODYWEIGHT_FRACTION = "conservative_bodyweight_fraction"
    BODYWEIGHT_ONLY = "bodyweight_only"
    NO_BASIS = "no_basis"
    PRESERVED_FROM_BLOCK = "preserved_from_block"

    @property
    def reason(self) -> str:
        return _LOAD_SOURCE_REASON[self]

    @property
    def is_prescribable(self) -> bool:
        """Whether this block can be handed to the user as-is.

        ``NO_BASIS`` is the only member that cannot: a loaded exercise with no
        load is not a prescription."""
        return self is not StartingLoadSource.NO_BASIS


_LOAD_SOURCE_REASON: dict[StartingLoadSource, str] = {
    StartingLoadSource.REMEMBERED: (
        "the load came from what this user has actually lifted on this movement, "
        "derived from their estimated 1RM at the prescribed rep count. Check the "
        "block's `progression` for whether the RPE of their last session moved it"
    ),
    StartingLoadSource.CONSERVATIVE_BODYWEIGHT_FRACTION: (
        "no history on this movement, so the load is a deliberately light "
        "fraction of body mass -- biased low on purpose so RPE-driven "
        "progression converges upward over two or three sessions rather than "
        "starting someone too heavy. Expect it to feel easy; that is the design"
    ),
    StartingLoadSource.BODYWEIGHT_ONLY: (
        "the exercise supplies no external load, so 0 kg is the correct "
        "prescription rather than a missing one. Note the dose of such a block "
        "cannot be re-solved -- the engine solves weight from volume, and an "
        "implied weight for a true bodyweight movement is meaningless"
    ),
    StartingLoadSource.NO_BASIS: (
        "this movement needs an external load and there was nothing to derive "
        "one from -- no history on it and no body mass supplied. The block names "
        "the exercise and the scheme but MUST NOT be prescribed at 0 kg; supply "
        "`body_mass_kg` or a session log, or ask the user for a working weight"
    ),
    StartingLoadSource.PRESERVED_FROM_BLOCK: (
        "the load was solved to preserve the block's existing volume, not from "
        "any load basis. This is what a re-rolled block reports: the work is the "
        "work the session was generated with"
    ),
}


class UnmetConstraintKind(str, Enum):
    """A way in which the generated session does not match what was asked for.

    Every one of these is reported rather than silently absorbed. A session that
    quietly drops a requested muscle, or quietly runs twenty minutes long, reads
    as a bug -- the same instinct that makes every unvaried entry carry a
    ``DoseOutcome``."""

    NO_PERMITTED_EXERCISE = "no_permitted_exercise"
    MODALITY_NOT_SUPPORTED = "modality_not_supported"
    TIME_BUDGET_OVERSHOT = "time_budget_overshot"
    TIME_BUDGET_UNDERFILLED = "time_budget_underfilled"
    STARTING_LOAD_UNKNOWN = "starting_load_unknown"
    LOAD_CAPPED_BY_EQUIPMENT = "load_capped_by_equipment"


@dataclass(frozen=True)
class UnmetConstraint:
    kind: UnmetConstraintKind
    detail: str


class StartingLoadPolicy(str, Enum):
    """Which basis the session's loads came from, in aggregate.

    Surfaced so a client can say "we start you light on purpose" rather than
    letting a deliberately conservative first prescription read as the app
    underestimating the user -- see ``docs/api-v1-draft.md``."""

    FROM_HISTORY = "from_history"
    CONSERVATIVE = "conservative"
    UNRESOLVED = "unresolved"
    MIXED = "mixed"
    NONE_NEEDED = "none_needed"

    @property
    def reason(self) -> str:
        return _LOAD_POLICY_REASON[self]


_LOAD_POLICY_REASON: dict[StartingLoadPolicy, str] = {
    StartingLoadPolicy.FROM_HISTORY: "every loaded block was built from this user's own logged lifts",
    StartingLoadPolicy.CONSERVATIVE: (
        "no usable history, so every loaded block starts deliberately light and "
        "is expected to climb over the first few sessions"
    ),
    StartingLoadPolicy.UNRESOLVED: (
        "no loaded block could be given a weight at all -- no history and no body "
        "mass. The session names the movements and the schemes and nothing more; "
        "supply `body_mass_kg` or a session log, or collect a working weight from "
        "the user"
    ),
    StartingLoadPolicy.MIXED: (
        "the loaded blocks did not all come from the same basis -- some from "
        "logged lifts, some starting deliberately light, or some with no weight "
        "at all. Read each block's own `load_source`"
    ),
    StartingLoadPolicy.NONE_NEEDED: "no block in this session carries an external load",
}


@dataclass(frozen=True)
class SessionBlock:
    """One exercise slot, and the invariant re-rolling it must preserve.

    ``index`` is the block's stable address within the session, so a client can
    ask for one block to be re-rolled without sending the rest back.

    ``time_budget_seconds`` is the share of the session budget this block was
    allocated, which is *not* the same as ``time_seconds``: the prescribed
    scheme lands as close to the budget as the objective's rest range allows,
    and the difference is exactly what the report's fit check reads."""

    index: int
    entry: RoutineEntry
    target: Muscle
    time_budget_seconds: float
    load_source: StartingLoadSource
    load_capped_by_equipment: bool = False
    #: What history said this block's load should be (M8b). ``None`` when no
    #: session log was supplied, which is not the same as a ``NO_HISTORY``
    #: decision -- that means memory was consulted and had nothing.
    progression: ExerciseProgression | None = None

    @property
    def volume(self) -> float:
        """The invariant a re-roll holds. In the block's own dose currency --
        kg-reps for resistance work -- per ``Dose.load_volume``."""
        return self.entry.volume

    @property
    def time_seconds(self) -> float:
        """The other invariant a re-roll holds."""
        return self.entry.time_seconds

    @property
    def fits_time_budget(self) -> bool:
        return pct_diff(self.time_budget_seconds, self.time_seconds) <= TIME_BUDGET_TOLERANCE

    @property
    def is_variable(self) -> bool:
        """Whether ``vary_block`` can re-solve this block's dose.

        False for a bodyweight block, and it is not a defect: the search solves
        a weight from a volume, and both are zero. Such a block can still have
        its *exercise* substituted -- only the dose is fixed."""
        return isinstance(self.entry.dose, RepsDose) and self.volume > 0.0


@dataclass(frozen=True)
class SessionGenerationReport:
    """What was asked for, what came out, and every way the two differ."""

    muscles_requested: tuple[Muscle, ...]
    muscles_covered: tuple[Muscle, ...]
    time_budget_seconds: float
    prescribed_time_seconds: float
    starting_load_policy: StartingLoadPolicy
    session_intent_load_multiplier: float
    #: The hardest movement this user's experience level allowed, and how much of
    #: the library that left. Reported because the ceiling applies even when no
    #: background was supplied -- beginner is the safe default -- and it removes
    #: roughly a third of the library in a way ``context_filter`` cannot show.
    skill_ceiling: Difficulty = Difficulty.NOVICE
    skill_filter: ContextFilterReport | None = None
    unmet_constraints: tuple[UnmetConstraint, ...] = ()

    @property
    def muscles_uncovered(self) -> tuple[Muscle, ...]:
        covered = set(self.muscles_covered)
        return tuple(m for m in self.muscles_requested if m not in covered)

    @property
    def fits_time_budget(self) -> bool:
        return (
            pct_diff(self.time_budget_seconds, self.prescribed_time_seconds)
            <= TIME_BUDGET_TOLERANCE
        )

    @property
    def is_prescribable(self) -> bool:
        """Whether the whole session can be handed to the user as-is.

        False when any requested muscle went uncovered or any block came back
        with no load basis. Both are honest results rather than errors, and both
        need the caller to do something before the session is shown."""
        return not self.muscles_uncovered and not any(
            constraint.kind is UnmetConstraintKind.STARTING_LOAD_UNKNOWN
            for constraint in self.unmet_constraints
        )


@dataclass(frozen=True)
class GeneratedSession:
    """A session built from scratch, plus the account of how it got that way.

    ``blocks[i].entry`` is ``routine.entries[i]`` -- the same object, offered
    both ways so a caller that only wants the routine is not forced to
    reassemble it. This mirrors ``RoutineVariation``."""

    routine: Routine
    blocks: tuple[SessionBlock, ...]
    report: SessionGenerationReport

    @property
    def total_volume(self) -> float:
        return self.routine.total_volume

    @property
    def total_time_seconds(self) -> float:
        return self.routine.total_time_seconds


@dataclass(frozen=True)
class BlockVariation:
    """One block re-rolled, and proof that it still holds its invariant.

    ``volume_preserved`` and ``time_preserved`` are computed rather than
    asserted because a re-roll can legitimately fail to move -- an exercise with
    no permitted substitute and no scheme inside tolerance comes back unchanged,
    which preserves the invariant trivially and must not look like success at
    something it did not do. Read ``dose_outcome`` for which happened."""

    original: SessionBlock
    block: SessionBlock
    dose_outcome: DoseOutcome
    exercise_outcome: ExerciseOutcome
    volume_tolerance: float
    time_tolerance: float

    @property
    def volume_preserved(self) -> bool:
        return pct_diff(self.original.volume, self.block.volume) <= self.volume_tolerance

    @property
    def time_preserved(self) -> bool:
        return pct_diff(self.original.time_seconds, self.block.time_seconds) <= self.time_tolerance

    @property
    def target_preserved(self) -> bool:
        """The block still trains the muscle the session was generated for.

        Substitution holds the target muscle fixed by construction, so this is a
        guard against a future relaxation of that rule rather than a live risk."""
        return self.block.target is self.original.target

    @property
    def exercise_substituted(self) -> bool:
        return self.exercise_outcome in (
            ExerciseOutcome.SUBSTITUTED_FOR_VARIETY,
            ExerciseOutcome.SUBSTITUTED_FOR_CONSTRAINT,
        )

    @property
    def is_unsafe(self) -> bool:
        """A contraindicated exercise survived the re-roll. Never silent."""
        return self.exercise_outcome is ExerciseOutcome.BLOCKED_NO_LEGAL_ALTERNATIVE


def generate_session(
    *,
    muscles: Sequence[Muscle],
    duration_minutes: float,
    db: ExerciseDB,
    objective: ObjectiveStrategy = DEFAULT_OBJECTIVE,
    context: VariationContext | None = None,
    memory: TrainingMemory | None = None,
    background: TrainingBackground | None = None,
    body_mass_kg: float | None = None,
    name: str | None = None,
    seed: int | None = None,
    weight_increment: float = 2.5,
) -> GeneratedSession:
    """Build a session for ``duration_minutes`` training ``muscles``.

    Difficulty is not a parameter here: it arrives as ``context.session_intent``
    so that it composes with readiness and accumulated load through
    ``VariationContext.load_multiplier``, and so there is one place that decides
    how hard today is rather than two that can disagree.

    ``context`` omitted means "no constraints known", exactly as in
    ``vary_routine`` -- a deliberate state, not a default user.

    ``memory`` is what makes the loads *this user's*. Without it they come from
    the conservative body-mass fractions, or from nothing, and the report says
    which.

    ``background`` supplies the skill ceiling (``experience_level``) and a
    selection nudge toward movements the user already performs well
    (``familiar_exercise_ids``). Omitted, the ceiling is the beginner one, which
    is the safe direction to be wrong in.

    ``body_mass_kg`` is health-bucket data, accepted request-scoped and
    forgotten. It is never persisted, logged, or interpolated into an error.
    """
    resolved_context = context if context is not None else VariationContext.unconstrained()
    rng = random.Random(seed)
    budget_seconds = duration_minutes * 60.0
    # dict.fromkeys rather than a set: a caller listing the same muscle twice
    # meant it once, and the order they asked in is the order of the session.
    requested = tuple(dict.fromkeys(muscles))
    unmet: list[UnmetConstraint] = []

    if not requested:
        return GeneratedSession(
            routine=Routine(name=name or _default_name(objective), entries=[]),
            blocks=(),
            report=SessionGenerationReport(
                muscles_requested=(),
                muscles_covered=(),
                time_budget_seconds=budget_seconds,
                prescribed_time_seconds=0.0,
                starting_load_policy=StartingLoadPolicy.NONE_NEEDED,
                session_intent_load_multiplier=resolved_context.load_multiplier,
                skill_ceiling=skill_ceiling_for(background),
                skill_filter=summarise_skill_filter(background, db),
            ),
        )

    per_muscle_seconds = budget_seconds / len(requested)
    blocks_per_muscle = _blocks_per_muscle(per_muscle_seconds, objective)
    block_budget_seconds = per_muscle_seconds / blocks_per_muscle

    # Solved once: every block in this session gets the same share of the
    # budget, so they all solve to the same scheme. Deliberate -- the variety a
    # user notices is in the exercises, and a single scheme keeps the session's
    # total time predictable, which is the parameter they actually asked for.
    sets, reps, rest_seconds = _solve_scheme(
        objective, block_budget_seconds, prefer_estimable_reps=memory is not None
    )

    selections: list[tuple[Muscle, Exercise]] = []
    used: set[str] = set()
    for muscle in requested:
        chosen = _select_exercises(
            muscle,
            db,
            rng,
            objective=objective,
            context=resolved_context,
            background=background,
            can_load=memory is not None or body_mass_kg is not None,
            count=blocks_per_muscle,
            already_used=used,
        )
        if not chosen:
            unmet.append(_no_candidate_constraint(muscle, db, objective, resolved_context))
            continue
        for exercise in chosen:
            used.add(exercise.id)
            selections.append((muscle, exercise))

    # Built once for the whole session, not per block: the same exercise must
    # not be progressed twice. Same rule as ``vary_routine``.
    progression = (
        ProgressionPlan.build(
            memory,
            objective=objective,
            prescribed_reps={exercise.id: reps for _, exercise in selections},
            weight_increment=weight_increment,
        )
        if memory is not None
        else ProgressionPlan.none()
    )

    blocks: list[SessionBlock] = []
    # Collected and reported once per kind rather than once per block: the
    # per-block ``load_source`` and ``load_capped_by_equipment`` already carry
    # which movement, and five near-identical constraint lines bury the one
    # constraint a reader has not seen before.
    unresolved: list[str] = []
    capped_names: list[str] = []
    for index, (muscle, exercise) in enumerate(_ordered(selections)):
        weight, source, capped = _resolve_load(
            exercise,
            reps=reps,
            progression=progression,
            body_mass_kg=body_mass_kg,
            load_multiplier=resolved_context.load_multiplier,
            weight_increment=weight_increment,
            context=resolved_context,
        )
        if source is StartingLoadSource.NO_BASIS:
            unresolved.append(exercise.name)
        if capped:
            capped_names.append(exercise.name)
        blocks.append(
            SessionBlock(
                index=index,
                entry=RoutineEntry(
                    exercise_id=exercise.id,
                    dose=RepsDose(
                        sets=sets, reps=reps, weight=weight, rep_seconds=objective.rep_seconds
                    ),
                    rest_seconds=rest_seconds,
                ),
                target=muscle,
                time_budget_seconds=block_budget_seconds,
                load_source=source,
                load_capped_by_equipment=capped,
                progression=progression.for_exercise(exercise.id),
            )
        )

    if unresolved:
        unmet.append(
            UnmetConstraint(
                kind=UnmetConstraintKind.STARTING_LOAD_UNKNOWN,
                detail=(
                    f"{len(unresolved)} block(s) need an external load with no "
                    "history and no body mass to derive one from "
                    f"({', '.join(sorted(unresolved))}). They must not be "
                    "prescribed at 0 kg"
                ),
            )
        )
    if capped_names:
        unmet.append(
            UnmetConstraint(
                kind=UnmetConstraintKind.LOAD_CAPPED_BY_EQUIPMENT,
                detail=(
                    f"{len(capped_names)} block(s) were capped at the heaviest "
                    "load this user has access to, so they carry less volume than "
                    f"the requested difficulty asked for ({', '.join(sorted(capped_names))})"
                ),
            )
        )

    routine = Routine(
        name=name or _default_name(objective),
        entries=[block.entry for block in blocks],
    )
    prescribed_seconds = routine.total_time_seconds
    covered = tuple(dict.fromkeys(block.target for block in blocks))
    if len(covered) == len(requested):
        # The budget is only judged on a session that got everything it asked
        # for. An uncovered muscle is *why* the time came up short, and reporting
        # both makes the reader hunt for a second cause that does not exist.
        unmet.extend(_time_constraints(budget_seconds, prescribed_seconds, blocks_per_muscle))

    return GeneratedSession(
        routine=routine,
        blocks=tuple(blocks),
        report=SessionGenerationReport(
            muscles_requested=requested,
            muscles_covered=covered,
            time_budget_seconds=budget_seconds,
            prescribed_time_seconds=prescribed_seconds,
            starting_load_policy=_load_policy(blocks),
            session_intent_load_multiplier=resolved_context.load_multiplier,
            skill_ceiling=skill_ceiling_for(background),
            skill_filter=summarise_skill_filter(background, db),
            unmet_constraints=tuple(unmet),
        ),
    )


def vary_block(
    block: SessionBlock,
    db: ExerciseDB,
    *,
    objective: ObjectiveStrategy = DEFAULT_OBJECTIVE,
    context: VariationContext | None = None,
    seed: int | None = None,
    substitution_prob: float | None = None,
    volume_tolerance: float = 0.075,
    time_tolerance: float = 0.10,
    weight_increment: float = 2.5,
    allow_equipment_change: bool = True,
) -> BlockVariation:
    """Re-roll one block, holding its own volume and time.

    This is ``vary_entry`` addressed at a single block, and it is deliberately
    thin -- the invariant it needs is the one variation has held per entry since
    M1. What the wrapper adds is two guards that only matter once difficulty is
    a session parameter:

    **The adaptive tier is neutralised.** The block's prescribed weight already
    embodies ``context.load_multiplier`` -- difficulty, readiness and
    accumulated load were applied when the session was generated. Passing the
    same context straight through would apply all three a second time, so a
    ``CHALLENGING`` session would get 15% heavier every time the user re-rolled
    a block, which is exactly the "jeopardising the input parameters" failure
    blocks exist to prevent. The context's constraint tiers are kept; only the
    load scaling is dropped. See ``VariationContext.without_adaptive_load``.

    **Memory is not consulted, and there is no ``memory`` parameter.** Re-rolling
    is the user asking for different work of the *same* size, not for
    reprogramming: a progression decision here would move the load off the
    block's volume, and the session's difficulty parameter is what owns that
    number. Generation is where history speaks.
    """
    resolved_context = (
        context.without_adaptive_load()
        if context is not None
        else VariationContext.unconstrained()
    )
    variation = vary_routine(
        Routine(name="block", entries=[block.entry]),
        db,
        objective=objective,
        context=resolved_context,
        seed=seed,
        substitution_prob=substitution_prob,
        volume_tolerance=volume_tolerance,
        time_tolerance=time_tolerance,
        weight_increment=weight_increment,
        allow_equipment_change=allow_equipment_change,
    )
    entry_variation = variation.entry_variations[0]
    varied_entry = entry_variation.entry
    return BlockVariation(
        original=block,
        block=SessionBlock(
            index=block.index,
            entry=varied_entry,
            # Read from the exercise rather than carried over: after a
            # substitution the honest answer is what the new movement targets.
            target=db[varied_entry.exercise_id].target,
            time_budget_seconds=block.time_budget_seconds,
            load_source=StartingLoadSource.PRESERVED_FROM_BLOCK,
            load_capped_by_equipment=block.load_capped_by_equipment,
        ),
        dose_outcome=entry_variation.dose_outcome,
        exercise_outcome=entry_variation.exercise_outcome,
        volume_tolerance=volume_tolerance,
        time_tolerance=time_tolerance,
    )


def _default_name(objective: ObjectiveStrategy) -> str:
    return f"generated {objective.objective.value} session"


def _blocks_per_muscle(per_muscle_seconds: float, objective: ObjectiveStrategy) -> int:
    """How many exercise slots one muscle's time share supports.

    Sized against a nominal mid-range block for this objective rather than
    against the solved scheme, because the scheme is solved *from* the block
    budget and the budget depends on this count."""
    min_sets, max_sets = objective.set_range
    min_reps, max_reps = objective.rep_range
    min_rest, max_rest = objective.rest_range_seconds
    nominal = ((min_sets + max_sets) // 2) * (
        ((min_reps + max_reps) // 2) * objective.rep_seconds + (min_rest + max_rest) // 2
    )
    # At least one: a requested muscle is never dropped for want of time. The
    # overshoot is reported instead.
    return max(1, min(MAX_BLOCKS_PER_MUSCLE, round(per_muscle_seconds / nominal)))


def _solve_scheme(
    objective: ObjectiveStrategy,
    budget_seconds: float,
    *,
    prefer_estimable_reps: bool = False,
) -> tuple[int, int, int]:
    """The ``(sets, reps, rest)`` inside this objective's ranges landing closest
    to ``budget_seconds``.

    Rest is solved from the budget and then clamped to the objective's range,
    the same way ``vary_entry`` solves it from the original time -- including the
    rounding to 5-second steps, because a prescription of 87 seconds' rest is
    false precision.

    ``prefer_estimable_reps`` breaks ties toward a rep count a rep-max formula
    will actually speak about, and it exists because of a genuinely surprising
    interaction: hypertrophy's rep range is 8-15, so its mid-range scheme is 11
    reps, and ``MAX_ESTIMABLE_REPS`` is 10 -- one rep past the point where
    ``TrainingMemory.working_load`` refuses to extrapolate. Without this, a
    generated hypertrophy session silently ignored every returning user's
    history and started them on the beginner fractions. Applied only when memory
    was supplied, and only *after* time fit, so it never buys history at the cost
    of the budget the user actually asked for.

    Always returns a scheme, even when the closest one overshoots the budget: a
    session too short to hold one legal block is still worth emitting with the
    miss reported, and a caller cannot act on ``None``."""
    min_sets, max_sets = objective.set_range
    min_reps, max_reps = objective.rep_range
    min_rest, max_rest = objective.rest_range_seconds
    mid_sets, mid_reps = (min_sets + max_sets) // 2, (min_reps + max_reps) // 2

    best: tuple[tuple[int, int, int, int, int, int], tuple[int, int, int]] | None = None
    for sets in range(min_sets, max_sets + 1):
        for reps in range(min_reps, max_reps + 1):
            work = reps * objective.rep_seconds
            rest = int(max(min_rest, min(max_rest, round((budget_seconds / sets - work) / 5) * 5)))
            elapsed = sets * (work + rest)
            # Time fit is bucketed rather than compared exactly, then ties break
            # toward a rep count history can speak about, then toward the middle
            # of the objective's ranges, and finally on the numbers themselves --
            # so the choice is fully deterministic and a seeded session is
            # reproducible, without a few seconds of rounding deciding the
            # prescription.
            key = (
                round(abs(elapsed - budget_seconds) / _SCHEME_TIME_GRANULARITY_SECONDS),
                1 if prefer_estimable_reps and reps > MAX_ESTIMABLE_REPS else 0,
                abs(sets - mid_sets),
                abs(reps - mid_reps),
                sets,
                reps,
            )
            if best is None or key < best[0]:
                best = (key, (sets, reps, rest))
    assert best is not None  # both ranges are non-empty by ObjectiveStrategy's contract
    return best[1]


def _within_skill_ceiling(exercise: Exercise, background: TrainingBackground | None) -> bool:
    """Whether this movement's skill demand suits the user's experience.

    Fails **open** on an undeclared difficulty, matching how
    ``find_substitutes`` treats an undeclared movement pattern. The alternative
    was tried in reasoning and rejected: difficulty is carried by 71% of the
    library and only ~2% of the exercisedb half, so failing closed would draw
    every session from one source and shrink the pool far more than it would
    improve safety. Health contraindications are the tier that fails closed --
    see ``VariationContext.permits``.

    ``familiar_exercise_ids`` overrides the ceiling outright, because the ceiling
    is a *proxy* for "can this person perform this safely" and that field is
    direct evidence of it -- the schema names it as exactly this: "exercise ids
    the user can already perform with sound technique". Refusing to prescribe a
    lift someone has demonstrated, because a grade in a table says it is above
    their level, is the proxy overruling the measurement."""
    if exercise.difficulty is None:
        return True
    if background is not None and exercise.id in background.familiar_exercise_ids:
        return True
    level = background.experience_level if background else ExperienceLevel.BEGINNER
    return exercise.difficulty.rank <= _MAX_DIFFICULTY[level].rank


def skill_ceiling_for(background: TrainingBackground | None) -> Difficulty:
    """The hardest movement this user may be prescribed. Public because the
    report carries it: a client should be able to say "we kept it to novice
    movements because you told us you are a beginner"."""
    return _MAX_DIFFICULTY[background.experience_level if background else ExperienceLevel.BEGINNER]


def summarise_skill_filter(
    background: TrainingBackground | None, db: ExerciseDB
) -> ContextFilterReport:
    """How much of the library the skill ceiling alone rules out.

    Worth surfacing for the reason ``summarise_filter`` exists, and more
    urgently: the ceiling is applied even when the caller supplies no background
    at all, because beginner is the safe direction to default. That removes
    roughly a third of the library invisibly, and ``context_filter`` cannot see
    it -- it only knows about ``VariationContext``."""
    exercises = db.all()
    return ContextFilterReport(
        permitted=sum(1 for exercise in exercises if _within_skill_ceiling(exercise, background)),
        total=len(exercises),
    )


def _select_exercises(
    muscle: Muscle,
    db: ExerciseDB,
    rng: random.Random,
    *,
    objective: ObjectiveStrategy,
    context: VariationContext,
    background: TrainingBackground | None,
    can_load: bool,
    count: int,
    already_used: set[str],
) -> list[Exercise]:
    """Up to ``count`` distinct permitted exercises targeting ``muscle``.

    ``can_load=False`` means no load basis exists for the whole session, so
    bodyweight movements are preferred -- their 0 kg is correct rather than
    missing. It is a preference and not a filter: a muscle with no permitted
    bodyweight option still gets loaded blocks, reported as ``NO_BASIS``, which
    is more useful than an absent muscle."""
    candidates = [
        exercise
        for exercise in _candidates(muscle, db, objective=objective, context=context)
        if exercise.id not in already_used and _within_skill_ceiling(exercise, background)
    ]
    if not candidates:
        return []

    familiar = background.familiar_exercise_ids if background else frozenset()

    def score(exercise: Exercise) -> float:
        value = context.preference_score(exercise)
        if exercise.id in familiar:
            value += FAMILIARITY_BONUS
        if not can_load and exercise.is_bodyweight:
            # Large enough to dominate the band, so bodyweight candidates are
            # taken first whenever any exist -- but still a score, so it cannot
            # empty the pool.
            value += 1.0
        return value

    # The same banding ``best_matches`` uses for substitutes, for the same
    # reason: dozens of exercises tie, and taking a fixed top-N off a sorted
    # list would pick whichever ids sort first rather than the best of them.
    best = max(score(exercise) for exercise in candidates)
    band = [exercise for exercise in candidates if score(exercise) >= best - SUBSTITUTE_SCORE_BAND]
    banded = {exercise.id for exercise in band}
    # Random order within the band, then the rest of the permitted pool
    # best-scoring first, so a band smaller than the session needs still fills
    # rather than returning fewer blocks than the time budget supports.
    draw_order = rng.sample(band, k=len(band)) + sorted(
        (exercise for exercise in candidates if exercise.id not in banded),
        key=lambda exercise: (-score(exercise), exercise.id),
    )
    return _take_diverse(draw_order, count)


def _diversity_key(exercise: Exercise) -> tuple[str, str]:
    """What makes this exercise a different *kind* of work from another one.

    Movement pattern where it is declared -- the same field substitution leans
    on. Where it is not, equipment: two exercises for one muscle with no
    declared pattern and the same equipment are near-certainly variants of each
    other, and "Muscle up" alongside "Muscle-up (on vertical bar)" is what the
    alternative looks like. Coarse, but the failure mode it prevents is visible
    to the user and the one it risks -- passing over a genuinely distinct
    movement -- is not."""
    if exercise.movement_pattern is not None:
        return ("pattern", exercise.movement_pattern.value)
    return ("equipment", exercise.equipment.value)


def _take_diverse(draw_order: Sequence[Exercise], count: int) -> list[Exercise]:
    """``count`` exercises off ``draw_order``, spending each kind of work once
    before spending any of them twice.

    Without this, a muscle with 200 permitted candidates reliably produces a
    session of near-duplicates -- four cable fly variants for one chest slot,
    drawn uniformly because they all score identically. Muscle tags cannot see
    that.

    The pass is a preference and not a filter: a muscle reachable through only
    one pattern still fills its blocks, from the second loop below."""
    chosen: list[Exercise] = []
    spent: set[tuple[str, str]] = set()
    for exercise in draw_order:
        if len(chosen) >= count:
            return chosen
        key = _diversity_key(exercise)
        if key in spent:
            continue
        chosen.append(exercise)
        spent.add(key)
    taken = {exercise.id for exercise in chosen}
    for exercise in draw_order:
        if len(chosen) >= count:
            break
        if exercise.id not in taken:
            chosen.append(exercise)
    return chosen


def _candidates(
    muscle: Muscle,
    db: ExerciseDB,
    *,
    objective: ObjectiveStrategy,
    context: VariationContext,
) -> list[Exercise]:
    return [
        exercise
        for exercise in db.all()
        if exercise.target is muscle
        and exercise.modality is objective.preferred_modality
        and context.permits(exercise)
    ]


def _no_candidate_constraint(
    muscle: Muscle,
    db: ExerciseDB,
    objective: ObjectiveStrategy,
    context: VariationContext,
) -> UnmetConstraint:
    """Say *why* a muscle went uncovered, since the two causes need different
    fixes from the caller.

    A muscle the library only reaches through cardio or mobility work is a
    perimeter gap that no change of equipment or health profile will close --
    it needs V2's dose search and a MET currency. A muscle with resistance
    exercises that this user is not permitted is a constraint problem, and the
    caller can act on it."""
    in_modality = any(
        exercise.target is muscle and exercise.modality is objective.preferred_modality
        for exercise in db.all()
    )
    if not in_modality:
        return UnmetConstraint(
            kind=UnmetConstraintKind.MODALITY_NOT_SUPPORTED,
            detail=(
                f"the library trains {muscle.value!r} only outside "
                f"{objective.preferred_modality.value!r}, and non-resistance doses "
                "can be neither generated nor varied yet -- there is no "
                "duration/distance/rounds search and no MET currency to preserve"
            ),
        )
    return UnmetConstraint(
        kind=UnmetConstraintKind.NO_PERMITTED_EXERCISE,
        detail=(
            f"{muscle.value!r} has {objective.preferred_modality.value} exercises "
            "in the library but none this user is permitted -- check equipment "
            "access, excluded movement patterns and health contraindications"
        ),
    )


def _ordered(selections: list[tuple[Muscle, Exercise]]) -> list[tuple[Muscle, Exercise]]:
    """Compound movements before isolation ones, muscle order preserved.

    The one ordering rule the data actually supports (``Exercise.mechanics``,
    71% coverage): a compound lift done fatigued after isolation work on the
    same muscle is the worse session, whatever else is true. Undeclared
    mechanics sort between the two rather than last, because an unclassified
    movement is not knowingly an isolation one."""
    order = {Mechanics.COMPOUND: 0, None: 1, Mechanics.ISOLATION: 2}
    muscle_rank = {muscle: rank for rank, muscle in enumerate(dict.fromkeys(m for m, _ in selections))}
    return sorted(
        selections,
        key=lambda pair: (muscle_rank[pair[0]], order[pair[1].mechanics], pair[1].id),
    )


def _resolve_load(
    exercise: Exercise,
    *,
    reps: int,
    progression: ProgressionPlan,
    body_mass_kg: float | None,
    load_multiplier: float,
    weight_increment: float,
    context: VariationContext,
) -> tuple[float, StartingLoadSource, bool]:
    """This block's prescribed weight, where it came from, and whether the
    user's equipment capped it.

    ``load_multiplier`` scales the load rather than the sets or reps because the
    scheme is already fixed by the time budget: at fixed ``sets x reps``,
    scaling the load and scaling the volume target are the same operation, and
    session time must not move with difficulty. That is the same rule variation
    follows -- 'harder' means more work in the same window."""
    if exercise.is_bodyweight:
        return 0.0, StartingLoadSource.BODYWEIGHT_ONLY, False

    entry_progression = progression.for_exercise(exercise.id)
    if entry_progression is not None and entry_progression.working_load_kg is not None:
        base, source = entry_progression.working_load_kg, StartingLoadSource.REMEMBERED
    elif body_mass_kg is not None:
        base = body_mass_kg * _load_fraction(exercise)
        source = StartingLoadSource.CONSERVATIVE_BODYWEIGHT_FRACTION
    else:
        return 0.0, StartingLoadSource.NO_BASIS, False

    weight = round_to_increment(base * load_multiplier, weight_increment)
    capped = False
    if not context.permits_load(weight) and context.max_load_kg is not None:
        # Down to the nearest increment they can actually load, never up: the
        # cap is a fact about their equipment.
        weight = math.floor(context.max_load_kg / weight_increment) * weight_increment
        capped = True
    # One increment is the floor for a loaded movement. A prescription of 0 kg
    # on a barbell is not a light session, it is a different exercise.
    return max(weight, weight_increment), source, capped


def _load_fraction(exercise: Exercise) -> float:
    """The fraction of body mass to start this movement at.

    Movement pattern first because it is the finer signal -- a hinge and a
    single-joint knee movement are not started at the same load and both are
    ``UPPER_LEGS``. Body part second, because it is always known. Note this
    inherits any wrong pattern in the library (see
    ``docs/known-gaps.md``): a mislabelled movement gets the wrong fraction, and
    the table is biased light in every row so that error lands on the safe
    side."""
    if exercise.movement_pattern is not None:
        return _CONSERVATIVE_LOAD_FRACTION.get(exercise.movement_pattern, _DEFAULT_LOAD_FRACTION)
    return _BODY_PART_LOAD_FRACTION.get(exercise.body_part, _DEFAULT_LOAD_FRACTION)


def _load_policy(blocks: Sequence[SessionBlock]) -> StartingLoadPolicy:
    """Which basis the session's loads came from, in aggregate.

    Bodyweight blocks are excluded from the question rather than counted as a
    basis: they need no weight, so a session of nothing but push-ups is
    ``NONE_NEEDED`` and not a failure to resolve anything."""
    bases = {
        block.load_source
        for block in blocks
        if block.load_source is not StartingLoadSource.BODYWEIGHT_ONLY
    }
    if not bases:
        return StartingLoadPolicy.NONE_NEEDED
    if len(bases) > 1:
        return StartingLoadPolicy.MIXED
    return _POLICY_FOR_SOURCE[bases.pop()]


_POLICY_FOR_SOURCE: dict[StartingLoadSource, StartingLoadPolicy] = {
    StartingLoadSource.REMEMBERED: StartingLoadPolicy.FROM_HISTORY,
    StartingLoadSource.CONSERVATIVE_BODYWEIGHT_FRACTION: StartingLoadPolicy.CONSERVATIVE,
    StartingLoadSource.NO_BASIS: StartingLoadPolicy.UNRESOLVED,
    # Never reached from generation -- a preserved load only exists on a re-roll.
    StartingLoadSource.PRESERVED_FROM_BLOCK: StartingLoadPolicy.FROM_HISTORY,
    StartingLoadSource.BODYWEIGHT_ONLY: StartingLoadPolicy.NONE_NEEDED,
}


def _time_constraints(
    budget_seconds: float, prescribed_seconds: float, blocks_per_muscle: int
) -> list[UnmetConstraint]:
    if pct_diff(budget_seconds, prescribed_seconds) <= TIME_BUDGET_TOLERANCE:
        return []
    minutes = prescribed_seconds / 60.0
    requested_minutes = budget_seconds / 60.0
    if prescribed_seconds > budget_seconds:
        return [
            UnmetConstraint(
                kind=UnmetConstraintKind.TIME_BUDGET_OVERSHOT,
                detail=(
                    f"the shortest legal session for these muscles runs "
                    f"{minutes:.0f} min against a {requested_minutes:.0f} min "
                    "budget -- one block per requested muscle is the floor, and a "
                    "muscle is never dropped to save time"
                ),
            )
        ]
    return [
        UnmetConstraint(
            kind=UnmetConstraintKind.TIME_BUDGET_UNDERFILLED,
            detail=(
                f"the session fills {minutes:.0f} min of a "
                f"{requested_minutes:.0f} min budget: at most "
                f"{blocks_per_muscle} block(s) per muscle, and rest is capped by "
                "the objective's own range"
            ),
        )
    ]
