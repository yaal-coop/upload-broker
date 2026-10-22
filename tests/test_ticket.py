import datetime

import pytest
import time_machine
from joserfc import jwt
from joserfc.jwk import OctKey

from tests.conftest import OWNER
from tests.conftest import TICKET_KEY
from upload_broker.ticket import InvalidTicket
from upload_broker.ticket import Ticket
from upload_broker.ticket import decode_ticket
from upload_broker.ticket import encode_ticket

NOW = datetime.datetime(2026, 10, 22, 12, tzinfo=datetime.UTC)


def make_ticket(**overrides: object) -> Ticket:
    values: dict[str, object] = {
        "sub": "user-1",
        "exp": int((NOW + datetime.timedelta(days=7)).timestamp()),
        "key": "archive.zip",
        "upload_id": "upload-1",
        "size": 10,
        "md5": "0" * 32,
        "part_size": 4,
        "source_id": "workspace-1",
        "title": "Workspace",
        "owner": OWNER,
    }
    return Ticket.model_validate(values | overrides)


@time_machine.travel(NOW)
def test_ticket_reads_back_its_content() -> None:
    ticket = make_ticket()
    assert decode_ticket(encode_ticket(ticket, TICKET_KEY), TICKET_KEY) == ticket


@time_machine.travel(NOW)
def test_ticket_signed_with_another_key_is_rejected() -> None:
    value = encode_ticket(make_ticket(), "another-key-for-the-tests-0123456789")
    with pytest.raises(InvalidTicket):
        decode_ticket(value, TICKET_KEY)


def test_expired_ticket_is_rejected() -> None:
    with time_machine.travel(NOW):
        value = encode_ticket(make_ticket(), TICKET_KEY)
    with time_machine.travel(NOW + datetime.timedelta(days=8)):
        with pytest.raises(InvalidTicket):
            decode_ticket(value, TICKET_KEY)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidTicket):
        decode_ticket("not a ticket", TICKET_KEY)


@time_machine.travel(NOW)
def test_signed_ticket_with_missing_fields_is_rejected() -> None:
    value = jwt.encode(
        {"alg": "HS256"},
        {"sub": "user-1", "exp": int(NOW.timestamp()) + 60},
        OctKey.import_key(TICKET_KEY),
    )
    with pytest.raises(InvalidTicket):
        decode_ticket(value, TICKET_KEY)


@pytest.mark.parametrize(("size", "part_count"), [(1, 1), (4, 1), (5, 2), (8, 2)])
def test_part_count_covers_the_whole_file(size: int, part_count: int) -> None:
    assert make_ticket(size=size, part_size=4).part_count == part_count
