import pytest
from fastapi.testclient import TestClient

from upload_broker.app import create_app
from upload_broker.app import create_fastapi
from upload_broker.settings import Settings


def test_health_returns_ok() -> None:
    client = TestClient(create_fastapi())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_served_app_answers_behind_a_trusted_proxy() -> None:
    client = TestClient(create_app(Settings(trusted_proxies="testclient")))
    response = client.get("/health", headers={"X-Forwarded-For": "192.0.2.1"})
    assert response.status_code == 200


def test_served_app_reads_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_BROKER_TRUSTED_PROXIES", "10.0.0.0/8")
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
