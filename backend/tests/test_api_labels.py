import csv
import io
import json

import httpx
import yaml
from openpyxl import load_workbook

from tests.conftest import png_image

DESIGN = {
    "width_mm": 50,
    "height_mm": 25,
    "dpi": 203,
    "elements": [
        {"type": "text", "id": "t", "x": 10, "y": 10, "text": "{{name}}"},
        {"type": "barcode", "id": "b", "x": 10, "y": 60, "data": "{{sku}}", "height": 50},
    ],
}


async def create_design_label(client: httpx.AsyncClient, **overrides) -> dict:
    body = {"name": "Product", "kind": "design", "design": DESIGN, "tags": ["shop"]} | overrides
    response = await client.post("/api/labels", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_design_label_derives_zpl_and_variables(client: httpx.AsyncClient):
    label = await create_design_label(
        client, variables=[{"name": "sku", "label": "SKU", "default": "000"}]
    )
    assert label["kind"] == "design"
    assert (label["width_mm"], label["height_mm"], label["dpi"]) == (50, 25, 203)
    assert "^FD{{name}}^FS" in label["zpl"]
    assert [v["name"] for v in label["variables"]] == ["name", "sku"]
    assert label["variables"][1]["label"] == "SKU"
    assert label["created_by"] == "Local user"


async def test_create_zpl_label_and_validation(client: httpx.AsyncClient):
    response = await client.post(
        "/api/labels", json={"name": "Raw", "kind": "zpl", "zpl": "^XA^FD{{x}}^FS^XZ"}
    )
    assert response.json()["variables"][0]["name"] == "x"
    missing = await client.post("/api/labels", json={"name": "Raw", "kind": "zpl"})
    assert missing.status_code == 422


async def test_update_keeps_variable_metadata(client: httpx.AsyncClient):
    label = await create_design_label(client)
    await client.put(
        f"/api/labels/{label['id']}/variables",
        json=[{"name": "name", "label": "Product name", "required": False}],
    )
    design = json.loads(json.dumps(DESIGN))
    design["elements"].append({"type": "text", "id": "t2", "text": "{{price}}"})
    updated = (
        await client.put(f"/api/labels/{label['id']}", json={"name": "Renamed", "design": design})
    ).json()
    assert updated["name"] == "Renamed"
    variables = {v["name"]: v for v in updated["variables"]}
    assert list(variables) == ["name", "sku", "price"]
    assert variables["name"]["label"] == "Product name"
    assert variables["name"]["required"] is False
    assert "{{price}}" in updated["zpl"]


async def test_list_filters_and_tags(client: httpx.AsyncClient):
    await create_design_label(client, name="Shipping box", tags=["shipping"])
    await client.post(
        "/api/labels",
        json={"name": "Static", "kind": "zpl", "zpl": "^XA^XZ", "description": "plain label"},
    )
    all_labels = (await client.get("/api/labels")).json()
    assert all_labels["total"] == 2
    assert [label["name"] for label in all_labels["items"]] == ["Static", "Shipping box"]
    assert (await client.get("/api/labels", params={"q": "plain"})).json()["total"] == 1
    assert (await client.get("/api/labels", params={"tag": "shipping"})).json()["total"] == 1
    templates = (await client.get("/api/labels", params={"has_variables": True})).json()
    assert [label["name"] for label in templates["items"]] == ["Shipping box"]
    assert (await client.get("/api/labels", params={"kind": "zpl"})).json()["total"] == 1
    assert (await client.get("/api/labels/tags")).json() == ["shipping"]
    page = (await client.get("/api/labels", params={"limit": 1, "offset": 1})).json()
    assert len(page["items"]) == 1 and page["total"] == 2


async def test_duplicate_delete_export(client: httpx.AsyncClient):
    label = await create_design_label(client)
    copy = (await client.post(f"/api/labels/{label['id']}/duplicate")).json()
    assert copy["name"] == "Product (copy)"
    assert copy["design"] == label["design"]

    export = await client.get(f"/api/labels/{label['id']}/export.zpl")
    assert export.text == label["zpl"]
    assert 'filename="Product.zpl"' in export.headers["content-disposition"]

    deleted = await client.delete(f"/api/labels/{label['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/labels/{label['id']}")).status_code == 404


