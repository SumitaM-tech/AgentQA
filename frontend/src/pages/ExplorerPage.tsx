import { Compass } from "lucide-react";
import { useEffect, useState } from "react";

import { ExplorationGraph } from "@/components/ExplorationGraph";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/states";
import { useRunBugs, useRunGraph, useRuns } from "@/hooks/useApi";
import { hostOf, formatDateTime } from "@/lib/utils";
import { isActive } from "@/types";

export default function ExplorerPage() {
  const runs = useRuns({ limit: 50 });
  const [runId, setRunId] = useState("");
  useEffect(() => { if (!runId && runs.data?.length) setRunId(runs.data[0].id); }, [runs.data, runId]);
  const selected = runs.data?.find((r) => r.id === runId);
  const bugs = useRunBugs(runId, !!selected && isActive(selected.status));
  const graph = useRunGraph(runId, !!selected && isActive(selected.status));

  return (
    <>
      <PageHeader title="Explorer" subtitle="The application as the agent discovered it"
        actions={runs.data?.length ? (
          <select aria-label="Select run" value={runId} onChange={(e) => setRunId(e.target.value)} className="h-9 rounded-lg border border-border bg-card px-3 text-sm">
            {runs.data.map((r) => <option key={r.id} value={r.id}>{hostOf(r.target_url)} · {formatDateTime(r.created_at)} · {r.states_count} states</option>)}
          </select>
        ) : undefined} />
      <Card className="h-[calc(100vh-13rem)] min-h-[480px] overflow-hidden">
        {runs.isLoading ? <Spinner /> : runs.error ? <ErrorState error={runs.error} onRetry={runs.refetch} />
          : !runs.data?.length ? <EmptyState icon={Compass} title="Nothing explored yet" hint="Start a QA run to build an exploration graph." />
          : graph.isLoading ? <Spinner /> : graph.error ? <ErrorState error={graph.error} onRetry={graph.refetch} />
          : !graph.data?.states.length ? <EmptyState icon={Compass} title="This run has no states" />
          : <ExplorationGraph key={runId} graph={graph.data} bugs={bugs.data ?? []} />}
      </Card>
    </>
  );
}
