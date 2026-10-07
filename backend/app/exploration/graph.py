"""In-memory + persisted graph of discovered UI states and transitions.

Nodes = distinct UI states (keyed by `state_fingerprint`).
Edges  = an Action taken from one state that led to another (or the same)
state.

This is what lets the agent (a) avoid re-exploring the same state via the
same action twice, and (b) prioritize states with unexplored outgoing
actions when planning the next step (`GraphSummary.unexplored_state_ids`).
Persistence to Postgres happens through `app.database`; this module owns
the graph *logic* (dedup, frontier calculation), not SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.agent.legacy_state import Action, GraphSummary, Observation


@dataclass
class StateNode:
    node_id: UUID
    fingerprint: str
    observation: Observation
    outgoing_action_signatures: set[str] = field(default_factory=set)


@dataclass
class StateEdge:
    edge_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    action: Action
    step_index: int


class StateGraph:
    """Session-scoped graph. One instance per running AgentOrchestrator."""

    def __init__(self) -> None:
        self._nodes: dict[UUID, StateNode] = {}
        self._nodes_by_fingerprint: dict[str, UUID] = {}
        self._edges: list[StateEdge] = []

    def get_or_create_node(self, observation: Observation) -> StateNode:
        existing_id = self._nodes_by_fingerprint.get(observation.state_fingerprint)
        if existing_id is not None:
            return self._nodes[existing_id]
        node = StateNode(node_id=uuid4(), fingerprint=observation.state_fingerprint, observation=observation)
        self._nodes[node.node_id] = node
        self._nodes_by_fingerprint[node.fingerprint] = node.node_id
        return node

    def record_transition(
        self, source: StateNode, action: Action, target: StateNode, step_index: int
    ) -> StateEdge:
        edge = StateEdge(
            edge_id=uuid4(),
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action=action,
            step_index=step_index,
        )
        self._edges.append(edge)
        source.outgoing_action_signatures.add(_action_signature(action))
        return edge

    def unexplored_nodes(self) -> list[StateNode]:
        """Nodes whose visible interactive elements are not all covered by
        an outgoing action yet."""
        result = []
        for node in self._nodes.values():
            tried_targets = {
                sig.split(":", 1)[1] for sig in node.outgoing_action_signatures if ":" in sig
            }
            all_targets = {el.element_id for el in node.observation.interactive_elements}
            if all_targets - tried_targets:
                result.append(node)
        return result

    def summary(self, current_node_id: UUID | None) -> GraphSummary:
        return GraphSummary(
            total_states=len(self._nodes),
            total_transitions=len(self._edges),
            unexplored_state_ids=[n.node_id for n in self.unexplored_nodes()],
            current_state_id=current_node_id,
        )


def _action_signature(action: Action) -> str:
    return f"{action.action_type.value}:{action.target_element_id or ''}"
