import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import { CopyButton } from "@/components/CopyButton";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";
import { useHealth } from "@/hooks/useApi";
import { pct } from "@/lib/utils";

/** Optional, human-reviewed fix suggestion. Never edits code: it only renders a proposed diff. */
export function CandidateFix({ bugId }: { bugId: string }) {
  const { data: health } = useHealth();
  const enabled = !!health?.fix_agent_enabled;
  const qc = useQueryClient();
  const { toast } = useToast();
  const [source, setSource] = useState("");
  const saved = useQuery({
    queryKey: ["fix", bugId], enabled,
    queryFn: async () => { try { return await api.getCandidateFix(bugId); } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e; } },
  });
  const gen = useMutation({
    mutationFn: () => api.createCandidateFix(bugId, source),
    onSuccess: (d) => { qc.setQueryData(["fix", bugId], d); toast("Candidate fix generated — review it before using it.", "success"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const fix = saved.data;

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Wrench className="h-4 w-4" aria-hidden />Candidate fix (AI suggestion)</span>} />
      <div className="space-y-4 p-4 text-sm">
        {!enabled ? (
          <p className="text-muted-foreground">Disabled. Set <code className="rounded bg-muted px-1">FIX_AGENT_ENABLED=true</code> in the backend <code className="rounded bg-muted px-1">.env</code> to enable suggestions. The system never modifies your code; it only proposes a diff for review.</p>
        ) : (
          <>
            <div>
              <label htmlFor="src" className="mb-1.5 block text-xs font-medium text-muted-foreground">Relevant source code (optional, pasted by you; secrets are redacted)</label>
              <Textarea id="src" value={source} onChange={(e) => setSource(e.target.value)} maxLength={20000} placeholder="Paste the file or function you suspect. Without it, only a root-cause hypothesis is produced." className="font-mono text-xs" />
              <div className="mt-2 flex items-center gap-3"><Button variant="primary" disabled={gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? "Generating…" : fix ? "Regenerate" : "Generate candidate fix"}</Button>
                <span className="text-xs text-muted-foreground">Uses your Gemini quota. Nothing is applied automatically.</span></div>
            </div>
            {fix && (
              <div className="space-y-4 border-t border-border pt-4">
                <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs">AI-generated and unverified — confidence {pct(fix.confidence)}. Review carefully before applying anything.{!fix.source_context_provided && " No source code was provided, so this is a hypothesis only."}</p>
                <section><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary</h4><p>{fix.summary}</p></section>
                <section><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Potential root cause</h4><p>{fix.root_cause}</p></section>
                {fix.proposed_changes.map((c, i) => (
                  <section key={i} className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Affected file: <span className="font-mono normal-case">{c.path}</span></h4>
                    <p className="text-muted-foreground">{c.description}</p>
                    <div className="grid gap-2 md:grid-cols-2">
                      <div><p className="mb-1 text-xs font-semibold">Before</p><pre className="max-h-48 overflow-auto rounded-lg border border-red-500/30 bg-red-500/5 p-2 font-mono text-xs">{c.before}</pre></div>
                      <div><p className="mb-1 text-xs font-semibold">After</p><pre className="max-h-48 overflow-auto rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2 font-mono text-xs">{c.after}</pre></div>
                    </div>
                  </section>
                ))}
                {fix.diff && (
                  <section><div className="mb-1 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Diff</h4><span className="flex items-center text-xs">Copy diff <CopyButton text={fix.diff} label="diff" /></span></div>
                    <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-background/70 p-3 font-mono text-xs">{fix.diff}</pre></section>
                )}
                <section><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Verification steps</h4>
                  <ol className="list-decimal space-y-0.5 pl-5">{fix.verification_plan.map((v, i) => <li key={i}>{v}</li>)}</ol></section>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
