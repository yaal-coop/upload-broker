# upload-broker

upload-broker lets authenticated clients upload large files to an S3 bucket without holding any S3 credentials.

It applies the [Valet Key pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/valet-key):

- the client authenticates with an OAuth 2.0 access token;
- upload-broker starts a multipart upload and returns one presigned URL per part;
- the client uploads the parts straight to the bucket, so files never go through upload-broker;
- the client reports the end of the upload, and upload-broker completes it and notifies the recipient service.

It was written to move workspace archives from [drive-migrator](https://github.com/suitenumerique/drive-migrator) to their destination.

## Run the container

```console
$ docker run --publish 8080:8080 ghcr.io/yaal-coop/upload-broker
```

The image serves the application with [Granian](https://github.com/emmett-framework/granian) on port 8080.

## Configuration

Settings are read from environment variables:

| Variable | Default | Description |
|---|---|---|
| `UPLOAD_BROKER_TRUSTED_PROXIES` | `127.0.0.1` | Comma-separated addresses or networks of the reverse proxies whose `X-Forwarded-*` headers are trusted, or `*`. |

## Development

The project uses [uv](https://docs.astral.sh/uv/).

```console
$ uv run pytest
$ uv run prek run --all-files
```

`compose.yaml` starts a single-node [Garage](https://garagehq.deuxfleurs.fr/) S3 server.
After the first start, create the bucket and the development key:

```console
$ docker compose up --detach
$ dev/garage-init.sh
```

With Podman, set `COMPOSE="podman compose"` before running the script.

The development S3 endpoint is `http://127.0.0.1:3900`, in the `garage` region, with the `uploads` bucket.
Its access key is `GK000000000000000000000000` and its secret key is 64 zeros.
