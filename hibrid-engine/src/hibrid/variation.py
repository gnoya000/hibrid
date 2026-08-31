"""Variation engine: micro-vary an existing routine while holding its training
stimulus and its total time roughly constant.

Per exercise entry, this may (a) substitute the exercise for a movement-pattern
and muscle-matched alternative, and (b) shift the sets/reps scheme, solving for
the weight and rest that keep that entry within tolerance of the original.
Which schemes, rest and tempo are even on the table is owned by an
``ObjectiveStrategy`` rather than by a single fixed range -- this module owns
"hold the invariant and vary the rest", not what "the rest" should look like
for a given objective.

**Which invariant is itself the objective's choice**, and this is the part most
easily got wrong. ``ObjectiveStrategy.variation_policy`` names one of two:

* ``Invariant.LOAD_VOLUME`` -- hold ``sets * reps * weight``, solve the weight
  per candidate scheme. Right for hypertrophy and local endurance, where total
  work is what drives the adaptation.
* ``Invariant.INTENSITY`` -- hold the bar weight at the reference load, let
  total work float within tolerance. Right for strength, where proximity to
  maximum is the adaptation and total work is a by-product.

Solving load from a volume target under a strength objective preserves the
arithmetic and destroys the training: a 4x4 at 100 kg and a 6x6 at 45 kg carry
identical volume, pass every tolerance, and are not the same session. The same
policy also bounds how often an exercise may be substituted, because strength
is a movement-specific skill and because ``TrainingMemory`` is keyed on the
exercise -- so an unbounded swap rate discards the history that progression
reads.

The volume target is the entry's own volume scaled by
``VariationContext.load_multiplier``, which composes three separate things: how
recovered the user's *own* baseline says they are (M3 pass 2), how hard they
asked this particular session to be, and what the last four weeks of logged work
plus any dated event they are training toward say the block can carry (M8c).
Time is never scaled with any of them -- a session's length is set by the user's
calendar, not by their HRV, their mood or their race date -- so an adjusted entry
is the same time doing lighter or heavier work.

Known limitation: substitution still doesn't distinguish per-hand (dumbbell)
from total-bar (barbell) load, so a swap across those can imply a weight that
means something different in practice. Deferred to a later version.

The related bodyweight half of that bug is now handled -- ``find_substitutes``
refuses to swap a loaded exercise for a bodyweight one, so the engine no longer
solves a meaningless "implied weight" for a push-up. That became load-bearing
when the library grew to 4,531 exercises, a quarter of them bodyweight.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from hibrid.exercise_db import ExerciseDB
from hibrid.load_management import LoadManagementAssessment
from hibrid.models import Exercise, RepsDose, Routine, RoutineEntry
from hibrid.objective_strategy import HypertrophyStrategy, Invariant, ObjectiveStrategy
from hibrid.progression import ExerciseProgression, ProgressionPlan
from hibrid.readiness import ReadinessAssessment
from hibrid.training_memory import TrainingMemory
from hibrid.variation_context import SessionIntent, VariationContext, intent_exceeds

#: V1's original fixed behaviour, kept as the default so existing callers that
#: don't pass ``objective`` see no change in outcome.
DEFAULT_OBJECTIVE: ObjectiveStrategy = HypertrophyStrategy()

#: Used when neither the caller nor the user's ``novelty_preference`` says
#: otherwise.
DEFAULT_SUBSTITUTION_PROB = 0.3


def round_to_increment(value: float, increment: float) -> float:
    return round(value / increment) * increment


def pct_diff(a: float, b: float) -> float:
    if a == 0:
        return 0.0 if b == 0 else float("inf")
    return abs(a - b) / abs(a)


#: How far below the best similarity score a substitute may still be drawn.
#: Muscle tags are coarse, so dozens of exercises routinely tie at the top --
#: 39 candidates share the best score for a dumbbell lateral raise. Taking a
#: fixed top-N off the ranked list would not pick the best of them, it would
#: pick whichever ids sort first, biasing every routine toward exercise names
#: beginning with "band" and "barbell". Sampling the whole tied band instead
#: keeps the choice varied and leaves determinism to the seeded rng.
SUBSTITUTE_SCORE_BAND = 0.05


def best_matches(
    source: Exercise,
    candidates: list[Exercise],
    context: VariationContext | None = None,
) -> list[Exercise]:
    """The candidates scoring within ``SUBSTITUTE_SCORE_BAND`` of the best one.

    A context's soft preferences shift the score before the band is taken. The
    dislike penalty is deliberately larger than the band, so a disliked
    candidate drops out whenever an equally-suitable alternative exists -- but
    it stays selectable when *everything* available is disliked, which is what
    keeps a dislike a cost rather than a smuggled-in exclusion."""

    def score(exercise: Exercise) -> float:
        base = source.similarity(exercise)
        return base + context.preference_score(exercise) if context else base

    best = max(score(ex) for ex in candidates)
    return [ex for ex in candidates if score(ex) >= best - SUBSTITUTE_SCORE_BAND]


class ExerciseOutcome(str, Enum):
    """What happened to an entry's *exercise*, independent of its dose.

    ``SUBSTITUTED_FOR_CONSTRAINT`` and ``SUBSTITUTED_FOR_VARIETY`` are kept
    apart because they mean opposite things to a reviewer: one is the safety
    layer doing its job, the other is the novelty dial. ``BLOCKED_NO_LEGAL_
    ALTERNATIVE`` is the case that must never be silent -- see its reason."""

    KEPT = "kept"
    SUBSTITUTED_FOR_VARIETY = "substituted_for_variety"
    SUBSTITUTED_FOR_CONSTRAINT = "substituted_for_constraint"
    BLOCKED_NO_LEGAL_ALTERNATIVE = "blocked_no_legal_alternative"

    @property
    def reason(self) -> str:
        return _EXERCISE_OUTCOME_REASON[self]


_EXERCISE_OUTCOME_REASON: dict[ExerciseOutcome, str] = {
    ExerciseOutcome.KEPT: "the prescribed exercise was kept",
    ExerciseOutcome.SUBSTITUTED_FOR_VARIETY: "swapped for variety, per the novelty dial",
    ExerciseOutcome.SUBSTITUTED_FOR_CONSTRAINT: (
        "the prescribed exercise is not permitted for this user, so it was "
        "swapped for a permitted alternative"
    ),
    ExerciseOutcome.BLOCKED_NO_LEGAL_ALTERNATIVE: (
        "the prescribed exercise is NOT permitted for this user and no "
        "permitted substitute exists -- it was left in place and must not be "
        "prescribed as-is. Variation cannot drop an entry; resolving this is "
        "the generating layer's job"
    ),
}


class DoseOutcome(str, Enum):
    """Why an entry's dose did or did not move.

    An entry passes through unchanged for four genuinely different reasons,
    and without this they are indistinguishable in the output -- "nothing
    changed" reads as "the current scheme was already right" when it usually
    means "no candidate was ever considered". Distinguishing them is what
    makes an objective's effect auditable rather than mysterious."""

    VARIED = "varied"
    VARIED_FOR_STRAIN = "varied_for_strain"
    VARIED_FOR_LOAD_MANAGEMENT = "varied_for_load_management"
    VARIED_FOR_PROGRESSION = "varied_for_progression"
    VARIED_AT_REMEMBERED_LOAD = "varied_at_remembered_load"
    VARIED_FOR_SESSION_INTENT = "varied_for_session_intent"
    UNVARIED_NOT_REPS_DOSE = "unvaried_not_reps_dose"
    UNVARIED_MODALITY_MISMATCH = "unvaried_modality_mismatch"
    UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE = "unvaried_no_scheme_in_objective_range"
    UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE = "unvaried_no_candidate_within_tolerance"
    UNVARIED_HOLDING_INTENSITY = "unvaried_holding_intensity"
    UNVARIED_LOAD_EXCEEDS_EQUIPMENT = "unvaried_load_exceeds_equipment"
    UNVARIED_ADJUSTMENT_BELOW_WEIGHT_INCREMENT = "unvaried_adjustment_below_weight_increment"

    @property
    def is_varied(self) -> bool:
        """Whether the dose moved at all, by whichever route.

        Exists so callers test the *question* rather than one enum member: an
        ``is not VARIED`` check silently reclassified every strain-driven
        deload as unvaried the moment ``VARIED_FOR_STRAIN`` was added."""
        return self in (
            DoseOutcome.VARIED,
            DoseOutcome.VARIED_FOR_STRAIN,
            DoseOutcome.VARIED_FOR_LOAD_MANAGEMENT,
            DoseOutcome.VARIED_FOR_PROGRESSION,
            DoseOutcome.VARIED_AT_REMEMBERED_LOAD,
            DoseOutcome.VARIED_FOR_SESSION_INTENT,
        )

    @property
    def reason(self) -> str:
        return _DOSE_OUTCOME_REASON[self]


