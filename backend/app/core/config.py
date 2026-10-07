"""Central application settings, loaded from environment variables.

Every configurable value used anywhere in the backend must be declared
here — no reading os.environ ad hoc in other modules. This keeps the
Gemini model name, timeouts and infra config auditable in one place.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # -- Gemini --
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_max_output_tokens: int = Field(default=4096, alias="GEMINI_MAX_OUTPUT_TOKENS")
    gemini_request_timeout_seconds: int = Field(default=60, alias="GEMINI_REQUEST_TIMEOUT_SECONDS")

    # -- Database --
    database_url: str = Field(
        default="postgresql+asyncpg://agentqa:change_me@localhost:5432/agentqa",
        alias="DATABASE_URL",
    )

    # -- Redis --
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # -- Backend --
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    backend_cors_origins: str = Field(default="http://localhost:5173", alias="BACKEND_CORS_ORIGINS")
    enable_debug_endpoints: bool = Field(default=False, alias="ENABLE_DEBUG_ENDPOINTS")  # /api/browser, /api/ai: dev only
    auto_create_schema: bool = Field(default=True, alias="AUTO_CREATE_SCHEMA")  # dev convenience; use Alembic in prod
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # -- Agent / exploration defaults --
    default_max_steps: int = Field(default=25, alias="DEFAULT_MAX_STEPS")
    action_timeout_ms: int = Field(default=15000, alias="ACTION_TIMEOUT_MS")
    navigation_timeout_ms: int = Field(default=30000, alias="NAVIGATION_TIMEOUT_MS")
    screenshot_dir: str = Field(default="./data/artifacts/screenshots", alias="SCREENSHOT_DIR")
    dom_snapshot_dir: str = Field(default="./data/artifacts/dom", alias="DOM_SNAPSHOT_DIR")

    trace_dir: str = Field(default="./data/artifacts/traces", alias="TRACE_DIR")

    # -- Agent reasoning engine --
    agent_absolute_max_steps: int = Field(default=200, ge=1, alias="AGENT_ABSOLUTE_MAX_STEPS")
    agent_max_wall_seconds: int = Field(default=900, ge=10, alias="AGENT_MAX_WALL_SECONDS")

    # -- Run limits (MAX_STEPS / MAX_RUNTIME / MAX_DEPTH / MAX_RETRIES) --
    max_steps: int = Field(default=25, ge=1, alias="MAX_STEPS")
    max_runtime_seconds: int = Field(default=600, ge=10, alias="MAX_RUNTIME")
    max_depth: int = Field(default=6, ge=1, alias="MAX_DEPTH")
    max_retries: int = Field(default=1, ge=0, le=5, alias="MAX_RETRIES")
    max_concurrent_browsers: int = Field(default=1, ge=1, le=10, alias="MAX_CONCURRENT_BROWSERS")

    gemini_temperature: float = Field(default=0.4, ge=0.0, le=2.0, alias="GEMINI_TEMPERATURE")

    # -- Security / retention --
    allowed_domains_raw: str = Field(default="", alias="ALLOWED_DOMAINS")  # comma-separated; empty = any public domain
    fix_agent_enabled: bool = Field(default=False, alias="FIX_AGENT_ENABLED")  # candidate-fix suggestions (never edits code)
    max_artifact_size_mb: int = Field(default=200, ge=1, alias="MAX_ARTIFACT_SIZE")  # per run
    max_screenshots_per_run: int = Field(default=150, ge=5, alias="MAX_SCREENSHOTS_PER_RUN")
    run_retention_days: int = Field(default=30, ge=0, alias="RUN_RETENTION_DAYS")  # 0 = keep forever

    # -- Browser --
    browser_max_sessions: int = Field(default=2, ge=1, le=50, alias="BROWSER_MAX_SESSIONS")
    browser_session_ttl_seconds: int = Field(default=900, ge=30, alias="BROWSER_SESSION_TTL_SECONDS")
    browser_max_actions: int = Field(default=200, ge=1, alias="BROWSER_MAX_ACTIONS")
    browser_trace_enabled: bool = Field(default=False, alias="BROWSER_TRACE_ENABLED")
    # Allow loopback/private-network targets (needed to test local apps).
    # Default false (SSRF-safe). Set true only to test local apps. Link-local (cloud metadata) is always blocked.
    browser_allow_private_networks: bool = Field(default=False, alias="BROWSER_ALLOW_PRIVATE_NETWORKS")  # default: blocked (SSRF safe)
    browser_headless: bool = Field(default=True, alias="BROWSER_HEADLESS")
    browser_type: str = Field(default="chromium", alias="BROWSER_TYPE")
    browser_viewport_width: int = Field(default=1440, alias="BROWSER_VIEWPORT_WIDTH")
    browser_viewport_height: int = Field(default=900, alias="BROWSER_VIEWPORT_HEIGHT")

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_domains_raw.split(",") if d.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings are cached — construct once per process."""
    return Settings()
