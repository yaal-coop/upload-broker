from fastapi import FastAPI
from granian.utils.proxies import wrap_asgi_with_proxy_headers
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from upload_broker.api import add_error_handlers
from upload_broker.api import uploads_router
from upload_broker.auth import AudienceIntrospectTokenValidator
from upload_broker.auth import BearerAuthentication
from upload_broker.settings import Settings
from upload_broker.storage import Storage
from upload_broker.storage import s3_client
from upload_broker.tribu import Tribu
from upload_broker.uploads import Uploads


def create_fastapi(settings: Settings, tribu: Tribu | None = None) -> FastAPI:
    """Build the FastAPI application with its routes.

    The Tribu client is built from the settings when omitted.
    """
    app = FastAPI(title="upload-broker")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    storage = Storage(
        s3_client(settings),
        settings.s3_bucket,
        prefix=settings.object_prefix,
        part_size_min=settings.part_size_min,
        max_parts=settings.max_parts,
    )
    uploads = Uploads(
        storage,
        tribu or Tribu.from_settings(settings),
        settings.ticket_key.get_secret_value(),
        settings.presign_expiration,
    )
    authentication = BearerAuthentication(
        AudienceIntrospectTokenValidator.from_settings(settings),
        settings.required_scope,
    )
    app.include_router(uploads_router(uploads, authentication))
    add_error_handlers(app)
    return app


def create_app(settings: Settings | None = None) -> ASGIApp:
    """Build the application served by Granian, behind the trusted reverse proxies.

    Settings are read from the environment when omitted.
    """
    if settings is None:
        settings = Settings()
    wrapped = wrap_asgi_with_proxy_headers(
        create_fastapi(settings), trusted_hosts=settings.trusted_proxies
    )

    # Granian's wrapper is a plain function returning a coroutine, which ASGI
    # servers other than Granian (and Starlette's test client) take for ASGI 2.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await wrapped(scope, receive, send)

    return app
