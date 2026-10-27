import datetime
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field

from upload_broker.auth import BearerAuthentication
from upload_broker.storage import Part
from upload_broker.storage import PartsMismatch
from upload_broker.storage import PresignedPart
from upload_broker.storage import SizeMismatch
from upload_broker.storage import TooLarge
from upload_broker.storage import UploadNotFound
from upload_broker.ticket import InvalidTicket
from upload_broker.ticket import Owner
from upload_broker.tribu import AlreadyQueued
from upload_broker.tribu import TribuRejected
from upload_broker.tribu import TribuUnavailable
from upload_broker.uploads import TicketOwnerMismatch
from upload_broker.uploads import Uploads

NonEmpty = Annotated[str, Field(min_length=1)]

ERRORS: dict[type[Exception], tuple[int, str]] = {
    TicketOwnerMismatch: (status.HTTP_403_FORBIDDEN, "ticket_owner_mismatch"),
    InvalidTicket: (status.HTTP_400_BAD_REQUEST, "invalid_ticket"),
    TooLarge: (status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large"),
    PartsMismatch: (status.HTTP_409_CONFLICT, "parts_mismatch"),
    SizeMismatch: (status.HTTP_409_CONFLICT, "size_mismatch"),
    UploadNotFound: (status.HTTP_404_NOT_FOUND, "upload_not_found"),
    AlreadyQueued: (status.HTTP_409_CONFLICT, "already_queued"),
    TribuRejected: (status.HTTP_502_BAD_GATEWAY, "tribu_rejected"),
    TribuUnavailable: (status.HTTP_503_SERVICE_UNAVAILABLE, "tribu_unavailable"),
}


class OwnerBody(BaseModel):
    email: NonEmpty
    first_name: NonEmpty
    last_name: NonEmpty


class OpenRequest(BaseModel):
    source_id: NonEmpty
    """Identifier of the archive on the client side."""

    size: int = Field(gt=0)
    """Size of the file, in bytes."""

    md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    """MD5 checksum of the whole file, in lowercase hexadecimal."""

    title: NonEmpty
    owner: OwnerBody


class PartUrl(BaseModel):
    number: int
    url: str


class OpenResponse(BaseModel):
    ticket: str
    """Signed ticket to send back to resume or complete the upload."""

    part_size: int
    """Size of every part but the last one, in bytes."""

    expires_at: datetime.datetime
    """Expiration of the ticket and of the URLs."""

    parts: list[PartUrl]


class TicketRequest(BaseModel):
    ticket: NonEmpty


class PartsResponse(BaseModel):
    parts: list[PartUrl]


class SentPart(BaseModel):
    number: int = Field(gt=0)
    etag: NonEmpty


class CompleteRequest(BaseModel):
    ticket: NonEmpty
    parts: list[SentPart]
    """Number and ETag of every part, as returned by the bucket."""


def part_urls(parts: list[PresignedPart]) -> list[PartUrl]:
    """Turn presigned parts into the response format."""
    return [PartUrl(number=part.number, url=part.url) for part in parts]


def uploads_router(uploads: Uploads, authentication: BearerAuthentication) -> APIRouter:
    """Build the routes of the upload operations."""
    router = APIRouter(prefix="/uploads")
    Subject = Annotated[str, Depends(authentication)]

    @router.post("", status_code=status.HTTP_201_CREATED)
    def open_upload(body: OpenRequest, sub: Subject) -> OpenResponse:
        """Start an upload and return the URLs of all its parts."""
        opened = uploads.open(
            sub=sub,
            source_id=body.source_id,
            size=body.size,
            md5=body.md5,
            title=body.title,
            owner=Owner.model_validate(body.owner.model_dump()),
        )
        return OpenResponse(
            ticket=opened.ticket,
            part_size=opened.part_size,
            expires_at=opened.expires_at,
            parts=part_urls(opened.parts),
        )

    @router.post("/parts")
    def missing_parts(body: TicketRequest, sub: Subject) -> PartsResponse:
        """Return new URLs for the parts the bucket has not received yet."""
        return PartsResponse(parts=part_urls(uploads.missing_parts(body.ticket, sub)))

    @router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
    def complete(body: CompleteRequest, sub: Subject) -> None:
        """Assemble the file from its parts, and hand it over to Tribu."""
        parts = [Part(number=part.number, etag=part.etag) for part in body.parts]
        uploads.complete(body.ticket, sub, parts)

    return router


def error_handler(
    status_code: int, code: str
) -> Callable[[Request, Exception], JSONResponse]:
    """Build a handler that answers with the status and the error code."""

    def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": code})

    return handler


def add_error_handlers(app: FastAPI) -> None:
    """Answer the upload errors with their HTTP status and a stable error code."""
    for error, (status_code, code) in ERRORS.items():
        app.add_exception_handler(error, error_handler(status_code, code))
