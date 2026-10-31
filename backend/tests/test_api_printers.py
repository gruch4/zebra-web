import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from app.main import create_app
from app.printer.emulator import PrinterEmulator
from tests.conftest import make_settings


async def test_health(client: httpx.AsyncClient):
    response = await client.get("/api/health")
    assert response.json() == {"status": "ok"}


async def test_me_without_auth(client: httpx.AsyncClient):
    response = await client.get("/api/me")
    assert response.json()["auth_enabled"] is False
    assert response.json()["sub"] == "local"


async def test_printer_crud_and_default_handling(client: httpx.AsyncClient):
    first = (await client.post("/api/printers", json={"name": "A", "host": "10.0.0.1"})).json()
    assert first["is_default"] is True  # first printer becomes default
    second = (
        await client.post(
            "/api/printers", json={"name": "B", "host": "10.0.0.2", "is_default": True}
        )
    ).json()
    printers = (await client.get("/api/printers")).json()
    assert [(p["name"], p["is_default"]) for p in printers] == [("B", True), ("A", False)]

    updated = await client.put(
        f"/api/printers/{first['id']}",
        json={"name": "A2", "host": "10.0.0.3", "port": 9101, "dpi": 300, "is_default": True},
    )
    assert updated.json()["port"] == 9101
    assert (await client.get(f"/api/printers/{second['id']}")).json()["is_default"] is False

    assert (await client.delete(f"/api/printers/{first['id']}")).status_code == 204
    assert (await client.get(f"/api/printers/{second['id']}")).json()["is_default"] is True
    assert (await client.get(f"/api/printers/{first['id']}")).status_code == 404


async def test_printer_validation(client: httpx.AsyncClient):
    response = await client.post("/api/printers", json={"name": "", "host": "x", "port": 0})
    assert response.status_code == 422
    too_long = {"name": "P", "host": "printer.local", "model": "x" * 101}
    assert (await client.post("/api/printers", json=too_long)).status_code == 422
    # Names DNS cannot encode: an empty label, or a label over 63 characters.
    for host in ("a..b", "x" * 64 + ".local"):
        response = await client.post("/api/printers", json={"name": "P", "host": host})
        assert response.status_code == 422, response.text
        assert "Invalid printer host name" in response.json()["detail"]


async def test_connection_test(client: httpx.AsyncClient, emulator: PrinterEmulator, closed_port):
    ok = await client.post("/api/printers/test", json={"host": "127.0.0.1", "port": emulator.port})
    assert ok.json() == {
        "ok": True,
        "model": "ZD420t-203dpi",
        "firmware": "V84.20.23Z",
        "dpi": 203,
        "error": None,
    }
    failed = await client.post(
        "/api/printers/test", json={"host": "127.0.0.1", "port": closed_port}
    )
    assert failed.json()["ok"] is False
    assert "Cannot connect" in failed.json()["error"]


