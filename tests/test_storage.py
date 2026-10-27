import datetime
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from tests.conftest import put_parts
from upload_broker.settings import MIB
from upload_broker.settings import Settings
from upload_broker.storage import MAX_PART_SIZE
from upload_broker.storage import Part
from upload_broker.storage import PartsMismatch
from upload_broker.storage import SizeMismatch
from upload_broker.storage import Storage
from upload_broker.storage import TooLarge
from upload_broker.storage import UploadNotFound
from upload_broker.storage import s3_client

DATA = b"a" * 5 * MIB + b"b" * 10
EXPIRATION = datetime.timedelta(hours=1)


def send(storage: Storage) -> tuple[str, str, list[Part]]:
    """Open an upload and send all its parts."""
    key, upload_id = storage.start("workspace-1")
    part_size = storage.part_size(len(DATA))
    presigned = storage.presign_parts(key, upload_id, [1, 2], EXPIRATION)
    return key, upload_id, put_parts(presigned, DATA, part_size)


def test_client_targets_the_configured_endpoint(settings: Settings) -> None:
    """The S3 client uses the configured endpoint and region."""
    client = s3_client(settings)
    assert client.meta.endpoint_url == settings.s3_endpoint_url
    assert client.meta.region_name == "us-east-1"


@pytest.mark.parametrize(
    ("size", "max_parts", "part_size"),
    [
        (1, 1000, 64 * MIB),
        (64 * MIB * 1000, 1000, 64 * MIB),
        (64 * MIB * 1000 + 1, 1000, 65 * MIB),
        (200 * 1000**3, 1000, 191 * MIB),
    ],
)
def test_part_size_fits_the_file_in_the_allowed_parts(
    storage: Storage, size: int, max_parts: int, part_size: int
) -> None:
    """The part size is the smallest one that fits the file in the allowed number of parts."""
    storage.part_size_min = 64 * MIB
    storage.max_parts = max_parts
    assert storage.part_size(size) == part_size
    assert (size + part_size - 1) // part_size <= max_parts


def test_file_needing_parts_larger_than_5_gib_is_refused(storage: Storage) -> None:
    """Files that need parts larger than 5 GiB are refused."""
    storage.max_parts = 10
    with pytest.raises(TooLarge):
        storage.part_size(MAX_PART_SIZE * 10 + 1)


def test_object_keys_use_the_prefix(storage: Storage) -> None:
    """Object keys start with the configured prefix and end with .zip."""
    storage.prefix = "archives/"
    key, _ = storage.start("workspace-1")
    assert key.startswith("archives/")
    assert key.endswith(".zip")


def test_presigned_urls_target_one_part_each(storage: Storage) -> None:
    """Each presigned URL targets its own part, and expires as requested."""
    key, upload_id = storage.start("workspace-1")
    parts = storage.presign_parts(key, upload_id, [1, 2], EXPIRATION)

    queries = [parse_qs(urlsplit(part.url).query) for part in parts]
    assert [query["partNumber"] for query in queries] == [["1"], ["2"]]
    assert all(query["uploadId"] == [upload_id] for query in queries)
    assert all(query["X-Amz-Expires"] == ["3600"] for query in queries)


def test_complete_assembles_the_parts_sent_by_the_client(storage: Storage) -> None:
    """Completing assembles the parts into an object that keeps the source id in its metadata."""
    key, upload_id, parts = send(storage)
    assert storage.received_parts(key, upload_id) == parts

    storage.complete(key, upload_id, parts, len(DATA))

    head = storage.client.head_object(Bucket=storage.bucket, Key=key)
    assert head["ContentLength"] == len(DATA)
    assert head["Metadata"] == {"source-id": "workspace-1"}


def test_completing_twice_succeeds(storage: Storage) -> None:
    """Completing an upload twice with the same parts succeeds."""
    key, upload_id, parts = send(storage)
    storage.complete(key, upload_id, parts, len(DATA))
    storage.complete(key, upload_id, parts, len(DATA))


def test_completing_again_with_other_parts_fails(storage: Storage) -> None:
    """Completing an upload again with other parts fails."""
    key, upload_id, parts = send(storage)
    storage.complete(key, upload_id, parts, len(DATA))
    with pytest.raises(UploadNotFound):
        storage.complete(key, upload_id, [Part(1, parts[0].etag)], len(DATA))


def test_parts_different_from_the_received_ones_are_refused(storage: Storage) -> None:
    """Parts that differ from the ones the bucket received are refused."""
    key, upload_id, parts = send(storage)
    with pytest.raises(PartsMismatch):
        storage.complete(key, upload_id, [parts[0], Part(2, '"0"')], len(DATA))


def test_object_of_another_size_than_announced_is_refused(storage: Storage) -> None:
    """An assembled object of another size than announced is refused."""
    key, upload_id, parts = send(storage)
    with pytest.raises(SizeMismatch):
        storage.complete(key, upload_id, parts, len(DATA) + 1)


def test_unknown_upload_cannot_be_completed(storage: Storage) -> None:
    """An unknown upload cannot be completed."""
    with pytest.raises(UploadNotFound):
        storage.complete("missing.zip", "unknown", [Part(1, '"0"')], 1)


def test_unknown_upload_has_no_received_parts(storage: Storage) -> None:
    """Listing the parts of an unknown upload fails."""
    with pytest.raises(UploadNotFound):
        storage.received_parts("missing.zip", "unknown")


def test_other_errors_while_listing_parts_are_raised(storage: Storage) -> None:
    """S3 errors other than a missing upload are raised when listing parts."""
    with Stubber(storage.client) as stubber:
        stubber.add_client_error("list_parts", service_error_code="AccessDenied")
        with pytest.raises(ClientError):
            storage.received_parts("archive.zip", "upload-1")


def test_other_errors_while_checking_the_object_are_raised(storage: Storage) -> None:
    """S3 errors other than a missing object are raised when checking the assembled object."""
    with Stubber(storage.client) as stubber:
        stubber.add_client_error("list_parts", service_error_code="NoSuchUpload")
        stubber.add_client_error(
            "head_object", service_error_code="403", http_status_code=403
        )
        with pytest.raises(ClientError):
            storage.complete("archive.zip", "upload-1", [Part(1, '"0"')], 1)
