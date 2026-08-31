import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Screen({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="safe-top mx-auto w-full max-w-md px-5 pt-8 pb-32">
      <header className="mb-6">
        <h1 className="text-display text-[28px] text-foreground">{title}</h1>
        {subtitle ? (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        ) : null}
      </header>
      {children}
    </div>
  );
}

export function Panel({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <section className={cn("arcade-panel rounded-2xl p-5", className)}>
      {label ? (
        <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </h2>
      ) : null}
      {children}
    </section>
  );
}

const barColor: Record<string, string> = {
  neon: "bg-neon",
  cyan: "bg-cyan",
  magenta: "bg-magenta",
  amber: "bg-amber",
};

function Track({
  value,
  className,
  striped,
}: {
  value: number;
  className: string;
  striped?: boolean;
}) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full transition-all", className)}
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          ...(striped
            ? {
                backgroundImage:
                  "repeating-linear-gradient(115deg, color-mix(in oklab, white 45%, transparent) 0 3px, transparent 3px 7px)",
              }
            : {}),
        }}
      />
    </div>
  );
}

/**
 * Two parallel lines per skill:
 * - frequency: how often the user trains that skill
 * - objective: assessed level from test assessments
 */
export function StatBar({
  label,
  frequency,
  objective,
  color = "neon",
}: {
  label: string;
  frequency: number;
  objective: number;
  color?: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">
          <span className="text-foreground/70">{frequency}%</span> ·{" "}
          <span className="text-display text-xs text-primary">{objective}</span>
        </span>
      </div>
      <div className="mt-2 grid gap-1.5">
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Freq.
          </span>
          <Track value={frequency} className={cn(barColor[color], "opacity-45")} striped />
        </div>
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            Livello
          </span>
          <Track value={objective} className={barColor[color] ?? "bg-neon"} />
        </div>
      </div>
    </div>
  );
}

export function ArcadeButton({
  children,
  onClick,
  variant = "ghost",
  className,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost";
  className?: string;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      className={cn(
        "rounded-full border px-4 py-2 text-sm font-semibold transition-all active:scale-[0.97]",
        variant === "primary"
          ? "border-transparent bg-primary text-primary-foreground arcade-glow"
          : "border-border bg-secondary text-foreground hover:border-primary/50 hover:text-primary",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Chip({
  children,
  active,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3.5 py-2 text-xs font-medium transition-colors",
        active
          ? "border-primary bg-primary/12 text-primary"
          : "border-border bg-secondary/70 text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