def restrict_printers(app: FastAPI, monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Production rules (no loopback) with only `port` allowed."""
    strict = make_settings(printer_allowed_ports=str(port), printer_allow_loopback=False)
    # Starlette's State keeps its attributes in `_state`, not in `__dict__`: since pytest 9.2,
    # `monkeypatch.setattr` would delete the settings on undo instead of restoring them.
    monkeypatch.setitem(app.state._state, "settings", strict)


@pytest.mark.parametrize(
    ("host", "port", "reason"),
    [
        ("127.0.0.1", 9100, "loopback"),
        ("localhost", 9100, "loopback"),
        ("::ffff:127.0.0.1", 9100, "loopback"),
        ("169.254.169.254", 9100, "cannot be used"),
        ("0.0.0.0", 9100, "cannot be used"),
        ("10.0.0.1", 5432, "Port 5432"),
    ],
)
async def test_printer_address_must_be_allowed(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch, host: str, port: int, reason: str
):
    restrict_printers(app, monkeypatch, 9100)
    refused = await client.post("/api/printers", json={"name": "X", "host": host, "port": port})
    assert refused.status_code == 422
    assert reason in refused.json()["detail"]

    created = await client.post("/api/printers", json={"name": "P", "host": "10.0.0.1"})
    assert created.status_code == 201
    printer_id = created.json()["id"]
    moved = await client.put(
        f"/api/printers/{printer_id}", json={"name": "P", "host": host, "port": port}
    )
    assert moved.status_code == 422
    assert reason in moved.json()["detail"]
    assert (await client.get(f"/api/printers/{printer_id}")).json()["host"] == "10.0.0.1"


async def test_connection_test_refuses_blocked_addresses(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch, emulator: PrinterEmulator
):
    restrict_printers(app, monkeypatch, emulator.port)
    loopback = await client.post(
        "/api/printers/test", json={"host": "127.0.0.1", "port": emulator.port}
    )
    assert loopback.json()["ok"] is False
    assert "loopback" in loopback.json()["error"]
    port = await client.post("/api/printers/test", json={"host": "10.0.0.1", "port": 6379})
    assert port.json()["ok"] is False
    assert "Port 6379" in port.json()["error"]
    assert emulator.state.received == []


async def test_stored_printer_with_blocked_address_is_not_contacted(
    client: httpx.AsyncClient, app: FastAPI, monkeypatch, printer: dict, emulator
):
    # The printer was saved before loopback was refused.
    restrict_printers(app, monkeypatch, emulator.port)
    status = (await client.get(f"/api/printers/{printer['id']}/status")).json()
    assert status["online"] is False
    assert "loopback" in status["error"]
    job = (await client.post("/api/print", json={"zpl": "^XA^FDx^FS^XZ"})).json()
    assert job["status"] == "failed"
    assert "loopback" in job["error"]
    assert emulator.state.received == []


async def test_identify_updates_printer(client: httpx.AsyncClient, printer: dict, emulator):
    emulator.state.dpmm = 12
    response = await client.post(f"/api/printers/{printer['id']}/identify")
    assert response.json()["dpi"] == 300
    assert response.json()["model"] == "ZD420t-203dpi"


async def test_status(client: httpx.AsyncClient, printer: dict, emulator: PrinterEmulator):
    status = (await client.get(f"/api/printers/{printer['id']}/status")).json()
    assert status["online"] and status["ready"]
    emulator.state.head_open = True
    status = (await client.get(f"/api/printers/{printer['id']}/status")).json()
    assert status["ready"] is False
    assert status["problems"] == ["Head open"]


async def test_status_offline(client: httpx.AsyncClient, closed_port):
    created = await client.post(
        "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
    )
    status = (await client.get(f"/api/printers/{created.json()['id']}/status")).json()
    assert status["online"] is False
    assert status["error"]


async def test_read_settings(client: httpx.AsyncClient, printer: dict):
    data = (await client.get(f"/api/printers/{printer['id']}/settings")).json()
    settings = {s["name"]: s for s in data["settings"]}
    assert settings["print_width"]["value"] == "832"
    assert settings["darkness"]["choices"] == "0.0 to 30.0"
    assert data["info"]["friendly_name"] == "EMULATOR"
    assert data["info"]["ip_address"] == "192.168.1.50"  # wired, not ip.addr 0.0.0.0
    raw = (await client.get(f"/api/printers/{printer['id']}/settings/raw")).json()
    assert {"key": "media.speed", "value": "4", "choices": "2 to 6"} in raw


async def test_write_settings(client: httpx.AsyncClient, printer: dict, emulator):
    response = await client.put(
        f"/api/printers/{printer['id']}/settings", json={"darkness": 22, "speed": 3}
    )
    assert response.status_code == 200
    assert response.json()["sent"] == "~SD22\n^XA^PR3^JUS^XZ\n"
    assert b"~SD22" in emulator.state.data
    empty = await client.put(f"/api/printers/{printer['id']}/settings", json={})
    assert empty.status_code == 422
    invalid = await client.put(f"/api/printers/{printer['id']}/settings", json={"darkness": 99})
    assert invalid.status_code == 422


async def test_actions(client: httpx.AsyncClient, printer: dict, emulator: PrinterEmulator):
    actions = (await client.get("/api/printers/actions")).json()
    assert {"action": "calibrate", "description": "Calibrate media and ribbon sensors"} in actions
    feed = await client.post(f"/api/printers/{printer['id']}/actions/feed")
    assert feed.json()["sent"] == "^XA^PH^XZ"  # a format with ^PH feeds one blank label
    response = await client.post(f"/api/printers/{printer['id']}/actions/calibrate")
    assert response.json()["sent"] == "~JC"
    assert emulator.state.data.endswith(b"~JC")
    unknown = await client.post(f"/api/printers/{printer['id']}/actions/explode")
    assert unknown.status_code == 404


async def test_settings_unreachable_returns_502(client: httpx.AsyncClient, closed_port):
    created = await client.post(
        "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
    )
    response = await client.get(f"/api/printers/{created.json()['id']}/settings")
    assert response.status_code == 502


async def test_spa_fallback(tmp_path, migrated_db):
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    application = create_app(make_settings(static_dir=tmp_path))
    async with LifespanManager(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            assert (await http.get("/designer/5")).text == "<html>app</html>"
            assert (await http.get("/assets/app.js")).text == "console.log(1)"
            assert (await http.get("/api/nope")).status_code == 404
            assert (await http.get("/api/health")).json() == {"status": "ok"}


async def test_settings_are_read_once_and_refreshed_after_changes(
    client: httpx.AsyncClient, printer: dict, emulator: PrinterEmulator
):
    def allcv_requests() -> int:
        return emulator.state.data.count(b"allcv")

    await client.get(f"/api/printers/{printer['id']}/settings")
    await client.get(f"/api/printers/{printer['id']}/settings/raw")
    assert allcv_requests() == 1  # the form and the raw list share one read
    await client.get(f"/api/printers/{printer['id']}/settings", params={"refresh": True})
    assert allcv_requests() == 2
    await client.put(f"/api/printers/{printer['id']}/settings", json={"darkness": 10})
    await client.get(f"/api/printers/{printer['id']}/settings")
    assert allcv_requests() == 3  # a change makes the next read go to the printer


async def test_device_info_falls_back_to_identification(client: httpx.AsyncClient, printer):
    await client.post(f"/api/printers/{printer['id']}/identify")
    info = (await client.get(f"/api/printers/{printer['id']}/settings")).json()["info"]
    assert info["model"] == "ZD420t-203dpi"
