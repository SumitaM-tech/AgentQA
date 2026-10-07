"""QAAgent: the reasoning engine wrapped in a finite state machine.

    OBSERVING -> PLANNING -> VALIDATING -> EXECUTING -> OBSERVING -> EVALUATING -> PLANNING ...
                                   \\-> RECOVERING (out-of-domain) -> OBSERVING

Nothing can run outside this loop: every browser action needs
`fsm.authorize_execution()`, which enforces the step and action budgets, and
every model proposal must pass the policy layer. The LLM only produces data
(`AgentAction`); actions are mapped to a fixed set of browser tools, never to code.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, Field

from app.agent.critic import BugCandidate, Critic, CriticVerdict, Verdict
from app.bugs.fingerprint import bug_fingerprint
from app.bugs.severity import assess_severity
from app.bugs.verifier import BugVerifier, decide
from app.agent.memory import ExplorationMemory
from app.agent.planner import DecisionModel, PlanResult, Planner
from app.agent.policies import PolicyConfig, PolicyEngine, detect_cycle
from app.agent.state import (
    ActionArguments,
    ActionType,
    AgentAction,
    AgentInput,
    AgentPhase,
    AgentStateMachine,
    BudgetExceeded,
    BugSummary,
    ExecutionResult,
    ExpectedOutcome,
    FSMLimits,
    StepRecord,
    TerminationReason,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.perception.models import PageObservation

logger = get_logger(__name__)

EventCallback = Callable[[str, dict[str, Any]], "Awaitable[None] | None"]


# ---------------------------------------------------------------------------
# Execution boundary
# ---------------------------------------------------------------------------

class ActionExecutor(Protocol):
    async def execute(self, action: AgentAction) -> ExecutionResult: ...
    async def observe(self) -> PageObservation: ...


def to_tool_call(action: AgentAction) -> tuple[str, dict[str, Any]]:
    """AgentAction -> (browser tool name, arguments). The ONLY bridge from model output to
    the browser; it can only produce calls to the fixed tool set in `app.browser.tools`."""
    a, t = action.arguments, action.action_type
    if t == ActionType.OPEN:
        return "browser_open", {"url": a.url}
    if t == ActionType.CLICK:
        return "browser_click", {"element_id": action.target}
    if t == ActionType.TYPE:
        return "browser_type", {"element_id": action.target, "text": a.text,
                                "clear_first": True if a.clear_first is None else a.clear_first,
                                "press_enter": bool(a.press_enter)}
    if t == ActionType.SELECT:
        args: dict[str, Any] = {"element_id": action.target}
        args.update({k: v for k, v in (("value", a.value), ("label", a.label), ("index", a.index)) if v is not None})
        return "browser_select", args
    if t == ActionType.SCROLL:
        if action.target:
            return "browser_scroll", {"element_id": action.target}
        return "browser_scroll", {"direction": a.direction or "down", **({"amount": a.amount} if a.amount else {})}
    if t == ActionType.PRESS:
        args = {"key": a.key}
        if action.target:
            args["element_id"] = action.target
        return "browser_press", args
    if t == ActionType.BACK:
        return "browser_back", {}
    if t == ActionType.FORWARD:
        return "browser_forward", {}
    if t == ActionType.RELOAD:
        return "browser_reload", {}
    if t == ActionType.SCREENSHOT:
        return "browser_screenshot", {}
    if t == ActionType.WAIT:
        return "browser_wait", {k: v for k, v in (("milliseconds", a.milliseconds), ("load_state", a.load_state))
                                if v is not None}
    raise ValueError(f"{t.value} is not an executable browser action")


class BrowserExecutor:
    """ActionExecutor over a BrowserSession, via the validated tool layer."""

    def __init__(self, session) -> None:  # noqa: ANN001 - BrowserSession
        from app.browser.tools import BrowserToolbox

        self.session = session
        self._toolbox = BrowserToolbox(session)

    async def execute(self, action: AgentAction) -> ExecutionResult:
        name, args = to_tool_call(action)
        res = await self._toolbox.execute(name, args)
        r = res.result or {}
        return ExecutionResult(
            ok=res.ok, error=res.error, error_code=res.error_code.value if res.error_code else None,
            url=r.get("url"), title=r.get("title"), screenshot_path=res.screenshot_path,
            duration_ms=int(r.get("duration_ms") or 0),
        )

    async def observe(self) -> PageObservation:
        return await self.session.observe()


# ---------------------------------------------------------------------------
# Config / result
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    max_steps: int = Field(default=25, ge=1)
    allowed_domains: list[str] | None = None   # None => the start URL's host
    policy: PolicyConfig | None = None         # full override (allowed_domains then ignored)
    planning_attempts: int = Field(default=3, ge=1, le=5)
    step_timeout_s: float = Field(default=90.0, gt=0)
    max_wall_seconds: float = Field(default=600.0, gt=0)
    max_recoveries: int = Field(default=3, ge=0, le=10)
    max_consecutive_rejections: int = Field(default=5, ge=1)
    max_consecutive_failures: int = Field(default=4, ge=1)
    max_stagnant_steps: int = Field(default=12, ge=1)
    max_loop_flags: int = Field(default=3, ge=1)
    always_use_critic_llm: bool = False
    send_screenshots: bool = True
    history_in_prompt: int = Field(default=8, ge=0, le=20)
    max_depth: int = Field(default=6, ge=1, le=50)        # navigation depth from the start state
    max_retries: int = Field(default=1, ge=0, le=5)       # retries for transient action failures + bug replays
    extra_hints: list[str] = Field(default_factory=list)  # e.g. "credentials available via {{USERNAME}}"
    known_bugs: list[BugSummary] = Field(default_factory=list)  # bugs from earlier runs of this project
    known_bug_fingerprints: list[str] = Field(default_factory=list)
    verify_bugs: bool = True
    avoid_elements: dict[str, list[str]] = Field(default_factory=dict)  # long-term memory: {state_id: [element ids]}


class AgentRunResult(BaseModel):
    termination: TerminationReason
    detail: str = ""
    steps: list[StepRecord] = Field(default_factory=list)
    bugs: list[BugCandidate] = Field(default_factory=list)
    states_discovered: int = 0
    steps_taken: int = 0
    actions_executed: int = 0
    recoveries: int = 0
    duration_s: float = 0.0
    final_url: str | None = None


class _StepTimeout(Exception):
    pass


class QAAgent:
    def __init__(
        self, planner_model: DecisionModel, *, critic_model: DecisionModel | None = None,
        config: AgentConfig | None = None, on_event: EventCallback | None = None,
        verifier: BugVerifier | None = None,
    ) -> None:
        self.planner_model = planner_model
        self.critic_model = critic_model
        self.config = config or AgentConfig()
        self._on_event = on_event
        self._fsm: AgentStateMachine | None = None
        self.verifier = verifier if verifier is not None else BugVerifier(self.config.max_retries)
        self._resume = asyncio.Event()
        self._resume.set()
        self._paused_at: float | None = None
        self._paused_total = 0.0

    # ------------------------------------------------------------------ public API
    def stop(self) -> None:
        """Request a graceful stop (takes effect before the next step)."""
        if self._fsm:
            self._fsm.request_stop()
        self._resume.set()  # release a paused loop so it can observe the stop request

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def pause(self) -> None:
        """Pause before the next step. Time spent paused does not count against the runtime budget."""
        if self._resume.is_set():
            self._paused_at = time.monotonic()
            self._resume.clear()

    def resume(self) -> None:
        if not self._resume.is_set():
            if self._paused_at is not None:
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = None
            self._resume.set()

    def _clock(self) -> float:
        extra = (time.monotonic() - self._paused_at) if self._paused_at is not None else 0.0
        return time.monotonic() - self._paused_total - extra

    async def _wait_if_paused(self) -> None:
        if self._resume.is_set():
            return
        await self._emit("run_paused")
        await self._resume.wait()
        await self._emit("run_resumed")

    async def _execute(self, executor: ActionExecutor, action: AgentAction) -> ExecutionResult:
        """Execute with bounded retries for transient failures (timeouts / flaky navigation)."""
        result = await self._timed(executor.execute(action), "execution")
        attempt = 0
        while (not result.ok and result.error_code in ("timeout", "navigation_failed")
               and attempt < self.config.max_retries and not (self._fsm and self._fsm.is_terminal)):
            attempt += 1
            await self._emit("action_retry", attempt=attempt, error_code=result.error_code)
            await asyncio.sleep(min(2.0, 0.5 * attempt))
            result = await self._timed(executor.execute(action), "execution")
        return result

    async def decide_next_action(self, inp: AgentInput, memory: ExplorationMemory, policy: PolicyEngine) -> PlanResult:
        """Stateless decision API: exactly one policy-approved action for `inp`."""
        return await Planner(self.planner_model, policy, max_attempts=self.config.planning_attempts,
                             send_screenshot=self.config.send_screenshots).plan(inp, memory)

    async def run(self, goal: str, start_url: str, executor: ActionExecutor) -> AgentRunResult:
        cfg, settings = self.config, get_settings()
        limits = FSMLimits.create(
            cfg.max_steps, absolute_max_steps=settings.agent_absolute_max_steps,
            max_wall_seconds=cfg.max_wall_seconds, absolute_max_wall_seconds=settings.agent_max_wall_seconds,
            max_recoveries=cfg.max_recoveries, max_consecutive_rejections=cfg.max_consecutive_rejections,
            max_consecutive_failures=cfg.max_consecutive_failures, max_stagnant_steps=cfg.max_stagnant_steps,
            max_loop_flags=cfg.max_loop_flags,
        )
        fsm = self._fsm = AgentStateMachine(limits, clock=self._clock)
        if cfg.policy is not None:
            policy_cfg = cfg.policy
        elif cfg.allowed_domains is not None:
            policy_cfg = PolicyConfig(allowed_domains=list(cfg.allowed_domains))
        else:
            policy_cfg = PolicyConfig.for_start_url(start_url)
        policy = PolicyEngine(policy_cfg)
        memory = ExplorationMemory()
        memory.seed_avoid({k: set(v) for k, v in cfg.avoid_elements.items()})
        planner = Planner(self.planner_model, policy, max_attempts=cfg.planning_attempts,
                          send_screenshot=cfg.send_screenshots)
        critic = Critic(self.critic_model, always_use_llm=cfg.always_use_critic_llm,
                        send_screenshot=cfg.send_screenshots)
        steps: list[StepRecord] = []
        bugs: list[BugCandidate] = []
        seen_bugs: set[str] = set()
        depth: dict[str, int] = {}
        started = time.monotonic()
        obs: PageObservation | None = None

        try:
            await self._emit("run_started", goal=goal, start_url=start_url, max_steps=limits.max_steps)
            start_verdict = policy.url_verdict(start_url)
            if not start_verdict.allowed:
                fsm.terminate(TerminationReason.FATAL_ERROR, f"start URL rejected: {start_verdict.message}")
            else:
                obs = await self._bootstrap(fsm, executor, start_url)
            state = None
            if obs is not None and not fsm.is_terminal:
                state, _ = memory.observe(obs, 0)
                depth[state.state_id] = 0
                await self._emit("page_loaded", url=obs.url, title=obs.title, observation=obs)
                await self._emit("state_observed", step=0, is_new=True, state_id=state.state_id, depth=0,
                                 observation=obs, from_state=None)
                fsm.transition(AgentPhase.PLANNING)

            while not fsm.is_terminal:
                await self._wait_if_paused()
                if fsm.check_limits():
                    break
                try:
                    step = fsm.begin_step()
                except BudgetExceeded:
                    break

                blocked = policy.element_blocked
                inp = AgentInput(
                    goal=goal, observation=obs, previous_actions=steps[-cfg.history_in_prompt:] if cfg.history_in_prompt else [],
                    current_state=memory.current_known_state(blocked) or state,
                    known_states=memory.known_states(10, blocked),
                    unexplored_transitions=memory.unexplored(15, blocked),
                    recent_bugs=(cfg.known_bugs[-3:] + [BugSummary(bug_id=b.bug_id, title=b.title, severity=b.severity,
                                                                   category=b.category, step_index=b.step_index)
                                                        for b in bugs[-5:]]),
                    step=step, max_steps=limits.max_steps, allowed_domains=list(policy_cfg.allowed_domains),
                    hints=list(cfg.extra_hints) + policy.hints(memory, obs, step, limits.max_steps) + (
                        [f"No new discoveries in {fsm.stagnant_steps} steps; try a different area."]
                        if fsm.stagnant_steps >= 4 else []),
                )
                plan = await self._timed(planner.plan(inp, memory), "planning")
                # An unavailable model (outage / no API key) is not a "rejected proposal": the deterministic
                # fallback explorer keeps the run going. Only policy/schema rejections count toward the limit.
                model_down = bool(plan.rejection_codes) and all(c == "model_error" for c in plan.rejection_codes)
                fsm.record_rejections(1 if (plan.used_fallback and not model_down) else 0)
                action = plan.action
                await self._emit("step_planned", step=step, action=action.model_dump(mode="json"),
                                 used_fallback=plan.used_fallback, rejections=plan.rejections)

                fsm.transition(AgentPhase.VALIDATING)
                label = self._label(obs, action.target)
                verdict = policy.check(action, obs, memory, step=step, max_steps=limits.max_steps)
                if not verdict.allowed:  # defense in depth: the planner already checked this
                    fsm.record_rejections(1)
                    steps.append(StepRecord(step_index=step, action=action, target_label=label,
                                            state_before=obs.state_fingerprint, verdict="rejected",
                                            verdict_reason=verdict.feedback[:200], policy_rejections=1))
                    fsm.transition(AgentPhase.PLANNING)
                    continue

                if action.action_type == ActionType.FINISH:
                    steps.append(StepRecord(step_index=step, action=action, state_before=obs.state_fingerprint,
                                            policy_rejections=len(plan.rejections), used_fallback=plan.used_fallback))
                    fsm.terminate(TerminationReason.GOAL_COMPLETE, action.reason)
                    break

                fsm.authorize_execution("step")   # -> EXECUTING (budget gate)
                before, state_before = obs, obs.state_fingerprint
                first_try = action.target is not None and not memory.is_tried(state_before, action.target)
                memory.note_action(state_before, action)   # counts even if the action fails
                result = await self._execute(executor, action)
                fsm.record_action_result(result.ok)

                fsm.transition(AgentPhase.OBSERVING)
                after = await self._timed(executor.observe(), "observation")
                fsm.transition(AgentPhase.EVALUATING)

                if not policy.domain_allowed(after.url):
                    obs = await self._recover(fsm, executor, policy, start_url)
                    steps.append(StepRecord(
                        step_index=step, action=action, target_label=label, state_before=state_before,
                        url_after=after.url, result=result, verdict="domain_violation",
                        verdict_reason="Left the allowed domain; navigated back."[:200],
                        policy_rejections=len(plan.rejections), used_fallback=plan.used_fallback))
                    if fsm.is_terminal:
                        break
                    state, _ = memory.observe(obs, step)
                    fsm.record_progress(False)
                    fsm.transition(AgentPhase.PLANNING)
                    continue

                verdict_c: CriticVerdict = await self._timed(
                    critic.evaluate(step=step, action=action, target_label=label, before=before, after=after,
                                    result=result), "critic")
                state, is_new = memory.observe(after, step)
                memory.note_transition(state_before, action, state.state_id)
                fsm.record_progress(is_new or first_try)
                fsm.record_loop(detect_cycle(memory.state_sequence, policy_cfg.loop_min_repeats,
                                             policy_cfg.loop_max_cycle) is not None)
                d_new = depth.get(state_before, 0) + 1
                depth[state.state_id] = min(depth.get(state.state_id, d_new), d_new)
                await self._emit("state_observed", step=step, is_new=is_new, state_id=state.state_id,
                                 depth=depth[state.state_id], observation=after, from_state=state_before)

                if verdict_c.bug is not None:
                    bug = verdict_c.bug
                    bug.fingerprint = bug_fingerprint(bug.category, bug.url, bug.title)
                    if bug.fingerprint in seen_bugs or bug.fingerprint in cfg.known_bug_fingerprints:
                        await self._emit("bug_duplicate", fingerprint=bug.fingerprint, title=bug.title,
                                         seen_before=bug.fingerprint in cfg.known_bug_fingerprints)
                        if bug.fingerprint in seen_bugs:
                            bug = None  # type: ignore[assignment]
                    if bug is not None:
                        await self._emit("bug_candidate", bug=bug.model_dump(mode="json"))
                        keep = True
                        if cfg.verify_bugs and self.verifier is not None:
                            vres = await self._timed(self.verifier.verify(bug, action, before, after, executor), "verification")
                            status, conf = decide(bug, vres)
                            bug.confidence, bug.status = round(conf, 3), ("verified" if status == "verified" else "unverified")
                            bug.verification = vres.as_dict()
                            keep = status != "discarded"
                            if vres.final_observation is not None and vres.final_observation.url != after.url:
                                pass  # replay ended elsewhere; the next observation below re-syncs the page
                            after = vres.final_observation or after
                        sev, why = assess_severity(bug.severity, category=bug.category, evidence=bug.evidence,
                                                   text=f"{bug.title} {bug.action_summary} {bug.url}",
                                                   reproduced=bug.status == "verified")
                        bug.severity, bug.severity_reason = sev, why
                        if keep:
                            seen_bugs.add(bug.fingerprint)
                            bugs.append(bug)
                            await self._emit("bug_reported", bug=bug.model_dump(mode="json"), action=action, label=label,
                                         state_before=state_before)
                        else:
                            await self._emit("bug_discarded", title=bug.title, confidence=bug.confidence)
                steps.append(StepRecord(
                    step_index=step, action=action, target_label=label, state_before=state_before,
                    state_after=state.state_id, url_after=after.url, result=result,
                    verdict=verdict_c.verdict.value, verdict_reason=verdict_c.reason[:200], new_state=is_new,
                    policy_rejections=len(plan.rejections), used_fallback=plan.used_fallback))
                await self._emit("step_evaluated", step=step, verdict=verdict_c.verdict.value,
                                 new_state=is_new, url=after.url, action=action, result=result, label=label,
                                 state_before=state_before, state_after=state.state_id, before=before,
                                 after=after, critic=verdict_c)
                # Depth guard: never wander deeper than max_depth; step back and mark the deep state done.
                if depth[state.state_id] > cfg.max_depth and not fsm.is_terminal:
                    memory.mark_exhausted(state.state_id)
                    await self._emit("depth_limit", state_id=state.state_id, depth=depth[state.state_id])
                    try:
                        fsm.authorize_execution("recovery")
                        back = AgentAction(action_type=ActionType.BACK, arguments=ActionArguments(),
                                           expected_outcome=ExpectedOutcome(summary="Back at a shallower state."),
                                           reason="Depth limit reached; going back.", exploration_priority=0.0)
                        await self._timed(executor.execute(back), "recovery")
                        after = await self._timed(executor.observe(), "observation")
                        state, _ = memory.observe(after, step)
                        depth.setdefault(state.state_id, 0)
                    except BudgetExceeded:
                        break
                obs = after
                fsm.transition(AgentPhase.PLANNING)

        except BudgetExceeded:
            pass  # the machine already recorded why
        except _StepTimeout as exc:
            fsm.terminate(TerminationReason.TIMEOUT, str(exc))
        except asyncio.CancelledError:
            fsm.terminate(TerminationReason.STOPPED, "cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must end in a defined state
            logger.exception("agent_run_failed")
            fsm.terminate(TerminationReason.FATAL_ERROR, f"{type(exc).__name__}: {str(exc)[:200]}")
        finally:
            if not fsm.is_terminal:
                fsm.terminate(TerminationReason.FATAL_ERROR, "loop exited unexpectedly")

        result_obj = AgentRunResult(
            termination=fsm.termination or TerminationReason.FATAL_ERROR, detail=fsm.detail, steps=steps, bugs=bugs,
            states_discovered=len(memory), steps_taken=fsm.steps_started, actions_executed=fsm.actions_executed,
            recoveries=fsm.recoveries, duration_s=round(time.monotonic() - started, 3),
            final_url=obs.url if obs else None,
        )
        await self._emit("run_finished", termination=result_obj.termination.value, detail=result_obj.detail,
                         steps=result_obj.steps_taken, bugs=len(bugs))
        return result_obj

    # ------------------------------------------------------------------ internals
    async def _bootstrap(self, fsm: AgentStateMachine, executor: ActionExecutor, url: str) -> PageObservation | None:
        action = AgentAction(
            action_type=ActionType.OPEN, arguments=ActionArguments(url=url),
            expected_outcome=ExpectedOutcome(summary="The application start page loads.", expects_navigation=True),
            reason="Opening the application under test.", exploration_priority=1.0)
        fsm.transition(AgentPhase.VALIDATING)
        fsm.authorize_execution("bootstrap")
        res = await self._execute(executor, action)
        fsm.transition(AgentPhase.OBSERVING)
        if not res.ok:
            reason = (TerminationReason.UNREACHABLE if (res.error_code or "") in ("navigation_failed", "timeout")
                      else TerminationReason.FATAL_ERROR)
            fsm.terminate(reason, f"could not open the start URL: {(res.error or '')[:160]}")
            return None
        return await self._timed(executor.observe(), "observation")

    async def _recover(self, fsm: AgentStateMachine, executor: ActionExecutor, policy: PolicyEngine,
                       start_url: str) -> PageObservation | None:
        """Left the allowed domain: BACK first, then reopen the start URL."""
        fsm.transition(AgentPhase.RECOVERING)
        obs: PageObservation | None = None
        for kind in ("back", "start"):
            fsm.authorize_execution("recovery")
            act = AgentAction(
                action_type=ActionType.BACK if kind == "back" else ActionType.OPEN,
                arguments=ActionArguments(url=start_url) if kind == "start" else ActionArguments(),
                expected_outcome=ExpectedOutcome(summary="Back on the allowed domain."),
                reason="Returning to the allowed domain.", exploration_priority=0.0)
            await self._timed(executor.execute(act), "recovery")
            obs = await self._timed(executor.observe(), "observation")
            if policy.domain_allowed(obs.url):
                break
        fsm.transition(AgentPhase.OBSERVING)
        if obs is None or not policy.domain_allowed(obs.url):
            fsm.terminate(TerminationReason.DOMAIN_VIOLATION, "could not return to the allowed domain")
        return obs

    @staticmethod
    def _label(obs: PageObservation, target: str | None) -> str | None:
        if not target:
            return None
        for e in obs.interactive_elements:
            if e.id == target:
                return (e.name or e.text or e.aria_label or "")[:40] or None
        return None

    async def _timed(self, coro: Awaitable[Any], what: str) -> Any:
        assert self._fsm is not None
        remaining = self._fsm.limits.max_wall_seconds - self._fsm.elapsed
        budget = max(0.001, min(self.config.step_timeout_s, remaining))
        try:
            return await asyncio.wait_for(coro, timeout=budget)
        except asyncio.TimeoutError as exc:
            raise _StepTimeout(f"{what} exceeded {budget:.0f}s") from exc

    async def _emit(self, event: str, **data: Any) -> None:
        if self._on_event is None:
            return
        try:
            out = self._on_event(event, data)
            if inspect.isawaitable(out):
                await out
        except Exception:  # noqa: BLE001 - observers must never break the run
            logger.warning("agent_event_callback_failed", event=event)
