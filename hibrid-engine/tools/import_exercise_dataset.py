"""Convert the hasaneyldrm/exercises-dataset JSON into exercise-library records.

Invoked by ``tools/build_exercise_library.py``; not a standalone entry point.

Committed rather than run once and thrown away, because the mapping decisions
below -- not the output -- are the real content, and a vendored 1300-entry
library that cannot be regenerated is a file nobody dares correct upstream.

Source: https://github.com/hasaneyldrm/exercises-dataset (data: MIT).
Only the data is imported. The dataset's media (``image``, ``gif_url``) is
Gym visual's property, redistributable only under their separate terms, so no
media is copied or referenced -- ``source_id`` is kept so a licensed consumer
can rejoin the media themselves.

Four source fields are dropped as pure redundancy, verified across all 1324
records: ``category`` (identical to ``body_part``), ``muscle_group`` (always
already present in ``secondary_muscles``), ``body_part`` itself (a strict
function of ``target``, so it lives on ``Muscle.body_part``), and the nine
non-English instruction translations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hibrid.models import Equipment, Modality, MovementPattern, Muscle

# The dataset writes the same muscle several ways ("traps"/"trapezius",
# "lats"/"latissimus dorsi"). Substitution matches on shared muscles, so every
# spelling must resolve to one canonical member or valid candidates are lost.
MUSCLE_SYNONYMS: dict[str, Muscle] = {
    # Back
    "lats": Muscle.LATS,
    "latissimus dorsi": Muscle.LATS,
    "upper back": Muscle.UPPER_BACK,
    "back": Muscle.UPPER_BACK,
    "traps": Muscle.TRAPS,
    "trapezius": Muscle.TRAPS,
    "rhomboids": Muscle.RHOMBOIDS,
    "lower back": Muscle.LOWER_BACK,
    "spine": Muscle.SPINE,
    # Cardio
    "cardiovascular system": Muscle.CARDIOVASCULAR_SYSTEM,
    # Chest
    "pectorals": Muscle.PECTORALS,
    "chest": Muscle.PECTORALS,
    "upper chest": Muscle.PECTORALS,
    "serratus anterior": Muscle.SERRATUS_ANTERIOR,
    # Lower arms -- grip and wrist work is forearm work; the dataset's
    # "hands"/"wrists"/"grip muscles" are regions, not distinct muscles.
    "forearms": Muscle.FOREARMS,
    "wrist flexors": Muscle.FOREARMS,
    "wrist extensors": Muscle.FOREARMS,
    "wrists": Muscle.FOREARMS,
    "hands": Muscle.FOREARMS,
    "grip muscles": Muscle.FOREARMS,
    # Lower legs -- soleus stays distinct from calves because it responds to
    # bent-knee work specifically, which is a real programming distinction.
    "calves": Muscle.CALVES,
    "soleus": Muscle.SOLEUS,
    "shins": Muscle.TIBIALIS_ANTERIOR,
    "ankles": Muscle.ANKLE_STABILISERS,
    "ankle stabilizers": Muscle.ANKLE_STABILISERS,
    "feet": Muscle.ANKLE_STABILISERS,
    # Neck
    "levator scapulae": Muscle.LEVATOR_SCAPULAE,
    "sternocleidomastoid": Muscle.STERNOCLEIDOMASTOID,
    # Shoulders
    "delts": Muscle.DELTS,
    "deltoids": Muscle.DELTS,
    "shoulders": Muscle.DELTS,
    "rear deltoids": Muscle.REAR_DELTS,
    "rotator cuff": Muscle.ROTATOR_CUFF,
    # Upper arms
    "biceps": Muscle.BICEPS,
    "triceps": Muscle.TRICEPS,
    "brachialis": Muscle.BRACHIALIS,
    # Upper legs
    "quads": Muscle.QUADS,
    "quadriceps": Muscle.QUADS,
    "hamstrings": Muscle.HAMSTRINGS,
    "glutes": Muscle.GLUTES,
    "adductors": Muscle.ADDUCTORS,
    "inner thighs": Muscle.ADDUCTORS,
    "groin": Muscle.ADDUCTORS,
    "abductors": Muscle.ABDUCTORS,
    "hip flexors": Muscle.HIP_FLEXORS,
    # Waist -- "core" collapses to abs: as a *secondary* tag it means trunk
    # stabilisation, and a separate fuzzy member would overlap abs/obliques
    # without ever being a distinct training target.
    "abs": Muscle.ABS,
    "abdominals": Muscle.ABS,
    "lower abs": Muscle.ABS,
    "core": Muscle.ABS,
    "obliques": Muscle.OBLIQUES,
}

EQUIPMENT_SYNONYMS: dict[str, Equipment] = {
    "assisted": Equipment.ASSISTED,
    "band": Equipment.BAND,
    "barbell": Equipment.BARBELL,
    "body weight": Equipment.BODYWEIGHT,
    "bosu ball": Equipment.BOSU_BALL,
    "cable": Equipment.CABLE,
    "dumbbell": Equipment.DUMBBELL,
    "elliptical machine": Equipment.ELLIPTICAL_MACHINE,
    "ez barbell": Equipment.EZ_BARBELL,
    "hammer": Equipment.HAMMER,
    "kettlebell": Equipment.KETTLEBELL,
    "leverage machine": Equipment.MACHINE,
    "medicine ball": Equipment.MEDICINE_BALL,
    "olympic barbell": Equipment.OLYMPIC_BARBELL,
    "resistance band": Equipment.RESISTANCE_BAND,
    "roller": Equipment.ROLLER,
    "rope": Equipment.ROPE,
    "skierg machine": Equipment.SKIERG_MACHINE,
    "sled machine": Equipment.SLED_MACHINE,
    "smith machine": Equipment.SMITH_MACHINE,
    "stability ball": Equipment.STABILITY_BALL,
    "stationary bike": Equipment.STATIONARY_BIKE,
    "stepmill machine": Equipment.STEPMILL_MACHINE,
    "tire": Equipment.TIRE,
    "trap bar": Equipment.TRAP_BAR,
    "upper body ergometer": Equipment.UPPER_BODY_ERGOMETER,
    "weighted": Equipment.WEIGHTED,
    "wheel roller": Equipment.WHEEL_ROLLER,
}

# The dataset has no movement pattern, but V1 substitution uses one. These name
# rules are checked in order and the first match wins; order is load-bearing,
# e.g. "split squat" must reach the lunge rule before the squat rule sees it,
# and "reverse fly" is a pull that must be caught before the fly rule.
#
# Matched on word boundaries, not as bare substrings: "row" inside "throw down"
# silently classified a batch of core exercises as horizontal pulls.
#
# Deliberately conservative -- an exercise no rule classifies gets None rather
# than a guess, and find_substitutes treats an absent pattern as "unknown"
# rather than "matches nothing".
PATTERN_RULES: tuple[tuple[MovementPattern, tuple[str, ...]], ...] = (
    # Single-joint knee work must be matched BEFORE the pull and squat rules:
    # "inverse leg curl (on pull-up cable machine)" otherwise reads as a
    # vertical pull because of the machine it is performed on.
    (
        MovementPattern.ISOLATION_KNEE,
        (
            r"leg curls?",
            r"hamstring curls?",
            r"leg extensions?",
            r"knee extensions?",
            r"femoral",
            r"prone hamstring",
            r"nordic",
        ),
    ),
    (MovementPattern.ISOLATION_SCAPULAR, (r"shrugs?",)),
    (MovementPattern.CALF, (r"calf raise", r"calf press", r"toe raise")),
    (MovementPattern.LUNGE, (r"lunges?", r"split squats?", r"step-?ups?")),
    (MovementPattern.SQUAT, (r"squats?", r"leg press", r"hack", r"sissy")),
    (
        MovementPattern.HINGE,
        (
            r"deadlifts?",
            r"good mornings?",
            r"hip thrusts?",
            r"glute bridges?",
            r"romanian",
            r"swings?",
            r"back extensions?",
            r"hyperextensions?",
            r"rack pulls?",
            r"cleans?",
            r"snatch(?:es)?",
        ),
    ),
    (
        MovementPattern.VERTICAL_PULL,
        (r"pull-?downs?", r"pull-?ups?", r"chin-?ups?", r"lat pull", r"pull-?overs?"),
    ),
    (MovementPattern.HORIZONTAL_PULL, (r"rows?", r"face pulls?", r"revers(?:e)? fly(?:e?s)?")),
    (
        MovementPattern.VERTICAL_PUSH,
        (
            r"shoulder press",
            r"overhead press",
            r"military press",
            r"push press",
            r"handstand",
            r"dips?",
        ),
    ),
    (
        MovementPattern.HORIZONTAL_PUSH,
        (r"bench press", r"chest press", r"push-?ups?", r"fly(?:e?s)?"),
    ),
    # Single-joint hip work the target-muscle fallback cannot reach, because
    # these share their target with squats and hinges.
    (
        MovementPattern.ISOLATION_HIP,
        (
            r"hip abductions?",
            r"hip adductions?",
            r"hip extensions?",
            r"leg abductions?",
            r"leg adductions?",
            # "Kickback" alone is ambiguous and must stay qualified: a tricep
            # kickback is elbow extension, and the unqualified form matches 11
            # of them in this source -- all already correctly ISOLATION_ARMS
            # via their target muscle.
            r"glute kick-?backs?",
            r"donkey kicks?",
            r"fire hydrants?",
            r"clamshells?",
        ),
    ),
    # Trunk flexion named explicitly, for the handful filed under a leg muscle
    # ("flutter kicks" targets glutes) that PATTERN_BY_TARGET therefore misses.
    (
        MovementPattern.CORE,
        (
            r"crunch(?:es)?",
            r"sit-?ups?",
            r"planks?",
            r"leg raises?",
            r"knee raises?",
            r"flutter kicks?",
            r"scissor kicks?",
            r"russian twists?",
            r"v-?ups?",
        ),
    ),
)

# Fallbacks once no name rule matched: an isolation movement is identifiable
# from what it targets, without needing to recognise its name.
PATTERN_BY_TARGET: dict[Muscle, MovementPattern] = {
    Muscle.BICEPS: MovementPattern.ISOLATION_ARMS,
    Muscle.TRICEPS: MovementPattern.ISOLATION_ARMS,
    Muscle.BRACHIALIS: MovementPattern.ISOLATION_ARMS,
    Muscle.FOREARMS: MovementPattern.ISOLATION_ARMS,
    Muscle.DELTS: MovementPattern.ISOLATION_SHOULDERS,
    Muscle.REAR_DELTS: MovementPattern.ISOLATION_SHOULDERS,
    Muscle.ROTATOR_CUFF: MovementPattern.ISOLATION_SHOULDERS,
    Muscle.ABS: MovementPattern.CORE,
    Muscle.OBLIQUES: MovementPattern.CORE,
    Muscle.SPINE: MovementPattern.CORE,
    Muscle.CALVES: MovementPattern.CALF,
    Muscle.SOLEUS: MovementPattern.CALF,
}

# Modality markers, checked in order. Cardio is decided by target muscle rather
# than by name because that is authoritative source data rather than a keyword
# guess -- it settles the seven exercises ("jack burpee", "mountain climber")
# that read as plyometric by name but are conditioning work.
MOBILITY_MARKERS = r"\bstretch(?:es|ing)?\b"
PLYOMETRIC_MARKERS = r"\b(?:jump|jumping|plyo\w*|hop|bound|burpee)\b"

UNILATERAL_MARKERS: tuple[str, ...] = (
    "one arm",
    "one-arm",
    "one leg",
    "one-leg",
    "single arm",
    "single leg",
    "alternate",
    "alternating",
    "lunge",
    "split squat",
    "step-up",
    "pistol",
)


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def display_name(name: str) -> str:
    """Sentence-case the source's all-lowercase names, leaving them otherwise
    verbatim. Title-casing would mangle 'EZ', '3/4' and the '(male)' media
    annotations, and rewriting source text is not the importer's job."""
    cleaned = re.sub(r"^ez\b", "EZ", name)
    return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned


