FROM docker.io/astral/uv:0.13.4-python3.14-trixie-slim@sha256:db955a4c5fd85c9e08ae2c02f3fcedf76765aebc7c9bc10c55a6bbcc1b0510be AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM builder AS dev

RUN uv sync --locked --no-dev --group compose
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
ENTRYPOINT ["granian", "--interface", "asgi", "--factory", "upload_broker.app:create_app", "--host", "0.0.0.0"]
CMD ["--port", "8080"]

FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

USER nobody
EXPOSE 8080
ENTRYPOINT ["granian", "--interface", "asgi", "--factory", "upload_broker.app:create_app", "--host", "0.0.0.0"]
CMD ["--port", "8080"]
