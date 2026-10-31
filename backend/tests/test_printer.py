import asyncio
import time
from unittest.mock import Mock

import pytest

from app.printer.addresses import AddressPolicy
from app.printer.client import PrinterClient, PrinterError
from app.printer.commands import PrinterSettings, curated_settings, device_info, settings_to_zpl
from app.printer.emulator import PrinterEmulator
from app.printer.sgd import parse_allcv, parse_getvar
from app.printer.status import (
    StatusParseError,
    parse_host_identification,
    parse_host_status,
)

HS_OK = (
    "\x02030,0,0,1218,000,0,0,0,000,0,0,0\x03\r\n"
    "\x02000,0,0,0,1,2,6,0,00000000,1,000\x03\r\n"
    "\x021234,0\x03\r\n"
)


def test_parse_host_status_ready():
    status = parse_host_status(HS_OK)
    assert status.ready
    assert status.label_length == 1218
    assert status.thermal_transfer
    assert status.print_mode == "tear"
    assert status.problems == []


def test_parse_host_status_problems():
    raw = (
        "\x02030,1,1,1218,000,0,0,0,000,0,0,0\x03\r\n"
        "\x02000,0,1,1,1,2,6,0,00000000,1,000\x03\r\n"
        "\x021234,0\x03\r\n"
    )
    status = parse_host_status(raw.encode())
    assert not status.ready
    assert status.problems == ["Paper out", "Head open", "Ribbon out", "Paused"]
    assert status.blocking_problems == ["Paper out", "Head open", "Ribbon out"]


def test_parse_host_status_invalid():
    with pytest.raises(StatusParseError):
        parse_host_status("garbage")


def test_parse_host_identification():
    ident = parse_host_identification("\x02ZD420t-300dpi,V84.20.23Z,12,8192KB\x03")
    assert ident.model == "ZD420t-300dpi"
    assert ident.firmware == "V84.20.23Z"
    assert ident.dpi == 300


def test_parse_allcv_and_getvar():
    raw = (
        "ezpl.print_width : 832 , Choices: 2 to 832\r\n"
        'device.friendly_name : "MY PRINTER" , Choices: 0-17 characters\r\n'
        "print.tone : 15.0 , Choices: 0.0 to 30.0\r\n"
        "garbage line without separator\r\n"
    )
    values = parse_allcv(raw)
    assert values["ezpl.print_width"].value == "832"
    assert values["ezpl.print_width"].choices == "2 to 832"
    assert values["device.friendly_name"].value == "MY PRINTER"
    assert parse_getvar(b'"203"') == "203"


@pytest.mark.parametrize(
    "raw",
    [
        'device.friendly_name : "MY PRINTER"\r\nprint.tone : 15.0\r\n',
        # The answer may come quoted as a whole, around quoted values on its first or last line.
        '"device.friendly_name : "MY PRINTER"\r\nprint.tone : 15.0 , Choices: 0.0 to 30.0\r\n"',
        '"print.tone : 15.0\r\ndevice.friendly_name : "MY PRINTER""\r\n',
    ],
)
def test_parse_allcv_quoted_values_without_choices(raw):
    values = parse_allcv(raw)
    assert values["device.friendly_name"].value == "MY PRINTER"
    assert values["print.tone"].value == "15.0"


def test_settings_to_zpl():
    zpl = settings_to_zpl(
        PrinterSettings(
            darkness=20,
            tear_off=-5,
            print_width=832,
            label_length=400,
            speed=4,
            media_tracking="gap",
            print_method="direct",
            print_mode="peel",
            orientation="inverted",
        )
    )
    assert zpl == "~SD20\n~TA-005\n^XA^PW832^LL400^PR4^MNY^MTD^MMP^POI^JUS^XZ\n"


def test_settings_validation():
    with pytest.raises(ValueError):
        PrinterSettings(darkness=31)


def test_curated_settings_uses_fallback_keys():
    values = parse_allcv("media.type : label , Choices: continuous,label\r\nappl.name : V1\r\n")
    by_name = {s["name"]: s for s in curated_settings(values)}
    assert by_name["media_tracking"]["value"] == "label"
    assert by_name["darkness"]["value"] is None
    assert device_info(values)["firmware"] == "V1"


