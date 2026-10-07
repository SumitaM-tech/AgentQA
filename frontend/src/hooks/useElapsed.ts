import { useEffect, useState } from "react";

import { parseUtc } from "@/lib/utils";

/** Seconds since `startedAt`, ticking each second while `running`; frozen at `finalSeconds` afterwards. */
export function useElapsed(startedAt: string | null, running: boolean, finalSeconds: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);
  const start = parseUtc(startedAt);
  if (!start) return null;
  if (!running && finalSeconds != null) return finalSeconds;
  return Math.max(0, (now - start.getTime()) / 1000);
}
