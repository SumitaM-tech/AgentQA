# Perception layer (`backend/app/perception/`)

The agent understands a page from **many signals**, not a screenshot alone. The
perception layer turns a live Playwright page into a structured
`PageObservation`, and a compact, sanitized, size-bounded view of it for Gemini.

```
Playwright page ──► observe_page() ──► PageObservation (full, typed)
                        │                    │
   window.__agentqa     │                    ├─► to_prompt_text()   compact text for Gemini
   (fixed in-page JS)   │                    ├─► to_compact_dict()  compact JSON (tool result)
   telemetry drains     │                    └─► gemini_context()   kwargs for GeminiService
                        ▼
                 ElementRegistry ──► ElementResolver ──► verified Locator (used by actions)
```

## Signals

| # | Signal | Where it comes from | Field |
|---|---|---|---|
| 1 | Screenshot | `page.screenshot` (failure-tolerant) | `screenshot_path` |
| 2 | Accessibility info | `aria_snapshot()`, values stripped | `accessibility_tree` |
| 3 | DOM metadata | in-page script: lang, meta description, headings, landmarks, forms, link/image/iframe counts, missing `alt`, node count, hidden-element count, modal open | `dom_metadata` |
| 4 | Interactive elements | in-page script (shadow DOM aware, clickable-div heuristic) | `interactive_elements` |
| 5 | URL | `page.url` | `url` |
| 6 | Title | `page.title()` | `title` |
| 7 | Visible text | rendered `innerText` (excludes `display:none`) | `visible_text` |
| 8 | Console errors | `console.error`, deduplicated with counts | `console_errors` |
| 9 | Network failures | failed requests + HTTP ≥ 400, query strings stripped, 5xx ranked first | `network_errors` |
| 10 | Browser exceptions | uncaught exceptions / unhandled rejections | `browser_exceptions` |

Also: `observation_id`, `timestamp`, `viewport` (size, scroll, page size, DPR),
`page_load_state` (`loading` → `domcontentloaded` → `load` → `networkidle`),
`dialogs`, `state_fingerprint` (URL path + title + element fingerprints, for
exploration-graph dedup), `truncation` (what was cut) and `warnings`.

Console/network/exception telemetry is reported **once, since the previous
observation**, so the agent sees what its last action caused.

## Interactive elements

Each `PageElement` has: `id`, `role`, `tag`, `name` (computed accessible name),
`text`, `aria_label`, `placeholder`, `value`, `input_type`, `href`, `visible`,
`in_viewport`, `enabled`, `checked`, `required`, `readonly`, `focused`,
`bounding_box` (viewport CSS px), `selector_strategy` + `fallback_strategies`,
`fingerprint`, `landmark`, `context`.

Only **visible** elements are returned (hidden ones are counted in
`dom_metadata.interactive_hidden`). Visibility follows Playwright's definition
(non-empty box, not `visibility:hidden`/`display:none`). If more than
`max_elements` are found, off-screen and disabled elements are dropped first and
`truncation.elements_omitted` says how many.

## Stable element identifiers

CSS selectors and DOM position are fragile in dynamic apps (re-renders, hashed
class names, generated ids). So the id is a **hash of a semantic fingerprint**:

```
role | tag | input type | normalized accessible name (lower-case, digits → #) |
name attr | data-testid (or a non-generated id) | link path | nearest landmark
```

- `e3fa91c` — 6 hex chars; the same element gets the same id across
  re-observation, re-render, reload and even a new browser session.
- Digits are masked, so `Cart (0)` → `Cart (1)` keeps its id.
- Class names, generated ids (`btn-482913`, `:r1:`, hex blobs) and pixel
  positions never contribute.
- **Identical elements** (one "Add to cart" per product) get a suffix. When each
  one sits in a row/list item with distinct heading text, the suffix is a hash of
  that **row context** (`e283552.2f86`) so ids survive reordering and insertion;
  otherwise it is a DOM-order ordinal (`.2`, `.3`).
- Known limits: an element whose accessible name genuinely changes gets a new id
  (re-observe); ordinal ids shift if identical, context-less siblings are
  inserted before them; iframes are not traversed (`iframe_count` is reported).

### Selector strategies (not CSS-first)

Each element carries an ordered list; the primary is the first strategy that is
unique on the page:

`testid` → `id` (non-generated only) → `role`+name → `label` → `placeholder` →
`text` → `css` (structural path, last resort, `fragile: true`). Non-unique
strategies carry an `nth`.

### Resolution and safety (`resolver.py`)

