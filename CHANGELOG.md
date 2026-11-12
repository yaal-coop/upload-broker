# Changelog

## 0.1.0 - 2026-11-12

First release.

### Added

- Upload of large files to an S3 bucket with presigned multipart URLs. Clients never hold S3 credentials.
- Authentication with bearer tokens checked by introspection (RFC 7662), with a required audience and scope.
- Signed upload tickets. Clients can get new URLs for the missing parts after an interruption or when the URLs expire.
- Uploads with missing parts or a wrong size are rejected when they complete.
- When an upload completes, Tribu receives a presigned URL to download the file.
- Stable error codes in the `detail` field of error responses.
- Health check endpoint at `/health`.
- Container image on ghcr.io, served by Granian, for amd64.
