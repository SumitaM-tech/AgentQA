import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Loader2, ShieldAlert, Rocket } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useProject } from "@/hooks/useApi";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/form";

function clientUrlError(v: string): string | null {
  if (!v.trim()) return "Enter the website URL to test.";
  try {
    const u = new URL(v.trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return "Only http:// and https:// URLs are supported.";
    if (u.username || u.password) return "Do not put credentials in the URL; use the authentication section.";
    return null;
  } catch {
    return "That doesn't look like a valid URL (e.g. https://example.com).";
  }
}

const PHASES = ["Creating run…", "Launching browser…", "Connecting agent…"];

export default function NewRunPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const projectId = params.get("project") ?? "";
  const project = useProject(projectId);
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(25);
  const [maxRuntime, setMaxRuntime] = useState(10);
  const [showAuth, setShowAuth] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [phase, setPhase] = useState(-1);
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    const p = project.data;
    if (p) { setUrl((u) => u || p.base_url); setGoal((g) => g || p.default_goals[0] || ""); }
  }, [project.data]);

  const localError = url ? clientUrlError(url) : null;

  // Debounced server-side safety check (SSRF rules + warnings) while typing.
  useEffect(() => {
    setWarnings([]); setBlocked(null); setAcknowledged(false);
    if (!url || clientUrlError(url)) return;
    const t = window.setTimeout(async () => {
      try {
        const r = await api.validateTarget(url.trim());
        setBlocked(r.ok ? null : r.error);
        setWarnings(r.warnings);
      } catch { /* backend offline: the submit will surface it */ }
    }, 450);
    return () => window.clearTimeout(t);
  }, [url]);

  const create = useMutation({
    mutationFn: async () => {
      setPhase(0);
      const created = await api.createRun({
        url: url.trim(),
        goal: goal.trim() || "Explore the application and look for bugs.",
        max_steps: maxSteps,
        max_runtime_seconds: maxRuntime * 60,
        project_id: projectId || undefined,
        auth: showAuth && (username || password) ? { username: username || undefined, password: password || undefined } : undefined,
      });
      setPhase(1);
      await api.startRun(created.run_id);
      setPhase(2);
      await new Promise((r) => setTimeout(r, 500));
      return created.run_id;
    },
    onSuccess: (id) => nav(`/runs/${id}`),
    onError: () => setPhase(-1),
  });

  const needsAck = warnings.some((w) => w.includes("local/private"));
  const canSubmit = !!url && !localError && !blocked && (!needsAck || acknowledged) && !create.isPending;

  const submit = (e: FormEvent) => { e.preventDefault(); if (canSubmit) create.mutate(); };
  const err = create.error instanceof ApiError ? create.error.message : create.error ? "Could not start the run." : null;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="New QA run" subtitle={project.data ? `Project: ${project.data.name}` : "Give the agent a website and a goal. It explores, tests and verifies bugs on its own."} />
      <Card className="p-5">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <div>
            <Label htmlFor="url">Target URL</Label>
            <Input id="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com" inputMode="url" autoFocus aria-invalid={!!(localError || blocked)} />
            {(localError || blocked) && <p role="alert" className="mt-1.5 flex items-center gap-1.5 text-xs text-danger"><ShieldAlert className="h-3.5 w-3.5" />{localError ?? blocked}</p>}
            {warnings.map((w) => <p key={w} className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</p>)}
            {needsAck && (
              <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} /> I understand and this is my own local application.</label>
            )}
          </div>
          <div>
            <Label htmlFor="goal">Testing goal</Label>
            {project.data && project.data.default_goals.length > 1 && (
              <div className="mb-2 flex flex-wrap gap-1.5">{project.data.default_goals.map((g) => <button type="button" key={g} onClick={() => setGoal(g)} className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground">{g.slice(0, 40)}</button>)}</div>
            )}
            <Textarea id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Thoroughly test the checkout flow" maxLength={2000} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="steps">Maximum steps</Label>
              <Input id="steps" type="number" min={1} max={200} value={maxSteps} onChange={(e) => setMaxSteps(Math.min(200, Math.max(1, Number(e.target.value) || 1)))} />
            </div>
            <div>
              <Label htmlFor="runtime">Maximum runtime (minutes)</Label>
              <Input id="runtime" type="number" min={1} max={60} value={maxRuntime} onChange={(e) => setMaxRuntime(Math.min(60, Math.max(1, Number(e.target.value) || 1)))} />
            </div>
          </div>
          <div>
            <button type="button" onClick={() => setShowAuth((v) => !v)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" aria-expanded={showAuth}>
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showAuth ? "rotate-180" : ""}`} /> Authentication (optional)
            </button>
            {showAuth && (
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <div><Label htmlFor="user">Test username</Label><Input id="user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" /></div>
                <div><Label htmlFor="pw">Test password</Label><Input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></div>
                <p className="text-[11px] text-muted-foreground sm:col-span-2">Use a dedicated test account. Credentials stay in server memory for this run only, are injected at execution time and are never shown to the AI model or stored.</p>
              </div>
            )}
          </div>
          {err && <p role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">{err}</p>}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={!canSubmit}>
            {create.isPending ? <><Loader2 className="h-4 w-4 animate-spin" /> {PHASES[Math.max(0, phase)]}</> : <><Rocket className="h-4 w-4" /> Start autonomous QA</>}
          </Button>
        </form>
      </Card>
    </div>
  );
}
