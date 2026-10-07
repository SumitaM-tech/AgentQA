import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Backend timestamps are naive UTC; treat them as UTC. */
export function parseUtc(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`);
}

export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return "--:--";
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatClock(ts: string): string {
  const d = parseUtc(ts);
  return d ? d.toLocaleTimeString([], { hour12: false }) : "";
}

export function formatDateTime(ts: string | null): string {
  const d = parseUtc(ts);
  return d ? d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}

export function pathOf(url: string): string {
  try { const u = new URL(url); return u.pathname + u.search || "/"; } catch { return url; }
}

export function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}
