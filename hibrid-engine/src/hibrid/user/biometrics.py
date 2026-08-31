"""Dated, immutable measurement records.

Every model here is one observation at one instant, from one source. Nothing is
overwritten: correcting a value means appending a superseding record. That is
what lets a future engine ask trend questions -- "is HRV suppressed relative to
this user's own 28-day baseline?" -- which no current-value field can answer,
and which matter far more than any single reading.

All records carry ``user_id`` so they stand alone as rows, documents, or graph
nodes without needing their parent object. They are also the highest-volume
part of the schema by a wide margin, and the part best kept OUT of a graph
database and in a time-series or columnar store; see ``docs/user-schema.md``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from hibrid.user.enums import (
    AssessmentMethod,
    BodyRegion,
    MeasurementSource,
    MenstrualPhase,
    TrainingObjective,
)
from hibrid.user.types import (
    BodyMassKg,
    DurationMinutes,
    EnergyKcal,
    GirthCm,
    HeartRateBpm,
    HeightCm,
    HrvMilliseconds,
    ImmutableModel,
    Likert1To10,
    Percent,
    PowerWatts,
    RespiratoryRate,
    Score0To100,
    UnitInterval,
    Vo2Max,
)


class MeasurementRecord(ImmutableModel):
    """Fields common to every observation.

    ``source`` and ``confidence`` exist so that readings of differing quality
    remain distinguishable downstream. A wrist-optical HRV estimate and a
    chest-strap one should not be averaged as equals, and only provenance makes
    that distinction recoverable after ingestion.
    """

    record_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    recorded_at: datetime
    source: MeasurementSource = MeasurementSource.UNKNOWN
    confidence: UnitInterval | None = Field(
        default=None,
        description="Optional reliability weight for this record, where the "
        "ingesting integration can supply one.",
    )
    notes: str | None = None


class BodyComposition(MeasurementRecord):
    """Anthropometrics. Height lives here rather than on the profile so that
    every measurable attribute follows the same snapshot rule."""

    body_mass_kg: BodyMassKg | None = None
    height_cm: HeightCm | None = None
    body_fat_percent: Percent | None = None
    lean_mass_kg: BodyMassKg | None = None
    skeletal_muscle_mass_kg: BodyMassKg | None = None
    bone_mass_kg: BodyMassKg | None = None
    total_body_water_percent: Percent | None = None
    visceral_fat_rating: float | None = Field(default=None, ge=0.0, le=60.0)

    girths_cm: dict[BodyRegion, GirthCm] = Field(
        default_factory=dict,
        description="Circumference measurements by region. A mapping rather "
        "than fixed fields because which sites get measured varies by user and "
        "by protocol.",
    )


class RecoveryReading(MeasurementRecord):
    """Objective overnight/resting physiology, typically from a wearable.

    This is the primary channel through which 'strain level and data from
    health devices' reaches the engine.
    """

    resting_heart_rate_bpm: HeartRateBpm | None = None
    hrv_rmssd_ms: HrvMilliseconds | None = Field(
        default=None,
        description="RMSSD specifically. Vendors report differing HRV metrics; "
        "naming the metric prevents silently mixing incomparable numbers.",
    )
    hrv_sdnn_ms: HrvMilliseconds | None = None

    sleep_duration_minutes: DurationMinutes | None = None
    sleep_efficiency_percent: Percent | None = None
    deep_sleep_minutes: DurationMinutes | None = None
    rem_sleep_minutes: DurationMinutes | None = None
    light_sleep_minutes: DurationMinutes | None = None
    awake_minutes: DurationMinutes | None = None
    sleep_debt_minutes: DurationMinutes | None = None

    respiratory_rate_bpm: RespiratoryRate | None = None
    blood_oxygen_percent: Percent | None = None
    skin_temperature_deviation_c: float | None = Field(default=None, ge=-10.0, le=10.0)

    readiness_score: Score0To100 | None = Field(
        default=None,
        description="Vendor-computed readiness/recovery index. Kept alongside "
        "the raw inputs, never instead of them -- vendor formulas are opaque "
        "and change without notice.",
    )
    strain_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Vendor-computed cumulative strain/load index.",
    )

    steps: int | None = Field(default=None, ge=0)
    active_energy_kcal: EnergyKcal | None = None
    total_energy_kcal: EnergyKcal | None = None

    menstrual_phase: MenstrualPhase | None = None


class WellnessCheckIn(MeasurementRecord):
    """Subjective self-report.

    Kept separate from ``RecoveryReading`` because it is a different kind of
    evidence with different failure modes -- self-report is biased but captures
    things no sensor sees (motivation, life stress, localised soreness). Both
    are needed; conflating them would hide which one a decision rested on.
    """

    energy: Likert1To10 | None = None
    soreness: Likert1To10 | None = None
    stress: Likert1To10 | None = None
    mood: Likert1To10 | None = None
    motivation: Likert1To10 | None = None
    sleep_quality: Likert1To10 | None = None
    perceived_recovery: Likert1To10 | None = None

    sore_regions: frozenset[BodyRegion] = frozenset()

    illness_reported: bool = False
    injury_flare_reported: bool = False
    alcohol_consumed: bool | None = None


class CardiovascularFitness(MeasurementRecord):
    """Aerobic capacity markers, measured or estimated."""

    vo2max_ml_kg_min: Vo2Max | None = None
    max_heart_rate_bpm: HeartRateBpm | None = None
    lactate_threshold_hr_bpm: HeartRateBpm | None = None
    functional_threshold_power_w: PowerWatts | None = None
    running_threshold_pace_s_per_km: float | None = Field(default=None, gt=0.0)
    heart_rate_recovery_60s_bpm: int | None = Field(default=None, ge=0, le=120)

    assessment_method: AssessmentMethod = AssessmentMethod.WEARABLE_ESTIMATE


class FitnessAssessment(MeasurementRecord):
    """The 'fitness score', decomposed by quality.

    A single overall number is what users want to see, but it is nearly useless
    as an algorithm input -- it cannot distinguish a strong, inflexible user
    from a mobile, weak one who scores identically. Storing per-objective
    components keyed by the same ``TrainingObjective`` enum used for goals lets
    the engine compare where the user *is* against where they want to *be*,
    dimension by dimension.
    """

    overall_score: Score0To100 | None = None
    component_scores: dict[TrainingObjective, Score0To100] = Field(default_factory=dict)

    assessment_method: AssessmentMethod = AssessmentMethod.FIELD_TEST
    protocol_name: str | None = None
