from hibrid.models import DistanceDose, DurationDose, RepsDose, Routine, RoundsDose, RoutineEntry


def test_reps_dose_volume_and_time():
    entry = RoutineEntry(exercise_id="bench_press", dose=RepsDose(sets=4, reps=8, weight=80), rest_seconds=120)
    assert entry.volume == 4 * 8 * 80
    assert entry.time_seconds == 4 * (8 * 3.0 + 120)


def test_duration_dose_volume_and_time():
    entry = RoutineEntry(exercise_id="plank", dose=DurationDose(sets=3, duration_seconds=45), rest_seconds=30)
    assert entry.volume == 3 * 45
    assert entry.time_seconds == 3 * (45 + 30)


def test_distance_dose_volume_and_time():
    entry = RoutineEntry(
        exercise_id="run", dose=DistanceDose(distance_m=1000, duration_seconds=300), rest_seconds=60
    )
    assert entry.volume == 1000
    assert entry.time_seconds == 300 + 60


def test_rounds_dose_volume_and_time():
    entry = RoutineEntry(exercise_id="circuit", dose=RoundsDose(rounds=5, round_seconds=45), rest_seconds=15)
    assert entry.volume == 5
    assert entry.time_seconds == 5 * (45 + 15)


def test_routine_totals():
    routine = Routine(
        name="Test",
        entries=[
            RoutineEntry(exercise_id="a", dose=RepsDose(sets=3, reps=10, weight=50)),
            RoutineEntry(exercise_id="b", dose=RepsDose(sets=4, reps=8, weight=60)),
        ],
    )
    assert routine.total_volume == 3 * 10 * 50 + 4 * 8 * 60
    assert routine.total_time_seconds == routine.entries[0].time_seconds + routine.entries[1].time_seconds


def test_routine_id_defaults_to_a_distinct_uuid():
    a = Routine(name="A")
    b = Routine(name="B")
    assert a.routine_id != b.routine_id
