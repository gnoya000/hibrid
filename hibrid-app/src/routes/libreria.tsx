import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Plus, Timer, Layers, Check, ChevronDown, Copy } from "lucide-react";
import { Screen, Panel, ArcadeButton, Chip } from "@/components/arcade";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { currentVariant, efforts, type Effort, type Sport } from "@/lib/fitness-data";
import {
  createRoutine,
  libraries,
  starterRoutines,
  type SavedRoutine,
} from "@/lib/library-data";

export const Route = createFileRoute("/libreria")({
  head: () => ({
    meta: [
      { title: "hibrid — Libreria di routine e sessioni" },
      {
        name: "description",
        content:
          "Pre-genera e salva routine hibrid divise per libreria: weight training, calisthenics e CrossFit, con prefill da routine esistenti.",
      },
      { property: "og:title", content: "hibrid — Libreria" },
      {
        property: "og:description",
        content: "Routine pronte all'uso, organizzate per libreria e riutilizzabili come base.",
      },
    ],
  }),
  component: Libreria,
});

function Libreria() {
  const [library, setLibrary] = useState<Sport>("gym");
  const [routines, setRoutines] = useState<SavedRoutine[]>(starterRoutines);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [name, setName] = useState("");
  const [minutes, setMinutes] = useState(45);
  const [effort, setEffort] = useState<Effort>("average");
  const [prefillId, setPrefillId] = useState<string | null>(null);

  const list = useMemo(() => routines.filter((r) => r.sport === library), [routines, library]);
  const prefillCandidates = list;

  const openCreate = () => {
    setName("");
    setMinutes(45);
    setEffort("average");
    setPrefillId(null);
    setCreating(true);
  };

  const save = () => {
    const prefillFrom = routines.find((r) => r.id === prefillId) ?? null;
    const next = createRoutine({ name, sport: library, minutes, effort, prefillFrom });
    setRoutines((prev) => [next, ...prev]);
    setCreating(false);
    setOpenId(next.id);
  };

  return (
    <Screen title="Libreria" subtitle="Routine pre-generate, pronte da usare">
      <div className="mb-3 flex flex-wrap gap-1.5">
        {libraries.map((l) => (
          <Chip key={l.key} active={library === l.key} onClick={() => setLibrary(l.key)}>
            {l.label}
          </Chip>
        ))}
      </div>

      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {list.length} routine salvate
        </p>
        <ArcadeButton variant="primary" onClick={openCreate}>
          <span className="inline-flex items-center gap-1.5">
            <Plus className="h-4 w-4" /> Nuova
          </span>
        </ArcadeButton>
      </div>

      <div className="grid gap-2">
        {list.length === 0 ? (
          <Panel className="py-8 text-center">
            <p className="text-sm text-muted-foreground">
              Nessuna routine in questa libreria. Creane una nuova.
            </p>
          </Panel>
        ) : null}

        {list.map((r) => {
          const open = openId === r.id;
          return (
            <Panel key={r.id}>
              <button
                type="button"
                onClick={() => setOpenId(open ? null : r.id)}
                className="flex w-full items-start justify-between gap-3 text-left"
              >
                <div>
                  <p className="text-display text-base text-foreground">{r.name}</p>
                  <p className="mt-1.5 flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <Timer className="h-3.5 w-3.5" /> {r.minutes}'
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Layers className="h-3.5 w-3.5" /> {r.blocks.length} blocchi
                    </span>
                    <span className="text-primary">
                      {efforts.find((e) => e.key === r.effort)?.label}
                    </span>
                  </p>
                </div>
                <ChevronDown
                  className={
                    "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform " +
                    (open ? "rotate-180" : "")
                  }
                />
              </button>

              {open ? (
                <div className="mt-3 grid gap-2 border-t border-border pt-3">
                  {r.blocks.map((b, i) => {
                    const v = currentVariant(b);
                    return (
                      <div key={b.id}>
                        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan">
                          {String(i + 1).padStart(2, "0")} · {b.pattern}
                        </p>
                        <p className="mt-1 text-sm leading-snug text-foreground">{v.name}</p>
                        <p className="text-sm text-muted-foreground">{v.prescription}</p>
                      </div>
                    );
                  })}
                  <ArcadeButton
                    className="mt-2 w-full justify-center py-2.5"
                    onClick={() => {
                      setName(`${r.name} copia`);
                      setMinutes(r.minutes);
                      setEffort(r.effort);
                      setPrefillId(r.id);
                      setCreating(true);
                    }}
                  >
                    <span className="inline-flex items-center gap-2">
                      <Copy className="h-4 w-4" /> Usa come base
                    </span>
                  </ArcadeButton>
                </div>
              ) : null}
            </Panel>
          );
        })}
      </div>

      <Sheet open={creating} onOpenChange={setCreating}>
        <SheetContent
          side="bottom"
          className="safe-bottom max-h-[88vh] overflow-y-auto rounded-t-3xl border-border"
        >
          <SheetHeader className="text-left">
            <SheetTitle className="text-display text-xl">Nuova routine</SheetTitle>
            <SheetDescription>
              Libreria: {libraries.find((l) => l.key === library)?.label}
            </SheetDescription>
          </SheetHeader>

          <div className="mt-4 grid gap-4">
            <div>
              <label
                htmlFor="routine-name"
                className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
              >
                Nome
              </label>
              <input
                id="routine-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Es. Upper power"
                className="w-full rounded-xl border border-border bg-secondary/50 px-4 py-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-primary"
              />
            </div>

            <div>
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.1em]">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <Timer className="h-3.5 w-3.5" /> Durata
                </span>
                <span className="text-display text-sm text-primary">{minutes}'</span>
              </div>
              <input
                type="range"
                min={20}
                max={90}
                step={5}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
                className="mt-3 h-1.5 w-full appearance-none rounded-full bg-muted accent-primary"
              />
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Effort
              </p>
              <div className="grid grid-cols-3 gap-2">
                {efforts.map((e) => (
                  <Chip key={e.key} active={effort === e.key} onClick={() => setEffort(e.key)}>
                    {e.label}
                  </Chip>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Precompila da routine esistente
              </p>
              <div className="grid gap-2">
                <button
                  type="button"
                  onClick={() => setPrefillId(null)}
                  className={
                    "flex items-center justify-between rounded-2xl border p-4 text-left transition-colors " +
                    (prefillId === null
                      ? "border-primary bg-primary/10"
                      : "border-border bg-secondary/50 hover:border-primary/60")
                  }
                >
                  <span className="text-sm font-semibold text-foreground">
                    Genera da zero
                  </span>
                  {prefillId === null ? <Check className="h-4 w-4 text-primary" /> : null}
                </button>
                {prefillCandidates.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setPrefillId(r.id)}
                    className={
                      "flex items-center justify-between gap-3 rounded-2xl border p-4 text-left transition-colors " +
                      (prefillId === r.id
                        ? "border-primary bg-primary/10"
                        : "border-border bg-secondary/50 hover:border-primary/60")
                    }
                  >
                    <span>
                      <span className="block text-sm font-semibold text-foreground">{r.name}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {r.blocks.length} blocchi · {r.minutes}'
                      </span>
                    </span>
                    {prefillId === r.id ? (
                      <Check className="h-4 w-4 shrink-0 text-primary" />
                    ) : null}
                  </button>
                ))}
              </div>
            </div>

            <ArcadeButton variant="primary" className="w-full justify-center py-3" onClick={save}>
              Salva in libreria
            </ArcadeButton>
          </div>
        </SheetContent>
      </Sheet>
    </Screen>
  );
}
