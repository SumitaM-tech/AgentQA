"""Gemini function-calling ("tool") schemas.

These are the ONLY three shapes Gemini is allowed to return. Each maps
1:1 to a Pydantic model in `app.agent.legacy_state`, so a successful function
call can be parsed straight into a typed object with no ad hoc parsing.
Gemini never receives raw HTML or executes anything itself — it only
returns one of these structures given an Observation + AgentState.
"""
from __future__ import annotations

# Gemini function declarations, in the google-genai SDK's expected shape.
# Kept as plain dicts (rather than importing genai types here) so this
# module has no SDK dependency and can be unit-tested / diffed easily.

PLAN_ACTION_TOOL = {
    "name": "plan_action",
    "description": (
        "Given the current AgentState (observation + history + graph "
        "summary + QA goal), decide the single next best action to take "
        "and predict what should happen as a result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["click", "fill", "select", "hover", "scroll", "navigate",
                         "press_key", "wait", "go_back", "assert", "finish"],
            },
            "target_element_id": {
                "type": "string",
                "description": "Must match an element_id from the current Observation's interactive_elements.",
            },
            "value": {"type": "string", "description": "Text/option/url payload, if applicable."},
            "reasoning": {"type": "string", "description": "Short rationale for this choice."},
            "expected_summary": {"type": "string"},
            "expected_url_change": {"type": "string"},
            "expected_new_elements": {"type": "array", "items": {"type": "string"}},
            "expected_console_clean": {"type": "boolean"},
        },
        "required": ["action_type", "reasoning", "expected_summary"],
    },
}

COMPARE_OUTCOME_TOOL = {
    "name": "compare_outcome",
    "description": (
        "Given an ExpectedOutcome and the actual post-action Observation, "
        "judge whether behavior matched, is suspicious, or is a confirmed bug."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["as_expected", "suspicious", "confirmed_bug", "false_positive"],
            },
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"},
            "discrepancies": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["outcome", "confidence", "reasoning"],
    },
}

GENERATE_BUG_REPORT_TOOL = {
    "name": "generate_bug_report",
    "description": (
        "Given a confirmed bug's full evidence trail (actions, expected vs "
        "actual observations, verification results), produce a structured "
        "bug report."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low", "cosmetic"],
            },
            "description": {"type": "string"},
            "steps_to_reproduce": {"type": "array", "items": {"type": "string"}},
            "expected_behavior": {"type": "string"},
            "actual_behavior": {"type": "string"},
        },
        "required": [
            "title", "severity", "description",
            "steps_to_reproduce", "expected_behavior", "actual_behavior",
        ],
    },
}

ALL_TOOLS = [PLAN_ACTION_TOOL, COMPARE_OUTCOME_TOOL, GENERATE_BUG_REPORT_TOOL]
