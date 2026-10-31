import httpx
from fastapi import FastAPI

from tests.conftest import png_image


async def test_jobs_and_history_timeline(
    client: httpx.AsyncClient, app: FastAPI, printer, emulator
):
    first = (await client.post("/api/print", json={"zpl": "^XA^FDone^FS^XZ"})).json()
    label = (
        await client.post(
            "/api/labels", json={"name": "Tag", "kind": "zpl", "zpl": "^XA^FD{{v}}^FS^XZ"}
        )
    ).json()
    batch = (
        await client.post(
            "/api/batches",
            json={"label_id": label["id"], "rows": [{"v": "a"}, {"v": "b"}, {"v": "c"}]},
        )
    ).json()
    await app.state.batch_runner.wait(batch["id"])
    second = (
        await client.post("/api/print", json={"label_id": label["id"], "variables": {"v": "z"}})
    ).json()

    jobs = (await client.get("/api/jobs")).json()
    assert jobs["total"] == 5
    assert jobs["items"][0]["id"] == second["id"]

    history = (await client.get("/api/history")).json()
    assert history["total"] == 3  # two single jobs + one batch
    assert [item["kind"] for item in history["items"]] == ["job", "batch", "job"]
    assert history["items"][1]["batch"]["sent"] == 3
    assert history["items"][2]["job"]["id"] == first["id"]

    only_batches = (await client.get("/api/history", params={"source": "batch"})).json()
    assert [item["kind"] for item in only_batches["items"]] == ["batch"]
    only_raw = (await client.get("/api/history", params={"source": "raw"})).json()
    assert [item["job"]["id"] for item in only_raw["items"]] == [first["id"]]
    searched = (await client.get("/api/history", params={"q": "Tag"})).json()
    assert searched["total"] == 2
    failed = (await client.get("/api/history", params={"status": "failed"})).json()
    assert failed["total"] == 0
    by_printer = (await client.get("/api/jobs", params={"printer_id": printer["id"]})).json()
    assert by_printer["total"] == 5


async def test_reprint_preview_and_save_as_label(client: httpx.AsyncClient, printer, emulator):
    job = (
        await client.post("/api/print", json={"zpl": "^XA^PW100^LL50^FO0,0^GB10,10,10^FS^XZ"})
    ).json()
    reprint = (await client.post(f"/api/jobs/{job['id']}/reprint", json={"copies": 2})).json()
    assert reprint["source"] == "reprint"
    assert reprint["copies"] == 2
    assert reprint["zpl"] == job["zpl"]
    assert emulator.state.formats_printed == 2

    preview = await client.get(f"/api/jobs/{job['id']}/preview.png")
    assert png_image(preview.content).size == (100, 50)

    label = (
        await client.post(f"/api/jobs/{job['id']}/save-as-label", json={"name": "From job"})
    ).json()
    assert label["name"] == "From job"
    assert label["zpl"] == job["zpl"]
    assert label["tags"] == ["from-history"]

    assert (await client.get("/api/jobs/9999")).status_code == 404


async def test_reprint_refuses_a_printer_with_another_resolution(
    client: httpx.AsyncClient, printer, emulator
):
    job = (await client.post("/api/print", json={"zpl": "^XA^FO0,0^GB10,10,10^FS^XZ"})).json()
    other = {"name": "300", "host": "127.0.0.1", "port": emulator.port, "dpi": 300}
    other_id = (await client.post("/api/printers", json=other)).json()["id"]
    response = await client.post(f"/api/jobs/{job['id']}/reprint", json={"printer_id": other_id})
    assert response.status_code == 422
    assert "203 dpi" in response.json()["detail"]
