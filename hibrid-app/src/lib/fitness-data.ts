export type Stat = {
  key: string;
  label: string;
  /** Frequenza di allenamento su quella skill (0-100) */
  frequency: number;
  /** Livello obiettivo misurato dai test assessment (0-100) */
  objective: number;
  color: "neon" | "cyan" | "magenta" | "amber";
};

export const avatarStats: Stat[] = [
  { key: "forza", label: "Forza", frequency: 82, objective: 78, color: "neon" },
  { key: "agilita", label: "Agilità", frequency: 44, objective: 61, color: "cyan" },
  { key: "resistenza", label: "Resistenza", frequency: 65, objective: 72, color: "amber" },
  { key: "ipertrofia", label: "Ipertrofia", frequency: 74, objective: 66, color: "magenta" },
  { key: "mobilita", label: "Mobilità", frequency: 28, objective: 43, color: "cyan" },
  { key: "potenza", label: "Potenza", frequency: 58, objective: 69, color: "neon" },
  { key: "equilibrio", label: "Equilibrio", frequency: 35, objective: 55, color: "amber" },
  { key: "recupero", label: "Recupero", frequency: 70, objective: 74, color: "magenta" },
];


export const weekStreak = {
  target: 5,
  done: 3,
  days: [
    { day: "LUN", state: "done" },
    { day: "MAR", state: "done" },
    { day: "MER", state: "rest" },
    { day: "GIO", state: "done" },
    { day: "VEN", state: "todo" },
    { day: "SAB", state: "todo" },
    { day: "DOM", state: "rest" },
  ] as { day: string; state: "done" | "todo" | "rest" }[],
};

export type Sport = "gym" | "crossfit" | "calisthenics";

export type Effort = "maintenance" | "average" | "challenging";

export const muscleGroups = [
  "Petto",
  "Dorso",
  "Gambe",
  "Spalle",
  "Braccia",
  "Core",
  "Full body",
];

export const equipmentOptions = [
  "Bilanciere",
  "Manubri",
  "Kettlebell",
  "Macchine",
  "Elastici",
  "Corpo libero",
  "Sbarra",
];

export type Block = {
  id: string;
  pattern: string;
  name: string;
  prescription: string;
  alternatives: { name: string; prescription: string; equipment: string }[];
  variantIndex: number;
  /**
   * Backend state for engine-generated blocks (no blank line above keeps
   * prettier happy): the data needed to POST this
   * block back to /sessions/blocks/vary. Absent on locally-mocked blocks.
   * Typed loosely here to avoid a cycle with engine-api.ts.
   */
  engine?: {
    exercise_id: string;
    dose: Record<string, unknown> & { kind: string };
    rest_seconds: number;
    index: number;
    time_budget_seconds: number;
    sport: Sport;
    effort: Effort;
  };
};

type Seed = Omit<Block, "variantIndex">;

