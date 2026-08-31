from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID, uuid4


class MovementPattern(str, Enum):
    """How a movement loads the body.

    The classic gym patterns came first. The functional-training import added
    the rest, which cannot be expressed without them -- a loaded carry, a
    Turkish get-up and a bear crawl are not squats, presses or pulls, and
    collapsing them into the gym vocabulary would make them substitutable for
    things they have nothing in common with.

    ``ISOLATION_KNEE`` and ``ISOLATION_SCAPULAR`` were added later, for the
    same reason and after an audit found their absence producing *wrong* data
    rather than merely missing data. A leg curl and a leg extension are
    single-joint knee movements with no home among squat/hinge/lunge, so the
    functional source's broad "knee dominant" category was labelling Nordic
    curls as ``SQUAT``; a shrug is scapulothoracic, not glenohumeral, so it was
    being filed under ``ISOLATION_SHOULDERS``. Both are named for the joint
    they isolate, matching ``ISOLATION_HIP``.

    A wrong pattern is worse than an absent one: ``VariationContext.permits``
    fails closed on an unknown pattern when a health contraindication is
    present, but a confidently-wrong pattern sails straight through that
    guard."""

    HORIZONTAL_PUSH = "horizontal_push"
    VERTICAL_PUSH = "vertical_push"
    HORIZONTAL_PULL = "horizontal_pull"
    VERTICAL_PULL = "vertical_pull"
    SQUAT = "squat"
    HINGE = "hinge"
    LUNGE = "lunge"
    CORE = "core"
    ISOLATION_ARMS = "isolation_arms"
    ISOLATION_SHOULDERS = "isolation_shoulders"
    ISOLATION_KNEE = "isolation_knee"
    ISOLATION_SCAPULAR = "isolation_scapular"
    CALF = "calf"
    # Functional patterns
    ROTATION = "rotation"
    ISOMETRIC_HOLD = "isometric_hold"
    LOADED_CARRY = "loaded_carry"
    LOCOMOTION = "locomotion"
    ISOLATION_HIP = "isolation_hip"


class Difficulty(str, Enum):
    """Skill/strength prerequisite, ordered easiest to hardest.

    The functional source grades on eight levels rather than the usual three,
    and the top four are a real distinction in that domain -- a press handstand
    is not merely an "advanced" push-up. Kept at source granularity because
    collapsing it is lossy and trivial to do later; ``rank`` gives the ordering
    that a progression needs."""

    BEGINNER = "beginner"
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
    MASTER = "master"
    GRAND_MASTER = "grand_master"
    LEGENDARY = "legendary"

    @property
    def rank(self) -> int:
        return _DIFFICULTY_ORDER.index(self)


_DIFFICULTY_ORDER: tuple["Difficulty", ...] = (
    Difficulty.BEGINNER,
    Difficulty.NOVICE,
    Difficulty.INTERMEDIATE,
    Difficulty.ADVANCED,
    Difficulty.EXPERT,
    Difficulty.MASTER,
    Difficulty.GRAND_MASTER,
    Difficulty.LEGENDARY,
)


class ForceType(str, Enum):
    PUSH = "push"
    PULL = "pull"
    PUSH_AND_PULL = "push_and_pull"
    OTHER = "other"


class Mechanics(str, Enum):
    COMPOUND = "compound"
    ISOLATION = "isolation"


class PlaneOfMotion(str, Enum):
    """The anatomical plane a movement travels in.

    Together with ``ForceType`` this is the discrimination the muscle tags could
    never provide: a lateral raise and a shoulder external rotation share every
    muscle tag but move in different planes."""

    SAGITTAL = "sagittal"
    FRONTAL = "frontal"
    TRANSVERSE = "transverse"