_DOSE_OUTCOME_REASON: dict[DoseOutcome, str] = {
    DoseOutcome.VARIED: "scheme changed",
    DoseOutcome.VARIED_FOR_STRAIN: (
        "the dose was re-solved against a volume target reduced by today's "
        "readiness -- session time is still preserved, the load is not. "
        "Readiness is named ahead of session intent even when both moved the "
        "target, because being backed off for strain is the fact that matters. "
        "Check the variation's `readiness` for the evidence"
    ),
    DoseOutcome.VARIED_FOR_LOAD_MANAGEMENT: (
        "the dose was re-solved against a volume target moved by accumulated "
        "training load or by a taper toward a dated event -- see the "
        "variation's `load_management` for which of the two bound, and the "
        "acute:chronic figures behind it. Session time is preserved as usual"
    ),
    DoseOutcome.VARIED_FOR_PROGRESSION: (
        "the working load moved because of how the last session went -- see "
        "this entry's `progression` for the decision, the RPE it was read "
        "from, and the objective's target band it was read against"
    ),
    DoseOutcome.VARIED_AT_REMEMBERED_LOAD: (
        "the dose was re-solved against what this user can currently lift "
        "rather than the weight written in the routine, with no progression "
        "decision on top. The routine's own number was simply stale"
    ),
    DoseOutcome.VARIED_FOR_SESSION_INTENT: (
        "the dose was re-solved against a volume target moved by the user's "
        "requested session effort, with readiness either unknown or not "
        "binding. Session time is preserved either way -- 'harder' means more "
        "total work in the same window, not a longer session"
    ),
    DoseOutcome.UNVARIED_NOT_REPS_DOSE: (
        "dose is not sets x reps x weight, and no search exists for duration, "
        "distance or rounds doses yet"
    ),
    DoseOutcome.UNVARIED_MODALITY_MISMATCH: (
        "the exercise's modality is not the one this objective prescribes in"
    ),
    DoseOutcome.UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE: (
        "no nearby scheme falls inside this objective's set/rep range -- the "
        "search stays near the current scheme by design, so an entry far "
        "outside the range is left alone rather than jumped into it"
    ),
    DoseOutcome.UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE: (
        "schemes were available but none preserved both volume and time within "
        "tolerance"
    ),
    DoseOutcome.UNVARIED_HOLDING_INTENSITY: (
        "this objective preserves load rather than volume, and no nearby scheme "
        "carried the same total work at the same bar weight. Repeating the "
        "prescription is the intended outcome here, not a failed search: "
        "strength is trained by repeating a movement, and the load moves "
        "through progression once the session is logged, not through the scheme "
        "search"
    ),
    DoseOutcome.UNVARIED_LOAD_EXCEEDS_EQUIPMENT: (
        "every scheme that preserved the dose implied a load heavier than the "
        "user's heaviest available weight. Note this checks solved candidate "
        "loads only -- an input routine already prescribing more than the user "
        "owns is not flagged"
    ),
    DoseOutcome.UNVARIED_ADJUSTMENT_BELOW_WEIGHT_INCREMENT: (
        "today's readiness or session intent called for a different load, but "
        "the change was smaller than one weight increment and rounded straight "
        "back onto the prescribed weight. The entry is genuinely unchanged -- "
        "lower `weight_increment` if the equipment allows finer jumps"
    ),
}


