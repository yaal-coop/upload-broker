import datetime
import hashlib

import httpx2
import pytest
from fastapi.testclient import TestClient

from dev.mock_tribu import create_app
from upload_broker.storage import Storage

DATA = b"0123456789"
SECRET_KEY = "mock-tribu-secret-key"
HOUR = datetime.timedelta(hours=1)


@pytest.fixture
def mock() -> TestClient:
    """Fake Tribu API."""
    return TestClient(create_app(SECRET_KEY))


@pytest.fixture
def file_url(storage: Storage) -> str:
    """Store a small archive in the bucket, and return its download URL."""
    key = f"{storage.prefix}archive.zip"
    storage.client.put_object(Bucket=storage.bucket, Key=key, Body=DATA)
    return storage.presign_download(key, HOUR)


def fields(file_url: str, **overrides: str) -> dict[str, str]:
    """Return the form fields that upload-broker sends for the archive."""
    return {
        "source-id": "workspace-1",
        "file-url": file_url,
        "file-size": str(len(DATA)),
        "checksum": hashlib.md5(DATA).hexdigest(),
        "title": "Workspace",
        "owner-mail": "owner@example.org",
        "owner-first-name": "Ada",
        "owner-last-name": "Lovelace",
        "secret-key": SECRET_KEY,
    } | overrides


def add(client: TestClient, values: dict[str, str]) -> int:
    """Send the fields as a multipart form, and return the status code."""
    files = {name: (None, value) for name, value in values.items()}
    return client.post("/migration/add", files=files).status_code


def test_archive_is_queued_then_downloaded(mock: TestClient, file_url: str) -> None:
    """The archive is accepted, then downloaded, and listed without the secret key."""
    assert add(mock, fields(file_url)) == 201
    assert mock.get("/migrations").json() == [
        {
            "source_id": "workspace-1",
            "file_url": file_url,
            "file_size": len(DATA),
            "checksum": hashlib.md5(DATA).hexdigest(),
            "title": "Workspace",
            "owner_mail": "owner@example.org",
            "owner_first_name": "Ada",
            "owner_last_name": "Lovelace",
            "status": "downloaded",
        }
    ]


def test_wrong_secret_key_is_forbidden(mock: TestClient, file_url: str) -> None:
    """An archive sent with another secret key is refused and not recorded."""
    assert add(mock, fields(file_url, **{"secret-key": "wrong"})) == 403
    assert mock.get("/migrations").json() == []


@pytest.mark.parametrize(
    "name",
    [
        "source-id",
        "file-url",
        "file-size",
        "checksum",
        "title",
        "owner-mail",
        "owner-first-name",
        "owner-last-name",
    ],
)
def test_missing_field_is_a_bad_request(
    mock: TestClient, file_url: str, name: str
) -> None:
    """Every field of the contract is required."""
    values = fields(file_url)
    del values[name]
    assert add(mock, values) == 400


def test_empty_field_is_a_bad_request(mock: TestClient, file_url: str) -> None:
    """Fields of the contract cannot be empty."""
    assert add(mock, fields(file_url, title="")) == 400


@pytest.mark.parametrize("size", ["ten", "-1"])
def test_size_must_be_a_natural_number(
    mock: TestClient, file_url: str, size: str
) -> None:
    """The file size is a number of bytes."""
    assert add(mock, fields(file_url, **{"file-size": size})) == 400


def test_unknown_file_is_a_bad_request(mock: TestClient, storage: Storage) -> None:
    """A URL that does not lead to a file is refused."""
    url = storage.presign_download("missing.zip", HOUR)
    assert add(mock, fields(url)) == 400


def test_unreachable_file_is_a_bad_request(file_url: str) -> None:
    """A URL whose server cannot be reached is refused."""

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable", request=request)

    client = TestClient(
        create_app(SECRET_KEY, transport=httpx2.MockTransport(unreachable))
    )
    assert add(client, fields(file_url)) == 400


def test_same_source_twice_is_a_conflict(mock: TestClient, file_url: str) -> None:
    """A source already in migration cannot be added again."""
    assert add(mock, fields(file_url)) == 201
    assert add(mock, fields(file_url)) == 409


def test_wrong_size_is_not_acceptable(mock: TestClient, file_url: str) -> None:
    """An archive whose real size differs from the announced one is refused."""
    assert add(mock, fields(file_url, **{"file-size": str(len(DATA) + 1)})) == 406
    assert mock.get("/migrations").json() == []


def test_wrong_checksum_is_recorded(mock: TestClient, file_url: str) -> None:
    """An archive with another MD5 is accepted, then marked as mismatching."""
    assert add(mock, fields(file_url, checksum="0" * 32)) == 201
    assert mock.get("/migrations").json()[0]["status"] == "checksum_mismatch"


def test_failed_download_is_recorded() -> None:
    """An archive whose download fails after the size check is marked as failed."""

    def size_only(request: httpx2.Request) -> httpx2.Response:
        if "Range" in request.headers:
            return httpx2.Response(
                206,
                headers={"Content-Range": f"bytes 0-0/{len(DATA)}"},
                content=DATA[:1],
            )
        return httpx2.Response(500)

    client = TestClient(
        create_app(SECRET_KEY, transport=httpx2.MockTransport(size_only))
    )
    assert add(client, fields("http://s3.test/archive.zip")) == 201
    assert client.get("/migrations").json()[0]["status"] == "download_failed"


def test_queued_failures_are_answered_in_order(mock: TestClient, file_url: str) -> None:
    """Queued statuses answer the next requests, then normal handling resumes."""
    assert mock.post("/failures", json={"status": 503}).status_code == 204
    assert mock.post("/failures", json={"status": 400}).status_code == 204
    statuses = [add(mock, fields(file_url)) for _ in range(3)]
    assert statuses == [503, 400, 201]


def test_failure_queue_can_be_emptied(mock: TestClient, file_url: str) -> None:
    """Emptying the queue restores normal handling."""
    mock.post("/failures", json={"status": 503})
    assert mock.delete("/failures").status_code == 204
    assert add(mock, fields(file_url)) == 201


@pytest.mark.parametrize("status", [42, 600])
def test_queued_failure_must_be_an_http_status(mock: TestClient, status: int) -> None:
    """Only HTTP statuses can be queued."""
    assert mock.post("/failures", json={"status": status}).status_code == 422


def test_migrations_can_be_forgotten(mock: TestClient, file_url: str) -> None:
    """Forgetting the migrations allows the same source to be added again."""
    add(mock, fields(file_url))
    assert mock.delete("/migrations").status_code == 204
    assert mock.get("/migrations").json() == []
    assert add(mock, fields(file_url)) == 201


def test_health(mock: TestClient) -> None:
    """The health check answers without authentication."""
    response = mock.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_secret_key_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, file_url: str
) -> None:
    """Without an explicit key, the key comes from MOCK_TRIBU_SECRET_KEY."""
    monkeypatch.setenv("MOCK_TRIBU_SECRET_KEY", "from-env")
    client = TestClient(create_app())
    assert add(client, fields(file_url, **{"secret-key": "from-env"})) == 201
