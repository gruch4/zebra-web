"""Bearer-token authentication for the external API.

Deliberately independent from the web UI's session: the cookie is never looked at, so a
logged-in browser cannot be tricked into calling these endpoints (no CSRF surface).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.deps import SessionDep
from app.auth import User
from app.models import ApiToken
from app.tokens import hash_token, token_status

bearer = HTTPBearer(
    auto_error=False,
    scheme_name="ApiToken",
    description=(
        "An API token created in the web UI under **API access**, sent as "
        "`Authorization: Bearer zw_...`."
    ),
)

# `last_used_at` is refreshed at most this often, to avoid a write on every request.
LAST_USED_RESOLUTION = timedelta(seconds=60)


@dataclass(slots=True, frozen=True)
class ApiClient:
    """The authenticated token and the user who created it."""

    token_id: int
    name: str
    owner_sub: str
    owner_identity: str

    @property
    def identity(self) -> str:
        """How labels and print jobs made through this token are attributed."""
        return f"api:{self.name} ({self.owner_identity})"[:255]

    def as_user(self) -> User:
        return User(sub=self.owner_sub, name=self.identity)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_client(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ApiClient:
    if credentials is None:
        raise _unauthorized("Missing API token")
    token = await session.scalar(
        select(ApiToken).where(ApiToken.token_hash == hash_token(credentials.credentials))
    )
    if token is None:
        raise _unauthorized("Invalid API token")
    state = token_status(token)
    if state == "revoked":
        raise _unauthorized("API token has been revoked")
    if state == "expired":
        raise _unauthorized("API token has expired")
    now = datetime.now(UTC)
    if token.last_used_at is None or now - token.last_used_at > LAST_USED_RESOLUTION:
        token.last_used_at = now
        await session.commit()
    return ApiClient(token.id, token.name, token.owner_sub, token.owner_identity)


ClientDep = Annotated[ApiClient, Depends(current_client)]
