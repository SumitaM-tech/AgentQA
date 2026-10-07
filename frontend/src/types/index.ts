/** TypeScript mirror of the FastAPI response models (backend/app/schemas/runs_api.py). */

export type RunStatus =
  | "queued" | "initializing" | "running" | "paused" | "completed" | "failed" | "stopped";
export const ACTIVE_STATUSES: RunStatus[] = ["queued", "initializing", "running", "paused"];
export const isActive = (s: RunStatus) => ACTIVE_STATUSES.includes(s);

export type Severity = "critical" | "high" | "medium" | "low" | "cosmetic";
export type BugStatus = "verified" | "unverified";

export interface Run {
  id: string;
  project_id: string;
  goal: string;
  target_url: string;
  status: RunStatus;
  max_steps: number;
  max_runtime_seconds: number;
  max_depth: number;
  max_retries: number;
  steps_taken: number;
  states_count: number;
  actions_count: number;
  bugs_count: number;
  errors_count: number;
  coverage: number;
  candidates_count: number;
  discarded_count: number;
  first_bug_at: string | null;
  has_credentials: boolean;
  error_message: string | null;
  termination_reason: string | null;
  termination_detail: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  last_screenshot_url: string | null;
  duration_seconds: number | null;
}

export interface RunCreateRequest {
  url: string;
  goal: string;
  max_steps?: number;
  max_runtime_seconds?: number;
  max_depth?: number;
  max_retries?: number;
  project_id?: string;
  auth?: { username?: string; password?: string };
}
export interface RunCreated { run_id: string; status: RunStatus; warnings: string[] }

export interface Bug {
  id: string;
  test_run_id: string;
  title: string;
  severity: Severity;
  category: string;
  confidence: number;
  status: BugStatus;
  description: string;
  steps_to_reproduce: string[];
  expected_behavior: string;
  actual_behavior: string;
  url: string;
  state_key: string;
  related_state_id: string | null;
  fingerprint: string;
  resolution: "open" | "resolved";
  resolved_at: string | null;
  bug_ref: string;
  severity_reason: string;
  evidence: string[];
  console_errors: string[];
  network_errors: string[];
  verification: { reproduced?: boolean; attempts?: number; confidence?: number; notes?: string[] };
  seen_before_count: number;
  fix_proposal: string | null;
  created_at: string;
  screenshot_url: string | null;
}

export interface UIState {
  id: string;
  test_run_id: string;
  fingerprint: string;
  url: string;
  title: string;
  depth: number;
  visit_count: number;
  discovered_at_step: number;
  visible_text_summary: string;
  interactive_elements: { id: string; role: string; name: string }[];
  created_at: string;
  last_seen_at: string;
  screenshot_url: string | null;
  bug_count: number;
}

export interface UIEdge {
  id: string;
  source_state_id: string;
  target_state_id: string;
  action_type: string;
  action_label: string;
  action_parameters: Record<string, unknown>;
  expected_result: string;
  actual_result: string;
  verdict: string | null;
  target_element_id: string | null;
  step_index: number;
  created_at: string;
}
export interface Graph { states: UIState[]; edges: UIEdge[]; current_state_id: string | null }

export type RunEventType =
  | "run_started" | "page_loaded" | "observation" | "agent_thinking" | "agent_action" | "action_completed"
  | "state_discovered" | "state_revisited" | "bug_detected" | "bug_verified" | "screenshot_created"
  | "error" | "run_completed";

export interface RunEvent {
  seq: number;
  type: RunEventType | "ping";
  message: string;
  data: Record<string, unknown>;
  timestamp: string;
  run_id?: string;
}

export interface TargetCheck { ok: boolean; url: string; error: string | null; warnings: string[] }

export interface Health {
  status: string;
  database: string;
  gemini_configured: boolean;
  gemini_model: string;
  private_networks_allowed: boolean;
  max_concurrent_browsers: number;
  environment: string;
  fix_agent_enabled: boolean;
  allowed_domains: string[];
}

export interface DashboardSummary {
  runs_total: number;
  runs_active: number;
  bugs_total: number;
  bugs_verified: number;
  bugs_by_severity: Partial<Record<Severity, number>>;
  states_total: number;
  status_counts: Partial<Record<RunStatus, number>>;
  avg_run_duration_seconds: number | null;
  runs_by_day: { date: string; runs: number }[];
  recent_activity: { run_id: string; label: string; states: number; actions: number; bugs: number }[];
  recent_runs: Run[];
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  base_url: string;
  allowed_domains: string[];
  default_goals: string[];
  run_count: number;
  bug_count: number;
  created_at: string;
  updated_at: string;
}

export interface Evaluation {
  run_id: string;
  states_explored: number;
  transitions: number;
  pages_tested: number;
  interactive_elements_tested: number;
  interactive_elements_seen: number;
  actions_total: number;
  actions_useful: number;
  action_efficiency: number | null;
  bugs_reported: number;
  bugs_verified: number;
  bugs_unverified: number;
  candidates: number;
  false_positives: number;
  false_positive_rate: number | null;
  bug_verification_rate: number | null;
  time_to_first_bug_seconds: number | null;
  exploration_coverage: number | null;
  exploration_coverage_estimated: boolean;
  notes: string[];
}

export interface BugStats {
  total: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  verified: number;
  unverified: number;
  open: number;
  resolved: number;
  avg_confidence: number | null;
}

export interface CandidateFix {
  summary: string;
  root_cause: string;
  files: string[];
  proposed_changes: { path: string; description: string; before: string; after: string }[];
  diff: string;
  confidence: number;
  verification_plan: string[];
  source_context_provided: boolean;
  requires_human_review: boolean;
}

export interface BackendSettings {
  ai: { model: string; temperature: number; api_key_configured: boolean; max_steps: number; max_runtime_seconds: number; max_depth: number; max_retries: number; fix_agent_enabled: boolean };
  browser: { engine: string; headless: boolean; max_concurrent_browsers: number; max_sessions: number };
  security: { allowed_domains: string[]; private_networks_allowed: boolean; downloads: string };
  retention: { max_artifact_size_mb: number; max_screenshots_per_run: number; run_retention_days: number };
  system: { environment: string };
}

export interface ProjectInput {
  name: string;
  description?: string;
  base_url: string;
  allowed_domains: string[];
  default_goals: string[];
}
