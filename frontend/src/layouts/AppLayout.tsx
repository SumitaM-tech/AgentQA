import { Bug, GitBranch, LayoutDashboard, Play, Settings, FolderKanban, Radar } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useHealth } from "@/hooks/useApi";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/runs", label: "Runs", icon: Play },
  { to: "/bugs", label: "Bugs", icon: Bug },
  { to: "/explorer", label: "Explorer", icon: GitBranch },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/settings", label: "Settings", icon: Settings },
];

function ConnectionPill() {
  const { data, isError, isLoading } = useHealth();
  const ok = !!data && data.status === "ok";
  const label = isLoading ? "Connecting" : isError ? "Disconnected" : ok ? "Connected" : "Degraded";
  const color = isLoading ? "bg-amber-400" : ok ? "bg-emerald-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 text-xs" role="status">
      <span className={cn("h-2 w-2 rounded-full", color, ok && "animate-pulse")} />
      {label}
    </div>
  );
}

export default function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:p-2">Skip to content</a>
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur">
        <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/20 text-primary"><Radar className="h-4 w-4" /></span>
          AgentQA <span className="text-muted-foreground font-normal">Cloud</span>
        </NavLink>
        <ConnectionPill />
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto border-b border-border p-2 md:w-52 md:flex-col md:border-b-0 md:border-r md:p-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
                  isActive && "bg-primary/15 text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <main id="content" tabIndex={-1} className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
