"""What the user actually did.

The organising idea is **prescribed versus performed**. A routine the engine
generated is a hypothesis; this module records the outcome. Keeping the
prescription alongside the execution is what makes the gap visible -- a user
who was told 4x8@80 and did 4x6@80 with an RPE of 10 has told the engine
something crucial that a bare log of "4x6@80" cannot.

Graph note: ``PerformedSet`` is deliberately shaped as a relationship with
properties -- ``(User)-[:PERFORMED {reps, load, rpe, at}]->(Exercise)``. That is
Neo4j's native model, so this projects to a graph edge without restructuring,
while remaining a perfectly ordinary row elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hibrid.user.enums import (
    MeasurementSource,
    SessionStatus,
    TrainingEnvironment,
    TrainingObjective,
)
from hibrid.user.types import (
    BodyMassKg,
    DistanceM,
    DurationSeconds,
    EnergyKcal,
    HeartRateBpm,
    ImmutableModel,
    Likert1To10,
    LoadKg,
    RepCount,
    RepsInReserve,
    Rpe,
    SetCount,
    UnitInterval,
)


class PerformedSet(ImmutableModel):
    """One executed set.

    Load, reps, duration and distance are all optional because a single shape
    has to cover a barbell set, a plank, and a run. Which fields are populated
    is itself information about the kind of work performed.
    """

    set_id: UUID = Field(default_factory=uuid4)
    exercise_id: str
    set_index: int = Field(ge=0, description="Order within the exercise.")

    reps_completed: RepCount | None = None
    load_kg: LoadKg | None = None
    duration_seconds: DurationSeconds | None = None
    distance_m: DistanceM | None = None

    rpe: Rpe | None = None
    reps_in_reserve: RepsInReserve | None = None
    tempo: str | None = Field(
        default=None,
        description="Standard 4-digit tempo notation, e.g. '3010'.",
    )
    rest_taken_seconds: DurationSeconds | None = None

    is_warmup: bool = False
    reached_failure: bool = False
    was_assisted: bool = False
    form_breakdown: bool = Field(
        default=False,
        description="Technique degraded on this set -- a signal to hold load "
        "rather than progress it.",
    )
    pain_reported: bool = False

    # --- Prescription, for deviation analysis ---
    prescribed_reps: RepCount | None = None
    prescribed_load_kg: LoadKg | None = None

    @property
    def volume_load_kg(self) -> float | None:
        """reps x load, the standard resistance-training volume unit.

        Mirrors ``RoutineEntry.volume`` in ``hibrid.models`` so prescribed and
        performed volume are measured the same way and remain comparable.
        """
        if self.reps_completed is None or self.load_kg is None:
            return None
        return self.reps_completed * self.load_kg


class PerformedExercise(ImmutableModel):
    """All sets of one exercise within a session."""

    exercise_id: str
    order_index: int = Field(ge=0)
    sets: tuple[PerformedSet, ...] = ()

    substituted_from_exercise_id: str | None = Field(
        default=None,
        description=(
            "Set when the user swapped out what was prescribed. One of the most "
            "informative fields in the schema: repeated substitution away from "
            "an exercise is a revealed preference or an access problem that no "
            "explicit preference field is likely to capture."
        ),
    )
    substitution_reason: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_sets(self) -> "PerformedExercise":
        mismatched = [s.exercise_id for s in self.sets if s.exercise_id != self.exercise_id]
        if mismatched:
            raise ValueError(
                f"sets must reference the parent exercise_id {self.exercise_id!r}, "
                f"found {sorted(set(mismatched))}"
            )
        return self

    @property
    def working_sets(self) -> tuple[PerformedSet, ...]:
        return tuple(s for s in self.sets if not s.is_warmup)

    @property
    def total_volume_load_kg(self) -> float:
        return sum(s.volume_load_kg or 0.0 for s in self.working_sets)


class TrainingSession(ImmutableModel):
    """One training occasion, planned or unplanned.

    Carries ``user_id`` so it stands alone as a record without its parent, and
    ``status`` so that a skipped session is representable -- absence of a
    session and a deliberately skipped one mean very different things, and only
    an explicit record can distinguish them.
    """

    session_id: UUID = Field(default_factory=uuid4)
    user_id: UUID

    performed_at: datetime
    status: SessionStatus = SessionStatus.COMPLETED

    prescribed_routine_id: UUID | None = None
    prescribed_routine_name: str | None = Field(
        default=None,
        description="Denormalised label for traceability if the routine that "
        "generated this session is later revised or deleted.",
    )
    exercises: tuple[PerformedExercise, ...] = ()

    duration_seconds: DurationSeconds | None = None
    average_heart_rate_bpm: HeartRateBpm | None = None
    max_heart_rate_bpm: HeartRateBpm | None = None
    active_energy_kcal: EnergyKcal | None = None

    session_rpe: Rpe | None = Field(
        default=None,
        description="Whole-session perceived exertion. Multiplied by duration "
        "this yields session-RPE training load, the standard cheap workload "
        "metric where no power or HR data exists.",
    )
    enjoyment: Likert1To10 | None = Field(
        default=None,
        description="Adherence predictor. A programme the user dislikes is one "
        "they will eventually stop executing, whatever its physiological merit.",
    )
    perceived_difficulty: Likert1To10 | None = None

    environment: TrainingEnvironment | None = None
    body_mass_at_session_kg: BodyMassKg | None = Field(
        default=None,
        description="Captured at session time so bodyweight-relative loads stay "
        "correct retrospectively.",
    )
    source: MeasurementSource = MeasurementSource.MANUAL_ENTRY
    notes: str | None = None

    @property
    def total_volume_load_kg(self) -> float:
        return sum(e.total_volume_load_kg for e in self.exercises)

    @property
    def total_working_sets(self) -> int:
        return sum(len(e.working_sets) for e in self.exercises)

    @property
    def session_load(self) -> float | None:
        """session-RPE x duration in minutes."""
        if self.session_rpe is None or self.duration_seconds is None:
            return None
        return self.session_rpe * (self.duration_seconds / 60.0)


class ExercisePerformanceRecord(ImmutableModel):
    """Rolling per-exercise state.

    DERIVED DATA. Everything here is recomputable from ``TrainingSession``
    history and is stored only as a materialised view, because the engine needs
    "what can this user currently lift on this movement?" on every prescription
    and recomputing it from full history each time does not scale. Treat the
    session log as the source of truth and this as a cache that must be
    rebuilt, never hand-edited.
    """

    user_id: UUID
    exercise_id: str
    computed_at: datetime

    estimated_one_rep_max_kg: LoadKg | None = None
    one_rep_max_formula: str | None = Field(
        default=None,
        description="Which estimator produced the value (Epley, Brzycki, ...). "
        "They disagree by several percent, so the number is uninterpretable "
        "without it.",
    )

    best_set_load_kg: LoadKg | None = None
    best_set_reps: RepCount | None = None
    best_estimated_1rm_date: datetime | None = None

    last_performed_at: datetime | None = None
    total_sessions: int = Field(default=0, ge=0)
    total_working_sets: SetCount = 0
    volume_load_last_7d_kg: float = Field(default=0.0, ge=0.0)
    volume_load_last_28d_kg: float = Field(default=0.0, ge=0.0)

    average_rpe: Rpe | None = None
    technical_proficiency: UnitInterval | None = Field(
        default=None,
        description="Confidence that the user executes this movement well, "
        "informed by form-breakdown flags and exposure count.",
    )


class TrainingLoadSummary(ImmutableModel):
    """Aggregate workload over a window.

    DERIVED DATA, like ``ExercisePerformanceRecord``. Exists because the
    acute-to-chronic workload ratio is the single most-cited quantitative guard
    against overtraining, and it needs both windows side by side to be read.
    """

    user_id: UUID
    computed_at: datetime
    window_end: datetime

    acute_load_7d: float = Field(default=0.0, ge=0.0)
    chronic_load_28d: float = Field(
        default=0.0,
        ge=0.0,
        description="The 28-day window's load NORMALISED to the acute window's "
        "length -- a weekly average, not a 28-day total. Stored that way so "
        "acute_chronic_ratio is the conventional figure, near 1.0 for steady "
        "training; a raw total would put steady training at 0.25 and make every "
        "published threshold unusable against it.",
    )

    volume_load_by_objective: dict[TrainingObjective, float] = Field(default_factory=dict)
    sessions_completed: int = Field(default=0, ge=0)
    sessions_prescribed: int = Field(default=0, ge=0)

    @property
    def acute_chronic_ratio(self) -> float | None:
        if self.chronic_load_28d <= 0:
            return None
        return self.acute_load_7d / self.chronic_load_28d

    @property
    def adherence_rate(self) -> float | None:
        if self.sessions_prescribed <= 0:
            return None
        return self.sessions_completed / self.sessions_prescribed
