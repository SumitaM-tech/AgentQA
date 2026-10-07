"""RunManager: owns the lifecycle of autonomous QA runs.

    queued -> initializing -> running <-> paused -> completed | failed | stopped

Runs execute as background asyncio tasks (HTTP requests never block on a run). A semaphore caps
concurrent browsers (MAX_CONCURRENT_BROWSERS, default 1) so a Core i3 laptop stays responsive;
extra runs wait in `queued`. Credentials are kept in memory only for the life of the run and are
injected at execution time via {{USERNAME}} / {{PASSWORD}} placeholders — the LLM never sees them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, update

from app.agent.agent import AgentConfig, BrowserExecutor, QAAgent
from app.agent.planner import DecisionModel, GeminiDecisionModel
from app.agent.state import ActionType, AgentAction, BugSummary, ExecutionResult, Severity, TerminationReason
from app.browser.manager import BrowserCapacityError, BrowserLaunchError, get_browser_manager
from app.browser.models import BrowserSessionConfig
from app.core.config import get_settings
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.core.url_security import check_target_url
from app.core.winloop import FIX_MESSAGE, windows_loop_problem
from app.database.session import get_sessionmaker
from app.exploration.store import SqlGraphStore
from app.models.bug import Bug
from app.models.memory_record import MemoryRecord
from app.models.project import Project
from app.models.test_run import TestRun
from app.services.run_recorder import RunRecorder

logger = get_logger(__name__)

ACTIVE_STATUSES = ("queued", "initializing", "running", "paused")
_COMPLETED = {TerminationReason.GOAL_COMPLETE, TerminationReason.MAX_STEPS, TerminationReason.MAX_ACTIONS,
              TerminationReason.TIMEOUT, TerminationReason.STAGNATION, TerminationReason.LOOP_DETECTED,
              TerminationReason.TOO_MANY_REJECTIONS}
_STATUS_TEXT = {
    TerminationReason.MAX_STEPS: "Maximum steps reached.", TerminationReason.TIMEOUT: "Maximum runtime reached.",
    TerminationReason.STAGNATION: "No useful unexplored actions remain.",
    TerminationReason.TOO_MANY_REJECTIONS: "No useful unexplored actions remain.",
    TerminationReason.LOOP_DETECTED: "Stopped to avoid an infinite loop.",
}


class CredentialExecutor:
    """Substitutes {{USERNAME}}/{{PASSWORD}} in TYPE actions at execution time and scrubs echoes."""

    def __init__(self, inner, username: str | None, password: str | None) -> None:  # noqa: ANN001
        self._inner, self._u, self._p = inner, username, password

    async def execute(self, action: AgentAction) -> ExecutionResult:
        if action.action_type == ActionType.TYPE and action.arguments.text and "{{" in action.arguments.text:
            text = action.arguments.text
            if self._u:
                text = text.replace("{{USERNAME}}", self._u)
            if self._p:
                text = text.replace("{{PASSWORD}}", self._p)
            action = action.model_copy(update={"arguments": action.arguments.model_copy(update={"text": text})})
        res = await self._inner.execute(action)
        if res.error:
            for s in (self._u, self._p):
                if s:
                    res = res.model_copy(update={"error": res.error.replace(s, "[redacted]")})
        return res

    async def observe(self):  # noqa: ANN201
        return await self._inner.observe()


class _Active:
    def __init__(self, task: asyncio.Task) -> None:
        self.task = task
        self.agent: QAAgent | None = None
        self.stop_requested = False


class RunManager:
    def __init__(self, decision_model_factory: Callable[[], DecisionModel] | None = None) -> None:
        self.decision_model_factory = decision_model_factory or (lambda: GeminiDecisionModel())
        self._active: dict[UUID, _Active] = {}
        self._recorders: dict[UUID, RunRecorder] = {}
        self._credentials: dict[UUID, tuple[str | None, str | None]] = {}
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None

    # ---------------------------------------------------------------- public API
    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(get_settings().max_concurrent_browsers)
            self._sem_loop = loop
        return self._sem

    def is_active(self, run_id: UUID) -> bool:
        return run_id in self._active

    def set_credentials(self, run_id: UUID, username: str | None, password: str | None) -> None:
        if username or password:
            self._credentials[run_id] = (username, password)

    def start(self, run_id: UUID) -> None:
        if run_id in self._active:
            raise RuntimeError("run already active")
        task = asyncio.create_task(self._execute(run_id), name=f"run-{run_id}")
        self._active[run_id] = _Active(task)
        task.add_done_callback(lambda _t, rid=run_id: self._active.pop(rid, None))

    async def stop(self, run_id: UUID) -> bool:
        a = self._active.get(run_id)
        if a is None:
            return False
        a.stop_requested = True
        if a.agent is not None:
            a.agent.stop()
        elif not a.task.done():  # still queued for a browser slot
            a.task.cancel()
        return True

    async def pause(self, run_id: UUID) -> bool:
        a = self._active.get(run_id)
        if a is None or a.agent is None or a.agent.paused:
            return False
        a.agent.pause()
        await self._set_status(run_id, "paused")
        await self._emit(run_id, "agent_thinking", "Run paused.")
        return True

    async def resume(self, run_id: UUID) -> bool:
        a = self._active.get(run_id)
        if a is None or a.agent is None or not a.agent.paused:
            return False
        a.agent.resume()
        await self._set_status(run_id, "running")
        await self._emit(run_id, "agent_thinking", "Run resumed.")
        return True

    async def shutdown(self) -> None:
        for rid in list(self._active):
            await self.stop(rid)
        tasks = [a.task for a in self._active.values()]
        if tasks:
            await asyncio.wait(tasks, timeout=15)
        for a in list(self._active.values()):
            a.task.cancel()

    async def recover_interrupted(self) -> int:
        """Runs left active by a previous process can never finish: mark them failed."""
        async with get_sessionmaker()() as db:
            res = await db.execute(update(TestRun).where(TestRun.status.in_(ACTIVE_STATUSES)).values(
                status="failed", error_message="Interrupted by a server restart.",
                termination_reason="interrupted", finished_at=datetime.utcnow()))
            await db.commit()
            return res.rowcount or 0

    # ---------------------------------------------------------------- internals
    async def _set_status(self, run_id: UUID, status: str, **extra) -> None:
        async with get_sessionmaker()() as db:
            await db.execute(update(TestRun).where(TestRun.id == run_id).values(status=status, **extra))
            await db.commit()

    async def _emit(self, run_id: UUID, type_: str, message: str, data: dict | None = None) -> None:
        rec = self._recorders.get(run_id)
        if rec is not None:
            await rec.emit(type_, message, data)

    async def _load_memory(self, project_id: UUID, run_id: UUID):  # noqa: ANN202
        """Long-term memory: known bug fingerprints/summaries and fruitless actions from earlier runs."""
        async with get_sessionmaker()() as db:
            bugs = (await db.execute(select(Bug).where(Bug.project_id == project_id, Bug.test_run_id != run_id)
                                     .order_by(Bug.created_at.desc()).limit(40))).scalars().all()
            mem = (await db.execute(select(MemoryRecord).where(
                MemoryRecord.project_id == project_id, MemoryRecord.kind == "action"))).scalars().all()
        fps = sorted({b.fingerprint for b in bugs if b.fingerprint})
        summaries, seen = [], set()
        for b in bugs:
            if b.fingerprint in seen:
                continue
            seen.add(b.fingerprint)
            try:
                sev = Severity(b.severity)
            except ValueError:
                sev = Severity.MEDIUM
            summaries.append(BugSummary(bug_id=str(b.id), title=b.title[:120], severity=sev, category=b.category))
        avoid: dict[str, list[str]] = {}
        for m in mem:
            p = m.payload or {}
            if not p.get("useful") and m.count >= 2 and "|" in m.key:
                state, _, target = m.key.partition("|")
                avoid.setdefault(state, []).append(target)
        return fps, summaries[:5], avoid

    async def _execute(self, run_id: UUID) -> None:
        settings = get_settings()
        sm = get_sessionmaker()
        try:
            async with self._semaphore():
                await self._run(run_id, settings, sm)
        except asyncio.CancelledError:  # stopped while waiting for a browser slot
            async with sm() as db:
                await db.execute(update(TestRun).where(TestRun.id == run_id).values(
                    status="stopped", termination_reason="stopped", finished_at=datetime.utcnow()))
                await db.commit()
            logger.info("run_cancelled_while_queued", run_id=str(run_id))
        finally:
            self._recorders.pop(run_id, None)
            self._credentials.pop(run_id, None)

    async def _run(self, run_id: UUID, settings, sm) -> None:  # noqa: ANN001
        async with sm() as db:
            run = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one()
            project_id, goal, url = run.project_id, run.goal, run.target_url
            proj = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            extra_domains = list(proj.allowed_domains) if proj and proj.allowed_domains else []
            limits = dict(max_steps=run.max_steps, max_runtime=run.max_runtime_seconds,
                          max_depth=run.max_depth, max_retries=run.max_retries)
        username, password = self._credentials.get(run_id, (None, None))
        active = self._active[run_id]
        rec = RunRecorder(run_id, project_id, bus=get_event_bus(), store=SqlGraphStore(sm), sessionmaker=sm,
                          secrets=[s for s in (username, password) if s], goal=goal)
        self._recorders[run_id] = rec
        await self._set_status(run_id, "initializing", started_at=datetime.utcnow())
        await rec.emit("agent_thinking", "Creating run and launching the browser...", {"phase": "initializing"})

        session = None
        try:
            problem = windows_loop_problem()
            if problem:
                raise RuntimeError(problem)
            check = await check_target_url(url, allowed_domains=(extra_domains or None))
            if not check.ok:
                raise ValueError(f"Target rejected: {check.error}")
            host = urlsplit(url).hostname or ""
            fps, known_bugs, avoid = await self._load_memory(project_id, run_id)
            cfg = BrowserSessionConfig.from_settings()
            domains = sorted({host, *extra_domains})  # never leave the target (+ project-approved) domains
            cfg.allowed_domains = domains
            session = await get_browser_manager().create_session(config=cfg)
            await rec.emit("agent_thinking", "Browser ready. Connecting the agent...", {"phase": "connecting"})

            model = self.decision_model_factory()
            hints = []
            if username or password:
                hints.append("Test credentials exist. In TYPE actions use the literal text {{USERNAME}} or "
                             "{{PASSWORD}} for login fields; never invent credentials.")
            agent = QAAgent(model, critic_model=model, on_event=rec.on_agent_event, config=AgentConfig(
                max_steps=limits["max_steps"], max_wall_seconds=limits["max_runtime"], max_depth=limits["max_depth"],
                max_retries=limits["max_retries"], allowed_domains=domains, extra_hints=hints, known_bugs=known_bugs,
                known_bug_fingerprints=fps, avoid_elements=avoid))
            active.agent = agent
            if active.stop_requested:
                agent.stop()
            await self._set_status(run_id, "running")
            executor = CredentialExecutor(BrowserExecutor(session), username, password)
            result = await agent.run(goal, url, executor)

            reason = result.termination
            if reason == TerminationReason.STOPPED:
                status = "stopped"
            elif reason in _COMPLETED:
                status = "completed"
            else:
                status = "failed"
            detail = _STATUS_TEXT.get(reason) or result.detail or reason.value
            if status == "failed":
                await self._set_status(run_id, "failed", error_message=rec.scrub(detail)[:1000])
                await rec.emit("error", rec.scrub(detail), {"termination": reason.value})
            await rec.finalize(status, reason.value, detail, {
                "steps_taken": result.steps_taken, "duration_s": result.duration_s, "final_url": result.final_url})
        except NotImplementedError:  # Playwright could not spawn its driver (Windows selector loop)
            await self._fail(run_id, rec, FIX_MESSAGE)
        except BrowserCapacityError as exc:
            await self._fail(run_id, rec, f"Browser busy: {exc}")
        except BrowserLaunchError as exc:
            await self._fail(run_id, rec, str(exc))
        except Exception as exc:  # noqa: BLE001 - a run must always end in a defined state
            logger.exception("run_failed", run_id=str(run_id))
            await self._fail(run_id, rec, f"{type(exc).__name__}: {str(exc)[:300]}")
        finally:
            if session is not None:
                await asyncio.shield(session.close())

    async def _fail(self, run_id: UUID, rec: RunRecorder, message: str) -> None:
        message = rec.scrub(message)
        await self._set_status(run_id, "failed", error_message=message[:1000])
        await rec.emit("error", message, {"fatal": True})
        await rec.finalize("failed", "fatal_error", message)


_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def set_run_manager(m: RunManager | None) -> None:
    global _manager
    _manager = m
