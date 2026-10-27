# upload-broker

upload-broker lets authenticated clients upload large files to an S3 bucket without holding any S3 credentials.

It applies the [Valet Key pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/valet-key):

- the client authenticates with an OAuth 2.0 access token;
- upload-broker starts a multipart upload and returns one presigned URL per part;
- the client uploads the parts straight to the bucket, so files never go through upload-broker;
- the client reports the end of the upload, and upload-broker completes it and notifies the recipient service.

It was written to move workspace archives from [drive-migrator](https://github.com/suitenumerique/drive-migrator) to their destination.

## API

Every route but `/health` requires a bearer token whose audience contains the service and whose scope contains `UPLOAD_BROKER_REQUIRED_SCOPE`.
The interactive documentation is served at `/docs`.

| Route | Body | Response |
|---|---|---|
| `POST /uploads` | `source_id`, `size`, `md5`, `title`, `owner` (`email`, `first_name`, `last_name`) | `201` with a `ticket`, the `part_size`, the `expires_at` date and one presigned URL per part |
| `POST /uploads/parts` | `ticket` | `200` with new URLs for the parts the bucket has not received yet |
| `POST /uploads/complete` | `ticket`, `parts` (`number` and `etag` of every part) | `204` once the file is assembled and handed over to Tribu |

The client sends each part with a `PUT` on its URL, and keeps the `ETag` header of the response.
On completion, upload-broker adds the file to the migration queue of Tribu.
Tribu gets a presigned download URL that expires with the ticket.
When Tribu is unavailable, the client can complete the upload again later.
When the upload was already handed over, completing it again answers `409` with `already_queued`.
Tribu gives the same answer when another archive of the same source is already in migration.

Errors answer with a stable code in `detail`:

| Status | Code | Meaning |
|---|---|---|
| `400` | `invalid_ticket` | The ticket is malformed, forged or expired. |
| `403` | `ticket_owner_mismatch` | The ticket was issued to another user. |
| `404` | `upload_not_found` | The upload was purged or never existed. |
| `409` | `parts_mismatch` | The parts differ from the ones the bucket received. |
| `409` | `size_mismatch` | The assembled file does not have the announced size. |
| `409` | `already_queued` | Tribu already has a migration in progress for this source. |
| `413` | `file_too_large` | The file needs more parts than the bucket accepts. |
| `502` | `tribu_rejected` | Tribu refused the file. The reason is in the logs. Retrying will not help. |
| `503` | `tribu_unavailable` | Tribu cannot be reached. Complete the upload again later. |

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
| `UPLOAD_BROKER_TRIBU_URL` | required | Base URL of the Tribu API. |
| `UPLOAD_BROKER_TRIBU_SECRET_KEY` | required | Secret key sent to the Tribu migration API. |
| `UPLOAD_BROKER_TRIBU_TIMEOUT` | `10` | Timeout of the requests to Tribu, in seconds. |
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

The unit tests simulate S3 with [moto](https://github.com/getmoto/moto), which does not check signatures nor expiration dates.
The tests of the presigned URLs run against Garage, and are not part of the default test run:

```console
$ uv run pytest tests/garage
```
