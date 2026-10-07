import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useEvaluation } from "@/hooks/useApi";
import { formatDuration, pct } from "@/lib/utils";

const na = "—";

function Row({ label, value, estimated, hint }: { label: string; value: string | number; estimated?: boolean; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
      <span className="text-muted-foreground" title={hint}>{label}{estimated && <span className="ml-1.5 rounded border border-amber-500/40 px-1 text-[10px] uppercase text-amber-700 dark:text-amber-300">estimated</span>}</span>
      <span className="font-mono tabular-nums">{value}</span>
    </div>
  );
}

export function EvaluationPanel({ runId, live }: { runId: string; live: boolean }) {
  const { data: e, isLoading, error, refetch } = useEvaluation(runId, live);
  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !e) return <ErrorState error={error} onRetry={refetch} />;
  const ratio = (v: number | null) => (v == null ? na : pct(v));
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader title="Exploration" />
        <div className="divide-y divide-border">
          <Row label="States explored" value={e.states_explored} />
          <Row label="Transitions" value={e.transitions} />
          <Row label="Pages tested" value={e.pages_tested} />
          <Row label="Interactive elements tested" value={`${e.interactive_elements_tested} / ${e.interactive_elements_seen} seen`} />
          <Row label="Exploration coverage" value={ratio(e.exploration_coverage)} estimated hint="Tested elements ÷ interactive elements observed. Not a share of the whole application." />
          <Row label="Action efficiency" value={ratio(e.action_efficiency)} hint="Useful actions ÷ total actions (an action is useful if it changed state or surfaced a finding)." />
        </div>
      </Card>
      <Card>
        <CardHeader title="Bug detection" />
        <div className="divide-y divide-border">
          <Row label="Candidates investigated" value={e.candidates} />
          <Row label="Reported bugs" value={e.bugs_reported} />
          <Row label="Verified bugs" value={e.bugs_verified} />
          <Row label="Unverified bugs" value={e.bugs_unverified} />
          <Row label="False positives (discarded)" value={e.false_positives} hint="Candidates that could not be reproduced and were not reported." />
          <Row label="Bug verification rate" value={ratio(e.bug_verification_rate)} />
          <Row label="Time to first verified bug" value={e.time_to_first_bug_seconds == null ? na : formatDuration(e.time_to_first_bug_seconds)} />
        </div>
      </Card>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground lg:col-span-2">
        {e.notes.map((n) => <li key={n}>{n}</li>)}
      </ul>
    </div>
  );
}
