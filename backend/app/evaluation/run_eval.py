"""Evaluate AgentQA against a target with a ground-truth bug list (e.g. the demo shop).

    python -m app.evaluation.run_eval --api http://localhost:8000 --url http://127.0.0.1:8080 \
        --truth ../demo-app/known_bugs.json [--steps 40] [--runtime 300] [--out eval_report.json]

Drives the REAL API (create -> start -> poll), then matches the reported bugs to the known ones by URL path plus
category/keyword. Reports detection rate, false positives (reported bugs matching no known bug), time-to-first-bug
and the run's own metrics. Nothing is simulated; it needs a running backend (and BROWSER_ALLOW_PRIVATE_NETWORKS=true
for a localhost target).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def match(known: dict, bug: dict) -> bool:
    if urlsplit(bug["url"]).path != known["url_path"] and known["url_path"] not in bug["url"]:
        return False
    text = " ".join([bug["title"], bug["description"], bug["actual_behavior"], *bug["evidence"], *bug["network_errors"],
                     *bug["console_errors"]]).lower()
    return bug["category"] in known["categories"] or any(k in text for k in known["keywords"])


def score(truth: list[dict], bugs: list[dict]) -> dict:
    found, matched_bug_ids = {}, set()
    for k in truth:
        hit = next((b for b in bugs if match(k, b)), None)
        found[k["id"]] = bool(hit)
        if hit:
            matched_bug_ids.add(hit["id"])
    detected = sum(found.values())
    fps = [b for b in bugs if not any(match(k, b) for k in truth)]
    by_kind = {kind: [found[k["id"]] for k in truth if k["detectable_by"] == kind] for kind in ("rules", "llm")}
    return {
        "known_bugs": len(truth), "detected": detected, "detection_rate": round(detected / len(truth), 3) if truth else None,
        "detection_rate_rule_detectable": round(sum(by_kind["rules"]) / len(by_kind["rules"]), 3) if by_kind["rules"] else None,
        "detection_rate_llm_detectable": round(sum(by_kind["llm"]) / len(by_kind["llm"]), 3) if by_kind["llm"] else None,
        "found": found, "reported_bugs": len(bugs), "unmatched_reports": [b["title"] for b in fps],
        "false_positive_rate": round(len(fps) / len(bugs), 3) if bugs else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--url", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--goal", default="Thoroughly test the shop: browse, search, log in, register, cart and checkout.")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--runtime", type=int, default=300)
    ap.add_argument("--out")
    a = ap.parse_args()
    truth = json.loads(Path(a.truth).read_text())["bugs"]
    with httpx.Client(base_url=a.api, timeout=30) as c:
        r = c.post("/api/runs", json={"url": a.url, "goal": a.goal, "max_steps": a.steps, "max_runtime_seconds": a.runtime})
        r.raise_for_status()
        rid = r.json()["run_id"]
        c.post(f"/api/runs/{rid}/start").raise_for_status()
        print(f"run {rid} started", file=sys.stderr)
        deadline = time.time() + a.runtime + 120
        while time.time() < deadline:
            run = c.get(f"/api/runs/{rid}").json()
            if run["status"] in ("completed", "failed", "stopped"):
                break
            time.sleep(2)
        bugs = c.get(f"/api/runs/{rid}/bugs").json()
        report = {"run": {k: run[k] for k in ("id", "status", "steps_taken", "states_count", "termination_reason")},
                  "evaluation": c.get(f"/api/runs/{rid}/evaluation").json(), "ground_truth": score(truth, bugs)}
    out = json.dumps(report, indent=2)
    print(out)
    if a.out:
        Path(a.out).write_text(out)
    return 0 if report["run"]["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
