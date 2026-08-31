import { Link, useRouterState } from "@tanstack/react-router";
import { User, Swords, Radio, Library } from "lucide-react";
import { cn } from "@/lib/utils";

const tabs = [
  { to: "/", label: "Profilo", icon: User },
  { to: "/sessione", label: "Sessione", icon: Swords },
  { to: "/libreria", label: "Libreria", icon: Library },
  { to: "/network", label: "Network", icon: Radio },
] as const;

export function TabBar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/90 backdrop-blur-xl">
      <ul className="mx-auto flex max-w-md">
        {tabs.map(({ to, label, icon: Icon }) => {
          const active = pathname === to;
          return (
            <li key={to} className="flex-1">
              <Link
                to={to}
                className={cn(
                  "flex flex-col items-center gap-1 py-3 text-[11px] font-semibold transition-colors",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <span
                  className={cn(
                    "grid h-9 w-9 place-items-center rounded-full transition-colors",
                    active ? "bg-primary/12" : "bg-transparent",
                  )}
                >
                  <Icon className="h-[18px] w-[18px]" strokeWidth={2.2} />
                </span>
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

