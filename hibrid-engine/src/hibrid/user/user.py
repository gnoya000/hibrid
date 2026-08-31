"""The ``User`` aggregate root.

Composition rule, which is also what keeps the schema graph-projectable:

* **Owned value objects** (profile, preferences, goals, health) are nested and
  carry no ``user_id``. They have no meaning apart from their user and would
  never be queried independently.
* **Independent facts** (measurements, sessions, derived records) each carry
  their own ``user_id`` and stand alone. They are high-volume, queried across
  users, and are the things that become their own rows, documents, or nodes.

That line is why this object can be loaded whole in a script today and split
across a graph store plus a time-series store later without the models
changing.

Persistence note: a real deployment will not load a user's entire history into
memory. This aggregate is the complete logical view; a repository layer is
expected to page the history collections. Nothing here assumes they are full.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import Field, model_validator

from hibrid.user.biometrics import (
    BodyComposition,
    CardiovascularFitness,
    FitnessAssessment,
    MeasurementRecord,
    RecoveryReading,
    WellnessCheckIn,
)
from hibrid.user.health import HealthProfile
from hibrid.user.history import (
    ExercisePerformanceRecord,
    TrainingLoadSummary,
    TrainingSession,
)
from hibrid.user.objectives import TrainingGoal
from hibrid.user.preferences import TrainingPreferences
from hibrid.user.profile import TrainingBackground, UserProfile
from hibrid.user.types import HibridModel

RecordT = TypeVar("RecordT", bound=MeasurementRecord)


class User(HibridModel):
    """Everything the engine may know about one person."""

    # --- Owned: who they are and what they want ---
    profile: UserProfile
    background: TrainingBackground = Field(default_factory=TrainingBackground)
    preferences: TrainingPreferences = Field(default_factory=TrainingPreferences)
    health: HealthProfile = Field(default_factory=HealthProfile)
    goals: tuple[TrainingGoal, ...] = ()

    # --- Independent facts: measured history, append-only ---
    body_composition_history: tuple[BodyComposition, ...] = ()
    recovery_history: tuple[RecoveryReading, ...] = ()
    wellness_history: tuple[WellnessCheckIn, ...] = ()
    cardiovascular_history: tuple[CardiovascularFitness, ...] = ()
    fitness_assessments: tuple[FitnessAssessment, ...] = ()

    # --- Independent facts: training history ---
    sessions: tuple[TrainingSession, ...] = ()

    # --- Derived views, rebuildable from the above ---
    exercise_records: dict[str, ExercisePerformanceRecord] = Field(default_factory=dict)
    load_summary: TrainingLoadSummary | None = None

    @property
    def user_id(self) -> UUID:
        return self.profile.user_id

    @model_validator(mode="after")
    def _validate_ownership(self) -> "User":
        """Every independent fact must belong to this user.

        Checked here because a mismatched ``user_id`` is exactly the sort of
        error that stays silent until someone's training data has been quietly
        blended with a stranger's.
        """
        owner = self.profile.user_id
        for field_name in (
            "body_composition_history",
            "recovery_history",
            "wellness_history",
            "cardiovascular_history",
            "fitness_assessments",
            "sessions",
        ):
            records = getattr(self, field_name)
            foreign = {r.user_id for r in records if r.user_id != owner}
            if foreign:
                raise ValueError(
                    f"{field_name} contains records belonging to other users: "
                    f"{sorted(str(u) for u in foreign)}"
                )
        for exercise_id, record in self.exercise_records.items():
            if record.user_id != owner:
                raise ValueError(
                    f"exercise_records[{exercise_id!r}] belongs to another user"
                )
            if record.exercise_id != exercise_id:
                raise ValueError(
                    f"exercise_records key {exercise_id!r} does not match "
                    f"record.exercise_id {record.exercise_id!r}"
                )
        if self.load_summary is not None and self.load_summary.user_id != owner:
            raise ValueError("load_summary belongs to another user")
        return self

    def age_years(self, on: date | None = None) -> float:
        return self.profile.age_years(on or date.today())

    @property
    def active_goals(self) -> tuple[TrainingGoal, ...]:
        return tuple(goal for goal in self.goals if goal.is_active)

    @property
    def primary_goal(self) -> TrainingGoal | None:
        """Highest-priority active goal, if any.

        Ties break toward the earliest-listed goal, so the result is stable
        rather than depending on dict or set ordering.
        """
        active = self.active_goals
        if not active:
            return None
        return max(active, key=lambda goal: goal.priority)

    def latest_body_composition(self) -> BodyComposition | None:
        return _latest(self.body_composition_history)

    def latest_recovery(self) -> RecoveryReading | None:
        return _latest(self.recovery_history)

    def latest_wellness(self) -> WellnessCheckIn | None:
        return _latest(self.wellness_history)

    def latest_cardiovascular_fitness(self) -> CardiovascularFitness | None:
        return _latest(self.cardiovascular_history)

    def latest_fitness_assessment(self) -> FitnessAssessment | None:
        return _latest(self.fitness_assessments)

    @property
    def current_body_mass_kg(self) -> float | None:
        """Most recent recorded body mass.

        Resolved by scanning back through history rather than reading a cached
        field, because the newest ``BodyComposition`` record may have been a
        girths-only or body-fat-only measurement.
        """
        for record in sorted(
            self.body_composition_history, key=lambda r: r.recorded_at, reverse=True
        ):
            if record.body_mass_kg is not None:
                return record.body_mass_kg
        return None


def _latest(records: tuple[RecordT, ...]) -> RecordT | None:
    """Most recent record by ``recorded_at``, or None if there are none."""
    if not records:
        return None
    return max(records, key=lambda record: record.recorded_at)


def latest_before(records: tuple[RecordT, ...], cutoff: datetime) -> RecordT | None:
    """Most recent record at or before ``cutoff``.

    Point-in-time lookup, kept available because training any model on this
    history requires reconstructing what was known *then*, not what is known
    now. Using current values to explain past decisions is target leakage.
    """
    eligible = [record for record in records if record.recorded_at <= cutoff]
    if not eligible:
        return None
    return max(eligible, key=lambda record: record.recorded_at)
