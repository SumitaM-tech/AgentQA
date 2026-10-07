import { Pause, Play, Square } from "lucide-react";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { useRunControls } from "@/hooks/useApi";
import type { RunStatus } from "@/types";

export function RunControls({ runId, status }: { runId: string; status: RunStatus }) {
  const { pause, resume, stop } = useRunControls(runId);
  const [confirm, setConfirm] = useState(false);
  const { toast } = useToast();
  const busy = pause.isPending || resume.isPending || stop.isPending;
  const err = (pause.error ?? resume.error ?? stop.error) as Error | null;
  return (
    <div className="flex items-center gap-2">
      {status === "running" && (
        <Button disabled={busy} onClick={() => pause.mutate()}><Pause className="h-4 w-4" /> Pause</Button>
      )}
      {status === "paused" && (
        <Button variant="primary" disabled={busy} onClick={() => resume.mutate()}><Play className="h-4 w-4" /> Resume</Button>
      )}
      {(status === "running" || status === "paused" || status === "initializing" || status === "queued") && (
        <Button variant="danger" disabled={busy} onClick={() => setConfirm(true)}><Square className="h-4 w-4" /> Stop</Button>
      )}
      {err && <span role="alert" className="text-xs text-danger">{err.message}</span>}
      <ConfirmDialog open={confirm} danger busy={stop.isPending} title="Stop this run?" confirmLabel="Stop run" message="The agent will stop after its current action. Findings and the graph collected so far are kept."
        onCancel={() => setConfirm(false)} onConfirm={() => stop.mutate(undefined, { onSuccess: () => { setConfirm(false); toast("Run stopped", "info"); }, onError: () => setConfirm(false) })} />
    </div>
  );
}
