"""Objective strategy interface: what each ``TrainingObjective`` wants a
set/rep scheme, rest and tempo to look like.

Strength, hypertrophy and muscular endurance are the same movement trained at
different points on the same reps/rest/tempo axis -- low reps and long rest
for maximal force, high reps and short rest for local endurance. That shared
shape is exactly what ``variation.candidate_rep_schemes`` used to hard-code as
one fixed range; this module pulls the range out into a strategy per
objective so the search is objective-aware instead of objective-blind.

A strategy owns **two** questions, and the second was added after the first
shipped:

* *What should one session look like?* -- the rep, set and rest ranges, the
  tempo and the target effort band.
* *What may change between sessions?* -- ``VariationPolicy``. Objectives differ
  far more here than in their rep ranges, and getting it wrong is worse: an
  engine free to swap the exercise and re-solve the load every session cannot
  train strength at all, because strength is a movement-specific motor skill
  and because a substitution discards the very history progression reads.

Objectives whose training effect isn't reps-based at all -- cardiovascular
endurance, flexibility, agility -- are deliberately not implemented here yet.
They need `variation.py` to know how to vary a ``DistanceDose`` or
``DurationDose``, which is a different search than "nearby (sets, reps)" and
has not been built. Shipping a strategy for them now would mean declaring
ranges nothing consults. The interface (``ObjectiveStrategy``) is written to
not preclude them -- ``preferred_modality`` already lets a future
``DurationDose``-based strategy exist alongside these -- but only the
resistance-based objectives are implemented.

This module imports ``TrainingObjective`` from ``hibrid.user.enums``: a shared
closed vocabulary, not user data. It does not consume a ``User`` instance --
health constraints, equipment and preferences reach the engine through
``VariationContext`` instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from hibrid.models import Modality
from hibrid.user.enums import TrainingObjective

#: How far around the current scheme to search, in each direction. A search
#: radius, not a training prescription -- independent of objective, unlike
#: every other property here.
_SET_SEARCH_RADIUS = 2
_REP_SEARCH_RADIUS = 4


class Invariant(str, Enum):
    """What a variation holds constant for the result to still be the same
    training stimulus.

    The two are not interchangeable, and picking the wrong one preserves the
    arithmetic while destroying the objective. Volume is the primary driver of
    hypertrophy, so holding it and solving the load is right there. Proximity
    to maximum is the primary driver of strength, so holding *that* and letting
    total work float is right for strength -- a 4x8 at 60 kg and a 4x4 at 120 kg
    are both defensible hypertrophy sessions carrying different volume, whereas
    a 4x4 at 100 kg and a 6x6 at 45 kg carry identical volume and only one of
    them is strength training.
    """

    LOAD_VOLUME = "load_volume"
    INTENSITY = "intensity"


@dataclass(frozen=True)
class VariationPolicy:
    """How far an objective lets a prescription move *between* sessions.

    Deliberately separate from the rep, set and rest ranges above: those
    describe what one session should look like, and this describes what may
    change from one session to the next. The second question is the one
    adaptation actually depends on, and until this existed the engine had no
    answer to it -- every objective varied by the same rules.

    Strength is the case that forces it. Maximal force production is largely a
    motor skill, so it is trained by repeating a movement and can only be
    *measured* on a movement with a stable history. Since ``TrainingMemory`` is
    keyed on the exercise, a substitution also discards the history that
    progression reads, which means unconstrained variation defeats the
    progression layer rather than merely annoying the user.
    """

    #: What ``vary_entry`` holds fixed while it searches for a new scheme.
    preserved_invariant: Invariant

    #: Ceiling on the per-entry substitution probability, applied whatever the
    #: source. Novelty is a preference; how often a movement may rotate and
    #: still be trainable is a property of the objective, and the second bounds
    #: the first the same way health bounds equipment elsewhere.
    max_substitution_prob: float


#: Strength barely tolerates exercise rotation, for both of the reasons in
#: ``VariationPolicy``. Not zero -- an occasional swap is how a user escapes a
#: movement that does not suit them, and a hard zero would make a
#: contraindicated lift unsubstitutable -- but low enough that a lift survives a
#: training block. At 0.1 a movement is still there ~59% of the time after five
#: sessions, against 3% at the schema's ``novelty_preference`` default of 0.5.
_STRENGTH_MAX_SUBSTITUTION_PROB = 0.10

#: Hypertrophy is deliberately left uncapped, which is not the same as saying
#: rotation is free for it. Volume drives growth rather than movement
#: specificity, so it tolerates variety far better than strength does -- but a
#: novel movement's first two or three exposures are limited by coordination
#: rather than by the muscle, so rotating *every* session still under-stimulates
#: the target. The correct bound is therefore per training block, not per
#: session, and the engine does not model a block yet. Capping it here with no
#: block boundary to rotate at would trade one wrong answer for another.
_HYPERTROPHY_MAX_SUBSTITUTION_PROB = 1.0

#: Local endurance is the least movement-specific of the three, and the one
#: where variety costs nothing measurable.
_ENDURANCE_MAX_SUBSTITUTION_PROB = 1.0


class ObjectiveStrategy(ABC):
    """One ``TrainingObjective``'s stance on how a resistance set should be
    structured: rep scheme, rest, tempo, target effort and which modality it
    applies to."""

    @property
    @abstractmethod
    def objective(self) -> TrainingObjective: ...

    @property
    @abstractmethod
    def preferred_modality(self) -> Modality:
        """The modality this objective prescribes work in. Entries whose
        exercise doesn't match are left unvaried -- see ``variation.py``."""

    @property
    @abstractmethod
    def rep_range(self) -> tuple[int, int]:
        """Inclusive (min, max) reps this objective trains in. Doubles as its
        intensity signal: fewer reps implies a heavier relative load, which
        V1 solves for from volume rather than from a tracked 1RM."""

    @property
    @abstractmethod
    def set_range(self) -> tuple[int, int]: ...

    @property
    @abstractmethod
    def rest_range_seconds(self) -> tuple[int, int]: ...

    @property
    @abstractmethod
    def rep_seconds(self) -> float:
        """Tempo: seconds per rep."""

    @property
    @abstractmethod
    def target_rpe_range(self) -> tuple[float, float]:
        """Target perceived-effort band, on the standard 1-10 RPE scale."""

    @property
    @abstractmethod
    def variation_policy(self) -> VariationPolicy:
        """What may change between sessions, and what must not."""

    def candidate_rep_schemes(self, sets: int, reps: int) -> list[tuple[int, int]]:
        """Nearby (sets, reps) schemes to try, clipped to this objective's
        ranges and excluding the current scheme."""
        min_sets, max_sets = self.set_range
        min_reps, max_reps = self.rep_range
        schemes = []
        for d_sets in range(-_SET_SEARCH_RADIUS, _SET_SEARCH_RADIUS + 1):
            for d_reps in range(-_REP_SEARCH_RADIUS, _REP_SEARCH_RADIUS + 1):
                new_sets, new_reps = sets + d_sets, reps + d_reps
                if not (min_sets <= new_sets <= max_sets) or not (min_reps <= new_reps <= max_reps):
                    continue
                if (new_sets, new_reps) == (sets, reps):
                    continue
                schemes.append((new_sets, new_reps))
        return schemes


