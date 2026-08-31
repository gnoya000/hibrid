"""Pydantic request/response schemas for the HTTP API.

The API is an external-data boundary exactly like ``hibrid.user`` -- untrusted
JSON from a caller -- so it stays on pydantic v2, never the internal
dataclasses in ``hibrid.models`` (see CLAUDE.md's pydantic-vs-dataclass
boundary rule). Each schema converts to/from a domain dataclass at the edge;
nothing past ``to_domain()`` ever sees a raw dict or an unvalidated float.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hibrid.exercise_db import ExerciseDB
from hibrid.load_management import (
    LoadManagementAssessment,
    LoadMetric,
    TaperPlan,
    WorkloadAssessment,
    WorkloadState,
)
from hibrid.models import (
    Difficulty,
    DistanceDose,
    Dose,
    DurationDose,
    Modality,
    Muscle,
    RepsDose,
    Routine,
    RoutineEntry,
    RoundsDose,
)
from hibrid.objective_strategy import Invariant, ObjectiveStrategy
from hibrid.progression import ExerciseProgression, ProgressionDecision
from hibrid.session_generation import (
    BlockVariation,
    GeneratedSession,
    SessionBlock,
    SessionGenerationReport,
    StartingLoadPolicy,
    StartingLoadSource,
    UnmetConstraint,
    UnmetConstraintKind,
)
from hibrid.readiness import (
    BaselineComparison,
    ReadinessAssessment,
    ReadinessFlag,
    ReadinessMetric,
    ReadinessState,
)
from hibrid.training_memory import OneRepMaxFormula, TrainingMemory
from hibrid.user.biometrics import RecoveryReading, WellnessCheckIn
from hibrid.user.history import ExercisePerformanceRecord, TrainingSession
from hibrid.user.enums import TrainingEnvironment, TrainingObjective
from hibrid.user.health import HealthProfile
from hibrid.user.objectives import TargetEvent
from hibrid.user.preferences import TrainingPreferences
from hibrid.user.profile import TrainingBackground
from hibrid.user.types import BodyMassKg
from hibrid.variation import DoseOutcome, EntryVariation, ExerciseOutcome, RoutineVariation
from hibrid.variation_context import ContextFilterReport, SessionIntent, VariationContext


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Dose: request side, one schema per shape, discriminated on `kind` -----


class RepsDoseIn(_ApiModel):
    kind: Literal["reps"] = "reps"
    sets: int = Field(gt=0)
    reps: int = Field(gt=0)
    weight: float = Field(ge=0)
    rep_seconds: float = Field(default=3.0, gt=0)

    def to_domain(self) -> RepsDose:
        return RepsDose(sets=self.sets, reps=self.reps, weight=self.weight, rep_seconds=self.rep_seconds)


class DurationDoseIn(_ApiModel):
    kind: Literal["duration"] = "duration"
    sets: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)

    def to_domain(self) -> DurationDose:
        return DurationDose(sets=self.sets, duration_seconds=self.duration_seconds)


class DistanceDoseIn(_ApiModel):
    kind: Literal["distance"] = "distance"
    distance_m: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)

    def to_domain(self) -> DistanceDose:
        return DistanceDose(distance_m=self.distance_m, duration_seconds=self.duration_seconds)


class RoundsDoseIn(_ApiModel):
    kind: Literal["rounds"] = "rounds"
    rounds: int = Field(gt=0)
    round_seconds: float = Field(gt=0)

    def to_domain(self) -> RoundsDose:
        return RoundsDose(rounds=self.rounds, round_seconds=self.round_seconds)


DoseIn = Annotated[
    Union[RepsDoseIn, DurationDoseIn, DistanceDoseIn, RoundsDoseIn],
    Field(discriminator="kind"),
]


class RoutineEntryIn(_ApiModel):
    exercise_id: str
    dose: DoseIn
    rest_seconds: int = Field(default=90, ge=0)

    def to_domain(self) -> RoutineEntry:
        return RoutineEntry(exercise_id=self.exercise_id, dose=self.dose.to_domain(), rest_seconds=self.rest_seconds)


class RoutineIn(_ApiModel):
    name: str
    entries: list[RoutineEntryIn] = Field(min_length=1)

    def to_domain(self) -> Routine:
        return Routine(name=self.name, entries=[entry.to_domain() for entry in self.entries])


# --- Dose: response side, mirrors the *In schemas plus a display string ----


class RepsDoseOut(_ApiModel):
    kind: Literal["reps"] = "reps"
    sets: int
    reps: int
    weight: float
    rep_seconds: float

    @classmethod
    def from_domain(cls, dose: RepsDose) -> "RepsDoseOut":
        return cls(sets=dose.sets, reps=dose.reps, weight=dose.weight, rep_seconds=dose.rep_seconds)


class DurationDoseOut(_ApiModel):
    kind: Literal["duration"] = "duration"
    sets: int
    duration_seconds: float

    @classmethod
    def from_domain(cls, dose: DurationDose) -> "DurationDoseOut":
        return cls(sets=dose.sets, duration_seconds=dose.duration_seconds)


class DistanceDoseOut(_ApiModel):
    kind: Literal["distance"] = "distance"
    distance_m: float
    duration_seconds: float

    @classmethod
    def from_domain(cls, dose: DistanceDose) -> "DistanceDoseOut":
        return cls(distance_m=dose.distance_m, duration_seconds=dose.duration_seconds)


class RoundsDoseOut(_ApiModel):
    kind: Literal["rounds"] = "rounds"
    rounds: int
    round_seconds: float

    @classmethod
    def from_domain(cls, dose: RoundsDose) -> "RoundsDoseOut":
        return cls(rounds=dose.rounds, round_seconds=dose.round_seconds)


DoseOut = Annotated[
    Union[RepsDoseOut, DurationDoseOut, DistanceDoseOut, RoundsDoseOut],
    Field(discriminator="kind"),
]


def _dose_out_from_domain(dose: Dose) -> DoseOut:
    if isinstance(dose, RepsDose):
        return RepsDoseOut.from_domain(dose)
    if isinstance(dose, DurationDose):
        return DurationDoseOut.from_domain(dose)
    if isinstance(dose, DistanceDose):
        return DistanceDoseOut.from_domain(dose)
    if isinstance(dose, RoundsDose):
        return RoundsDoseOut.from_domain(dose)
    raise TypeError(f"Unknown dose type: {type(dose)!r}")


class RoutineEntryOut(_ApiModel):
    exercise_id: str
    exercise_name: str
    dose: DoseOut
    describe: str
    rest_seconds: int
    volume: float
    time_seconds: float

    @classmethod
    def from_domain(cls, entry: RoutineEntry, db: ExerciseDB) -> "RoutineEntryOut":
        return cls(
            exercise_id=entry.exercise_id,
            exercise_name=db[entry.exercise_id].name,
            dose=_dose_out_from_domain(entry.dose),
            describe=entry.dose.describe(),
            rest_seconds=entry.rest_seconds,
            volume=entry.volume,
            time_seconds=entry.time_seconds,
        )


class RoutineOut(_ApiModel):
    routine_id: UUID
    name: str
    entries: list[RoutineEntryOut]
    total_volume: float
    total_time_seconds: float

    @classmethod
    def from_domain(cls, routine: Routine, db: ExerciseDB) -> "RoutineOut":
        return cls(
            routine_id=routine.routine_id,
            name=routine.name,
            entries=[RoutineEntryOut.from_domain(entry, db) for entry in routine.entries],
            total_volume=routine.total_volume,
            total_time_seconds=routine.total_time_seconds,
        )


class ProgressionOut(_ApiModel):
    """What history said this entry's load should be, and why (M8b).

    ``reference_load_kg`` is what the user can currently lift at this rep
    count, derived from their estimated 1RM rather than from the routine's own
    weight. ``working_load_kg`` is that after the decision is applied. When
    they differ from the routine's prescribed weight, that difference is the
    whole point: the file was stale."""

    decision: ProgressionDecision
    reason: str
    reference_load_kg: float | None
    working_load_kg: float | None
    observed_rpe: float | None = Field(
        description="Mean RPE of the last session's working sets. null means "
        "none was logged, which holds the load rather than progressing it.",
    )
    target_rpe_range: tuple[float, float] | None = Field(
        description="The objective's own target effort band, which the "
        "observed RPE was read against.",
    )

    @classmethod
    def from_domain(cls, progression: ExerciseProgression) -> "ProgressionOut":
        return cls(
            decision=progression.decision,
            reason=progression.explain(),
            reference_load_kg=progression.reference_load_kg,
            working_load_kg=progression.working_load_kg,
            observed_rpe=progression.observed_rpe,
            target_rpe_range=progression.target_rpe_range,
        )


class VariedEntryOut(RoutineEntryOut):
    """A varied entry, carrying the account of how it got that way.

    ``dose_outcome`` is what makes an unchanged row readable: without it, an
    entry the engine never found a candidate for is indistinguishable from one
    it deliberately left alone."""

    dose_outcome: DoseOutcome
    dose_outcome_reason: str
    exercise_outcome: ExerciseOutcome
    exercise_outcome_reason: str
    exercise_substituted: bool
    is_unsafe: bool = Field(
        description="A contraindicated exercise had no permitted substitute and "
        "survived into the output. Must not be prescribed as-is.",
    )
    progression: ProgressionOut | None = Field(
        default=None,
        description="Present when session history was supplied. null means no "
        "history was consulted at all -- distinct from a `no_history` decision, "
        "which means it was consulted and had nothing on this movement.",
    )

    @classmethod
    def from_entry_variation(cls, variation: EntryVariation, db: ExerciseDB) -> "VariedEntryOut":
        base = RoutineEntryOut.from_domain(variation.entry, db)
        return cls(
            **base.model_dump(),
            dose_outcome=variation.dose_outcome,
            dose_outcome_reason=variation.dose_outcome.reason,
            exercise_outcome=variation.exercise_outcome,
            exercise_outcome_reason=variation.exercise_outcome.reason,
            exercise_substituted=variation.exercise_substituted,
            is_unsafe=variation.is_unsafe,
            progression=(
                ProgressionOut.from_domain(variation.progression)
                if variation.progression is not None
                else None
            ),
        )


class VariedRoutineOut(_ApiModel):
    routine_id: UUID
    name: str
    entries: list[VariedEntryOut]
    total_volume: float
    total_time_seconds: float

    @classmethod
    def from_domain(cls, variation: RoutineVariation, db: ExerciseDB) -> "VariedRoutineOut":
        return cls(
            routine_id=variation.routine.routine_id,
            name=variation.routine.name,
            entries=[VariedEntryOut.from_entry_variation(ev, db) for ev in variation.entry_variations],
            total_volume=variation.routine.total_volume,
            total_time_seconds=variation.routine.total_time_seconds,
        )


class RoutineSummary(_ApiModel):
    """Lightweight listing entry -- deliberately doesn't resolve exercise
    names, so listing routines never needs the exercise DB."""

    file_stem: str
    routine_id: UUID
    name: str
    entry_count: int

    @classmethod
    def from_domain(cls, routine: Routine, file_stem: str) -> "RoutineSummary":
        return cls(file_stem=file_stem, routine_id=routine.routine_id, name=routine.name, entry_count=len(routine.entries))


# --- Objectives --------------------------------------------------------------


class ObjectiveOut(_ApiModel):
    """An implemented objective strategy's parameters, so a caller can render
    real values instead of hard-coding them."""

    objective: TrainingObjective
    preferred_modality: Modality
    rep_range: tuple[int, int]
    set_range: tuple[int, int]
    rest_range_seconds: tuple[int, int]
    rep_seconds: float
    target_rpe_range: tuple[float, float]
    preserved_invariant: Invariant = Field(
        description="What a variation of this objective holds constant. "
        "`load_volume` solves the load per candidate scheme so total work is "
        "preserved; `intensity` pins the load to the reference and lets total "
        "work float. A client should render the two differently -- under "
        "`intensity` the headline is the bar weight and its progression, not "
        "the diff.",
    )
    max_substitution_prob: float = Field(
        description="Ceiling this objective places on how often an exercise "
        "may be swapped, applied whatever the caller or the user's "
        "novelty_preference asked for. Low for strength, which is a "
        "movement-specific skill measured on a stable history.",
    )

    @classmethod
    def from_domain(cls, strategy: ObjectiveStrategy) -> "ObjectiveOut":
        policy = strategy.variation_policy
        return cls(
            objective=strategy.objective,
            preferred_modality=strategy.preferred_modality,
            rep_range=strategy.rep_range,
            set_range=strategy.set_range,
            rest_range_seconds=strategy.rest_range_seconds,
            rep_seconds=strategy.rep_seconds,
            target_rpe_range=strategy.target_rpe_range,
            preserved_invariant=policy.preserved_invariant,
            max_substitution_prob=policy.max_substitution_prob,
        )


# --- /vary --------------------------------------------------------------


class VariationContextIn(_ApiModel):
    """The caller-supplied user context, carried by the request itself.

    There is no user store: whoever invokes a variation -- the user, or a coach
    with access to these data points -- sends the context with it. That keeps
    the API stateless and defers the persistence decision the roadmap parked.

    These are the *real* ``hibrid.user`` models, not a flattened copy, so there
    is no second schema to drift out of sync and a typo'd field is rejected by
    ``extra="forbid"`` rather than silently dropping a health constraint.
    """

    health: HealthProfile | None = Field(
        default=None,
        description="Injuries and medical considerations. Supplies the "
        "inviolable tier -- never traded against an objective.",
    )
    preferences: TrainingPreferences | None = Field(
        default=None,
        description="Equipment access and content preferences. Supplies the "
        "hard tier (equipment, explicit exclusions) and the soft tier "
        "(dislikes, novelty appetite).",
    )
    environment: TrainingEnvironment | None = Field(
        default=None,
        description="Which EquipmentAccess record applies right now. Access is "
        "modelled per environment (full gym on weekdays, bodyweight when "
        "travelling); without this the record marked is_default wins.",
    )
    recovery_history: tuple[RecoveryReading, ...] = Field(
        default=(),
        description="Wearable readings. Send the whole trailing window, not "
        "just today's: readiness is judged against this user's own 28-day "
        "baseline, so a single reading yields no assessment at all.",
    )
    wellness_history: tuple[WellnessCheckIn, ...] = Field(
        default=(),
        description="Subjective check-ins. Same rule as recovery_history -- "
        "the window is the point, since self-report is individually biased.",
    )
    as_of: datetime | None = Field(
        default=None,
        description="The moment being planned for. Defaults to now; supply it "
        "to reconstruct what a past prescription was based on.",
    )
    session_intent: SessionIntent = Field(
        default=SessionIntent.MODERATE,
        description="How hard the user asked THIS session to be. A directive, "
        "not a measurement -- it needs no baseline and works on day one. "
        "Multiplies with readiness, which can only ever scale it down.",
    )
    target_event: TargetEvent | None = Field(
        default=None,
        description="A dated event to peak for (M8c). Inside the 14-day taper "
        "window the volume target is scaled down toward it, session time held. "
        "Outside the window it changes nothing but is still reported.",
    )
    load_metric: LoadMetric = Field(
        default=LoadMetric.SESSION_RPE,
        description="Which unit the acute:chronic ratio is computed in. "
        "session_rpe needs session_rpe + duration_seconds on each session; "
        "volume_load needs reps and load on the sets. The two are never mixed, "
        "so a log carrying neither yields no workload assessment at all.",
    )

    def to_domain(
        self,
        sessions: tuple[TrainingSession, ...] = (),
        *,
        session_intent: SessionIntent | None = None,
    ) -> VariationContext:
        """``sessions`` comes from the request's own ``history`` block rather
        than being repeated here: M8b's remembered loads and M8c's accumulated
        load read the *same* log, and two copies of it in one request is two
        chances for them to disagree. Note the windows are measured from this
        context's ``as_of``, not the history block's.

        ``session_intent`` overrides this block's own, for endpoints where how
        hard today should be is a top-level parameter of the request rather than
        a property of the context -- ``/sessions/generate`` names it
        ``difficulty``. Those endpoints reject a conflicting value rather than
        silently preferring one, so there is never a question of which won."""
        return VariationContext.from_parts(
            health=self.health,
            preferences=self.preferences,
            environment=self.environment,
            recovery=self.recovery_history,
            wellness=self.wellness_history,
            sessions=sessions,
            target_event=self.target_event,
            load_metric=self.load_metric,
            as_of=self.as_of,
            session_intent=session_intent if session_intent is not None else self.session_intent,
        )


class ContextFilterOut(_ApiModel):
    """How much of the library the supplied context still permits."""

    permitted: int
    total: int
    permitted_fraction: float

    @classmethod
    def from_domain(cls, report: ContextFilterReport) -> "ContextFilterOut":
        return cls(
            permitted=report.permitted,
            total=report.total,
            permitted_fraction=report.permitted_fraction,
        )


class BaselineComparisonOut(_ApiModel):
    """One metric against its own trailing baseline, inputs included.

    The raw numbers travel with the verdict deliberately: a caller shown only
    "suppressed" cannot tell a genuine crash from a borderline reading, and
    this is the output a user is most likely to dispute."""

    metric: ReadinessMetric
    latest: float
    baseline_mean: float
    baseline_sd: float
    sample_size: int
    z_score: float
    indicates_suppression: bool
    is_objective: bool = Field(
        description="Sensor-measured rather than self-reported. Kept visible "
        "because 'HRV is down' and 'they feel terrible' warrant different "
        "responses even when they score identically.",
    )
    describe: str

    @classmethod
    def from_domain(cls, comparison: BaselineComparison) -> "BaselineComparisonOut":
        return cls(
            metric=comparison.metric,
            latest=comparison.latest,
            baseline_mean=comparison.baseline_mean,
            baseline_sd=comparison.baseline_sd,
            sample_size=comparison.sample_size,
            z_score=comparison.z_score,
            indicates_suppression=comparison.indicates_suppression,
            is_objective=comparison.metric.is_objective,
            describe=comparison.describe(),
        )


class ReadinessOut(_ApiModel):
    """Today's strain verdict and the evidence behind it."""

    state: ReadinessState
    state_reason: str
    load_multiplier: float = Field(
        description="What the entry volume targets were scaled by. Never above "
        "1.0 -- increasing prescribed volume is progressive overload, which "
        "needs training-load history this layer does not read.",
    )
    modulates_load: bool
    comparisons: list[BaselineComparisonOut]
    flags: list[ReadinessFlag]
    as_of: datetime | None
    explain: str

    @classmethod
    def from_domain(cls, readiness: ReadinessAssessment) -> "ReadinessOut":
        return cls(
            state=readiness.state,
            state_reason=readiness.state.reason,
            load_multiplier=readiness.load_multiplier,
            modulates_load=readiness.modulates_load,
            comparisons=[BaselineComparisonOut.from_domain(c) for c in readiness.comparisons],
            flags=sorted(readiness.flags, key=lambda flag: flag.value),
            as_of=readiness.as_of,
            explain=readiness.explain(),
        )


