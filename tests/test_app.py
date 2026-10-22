import pytest
from fastapi.testclient import TestClient

from tests.conftest import TICKET_KEY
from upload_broker.app import create_app
from upload_broker.app import create_fastapi
from upload_broker.settings import Settings


def test_health_returns_ok() -> None:
    client = TestClient(create_fastapi())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_served_app_answers_behind_a_trusted_proxy(settings: Settings) -> None:
    settings.trusted_proxies = "testclient"
    client = TestClient(create_app(settings))
    response = client.get("/health", headers={"X-Forwarded-For": "192.0.2.1"})
    assert response.status_code == 200


def test_served_app_reads_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_BROKER_S3_BUCKET", "bucket")
    monkeypatch.setenv("UPLOAD_BROKER_S3_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("UPLOAD_BROKER_S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("UPLOAD_BROKER_TICKET_KEY", TICKET_KEY)
    monkeypatch.setenv("UPLOAD_BROKER_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