const gymSeeds: Seed[] = [
  {
    id: "b1",
    pattern: "Spinta orizzontale",
    name: "Panca piana bilanciere",
    prescription: "4 x 6 @ RPE 8 — rec 150\"",
    alternatives: [
      { name: "Panca manubri 30°", prescription: "4 x 8 @ RPE 8 — rec 120\"", equipment: "Manubri" },
      { name: "Chest press macchina", prescription: "4 x 10 @ RPE 8 — rec 90\"", equipment: "Macchine" },
      { name: "Push-up zavorrato", prescription: "5 x 12 @ RPE 8 — rec 90\"", equipment: "Corpo libero" },
    ],
  },
  {
    id: "b2",
    pattern: "Trazione verticale",
    name: "Trazioni presa prona",
    prescription: "4 x 8 @ RPE 8 — rec 120\"",
    alternatives: [
      { name: "Lat machine presa neutra", prescription: "4 x 10 @ RPE 8 — rec 90\"", equipment: "Macchine" },
      { name: "Pulldown elastico", prescription: "3 x 15 @ RPE 7 — rec 60\"", equipment: "Elastici" },
      { name: "Rematore manubrio 1 braccio", prescription: "4 x 10/lato — rec 75\"", equipment: "Manubri" },
    ],
  },
  {
    id: "b3",
    pattern: "Dominante ginocchio",
    name: "Squat bilanciere",
    prescription: "5 x 5 @ RPE 8 — rec 180\"",
    alternatives: [
      { name: "Goblet squat", prescription: "4 x 12 @ RPE 7 — rec 90\"", equipment: "Kettlebell" },
      { name: "Affondi camminati", prescription: "3 x 20 passi — rec 90\"", equipment: "Manubri" },
      { name: "Leg press", prescription: "4 x 10 @ RPE 8 — rec 120\"", equipment: "Macchine" },
    ],
  },
  {
    id: "b4",
    pattern: "Core anti-estensione",
    name: "Plank rollout",
    prescription: "3 x 10 controllati",
    alternatives: [
      { name: "Dead bug", prescription: "3 x 8/lato tempo 3\"", equipment: "Corpo libero" },
      { name: "Pallof press", prescription: "3 x 12/lato", equipment: "Elastici" },
      { name: "Hollow hold", prescription: "4 x 30\"", equipment: "Corpo libero" },
    ],
  },
];

const crossfitSeeds: Seed[] = [
  {
    id: "c1",
    pattern: "Warm-up",
    name: "3 giri: 200m row + 10 air squat",
    prescription: "Ritmo conversazionale",
    alternatives: [
      { name: "3 giri: 1' bike + 10 good morning", prescription: "Ritmo facile", equipment: "Macchine" },
      { name: "2 giri: 20 jumping jack + 10 inchworm", prescription: "Progressivo", equipment: "Corpo libero" },
      { name: "3 giri: 15 band pull-apart + 10 lunge", prescription: "Attivazione", equipment: "Elastici" },
    ],
  },
  {
    id: "c2",
    pattern: "Forza",
    name: "Clean & jerk",
    prescription: "6 x 2 @ 75% — ogni 90\"",
    alternatives: [
      { name: "Power clean", prescription: "8 x 2 @ 70% — EMOM", equipment: "Bilanciere" },
      { name: "Kettlebell swing pesante", prescription: "6 x 8 — rec 60\"", equipment: "Kettlebell" },
      { name: "Dumbbell snatch", prescription: "6 x 5/lato — rec 60\"", equipment: "Manubri" },
    ],
  },
  {
    id: "c3",
    pattern: "WOD",
    name: "AMRAP 12': 8 burpee + 12 KB swing + 200m run",
    prescription: "Obiettivo: 6-8 round",
    alternatives: [
      { name: "For time 21-15-9: thruster + pull-up", prescription: "Cap 10' — target 8'", equipment: "Bilanciere" },
      { name: "EMOM 14': 10 box jump / 12 wall ball", prescription: "Alternare i minuti", equipment: "Macchine" },
      { name: "Chipper: 50 double under + 40 sit-up + 30 push-up", prescription: "Cap 13'", equipment: "Corpo libero" },
    ],
  },
  {
    id: "c4",
    pattern: "Cooldown",
    name: "Mobilità anche 5'",
    prescription: "90/90 + pigeon 2 x 60\"",
    alternatives: [
      { name: "Respirazione + t-spine 5'", prescription: "3 x 8 rotazioni", equipment: "Corpo libero" },
      { name: "Stretch catena posteriore", prescription: "3 x 45\"", equipment: "Elastici" },
      { name: "Camminata scarico 6'", prescription: "Zona 1", equipment: "Corpo libero" },
    ],
  },
];

