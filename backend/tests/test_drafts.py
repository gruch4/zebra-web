import httpx
from asgi_lifespan import LifespanManager

from app.main import create_app
from tests.conftest import make_settings
from tests.test_auth import fake_provider


async def test_draft_round_trip_and_delete(client: httpx.AsyncClient):
    empty = (await client.get("/api/drafts/print-zpl")).json()
    assert empty == {"name": "print-zpl", "data": {}, "updated_at": None}

    body = {"data": {"zpl": "^XA^FDżółw^FS^XZ", "width_mm": 50}}
    saved = (await client.put("/api/drafts/print-zpl", json=body)).json()
    assert saved["data"] == body["data"] and saved["updated_at"]
    again = (await client.put("/api/drafts/print-zpl", json={"data": {"zpl": "x"}})).json()
    assert again["data"] == {"zpl": "x"}
    assert (await client.get("/api/drafts/print-zpl")).json()["data"] == {"zpl": "x"}

    deleted = await client.delete("/api/drafts/print-zpl")
    assert deleted.status_code == 204
    assert (await client.get("/api/drafts/print-zpl")).json()["data"] == {}


async def test_draft_validation(client: httpx.AsyncClient):
    assert (await client.get("/api/drafts/Bad Name")).status_code == 422
    too_big = {"data": {"zpl": "x" * (6 * 1024 * 1024 + 1)}}
    assert (await client.put("/api/drafts/print-zpl", json=too_big)).status_code == 413


async def test_drafts_are_per_user(migrated_db, monkeypatch, client):
    application = create_app(
        make_settings(
            auth_enabled=True,
            oidc_issuer="https://auth.example.com/application/o/zebra/",
            oidc_client_id="client",
            oidc_client_secret="secret",
            public_url="http://test",
        )
    )
    async with LifespanManager(application):
        transport = httpx.ASGITransport(app=application)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as alice,
            httpx.AsyncClient(transport=transport, base_url="http://test") as bob,
        ):
            client_ = application.state.oauth.authentik

            async def login(http, sub):
                async def token(request):
                    return {"userinfo": {"sub": sub, "email": f"{sub}@example.com"}}

                monkeypatch.setattr(client_, "authorize_access_token", token)
                await http.get("/auth/callback")

            fake_provider(monkeypatch, application)
            await login(alice, "alice")
            await login(bob, "bob")
            await alice.put("/api/drafts/print-zpl", json={"data": {"zpl": "alice"}})
            await bob.put("/api/drafts/print-zpl", json={"data": {"zpl": "bob"}})
            assert (await alice.get("/api/drafts/print-zpl")).json()["data"] == {"zpl": "alice"}
            assert (await bob.get("/api/drafts/print-zpl")).json()["data"] == {"zpl": "bob"}
            anonymous = await application_client_get(transport)
            assert anonymous == 401


async def application_client_get(transport) -> int:
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return (await http.get("/api/drafts/print-zpl")).status_code
