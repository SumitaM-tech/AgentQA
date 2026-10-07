import { cn } from "@/lib/utils";

export const Skeleton = ({ className }: { className?: string }) => (
  <div aria-hidden className={cn("animate-pulse rounded-md bg-muted/70", className)} />
);

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-2 p-4">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  );
}
