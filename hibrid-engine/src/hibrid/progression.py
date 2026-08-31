"""M8b: what last session says about this session's load.

The step that turns variation into programming. Everything before it treated
the input routine as the reference point on every run, which means a routine
progressed for six weeks would keep being measured against the numbers it was
written with -- the user creeps up to 92.5 kg and the engine keeps handing them
back 80. This module supplies the *remembered* target instead.

Two things are deliberately separate here, and conflating them is the mistake
this module exists to avoid:

* **The reference load** -- what this user is currently good for on this
  movement, derived from their estimated 1RM at the rep count being prescribed
  (``TrainingMemory.working_load``). This is history, not a judgement.
* **The progression decision** -- whether today should go up, hold, or come
  down, read from how the *last* session actually went. This is a judgement,
  and it moves the reference by at most one weight increment.

The decision is anchored on **RPE against the objective's own target band**,
which is what finally consumes ``ObjectiveStrategy.target_rpe_range`` --
declared since M2 and read by nothing until now. RPE rather than a fixed weekly
increment because the engine varies the rep scheme every session by design, so
there is no stable "same lift, more reps" ladder to climb; effort is the only
signal that stays comparable when the scheme moves underneath it.

**How this composes with everything else that touches load**, since there are
now four things and the order matters:

    input routine        gives the shape: sets x reps, and a fallback weight
    training memory      replaces the weight with what they can actually lift
    progression          moves that by one increment, up or down
    intent x readiness   scales the whole target for today

Each layer degrades to a no-op independently. No history means the input
routine's weight stands, exactly as before M8b existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hibrid.objective_strategy import ObjectiveStrategy
from hibrid.training_memory import LastPerformance, TrainingMemory


class ProgressionDecision(str, Enum):
    """Why this exercise's load moved, or did not.

    ``NO_HISTORY`` is kept apart from ``HELD`` for the same reason
    ``ReadinessState.UNKNOWN`` is kept apart from ``NORMAL``: "we have never
    seen this movement" and "we looked and today is not the day" are different
    facts, and only one of them is a judgement.
    """

    NO_HISTORY = "no_history"
    PROGRESSED = "progressed"
    HELD = "held"
    BACKED_OFF = "backed_off"

    @property
    def reason(self) -> str:
        return _DECISION_REASON[self]


_DECISION_REASON: dict[ProgressionDecision, str] = {
    ProgressionDecision.NO_HISTORY: (
        "this movement has no usable history, so the routine's own prescribed "
        "weight stands. Not a judgement that it is correct -- just the only "
        "number available"
    ),
    ProgressionDecision.PROGRESSED: (
        "last session came in easier than this objective's target effort, so "
        "the working load went up by one weight increment"
    ),
    ProgressionDecision.HELD: (
        "last session landed inside this objective's target effort band, or "
        "showed a reason not to add load yet -- missed reps or technique "
        "breaking down. The working load is unchanged"
    ),
    ProgressionDecision.BACKED_OFF: (
        "last session was harder than this objective's target effort, or pain "
        "was reported, so the working load came down by one weight increment"
    ),
}


@dataclass(frozen=True)
class ExerciseProgression:
    """One exercise's resolved load for this session, and the reason for it."""

    exercise_id: str
    decision: ProgressionDecision
    #: From history, before the decision was applied. ``None`` when there is no
    #: usable estimate -- a bodyweight movement, or one only ever trained in
    #: sets too long for a rep-max formula to speak about.
    reference_load_kg: float | None = None
    #: What to actually prescribe. ``None`` means "use the routine's weight".
    working_load_kg: float | None = None
    observed_rpe: float | None = None
    target_rpe_range: tuple[float, float] | None = None

    @property
    def moves_load(self) -> bool:
        return self.decision in (
            ProgressionDecision.PROGRESSED,
            ProgressionDecision.BACKED_OFF,
        )

    def explain(self) -> str:
        detail = self.decision.reason
        if self.observed_rpe is not None and self.target_rpe_range is not None:
            low, high = self.target_rpe_range
            detail += f" (RPE {self.observed_rpe:.1f} against a {low:.0f}-{high:.0f} target)"
        if self.reference_load_kg is not None and self.working_load_kg is not None:
            detail += f"; {self.reference_load_kg:.1f}kg -> {self.working_load_kg:.1f}kg"
        return detail


