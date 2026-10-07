import { AlertTriangle, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./button";

export function Spinner({ label }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, hint, action }: { icon: LucideIcon; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="rounded-full border border-border bg-muted/50 p-3"><Icon className="h-5 w-5 text-muted-foreground" /></div>
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="max-w-sm text-xs text-muted-foreground">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AlertTriangle className="h-6 w-6 text-danger" />
      <p className="max-w-md text-sm text-muted-foreground">{msg}</p>
      {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}
