"""Which addresses printer connections may go to.

Users add printers by host and port, and the app sends them raw data. Without limits the printer
endpoints could reach any TCP service the server can (the database, cloud metadata, the app
itself) and send it arbitrary bytes, so connections only go to printer ports and never to
loopback, link-local or other special addresses.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

# "This network": connecting to 0.0.0.0 reaches the local host on Linux.
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")


class AddressNotAllowed(ValueError):
    pass


def parse_ports(spec: str) -> tuple[tuple[int, int], ...]:
    """Parse "6101,9100-9109" into inclusive port ranges."""
    ranges = []
    for part in spec.split(","):
        if not part.strip():
            continue
        low, _, high = part.strip().partition("-")
        try:
            first, last = int(low), int(high or low)
        except ValueError:
            raise ValueError(f"Invalid port or port range {part.strip()!r}") from None
        if not 1 <= first <= last <= 65535:
            raise ValueError(f"Invalid port or port range {part.strip()!r}")
        ranges.append((first, last))
    if not ranges:
        raise ValueError("No ports given")
    return tuple(ranges)


@dataclass(frozen=True, slots=True)
class AddressPolicy:
    ports: tuple[tuple[int, int], ...]
    allow_loopback: bool = False

    def check_port(self, port: int) -> None:
        if not any(first <= port <= last for first, last in self.ports):
            allowed = ", ".join(
                str(first) if first == last else f"{first}-{last}" for first, last in self.ports
            )
            raise AddressNotAllowed(
                f"Port {port} is not allowed for printers (allowed: {allowed}); "
                "set PRINTER_ALLOWED_PORTS to change this"
            )

    def check_ip(self, address: str) -> None:
        ip = ipaddress.ip_address(address.partition("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_loopback:
            if not self.allow_loopback:
                raise AddressNotAllowed(
                    f"{address} is a loopback address; "
                    "set PRINTER_ALLOW_LOOPBACK=true to use it for printers"
                )
        elif (
            ip.is_link_local
            or ip.is_unspecified
            or ip.is_multicast
            or ip.is_reserved
            or ip in _THIS_NETWORK
        ):
            raise AddressNotAllowed(f"{address} cannot be used as a printer address")

    async def resolve(self, host: str, port: int) -> list[str]:
        """Check the port and every address `host` resolves to, and return those addresses.

        Callers connect to the returned addresses rather than to the name, so a DNS answer that
        changes after the check cannot redirect the connection. A name with any disallowed
        address is refused as a whole.
        """
        self.check_port(port)
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
        for address in addresses:
            self.check_ip(address)
        return addresses
