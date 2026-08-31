"""Closed vocabularies for the user schema.

Every one of these is a candidate node label or categorical feature in the
eventual graph model, which is why they are enums rather than free strings: a
closed set can be embedded, one-hot encoded, or made a node without a cleaning
step. Open-ended text that resists a closed set (a medical condition name, a
sport) stays a plain ``str`` field instead of being forced into an enum.

``Equipment`` and ``MovementPattern`` are deliberately NOT redefined here --
they already exist in ``hibrid.models`` and are re-exported so the user schema
and the exercise library share one vocabulary.
"""

from __future__ import annotations

from enum import Enum, IntEnum

from hibrid.models import Equipment, MovementPattern

__all__ = [
    "AssessmentMethod",
    "BiologicalSex",
    "BodyRegion",
    "Equipment",
    "ExperienceLevel",
    "InjuryStatus",
    "Laterality",
    "MeasurementSource",
    "MenstrualPhase",
    "MovementPattern",
    "SessionStatus",
    "TargetMetric",
    "TimeOfDay",
    "TrainingEnvironment",
    "TrainingObjective",
    "UnitSystem",
    "Weekday",
]


class BiologicalSex(str, Enum):
    """Sex used strictly for physiological modelling.

    This drives things that genuinely differ physiologically -- relative
    strength norms, VO2max percentile tables, cycle-aware periodization. It is
    kept separate from ``UserProfile.gender_identity``, which is how the person
    is addressed and carries no algorithmic meaning. Conflating the two would
    make the model both less accurate and less respectful.
    """

    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"
    UNDISCLOSED = "undisclosed"


class UnitSystem(str, Enum):
    """Display preference only -- stored values are always metric."""

    METRIC = "metric"
    IMPERIAL = "imperial"


class ExperienceLevel(str, Enum):
    UNTRAINED = "untrained"
    BEGINNER = "beginner"
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    ELITE = "elite"


class TrainingObjective(str, Enum):
    """Trainable qualities a routine can be optimised toward.

    Kept granular on purpose: "endurance" alone conflates muscular endurance
    (high-rep resistance work) with cardiovascular endurance (aerobic work),
    which call for opposite prescriptions.
    """

    STRENGTH = "strength"
    POWER = "power"
    HYPERTROPHY = "hypertrophy"
    MUSCULAR_ENDURANCE = "muscular_endurance"
    CARDIOVASCULAR_ENDURANCE = "cardiovascular_endurance"
    SPEED = "speed"
    AGILITY = "agility"
    BALANCE = "balance"
    FLEXIBILITY = "flexibility"
    MOBILITY = "mobility"
    BODY_RECOMPOSITION = "body_recomposition"
    GENERAL_HEALTH = "general_health"
    REHABILITATION = "rehabilitation"


class Weekday(IntEnum):
    """Values match ``datetime.date.weekday()`` so the two interoperate."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class TimeOfDay(str, Enum):
    EARLY_MORNING = "early_morning"
    MORNING = "morning"
    MIDDAY = "midday"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class TrainingEnvironment(str, Enum):
    COMMERCIAL_GYM = "commercial_gym"
    HOME_GYM = "home_gym"
    BODYWEIGHT_ONLY = "bodyweight_only"
    OUTDOOR = "outdoor"
    HOTEL_GYM = "hotel_gym"
    POOL = "pool"
    STUDIO = "studio"


class MeasurementSource(str, Enum):
    """Provenance of a recorded value.

    Retained because reliability differs sharply by source -- a chest-strap HR
    reading and a wrist-optical one are not interchangeable evidence, and a
    future model should be able to weight them differently rather than treating
    every number as equally trustworthy.
    """

    MANUAL_ENTRY = "manual_entry"
    APPLE_HEALTH = "apple_health"
    GOOGLE_FIT = "google_fit"
    GARMIN = "garmin"
    WHOOP = "whoop"
    OURA = "oura"
    FITBIT = "fitbit"
    POLAR = "polar"
    STRAVA = "strava"
    WITHINGS = "withings"
    SMART_SCALE = "smart_scale"
    CHEST_STRAP = "chest_strap"
    LAB_TEST = "lab_test"
    CLINICAL = "clinical"
    COACH_ASSESSMENT = "coach_assessment"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class BodyRegion(str, Enum):
    """Anatomical regions, used to localise injuries and limitations."""

    NECK = "neck"
    SHOULDER = "shoulder"
    ELBOW = "elbow"
    WRIST = "wrist"
    HAND = "hand"
    CHEST = "chest"
    UPPER_BACK = "upper_back"
    LOWER_BACK = "lower_back"
    CORE = "core"
    HIP = "hip"
    GROIN = "groin"
    HAMSTRING = "hamstring"
    QUADRICEPS = "quadriceps"
    KNEE = "knee"
    CALF = "calf"
    ANKLE = "ankle"
    FOOT = "foot"
    ACHILLES = "achilles"


class Laterality(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"


class InjuryStatus(str, Enum):
    ACTIVE = "active"
    RECOVERING = "recovering"
    RESOLVED = "resolved"
    CHRONIC = "chronic"


class MenstrualPhase(str, Enum):
    """Optional cycle context.

    Cycle phase measurably affects recovery capacity and injury risk, so it is
    a legitimate periodization input. Every field referencing it is optional
    and nullable -- the schema must work identically when it is never provided.
    """

    MENSTRUAL = "menstrual"
    FOLLICULAR = "follicular"
    OVULATORY = "ovulatory"
    LUTEAL = "luteal"
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    """How a prescribed session actually went.

    Adherence is a first-class signal: a routine that is repeatedly skipped or
    cut short is a failed prescription regardless of how good it looked on
    paper, and the engine needs to be able to see that.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    ABORTED = "aborted"
    UNPLANNED = "unplanned"


class TargetMetric(str, Enum):
    """What a measurable goal is expressed in."""

    ONE_REP_MAX_KG = "one_rep_max_kg"
    REPS_AT_LOAD = "reps_at_load"
    BODY_MASS_KG = "body_mass_kg"
    BODY_FAT_PERCENT = "body_fat_percent"
    DISTANCE_M = "distance_m"
    DURATION_SECONDS = "duration_seconds"
    VO2MAX = "vo2max"
    RANGE_OF_MOTION_DEGREES = "range_of_motion_degrees"
    FITNESS_SCORE = "fitness_score"


class AssessmentMethod(str, Enum):
    DIRECT_MEASUREMENT = "direct_measurement"
    FIELD_TEST = "field_test"
    SUBMAXIMAL_ESTIMATE = "submaximal_estimate"
    FORMULA_ESTIMATE = "formula_estimate"
    WEARABLE_ESTIMATE = "wearable_estimate"
    SELF_REPORTED = "self_reported"
