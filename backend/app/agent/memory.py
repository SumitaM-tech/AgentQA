"""Exploration memory: known UI states, what has been tried where, and the
sequences used for loop detection. Pure bookkeeping — no browser, no LLM."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from app.agent.state import (
    ActionType,
    AgentAction,
    KnownState,
    UnexploredTransition,
)
from app.perception.models import PageElement, PageObservation

_TYPEABLE_ROLES = frozenset({"textbox", "searchbox", "spinbutton"})
_SELECT_ROLES = frozenset({"combobox", "listbox"})
_NAV_ROLES = frozenset({"link"})
_ACTION_ROLES = frozenset({"button", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "switch",
                           "option", "treeitem", "clickable"})


@dataclass(frozen=True)
class ElementInfo:
    id: str
    role: str
    name: str
    tag: str
    input_type: str | None
    href: str | None
    enabled: bool

    @classmethod
    def from_element(cls, e: PageElement) -> "ElementInfo":
        return cls(e.id, e.role, e.name or e.text or e.aria_label or "", e.tag, e.input_type, e.href, e.enabled)

    @property
    def suggested_action(self) -> ActionType:
        if self.role in _TYPEABLE_ROLES:
            return ActionType.TYPE
        if self.role in _SELECT_ROLES and self.tag == "select":
            return ActionType.SELECT
        return ActionType.CLICK

    @property
    def rank(self) -> int:
        """Lower = explore sooner: navigation, then actions, then toggles/selects, then text fields."""
        if self.role in _NAV_ROLES and self.href and not self.href.startswith("#"):
            return 0
        if self.role in _ACTION_ROLES or self.role in _NAV_ROLES:
            return 1
        if self.role in _SELECT_ROLES or self.role in {"checkbox", "radio", "slider"}:
            return 2
        if self.role in _TYPEABLE_ROLES:
            return 3
        return 4


@dataclass
class _StateRecord:
    info: KnownState
    elements: dict[str, ElementInfo] = field(default_factory=dict)
    tried: set[str] = field(default_factory=set)


ElementFilter = Callable[[ElementInfo, str], bool]  # (element, state_url) -> True if it must NOT be suggested


class ExplorationMemory:
    def __init__(self, max_states: int = 500, max_elements_per_state: int = 80, max_sequence: int = 400) -> None:
        self._states: dict[str, _StateRecord] = {}
        self._tried_counts: Counter[tuple[str, str]] = Counter()
        self._element_counts: Counter[tuple[str, str]] = Counter()
        self._type_counts: Counter[tuple[str, str]] = Counter()  # (state_id, action_type)
        self._edges: dict[tuple[str, str], str] = {}
        self._max_states = max_states
        self._max_elements = max_elements_per_state
        self._max_sequence = max_sequence
        self.state_sequence: list[str] = []
        self.action_sequence: list[str] = []
        self.current_state_id: str | None = None
        self._avoid: dict[str, set[str]] = {}

    # -- recording ------------------------------------------------------------
    def observe(self, obs: PageObservation, step: int) -> tuple[KnownState, bool]:
        """Register the state the agent is currently in. Returns (state, is_new)."""
        sid = obs.state_fingerprint
        rec = self._states.get(sid)
        is_new = rec is None
        if rec is None:
            if len(self._states) >= self._max_states:  # bounded: drop the least recently seen state
                oldest = min(self._states.values(), key=lambda r: r.info.last_seen_step)
                del self._states[oldest.info.state_id]
            rec = _StateRecord(KnownState(state_id=sid, url=obs.url, title=obs.title, first_seen_step=step))
            self._states[sid] = rec
        arrived = sid != self.current_state_id
        if arrived:
            rec.info.visit_count += 1
        rec.info.url, rec.info.title, rec.info.last_seen_step = obs.url, obs.title, step
        rec.elements = {e.id: ElementInfo.from_element(e) for e in obs.interactive_elements[: self._max_elements]}
        rec.info.element_count = len(obs.interactive_elements)
        rec.tried.update(self._avoid.get(sid, set()) & set(rec.elements))
        self.current_state_id = sid
        self.state_sequence = (self.state_sequence + [sid])[-self._max_sequence:]
        return self._known(rec), is_new

    def note_action(self, state_id: str, action: AgentAction) -> None:
        key = action.key()
        self._tried_counts[(state_id, key)] += 1
        self.action_sequence = (self.action_sequence + [key])[-self._max_sequence:]
        self._type_counts[(state_id, action.action_type.value)] += 1
        if action.action_type == ActionType.OPEN and action.arguments.url:
            self._element_counts[("OPEN", action.arguments.url)] += 1
        if action.target:
            self._element_counts[(action.action_type.value, action.target)] += 1
            rec = self._states.get(state_id)
            if rec:
                rec.tried.add(action.target)

    def note_transition(self, from_id: str, action: AgentAction, to_id: str) -> None:
        self._edges[(from_id, action.key())] = to_id

    # -- queries --------------------------------------------------------------
    def visits(self, state_id: str) -> int:
        rec = self._states.get(state_id)
        return rec.info.visit_count if rec else 0

    def tried_count(self, state_id: str, action_key: str) -> int:
        return self._tried_counts[(state_id, action_key)]

    def element_action_count(self, action_type: ActionType | str, target: str) -> int:
        t = action_type.value if isinstance(action_type, ActionType) else action_type
        return self._element_counts[(t, target)]

    def type_count(self, state_id: str, action_type: ActionType | str) -> int:
        t = action_type.value if isinstance(action_type, ActionType) else action_type
        return self._type_counts[(state_id, t)]

    def is_tried(self, state_id: str, element_id: str) -> bool:
        rec = self._states.get(state_id)
        return bool(rec) and element_id in rec.tried

    def state(self, state_id: str) -> KnownState | None:
        rec = self._states.get(state_id)
        return self._known(rec) if rec else None

    def state_url(self, state_id: str) -> str | None:
        rec = self._states.get(state_id)
        return rec.info.url if rec else None

    def element(self, state_id: str, element_id: str) -> ElementInfo | None:
        rec = self._states.get(state_id)
        return rec.elements.get(element_id) if rec else None

    def __len__(self) -> int:
        return len(self._states)

    def _untried(self, rec: _StateRecord, blocked: ElementFilter | None) -> list[ElementInfo]:
        out = [
            e for e in rec.elements.values()
            if e.id not in rec.tried and e.enabled and not (blocked and blocked(e, rec.info.url))
        ]
        return sorted(out, key=lambda e: e.rank)  # stable: DOM order within a rank

    def _known(self, rec: _StateRecord, blocked: ElementFilter | None = None) -> KnownState:
        untried = len(self._untried(rec, blocked))
        return rec.info.model_copy(update={"untried_count": untried, "exhausted": untried == 0})

    def known_states(self, limit: int = 12, blocked: ElementFilter | None = None) -> list[KnownState]:
        recs = sorted(self._states.values(), key=lambda r: (r.info.state_id != self.current_state_id,
                                                            -r.info.last_seen_step))
        return [self._known(r, blocked) for r in recs[:limit]]

    def current_known_state(self, blocked: ElementFilter | None = None) -> KnownState | None:
        rec = self._states.get(self.current_state_id or "")
        return self._known(rec, blocked) if rec else None

    def unexplored(
        self, limit: int = 15, blocked: ElementFilter | None = None, per_other_state: int = 3
    ) -> list[UnexploredTransition]:
        """Untried elements: current state first, then a few from each other known state
        (so the agent can plan an alternate navigation path back to unexplored areas)."""
        out: list[UnexploredTransition] = []
        cur = self.current_state_id
        ordered = sorted(self._states.values(), key=lambda r: (r.info.state_id != cur, -r.info.last_seen_step))
        for rec in ordered:
            is_cur = rec.info.state_id == cur
            for e in self._untried(rec, blocked)[: (limit if is_cur else per_other_state)]:
                out.append(UnexploredTransition(
                    state_id=rec.info.state_id, state_url=rec.info.url, element_id=e.id, role=e.role,
                    name=e.name[:60], suggested_action=e.suggested_action, href=e.href, in_current_state=is_cur,
                ))
            if len(out) >= limit:
                break
        return out[:limit]

    def mark_exhausted(self, state_id: str) -> None:
        """Treat every element of a state as tried (used when a state is beyond the depth limit)."""
        rec = self._states.get(state_id)
        if rec:
            rec.tried.update(rec.elements)

    def seed_avoid(self, avoid: "dict[str, set[str]]") -> None:
        """Long-term memory: {state_id: {element ids that previously produced nothing useful}}."""
        self._avoid = {k: set(v) for k, v in avoid.items()}

    def exhausted(self, state_id: str, blocked: ElementFilter | None = None) -> bool:
        rec = self._states.get(state_id)
        return bool(rec) and not self._untried(rec, blocked)
