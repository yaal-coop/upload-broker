import dataclasses
import datetime

from upload_broker.storage import Part
from upload_broker.storage import PartsMismatch
from upload_broker.storage import PresignedPart
from upload_broker.storage import Storage
from upload_broker.ticket import InvalidTicket
from upload_broker.ticket import Owner
from upload_broker.ticket import Ticket
from upload_broker.ticket import decode_ticket
from upload_broker.ticket import encode_ticket


class TicketOwnerMismatch(InvalidTicket):
    """The ticket was issued to another subject."""


@dataclasses.dataclass(frozen=True)
class OpenedUpload:
    ticket: str
    part_size: int
    expires_at: datetime.datetime
    parts: list[PresignedPart]


class Uploads:
    """Upload operations, authorized by signed tickets."""

    def __init__(
        self, storage: Storage, ticket_key: str, expiration: datetime.timedelta
    ) -> None:
        self.storage = storage
        self.ticket_key = ticket_key
        self.expiration = expiration

    def open(
        self,
        sub: str,
        source_id: str,
        size: int,
        md5: str,
        title: str,
        owner: Owner,
    ) -> OpenedUpload:
        """Start an upload and return the URLs of all its parts."""
        part_size = self.storage.part_size(size)
        key, upload_id = self.storage.start(source_id)
        expires_at = (
            datetime.datetime.now(datetime.UTC).replace(microsecond=0) + self.expiration
        )
        ticket = Ticket(
            sub=sub,
            exp=int(expires_at.timestamp()),
            key=key,
            upload_id=upload_id,
            size=size,
            md5=md5,
            part_size=part_size,
            source_id=source_id,
            title=title,
            owner=owner,
        )
        parts = self.storage.presign_parts(
            key, upload_id, list(range(1, ticket.part_count + 1)), self.expiration
        )
        return OpenedUpload(
            ticket=encode_ticket(ticket, self.ticket_key),
            part_size=part_size,
            expires_at=expires_at,
            parts=parts,
        )

    def missing_parts(self, ticket_value: str, sub: str) -> list[PresignedPart]:
        """Return new URLs for the parts the bucket has not received yet.

        The URLs expire with the ticket.
        """
        ticket = self._ticket(ticket_value, sub)
        received = {
            part.number
            for part in self.storage.received_parts(ticket.key, ticket.upload_id)
        }
        missing = [
            number
            for number in range(1, ticket.part_count + 1)
            if number not in received
        ]
        remaining = datetime.datetime.fromtimestamp(
            ticket.exp, datetime.UTC
        ) - datetime.datetime.now(datetime.UTC)
        return self.storage.presign_parts(
            ticket.key, ticket.upload_id, missing, remaining
        )

    def complete(self, ticket_value: str, sub: str, parts: list[Part]) -> Ticket:
        """Assemble the object, and return the ticket for the delivery."""
        ticket = self._ticket(ticket_value, sub)
        if [part.number for part in parts] != list(range(1, ticket.part_count + 1)):
            raise PartsMismatch
        self.storage.complete(ticket.key, ticket.upload_id, parts, ticket.size)
        return ticket

    def _ticket(self, value: str, sub: str) -> Ticket:
        ticket = decode_ticket(value, self.ticket_key)
        if ticket.sub != sub:
            raise TicketOwnerMismatch
        return ticket