# --- Load management (M8c) ---------------------------------------------------


class WorkloadOut(_ApiModel):
    """The acute:chronic verdict, with the numbers it was read from.

    ``chronic_load_7d_equivalent`` is the four-week window normalised to one
    week, which is what makes the ratio comparable to the published figures --
    the raw 28-day total would put steady training near 0.25."""

    state: WorkloadState
    state_reason: str
    metric: LoadMetric
    load_multiplier: float
    acute_load_7d: float | None
    chronic_load_7d_equivalent: float | None
    acute_chronic_ratio: float | None = Field(
        description="null means the comparison could not be made honestly -- no "
        "logged load in the four-week window. Distinct from a ratio of 0.",
    )
    sessions_completed: int | None
    sessions_prescribed: int | None
    describe: str

    @classmethod
    def from_domain(cls, workload: WorkloadAssessment) -> "WorkloadOut":
        summary = workload.summary
        return cls(
            state=workload.state,
            state_reason=workload.state.reason,
            metric=workload.metric,
            load_multiplier=workload.load_multiplier,
            acute_load_7d=summary.acute_load_7d if summary else None,
            chronic_load_7d_equivalent=summary.chronic_load_28d if summary else None,
            acute_chronic_ratio=workload.acute_chronic_ratio,
            sessions_completed=summary.sessions_completed if summary else None,
            sessions_prescribed=summary.sessions_prescribed if summary else None,
            describe=workload.describe(),
        )


