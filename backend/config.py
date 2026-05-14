"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "parity"
    postgres_user: str = "parity"
    postgres_password: str = ""

    # ── ChromaDB ─────────────────────────────────────────────
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000

    # ── Grafana ──────────────────────────────────────────────
    grafana_url: str = "http://grafana:3000"
    grafana_api_key: str = ""

    # ── pyATS ────────────────────────────────────────────────
    pyats_username: str = ""
    pyats_password: str = ""
    pyats_connect_timeout: int = 60
    pyats_command_timeout: int = 30

    # ── Google Cloud / Gemini (Vertex AI) ────────────────────
    # Auth comes from Application Default Credentials (ADC) — no
    # API key. Run `gcloud auth application-default login` on the
    # host once; the docker-compose backend service mounts the
    # resulting credentials directory into the container so the
    # google-genai SDK picks them up.
    google_genai_use_vertexai: bool = True
    google_cloud_project: str = "parity-dynatrace"
    google_cloud_location: str = "us-central1"
    # Vertex publisher model IDs. Verified working 2026-05-13.
    # *-latest aliases do NOT resolve on Vertex — pin explicit IDs.
    gemini_flash_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-pro"
    gemini_lite_model: str = "gemini-2.5-flash-lite"

    # ── Dynatrace MCP ────────────────────────────────────────
    # Wired in Rewire 3. Defaults to the in-stack stub once it exists.
    dt_mcp_url: str = "http://parity-dt-mcp:8000/mcp"
    dt_environment: str = ""
    dt_platform_token: str = ""
    dt_grail_query_budget_gb: int = 1000

    # ── Jira ─────────────────────────────────────────────────
    jira_url: str = ""  # e.g. https://your-org.atlassian.net
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "PRTY"

    # ── Slack ────────────────────────────────────────────────
    slack_webhook_url: str = ""
    slack_signing_secret: str = ""

    # ── Application ──────────────────────────────────────────
    # Routers every 15 min, switches inherit the same cadence by default
    # (snapshots are cheap; storage is on Cloud SQL). Override per-device
    # via /api/v1/schedules if needed.
    snapshot_schedule_cron: str = "*/15 * * * *"
    inventory_refresh_minutes: int = 60
    approval_expiry_hours: int = 24
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
