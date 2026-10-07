from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AITestMode(str, Enum):
    TEXT = "text"                # plain text response
    STRUCTURED = "structured"    # AgentDecision via response_schema
    TOOL = "tool"                # AgentDecision via forced function call
    AGENT_DECISION = "agent_decision"  # reasoning-engine AgentAction schema (agent.state)


class AITestResponse(BaseModel):
    model: str
    mode: AITestMode
    used_image: bool
    text: str | None = None
    result: dict[str, Any] | None = None
