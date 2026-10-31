"""A minimal Zebra printer emulator listening on a TCP port.

It records every received payload, counts printed formats and answers the
status/identification/SGD queries the app uses. Run it with:

    python -m app.printer.emulator --port 9100

Add `--check` to probe a running emulator instead (exit code 0 when it answers ~HS);
docker-compose uses this as the container healthcheck.
"""

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field

from app.printer.client import PrinterClient, PrinterError

log = logging.getLogger("printer-emulator")

_GETVAR_RE = re.compile(rb'!\s*U1\s+getvar\s+"([^"]+)"', re.IGNORECASE)

DEFAULT_SETTINGS: dict[str, tuple[str, str | None]] = {
    "device.friendly_name": ("EMULATOR", "0-17 characters"),
    "appl.name": ("V84.20.23Z", None),
    "device.unique_id": ("D4J000000001", None),
    "head.resolution.in_dpi": ("203", None),
    "ezpl.print_width": ("832", "2 to 832"),
    "zpl.label_length": ("1218", "1 to 32000"),
    "print.tone": ("15.0", "0.0 to 30.0"),
    "media.speed": ("4", "2 to 6"),
    "ezpl.media_type": ("gap/notch", "continuous,gap/notch,mark"),
    "ezpl.print_method": ("thermal trans", "direct thermal,thermal trans"),
    "media.printmode": ("tear off", "tear off,peel off,rewind,applicator,cutter,delayed cut"),
    "ezpl.tear_off": ("0", "-120 to 120"),
    "zpl.label_top": ("0", "-120 to 120"),
    "zpl.left_position": ("0", "-9999 to 9999"),
    "zpl.print_orientation": ("normal", "normal,invert"),
    "odometer.total_print_length": ("1234 INCHES, 3134 CENTIMETERS", None),
    "ip.addr": ("0.0.0.0", None),
    "internal_wired.ip.addr": ("192.168.1.50", None),
}


@dataclass
class EmulatorState:
    dpmm: int = 8
    model: str = "ZD420t-203dpi"
    paper_out: bool = False
    head_open: bool = False
    paused: bool = False
    settings: dict[str, tuple[str, str | None]] = field(
        default_factory=lambda: dict(DEFAULT_SETTINGS)
    )
    received: list[bytes] = field(default_factory=list)
    silent: bool = False
    allcv_pause: float = 0.0  # seconds of silence in the middle of the allcv answer

    @property
    def data(self) -> bytes:
        return b"".join(self.received)

    @property
    def formats_printed(self) -> int:
        return self.data.upper().count(b"^XZ")

    def host_status(self) -> bytes:
        s1 = f"030,{int(self.paper_out)},{int(self.paused)},1218,000,0,0,0,000,0,0,0"
        s2 = f"000,0,{int(self.head_open)},0,1,2,6,0,00000000,1,000"
        s3 = "1234,0"
        return f"\x02{s1}\x03\r\n\x02{s2}\x03\r\n\x02{s3}\x03\r\n".encode()

    def host_identification(self) -> bytes:
        return f"\x02{self.model},V84.20.23Z,{self.dpmm},8192KB\x03\r\n".encode()

    def allcv(self) -> bytes:
        lines = []
        for key, (value, choices) in self.settings.items():
            line = f"{key} : {value}"
            if choices:
                line += f" , Choices: {choices}"
            lines.append(line)
        return ("\r\n".join(lines) + "\r\n").encode()

    def respond(self, chunk: bytes) -> bytes:
        if self.silent:
            return b""
        out = b""
        upper = chunk.upper()
        if b"~HS" in upper:
            out += self.host_status()
        if b"~HI" in upper:
            out += self.host_identification()
        for match in _GETVAR_RE.finditer(chunk):
            key = match.group(1).decode()
            if key == "allcv":
                out += self.allcv()
            else:
                value = self.settings.get(key, ("?", None))[0]
                out += f'"{value}"'.encode()
        return out


class PrinterEmulator:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.state = EmulatorState()
        self._server: asyncio.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while chunk := await reader.read(65536):
                self.state.received.append(chunk)
                log.info(
                    "received %d bytes (%d formats total)", len(chunk), self.state.formats_printed
                )
                reply = self.state.respond(chunk)
                if reply and self.state.allcv_pause and b"allcv" in chunk:
                    middle = len(reply) // 2
                    writer.write(reply[:middle])
                    await writer.drain()
                    await asyncio.sleep(self.state.allcv_pause)
                    reply = reply[middle:]
                if reply:
                    writer.write(reply)
                    await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> PrinterEmulator:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()


async def _main(host: str, port: int) -> None:
    emulator = PrinterEmulator(host, port)
    await emulator.start()
    log.info("Zebra emulator listening on %s:%d", host, emulator.port)
    await asyncio.Event().wait()


async def _check(host: str, port: int) -> bool:
    try:
        await PrinterClient(host, port, timeout=3.0).host_status()
    except PrinterError as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument(
        "--check", action="store_true", help="probe a running emulator with ~HS and exit"
    )
    args = parser.parse_args()
    if args.check:
        host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        sys.exit(0 if asyncio.run(_check(host, args.port)) else 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(_main(args.host, args.port))
