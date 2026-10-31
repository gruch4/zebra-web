"""Authentication via Authentik (OpenID Connect) with a signed session cookie."""

import json
import logging
from base64 import b64encode
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx2
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import Settings

log = logging.getLogger(__name__)

# The identity columns (created_by, user_sub, owner_sub, ...) are VARCHAR(255).
MAX_CLAIM_LENGTH = 255
# Browsers drop cookies over 4096 bytes. This bounds the encoded session; the signature
# (~35 bytes), the cookie name and its attributes (~70 bytes) fit in the rest.
SESSION_COOKIE_BUDGET = 3800


@dataclass(slots=True)
class User:
    sub: str
    email: str | None = None
    name: str | None = None

    @property
    def identity(self) -> str:
        return self.email or self.name or self.sub


LOCAL_USER = User(sub="local", name="Local user")


def create_oauth(settings: Settings) -> OAuth | None:
    if not settings.auth_enabled:
        return None
    oauth = OAuth()
    issuer = settings.oidc_issuer.rstrip("/") + "/"
    oauth.register(
        "authentik",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=issuer + ".well-known/openid-configuration",
        client_kwargs={"scope": settings.oidc_scopes, "code_challenge_method": "S256"},
    )
    return oauth


def current_user(request: Request) -> User:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return LOCAL_USER
    data = request.session.get("user")
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return User(sub=data["sub"], email=data.get("email"), name=data.get("name"))


def _safe_next(value: str | None) -> str:
    """Only allow local absolute paths as the post-login redirect target."""
    if (
        not value
        or not value.startswith("/")
        or value[1:2] in ("/", "\\")
        or any(ch == "\\" or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
    ):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    return value


def _groups(claim) -> set[str]:
    """The groups claim as a set; a lone group may arrive as a plain string."""
    if isinstance(claim, str):
        return {claim}
    if isinstance(claim, list):
        return {g for g in claim if isinstance(g, str)}
    return set()


def _claim(userinfo: dict, *keys: str) -> str | None:
    """The first non-empty string claim among `keys`, cut to fit the identity columns."""
    for key in keys:
        value = userinfo.get(key)
        if isinstance(value, str) and value:
            return value[:MAX_CLAIM_LENGTH]
    return None


def _cookie_size(session: dict) -> int:
    # Encoded the way SessionMiddleware does it, before signing.
    return len(b64encode(json.dumps(session).encode("utf-8")))


router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request):
    oauth: OAuth | None = request.app.state.oauth
    if oauth is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Authentication is disabled")
    return oauth.authentik


@router.get("/login")
async def login(request: Request, next: str | None = None):
    client = _client(request)
    settings: Settings = request.app.state.settings
    request.session["next"] = _safe_next(next)
    redirect_uri = settings.public_url.rstrip("/") + "/auth/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    client = _client(request)
    settings: Settings = request.app.state.settings
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Login failed: {exc.error}") from exc
    userinfo = token.get("userinfo") or await client.userinfo(token=token)
    allowed = settings.allowed_groups
    if allowed and not allowed & _groups(userinfo.get("groups")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your account is not allowed to use this app"
        )
    # The subject keys drafts and API tokens, so it is never truncated (OIDC caps it at 255).
    sub = userinfo.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > MAX_CLAIM_LENGTH:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login failed: invalid subject")
    target = _safe_next(request.session.pop("next", None))
    request.session["user"] = {
        "sub": sub,
        "email": _claim(userinfo, "email"),
        "name": _claim(userinfo, "name", "preferred_username"),
    }
    # The ID token is only a logout hint; a large one would push the cookie over the limit.
    id_token = token.get("id_token")
    with_token = {**request.session, "id_token": id_token}
    if id_token and _cookie_size(with_token) <= SESSION_COOKIE_BUDGET:
        request.session["id_token"] = id_token
    else:
        # Never keep a previous login's token: logout would send it as the hint.
        request.session.pop("id_token", None)
    return RedirectResponse(target, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    settings: Settings = request.app.state.settings
    id_token = request.session.get("id_token")
    request.session.clear()
    oauth: OAuth | None = request.app.state.oauth
    if oauth is None:
        return RedirectResponse("/", status_code=302)
    try:
        metadata = await oauth.authentik.load_server_metadata()
    except httpx2.HTTPError, ValueError:
        log.warning("OIDC metadata unavailable; logged out locally only", exc_info=True)
        return RedirectResponse("/", status_code=302)
    end_session = metadata.get("end_session_endpoint")
    if not end_session:
        return RedirectResponse("/", status_code=302)
    # client_id identifies the app when the ID token was too large to keep as a hint.
    params = {
        "client_id": settings.oidc_client_id,
        "post_logout_redirect_uri": settings.public_url.rstrip("/") + "/",
    }
    if id_token:
        params["id_token_hint"] = id_token
    return RedirectResponse(f"{end_session}?{urlencode(params)}", status_code=302)
