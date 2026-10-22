import datetime
import uuid
from typing import Annotated
from typing import Any

import pytest
from fastapi import Depends
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_iam import Server

from tests.conftest import SCOPE
from upload_broker.auth import AudienceIntrospectTokenValidator
from upload_broker.auth import BearerAuthentication
from upload_broker.settings import Settings


@pytest.fixture
def broker(iam_server: Server) -> Any:
    """Register the upload-broker client at the authorization server."""
    client = iam_server.models.Client(
        client_id=str(uuid.uuid4()),
        client_secret=str(uuid.uuid4()),
        token_endpoint_auth_method="client_secret_basic",
    )
    iam_server.backend.save(client)
    return client


@pytest.fixture
def migrator(iam_server: Server) -> Any:
    """Register the client that obtains tokens for the users."""
    client = iam_server.models.Client(client_id=str(uuid.uuid4()))
    iam_server.backend.save(client)
    return client


@pytest.fixture
def user(iam_server: Server) -> Any:
    return iam_server.random_user()


@pytest.fixture
def validator(iam_server: Server, broker: Any) -> AudienceIntrospectTokenValidator:
    return AudienceIntrospectTokenValidator(
        f"{iam_server.url}oauth/introspect",
        broker.client_id,
        broker.client_secret,
        audience=broker.client_id,
        timeout=5,
    )


@pytest.fixture
def client(validator: AudienceIntrospectTokenValidator) -> TestClient:
    app = FastAPI()
    authentication = BearerAuthentication(validator, SCOPE)

    @app.get("/subject")
    def subject(sub: Annotated[str, Depends(authentication)]) -> str:
        return sub

    return TestClient(app)


def bearer(
    iam_server: Server, user: Any, migrator: Any, broker: Any, **overrides: Any
) -> dict[str, str]:
    values: dict[str, Any] = {
        "audience": [migrator, broker],
        "scope": ["openid", SCOPE],
    }
    token = iam_server.random_token(
        subject=user, client=migrator, **(values | overrides)
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_valid_token_gives_its_subject(
    client: TestClient, iam_server: Server, user: Any, migrator: Any, broker: Any
) -> None:
    response = client.get(
        "/subject", headers=bearer(iam_server, user, migrator, broker)
    )
    assert response.status_code == 200
    assert response.json() == user.user_name


def test_missing_token_is_refused(client: TestClient) -> None:
    response = client.get("/subject")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_unknown_token_is_refused(client: TestClient) -> None:
    response = client.get("/subject", headers={"Authorization": "Bearer unknown"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_token"}


def test_expired_token_is_refused(
    client: TestClient, iam_server: Server, user: Any, migrator: Any, broker: Any
) -> None:
    issued = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    headers = bearer(iam_server, user, migrator, broker, issue_date=issued)
    assert client.get("/subject", headers=headers).status_code == 401


def test_revoked_token_is_refused(
    client: TestClient, iam_server: Server, user: Any, migrator: Any, broker: Any
) -> None:
    revoked = datetime.datetime.now(datetime.UTC)
    headers = bearer(iam_server, user, migrator, broker, revokation_date=revoked)
    assert client.get("/subject", headers=headers).status_code == 401


def test_token_meant_for_another_service_is_refused(
    client: TestClient, iam_server: Server, user: Any, migrator: Any, broker: Any
) -> None:
    headers = bearer(iam_server, user, migrator, broker, audience=[migrator])
    assert client.get("/subject", headers=headers).status_code == 401


def test_token_without_the_service_audience_is_refused(
    client: TestClient,
    validator: AudienceIntrospectTokenValidator,
    iam_server: Server,
    user: Any,
    migrator: Any,
    broker: Any,
) -> None:
    validator.audience = "another-service"
    headers = bearer(iam_server, user, migrator, broker)
    assert client.get("/subject", headers=headers).status_code == 401


def test_token_with_a_single_audience_string_is_accepted(
    validator: AudienceIntrospectTokenValidator,
) -> None:
    token = {"active": True, "scope": SCOPE, "aud": "upload-broker", "sub": "user"}
    validator.audience = "upload-broker"
    validator.validate_token(token, [SCOPE], None)


def test_token_without_subject_is_refused(
    client: TestClient, iam_server: Server, migrator: Any, broker: Any
) -> None:
    token = iam_server.random_token(
        subject=None, client=migrator, audience=[broker], scope=[SCOPE]
    )
    headers = {"Authorization": f"Bearer {token.access_token}"}
    assert client.get("/subject", headers=headers).status_code == 401


def test_token_without_the_required_scope_is_refused(
    client: TestClient, iam_server: Server, user: Any, migrator: Any, broker: Any
) -> None:
    headers = bearer(iam_server, user, migrator, broker, scope=["openid"])
    response = client.get("/subject", headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient_scope"}


def test_wrong_service_credentials_make_the_service_unavailable(
    client: TestClient,
    validator: AudienceIntrospectTokenValidator,
    iam_server: Server,
    user: Any,
    migrator: Any,
    broker: Any,
) -> None:
    validator.client.client_secret = "wrong"
    headers = bearer(iam_server, user, migrator, broker)
    assert client.get("/subject", headers=headers).status_code == 503


def test_validator_reads_its_settings(settings: Settings) -> None:
    validator = AudienceIntrospectTokenValidator.from_settings(settings)
    assert validator.introspection_url == settings.introspection_url
    assert validator.audience == settings.audience