class TaperOut(_ApiModel):
    """How far into a taper toward a dated event this session sits."""

    event_name: str
    event_date: date
    days_until_event: int
    load_multiplier: float
    is_tapering: bool = Field(
        description="False outside the taper window and after the event, where "
        "the plan is reported but changes nothing.",
    )
    describe: str

    @classmethod
    def from_domain(cls, taper: TaperPlan) -> "TaperOut":
        return cls(
            event_name=taper.event_name,
            event_date=taper.event_date,
            days_until_event=taper.days_until_event,
            load_multiplier=taper.load_multiplier,
            is_tapering=taper.is_tapering,
            describe=taper.describe(),
        )


class LoadManagementOut(_ApiModel):
    """What accumulated load and an upcoming event did to today's volume.

    ``load_multiplier`` is the *deeper* of the two cuts, not their product: both
    reduce the same quantity for different reasons, and compounding them would
    prescribe a session neither input asked for."""

    load_multiplier: float
    modulates_load: bool
    binding_taper: bool = Field(
        description="The taper, rather than the workload ratio, set the number.",
    )
    workload: WorkloadOut | None
    taper: TaperOut | None
    explain: str

    @classmethod
    def from_domain(cls, assessment: LoadManagementAssessment) -> "LoadManagementOut":
        return cls(
            load_multiplier=assessment.load_multiplier,
            modulates_load=assessment.modulates_load,
            binding_taper=assessment.binding_taper,
            workload=(
                WorkloadOut.from_domain(assessment.workload)
                if assessment.workload is not None
                else None
            ),
            taper=TaperOut.from_domain(assessment.taper) if assessment.taper is not None else None,
            explain=assessment.explain(),
        )


