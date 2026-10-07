import type { Severity } from "@/types";

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "cosmetic"];

export const SEVERITY_STYLES: Record<Severity, { label: string; badge: string; dot: string; ring: string }> = {
  critical: { label: "Critical", badge: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30", dot: "bg-red-400", ring: "#f87171" },
  high: { label: "High", badge: "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/30", dot: "bg-orange-400", ring: "#fb923c" },
  medium: { label: "Medium", badge: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30", dot: "bg-amber-400", ring: "#fbbf24" },
  low: { label: "Low", badge: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30", dot: "bg-sky-400", ring: "#38bdf8" },
  cosmetic: { label: "Cosmetic", badge: "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/30", dot: "bg-slate-400", ring: "#94a3b8" },
};

export function severityRank(s: Severity): number {
  return SEVERITY_ORDER.indexOf(s);
}
