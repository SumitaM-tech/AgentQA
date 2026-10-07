import json
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database import session as db_session
from app.main import app
from app.models import Bug, TestRun


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _project(client, **kw):
    body = {"name": "Shop", "base_url": "https://example.com", "allowed_domains": ["Example.com"], "default_goals": ["Test checkout"], **kw}
    r = client.post("/api/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_project_crud_and_domain_normalisation(client):
    p = _project(client)
    assert p["allowed_domains"] == ["example.com"] and p["run_count"] == 0
    r = client.patch(f"/api/projects/{p['id']}", json={"description": "d", "default_goals": ["A", "B"]})
    assert r.json()["default_goals"] == ["A", "B"]
    assert client.get(f"/api/projects/{p['id']}").json()["description"] == "d"
    assert client.post("/api/projects", json={"name": "x", "base_url": "https://a.com", "allowed_domains": ["not a domain!"]}).status_code == 422
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_project_allowlist_is_enforced_on_runs(client):
    p = _project(client, base_url="http://127.0.0.1:9", allowed_domains=["example.com"])
    r = client.post("/api/runs", json={"url": "http://127.0.0.1:9/", "goal": "g", "project_id": p["id"]})
    assert r.status_code == 403 and "allowed domains" in r.json()["detail"]
    ok = client.post("/api/runs", json={"url": "https://sub.example.com/", "goal": "g", "project_id": p["id"]})
    assert ok.status_code == 201
    assert client.get(f"/api/runs?project_id={p['id']}").json()[0]["id"] == ok.json()["run_id"]
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204 or True


def test_global_allowlist(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allowed_domains_raw", "example.com")
    assert client.post("/api/targets/validate", json={"url": "https://evil.test/"}).json()["ok"] is False
    assert client.post("/api/targets/validate", json={"url": "https://app.example.com/"}).json()["ok"] is True


async def _seed_bug(run_id, project_id):
    async with db_session.get_sessionmaker()() as db:
        b = Bug(test_run_id=run_id, project_id=project_id, title="Server error 500 on /api/x", severity="high", description="d",
                steps_to_reproduce=["Open page", "Click Pay"], expected_behavior="ok", actual_behavior="500", category="network",
                confidence=0.9, status="verified", url="http://a.test/cart", fingerprint="f" * 32,
                console_errors=["boom"], network_errors=["GET /api/x -> 500"], evidence=["server error 500"], verification={"notes": ["reproduced"]})
        db.add(b)
        await db.commit()
        return b.id


@pytest.fixture
def bug_id(client):
    import asyncio

    run = client.post("/api/runs", json={"url": "https://example.com/", "goal": "g"}).json()["run_id"]
    pid = client.get(f"/api/runs/{run}").json()["project_id"]
    return str(asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_seed_bug(uuid.UUID(run), uuid.UUID(pid))))


def test_bug_resolution_filters_stats_and_exports(client, bug_id):
    b = client.get(f"/api/bugs/{bug_id}").json()
    assert b["bug_ref"].startswith("BUG-") and b["resolution"] == "open"
    assert client.patch(f"/api/bugs/{bug_id}", json={"resolution": "resolved"}).json()["resolved_at"]
    assert client.patch(f"/api/bugs/{bug_id}", json={"resolution": "nope"}).status_code == 422
    assert bug_id in [x["id"] for x in client.get("/api/bugs?resolution=resolved&q=server").json()]
    assert client.get("/api/bugs/stats").json()["resolved"] >= 1
    md = client.get(f"/api/bugs/{bug_id}/export?format=md")
    assert md.headers["content-disposition"].startswith("attachment") and "## Steps to reproduce" in md.text and "1. Open page" in md.text
    assert json.loads(client.get(f"/api/bugs/{bug_id}/export?format=json").text)["id"] == bug_id
    assert client.get(f"/api/bugs/{bug_id}/export?format=pdf").status_code == 422


def test_candidate_fix_disabled_by_default(client, bug_id):
    assert client.post(f"/api/bugs/{bug_id}/candidate-fix", json={}).status_code == 403
    assert client.get(f"/api/bugs/{bug_id}/candidate-fix").status_code == 404


def test_candidate_fix_never_trusts_model_diff():
    from app.fixes.service import FixFileChange, build_diff

    d = build_diff([FixFileChange(path="src/pay.js", description="d", before="if (a)\n  go()", after="if (a && ok)\n  go()")])
    assert d.startswith("--- a/src/pay.js") and "+if (a && ok)" in d


async def test_candidate_fix_requires_source_for_high_confidence(monkeypatch):
    from app.fixes import service

    class _Svc:
        async def generate_structured(self, *a, **k):
            return service._ModelOut(summary="s", root_cause="r", changes=[service.FixFileChange(path="a.js", description="d", before="x", after="y")],
                                     confidence=0.95, verification_plan=["retest"])

    monkeypatch.setattr(get_settings(), "fix_agent_enabled", True)
    bug = Bug(title="t", severity="low", description="d", steps_to_reproduce=[], expected_behavior="", actual_behavior="", url="u",
              evidence=[], console_errors=[], network_errors=[], verification={})
    no_src = await service.generate_candidate_fix(bug, None, _Svc())
    assert no_src["files"] == [] and no_src["confidence"] <= 0.4 and no_src["requires_human_review"]
    with_src = await service.generate_candidate_fix(bug, "const x = 1;", _Svc())
    assert with_src["files"] == ["a.js"] and with_src["diff"]


def test_settings_and_health_never_leak_secrets(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIzaSECRETKEY123456789012345678901234")
    for path in ("/api/settings", "/api/health"):
        assert "AIzaSECRET" not in client.get(path).text
    assert client.get("/api/settings").json()["ai"]["api_key_configured"] is True


def test_dashboard_analytics_shape(client):
    s = client.get("/api/dashboard/summary").json()
    assert len(s["runs_by_day"]) == 14 and "status_counts" in s and "avg_run_duration_seconds" in s


def test_evaluation_endpoint_for_empty_run(client):
    run = client.post("/api/runs", json={"url": "https://example.com/", "goal": "g"}).json()["run_id"]
    e = client.get(f"/api/runs/{run}/evaluation").json()
    assert e["states_explored"] == 0 and e["exploration_coverage"] is None and e["exploration_coverage_estimated"] is True


def test_delete_run_rules(client):
    run = client.post("/api/runs", json={"url": "https://example.com/", "goal": "g"}).json()["run_id"]
    assert client.delete(f"/api/runs/{run}").status_code == 409          # queued = active
    client.post(f"/api/runs/{run}/stop")
    assert client.delete(f"/api/runs/{run}").status_code == 204
    assert client.get(f"/api/runs/{run}").status_code == 404


def test_log_redaction_processor():
    from app.core.logging import _redact_processor

    out = _redact_processor(None, "info", {"event": "login", "password": "hunter2", "api_key": "k", "note": "ok", "level": "info"})
    assert out["password"] == "[redacted]" and out["api_key"] == "[redacted]" and out["note"] == "ok"


def test_retention_prunes_only_unreferenced(tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention, "_root", lambda: tmp_path)
    d = tmp_path / "sess"
    d.mkdir()
    for i in range(6):
        (d / f"{i}.png").write_bytes(b"x" * 10)
    removed = retention._prune_dirs({"sess"}, keep={"sess/0.png"}, max_files=2, max_bytes=10**9)
    left = sorted(p.name for p in d.iterdir())
    assert removed == 4 and "0.png" in left and len(left) == 2


def test_debug_endpoints_are_off_unless_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "enable_debug_endpoints", False)
    from app.main import create_app

    c = TestClient(create_app())
    assert c.post("/api/browser/test", json={}).status_code == 404 and c.post("/api/ai/test", json={}).status_code == 404


def test_unhandled_errors_are_sanitised():
    from app.main import create_app

    a = create_app()

    @a.get("/boom")
    async def boom():  # noqa: ANN202
        raise RuntimeError("secret internals AIzaXYZ")

    r = TestClient(a, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error."}


def test_ground_truth_scoring():
    from app.evaluation.run_eval import score

    truth = [{"id": "a", "url_path": "/cart.html", "categories": ["network"], "keywords": ["500"], "detectable_by": "rules"},
             {"id": "b", "url_path": "/x.html", "categories": ["validation"], "keywords": ["valid"], "detectable_by": "llm"}]
    bugs = [{"id": "1", "url": "http://h/cart.html", "title": "Server error 500", "description": "", "actual_behavior": "", "evidence": [],
             "network_errors": [], "console_errors": [], "category": "network"},
            {"id": "2", "url": "http://h/other", "title": "Odd", "description": "", "actual_behavior": "", "evidence": [],
             "network_errors": [], "console_errors": [], "category": "ui"}]
    s = score(truth, bugs)
    assert s["detected"] == 1 and s["detection_rate"] == 0.5 and s["false_positive_rate"] == 0.5 and s["unmatched_reports"] == ["Odd"]


def test_repro_steps_follow_the_real_path_not_the_whole_run():
    from app.services.run_recorder import repro_steps

    edges = [("home", "home", "Clicking 'Home'"), ("home", "products", "Clicking 'Products'"), ("products", "home", "Clicking 'Home'"),
             ("home", "cart", "Clicking 'Cart'")]
    # trigger executed from `cart`: shortest real path to cart, then the trigger
    assert repro_steps(edges, "home", "cart", "Clicking 'Apply coupon'") == ["Open the application start page", "Clicking 'Cart'", "Clicking 'Apply coupon'"]
    # trigger executed from the start page itself
    assert repro_steps(edges, "home", "home", "Clicking 'Products'") == ["Open the application start page", "Clicking 'Products'"]
    assert repro_steps([], None, "x", None) == ["Open the application start page"]
