"""API-key authentication for this service's own endpoints.

This is a plain shared-secret check on the X-API-Key header, compared in
constant time. It is deliberately simple: it stops casual abuse of a
portfolio endpoint. It is NOT Azure authentication — Azure calls use
DefaultAzureCredential (Entra ID) and need no keys at all.
"""

import hmac
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Shared secret protecting this support-agent API.",
)


def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """FastAPI dependency: reject requests without the correct X-API-Key."""
    if not settings.app_api_key:
        # Fail closed: a missing server-side key means nobody gets in.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key is not configured on the server.",
        )
    if api_key is None or not hmac.compare_digest(
        api_key.encode(), settings.app_api_key.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
        )


def generate_api_key() -> str:
    """Mint a new random hex key for APP_API_KEY (64 chars)."""
    return secrets.token_hex(32)