# --- Training memory (M8a) ---------------------------------------------------


class SessionHistoryIn(_ApiModel):
    """A session log to derive per-exercise performance records from.

    Sessions travel in the request for the same reason the user context does:
    there is no user store, and the API stays stateless."""

    user_id: UUID
    sessions: tuple[TrainingSession, ...] = Field(
        default=(),
        description="The real hibrid.user.history models. Skipped and aborted "
        "sessions may be included -- they are read as adherence signal and "
        "deliberately excluded from performance figures.",
    )
    as_of: datetime = Field(
        description="Required, not defaulted to now: rolling windows are "
        "measured back from it, and reconstructing a past prescription has to "
        "see the history as it stood then.",
    )
    formula: OneRepMaxFormula = Field(
        default=OneRepMaxFormula.EPLEY,
        description="Estimators disagree by several percent on the same set, "
        "so the choice is explicit and travels back in the response.",
    )

    @model_validator(mode="after")
    def _validate_ownership(self) -> "SessionHistoryIn":
        foreign = {s.user_id for s in self.sessions if s.user_id != self.user_id}
        if foreign:
            raise ValueError(
                "sessions contains records belonging to other users: "
                f"{sorted(str(u) for u in foreign)}"
            )
        return self

    def to_memory(self) -> TrainingMemory:
        return TrainingMemory.from_sessions(
            self.sessions, user_id=self.user_id, as_of=self.as_of, formula=self.formula
        )


