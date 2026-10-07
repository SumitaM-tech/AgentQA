"""Function-calling declarations, auto-derived from the Pydantic schemas
in `schemas.py` (via `parameters_json_schema`) so they cannot drift."""
from __future__ import annotations

from google.genai import types
from pydantic import BaseModel

from app.llm.schemas import AgentDecision, BugAnalysis, BugReport


def _declaration(name: str, description: str, model: type[BaseModel]) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name, description=description, parameters_json_schema=model.model_json_schema()
    )


RECORD_AGENT_DECISION = _declaration(
    "record_agent_decision", "Record the next QA action and its predicted outcome.", AgentDecision
)
RECORD_BUG_ANALYSIS = _declaration(
    "record_bug_analysis", "Record whether an observed outcome is a bug.", BugAnalysis
)
RECORD_BUG_REPORT = _declaration("record_bug_report", "Record a structured bug report.", BugReport)

ALL_DECLARATIONS = {
    d.name: d for d in (RECORD_AGENT_DECISION, RECORD_BUG_ANALYSIS, RECORD_BUG_REPORT)
}


def tool_for(declaration: types.FunctionDeclaration) -> types.Tool:
    return types.Tool(function_declarations=[declaration])


def forced_tool_config(function_name: str) -> types.ToolConfig:
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=[function_name],
        )
    )
