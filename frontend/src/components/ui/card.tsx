import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("glass", className)} {...p} />;
}

export function CardHeader({ title, action, className }: { title: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center justify-between gap-3 border-b border-border px-4 py-3", className)}>
      <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
      {action}
    </div>
  );
}
