# AgentQA demo shop

**Demo/test application — it contains intentional bugs.** Do not confuse them with real defects.

    python server.py 8080        # http://127.0.0.1:8080

Pages: home, products, product detail, search, login (`demo` / `demo123`), register, cart, checkout, contact.
`known_bugs.json` is the ground truth used by `python -m app.evaluation.run_eval`. Bugs marked `rules` are
deterministic (console error, 404 link, HTTP 500, uncaught exception); bugs marked `llm` (missing validation) need
the Gemini critic and are only found when `GEMINI_API_KEY` is set.
