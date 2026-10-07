import { Bug, CheckCircle2, CircleDot, Gauge } from "lucide-react";
import { useState } from "react";

import { BugList } from "@/components/BugList";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { StackedBar } from "@/components/charts";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useBugStats, useBugs } from "@/hooks/useApi";
import { useDebounce } from "@/hooks/useDebounce";
import { SEVERITY_ORDER, SEVERITY_STYLES } from "@/lib/severity";
import { pct } from "@/lib/utils";

export default function BugsPage() {
  const [search, setSearch] = useState("");
  const q = useDebounce(search.trim(), 300);
  const bugs = useBugs({ q: q || undefined });
  const stats = useBugStats();
  const s = stats.data;
  return (
    <>
      <PageHeader title="Bugs" subtitle="Findings from all runs, with evidence and verification status" />
      <div className="mb-5 space-y-4">
        {stats.isLoading ? <Skeleton className="h-24" /> : s && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricCard label="Total bugs" value={s.total} icon={Bug} />
              <MetricCard label="Verified" value={s.verified} icon={CheckCircle2} tone="success" hint={`${s.unverified} unverified`} />
              <MetricCard label="Open" value={s.open} icon={CircleDot} tone={s.open ? "danger" : "default"} hint={`${s.resolved} resolved`} />
              <MetricCard label="Avg. confidence" value={s.avg_confidence == null ? "—" : pct(s.avg_confidence)} icon={Gauge} />
            </div>
            {s.total > 0 && (
              <Card><CardHeader title="By severity" /><div className="p-4">
                <StackedBar label="Bugs by severity" parts={SEVERITY_ORDER.map((k) => ({ label: SEVERITY_STYLES[k].label, value: s.by_severity[k] ?? 0, className: SEVERITY_STYLES[k].dot }))} /></div></Card>
            )}
          </>
        )}
      </div>
      {bugs.isLoading ? <Skeleton className="h-64" /> : bugs.error ? <ErrorState error={bugs.error} onRetry={bugs.refetch} /> : <BugList bugs={bugs.data ?? []} showSearch search={search} onSearch={setSearch} />}
    </>
  );
}