class PerformanceRecordOut(_ApiModel):
    """One exercise's rolling state. Derived, never authoritative."""

    exercise_id: str
    exercise_name: str
    estimated_one_rep_max_kg: float | None = Field(
        description="null is common and expected -- a bodyweight movement or "
        "one only ever trained in sets too long to estimate from has no "
        "knowable 1RM. It is never a quietly extrapolated number.",
    )
    one_rep_max_formula: str | None
    best_set_load_kg: float | None
    best_set_reps: int | None
    best_estimated_1rm_date: datetime | None
    last_performed_at: datetime | None
    total_sessions: int
    total_working_sets: int
    volume_load_last_7d_kg: float
    volume_load_last_28d_kg: float
    average_rpe: float | None

    @classmethod
    def from_domain(cls, record: ExercisePerformanceRecord, db: ExerciseDB) -> "PerformanceRecordOut":
        return cls(
            exercise_id=record.exercise_id,
            exercise_name=db[record.exercise_id].name,
            estimated_one_rep_max_kg=record.estimated_one_rep_max_kg,
            one_rep_max_formula=record.one_rep_max_formula,
            best_set_load_kg=record.best_set_load_kg,
            best_set_reps=record.best_set_reps,
            best_estimated_1rm_date=record.best_estimated_1rm_date,
            last_performed_at=record.last_performed_at,
            total_sessions=record.total_sessions,
            total_working_sets=record.total_working_sets,
            volume_load_last_7d_kg=record.volume_load_last_7d_kg,
            volume_load_last_28d_kg=record.volume_load_last_28d_kg,
            average_rpe=record.average_rpe,
        )


class PerformanceRecordsResponse(_ApiModel):
    as_of: datetime
    formula: OneRepMaxFormula
    records: list[PerformanceRecordOut]
    exercises_with_estimate: int = Field(
        description="How many movements the log could produce a 1RM estimate "
        "for. Reported alongside the total so a log that yielded almost no "
        "estimates is visible rather than looking like an empty result.",
    )
    exercises_without_estimate: int

    @classmethod
    def from_domain(cls, memory: TrainingMemory, db: ExerciseDB) -> "PerformanceRecordsResponse":
        records = [
            PerformanceRecordOut.from_domain(record, db)
            for record in sorted(memory.records.values(), key=lambda r: r.exercise_id)
        ]
        estimated = sum(1 for r in records if r.estimated_one_rep_max_kg is not None)
        return cls(
            as_of=memory.as_of,
            formula=memory.formula,
            records=records,
            exercises_with_estimate=estimated,
            exercises_without_estimate=len(records) - estimated,
        )


class VaryRequest(_ApiModel):
    """A routine, an objective, the engine's tuning knobs, and -- since M3 --
    the user context that makes the result personal."""

    routine: RoutineIn | None = Field(
        default=None, description="An inline routine. Exactly one of this or `routine_name` must be set."
    )
    routine_name: str | None = Field(
        default=None, description="File stem of a routine under routines/, e.g. 'example_ppl'."
    )
    context: VariationContextIn | None = Field(
        default=None,
        description="Omit for an unconstrained variation. That means 'no "
        "constraints known', not 'a user with no constraints'.",
    )
    history: SessionHistoryIn | None = Field(
        default=None,
        description="Session log to programme from. With it, each entry's load "
        "comes from what this user can currently lift adjusted by how their "
        "last session went, rather than from the weight written in the routine "
        "(M8b) -- and the same log supplies the acute:chronic ratio that can "
        "back the whole session off (M8c). Omit and the routine's own numbers "
        "stand.",
    )
    objective: TrainingObjective = TrainingObjective.HYPERTROPHY
    seed: int | None = None
    substitution_prob: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Leave null to derive from the context's novelty_preference, "
        "falling back to 0.3 when no context is supplied.",
    )
    volume_tolerance: float = Field(default=0.075, ge=0.0)
    time_tolerance: float = Field(default=0.10, ge=0.0)
    weight_increment: float = Field(default=2.5, gt=0.0)
    allow_equipment_change: bool = True

    @model_validator(mode="after")
    def _validate_routine_source(self) -> "VaryRequest":
        if (self.routine is None) == (self.routine_name is None):
            raise ValueError("exactly one of `routine` or `routine_name` must be set")
        return self


# --- /sessions/generate and /sessions/blocks/vary (M5, one session) ----------


class UnmetConstraintOut(_ApiModel):
    """One way the generated session does not match what was asked for."""

    kind: UnmetConstraintKind
    detail: str

    @classmethod
    def from_domain(cls, constraint: UnmetConstraint) -> "UnmetConstraintOut":
        return cls(kind=constraint.kind, detail=constraint.detail)


