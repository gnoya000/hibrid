import { createFileRoute } from "@tanstack/react-router";
import { Flame } from "lucide-react";
import { Screen, Panel, StatBar } from "@/components/arcade";
import { avatarStats, weekStreak } from "@/lib/fitness-data";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "hibrid — Profilo atleta e streak settimanale" },
      {
        name: "description",
        content:
          "Il tuo avatar hibrid: forza, agilità, resistenza, ipertrofia e mobilità, più la streak degli allenamenti della settimana.",
      },
      { property: "og:title", content: "hibrid — Profilo atleta" },
      {
        property: "og:description",
        content: "Punteggi di fitness e streak settimanale nel tuo profilo hibrid.",
      },
    ],
  }),
  component: Profilo,
});

function Profilo() {
  const overall = Math.round(
    avatarStats.reduce((a, s) => a + s.objective, 0) / avatarStats.length,
  );

  return (
    <Screen title="hibrid" subtitle="Ciao Giacomo — ecco il tuo stato di forma">
      <Panel className="mb-4">
        <div className="flex items-center gap-4">
          <div className="grid h-20 w-20 shrink-0 place-items-center rounded-2xl bg-primary/10">
            <PixelAvatar />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Livello fitness
            </p>
            <p className="text-display mt-1 text-[36px] leading-none text-primary">{overall}</p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Ibrido — forza + condizionamento
            </p>
          </div>
        </div>
      </Panel>

      <Panel label="Attributi" className="mb-4">
        <p className="-mt-2 mb-4 text-xs leading-relaxed text-muted-foreground">
          Per ogni skill: <span className="text-foreground/80">frequenza</span> di allenamento e{" "}
          <span className="text-primary">livello obiettivo</span> dai test assessment.
        </p>
        <div className="grid gap-4">
          {avatarStats.map((s) => (
            <StatBar
              key={s.key}
              label={s.label}
              frequency={s.frequency}
              objective={s.objective}
              color={s.color}
            />
          ))}
        </div>
      </Panel>

      <Panel label="Streak settimana">
        <div className="flex items-end justify-between">
          <p className="text-display text-[28px] leading-none text-primary">
            {weekStreak.done}
            <span className="text-muted-foreground">/{weekStreak.target}</span>
          </p>
          <span className="flex items-center gap-1.5 rounded-full bg-amber/15 px-3 py-1 text-xs font-semibold text-foreground/80">
            <Flame className="h-3.5 w-3.5" /> {weekStreak.done} di fila
          </span>
        </div>
        <div className="mt-4 grid grid-cols-7 gap-1.5">
          {weekStreak.days.map((d) => (
            <div key={d.day} className="text-center">
              <div
                className={cn(
                  "grid h-10 place-items-center rounded-xl border text-sm",
                  d.state === "done" && "border-transparent bg-primary text-primary-foreground",
                  d.state === "todo" && "border-dashed border-border text-muted-foreground",
                  d.state === "rest" && "border-transparent bg-muted text-muted-foreground/70",
                )}
              >
                {d.state === "done" ? "✓" : d.state === "rest" ? "–" : "?"}
              </div>
              <p className="mt-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                {d.day}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          Mancano <span className="font-semibold text-primary">{Math.max(0, weekStreak.target - weekStreak.done)}</span>{" "}
          sessioni per completare la settimana.
        </p>
      </Panel>
    </Screen>
  );
}


function PixelAvatar() {
  const grid = [
    "0011100",
    "0111110",
    "0101010",
    "0111110",
    "0011100",
    "0111110",
    "1101011",
    "0010100",
  ];
  return (
    <div className="grid gap-[1px]">
      {grid.map((row, y) => (
        <div key={y} className="flex gap-[1px]">
          {row.split("").map((c, x) => (
            <span
              key={x}
              className={cn(
                "h-[7px] w-[7px] rounded-[1px]",
                c === "1" ? "bg-primary" : "bg-transparent",
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
