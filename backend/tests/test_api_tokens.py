import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from app import auth
from app.auth import User
from app.models import ApiToken
from app.tokens import generate_token, hash_token, token_status
from tests.conftest import add_token


@pytest.fixture
def as_user(app: FastAPI) -> Iterator:
    """Act as a logged-in user instead of the local user."""

    def switch(sub: str) -> None:
        app.dependency_overrides[auth.current_user] = lambda: User(sub=sub, name=sub)

    yield switch
    app.dependency_overrides.pop(auth.current_user, None)


def test_generate_token():
    token, prefix, digest = generate_token()
    assert re.fullmatch(r"zw_[0-9a-f]{48}", token)
    assert token.startswith(prefix)
    assert digest == hash_token(token)
    assert len(digest) == 64
    assert generate_token()[0] != token


def test_token_status():
    now = datetime.now(UTC)
    token = ApiToken(expires_at=None, revoked_at=None)
    assert token_status(token) == "active"
    token.expires_at = now - timedelta(seconds=1)
    assert token_status(token) == "expired"
    token.revoked_at = now
    assert token_status(token) == "revoked"


async def test_secret_is_returned_only_when_created(client: httpx.AsyncClient, api_token: dict):
    assert api_token["token"].startswith("zw_")
    assert api_token["token"].startswith(api_token["prefix"])
    assert api_token["name"] == "Inventory"
    assert api_token["status"] == "active"
    assert api_token["owner"] == "Local user"
    # With login disabled every token is the local user's own, not "shared".
    assert api_token["shared"] is False

    listed = (await client.get("/api/tokens")).json()
    assert [t["id"] for t in listed] == [api_token["id"]]
    assert "token" not in listed[0]
    assert "token_hash" not in listed[0]
    assert api_token["token"] not in (await client.get("/api/tokens")).text


async def test_name_and_expiry_are_validated(client: httpx.AsyncClient):
    assert (await client.post("/api/tokens", json={"name": "   "})).status_code == 422
    assert (await client.post("/api/tokens", json={"name": "x" * 101})).status_code == 422

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = await client.post("/api/tokens", json={"name": "Old", "expires_at": past})
    assert response.status_code == 422

    # A date without a timezone is ambiguous and rejected instead of being guessed.
    naive = await client.post("/api/tokens", json={"name": "Naive", "expires_at": "2099-01-01"})
    assert naive.status_code == 422

    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    created = await client.post("/api/tokens", json={"name": " Padded ", "expires_at": future})
    assert created.status_code == 201
    assert created.json()["name"] == "Padded"
    assert created.json()["expires_at"] is not None


async def test_listing_is_newest_first(client: httpx.AsyncClient):
    for name in ("first", "second", "third"):
        await client.post("/api/tokens", json={"name": name})
    names = [t["name"] for t in (await client.get("/api/tokens")).json()]
    assert names == ["third", "second", "first"]


async def test_revoke(client: httpx.AsyncClient, api_token: dict):
    url = f"/api/tokens/{api_token['id']}"
    assert (await client.delete(url)).status_code == 204
    revoked = (await client.get("/api/tokens")).json()[0]
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"] is not None
    first = revoked["revoked_at"]
    # Revoking again is harmless and keeps the original time.
    assert (await client.delete(url)).status_code == 204
    assert (await client.get("/api/tokens")).json()[0]["revoked_at"] == first
    assert (await client.delete("/api/tokens/9999")).status_code == 404


async def test_users_only_manage_their_own_tokens(client: httpx.AsyncClient, app: FastAPI, as_user):
    mine = await add_token(app, "alice", "alice token")
    theirs = await add_token(app, "bob", "bob token")

    as_user("alice")
    names = [t["name"] for t in (await client.get("/api/tokens")).json()]
    assert names == ["alice token"]
    assert (await client.delete(f"/api/tokens/{theirs}")).status_code == 404
    assert (await client.delete(f"/api/tokens/{mine}")).status_code == 204


async def test_tokens_of_the_local_user_are_shared(
    client: httpx.AsyncClient, app: FastAPI, as_user
):
    """Tokens made before login was enabled must stay manageable once users exist."""
    legacy = await add_token(app, "local", "legacy")

    as_user("alice")
    listed = (await client.get("/api/tokens")).json()
    assert [(t["name"], t["shared"]) for t in listed] == [("legacy", True)]
    assert (await client.delete(f"/api/tokens/{legacy}")).status_code == 204

    as_user("bob")
    assert [t["status"] for t in (await client.get("/api/tokens")).json()] == ["revoked"]


async def test_api_tokens_cannot_mint_tokens(client: httpx.AsyncClient, api_headers: dict):
    """Token management exists only for the logged-in UI user, never under /api/v1."""
    response = await client.post("/api/v1/tokens", json={"name": "x"}, headers=api_headers)
    assert response.status_code == 404


async def test_with_login_disabled_every_token_is_manageable(
    client: httpx.AsyncClient, app: FastAPI
):
    """Tokens made while login was on must not become live-but-invisible if it is switched off."""
    theirs = await add_token(app, "alice", "alice token")
    listed = (await client.get("/api/tokens")).json()
    assert [(t["name"], t["shared"]) for t in listed] == [("alice token", False)]
    assert (await client.delete(f"/api/tokens/{theirs}")).status_code == 204
    assert (await client.get("/api/tokens")).json()[0]["status"] == "revoked"
