"""Edge cases of the external API found in review: bad input, spoofing, retries and privacy."""

import time

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.api_v1 import routes
from app.models import PrintJob
from app.printer.client import PrinterClient, PrinterError
from app.printer.emulator import PrinterEmulator

V1 = "/api/v1"
SIMPLE = "^XA^FO10,10^A0N,30,30^FDHello {{name}}^FS^XZ"


# ---- NUL characters -------------------------------------------------------------------------


async def test_nul_characters_are_rejected_before_anything_is_printed(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, emulator: PrinterEmulator
):
    """The job is stored after printing and Postgres cannot store NUL, so a label would print
    but the request fail with a 500 and be missing from the history (and print again on retry)."""
    headers = {**api_headers, "Idempotency-Key": "nul"}
    bodies = [
        {"zpl": "^XA^FDa\x00b^FS^XZ"},
        {"zpl": "^XA^FD{{x}}^FS^XZ", "variables": {"x": "a\x00b"}},
        {"zpl": "^XA^FD{{x}}^FS^XZ", "variables": {"a\x00b": "x"}},
        {"zpl": "^XA^XZ", "name": "a\x00b"},
    ]
    for body in bodies:
        response = await client.post(f"{V1}/print", headers=headers, json=body)
        assert response.status_code == 422, body
    assert emulator.state.data == b""
    assert (await client.get("/api/jobs")).json()["total"] == 0


async def test_nul_characters_are_rejected_when_storing_labels(
    client: httpx.AsyncClient, api_headers: dict
):
    base = {"name": "x", "zpl": "^XA^XZ"}
    for override in (
        {"name": "a\x00b"},
        {"zpl": "^XA\x00^XZ"},
        {"description": "a\x00b"},
        {"tags": ["a\x00b"]},
        {"external_ref": "a\x00b"},
    ):
        response = await client.post(f"{V1}/labels", headers=api_headers, json=base | override)
        assert response.status_code == 422, override
    assert (await client.get("/api/labels")).json()["total"] == 0


async def test_the_web_ui_cannot_print_nul_characters_either(
    client: httpx.AsyncClient, printer: dict, emulator: PrinterEmulator
):
    response = await client.post("/api/print", json={"zpl": "^XA^FDa\x00b^FS^XZ"})
    assert response.status_code == 422
    assert emulator.state.data == b""
    assert (await client.post("/api/tokens", json={"name": "a\x00b"})).status_code == 422


async def test_nul_characters_are_rejected_before_saving_or_searching(
    client: httpx.AsyncClient, api_headers: dict
):
    """Postgres takes NUL neither in text nor in JSONB, so the commit or query would fail with
    a 500; the web UI's inputs (nested ones too) are refused up front like the API's."""
    zpl_label = {"name": "x", "kind": "zpl", "zpl": "^XA^XZ"}
    label = (await client.post("/api/labels", json=zpl_label)).json()
    nul = "a\x00b"
    design = {"elements": [{"type": "text", "id": "t", "text": nul}]}
    requests = [
        ("POST", "/api/printers", {"json": {"name": nul, "host": "printer.local"}}),
        ("POST", "/api/labels", {"json": zpl_label | {"name": nul}}),
        ("POST", "/api/labels", {"json": {"name": "x", "kind": "design", "design": design}}),
        ("PUT", f"/api/labels/{label['id']}", {"json": {"tags": [nul]}}),
        ("PUT", f"/api/labels/{label['id']}/variables", {"json": [{"name": "x", "help": nul}]}),
        ("POST", "/api/labels/import", {"files": [("files", ("a.zpl", b"^XA\x00^XZ"))]}),
        ("PUT", "/api/drafts/print-zpl", {"json": {"data": {"zpl": nul}}}),
        (
            "POST",
            "/api/batches/validate",
            {"json": {"label_id": label["id"], "rows": [{nul: "x"}]}},
        ),
        ("GET", "/api/labels", {"params": {"q": nul}}),
        ("GET", "/api/labels", {"params": {"tag": nul}}),
        ("GET", "/api/jobs", {"params": {"q": nul}}),
        ("GET", "/api/history", {"params": {"q": nul}}),
        ("GET", f"{V1}/labels", {"params": {"external_ref": nul}, "headers": api_headers}),
    ]
    for method, url, kwargs in requests:
        response = await client.request(method, url, **kwargs)
        assert response.status_code == 422, (method, url, kwargs)
    assert (await client.get("/api/labels")).json()["total"] == 1
    assert (await client.get("/api/printers")).json() == []


# ---- the "api" source -----------------------------------------------------------------------


async def test_the_web_ui_cannot_claim_the_api_source(
    client: httpx.AsyncClient, app: FastAPI, api_headers: dict, printer: dict
):
    response = await client.post("/api/print", json={"zpl": "^XA^XZ", "source": "api"})
    assert response.status_code == 422

    # What marks a job as made through the API is the token that sent it, not a label on it.
    async with app.state.sessionmaker() as session:
        job = PrintJob(source="api", zpl="^XA^XZ", status="sent", variables={})
        session.add(job)
        await session.commit()
        job_id = job.id
    assert (await client.get(f"{V1}/jobs/{job_id}", headers=api_headers)).status_code == 404


