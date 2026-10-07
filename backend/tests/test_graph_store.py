import uuid

import pytest

from app.database import session as db_session
from app.database.base import Base
from app.exploration.store import EdgeWrite, SqlGraphStore, StateWrite
from app.models import Project, TestRun


@pytest.fixture
async def run_id():
    import app.models  # noqa: F401

    async with db_session.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db_session.get_sessionmaker()() as db:
        p = Project(name="t", base_url="http://x.test")
        db.add(p)
        await db.flush()
        r = TestRun(project_id=p.id, goal="g", target_url="http://x.test/")
        db.add(r)
        await db.commit()
        return r.id


def _state(fp, url="http://x.test/", step=0, depth=0):
    return StateWrite(fingerprint=fp, url=url, title="T", step=step, depth=depth, summary="hello",
                      elements=[{"id": "e1", "role": "button", "name": "Go"}], screenshot=None)


async def test_upsert_creates_then_counts_revisits(run_id):
    store = SqlGraphStore(db_session.get_sessionmaker())
    sid, created = await store.upsert_state(run_id, _state("fp1"))
    assert created
    sid2, created2 = await store.upsert_state(run_id, _state("fp1"))
    assert sid2 == sid and not created2
    from sqlalchemy import select
    from app.models import UIState
    async with db_session.get_sessionmaker()() as db:
        row = (await db.execute(select(UIState).where(UIState.id == sid))).scalar_one()
    assert row.visit_count == 2


async def test_transition_links_existing_states_only(run_id):
    store = SqlGraphStore(db_session.get_sessionmaker())
    await store.upsert_state(run_id, _state("a"))
    await store.upsert_state(run_id, _state("b", url="http://x.test/b", step=1, depth=1))
    edge = EdgeWrite("a", "b", 1, "click", "Clicking 'Go'", {}, "Page b loads", "Now at 'B'", "as_expected", "e1")
    assert await store.add_transition(run_id, edge) is not None
    missing = EdgeWrite("a", "zzz", 2, "click", "x", {}, "", "", None)
    assert await store.add_transition(run_id, missing) is None
    assert await store.state_id(uuid.uuid4(), "a") is None
