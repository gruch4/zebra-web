import io
import json
import struct
import zlib

import httpx
import pytest
from PIL import Image, ImageDraw, ImageOps

from app.printer.emulator import PrinterEmulator
from app.render.renderer import render_zpl
from app.services.print_service import apply_copies
from app.zpl.generator import Design, generate_zpl
from tests.conftest import png_image

SIMPLE = "^XA^FO10,10^A0N,30,30^FDHello {{name}}^FS^XZ"


def test_apply_copies():
    assert apply_copies("^XA^XZ", 1) == "^XA^XZ"
    assert apply_copies("^XA^FDx^FS^XZ", 3) == "^XA^FDx^FS^PQ3^XZ"
    assert apply_copies("^XA^PQ2^XZ", 2) == "^XA^PQ2^XZ\n^XA^PQ2^XZ"
    assert apply_copies("^XA^XZ^XA^XZ\n", 2) == "^XA^XZ^XA^XZ\n^XA^XZ^XA^XZ\n"


def test_apply_copies_counts_image_and_format_recalls_but_not_definitions():
    zpl = "^XA^DFF^FS^FO0,0^FN1^FS^XZ^XA^ILR:IMG.GRF^FS^XZ^XA^XFF^FS^FN1^FDa^FS^XZ"
    assert apply_copies(zpl, 2) == (
        "^XA^DFF^FS^FO0,0^FN1^FS^XZ^XA^ILR:IMG.GRF^FS^PQ2^XZ^XA^XFF^FS^FN1^FDa^FS^PQ2^XZ"
    )


def test_apply_copies_keeps_setup_formats_once():
    setup = "^XA~SD15^JUS^XZ\n"
    label = "^XA^FDa^FS^PQ1,,,Y^XZ\n"
    assert apply_copies(setup + label, 3) == setup + "^XA^FDa^FS^PQ3,,,Y^XZ\n"
    # every printable format is multiplied, keeping its own quantity
    two = "^XA^FDa^FS^PQ2^XZ^XA^FDb^FS^XZ"
    assert apply_copies(two, 3) == "^XA^FDa^FS^PQ6^XZ^XA^FDb^FS^PQ3^XZ"


