from fastapi import FastAPI
from granian.utils.proxies import wrap_asgi_with_proxy_headers
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from upload_broker.settings import Settings


def create_fastapi() -> FastAPI:
    """Build the FastAPI application with its routes."""
    app = FastAPI(title="upload-broker")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def create_app(settings: Settings | None = None) -> ASGIApp:
    """Build the application served by Granian, behind the trusted reverse proxies.

    Settings are read from the environment when omitted.
    """
    if settings is None:
        settings = Settings()
    wrapped = wrap_asgi_with_proxy_headers(
        create_fastapi(), trusted_hosts=settings.trusted_proxies
    )

    # Granian's wrapper is a plain function returning a coroutine, which ASGI
    # servers other than Granian (and Starlette's test client) take for ASGI 2.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await wrapped(scope, receive, send)

    return app