const calisthenicsSeeds: Seed[] = [
  {
    id: "k1",
    pattern: "Skill",
    name: "Handstand contro muro",
    prescription: "5 x 30\" — rec 60\"",
    alternatives: [
      { name: "Pike push-up", prescription: "4 x 8 — rec 75\"", equipment: "Corpo libero" },
      { name: "Wall walk", prescription: "5 x 3 — rec 60\"", equipment: "Corpo libero" },
      { name: "Ring support hold", prescription: "5 x 20\"", equipment: "Sbarra" },
    ],
  },
  {
    id: "k2",
    pattern: "Trazione",
    name: "Trazioni archer",
    prescription: "4 x 5/lato — rec 120\"",
    alternatives: [
      { name: "Trazioni negative 5\"", prescription: "4 x 4 — rec 120\"", equipment: "Sbarra" },
      { name: "Australian pull-up", prescription: "4 x 12 — rec 75\"", equipment: "Sbarra" },
      { name: "Rematore elastico", prescription: "3 x 15 — rec 60\"", equipment: "Elastici" },
    ],
  },
  {
    id: "k3",
    pattern: "Gambe unilaterale",
    name: "Pistol squat assistito",
    prescription: "4 x 6/lato — rec 90\"",
    alternatives: [
      { name: "Step-up alto", prescription: "4 x 10/lato — rec 75\"", equipment: "Corpo libero" },
      { name: "Bulgarian split squat", prescription: "4 x 10/lato — rec 90\"", equipment: "Manubri" },
      { name: "Nordic curl eccentrico", prescription: "4 x 5 — rec 90\"", equipment: "Corpo libero" },
    ],
  },
  {
    id: "k4",
    pattern: "Core dinamico",
    name: "Toes to bar",
    prescription: "4 x 8 — rec 60\"",
    alternatives: [
      { name: "Hanging knee raise", prescription: "4 x 12 — rec 60\"", equipment: "Sbarra" },
      { name: "V-up", prescription: "4 x 15 — rec 45\"", equipment: "Corpo libero" },
      { name: "Ab wheel", prescription: "3 x 10 — rec 60\"", equipment: "Macchine" },
    ],
  },
];

const seedsBySport: Record<Sport, Seed[]> = {
  gym: gymSeeds,
  crossfit: crossfitSeeds,
  calisthenics: calisthenicsSeeds,
};

export const sports: { key: Sport; label: string; blurb: string }[] = [
  { key: "gym", label: "Gym", blurb: "Volume, set e rep" },
  { key: "crossfit", label: "CrossFit", blurb: "Forza + WOD" },
  { key: "calisthenics", label: "Calisthenics", blurb: "Skill + corpo libero" },
];

export const efforts: { key: Effort; label: string; mult: number }[] = [
  { key: "maintenance", label: "Maintenance", mult: 0.85 },
  { key: "average", label: "Average effort", mult: 1 },
  { key: "challenging", label: "Challenging", mult: 1.2 },
];

export function buildSession(sport: Sport, minutes: number): Block[] {
  const seeds = seedsBySport[sport];
  const count = minutes <= 30 ? 2 : minutes <= 50 ? 3 : seeds.length;
  return seeds.slice(0, count).map((s) => ({ ...s, variantIndex: 0 }));
}

export function currentVariant(block: Block) {
  if (block.variantIndex === 0) return { name: block.name, prescription: block.prescription };
  const alt = block.alternatives[(block.variantIndex - 1) % block.alternatives.length];
  if (!alt) return { name: block.name, prescription: block.prescription };
  return { name: alt.name, prescription: alt.prescription };
}

export function estimatedLoad(blocks: Block[], effort: Effort) {
  const mult = efforts.find((e) => e.key === effort)?.mult ?? 1;
  return Math.round(blocks.length * 120 * mult);
}

/** Tutte le opzioni selezionabili per un blocco: originale + alternative */
export function variantOptions(block: Block) {
  return [
    { index: 0, name: block.name, prescription: block.prescription, equipment: "Base" },
    ...block.alternatives.map((a, i) => ({
      index: i + 1,
      name: a.name,
      prescription: a.prescription,
      equipment: a.equipment,
    })),
  ];
}
