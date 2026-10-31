import io

import httpx
from fastapi import FastAPI
from openpyxl import Workbook

from app.models import PrintBatch
from app.printer.emulator import PrinterEmulator

LABEL = {
    "name": "Price tag",
    "kind": "zpl",
    "zpl": "^XA^FO10,10^A0N,30,30^FD{{name}} {{price}}^FS^XZ",
    "variables": [{"name": "price", "type": "number"}],
}


async def create_label(client: httpx.AsyncClient) -> dict:
    response = await client.post("/api/labels", json=LABEL)
    assert response.status_code == 201
    return response.json()


async def finish(app: FastAPI, batch_id: int) -> None:
    await app.state.batch_runner.wait(batch_id)


async def test_parse_csv_upload(client: httpx.AsyncClient):
    label = await create_label(client)
    content = b"Name;Price;copies\nApple;1.5;2\nPear;abc;1\n"
    response = await client.post(
        "/api/batches/parse",
        data={"label_id": str(label["id"])},
        files={"file": ("prices.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["format"] == "csv"
    assert data["columns"] == ["Name", "Price", "copies"]
    assert data["mapping"] == {"name": "Name", "price": "Price"}
    assert data["copies_column"] == "copies"
    assert (data["valid_count"], data["error_count"]) == (1, 1)
    assert data["preview"][0]["copies"] == 2
    assert data["preview"][1]["errors"] == ["price must be a number"]


async def test_parse_pasted_json_and_xlsx(client: httpx.AsyncClient):
    label = await create_label(client)
    pasted = await client.post(
        "/api/batches/parse",
        data={"label_id": str(label["id"]), "text": '[{"name": "A", "price": 1}]'},
    )
    assert pasted.json()["format"] == "json"
    assert pasted.json()["valid_count"] == 1

    workbook = Workbook()
    workbook.active.append(["name", "price"])
    workbook.active.append(["B", 2])
    buf = io.BytesIO()
    workbook.save(buf)
    xlsx = await client.post(
        "/api/batches/parse",
        data={"label_id": str(label["id"])},
        files={"file": ("d.xlsx", buf.getvalue(), "application/octet-stream")},
    )
    assert xlsx.json()["rows"] == [{"name": "B", "price": "2"}]


async def test_parse_errors(client: httpx.AsyncClient):
    label = await create_label(client)
    nothing = await client.post("/api/batches/parse", data={"label_id": str(label["id"])})
    assert nothing.status_code == 422
    broken = await client.post(
        "/api/batches/parse",
        data={"label_id": str(label["id"]), "text": "{oops", "format": "json"},
    )
    assert broken.status_code == 422
    assert "Invalid JSON" in broken.json()["detail"]


async def test_batch_prints_valid_rows(
    client: httpx.AsyncClient, app: FastAPI, printer, emulator: PrinterEmulator
):
    label = await create_label(client)
    rows = [{"n": f"Item {i}", "p": str(i), "c": "1"} for i in range(5)]
    rows.append({"n": "Bad", "p": "x", "c": "1"})
    rows[0]["c"] = "3"
    body = {
        "label_id": label["id"],
        "rows": rows,
        "mapping": {"name": "n", "price": "p"},
        "copies_column": "c",
        "data_filename": "items.csv",
    }
    response = await client.post("/api/batches", json=body)
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["total"] == 5
    await finish(app, batch["id"])

    batch = (await client.get(f"/api/batches/{batch['id']}")).json()
    assert (batch["status"], batch["sent"], batch["failed"]) == ("done", 5, 0)
    assert batch["data_filename"] == "items.csv"
    assert emulator.state.formats_printed == 5
    assert b"^FDItem 0 0^FS^PQ3^XZ" in emulator.state.data

    jobs = (await client.get("/api/jobs", params={"batch_id": batch["id"]})).json()
    assert jobs["total"] == 5
    assert [job["batch_row"] for job in jobs["items"]] == [0, 1, 2, 3, 4]
    assert all(job["source"] == "batch" for job in jobs["items"])


async def test_batch_selected_rows_and_dry_run(client: httpx.AsyncClient, printer, emulator):
    label = await create_label(client)
    rows = [{"name": "A", "price": "1"}, {"name": "B", "price": "2"}, {"name": "C", "price": "z"}]
    body = {"label_id": label["id"], "rows": rows, "selected": [1, 2]}
    dry = (await client.post("/api/batches/dry-run", json=body)).json()
    assert dry["count"] == 1
    assert dry["zpl"] == "^XA^FO10,10^A0N,30,30^FDB 2^FS^XZ"
    assert [row["index"] for row in dry["skipped"]] == [2]
    assert emulator.state.received == []

    nothing = await client.post(
        "/api/batches", json={"label_id": label["id"], "rows": rows, "selected": [2]}
    )
    assert nothing.status_code == 422


async def test_batch_stops_when_printer_not_ready(
    client: httpx.AsyncClient, app: FastAPI, printer, emulator: PrinterEmulator
):
    label = await create_label(client)
    emulator.state.paper_out = True
    batch = (
        await client.post(
            "/api/batches",
            json={"label_id": label["id"], "rows": [{"name": "A", "price": "1"}]},
        )
    ).json()
    await finish(app, batch["id"])
    batch = (await client.get(f"/api/batches/{batch['id']}")).json()
    assert batch["status"] == "failed"
    assert batch["error"] == "Printer not ready: Paper out"
    assert batch["sent"] == 0
    assert emulator.state.formats_printed == 0


async def test_batch_failure_and_retry(
    client: httpx.AsyncClient, app: FastAPI, emulator: PrinterEmulator, closed_port: int
):
    label = await create_label(client)
    printer = (
        await client.post(
            "/api/printers", json={"name": "P", "host": "127.0.0.1", "port": closed_port}
        )
    ).json()
    rows = [{"name": str(i), "price": "1"} for i in range(3)]
    batch = (await client.post("/api/batches", json={"label_id": label["id"], "rows": rows})).json()
    await finish(app, batch["id"])
    batch = (await client.get(f"/api/batches/{batch['id']}")).json()
    # Chunk size is 2 in tests: the first chunk fails and the batch stops.
    assert (batch["status"], batch["sent"], batch["failed"]) == ("failed", 0, 2)
    assert "Cannot connect" in batch["error"]

    await client.put(
        f"/api/printers/{printer['id']}",
        json={"name": "P", "host": "127.0.0.1", "port": emulator.port},
    )
    retry = (await client.post(f"/api/batches/{batch['id']}/retry-failed")).json()
    assert retry["total"] == 3
    assert retry["data_filename"] == f"Retry of batch #{batch['id']}"
    await finish(app, retry["id"])
    retry = (await client.get(f"/api/batches/{retry['id']}")).json()
    assert (retry["status"], retry["sent"]) == ("done", 3)

    again = await client.post(f"/api/batches/{retry['id']}/retry-failed")
    assert again.status_code == 422


async def test_cancel_and_recover(client: httpx.AsyncClient, app: FastAPI, printer):
    label = await create_label(client)
    async with app.state.sessionmaker() as session:
        queued = PrintBatch(label_id=label["id"], printer_id=printer["id"], status="queued")
        cancelled_before_start = PrintBatch(
            label_id=label["id"],
            printer_id=printer["id"],
            status="queued",
            rows=[{"row": 0, "values": {"name": "A", "price": "1"}, "copies": 1}],
            total=1,
        )
        stale = PrintBatch(label_id=label["id"], printer_id=printer["id"], status="running")
        session.add_all([queued, cancelled_before_start, stale])
        await session.commit()

    cancelled = (await client.post(f"/api/batches/{queued.id}/cancel")).json()
    assert cancelled["status"] == "cancelled"

    runner = app.state.batch_runner
    runner.cancel(cancelled_before_start.id)
    await runner.start(cancelled_before_start.id)
    result = (await client.get(f"/api/batches/{cancelled_before_start.id}")).json()
    assert (result["status"], result["sent"]) == ("cancelled", 0)

    await runner.recover()
    recovered = (await client.get(f"/api/batches/{stale.id}")).json()
    assert recovered["status"] == "failed"
    assert "restart" in recovered["error"]

    listing = (await client.get("/api/batches")).json()
    assert listing["total"] == 3


async def test_long_data_filename_is_truncated(client: httpx.AsyncClient, app: FastAPI, printer):
    label = await create_label(client)
    batch = (
        await client.post(
            "/api/batches",
            json={
                "label_id": label["id"],
                "rows": [{"name": "A", "price": "1"}],
                "data_filename": "d" * 400,
            },
        )
    ).json()
    await finish(app, batch["id"])
    assert batch["data_filename"] == "d" * 255


async def test_retry_refuses_when_printer_was_deleted(
    client: httpx.AsyncClient, app: FastAPI, closed_port: int, emulator: PrinterEmulator
):
    label = await create_label(client)
    default = (
        await client.post(
            "/api/printers", json={"name": "Default", "host": "127.0.0.1", "port": emulator.port}
        )
    ).json()
    broken = (
        await client.post(
            "/api/printers", json={"name": "Broken", "host": "127.0.0.1", "port": closed_port}
        )
    ).json()
    batch = (
        await client.post(
            "/api/batches",
            json={
                "label_id": label["id"],
                "printer_id": broken["id"],
                "rows": [{"name": "A", "price": "1"}],
            },
        )
    ).json()
    await finish(app, batch["id"])
    await client.delete(f"/api/printers/{broken['id']}")
    response = await client.post(f"/api/batches/{batch['id']}/retry-failed")
    assert response.status_code == 409
    assert "printer" in response.json()["detail"]
    assert default["is_default"]
    assert emulator.state.formats_printed == 0


async def test_dry_run_matches_what_the_batch_sends(client: httpx.AsyncClient, printer):
    label = (
        await client.post(
            "/api/labels",
            json={"name": "D", "kind": "zpl", "zpl": "^XA~SD20^MMC^FO0,0^FD{{v}}^FS^JUS^XZ"},
        )
    ).json()
    body = {"label_id": label["id"], "rows": [{"v": "a"}]}
    dry = (await client.post("/api/batches/dry-run", json=body)).json()
    assert dry["zpl"] == "^XA~SD20^FO0,0^FDa^FS^XZ"  # cutter and ^JUS removed, darkness kept
