"""Async TCP client for Zebra printers (raw port 9100)."""

import asyncio
import time
from collections.abc import Callable
from typing import ClassVar

from app.printer.addresses import AddressNotAllowed, AddressPolicy
from app.printer.sgd import SgdValue, parse_allcv, parse_getvar
from app.printer.status import (
    HostIdentification,
    PrinterStatus,
    StatusParseError,
    parse_host_identification,
    parse_host_status,
)

ALLCV_IDLE_SECONDS = 3.0
ALLCV_MAX_SECONDS = 30.0


class PrinterError(Exception):
    def __init__(self, message: str, *, maybe_sent: bool = False) -> None:
        super().__init__(message)
        # True when the failure happened after the data was handed to the connection, so the
        # printer may still print it. False when nothing was sent (e.g. cannot connect).
        self.maybe_sent = maybe_sent


def _etx_count(count: int) -> Callable[[bytes], bool]:
    return lambda buf: buf.count(b"\x03") >= count


class PrinterClient:
    # Zebra printers handle one connection at a time; serialize access per printer.
    _locks: ClassVar[dict[tuple[str, int], asyncio.Lock]] = {}

    def __init__(
        self,
        host: str,
        port: int = 9100,
        timeout: float = 5.0,
        settings_idle: float = ALLCV_IDLE_SECONDS,
        policy: AddressPolicy | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.settings_idle = settings_idle
        # Where connections may go; None allows any address (tools and tests only).
        self.policy = policy

    @property
    def _lock(self) -> asyncio.Lock:
        return self._locks.setdefault((self.host, self.port), asyncio.Lock())

    async def _open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self.policy is None:
            return await asyncio.open_connection(self.host, self.port)
        # Connect to the checked addresses, not the name, so DNS cannot change them in between.
        # Try each like open_connection does for a name; the last one's error is reported.
        addresses = await self.policy.resolve(self.host, self.port)
        for address in addresses[:-1]:
            try:
                return await asyncio.open_connection(address, self.port)
            except OSError:
                pass
        return await asyncio.open_connection(addresses[-1], self.port)

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            return await asyncio.wait_for(self._open(), timeout=self.timeout)
        except AddressNotAllowed as exc:
            raise PrinterError(str(exc)) from exc
        except TimeoutError as exc:
            raise PrinterError(f"Timed out connecting to {self.host}:{self.port}") from exc
        except OSError as exc:
            raise PrinterError(f"Cannot connect to {self.host}:{self.port}: {exc}") from exc

    async def _close(self, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=self.timeout)
        # TimeoutError is an OSError, so it has to be handled first.
        except TimeoutError:
            # A printer that stopped reading never lets buffered data flush, so closing would
            # wait (holding this printer's lock) forever: drop the connection instead.
            writer.transport.abort()
        except OSError:
            pass  # the connection already broke: nothing is left to close

    async def send(self, data: str | bytes) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        async with self._lock:
            _, writer = await self._connect()
            try:
                writer.write(payload)
                await asyncio.wait_for(writer.drain(), timeout=self.timeout)
            except (TimeoutError, OSError) as exc:
                raise PrinterError(
                    f"Failed to send data to {self.host}:{self.port}: {exc or type(exc).__name__}"
                    " (the printer may still print it)",
                    maybe_sent=True,
                ) from exc
            finally:
                await self._close(writer)

    async def query(
        self,
        command: str,
        *,
        done: Callable[[bytes], bool] | None = None,
        idle: float = 0.5,
        max_wait: float | None = None,
    ) -> bytes:
        """Send a command and collect the response.

        Reading stops when `done(buffer)` is true, when no data arrives for `idle` seconds
        after the first byte, or when the overall timeout elapses.
        """
        async with self._lock:
            reader, writer = await self._connect()
            # The read budget starts once we own the connection, not while queued for the lock.
            deadline = time.monotonic() + (max_wait or self.timeout)
            try:
                writer.write(command.encode("utf-8"))
                await writer.drain()
                buf = b""
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    wait = min(remaining, idle) if buf else remaining
                    try:
                        chunk = await asyncio.wait_for(reader.read(65536), timeout=wait)
                    except TimeoutError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    if done and done(buf):
                        break
            except OSError as exc:
                raise PrinterError(f"Communication error with {self.host}:{self.port}") from exc
            finally:
                await self._close(writer)
        if not buf:
            raise PrinterError(f"No response from {self.host}:{self.port} to {command.strip()!r}")
        return buf

    async def host_status(self) -> PrinterStatus:
        raw = await self.query("~HS", done=_etx_count(3))
        try:
            return parse_host_status(raw)
        except StatusParseError as exc:
            raise PrinterError(str(exc)) from exc

    async def host_identification(self) -> HostIdentification:
        raw = await self.query("~HI", done=_etx_count(1))
        try:
            return parse_host_identification(raw)
        except StatusParseError as exc:
            raise PrinterError(str(exc)) from exc

    async def getvar(self, key: str) -> str:
        raw = await self.query(f'! U1 getvar "{key}"\r\n', done=lambda buf: buf.count(b'"') >= 2)
        return parse_getvar(raw)

    async def all_settings(self) -> dict[str, SgdValue]:
        # Printers send the few hundred settings in bursts and pause while reading slow
        # subsystems (e.g. the Bluetooth radio), so wait longer for the next burst.
        raw = await self.query(
            '! U1 getvar "allcv"\r\n',
            idle=self.settings_idle,
            max_wait=max(ALLCV_MAX_SECONDS, self.timeout * 6),
        )
        return parse_allcv(raw)