async def test_client_against_emulator(emulator: PrinterEmulator):
    client = PrinterClient("127.0.0.1", emulator.port, timeout=1.0)
    await client.send("^XA^FDtest^FS^XZ")
    status = await client.host_status()
    assert status.ready
    ident = await client.host_identification()
    assert ident.dpi == 203
    assert await client.getvar("ezpl.print_width") == "832"
    settings = await client.all_settings()
    assert settings["print.tone"].value == "15.0"
    assert emulator.state.formats_printed == 1


async def test_client_unreachable(closed_port: int):
    client = PrinterClient("127.0.0.1", closed_port, timeout=0.5)
    with pytest.raises(PrinterError, match="Cannot connect"):
        await client.send("^XA^XZ")


async def test_client_policy(emulator: PrinterEmulator):
    ports = ((emulator.port, emulator.port),)
    blocked = PrinterClient("localhost", emulator.port, timeout=1.0, policy=AddressPolicy(ports))
    with pytest.raises(PrinterError, match="loopback") as excinfo:
        await blocked.send("^XA^XZ")
    assert excinfo.value.maybe_sent is False
    assert emulator.state.received == []
    # "localhost" may resolve to ::1 first, where the emulator is not listening.
    allowed = PrinterClient(
        "localhost", emulator.port, timeout=1.0, policy=AddressPolicy(ports, allow_loopback=True)
    )
    assert (await allowed.host_status()).ready


async def test_a_failure_before_sending_is_not_maybe_sent(closed_port: int):
    client = PrinterClient("127.0.0.1", closed_port, timeout=0.5)
    with pytest.raises(PrinterError) as excinfo:
        await client.send("^XA^XZ")
    assert excinfo.value.maybe_sent is False


async def test_a_failure_while_sending_may_still_print():
    """A printer that accepts the connection but stops reading: part of the data may arrive."""

    async def stall(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(30)

    server = await asyncio.start_server(stall, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        client = PrinterClient("127.0.0.1", port, timeout=0.3)
        started = time.monotonic()
        # More than the socket buffers hold, so the write cannot complete.
        with pytest.raises(PrinterError, match="may still print it") as excinfo:
            await client.send("^XA" + "A" * 40_000_000 + "^XZ")
        assert excinfo.value.maybe_sent is True
        # Closing the stuck connection is bounded too, so the printer is not locked forever.
        assert time.monotonic() - started < 3
    finally:
        server.close()


async def test_a_connection_that_cannot_close_is_dropped():
    """If closing times out (the printer stopped reading), the connection is aborted."""

    async def never_closes() -> None:
        await asyncio.sleep(30)

    writer = Mock()
    writer.wait_closed = never_closes
    await PrinterClient("127.0.0.1", 9100, timeout=0.1)._close(writer)
    writer.close.assert_called_once()
    writer.transport.abort.assert_called_once()


async def test_client_no_response(emulator: PrinterEmulator):
    emulator.state.silent = True
    client = PrinterClient("127.0.0.1", emulator.port, timeout=0.3)
    with pytest.raises(PrinterError, match="No response"):
        await client.host_status()


async def test_query_budget_starts_after_waiting_for_the_lock(emulator: PrinterEmulator):
    client = PrinterClient("127.0.0.1", emulator.port, timeout=0.5)
    async with client._lock:
        waiting = asyncio.create_task(client.host_status())
        await asyncio.sleep(0.7)  # longer than the whole timeout
    status = await waiting
    assert status.ready


async def test_settings_list_survives_pauses_in_the_answer(emulator: PrinterEmulator):
    # Real printers pause while answering allcv (e.g. reading the Bluetooth radio).
    emulator.state.allcv_pause = 1.5
    settings = await PrinterClient("127.0.0.1", emulator.port, timeout=1.0).all_settings()
    assert set(settings) == set(emulator.state.settings)


def test_device_info_prefers_the_wired_address():
    values = parse_allcv(
        "ip.addr : 0.0.0.0\r\ninternal_wired.ip.addr : 10.0.0.7\r\n"
        "wlan.mac_addr : 00:00:00:00:00:00\r\n"
    )
    info = device_info(values)
    assert info["ip_address"] == "10.0.0.7"
    assert info["mac_address"] is None
