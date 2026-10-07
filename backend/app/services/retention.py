"""Artifact retention: per-run screenshot/size caps, run expiry, and orphan cleanup.

Evidence is never touched while a run is active: pruning happens in `RunRecorder.finalize`, and expiry only
considers finished runs older than RUN_RETENTION_DAYS (0 = keep forever). Screenshots referenced by a bug or a
graph state are always kept; only unreferenced extras beyond the caps are removed.
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.core.artifacts import to_relative
from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.bug import Bug
from app.models.test_run import TestRun
from app.models.ui_state import UIState

logger = get_logger(__name__)
_FINISHED = ("completed", "failed", "stopped")


def _root() -> Path:
    return Path(get_settings().screenshot_dir).resolve()


async def _referenced(run_id: UUID) -> set[str]:
    async with get_sessionmaker()() as db:
        states = (await db.execute(select(UIState.screenshot_path).where(UIState.test_run_id == run_id))).scalars().all()
        bugs = (await db.execute(select(Bug.screenshot_path).where(Bug.test_run_id == run_id))).scalars().all()
        last = (await db.execute(select(TestRun.last_screenshot).where(TestRun.id == run_id))).scalar_one_or_none()
    return {p for p in (*states, *bugs, last) if p}


def _prune_dirs(dirs: set[str], keep: set[str], max_files: int, max_bytes: int) -> int:
    root, removed = _root(), 0
    files: list[Path] = []
    for d in dirs:
        base = (root / d).resolve()
        if base.parent == root and base.is_dir():
            files += [f for f in base.rglob("*") if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime)  # oldest first
    total = sum(f.stat().st_size for f in files)
    count = len(files)
    for f in files:
        if count <= max_files and total <= max_bytes:
            break
        rel = f.relative_to(root).as_posix()
        if rel in keep:
            continue
        size = f.stat().st_size
        f.unlink(missing_ok=True)
        count, total, removed = count - 1, total - size, removed + 1
    return removed


async def prune_run_screenshots(run_id: UUID, dirs: set[str]) -> int:
    if not dirs:
        return 0
    s = get_settings()
    keep = await _referenced(run_id)
    removed = await asyncio.to_thread(_prune_dirs, dirs, keep, s.max_screenshots_per_run, s.max_artifact_size_mb * 1024 * 1024)
    if removed:
        logger.info("artifacts_pruned", run_id=str(run_id), removed=removed)
    return removed


async def delete_run_artifacts(db, run_id: UUID) -> None:  # noqa: ANN001
    """Remove the screenshot folders used by a run (call before deleting the run row)."""
    paths = await _referenced(run_id)
    dirs = {p.split("/")[0] for p in paths if "/" in p}
    root = _root()
    for d in dirs:
        target = (root / d).resolve()
        if target.parent == root and target.is_dir():
            await asyncio.to_thread(shutil.rmtree, target, True)


async def expire_old_runs() -> int:
    """Delete finished runs older than RUN_RETENTION_DAYS together with their artifacts."""
    days = get_settings().run_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_sessionmaker()() as db:
        runs = (await db.execute(select(TestRun).where(TestRun.status.in_(_FINISHED), TestRun.created_at < cutoff))).scalars().all()
        for r in runs:
            await delete_run_artifacts(db, r.id)
            await db.delete(r)
        await db.commit()
    if runs:
        logger.info("runs_expired", count=len(runs), retention_days=days)
    return len(runs)


async def retention_loop(interval_s: int = 6 * 3600) -> None:
    while True:
        try:
            await expire_old_runs()
        except Exception:  # noqa: BLE001
            logger.warning("retention_failed")
        await asyncio.sleep(interval_s)
