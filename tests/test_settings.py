import pytest
from pydantic import SecretStr
from pydantic import ValidationError

from tests.conftest import make_settings

S3 = {
    "s3_endpoint_url": "http://localhost:3900",
    "s3_region": "garage",
    "s3_bucket": "bucket",
    "s3_access_key_id": "key",
    "s3_secret_access_key": SecretStr("secret"),
}


@pytest.mark.parametrize("missing", ["s3_endpoint_url", "s3_region"])
def test_s3_server_must_be_given(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    """The service does not start without the S3 endpoint and region."""
    monkeypatch.delenv(f"UPLOAD_BROKER_{missing.upper()}", raising=False)
    s3 = {name: value for name, value in S3.items() if name != missing}
    with pytest.raises(ValidationError, match=missing):
        make_settings(**s3)
