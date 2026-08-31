"""What the user is training for.

Objectives are a weight vector rather than a single mode. Real athletes want
blends ("mostly strength, keep my mobility"), and an engine that has to trade
qualities off against each other needs the trade-off stated numerically instead
of inferring it from a single enum. The vector doubles as a ready-made
regression target or conditioning input for a future model.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hibrid.user.enums import TargetMetric, TrainingObjective
from hibrid.user.types import HibridModel, ImmutableModel, Likert1To10, UnitInterval

_WEIGHT_SUM_TOLERANCE = 1e-6


class ObjectiveWeights(HibridModel):
    """A normalised preference distribution over training objectives.

    Weights must be non-negative and sum to 1.0, which makes vectors comparable
    across users and over time -- an unnormalised vector would silently encode
    "total training intent" alongside its distribution and make any two users
    incomparable.
    """

    weights: dict[TrainingObjective, UnitInterval]

    @model_validator(mode="after")
    def _validate_distribution(self) -> "ObjectiveWeights":
        if not self.weights:
            raise ValueError("objective weights must name at least one objective")
        total = sum(self.weights.values())
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"objective weights must sum to 1.0, got {total:.6f}. "
                "Use ObjectiveWeights.normalised() to build from raw shares."
            )
        return self

    @classmethod
    def normalised(cls, raw: dict[TrainingObjective, float]) -> ObjectiveWeights:
        """Build from arbitrary non-negative shares, scaling them to sum to 1."""
        if not raw:
            raise ValueError("objective weights must name at least one objective")
        if any(value < 0 for value in raw.values()):
            raise ValueError("objective weights must be non-negative")
        total = sum(raw.values())
        if total <= 0:
            raise ValueError("objective weights must not all be zero")
        return cls(weights={k: v / total for k, v in raw.items()})

    @property
    def primary(self) -> TrainingObjective:
        return max(self.weights.items(), key=lambda item: item[1])[0]


class TargetEvent(ImmutableModel):
    """A fixed date the plan must peak for.

    A dated event is what turns generic programming into periodization: it
    supplies the deadline that taper and peaking phases are computed backwards
    from.
    """

    event_id: UUID = Field(default_factory=uuid4)
    name: str
    event_date: date
    event_type: str | None = Field(
        default=None,
        description="Free text (marathon, powerlifting meet, ski season, wedding).",
    )
    importance: Likert1To10 = 5
    notes: str | None = None


class PerformanceTarget(HibridModel):
    """A specific, measurable outcome -- the objective vector made concrete.

    ``ObjectiveWeights`` says which direction to move; this says how far and by
    when, giving the engine an error signal it can actually close.
    """

    target_id: UUID = Field(default_factory=uuid4)
    metric: TargetMetric

    exercise_id: str | None = Field(
        default=None,
        description=(
            "Required for exercise-scoped metrics such as ONE_REP_MAX_KG. "
            "References ExerciseDB by id rather than embedding the exercise."
        ),
    )
    target_value: float
    baseline_value: float | None = Field(
        default=None,
        description="Value when the target was set, so progress is measurable.",
    )
    secondary_value: float | None = Field(
        default=None,
        description="Second dimension where a metric needs one, e.g. the load "
        "for REPS_AT_LOAD or the distance for a DURATION_SECONDS time trial.",
    )

    target_date: date | None = None
    is_achieved: bool = False
    achieved_on: date | None = None


class TrainingGoal(HibridModel):
    """A coherent training intent over a time window.

    A user may hold several concurrently (an in-season goal plus a standing
    mobility goal); ``priority`` is what lets the engine resolve conflicts
    between them rather than averaging them into mush.
    """

    goal_id: UUID = Field(default_factory=uuid4)
    name: str | None = None

    objectives: ObjectiveWeights
    priority: Likert1To10 = 5

    start_date: date | None = None
    target_date: date | None = None
    is_active: bool = True

    target_event: TargetEvent | None = None
    performance_targets: tuple[PerformanceTarget, ...] = ()

    notes: str | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> "TrainingGoal":
        if (
            self.start_date is not None
            and self.target_date is not None
            and self.target_date < self.start_date
        ):
            raise ValueError("target_date must not precede start_date")
        return self
