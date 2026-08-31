"""Convert the functional-training CSV into exercise-library records.

Invoked by ``tools/build_exercise_library.py``; not a standalone entry point.

Source: ``data/functional_tranining_bare_dataset.csv`` (semicolon-delimited,
UTF-8 BOM). It supplies ~3200 exercises the original library lacks entirely --
kettlebell, clubbell, macebell, sandbag, rings, sliders, landmine and carry
work -- plus the enrichment attributes the roadmap asked for: difficulty, force
type, mechanics, plane of motion and symmetry.

The source's vocabularies are richer than the library's in two places and
coarser in one:

* Muscles are anatomical (``Biceps Femoris``, ``Iliopsoas``) and collide with
  their own coarse spellings (``Quadriceps Femoris``/``Quadriceps``,
  ``Glutes``/``Gluteus Maximus``). All 57 resolve into the existing 30-member
  ``Muscle`` enum -- no member had to be added. The finer discrimination the
  anatomy would have bought is instead supplied by plane of motion and force
  type, which are real fields rather than a muscle taxonomy.
* Movement patterns are far richer (41 vs 11) and five had to be added to
  ``MovementPattern``; the rest fold into existing members.
* Lunges are not distinguished -- the source files them under ``Knee Dominant``
  alongside squats -- so lunges are recovered from the exercise name.

``Unsorted*`` is the source's own "unknown" marker and is treated as missing
data, never as a value.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from hibrid.models import (
    Difficulty,
    Equipment,
    ForceType,
    Mechanics,
    Modality,
    MovementPattern,
    Muscle,
    PlaneOfMotion,
    Symmetry,
)

#: The source's marker for "we haven't classified this yet".
UNKNOWN = {"", "unsorted*", "none", "other"}

MUSCLE_SYNONYMS: dict[str, Muscle] = {
    # Back
    "latissimus dorsi": Muscle.LATS,
    "teres major": Muscle.LATS,  # functionally the lat's synergist
    "back": Muscle.UPPER_BACK,
    "rhomboids": Muscle.RHOMBOIDS,
    "trapezius": Muscle.TRAPS,
    "upper trapezius": Muscle.TRAPS,
    "levator scapulae": Muscle.LEVATOR_SCAPULAE,
    "erector spinae": Muscle.LOWER_BACK,
    # Chest
    "pectoralis major": Muscle.PECTORALS,
    "chest": Muscle.PECTORALS,
    "serratus anterior": Muscle.SERRATUS_ANTERIOR,
    # Shoulders -- the source separates the three deltoid heads, which the
    # library does not; only the posterior head has its own member, because
    # rear-delt work is programmed separately in a way front/side is not.
    "shoulders": Muscle.DELTS,
    "anterior deltoids": Muscle.DELTS,
    "lateral deltoids": Muscle.DELTS,
    "medial deltoids": Muscle.DELTS,
    "posterior deltoids": Muscle.REAR_DELTS,
    "infraspinatus": Muscle.ROTATOR_CUFF,
    "supraspinatus": Muscle.ROTATOR_CUFF,
    "subscapularis": Muscle.ROTATOR_CUFF,
    "teres minor": Muscle.ROTATOR_CUFF,
    # Arms
    "biceps": Muscle.BICEPS,
    "biceps brachii": Muscle.BICEPS,
    "brachialis": Muscle.BRACHIALIS,
    "triceps": Muscle.TRICEPS,
    "triceps brachii": Muscle.TRICEPS,
    "anconeus": Muscle.TRICEPS,
    "forearms": Muscle.FOREARMS,
    "brachioradialis": Muscle.FOREARMS,
    "flexor carpi radialis": Muscle.FOREARMS,
    # Core
    "abdominals": Muscle.ABS,
    "rectus abdominis": Muscle.ABS,
    "transverse abdominis": Muscle.ABS,
    "obliques": Muscle.OBLIQUES,
    # Hips and legs
    "glutes": Muscle.GLUTES,
    "gluteus maximus": Muscle.GLUTES,
    # Glute med/min are hip abductors by function, but the source lists
    # "Abductors" separately, so its own distinction is preserved.
    "gluteus medius": Muscle.GLUTES,
    "gluteus minimus": Muscle.GLUTES,
    "quadriceps": Muscle.QUADS,
    "quadriceps femoris": Muscle.QUADS,
    "rectus femoris": Muscle.QUADS,
    "vastus mediais": Muscle.QUADS,  # sic -- source typo for vastus medialis
    "hamstrings": Muscle.HAMSTRINGS,
    "biceps femoris": Muscle.HAMSTRINGS,
    "adductors": Muscle.ADDUCTORS,
    "adductor magnus": Muscle.ADDUCTORS,
    "abductors": Muscle.ABDUCTORS,
    "tensor fasciae latae": Muscle.ABDUCTORS,
    "hip flexors": Muscle.HIP_FLEXORS,
    "iliopsoas": Muscle.HIP_FLEXORS,
    # Lower leg
    "calves": Muscle.CALVES,
    "gastrocnemius": Muscle.CALVES,
    "soleus": Muscle.SOLEUS,
    "shins": Muscle.TIBIALIS_ANTERIOR,
    "tibialis anterior": Muscle.TIBIALIS_ANTERIOR,
    "extensor digitorum longus": Muscle.TIBIALIS_ANTERIOR,
    "extensor hallucis longus": Muscle.TIBIALIS_ANTERIOR,
    "tibialis posterior": Muscle.ANKLE_STABILISERS,
}

EQUIPMENT_SYNONYMS: dict[str, Equipment] = {
    "ab wheel": Equipment.AB_WHEEL,
    "barbell": Equipment.BARBELL,
    "battle ropes": Equipment.BATTLE_ROPES,
    "bodyweight": Equipment.BODYWEIGHT,
    "bulgarian bag": Equipment.BULGARIAN_BAG,
    "cable": Equipment.CABLE,
    "climbing rope": Equipment.CLIMBING_ROPE,
    "clubbell": Equipment.CLUBBELL,
    "dumbbell": Equipment.DUMBBELL,
    "ez bar": Equipment.EZ_BARBELL,
    "gymnastic rings": Equipment.GYMNASTIC_RINGS,
    "heavy sandbag": Equipment.SANDBAG,  # same implement, heavier load
    "indian club": Equipment.INDIAN_CLUB,
    "kettlebell": Equipment.KETTLEBELL,
    "landmine": Equipment.LANDMINE,
    "macebell": Equipment.MACEBELL,
    "medicine ball": Equipment.MEDICINE_BALL,
    "miniband": Equipment.MINIBAND,
    "parallette bars": Equipment.PARALLETTE_BARS,
    "pull up bar": Equipment.PULL_UP_BAR,
    "resistance band": Equipment.RESISTANCE_BAND,
    "sandbag": Equipment.SANDBAG,
    "slam ball": Equipment.SLAM_BALL,
    "sled": Equipment.SLED_MACHINE,
    "sliders": Equipment.SLIDERS,
    "stability ball": Equipment.STABILITY_BALL,
    "superband": Equipment.SUPERBAND,
    "suspension trainer": Equipment.SUSPENSION_TRAINER,
    "tire": Equipment.TIRE,
    "trap bar": Equipment.TRAP_BAR,
    "wall ball": Equipment.WALL_BALL,
    "weight plate": Equipment.WEIGHT_PLATE,
}

PATTERN_SYNONYMS: dict[str, MovementPattern] = {
    "knee dominant": MovementPattern.SQUAT,
    "hip hinge": MovementPattern.HINGE,
    "hip dominant": MovementPattern.HINGE,
    "hip extension": MovementPattern.HINGE,
    "horizontal push": MovementPattern.HORIZONTAL_PUSH,
    "horizontal adduction": MovementPattern.HORIZONTAL_PUSH,
    "vertical push": MovementPattern.VERTICAL_PUSH,
    "horizontal pull": MovementPattern.HORIZONTAL_PULL,
    "vertical pull": MovementPattern.VERTICAL_PULL,
    "elbow flexion": MovementPattern.ISOLATION_ARMS,
    "elbow extension": MovementPattern.ISOLATION_ARMS,
    "wrist flexion": MovementPattern.ISOLATION_ARMS,
    "wrist extension": MovementPattern.ISOLATION_ARMS,
    "shoulder abduction": MovementPattern.ISOLATION_SHOULDERS,
    "shoulder flexion": MovementPattern.ISOLATION_SHOULDERS,
    "shoulder external rotation": MovementPattern.ISOLATION_SHOULDERS,
    "shoulder internal rotation": MovementPattern.ISOLATION_SHOULDERS,
    "shoulder scapular plane elevation": MovementPattern.ISOLATION_SHOULDERS,
    # Scapulothoracic, not glenohumeral: a shrug elevates the shoulder blade
    # and shares no joint action with a lateral raise.
    "scapular elevation": MovementPattern.ISOLATION_SCAPULAR,
    "ankle plantar flexion": MovementPattern.CALF,
    "ankle dorsiflexion": MovementPattern.CALF,
    "hip abduction": MovementPattern.ISOLATION_HIP,
    "hip adduction": MovementPattern.ISOLATION_HIP,
    "hip external rotation": MovementPattern.ISOLATION_HIP,
    "hip internal rotation": MovementPattern.ISOLATION_HIP,
    # Anti-* patterns are resisted movement: the trunk's job is to stop motion,
    # which is core work regardless of what the limbs are doing.
    "anti-extension": MovementPattern.CORE,
    "anti-flexion": MovementPattern.CORE,
    "anti-rotational": MovementPattern.CORE,
    "anti-lateral flexion": MovementPattern.CORE,
    "spinal flexion": MovementPattern.CORE,
    "spinal extension": MovementPattern.CORE,
    "lateral flexion": MovementPattern.CORE,
    "hip flexion": MovementPattern.CORE,
    "rotational": MovementPattern.ROTATION,
    "spinal rotational": MovementPattern.ROTATION,
    "isometric hold": MovementPattern.ISOMETRIC_HOLD,
    "loaded carry": MovementPattern.LOADED_CARRY,
    "locomotion": MovementPattern.LOCOMOTION,
    "lateral locomotion": MovementPattern.LOCOMOTION,
}

# "Primary Exercise Classification" is the source's own discipline label and is
# the most direct modality signal available anywhere in the project's data.
MODALITY_SYNONYMS: dict[str, Modality] = {
    "bodybuilding": Modality.RESISTANCE,
    "powerlifting": Modality.RESISTANCE,
    "olympic weightlifting": Modality.RESISTANCE,
    "calisthenics": Modality.RESISTANCE,
    "grinds": Modality.RESISTANCE,
    "postural": Modality.RESISTANCE,
    "plyometric": Modality.PLYOMETRIC,
    "ballistics": Modality.PLYOMETRIC,
    "mobility": Modality.MOBILITY,
    "balance": Modality.BALANCE,
    "animal flow": Modality.BALANCE,
}

DIFFICULTY_SYNONYMS: dict[str, Difficulty] = {d.value: d for d in Difficulty}
FORCE_SYNONYMS: dict[str, ForceType] = {
    "push": ForceType.PUSH,
    "pull": ForceType.PULL,
    "push & pull": ForceType.PUSH_AND_PULL,
}
PLANE_SYNONYMS: dict[str, PlaneOfMotion] = {
    "sagittal plane": PlaneOfMotion.SAGITTAL,
    "frontal plane": PlaneOfMotion.FRONTAL,
    "transverse plane": PlaneOfMotion.TRANSVERSE,
}
SYMMETRY_SYNONYMS: dict[str, Symmetry] = {s.value: s for s in Symmetry}


def clean(value: str | None) -> str:
    text = (value or "").strip().lower()
    return "" if text in UNKNOWN else text


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


#: "Knee Dominant" in the source covers every movement the knee drives --
#: squats, lunges and single-joint curls/extensions alike -- so mapping it
#: straight to SQUAT mislabels the other two. Both are recovered from the name.
#: Order matters against the lunge rule below only in that neither overlaps.
KNEE_ISOLATION_MARKERS = r"\b(?:leg curls?|hamstring curls?|leg extensions?|nordic|femoral)\b"


def resolve_pattern(row: dict[str, str], name: str) -> MovementPattern | None:
    lowered = name.lower()
    # The source files lunges under "Knee Dominant" with squats, losing a
    # distinction the library already makes, so recover it from the name first.
    if re.search(r"\b(?:lunge|lunges|split squat|step-?up)\b", lowered):
        return MovementPattern.LUNGE

    source_pattern: MovementPattern | None = None
    for column in ("Movement Pattern #1", "Movement Pattern #2", "Movement Pattern #3"):
        source_pattern = PATTERN_SYNONYMS.get(clean(row.get(column)))
        if source_pattern is not None:
            break

    # Same category, same problem: a Nordic hamstring curl is not a squat. This
    # is scoped to the knee-dominant bucket deliberately -- applied globally the
    # markers also match holds whose *name* mentions a leg extension performed
    # during them ("Ring Tuck Front Lever with Alternating Single Leg
    # Extensions"), which are isometric holds, not knee isolation.
    if source_pattern is MovementPattern.SQUAT and re.search(KNEE_ISOLATION_MARKERS, lowered):
        return MovementPattern.ISOLATION_KNEE
    return source_pattern


def convert(row: dict[str, str]) -> dict[str, Any] | None:
    """One CSV row into library fields, or None if it cannot be placed."""
    target = MUSCLE_SYNONYMS.get(clean(row["Prime Mover Muscle"])) or MUSCLE_SYNONYMS.get(
        clean(row["Target Muscle Group"])
    )
    equipment = EQUIPMENT_SYNONYMS.get(clean(row["Primary Equipment"]))
    if target is None or equipment is None:
        return None

    name = row["Exercise"]
    secondary = dict.fromkeys(
        muscle
        for column in ("Target Muscle Group", "Secondary Muscle", "Tertiary Muscle")
        if (muscle := MUSCLE_SYNONYMS.get(clean(row.get(column)))) is not None
        and muscle is not target
    )
    symmetry = SYMMETRY_SYNONYMS.get(clean(row["Laterality"]))

    fields: dict[str, Any] = {
        "name": name,
        "target": target.value,
        "equipment": equipment.value,
        "secondary_muscles": [m.value for m in secondary],
    }
    pattern = resolve_pattern(row, name)
    if pattern is not None:
        fields["movement_pattern"] = pattern.value
    modality = MODALITY_SYNONYMS.get(clean(row["Primary Exercise Classification"]))
    if modality is not None and modality is not Modality.RESISTANCE:
        fields["modality"] = modality.value
    if symmetry is not None and symmetry is not Symmetry.BILATERAL:
        fields["unilateral"] = True

    optional: dict[str, Any] = {
        "difficulty": DIFFICULTY_SYNONYMS.get(clean(row["Difficulty Level"])),
        "force_type": FORCE_SYNONYMS.get(clean(row["Force Type"])),
        "mechanics": Mechanics.__members__.get(clean(row["Mechanics"]).upper()),
        "plane_of_motion": PLANE_SYNONYMS.get(clean(row["Plane Of Motion #1"])),
        "symmetry": symmetry,
    }
    fields.update({k: v.value for k, v in optional.items() if v is not None})
    fields["source"] = "functional"
    return fields


def build(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Library field-dicts, plus a count of rows that could not be mapped.

    A list rather than a name-keyed mapping so that rows sharing an exact name
    are not silently dropped."""
    records: list[dict[str, Any]] = []
    skipped = 0
    for row in read_rows(path):
        fields = convert(row)
        if fields is None:
            skipped += 1
            continue
        records.append(fields)
    return records, skipped