`ElementResolver.locate(page, id)`:
1. fast path: the `data-agentqa-id` attribute written at observation time;
2. otherwise walk the strategies above.

**Every candidate is verified against the recorded fingerprint (and row context)
before use.** A DOM node that was recycled to show something else is rejected
with `element_not_found` ("call browser_get_page_state to refresh") instead of
being clicked. Set `ObservationLimits.tag_dom=False` to stop writing attributes
to the page under test; strategies alone then resolve elements.

## Sanitization and truncation (`sanitize.py`, `ObservationLimits`)

Page content is untrusted input. Before anything reaches Gemini:

- **Invisible characters removed**: control chars, zero-width, bidi overrides,
  Unicode tag characters (used to hide prompt-injection text), private-use.
- **Secrets redacted**: JWTs, AWS/Google/GitHub/`sk-` keys, bearer tokens,
  Luhn-valid card numbers → `[redacted]`.
- **Sensitive field values redacted in the page** (type=password, names/labels
  like `password|token|otp|cvv|ssn|api key`, `autocomplete=cc-*`), so raw values
  never enter the Python process.
- **Accessibility tree**: Playwright's snapshot includes typed values
  (including passwords), so all `textbox`/`combobox`/… values are replaced by
  `[value omitted]` and `/url:` query strings are cut.
- **Untrusted block**: compact text puts all page-derived content between
  `=== UNTRUSTED PAGE CONTENT … ===` / `=== END … ===`; the delimiter inside page
  text is neutralized so it cannot be forged.
- **Bounds** (defaults): 150 elements, 4000 chars visible text, 5000 chars
  accessibility tree, 80 chars per name/value, 15 console / 15 network / 8
  exception entries, 300 chars per message. Truncated text ends with
  `…[+N chars]`; nothing is cut silently (`truncation`).
- **Never raw HTML.** Only extracted fields are used.

## Compact representation for Gemini (`compact.py`)

`to_prompt_text(obs, CompactOptions(max_chars=12000))`:

```
URL / Title / Load / Viewport+scroll [/ modal dialog open]
ISSUES since last observation:  exception / console / network / dialog lines
=== UNTRUSTED PAGE CONTENT ... ===
ELEMENTS (id role "name" ...):
e3fa91c button "Sign in"
e7a6fa2 textbox "Username" [required]
e5a432e textbox "Password" type=password
e283552.2f86 button "Add to cart"
...  (+N more elements omitted)
VISIBLE TEXT: ...
ACCESSIBILITY TREE: ...
=== END UNTRUSTED PAGE CONTENT ===
```

Budget order: header and issues are never dropped; elements get ~55% of the
remainder, visible text ~25%, the accessibility tree whatever is left. On-screen,
enabled elements are preferred when trimming.

Measured on the test app: `index.html` = 5.5k chars raw HTML → 19k chars full
JSON → **3.0k chars (~750 tokens)** compact; `bulk.html` (400 links + long text)
= 42.7k raw HTML → **8.0k chars (~2k tokens)** compact.

`to_compact_dict()` is the same content as JSON and is what the
`browser_get_page_state` tool returns. `gemini_context(obs)` returns kwargs for
`GeminiService.decide_next_action(...)` (URL, title, elements, accessibility
tree, page text, issues). The screenshot is passed separately as an image.

## Using it

```python
async with get_browser_manager().session() as s:
    await s.open_url("http://localhost:3000")
    obs = await s.observe()                 # PageObservation; also refreshes the resolver
    prompt = obs.to_prompt_text()           # compact text for Gemini
    await s.click(obs.interactive_elements[0].id)   # id resolved + verified at action time
```

`POST /api/browser/test` returns the full `observation` plus the exact
`compact_prompt` that would be sent to Gemini.

## Tests

`tests/test_perception.py` (unit + real Chromium against the local **Mini Shop**
app in `tests/fixtures/app/`): all ten signals present; element fields; id
stability across re-render/reload/new session/text change; duplicates surviving
reordering and hitting the correct item; resolver fallback when attributes are
stripped; refusal to act on a recycled node; password/token redaction in every
output (including the accessibility tree); hidden-character and secret
sanitization; forged-delimiter neutralization; truncation limits and prompt size
on a large page; `tag_dom=False`; tool result and Gemini context.

## Not covered yet

iframe contents, closed shadow roots, canvas/WebGL content, and elements that are
only reachable by hover. Legacy `app/perception/observation.py` and
`playwright_driver.py` still feed the older orchestrator until it migrates.
