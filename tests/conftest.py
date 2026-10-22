import uuid
from collections.abc import Iterator

import httpx2
import pytest
from moto.server import ThreadedMotoServer
from pydantic import SecretStr

from upload_broker.settings import MIB
from upload_broker.settings import Settings
from upload_broker.storage import Part
from upload_broker.storage import PresignedPart
from upload_broker.storage import Storage
from upload_broker.storage import s3_client
from upload_broker.ticket import Owner
from upload_broker.uploads import Uploads

TICKET_KEY = "ticket-key-for-the-tests-0123456789"
SCOPE = "depot:archive:create"
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


@pytest.fixture
def uploads(storage: Storage, settings: Settings) -> Uploads:
    return Uploads(
        storage,
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
