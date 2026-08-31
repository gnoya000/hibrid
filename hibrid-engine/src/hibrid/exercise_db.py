from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import yaml

from hibrid.models import (
    Difficulty,
    Equipment,
    Exercise,
    ForceType,
    Mechanics,
    Modality,
    MovementPattern,
    Muscle,
    PlaneOfMotion,
    Symmetry,
)

EnumT = TypeVar("EnumT", bound=Enum)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "exercises.yaml"


class UnknownExerciseError(KeyError):
    """An exercise id that is not in the library.

    Subclasses ``KeyError`` so existing lookup handling still catches it, but
    carries the id as an attribute: a bare ``KeyError`` from a dict lookup deep
    in the engine reads as an internal fault, when the cause is almost always a
    caller's typo. ``hibrid.api`` translates this into a 400 rather than
    letting it surface as a 500."""

    def __init__(self, exercise_id: str) -> None:
        super().__init__(exercise_id)
        self.exercise_id = exercise_id

try:  # libyaml when available -- the library is ~1300 entries and on the hot path
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover - depends on the local libyaml build
    from yaml import SafeLoader as _Loader  # type: ignore[assignment]


class ExerciseDB:
    def __init__(self, exercises: dict[str, Exercise]):
        self._exercises = exercises

    @classmethod
    def load(cls, path: Path | str = DEFAULT_DB_PATH) -> "ExerciseDB":
        raw: dict[str, dict[str, Any]] = yaml.load(Path(path).read_text(), Loader=_Loader)
        return cls({eid: cls._parse(eid, fields) for eid, fields in raw.items()})

    @staticmethod
    def _optional(enum: type[EnumT], value: Any) -> EnumT | None:
        """Enrichment attributes are absent for sources that never carried them,
        so a missing key is normal rather than a defect."""
        return enum(value) if value else None

    @classmethod
    def _parse(cls, exercise_id: str, fields: dict[str, Any]) -> Exercise:
        return Exercise(
            id=exercise_id,
            name=fields["name"],
            target=Muscle(fields["target"]),
            equipment=Equipment(fields["equipment"]),
            secondary_muscles=tuple(Muscle(m) for m in fields.get("secondary_muscles", ())),
            movement_pattern=cls._optional(MovementPattern, fields.get("movement_pattern")),
            modality=Modality(fields.get("modality", Modality.RESISTANCE.value)),
            unilateral=fields.get("unilateral", False),
            difficulty=cls._optional(Difficulty, fields.get("difficulty")),
            force_type=cls._optional(ForceType, fields.get("force_type")),
            mechanics=cls._optional(Mechanics, fields.get("mechanics")),
            plane_of_motion=cls._optional(PlaneOfMotion, fields.get("plane_of_motion")),
            symmetry=cls._optional(Symmetry, fields.get("symmetry")),
            source=fields.get("source"),
            source_id=fields.get("source_id"),
        )

    def __getitem__(self, exercise_id: str) -> Exercise:
        try:
            return self._exercises[exercise_id]
        except KeyError:
            raise UnknownExerciseError(exercise_id) from None

    def __contains__(self, exercise_id: str) -> bool:
        return exercise_id in self._exercises

    def __len__(self) -> int:
        return len(self._exercises)

    def all(self) -> list[Exercise]:
        return list(self._exercises.values())

    def find_substitutes(
        self,
        exercise_id: str,
        *,
        allow_equipment_change: bool = True,
        require_same_target: bool = True,
        require_same_movement_pattern: bool = True,
        limit: int | None = None,
    ) -> list[Exercise]:
        """Exercises that can stand in for ``exercise_id``, best match first.

        Ranked by ``Exercise.similarity`` (shared target muscle, then shared
        secondaries), so callers picking randomly from a truncated list still
        draw from genuinely close alternatives rather than the whole body part.

        Movement pattern is applied as a filter only when *both* exercises
        declare one -- it is derived heuristically at import and is absent for
        exercises the rules could not classify confidently, which should not
        make those exercises unsubstitutable.

        ``require_same_movement_pattern=False`` relaxes that, keeping only the
        shared target muscle. It exists for one case: when the prescribed
        movement *pattern* is itself contraindicated, holding it fixed
        guarantees every candidate is also contraindicated, so the search has
        to widen or the entry cannot be made safe at all. See ``variation.py``.

        Candidates never cross modality -- a quad stretch and a leg press share
        a target muscle but are not alternatives for one another, and their
        doses are not even expressed in the same units.

        Loaded and bodyweight exercises are never swapped for one another: the
        variation engine solves a weight from volume, and an "implied weight"
        for a true bodyweight movement is meaningless (see ``variation.py``)."""
        source = self[exercise_id]
        candidates = []
        for ex in self._exercises.values():
            if ex.id == source.id:
                continue
            if ex.modality is not source.modality:
                continue
            if require_same_target and ex.target is not source.target:
                continue
            if ex.is_bodyweight != source.is_bodyweight:
                continue
            if not allow_equipment_change and ex.equipment is not source.equipment:
                continue
            if (
                require_same_movement_pattern
                and ex.movement_pattern is not None
                and source.movement_pattern is not None
                and ex.movement_pattern is not source.movement_pattern
            ):
                continue
            candidates.append(ex)

        # id as the tiebreaker keeps ordering deterministic across runs, which
        # is what makes seeded variation reproducible.
        candidates.sort(key=lambda ex: (-source.similarity(ex), ex.id))
        return candidates[:limit] if limit is not None else candidates
