"""Application settings.

Settings are read once at startup and passed explicitly into `create_app` and the worker.
There is no module-level singleton: a test that needs a different configuration constructs a
different `Settings` instance rather than mutating global state.

Validation is deliberately strict and happens at construction. A missing API key is cheaper to
discover during startup than halfway through a user's research run.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.errors import ConfigurationError

REPO_ROOT = Path(__file__).resolve().parent.parent


def _blank_to_none(value: object) -> object:
    """Treat a blank .env entry as absent.

    `OPENAI_API_KEY=` in a .env file arrives as an empty string. Without this, an unset key
    would be wrapped as SecretStr('') and satisfy the "is a key configured" check, so the
    failure would surface as a 401 from the provider mid-run instead of at startup.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalSecret = Annotated[SecretStr | None, BeforeValidator(_blank_to_none)]
OptionalStr = Annotated[str | None, BeforeValidator(_blank_to_none)]


class AppEnv(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"
    TEST = "test"
    PRODUCTION = "production"


class LlmProvider(StrEnum):
    SCRIPTED = "scripted"
    OPENAI = "openai"


class EmbeddingProvider(StrEnum):
    HASH = "hash"
    LOCAL = "local"
    OPENAI = "openai"


class ToolsMode(StrEnum):
    LIVE = "live"
    FIXTURES = "fixtures"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = AppEnv.LOCAL
    app_name: str = "Meridian"
    public_base_url: str = "http://localhost:8000"

    # --- Storage -----------------------------------------------------------------
    # Relative SQLite paths resolve under data_dir so the repository root stays clean and
    # the directory can be a Docker volume without touching any URL.
    data_dir: Path = REPO_ROOT / "var"
    database_url: str = "sqlite+aiosqlite:///meridian.db"
    company_database_url: str = "sqlite+aiosqlite:///company.db"
    checkpoint_database_url: str = "sqlite:///checkpoints.db"
    database_echo: bool = False

    redis_url: OptionalStr = None

    # --- Auth --------------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=720, ge=5, le=10_080)

    # --- Model providers ---------------------------------------------------------
    llm_provider: LlmProvider = LlmProvider.SCRIPTED
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: OptionalSecret = None
    openai_model: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)

    embedding_provider: EmbeddingProvider = EmbeddingProvider.HASH
    embedding_model: str = "text-embedding-3-small"
    hash_embedding_dimensions: int = Field(default=512, ge=64, le=4096)
    chroma_dir: Path = Path("chroma")

    # --- Tools -------------------------------------------------------------------
    tools_mode: ToolsMode = ToolsMode.FIXTURES
    fixtures_dir: Path = REPO_ROOT / "tests" / "fixtures"
    tavily_api_key: OptionalSecret = None
    tool_timeout_seconds: float = Field(default=20.0, gt=0)
    tool_max_retries: int = Field(default=2, ge=0, le=5)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0)
    fetch_url_max_bytes: int = Field(default=2_000_000, ge=1024)
    sql_row_limit: int = Field(default=500, ge=1, le=10_000)
    sql_statement_timeout_seconds: float = Field(default=10.0, gt=0)
    tool_cache_ttl_seconds: int = Field(default=900, ge=0)

    # --- Agent budgets (defaults; a run may request lower, never higher) ---------
    max_steps: int = Field(default=12, ge=1, le=50)
    max_tokens: int = Field(default=120_000, ge=1_000)
    max_cost_usd: float = Field(default=0.50, gt=0)
    max_wall_seconds: float = Field(default=300.0, gt=0)
    observation_summary_token_threshold: int = Field(default=8_000, ge=500)

    # --- Worker ------------------------------------------------------------------
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    worker_heartbeat_seconds: float = Field(default=5.0, gt=0)
    # A run is considered stuck once it has missed several heartbeats; the multiplier keeps
    # the reaper from killing a run that is merely inside one slow tool call.
    reaper_missed_heartbeats: int = Field(default=6, ge=2)
    reaper_interval_seconds: float = Field(default=15.0, gt=0)
    graceful_shutdown_seconds: float = Field(default=20.0, gt=0)

    # --- API ---------------------------------------------------------------------
    cors_allow_origins: tuple[str, ...] = ("http://localhost:5173",)
    rate_limit_requests: int = Field(default=120, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    run_rate_limit_per_hour: int = Field(default=60, ge=1)
    frontend_dist_dir: Path = REPO_ROOT / "frontend" / "dist"

    # --- Observability -----------------------------------------------------------
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: OptionalStr = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_scripted(self) -> bool:
        return self.llm_provider is LlmProvider.SCRIPTED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def offline(self) -> bool:
        """True when nothing in this configuration is allowed to touch the network."""
        return (
            self.llm_provider is LlmProvider.SCRIPTED
            and self.tools_mode is ToolsMode.FIXTURES
            and self.embedding_provider is EmbeddingProvider.HASH
        )

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> Self:
        self.data_dir = self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir
        if not self.chroma_dir.is_absolute():
            self.chroma_dir = self.data_dir / self.chroma_dir
        self.database_url = _anchor_sqlite_path(self.database_url, self.data_dir)
        self.company_database_url = _anchor_sqlite_path(self.company_database_url, self.data_dir)
        self.checkpoint_database_url = _anchor_sqlite_path(
            self.checkpoint_database_url, self.data_dir
        )
        return self

    @model_validator(mode="after")
    def _require_credentials_for_remote_providers(self) -> Self:
        # Ollama serves the OpenAI protocol without authentication, so a loopback base URL is
        # the one case where a missing key is legitimate.
        needs_llm_key = (
            self.llm_provider is LlmProvider.OPENAI
            and self.openai_api_key is None
            and not _is_loopback_url(self.openai_base_url)
        )
        if needs_llm_key:
            raise ConfigurationError(
                "LLM_PROVIDER=openai needs OPENAI_API_KEY. Set a free Groq key with "
                "OPENAI_BASE_URL=https://api.groq.com/openai/v1, or run Ollama locally "
                "with OPENAI_BASE_URL=http://localhost:11434/v1."
            )
        if self.embedding_provider is EmbeddingProvider.OPENAI and self.openai_api_key is None:
            raise ConfigurationError(
                "EMBEDDING_PROVIDER=openai needs OPENAI_API_KEY. Use EMBEDDING_PROVIDER=hash "
                "to run fully offline."
            )
        return self

    @model_validator(mode="after")
    def _forbid_insecure_production_defaults(self) -> Self:
        if self.app_env is not AppEnv.PRODUCTION:
            return self
        if "change-me" in self.jwt_secret.get_secret_value():
            raise ConfigurationError(
                "APP_ENV=production refuses the development JWT_SECRET. Generate one with "
                '`python -c "import secrets; print(secrets.token_urlsafe(48))"`.'
            )
        if any(origin == "*" for origin in self.cors_allow_origins):
            raise ConfigurationError(
                "APP_ENV=production refuses CORS_ALLOW_ORIGINS=*. List the exact origins."
            )
        return self

    @model_validator(mode="after")
    def _validate_budget_coherence(self) -> Self:
        if self.observation_summary_token_threshold >= self.max_tokens:
            raise ConfigurationError(
                "OBSERVATION_SUMMARY_TOKEN_THRESHOLD must be below MAX_TOKENS, otherwise "
                "summarisation can never trigger before the token budget stops the run."
            )
        return self

    def ensure_directories(self) -> None:
        """Create the writable directories the process needs.

        Called explicitly by the composition root rather than from a validator, because
        constructing settings should stay free of side effects for tests.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.embedding_provider is EmbeddingProvider.LOCAL:
            self.chroma_dir.mkdir(parents=True, exist_ok=True)


def _anchor_sqlite_path(url: str, data_dir: Path) -> str:
    """Rewrite a relative SQLite URL so it resolves under `data_dir`.

    SQLAlchemy resolves relative SQLite paths against the process working directory, which
    differs between `tasks.ps1 dev`, the worker and pytest. Anchoring them means all three
    processes open the same file.
    """
    prefix, separator, path = url.partition(":///")
    if not separator or not prefix.startswith("sqlite"):
        return url
    if path in {"", ":memory:"} or path.startswith(("/", ":memory:")):
        return url
    candidate = Path(path)
    if candidate.is_absolute():
        return url
    return f"{prefix}:///{(data_dir / candidate).as_posix()}"


def _is_loopback_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        host in lowered
        for host in ("//localhost", "//127.0.0.1", "//[::1]", "//host.docker.internal")
    )
