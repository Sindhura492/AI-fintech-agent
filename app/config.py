from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_username: str = ""  # alternate env name; prefer neo4j_user
    neo4j_password: str = ""
    # Opt-in when a corporate TLS proxy injects a self-signed cert (Aura + MITM).
    neo4j_trust_all: bool = False

    email_address: str = ""
    email_app_password: str = ""
    email_imap_host: str = "imap.gmail.com"

    llama_cloud_api_key: str = ""

    demo_mode: bool = False
    log_level: str = "INFO"

    audit_log_path: str = "audit_log.jsonl"
    metrics_db_path: str = Field(
        default_factory=lambda: str(_PROJECT_ROOT / "data" / "agent_finance.db")
    )

    def resolved_neo4j_user(self) -> str:
        return (self.neo4j_username or self.neo4j_user or "neo4j").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
