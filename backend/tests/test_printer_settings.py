from pathlib import Path

import httpx

from app.printer.emulator import PrinterEmulator
from app.zpl.printer_settings import DEFAULT_POLICY, strip_printer_settings

FIXTURE = Path(__file__).parent / "fixtures" / "zebradesigner_asn.zpl"
FROM_PRINTER = dict.fromkeys(DEFAULT_POLICY, "printer")


def commands(items) -> list[str]:
    return [item.command for item in items]


def test_default_policy_keeps_label_stock_settings_and_drops_hardware_ones():
    result = strip_printer_settings(FIXTURE.read_text())
    # print mode (cutter), backfeed and print method come from the printer; ^JUS is never sent
    assert commands(result.removed) == ["~JSN", "^MTT", "^JUS", "^MMC"]
    assert commands(result.kept) == [
        "~TA000",
        "^LT0",
        "^MNW",
        "^PON",
        "^PR6,6",
        "~SD15",
        "^LS0",
    ]
    for kept in ("^MNW", "~SD15", "^PW799", "^LL320", "^PQ1,,,Y", "^FDDOC_TITLE^FS"):
        assert kept in result.zpl
    assert "^MMC" not in result.zpl and "^JUS" not in result.zpl
    assert "^MTT" not in result.zpl  # would stop a printer without ribbon
    assert result.removed[3].group == "print_mode"
    assert result.removed[1].group == "print_method"
    assert result.removed[2].group is None  # always removed


def test_every_group_can_come_from_the_printer():
    result = strip_printer_settings(FIXTURE.read_text(), FROM_PRINTER)
    assert result.kept == []
    assert len(result.removed) == 11
    label_only = strip_printer_settings(
        FIXTURE.read_text(), {"print_mode": "label", "print_method": "label"}
    )
    assert "^MMC" in label_only.zpl and "~JSN" in label_only.zpl and "^MTT" in label_only.zpl
    assert commands(label_only.removed) == ["^JUS"]


def test_settings_only_formats_and_sgd_lines_disappear():
    zpl = '! U1 setvar "print.tone" "20"\r\n^XA~SD20^PR4^JUS^XZ\n^XA^FO10,10^FDa^FS^XZ\n'
    result = strip_printer_settings(zpl, FROM_PRINTER)
    assert result.zpl == "^XA^FO10,10^FDa^FS^XZ\n"
    assert {r.description for r in result.removed} == {
        "darkness",
        "print speed",
        "save or restore configuration",
        "SGD printer setting",
    }


def test_unknown_policy_values_fall_back_to_defaults():
    from app.zpl.printer_settings import resolve_policy

    assert resolve_policy({"media": "printer", "bogus": "label", "position": "maybe"}) == (
        DEFAULT_POLICY | {"media": "printer"}
    )


def test_label_without_settings_is_unchanged():
    zpl = "^XA^PW400^FO10,10^FDa^FS^PQ2^XZ"
    assert strip_printer_settings(zpl).zpl == zpl
    assert strip_printer_settings(zpl).removed == []


async def test_printer_policy_is_used_when_printing(
    client: httpx.AsyncClient, printer, emulator: PrinterEmulator
):
    assert printer["label_settings"] == DEFAULT_POLICY
    zpl = "^XA~SD25^MMC^FO10,10^FDa^FS^XZ"
    job = (await client.post("/api/print", json={"zpl": zpl})).json()
    assert job["zpl"] == "^XA~SD25^FO10,10^FDa^FS^XZ"  # darkness from label, cutter from printer

    updated = await client.put(
        f"/api/printers/{printer['id']}/label-settings", json={"darkness_speed": "printer"}
    )
    assert updated.json()["label_settings"]["darkness_speed"] == "printer"
    job = (await client.post("/api/print", json={"zpl": zpl})).json()
    assert job["zpl"] == "^XA^FO10,10^FDa^FS^XZ"

    body = {"zpl": zpl, "keep_printer_settings": True}
    kept = (await client.post("/api/print", json=body)).json()
    assert kept["zpl"] == zpl
    assert b"^MMC" in emulator.state.data


