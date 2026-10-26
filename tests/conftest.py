import email.parser
import email.policy
import uuid
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer
from pydantic import SecretStr
from pytest_iam import Server

from upload_broker.app import create_fastapi
from upload_broker.settings import MIB
from upload_broker.settings import Settings
from upload_broker.storage import Part
from upload_broker.storage import PresignedPart
from upload_broker.storage import Storage
from upload_broker.storage import s3_client
from upload_broker.ticket import Owner
from upload_broker.tribu import Tribu
from upload_broker.uploads import Uploads

TICKET_KEY = "ticket-key-for-the-tests-0123456789"
SCOPE = "depot:archive:create"
TRIBU_SECRET_KEY = "tribu-secret-key"
OWNER = Owner(email="owner@example.org", first_name="Ada", last_name="Lovelace")


@pytest.fixture(scope="session")
def s3_endpoint_url() -> Iterator[str]:
    """Moto S3 server, so that presigned URLs can be used with real HTTP requests."""
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def settings(s3_endpoint_url: str) -> Settings:
    settings = Settings(
        s3_endpoint_url=s3_endpoint_url,
        s3_region="us-east-1",
        s3_bucket=f"test-{uuid.uuid4()}",
        s3_access_key_id="test",
        s3_secret_access_key=SecretStr("test"),
        ticket_key=SecretStr(TICKET_KEY),
        part_size_min=5 * MIB,
        introspection_url="http://localhost/introspect",
        client_id="upload-broker",
        client_secret=SecretStr("secret"),
        audience="upload-broker",
        required_scope=SCOPE,
        tribu_url="http://tribu.test/api",
        tribu_secret_key=SecretStr(TRIBU_SECRET_KEY),
    )
    s3_client(settings).create_bucket(Bucket=settings.s3_bucket)
    return settings


@pytest.fixture
def storage(settings: Settings) -> Storage:
    return Storage(
        s3_client(settings),
        settings.s3_bucket,
        part_size_min=settings.part_size_min,
        max_parts=settings.max_parts,
    )


class FakeTribu:
    """Tribu migration API, that checks the size of the archives it receives."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.forms: list[dict[str, str]] = []
        self.failures: list[httpx2.Response | httpx2.HTTPError] = []
        """Answers to give before handling the requests normally."""

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, httpx2.HTTPError):
                raise failure
            return failure

        form = parse_form(request)
        if any(f["source-id"] == form["source-id"] for f in self.forms):
            return httpx2.Response(409)

        download = httpx2.get(form["file-url"], headers={"Range": "bytes=0-0"})
        assert download.headers["Content-Range"] == f"bytes 0-0/{form['file-size']}"

        self.forms.append(form)
        return httpx2.Response(201)


def parse_form(request: httpx2.Request) -> dict[str, str]:
    """Read the fields of a multipart/form-data body."""
    headers = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        headers + request.read()
    )
    return {
        part["Content-Disposition"].params["name"]: part.get_content()
        for part in message.iter_parts()
    }


@pytest.fixture
def tribu_server() -> FakeTribu:
    return FakeTribu()


@pytest.fixture
def tribu(settings: Settings, tribu_server: FakeTribu) -> Tribu:
    return Tribu(
        settings.tribu_url,
        settings.tribu_secret_key.get_secret_value(),
        settings.tribu_timeout,
        transport=httpx2.MockTransport(tribu_server),
    )


@pytest.fixture
def uploads(storage: Storage, tribu: Tribu, settings: Settings) -> Uploads:
    return Uploads(
        storage,
        tribu,
        settings.ticket_key.get_secret_value(),
        settings.presign_expiration,
    )


def put_parts(parts: list[PresignedPart], data: bytes, part_size: int) -> list[Part]:
    """Upload the data to the presigned URLs, as the client does."""
    sent = []
    for part in parts:
        offset = (part.number - 1) * part_size
        response = httpx2.put(part.url, content=data[offset : offset + part_size])
        response.raise_for_status()
        sent.append(Part(number=part.number, etag=response.headers["ETag"]))
    return sent


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


def bearer(
    iam_server: Server, user: Any, migrator: Any, broker: Any, **overrides: Any
) -> dict[str, str]:
    """Issue a token to the migrator for the user, and return its header."""
    values: dict[str, Any] = {
        "audience": [migrator, broker],
        "scope": ["openid", SCOPE],
    }
    token = iam_server.random_token(
        subject=user, client=migrator, **(values | overrides)
    )
    return {"Authorization": f"Bearer {token.access_token}"}


@pytest.fixture
def headers(
    iam_server: Server, user: Any, migrator: Any, broker: Any
) -> dict[str, str]:
    """Return the authorization header of a valid token for the user."""
    return bearer(iam_server, user, migrator, broker)


@pytest.fixture
def api(
    settings: Settings, iam_server: Server, broker: Any, tribu: Tribu
) -> TestClient:
    """Return a client of the whole application, authenticated by the test server."""
    settings.introspection_url = f"{iam_server.url}oauth/introspect"
    settings.client_id = broker.client_id
    settings.client_secret = SecretStr(broker.client_secret)
    settings.audience = broker.client_id
    return TestClient(create_fastapi(settings, tribu))
