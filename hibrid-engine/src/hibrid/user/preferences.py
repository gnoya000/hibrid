"""What the user wants and what their life allows.

Two different kinds of information share this module deliberately:

* **Constraints** -- equipment, time, days. Violating one produces a routine
  the user physically cannot execute.
* **Preferences** -- novelty appetite, disliked movements. Violating one
  produces a routine they *can* execute but won't.

Both belong to the same optimisation, but a future engine should treat the
first as hard bounds and the second as soft cost terms, so they are labelled
distinctly rather than blended into one bag of "settings".
"""

from __future__ import annotations

from datetime import time

from pydantic import Field, model_validator

from hibrid.models import Equipment, MovementPattern
from hibrid.user.enums import TimeOfDay, TrainingEnvironment, Weekday
from hibrid.user.types import (
    DurationMinutes,
    HibridModel,
    SessionsPerWeek,
    UnitInterval,
)


class AvailabilityWindow(HibridModel):
    """A recurring window on one weekday when training is actually possible."""

    weekday: Weekday
    earliest_start: time | None = None
    latest_end: time | None = None
    preferred_time_of_day: TimeOfDay | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "AvailabilityWindow":
        if (
            self.earliest_start is not None
            and self.latest_end is not None
            and self.latest_end <= self.earliest_start
        ):
            raise ValueError("latest_end must be after earliest_start")
        return self


class EquipmentAccess(HibridModel):
    """What the user can actually train with, per environment.

    Modelled per environment rather than as one global set because access is
    routinely context-dependent -- a full gym on weekdays, bodyweight only when
    travelling -- and a single flat set cannot express that.
    """

    environment: TrainingEnvironment
    available_equipment: frozenset[Equipment] = frozenset()

    available_exercise_ids: frozenset[str] = frozenset()
    """Optional explicit allowlist, for a home gym whose exact inventory is
    known more precisely than an equipment category can express."""

    max_load_kg: float | None = Field(
        default=None,
        gt=0.0,
        description="Heaviest loadable weight available, e.g. the largest "
        "dumbbell in a home rack. Bounds any prescribed load.",
    )
    is_default: bool = False


class TrainingPreferences(HibridModel):
    """Scheduling constraints and stylistic preferences."""

    # --- Hard constraints: time and availability ---
    sessions_per_week_target: SessionsPerWeek = 3
    preferred_session_duration_minutes: DurationMinutes = 60.0
    max_session_duration_minutes: DurationMinutes | None = None
    availability: tuple[AvailabilityWindow, ...] = ()
    min_rest_days_between_sessions: int = Field(default=0, ge=0, le=7)

    # --- Hard constraints: equipment ---
    equipment_access: tuple[EquipmentAccess, ...] = ()

    # --- Soft preferences: content ---
    preferred_exercise_ids: frozenset[str] = frozenset()
    disliked_exercise_ids: frozenset[str] = frozenset()
    excluded_exercise_ids: frozenset[str] = Field(
        default=frozenset(),
        description="Hard exclusions -- never prescribe, as opposed to the "
        "merely disliked, which may be prescribed at a cost.",
    )
    excluded_movement_patterns: frozenset[MovementPattern] = frozenset()

    # --- Soft preferences: style ---
    novelty_preference: UnitInterval = Field(
        default=0.5,
        description=(
            "Appetite for variation between sessions. 0 = keep it identical and "
            "measurable, 1 = surprise me. This is the user-facing dial that the "
            "existing variation engine's substitution_prob should ultimately be "
            "derived from rather than hard-coded."
        ),
    )
    intensity_preference: UnitInterval = Field(
        default=0.5,
        description="Tolerance for hard sessions, independent of capability.",
    )
    prefers_supersets: bool = False
    prefers_free_weights_over_machines: bool | None = None
    willing_to_train_when_sore: bool = True
    willing_to_train_fasted: bool | None = None

    @model_validator(mode="after")
    def _validate_preferences(self) -> "TrainingPreferences":
        if (
            self.max_session_duration_minutes is not None
            and self.max_session_duration_minutes < self.preferred_session_duration_minutes
        ):
            raise ValueError(
                "max_session_duration_minutes must be at least "
                "preferred_session_duration_minutes"
            )
        overlap = self.preferred_exercise_ids & self.excluded_exercise_ids
        if overlap:
            raise ValueError(
                f"exercises cannot be both preferred and excluded: {sorted(overlap)}"
            )
        return self