@dataclass(frozen=True)
class EntryVariation:
    """One entry's variation result.

    ``exercise_outcome`` and ``dose_outcome`` are independent: an entry can
    have its exercise swapped while its dose passes through untouched (a cardio
    swap keeps its rounds dose), and vice versa."""

    entry: RoutineEntry
    dose_outcome: DoseOutcome
    exercise_outcome: ExerciseOutcome
    #: What history said this entry's load should be built from (M8b). ``None``
    #: when no memory was supplied, which is not the same as
    #: ``ProgressionDecision.NO_HISTORY`` -- that means memory was consulted and
    #: had nothing on this movement.
    progression: ExerciseProgression | None = None

    @property
    def exercise_substituted(self) -> bool:
        return self.exercise_outcome in (
            ExerciseOutcome.SUBSTITUTED_FOR_VARIETY,
            ExerciseOutcome.SUBSTITUTED_FOR_CONSTRAINT,
        )

    @property
    def is_unsafe(self) -> bool:
        """A contraindicated exercise survived into the output.

        Never let this pass silently: the entry is in the returned routine, so
        anything rendering or executing it has to check."""
        return self.exercise_outcome is ExerciseOutcome.BLOCKED_NO_LEGAL_ALTERNATIVE


@dataclass(frozen=True)
class RoutineVariation:
    """A varied routine plus the per-entry account of how it got that way.

    ``entry_variations[i].entry`` is ``routine.entries[i]`` -- the same object,
    offered both ways so callers that only want the routine are not forced to
    reassemble it.

    ``readiness``, ``session_intent`` and ``load_management`` are carried here
    rather than per entry because they are facts about the person and the
    session, not about any exercise. All must be surfaced: a routine whose loads
    came back 25% lighter with no explanation reads as a bug, and when several
    moved the target only one of them gets named in the per-entry
    ``dose_outcome``."""

    routine: Routine
    entry_variations: tuple[EntryVariation, ...]
    readiness: ReadinessAssessment | None = None
    session_intent: SessionIntent = SessionIntent.MODERATE
    #: Empty when no session log and no target event were supplied (M8c).
    load_management: LoadManagementAssessment | None = None
    load_multiplier: float = 1.0
    #: The substitution probability actually used, after the objective's
    #: ``VariationPolicy`` capped it. Carried for the same reason
    #: ``load_multiplier`` is: a caller that asked for 0.8 and silently got 0.1
    #: has no way to tell whether the engine ignored it or the objective
    #: overruled it.
    substitution_prob: float = DEFAULT_SUBSTITUTION_PROB
    #: Empty when no ``TrainingMemory`` was supplied -- the routine was varied,
    #: not programmed.
    progression: ProgressionPlan = field(default_factory=ProgressionPlan.none)

    @property
    def intent_capped_by_readiness(self) -> bool:
        """The user asked for more work than their readiness allowed.

        The rule itself lives in ``variation_context.intent_exceeds``, which
        carries the argument for why an invisible cancellation has to be
        reported. Kept as a property here because a caller holding a variation
        should not have to go back to the context to ask."""
        return intent_exceeds(self.session_intent, self.readiness)

    @property
    def intent_capped_by_load_management(self) -> bool:
        """The same invisible case by the other route (M8c): a ``CHALLENGING``
        session during a taper, or in a week already running ahead of the
        four-week average, capped back to baseline volume."""
        return intent_exceeds(self.session_intent, self.load_management)


