from pathlib import Path

from hibrid.models import DistanceDose, DurationDose, RepsDose, Routine, RoutineEntry
from hibrid.routine_io import dump_routine, load_routine

EXAMPLE_PPL = "routines/example_ppl.yaml"
EXAMPLE_MIXED = "routines/example_mixed.yaml"


def test_load_example_ppl_routine():
    routine = load_routine(EXAMPLE_PPL)
    assert routine.name == "Push Day"
    assert len(routine.entries) == 5
    assert isinstance(routine.entries[0].dose, RepsDose)


def test_mixed_modality_routine_round_trips(tmp_path: Path):
    """The M1 milestone test: one routine holding a barbell squat, a timed
    row and a held stretch -- three different dose shapes -- survives a
    dump/load cycle unchanged."""
    routine = load_routine(EXAMPLE_MIXED)
    assert [type(entry.dose) for entry in routine.entries] == [RepsDose, DistanceDose, DurationDose]

    out = tmp_path / "roundtrip.yaml"
    out.write_text(dump_routine(routine))
    reloaded = load_routine(out)

    assert reloaded.routine_id == routine.routine_id
    assert reloaded.name == routine.name
    assert reloaded.entries == routine.entries


def test_routine_id_round_trips(tmp_path: Path):
    routine = Routine(name="Solo", entries=[RoutineEntry(exercise_id="a", dose=RepsDose(sets=3, reps=8, weight=20))])
    out = tmp_path / "solo.yaml"
    out.write_text(dump_routine(routine))
    reloaded = load_routine(out)
    assert reloaded.routine_id == routine.routine_id
