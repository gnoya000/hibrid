"""Shared constrained scalar types and the common model base.

Every user-facing quantity is expressed through one of these aliases rather than
a bare ``float``, so the valid range is part of the schema itself instead of
living in validation code somewhere downstream. Pydantic enforces them at
construction time and exports them into the generated JSON Schema.

CANONICAL UNITS -- the schema stores SI/metric internally, always:
    mass         kilograms   (``_kg``)
    length       centimetres (``_cm``) or metres (``_m``) where named
    duration     seconds (``_seconds``) or minutes (``_minutes``) where named
    energy       kilocalories (``_kcal``)
    temperature  degrees Celsius (``_c``)

A user's preferred *display* units are a presentation concern recorded on
``UserProfile.unit_system``; no stored value is ever in imperial units. This
removes an entire class of unit-confusion bugs from every future algorithm.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# --- Normalised scales -------------------------------------------------------

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
"""A 0.0-1.0 proportion (weights, preference strengths, adherence ratios)."""

Score0To100 = Annotated[float, Field(ge=0.0, le=100.0)]
"""A 0-100 index, matching how consumer wearables report readiness/recovery."""

Percent = Annotated[float, Field(ge=0.0, le=100.0)]

# --- Subjective scales -------------------------------------------------------

Rpe = Annotated[float, Field(ge=1.0, le=10.0)]
"""Rating of Perceived Exertion on the standard 1-10 scale."""

RepsInReserve = Annotated[float, Field(ge=0.0, le=10.0)]
"""Estimated reps left before failure. Complementary to RPE; both are kept
because athletes and coaches reliably report one or the other, not both."""

Likert1To10 = Annotated[int, Field(ge=1, le=10)]
"""Self-reported 1-10 rating (energy, soreness, stress, mood, enjoyment)."""

Severity0To10 = Annotated[int, Field(ge=0, le=10)]

# --- Anthropometrics ---------------------------------------------------------

BodyMassKg = Annotated[float, Field(gt=0.0, le=650.0)]
HeightCm = Annotated[float, Field(gt=0.0, le=280.0)]
GirthCm = Annotated[float, Field(gt=0.0, le=300.0)]

# --- Load and work -----------------------------------------------------------

LoadKg = Annotated[float, Field(ge=0.0, le=1000.0)]
"""External load. Zero is legitimate: bodyweight and mobility work carry none."""

DistanceM = Annotated[float, Field(ge=0.0)]
DurationSeconds = Annotated[float, Field(ge=0.0)]
DurationMinutes = Annotated[float, Field(ge=0.0)]
EnergyKcal = Annotated[float, Field(ge=0.0)]

# --- Cardiovascular ----------------------------------------------------------

HeartRateBpm = Annotated[int, Field(ge=20, le=250)]
HrvMilliseconds = Annotated[float, Field(ge=0.0, le=500.0)]
Vo2Max = Annotated[float, Field(ge=5.0, le=100.0)]
"""ml/kg/min."""
PowerWatts = Annotated[float, Field(ge=0.0, le=2000.0)]
RespiratoryRate = Annotated[float, Field(ge=1.0, le=60.0)]

# --- Counts ------------------------------------------------------------------

RepCount = Annotated[int, Field(ge=0, le=1000)]
SetCount = Annotated[int, Field(ge=0, le=100)]
SessionsPerWeek = Annotated[int, Field(ge=0, le=21)]


class HibridModel(BaseModel):
    """Base for every user-schema model.

    ``extra="forbid"`` is the load-bearing choice: an unrecognised key from a
    device export or an API payload raises instead of being silently dropped,
    so schema drift surfaces at ingestion rather than as a mysteriously absent
    feature much later in a training pipeline.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
        str_strip_whitespace=True,
    )


class ImmutableModel(HibridModel):
    """Base for recorded facts, which must never be edited after the fact.

    Measurements and performed work are historical events: correcting one means
    appending a superseding record, not mutating the original. Keeping that
    immutable is what makes the history trustworthy as training data.
    """

    model_config = ConfigDict(frozen=True)
