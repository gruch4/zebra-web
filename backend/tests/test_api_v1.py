import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from app.main import create_app
from app.models import ApiToken, Label
from app.printer.emulator import PrinterEmulator
from tests.conftest import make_settings

V1 = "/api/v1"
SIMPLE = "^XA^FO10,10^A0N,30,30^FDHello {{name}}^FS^XZ"
DESIGN = {
    "width_mm": 50,
    "height_mm": 25,
    "elements": [{"type": "text", "id": "t", "x": 10, "y": 10, "text": "SKU {{sku}}"}],
}


async def set_token(app: FastAPI, token_id: int, **values) -> None:
    async with app.state.sessionmaker() as session:
        await session.execute(update(ApiToken).where(ApiToken.id == token_id).values(**values))
        await session.commit()


# ---- authentication -------------------------------------------------------------------------


async def test_a_token_is_always_required(client: httpx.AsyncClient):
    # The web UI's endpoints are open in this test setup (AUTH_ENABLED=false), the API is not.
    assert (await client.get("/api/printers")).status_code == 200
    response = await client.get(f"{V1}/printers")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Bearer nope", "Bearer ", "Basic abc", "zw_abc"])
async def test_garbage_credentials_are_rejected(client: httpx.AsyncClient, authorization):
    response = await client.get(f"{V1}/printers", headers={"Authorization": authorization})
    assert response.status_code == 401


async def test_revoked_token_is_rejected(
    client: httpx.AsyncClient, api_token: dict, api_headers: dict
):
    assert (await client.get(f"{V1}/printers", headers=api_headers)).status_code == 200
    await client.delete(f"/api/tokens/{api_token['id']}")
    response = await client.get(f"{V1}/printers", headers=api_headers)
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"]


async def test_expired_token_is_rejected(
    client: httpx.AsyncClient, app: FastAPI, api_token: dict, api_headers: dict
):
    await set_token(app, api_token["id"], expires_at=datetime.now(UTC) - timedelta(minutes=1))
    response = await client.get(f"{V1}/printers", headers=api_headers)
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


async def test_last_use_is_recorded(client: httpx.AsyncClient, api_headers: dict):
    assert (await client.get("/api/tokens")).json()[0]["last_used_at"] is None
    await client.get(f"{V1}/printers", headers=api_headers)
    assert (await client.get("/api/tokens")).json()[0]["last_used_at"] is not None


# ---- printers -------------------------------------------------------------------------------


async def test_list_printers(client: httpx.AsyncClient, api_headers: dict, printer: dict):
    response = await client.get(f"{V1}/printers", headers=api_headers)
    assert response.status_code == 200
    (listed,) = response.json()
    assert listed == {
        "id": printer["id"],
        "name": "Emulator",
        "dpi": 203,
        "model": printer["model"],
        "is_default": True,
    }  # the printer's address is not exposed


# ---- printing raw ZPL -----------------------------------------------------------------------


