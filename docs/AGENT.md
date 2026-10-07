# Reasoning engine (`backend/app/agent/`)

The agent is a **finite state machine wrapped around a policy-checked decision
loop**. The LLM never touches the browser and never runs code — it returns one
typed `AgentAction`, which is checked twice (schema, then policy) before it can
reach the fixed browser tool set.

```
                 ┌──────────────────────────────────────────────┐
                 ▼                                              │
INIT → VALIDATING(bootstrap OPEN) → EXECUTING → OBSERVING → PLANNING
                                                    ▲              │
                                          RECOVERING│              ▼
                                     (out-of-domain)│         VALIDATING(step)
                                                    │              │
                                            EVALUATING ◄────── EXECUTING
                                                                    │
                                                              OBSERVING → EVALUATING → PLANNING …
                                                                                          │
                                                                              FINISH / limit hit
                                                                                          ▼
                                                                                     TERMINATED
```

Every transition is checked against a fixed table (`TRANSITIONS` in
`state.py`); an illegal one raises `InvalidTransition` instead of silently
proceeding.

## Files

| File | Responsibility |
|---|---|
| `state.py` | `AgentAction` decision schema, `AgentInput`, the FSM (`AgentStateMachine`, `AgentPhase`, `FSMLimits`) |
| `memory.py` | `ExplorationMemory` — known states, tried elements/actions, sequences for loop detection |
| `policies.py` | `PolicyEngine` — every deterministic safeguard |
| `prompts.py` | Planner + critic system prompts and prompt builders |
| `planner.py` | Model call → schema validation → policy check → retry → deterministic fallback |
| `critic.py` | Rule-based signals + guard-railed LLM assessment → verdict + bug candidate |
| `agent.py` | `QAAgent` — wires the FSM, planner, critic, memory and a browser executor together |

## The decision: `AgentAction`

```python
class AgentAction(BaseModel):
    action_type: ActionType   # OPEN CLICK TYPE SELECT SCROLL PRESS BACK FORWARD RELOAD WAIT FINISH
    target: str | None        # element id, e.g. "e3fa91c" — never a CSS selector, URL or script
    arguments: ActionArguments
    expected_outcome: ExpectedOutcome
    reason: str                    # ONE short operational sentence
    exploration_priority: float    # 0..1
```