async def test_label_settings_api_validation_and_groups(client: httpx.AsyncClient, printer):
    groups = (await client.get("/api/printers/label-settings")).json()
    assert [g["group"] for g in groups] == [
        "media",
        "print_method",
        "darkness_speed",
        "position",
        "print_mode",
    ]
    assert groups[4] == {
        "group": "print_mode",
        "title": "Print mode (tear-off, peel, cutter) and backfeed",
        "commands": ["JS", "MM", "XB"],
        "default": "printer",
    }
    bad = await client.put(f"/api/printers/{printer['id']}/label-settings", json={"nope": "label"})
    assert bad.status_code == 422
    bad_value = await client.put(
        f"/api/printers/{printer['id']}/label-settings", json={"media": "sometimes"}
    )
    assert bad_value.status_code == 422


async def test_batches_use_the_printer_policy(client: httpx.AsyncClient, app, printer, emulator):
    label = (
        await client.post(
            "/api/labels",
            json={"name": "L", "kind": "zpl", "zpl": "^XA^PR6^MMC^FO0,0^FD{{v}}^FS^JUS^XZ"},
        )
    ).json()
    batch = (
        await client.post("/api/batches", json={"label_id": label["id"], "rows": [{"v": "x"}]})
    ).json()
    await app.state.batch_runner.wait(batch["id"])
    assert b"^XA^PR6^FO0,0^FDx^FS^XZ" in emulator.state.data


async def test_analysis_endpoint_and_preview(client: httpx.AsyncClient, printer):
    zpl = "^XA^POI^MMC^FO0,0^GB10,10,10^FS^XZ"
    data = (await client.post("/api/zpl/printer-settings", json={"zpl": zpl})).json()
    assert data["removed"] == [
        {"command": "^MMC", "description": "print mode", "group": "print_mode"}
    ]
    assert data["kept"] == [
        {"command": "^POI", "description": "print orientation", "group": "position"}
    ]

    await client.put(f"/api/printers/{printer['id']}/label-settings", json={"position": "printer"})
    with_printer = (
        await client.post(
            "/api/zpl/printer-settings", json={"zpl": zpl, "printer_id": printer["id"]}
        )
    ).json()
    assert with_printer["zpl"] == "^XA^FO0,0^GB10,10,10^FS^XZ"

    body = {"zpl": zpl, "width_mm": 10, "height_mm": 10}
    as_pasted = await client.post("/api/render", json=body)
    stripped = await client.post(
        "/api/render", json=body | {"strip_printer_settings": True, "printer_id": printer["id"]}
    )
    # Without a printer id the default printer's policy applies, as when printing.
    default = await client.post("/api/render", json=body | {"strip_printer_settings": True})
    assert as_pasted.content != stripped.content  # ^POI replaced by the printer's orientation
    assert default.content == stripped.content


async def test_reprint_sends_exactly_what_was_sent(
    client: httpx.AsyncClient, printer, emulator: PrinterEmulator
):
    zpl = "^XA^MMC^FO0,0^FDa^FS^XZ"
    job = (await client.post("/api/print", json={"zpl": zpl, "keep_printer_settings": True})).json()
    reprint = (await client.post(f"/api/jobs/{job['id']}/reprint", json={})).json()
    assert reprint["zpl"] == zpl
    assert emulator.state.data.count(b"^MMC") == 2


def test_hardware_memory_and_network_commands_are_always_removed():
    zpl = "^XA^SR200^IDR:*.*^NSS,10.0.0.9,255.255.255.0,10.0.0.1^FO0,0^FDa^FS^XZ~EG~JP^XA^ZZ^XZ"
    result = strip_printer_settings(zpl, {group: "label" for group in DEFAULT_POLICY})
    assert result.zpl == "^XA^FO0,0^FDa^FS^XZ"
    assert {r.description for r in result.removed} == {
        "printhead resistance",
        "object delete",
        "network settings",
        "erase graphics",
        "pause and cancel format",
        "printer sleep",
    }
    assert all(r.group is None for r in result.removed)
