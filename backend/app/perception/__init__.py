"""Perception layer: multi-signal page understanding for the QA agent.

    observe_page(page, telemetry) -> PageObservation      (extractor.py)
    to_prompt_text / to_compact_dict / gemini_context      (compact.py)
    ElementResolver / ElementRegistry                      (resolver.py)

The older `observation.py` (agent.legacy_state.Observation) remains only for the
legacy orchestrator and is superseded by this package.
"""
from app.perception.compact import CompactOptions, gemini_context, to_compact_dict, to_prompt_text
from app.perception.extractor import observe_page
from app.perception.models import (
    ObservationLimits,
    PageElement,
    PageObservation,
    SelectorStrategy,
)
from app.perception.resolver import ElementRegistry, ElementResolutionError, ElementResolver

__all__ = [
    "CompactOptions", "ElementRegistry", "ElementResolutionError", "ElementResolver",
    "ObservationLimits", "PageElement", "PageObservation", "SelectorStrategy",
    "gemini_context", "observe_page", "to_compact_dict", "to_prompt_text",
]
