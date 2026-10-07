import { cn } from "@/lib/utils";
import type { RunStatus } from "@/types";

const STYLES: Record<RunStatus, { cls: string; label: string; pulse?: boolean }> = {
  queued: { cls: "bg-slate-500/15 text-slate-600 dark:text-slate-300 border-slate-500/30", label: "QUEUED" },
  initializing: { cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30", label: "INITIALIZING", pulse: true },
  running: { cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30", label: "RUNNING", pulse: true },
  paused: { cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30", label: "PAUSED" },
  completed: { cls: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border-indigo-500/30", label: "COMPLETED" },
  failed: { cls: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30", label: "FAILED" },
  stopped: { cls: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-300 border-zinc-500/30", label: "STOPPED" },
};

export function StatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const s = STYLES[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide", s.cls, className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", s.pulse && "animate-pulse")} />
      {s.label}
    </span>
  );
}
