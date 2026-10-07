import type {
  BackendSettings, Bug, BugStats, CandidateFix, DashboardSummary, Evaluation, Graph, Health, Project, ProjectInput, Run, RunCreateRequest,
  RunCreated, RunEvent, UIState, TargetCheck,
} from "@/types";

export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  summary: () => request<DashboardSummary>("/api/dashboard/summary"),
  validateTarget: (url: string) => post<TargetCheck>("/api/targets/validate", { url }),

  createRun: (payload: RunCreateRequest) => post<RunCreated>("/api/runs", payload),
  listRuns: (p: { status?: string; q?: string; project_id?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams({ limit: String(p.limit ?? 25), offset: String(p.offset ?? 0) });
    if (p.status) qs.set("status", p.status);
    if (p.q) qs.set("q", p.q);
    if (p.project_id) qs.set("project_id", p.project_id);
    return request<Run[]>(`/api/runs?${qs}`);
  },
  deleteRun: (id: string) => request<void>(`/api/runs/${id}`, { method: "DELETE" }),
  runEvaluation: (id: string) => request<Evaluation>(`/api/runs/${id}/evaluation`),
  getRun: (id: string) => request<Run>(`/api/runs/${id}`),
  startRun: (id: string) => post<Run>(`/api/runs/${id}/start`),
  stopRun: (id: string) => post<Run>(`/api/runs/${id}/stop`),
  pauseRun: (id: string) => post<Run>(`/api/runs/${id}/pause`),
  resumeRun: (id: string) => post<Run>(`/api/runs/${id}/resume`),
  runStates: (id: string) => request<UIState[]>(`/api/runs/${id}/states`),
  runGraph: (id: string) => request<Graph>(`/api/runs/${id}/graph`),
  runBugs: (id: string) => request<Bug[]>(`/api/runs/${id}/bugs`),
  runEvents: (id: string, after = 0) => request<RunEvent[]>(`/api/runs/${id}/events?after=${after}&limit=2000`),

  listBugs: (p: { runId?: string; projectId?: string; q?: string } = {}) => {
    const qs = new URLSearchParams({ limit: "500" });
    if (p.runId) qs.set("run_id", p.runId);
    if (p.projectId) qs.set("project_id", p.projectId);
    if (p.q) qs.set("q", p.q);
    return request<Bug[]>(`/api/bugs?${qs}`);
  },
  bugStats: (projectId?: string) => request<BugStats>(`/api/bugs/stats${projectId ? `?project_id=${projectId}` : ""}`),
  getBug: (id: string) => request<Bug>(`/api/bugs/${id}`),
  setBugResolution: (id: string, resolution: "open" | "resolved") => request<Bug>(`/api/bugs/${id}`, { method: "PATCH", body: JSON.stringify({ resolution }) }),
  getCandidateFix: (id: string) => request<CandidateFix>(`/api/bugs/${id}/candidate-fix`),
  createCandidateFix: (id: string, sourceContext?: string) => post<CandidateFix>(`/api/bugs/${id}/candidate-fix`, { source_context: sourceContext || null }),

  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (p: ProjectInput) => post<Project>("/api/projects", p),
  updateProject: (id: string, p: Partial<ProjectInput>) => request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  settings: () => request<BackendSettings>("/api/settings"),
};

/** Download a server-generated bug report (json | md) as a file. */
export async function downloadBugReport(id: string, format: "json" | "md", name: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/bugs/${id}/export?format=${format}`);
  if (!res.ok) throw new ApiError(res.status, "Export failed");
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.${format}` });
  a.click();
  URL.revokeObjectURL(url);
}

/** Screenshot URLs from the API are server-relative; make them absolute. */
export const assetUrl = (p: string | null | undefined): string | null => (p ? `${API_URL}${p}` : null);

export function runSocketUrl(runId: string, after: number): string {
  const ws = API_URL.replace(/^http/, "ws");
  return `${ws}/ws/runs/${runId}?after=${after}`;
}
