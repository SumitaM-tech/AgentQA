import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { isActive, type RunStatus } from "@/types";

const active = (s?: RunStatus) => (s ? isActive(s) : false);

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10_000, retry: false });

export const useSummary = () =>
  useQuery({ queryKey: ["summary"], queryFn: api.summary, refetchInterval: 8_000 });

export const useRuns = (p: { status?: string; q?: string; project_id?: string; limit?: number; offset?: number } = {}) =>
  useQuery({ queryKey: ["runs", p], queryFn: () => api.listRuns(p), refetchInterval: 6_000, placeholderData: (prev) => prev });

export const useRun = (id: string) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => api.getRun(id),
    // Live updates arrive over WebSocket; polling is only a safety net while the run is active.
    refetchInterval: (q) => (active(q.state.data?.status) ? 4_000 : false),
  });

export const useRunGraph = (id: string, live: boolean) =>
  useQuery({ queryKey: ["graph", id], queryFn: () => api.runGraph(id), refetchInterval: live ? 6_000 : false });

export const useRunBugs = (id: string, live: boolean) =>
  useQuery({ queryKey: ["run-bugs", id], queryFn: () => api.runBugs(id), refetchInterval: live ? 6_000 : false });

export const useBugs = (p: { runId?: string; projectId?: string; q?: string } = {}) =>
  useQuery({ queryKey: ["bugs", p], queryFn: () => api.listBugs(p), refetchInterval: 10_000, placeholderData: (prev) => prev });
export const useBug = (id: string) => useQuery({ queryKey: ["bug", id], queryFn: () => api.getBug(id) });
export const useBugStats = (projectId?: string) => useQuery({ queryKey: ["bug-stats", projectId], queryFn: () => api.bugStats(projectId), refetchInterval: 10_000 });
export const useEvaluation = (id: string, live: boolean) =>
  useQuery({ queryKey: ["evaluation", id], queryFn: () => api.runEvaluation(id), refetchInterval: live ? 6_000 : false });
export const useProject = (id: string) => useQuery({ queryKey: ["project", id], queryFn: () => api.getProject(id), enabled: !!id });
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: api.settings });

export const useProjects = () => useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

export function useRunControls(id: string) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["run", id] });
    qc.invalidateQueries({ queryKey: ["runs"] });
  };
  const opts = { onSuccess: refresh };
  return {
    pause: useMutation({ mutationFn: () => api.pauseRun(id), ...opts }),
    resume: useMutation({ mutationFn: () => api.resumeRun(id), ...opts }),
    stop: useMutation({ mutationFn: () => api.stopRun(id), ...opts }),
  };
}
