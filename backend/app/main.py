"""FastAPI application entrypoint. `uvicorn app.main:app`."""
from __future__ import annotations

from contextlib import asynccontextmanager

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_ai import router as ai_router
from app.api.routes_bugs import router as bugs_router
from app.api.routes_browser import router as browser_router
from app.api.routes_health import router as health_router
from app.api.routes_projects import router as projects_router
from app.api.routes_runs import router as runs_router
from app.api.routes_ws import router as ws_router
from app.browser.manager import get_browser_manager
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.run_manager import get_run_manager

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if settings.auto_create_schema:  # dev convenience; production uses `alembic upgrade head`
        from app.database.base import Base
        from app.database import session as db_session
        import app.models  # noqa: F401 - registers all tables on Base.metadata

        async with db_session.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    from app.core.winloop import windows_loop_problem

    if (problem := windows_loop_problem()):
        logger.error("windows_event_loop_unsupported", fix=problem)
    recovered = await get_run_manager().recover_interrupted()
    if recovered:
        logger.warning("interrupted_runs_marked_failed", count=recovered)
    from app.services.retention import retention_loop

    retention = asyncio.create_task(retention_loop(), name="retention")
    yield
    retention.cancel()
    await get_run_manager().shutdown()
    await get_browser_manager().shutdown()  # always release Chromium on exit


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AgentQA Cloud",
        description="Autonomous QA agent that tests live web applications.",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    app.include_router(bugs_router)
    app.include_router(ws_router)
    if settings.enable_debug_endpoints:  # raw browser/LLM debug APIs: never enabled by default
        app.include_router(ai_router)
        app.include_router(browser_router)
        logger.warning("debug_endpoints_enabled")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """One failing request never leaks internals or takes the server down."""
        logger.error("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    logger.info(
        "app_configured",
        environment=settings.environment,
        gemini_model=settings.gemini_model,
        cors_origins=settings.cors_origins_list,
    )
    return app


app = create_app()
