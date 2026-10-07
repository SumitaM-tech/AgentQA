/** Tiny dependency-free SVG charts (no chart library, keeps the bundle small for a low-end laptop). */
import { cn } from "@/lib/utils";

export function BarChart({ data, height = 120, label }: { data: { label: string; value: number }[]; height?: number; label: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const w = 100 / Math.max(1, data.length);
  return (
    <figure>
      <svg viewBox={`0 0 100 ${height / 4}`} preserveAspectRatio="none" role="img" aria-label={label} className="w-full" style={{ height }}>
        {data.map((d, i) => {
          const h = (d.value / max) * (height / 4 - 2);
          return (
            <rect key={i} x={i * w + w * 0.15} y={height / 4 - h} width={w * 0.7} height={Math.max(h, d.value ? 0.6 : 0.2)} rx={0.6} className="fill-primary/70">
              <title>{`${d.label}: ${d.value}`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{data[0]?.label}</span><span>{data[data.length - 1]?.label}</span>
      </figcaption>
    </figure>
  );
}

export function StackedBar({ parts, label }: { parts: { label: string; value: number; className: string }[]; label: string }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${label}: ${parts.map((p) => `${p.label} ${p.value}`).join(", ")}`}>
        {total > 0 && parts.filter((p) => p.value > 0).map((p) => <div key={p.label} className={p.className} style={{ width: `${(p.value / total) * 100}%` }} title={`${p.label}: ${p.value}`} />)}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center justify-between">
            <span className="flex items-center gap-2"><span className={cn("h-2 w-2 rounded-sm", p.className)} aria-hidden />{p.label}</span>
            <span className="tabular-nums text-muted-foreground">{p.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function GroupedBars({ data, label }: { data: { label: string; a: number; b: number; c: number }[]; label: string }) {
  const max = Math.max(1, ...data.flatMap((d) => [d.a, d.b, d.c]));
  return (
    <div role="img" aria-label={label} className="space-y-2">
      {data.map((d, i) => (
        <div key={i} className="grid grid-cols-[72px_1fr] items-center gap-2 text-[11px]">
          <span className="truncate text-muted-foreground" title={d.label}>{d.label}</span>
          <div className="space-y-0.5" title={`states ${d.a} · actions ${d.b} · bugs ${d.c}`}>
            <div className="h-1.5 rounded bg-cyan-500/70" style={{ width: `${(d.a / max) * 100}%` }} />
            <div className="h-1.5 rounded bg-primary/60" style={{ width: `${(d.b / max) * 100}%` }} />
            <div className="h-1.5 rounded bg-red-500/70" style={{ width: `${(d.c / max) * 100}%` }} />
          </div>
        </div>
      ))}
      <div className="flex gap-4 pt-1 text-[10px] text-muted-foreground">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-cyan-500/70" />states</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-primary/60" />actions</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-red-500/70" />bugs</span>
      </div>
    </div>
  );
}
