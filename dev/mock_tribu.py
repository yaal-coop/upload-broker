"""Fake Tribu migration API, for development."""

import asyncio
import hashlib
import os
from typing import Literal

import httpx2
from fastapi import BackgroundTasks
from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import Field

FIELDS = (
    "source-id",
    "file-url",
    "file-size",
    "checksum",
    "title",
    "owner-mail",
    "owner-first-name",
    "owner-last-name",
    "secret-key",
)

Status = Literal["queued", "downloaded", "checksum_mismatch", "download_failed"]


class Migration(BaseModel):
    source_id: str
    file_url: str
    file_size: int
    checksum: str
    title: str
    owner_mail: str
    owner_first_name: str
    owner_last_name: str
    status: Status = "queued"


class Failure(BaseModel):
    status: int = Field(ge=100, le=599)


def create_app(
    secret_key: str | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the fake Tribu API.

    The secret key is read from MOCK_TRIBU_SECRET_KEY when omitted.
    """
    if secret_key is None:
        secret_key = os.environ["MOCK_TRIBU_SECRET_KEY"]

    app = FastAPI(title="mock-tribu")
    migrations: dict[str, Migration] = {}
    failures: list[int] = []
    lock = asyncio.Lock()

    async def remote_size(url: str) -> int | None:
        """Read the size of the file from a one-byte range request."""
        try:
            async with httpx2.AsyncClient(transport=transport) as client:
                response = await client.get(url, headers={"Range": "bytes=0-0"})
        except httpx2.HTTPError:
            return None
        _, _, total = response.headers.get("Content-Range", "").partition("/")
        return int(total) if total.isdigit() else None

    async def download(migration: Migration) -> None:
        digest = hashlib.md5()
        try:
            async with (
                httpx2.AsyncClient(transport=transport) as client,
                client.stream("GET", migration.file_url) as response,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    digest.update(chunk)
        except httpx2.HTTPError:
            migration.status = "download_failed"
            return

        if digest.hexdigest() == migration.checksum:
            migration.status = "downloaded"
        else:
            migration.status = "checksum_mismatch"

    @app.post("/migration/add")
    async def add(request: Request, background: BackgroundTasks) -> Response:
        if failures:
            return Response(status_code=failures.pop(0))

        form = await request.form()
        if form.get("secret-key") != secret_key:
            return Response(status_code=403)

        received = {name: form.get(name) for name in FIELDS}
        values = {
            name: value
            for name, value in received.items()
            if isinstance(value, str) and value
        }
        if len(values) != len(FIELDS) or not values["file-size"].isdigit():
            return Response(status_code=400)

        async with lock:
            if values["source-id"] in migrations:
                return Response(status_code=409)

            size = await remote_size(values["file-url"])
            if size is None:
                return Response(status_code=400)
            if size != int(values["file-size"]):
                return Response(status_code=406)

            migration = Migration(
                source_id=values["source-id"],
                file_url=values["file-url"],
                file_size=size,
                checksum=values["checksum"],
                title=values["title"],
                owner_mail=values["owner-mail"],
                owner_first_name=values["owner-first-name"],
                owner_last_name=values["owner-last-name"],
            )
            migrations[migration.source_id] = migration

        background.add_task(download, migration)
        return Response(status_code=201)

    @app.get("/migrations")
    def list_migrations() -> list[Migration]:
        return list(migrations.values())

    @app.delete("/migrations", status_code=204)
    def forget_migrations() -> None:
        migrations.clear()

    @app.post("/failures", status_code=204)
    def queue_failure(failure: Failure) -> None:
        failures.append(failure.status)

    @app.delete("/failures", status_code=204)
    def empty_failures() -> None:
        failures.clear()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
