import { Moon, Sun } from "lucide-react";

import { API_URL } from "@/api/client";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useHealth, useSettings } from "@/hooks/useApi";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

const Row = ({ k, v, warn }: { k: string; v: React.ReactNode; warn?: boolean }) => (
  <div className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm"><span className="text-muted-foreground">{k}</span>
    <span className={cn("text-right font-mono text-xs", warn && "font-semibold text-amber-700 dark:text-amber-300")}>{v}</span></div>
);
const Section = ({ title, children }: { title: string; children: React.ReactNode }) => <Card><CardHeader title={title} /><div className="divide-y divide-border">{children}</div></Card>;

export default function SettingsPage() {
  const settings = useSettings();
  const health = useHealth();
  const { theme, setTheme } = useTheme();
  const s = settings.data;
  return (
    <>
      <PageHeader title="Settings" subtitle="Backend values are read-only here: edit backend/.env and restart. Secrets are never shown." />
      <div className="grid max-w-5xl gap-5 lg:grid-cols-2">
        {settings.isLoading ? <Skeleton className="h-64 lg:col-span-2" /> : settings.error || !s ? <div className="lg:col-span-2"><ErrorState error={settings.error} onRetry={settings.refetch} /></div> : (
          <>
            <Section title="AI">
              <Row k="Gemini model" v={s.ai.model} />
              <Row k="API key" v={s.ai.api_key_configured ? "configured" : "missing — fallback explorer only"} warn={!s.ai.api_key_configured} />
              <Row k="Temperature" v={s.ai.temperature} />
              <Row k="Default step limit" v={s.ai.max_steps} />
              <Row k="Default runtime limit" v={`${s.ai.max_runtime_seconds}s`} />
              <Row k="Max depth / retries" v={`${s.ai.max_depth} / ${s.ai.max_retries}`} />
              <Row k="Candidate fixes" v={s.ai.fix_agent_enabled ? "enabled" : "disabled"} />
            </Section>
            <Section title="Browser">
              <Row k="Browser" v={s.browser.engine} />
              <Row k="Headless" v={s.browser.headless ? "yes" : "no"} />
              <Row k="Concurrent runs" v={s.browser.max_concurrent_browsers} />
              <Row k="Max browser sessions" v={s.browser.max_sessions} />
            </Section>
            <Section title="Security">
              <Row k="Allowed domains" v={s.security.allowed_domains.length ? s.security.allowed_domains.join(", ") : "any public domain"} />
              <Row k="Private network blocking" v={s.security.private_networks_allowed ? "OFF (local targets allowed)" : "on"} warn={s.security.private_networks_allowed} />
              <Row k="Downloads" v={s.security.downloads} />
            </Section>
            <Section title="Data retention">
              <Row k="Max screenshots / run" v={s.retention.max_screenshots_per_run} />
              <Row k="Max artifacts / run" v={`${s.retention.max_artifact_size_mb} MB`} />
              <Row k="Run retention" v={s.retention.run_retention_days ? `${s.retention.run_retention_days} days` : "keep forever"} />
            </Section>
          </>
        )}
        <Section title="Appearance">
          <div className="flex gap-2 p-4" role="radiogroup" aria-label="Theme">
            {(["dark", "light"] as const).map((t) => (
              <button key={t} role="radio" aria-checked={theme === t} onClick={() => setTheme(t)}
                className={cn("flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm capitalize", theme === t ? "border-primary/60 bg-primary/15" : "border-border text-muted-foreground hover:text-foreground")}>
                {t === "dark" ? <Moon className="h-4 w-4" aria-hidden /> : <Sun className="h-4 w-4" aria-hidden />}{t} mode
              </button>))}
          </div>
        </Section>
        <Section title="System">
          <Row k="Backend URL" v={API_URL} />
          <Row k="Connection" v={health.isError ? "disconnected" : health.data?.status ?? "…"} warn={health.isError} />
          <Row k="Database" v={health.data?.database ?? "…"} warn={health.data?.database !== "ok" && !!health.data} />
          <Row k="Environment" v={health.data?.environment ?? "…"} />
        </Section>
      </div>
    </>
  );
}
