import dataclasses
import datetime
import hashlib
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from types_boto3_s3 import S3Client

from upload_broker.settings import MIB
from upload_broker.settings import Settings

MAX_PART_SIZE = 5 * 1024 * MIB


class UploadError(Exception):
    pass


class TooLarge(UploadError):
    """The file needs more parts than the server accepts."""


class PartsMismatch(UploadError):
    """The parts sent by the client differ from the parts received by the bucket."""


class SizeMismatch(UploadError):
    """The assembled object does not have the announced size."""


class UploadNotFound(UploadError):
    """The upload is neither in progress nor completed."""


@dataclasses.dataclass(frozen=True)
class Part:
    number: int
    etag: str


@dataclasses.dataclass(frozen=True)
class PresignedPart:
    number: int
    url: str


def s3_client(settings: Settings) -> S3Client:
    """Build the S3 client of the service."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.s3_addressing_style},
            # Recent botocore adds checksums that Garage and Scaleway reject.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def multipart_etag(parts: list[Part]) -> str:
    """Compute the ETag S3 gives to an object assembled from these parts."""
    digests = b"".join(bytes.fromhex(part.etag.strip('"')) for part in parts)
    return f'"{hashlib.md5(digests).hexdigest()}-{len(parts)}"'


class Storage:
    """Multipart uploads to the bucket, driven by presigned URLs."""

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        prefix: str = "",
        part_size_min: int = 64 * MIB,
        max_parts: int = 1000,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.part_size_min = part_size_min
        self.max_parts = max_parts

    def part_size(self, size: int) -> int:
        """Pick the smallest part size that fits the file in the allowed number of parts."""
        needed = (size + self.max_parts - 1) // self.max_parts
        rounded = (needed + MIB - 1) // MIB * MIB
        part_size = max(self.part_size_min, rounded)
        if part_size > MAX_PART_SIZE:
            raise TooLarge
        return part_size

    def start(self, source_id: str) -> tuple[str, str]:
        """Open a multipart upload, and return the object key and the upload id."""
        key = f"{self.prefix}{uuid.uuid4()}.zip"
        response = self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, Metadata={"source-id": source_id}
        )
        return key, response["UploadId"]

    def presign_parts(
        self,
        key: str,
        upload_id: str,
        numbers: list[int],
        expires_in: datetime.timedelta,
    ) -> list[PresignedPart]:
        return [
            PresignedPart(
                number=number,
                url=self.client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": self.bucket,
                        "Key": key,
                        "UploadId": upload_id,
                        "PartNumber": number,
                    },
                    ExpiresIn=int(expires_in.total_seconds()),
                ),
            )
            for number in numbers
        ]

    def received_parts(self, key: str, upload_id: str) -> list[Part]:
        """List the parts the bucket received, in order.

        Raise UploadNotFound when the upload is not in progress.
        """
        paginator = self.client.get_paginator("list_parts")
        try:
            return [
                Part(number=part["PartNumber"], etag=part["ETag"])
                for page in paginator.paginate(
                    Bucket=self.bucket, Key=key, UploadId=upload_id
                )
                for part in page.get("Parts", [])
            ]

        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchUpload":
                raise UploadNotFound from exc
            raise

    def complete(self, key: str, upload_id: str, parts: list[Part], size: int) -> None:
        """Assemble the object from the parts the client sent.

        Completing an upload that is already completed with the same parts succeeds.
        """
        try:
            received = self.received_parts(key, upload_id)
        except UploadNotFound:
            self._check_completed(key, parts, size)
            return

        if [(p.number, p.etag.strip('"')) for p in parts] != [
            (p.number, p.etag.strip('"')) for p in received
        ]:
            raise PartsMismatch

        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [{"PartNumber": p.number, "ETag": p.etag} for p in parts]
            },
        )
        self._check_completed(key, parts, size)

    def _check_completed(self, key: str, parts: list[Part], size: int) -> None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise UploadNotFound from exc
            raise

        if head["ETag"] != multipart_etag(parts):
            raise UploadNotFound

        if head["ContentLength"] != size:
            raise SizeMismatch
