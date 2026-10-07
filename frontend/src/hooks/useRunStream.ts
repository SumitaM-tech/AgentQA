import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, assetUrl, runSocketUrl } from "@/api/client";
import type { RunEvent } from "@/types";

export type StreamState = "idle" | "connecting" | "open" | "reconnecting" | "closed";

const REFRESH_TYPES = new Set([
  "state_discovered", "state_revisited", "bug_detected", "bug_verified", "action_completed", "run_completed", "error",
]);

/**
 * Loads a run's persisted events, then (while the run is active) follows the live WebSocket.
 * - Replays from the last seen `seq` after every reconnect, so nothing is missed or duplicated.
 * - Reconnects with exponential backoff; stops once `run_completed` arrives or the run is inactive.
 */
export function useRunStream(runId: string, live: boolean) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<StreamState>("idle");
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const lastSeq = useRef(0);
  const timer = useRef<number>();
  const debounce = useRef<number>();

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let done = false;
    lastSeq.current = 0;
    setEvents([]);

    const refresh = () => {
      window.clearTimeout(debounce.current);
      debounce.current = window.setTimeout(() => {
        for (const key of ["run", "graph", "run-bugs", "bugs", "runs", "summary"]) {
          qc.invalidateQueries({ queryKey: [key] });
        }
      }, 400);
    };

    const ingest = (batch: RunEvent[]) => {
      const fresh = batch.filter((e) => e.type !== "ping" && e.seq > lastSeq.current);
      if (!fresh.length) return;
      lastSeq.current = fresh[fresh.length - 1].seq;
      setEvents((prev) => [...prev, ...fresh].slice(-1500));
      for (const e of fresh) {
        const shot = (e.data as { screenshot_url?: string }).screenshot_url;
        if (shot) setScreenshot(assetUrl(shot));
        if (e.type === "run_completed") done = true;
      }
      if (done) { ws?.close(); setState("closed"); }
      if (fresh.some((e) => REFRESH_TYPES.has(e.type))) refresh();
    };

    const connect = () => {
      if (cancelled || done) return;
      setState(attempt === 0 ? "connecting" : "reconnecting");
      ws = new WebSocket(runSocketUrl(runId, lastSeq.current));
      ws.onopen = () => { attempt = 0; setState("open"); };
      ws.onmessage = (m) => {
        try { ingest([JSON.parse(m.data) as RunEvent]); } catch { /* ignore malformed frame */ }
      };
      ws.onclose = () => {
        if (cancelled) return;
        if (done) { setState("closed"); return; }
        attempt += 1;
        setState("reconnecting");
        timer.current = window.setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt));
      };
      ws.onerror = () => ws?.close();
    };

    (async () => {
      try {
        // Persisted history first (covers finished runs and page reloads).
        for (let guard = 0; guard < 10; guard++) {
          const batch = await api.runEvents(runId, lastSeq.current);
          if (cancelled) return;
          ingest(batch);
          if (batch.length < 2000) break;
        }
      } catch { /* the WebSocket replay will fill the gap */ }
      if (cancelled) return;
      if (live && !done) connect();
      else setState("closed");
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(timer.current);
      window.clearTimeout(debounce.current);
      ws?.close();
    };
    // `live` is read once per mount of a run: switching runs remounts via the route key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return { events, state, screenshot };
}
