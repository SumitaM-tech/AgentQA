from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.services.run_manager import get_run_manager

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/health")
async def health() -> dict:
    """Liveness + dependency summary. Never exposes secrets (only whether the Gemini key is set)."""
    s = get_settings()
    db_ok = True
    try:
        async with get_sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unreachable",
            "gemini_configured": bool(s.gemini_api_key), "gemini_model": s.gemini_model,
            "private_networks_allowed": s.browser_allow_private_networks,
            "max_concurrent_browsers": s.max_concurrent_browsers, "environment": s.environment,
            "fix_agent_enabled": s.fix_agent_enabled, "allowed_domains": s.allowed_domains}
