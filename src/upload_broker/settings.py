import datetime
from typing import Literal

from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

MIB = 1024 * 1024


class Settings(BaseSettings):
    """Service configuration, read from UPLOAD_BROKER_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="UPLOAD_BROKER_")

    s3_endpoint_url: str | None = None
    """Public endpoint of the S3 server. The presigned URLs point to it."""

    s3_region: str | None = None
    s3_bucket: str
    s3_access_key_id: str
    s3_secret_access_key: SecretStr
    s3_addressing_style: Literal["path", "virtual"] = "path"

    object_prefix: str = ""
    """Prefix of the object keys in the bucket."""

    presign_expiration: datetime.timedelta = Field(
        default=datetime.timedelta(days=7),
        gt=datetime.timedelta(0),
        le=datetime.timedelta(days=7),
    )
    """Lifetime of the tickets and of the presigned URLs. S3 caps it at 7 days."""

    part_size_min: int = Field(default=64 * MIB, ge=5 * MIB)
    max_parts: int = Field(default=1000, ge=1, le=10000)
    """Maximum number of parts of an upload: 1000 on Scaleway, 10000 on AWS."""

    ticket_key: SecretStr = Field(min_length=32)
    """Secret that signs the upload tickets."""

    introspection_url: str
    """Token introspection endpoint of the authorization server (RFC 7662)."""

    client_id: str
    client_secret: SecretStr
    """Credentials of the service at the authorization server."""

    audience: str
    """Audience that the tokens must contain to be accepted."""

    required_scope: str
    """Scope that the tokens must contain to be accepted."""

    introspection_timeout: float = 10
    """Timeout of the introspection requests, in seconds."""

    trusted_proxies: str = "127.0.0.1"
    """Comma-separated addresses or networks whose X-Forwarded-* headers are trusted, or *."""
