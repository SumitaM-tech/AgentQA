import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { RunTable } from "@/components/RunTable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/ui/modal";
import { TableSkeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useRuns } from "@/hooks/useApi";
import { useDebounce } from "@/hooks/useDebounce";
import { cn } from "@/lib/utils";
import type { Run } from "@/types";

const FILTERS = ["all", "running", "completed", "failed", "stopped"] as const;
const PAGE = 25;

export default function RunsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [toDelete, setToDelete] = useState<Run | null>(null);
  const q = useDebounce(search.trim(), 300);
  useEffect(() => setPage(0), [q, filter]);
  const { data, isLoading, error, refetch, isFetching } = useRuns({ status: filter === "all" ? undefined : filter, q: q || undefined, limit: PAGE, offset: page * PAGE });
  const qc = useQueryClient();
  const { toast } = useToast();
  const del = useMutation({
    mutationFn: (id: string) => api.deleteRun(id),
    onSuccess: () => { toast("Run deleted", "success"); setToDelete(null); qc.invalidateQueries({ queryKey: ["runs"] }); qc.invalidateQueries({ queryKey: ["summary"] }); },
    onError: (e: Error) => { toast(e.message, "error"); setToDelete(null); },
  });

  return (
    <>
      <PageHeader title="Runs" subtitle="History of every autonomous QA run" actions={<Link to="/runs/new"><Button variant="primary"><Plus className="h-4 w-4" /> New QA Run</Button></Link>} />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden />
          <Input aria-label="Search runs" placeholder="Search runs…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </div>
        <div className="flex gap-1.5" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)} className={cn("rounded-full border px-3 py-1 text-xs capitalize", filter === f ? "border-primary/50 bg-primary/15" : "border-border text-muted-foreground hover:text-foreground")}>{f}</button>
          ))}
        </div>
      </div>
      <Card className={cn(isFetching && !isLoading && "opacity-90")}>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length
          ? <EmptyState icon={Plus} title={q || filter !== "all" ? "No runs match" : "No runs yet"} hint="Runs you start are kept across restarts." />
          : <RunTable runs={data} onDelete={setToDelete} />}
        {(page > 0 || (data?.length ?? 0) === PAGE) && (
          <div className="flex items-center justify-between border-t border-border p-3 text-xs">
            <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <span className="text-muted-foreground">Page {page + 1}</span>
            <Button size="sm" disabled={(data?.length ?? 0) < PAGE} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        )}
      </Card>
      <ConfirmDialog open={!!toDelete} danger busy={del.isPending} title="Delete this run?" confirmLabel="Delete run"
        message="The run, its graph, bugs, events and screenshots will be permanently deleted." onCancel={() => setToDelete(null)} onConfirm={() => toDelete && del.mutate(toDelete.id)} />
    </>
  );
}
