import { AlertTriangle, Bug, Compass, Gauge, MousePointerClick, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { assetUrl } from "@/api/client";
import { ActivityFeed } from "@/components/ActivityFeed";
import { BrowserPreview } from "@/components/BrowserPreview";
import { BugList } from "@/components/BugList";
import { EvaluationPanel } from "@/components/EvaluationPanel";
import { ExplorationGraph } from "@/components/ExplorationGraph";
import { MetricCard } from "@/components/MetricCard";
import { RunControls } from "@/components/RunControls";
import { ScreenshotPreview } from "@/components/ScreenshotPreview";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useRun, useRunBugs, useRunGraph } from "@/hooks/useApi";
import { useElapsed } from "@/hooks/useElapsed";
import { useRunStream } from "@/hooks/useRunStream";
import { cn, formatDateTime, formatDuration, hostOf, pathOf, pct } from "@/lib/utils";
import { isActive } from "@/types";

const TABS = ["Overview", "Timeline", "States", "Graph", "Bugs", "Screenshots", "Metrics"] as const;
type Tab = (typeof TABS)[number];

export default function RunPage() {
  const { runId = "" } = useParams();
  return <RunView key={runId} runId={runId} />;
}

function Verbose({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} /> Verbose</label>;
}

function RunView({ runId }: { runId: string }) {
  const run = useRun(runId);
  const live = !!run.data && isActive(run.data.status);
  const stream = useRunStream(runId, run.isSuccess ? live : true);
  const graph = useRunGraph(runId, live);
  const bugs = useRunBugs(runId, live);
  const [tab, setTab] = useState<Tab>("Overview");
  const [verbose, setVerbose] = useState(false);
  const r = run.data;
  const elapsed = useElapsed(r?.started_at ?? null, !!r && (r.status === "running" || r.status === "initializing"), r?.duration_seconds ?? null);

  if (run.isLoading) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-24" /><Skeleton className="h-72" /></div>;
  if (run.error || !r) return <ErrorState error={run.error} onRetry={run.refetch} />;
  const preview = stream.screenshot ?? assetUrl(r.last_screenshot_url);
  const shots = [
    ...(graph.data?.states ?? []).filter((s) => s.screenshot_url).map((s) => ({ key: `s${s.id}`, url: s.screenshot_url, label: `State: ${s.title || pathOf(s.url)}` })),
    ...(bugs.data ?? []).filter((b) => b.screenshot_url).map((b) => ({ key: `b${b.id}`, url: b.screenshot_url, label: `${b.bug_ref}: ${b.title}` })),
  ];

  return (
    <div className="space-y-5">
      <div className="glass flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-3"><StatusBadge status={r.status} /><span className="truncate font-semibold">{hostOf(r.target_url)}</span>
            <span className="font-mono text-xs text-muted-foreground" title={r.id}>#{r.id.slice(0, 8)}</span></div>
          <p className="max-w-2xl truncate text-sm text-muted-foreground" title={r.goal}>{r.goal}</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
            <span>Duration <b className="tabular-nums text-foreground">{formatDuration(elapsed)}</b></span>
            <span>Steps <b className="tabular-nums text-foreground">{r.steps_taken}/{r.max_steps}</b></span>
            <span className="flex items-center gap-1.5" role="status">
              <span className={cn("h-1.5 w-1.5 rounded-full", stream.state === "open" ? "bg-emerald-500" : stream.state === "reconnecting" ? "animate-pulse bg-amber-500" : "bg-slate-500")} aria-hidden />
              {stream.state === "open" ? "Live" : stream.state === "reconnecting" ? "Reconnecting…" : stream.state === "connecting" ? "Connecting…" : live ? "Not streaming" : "Finished"}
            </span>
          </div>
        </div>
        <RunControls runId={runId} status={r.status} />
      </div>

      {r.status === "failed" && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger/10 p-4 text-sm">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          <div><p className="font-medium text-danger">Run failed</p><p className="text-muted-foreground">Reason: {r.error_message ?? r.termination_detail ?? "The run ended with an error."}</p>
            <p className="mt-1 text-xs text-muted-foreground">The application server remains available.</p></div>
        </div>
      )}
      {(r.status === "completed" || r.status === "stopped") && r.termination_detail && (
        <p className="rounded-xl border border-border bg-card/60 p-3 text-sm text-muted-foreground">Finished: {r.termination_detail}</p>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <MetricCard label="States discovered" value={r.states_count} icon={Compass} />
        <MetricCard label="Actions executed" value={r.actions_count} icon={MousePointerClick} />
        <MetricCard label="Bugs found" value={r.bugs_count} icon={Bug} tone={r.bugs_count ? "danger" : "default"} />
        <MetricCard label="Coverage (est.)" value={pct(r.coverage)} icon={Gauge} hint="elements exercised / seen" />
        <MetricCard label="Errors" value={r.errors_count} icon={AlertTriangle} />
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Run sections">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cn("-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors", tab === t ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t}{t === "Bugs" && r.bugs_count ? ` (${r.bugs_count})` : ""}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={tab}>
        {tab === "Overview" && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <BrowserPreview src={preview} url={r.target_url} />
            <Card><CardHeader title="Agent activity" action={<Verbose value={verbose} onChange={setVerbose} />} /><ActivityFeed events={stream.events} verbose={verbose} /></Card>
          </div>
        )}
        {tab === "Timeline" && (
          <Card><CardHeader title={`Event timeline (${stream.events.length} events)`} action={<Verbose value={verbose} onChange={setVerbose} />} />
            <ActivityFeed events={stream.events} verbose={verbose} limit={600} height="h-[560px]" /></Card>
        )}
        {tab === "States" && (
          <Card>
            {graph.isLoading ? <Skeleton className="h-40" /> : !graph.data?.states.length ? <EmptyState icon={Compass} title="No states yet" /> : (
              <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Discovered states</caption>
                <thead className="text-xs text-muted-foreground"><tr className="border-b border-border">{["Title", "URL", "Depth", "Visits", "Bugs", "First discovered"].map((h) => <th scope="col" key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
                <tbody>{graph.data.states.map((s) => (
                  <tr key={s.id} className="border-b border-border/60"><td className="px-4 py-2 font-medium">{s.title || "Untitled"}</td><td className="max-w-[260px] truncate px-4 py-2 font-mono text-xs text-muted-foreground" title={s.url}>{pathOf(s.url)}</td>
                    <td className="px-4 py-2 tabular-nums">{s.depth}</td><td className="px-4 py-2 tabular-nums">{s.visit_count}</td><td className="px-4 py-2 tabular-nums">{s.bug_count}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">{formatDateTime(s.created_at)}</td></tr>))}</tbody></table></div>)}
          </Card>
        )}
        {tab === "Graph" && (
          <Card className="h-[680px] overflow-hidden">
            {graph.isLoading ? <Skeleton className="h-full" /> : graph.error ? <ErrorState error={graph.error} onRetry={graph.refetch} />
              : !graph.data?.states.length ? <EmptyState icon={Compass} title="No states yet" hint="The graph builds in real time as the agent discovers pages." />
              : <ExplorationGraph graph={graph.data} bugs={bugs.data ?? []} />}
          </Card>
        )}
        {tab === "Bugs" && (bugs.isLoading ? <Skeleton className="h-40" /> : bugs.error ? <ErrorState error={bugs.error} onRetry={bugs.refetch} /> : <BugList bugs={bugs.data ?? []} />)}
        {tab === "Screenshots" && (
          shots.length === 0 ? <Card><EmptyState icon={Compass} title="No screenshots yet" hint="Screenshots are captured for each discovered state and bug." /></Card> : (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {shots.map((s) => <li key={s.key} className="glass overflow-hidden"><ScreenshotPreview src={s.url} alt={s.label} caption={s.label} /><p className="truncate p-2 text-xs text-muted-foreground" title={s.label}>{s.label}</p></li>)}
            </ul>)
        )}
        {tab === "Metrics" && <EvaluationPanel runId={runId} live={live} />}
      </div>
      <p className="text-xs text-muted-foreground">Project: <Link className="text-primary hover:underline" to={`/projects/${r.project_id}`}>open project</Link></p>
    </div>
  );
}
