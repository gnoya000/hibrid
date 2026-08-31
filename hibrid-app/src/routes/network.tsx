import { createFileRoute } from "@tanstack/react-router";
import { Users, Trophy, Swords } from "lucide-react";
import { Screen, Panel } from "@/components/arcade";

export const Route = createFileRoute("/network")({
  head: () => ({
    meta: [
      { title: "hibrid — Network e sfide tra atleti" },
      {
        name: "description",
        content:
          "L'area sociale di hibrid: crew, classifiche settimanali e sfide sulle micro variazioni di allenamento.",
      },
      { property: "og:title", content: "hibrid — Network" },
      {
        property: "og:description",
        content: "Crew, leaderboard e sfide: la parte sociale di hibrid.",
      },
    ],
  }),
  component: Network,
});

const ideas = [
  { icon: Users, title: "Crew", copy: "Piccoli gruppi che condividono routine e varianti." },
  { icon: Trophy, title: "Leaderboard", copy: "Classifica settimanale su streak e volume." },
  { icon: Swords, title: "Sfide", copy: "Duelli 1v1 sullo stesso WOD o sullo stesso blocco." },
];

function Network() {
  return (
    <Screen title="Network" subtitle="Area sociale — in arrivo">
      <Panel className="scanlines mb-4 py-8 text-center">
        <p className="text-display text-2xl text-primary">
          COMING SOON<span className="blink">_</span>
        </p>
        <p className="mx-auto mt-3 max-w-[16rem] text-sm leading-relaxed text-muted-foreground">
          Stiamo definendo come far incontrare gli atleti hibrid. Ecco le direzioni in valutazione.
        </p>
      </Panel>

      <div className="grid gap-2">
        {ideas.map(({ icon: Icon, title, copy }) => (
          <Panel key={title}>
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                <Icon className="h-4 w-4" />
              </span>
              <div>
                <p className="text-display text-base text-foreground">{title}</p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{copy}</p>
              </div>
            </div>
          </Panel>
        ))}
      </div>
    </Screen>
  );
}
