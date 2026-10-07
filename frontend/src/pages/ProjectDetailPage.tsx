import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Play, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { BugList } from "@/components/BugList";
import { PageHeader } from "@/components/PageHeader";
import { RunTable } from "@/components/RunTable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/ui/modal";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useBugs, useProject, useRuns } from "@/hooks/useApi";
import { splitList } from "@/pages/ProjectsPage";

export default function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  const runs = useRuns({ project_id: projectId, limit: 10 });
  const bugs = useBugs({ projectId });
  const nav = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [domains, setDomains] = useState("");
  const [goals, setGoals] = useState("");
  const [confirm, setConfirm] = useState(false);
  const p = project.data;
  useEffect(() => { if (p) { setDomains(p.allowed_domains.join(", ")); setGoals(p.default_goals.join("\n")); } }, [p]);

  const save = useMutation({
    mutationFn: () => api.updateProject(projectId, { allowed_domains: splitList(domains), default_goals: splitList(goals) }),
    onSuccess: () => { toast("Project saved", "success"); qc.invalidateQueries({ queryKey: ["project", projectId] }); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const del = useMutation({
    mutationFn: () => api.deleteProject(projectId),
    onSuccess: () => { toast("Project deleted", "success"); qc.invalidateQueries({ queryKey: ["projects"] }); nav("/projects"); },
    onError: (e: Error) => { toast(e.message, "error"); setConfirm(false); },
  });

  if (project.isLoading) return <Skeleton className="h-64" />;
  if (project.error || !p) return <ErrorState error={project.error} onRetry={project.refetch} />;
  return (
    <div className="space-y-5">
      <Link to="/projects" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" aria-hidden /> Projects</Link>
      <PageHeader title={p.name} subtitle={p.description || p.base_url}
        actions={<div className="flex gap-2"><Link to={`/runs/new?project=${p.id}`}><Button variant="primary"><Play className="h-4 w-4" /> Run QA test</Button></Link>
          <Button variant="danger" onClick={() => setConfirm(true)} aria-label="Delete project"><Trash2 className="h-4 w-4" /></Button></div>} />
      <Card>
        <CardHeader title="Settings" />
        <div className="grid gap-4 p-4 md:grid-cols-2">
          <div><Label htmlFor="d">Allowed domains</Label><Input id="d" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="empty = target host only" />
            <p className="mt-1 text-[11px] text-muted-foreground">The agent can only navigate within these domains (and their subdomains).</p></div>
          <div><Label htmlFor="g">Default QA goals (one per line)</Label><Textarea id="g" value={goals} onChange={(e) => setGoals(e.target.value)} /></div>
          <div className="md:col-span-2"><Button disabled={save.isPending} onClick={() => save.mutate()}>Save changes</Button></div>
        </div>
      </Card>
      <Card><CardHeader title="Previous runs" action={<Link className="text-xs text-primary hover:underline" to="/runs">All runs</Link>} />
        {runs.isLoading ? <Skeleton className="h-24" /> : !runs.data?.length ? <EmptyState icon={Play} title="No runs for this project yet" /> : <RunTable runs={runs.data} />}</Card>
      <div><h2 className="mb-2 text-sm font-semibold">Bugs</h2>{bugs.isLoading ? <Skeleton className="h-24" /> : <BugList bugs={bugs.data ?? []} />}</div>
      <ConfirmDialog open={confirm} danger busy={del.isPending} title="Delete project?" confirmLabel="Delete project"
        message="The project and all of its runs, bugs and memory will be permanently deleted." onCancel={() => setConfirm(false)} onConfirm={() => del.mutate()} />
    </div>
  );
}
