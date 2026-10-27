import datetime
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit

import httpx2
import pytest
import time_machine

from tests.conftest import OWNER
from tests.conftest import FakeTribu
from tests.conftest import put_parts
from upload_broker.settings import MIB
from upload_broker.storage import Part
from upload_broker.storage import Storage
from upload_broker.tribu import AlreadyQueued
from upload_broker.uploads import OpenedUpload
from upload_broker.uploads import Uploads

DATA = b"a" * 5 * MIB + b"b" * 10
HOUR = datetime.timedelta(hours=1)


def send(uploads: Uploads) -> tuple[OpenedUpload, list[Part]]:
    """Open an upload and send all its parts to the presigned URLs."""
    opened = uploads.open(
        sub="user-1",
        source_id="workspace-1",
        size=len(DATA),
        md5="0" * 32,
        title="Workspace",
        owner=OWNER,
    )
    return opened, put_parts(opened.parts, DATA, opened.part_size)


def stored(storage: Storage) -> str:
    """Store a small object, and return its key."""
    key = f"{storage.prefix}archive.zip"
    storage.client.put_object(Bucket=storage.bucket, Key=key, Body=b"0123456789")
    return key


def tampered(url: str) -> str:
    """Replace the signature of a presigned URL."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query)) | {"X-Amz-Signature": "0" * 64}
    return parts._replace(query=urlencode(query)).geturl()


def test_uploaded_file_is_handed_over_to_tribu(
    uploads: Uploads, tribu_server: FakeTribu
) -> None:
    """Parts sent to the presigned URLs are assembled, and Tribu can download the file."""
    opened, parts = send(uploads)
    uploads.complete(opened.ticket, "user-1", parts)
    assert [form["source-id"] for form in tribu_server.forms] == ["workspace-1"]


def test_completing_twice_recognizes_the_assembled_file(uploads: Uploads) -> None:
    """A second completion recognizes the object that Garage assembled."""
    opened, parts = send(uploads)
    uploads.complete(opened.ticket, "user-1", parts)
    with pytest.raises(AlreadyQueued):
        uploads.complete(opened.ticket, "user-1", parts)


def test_download_url_serves_ranges_but_not_head(storage: Storage) -> None:
    """The download URL serves a byte range, but refuses HEAD requests."""
    url = storage.presign_download(stored(storage), HOUR)
    response = httpx2.get(url, headers={"Range": "bytes=0-0"})
    assert response.status_code == 206
    assert response.headers["Content-Range"] == "bytes 0-0/10"
    assert httpx2.head(url).status_code == 403


def test_tampered_urls_are_refused(storage: Storage) -> None:
    """Upload and download URLs with a modified signature are refused."""
    key, upload_id = storage.start("workspace-1")
    [part] = storage.presign_parts(key, upload_id, [1], HOUR)
    download = storage.presign_download(stored(storage), HOUR)

    assert httpx2.put(tampered(part.url), content=b"a").status_code == 403
    assert httpx2.get(tampered(download)).status_code == 403


def presigned_ago(
    storage: Storage, delay: datetime.timedelta, key: str, upload_id: str
) -> tuple[str, str]:
    """Return a part URL and a download URL, signed for one hour, some time ago."""
    with time_machine.travel(datetime.datetime.now(datetime.UTC) - delay):
        [part] = storage.presign_parts(key, upload_id, [1], HOUR)
        return part.url, storage.presign_download(stored(storage), HOUR)


def test_urls_are_accepted_until_they_expire(storage: Storage) -> None:
    """URLs signed half an hour ago for one hour still work."""
    key, upload_id = storage.start("workspace-1")
    part, download = presigned_ago(storage, HOUR / 2, key, upload_id)
    assert httpx2.put(part, content=b"a").is_success
    assert httpx2.get(download).is_success


def test_expired_urls_are_refused(storage: Storage) -> None:
    """Upload and download URLs are refused once expired."""
    key, upload_id = storage.start("workspace-1")
    part, download = presigned_ago(storage, 2 * HOUR, key, upload_id)
    # AWS answers 403, Garage answers 400.
    assert httpx2.put(part, content=b"a").is_client_error
    assert httpx2.get(download).is_client_error
