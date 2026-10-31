import httpx
from fastapi import FastAPI

from app import token_admin
from tests.conftest import add_token


def test_arguments():
    assert token_admin.parse_args(["list"]).command == "list"
    assert token_admin.parse_args(["revoke", "3", "4"]).ids == [3, 4]
    assert token_admin.parse_args(["revoke-owner", "some-sub"]).owner_sub == "some-sub"


async def test_list_shows_tokens_and_their_owners(client: httpx.AsyncClient, app: FastAPI):
    await add_token(app, "alice-sub", "Alice script")
    created = (await client.post("/api/tokens", json={"name": "Inventory"})).json()
    lines = await token_admin.list_tokens(app.state.sessionmaker)
    assert lines[0].split()[:3] == ["ID", "STATUS", "NAME"]
    text = "\n".join(lines)
    assert "Alice script" in text
    assert "sub: alice-sub" in text
    assert f"{created['prefix']}..." in text
    assert created["token"] not in text


async def test_revoke_by_id(client: httpx.AsyncClient, app: FastAPI, api_token, api_headers):
    sessionmaker = app.state.sessionmaker
    assert (await client.get("/api/v1/printers", headers=api_headers)).status_code == 200

    args = token_admin.parse_args(["revoke", str(api_token["id"]), "9999"])
    assert await token_admin.run(args, sessionmaker) == ["Revoked 1 token(s)"]
    assert (await client.get("/api/v1/printers", headers=api_headers)).status_code == 401
    # Already revoked, or unknown: nothing more to do.
    assert await token_admin.run(args, sessionmaker) == ["Revoked 0 token(s)"]


async def test_revoke_everything_of_an_owner(client: httpx.AsyncClient, app: FastAPI):
    sessionmaker = app.state.sessionmaker
    await add_token(app, "alice-sub", "one")
    await add_token(app, "alice-sub", "two")
    await add_token(app, "bob-sub", "keep")

    args = token_admin.parse_args(["revoke-owner", "alice-sub"])
    assert await token_admin.run(args, sessionmaker) == ["Revoked 2 token(s)"]
    statuses = {t["name"]: t["status"] for t in (await client.get("/api/tokens")).json()}
    assert statuses == {"one": "revoked", "two": "revoked", "keep": "active"}