class SessionBlockOut(RoutineEntryOut):
    """One exercise slot, and the invariant re-rolling it must preserve.

    ``volume`` and ``time_seconds`` are inherited from ``RoutineEntryOut`` and
    *are* the invariant: send this block to ``/sessions/blocks/vary`` and both
    come back within tolerance, whatever the exercise and scheme did.

    ``time_budget_seconds`` is the share of the session budget this block was
    allocated, which is not the same as ``time_seconds`` -- the prescribed scheme
    lands as close to it as the objective's rest range permits."""

    index: int = Field(
        description="Stable address of this block within the session. Re-roll "
        "one block by sending it to /sessions/blocks/vary; the index travels "
        "back untouched so the client can put it back where it came from.",
    )
    target: Muscle = Field(
        description="Which requested muscle this block serves. Preserved across "
        "a re-roll -- substitution holds the target muscle fixed.",
    )
    time_budget_seconds: float
    fits_time_budget: bool
    load_source: StartingLoadSource
    load_source_reason: str = Field(
        description="Why the weight is what it is. Read it before trusting the "
        "number: `no_basis` and `bodyweight_only` both prescribe 0 kg and mean "
        "opposite things.",
    )
    load_capped_by_equipment: bool = Field(
        description="The solved load exceeded the heaviest weight this user has "
        "access to and was capped down, so the block carries less volume than "
        "the session's difficulty asked for.",
    )
    is_variable: bool = Field(
        description="Whether this block's dose can be re-solved. False for a "
        "bodyweight block, and not a defect: the engine solves a weight from a "
        "volume and both are zero. Its exercise can still be substituted.",
    )
    progression: ProgressionOut | None = Field(
        default=None,
        description="Present when session history was supplied. null means no "
        "history was consulted at all.",
    )

    @classmethod
    def from_block(cls, block: SessionBlock, db: ExerciseDB) -> "SessionBlockOut":
        base = RoutineEntryOut.from_domain(block.entry, db)
        return cls(
            **base.model_dump(),
            index=block.index,
            target=block.target,
            time_budget_seconds=block.time_budget_seconds,
            fits_time_budget=block.fits_time_budget,
            load_source=block.load_source,
            load_source_reason=block.load_source.reason,
            load_capped_by_equipment=block.load_capped_by_equipment,
            is_variable=block.is_variable,
            progression=(
                ProgressionOut.from_domain(block.progression)
                if block.progression is not None
                else None
            ),
        )


class GeneratedSessionOut(_ApiModel):
    routine_id: UUID
    name: str
    blocks: list[SessionBlockOut]
    total_volume: float = Field(
        description="Sum of each block's own dose currency. Bodyweight blocks "
        "contribute zero, which is why a session containing them totals less "
        "than its loaded blocks suggest -- see Dose.load_volume.",
    )
    total_time_seconds: float

    @classmethod
    def from_domain(cls, session: GeneratedSession, db: ExerciseDB) -> "GeneratedSessionOut":
        return cls(
            routine_id=session.routine.routine_id,
            name=session.routine.name,
            blocks=[SessionBlockOut.from_block(block, db) for block in session.blocks],
            total_volume=session.total_volume,
            total_time_seconds=session.total_time_seconds,
        )


class GenerationReportOut(_ApiModel):
    """What was asked for, what came out, and every way the two differ.

    The part to insist on. A session that quietly drops a requested muscle, or
    quietly runs ten minutes long, reads as a bug -- the same instinct that makes
    every unvaried entry carry a `dose_outcome`."""

    muscles_requested: list[Muscle]
    muscles_covered: list[Muscle]
    muscles_uncovered: list[Muscle] = Field(
        description="Requested muscles that got no block at all. Never silent: "
        "read unmet_constraints for whether the cause is this user's "
        "constraints or a gap in the library's perimeter.",
    )
    time_budget_seconds: float
    prescribed_time_seconds: float
    fits_time_budget: bool
    starting_load_policy: StartingLoadPolicy
    starting_load_policy_reason: str = Field(
        description="Lets a client say 'we start you light on purpose' rather "
        "than letting a deliberately conservative first prescription read as "
        "the app underestimating the user.",
    )
    session_intent_load_multiplier: float = Field(
        description="What the requested difficulty scaled every block's load "
        "by, after readiness and accumulated load had their say and after the "
        "cap at 1.0 that a binding protective term applies. 1.0 means baseline.",
    )
    is_prescribable: bool = Field(
        description="False when a requested muscle went uncovered or a block "
        "came back with no load basis. Both are honest results rather than "
        "errors, and both need the caller to act before showing the session.",
    )
    skill_ceiling: Difficulty = Field(
        description="The hardest movement this user's experience level allowed. "
        "Applied even when no `background` was sent, because beginner is the "
        "safe direction to default -- send one to widen it.",
    )
    skill_filter: ContextFilterOut | None = Field(
        default=None,
        description="How much of the library the skill ceiling alone left. "
        "Reported separately from context_filter because that one only knows "
        "about health, equipment and preferences: at the default beginner "
        "ceiling this removes roughly a third of the library, and without this "
        "field that narrowing is invisible.",
    )
    unmet_constraints: list[UnmetConstraintOut]

    @classmethod
    def from_domain(cls, report: SessionGenerationReport) -> "GenerationReportOut":
        return cls(
            muscles_requested=list(report.muscles_requested),
            muscles_covered=list(report.muscles_covered),
            muscles_uncovered=list(report.muscles_uncovered),
            time_budget_seconds=report.time_budget_seconds,
            prescribed_time_seconds=report.prescribed_time_seconds,
            fits_time_budget=report.fits_time_budget,
            starting_load_policy=report.starting_load_policy,
            starting_load_policy_reason=report.starting_load_policy.reason,
            session_intent_load_multiplier=report.session_intent_load_multiplier,
            is_prescribable=report.is_prescribable,
            skill_ceiling=report.skill_ceiling,
            skill_filter=(
                ContextFilterOut.from_domain(report.skill_filter)
                if report.skill_filter is not None
                else None
            ),
            unmet_constraints=[
                UnmetConstraintOut.from_domain(constraint)
                for constraint in report.unmet_constraints
            ],
        )


