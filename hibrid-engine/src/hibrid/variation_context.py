"""The bridge from the V2 user schema to the engine — M3.

This is the first module that reads ``hibrid.user`` as *data about a person*
rather than as a shared vocabulary. It resolves a ``User`` (or the parts of one
that matter here) into the flat, pre-computed sets the candidate search needs,
so the hot path never walks an injury list per exercise.

The tiers are kept apart because they are not interchangeable, and the schema is
explicit that conflating them is the mistake to avoid:

* **Inviolable** — health contraindications. Never traded against an objective.
* **Hard** — equipment the user does not have, movements they have excluded
  outright. Violating one yields a routine they physically cannot execute.
* **Soft** — dislikes and preferences. Violating one yields a routine they
  *can* execute but won't enjoy, so it is a cost, never an exclusion.
* **Adaptive** — today's strain (pass 2), today's `SessionIntent`, and
  accumulated load across the block (M8c). Unlike the three above, these say
  nothing about *which* exercises are allowed; they scale *how much* work the
  permitted ones carry, and they are the only inputs that differ between two
  runs of the same routine for the same person.

``permits()`` answers the first two. ``preference_score()`` answers the third,
and deliberately cannot veto anything. ``load_multiplier`` answers the fourth
and likewise cannot veto anything — an adjusted session is lighter or heavier,
never a filtered exercise pool.

The adaptive tier holds three inputs rather than one because they are different
in kind and must not be conflated. Readiness is a *measurement* of the user,
baseline-relative and downward-only, and about *today*. `SessionIntent` is a
*directive from* the user, needing no baseline and permitted to raise the target
within a narrow band. `LoadManagementAssessment` is about neither today nor what
the user wants: it reads the last four weeks of logged work, plus any dated
event they are training toward. They compose by multiplication; see
`load_multiplier`.

Deliberately NOT read, to be honest about the gap rather than to imply
coverage:

* ``MedicalConsideration``'s structured effect flags (``limits_overhead_work``,
  ``limits_high_impact``, ``caps_max_heart_rate``,
  ``limits_valsalva_or_breath_holding``, ``limits_supine_positions``). Each
  needs a clinical mapping onto movement patterns or modalities that should be
  decided deliberately, not guessed at here. Their
  ``contraindicated_movement_patterns`` / ``contraindicated_exercise_ids``
  *are* read, via ``HealthProfile``'s properties.
* Session-duration budgets. Variation preserves time by construction, so a
  time budget binds *generation* (roadmap M5), not variation: if the input
  routine already fits, the output does too, and if it does not, varying it
  cannot help.
* Objective weight vectors. A blend still has nowhere to route to for half the
  objectives it can name — roadmap M4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from hibrid.exercise_db import ExerciseDB
from hibrid.load_management import LoadManagementAssessment, LoadMetric, next_target_event
from hibrid.models import Equipment, Exercise, MovementPattern
from hibrid.readiness import ReadinessAssessment
from hibrid.user.biometrics import RecoveryReading, WellnessCheckIn
from hibrid.user.enums import TrainingEnvironment
from hibrid.user.health import HealthProfile
from hibrid.user.history import TrainingSession
from hibrid.user.objectives import TargetEvent
from hibrid.user.preferences import EquipmentAccess, TrainingPreferences
from hibrid.user.user import User

#: Score adjustments applied to a candidate's similarity when ranking
#: substitutes. Small relative to the similarity scale (0-1) on purpose: a
#: preference nudges the choice between comparable candidates, it does not
#: promote an unsuitable exercise over a suitable one.
DISLIKE_PENALTY = 0.15
PREFERENCE_BONUS = 0.10


class SessionIntent(str, Enum):
    """How hard the user has asked *this* session to be.

    A directive, not a measurement -- which is what makes it different in kind
    from ``ReadinessAssessment``. "How recovered are you?" asks the user to
    describe their body and leaves the engine to decide; "how hard do you want
    this?" is the user deciding. That difference has three consequences worth
    stating, because they are why this is a separate field rather than another
    signal folded into readiness:

    * **It needs no baseline.** A self-reported 1-10 score is only meaningful
      against the same person's own history, which is why ``readiness.py``
      declines to judge until it has one. "Light" means light on install day.
    * **It is not health data.** A stated preference for an easier session says
      nothing about the user's body, unlike a recovery score. See HANDOFF.md
      §4 for why that distinction is worth preserving.
    * **It cannot protect the user from themselves.** Whoever is most likely to
      pick ``CHALLENGING`` every day is exactly the person deloading exists
      for. That is the entire reason readiness is kept alongside it rather
      than replaced by it -- see ``VariationContext.load_multiplier``.

    Three levels rather than five: the steps have to be large enough to produce
    a visibly different session, and a finer scale reintroduces the calibration
    problem ("is my 6 your 6?") that choosing words over numbers avoids.
    """

    LIGHT = "light"
    MODERATE = "moderate"
    CHALLENGING = "challenging"

    @property
    def load_multiplier(self) -> float:
        """What to scale the volume target by. ``MODERATE`` is exactly 1.0, so
        the default composes to a no-op."""
        return _INTENT_MULTIPLIER[self]

    @property
    def reason(self) -> str:
        return _INTENT_REASON[self]


#: Deliberately a narrow band. A session-to-session choice is not progression:
#: sustained overreaching is what periodization exists to manage (roadmap M8),
#: and a dial wide enough to self-prescribe a 50% jump would quietly become a
#: progression mechanism with none of the safeguards.
_INTENT_MULTIPLIER: dict[SessionIntent, float] = {
    SessionIntent.LIGHT: 0.85,
    SessionIntent.MODERATE: 1.0,
    SessionIntent.CHALLENGING: 1.15,
}

_INTENT_REASON: dict[SessionIntent, str] = {
    SessionIntent.LIGHT: "the user asked for an easier session than usual",
    SessionIntent.MODERATE: "the user asked for a normal session, so the prescribed volume stands",
    SessionIntent.CHALLENGING: (
        "the user asked for a harder session than usual. Note this raises total "
        "work at the same session length, not the weight on a top set -- the "
        "engine solves load from volume and has no 1RM model yet"
    ),
}


class LoadModulator(Protocol):
    """Anything in the adaptive tier that can scale the volume target.

    A ``Protocol`` rather than a base class because ``ReadinessAssessment`` and
    ``LoadManagementAssessment`` are unrelated in every other respect -- one
    reads a wearable against a 28-day baseline, the other reads four weeks of
    logged sessions -- and the only thing worth sharing is the pair of questions
    below. Exists so ``intent_exceeds`` can be written once for both."""

    @property
    def load_multiplier(self) -> float: ...

    @property
    def modulates_load(self) -> bool: ...


def intent_exceeds(intent: SessionIntent, modulator: LoadModulator | None) -> bool:
    """Whether the user asked for more work than a protective term allowed.

    Needed because the interesting case is *invisible* in the numbers:
    ``CHALLENGING`` against a ``SUPPRESSED`` readiness composes to exactly 1.0,
    so the dose is volume-preserving and every downstream outcome honestly reads
    as an ordinary variation. Without this, the user asked for a hard session,
    got a normal one, and nothing anywhere says why.

    Asked of one modulator at a time, never of the final composed multiplier:
    comparing against the combined number would blame readiness for a taper's
    doing. Lives here rather than on ``RoutineVariation`` because generation
    needs the same answer from a bare context, and two copies of this rule would
    drift.
    """
    if modulator is None or not modulator.modulates_load:
        return False
    return intent.load_multiplier * modulator.load_multiplier > 1.0


@dataclass(frozen=True)
class VariationContext:
    """Everything about one person that constrains varying one routine.

    A stdlib dataclass rather than a pydantic model, matching ``hibrid.models``:
    by the time this exists the untrusted input has already been validated, and
    it sits on the candidate-search hot path. Validation belongs at the
    ``hibrid.user`` / ``hibrid.api`` boundary it was resolved from.

    ``None`` means *unconstrained*, which is not the same as an empty set:
    ``available_equipment=None`` is "equipment unknown, allow anything", while
    ``frozenset()`` is "this person has no equipment at all".
    """

    # --- Inviolable ---
    blocked_movement_patterns: frozenset[MovementPattern] = frozenset()
    blocked_exercise_ids: frozenset[str] = frozenset()

    # --- Hard ---
    available_equipment: frozenset[Equipment] | None = None
    allowed_exercise_ids: frozenset[str] | None = None
    excluded_movement_patterns: frozenset[MovementPattern] = frozenset()
    excluded_exercise_ids: frozenset[str] = frozenset()
    max_load_kg: float | None = None

    # --- Soft ---
    disliked_exercise_ids: frozenset[str] = frozenset()
    preferred_exercise_ids: frozenset[str] = frozenset()
    novelty_preference: float | None = None

    # --- Adaptive ---
    #: ``None`` means no readings were supplied at all, which is a weaker
    #: statement than ``ReadinessState.UNKNOWN`` (readings existed but could
    #: not support a baseline). Both leave the dose alone; only one of them
    #: means anyone looked.
    readiness: ReadinessAssessment | None = None

    #: What the user asked for today. Defaults to a no-op, so a caller that
    #: never surfaces the control behaves exactly as before it existed.
    session_intent: SessionIntent = SessionIntent.MODERATE

    #: What the last four weeks of logged work, and any dated event, say about
    #: today (M8c). ``None`` means no session log was supplied at all, which is
    #: weaker than ``WorkloadState.UNKNOWN`` -- sessions existed but could not
    #: support a comparison.
    load_management: LoadManagementAssessment | None = None

    @property
    def _protective_multiplier(self) -> float:
        """Everything that can only ever reduce the dose, combined.

        Readiness and load management **multiply** rather than one overriding
        the other because they are about different time scales and both answers
        are real: one is how this body woke up, the other is what the last four
        weeks have already cost it. A user who is acutely wrecked *and*
        chronically overloaded has earned both reductions. (Within load
        management the two protective terms take the deeper cut instead of
        compounding -- see ``LoadManagementAssessment.load_multiplier`` for why
        that case is different.)
        """
        readiness = self.readiness.load_multiplier if self.readiness else 1.0
        management = self.load_management.load_multiplier if self.load_management else 1.0
        return readiness * management

    @property
    def load_multiplier(self) -> float:
        """What to scale an entry's volume target by, all in.

        The inputs **multiply** rather than one overriding the other, because
        they answer different questions and every answer is real: intent is what
        the user wants, readiness is what their body will tolerate today, load
        management is what the block has already spent. Not one of them is
        silently discarded, and ``RoutineVariation`` carries all three so the
        output can say which one moved the number.

        **Multiplying is not sufficient on its own**, which is worth spelling
        out because it looks like it should be. ``CHALLENGING`` (1.15) against
        a merely ``SUPPRESSED`` readiness (0.90) multiplies to 1.035 -- a user
        whose own baseline says they are under-recovered would be handed *more*
        work than their normal prescription, which is precisely the outcome the
        adaptive tier exists to prevent. So a binding protective term also
        **caps the result at 1.0**: a user showing suppression, or tapering for
        a race, never gets above their baseline volume however they answered.

        What survives the cap is the ordering. Suppressed-and-challenging still
        beats suppressed-and-moderate, which still beats suppressed-and-light,
        so the user's answer visibly changed something even when their body
        overruled the ambition in it.

        Always exactly ``1.0`` when nothing is known and nothing is asked, so
        callers multiply unconditionally instead of branching.
        """
        protective = self._protective_multiplier
        combined = self.session_intent.load_multiplier * protective
        return min(combined, 1.0) if protective < 1.0 else combined

    def permits(self, exercise: Exercise) -> bool:
        """Whether this exercise may be prescribed at all.

        Inviolable and hard constraints only. A disliked exercise is permitted
        -- that is the entire distinction between a dislike and an exclusion.
        """
        if exercise.id in self.blocked_exercise_ids or exercise.id in self.excluded_exercise_ids:
            return False

        pattern = exercise.movement_pattern
        if pattern is None:
            # Movement pattern is derived at import and absent for ~6% of the
            # library, where it means *unknown* rather than *none*. The two
            # tiers must treat that differently:
            #
            # Health blocks fail CLOSED -- not knowing whether this is the
            # contraindicated movement is not a reason to hand it to someone it
            # could injure. The cost is a slightly smaller candidate pool; the
            # alternative cost is an injury.
            #
            # Preference exclusions fail OPEN -- the user said "no squats", and
            # an unclassified exercise is not knowingly a squat. Over-applying
            # a preference is a worse trade than under-applying it.
            if self.blocked_movement_patterns:
                return False
        elif pattern in self.blocked_movement_patterns or pattern in self.excluded_movement_patterns:
            return False

        if self.allowed_exercise_ids is not None and exercise.id in self.allowed_exercise_ids:
            # An explicit allowlist entry answers the equipment question by
            # itself -- it exists precisely for inventory an equipment category
            # cannot express.
            return True
        if self.available_equipment is not None and exercise.equipment not in self.available_equipment:
            return False
        return True

    def permits_load(self, load_kg: float) -> bool:
        """Whether a solved load is actually liftable with what they own."""
        return self.max_load_kg is None or load_kg <= self.max_load_kg

    def preference_score(self, exercise: Exercise) -> float:
        """Soft adjustment to a candidate's ranking. Never a veto."""
        score = 0.0
        if exercise.id in self.disliked_exercise_ids:
            score -= DISLIKE_PENALTY
        if exercise.id in self.preferred_exercise_ids:
            score += PREFERENCE_BONUS
        return score

    @property
    def intent_capped_by_readiness(self) -> bool:
        """The user asked for more work than their readiness allowed. See
        ``intent_exceeds`` for why this has to be reported at all."""
        return intent_exceeds(self.session_intent, self.readiness)

    @property
    def intent_capped_by_load_management(self) -> bool:
        """The same cancellation by the other route: a hard session asked for
        during a taper, or in a week already ahead of the four-week average."""
        return intent_exceeds(self.session_intent, self.load_management)

    def without_adaptive_load(self) -> "VariationContext":
        """The same person and the same constraints, at baseline volume.

        Drops the whole adaptive tier -- session intent, readiness and
        accumulated load -- and keeps the other three intact. Needed wherever a
        dose has *already* been solved against ``load_multiplier`` and is being
        re-solved: applying the multiplier a second time compounds it, so a
        ``CHALLENGING`` session would climb 15% on every re-roll and a
        suppressed one would sink 10%. The first consumer is
        ``session_generation.vary_block`` -- a generated block's prescribed
        weight already embodies today's adjustment, and re-rolling that block
        must change the work, not the amount of it.

        Health, equipment and preferences are deliberately untouched: those are
        facts about what the user may do, and nothing about re-solving a dose
        makes a contraindication less true.
        """
        return replace(
            self,
            session_intent=SessionIntent.MODERATE,
            readiness=None,
            load_management=None,
        )

    @classmethod
    def unconstrained(cls) -> "VariationContext":
        """The no-user-supplied default: every exercise permitted.

        Named rather than left implicit so that "no context" is an explicit
        state in the engine instead of a scattering of ``if context is not
        None`` checks.
        """
        return cls()

    @classmethod
    def from_parts(
        cls,
        *,
        health: HealthProfile | None = None,
        preferences: TrainingPreferences | None = None,
        environment: TrainingEnvironment | None = None,
        recovery: Sequence[RecoveryReading] = (),
        wellness: Sequence[WellnessCheckIn] = (),
        sessions: Sequence[TrainingSession] = (),
        target_event: TargetEvent | None = None,
        load_metric: LoadMetric = LoadMetric.SESSION_RPE,
        as_of: datetime | None = None,
        session_intent: SessionIntent = SessionIntent.MODERATE,
    ) -> "VariationContext":
        """Resolve the V2 models that bear on variation.

        ``environment`` selects which ``EquipmentAccess`` applies, since access
        is modelled per environment -- a full gym on weekdays, bodyweight only
        when travelling. Without one, the entry marked ``is_default`` wins, then
        the first listed.

        ``recovery`` / ``wellness`` are the *whole* histories, not just the
        latest reading: the assessment is baseline-relative, so it needs the
        trailing window to compare against. ``sessions`` is the whole training
        log for the same reason -- the acute:chronic ratio compares this week
        against the four before it, so a week of sessions on its own yields no
        assessment at all. ``as_of`` is the moment being planned for, defaulting
        to now.
        """
        moment = as_of if as_of is not None else datetime.now(timezone.utc)
        access = _select_equipment_access(preferences, environment)
        return cls(
            blocked_movement_patterns=health.blocked_movement_patterns if health else frozenset(),
            blocked_exercise_ids=health.blocked_exercise_ids if health else frozenset(),
            available_equipment=access.available_equipment if access else None,
            allowed_exercise_ids=(
                access.available_exercise_ids if access and access.available_exercise_ids else None
            ),
            excluded_movement_patterns=(
                preferences.excluded_movement_patterns if preferences else frozenset()
            ),
            excluded_exercise_ids=preferences.excluded_exercise_ids if preferences else frozenset(),
            max_load_kg=access.max_load_kg if access else None,
            disliked_exercise_ids=preferences.disliked_exercise_ids if preferences else frozenset(),
            preferred_exercise_ids=preferences.preferred_exercise_ids if preferences else frozenset(),
            novelty_preference=preferences.novelty_preference if preferences else None,
            readiness=(
                ReadinessAssessment.assess(recovery=recovery, wellness=wellness, as_of=moment)
                if recovery or wellness
                else None
            ),
            session_intent=session_intent,
            # One assessment covers both inputs, so a log with no event still
            # yields the workload verdict and an event with no log still yields
            # the taper.
            load_management=(
                LoadManagementAssessment.from_sessions(
                    sessions, as_of=moment, event=target_event, metric=load_metric
                )
                if sessions or target_event is not None
                else None
            ),
        )

    @classmethod
    def from_user(
        cls,
        user: User,
        *,
        environment: TrainingEnvironment | None = None,
        load_metric: LoadMetric = LoadMetric.SESSION_RPE,
        as_of: datetime | None = None,
        session_intent: SessionIntent = SessionIntent.MODERATE,
    ) -> "VariationContext":
        """Resolve a whole ``User``. The headline of M3: V2 finally read.

        ``session_intent`` is not read from the ``User`` because it does not
        live there: it is a choice about *today*, made at the moment a session
        is generated, not a stored property of the person. The target event is
        the opposite case and *is* read from the user: a date they are training
        toward belongs to their goals, not to one session."""
        moment = as_of if as_of is not None else datetime.now(timezone.utc)
        return cls.from_parts(
            health=user.health,
            preferences=user.preferences,
            environment=environment,
            recovery=user.recovery_history,
            wellness=user.wellness_history,
            sessions=user.sessions,
            target_event=next_target_event(user, as_of=moment),
            load_metric=load_metric,
            as_of=moment,
            session_intent=session_intent,
        )