async def test_import_zpl_files(client: httpx.AsyncClient):
    files = [
        ("files", ("first.zpl", b"^XA^FD{{a}}^FS^XZ", "text/plain")),
        ("files", ("second.txt", b"^XA^XZ", "text/plain")),
    ]
    imported = (await client.post("/api/labels/import", files=files)).json()
    assert [label["name"] for label in imported] == ["first", "second"]
    assert imported[0]["variables"][0]["name"] == "a"
    assert imported[0]["tags"] == ["imported"]


async def test_previews(client: httpx.AsyncClient):
    label = await create_design_label(client)
    preview = await client.get(f"/api/labels/{label['id']}/preview.png")
    assert preview.status_code == 200
    assert png_image(preview.content).size == (400, 200)

    blank = await client.post(f"/api/templates/{label['id']}/preview.png", json={"variables": {}})
    filled = await client.post(
        f"/api/templates/{label['id']}/preview.png",
        json={"variables": {"name": "Widget", "sku": "12345"}},
    )
    assert filled.status_code == 200
    assert filled.content != blank.content


async def test_variables_endpoint_and_sample_data(client: httpx.AsyncClient):
    label = await create_design_label(
        client, variables=[{"name": "sku", "type": "number", "default": "7"}]
    )
    variables = (await client.get(f"/api/labels/{label['id']}/variables")).json()
    assert [v["name"] for v in variables] == ["name", "sku"]

    sample_csv = await client.get(f"/api/labels/{label['id']}/sample-data.csv")
    rows = list(csv.DictReader(io.StringIO(sample_csv.text)))
    assert rows == [{"name": "example name", "sku": "7", "copies": "1"}]

    sample_json = (await client.get(f"/api/labels/{label['id']}/sample-data.json")).json()
    assert sample_json[0]["sku"] == "7"

    sample_yaml = await client.get(f"/api/labels/{label['id']}/sample-data.yaml")
    assert yaml.safe_load(sample_yaml.text)[0]["copies"] == "1"

    sample_xlsx = await client.get(f"/api/labels/{label['id']}/sample-data.xlsx")
    sheet = load_workbook(io.BytesIO(sample_xlsx.content)).active
    assert [cell.value for cell in sheet[1]] == ["name", "sku", "copies"]

    unknown = await client.get(f"/api/labels/{label['id']}/sample-data.pdf")
    assert unknown.status_code == 422


async def test_print_label_from_archive(client: httpx.AsyncClient, printer, emulator):
    label = await create_design_label(client, variables=[{"name": "sku", "default": "999"}])
    job = (
        await client.post(
            "/api/print", json={"label_id": label["id"], "variables": {"name": "Widget"}}
        )
    ).json()
    assert job["source"] == "archive"
    assert job["label_id"] == label["id"]
    assert job["label_name"] == "Product"
    assert job["variables"] == {"name": "Widget", "sku": "999"}
    assert b"^FDWidget^FS" in emulator.state.data
    template_job = (
        await client.post(
            "/api/print",
            json={"label_id": label["id"], "variables": {"name": "X"}, "source": "template"},
        )
    ).json()
    assert template_job["source"] == "template"


async def test_export_with_non_latin1_name(client: httpx.AsyncClient):
    label = (
        await client.post("/api/labels", json={"name": "Żółw ąę", "kind": "zpl", "zpl": "^XA^XZ"})
    ).json()
    response = await client.get(f"/api/labels/{label['id']}/export.zpl")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="___w __.zpl"' in disposition
    assert "filename*=UTF-8''%C5%BB%C3%B3%C5%82w%20%C4%85%C4%99.zpl" in disposition


async def test_long_import_name_and_size_limits(client: httpx.AsyncClient):
    files = [("files", ("x" * 300 + ".zpl", b"^XA^XZ", "text/plain"))]
    imported = (await client.post("/api/labels/import", files=files)).json()
    assert imported[0]["name"] == "x" * 200
    copy = (await client.post(f"/api/labels/{imported[0]['id']}/duplicate")).json()
    assert copy["name"] == "x" * 193 + " (copy)"
    too_big = await client.post(
        "/api/labels", json={"name": "B", "kind": "zpl", "zpl": "^XA^XZ", "height_mm": 5000}
    )
    assert too_big.status_code == 422


async def test_malformed_image_in_design_is_rejected(client: httpx.AsyncClient):
    design = {
        "elements": [
            {
                "type": "image",
                "id": "i",
                "width": 8,
                "height": 4,
                "bytes_per_row": 1,
                "data": "AA==",
            }
        ]
    }
    response = await client.post(
        "/api/labels", json={"name": "I", "kind": "design", "design": design}
    )
    assert response.status_code == 422
