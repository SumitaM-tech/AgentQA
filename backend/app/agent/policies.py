"""Deterministic policy layer. Every proposed action passes through here before
it can run — regardless of how confident the model is.

Safeguards: invalid targets, actions outside the allowed domain, dangerous
navigation (logout / destructive / payment / download / non-http schemes),
repeated clicks, repeated state exploration, ping-pong and cyclic loops, and
oversized/secret-looking input. Rejections carry a short reason + suggestion that
is fed back to the planner.

Pure functions over (action, observation, memory): no browser, no LLM, unit-testable.
"""
from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.agent.memory import ElementInfo, ExplorationMemory
from app.agent.state import ActionType, AgentAction
from app.browser.actions import host_allowed
from app.perception.models import PageElement, PageObservation
from app.perception.sanitize import redact_secrets


class PolicyCode(str, Enum):
    OK = "ok"
    STEP_BUDGET = "step_budget"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_DISABLED = "target_disabled"
    TARGET_ROLE_MISMATCH = "target_role_mismatch"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    DANGEROUS_NAVIGATION = "dangerous_navigation"
    DANGEROUS_ELEMENT = "dangerous_element"
    REPEATED_ACTION = "repeated_action"
    REPEATED_ELEMENT = "repeated_element"
    STATE_OVEREXPLORED = "state_overexplored"
    LOOP_DETECTED = "loop_detected"
    HISTORY_PINGPONG = "history_pingpong"
    TEXT_TOO_LONG = "text_too_long"
    SECRET_IN_TEXT = "secret_in_text"
    WAIT_LIMIT = "wait_limit"
    SCROLL_LIMIT = "scroll_limit"
    RELOAD_LIMIT = "reload_limit"


class PolicyVerdict(BaseModel):
    allowed: bool = True
    code: PolicyCode = PolicyCode.OK
    message: str = ""
    suggestion: str = ""
    category: str | None = None

    @property
    def feedback(self) -> str:
        return f"{self.message} {self.suggestion}".strip()


ALLOW = PolicyVerdict()

# Categories that are ALWAYS blocked (never configurable): they leave the sandbox.
_ALWAYS_BLOCKED = frozenset({"scheme", "external"})
_BAD_SCHEMES = frozenset({"mailto", "tel", "sms", "javascript", "data", "file", "ftp", "blob", "ws", "wss"})

_DESTRUCTIVE = re.compile(
    r"\b(delete|remove|erase|wipe|destroy|deactivate|terminate|close)\b.{0,20}\b(account|profile|workspace|"
    r"organi[sz]ation|team|project|database|everything|all (data|items|records|users))\b"
    r"|\bdelete all\b|\bfactory reset\b|\bpermanently (delete|remove)\b|\b(reset|clear) (all )?(data|database)\b",
    re.IGNORECASE,
)
_LOGOUT = re.compile(r"\b(log ?out|sign ?out|log ?off)\b", re.IGNORECASE)
_PAYMENT = re.compile(
    r"\b(pay( now)?|place (your )?order|buy now|confirm (purchase|payment|order)|complete (purchase|order)|"
    r"submit payment|donate)\b",
    re.IGNORECASE,
)
_PATH_LOGOUT = re.compile(r"/(log[-_]?out|sign[-_]?out|log[-_]?off)(/|$)", re.IGNORECASE)
_PATH_DESTRUCTIVE = re.compile(
    r"/(delete[-_]?(account|user|profile|all)?|destroy|deactivate|remove[-_]?account|"
    r"factory[-_]?reset|wipe[-_]?(data|account|all)?)(/|$)", re.IGNORECASE
)
_DOWNLOAD = re.compile(r"\.(exe|msi|dmg|pkg|apk|zip|tar|gz|7z|rar|iso|bat|cmd|sh|jar|scr)$", re.IGNORECASE)

_TYPEABLE = frozenset({"textbox", "searchbox", "spinbutton", "combobox"})


class PolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_domains: list[str] = Field(default_factory=list)  # empty => unrestricted (not recommended)
    allow_subdomains: bool = True
    blocked_categories: frozenset[str] = frozenset({"destructive", "logout", "payment", "download"})
    max_identical_actions_per_state: int = Field(default=2, ge=1)
    max_actions_per_element: int = Field(default=4, ge=1)
    max_state_visits: int = Field(default=8, ge=1)
    max_consecutive_waits: int = Field(default=2, ge=1)
    max_scrolls_per_state: int = Field(default=3, ge=1)
    max_reloads_per_state: int = Field(default=2, ge=1)
    max_opens_of_same_url: int = Field(default=2, ge=1)
    max_text_length: int = Field(default=500, ge=1, le=500)
    max_wait_ms: int = Field(default=10_000, ge=0, le=10_000)
    loop_min_repeats: int = Field(default=3, ge=2)
    loop_max_cycle: int = Field(default=4, ge=2)

    @classmethod
    def for_start_url(cls, start_url: str, **overrides) -> "PolicyConfig":
        host = urlsplit(start_url).hostname or ""
        return cls(allowed_domains=[host] if host else [], **overrides)


def detect_cycle(sequence: list[str], min_repeats: int = 3, max_cycle: int = 4) -> int | None:
    """Length of a cycle (>= 2) that repeats `min_repeats` times at the end of `sequence`
    (e.g. A,B,A,B,A,B -> 2). Consecutive identical states (length 1) are *stagnation*,
    not a loop, and are handled by the FSM's stagnation counter."""
    for length in range(2, max_cycle + 1):
        need = length * min_repeats
        if len(sequence) < need:
            continue
        tail = sequence[-need:]
        unit = tail[:length]
        if len(set(unit)) > 1 and tail == unit * min_repeats:
            return length
    return None


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ domains / urls
    def domain_allowed(self, url: str) -> bool:
        host = urlsplit(url).hostname or ""
        return bool(host) and host_allowed(host, self.config.allowed_domains, self.config.allow_subdomains)

    def url_verdict(self, url: str) -> PolicyVerdict:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return PolicyVerdict(allowed=False, code=PolicyCode.DANGEROUS_NAVIGATION, category="scheme",
                                 message=f"Scheme '{parts.scheme}' is not allowed.", suggestion="Use http(s) URLs only.")
        if not self.domain_allowed(url):
            allowed = ", ".join(self.config.allowed_domains) or "(none)"
            return PolicyVerdict(allowed=False, code=PolicyCode.DOMAIN_NOT_ALLOWED, category="external",
                                 message=f"'{parts.hostname}' is outside the allowed domains ({allowed}).",
                                 suggestion="Stay on the application under test.")
        cat = self._path_category(parts.path)
        if cat and cat in self.config.blocked_categories:
            return PolicyVerdict(allowed=False, code=PolicyCode.DANGEROUS_NAVIGATION, category=cat,
                                 message=f"Navigating to this URL looks {cat} ({parts.path}).",
                                 suggestion="Pick a different, non-destructive path.")
        return ALLOW

    @staticmethod
    def _path_category(path: str) -> str | None:
        if _PATH_LOGOUT.search(path):
            return "logout"
        if _PATH_DESTRUCTIVE.search(path):
            return "destructive"
        if _DOWNLOAD.search(path):
            return "download"
        return None

    # ------------------------------------------------------------------ elements
    def element_category(self, e: ElementInfo, page_url: str) -> str | None:
        """Why clicking this element is unsafe (category), or None if it is fine."""
        cats = self.config.blocked_categories
        if e.href:
            href = e.href.strip()
            scheme = urlsplit(href).scheme.lower()
            if scheme in _BAD_SCHEMES:
                return "scheme"
            if not href.startswith("#"):
                full = urljoin(page_url, href)
                if not self.domain_allowed(full):
                    return "external"
                path_cat = self._path_category(urlsplit(full).path)
                if path_cat and path_cat in cats:
                    return path_cat
        name = e.name or ""
        if "logout" in cats and _LOGOUT.search(name):
            return "logout"
        if "destructive" in cats and _DESTRUCTIVE.search(name):
            return "destructive"
        if "payment" in cats and _PAYMENT.search(name):
            return "payment"
        return None

    def element_blocked(self, e: ElementInfo, page_url: str) -> bool:
        """Filter for exploration memory: never suggest elements the policy would reject."""
        return self.element_category(e, page_url) is not None

    # ------------------------------------------------------------------ main check
    def check(
        self, action: AgentAction, obs: PageObservation, memory: ExplorationMemory, *, step: int, max_steps: int
    ) -> PolicyVerdict:
        t = action.action_type
        if t == ActionType.FINISH:
            return ALLOW
        if step > max_steps:
            return PolicyVerdict(allowed=False, code=PolicyCode.STEP_BUDGET,
                                 message=f"Step budget ({max_steps}) exhausted.", suggestion="Choose FINISH.")

        state_id = obs.state_fingerprint
        cfg = self.config

        # --- targets --------------------------------------------------------
        element: PageElement | None = None
        if action.target:
            element = next((e for e in obs.interactive_elements if e.id == action.target), None)
            if element is None:
                sample = ", ".join(f"{e.id} \"{(e.name or e.text)[:20]}\"" for e in obs.interactive_elements[:5])
                return PolicyVerdict(allowed=False, code=PolicyCode.TARGET_NOT_FOUND,
                                     message=f"Target '{action.target}' is not on the current page.",
                                     suggestion=f"Use an id from ELEMENTS, e.g. {sample}." if sample else
                                     "The page has no interactive elements; use OPEN, BACK, WAIT or FINISH.")
            if t in (ActionType.CLICK, ActionType.TYPE, ActionType.SELECT) and not element.enabled:
                return PolicyVerdict(allowed=False, code=PolicyCode.TARGET_DISABLED,
                                     message=f"'{action.target}' is disabled.",
                                     suggestion="Pick an enabled element (satisfy required fields first).")
            if t == ActionType.TYPE and (element.role not in _TYPEABLE or element.readonly
                                         or element.tag == "select"):
                return PolicyVerdict(allowed=False, code=PolicyCode.TARGET_ROLE_MISMATCH,
                                     message=f"'{action.target}' ({element.role}) cannot be typed into.",
                                     suggestion="TYPE only into textbox/searchbox/spinbutton elements.")
            if t == ActionType.SELECT and element.tag != "select":
                return PolicyVerdict(allowed=False, code=PolicyCode.TARGET_ROLE_MISMATCH,
                                     message=f"'{action.target}' ({element.role}) is not a <select>.",
                                     suggestion="Use CLICK for custom dropdowns.")

        # --- input hygiene --------------------------------------------------
        if t == ActionType.TYPE:
            text = action.arguments.text or ""
            if len(text) > cfg.max_text_length:
                return PolicyVerdict(allowed=False, code=PolicyCode.TEXT_TOO_LONG,
                                     message=f"Text exceeds {cfg.max_text_length} characters.",
                                     suggestion="Use a shorter value.")
            if redact_secrets(text) != text:
                return PolicyVerdict(allowed=False, code=PolicyCode.SECRET_IN_TEXT,
                                     message="Text looks like a real secret/token/card number.",
                                     suggestion="Use obviously fake test data.")

        # --- navigation safety ---------------------------------------------
        if t == ActionType.OPEN:
            v = self.url_verdict(action.arguments.url or "")
            if not v.allowed:
                return v
            if memory.element_action_count("OPEN", action.arguments.url or "") >= cfg.max_opens_of_same_url:
                return PolicyVerdict(allowed=False, code=PolicyCode.REPEATED_ACTION,
                                     message="This URL has already been opened repeatedly.",
                                     suggestion="Explore an untried element instead.")
        if t in (ActionType.CLICK, ActionType.PRESS) and element is not None:
            if t == ActionType.CLICK or (action.arguments.key or "") in ("Enter", "Space"):
                info = ElementInfo.from_element(element)
                cat = self.element_category(info, obs.url)
                if cat in ("external", "scheme"):
                    return PolicyVerdict(allowed=False, code=PolicyCode.DOMAIN_NOT_ALLOWED, category=cat,
                                         message=f"'{action.target}' leads outside the allowed domain or to a non-web scheme.",
                                         suggestion="Stay on the application under test.")
                if cat:
                    return PolicyVerdict(allowed=False, code=PolicyCode.DANGEROUS_ELEMENT, category=cat,
                                         message=f"'{action.target}' (\"{info.name[:30]}\") is a {cat} action.",
                                         suggestion="Pick a non-destructive element.")

        # --- repetition, loops, over-exploration -----------------------------
        key = action.key()
        if memory.tried_count(state_id, key) >= cfg.max_identical_actions_per_state:
            return PolicyVerdict(allowed=False, code=PolicyCode.REPEATED_ACTION,
                                 message="This exact action was already tried in this state.",
                                 suggestion="Try a different element or different input.")
        if action.target and t in (ActionType.CLICK, ActionType.SELECT, ActionType.PRESS):
            if memory.element_action_count(t, action.target) >= cfg.max_actions_per_element:
                return PolicyVerdict(allowed=False, code=PolicyCode.REPEATED_ELEMENT,
                                     message=f"'{action.target}' has already been {t.value}-ed {cfg.max_actions_per_element} times.",
                                     suggestion="Move on to a different element.")
        if action.target and t == ActionType.TYPE:
            if memory.element_action_count(t, action.target) >= cfg.max_actions_per_element + 2:
                return PolicyVerdict(allowed=False, code=PolicyCode.REPEATED_ELEMENT,
                                     message=f"'{action.target}' has received enough input variations.",
                                     suggestion="Test a different field.")

        if t == ActionType.WAIT:
            if (action.arguments.milliseconds or 0) > cfg.max_wait_ms:
                return PolicyVerdict(allowed=False, code=PolicyCode.WAIT_LIMIT,
                                     message=f"WAIT is limited to {cfg.max_wait_ms} ms.", suggestion="Wait less.")
            tail = memory.action_sequence[-cfg.max_consecutive_waits:]
            if len(tail) == cfg.max_consecutive_waits and all(k.startswith("WAIT:") for k in tail):
                return PolicyVerdict(allowed=False, code=PolicyCode.WAIT_LIMIT,
                                     message="Too many consecutive WAITs.", suggestion="Act on the page instead.")
        if t == ActionType.SCROLL and memory.type_count(state_id, t) >= cfg.max_scrolls_per_state:
            return PolicyVerdict(allowed=False, code=PolicyCode.SCROLL_LIMIT,
                                 message="Already scrolled enough in this state.",
                                 suggestion="Interact with an element or navigate elsewhere.")
        if t == ActionType.RELOAD and memory.type_count(state_id, t) >= cfg.max_reloads_per_state:
            return PolicyVerdict(allowed=False, code=PolicyCode.RELOAD_LIMIT,
                                 message="Already reloaded this state enough.", suggestion="Try something else.")
        if t == ActionType.SCREENSHOT and memory.type_count(state_id, t) >= 1:
            return PolicyVerdict(allowed=False, code=PolicyCode.RELOAD_LIMIT,
                                 message="A screenshot of this state was already taken.",
                                 suggestion="Interact with the page instead.")
        if t in (ActionType.BACK, ActionType.FORWARD):
            last = [k.split(":", 1)[0] for k in memory.action_sequence[-2:]]
            opposite = "FORWARD" if t == ActionType.BACK else "BACK"
            if last and last[-1] == opposite:
                return PolicyVerdict(allowed=False, code=PolicyCode.HISTORY_PINGPONG,
                                     message=f"{t.value} right after {opposite} just undoes it.",
                                     suggestion="Explore a new element instead.")
            if len(last) == 2 and all(x == t.value for x in last):
                return PolicyVerdict(allowed=False, code=PolicyCode.REPEATED_ACTION,
                                     message=f"Repeated {t.value} without exploring.",
                                     suggestion="Interact with the page first.")

        revisit_cap = memory.visits(state_id) >= cfg.max_state_visits
        if revisit_cap and t != ActionType.OPEN and (action.target is None or memory.is_tried(state_id, action.target)):
            return PolicyVerdict(allowed=False, code=PolicyCode.STATE_OVEREXPLORED,
                                 message=f"This state was visited {memory.visits(state_id)} times already.",
                                 suggestion="OPEN an unexplored URL from UNEXPLORED TRANSITIONS or FINISH.")

        cycle = detect_cycle(memory.state_sequence, cfg.loop_min_repeats, cfg.loop_max_cycle)
        if cycle and memory.tried_count(state_id, key) >= 1:
            return PolicyVerdict(allowed=False, code=PolicyCode.LOOP_DETECTED,
                                 message=f"The agent is cycling through {cycle} states.",
                                 suggestion="Choose an element that was never tried, or FINISH.")
        return ALLOW

    # ------------------------------------------------------------------ hints
    def hints(self, memory: ExplorationMemory, obs: PageObservation, step: int, max_steps: int) -> list[str]:
        out: list[str] = []
        cycle = detect_cycle(memory.state_sequence, self.config.loop_min_repeats, self.config.loop_max_cycle)
        if cycle:
            out.append(f"You are cycling through {cycle} states; take an action you have never tried or OPEN a new area.")
        if memory.exhausted(obs.state_fingerprint, self.element_blocked):
            out.append("Every element in this state has been tried; navigate to another known state or FINISH.")
        if max_steps - step < max(2, max_steps // 5):
            out.append("Few steps remain: prioritize the highest-value untested flows, then FINISH.")
        return out
