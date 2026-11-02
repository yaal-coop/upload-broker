"""Create the menshen services and rules of the development stack.

Each step uses get_or_create, so the script can run many times.
"""

from token_exchange.models import ScopeGrant
from token_exchange.models import ServiceProvider
from token_exchange.models import ServiceProviderCredentials
from token_exchange.models import TokenExchangeRule

SOURCE_AUDIENCE = "impress"
SOURCE_CLIENT_ID = "drive-migrator"
SOURCE_CLIENT_SECRET = "dev-drive-migrator-secret"
TARGET_AUDIENCE = "upload-broker"
TARGET_CLIENT_ID = "upload-broker"
TARGET_CLIENT_SECRET = "dev-client-secret"
SOURCE_SCOPE = "openid"
GRANTED_SCOPE = "depot:archive:create"


def service(audience_id: str, client_id: str, client_secret: str) -> ServiceProvider:
    """Create a service and its credentials, and reset the secret."""
    provider, _ = ServiceProvider.objects.get_or_create(
        audience_id=audience_id, defaults={"name": audience_id}
    )
    credentials, _ = ServiceProviderCredentials.objects.get_or_create(
        service_provider=provider, client_id=client_id
    )
    credentials.set_client_secret(client_secret, save=True)
    return provider


def main() -> None:
    """Let drive-migrator exchange Keycloak tokens for upload-broker tokens."""
    source = service(SOURCE_AUDIENCE, SOURCE_CLIENT_ID, SOURCE_CLIENT_SECRET)
    target = service(TARGET_AUDIENCE, TARGET_CLIENT_ID, TARGET_CLIENT_SECRET)
    rule, _ = TokenExchangeRule.objects.get_or_create(
        source_service=source, target_service=target
    )
    ScopeGrant.objects.get_or_create(
        rule=rule, source_scope=SOURCE_SCOPE, granted_scope=GRANTED_SCOPE
    )
    print(
        f"Menshen is ready: {SOURCE_CLIENT_ID} exchanges {SOURCE_AUDIENCE} tokens"
        f" for {TARGET_AUDIENCE} tokens with the {GRANTED_SCOPE} scope"
    )