`model_config = ConfigDict(extra="forbid")` everywhere in this schema, so a
model that tries to smuggle extra fields (`"code": "..."`, `"js": "..."`) is
rejected outright — see `tests/test_agent_loop.py::test_model_never_executes_outside_the_fixed_tool_set`.
Validators enforce: the action's target requirement matches its type; only the
arguments that type accepts are present; `OPEN` URLs are syntactically valid
http(s); `PRESS` keys are allow-listed; `reason` is short, single-sentence, and
rejected if it contains chain-of-thought phrases ("let me think", "step by
step", "hmm", …) — **no hidden reasoning is ever accepted, let alone shown**.

`AgentAction.key()` is the canonical identity (type + target + a hash of
arguments) used everywhere repetition is tracked.

## Preferences, enforced structurally

The prompt states the six preferences (unexplored functionality → meaningful
flows → edge cases → validation → error handling → alternate paths) and the
system is built so the model naturally follows them:

- `ExplorationMemory.unexplored()` ranks untried elements — real navigation
  links first, then actions, then toggles/selects, then text fields — and is
  handed to the planner as `UNEXPLORED TRANSITIONS`, current state first, then
  a few from every other known state (**alternate navigation paths**).
- `ExpectedOutcome.expects_error_feedback` exists specifically so the planner
  can predict *"this should show a validation error"* and the critic won't
  flag the resulting error message as a bug — this is what makes deliberately
  testing **edge cases / validation / error handling** low-friction instead of
  something the critic punishes.
- The deterministic fallback (see below) itself prefers untried navigation,
  then form fields with edge-case values (`sample_text`: invalid email,
  negative quantity, bad URL) over anything already tried.

## Preventing repetition — the policy layer (`policies.py`)

Every proposed action is checked by `PolicyEngine.check()`, which never trusts
the model:

| Safeguard | How |
|---|---|
| Repeated clicks | `max_identical_actions_per_state` (exact action, by `.key()`) and `max_actions_per_element` (same element across action types) |
| Infinite loops | `detect_cycle()` finds a length-2..4 state cycle repeating `loop_min_repeats` times in `memory.state_sequence`; the repeated action is blocked |
| Repeated-state exploration | `max_state_visits`; once hit, only actions on **untried** elements are allowed — an exhausted state is not enough on its own, but combined with the per-element caps above it reliably terminates dead ends |
| Invalid targets | target must exist on the current observation, be enabled, and match the action's role requirements (`TYPE` only into textboxes, `SELECT` only on `<select>`) |
| Dangerous navigation | non-http(s) schemes; path patterns for logout/destructive/payment/download (`/logout`, `/delete-account`, `/factory-reset`, `installer.exe`, …); element **names** matching the same categories ("Log out", "Delete my account", "Pay now"), so a same-page button is caught even with no URL |
| Outside the allowed domain | `PolicyConfig.allowed_domains` (defaults to the start URL's host); checked for `OPEN` and for any link a `CLICK`/`PRESS Enter` would follow, using `href`, *before* the browser ever navigates |
| Input hygiene | `TYPE` text capped at 500 chars; text that itself looks like a real secret (`redact_secrets` pattern match) is rejected — always use obviously-fake test data |
| Wait/scroll/reload abuse | capped counts per state, plus "no more than N `WAIT`s in a row" and "`BACK` right after `FORWARD` (and vice versa) is a no-op, blocked" |

A rejection returns a `PolicyVerdict(message, suggestion)` — the planner feeds
this back into the next prompt attempt so the model can self-correct.
Blocked/dangerous elements are also excluded from `ExplorationMemory`'s
"unexplored" suggestions via an `element_blocked` filter, so the agent isn't
even tempted to keep proposing them.

## Never unlimited: the FSM (`state.py`)

`FSMLimits.create(requested_max_steps, absolute_max_steps=..., ...)` **clamps**
whatever the caller asks for to `AGENT_ABSOLUTE_MAX_STEPS` /
`AGENT_MAX_WALL_SECONDS` (env-configurable deployment ceilings) — a run can
never request its way to unbounded steps.

Two independent gates, both mandatory:
- `begin_step()` — enforces `max_steps` (raises `BudgetExceeded` past it).
- `authorize_execution()` — every single browser action, bootstrap included,
  must pass through here; it enforces `max_actions` (`1 + max_steps +
  max_recoveries`) *independently* of the step counter (proven directly in
  `tests/test_agent_fsm.py::test_action_budget_enforced_independent_of_step_counter`).

Soft limits checked once per iteration (`check_limits()`), any one of which
terminates the run: too many consecutive failed actions, too many consecutive
policy rejections, a detected loop, too many steps without discovering
anything new (stagnation), wall-clock timeout, or an external stop request.
`TerminationReason` records exactly why a run ended.

## Recovery: leaving the allowed domain

Policy blocks known-bad links before they're clicked, but a page can still
redirect somewhere unexpected. If the post-action URL is outside the allowed
domain, the FSM enters `RECOVERING`: `BACK`, then (if that didn't work) `OPEN`
the start URL again — each attempt bound by its own action-budget slot
(`max_recoveries`, separately capped) — and terminates with
`DOMAIN_VIOLATION` if it still can't get back.

## The planner: model → schema → policy → fallback

```
build_planner_prompt(AgentInput) → model.generate(..., schema=AgentAction)
    → parse/validate → PolicyEngine.check()
        allowed?  → return it
        rejected? → feed the reason back, retry (up to planning_attempts)
    → all attempts failed → deterministic fallback_action()
```

The fallback walks `ExplorationMemory.unexplored()` in priority order and
returns the first candidate the policy itself approves — so even if the model
is down, hallucinating, or adversarial, **the agent still makes safe,
policy-checked progress** instead of stalling. `PlanResult.used_fallback` and
`.rejections` are recorded on every step for observability.

## The critic: rules first, LLM second, hard evidence always wins

`rule_checks()` is pure and deterministic: uncaught exceptions and 5xx
responses are **hard evidence** (`Signal.hard=True`); console errors, failed
requests, a blank page, and the prediction's own checkable claims
(`url_contains`, `text_contains`, `expects_navigation`,
`expects_error_feedback`) are checked without any model call. If nothing was
found, the verdict is `as_expected` and the LLM is never invoked — most steps
don't need judgement.

When something *is* found, `CriticAssessment` (structured output) is
requested, but **the LLM cannot dismiss hard evidence**: if it says
`as_expected`/`unexpected_ok` while an uncaught exception or 5xx occurred, the
verdict is forced to at least `suspicious`
(`tests/test_agent_loop.py::test_hard_evidence_cannot_be_dismissed_by_the_critic_llm`).
Conversely it can't invent a bug from nothing: `bug` with zero rule signals
and low confidence/no discrepancies is downgraded to `suspicious`. A
`BugCandidate` is only created for `bug`/`suspicious` at medium+ severity, and
`QAAgent` deduplicates by `(category, url, title)` within a run.

## Wiring it up (`agent.py`)

```python
agent = QAAgent(
    planner_model=GeminiDecisionModel(),   # or any DecisionModel — see planner.py
    critic_model=GeminiDecisionModel(),    # optional; rules alone still work without it
    config=AgentConfig(max_steps=25, allowed_domains=["myapp.example.com"]),
)
result = await agent.run(goal="...", start_url="https://myapp.example.com", executor=BrowserExecutor(session))
```

`to_tool_call(action)` is the **only** bridge from a decision to the browser —
it maps each `ActionType` to one call in the fixed tool set from
`app.browser.tools` (`browser_open`, `browser_click`, …); `FINISH` raises
rather than being sent anywhere. `BrowserExecutor` runs that call through
`BrowserToolbox` (validated args, no JS/Python/shell — see `docs/PERCEPTION.md`
and the browser-engine docs) and returns `PageObservation`/`ExecutionResult`,
never raw Playwright objects.

`AgentRunResult` reports `termination`, every `StepRecord`, every
`BugCandidate`, and run stats (`states_discovered`, `steps_taken`,
`actions_executed`, `recoveries`, `duration_s`). `on_event` receives
`run_started` / `step_planned` / `step_evaluated` / `bug_found` /
`run_finished` for live streaming.

## `POST /api/ai/test` (`mode=agent_decision`)

Exercises the planner's exact prompt/schema/system-instruction path (no
policy layer, no browser) — useful for checking the model follows the schema
and preference ordering before wiring up a live browser session. See
`WINDOWS.md` for `curl.exe` examples.

## Tests

- `tests/test_agent_schema.py` (62 tests) — every valid `ActionType`/argument
  combination is accepted; every malformed target, wrong/missing/extra
  argument, dangerous scheme, out-of-range value, and chain-of-thought
  `reason` is rejected; `.key()` identity; `parse_decision` rejects lists,
  non-JSON, and multi-action payloads.
- `tests/test_agent_policies.py` (53 tests) — one test per safeguard row
  above, plus `detect_cycle` unit cases and hint generation.
- `tests/test_agent_fsm.py` (19 tests) — legal/illegal transitions,
  `TERMINATED` as a sink, every hard limit (steps, actions — proven
  independently of the step counter, recoveries) and every soft limit
  (failures, rejections, loop, stagnation, wall-clock, external stop).
- `tests/test_agent_loop.py` (21 tests) — the full loop against a scripted
  model and a small fake multi-page site (`tests/agent_helpers.py`, no
  browser/network/LLM): reaches `FINISH`; hard step ceiling; ceiling clamped
  regardless of what's requested; policy rejection → fallback progress;
  adversarial/malformed/exception-raising model output never reaches the
  browser; out-of-domain click blocked outright *and* an actual redirect is
  recovered from; identical-action and loop safeguards engage; consecutive
  failures stop the run; bug detection + deduplication; hard evidence
  overrides the critic LLM; expected validation feedback is not a bug;
  `FINISH` never touches the browser; external `stop()`; event emission; slow
  model bounded by `step_timeout_s`.

All 195 tests in the repo pass, including the browser/perception integration
suites exercised against real headless Chromium.
