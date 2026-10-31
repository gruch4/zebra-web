"""Managing API tokens from the web UI (session login; a token cannot create tokens)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, true

from app.api.deps import SessionDep, UserDep
from app.auth import LOCAL_USER, User
from app.models import ApiToken
from app.schemas import ApiTokenCreated, ApiTokenIn, ApiTokenOut
from app.tokens import generate_token, token_status

router = APIRouter(prefix="/tokens", tags=["tokens"])


def token_fields(token: ApiToken, user: User) -> dict:
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "owner": token.owner_identity,
        # Only notable to real users looking at tokens that predate login; to the local user
        # (login disabled) every token is simply their own.
        "shared": token.owner_sub == LOCAL_USER.sub and user.sub != LOCAL_USER.sub,
        "status": token_status(token),
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "last_used_at": token.last_used_at,
        "revoked_at": token.revoked_at,
    }


def _visible(user: User):
    if user.sub == LOCAL_USER.sub:
        # Login is disabled, so there are no separate users: whoever opens the app manages
        # every token. This also keeps tokens made while login was on from being orphaned
        # (live but invisible) if it is switched off again.
        return true()
    # Tokens made before login was enabled belong to the shared "local" user; keep them
    # manageable by everyone so turning on Authentik never orphans them.
    return ApiToken.owner_sub.in_({user.sub, LOCAL_USER.sub})


async def _get_token(session: SessionDep, user: UserDep, token_id: int) -> ApiToken:
    token = await session.scalar(select(ApiToken).where(ApiToken.id == token_id, _visible(user)))
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    return token


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(session: SessionDep, user: UserDep):
    rows = await session.scalars(
        select(ApiToken)
        .where(_visible(user))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    )
    return [ApiTokenOut(**token_fields(token, user)) for token in rows]


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(body: ApiTokenIn, session: SessionDep, user: UserDep):
    """Create a token. The secret is only returned here, once; only its hash is stored."""
    if body.expires_at is not None and body.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The expiry must be in the future"
        )
    secret, prefix, digest = generate_token()
    token = ApiToken(
        owner_sub=user.sub,
        owner_identity=user.identity[:255],
        name=body.name,
        prefix=prefix,
        token_hash=digest,
        expires_at=body.expires_at,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return ApiTokenCreated(**token_fields(token, user), token=secret)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: int, session: SessionDep, user: UserDep):
    token = await _get_token(session, user, token_id)
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await session.commit()