# ---- built-in variable names ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["date", "time", "datetime", "year"])
async def test_built_in_variables_cannot_be_set(
    client: httpx.AsyncClient,
    api_headers: dict,
    printer: dict,
    emulator: PrinterEmulator,
    name: str,
):
    """They are always filled from the clock, so a value would be ignored without a word."""
    label = (
        await client.post(
            "/api/labels",
            json={"name": "Dated", "kind": "zpl", "zpl": "^XA^FD{{date}} {{sku}}^FS^XZ"},
        )
    ).json()
    requests = [
        (f"{V1}/print", {"zpl": "^XA^FD{{date}}^FS^XZ", "variables": {name: "2027-03-01"}}),
        (
            f"{V1}/labels/{label['id']}/print",
            {"variables": {"sku": "A1", name: "2027-03-01"}},
        ),
    ]
    for url, body in requests:
        response = await client.post(url, headers=api_headers, json=body)
        assert response.status_code == 422, url
        detail = response.json()["detail"]
        assert list(detail["invalid"]) == [name]
        assert "built in" in detail["message"] or "automatically" in detail["message"]
    assert emulator.state.data == b""


async def test_built_in_variables_are_still_filled_in(
    client: httpx.AsyncClient, api_headers: dict, printer: dict
):
    response = await client.post(
        f"{V1}/print", headers=api_headers, json={"zpl": "^XA^FD{{year}}^FS^XZ"}
    )
    assert response.status_code == 200
    assert response.json()["zpl"] != "^XA^FD{{year}}^FS^XZ"


# ---- listing labels and what they reveal ----------------------------------------------------


async def test_label_list_is_light_and_does_not_reveal_web_users(
    client: httpx.AsyncClient, api_headers: dict
):
    ui_label = (
        await client.post("/api/labels", json={"name": "From the UI", "kind": "zpl", "zpl": SIMPLE})
    ).json()
    assert ui_label["created_by"] == "Local user"
    api_label = (
        await client.post(
            f"{V1}/labels", headers=api_headers, json={"name": "From the API", "zpl": SIMPLE}
        )
    ).json()

    listed = (await client.get(f"{V1}/labels", headers=api_headers)).json()
    assert listed["total"] == 2
    for item in listed["items"]:
        assert "zpl" not in item
        assert "design" not in item
        assert isinstance(item["variables"], list)  # still says what a label needs
    by_name = {item["name"]: item for item in listed["items"]}
    assert by_name["From the UI"]["created_by"] is None
    assert by_name["From the API"]["created_by"] == "api:Inventory"

    full = (await client.get(f"{V1}/labels/{ui_label['id']}", headers=api_headers)).json()
    assert full["zpl"] == SIMPLE
    assert full["created_by"] is None
    assert "Local user" not in (await client.get(f"{V1}/labels", headers=api_headers)).text
    assert api_label["zpl"] == SIMPLE


# ---- retries after a failure ----------------------------------------------------------------


async def test_a_failure_after_sending_keeps_the_idempotency_key(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, monkeypatch
):
    """If the data may have reached the printer, the label may still come out; the same key must
    not print it again."""
    sent: list[str] = []

    async def send(self, data):
        sent.append(data)
        raise PrinterError(
            "Failed to send data: timed out (the printer may still print it)", maybe_sent=True
        )

    monkeypatch.setattr(PrinterClient, "send", send)
    headers = {**api_headers, "Idempotency-Key": "maybe"}
    body = {"zpl": "^XA^FDmaybe^FS^XZ"}

    first = await client.post(f"{V1}/print", headers=headers, json=body)
    assert first.status_code == 502
    assert first.json()["status"] == "failed"
    assert "may still print" in first.json()["error"]
    assert "idempotent-replay" not in first.headers

    again = await client.post(f"{V1}/print", headers=headers, json=body)
    assert again.status_code == 502
    assert again.headers["idempotent-replay"] == "true"
    assert again.json()["id"] == first.json()["id"]
    assert len(sent) == 1

    # A different request with the key is still a conflict, and a new key prints again.
    other = await client.post(f"{V1}/print", headers=headers, json={"zpl": "^XA^FDother^FS^XZ"})
    assert other.status_code == 409
    fresh = await client.post(
        f"{V1}/print", headers={**api_headers, "Idempotency-Key": "new"}, json=body
    )
    assert fresh.status_code == 502
    assert fresh.json()["id"] != first.json()["id"]
    assert len(sent) == 2


async def test_a_failure_before_sending_leaves_the_key_free(
    client: httpx.AsyncClient, api_headers: dict, printer: dict, monkeypatch
):
    attempts = 0

    async def send(self, data):
        nonlocal attempts
        attempts += 1
        raise PrinterError("Cannot connect to the printer")

    monkeypatch.setattr(PrinterClient, "send", send)
    headers = {**api_headers, "Idempotency-Key": "free"}
    for expected in (1, 2):
        response = await client.post(f"{V1}/print", headers=headers, json={"zpl": "^XA^XZ"})
        assert response.status_code == 502
        assert "idempotent-replay" not in response.headers
        assert attempts == expected


async def test_duplicates_wait_a_bounded_time_for_a_request_still_printing(
    client: httpx.AsyncClient,
    app: FastAPI,
    api_token: dict,
    api_headers: dict,
    printer: dict,
    emulator: PrinterEmulator,
    monkeypatch,
):
    monkeypatch.setattr(routes, "lock_wait", lambda settings: 0.5)
    headers = {**api_headers, "Idempotency-Key": "busy"}
    body = {"zpl": "^XA^FDbusy^FS^XZ"}

    # Another request holds the key (a print in flight): the duplicate gives up, politely.
    async with app.state.engine.connect() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": routes.lock_key(api_token["id"], "busy")},
        )
        started = time.monotonic()
        waited = await client.post(f"{V1}/print", headers=headers, json=body)
        elapsed = time.monotonic() - started
        await holder.rollback()
    assert waited.status_code == 409
    assert waited.headers["retry-after"] == "5"
    assert 0.4 < elapsed < 5
    assert emulator.state.data == b""

    # Once the other request is done the key is usable again.
    assert (await client.post(f"{V1}/print", headers=headers, json=body)).status_code == 200
