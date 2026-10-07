import { Bug as BugIcon, CheckCircle2, CircleDot, Search, ShieldQuestion } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeverityBadge } from "@/components/SeverityBadge";
import { Input } from "@/components/ui/form";
import { EmptyState } from "@/components/ui/states";
import { severityRank } from "@/lib/severity";
import { cn, formatDateTime, pathOf, pct, truncate } from "@/lib/utils";
import type { Bug } from "@/types";

const FILTERS = ["all", "critical", "high", "medium", "low", "verified", "unverified", "open", "resolved"] as const;
type Filter = (typeof FILTERS)[number];

function matches(b: Bug, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "verified" || f === "unverified") return b.status === f;
  if (f === "open" || f === "resolved") return b.resolution === f;
  return b.severity === f;
}

/** Table of bugs with filters and (optional) free-text search. Rows open the full bug page. */
export function BugList({ bugs, showSearch = false, search, onSearch }: { bugs: Bug[]; showSearch?: boolean; search?: string; onSearch?: (v: string) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const counts = useMemo(() => {
    const c = Object.fromEntries(FILTERS.map((f) => [f, 0])) as Record<Filter, number>;
    for (const b of bugs) for (const f of FILTERS) if (matches(b, f)) c[f] += 1;
    return c;
  }, [bugs]);
  const rows = useMemo(() => bugs.filter((b) => matches(b, filter))
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || b.created_at.localeCompare(a.created_at)), [bugs, filter]);

  return (
    <div className="glass min-w-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-3">
        {showSearch && (
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search bugs" placeholder="Search bugs…" value={search ?? ""} onChange={(e) => onSearch?.(e.target.value)} className="pl-9" />
          </div>
        )}
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter bugs">
          {FILTERS.map((f) => (
            <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)}
              className={cn("rounded-full border px-3 py-1 text-xs capitalize transition-colors", filter === f ? "border-primary/50 bg-primary/15 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
              {f} <span className="ml-1 tabular-nums opacity-70">{counts[f]}</span>
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState icon={BugIcon} title="No bugs match" hint={bugs.length ? "Try another filter." : "Bugs appear here once the agent finds and verifies them."} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Detected bugs</caption>
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b border-border">{["Bug ID", "Severity", "Title", "Category", "Confidence", "Status", "URL", "Detected at"].map((h) => <th key={h} scope="col" className="whitespace-nowrap px-4 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} className="border-b border-border/60 transition-colors hover:bg-muted/30">
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs"><Link to={`/bugs/${b.id}`} className="hover:text-primary">{b.bug_ref}</Link></td>
                  <td className="px-4 py-2.5"><SeverityBadge severity={b.severity} /></td>
                  <td className="max-w-[300px] px-4 py-2.5 font-medium"><Link to={`/bugs/${b.id}`} className="hover:text-primary">{truncate(b.title, 70)}</Link></td>
                  <td className="px-4 py-2.5 capitalize text-muted-foreground">{b.category.replace("_", " ")}</td>
                  <td className="px-4 py-2.5 tabular-nums">{pct(b.confidence)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <span className="inline-flex flex-col gap-0.5 text-xs">
                      {b.status === "verified"
                        ? <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden />Verified</span>
                        : <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300"><ShieldQuestion className="h-3.5 w-3.5" aria-hidden />Unverified</span>}
                      <span className="inline-flex items-center gap-1 text-muted-foreground"><CircleDot className="h-3 w-3" aria-hidden />{b.resolution === "resolved" ? "Resolved" : "Open"}</span>
                    </span>
                  </td>
                  <td className="max-w-[180px] truncate px-4 py-2.5 text-muted-foreground" title={b.url}>{pathOf(b.url)}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-muted-foreground">{formatDateTime(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