async def test_print_zpl(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    response = await client.post(
        f"{V1}/print",
        headers=api_headers,
        json={"zpl": SIMPLE, "variables": {"name": "World"}, "copies": 2, "name": "Greeting"},
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "sent"
    assert job["printer_id"] == printer["id"]
    assert job["label_name"] == "Greeting"
    assert job["copies"] == 2
    assert job["variables"] == {"name": "World"}
    # API clients see the integration, never the e-mail of the person who owns the token.
    assert job["created_by"] == "api:Inventory"
    assert "printer_host" not in job
    assert b"^FDHello World^FS^PQ2^XZ" in emulator.state.data


async def test_api_prints_show_up_in_the_history(
    client: httpx.AsyncClient, api_headers: dict, printer: dict
):
    job = (
        await client.post(f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ", "name": "A"})
    ).json()
    history = (await client.get("/api/history", params={"source": "api"})).json()
    assert [item["job"]["id"] for item in history["items"]] == [job["id"]]
    assert history["items"][0]["job"]["source"] == "api"
    assert history["items"][0]["job"]["created_by"] == "api:Inventory (Local user)"
    # The web UI can reprint what came in through the API.
    reprint = await client.post(f"/api/jobs/{job['id']}/reprint", json={})
    assert reprint.json()["status"] == "sent"


async def test_print_can_pick_a_printer(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, closed_port: int
):
    other = (
        await client.post(
            "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
        )
    ).json()
    response = await client.post(
        f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ", "printer_id": other["id"]}
    )
    assert response.status_code == 502
    assert response.json()["printer_id"] == other["id"]


async def test_print_validation_errors(client: httpx.AsyncClient, api_headers: dict, printer):
    missing = await client.post(f"{V1}/print", headers=api_headers, json={"zpl": SIMPLE})
    assert missing.status_code == 422
    assert missing.json()["detail"]["missing"] == ["name"]

    for body in (
        {},
        {"zpl": ""},
        {"zpl": "^XA^XZ", "copies": 0},
        {"zpl": "^XA^XZ", "copies": 1001},
    ):
        response = await client.post(f"{V1}/print", headers=api_headers, json=body)
        assert response.status_code == 422, body

    unknown = await client.post(
        f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ", "printer_id": 999}
    )
    assert unknown.status_code == 404


async def test_print_without_any_printer(client: httpx.AsyncClient, api_headers: dict):
    response = await client.post(f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ"})
    assert response.status_code == 404


async def test_failed_print_is_502_with_the_job(
    client: httpx.AsyncClient, api_headers: dict, closed_port: int
):
    await client.post(
        "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
    )
    response = await client.post(f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ"})
    assert response.status_code == 502
    job = response.json()
    assert job["status"] == "failed"
    assert "Cannot connect" in job["error"]

    # The failed attempt is in the history, with the same id.
    recorded = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert recorded["status"] == "failed"
    assert recorded["source"] == "api"
    fetched = await client.get(f"{V1}/jobs/{job['id']}", headers=api_headers)
    assert fetched.json()["status"] == "failed"


# ---- storing labels -------------------------------------------------------------------------


async def test_store_label(client: httpx.AsyncClient, api_headers: dict):
    response = await client.post(
        f"{V1}/labels",
        headers=api_headers,
        json={
            "name": "Shelf label",
            "zpl": SIMPLE,
            "description": "For the shelf",
            "tags": ["inventory", "shelf"],
            "external_ref": "inv:1",
            "width_mm": 50,
            "height_mm": 25,
        },
    )
    assert response.status_code == 201, response.text
    label = response.json()
    assert label["name"] == "Shelf label"
    assert label["kind"] == "zpl"
    assert label["tags"] == ["inventory", "shelf", "api"]
    assert [v["name"] for v in label["variables"]] == ["name"]
    assert (label["width_mm"], label["height_mm"], label["dpi"]) == (50, 25, 203)
    assert label["external_ref"] == "inv:1"
    assert label["created_by"] == "api:Inventory"

    # Visible to everyone in the web UI's archive, and nothing was printed.
    archived = (await client.get("/api/labels")).json()
    assert [item["id"] for item in archived["items"]] == [label["id"]]
    assert (await client.get("/api/jobs")).json()["total"] == 0
    assert (await client.get(f"/api/labels/{label['id']}/preview.png")).status_code == 200


async def test_same_external_ref_updates_the_label(client: httpx.AsyncClient, api_headers: dict):
    body = {
        "name": "Shelf label",
        "zpl": SIMPLE,
        "description": "Keep me",
        "tags": ["inventory"],
        "external_ref": "inv:1",
    }
    created = await client.post(f"{V1}/labels", headers=api_headers, json=body)
    assert created.status_code == 201
    label_id = created.json()["id"]

    # Meanwhile somebody edits the label's variable settings in the web UI.
    await client.put(
        f"/api/labels/{label_id}/variables",
        json=[{"name": "name", "label": "Product", "required": False}],
    )

    changed = await client.post(
        f"{V1}/labels",
        headers=api_headers,
        json={"name": "Renamed", "zpl": SIMPLE.replace("Hello", "Bye"), "external_ref": "inv:1"},
    )
    assert changed.status_code == 200, changed.text
    label = changed.json()
    assert label["id"] == label_id
    assert label["name"] == "Renamed"
    assert "Bye" in label["zpl"]
    # Fields that were left out keep their value.
    assert label["description"] == "Keep me"
    assert label["tags"] == ["inventory", "api"]
    assert label["variables"][0]["label"] == "Product"
    assert (await client.get("/api/labels")).json()["total"] == 1

    # Fields that are sent replace the old value.
    retagged = await client.post(
        f"{V1}/labels",
        headers=api_headers,
        json={"name": "Renamed", "zpl": SIMPLE, "external_ref": "inv:1", "tags": ["new"]},
    )
    assert retagged.json()["tags"] == ["new", "api"]


async def test_labels_without_external_ref_are_always_new(
    client: httpx.AsyncClient, api_headers: dict
):
    ids = set()
    for _ in range(2):
        response = await client.post(
            f"{V1}/labels", headers=api_headers, json={"name": "Same", "zpl": "^XA^XZ"}
        )
        assert response.status_code == 201
        ids.add(response.json()["id"])
    assert len(ids) == 2


async def test_external_refs_belong_to_their_owner(
    client: httpx.AsyncClient, app: FastAPI, api_headers: dict
):
    async with app.state.sessionmaker() as session:
        other = Label(
            name="Theirs",
            kind="zpl",
            zpl="^XA^XZ",
            external_owner="someone-else",
            external_ref="inv:1",
            variables=[],
            tags=[],
        )
        session.add(other)
        await session.commit()
        other_id = other.id

    response = await client.post(
        f"{V1}/labels",
        headers=api_headers,
        json={"name": "Mine", "zpl": "^XA^XZ", "external_ref": "inv:1"},
    )
    assert response.status_code == 201
    assert response.json()["id"] != other_id

    found = await client.get(f"{V1}/labels", headers=api_headers, params={"external_ref": "inv:1"})
    assert [item["name"] for item in found.json()["items"]] == ["Mine"]


async def test_concurrent_stores_of_one_ref_make_one_label(
    client: httpx.AsyncClient, api_headers: dict
):
    body = {"name": "Race", "zpl": "^XA^XZ", "external_ref": "inv:race"}
    responses = await asyncio.gather(
        *(client.post(f"{V1}/labels", headers=api_headers, json=body) for _ in range(4))
    )
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert (await client.get("/api/labels")).json()["total"] == 1


async def test_store_label_validation(client: httpx.AsyncClient, api_headers: dict):
    for body in (
        {"zpl": "^XA^XZ"},
        {"name": "x"},
        {"name": "", "zpl": "^XA^XZ"},
        {"name": "x", "zpl": ""},
        {"name": "x", "zpl": "^XA^XZ", "dpi": 10},
        {"name": "x", "zpl": "^XA^XZ", "external_ref": ""},
    ):
        response = await client.post(f"{V1}/labels", headers=api_headers, json=body)
        assert response.status_code == 422, body


# ---- reading labels -------------------------------------------------------------------------


async def test_read_labels(client: httpx.AsyncClient, api_headers: dict):
    ui_label = (
        await client.post(
            "/api/labels",
            json={"name": "From the UI", "kind": "design", "design": DESIGN, "tags": ["ui"]},
        )
    ).json()
    stored = (
        await client.post(
            f"{V1}/labels",
            headers=api_headers,
            json={"name": "From the API", "zpl": SIMPLE, "external_ref": "inv:9"},
        )
    ).json()

    listed = (await client.get(f"{V1}/labels", headers=api_headers)).json()
    assert listed["total"] == 2
    assert {item["name"] for item in listed["items"]} == {"From the UI", "From the API"}

    by_tag = (await client.get(f"{V1}/labels", headers=api_headers, params={"tag": "api"})).json()
    assert [item["id"] for item in by_tag["items"]] == [stored["id"]]
    by_name = (await client.get(f"{V1}/labels", headers=api_headers, params={"q": "the ui"})).json()
    assert [item["id"] for item in by_name["items"]] == [ui_label["id"]]
    paged = (await client.get(f"{V1}/labels", headers=api_headers, params={"limit": 1})).json()
    assert (len(paged["items"]), paged["total"]) == (1, 2)

    one = (await client.get(f"{V1}/labels/{ui_label['id']}", headers=api_headers)).json()
    assert one["kind"] == "design"
    assert "SKU {{sku}}" in one["zpl"]
    assert "design" not in one
    assert (await client.get(f"{V1}/labels/9999", headers=api_headers)).status_code == 404


# ---- printing archived labels ---------------------------------------------------------------


async def test_print_archived_labels(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    zpl_label = (
        await client.post("/api/labels", json={"name": "Greeting", "kind": "zpl", "zpl": SIMPLE})
    ).json()
    design_label = (
        await client.post(
            "/api/labels", json={"name": "Product", "kind": "design", "design": DESIGN}
        )
    ).json()

    response = await client.post(
        f"{V1}/labels/{zpl_label['id']}/print",
        headers=api_headers,
        json={"variables": {"name": "Alice"}},
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert (job["label_id"], job["label_name"]) == (zpl_label["id"], "Greeting")
    assert job["variables"] == {"name": "Alice"}
    assert b"^FDHello Alice^FS" in emulator.state.data

    response = await client.post(
        f"{V1}/labels/{design_label['id']}/print",
        headers=api_headers,
        json={"variables": {"sku": "A-1"}, "copies": 3},
    )
    assert response.status_code == 200, response.text
    assert "^FDSKU A-1^FS" in response.json()["zpl"]
    assert b"^PQ3" in emulator.state.data

    history = (await client.get("/api/jobs", params={"source": "api"})).json()
    assert history["total"] == 2


async def test_print_archived_label_errors(
    client: httpx.AsyncClient, api_headers: dict, printer: dict
):
    label = (
        await client.post("/api/labels", json={"name": "Greeting", "kind": "zpl", "zpl": SIMPLE})
    ).json()
    missing = await client.post(f"{V1}/labels/{label['id']}/print", headers=api_headers, json={})
    assert missing.status_code == 422
    assert missing.json()["detail"]["missing"] == ["name"]
    unknown = await client.post(f"{V1}/labels/999/print", headers=api_headers, json={})
    assert unknown.status_code == 404


# ---- reading jobs ---------------------------------------------------------------------------


async def test_jobs_are_limited_to_those_made_through_the_api(
    client: httpx.AsyncClient, api_headers: dict, printer: dict
):
    ui_job = (await client.post("/api/print", json={"zpl": "^XA^XZ"})).json()
    api_job = (await client.post(f"{V1}/print", headers=api_headers, json={"zpl": "^XA^XZ"})).json()

    assert (await client.get(f"{V1}/jobs/{api_job['id']}", headers=api_headers)).status_code == 200
    assert (await client.get(f"{V1}/jobs/{ui_job['id']}", headers=api_headers)).status_code == 404


# ---- idempotency ----------------------------------------------------------------------------


def occurrences(emulator: PrinterEmulator, needle: bytes) -> int:
    return emulator.state.data.count(needle)


async def test_a_repeated_key_does_not_print_again(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    headers = {**api_headers, "Idempotency-Key": "order-1"}
    body = {"zpl": SIMPLE, "variables": {"name": "Once"}}

    first = await client.post(f"{V1}/print", headers=headers, json=body)
    assert first.status_code == 200
    assert "idempotent-replay" not in first.headers

    second = await client.post(f"{V1}/print", headers=headers, json=body)
    assert second.status_code == 200
    assert second.headers["idempotent-replay"] == "true"
    assert second.json() == first.json()

    assert occurrences(emulator, b"Hello Once") == 1
    assert (await client.get("/api/jobs")).json()["total"] == 1


async def test_a_key_cannot_be_reused_for_another_request(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    headers = {**api_headers, "Idempotency-Key": "order-1"}
    await client.post(f"{V1}/print", headers=headers, json={"zpl": "^XA^FDone^FS^XZ"})
    clash = await client.post(f"{V1}/print", headers=headers, json={"zpl": "^XA^FDtwo^FS^XZ"})
    assert clash.status_code == 409
    assert occurrences(emulator, b"two") == 0
    # Copies are part of the request too.
    clash = await client.post(
        f"{V1}/print", headers=headers, json={"zpl": "^XA^FDone^FS^XZ", "copies": 2}
    )
    assert clash.status_code == 409


async def test_keys_are_per_token(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    other = (await client.post("/api/tokens", json={"name": "Second"})).json()
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    body = {"zpl": "^XA^FDshared^FS^XZ"}
    for headers in (api_headers, other_headers):
        response = await client.post(
            f"{V1}/print", headers={**headers, "Idempotency-Key": "k"}, json=body
        )
        assert response.status_code == 200
        assert "idempotent-replay" not in response.headers
    assert occurrences(emulator, b"shared") == 2


async def test_a_failed_print_can_be_retried_with_the_same_key(
    client: httpx.AsyncClient, api_headers: dict, emulator: PrinterEmulator, closed_port: int
):
    off = (
        await client.post(
            "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
        )
    ).json()
    headers = {**api_headers, "Idempotency-Key": "retry-me"}
    body = {"zpl": "^XA^FDretry^FS^XZ"}

    failed = await client.post(f"{V1}/print", headers=headers, json=body)
    assert failed.status_code == 502
    again = await client.post(f"{V1}/print", headers=headers, json=body)
    assert again.status_code == 502
    assert again.json()["id"] != failed.json()["id"]  # tried again, not replayed

    # Once the printer works the same key prints, and only once.
    await client.put(
        f"/api/printers/{off['id']}",
        json={"name": "Off", "host": "127.0.0.1", "port": emulator.port},
    )
    sent = await client.post(f"{V1}/print", headers=headers, json=body)
    assert sent.status_code == 200
    replay = await client.post(f"{V1}/print", headers=headers, json=body)
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json()["id"] == sent.json()["id"]
    assert occurrences(emulator, b"retry") == 1


async def test_concurrent_requests_with_one_key_print_once(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    headers = {**api_headers, "Idempotency-Key": "burst"}
    body = {"zpl": "^XA^FDburst^FS^XZ"}
    responses = await asyncio.gather(
        *(client.post(f"{V1}/print", headers=headers, json=body) for _ in range(5))
    )
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum("idempotent-replay" in r.headers for r in responses) == 4
    assert occurrences(emulator, b"burst") == 1


async def test_archived_label_prints_are_idempotent_too(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    label = (
        await client.post("/api/labels", json={"name": "Greeting", "kind": "zpl", "zpl": SIMPLE})
    ).json()
    headers = {**api_headers, "Idempotency-Key": "label-1"}
    url = f"{V1}/labels/{label['id']}/print"
    first = await client.post(url, headers=headers, json={"variables": {"name": "Bo"}})
    replay = await client.post(url, headers=headers, json={"variables": {"name": "Bo"}})
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    changed = await client.post(url, headers=headers, json={"variables": {"name": "Cy"}})
    assert changed.status_code == 409
    assert occurrences(emulator, b"Hello Bo") == 1


async def test_key_format_is_validated(client: httpx.AsyncClient, api_headers: dict, printer):
    for key in ("has space", "x" * 256):
        response = await client.post(
            f"{V1}/print", headers={**api_headers, "Idempotency-Key": key}, json={"zpl": "^XA^XZ"}
        )
        assert response.status_code == 422, key


# ---- OpenAPI and docs -----------------------------------------------------------------------


async def test_openapi_document_covers_only_the_external_api(client: httpx.AsyncClient):
    response = await client.get(f"{V1}/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "Zebra Web external API"
    assert spec["servers"] == [{"url": "/api/v1"}]
    assert set(spec["paths"]) == {
        "/printers",
        "/print",
        "/labels",
        "/labels/{label_id}",
        "/labels/{label_id}/print",
        "/jobs/{job_id}",
    }
    operations = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert operations == {
        "listPrinters",
        "printZpl",
        "storeLabel",
        "listLabels",
        "getLabel",
        "printLabel",
        "getJob",
    }
    assert spec["components"]["securitySchemes"]["ApiToken"] == {
        "type": "http",
        "scheme": "bearer",
        "description": spec["components"]["securitySchemes"]["ApiToken"]["description"],
    }
    for path in spec["paths"].values():
        for op in path.values():
            assert op["security"] == [{"ApiToken": []}]
    for path in spec["paths"].values():
        for op in path.values():
            assert "401" in op["responses"]
    print_op = spec["paths"]["/print"]["post"]
    assert "502" in print_op["responses"]
    assert {p["name"] for p in print_op["parameters"]} == {"Idempotency-Key"}
    assert "201" in spec["paths"]["/labels"]["post"]["responses"]
    assert "200" in spec["paths"]["/labels"]["post"]["responses"]


async def test_swagger_page_works_offline(client: httpx.AsyncClient):
    page = await client.get(f"{V1}/docs")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    html = page.text
    assert "/api/v1/openapi.json" in html
    assert "/api/v1/swagger/swagger-ui-bundle.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert "fastapi.tiangolo.com" not in html

    for asset in ("swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"):
        served = await client.get(f"{V1}/swagger/{asset}")
        assert served.status_code == 200, asset
        assert len(served.content) > 100
    assert (await client.get(f"{V1}/redoc")).status_code == 404


async def test_internal_docs_are_off_by_default(client: httpx.AsyncClient):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404, path


async def test_internal_docs_can_be_enabled():
    application = create_app(make_settings(enable_internal_docs=True))
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        spec = (await http.get("/openapi.json")).json()
        assert "/api/printers" in spec["paths"]
        assert not any(path.startswith("/api/v1") for path in spec["paths"])
        assert (await http.get("/docs")).status_code == 200
        assert (await http.get("/api/v1/docs")).status_code == 200


async def test_disabled_docs_are_not_swallowed_by_the_frontend(tmp_path):
    """With the frontend mounted, unknown backend paths must be 404, not index.html."""
    (tmp_path / "index.html").write_text("<html>app</html>")
    application = create_app(make_settings(static_dir=tmp_path))
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.get("/printers")).text == "<html>app</html>"  # a client-side route
        for path in ("/docs", "/redoc", "/openapi.json", "/api/nope", "/api/v1/nope"):
            assert (await http.get(path)).status_code == 404, path
        assert (await http.get("/api/v1/docs")).status_code == 200
