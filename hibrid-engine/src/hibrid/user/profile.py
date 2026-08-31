"""Stable identity, demographics, and training background.

Governing rule for what belongs here: **anything measurable and changeable is a
dated snapshot, not a profile field.** Height, body mass and fitness scores all
live in ``biometrics`` even though two of them barely move, because a single
consistent rule removes the recurring "is this a profile attribute or a
measurement?" argument and guarantees the engine can always see a trend.

Age is likewise never stored -- only ``birth_date`` is, with age derived on
demand. A stored age is wrong the day after it is written.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from pydantic import Field

from hibrid.user.enums import BiologicalSex, ExperienceLevel, UnitSystem
from hibrid.user.types import HibridModel, SessionsPerWeek


def _years_between(start: date, end: date) -> float:
    """Elapsed years, using the average Gregorian year to stay continuous.

    Continuity matters more than calendar exactness here: a training model
    consuming age as a feature should see it advance smoothly rather than jump
    by a whole year on a birthday.
    """
    return (end - start).days / 365.2425


class UserProfile(HibridModel):
    """Who the user is, independent of their current condition."""

    user_id: UUID = Field(default_factory=uuid4)
    display_name: str | None = None

    birth_date: date
    biological_sex: BiologicalSex = BiologicalSex.UNDISCLOSED

    gender_identity: str | None = Field(
        default=None,
        description=(
            "Free text, for addressing the person. Intentionally NOT an enum and "
            "intentionally not an algorithm input -- see BiologicalSex, which is "
            "the field physiological modelling should read."
        ),
    )

    timezone: str = Field(
        default="UTC",
        description=(
            "IANA timezone name. Required to interpret device timestamps and to "
            "schedule sessions in the user's own local time."
        ),
    )
    locale: str | None = None
    unit_system: UnitSystem = UnitSystem.METRIC

    created_at: datetime
    updated_at: datetime | None = None

    def age_years(self, on: date) -> float:
        """Age on a given date. Requires the date explicitly so that any value
        derived from a historical record is computed as of that record."""
        return _years_between(self.birth_date, on)


class TrainingBackground(HibridModel):
    """Training experience, which conditions how fast progression may advance.

    Separated from ``UserProfile`` because it evolves on a different timescale
    and for different reasons than identity does.
    """

    experience_level: ExperienceLevel = ExperienceLevel.BEGINNER

    training_start_date: date | None = Field(
        default=None,
        description=(
            "When consistent training began. Training age predicts adaptation "
            "rate far better than chronological age does."
        ),
    )
    resistance_training_start_date: date | None = None

    primary_sport: str | None = None
    secondary_sports: tuple[str, ...] = ()

    typical_sessions_per_week: SessionsPerWeek | None = Field(
        default=None,
        description="Historic adherence baseline, not the aspirational target.",
    )
    longest_consistent_streak_weeks: int | None = Field(default=None, ge=0)

    has_coaching_experience: bool = False
    familiar_exercise_ids: frozenset[str] = frozenset()
    """Exercise ids the user can already perform with sound technique. Prevents
    prescribing a technically demanding lift to someone who has never done it."""

    def training_age_years(self, on: date) -> float | None:
        if self.training_start_date is None:
            return None
        return _years_between(self.training_start_date, on)
