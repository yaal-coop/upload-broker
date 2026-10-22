import datetime
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
import time_machine

from tests.conftest import OWNER
from tests.conftest import TICKET_KEY
from tests.conftest import put_parts
from upload_broker.settings import MIB
from upload_broker.storage import Part
from upload_broker.storage import PartsMismatch
from upload_broker.storage import TooLarge
from upload_broker.storage import UploadNotFound
from upload_broker.ticket import InvalidTicket
from upload_broker.ticket import decode_ticket
from upload_broker.uploads import OpenedUpload
from upload_broker.uploads import TicketOwnerMismatch
from upload_broker.uploads import Uploads

DATA = b"a" * 5 * MIB + b"b" * 10


def open_upload(uploads: Uploads, size: int = len(DATA)) -> OpenedUpload:
    return uploads.open(
        sub="user-1",
        source_id="workspace-1",
        size=size,
        md5="0" * 32,
        title="Workspace",
        owner=OWNER,
    )


def test_open_hands_out_one_url_per_part(uploads: Uploads) -> None:
    opened = open_upload(uploads)

    assert opened.part_size == 5 * MIB
    assert [part.number for part in opened.parts] == [1, 2]
    assert opened.expires_at - datetime.datetime.now(
        datetime.UTC
    ) <= datetime.timedelta(days=7)


def test_open_refuses_files_too_large(uploads: Uploads) -> None:
    uploads.storage.max_parts = 1
    with pytest.raises(TooLarge):
        open_upload(uploads, size=6 * 1024 * MIB)


def test_uploaded_file_is_completed(uploads: Uploads) -> None:
    opened = open_upload(uploads)
    parts = put_parts(opened.parts, DATA, opened.part_size)

    ticket = uploads.complete(opened.ticket, "user-1", parts)

    assert ticket.source_id == "workspace-1"
    assert ticket.owner == OWNER
    head = uploads.storage.client.head_object(
        Bucket=uploads.storage.bucket, Key=ticket.key
    )
    assert head["ContentLength"] == len(DATA)


def test_missing_parts_lists_only_the_parts_not_received(uploads: Uploads) -> None:
    opened = open_upload(uploads)
    put_parts(opened.parts[:1], DATA, opened.part_size)

    missing = uploads.missing_parts(opened.ticket, "user-1")

    assert [part.number for part in missing] == [2]


def test_missing_parts_urls_expire_with_the_ticket(uploads: Uploads) -> None:
    opened = open_upload(uploads)
    with time_machine.travel(datetime.timedelta(days=6), tick=False):
        missing = uploads.missing_parts(opened.ticket, "user-1")

    expires = int(parse_qs(urlsplit(missing[0].url).query)["X-Amz-Expires"][0])
    assert expires <= datetime.timedelta(days=1).total_seconds()


def test_complete_requires_every_part_in_order(uploads: Uploads) -> None:
    opened = open_upload(uploads)
    parts = put_parts(opened.parts, DATA, opened.part_size)
    with pytest.raises(PartsMismatch):
        uploads.complete(opened.ticket, "user-1", parts[:1])


def test_purged_upload_has_no_missing_parts_to_send(uploads: Uploads) -> None:
    opened = open_upload(uploads)
    ticket = decode_ticket(opened.ticket, TICKET_KEY)
    uploads.storage.client.abort_multipart_upload(
        Bucket=uploads.storage.bucket, Key=ticket.key, UploadId=ticket.upload_id
    )
    with pytest.raises(UploadNotFound):
        uploads.missing_parts(opened.ticket, "user-1")


@pytest.mark.parametrize("operation", ["missing_parts", "complete"])
def test_ticket_of_another_subject_is_refused(uploads: Uploads, operation: str) -> None:
    opened = open_upload(uploads)
    arguments: list[object] = [opened.ticket, "user-2"]
    if operation == "complete":
        arguments.append([Part(1, '"0"')])
    with pytest.raises(TicketOwnerMismatch):
        getattr(uploads, operation)(*arguments)


def test_forged_ticket_is_refused(uploads: Uploads) -> None:
    with pytest.raises(InvalidTicket):
        uploads.missing_parts("forged", "user-1")