class Symmetry(str, Enum):
    """Whether a movement loads both sides, one side, or crosses the midline.

    Deliberately *not* named ``Laterality``: ``hibrid.user.enums.Laterality``
    already means left/right/bilateral for an injury *site*, which is an
    unrelated concept. Sharing the name would invite exactly the kind of quiet
    mismatch the shared-vocabulary rule exists to prevent."""

    BILATERAL = "bilateral"
    UNILATERAL = "unilateral"
    CONTRALATERAL = "contralateral"
    IPSILATERAL = "ipsilateral"


class Modality(str, Enum):
    """The kind of training an exercise is, independent of what it targets.

    The project's premise is that objectives like flexibility and agility are
    unreachable through resistance training alone, so *which discipline* a piece
    of work belongs to has to be first-class rather than inferred from equipment.

    This is also the axis on which "equivalent work" stops being comparable:
    ``sets x reps x weight`` is the dose for RESISTANCE and is meaningless for
    the others, each of which needs its own measure (duration, distance,
    contacts). Prescription is not yet modality-generic -- see
    ``docs/roadmap.md`` M1, which this enum exists to unblock."""

    RESISTANCE = "resistance"
    CARDIO = "cardio"
    MOBILITY = "mobility"
    PLYOMETRIC = "plyometric"
    BALANCE = "balance"


class BodyPart(str, Enum):
    """Coarse anatomical grouping. Never stored on an exercise -- it is derived
    from the target muscle via ``Muscle.body_part``, because in the source
    dataset every target muscle belongs to exactly one body part."""

    BACK = "back"
    CARDIO = "cardio"
    CHEST = "chest"
    LOWER_ARMS = "lower_arms"
    LOWER_LEGS = "lower_legs"
    NECK = "neck"
    SHOULDERS = "shoulders"
    UPPER_ARMS = "upper_arms"
    UPPER_LEGS = "upper_legs"
    WAIST = "waist"


class Muscle(str, Enum):
    """Canonical muscle vocabulary.

    The source dataset expresses muscles as free text and collides with itself:
    ``traps``/``trapezius``, ``lats``/``latissimus dorsi``, ``quads``/
    ``quadriceps``, ``delts``/``deltoids``/``shoulders`` all appear as distinct
    strings for the same muscle. Substitution matches on shared muscles, so an
    un-normalised vocabulary silently loses valid candidates -- a barbell row
    tagged ``traps`` would not match a shrug tagged ``trapezius``.

    This enum is the single normalised vocabulary; the raw-string synonyms are
    resolved at import time (see ``tools/import_exercise_dataset.py``)."""

    # Back
    LATS = "lats"
    UPPER_BACK = "upper_back"
    TRAPS = "traps"
    RHOMBOIDS = "rhomboids"
    LOWER_BACK = "lower_back"
    SPINE = "spine"
    # Cardio
    CARDIOVASCULAR_SYSTEM = "cardiovascular_system"
    # Chest
    PECTORALS = "pectorals"
    SERRATUS_ANTERIOR = "serratus_anterior"
    # Lower arms
    FOREARMS = "forearms"
    # Lower legs
    CALVES = "calves"
    SOLEUS = "soleus"
    TIBIALIS_ANTERIOR = "tibialis_anterior"
    ANKLE_STABILISERS = "ankle_stabilisers"
    # Neck
    LEVATOR_SCAPULAE = "levator_scapulae"
    STERNOCLEIDOMASTOID = "sternocleidomastoid"
    # Shoulders
    DELTS = "delts"
    REAR_DELTS = "rear_delts"
    ROTATOR_CUFF = "rotator_cuff"
    # Upper arms
    BICEPS = "biceps"
    TRICEPS = "triceps"
    BRACHIALIS = "brachialis"
    # Upper legs
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    ADDUCTORS = "adductors"
    ABDUCTORS = "abductors"
    HIP_FLEXORS = "hip_flexors"
    # Waist
    ABS = "abs"
    OBLIQUES = "obliques"

    @property
    def body_part(self) -> BodyPart:
        return _MUSCLE_BODY_PART[self]


