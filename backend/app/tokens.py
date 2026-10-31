"""API token generation and hashing. Only the SHA-256 hash of a token is ever stored."""

import hashlib
import secrets
from datetime import UTC, datetime

from app.models import ApiToken

TOKEN_PREFIX = "zw_"
# Characters of the token kept (in the clear) to recognise it in the UI.
DISPLAY_PREFIX_LENGTH = 9


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """A new token: (plaintext, display prefix, hash). The plaintext cannot be recovered later."""
    # 192 bits as hex: no "-" or "_" so a double click selects the whole token.
    token = TOKEN_PREFIX + secrets.token_hex(24)
    return token, token[:DISPLAY_PREFIX_LENGTH], hash_token(token)


def token_status(token: ApiToken, now: datetime | None = None) -> str:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= (now or datetime.now(UTC)):
        return "expired"
    return "active"
