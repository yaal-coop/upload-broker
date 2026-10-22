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
| `UPLOAD_BROKER_S3_ENDPOINT_URL` | AWS | Public endpoint of the S3 server. The presigned URLs point to it. |
| `UPLOAD_BROKER_S3_REGION` | | Region of the bucket. |
| `UPLOAD_BROKER_S3_BUCKET` | required | Bucket that receives the files. |
| `UPLOAD_BROKER_S3_ACCESS_KEY_ID` | required | S3 access key. |
| `UPLOAD_BROKER_S3_SECRET_ACCESS_KEY` | required | S3 secret key. |
| `UPLOAD_BROKER_S3_ADDRESSING_STYLE` | `path` | `path` or `virtual`. |
| `UPLOAD_BROKER_OBJECT_PREFIX` | | Prefix of the object keys. |
| `UPLOAD_BROKER_PRESIGN_EXPIRATION` | 7 days | Lifetime of the tickets and of the presigned URLs, in seconds or as an ISO 8601 duration. S3 caps it at 7 days. |
| `UPLOAD_BROKER_PART_SIZE_MIN` | 64 MiB | Minimum part size, in bytes. |
| `UPLOAD_BROKER_MAX_PARTS` | `1000` | Maximum number of parts of an upload: 1000 on Scaleway, 10000 on AWS. |
| `UPLOAD_BROKER_TICKET_KEY` | required | Secret of at least 32 characters that signs the upload tickets. |
| `UPLOAD_BROKER_INTROSPECTION_URL` | required | Token introspection endpoint of the authorization server (RFC 7662). |
| `UPLOAD_BROKER_CLIENT_ID` | required | Client ID of the service at the authorization server. |
| `UPLOAD_BROKER_CLIENT_SECRET` | required | Client secret of the service at the authorization server. |
| `UPLOAD_BROKER_AUDIENCE` | required | Audience that the tokens must contain. |
| `UPLOAD_BROKER_REQUIRED_SCOPE` | required | Scope that the tokens must contain. |
| `UPLOAD_BROKER_INTROSPECTION_TIMEOUT` | `10` | Timeout of the introspection requests, in seconds. |
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
