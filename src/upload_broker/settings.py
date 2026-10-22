from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, read from UPLOAD_BROKER_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="UPLOAD_BROKER_")

    trusted_proxies: str = "127.0.0.1"
    """Comma-separated addresses or networks whose X-Forwarded-* headers are trusted, or *."""
