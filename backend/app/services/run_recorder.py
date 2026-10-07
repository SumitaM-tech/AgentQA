"""RunRecorder: turns raw agent events into persisted rows + typed live events.

The agent (app.agent.agent.QAAgent) emits low-level callbacks; this class is the single place that
(1) persists states / transitions / actions / bugs / counters, (2) maps them to the public event
vocabulary (run_started, page_loaded, observation, agent_thinking, agent_action, action_completed,
state_discovered, state_revisited, bug_detected, bug_verified, screenshot_created, error,
run_completed), (3) appends every event to run_events and publishes it on the in-process bus.

Only short, operational text is ever emitted: `agent_thinking` carries the action's one-sentence
`reason` (schema-validated to reject deliberation) — never raw model reasoning.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.artifacts import to_relative, to_url
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.exploration.store import EdgeWrite, GraphStore, StateWrite
from app.models.bug import Bug
from app.models.agent_action import AgentAction as AgentActionRow
from app.models.memory_record import MemoryRecord
from app.models.run_event import RunEvent
from app.models.test_run import TestRun
from app.perception.models import PageObservation
from app.perception.sanitize import redact_secrets

logger = get_logger(__name__)


def repro_steps(edges: list[tuple[str, str, str]], start: str | None, target: str, trigger: str | None) -> list[str]:
    """Steps to reproduce = shortest recorded path (BFS over real transitions) from the start state to the state the
    triggering action was executed from, followed by that triggering action. Nothing here is invented: every step is an
    action the agent actually executed."""
    steps = ["Open the application start page"]
    if start and start != target:
        graph: dict[str, list[tuple[str, str]]] = {}
        for src, dst, text in edges:
            if src != dst:
                graph.setdefault(src, []).append((dst, text))
        prev: dict[str, tuple[str, str]] = {}
        queue, seen = [start], {start}
        while queue and target not in seen:
            cur = queue.pop(0)
            for nxt, text in graph.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = (cur, text)
                    queue.append(nxt)
        path: list[str] = []
        node = target
        while node in prev:
            node, text = prev[node][0], prev[node][1]
            path.append(text)
        steps += list(reversed(path))
    if trigger:
        steps.append(trigger)  # the action that exposed the problem, executed from `target`
    return steps


def _ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


class RunRecorder:
    def __init__(
        self, run_id: UUID, project_id: UUID, *, bus: EventBus, store: GraphStore,
        sessionmaker: async_sessionmaker[AsyncSession], secrets: list[str] | None = None, goal: str = "",
    ) -> None:
        self.run_id, self.project_id = run_id, project_id
        self._bus, self._store, self._sm = bus, store, sessionmaker
        self._secrets = [s for s in (secrets or []) if s]
        self._seq = 0
        self._obs: PageObservation | None = None
        self._steps: list[str] = []          # human-readable action log
        self._edges: list[tuple[str, str, str]] = []  # (source fp, target fp, action text) of executed actions
        self._start_fp: str | None = None
        self._seen: dict[str, set[str]] = {}
        self._tried: dict[str, set[str]] = {}
        self._mem: dict[tuple[str, str], dict[str, Any]] = {}
        self.stats = {"steps": 0, "actions": 0, "states": 0, "bugs": 0, "errors": 0, "candidates": 0, "discarded": 0}
        self._first_bug_at: datetime | None = None
        self.screenshot_dirs: set[str] = set()
        self._last_screenshot: str | None = None
        self.goal = goal

    # ------------------------------------------------------------------ helpers
    def scrub(self, text: str | None) -> str:
        out = redact_secrets(text or "")
        for s in self._secrets:
            out = out.replace(s, "[redacted]")
        return out

    def _label(self, obs: PageObservation | None, target: str | None) -> str | None:
        if obs is None or not target:
            return None
        for e in obs.interactive_elements:
            if e.id == target:
                return (e.name or e.text or e.aria_label or e.tag or "")[:60] or None
        return None

    def _describe(self, action: Any, label: str | None) -> str:
        t = action.action_type.value
        a = action.arguments
        name = f"'{label}'" if label else (action.target or "")
        if t == "OPEN":
            return f"Opening {a.url}"
        if t == "CLICK":
            return f"Clicking {name}".strip()
        if t == "TYPE":
            shown = "credentials" if a.text and "{{" in a.text else f"'{self.scrub(a.text)[:30]}'"
            return f"Typing {shown} into {name}".strip()
        if t == "SELECT":
            return f"Selecting {a.value or a.label or a.index} in {name}".strip()
        if t == "SCROLL":
            return f"Scrolling {a.direction or 'to element'}"
        if t == "PRESS":
            return f"Pressing {a.key}"
        return {"BACK": "Going back", "FORWARD": "Going forward", "RELOAD": "Reloading the page",
                "WAIT": "Waiting for the page", "FINISH": "Finishing the run"}.get(t, t.title())

    async def emit(self, type_: str, message: str = "", data: dict[str, Any] | None = None) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "type": type_, "run_id": str(self.run_id), "message": self.scrub(message),
                 "data": data or {}, "timestamp": _ts()}
        try:
            async with self._sm() as db:
                db.add(RunEvent(test_run_id=self.run_id, seq=self._seq, type=type_, message=event["message"],
                                data=event["data"], timestamp=datetime.utcnow()))
                await db.commit()
        except Exception:  # noqa: BLE001 - persistence problems must not kill a run
            logger.warning("event_persist_failed", type=type_)
        self._bus.publish(self.run_id, event)
        return event

    async def _update_run(self, **values: Any) -> None:
        async with self._sm() as db:
            await db.execute(update(TestRun).where(TestRun.id == self.run_id).values(**values))
            await db.commit()

    def _coverage(self) -> float:
        seen = sum(len(v) for v in self._seen.values())
        tried = sum(len(self._tried.get(k, set()) & v) for k, v in self._seen.items())
        return round(tried / seen, 3) if seen else 0.0

    async def _flush_counters(self, **extra: Any) -> None:
        await self._update_run(
            steps_taken=self.stats["steps"], states_count=self.stats["states"], actions_count=self.stats["actions"],
            bugs_count=self.stats["bugs"], errors_count=self.stats["errors"], coverage=self._coverage(),
            candidates_count=self.stats["candidates"], discarded_count=self.stats["discarded"],
            first_bug_at=self._first_bug_at,
            last_screenshot=self._last_screenshot, **extra)

    def _metrics(self) -> dict[str, Any]:
        return {**self.stats, "coverage": self._coverage()}

    # ------------------------------------------------------------------ agent callback
    async def on_agent_event(self, name: str, d: dict[str, Any]) -> None:
        handler = getattr(self, f"_on_{name}", None)
        if handler is not None:
            await handler(d)

    async def _on_run_started(self, d: dict[str, Any]) -> None:
        await self.emit("run_started", f"Run started: {self.scrub(d.get('goal', ''))[:160]}",
                        {"goal": d.get("goal"), "start_url": d.get("start_url"), "max_steps": d.get("max_steps")})

    async def _on_page_loaded(self, d: dict[str, Any]) -> None:
        obs: PageObservation = d["observation"]
        rel = to_relative(obs.screenshot_path)
        self._last_screenshot = rel or self._last_screenshot
        await self.emit("page_loaded", f"Loaded {obs.title or obs.url}",
                        {"url": obs.url, "title": obs.title, "screenshot_url": to_url(rel)})

    async def _on_state_observed(self, d: dict[str, Any]) -> None:
        obs: PageObservation = d["observation"]
        self._obs = obs
        fp = obs.state_fingerprint
        self._start_fp = self._start_fp or fp
        rel = to_relative(obs.screenshot_path)
        if rel:
            self._last_screenshot = rel
            self.screenshot_dirs.add(rel.split("/")[0])
        elements = [{"id": e.id, "role": e.role, "name": (e.name or e.text or "")[:40]}
                    for e in obs.interactive_elements[:30]]
        self._seen.setdefault(fp, set()).update(e.id for e in obs.interactive_elements)
        state_uuid, created = await self._store.upsert_state(self.run_id, StateWrite(
            fingerprint=fp, url=obs.url, title=obs.title, step=d["step"], depth=d["depth"],
            summary=self.scrub(obs.visible_text[:300]), elements=elements, screenshot=rel))
        if created:
            self.stats["states"] += 1
        await self.emit(
            "observation", f"Observed {obs.title or obs.url}: {len(obs.interactive_elements)} interactive elements",
            {"url": obs.url, "title": obs.title, "interactive_elements": len(obs.interactive_elements),
             "console_errors": len(obs.console_errors), "network_errors": len(obs.network_errors),
             "screenshot_url": to_url(rel)})
        if rel:
            await self.emit("screenshot_created", "Screenshot captured", {"screenshot_url": to_url(rel), "state_id": str(state_uuid)})
        payload = {"state_id": str(state_uuid), "fingerprint": fp, "url": obs.url, "title": obs.title,
                   "depth": d["depth"], "screenshot_url": to_url(rel)}
        if created:
            await self.emit("state_discovered", f"New state discovered: {obs.title or obs.url}", payload)
        else:
            await self.emit("state_revisited", f"Revisited {obs.title or obs.url}", payload)
        await self._flush_counters()
        self._track_url(obs.url)

    def _track_url(self, url: str) -> None:
        key = ("url", url.split("#")[0][:500])
        self._mem[key] = {"useful": True, "count": self._mem.get(key, {}).get("count", 0) + 1}

    async def _on_step_planned(self, d: dict[str, Any]) -> None:
        a = d["action"]
        if d.get("used_fallback") and not getattr(self, "_fallback_noted", False):
            self._fallback_noted = True
            await self.emit("agent_thinking", "AI model unavailable; using the built-in explorer for these steps.", {"fallback": True})
        label = self._label(self._obs, a.get("target"))
        # `reason` is validated by AgentAction to be one concise operational sentence — safe to show.
        await self.emit("agent_thinking", a.get("reason", ""), {"step": d["step"], "priority": a.get("exploration_priority")})
        if a.get("action_type") != "FINISH":  # announce the action as it starts, not after it finishes
            from app.agent.state import AgentAction
            try:
                text = self._describe(AgentAction.model_validate(a), label)
                await self.emit("agent_action", text, {"step": d["step"], "action": str(a["action_type"]).lower(),
                                                       "target": label, "expected": a["expected_outcome"]["summary"]})
            except Exception:  # noqa: BLE001 - cosmetic event only
                pass

    async def _on_step_evaluated(self, d: dict[str, Any]) -> None:
        action, result, before, after, critic = d["action"], d["result"], d["before"], d["after"], d["critic"]
        label = d.get("label")
        step = d["step"]
        text = self._describe(action, label)
        self._steps.append(text)
        self._edges.append((d["state_before"], d["state_after"], text))
        self.stats["steps"] = step
        self.stats["actions"] += 1
        if action.target:
            self._tried.setdefault(d["state_before"], set()).add(action.target)
        rel = to_relative(after.screenshot_path)
        if rel:
            self._last_screenshot = rel
        actual = (critic.reason if critic.verdict.value != "as_expected"
                  else f"Now at '{after.title or after.url}'")
        expected = action.expected_outcome.summary
        sm = d["state_before"], d["state_after"]
        edge_id = await self._store.add_transition(self.run_id, EdgeWrite(
            source_fingerprint=sm[0], target_fingerprint=sm[1], step=step, action_type=action.action_type.value.lower(),
            label=text, parameters=self._safe_params(action), expected=self.scrub(expected),
            actual=self.scrub(actual), verdict=critic.verdict.value, target_element_id=action.target))
        async with self._sm() as db:
            db.add(AgentActionRow(
                test_run_id=self.run_id, step_index=step, action_type=action.action_type.value.lower(),
                target_element_id=action.target, action_value=self._safe_params(action).get("text") or None,
                reasoning=self.scrub(action.reason), expected_summary=self.scrub(expected),
                verdict_outcome=critic.verdict.value, verdict_confidence=critic.confidence,
                verdict_reasoning=self.scrub(critic.reason)))
            await db.commit()
        useful = bool(d["new_state"]) or sm[0] != sm[1] or critic.verdict.value not in ("as_expected", "action_failed")
        if action.target:
            k = ("action", f"{sm[0]}|{action.target}"[:590])
            prev = self._mem.get(k, {})
            self._mem[k] = {"useful": bool(prev.get("useful")) or useful, "failed": not result.ok,
                            "count": prev.get("count", 0) + 1}
        await self.emit("action_completed", f"{text} — {'ok' if result.ok else 'failed'}", {
            "step": step, "ok": result.ok, "verdict": critic.verdict.value, "new_state": d["new_state"],
            "url": after.url, "duration_ms": result.duration_ms, "edge_id": str(edge_id) if edge_id else None,
            "screenshot_url": to_url(rel), "metrics": self._metrics()})
        if not result.ok:
            self.stats["errors"] += 1
            await self.emit("error", f"Action failed: {self.scrub(result.error or result.error_code or '')[:200]}",
                            {"step": step, "code": result.error_code})
        await self._flush_counters()

    def _safe_params(self, action: Any) -> dict[str, Any]:
        params = dict(action.arguments.provided())
        if "text" in params:
            params["text"] = "[credential]" if "{{" in str(params["text"]) else self.scrub(str(params["text"]))
        return params

    async def _on_bug_candidate(self, d: dict[str, Any]) -> None:
        b = d["bug"]
        self.stats["candidates"] += 1
        await self.emit("bug_detected", f"Potential issue: {b['title']}",
                        {"title": b["title"], "severity": b["severity"], "category": b["category"],
                         "status": "candidate", "url": b["url"]})
        await self.emit("agent_thinking", "Re-checking the potential issue before reporting it.", {})

    async def _on_bug_discarded(self, d: dict[str, Any]) -> None:
        self.stats["discarded"] += 1
        await self._flush_counters()
        await self.emit("agent_thinking", f"Could not reproduce '{d['title'][:80]}'; not reporting it.", {})

    async def _on_bug_duplicate(self, d: dict[str, Any]) -> None:
        await self.emit("agent_thinking", "Skipping a finding that was already reported.", {"fingerprint": d["fingerprint"]})

    async def _on_depth_limit(self, d: dict[str, Any]) -> None:
        await self.emit("agent_thinking", "Depth limit reached; stepping back to explore other areas.", {})

    async def _on_action_retry(self, d: dict[str, Any]) -> None:
        await self.emit("agent_thinking", f"Action hit a transient error; retrying (attempt {d['attempt']}).", {})

    async def _on_bug_reported(self, d: dict[str, Any]) -> None:
        b = d["bug"]
        async with self._sm() as db:
            prior = (await db.execute(select(func.count()).select_from(Bug).where(
                Bug.project_id == self.project_id, Bug.fingerprint == b["fingerprint"],
                Bug.test_run_id != self.run_id))).scalar_one()
        state_uuid = await self._store.state_id(self.run_id, b["state_id"])
        trigger = self._describe(d["action"], d.get("label")) if d.get("action") is not None else None
        steps = repro_steps(self._edges, self._start_fp, d.get("state_before") or b["state_id"], trigger)
        evidence = list(dict.fromkeys(b["evidence"]))  # de-duplicate, keep order
        clean = lambda t: re.sub(r" e[0-9a-f]{6,}(?= )", "", self.scrub(t))  # noqa: E731 - hide internal element ids
        async with self._sm() as db:
            row = Bug(
                test_run_id=self.run_id, project_id=self.project_id, title=self.scrub(b["title"])[:512],
                severity=b["severity"], description=clean(b["description"]), steps_to_reproduce=steps,
                expected_behavior=self.scrub(b["expected"]), actual_behavior=self.scrub(b["actual"]),
                related_state_id=state_uuid, category=b["category"], confidence=b["confidence"],
                status=b["status"], url=b["url"][:2048], state_key=b["state_id"][:64], fingerprint=b["fingerprint"],
                screenshot_path=to_relative(b.get("screenshot_path")), console_errors=[self.scrub(x) for x in b["console_errors"]],
                network_errors=[self.scrub(x) for x in b["network_errors"]],
                evidence=[self.scrub(x) for x in evidence], severity_reason=b["severity_reason"],
                verification=b["verification"], seen_before_count=int(prior))
            db.add(row)
            await db.commit()
            bug_id = row.id
        self.stats["bugs"] += 1
        payload = {"bug_id": str(bug_id), "title": b["title"], "severity": b["severity"], "category": b["category"],
                   "confidence": b["confidence"], "status": b["status"], "url": b["url"],
                   "screenshot_url": to_url(to_relative(b.get("screenshot_path"))), "seen_before": int(prior)}
        if b["status"] == "verified":
            self._first_bug_at = self._first_bug_at or datetime.utcnow()
            await self.emit("bug_verified", f"Bug verified: {b['title']}", payload)
        else:
            await self.emit("bug_detected", f"Possible bug (unverified): {b['title']}", {**payload, "status": "unverified"})
        await self._flush_counters()

    # ------------------------------------------------------------------ lifecycle
    async def flush_memory(self) -> None:
        """Persist long-term memory (project-scoped) collected during the run."""
        if not self._mem:
            return
        async with self._sm() as db:
            for (kind, key), payload in self._mem.items():
                row = (await db.execute(select(MemoryRecord).where(
                    MemoryRecord.project_id == self.project_id, MemoryRecord.kind == kind,
                    MemoryRecord.key == key))).scalar_one_or_none()
                if row is None:
                    db.add(MemoryRecord(project_id=self.project_id, kind=kind, key=key, payload=payload,
                                        count=payload.get("count", 1)))
                else:
                    old = row.payload or {}
                    row.payload = {**payload, "useful": bool(old.get("useful")) or bool(payload.get("useful"))}
                    row.count = row.count + payload.get("count", 1)
            await db.commit()
        self._mem.clear()

    async def finalize(self, status: str, termination: str, detail: str, extra: dict[str, Any] | None = None) -> None:
        await self.flush_memory()
        try:
            from app.services.retention import prune_run_screenshots

            await prune_run_screenshots(self.run_id, self.screenshot_dirs)
        except Exception:  # noqa: BLE001 - housekeeping must never fail a run
            logger.warning("artifact_prune_failed", run_id=str(self.run_id))
        await self._flush_counters(status=status, termination_reason=termination,
                                   termination_detail=self.scrub(detail)[:1000], finished_at=datetime.utcnow())
        await self.emit("run_completed", f"Run {status}: {self.scrub(detail)[:160] or termination}",
                        {"status": status, "termination": termination, "detail": self.scrub(detail),
                         "metrics": self._metrics(), **(extra or {})})
