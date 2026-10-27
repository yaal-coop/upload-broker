import uuid
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from tests.conftest import make_settings
from upload_broker.settings import Settings
from upload_broker.storage import s3_client


@pytest.fixture
def settings() -> Iterator[Settings]:
    """Garage from compose.yaml, with an object prefix for each test."""
    settings = make_settings(
        s3_endpoint_url="http://127.0.0.1:3900",
        s3_region="garage",
        s3_bucket="uploads",
        s3_access_key_id="GK000000000000000000000000",
        s3_secret_access_key=SecretStr("0" * 64),
        object_prefix=f"tests/{uuid.uuid4()}/",
    )
    yield settings

    client = s3_client(settings)
    bucket, prefix = settings.s3_bucket, settings.object_prefix
    for upload in client.list_multipart_uploads(Bucket=bucket, Prefix=prefix).get(
        "Uploads", []
    ):
        client.abort_multipart_upload(
            Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"]
        )
    for item in client.list_objects_v2(Bucket=bucket, Prefix=prefix).get(
        "Contents", []
    ):
        client.delete_object(Bucket=bucket, Key=item["Key"])
