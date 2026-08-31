"""FastAPI playground for the routine-variation engine.

This exposes the same "vary a routine and see what comes out" surface the CLI
already provides, over HTTP, so parameters can be swept without a terminal and
so a future frontend has a real API to call instead of a mock. The
auto-generated Swagger UI at ``/docs`` *is* the playground for now -- there is
no separate frontend yet, and none is needed to exercise every endpoint here.

What "input" means today, honestly: only what the engine actually consumes --
a routine, an objective (``hibrid.objective_strategy.STRATEGIES_BY_OBJECTIVE``),
the engine's own tuning knobs, and since M3 a per-user context (health
constraints, equipment inventory, preferences, and recovery/wellness history).
Still not consumed: blended objective weights, which need ``docs/roadmap.md``
M4. See ``VaryRequest`` in ``schemas.py`` for the exact, current boundary.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hibrid.api.schemas import (
    ContextFilterOut,
    GenerateSessionRequest,
    GenerateSessionResponse,
    GeneratedSessionOut,
    GenerationReportOut,
    LoadManagementOut,
    ObjectiveOut,
    SessionHistoryIn,
    PerformanceRecordsResponse,
    ReadinessOut,
    RoutineOut,
    RoutineSummary,
    VariedRoutineOut,
    VaryBlockRequest,
    VaryBlockResponse,
    VaryRequest,
    VaryResponse,
)
from hibrid.exercise_db import ExerciseDB, UnknownExerciseError
from hibrid.variation_context import VariationContext, summarise_filter
from hibrid.models import Routine
from hibrid.objective_strategy import STRATEGIES_BY_OBJECTIVE, ObjectiveStrategy
from hibrid.routine_io import load_routine
from hibrid.session_generation import generate_session, vary_block
from hibrid.training_memory import TrainingMemory
from hibrid.user.enums import TrainingObjective
from hibrid.variation import vary_routine

ROUTINES_DIR = Path(__file__).resolve().parents[3] / "routines"

app = FastAPI(
    title="hibrid variation playground",
    description="Test the routine-variation engine with different inputs.",
)

# Dev-only: this is a local playground with no auth and no deployment story
# yet. Tighten this before it is ever reachable from outside localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UnknownExerciseError)
async def unknown_exercise_handler(request: Request, exc: Exception) -> JSONResponse:
    """An unrecognised exercise id is a caller error, not a server fault.

    It surfaces as a bare ``KeyError`` from deep inside the engine, which would
    otherwise escape as a 500 and read as "the API is broken" when the cause is
    a typo in the request body."""
    exercise_id = exc.exercise_id if isinstance(exc, UnknownExerciseError) else "<unknown>"
    return JSONResponse(
        status_code=400,
        content={"detail": f"Unknown exercise_id: {exercise_id!r}. Check GET /routines for valid ids."},
    )


@lru_cache(maxsize=1)
def _db() -> ExerciseDB:
    return ExerciseDB.load()


def _strategy(objective: TrainingObjective) -> ObjectiveStrategy:
    """The strategy for an objective, or a 400.

    Only the three resistance objectives have one. Naming an unimplemented
    objective is a caller error rather than a server fault, and the message lists
    what is available -- see ``objective_strategy.py`` for why the rest are
    deliberately absent."""
    strategy = STRATEGIES_BY_OBJECTIVE.get(objective)
    if strategy is None:
        available = ", ".join(implemented.value for implemented in STRATEGIES_BY_OBJECTIVE)
        raise HTTPException(
            status_code=400,
            detail=f"No strategy implemented for {objective.value!r} yet. Available: {available}.",
        )
    return strategy


def _load_named_routine(name: str) -> Routine:
    path = ROUTINES_DIR / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No routine named {name!r} under routines/.")
    return load_routine(path)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/objectives")
def list_objectives() -> list[ObjectiveOut]:
    return [ObjectiveOut.from_domain(strategy) for strategy in STRATEGIES_BY_OBJECTIVE.values()]


@app.get("/routines")
def list_routines() -> list[RoutineSummary]:
    return [
        RoutineSummary.from_domain(load_routine(path), path.stem) for path in sorted(ROUTINES_DIR.glob("*.yaml"))
    ]


@app.get("/routines/{routine_name}")
def get_routine(routine_name: str) -> RoutineOut:
    return RoutineOut.from_domain(_load_named_routine(routine_name), _db())


@app.post("/performance-records")
def performance_records(request: SessionHistoryIn) -> PerformanceRecordsResponse:
    """Rebuild per-exercise performance records from a session log (M8a).

    Always recomputed from the sessions supplied -- the log is the source of
    truth and these records are a cache of this computation, so there is
    deliberately no way to hand one in."""
    memory = TrainingMemory.from_sessions(
        request.sessions,
        user_id=request.user_id,
        as_of=request.as_of,
        formula=request.formula,
    )
    return PerformanceRecordsResponse.from_domain(memory, _db())


@app.post("/sessions/generate")
def generate(request: GenerateSessionRequest) -> GenerateSessionResponse:
    """Build a session from scratch: a time budget, muscles, and a difficulty.

    The single-session slice of M5. The weekly ``POST /plans/generate`` in
    ``docs/api-v1-draft.md`` additionally needs the ``TrainingPlan`` type and
    persistence, neither of which one session requires.

    The session comes back as **blocks**, each one exercise slot carrying the
    invariant a re-roll must preserve. That is what makes
    ``POST /sessions/blocks/vary`` safe: re-rolling any block holds that block's
    own volume and time, so the three requested parameters survive however many
    times the user presses the button.

    Resistance work only. A requested muscle the library reaches only through
    cardio, mobility or balance work comes back in ``report.unmet_constraints``
    as ``modality_not_supported`` rather than as a quietly missing block --
    non-resistance doses can be neither prescribed nor varied yet, and there is
    no MET currency to preserve for them."""
    db = _db()
    strategy = _strategy(request.objective)
    sessions = request.history.sessions if request.history is not None else ()
    context = (
        request.context.to_domain(sessions, session_intent=request.difficulty)
        if request.context is not None
        # Difficulty still has to reach the engine when no context was sent, and
        # it travels on the context by design -- so build a bare one rather than
        # giving generate_session a second way to be told the same thing.
        else VariationContext(session_intent=request.difficulty)
    )
    session = generate_session(
        muscles=request.muscles,
        duration_minutes=request.duration_minutes,
        db=db,
        objective=strategy,
        context=context,
        memory=request.history.to_memory() if request.history is not None else None,
        background=request.background,
        body_mass_kg=request.body_mass_kg,
        name=request.name,
        seed=request.seed,
        weight_increment=request.weight_increment,
    )
    return GenerateSessionResponse(
        session=GeneratedSessionOut.from_domain(session, db),
        report=GenerationReportOut.from_domain(session.report),
        context_filter=(
            ContextFilterOut.from_domain(summarise_filter(context, db))
            if request.context is not None
            else None
        ),
        readiness=(
            ReadinessOut.from_domain(context.readiness) if context.readiness is not None else None
        ),
        load_management=(
            LoadManagementOut.from_domain(context.load_management)
            if context.load_management is not None
            else None
        ),
        difficulty=request.difficulty,
        difficulty_reason=request.difficulty.reason,
        intent_capped_by_readiness=context.intent_capped_by_readiness,
        intent_capped_by_load_management=context.intent_capped_by_load_management,
    )


@app.post("/sessions/blocks/vary")
def vary_session_block(request: VaryBlockRequest) -> VaryBlockResponse:
    """Re-roll one block, holding its own volume and time.

    Stateless like everything else here: the client posts the block back rather
    than naming a stored one. The response reports whether each invariant
    actually held instead of asserting it, because a block with no permitted
    substitute and no scheme inside tolerance legitimately comes back
    unchanged -- read ``varied.dose_outcome`` for which happened."""
    db = _db()
    variation = vary_block(
        request.block.to_domain(db),
        db,
        objective=_strategy(request.objective),
        context=request.context.to_domain() if request.context is not None else None,
        seed=request.seed,
        substitution_prob=request.substitution_prob,
        volume_tolerance=request.volume_tolerance,
        time_tolerance=request.time_tolerance,
        weight_increment=request.weight_increment,
        allow_equipment_change=request.allow_equipment_change,
    )
    return VaryBlockResponse.from_domain(variation, db)


@app.post("/vary")
def vary(request: VaryRequest) -> VaryResponse:
    db = _db()
    if request.routine is not None:
        original = request.routine.to_domain()
    else:
        assert request.routine_name is not None  # enforced by VaryRequest's validator
        original = _load_named_routine(request.routine_name)

    strategy = _strategy(request.objective)

    # The one session log feeds both M8b's remembered loads and M8c's
    # acute:chronic ratio, so it is read from the history block for either.
    sessions = request.history.sessions if request.history is not None else ()
    context = request.context.to_domain(sessions) if request.context is not None else None
    memory = request.history.to_memory() if request.history is not None else None
    variation = vary_routine(
        original,
        db,
        objective=strategy,
        context=context,
        memory=memory,
        seed=request.seed,
        substitution_prob=request.substitution_prob,
        volume_tolerance=request.volume_tolerance,
        time_tolerance=request.time_tolerance,
        weight_increment=request.weight_increment,
        allow_equipment_change=request.allow_equipment_change,
    )
    return VaryResponse(
        original=RoutineOut.from_domain(original, db),
        varied=VariedRoutineOut.from_domain(variation, db),
        context_filter=(
            ContextFilterOut.from_domain(summarise_filter(context, db)) if context is not None else None
        ),
        readiness=(
            ReadinessOut.from_domain(variation.readiness) if variation.readiness is not None else None
        ),
        load_management=(
            LoadManagementOut.from_domain(variation.load_management)
            if variation.load_management is not None
            else None
        ),
        session_intent=variation.session_intent,
        session_intent_reason=variation.session_intent.reason,
        intent_capped_by_readiness=variation.intent_capped_by_readiness,
        intent_capped_by_load_management=variation.intent_capped_by_load_management,
        load_multiplier=variation.load_multiplier,
        substitution_prob=variation.substitution_prob,
    )