def _select_equipment_access(
    preferences: TrainingPreferences | None, environment: TrainingEnvironment | None
) -> EquipmentAccess | None:
    if preferences is None or not preferences.equipment_access:
        return None
    options = preferences.equipment_access
    if environment is not None:
        for access in options:
            if access.environment is environment:
                return access
        # An environment was named and the user has no access record for it.
        # Returning the default would silently prescribe equipment they do not
        # have where they are, which is exactly the failure this tier exists to
        # prevent -- so treat it as "nothing available" instead.
        return EquipmentAccess(environment=environment, available_equipment=frozenset())
    for access in options:
        if access.is_default:
            return access
    return options[0]


@dataclass(frozen=True)
class ContextFilterReport:
    """How much of the library a context ruled out.

    Worth surfacing rather than leaving to be inferred: a context that permits
    three exercises produces technically-valid output that is useless, and the
    symptom -- a routine that never changes -- looks identical to the engine
    simply finding no better scheme.
    """

    permitted: int
    total: int

    @property
    def permitted_fraction(self) -> float:
        return self.permitted / self.total if self.total else 0.0


def summarise_filter(context: VariationContext, db: ExerciseDB) -> ContextFilterReport:
    """How many of the library's exercises this context still allows."""
    exercises = db.all()
    return ContextFilterReport(
        permitted=sum(1 for exercise in exercises if context.permits(exercise)),
        total=len(exercises),
    )
