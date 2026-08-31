from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hibrid.api.app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_objectives_returns_the_three_implemented_strategies():
    response = client.get("/objectives")
    assert response.status_code == 200
    objectives = {o["objective"] for o in response.json()}
    assert objectives == {"strength", "hypertrophy", "muscular_endurance"}


def test_list_objectives_exposes_real_strategy_parameters():
    response = client.get("/objectives")
    strength = next(o for o in response.json() if o["objective"] == "strength")
    assert strength["rep_range"] == [1, 6]
    assert strength["preferred_modality"] == "resistance"


def test_list_objectives_exposes_the_variation_policy():
    """A client has to render an intensity-preserving objective differently --
    the headline there is the bar weight, not the diff -- so it must be able to
    read which invariant applies rather than hard-coding the objective names."""
    objectives = {o["objective"]: o for o in client.get("/objectives").json()}
    assert objectives["strength"]["preserved_invariant"] == "intensity"
    assert objectives["hypertrophy"]["preserved_invariant"] == "load_volume"
    assert (
        objectives["strength"]["max_substitution_prob"]
        < objectives["hypertrophy"]["max_substitution_prob"]
    )


def test_vary_reports_the_substitution_probability_it_actually_used():
    """Asking for full novelty under a strength objective must not look like
    the request was ignored."""
    response = client.post(
        "/vary",
        json={
            "routine_name": "example_ppl",
            "objective": "strength",
            "seed": 1,
            "substitution_prob": 1.0,
        },
    )
    assert response.status_code == 200
    assert response.json()["substitution_prob"] == pytest.approx(0.10)


def test_list_routines_includes_the_example_files():
    response = client.get("/routines")
    assert response.status_code == 200
    stems = {r["file_stem"] for r in response.json()}
    assert "example_ppl" in stems
    assert "example_mixed" in stems


def test_get_routine_by_name():
    response = client.get("/routines/example_ppl")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Push Day"
    assert len(body["entries"]) == 5
    assert body["entries"][0]["exercise_name"]


def test_get_routine_404_for_unknown_name():
    response = client.get("/routines/does-not-exist")
    assert response.status_code == 404


def test_vary_by_routine_name_is_seed_reproducible():
    """Each call is a fresh Routine (a variation gets its own routine_id per
    M1), so compare the entries -- the actual output of the algorithm -- not
    the generated identity."""
    payload = {"routine_name": "example_ppl", "objective": "hypertrophy", "seed": 7}
    first = client.post("/vary", json=payload).json()
    second = client.post("/vary", json=payload).json()
    assert first["varied"]["entries"] == second["varied"]["entries"]


def test_vary_with_strength_objective_keeps_changed_reps_within_its_range():
    """Reps only have to land in (1, 6) when the engine actually found a new
    scheme -- an entry with no in-tolerance candidate keeps its original
    scheme unchanged, which can legitimately sit outside the target range."""
    payload = {
        "routine_name": "example_ppl",
        "objective": "strength",
        "seed": 3,
        "substitution_prob": 0.0,
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 200
    body = response.json()
    for original, new in zip(body["original"]["entries"], body["varied"]["entries"]):
        if new["dose"]["kind"] == "reps" and new["dose"] != original["dose"]:
            assert 1 <= new["dose"]["reps"] <= 6


def test_vary_rejects_unimplemented_objective_with_400():
    payload = {"routine_name": "example_ppl", "objective": "cardiovascular_endurance"}
    response = client.post("/vary", json=payload)
    assert response.status_code == 400
    assert "cardiovascular_endurance" in response.json()["detail"]


def test_vary_rejects_unknown_objective_value_with_422():
    payload = {"routine_name": "example_ppl", "objective": "not_a_real_objective"}
    response = client.post("/vary", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"routine_name": "example_ppl", "routine": {"name": "x", "entries": []}},
        {},
    ],
)
def test_vary_requires_exactly_one_routine_source(payload):
    response = client.post("/vary", json=payload)
    assert response.status_code == 422