def resolve_modality(name: str, target: Muscle) -> Modality:
    if target is Muscle.CARDIOVASCULAR_SYSTEM:
        return Modality.CARDIO
    lowered = name.lower()
    if re.search(MOBILITY_MARKERS, lowered):
        return Modality.MOBILITY
    if re.search(PLYOMETRIC_MARKERS, lowered):
        return Modality.PLYOMETRIC
    return Modality.RESISTANCE


def resolve_pattern(name: str, target: Muscle) -> MovementPattern | None:
    if target is Muscle.CARDIOVASCULAR_SYSTEM:
        return None  # a rower/bike is not a horizontal pull
    lowered = name.lower()
    for pattern, keywords in PATTERN_RULES:
        if any(re.search(rf"\b{keyword}\b", lowered) for keyword in keywords):
            return pattern
    return PATTERN_BY_TARGET.get(target)


def convert(record: dict[str, Any]) -> dict[str, Any]:
    target = MUSCLE_SYNONYMS[record["target"]]
    # Secondaries are deduped and stripped of the target: the source often
    # repeats the target muscle in secondary_muscles, and a muscle cannot be
    # both the primary target and a synergist of itself.
    secondary = dict.fromkeys(
        MUSCLE_SYNONYMS[m] for m in record["secondary_muscles"] if MUSCLE_SYNONYMS[m] is not target
    )
    name = display_name(record["name"])
    fields: dict[str, Any] = {
        "name": name,
        "target": target.value,
        "equipment": EQUIPMENT_SYNONYMS[record["equipment"]].value,
        "secondary_muscles": [m.value for m in secondary],
    }
    pattern = resolve_pattern(record["name"], target)
    if pattern is not None:
        fields["movement_pattern"] = pattern.value
    modality = resolve_modality(record["name"], target)
    if modality is not Modality.RESISTANCE:  # resistance is the model default
        fields["modality"] = modality.value
    if any(marker in record["name"].lower() for marker in UNILATERAL_MARKERS):
        fields["unilateral"] = True
    fields["source"] = "exercisedb"
    fields["source_id"] = record["id"]
    return fields


def build(path: Path) -> list[dict[str, Any]]:
    """Library field-dicts, ordered by upstream id.

    A list rather than a name-keyed mapping: six records share an exact name
    with another record, and keying by name would silently drop them."""
    records = json.loads(path.read_text())
    return [convert(record) for record in sorted(records, key=lambda r: r["id"])]
