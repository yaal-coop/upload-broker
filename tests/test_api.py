from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pytest_iam import Server

from tests.conftest import FakeTribu
from tests.conftest import bearer
from tests.conftest import put_parts
from upload_broker.app import create_fastapi
from upload_broker.settings import MIB
from upload_broker.settings import Settings
from upload_broker.storage import PresignedPart
from upload_broker.storage import s3_client
from upload_broker.ticket import decode_ticket

DATA = b"a" * 5 * MIB + b"b" * 10
OPEN_BODY: dict[str, Any] = {
    "source_id": "workspace-1",
    "size": len(DATA),
    "md5": "0" * 32,
    "title": "Workspace",
    "owner": {
        "email": "owner@example.org",
        "first_name": "Ada",
        "last_name": "Lovelace",
    },
}


def open_upload(
    api: TestClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = api.post("/uploads", json=OPEN_BODY | overrides, headers=headers)
    assert response.status_code == 201
    opened: dict[str, Any] = response.json()
    return opened


def send_parts(
    opened: dict[str, Any], parts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    presigned = [PresignedPart(number=p["number"], url=p["url"]) for p in parts]
    sent = put_parts(presigned, DATA, opened["part_size"])
    return [{"number": part.number, "etag": part.etag} for part in sent]


def test_file_is_uploaded_completed_and_handed_over_to_tribu(
    api: TestClient,
    headers: dict[str, str],
    settings: Settings,
    tribu_server: FakeTribu,
) -> None:
    opened = open_upload(api, headers)
    assert opened["part_size"] == 5 * MIB
    assert [part["number"] for part in opened["parts"]] == [1, 2]

    parts = send_parts(opened, opened["parts"])
    response = api.post(
        "/uploads/complete",
        json={"ticket": opened["ticket"], "parts": parts},
        headers=headers,
    )
    assert response.status_code == 204

    key = decode_ticket(opened["ticket"], settings.ticket_key.get_secret_value()).key
    head = s3_client(settings).head_object(Bucket=settings.s3_bucket, Key=key)
    assert head["ContentLength"] == len(DATA)
    assert [form["source-id"] for form in tribu_server.forms] == ["workspace-1"]


def test_completing_twice_reports_the_archive_already_queued(
    api: TestClient, headers: dict[str, str]
) -> None:
    opened = open_upload(api, headers)
    body = {"ticket": opened["ticket"], "parts": send_parts(opened, opened["parts"])}
    assert api.post("/uploads/complete", json=body, headers=headers).status_code == 204

    response = api.post("/uploads/complete", json=body, headers=headers)
    assert response.status_code == 409
    assert response.json() == {"detail": "already_queued"}


def test_completing_again_after_tribu_was_unavailable_succeeds(
    api: TestClient, headers: dict[str, str], tribu_server: FakeTribu
) -> None:
    tribu_server.failures = [httpx2.Response(503)]
    opened = open_upload(api, headers)
    body = {"ticket": opened["ticket"], "parts": send_parts(opened, opened["parts"])}

    response = api.post("/uploads/complete", json=body, headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "tribu_unavailable"}

    assert api.post("/uploads/complete", json=body, headers=headers).status_code == 204


def test_archive_refused_by_tribu_is_reported(
    api: TestClient, headers: dict[str, str], tribu_server: FakeTribu
) -> None:
    tribu_server.failures = [httpx2.Response(400)]
    opened = open_upload(api, headers)
    body = {"ticket": opened["ticket"], "parts": send_parts(opened, opened["parts"])}

    response = api.post("/uploads/complete", json=body, headers=headers)
    assert response.status_code == 502
    assert response.json() == {"detail": "tribu_rejected"}


def test_resume_returns_only_the_missing_parts(
    api: TestClient, headers: dict[str, str]
) -> None:
    opened = open_upload(api, headers)
    send_parts(opened, opened["parts"][:1])

    response = api.post(
        "/uploads/parts", json={"ticket": opened["ticket"]}, headers=headers
    )

    assert response.status_code == 200
    assert [part["number"] for part in response.json()["parts"]] == [2]


def test_requests_without_token_are_refused(api: TestClient) -> None:
    assert api.post("/uploads", json=OPEN_BODY).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"size": 0},
        {"md5": "not-a-checksum"},
        {"source_id": ""},
        {"owner": {"email": "", "first_name": "Ada", "last_name": "Lovelace"}},
    ],
)
def test_invalid_upload_requests_are_refused(
    api: TestClient, headers: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = api.post("/uploads", json=OPEN_BODY | overrides, headers=headers)
    assert response.status_code == 422


def test_file_too_large_is_refused(
    api: TestClient, headers: dict[str, str], settings: Settings
) -> None:
    settings.max_parts = 1
    small_api = TestClient(create_fastapi(settings))
    response = small_api.post(
        "/uploads", json=OPEN_BODY | {"size": 6 * 1024 * MIB}, headers=headers
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "file_too_large"}


def test_completing_with_missing_parts_is_refused(
    api: TestClient, headers: dict[str, str]
) -> None:
    opened = open_upload(api, headers)
    parts = send_parts(opened, opened["parts"])
    response = api.post(
        "/uploads/complete",
        json={"ticket": opened["ticket"], "parts": parts[:1]},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "parts_mismatch"}


def test_file_of_another_size_than_announced_is_refused(
    api: TestClient, headers: dict[str, str]
) -> None:
    opened = open_upload(api, headers, size=len(DATA) + 1)
    response = api.post(
        "/uploads/complete",
        json={"ticket": opened["ticket"], "parts": send_parts(opened, opened["parts"])},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "size_mismatch"}


def test_invalid_ticket_is_refused(api: TestClient, headers: dict[str, str]) -> None:
    response = api.post("/uploads/parts", json={"ticket": "forged"}, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid_ticket"}


def test_ticket_of_another_user_is_refused(
    api: TestClient,
    headers: dict[str, str],
    iam_server: Server,
    migrator: Any,
    broker: Any,
) -> None:
    opened = open_upload(api, headers)
    other = bearer(iam_server, iam_server.random_user(), migrator, broker)
    response = api.post(
        "/uploads/parts", json={"ticket": opened["ticket"]}, headers=other
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "ticket_owner_mismatch"}


def test_purged_upload_is_not_found(
    api: TestClient, headers: dict[str, str], settings: Settings
) -> None:
    opened = open_upload(api, headers)
    ticket = decode_ticket(opened["ticket"], settings.ticket_key.get_secret_value())
    s3_client(settings).abort_multipart_upload(
        Bucket=settings.s3_bucket, Key=ticket.key, UploadId=ticket.upload_id
    )
    response = api.post(
        "/uploads/parts", json={"ticket": opened["ticket"]}, headers=headers
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "upload_not_found"}