_MUSCLE_BODY_PART: dict[Muscle, BodyPart] = {
    Muscle.LATS: BodyPart.BACK,
    Muscle.UPPER_BACK: BodyPart.BACK,
    Muscle.TRAPS: BodyPart.BACK,
    Muscle.RHOMBOIDS: BodyPart.BACK,
    Muscle.LOWER_BACK: BodyPart.BACK,
    Muscle.SPINE: BodyPart.BACK,
    Muscle.CARDIOVASCULAR_SYSTEM: BodyPart.CARDIO,
    Muscle.PECTORALS: BodyPart.CHEST,
    Muscle.SERRATUS_ANTERIOR: BodyPart.CHEST,
    Muscle.FOREARMS: BodyPart.LOWER_ARMS,
    Muscle.CALVES: BodyPart.LOWER_LEGS,
    Muscle.SOLEUS: BodyPart.LOWER_LEGS,
    Muscle.TIBIALIS_ANTERIOR: BodyPart.LOWER_LEGS,
    Muscle.ANKLE_STABILISERS: BodyPart.LOWER_LEGS,
    Muscle.LEVATOR_SCAPULAE: BodyPart.NECK,
    Muscle.STERNOCLEIDOMASTOID: BodyPart.NECK,
    Muscle.DELTS: BodyPart.SHOULDERS,
    Muscle.REAR_DELTS: BodyPart.SHOULDERS,
    Muscle.ROTATOR_CUFF: BodyPart.SHOULDERS,
    Muscle.BICEPS: BodyPart.UPPER_ARMS,
    Muscle.TRICEPS: BodyPart.UPPER_ARMS,
    Muscle.BRACHIALIS: BodyPart.UPPER_ARMS,
    Muscle.QUADS: BodyPart.UPPER_LEGS,
    Muscle.HAMSTRINGS: BodyPart.UPPER_LEGS,
    Muscle.GLUTES: BodyPart.UPPER_LEGS,
    Muscle.ADDUCTORS: BodyPart.UPPER_LEGS,
    Muscle.ABDUCTORS: BodyPart.UPPER_LEGS,
    Muscle.HIP_FLEXORS: BodyPart.UPPER_LEGS,
    Muscle.ABS: BodyPart.WAIST,
    Muscle.OBLIQUES: BodyPart.WAIST,
}


class Equipment(str, Enum):
    """Equipment vocabulary, matching the source dataset's distinctions.

    Shared with ``hibrid.user`` (``EquipmentAccess``), so a gym inventory and an
    exercise requirement are always expressed in the same terms."""

    AB_WHEEL = "ab_wheel"
    ASSISTED = "assisted"
    BAND = "band"
    BARBELL = "barbell"
    BATTLE_ROPES = "battle_ropes"
    BODYWEIGHT = "bodyweight"
    BOSU_BALL = "bosu_ball"
    BULGARIAN_BAG = "bulgarian_bag"
    CABLE = "cable"
    CLIMBING_ROPE = "climbing_rope"
    CLUBBELL = "clubbell"
    DUMBBELL = "dumbbell"
    ELLIPTICAL_MACHINE = "elliptical_machine"
    EZ_BARBELL = "ez_barbell"
    GYMNASTIC_RINGS = "gymnastic_rings"
    HAMMER = "hammer"
    INDIAN_CLUB = "indian_club"
    KETTLEBELL = "kettlebell"
    LANDMINE = "landmine"
    MACEBELL = "macebell"
    MACHINE = "machine"
    MEDICINE_BALL = "medicine_ball"
    MINIBAND = "miniband"
    OLYMPIC_BARBELL = "olympic_barbell"
    PARALLETTE_BARS = "parallette_bars"
    PULL_UP_BAR = "pull_up_bar"
    RESISTANCE_BAND = "resistance_band"
    ROLLER = "roller"
    ROPE = "rope"
    SANDBAG = "sandbag"
    SKIERG_MACHINE = "skierg_machine"
    SLAM_BALL = "slam_ball"
    SLED_MACHINE = "sled_machine"
    SLIDERS = "sliders"
    SMITH_MACHINE = "smith_machine"
    STABILITY_BALL = "stability_ball"
    STATIONARY_BIKE = "stationary_bike"
    STEPMILL_MACHINE = "stepmill_machine"
    SUPERBAND = "superband"
    SUSPENSION_TRAINER = "suspension_trainer"
    TIRE = "tire"
    TRAP_BAR = "trap_bar"
    UPPER_BODY_ERGOMETER = "upper_body_ergometer"
    WALL_BALL = "wall_ball"
    WEIGHT_PLATE = "weight_plate"
    WEIGHTED = "weighted"
    WHEEL_ROLLER = "wheel_roller"