def _retarget_outcome(
    context: VariationContext, progression: ExerciseProgression | None
) -> DoseOutcome:
    """Which input gets named when the volume target moved.

    Four can move it at once, so this picks a headline in priority order:
    readiness first because backing off for strain is the safety-relevant
    fact, then load management because an accumulated-load cut is the other
    protective one, then progression because it changed the *programme* rather
    than just today, then intent. The same principle already makes the
    equipment load cap outrank a tolerance. The full breakdown is always on
    the ``EntryVariation`` and ``RoutineVariation`` -- this only decides which
    single label a reader sees first."""
    if context.readiness is not None and context.readiness.modulates_load:
        return DoseOutcome.VARIED_FOR_STRAIN
    if context.load_management is not None and context.load_management.modulates_load:
        return DoseOutcome.VARIED_FOR_LOAD_MANAGEMENT
    if progression is not None and progression.moves_load:
        return DoseOutcome.VARIED_FOR_PROGRESSION
    if context.session_intent.load_multiplier != 1.0:
        return DoseOutcome.VARIED_FOR_SESSION_INTENT
    # The reference load came from history but the decision was to hold: the
    # target still moved, because the routine's own weight was stale.
    return DoseOutcome.VARIED_AT_REMEMBERED_LOAD


def vary_entry(
    entry: RoutineEntry,
    db: ExerciseDB,
    rng: random.Random,
    *,
    objective: ObjectiveStrategy,
    context: VariationContext,
    progression: ProgressionPlan,
    substitution_prob: float,
    volume_tolerance: float,
    time_tolerance: float,
    weight_increment: float,
    allow_equipment_change: bool,
) -> EntryVariation:
    source = db[entry.exercise_id]
    exercise_id = entry.exercise_id

    # An impermissible prescription is replaced whatever the novelty dial says.
    # Substituting for safety is not a stylistic choice.
    must_replace = not context.permits(source)
    if must_replace or rng.random() < substitution_prob:
        permitted = [
            candidate
            for candidate in db.find_substitutes(
                exercise_id, allow_equipment_change=allow_equipment_change
            )
            if context.permits(candidate)
        ]
        if not permitted and must_replace:
            # Substitution normally holds the movement pattern fixed. When the
            # pattern is *itself* what makes the exercise impermissible, that
            # guarantees every candidate is impermissible too -- a blocked
            # overhead press has only other overhead presses as substitutes.
            # Widen to the shared target muscle so the entry still trains what
            # it was there to train, by a route this user is allowed to take.
            permitted = [
                candidate
                for candidate in db.find_substitutes(
                    exercise_id,
                    allow_equipment_change=allow_equipment_change,
                    require_same_movement_pattern=False,
                )
                if context.permits(candidate)
            ]
        if permitted:
            # find_substitutes never returns the source itself, so any draw
            # here is a genuine swap.
            exercise_id = rng.choice(best_matches(source, permitted, context)).id
            exercise_outcome = (
                ExerciseOutcome.SUBSTITUTED_FOR_CONSTRAINT
                if must_replace
                else ExerciseOutcome.SUBSTITUTED_FOR_VARIETY
            )
        elif must_replace:
            exercise_outcome = ExerciseOutcome.BLOCKED_NO_LEGAL_ALTERNATIVE
        else:
            exercise_outcome = ExerciseOutcome.KEPT
    else:
        exercise_outcome = ExerciseOutcome.KEPT

    def unvaried(outcome: DoseOutcome) -> EntryVariation:
        return EntryVariation(
            entry=RoutineEntry(exercise_id=exercise_id, dose=entry.dose, rest_seconds=entry.rest_seconds),
            dose_outcome=outcome,
            exercise_outcome=exercise_outcome,
        )

    dose = entry.dose
    if not isinstance(dose, RepsDose):
        return unvaried(DoseOutcome.UNVARIED_NOT_REPS_DOSE)
    if db[exercise_id].modality is not objective.preferred_modality:
        return unvaried(DoseOutcome.UNVARIED_MODALITY_MISMATCH)

    # The load this entry's volume target is built from. The routine's own
    # weight is only the fallback: once there is history, what the user can
    # currently lift outranks what the YAML was written with, or six weeks of
    # progression would be undone on every run (M8b).
    # Resolved for the *final* exercise id, after any substitution. A user's
    # barbell bench history says nothing about their dumbbell press, so a
    # swapped entry correctly falls back to the routine's own weight.
    entry_progression = progression.for_exercise(exercise_id)
    reference_load = progression.load_for(
        exercise_id, reps=dose.reps, fallback_kg=dose.weight
    )
    reference_volume = dose.sets * dose.reps * reference_load

    schemes = objective.candidate_rep_schemes(dose.sets, dose.reps)
    rng.shuffle(schemes)

    # The target differs from the routine's own volume when history moved the
    # reference load, or when strain and session intent scale it. Both are 1:1
    # no-ops when nothing is known and nothing is asked, so a caller supplying
    # neither sees the original volume-preserving behaviour exactly.
    retargeted = context.load_multiplier != 1.0 or reference_volume != dose.load_volume
    if retargeted:
        # Against a moved target, keeping the current scheme is no longer a
        # no-op -- it is the same sets and reps at a different load, which is
        # exactly what a deload (or a heavier session) looks like. Appended
        # last so a genuine scheme change still wins when one fits, and
        # appended unconditionally so the adjustment also reaches an entry
        # sitting outside the objective's range, which the scheme search
        # deliberately refuses to touch.
        schemes.append((dose.sets, dose.reps))
    if not schemes:
        return unvaried(DoseOutcome.UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE)

    target_volume = reference_volume * context.load_multiplier
    original_time = entry.time_seconds
    min_rest, max_rest = objective.rest_range_seconds
    load_capped_a_candidate = False
    adjustment_rounded_away = False

    # Which quantity this variation holds, and which one it lets float. Under
    # LOAD_VOLUME the load is solved per candidate scheme so that total work is
    # preserved; under INTENSITY that is inverted -- the bar weight is fixed at
    # the reference and total work becomes the residual the tolerance judges.
    #
    # ``intensity_target`` is therefore computed once, outside the loop, and
    # that independence from ``(cand_sets, cand_reps)`` *is* the invariant.
    #
    # Note the adaptive multiplier deliberately stays on the volume target and
    # is not moved onto the load: under INTENSITY a deload or a taper then takes
    # sets away and leaves the bar where it is, which is what both are for. That
    # is the shape a real taper has and the one a volume-solved load could not
    # express.
    hold_intensity = objective.variation_policy.preserved_invariant is Invariant.INTENSITY
    intensity_target = round_to_increment(reference_load, weight_increment)

    for cand_sets, cand_reps in schemes:
        cand_weight = (
            intensity_target
            if hold_intensity
            else round_to_increment(target_volume / (cand_sets * cand_reps), weight_increment)
        )
        if cand_weight <= 0:
            continue
        if (cand_sets, cand_reps, cand_weight) == (dose.sets, dose.reps, dose.weight):
            # Only reachable for the current scheme appended above, when the
            # adjusted target rounded straight back onto the prescription.
            # Nothing moved, so this must not be returned as if it had.
            #
            # Under INTENSITY it is not a rounding artefact at all: the load was
            # never what the adjustment was supposed to move -- the change was
            # meant to land on the scheme -- so reporting "lower your weight
            # increment" would send a reader after a fix that cannot help.
            if not hold_intensity:
                adjustment_rounded_away = True
            continue
        if not context.permits_load(cand_weight):
            load_capped_a_candidate = True
            continue
        cand_volume = cand_sets * cand_reps * cand_weight
        if pct_diff(cand_volume, target_volume) > volume_tolerance:
            continue

        # Solve rest so total time for this entry matches the original, at
        # this objective's tempo.
        cand_rest = original_time / cand_sets - cand_reps * objective.rep_seconds
        cand_rest = max(min_rest, min(max_rest, round(cand_rest / 5) * 5))
        cand_time = cand_sets * (cand_reps * objective.rep_seconds + cand_rest)
        if pct_diff(cand_time, original_time) > time_tolerance:
            continue

        return EntryVariation(
            entry=RoutineEntry(
                exercise_id=exercise_id,
                dose=RepsDose(
                    sets=cand_sets,
                    reps=cand_reps,
                    weight=cand_weight,
                    rep_seconds=objective.rep_seconds,
                ),
                rest_seconds=cand_rest,
            ),
            dose_outcome=(
                _retarget_outcome(context, entry_progression) if retargeted else DoseOutcome.VARIED
            ),
            exercise_outcome=exercise_outcome,
            progression=entry_progression,
        )

    # The load cap wins the explanation when it killed a candidate: it is a
    # fact about the user's equipment, which is more actionable than a
    # tolerance the caller chose.
    if load_capped_a_candidate:
        return unvaried(DoseOutcome.UNVARIED_LOAD_EXCEEDS_EQUIPMENT)
    if adjustment_rounded_away:
        return unvaried(DoseOutcome.UNVARIED_ADJUSTMENT_BELOW_WEIGHT_INCREMENT)
    if hold_intensity and not retargeted:
        # Kept apart from the tolerance case below because it means something
        # different to a reader: under an intensity-preserving objective a held
        # prescription is the correct answer rather than a search that came up
        # empty, and an app rendering it as a failure would be lying.
        #
        # ``not retargeted`` is load-bearing. When something *did* move the
        # target -- a deload, a taper, a progression step -- and no scheme could
        # express it at this bar weight, holding is a failure to deliver a
        # requested adjustment, not the intended outcome. Reporting that as
        # "this is deliberate" would be the same lie in the other direction.
        return unvaried(DoseOutcome.UNVARIED_HOLDING_INTENSITY)
    return unvaried(DoseOutcome.UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE)


