"""Rule-based severity with an explainable rationale.

The critic (rules + Gemini) proposes a severity; these rules set a floor when hard evidence
exists and bump user-critical flows, so severity is never arbitrary. The returned reason
is stored with the bug and shown in the UI.
"""
from __future__ import annotations

import re

from app.agent.state import Severity

_ORDER = [Severity.COSMETIC, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
_CRITICAL_FLOW = re.compile(r"\b(login|log in|sign ?in|sign ?up|register|checkout|payment|pay|card|order|password|auth)\b", re.I)


def _max(a: Severity, b: Severity) -> Severity:
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


def _bump(s: Severity) -> Severity:
    return _ORDER[min(_ORDER.index(s) + 1, len(_ORDER) - 1)]


def assess_severity(
    proposed: Severity, *, category: str, evidence: list[str], text: str = "", reproduced: bool = False,
) -> tuple[Severity, str]:
    """Return (severity, human-readable reason)."""
    sev, reasons = proposed, [f"Initial assessment: {proposed.value}."]
    joined = " ".join(evidence).lower()
    if "uncaught exception" in joined:
        if _ORDER.index(sev) < _ORDER.index(Severity.HIGH):
            sev = _max(sev, Severity.HIGH)
            reasons.append("Raised to high: uncaught JavaScript exception observed.")
    if re.search(r"server error 5\d\d", joined):
        if _ORDER.index(sev) < _ORDER.index(Severity.HIGH):
            sev = _max(sev, Severity.HIGH)
            reasons.append("Raised to high: server responded with a 5xx error.")
    if "blank" in joined and "page" in joined:
        sev = _max(sev, Severity.HIGH)
        reasons.append("Raised to high: page rendered blank.")
    if _CRITICAL_FLOW.search(text or "") and sev in (Severity.MEDIUM, Severity.HIGH):
        bumped = _bump(sev)
        if bumped != sev:
            sev = bumped
            reasons.append(f"Raised to {sev.value}: affects an authentication/checkout/payment flow.")
    if category in ("console_error",) and sev in (Severity.HIGH, Severity.CRITICAL) and "uncaught" not in joined:
        sev = Severity.MEDIUM
        reasons.append("Capped at medium: console message without a user-visible failure.")
    if reproduced:
        reasons.append("Reproduced on retry.")
    return sev, " ".join(reasons)