class GenerateSessionRequest(_ApiModel):
    """The three things a user can answer without owning a programme: how long
    they have, what they want to train, and how hard they want it."""

    muscles: tuple[Muscle, ...] = Field(
        min_length=1,
        description="Muscles to train, in the order they should appear. One or "
        "more blocks per muscle, sized by the time budget. Listing one twice "
        "means it once.",
    )
    duration_minutes: float = Field(
        gt=0.0,
        le=480.0,
        description="Total session budget, split evenly across the requested "
        "muscles. The prescribed session lands within 10% of it or the report "
        "says why not.",
    )
    difficulty: SessionIntent = Field(
        default=SessionIntent.MODERATE,
        description="How hard this session should be relative to the user's own "
        "baseline: light / moderate / challenging. This is `SessionIntent`, the "
        "same dial /vary uses -- a directive rather than a measurement, so it "
        "needs no history and works on day one. It scales load, never session "
        "time, and readiness or a taper can only ever scale it down.",
    )
    objective: TrainingObjective = TrainingObjective.HYPERTROPHY
    context: VariationContextIn | None = Field(
        default=None,
        description="Health, equipment and preferences. Omit for an "
        "unconstrained session -- that means 'no constraints known', not 'a user "
        "with no constraints'. Do not set session_intent inside it; use the "
        "top-level `difficulty`.",
    )
    history: SessionHistoryIn | None = Field(
        default=None,
        description="Session log. With it, a block's load comes from what this "
        "user has actually lifted on that movement (M8b) instead of from the "
        "conservative body-mass fractions. The same log supplies the "
        "acute:chronic ratio that can back the whole session off (M8c).",
    )
    background: TrainingBackground | None = Field(
        default=None,
        description="Supplies the skill ceiling (experience_level) and a nudge "
        "toward movements the user already performs well "
        "(familiar_exercise_ids). Omitted, the ceiling is the beginner one, "
        "which is the safe direction to be wrong in.",
    )
    body_mass_kg: BodyMassKg | None = Field(
        default=None,
        description="Used only to derive a conservative starting load where "
        "there is no history on a movement. Health-bucket data: accepted "
        "request-scoped and forgotten -- never persisted and never logged. "
        "Without it and without history, loaded blocks come back with "
        "load_source `no_basis` and must not be prescribed as-is.",
    )
    name: str | None = None
    seed: int | None = None
    weight_increment: float = Field(default=2.5, gt=0.0)

    @model_validator(mode="after")
    def _validate_single_difficulty(self) -> "GenerateSessionRequest":
        """Reject a difficulty stated twice and differently.

        ``session_intent`` is a legitimate field of ``VariationContextIn``
        because /vary reads it there, but here the session parameter is
        top-level. Silently preferring one would be exactly the kind of quietly
        dropped field ``extra="forbid"`` exists to prevent, so a conflict is an
        error and agreement is allowed through."""
        if (
            self.context is not None
            and "session_intent" in self.context.model_fields_set
            and self.context.session_intent is not self.difficulty
        ):
            raise ValueError(
                "difficulty and context.session_intent disagree "
                f"({self.difficulty.value!r} vs {self.context.session_intent.value!r}); "
                "set the top-level `difficulty` only"
            )
        return self


class GenerateSessionResponse(_ApiModel):
    session: GeneratedSessionOut
    report: GenerationReportOut
    context_filter: ContextFilterOut | None = Field(
        default=None,
        description="Present when a context was supplied. A low permitted count "
        "explains an otherwise-mysterious lack of exercise variety.",
    )
    readiness: ReadinessOut | None = Field(
        default=None,
        description="Present when recovery or wellness history was supplied. "
        "Explains loads lighter than the requested difficulty implies.",
    )
    load_management: LoadManagementOut | None = Field(
        default=None,
        description="Present when a session log or a target event was supplied.",
    )
    difficulty: SessionIntent
    difficulty_reason: str
    intent_capped_by_readiness: bool = Field(
        default=False,
        description="The user asked for a harder session than their own "
        "baseline allowed. Worth reading: challenging against a suppressed "
        "readiness composes to exactly 1.0, so the request is cancelled while "
        "every block honestly reports an ordinary prescription.",
    )
    intent_capped_by_load_management: bool = Field(
        default=False,
        description="The same cancellation by the other route -- a hard session "
        "asked for during a taper, or in a week already ahead of the four-week "
        "average.",
    )


class SessionBlockIn(_ApiModel):
    """A block sent back for re-rolling.

    Only the fields the invariant is computed from: the block's volume and time
    come from its own dose and rest, so nothing else has to survive the round
    trip. ``target`` and ``time_budget_seconds`` are derived when omitted, so a
    client can post back the three fields it can see on screen."""

    exercise_id: str
    dose: DoseIn
    rest_seconds: int = Field(default=90, ge=0)
    index: int = Field(default=0, ge=0)
    time_budget_seconds: float | None = Field(
        default=None,
        description="Defaults to the block's own prescribed time, which is what "
        "a re-roll preserves anyway. Send the generated value back to keep the "
        "block's fit against the original session budget reported honestly.",
    )
    load_capped_by_equipment: bool = Field(
        default=False,
        description="Carried through untouched. Generation set this when it had "
        "to cap a load; it cannot be reconstructed from a dose, so send it back "
        "if you want it reported on the re-rolled block.",
    )

    def to_domain(self, db: ExerciseDB) -> SessionBlock:
        entry = RoutineEntry(
            exercise_id=self.exercise_id,
            dose=self.dose.to_domain(),
            rest_seconds=self.rest_seconds,
        )
        return SessionBlock(
            index=self.index,
            entry=entry,
            target=db[self.exercise_id].target,
            time_budget_seconds=(
                self.time_budget_seconds
                if self.time_budget_seconds is not None
                else entry.time_seconds
            ),
            # The block arrived already prescribed; where its weight originally
            # came from is not recoverable from the wire and does not bear on
            # re-solving it.
            load_source=StartingLoadSource.PRESERVED_FROM_BLOCK,
            load_capped_by_equipment=self.load_capped_by_equipment,
        )


