from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from pydantic import BaseModel
from pydantic import ValidationError

ALGORITHM = "HS256"


class InvalidTicket(Exception):
    """The ticket is malformed, forged or expired."""


class Owner(BaseModel):
    email: str
    first_name: str
    last_name: str


class Ticket(BaseModel):
    """Everything needed to resume or complete an upload."""

    sub: str
    """Subject of the token that started the upload."""

    exp: int
    """Expiration, as a Unix timestamp."""

    key: str
    upload_id: str
    size: int
    md5: str
    part_size: int
    source_id: str
    title: str
    owner: Owner

    @property
    def part_count(self) -> int:
        return (self.size + self.part_size - 1) // self.part_size


def encode_ticket(ticket: Ticket, secret: str) -> str:
    """Sign the ticket."""
    return jwt.encode(
        {"alg": ALGORITHM}, ticket.model_dump(), OctKey.import_key(secret)
    )


def decode_ticket(value: str, secret: str) -> Ticket:
    """Check the signature and the expiration of the ticket, and return its content."""
    try:
        token = jwt.decode(value, OctKey.import_key(secret), algorithms=[ALGORITHM])
        jwt.JWTClaimsRegistry(exp={"essential": True}).validate(token.claims)
        return Ticket.model_validate(token.claims)
    except (JoseError, ValueError, ValidationError) as exc:
        raise InvalidTicket from exc
