"""The exploration loop that wires perception, Gemini and the browser
together. This is the only module allowed to know about all these layers
at once (browser, LLM, graph, persistence, event streaming).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.legacy_state import ActionType, AgentState, StepRecord, VerdictOutcome
from app.browser.interface import BrowserTool
from app.bugs.verification import verify_suspicious_finding
from app.core.config import get_settings
from app.core.events import publish_event
from app.core.logging import get_logger
from app.exploration.graph import StateGraph
from app.llm.gemini_client import GeminiClient
from app.services import run_persistence

logger = get_logger(__name__)


class AgentOrchestrator:
    """Runs one TestRun's exploration loop end to end.

    Step sequence per iteration:
      1. Build AgentState (current Observation + history + graph summary).
      2. gemini.plan_action(state) -> (Action, ExpectedOutcome)
      3. browser.execute(action)
      4. browser.observe() -> post-action Observation
      5. gemini.compare_outcome(expected, post_observation) -> Verdict
      6. graph.record_transition(...); persist UIState/UITransition/AgentAction
      7. if Verdict is suspicious/confirmed: verify_suspicious_finding(...);
         if it reproduces, gemini.generate_bug_report(...) and persist it
      8. publish a WebSocket event at each sub-step
    Loop ends on ActionType.FINISH, max_steps, or an external stop() call.
    """

    def __init__(
        self,
        test_run_id: UUID,
        goal: str,
        target_url: str,
        max_steps: int,
        browser_tool: BrowserTool,
        gemini_client: GeminiClient,
        state_graph: StateGraph,
        db_session: AsyncSession,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.session_id = test_run_id
        self.goal = goal
        self.target_url = target_url
        self.max_steps = max_steps
        self.browser_tool = browser_tool
        self.gemini_client = gemini_client
        self.state_graph = state_graph
        self.db = db_session
        self.username = username
        self.password = password
        self._stop_requested = False

    async def run(self) -> None:
        settings = get_settings()
        step_index = 0
        try:
            await self.browser_tool.launch(headless=settings.browser_headless)
            if self.username or self.password:
                await self.browser_tool.set_credentials(self.username, self.password)
            await self.browser_tool.navigate(self.target_url)
            await publish_event(
                self.session_id, "session_started", {"goal": self.goal, "target_url": self.target_url}
            )

            observation = await self.browser_tool.observe()
            current_node = self.state_graph.get_or_create_node(observation)
            await run_persistence.get_or_create_ui_state(
                self.db, self.session_id, current_node.node_id, observation, discovered_at_step=0
            )
            await self.db.commit()
            await publish_event(self.session_id, "observation", observation.model_dump(mode="json"))

            history: list[StepRecord] = []

            while step_index < self.max_steps and not self._stop_requested:
                state = AgentState(
                    session_id=self.session_id,
                    goal=self.goal,
                    max_steps=self.max_steps,
                    steps_taken=step_index,
                    current_observation=observation,
                    recent_history=history,
                    graph_summary=self.state_graph.summary(current_node.node_id),
                    credentials_available=bool(self.username and self.password),
                )

                action, expected = await self.gemini_client.plan_action(state)
                await publish_event(
                    self.session_id,
                    "action_planned",
                    {"action": action.model_dump(mode="json"), "expected": expected.model_dump(mode="json")},
                )

                if action.action_type == ActionType.FINISH:
                    await run_persistence.record_agent_action(
                        self.db, self.session_id, step_index, action, expected, None
                    )
                    await self.db.commit()
                    logger.info("agent_finished", test_run_id=str(self.session_id), reasoning=action.reasoning)
                    break

                pre_observation = observation
                await self.browser_tool.execute(action)
                await publish_event(self.session_id, "action_executed", {"action": action.model_dump(mode="json")})

                observation = await self.browser_tool.observe()
                await publish_event(self.session_id, "observation", observation.model_dump(mode="json"))

                verdict = await self.gemini_client.compare_outcome(expected, observation, pre_observation)
                await publish_event(self.session_id, "verdict", verdict.model_dump(mode="json"))

                target_node = self.state_graph.get_or_create_node(observation)
                edge = self.state_graph.record_transition(current_node, action, target_node, step_index)

                await run_persistence.get_or_create_ui_state(
                    self.db, self.session_id, target_node.node_id, observation, discovered_at_step=step_index + 1
                )
                await run_persistence.record_ui_transition(
                    self.db,
                    self.session_id,
                    edge.edge_id,
                    current_node.node_id,
                    target_node.node_id,
                    action,
                    step_index,
                )
                await run_persistence.record_agent_action(
                    self.db, self.session_id, step_index, action, expected, verdict
                )
                await publish_event(
                    self.session_id,
                    "graph_updated",
                    self.state_graph.summary(target_node.node_id).model_dump(mode="json"),
                )

                if verdict.outcome in (VerdictOutcome.SUSPICIOUS, VerdictOutcome.CONFIRMED_BUG):
                    confirmed, evidence_observations = await verify_suspicious_finding(
                        action, verdict, pre_observation, observation, self.browser_tool, self.gemini_client
                    )
                    if confirmed:
                        evidence = [(action, expected, verdict, obs) for obs in evidence_observations]
                        bug_report = await self.gemini_client.generate_bug_report(evidence)
                        await run_persistence.record_bug(
                            self.db, self.session_id, bug_report, target_node.node_id, edge.edge_id
                        )
                        await publish_event(self.session_id, "bug_detected", bug_report.model_dump(mode="json"))

                history.append(
                    StepRecord(
                        step_index=step_index,
                        action=action,
                        expected=expected,
                        verdict=verdict,
                        resulting_state_fingerprint=observation.state_fingerprint,
                    )
                )
                current_node = target_node
                step_index += 1

                await run_persistence.update_run_status(
                    self.db, self.session_id, "running", steps_taken=step_index
                )
                await self.db.commit()
                await publish_event(self.session_id, "step_completed", {"step_index": step_index})

            final_status = "stopped" if self._stop_requested else "completed"
            await run_persistence.update_run_status(
                self.db, self.session_id, final_status, steps_taken=step_index
            )
            await self.db.commit()
            await publish_event(self.session_id, "session_completed", {"status": final_status})

        except Exception as exc:  # noqa: BLE001 - top-level run loop must never crash silently
            logger.error("orchestrator_run_failed", test_run_id=str(self.session_id), error=str(exc))
            await self.db.rollback()
            await run_persistence.update_run_status(
                self.db, self.session_id, "failed", steps_taken=step_index, error_message=str(exc)
            )
            await self.db.commit()
            await publish_event(self.session_id, "session_error", {"message": str(exc)})
            raise
        finally:
            await self.browser_tool.close()

    async def stop(self) -> None:
        """Signal the loop to stop after the current step completes."""
        self._stop_requested = True
