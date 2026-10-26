import logging

import httpx2

from upload_broker.settings import Settings
from upload_broker.ticket import Ticket

logger = logging.getLogger(__name__)


class TribuError(Exception):
    pass


class AlreadyQueued(TribuError):
    """Tribu already has a migration in progress for this source."""


class TribuUnavailable(TribuError):
    """Tribu cannot be reached, or failed to answer."""


class TribuRejected(TribuError):
    """Tribu refused the archive."""


class Tribu:
    """Client of the Tribu migration API."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        timeout: float,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.secret_key = secret_key
        self.client = httpx2.Client(base_url=url, timeout=timeout, transport=transport)

    @classmethod
    def from_settings(cls, settings: Settings) -> Tribu:
        return cls(
            settings.tribu_url,
            settings.tribu_secret_key.get_secret_value(),
            settings.tribu_timeout,
        )

    def add(self, ticket: Ticket, file_url: str) -> None:
        """Add the archive to the migration queue of Tribu."""
        fields = {
            "source-id": ticket.source_id,
            "file-url": file_url,
            "file-size": str(ticket.size),
            "checksum": ticket.md5,
            "title": ticket.title,
            "owner-mail": ticket.owner.email,
            "owner-first-name": ticket.owner.first_name,
            "owner-last-name": ticket.owner.last_name,
            "secret-key": self.secret_key,
        }
        try:
            # Fields without file name, as httpx only sends multipart bodies with files.
            response = self.client.post(
                "migration/add",
                files={name: (None, value) for name, value in fields.items()},
            )
        except httpx2.HTTPError as exc:
            logger.warning("Tribu is unavailable for %s: %s", ticket.source_id, exc)
            raise TribuUnavailable from exc

        if response.is_success:
            return

        if response.status_code == httpx2.codes.CONFLICT:
            raise AlreadyQueued

        logger.warning(
            "Tribu answered %s for %s: %s",
            response.status_code,
            ticket.source_id,
            response.text,
        )
        if response.is_server_error:
            raise TribuUnavailable
        raise TribuRejected