def test_unknown_exercise_id_returns_400_not_500():
    payload = {
        "routine": {
            "name": "Typo'd exercise id",
            "entries": [
                {"exercise_id": "no-such-exercise", "dose": {"kind": "reps", "sets": 3, "reps": 8, "weight": 80}}
            ],
        },
        "substitution_prob": 0.0,
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 400
    assert "no-such-exercise" in response.json()["detail"]


def test_varied_entries_carry_a_dose_outcome_and_reason():
    payload = {"routine_name": "example_ppl", "objective": "hypertrophy", "seed": 3, "substitution_prob": 0.0}
    body = client.post("/vary", json=payload).json()
    for original, new in zip(body["original"]["entries"], body["varied"]["entries"]):
        moved = new["dose"] != original["dose"]
        assert (new["dose_outcome"] == "varied") == moved
        assert new["dose_outcome_reason"]
        assert new["exercise_substituted"] is False


def test_unvaried_entry_reports_which_guard_stopped_it():
    """The whole point of the outcome field: three different reasons for
    "unchanged" must be distinguishable over the wire."""
    payload = {
        "routine": {
            "name": "Three ways to not vary",
            "entries": [
                {"exercise_id": "run", "dose": {"kind": "distance", "distance_m": 1000, "duration_seconds": 300}},
                {"exercise_id": "burpee", "dose": {"kind": "reps", "sets": 4, "reps": 10, "weight": 0}},
                {"exercise_id": "barbell-bench-press", "dose": {"kind": "reps", "sets": 4, "reps": 8, "weight": 80}},
            ],
        },
        "objective": "muscular_endurance",
        "seed": 1,
        "substitution_prob": 0.0,
    }
    outcomes = [e["dose_outcome"] for e in client.post("/vary", json=payload).json()["varied"]["entries"]]
    assert outcomes == [
        "unvaried_not_reps_dose",
        "unvaried_modality_mismatch",
        "unvaried_no_scheme_in_objective_range",
    ]


def test_substitution_is_reported_separately_from_the_dose_outcome():
    payload = {
        "routine": {
            "name": "Cardio, substitution on",
            "entries": [
                {"exercise_id": "run", "dose": {"kind": "distance", "distance_m": 1000, "duration_seconds": 300}}
            ],
        },
        "seed": 1,
        "substitution_prob": 1.0,
    }
    entry = client.post("/vary", json=payload).json()["varied"]["entries"][0]
    assert entry["exercise_substituted"] is True
    assert entry["exercise_id"] != "run"
    assert entry["dose_outcome"] == "unvaried_not_reps_dose"


SHOULDER_INJURY_DUMBBELLS_ONLY = {
    "health": {
        "injuries": [
            {
                "body_region": "shoulder",
                "status": "active",
                "severity": 6,
                "contraindicated_movement_patterns": ["vertical_push"],
            }
        ]
    },
    "preferences": {
        "equipment_access": [
            {"environment": "home_gym", "available_equipment": ["dumbbell"], "is_default": True}
        ]
    },
}


def test_context_enforces_the_m3_milestone_over_http():
    """The milestone test, end to end through the API."""
    payload = {
        "routine": {
            "name": "Overhead day",
            "entries": [
                {"exercise_id": "barbell-overhead-press", "dose": {"kind": "reps", "sets": 4, "reps": 8, "weight": 50}}
            ],
        },
        "context": SHOULDER_INJURY_DUMBBELLS_ONLY,
        "seed": 1,
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 200
    entry = response.json()["varied"]["entries"][0]
    assert entry["exercise_id"] != "barbell-overhead-press"
    assert entry["exercise_outcome"] == "substituted_for_constraint"
    assert entry["is_unsafe"] is False


def test_context_filter_reports_how_much_of_the_library_is_permitted():
    payload = {"routine_name": "example_ppl", "context": SHOULDER_INJURY_DUMBBELLS_ONLY, "seed": 1}
    body = client.post("/vary", json=payload).json()
    report = body["context_filter"]
    assert 0 < report["permitted"] < report["total"]
    assert 0.0 < report["permitted_fraction"] < 1.0


def test_context_filter_is_absent_when_no_context_is_supplied():
    body = client.post("/vary", json={"routine_name": "example_ppl", "seed": 1}).json()
    assert body["context_filter"] is None


def test_a_typo_in_a_health_field_is_rejected_rather_than_dropped():
    """The reason this context travels in the body: extra=\"forbid\" means a
    misspelled health constraint raises instead of silently meaning
    'no constraint'."""
    payload = {
        "routine_name": "example_ppl",
        "context": {
            "health": {
                "injuries": [
                    {
                        "body_region": "shoulder",
                        "status": "active",
                        "contraindicated_movement_pattern": ["vertical_push"],
                    }
                ]
            }
        },
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 422


NOW_AT = datetime(2026, 8, 9, 7, 0, tzinfo=timezone.utc)
NOW = NOW_AT.isoformat()
STEADY_HRV = [58.0, 62.0, 59.0, 61.0, 57.0, 63.0, 60.0, 58.0, 62.0, 61.0, 59.0, 60.0, 64.0, 56.0]
RECOVERY_USER_ID = "11111111-1111-1111-1111-111111111111"


def recovery_history(latest_hrv: float) -> list[dict]:
    """A fortnight of steady HRV plus one fresh reading, as JSON a caller
    would actually post."""

    def reading(hours_ago: float, hrv: float) -> dict:
        return {
            "user_id": RECOVERY_USER_ID,
            "recorded_at": (NOW_AT - timedelta(hours=hours_ago)).isoformat(),
            "hrv_rmssd_ms": hrv,
        }

    baseline = [reading(24 * (day + 1), value) for day, value in enumerate(STEADY_HRV)]
    return [reading(4, latest_hrv), *baseline]


def test_suppressed_recovery_lightens_the_routine_over_http():
    """M3 pass 2 end to end: the HRV half of the milestone the roadmap parked."""
    payload = {
        "routine": {
            "name": "Bench",
            "entries": [
                {"exercise_id": "barbell-bench-press", "dose": {"kind": "reps", "sets": 4, "reps": 8, "weight": 80}}
            ],
        },
        "context": {"recovery_history": recovery_history(45.0), "as_of": NOW},
        "seed": 3,
        "substitution_prob": 0.0,
    }
    body = client.post("/vary", json=payload).json()

    readiness = body["readiness"]
    assert readiness["state"] == "suppressed"
    assert readiness["load_multiplier"] < 1.0
    assert readiness["modulates_load"] is True
    assert readiness["comparisons"][0]["metric"] == "hrv_rmssd"
    assert readiness["comparisons"][0]["is_objective"] is True
    assert body["varied"]["total_volume"] < body["original"]["total_volume"]
    assert body["varied"]["entries"][0]["dose_outcome"] == "varied_for_strain"


def test_the_same_hrv_against_a_lower_baseline_is_not_a_deload():
    """The absolute value is identical to the test above. Only this user's own
    history differs, and that is the entire decision."""
    payload = {
        "routine_name": "example_ppl",
        "context": {"recovery_history": recovery_history(58.0), "as_of": NOW},
        "seed": 3,
    }
    body = client.post("/vary", json=payload).json()
    assert body["readiness"]["state"] == "normal"
    assert body["readiness"]["load_multiplier"] == 1.0


def test_readiness_is_absent_when_no_readings_are_supplied():
    body = client.post("/vary", json={"routine_name": "example_ppl", "seed": 1}).json()
    assert body["readiness"] is None


def test_a_single_reading_yields_no_assessment_rather_than_a_guess():
    """One reading has no baseline to be suppressed against, and that must
    read as UNKNOWN rather than as a clean bill of health."""
    payload = {
        "routine_name": "example_ppl",
        "context": {
            "recovery_history": [
                {"user_id": RECOVERY_USER_ID, "recorded_at": "2026-08-09T03:00:00Z", "hrv_rmssd_ms": 20.0}
            ],
            "as_of": NOW,
        },
        "seed": 1,
    }
    body = client.post("/vary", json=payload).json()
    assert body["readiness"]["state"] == "unknown"
    assert body["readiness"]["load_multiplier"] == 1.0
    assert body["readiness"]["comparisons"] == []


def performed_session(days_ago: float, sets: list[dict], *, status: str = "completed") -> dict:
    return {
        "user_id": RECOVERY_USER_ID,
        "performed_at": (NOW_AT - timedelta(days=days_ago)).isoformat(),
        "status": status,
        "exercises": [{"exercise_id": "barbell-bench-press", "order_index": 0, "sets": sets}],
    }


def bench_set(index: int, reps: int, load: float, **extra: object) -> dict:
    return {
        "exercise_id": "barbell-bench-press",
        "set_index": index,
        "reps_completed": reps,
        "load_kg": load,
        **extra,
    }


def performance_records(sessions: list[dict], formula: str = "epley") -> dict:
    return client.post(
        "/performance-records",
        json={
            "user_id": RECOVERY_USER_ID,
            "sessions": sessions,
            "as_of": NOW,
            "formula": formula,
        },
    ).json()


def test_performance_records_derives_a_one_rep_max_from_a_session_log():
    body = performance_records([performed_session(2, [bench_set(0, 8, 80.0, rpe=9.0)])])
    record = body["records"][0]

    assert body["exercises_with_estimate"] == 1
    assert record["exercise_name"]
    assert record["estimated_one_rep_max_kg"] == pytest.approx(80.0 * (1 + 8 / 30))
    assert record["one_rep_max_formula"] == "epley"
    assert record["volume_load_last_7d_kg"] == pytest.approx(640.0)


def test_skipped_sessions_do_not_inflate_a_one_rep_max_over_http():
    """The heaviest set in the log is in a session that never happened."""
    body = performance_records(
        [
            performed_session(2, [bench_set(0, 8, 80.0)]),
            performed_session(1, [bench_set(0, 8, 120.0)], status="skipped"),
        ]
    )
    assert body["records"][0]["estimated_one_rep_max_kg"] == pytest.approx(80.0 * (1 + 8 / 30))


def test_an_unestimable_log_is_reported_rather_than_returned_empty():
    """A bodyweight-only history still produces a record -- with a null 1RM and
    a count that makes the absence visible."""
    body = performance_records([performed_session(2, [bench_set(0, 20, 0.0)])])
    assert body["exercises_with_estimate"] == 0
    assert body["exercises_without_estimate"] == 1
    assert body["records"][0]["estimated_one_rep_max_kg"] is None
    assert body["records"][0]["one_rep_max_formula"] is None


def test_choosing_brzycki_is_reflected_in_the_response():
    body = performance_records([performed_session(2, [bench_set(0, 8, 80.0)])], formula="brzycki")
    assert body["formula"] == "brzycki"
    assert body["records"][0]["estimated_one_rep_max_kg"] == pytest.approx(80.0 * 36 / 29)


def test_sessions_belonging_to_another_user_are_rejected():
    """The error that otherwise stays silent until one person's training data
    has been blended with a stranger's."""
    foreign = performed_session(2, [bench_set(0, 8, 80.0)])
    foreign["user_id"] = "22222222-2222-2222-2222-222222222222"
    response = client.post(
        "/performance-records",
        json={"user_id": RECOVERY_USER_ID, "sessions": [foreign], "as_of": NOW},
    )
    assert response.status_code == 422


def test_an_empty_log_yields_no_records_rather_than_an_error():
    body = performance_records([])
    assert body["records"] == []
    assert body["exercises_with_estimate"] == 0


BENCH_ROUTINE = {
    "name": "Bench day",
    "entries": [
        {"exercise_id": "barbell-bench-press", "dose": {"kind": "reps", "sets": 4, "reps": 8, "weight": 80}}
    ],
}


def vary_at_intent(intent: str | None = None, **context: object) -> dict:
    ctx = dict(context)
    if intent is not None:
        ctx["session_intent"] = intent
    payload = {"routine": BENCH_ROUTINE, "seed": 3, "substitution_prob": 0}
    if ctx:
        payload["context"] = ctx
    return client.post("/vary", json=payload).json()


def test_session_intent_moves_volume_in_both_directions_over_http():
    light = vary_at_intent("light")
    moderate = vary_at_intent("moderate")
    challenging = vary_at_intent("challenging")

    assert light["load_multiplier"] == 0.85
    assert moderate["load_multiplier"] == 1.0
    assert challenging["load_multiplier"] == 1.15
    assert (
        light["varied"]["total_volume"]
        < moderate["varied"]["total_volume"]
        < challenging["varied"]["total_volume"]
    )
    assert light["varied"]["entries"][0]["dose_outcome"] == "varied_for_session_intent"


def test_session_intent_defaults_to_moderate_with_no_context_at_all():
    body = client.post("/vary", json={"routine_name": "example_ppl", "seed": 1}).json()
    assert body["session_intent"] == "moderate"
    assert body["load_multiplier"] == 1.0


def test_readiness_caps_an_ambitious_request_over_http():
    """1.15 x 0.90 = 1.035 would hand an under-recovered user more work than
    normal. The cap holds them at 1.0 -- and the response has to make that
    legible, since every entry honestly reads `varied`."""
    body = vary_at_intent(
        "challenging", recovery_history=recovery_history(45.0), as_of=NOW
    )
    assert body["readiness"]["state"] == "suppressed"
    assert body["session_intent"] == "challenging"
    assert body["load_multiplier"] == 1.0
    assert body["varied"]["total_volume"] <= body["original"]["total_volume"]


def test_an_unknown_session_intent_is_rejected():
    body = {"routine_name": "example_ppl", "context": {"session_intent": "brutal"}}
    assert client.post("/vary", json=body).status_code == 422


def bench_history(rpe: float | None = 8.0, load: float = 100.0) -> dict:
    """One recent session at a load the routine below does not know about."""
    return {
        "user_id": RECOVERY_USER_ID,
        "as_of": NOW,
        "sessions": [
            performed_session(3, [bench_set(0, 8, load, **({"rpe": rpe} if rpe else {}))])
        ],
    }


def test_history_overrides_the_weight_written_in_the_routine():
    """M8b end to end: the routine says 80kg, the user benches 100."""
    payload = {
        "routine": BENCH_ROUTINE,
        "history": bench_history(),
        "seed": 3,
        "substitution_prob": 0,
    }
    body = client.post("/vary", json=payload).json()
    entry = body["varied"]["entries"][0]

    assert entry["progression"]["decision"] == "held"
    assert entry["progression"]["reference_load_kg"] == pytest.approx(100.0)
    assert entry["progression"]["target_rpe_range"] == [7.0, 9.0]
    assert entry["dose_outcome"] == "varied_at_remembered_load"
    assert body["varied"]["total_volume"] > body["original"]["total_volume"]


def test_an_easy_session_progresses_the_load_over_http():
    body = client.post(
        "/vary",
        json={
            "routine": BENCH_ROUTINE,
            "history": bench_history(rpe=6.0),
            "seed": 3,
            "substitution_prob": 0,
        },
    ).json()
    progression = body["varied"]["entries"][0]["progression"]

    assert progression["decision"] == "progressed"
    assert progression["working_load_kg"] == pytest.approx(102.5)
    assert body["varied"]["entries"][0]["dose_outcome"] == "varied_for_progression"


def test_progression_is_absent_when_no_history_is_supplied():
    body = client.post(
        "/vary", json={"routine": BENCH_ROUTINE, "seed": 3, "substitution_prob": 0}
    ).json()
    assert body["varied"]["entries"][0]["progression"] is None


# --- Load management (M8c) ---------------------------------------------------


def sprpe_session(days_ago: float, *, rpe: float = 7.0, minutes: float = 60.0) -> dict:
    return {
        "user_id": RECOVERY_USER_ID,
        "performed_at": (NOW_AT - timedelta(days=days_ago)).isoformat(),
        "status": "completed",
        "session_rpe": rpe,
        "duration_seconds": minutes * 60,
    }


def steady_block() -> list[dict]:
    """Six weeks at three sessions a week -- a ratio of exactly 1.0."""
    return [sprpe_session(1 + index * 7 / 3) for index in range(18)]


def vary_with_load(sessions: list[dict], **context: object) -> dict:
    payload = {
        "routine": BENCH_ROUTINE,
        "history": {"user_id": RECOVERY_USER_ID, "as_of": NOW, "sessions": sessions},
        "context": {"as_of": NOW, **context},
        "seed": 3,
        "substitution_prob": 0,
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_one_session_log_feeds_both_remembered_loads_and_accumulated_load():
    """The log is posted once. M8b reads it per exercise, M8c reads it per
    session -- two copies in one request would be two chances to disagree."""
    body = vary_with_load(steady_block())

    assert body["load_management"]["workload"]["state"] == "optimal"
    assert body["load_management"]["workload"]["acute_chronic_ratio"] == pytest.approx(1.0)
    assert body["load_multiplier"] == 1.0


def test_a_doubled_week_backs_the_session_off_over_http():
    doubled = steady_block() + [sprpe_session(days) for days in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    body = vary_with_load(doubled)

    assert body["load_management"]["workload"]["state"] == "spike"
    assert body["load_multiplier"] == 0.75
    assert body["varied"]["entries"][0]["dose_outcome"] == "varied_for_load_management"
    assert body["varied"]["total_volume"] < body["original"]["total_volume"]


def test_a_taper_scales_volume_toward_a_dated_event_over_http():
    event_date = (NOW_AT + timedelta(days=7)).date().isoformat()
    body = vary_with_load(
        steady_block(), target_event={"name": "Regionals", "event_date": event_date}
    )

    assert body["load_management"]["taper"]["is_tapering"] is True
    assert body["load_management"]["binding_taper"] is True
    assert body["load_multiplier"] == pytest.approx(0.775)
    assert body["varied"]["total_volume"] < body["original"]["total_volume"]


def test_a_new_users_ordinary_week_is_not_reported_as_a_spike():
    body = vary_with_load([sprpe_session(1 + index * 7 / 3) for index in range(9)])

    assert body["load_management"]["workload"]["state"] == "unknown"
    assert body["load_multiplier"] == 1.0


def test_load_management_is_absent_when_no_log_and_no_event_are_supplied():
    body = client.post("/vary", json={"routine": BENCH_ROUTINE, "seed": 3}).json()
    assert body["load_management"] is None
    assert body["intent_capped_by_load_management"] is False


def test_an_ambitious_request_during_a_taper_is_capped_over_http():
    event_date = (NOW_AT + timedelta(days=3)).date().isoformat()
    body = vary_with_load(
        steady_block(),
        session_intent="challenging",
        target_event={"name": "Regionals", "event_date": event_date},
    )

    assert body["session_intent"] == "challenging"
    assert body["load_multiplier"] < 1.0
    assert body["varied"]["total_volume"] < body["original"]["total_volume"]


def test_novelty_preference_drives_substitution_when_prob_is_omitted():
    payload = {
        "routine_name": "example_ppl",
        "context": {"preferences": {"novelty_preference": 0.0}},
        "seed": 1,
    }
    body = client.post("/vary", json=payload).json()
    assert all(e["exercise_substituted"] is False for e in body["varied"]["entries"])


def test_vary_with_inline_mixed_modality_routine_leaves_non_resistance_entries_unvaried():
    payload = {
        "routine": {
            "name": "Inline Mixed",
            "entries": [
                {"exercise_id": "barbell-front-squat", "dose": {"kind": "reps", "sets": 4, "reps": 6, "weight": 90}},
                {
                    "exercise_id": "run",
                    "dose": {"kind": "distance", "distance_m": 1000, "duration_seconds": 300},
                    "rest_seconds": 60,
                },
            ],
        },
        "objective": "hypertrophy",
        "seed": 1,
        "substitution_prob": 0.0,
    }
    response = client.post("/vary", json=payload)
    assert response.status_code == 200
    varied_run = response.json()["varied"]["entries"][1]
    assert varied_run["dose"] == {"kind": "distance", "distance_m": 1000.0, "duration_seconds": 300.0}


# --- POST /sessions/generate and /sessions/blocks/vary (M5, one session) ------


def _generate(**overrides):
    payload = {
        "muscles": ["pectorals", "lats"],
        "duration_minutes": 60,
        "body_mass_kg": 80.0,
        "seed": 7,
    }
    payload.update(overrides)
    return client.post("/sessions/generate", json=payload)


def test_generate_builds_a_session_from_time_muscles_and_difficulty():
    response = _generate()
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["blocks"]
    assert body["report"]["fits_time_budget"]
    assert body["report"]["is_prescribable"]
    assert body["report"]["unmet_constraints"] == []
    assert body["difficulty"] == "moderate"
    assert body["difficulty_reason"]


def test_every_generated_block_carries_its_own_invariant_over_http():
    blocks = _generate().json()["session"]["blocks"]
    for index, block in enumerate(blocks):
        assert block["index"] == index
        assert block["volume"] >= 0.0
        assert block["time_seconds"] > 0.0
        assert block["target"] in {"pectorals", "lats"}
        assert block["exercise_name"]
        assert block["load_source_reason"]


def test_the_generated_session_respects_its_time_budget_over_http():
    body = _generate(duration_minutes=45).json()
    assert body["report"]["time_budget_seconds"] == 45 * 60
    assert abs(body["session"]["total_time_seconds"] - 45 * 60) <= 0.10 * 45 * 60


def test_difficulty_moves_volume_and_holds_time_over_http():
    sessions = {
        difficulty: _generate(difficulty=difficulty, muscles=["quads"]).json()
        for difficulty in ("light", "moderate", "challenging")
    }
    volumes = [sessions[d]["session"]["total_volume"] for d in ("light", "moderate", "challenging")]
    times = {sessions[d]["session"]["total_time_seconds"] for d in sessions}
    assert volumes == sorted(volumes) and volumes[0] < volumes[-1]
    assert len(times) == 1
    assert sessions["light"]["report"]["session_intent_load_multiplier"] == pytest.approx(0.85)


def test_difficulty_stated_twice_and_differently_is_rejected():
    """Silently preferring one would be exactly the quietly dropped field that
    extra="forbid" exists to prevent."""
    response = _generate(difficulty="light", context={"session_intent": "challenging"})
    assert response.status_code == 422
    assert "disagree" in str(response.json())


def test_difficulty_stated_twice_and_agreeing_is_allowed():
    response = _generate(difficulty="light", context={"session_intent": "light"})
    assert response.status_code == 200


def test_a_muscle_only_trained_outside_resistance_is_reported_not_dropped():
    body = _generate(muscles=["cardiovascular_system", "pectorals"]).json()
    assert body["report"]["muscles_uncovered"] == ["cardiovascular_system"]
    assert not body["report"]["is_prescribable"]
    gap = body["report"]["unmet_constraints"][0]
    assert gap["kind"] == "modality_not_supported"
    assert "MET" in gap["detail"]


def test_generate_without_body_mass_or_history_reports_the_missing_load_basis():
    body = _generate(
        muscles=["quads"],
        body_mass_kg=None,
        context={"preferences": {"equipment_access": [{"environment": "commercial_gym", "available_equipment": ["barbell"]}]}},
    ).json()
    assert all(b["load_source"] == "no_basis" for b in body["session"]["blocks"])
    assert not body["report"]["is_prescribable"]
    assert "starting_load_unknown" in {c["kind"] for c in body["report"]["unmet_constraints"]}


def test_generate_reports_the_conservative_starting_load_policy():
    body = _generate().json()
    assert body["report"]["starting_load_policy"] == "conservative"
    assert body["report"]["starting_load_policy_reason"]


def test_generate_honours_equipment_access_over_http():
    body = _generate(
        muscles=["pectorals"],
        context={
            "preferences": {
                "equipment_access": [
                    {"environment": "home_gym", "available_equipment": ["dumbbell"], "is_default": True}
                ]
            }
        },
    ).json()
    assert body["session"]["blocks"]
    assert body["context_filter"]["permitted"] < body["context_filter"]["total"]


def test_a_health_contraindication_narrows_the_generated_pool_over_http():
    """The permits() check itself is covered in test_session_generation; what
    this pins is that the health block reaches generation at all, and that the
    narrowing is visible rather than mysterious."""
    body = _generate(
        muscles=["quads"],
        context={
            "health": {
                "injuries": [
                    {
                        "body_region": "knee",
                        "status": "active",
                        "contraindicated_movement_patterns": ["squat", "lunge", "isolation_knee"],
                    }
                ]
            }
        },
    ).json()
    assert body["session"]["blocks"]
    assert body["report"]["is_prescribable"]
    assert body["context_filter"]["permitted"] < body["context_filter"]["total"]


def test_suppressed_recovery_caps_an_ambitious_generated_session_over_http():
    """The invisible case, on the generation path: asking for a hard session
    while under-recovered composes to exactly 1.0, so nothing in the loads says
    the request was cancelled. Reuses the same fixture as the /vary tests."""
    body = _generate(
        muscles=["quads"],
        difficulty="challenging",
        context={"recovery_history": recovery_history(45.0), "as_of": NOW},
    ).json()
    assert body["readiness"]["state"] == "suppressed"
    assert body["intent_capped_by_readiness"] is True
    assert body["report"]["session_intent_load_multiplier"] == pytest.approx(1.0)


def test_generate_rejects_an_unimplemented_objective():
    response = _generate(objective="flexibility")
    assert response.status_code == 400
    assert "flexibility" in response.json()["detail"]


def test_generate_requires_at_least_one_muscle():
    assert _generate(muscles=[]).status_code == 422


def test_generate_rejects_a_zero_length_session():
    assert _generate(duration_minutes=0).status_code == 422


def test_generate_rejects_a_typo_in_a_nested_user_model():
    response = _generate(context={"preferences": {"novelty_preferance": 0.9}})
    assert response.status_code == 422


def test_the_same_seed_reproduces_the_same_session_over_http():
    first, second = _generate(seed=99).json(), _generate(seed=99).json()
    assert [b["exercise_id"] for b in first["session"]["blocks"]] == [
        b["exercise_id"] for b in second["session"]["blocks"]
    ]


def _reroll(block, **overrides):
    payload = {
        "block": {
            "exercise_id": block["exercise_id"],
            "dose": block["dose"],
            "rest_seconds": block["rest_seconds"],
            "index": block["index"],
            "time_budget_seconds": block["time_budget_seconds"],
        },
        "substitution_prob": 1.0,
        "seed": 3,
    }
    payload.update(overrides)
    return client.post("/sessions/blocks/vary", json=payload)


def test_a_block_round_trips_from_generate_into_vary():
    block = _generate().json()["session"]["blocks"][0]
    response = _reroll(block)
    assert response.status_code == 200
    body = response.json()
    assert body["original"]["exercise_id"] == block["exercise_id"]
    assert body["varied"]["index"] == block["index"]
    assert body["volume_preserved"] and body["time_preserved"] and body["target_preserved"]
    assert body["varied"]["dose_outcome_reason"]
    assert body["varied"]["exercise_outcome_reason"]


def test_re_rolling_a_block_preserves_its_volume_and_time_over_http():
    for block in _generate().json()["session"]["blocks"]:
        body = _reroll(block).json()
        assert body["volume_preserved"]
        assert body["time_preserved"]
        assert body["varied"]["target"] == block["target"]


def test_re_rolling_applies_no_further_load_scaling_over_http():
    """The block's numbers already embody the difficulty, so re-solving them must
    not scale again -- otherwise a challenging session climbs on every re-roll."""
    body = _generate(muscles=["quads"], difficulty="challenging").json()
    block = next(b for b in body["session"]["blocks"] if b["is_variable"])
    for _ in range(5):
        result = _reroll(block, context={"session_intent": "challenging"}).json()
        assert result["load_multiplier"] == 1.0
        assert result["volume_preserved"]
        block = {**result["varied"], "time_budget_seconds": block["time_budget_seconds"]}


def test_re_rolling_still_honours_health_constraints_over_http():
    context = {
        "health": {
            "injuries": [
                {
                    "body_region": "shoulder",
                    "status": "active",
                    "contraindicated_movement_patterns": ["vertical_push", "horizontal_push"],
                }
            ]
        }
    }
    block = _generate(muscles=["pectorals"], context=context).json()["session"]["blocks"][0]
    body = _reroll(block, context=context).json()
    assert body["varied"]["is_unsafe"] is False


def test_re_rolling_an_unknown_exercise_is_a_400_not_a_500():
    response = _reroll({"exercise_id": "not-a-real-id", "dose": {"kind": "reps", "sets": 3, "reps": 10, "weight": 20.0},
                        "rest_seconds": 90, "index": 0, "time_budget_seconds": 450.0})
    assert response.status_code == 400
    assert "not-a-real-id" in response.json()["detail"]


def test_the_generation_report_declares_the_skill_ceiling_it_applied():
    """The default ceiling applies with no background sent and removes a third of
    the library. context_filter cannot see that, so the report has to."""
    body = _generate(muscles=["quads"]).json()
    assert body["report"]["skill_ceiling"] == "novice"
    assert 0.0 < body["report"]["skill_filter"]["permitted_fraction"] < 1.0

    wider = _generate(muscles=["quads"], background={"experience_level": "elite"}).json()
    assert wider["report"]["skill_ceiling"] == "legendary"
    assert wider["report"]["skill_filter"]["permitted_fraction"] == 1.0


def test_history_supplies_a_remembered_load_over_http():
    exercise_id = "barbell-front-rack-squat"
    body = _generate(
        muscles=["quads"],
        seed=15,
        background={"experience_level": "intermediate", "familiar_exercise_ids": [exercise_id]},
        context={"preferences": {"preferred_exercise_ids": [exercise_id]}},
        history={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "as_of": "2026-08-12T09:00:00Z",
            "sessions": [
                {
                    "user_id": "11111111-1111-1111-1111-111111111111",
                    "performed_at": "2026-08-09T07:00:00Z",
                    "status": "completed",
                    "exercises": [
                        {
                            "exercise_id": exercise_id,
                            "order_index": 0,
                            "sets": [
                                {"exercise_id": exercise_id, "set_index": 0, "reps_completed": 8, "load_kg": 120, "rpe": 6},
                                {"exercise_id": exercise_id, "set_index": 1, "reps_completed": 8, "load_kg": 120, "rpe": 6},
                            ],
                        }
                    ],
                }
            ],
        },
    ).json()
    remembered = next(
        b for b in body["session"]["blocks"] if b["load_source"] == "remembered"
    )
    assert remembered["exercise_id"] == exercise_id
    assert remembered["progression"]["decision"] == "progressed"
    assert remembered["dose"]["weight"] > 100.0
    # A log means the scheme stays inside the rep-max formula's range, or the
    # remembered load could never be resolved.
    assert all(b["dose"]["reps"] <= 10 for b in body["session"]["blocks"])
    assert body["report"]["starting_load_policy"] == "mixed"