@dataclass(frozen=True)
class ProgressionPlan:
    """Every exercise's resolved load for one session.

    Built once per routine rather than per entry, so the same exercise
    appearing twice cannot be progressed twice.
    """

    progressions: dict[str, ExerciseProgression]

    def for_exercise(self, exercise_id: str) -> ExerciseProgression | None:
        return self.progressions.get(exercise_id)

    def load_for(self, exercise_id: str, *, reps: int, fallback_kg: float) -> float:
        """The load to build this entry's volume target from.

        ``fallback_kg`` is the routine's own prescribed weight, which stands
        whenever history cannot improve on it. Callers pass it rather than
        branching, so "no history" is a value here and not a control-flow
        special case at every use site."""
        progression = self.progressions.get(exercise_id)
        if progression is None or progression.working_load_kg is None:
            return fallback_kg
        return progression.working_load_kg

    @property
    def is_empty(self) -> bool:
        return not self.progressions

    @classmethod
    def none(cls) -> "ProgressionPlan":
        """No history consulted. Named, so "not programming" is explicit."""
        return cls(progressions={})

    @classmethod
    def build(
        cls,
        memory: TrainingMemory,
        *,
        objective: ObjectiveStrategy,
        prescribed_reps: dict[str, int],
        weight_increment: float,
    ) -> "ProgressionPlan":
        """Resolve every exercise the routine prescribes.

        ``prescribed_reps`` carries the rep count each exercise is being
        prescribed at, because the reference load depends on it -- 100 kg for
        a triple and 100 kg for a set of ten are not the same claim about a
        person. Keyed by exercise so the caller does the routine-walking and
        this stays a pure function of history plus intent.
        """
        return cls(
            progressions={
                exercise_id: _resolve(
                    exercise_id=exercise_id,
                    memory=memory,
                    objective=objective,
                    reps=reps,
                    weight_increment=weight_increment,
                )
                for exercise_id, reps in prescribed_reps.items()
            }
        )


def _resolve(
    *,
    exercise_id: str,
    memory: TrainingMemory,
    objective: ObjectiveStrategy,
    reps: int,
    weight_increment: float,
) -> ExerciseProgression:
    reference = memory.working_load(exercise_id, reps)
    last = memory.last_performance(exercise_id)

    if reference is None or last is None:
        return ExerciseProgression(
            exercise_id=exercise_id, decision=ProgressionDecision.NO_HISTORY
        )

    decision = _decide(last, objective)
    working = reference
    if decision is ProgressionDecision.PROGRESSED:
        working = reference + weight_increment
    elif decision is ProgressionDecision.BACKED_OFF:
        # Never below one increment: a working load of zero is not a deload, it
        # is a bodyweight exercise, and the two must not be confused downstream.
        working = max(weight_increment, reference - weight_increment)

    return ExerciseProgression(
        exercise_id=exercise_id,
        decision=decision,
        reference_load_kg=reference,
        working_load_kg=working,
        observed_rpe=last.mean_rpe,
        target_rpe_range=objective.target_rpe_range,
    )


def _decide(last: LastPerformance, objective: ObjectiveStrategy) -> ProgressionDecision:
    """Read one session's outcome against the objective's target effort.

    Order matters: the safety-side signals are checked before the effort
    comparison, because a session that hurt or fell apart technically is not
    made progressable by a comfortable RPE. A user reporting low effort *and*
    pain is describing a joint that let go, not an easy day.
    """
    if last.pain_reported:
        return ProgressionDecision.BACKED_OFF
    if last.form_breakdown:
        # The schema names this exactly: "a signal to hold load rather than
        # progress it". Holding, not backing off -- technique breaking down at
        # a load they can otherwise handle is a skill problem, and stripping
        # weight does not train the skill.
        return ProgressionDecision.HELD
    if last.met_prescribed_reps is False:
        # Deliberately `is False`, not falsy: None means nothing was prescribed
        # to compare against, and an unplanned session is not a failed one.
        return ProgressionDecision.HELD

    observed = last.mean_rpe
    if observed is None:
        # No effort data means no basis for a judgement. Holding is the honest
        # default; progressing on silence would add load every single session
        # for any user who never logs RPE.
        return ProgressionDecision.HELD

    low, high = objective.target_rpe_range
    if observed < low:
        return ProgressionDecision.PROGRESSED
    if observed > high:
        return ProgressionDecision.BACKED_OFF
    return ProgressionDecision.HELD
