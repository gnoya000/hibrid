"""User schema for the hibrid engine.

V2 scope: **data modelling only.** These models describe everything a future
routine-generation engine may read about a person; no engine reads them yet.
The schema is deliberately built ahead of the logic because schema churn is far
more expensive than logic churn -- an algorithm can be rewritten, but reshaping
data that has already been collected loses history that cannot be recovered.

Design rules, each explained where it is applied:

1. Canonical metric/SI units everywhere (``types``).
2. Anything measurable and changeable is a dated immutable snapshot, never a
   mutable field (``biometrics``).
3. Provenance travels with every measurement (``enums.MeasurementSource``).
4. Objectives are a normalised weight vector, not a single mode
   (``objectives``).
5. Hard constraints (health, equipment, time) stay distinct from soft
   preferences (``health``, ``preferences``).
6. Prescribed and performed are both recorded, so deviation is visible
   (``history``).
7. Derived data is explicitly labelled as rebuildable cache (``history``).
8. Relationships are ID references, keeping the whole schema projectable onto
   a graph without restructuring (see ``docs/user-schema.md``).
"""

from hibrid.user.biometrics import (
    BodyComposition,
    CardiovascularFitness,
    FitnessAssessment,
    MeasurementRecord,
    RecoveryReading,
    WellnessCheckIn,
)
from hibrid.user.enums import (
    AssessmentMethod,
    BiologicalSex,
    BodyRegion,
    Equipment,
    ExperienceLevel,
    InjuryStatus,
    Laterality,
    MeasurementSource,
    MenstrualPhase,
    MovementPattern,
    SessionStatus,
    TargetMetric,
    TimeOfDay,
    TrainingEnvironment,
    TrainingObjective,
    UnitSystem,
    Weekday,
)
from hibrid.user.health import HealthProfile, Injury, MedicalConsideration
from hibrid.user.history import (
    ExercisePerformanceRecord,
    PerformedExercise,
    PerformedSet,
    TrainingLoadSummary,
    TrainingSession,
)
from hibrid.user.objectives import (
    ObjectiveWeights,
    PerformanceTarget,
    TargetEvent,
    TrainingGoal,
)
from hibrid.user.preferences import (
    AvailabilityWindow,
    EquipmentAccess,
    TrainingPreferences,
)
from hibrid.user.profile import TrainingBackground, UserProfile
from hibrid.user.types import HibridModel, ImmutableModel
from hibrid.user.user import User, latest_before

__all__ = [
    "AssessmentMethod",
    "AvailabilityWindow",
    "BiologicalSex",
    "BodyComposition",
    "BodyRegion",
    "CardiovascularFitness",
    "Equipment",
    "EquipmentAccess",
    "ExercisePerformanceRecord",
    "ExperienceLevel",
    "FitnessAssessment",
    "HealthProfile",
    "HibridModel",
    "ImmutableModel",
    "Injury",
    "InjuryStatus",
    "Laterality",
    "MeasurementRecord",
    "MeasurementSource",
    "MedicalConsideration",
    "MenstrualPhase",
    "MovementPattern",
    "ObjectiveWeights",
    "PerformanceTarget",
    "PerformedExercise",
    "PerformedSet",
    "RecoveryReading",
    "SessionStatus",
    "TargetEvent",
    "TargetMetric",
    "TimeOfDay",
    "TrainingBackground",
    "TrainingEnvironment",
    "TrainingGoal",
    "TrainingLoadSummary",
    "TrainingObjective",
    "TrainingPreferences",
    "TrainingSession",
    "UnitSystem",
    "User",
    "UserProfile",
    "Weekday",
    "WellnessCheckIn",
    "latest_before",
]
