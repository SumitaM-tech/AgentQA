import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function MetricCard({ label, value, icon: Icon, hint, tone }: {
  label: string; value: string | number; icon: LucideIcon; hint?: string; tone?: "danger" | "success" | "default";
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-muted-foreground">
        <span className="text-xs font-medium">{label}</span>
        <Icon className="h-4 w-4" />
      </div>
      <div className={cn("mt-2 text-2xl font-semibold tabular-nums", tone === "danger" && "text-danger", tone === "success" && "text-success")}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </Card>
  );
}
