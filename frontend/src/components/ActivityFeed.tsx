import { AlertTriangle, Brain, Bug, Camera, CheckCircle2, Compass, Flag, MousePointerClick, Play, ScanEye } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn, formatClock } from "@/lib/utils";
import type { RunEvent } from "@/types";

const ICONS: Record<string, { icon: typeof Brain; cls: string }> = {
  run_started: { icon: Play, cls: "text-emerald-600 dark:text-emerald-400" },
  page_loaded: { icon: ScanEye, cls: "text-sky-600 dark:text-sky-400" },
  observation: { icon: ScanEye, cls: "text-slate-400" },
  agent_thinking: { icon: Brain, cls: "text-violet-600 dark:text-violet-400" },
  agent_action: { icon: MousePointerClick, cls: "text-foreground" },
  action_completed: { icon: CheckCircle2, cls: "text-emerald-600 dark:text-emerald-400" },
  state_discovered: { icon: Compass, cls: "text-cyan-600 dark:text-cyan-400" },
  state_revisited: { icon: Compass, cls: "text-slate-500" },
  bug_detected: { icon: Bug, cls: "text-amber-600 dark:text-amber-400" },
  bug_verified: { icon: Bug, cls: "text-red-600 dark:text-red-400" },
  screenshot_created: { icon: Camera, cls: "text-slate-500" },
  error: { icon: AlertTriangle, cls: "text-red-600 dark:text-red-400" },
  run_completed: { icon: Flag, cls: "text-indigo-400" },
};

/** `observation`, `screenshot_created` and `state_revisited` are noisy; hidden unless "verbose". */
const QUIET = new Set(["observation", "screenshot_created", "state_revisited"]);

export function ActivityFeed({ events, verbose = false, limit = 400, height = "h-[360px]" }: { events: RunEvent[]; verbose?: boolean; limit?: number; height?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  // Only the newest `limit` rows are rendered, so very long runs stay fast.
  const shown = events.filter((e) => verbose || !QUIET.has(e.type)).slice(-limit);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <div
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      className={cn(height, "space-y-0.5 overflow-y-auto p-2 font-mono text-xs")}
      role="log"
      aria-live="polite"
    >
      {shown.length === 0 && <p className="p-4 text-center text-muted-foreground">Waiting for agent activity…</p>}
      {shown.map((e) => {
        const meta = ICONS[e.type] ?? ICONS.observation;
        const Icon = meta.icon;
        return (
          <div key={e.seq} className="flex items-start gap-2 rounded-md px-2 py-1 hover:bg-muted/40">
            <span className="mt-0.5 shrink-0 tabular-nums text-muted-foreground">{formatClock(e.timestamp)}</span>
            <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", meta.cls)} />
            <span className={cn("min-w-0 break-words", e.type === "agent_thinking" && "italic text-muted-foreground")}>{e.message}</span>
          </div>
        );
      })}
    </div>
  );
}
