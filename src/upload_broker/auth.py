from typing import Annotated
from typing import Any

import httpx2
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oauth2.base import OAuth2Error
from authlib.oauth2.rfc6750 import InvalidTokenError
from authlib.oauth2.rfc7662 import IntrospectTokenValidator
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer

from upload_broker.settings import Settings


class AudienceIntrospectTokenValidator(IntrospectTokenValidator):
    """Validate tokens by introspection, and require the service in their audience."""

    def __init__(
        self,
        introspection_url: str,
        client_id: str,
        client_secret: str,
        audience: str,
        timeout: float,
    ) -> None:
        super().__init__()
        self.introspection_url = introspection_url
        self.audience = audience
        self.client = OAuth2Client(
            client_id,
            client_secret,
            token_endpoint_auth_method="client_secret_basic",
            timeout=timeout,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> AudienceIntrospectTokenValidator:
        return cls(
            settings.introspection_url,
            settings.client_id,
            settings.client_secret.get_secret_value(),
            settings.audience,
            settings.introspection_timeout,
        )

    def authenticate_token(self, token_string: str) -> dict[str, Any]:
        return self.introspect_token(token_string)

    def introspect_token(self, token_string: str) -> dict[str, Any]:
        response = self.client.introspect_token(
            self.introspection_url, token=token_string
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def validate_token(
        self, token: dict[str, Any], scopes: list[str], request: object
    ) -> None:
        super().validate_token(token, scopes, request)
        audience = token.get("aud") or []
        if isinstance(audience, str):
            audience = [audience]
        if self.audience not in audience or not token.get("sub"):
            raise InvalidTokenError()


class BearerAuthentication:
    """FastAPI dependency that returns the subject of a valid bearer token."""

    def __init__(self, validator: AudienceIntrospectTokenValidator, scope: str) -> None:
        self.validator = validator
        self.scope = scope

    def __call__(
        self,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(HTTPBearer(auto_error=False)),
        ],
    ) -> str:
        if credentials is None:
            # RFC 6750 §3.1: no error code when the request has no credentials.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            token = self.validator.authenticate_token(credentials.credentials)
            self.validator.validate_token(token, [self.scope], None)

        except OAuth2Error as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.error,
                headers=dict(exc.get_headers()),
            ) from exc

        except httpx2.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="token introspection is unavailable",
            ) from exc

        subject: str = token["sub"]
        return subject
