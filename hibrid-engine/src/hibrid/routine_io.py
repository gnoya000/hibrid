from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml

from hibrid.models import DistanceDose, Dose, DurationDose, RepsDose, Routine, RoutineEntry, RoundsDose


def _parse_dose(raw: dict[str, Any]) -> Dose:
    kind = raw["kind"]
    if kind == "reps":
        return RepsDose(
            sets=raw["sets"],
            reps=raw["reps"],
            weight=raw["weight"],
            rep_seconds=raw.get("rep_seconds", 3.0),
        )
    if kind == "duration":
        return DurationDose(sets=raw["sets"], duration_seconds=raw["duration_seconds"])
    if kind == "distance":
        return DistanceDose(distance_m=raw["distance_m"], duration_seconds=raw["duration_seconds"])
    if kind == "rounds":
        return RoundsDose(rounds=raw["rounds"], round_seconds=raw["round_seconds"])
    raise ValueError(f"Unknown dose kind: {kind!r}")


def _dump_dose(dose: Dose) -> dict[str, Any]:
    if isinstance(dose, RepsDose):
        return {
            "kind": "reps",
            "sets": dose.sets,
            "reps": dose.reps,
            "weight": dose.weight,
            "rep_seconds": dose.rep_seconds,
        }
    if isinstance(dose, DurationDose):
        return {"kind": "duration", "sets": dose.sets, "duration_seconds": dose.duration_seconds}
    if isinstance(dose, DistanceDose):
        return {"kind": "distance", "distance_m": dose.distance_m, "duration_seconds": dose.duration_seconds}
    if isinstance(dose, RoundsDose):
        return {"kind": "rounds", "rounds": dose.rounds, "round_seconds": dose.round_seconds}
    raise TypeError(f"Unknown dose type: {type(dose)!r}")


def load_routine(path: Path | str) -> Routine:
    raw = yaml.safe_load(Path(path).read_text())
    entries = [
        RoutineEntry(
            exercise_id=entry["exercise_id"],
            dose=_parse_dose(entry["dose"]),
            rest_seconds=entry.get("rest_seconds", 90),
        )
        for entry in raw["entries"]
    ]
    routine_id = UUID(raw["routine_id"]) if "routine_id" in raw else uuid4()
    return Routine(name=raw["name"], entries=entries, routine_id=routine_id)


def dump_routine(routine: Routine) -> str:
    raw = {
        "routine_id": str(routine.routine_id),
        "name": routine.name,
        "entries": [
            {
                "exercise_id": e.exercise_id,
                "dose": _dump_dose(e.dose),
                "rest_seconds": e.rest_seconds,
            }
            for e in routine.entries
        ],
    }
    return yaml.safe_dump(raw, sort_keys=False)
