import { buildSession, type Block, type Effort, type Sport } from "@/lib/fitness-data";

export type SavedRoutine = {
  id: string;
  name: string;
  sport: Sport;
  minutes: number;
  effort: Effort;
  blocks: Block[];
};

/** Le "librerie" sono raggruppate per sport */
export const libraries: { key: Sport; label: string; blurb: string }[] = [
  { key: "gym", label: "Weight training", blurb: "Volume, set e rep" },
  { key: "calisthenics", label: "Calisthenics", blurb: "Skill + corpo libero" },
  { key: "crossfit", label: "CrossFit", blurb: "Forza + WOD" },
];

function routine(
  id: string,
  name: string,
  sport: Sport,
  minutes: number,
  effort: Effort,
  variants: number[] = [],
): SavedRoutine {
  const blocks = buildSession(sport, minutes).map((b, i) => ({
    ...b,
    id: `${id}-${b.id}`,
    variantIndex: variants[i] ?? 0,
  }));
  return { id, name, sport, minutes, effort, blocks };
}

export const starterRoutines: SavedRoutine[] = [
  routine("r1", "Upper power", "gym", 60, "challenging", [0, 0, 1, 0]),
  routine("r2", "Full body express", "gym", 30, "average"),
  routine("r3", "Skill day", "calisthenics", 45, "average", [0, 1, 0]),
  routine("r4", "Metcon misto", "crossfit", 60, "challenging"),
];

export function createRoutine(input: {
  name: string;
  sport: Sport;
  minutes: number;
  effort: Effort;
  prefillFrom?: SavedRoutine | null;
}): SavedRoutine {
  const id = `r${Date.now()}`;
  const base = input.prefillFrom
    ? input.prefillFrom.blocks.map((b) => ({ ...b }))
    : buildSession(input.sport, input.minutes);

  const blocks = base.map((b) => ({ ...b, id: `${id}-${b.id.split("-").pop()}` }));

  return {
    id,
    name: input.name.trim() || "Routine senza nome",
    sport: input.sport,
    minutes: input.minutes,
    effort: input.effort,
    blocks,
  };
}
