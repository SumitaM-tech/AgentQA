import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Download, ShieldQuestion } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { api, downloadBugReport } from "@/api/client";
import { CandidateFix } from "@/components/CandidateFix";
import { CopyButton } from "@/components/CopyButton";
import { ScreenshotPreview } from "@/components/ScreenshotPreview";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { useBug } from "@/hooks/useApi";
import { formatDateTime, pct } from "@/lib/utils";
import type { Bug } from "@/types";

function reportText(b: Bug): string {
  const steps = b.steps_to_reproduce.map((s, i) => `${i + 1}. ${s}`).join("\n");
  return `${b.bug_ref}: ${b.title}\nSeverity: ${b.severity} | Confidence: ${pct(b.confidence)} | Category: ${b.category} | Status: ${b.status}/${b.resolution}\nURL: ${b.url}\nDetected: ${b.created_at}Z\n\nDescription:\n${b.description}\n\nSteps to reproduce:\n${steps}\n\nExpected:\n${b.expected_behavior}\n\nActual:\n${b.actual_behavior}\n\nConsole errors:\n${b.console_errors.join("\n") || "none"}\n\nNetwork errors:\n${b.network_errors.join("\n") || "none"}`;
}

const Mono = ({ lines }: { lines: string[] }) => lines.length
  ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-background/70 p-3 font-mono text-xs">{lines.join("\n")}</pre>
  : <p className="text-xs text-muted-foreground">None captured.</p>;

const Section = ({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) => (
  <Card><CardHeader title={title} action={action} /><div className="space-y-2 p-4 text-sm">{children}</div></Card>
);

export default function BugDetailPage() {
  const { bugId = "" } = useParams();
  const { data: b, isLoading, error, refetch } = useBug(bugId);
  const qc = useQueryClient();
  const { toast } = useToast();
  const toggle = useMutation({
    mutationFn: (r: "open" | "resolved") => api.setBugResolution(bugId, r),
    onSuccess: (nb) => { qc.setQueryData(["bug", bugId], nb); qc.invalidateQueries({ queryKey: ["bugs"] }); qc.invalidateQueries({ queryKey: ["bug-stats"] }); toast(nb.resolution === "resolved" ? "Marked as resolved" : "Reopened", "success"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const exp = async (f: "json" | "md") => { try { await downloadBugReport(bugId, f, b?.bug_ref.toLowerCase() ?? "bug"); } catch (e) { toast((e as Error).message, "error"); } };

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-64" /></div>;
  if (error || !b) return <ErrorState error={error} onRetry={refetch} />;
  const v = b.verification ?? {};

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <Link to="/bugs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" aria-hidden /> All bugs</Link>
      <div className="glass space-y-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <p className="flex items-center gap-1 font-mono text-xs text-muted-foreground">{b.bug_ref}<CopyButton text={b.id} label="bug ID" /></p>
            <h1 className="text-xl font-semibold leading-snug">{b.title}</h1>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <SeverityBadge severity={b.severity} />
              <span className="rounded-md border border-border px-2 py-0.5">Confidence {pct(b.confidence)}</span>
              <span className="rounded-md border border-border px-2 py-0.5 capitalize">{b.category.replace("_", " ")}</span>
              {b.status === "verified"
                ? <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden />Verified</span>
                : <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300"><ShieldQuestion className="h-3.5 w-3.5" aria-hidden />Unverified</span>}
              <span className="rounded-md border border-border px-2 py-0.5">{b.resolution === "resolved" ? "Resolved" : "Open"}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => toggle.mutate(b.resolution === "open" ? "resolved" : "open")} disabled={toggle.isPending}>{b.resolution === "open" ? "Mark resolved" : "Reopen"}</Button>
            <Button onClick={() => exp("json")}><Download className="h-4 w-4" aria-hidden /> Export JSON</Button>
            <Button onClick={() => exp("md")}><Download className="h-4 w-4" aria-hidden /> Export Markdown</Button>
            <span className="flex items-center text-xs text-muted-foreground">Copy report<CopyButton text={reportText(b)} label="full bug report" /></span>
          </div>
        </div>
        <p className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground"><span className="break-all">{b.url}</span><CopyButton text={b.url} label="URL" /><span>Detected {formatDateTime(b.created_at)}</span></p>
        {b.seen_before_count > 0 && <p className="text-xs text-amber-700 dark:text-amber-300">Also found in {b.seen_before_count} earlier run(s) of this project.</p>}
      </div>

      <Section title="Description"><p>{b.description}</p></Section>
      <Section title="Steps to reproduce" action={<CopyButton text={b.steps_to_reproduce.map((s, i) => `${i + 1}. ${s}`).join("\n")} label="reproduction steps" />}>
        <ol className="list-decimal space-y-0.5 pl-5">{b.steps_to_reproduce.map((s, i) => <li key={i}>{s}</li>)}</ol>
      </Section>
      <div className="grid gap-5 md:grid-cols-2">
        <Section title="Expected result"><p>{b.expected_behavior}</p></Section>
        <Section title="Actual result"><p>{b.actual_behavior}</p></Section>
      </div>
      <Section title="Severity rationale"><p className="text-muted-foreground">{b.severity_reason || "—"}</p></Section>
      <Section title="Verification">
        <p>{v.reproduced ? "Reproduced on re-check." : "Not reproduced on re-check (reported with reduced confidence)."} Attempts: {v.attempts ?? 0}.</p>
        <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">{(v.notes ?? []).map((n, i) => <li key={i}>{n}</li>)}</ul>
      </Section>
      <Section title="Evidence">
        <ScreenshotPreview src={b.screenshot_url} alt={`Screenshot when ${b.bug_ref} was detected`} caption={`${b.bug_ref} screenshot`} className="max-w-xl" />
        {b.evidence.length > 0 && <><h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signals</h3><Mono lines={b.evidence} /></>}
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Console errors</h3><Mono lines={b.console_errors} />
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Network errors</h3><Mono lines={b.network_errors} />
      </Section>
      <Section title="Context">
        <dl className="grid gap-2 text-xs sm:grid-cols-[160px_1fr]">
          <dt className="text-muted-foreground">Application state</dt><dd className="font-mono">{b.state_key ? b.state_key.slice(0, 16) : "—"}</dd>
          <dt className="text-muted-foreground">Agent action</dt><dd>{b.steps_to_reproduce[b.steps_to_reproduce.length - 1] ?? "—"}</dd>
          <dt className="text-muted-foreground">Related exploration state</dt><dd>{b.related_state_id ? <Link className="text-primary hover:underline" to={`/runs/${b.test_run_id}`}>Open the run’s graph</Link> : "—"}</dd>
          <dt className="text-muted-foreground">Run</dt><dd><Link className="text-primary hover:underline" to={`/runs/${b.test_run_id}`}>{b.test_run_id.slice(0, 8)}</Link></dd>
        </dl>
      </Section>
      <CandidateFix bugId={b.id} />
    </div>
  );
}
