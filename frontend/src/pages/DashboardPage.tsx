import { Activity, Clock, Compass, Plus, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { BarChart, GroupedBars, StackedBar } from "@/components/charts";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { RunTable } from "@/components/RunTable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton, TableSkeleton } from "@/components/ui/skeleton";
import { useSummary } from "@/hooks/useApi";
import { SEVERITY_ORDER, SEVERITY_STYLES } from "@/lib/severity";
import { formatDuration } from "@/lib/utils";

const STATUS_PARTS = [
  { key: "completed", label: "Completed", className: "bg-indigo-500" },
  { key: "running", label: "Running", className: "bg-emerald-500" },
  { key: "failed", label: "Failed", className: "bg-red-500" },
  { key: "stopped", label: "Stopped", className: "bg-zinc-500" },
] as const;

export default function DashboardPage() {
  const { data, isLoading, error, refetch } = useSummary();
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Autonomous QA across your applications"
        actions={<Link to="/runs/new"><Button variant="primary"><Plus className="h-4 w-4" /> New QA Run</Button></Link>} />
      {isLoading ? (
        <div className="space-y-5"><div className="grid grid-cols-2 gap-3 lg:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div><TableSkeleton /></div>
      ) : error || !data ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <MetricCard label="Total runs" value={data.runs_total} icon={Activity} />
            <MetricCard label="Active runs" value={data.runs_active} icon={Activity} tone={data.runs_active ? "success" : "default"} />
            <MetricCard label="Verified bugs" value={data.bugs_verified} icon={ShieldCheck} tone={data.bugs_verified ? "danger" : "default"} hint={`${data.bugs_total} total`} />
            <MetricCard label="States explored" value={data.states_total} icon={Compass} />
            <MetricCard label="Avg. run duration" value={data.avg_run_duration_seconds == null ? "—" : formatDuration(data.avg_run_duration_seconds)} icon={Clock} />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card><CardHeader title="Runs over time (14 days)" />
              <div className="p-4">{data.runs_total === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">No runs yet.</p>
                : <BarChart label="Runs per day for the last 14 days" data={data.runs_by_day.map((d) => ({ label: d.date.slice(5), value: d.runs }))} />}</div></Card>
            <Card><CardHeader title="Run status distribution" />
              <div className="p-4"><StackedBar label="Runs by status" parts={STATUS_PARTS.map((p) => ({ label: p.label, className: p.className, value: data.status_counts[p.key] ?? 0 }))} /></div></Card>
            <Card><CardHeader title="Bugs by severity" />
              <ul className="space-y-2 p-4 text-sm">
                {SEVERITY_ORDER.map((s) => {
                  const n = data.bugs_by_severity[s] ?? 0;
                  const max = Math.max(1, ...Object.values(data.bugs_by_severity).map((v) => v ?? 0));
                  return (
                    <li key={s} className="space-y-1">
                      <div className="flex justify-between"><span>{SEVERITY_STYLES[s].label}</span><span className="tabular-nums text-muted-foreground">{n}</span></div>
                      <div className="h-1.5 rounded-full bg-muted"><div className={`h-full rounded-full ${SEVERITY_STYLES[s].dot}`} style={{ width: `${(n / max) * 100}%` }} /></div>
                    </li>
                  );
                })}
              </ul></Card>
            <Card><CardHeader title="Exploration activity (latest runs)" />
              <div className="p-4">{data.recent_activity.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">No runs yet.</p>
                : <GroupedBars label="States, actions and bugs for the latest runs" data={data.recent_activity.map((a) => ({ label: a.label, a: a.states, b: a.actions, c: a.bugs }))} />}</div></Card>
          </div>
          <Card>
            <CardHeader title="Recent runs" action={<Link to="/runs" className="text-xs text-primary hover:underline">View all</Link>} />
            {data.recent_runs.length === 0
              ? <EmptyState icon={Plus} title="No runs yet" hint="Start your first autonomous QA run against a website." action={<Link to="/runs/new"><Button variant="primary" size="sm">+ New QA Run</Button></Link>} />
              : <RunTable runs={data.recent_runs} />}
          </Card>
        </div>
      )}
    </>
  );
}
