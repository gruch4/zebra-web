from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import pytest
from asgi_lifespan import LifespanManager
from fastapi.responses import RedirectResponse

from app.main import create_app
from tests.conftest import make_settings


@pytest.fixture
async def auth_app(migrated_db, request):
    groups = getattr(request, "param", "")
    application = create_app(
        make_settings(
            auth_enabled=True,
            oidc_issuer="https://auth.example.com/application/o/zebra/",
            oidc_client_id="client",
            oidc_client_secret="secret",
            oidc_allowed_groups=groups,
            public_url="http://test",
        )
    )
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def auth_client(auth_app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def fake_provider(monkeypatch, app, *, id_token="the-id-token", **claims):
    client = app.state.oauth.authentik

    async def authorize_redirect(request, redirect_uri):
        return RedirectResponse(f"https://auth.example.com/authorize?redirect_uri={redirect_uri}")

    async def authorize_access_token(request):
        return {
            "id_token": id_token,
            "userinfo": {
                "sub": "u1",
                "email": "user@example.com",
                "name": "User",
                "groups": ["printing"],
            }
            | claims,
        }

    async def load_server_metadata():
        return {"end_session_endpoint": "https://auth.example.com/end-session/"}

    monkeypatch.setattr(client, "authorize_redirect", authorize_redirect)
    monkeypatch.setattr(client, "authorize_access_token", authorize_access_token)
    monkeypatch.setattr(client, "load_server_metadata", load_server_metadata)


async def test_api_requires_login(auth_client: httpx.AsyncClient):
    assert (await auth_client.get("/api/health")).status_code == 200
    assert (await auth_client.get("/api/me")).status_code == 401
    assert (await auth_client.get("/api/printers")).status_code == 401


async def test_login_callback_and_logout(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app)
    login = await auth_client.get("/auth/login", params={"next": "/labels"})
    assert login.status_code == 307
    assert "redirect_uri=http://test/auth/callback" in login.headers["location"]

    callback = await auth_client.get("/auth/callback")
    assert callback.status_code == 302
    assert callback.headers["location"] == "/labels"

    me = (await auth_client.get("/api/me")).json()
    assert me == {
        "sub": "u1",
        "email": "user@example.com",
        "name": "User",
        "auth_enabled": True,
    }

    logout = await auth_client.get("/auth/logout")
    location = urlparse(logout.headers["location"])
    assert location.netloc == "auth.example.com"
    query = parse_qs(location.query)
    assert query["id_token_hint"] == ["the-id-token"]
    assert query["client_id"] == ["client"]
    assert query["post_logout_redirect_uri"] == ["http://test/"]
    assert (await auth_client.get("/api/me")).status_code == 401


def session_cookie(response: httpx.Response) -> str:
    """The session cookie's name=value, as the browser measures it against its size limit."""
    cookies = response.headers.get_list("set-cookie")
    return next(c for c in cookies if c.startswith("zebra_session=")).split(";")[0]


async def test_large_id_token_is_not_kept_in_the_cookie(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app, id_token="x" * 5000)
    callback = await auth_client.get("/auth/callback")
    assert callback.status_code == 302
    assert len(session_cookie(callback)) < 4096
    assert (await auth_client.get("/api/me")).status_code == 200

    query = parse_qs(urlparse((await auth_client.get("/auth/logout")).headers["location"]).query)
    assert "id_token_hint" not in query
    assert query["client_id"] == ["client"]


async def test_a_new_login_never_keeps_the_previous_id_token(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app)
    await auth_client.get("/auth/callback")
    # Logging in again (e.g. as someone else) with a token too large to keep.
    fake_provider(monkeypatch, auth_app, id_token="x" * 5000)
    await auth_client.get("/auth/callback")
    query = parse_qs(urlparse((await auth_client.get("/auth/logout")).headers["location"]).query)
    assert "id_token_hint" not in query


async def test_logout_works_when_the_provider_is_unreachable(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app)
    await auth_client.get("/auth/callback")

    async def load_server_metadata():
        raise httpx2.ConnectError("down")

    monkeypatch.setattr(
        auth_app.state.oauth.authentik, "load_server_metadata", load_server_metadata
    )
    logout = await auth_client.get("/auth/logout")
    assert logout.status_code == 302
    assert logout.headers["location"] == "/"
    assert session_cookie(logout) == "zebra_session=null"
    assert (await auth_client.get("/api/me")).status_code == 401


async def test_unsafe_next_is_ignored(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app)
    await auth_client.get("/auth/login", params={"next": "//evil.example.com"})
    callback = await auth_client.get("/auth/callback")
    assert callback.headers["location"] == "/"


@pytest.mark.parametrize("auth_app", ["admins,printing"], indirect=True)
async def test_allowed_groups(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app, groups=["guests"])
    assert (await auth_client.get("/auth/callback")).status_code == 403
    fake_provider(monkeypatch, auth_app, groups=["printing"])
    assert (await auth_client.get("/auth/callback")).status_code == 302


@pytest.mark.parametrize("auth_app", ["a,printing"], indirect=True)
async def test_groups_claim_is_matched_as_whole_names(auth_client, auth_app, monkeypatch):
    # A string claim is one group, not a set of characters ("admins" contains "a").
    fake_provider(monkeypatch, auth_app, groups="admins")
    assert (await auth_client.get("/auth/callback")).status_code == 403
    fake_provider(monkeypatch, auth_app, groups="printing")
    assert (await auth_client.get("/auth/callback")).status_code == 302
    fake_provider(monkeypatch, auth_app, groups=[{"name": "printing"}])
    assert (await auth_client.get("/auth/callback")).status_code == 403


async def test_identity_claims_fit_the_database(auth_client, auth_app, monkeypatch):
    fake_provider(monkeypatch, auth_app, sub="s" * 256)
    assert (await auth_client.get("/auth/callback")).status_code == 401

    fake_provider(monkeypatch, auth_app, sub="s" * 255, email="e" * 300, name="n" * 300)
    assert (await auth_client.get("/auth/callback")).status_code == 302
    me = (await auth_client.get("/api/me")).json()
    assert (len(me["sub"]), len(me["email"]), len(me["name"])) == (255, 255, 255)

    draft = await auth_client.put("/api/drafts/print-zpl", json={"data": {"zpl": "x"}})
    assert draft.status_code == 200, draft.text
    label = await auth_client.post(
        "/api/labels", json={"name": "x", "kind": "zpl", "zpl": "^XA^XZ"}
    )
    assert label.status_code == 201, label.text
    assert label.json()["created_by"] == "e" * 255


async def test_external_api_uses_tokens_not_the_login(auth_client, auth_app, monkeypatch):
    # Both need credentials, and neither is satisfied by "being logged out".
    assert (await auth_client.get("/api/tokens")).status_code == 401
    assert (await auth_client.get("/api/v1/printers")).status_code == 401

    fake_provider(monkeypatch, auth_app)
    await auth_client.get("/auth/callback")
    created = await auth_client.post("/api/tokens", json={"name": "Inventory"})
    assert created.status_code == 201
    assert created.json()["owner"] == "user@example.com"
    headers = {"Authorization": f"Bearer {created.json()['token']}"}

    # The browser session alone does not open the external API (no cookie-based access)...
    assert (await auth_client.get("/api/v1/printers")).status_code == 401
    # ...and a system without any session can use it with the token.
    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as system:
        assert (await system.get("/api/v1/printers", headers=headers)).status_code == 200
        # The token cannot be used for the web UI's endpoints.
        assert (await system.get("/api/tokens", headers=headers)).status_code == 401
        assert (await system.get("/api/printers", headers=headers)).status_code == 401


async def test_login_disabled_without_auth(client: httpx.AsyncClient):
    assert (await client.get("/auth/login")).status_code == 404


def test_auth_requires_secret_and_oidc_settings():
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        make_settings(auth_enabled=True, session_secret="change-me")
    with pytest.raises(ValueError, match="OIDC_ISSUER"):
        make_settings(auth_enabled=True)


@pytest.mark.parametrize(
    "target",
    ["//evil.com", "/\\evil.com", "/\\\\evil.com", "/\t/evil.com", "https://evil.com", "labels"],
)
async def test_redirect_targets_must_be_local_paths(auth_client, auth_app, monkeypatch, target):
    fake_provider(monkeypatch, auth_app)
    await auth_client.get("/auth/login", params={"next": target})
    assert (await auth_client.get("/auth/callback")).headers["location"] == "/"


def test_safe_next_keeps_local_paths():
    from app.auth import _safe_next

    assert _safe_next("/templates/3?tab=mass") == "/templates/3?tab=mass"