#: Equipment that supplies no external load, so a prescribed ``weight`` is not a
#: load the user selects. Consulted by substitution to avoid solving a
#: physically meaningless "implied weight" -- see the known limitation in
#: ``variation.py``.
BODYWEIGHT_EQUIPMENT: frozenset[Equipment] = frozenset(
    {
        Equipment.AB_WHEEL,
        Equipment.ASSISTED,
        Equipment.BODYWEIGHT,
        Equipment.BOSU_BALL,
        Equipment.CLIMBING_ROPE,
        Equipment.GYMNASTIC_RINGS,
        Equipment.PARALLETTE_BARS,
        Equipment.PULL_UP_BAR,
        Equipment.ROLLER,
        Equipment.SLIDERS,
        Equipment.STABILITY_BALL,
        Equipment.SUSPENSION_TRAINER,
        Equipment.WHEEL_ROLLER,
    }
)


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    target: Muscle
    equipment: Equipment
    secondary_muscles: tuple[Muscle, ...] = ()
    movement_pattern: MovementPattern | None = None
    modality: Modality = Modality.RESISTANCE
    unilateral: bool = False
    # Enrichment attributes. Optional because they are only as good as the
    # source that supplied them -- the functional dataset carries all of them,
    # the original library carries none, and inventing values for the gap would
    # be worse than an honest None.
    difficulty: Difficulty | None = None
    force_type: ForceType | None = None
    mechanics: Mechanics | None = None
    plane_of_motion: PlaneOfMotion | None = None
    symmetry: Symmetry | None = None
    source: str | None = None
    source_id: str | None = None

    @property
    def body_part(self) -> BodyPart:
        return self.target.body_part

    @property
    def muscles(self) -> frozenset[Muscle]:
        """Target plus secondaries -- the full set this exercise trains."""
        return frozenset((self.target, *self.secondary_muscles))

    @property
    def is_bodyweight(self) -> bool:
        return self.equipment in BODYWEIGHT_EQUIPMENT

    def similarity(self, other: "Exercise") -> float:
        """How interchangeable two exercises are, in ``[0.0, 1.0]``.

        Weighted so the primary target dominates: hitting the same target muscle
        is worth more than any amount of secondary overlap, because an exercise
        sharing only secondaries trains something different. Secondary overlap
        is scored by Jaccard index so that broad, many-muscle exercises do not
        outrank precise matches purely by having more tags.

        ``plane_of_motion`` and ``force_type`` break the ties muscle tags cannot:
        a lateral raise and a shoulder external rotation carry identical muscle
        tags but move in different planes. They only contribute when *both*
        exercises declare them, so an enriched exercise is never penalised for
        being compared against one from a source that lacked the field."""
        target_score = 1.0 if self.target is other.target else 0.0
        mine, theirs = set(self.secondary_muscles), set(other.secondary_muscles)
        union = mine | theirs
        secondary_score = len(mine & theirs) / len(union) if union else 0.0
        base = 0.7 * target_score + 0.3 * secondary_score

        comparable = [
            (self.plane_of_motion, other.plane_of_motion),
            (self.force_type, other.force_type),
        ]
        known = [(a, b) for a, b in comparable if a is not None and b is not None]
        if not known:
            return base
        agreement = sum(1.0 for a, b in known if a is b) / len(known)
        # Scaled, not added, so the result stays in [0, 1] and a shared target
        # still outranks any amount of agreement on the secondary axes.
        return base * (0.8 + 0.2 * agreement)


