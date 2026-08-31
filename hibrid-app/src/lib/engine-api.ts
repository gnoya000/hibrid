// Client for the hibrid-engine FastAPI backend.
//
// The engine is a pure, stateless service (see hibrid-engine/HANDOFF.md): it
// takes a time budget, the muscles to train and a difficulty, and returns a
// session of re-rollable blocks. This module maps the Italian, sport-oriented
// vocabulary the UI speaks onto the engine's enums, and adapts the engine's
// `SessionBlock` shape onto the frontend `Block` shape used by the screens.
//
// Every call falls back to the local mock (`fitness-data.buildSession`) when the
// backend is unreachable, so the UI can still be iterated on offline.

import { buildSession, type Block, type Effort, type Sport } from "@/lib/fitness-data";

const API_URL =
  (import.meta.env["VITE_API_URL"] as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

// A conservative default so the engine can prescribe a starting load instead of
// returning `no_basis` / 0 kg. Health-bucket data on the backend: request-scoped
// and never persisted. Overridable per call once a profile screen exists.
const DEFAULT_BODY_MASS_KG = 75;

// --- vocabulary mapping ------------------------------------------------------

/** UI muscle groups (Italian) -> engine `Muscle` enum values. */
const MUSCLE_MAP: Record<string, string[]> = {
  Petto: ["pectorals"],
  Dorso: ["lats"],
  Gambe: ["quads"],
  Spalle: ["delts"],
  Braccia: ["biceps"],
  Core: ["abs"],
  "Full body": ["pectorals", "lats", "quads", "delts", "abs"],
};

const FULL_BODY: string[] = ["pectorals", "lats", "quads", "delts", "abs"];

/** Sport picker -> engine `TrainingObjective`. */
const OBJECTIVE_BY_SPORT: Record<Sport, string> = {
  gym: "hypertrophy",
  crossfit: "muscular_endurance",
  calisthenics: "strength",
};

/** Effort picker -> engine `SessionIntent` (difficulty). */
const DIFFICULTY_BY_EFFORT: Record<Effort, string> = {
  maintenance: "light",
  average: "moderate",
  challenging: "challenging",
};

function musclesToEngine(muscles: string[]): string[] {
  const out: string[] = [];
  for (const m of muscles) {
    for (const e of MUSCLE_MAP[m] ?? []) {
      if (!out.includes(e)) out.push(e);
    }
  }
  return out.length > 0 ? out : FULL_BODY;
}

// --- engine payload shapes (only the fields we read) -------------------------

type EngineDose = Record<string, unknown> & { kind: string };

type EngineBlock = {
  exercise_id: string;
  exercise_name: string;
  dose: EngineDose;
  describe: string;
  rest_seconds: number;
  index: number;
  target: string;
  time_budget_seconds: number;
};

type GenerateResponse = {
  session: { blocks: EngineBlock[] };
};

type VaryBlockResponse = {
  varied: EngineBlock;
};

/** Backend data we carry on a `Block` so it can be posted back for a re-roll. */
export type BlockEngineState = {
  exercise_id: string;
  dose: EngineDose;
  rest_seconds: number;
  index: number;
  time_budget_seconds: number;
  sport: Sport;
  effort: Effort;
};

// --- HTTP --------------------------------------------------------------------

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${path} -> ${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

/** Ping the backend. Used to show an online/offline badge. */
export async function engineOnline(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// --- adapters ----------------------------------------------------------------

function engineBlockToBlock(eb: EngineBlock, sport: Sport, effort: Effort): Block {
  return {
    id: `eng-${eb.index}`,
    pattern: prettyMuscle(eb.target),
    name: eb.exercise_name,
    prescription: eb.describe,
    alternatives: [],
    variantIndex: 0,
    engine: {
      exercise_id: eb.exercise_id,
      dose: eb.dose,
      rest_seconds: eb.rest_seconds,
      index: eb.index,
      time_budget_seconds: eb.time_budget_seconds,
      sport,
      effort,
    },
  };
}

function prettyMuscle(target: string): string {
  return target
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// --- public API --------------------------------------------------------------

/**
 * Generate a session from the engine. Falls back to the local mock when the
 * backend is unreachable, so the screen always has something to show.
 */
export async function generateSession(params: {
  sport: Sport;
  minutes: number;
  effort: Effort;
  muscles: string[];
}): Promise<{ blocks: Block[]; source: "engine" | "mock" }> {
  const { sport, minutes, effort, muscles } = params;
  try {
    const data = await post<GenerateResponse>("/sessions/generate", {
      muscles: musclesToEngine(muscles),
      duration_minutes: minutes,
      difficulty: DIFFICULTY_BY_EFFORT[effort],
      objective: OBJECTIVE_BY_SPORT[sport],
      body_mass_kg: DEFAULT_BODY_MASS_KG,
    });
    const blocks = data.session.blocks.map((eb) => engineBlockToBlock(eb, sport, effort));
    if (blocks.length === 0) throw new Error("engine returned no blocks");
    return { blocks, source: "engine" };
  } catch {
    return { blocks: buildSession(sport, minutes), source: "mock" };
  }
}

/**
 * Re-roll a single block against its own invariant (volume + time). Returns the
 * new exercise name/prescription plus the engine state to carry forward, or
 * `null` when the backend is unreachable (caller keeps the local fallback).
 */
export async function varyBlock(block: Block): Promise<{
  name: string;
  prescription: string;
  equipment: string;
  engine: BlockEngineState;
} | null> {
  if (!block.engine) return null;
  try {
    const data = await post<VaryBlockResponse>("/sessions/blocks/vary", {
      block: {
        exercise_id: block.engine.exercise_id,
        dose: block.engine.dose,
        rest_seconds: block.engine.rest_seconds,
        index: block.engine.index,
        time_budget_seconds: block.engine.time_budget_seconds,
      },
      objective: OBJECTIVE_BY_SPORT[block.engine.sport],
      // A re-roll button wants a different exercise, definitively.
      substitution_prob: 1.0,
    });
    const v = data.varied;
    return {
      name: v.exercise_name,
      prescription: v.describe,
      equipment: prettyMuscle(v.target),
      engine: {
        exercise_id: v.exercise_id,
        dose: v.dose,
        rest_seconds: v.rest_seconds,
        index: v.index,
        time_budget_seconds: v.time_budget_seconds,
        sport: block.engine.sport,
        effort: block.engine.effort,
      },
    };
  } catch {
    return null;
  }
}
