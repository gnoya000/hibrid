"""Injuries, limitations, and medical context.

These are the schema's hard safety bounds: unlike preferences, an engine must
never trade these off against a training objective. They are modelled as
explicit contraindication sets (patterns and exercise ids) rather than as free
text, so a future planner can mechanically exclude work instead of needing to
interpret a note.

Scope note: this is deliberately *not* a medical ontology and carries no
diagnostic meaning. It records what the user or their clinician has stated, so
that programming can stay inside it.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hibrid.models import MovementPattern
from hibrid.user.enums import BodyRegion, InjuryStatus, Laterality
from hibrid.user.types import HibridModel, LoadKg, Severity0To10


class Injury(HibridModel):
    """A localised physical limitation, current or historical.

    Resolved injuries are kept rather than deleted: prior injury is one of the
    strongest predictors of future injury at the same site, so the record stays
    useful to the engine long after the pain stops.
    """

    injury_id: UUID = Field(default_factory=uuid4)

    body_region: BodyRegion
    laterality: Laterality = Laterality.BILATERAL
    status: InjuryStatus
    severity: Severity0To10 = 0

    onset_date: date | None = None
    resolved_date: date | None = None
    description: str | None = None

    contraindicated_movement_patterns: frozenset[MovementPattern] = frozenset()
    """Patterns to avoid entirely while this injury is active or chronic."""

    contraindicated_exercise_ids: frozenset[str] = frozenset()

    painful_exercise_ids: frozenset[str] = Field(
        default=frozenset(),
        description="Provokes symptoms but is not strictly forbidden -- a "
        "strong cost signal rather than a hard exclusion.",
    )

    max_tolerated_load_kg: LoadKg | None = Field(
        default=None,
        description="Ceiling on load for affected movements, where a clinician "
        "or the user has established one.",
    )

    clinician_cleared: bool = Field(
        default=False,
        description="Whether a professional has cleared a return to training. "
        "Gates any automatic progression past conservative defaults.",
    )
    requires_medical_clearance: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> "Injury":
        if (
            self.onset_date is not None
            and self.resolved_date is not None
            and self.resolved_date < self.onset_date
        ):
            raise ValueError("resolved_date must not precede onset_date")
        if self.status is InjuryStatus.RESOLVED and self.resolved_date is None:
            raise ValueError("a resolved injury must carry a resolved_date")
        return self

    @property
    def is_limiting(self) -> bool:
        """Whether this injury should currently constrain programming."""
        return self.status in (InjuryStatus.ACTIVE, InjuryStatus.RECOVERING, InjuryStatus.CHRONIC)


class MedicalConsideration(HibridModel):
    """A health condition that changes what safe programming looks like.

    Held as free-text ``condition`` plus explicit structured *effects*. The
    condition name is for humans; the effect flags are what an engine reads, so
    a new condition never requires the algorithm to learn a new vocabulary.
    """

    consideration_id: UUID = Field(default_factory=uuid4)

    condition: str
    diagnosed_on: date | None = None
    is_active: bool = True
    severity: Severity0To10 = 0

    # --- Structured effects on programming ---
    caps_max_heart_rate: bool = False
    max_heart_rate_bpm: int | None = Field(default=None, ge=20, le=250)
    limits_valsalva_or_breath_holding: bool = Field(
        default=False,
        description="Relevant to hypertension and cardiac conditions; rules out "
        "maximal straining efforts.",
    )
    limits_supine_positions: bool = Field(
        default=False,
        description="Relevant in later pregnancy, reflux, and some spinal "
        "conditions.",
    )
    limits_high_impact: bool = False
    limits_overhead_work: bool = False
    requires_medical_clearance: bool = False

    contraindicated_movement_patterns: frozenset[MovementPattern] = frozenset()
    contraindicated_exercise_ids: frozenset[str] = frozenset()

    notes: str | None = None


class HealthProfile(HibridModel):
    """All safety-relevant constraints, gathered into one place.

    Aggregated rather than left as loose lists on ``User`` so that a future
    engine has exactly one place to ask "what am I not allowed to do?", and
    cannot accidentally consult injuries while forgetting medical constraints.
    """

    injuries: tuple[Injury, ...] = ()
    medical_considerations: tuple[MedicalConsideration, ...] = ()

    is_pregnant: bool | None = None
    pregnancy_due_date: date | None = None

    smokes: bool | None = None
    typical_sleep_hours: float | None = Field(default=None, ge=0.0, le=24.0)
    typical_daily_steps: int | None = Field(default=None, ge=0)

    occupation_activity_level: str | None = Field(
        default=None,
        description="Sedentary desk work versus manual labour meaningfully "
        "changes recovery budget outside of training.",
    )

    @property
    def active_injuries(self) -> tuple[Injury, ...]:
        return tuple(injury for injury in self.injuries if injury.is_limiting)

    @property
    def blocked_movement_patterns(self) -> frozenset[MovementPattern]:
        """Union of every currently-binding movement-pattern contraindication."""
        blocked: set[MovementPattern] = set()
        for injury in self.active_injuries:
            blocked |= injury.contraindicated_movement_patterns
        for consideration in self.medical_considerations:
            if consideration.is_active:
                blocked |= consideration.contraindicated_movement_patterns
        return frozenset(blocked)

    @property
    def blocked_exercise_ids(self) -> frozenset[str]:
        blocked: set[str] = set()
        for injury in self.active_injuries:
            blocked |= injury.contraindicated_exercise_ids
        for consideration in self.medical_considerations:
            if consideration.is_active:
                blocked |= consideration.contraindicated_exercise_ids
        return frozenset(blocked)
