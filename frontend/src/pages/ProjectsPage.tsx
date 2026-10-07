import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { TableSkeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useProjects } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/utils";

export const splitList = (v: string) => v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);

export default function ProjectsPage() {
  const { data, isLoading, error, refetch } = useProjects();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", url: "", description: "", domains: "", goals: "" });
  const qc = useQueryClient();
  const { toast } = useToast();
  const create = useMutation({
    mutationFn: () => api.createProject({ name: f.name.trim(), description: f.description.trim() || undefined, base_url: f.url.trim(), allowed_domains: splitList(f.domains), default_goals: splitList(f.goals) }),
    onSuccess: () => { toast("Project created", "success"); setOpen(false); setF({ name: "", url: "", description: "", domains: "", goals: "" }); qc.invalidateQueries({ queryKey: ["projects"] }); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((p) => ({ ...p, [k]: e.target.value }));

  return (
    <>
      <PageHeader title="Projects" subtitle="One project per application; runs in a project share long-term memory" actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New project</Button>} />
      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length
          ? <EmptyState icon={FolderKanban} title="No projects yet" hint="Create a project for the app you want to test, or just start a run — one is created automatically." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}>New project</Button>} />
          : <ul className="divide-y divide-border">{data.map((p) => (
              <li key={p.id}><Link to={`/projects/${p.id}`} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-muted/30">
                <div className="min-w-0"><p className="font-medium">{p.name}</p><p className="truncate text-xs text-muted-foreground">{p.base_url}</p></div>
                <div className="flex gap-5 text-xs text-muted-foreground"><span>{p.run_count} runs</span><span>{p.bug_count} bugs</span><span>Created {formatDateTime(p.created_at)}</span></div>
              </Link></li>))}</ul>}
      </Card>
      <Modal open={open} onClose={() => setOpen(false)} title="New project">
        <form onSubmit={submit} className="space-y-4">
          <div><Label htmlFor="pn">Project name</Label><Input id="pn" required value={f.name} onChange={set("name")} /></div>
          <div><Label htmlFor="pu">Target URL</Label><Input id="pu" required type="url" placeholder="https://example.com" value={f.url} onChange={set("url")} /></div>
          <div><Label htmlFor="pd">Description</Label><Textarea id="pd" value={f.description} onChange={set("description")} /></div>
          <div><Label htmlFor="pa">Allowed domains (comma or line separated; empty = target host only)</Label><Input id="pa" placeholder="example.com, api.example.com" value={f.domains} onChange={set("domains")} /></div>
          <div><Label htmlFor="pg">Default QA goals (one per line)</Label><Textarea id="pg" placeholder="Thoroughly test the checkout flow." value={f.goals} onChange={set("goals")} /></div>
          <div className="flex justify-end gap-2"><Button type="button" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" disabled={create.isPending}>Create project</Button></div>
        </form>
      </Modal>
    </>
  );
}
