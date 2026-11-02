"""Menshen settings for the upload-broker development stack."""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from menshen.settings import Production


def signing_key() -> str:
    """Create a new RSA private key, in PEM format."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class Compose(Production):
    """Production settings, served over plain HTTP, with a key created at startup."""

    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    TOKEN_EXCHANGE_JWT_SIGNING_KEYS = {"dev": signing_key()}
    TOKEN_EXCHANGE_JWT_CURRENT_KID = "dev"