def vary_routine(
    routine: Routine,
    db: ExerciseDB,
    *,
    objective: ObjectiveStrategy = DEFAULT_OBJECTIVE,
    context: VariationContext | None = None,
    memory: TrainingMemory | None = None,
    seed: int | None = None,
    substitution_prob: float | None = None,
    volume_tolerance: float = 0.075,
    time_tolerance: float = 0.10,
    weight_increment: float = 2.5,
    allow_equipment_change: bool = True,
) -> RoutineVariation:
    """Vary ``routine`` for one person.

    ``context`` is what makes the result personal -- health contraindications,
    equipment, dislikes. Omitting it means "no constraints known", which is a
    deliberate state rather than a default user: every exercise is permitted.

    ``memory`` is what makes the result *programmed* rather than merely varied
    (M8b). With it, each entry's load comes from what this user can currently
    lift, adjusted by how their last session went; without it the routine's own
    prescribed weight stands and the behaviour is exactly as it was before
    training history was read at all. It is a separate parameter from
    ``context`` because it is derived from the session log rather than resolved
    from the user's schema, and because a caller may legitimately want
    constraints without programming.

    ``substitution_prob`` left as ``None`` derives from the user's
    ``novelty_preference`` if the context carries one, falling back to
    ``DEFAULT_SUBSTITUTION_PROB``. The schema names that field as the dial this
    should come from, rather than a hard-coded constant."""
    resolved_context = context if context is not None else VariationContext.unconstrained()
    if substitution_prob is None:
        substitution_prob = (
            resolved_context.novelty_preference
            if resolved_context.novelty_preference is not None
            else DEFAULT_SUBSTITUTION_PROB
        )
    # The objective bounds it whatever the source, including an explicit
    # argument. How often a movement may rotate and still be trainable is a
    # property of the objective, not a preference and not a caller's choice --
    # the same tiering that stops a dislike vetoing a health constraint. A
    # caller that asked for more is told what it actually got, on
    # ``RoutineVariation.substitution_prob``.
    substitution_prob = min(
        substitution_prob, objective.variation_policy.max_substitution_prob
    )

    # Built once for the whole routine, not per entry: the same exercise listed
    # twice must not be progressed twice.
    progression = (
        ProgressionPlan.build(
            memory,
            objective=objective,
            prescribed_reps=_prescribed_reps(routine),
            weight_increment=weight_increment,
        )
        if memory is not None
        else ProgressionPlan.none()
    )

    rng = random.Random(seed)
    variations = tuple(
        vary_entry(
            entry,
            db,
            rng,
            objective=objective,
            context=resolved_context,
            progression=progression,
            substitution_prob=substitution_prob,
            volume_tolerance=volume_tolerance,
            time_tolerance=time_tolerance,
            weight_increment=weight_increment,
            allow_equipment_change=allow_equipment_change,
        )
        for entry in routine.entries
    )
    varied = Routine(
        name=f"{routine.name} (variation)",
        entries=[variation.entry for variation in variations],
    )
    return RoutineVariation(
        routine=varied,
        entry_variations=variations,
        readiness=resolved_context.readiness,
        session_intent=resolved_context.session_intent,
        load_management=resolved_context.load_management,
        load_multiplier=resolved_context.load_multiplier,
        substitution_prob=substitution_prob,
        progression=progression,
    )


def _prescribed_reps(routine: Routine) -> dict[str, int]:
    """The rep count each exercise is prescribed at, for the load lookup.

    Only ``RepsDose`` entries have one, and only they can be progressed. An
    exercise appearing twice at different rep counts keeps the first, which is
    a real limitation -- see the ``vary_entry`` note on repeated exercises."""
    return {
        entry.exercise_id: entry.dose.reps
        for entry in reversed(routine.entries)
        if isinstance(entry.dose, RepsDose)
    }
