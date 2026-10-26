import logging

import httpx2
import pytest

from tests.conftest import OWNER
from tests.conftest import TRIBU_SECRET_KEY
from tests.conftest import FakeTribu
from tests.conftest import parse_form
from upload_broker.ticket import Ticket
from upload_broker.tribu import AlreadyQueued
from upload_broker.tribu import Tribu
from upload_broker.tribu import TribuRejected
from upload_broker.tribu import TribuUnavailable

TICKET = Ticket(
    sub="user-1",
    exp=0,
    key="archive.zip",
    upload_id="upload-1",
    size=1234,
    md5="0" * 32,
    part_size=1234,
    source_id="workspace-1",
    title="Workspace",
    owner=OWNER,
)
FILE_URL = "https://s3.example.org/bucket/archive.zip?X-Amz-Signature=0"


def answering(response: httpx2.Response | httpx2.HTTPError) -> Tribu:
    """Build a client of a Tribu server that gives a single answer."""
    server = FakeTribu()
    server.failures = [response]
    return Tribu(
        "http://tribu.test/api",
        TRIBU_SECRET_KEY,
        timeout=1,
        transport=httpx2.MockTransport(server),
    )


def test_archive_is_sent_as_a_form_with_the_secret_key(
    tribu: Tribu, tribu_server: FakeTribu
) -> None:
    tribu_server.failures = [httpx2.Response(201)]
    tribu.add(TICKET, FILE_URL)

    request = tribu_server.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://tribu.test/api/migration/add"
    assert request.headers["Content-Type"].startswith("multipart/form-data;")
    assert "Authorization" not in request.headers
    assert parse_form(request) == {
        "source-id": "workspace-1",
        "file-url": FILE_URL,
        "file-size": "1234",
        "checksum": "0" * 32,
        "title": "Workspace",
        "owner-mail": OWNER.email,
        "owner-first-name": OWNER.first_name,
        "owner-last-name": OWNER.last_name,
        "secret-key": TRIBU_SECRET_KEY,
    }


@pytest.mark.parametrize("status_code", [200, 201, 204])
def test_successful_answers_are_accepted(status_code: int) -> None:
    answering(httpx2.Response(status_code)).add(TICKET, FILE_URL)


def test_source_already_in_migration_is_reported() -> None:
    with pytest.raises(AlreadyQueued):
        answering(httpx2.Response(409)).add(TICKET, FILE_URL)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 406])
def test_refused_archives_are_reported_and_logged(
    status_code: int, caplog: pytest.LogCaptureFixture
) -> None:
    tribu = answering(httpx2.Response(status_code, text="invalid owner"))
    with caplog.at_level(logging.WARNING), pytest.raises(TribuRejected):
        tribu.add(TICKET, FILE_URL)

    assert f"Tribu answered {status_code} for workspace-1: invalid owner" in caplog.text
    assert TRIBU_SECRET_KEY not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        httpx2.Response(500),
        httpx2.Response(503),
        httpx2.ConnectError("connection refused"),
        httpx2.ReadTimeout("timed out"),
    ],
)
def test_unavailable_tribu_is_reported(
    failure: httpx2.Response | httpx2.HTTPError,
) -> None:
    with pytest.raises(TribuUnavailable):
        answering(failure).add(TICKET, FILE_URL)
