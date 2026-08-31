import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { RefreshCw, Timer, Dumbbell, Zap, Check, Shuffle, Loader2 } from "lucide-react";
import { Screen, Panel, ArcadeButton, Chip } from "@/components/arcade";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  buildSession,
  currentVariant,
  variantOptions,
  efforts,
  equipmentOptions,
  estimatedLoad,
  muscleGroups,
  sports,
  type Effort,
  type Sport,
} from "@/lib/fitness-data";
import { generateSession, varyBlock } from "@/lib/engine-api";

export const Route = createFileRoute("/sessione")({
  head: () => ({
    meta: [
      { title: "hibrid — Crea la sessione di allenamento" },
      {
        name: "description",
        content:
          "Genera una sessione hibrid da tempo disponibile, muscoli, attrezzatura ed effort, e sostituisci ogni esercizio con un'alternativa equivalente.",
      },
      { property: "og:title", content: "hibrid — Creazione sessione" },
      {
        property: "og:description",
        content: "Routine gym, CrossFit o calisthenics adattate ai tuoi parametri locali.",
      },
    ],
  }),
  component: Sessione,
});

function Sessione() {
  const [sport, setSport] = useState<Sport>("gym");
  const [minutes, setMinutes] = useState(45);
  const [effort, setEffort] = useState<Effort>("average");
  const [muscles, setMuscles] = useState<string[]>(["Full body"]);
  const [gear, setGear] = useState<string[]>(["Bilanciere", "Manubri"]);
  // Mock blocks for the very first (server-rendered) paint; replaced by the
  // engine once the component mounts in the browser.
  const [blocks, setBlocks] = useState(() => buildSession("gym", 45));
  const [editingId, setEditingId] = useState<string | null>(null);
  const [source, setSource] = useState<"engine" | "mock">("mock");
  const [loading, setLoading] = useState(false);
  const [swappingId, setSwappingId] = useState<string | null>(null);
  const reqId = useRef(0);

  const toggle = (list: string[], set: (v: string[]) => void, item: string) =>
    set(list.includes(item) ? list.filter((i) => i !== item) : [...list, item]);

  const regenerate = async (
    nextSport = sport,
    nextMinutes = minutes,
    nextEffort = effort,
    nextMuscles = muscles,
  ) => {
    const id = ++reqId.current;
    setLoading(true);
    try {
      const result = await generateSession({
        sport: nextSport,
        minutes: nextMinutes,
        effort: nextEffort,
        muscles: nextMuscles,
      });
      if (id !== reqId.current) return; // a newer request superseded this one
      setBlocks(result.blocks);
      setSource(result.source);
    } catch {
      /* aborted; ignore */
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  };

  // Pull a real session from the engine on mount (client-side only, so SSR keeps
  // the synchronous mock render).
  useEffect(() => {
    void regenerate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const swap = async (id: string) => {
    const block = blocks.find((b) => b.id === id);
    if (!block) return;
    if (block.engine) {
      setSwappingId(id);
      try {
        const v = await varyBlock(block);
        if (v) {
          setBlocks((prev) =>
            prev.map((b) =>
              b.id === id
                ? {
                    ...b,
                    alternatives: [
                      ...b.alternatives,
                      { name: v.name, prescription: v.prescription, equipment: v.equipment },
                    ],
                    variantIndex: b.alternatives.length + 1,
                    engine: v.engine,
                  }
                : b,
            ),
          );
          return;
        }
      } finally {
        setSwappingId(null);
      }
    }
    // Fallback: cycle through locally-known alternatives.
    setBlocks((prev) =>
      prev.map((b) => (b.id === id ? { ...b, variantIndex: b.variantIndex + 1 } : b)),
    );
  };

  const setVariant = (id: string, index: number) =>
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, variantIndex: index } : b)));

  const editing = blocks.find((b) => b.id === editingId) ?? null;

  return (
    <Screen title="Crea sessione" subtitle="Micro variazioni, stessi obiettivi">
      <Panel label="Sport" className="mb-3">
        <div className="grid grid-cols-3 gap-2">
          {sports.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => {
                setSport(s.key);
                void regenerate(s.key, minutes);
              }}
              className={
                "rounded-xl border p-3 text-left transition-colors " +
                (sport === s.key
                  ? "border-primary bg-primary/15"
                  : "border-border bg-secondary/50 hover:border-primary/60")
              }
            >
              <p className="text-display text-base text-foreground">{s.label}</p>
              <p className="mt-1.5 text-xs leading-snug text-muted-foreground">{s.blurb}</p>
            </button>
          ))}
        </div>
      </Panel>

      <Panel label="Parametri locali" className="mb-3">
        <div className="mb-4">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.1em]">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Timer className="h-3.5 w-3.5" /> Tempo
            </span>
            <span className="text-display text-sm text-primary">{minutes}'</span>
          </div>
          <input
            type="range"
            min={20}
            max={90}
            step={5}
            value={minutes}
            onChange={(e) => {
              const v = Number(e.target.value);
              setMinutes(v);
              void regenerate(sport, v);
            }}
            className="mt-3 h-1.5 w-full appearance-none rounded-full bg-muted accent-primary"
          />
        </div>

        <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          <Dumbbell className="h-3.5 w-3.5" /> Muscoli
        </p>
        <div className="mb-4 flex flex-wrap gap-1.5">
          {muscleGroups.map((m) => (
            <Chip
              key={m}
              active={muscles.includes(m)}
              onClick={() => toggle(muscles, setMuscles, m)}
            >
              {m}
            </Chip>
          ))}
        </div>

        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Attrezzatura
        </p>
        <div className="mb-4 flex flex-wrap gap-1.5">
          {equipmentOptions.map((e) => (
            <Chip key={e} active={gear.includes(e)} onClick={() => toggle(gear, setGear, e)}>
              {e}
            </Chip>
          ))}
        </div>

        <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          <Zap className="h-3.5 w-3.5" /> Effort
        </p>
        <div className="grid grid-cols-3 gap-2">
          {efforts.map((e) => (
            <Chip
              key={e.key}
              active={effort === e.key}
              onClick={() => {
                setEffort(e.key);
                void regenerate(sport, minutes, e.key);
              }}
            >
              {e.label}
            </Chip>
          ))}
        </div>
      </Panel>

      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Routine generata
          </p>
          <span
            className={
              "rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] " +
              (source === "engine"
                ? "bg-primary/15 text-primary"
                : "bg-muted text-muted-foreground")
            }
            title={
              source === "engine"
                ? "Sessione generata dal motore hibrid"
                : "Motore non raggiungibile: dati locali di esempio"
            }
          >
            {source === "engine" ? "engine" : "offline"}
          </span>
        </div>
        <ArcadeButton variant="primary" onClick={() => void regenerate()}>
          <span className="inline-flex items-center gap-1.5">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Rigenera
          </span>
        </ArcadeButton>
      </div>

      <div className="grid gap-2">
        {blocks.map((b, i) => {
          const v = currentVariant(b);
          return (
            <Panel key={b.id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
                    {String(i + 1).padStart(2, "0")} · {b.pattern}
                  </p>
                  <p className="mt-1.5 text-sm leading-snug text-foreground">{v.name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{v.prescription}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditingId(b.id)}
                  aria-label={`Modifica o rigenera l'esercizio ${b.pattern}`}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-border text-muted-foreground transition-colors hover:border-primary hover:text-primary active:scale-[0.95]"
                >
                  {swappingId === b.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                </button>
              </div>
              {b.variantIndex > 0 ? (
                <p className="mt-3 border-t border-border pt-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-magenta">
                  Variante {b.variantIndex} · stesso stimolo
                </p>
              ) : null}
            </Panel>
          );
        })}
      </div>

      <Panel className="mt-3">
        <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          <span>Carico stimato</span>
          <span className="text-display text-sm text-primary">
            {estimatedLoad(blocks, effort)} au
          </span>
        </div>
      </Panel>

      <ArcadeButton variant="primary" className="mt-3 w-full py-3">
        Start sessione
      </ArcadeButton>

      <Sheet open={editing !== null} onOpenChange={(o) => !o && setEditingId(null)}>
        <SheetContent
          side="bottom"
          className="safe-bottom max-h-[85vh] overflow-y-auto rounded-t-3xl border-border"
        >
          {editing ? (
            <>
              <SheetHeader className="text-left">
                <SheetTitle className="text-display text-xl">{editing.pattern}</SheetTitle>
                <SheetDescription>
                  Scegli manualmente il movimento: stesso stimolo, stessi obiettivi.
                </SheetDescription>
              </SheetHeader>

              <div className="mt-4 grid gap-2">
                {variantOptions(editing).map((opt) => {
                  const active =
                    editing.variantIndex % (editing.alternatives.length + 1) === opt.index;
                  return (
                    <button
                      key={opt.index}
                      type="button"
                      onClick={() => {
                        setVariant(editing.id, opt.index);
                        setEditingId(null);
                      }}
                      className={
                        "flex items-start justify-between gap-3 rounded-2xl border p-4 text-left transition-colors " +
                        (active
                          ? "border-primary bg-primary/10"
                          : "border-border bg-secondary/50 hover:border-primary/60")
                      }
                    >
                      <div>
                        <p className="text-sm font-semibold text-foreground">{opt.name}</p>
                        <p className="mt-1 text-sm text-muted-foreground">{opt.prescription}</p>
                        <p className="mt-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
                          {opt.equipment}
                        </p>
                      </div>
                      {active ? <Check className="mt-1 h-4 w-4 shrink-0 text-primary" /> : null}
                    </button>
                  );
                })}
              </div>

              <ArcadeButton
                variant="primary"
                className="mt-4 w-full justify-center py-3"
                onClick={() => {
                  swap(editing.id);
                  setEditingId(null);
                }}
              >
                <span className="inline-flex items-center gap-2">
                  <Shuffle className="h-4 w-4" /> Rigenera automaticamente
                </span>
              </ArcadeButton>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </Screen>
  );
}
