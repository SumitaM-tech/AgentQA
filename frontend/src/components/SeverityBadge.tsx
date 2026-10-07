import { AlertOctagon, AlertTriangle, Info, Minus, Sparkles } from "lucide-react";

import { SEVERITY_STYLES } from "@/lib/severity";
import { cn } from "@/lib/utils";
import type { Severity } from "@/types";

// Icon + text label, so severity is never communicated by colour alone.
const ICONS: Record<Severity, typeof Info> = { critical: AlertOctagon, high: AlertTriangle, medium: Info, low: Minus, cosmetic: Sparkles };

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const s = SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.medium;
  const Icon = ICONS[severity] ?? Info;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold", s.badge, className)}>
      <Icon className="h-3 w-3" aria-hidden />
      {s.label}
    </span>
  );
}