class Dose(ABC):
    """The prescribed quantity of work for one routine entry.

    Resistance training's dose is sets x reps x weight, and nothing else in
    the library can be described that way -- a plank has no reps, a row has no
    discrete rep at all. Rather than one record with most fields ``None``
    depending on modality, each shape gets its own class, so "how much work is
    this" and "how long does it take" are defined once per shape instead of
    inferred from which fields happen to be populated. See ``docs/roadmap.md``
    M1, and ``hibrid.user.history.PerformedSet`` for the logging-side
    counterpart this mirrors.
    """

    @property
    @abstractmethod
    def load_volume(self) -> float:
        """The per-modality "equivalent work" quantity a variation holds
        constant. Not comparable across dose types -- kg-reps, metres and
        seconds are different currencies."""

    @abstractmethod
    def time_seconds(self, rest_seconds: int) -> float:
        """Total time this dose takes, given the rest between sets/rounds."""

    @abstractmethod
    def describe(self) -> str:
        """Short human-readable rendering, e.g. ``"4x8@80"`` or ``"3x45s"``."""


@dataclass(frozen=True)
class RepsDose(Dose):
    """Resistance training: sets of reps against an external (or zero) load."""

    sets: int
    reps: int
    weight: float
    rep_seconds: float = 3.0

    @property
    def load_volume(self) -> float:
        return self.sets * self.reps * self.weight

    def time_seconds(self, rest_seconds: int) -> float:
        return self.sets * (self.reps * self.rep_seconds + rest_seconds)

    def describe(self) -> str:
        return f"{self.sets}x{self.reps}@{self.weight}"


@dataclass(frozen=True)
class DurationDose(Dose):
    """Time-under-tension work with no discrete reps: holds, planks, stretches."""

    sets: int
    duration_seconds: float

    @property
    def load_volume(self) -> float:
        return self.sets * self.duration_seconds

    def time_seconds(self, rest_seconds: int) -> float:
        return self.sets * (self.duration_seconds + rest_seconds)

    def describe(self) -> str:
        return f"{self.sets}x{self.duration_seconds:.0f}s"


@dataclass(frozen=True)
class DistanceDose(Dose):
    """Distance-based cardio: a run, a row."""

    distance_m: float
    duration_seconds: float

    @property
    def load_volume(self) -> float:
        return self.distance_m

    def time_seconds(self, rest_seconds: int) -> float:
        return self.duration_seconds + rest_seconds

    def describe(self) -> str:
        return f"{self.distance_m:.0f}m/{self.duration_seconds:.0f}s"


@dataclass(frozen=True)
class RoundsDose(Dose):
    """Circuit-style work measured in completed rounds, not sets of one
    exercise -- intervals, EMOM, AMRAP (see ``docs/roadmap.md`` M6)."""

    rounds: int
    round_seconds: float

    @property
    def load_volume(self) -> float:
        return self.rounds

    def time_seconds(self, rest_seconds: int) -> float:
        return self.rounds * (self.round_seconds + rest_seconds)

    def describe(self) -> str:
        return f"{self.rounds} rounds/{self.round_seconds:.0f}s"


@dataclass
class RoutineEntry:
    exercise_id: str
    dose: Dose
    rest_seconds: int = 90

    @property
    def volume(self) -> float:
        return self.dose.load_volume

    @property
    def time_seconds(self) -> float:
        return self.dose.time_seconds(self.rest_seconds)


@dataclass
class Routine:
    name: str
    entries: list[RoutineEntry] = field(default_factory=list)
    routine_id: UUID = field(default_factory=uuid4)

    @property
    def total_volume(self) -> float:
        """Sum of each entry's own dose currency. Only physically meaningful
        when every entry shares a dose type -- see ``Dose.load_volume``."""
        return sum(e.volume for e in self.entries)

    @property
    def total_time_seconds(self) -> float:
        return sum(e.time_seconds for e in self.entries)
