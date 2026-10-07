"""Candidate-fix generation (OPTIONAL, disabled unless FIX_AGENT_ENABLED=true).

Safety contract:
  * It only PROPOSES changes as text. It never writes files, runs commands or reads the filesystem.
  * Source code is supplied by the human in the request (pasted snippet, size-capped, secrets redacted).
  * The model returns structured data only; the unified diff is built here with difflib from before/after text.
  * Output is advisory and always labelled as needing human review.
"""
from __future__ import annotations

import difflib
import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.service import GeminiService
from app.models.bug import Bug
from app.perception.sanitize import redact_secrets

logger = get_logger(__name__)
MAX_CONTEXT_CHARS = 20_000


class FixFileChange(BaseModel):
    path: str = Field(max_length=300, description="File path as given in the provided source context; never invent one")
    description: str = Field(max_length=500)
    before: str = Field(max_length=4000, description="Exact existing lines being replaced (from the provided context)")
    after: str = Field(max_length=4000, description="Replacement lines")


class _ModelOut(BaseModel):
    summary: str = Field(max_length=500)
    root_cause: str = Field(max_length=1200, description="Most likely cause, phrased as a hypothesis unless the source proves it")
    changes: list[FixFileChange] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)
    verification_plan: list[str] = Field(default_factory=list, max_length=8)


SYSTEM = (
    "You are a senior engineer reviewing an automatically detected web-app bug. Propose a candidate fix for HUMAN review. "
    "Rules: use only the evidence and source context provided; if no source context is given, return NO file changes, "
    "state the likely root cause as a hypothesis and lower the confidence (<= 0.4). Never invent file paths, APIs or code "
    "that is not in the context. Never suggest running commands. 'before' must quote the provided source exactly."
)


def build_diff(changes: list[FixFileChange]) -> str:
    parts = []
    for c in changes:
        parts.extend(difflib.unified_diff(c.before.splitlines(), c.after.splitlines(),
                                          fromfile=f"a/{c.path}", tofile=f"b/{c.path}", lineterm=""))
    return "\n".join(parts)


def _prompt(bug: Bug, source: str | None) -> str:
    evidence = {
        "title": bug.title, "category": bug.category, "severity": bug.severity, "url": bug.url,
        "description": bug.description, "steps_to_reproduce": bug.steps_to_reproduce,
        "expected": bug.expected_behavior, "actual": bug.actual_behavior, "evidence": bug.evidence[:10],
        "console_errors": bug.console_errors[:10], "network_errors": bug.network_errors[:10],
        "verification": bug.verification,
    }
    text = redact_secrets(json.dumps(evidence, default=str)[:12_000])
    ctx = redact_secrets(source[:MAX_CONTEXT_CHARS]) if source else "(none provided)"
    return f"BUG EVIDENCE (JSON):\n{text}\n\nSOURCE CONTEXT PROVIDED BY THE USER:\n{ctx}"


async def generate_candidate_fix(bug: Bug, source_context: str | None, service: GeminiService | None = None) -> dict[str, Any]:
    if not get_settings().fix_agent_enabled:
        raise PermissionError("Candidate fixes are disabled. Set FIX_AGENT_ENABLED=true to enable them.")
    svc = service or GeminiService()
    out = await svc.generate_structured(_prompt(bug, source_context), _ModelOut, system_instruction=SYSTEM, max_output_tokens=2048)
    changes = out.changes if source_context else []
    confidence = out.confidence if source_context else min(out.confidence, 0.4)
    return {
        "summary": out.summary, "root_cause": out.root_cause,
        "files": sorted({c.path for c in changes}),
        "proposed_changes": [c.model_dump() for c in changes],
        "diff": build_diff(changes), "confidence": round(confidence, 2),
        "verification_plan": out.verification_plan,
        "source_context_provided": bool(source_context),
        "requires_human_review": True,
    }