class VariedBlockOut(SessionBlockOut):
    """A re-rolled block, carrying the account of how it got that way."""

    dose_outcome: DoseOutcome
    dose_outcome_reason: str
    exercise_outcome: ExerciseOutcome
    exercise_outcome_reason: str
    exercise_substituted: bool
    is_unsafe: bool = Field(
        description="A contraindicated exercise had no permitted substitute and "
        "survived into the output. Must not be prescribed as-is.",
    )

    @classmethod
    def from_block_variation(cls, variation: BlockVariation, db: ExerciseDB) -> "VariedBlockOut":
        base = SessionBlockOut.from_block(variation.block, db)
        return cls(
            **base.model_dump(),
            dose_outcome=variation.dose_outcome,
            dose_outcome_reason=variation.dose_outcome.reason,
            exercise_outcome=variation.exercise_outcome,
            exercise_outcome_reason=variation.exercise_outcome.reason,
            exercise_substituted=variation.exercise_substituted,
            is_unsafe=variation.is_unsafe,
        )


class VaryBlockRequest(_ApiModel):
    """Re-roll one block of a generated session, holding its own volume and time.

    There is no `history` block and no `difficulty`, and both omissions are
    deliberate. The block's prescribed weight already embodies the difficulty,
    readiness and accumulated load that were applied when the session was
    generated, so applying any of them again would compound: a challenging
    session would climb 15% on every re-roll. A context is still worth sending --
    its health, equipment and preference tiers are honoured in full -- but its
    adaptive tier is neutralised here."""

    block: SessionBlockIn
    objective: TrainingObjective = TrainingObjective.HYPERTROPHY
    context: VariationContextIn | None = None
    seed: int | None = None
    substitution_prob: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Leave null to derive from the context's "
        "novelty_preference, falling back to 0.3. Send 1.0 for 'definitely give "
        "me a different exercise', which is what a re-roll button wants.",
    )
    volume_tolerance: float = Field(default=0.075, ge=0.0)
    time_tolerance: float = Field(default=0.10, ge=0.0)
    weight_increment: float = Field(default=2.5, gt=0.0)
    allow_equipment_change: bool = True


class VaryBlockResponse(_ApiModel):
    original: SessionBlockOut
    varied: VariedBlockOut
    volume_preserved: bool = Field(
        description="The re-rolled block still carries the original's volume "
        "within volume_tolerance. Note an unvaried block preserves it "
        "trivially -- read varied.dose_outcome for whether anything moved.",
    )
    time_preserved: bool
    target_preserved: bool = Field(
        description="The block still trains the muscle the session was "
        "generated for. Substitution holds the target muscle fixed, so this is "
        "a guard rather than a live risk.",
    )
    load_multiplier: float = Field(
        description="Always 1.0, by construction. The block's numbers already "
        "embody today's adjustment, so re-solving them applies no further "
        "scaling -- that is what keeps the session's difficulty parameter "
        "intact across repeated re-rolls.",
    )

    @classmethod
    def from_domain(cls, variation: BlockVariation, db: ExerciseDB) -> "VaryBlockResponse":
        return cls(
            original=SessionBlockOut.from_block(variation.original, db),
            varied=VariedBlockOut.from_block_variation(variation, db),
            volume_preserved=variation.volume_preserved,
            time_preserved=variation.time_preserved,
            target_preserved=variation.target_preserved,
            load_multiplier=1.0,
        )


class VaryResponse(_ApiModel):
    original: RoutineOut
    varied: VariedRoutineOut
    context_filter: ContextFilterOut | None = Field(
        default=None,
        description="Present when a context was supplied. A low permitted count "
        "explains an otherwise-mysterious lack of variation.",
    )
    readiness: ReadinessOut | None = Field(
        default=None,
        description="Present when recovery or wellness history was supplied. "
        "Explains a varied routine whose loads came back lighter than the "
        "original -- without it that reads as an engine bug.",
    )
    load_management: LoadManagementOut | None = Field(
        default=None,
        description="Present when a session log or a target event was supplied. "
        "Explains a session backed off for accumulated load, or scaled down "
        "into a taper, neither of which is visible in today's readiness.",
    )
    session_intent: SessionIntent = Field(
        description="The effort level this variation was solved for.",
    )
    session_intent_reason: str
    intent_capped_by_readiness: bool = Field(
        default=False,
        description="The user asked for more work than their readiness allowed. "
        "Worth reading: challenging against a suppressed readiness composes to "
        "exactly 1.0, so the request is cancelled while every entry honestly "
        "reports a plain variation.",
    )
    intent_capped_by_load_management: bool = Field(
        default=False,
        description="The same cancellation by the other route -- a hard session "
        "asked for during a taper, or in a week already ahead of the four-week "
        "average.",
    )
    load_multiplier: float = Field(
        description="What every entry's volume target was scaled by: the "
        "session intent's multiplier times readiness' times load management's, "
        "capped at 1.0 whenever a protective term binds. 1.0 means the routine "
        "is volume-preserving in the original sense. Anything else is why the "
        "varied total_volume does not match the original's.",
    )
    substitution_prob: float = Field(
        description="The per-entry substitution probability actually used, "
        "after the objective's ceiling was applied. A caller that asked for "
        "0.8 under a strength objective and sees 0.1 here is being told the "
        "objective overruled it, rather than left to guess the request was "
        "ignored.",
    )