async def test_print_raw_with_variables(client: httpx.AsyncClient, printer, emulator):
    response = await client.post(
        "/api/print", json={"zpl": SIMPLE, "variables": {"name": "World"}, "copies": 2}
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "sent"
    assert job["source"] == "raw"
    assert job["printer_id"] == printer["id"]
    assert job["zpl"] == SIMPLE.replace("{{name}}", "World")
    assert job["variables"] == {"name": "World"}
    assert job["created_by"] == "Local user"
    assert b"^FDHello World^FS^PQ2^XZ" in emulator.state.data


async def test_print_missing_variable_is_rejected(client: httpx.AsyncClient, printer):
    response = await client.post("/api/print", json={"zpl": SIMPLE})
    assert response.status_code == 422
    assert response.json()["detail"]["missing"] == ["name"]


async def test_print_raw_uses_given_definitions(client: httpx.AsyncClient, printer, emulator):
    zpl = "^XA^FDHello {{name}}{{note}}^FS^XZ"
    definitions = [
        {"name": "name", "default": "World"},
        {"name": "note", "required": False},
    ]
    response = await client.post(
        "/api/print", json={"zpl": zpl, "variables": {"note": ""}, "definitions": definitions}
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["zpl"] == "^XA^FDHello World^FS^XZ"
    assert job["variables"] == {"name": "World", "note": ""}


async def test_print_requires_exactly_one_source(client: httpx.AsyncClient, printer):
    response = await client.post("/api/print", json={"zpl": "^XA^XZ", "label_id": 1})
    assert response.status_code == 422


async def test_print_without_printer(client: httpx.AsyncClient):
    response = await client.post("/api/print", json={"zpl": "^XA^XZ"})
    assert response.status_code == 404


async def test_print_failure_is_recorded(client: httpx.AsyncClient, closed_port):
    await client.post(
        "/api/printers", json={"name": "Off", "host": "127.0.0.1", "port": closed_port}
    )
    job = (await client.post("/api/print", json={"zpl": "^XA^XZ"})).json()
    assert job["status"] == "failed"
    assert "Cannot connect" in job["error"]


async def test_print_design(client: httpx.AsyncClient, printer, emulator: PrinterEmulator):
    design = {
        "width_mm": 50,
        "height_mm": 25,
        "elements": [{"type": "text", "id": "t", "text": "SKU {{sku}}"}],
    }
    job = (
        await client.post("/api/print", json={"design": design, "variables": {"sku": "A1"}})
    ).json()
    assert job["source"] == "designer"
    assert "^FDSKU A1^FS" in job["zpl"]


async def test_print_design_uses_given_definitions(client: httpx.AsyncClient, printer, emulator):
    design = {
        "elements": [
            {"type": "text", "id": "t", "text": "SKU {{sku}}"},
            {"type": "text", "id": "n", "text": "{{note}}"},
        ],
    }
    definitions = [{"name": "sku", "default": "B2"}, {"name": "note", "required": False}]
    response = await client.post(
        "/api/print", json={"design": design, "variables": {}, "definitions": definitions}
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert "^FDSKU B2^FS" in job["zpl"]
    assert job["variables"] == {"sku": "B2", "note": ""}

    # Definitions are checked too: a number variable rejects text.
    definitions[0]["type"] = "number"
    response = await client.post("/api/print", json={"design": design, "definitions": definitions})
    assert response.status_code == 422
    assert response.json()["detail"]["invalid"] == {"sku": "must be a number"}


async def test_print_design_refuses_another_resolution(client: httpx.AsyncClient, printer):
    design = {"dpi": 300, "elements": [{"type": "text", "id": "t", "text": "x"}]}
    response = await client.post("/api/print", json={"design": design})
    assert response.status_code == 422
    assert "300 dpi" in response.json()["detail"]


async def test_render_png_and_info(client: httpx.AsyncClient):
    response = await client.post(
        "/api/render",
        json={"zpl": "^XA^FO0,0^GB10,10,10^FS^QQ^XZ", "width_mm": 25, "height_mm": 10},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert json.loads(response.headers["x-render-warnings"]) == ["Unsupported command ^QQ ignored"]
    image = png_image(response.content)
    assert image.size == (200, 80)
    assert image.getpixel((5, 5)) == 0

    info = (await client.post("/api/render/info", json={"zpl": "^XA^XZ^XA^XZ"})).json()
    assert info["label_count"] == 2
    assert info["image"].startswith("data:image/png;base64,")


async def test_render_fills_variables_like_printing(client: httpx.AsyncClient):
    # The designer previews its template with the defaults filled in. In a ^FH field the
    # values, and the placeholders left without one, must show as written.
    design = {"elements": [{"type": "text", "id": "t", "text": "~ {{price}} {{item_ab}}"}]}
    template = (await client.post("/api/designer/zpl", json=design)).json()["zpl"]
    preview = await client.post(
        "/api/render", json={"zpl": template, "variables": {"price": "1_00"}}
    )
    printed_zpl = generate_zpl(Design.model_validate(design), {"price": "1_00"})
    assert "^FH_^FD_7E 1_5F00 {{item_5Fab}}^FS" in printed_zpl
    printed = await client.post("/api/render", json={"zpl": printed_zpl})
    assert preview.content == printed.content


async def test_render_index_out_of_range(client: httpx.AsyncClient):
    response = await client.post("/api/render", json={"zpl": "^XA^XZ", "index": 3})
    assert response.status_code == 422


async def test_detect_variables(client: httpx.AsyncClient):
    response = await client.post("/api/variables", json={"zpl": "{{a}} {{b}} {{a}} {{date}}"})
    assert response.json() == {"variables": ["a", "b"]}


async def test_designer_zpl(client: httpx.AsyncClient):
    design = {"elements": [{"type": "qrcode", "id": "q", "data": "{{url}}"}]}
    data = (await client.post("/api/designer/zpl", json=design)).json()
    assert data["variables"] == ["url"]
    assert "^BQN,2,4^FDMA,{{url}}^FS" in data["zpl"]


async def test_graphic_convert(client: httpx.AsyncClient):
    img = Image.new("RGB", (100, 50), "white")
    ImageDraw.Draw(img).rectangle((0, 0, 49, 49), fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    response = await client.post(
        "/api/graphics/convert",
        files={"file": ("logo.png", buf.getvalue(), "image/png")},
        data={"width": "40"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["width"], data["height"], data["bytes_per_row"]) == (40, 20, 5)
    assert data["zpl"].startswith("^GFA,100,100,5,")
    assert data["preview"].startswith("data:image/png;base64,")

    bad = await client.post(
        "/api/graphics/convert", files={"file": ("x.png", b"not an image", "image/png")}
    )
    assert bad.status_code == 422


def png_header(width: int, height: int) -> bytes:
    """A 1-bit PNG that claims the given size; only its header is valid."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


async def test_graphic_convert_rejects_images_with_too_many_pixels(client: httpx.AsyncClient):
    # 36 MP is over our limit but below Pillow's own check; 400 MP trips Pillow's bomb check.
    for width, height in [(6000, 6000), (20000, 20000)]:
        response = await client.post(
            "/api/graphics/convert",
            files={"file": ("big.png", png_header(width, height), "image/png")},
        )
        assert response.status_code == 413, response.text
        assert "too many pixels" in response.json()["detail"]


async def test_element_preview_rejects_oversized_elements(client: httpx.AsyncClient):
    box = {"type": "box", "id": "b", "width": 99999, "height": 20, "thickness": 2}
    response = await client.post("/api/designer/element-preview", json={"element": box})
    assert response.status_code == 422


async def test_element_preview(client: httpx.AsyncClient):
    box = {"type": "box", "id": "b", "x": 50, "y": 50, "width": 30, "height": 20, "thickness": 20}
    data = (await client.post("/api/designer/element-preview", json={"element": box})).json()
    assert (data["width"], data["height"], data["offset_x"], data["offset_y"]) == (30, 20, 0, 0)
    assert data["image"].startswith("data:image/png;base64,")

    text = {"type": "text", "id": "t", "text": "   "}
    empty = (await client.post("/api/designer/element-preview", json={"element": text})).json()
    assert empty["image"] is None

    ean = {"type": "barcode", "id": "e", "symbology": "ean13", "data": "{{sku}}"}
    failed = (await client.post("/api/designer/element-preview", json={"element": ean})).json()
    assert failed["image"] is None
    assert any("EAN-13" in warning for warning in failed["warnings"])
    # With the variable's default value the barcode can be drawn.
    filled = await client.post(
        "/api/designer/element-preview",
        json={"element": ean, "values": {"sku": "4006381333931"}},
    )
    assert filled.json()["image"] is not None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
async def test_element_preview_is_placed_like_the_printed_field(
    client: httpx.AsyncClient, rotation: int
):
    """The canvas draws the preview at the element's position without rotating it, so the
    preview must land where the full label renders the field."""
    element = {
        "type": "text",
        "id": "t",
        "x": 100,
        "y": 60,
        "text": "BATCH 01",
        "rotation": rotation,
    }
    data = (await client.post("/api/designer/element-preview", json={"element": element})).json()
    design = {"width_mm": 100, "height_mm": 50, "elements": [element]}
    zpl = (await client.post("/api/designer/zpl", json=design)).json()["zpl"]
    full = render_zpl(zpl)
    bbox = ImageOps.invert(Image.open(io.BytesIO(full.png)).convert("L")).getbbox()
    assert bbox == (
        100 + data["offset_x"],
        60 + data["offset_y"],
        100 + data["offset_x"] + data["width"],
        60 + data["offset_y"] + data["height"],
    )
    # The field box contains the ink; rotated a quarter turn it is the cell height wide, plus
    # the dot or two font 0 capitals rise above the cell (docs/print-tests T04).
    assert data["field_width"] >= data["offset_x"] + data["width"]
    assert data["field_height"] >= data["offset_y"] + data["height"]
    if rotation in (90, 270):
        assert 30 <= data["field_width"] <= 32


async def test_designer_preview_zpl_encodes_values_like_printing(client: httpx.AsyncClient):
    design = {"elements": [{"type": "barcode", "id": "b", "data": "{{sku}}"}]}
    template = (await client.post("/api/designer/zpl", json=design)).json()["zpl"]
    assert "^FD{{sku}}^FS" in template
    response = await client.post(
        "/api/designer/preview-zpl", json={"design": design, "values": {"sku": "123456"}}
    )
    assert "^FD>;123456^FS" in response.json()["zpl"]


def test_apply_copies_uses_real_commands_only():
    # ^PQ in field data or a comment is not a command; the last ^PQ is the one that counts.
    zpl = "^XA^FX ^PQ9 ^FS^FO0,0^FD^PQ5^FS^PQ1^PQ2,0,0,N^XZ"
    assert apply_copies(zpl, 3) == "^XA^FX ^PQ9 ^FS^FO0,0^FD^PQ5^FS^PQ1^PQ6,0,0,N^XZ"
    # Changed control characters are honoured.
    assert apply_copies("^XA^CC++FO0,0+FDx+FS+XZ", 2) == "^XA^CC++FO0,0+FDx+FS+PQ2+XZ"


def test_apply_copies_replicates_serial_numbers():
    # Two copies of a series of 10 print each serial number twice, not 20 numbers.
    zpl = "^XA^FO0,0^SN001,1,Y^FS^PQ10^XZ"
    assert apply_copies(zpl, 2) == "^XA^FO0,0^SN001,1,Y^FS^PQ20,,1^XZ"
    assert apply_copies("^XA^FO0,0^FD1^SF%,1^FS^PQ6,0,1^XZ", 3) == (
        "^XA^FO0,0^FD1^SF%,1^FS^PQ18,0,5^XZ"
    )


async def test_print_value_with_caret_in_field_data(client: httpx.AsyncClient, printer, emulator):
    response = await client.post("/api/print", json={"zpl": SIMPLE, "variables": {"name": "A^B"}})
    assert response.status_code == 200, response.text
    assert "^FH_^FDHello A_5EB^FS" in response.json()["zpl"]
    outside = "^XA^FO{{x}},10^FDa^FS^XZ"
    response = await client.post("/api/print", json={"zpl": outside, "variables": {"x": "1^XZ"}})
    assert response.status_code == 422


async def test_render_refuses_control_prefixes_outside_field_data(client: httpx.AsyncClient):
    body = {"zpl": "^XA^FO{{x}},10^FDa^FS^XZ", "variables": {"x": "1^XZ"}}
    response = await client.post("/api/render", json=body)
    assert response.status_code == 422
    assert "x" in response.json()["detail"]["invalid"]


def test_apply_copies_with_a_superscript_quantity():
    assert apply_copies("^XA^FDx^FS^PQ²^XZ", 2) == "^XA^FDx^FS^PQ2^XZ"