@dataclass(frozen=True)
class StrengthStrategy(ObjectiveStrategy):
    """Low reps against a heavy relative load, long rest -- maximal-force
    adaptation."""

    @property
    def objective(self) -> TrainingObjective:
        return TrainingObjective.STRENGTH

    @property
    def preferred_modality(self) -> Modality:
        return Modality.RESISTANCE

    @property
    def rep_range(self) -> tuple[int, int]:
        return (1, 6)

    @property
    def set_range(self) -> tuple[int, int]:
        return (3, 6)

    @property
    def rest_range_seconds(self) -> tuple[int, int]:
        return (120, 300)

    @property
    def rep_seconds(self) -> float:
        return 2.5

    @property
    def target_rpe_range(self) -> tuple[float, float]:
        return (8.0, 10.0)

    @property
    def variation_policy(self) -> VariationPolicy:
        return VariationPolicy(
            preserved_invariant=Invariant.INTENSITY,
            max_substitution_prob=_STRENGTH_MAX_SUBSTITUTION_PROB,
        )


@dataclass(frozen=True)
class HypertrophyStrategy(ObjectiveStrategy):
    """Moderate reps and rest -- the muscle-growth-optimised middle ground,
    and V1's original fixed behaviour before objectives existed."""

    @property
    def objective(self) -> TrainingObjective:
        return TrainingObjective.HYPERTROPHY

    @property
    def preferred_modality(self) -> Modality:
        return Modality.RESISTANCE

    @property
    def rep_range(self) -> tuple[int, int]:
        return (8, 15)

    @property
    def set_range(self) -> tuple[int, int]:
        return (3, 5)

    @property
    def rest_range_seconds(self) -> tuple[int, int]:
        return (60, 120)

    @property
    def rep_seconds(self) -> float:
        return 3.0

    @property
    def target_rpe_range(self) -> tuple[float, float]:
        return (7.0, 9.0)

    @property
    def variation_policy(self) -> VariationPolicy:
        return VariationPolicy(
            preserved_invariant=Invariant.LOAD_VOLUME,
            max_substitution_prob=_HYPERTROPHY_MAX_SUBSTITUTION_PROB,
        )


@dataclass(frozen=True)
class MuscularEnduranceStrategy(ObjectiveStrategy):
    """High reps against a light relative load, short rest -- local muscular
    endurance. Not to be confused with ``TrainingObjective.CARDIOVASCULAR_ENDURANCE``,
    which is aerobic work and out of scope here -- see the module docstring."""

    @property
    def objective(self) -> TrainingObjective:
        return TrainingObjective.MUSCULAR_ENDURANCE

    @property
    def preferred_modality(self) -> Modality:
        return Modality.RESISTANCE

    @property
    def rep_range(self) -> tuple[int, int]:
        return (15, 25)

    @property
    def set_range(self) -> tuple[int, int]:
        return (2, 4)

    @property
    def rest_range_seconds(self) -> tuple[int, int]:
        return (20, 60)

    @property
    def rep_seconds(self) -> float:
        return 2.0

    @property
    def target_rpe_range(self) -> tuple[float, float]:
        return (6.0, 8.0)

    @property
    def variation_policy(self) -> VariationPolicy:
        return VariationPolicy(
            preserved_invariant=Invariant.LOAD_VOLUME,
            max_substitution_prob=_ENDURANCE_MAX_SUBSTITUTION_PROB,
        )


#: Canonical instance per implemented objective. Strategies are stateless and
#: immutable, so one shared instance per objective is enough.
STRATEGIES_BY_OBJECTIVE: dict[TrainingObjective, ObjectiveStrategy] = {
    TrainingObjective.STRENGTH: StrengthStrategy(),
    TrainingObjective.HYPERTROPHY: HypertrophyStrategy(),
    TrainingObjective.MUSCULAR_ENDURANCE: MuscularEnduranceStrategy(),
}
