"""LEGACY agent contracts (Action, Observation, Verdict, AgentState, ...) used by the first-generation
orchestrator, `app.llm.gemini_client`, persistence and `app.exploration.graph`. The reasoning engine
(`app.agent.state`, `agent.py`, ...) supersedes these; they remain until those callers migrate.


These models are the "interface" between the deterministic execution layer
and Gemini's reasoning layer. Gemini only ever sees/returns these shapes
(as JSON, via function calling) — it never sees raw Playwright objects.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    HOVER = "hover"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    PRESS_KEY = "press_key"
    WAIT = "wait"
    GO_BACK = "go_back"
    ASSERT = "assert"          # a pure verification step, no DOM mutation
    FINISH = "finish"          # agent declares the goal met / exhausted


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    COSMETIC = "cosmetic"


class VerdictOutcome(str, Enum):
    AS_EXPECTED = "as_expected"
    SUSPICIOUS = "suspicious"          # needs verification pass
    CONFIRMED_BUG = "confirmed_bug"
    FALSE_POSITIVE = "false_positive"  # verification cleared it


# ---------------------------------------------------------------------------
# Perception
# ---------------------------------------------------------------------------

class InteractiveElement(BaseModel):
    """One actionable element extracted from the DOM/accessibility tree."""
    element_id: str = Field(description="Stable synthetic id, e.g. data-agentqa-id")
    role: str = Field(description="ARIA role or tag-derived role")
    accessible_name: str = ""
    tag: str
    is_visible: bool
    is_enabled: bool
    bounding_box: Optional[dict[str, float]] = None  # x, y, width, height
    attributes: dict[str, str] = Field(default_factory=dict)


class ConsoleMessage(BaseModel):
    level: str  # "error" | "warning" | "log"
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class NetworkEvent(BaseModel):
    url: str
    method: str
    status: Optional[int] = None
    ok: bool
    resource_type: str
    duration_ms: Optional[float] = None


class Observation(BaseModel):
    """Everything the agent perceived about the app at one point in time.

    Built entirely by deterministic code (`app/perception/`). Gemini
    receives this as input; it never generates one.
    """
    observation_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    url: str
    title: str
    screenshot_path: str = Field(description="Path/URL of the stored PNG artifact")
    dom_snapshot_path: str = Field(description="Path/URL of the stored DOM/AX-tree artifact")
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    console_messages: list[ConsoleMessage] = Field(default_factory=list)
    network_events: list[NetworkEvent] = Field(default_factory=list)
    http_status: Optional[int] = None
    state_fingerprint: str = Field(description="Hash used for graph de-duplication")


# ---------------------------------------------------------------------------
# Action / prediction / verdict (Gemini's outputs)
# ---------------------------------------------------------------------------

class Action(BaseModel):
    """A single next step, as decided by Gemini, to be executed by
    `BrowserTool`."""
    action_type: ActionType
    target_element_id: Optional[str] = Field(
        default=None, description="Must match an InteractiveElement.element_id from the Observation"
    )
    value: Optional[str] = Field(default=None, description="Text to type, option to select, url to navigate to, etc.")
    reasoning: str = Field(description="Gemini's short rationale for choosing this action")


class ExpectedOutcome(BaseModel):
    """Gemini's prediction of what should happen before the action runs."""
    expected_summary: str
    expected_url_change: Optional[str] = None
    expected_new_elements: list[str] = Field(default_factory=list)
    expected_console_clean: bool = True


class Verdict(BaseModel):
    """Result of comparing ExpectedOutcome to the post-action Observation."""
    outcome: VerdictOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    discrepancies: list[str] = Field(default_factory=list)


class BugReport(BaseModel):
    """Structured, evidence-backed bug report generated by Gemini after a
    verification pass."""
    bug_id: UUID = Field(default_factory=uuid4)
    title: str
    severity: BugSeverity
    description: str
    steps_to_reproduce: list[str]
    expected_behavior: str
    actual_behavior: str
    evidence_screenshot_paths: list[str] = Field(default_factory=list)
    evidence_dom_paths: list[str] = Field(default_factory=list)
    related_state_node_id: Optional[UUID] = None
    related_state_edge_id: Optional[UUID] = None
    fix_proposal: Optional[str] = Field(default=None, description="Phase 2: candidate source fix")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Agent state (full context passed to Gemini each turn)
# ---------------------------------------------------------------------------

class StepRecord(BaseModel):
    """Compact history entry — enough for Gemini to avoid repeating itself
    without re-sending full Observations for every past step."""
    step_index: int
    action: Action
    expected: ExpectedOutcome
    verdict: Optional[Verdict] = None
    resulting_state_fingerprint: str


class GraphSummary(BaseModel):
    """Condensed view of the exploration graph so far, used to steer
    Gemini toward unexplored states instead of re-treading old ground."""
    total_states: int
    total_transitions: int
    unexplored_state_ids: list[UUID] = Field(default_factory=list)
    current_state_id: Optional[UUID] = None


class AgentState(BaseModel):
    """The full context object sent to Gemini on every planning call."""
    session_id: UUID
    goal: str
    max_steps: int
    steps_taken: int
    current_observation: Observation
    recent_history: list[StepRecord] = Field(default_factory=list)
    graph_summary: GraphSummary
    credentials_available: bool = False
    extra_context: dict[str, Any] = Field(default_factory=dict)
