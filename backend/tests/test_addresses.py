import pytest

from app.printer.addresses import AddressNotAllowed, AddressPolicy, parse_ports

PORTS = parse_ports("9100")
LOOPBACK = ["127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1"]
SPECIAL = [
    "169.254.169.254",
    "fe80::1",
    "0.0.0.0",
    "0.1.2.3",
    "::",
    "224.0.0.1",
    "ff02::1",
    "240.0.0.1",
    "255.255.255.255",
]


def test_parse_ports():
    assert parse_ports("6101, 9100-9109,") == ((6101, 6101), (9100, 9109))
    assert parse_ports("1-65535") == ((1, 65535),)


@pytest.mark.parametrize("spec", ["", " , ", "0", "70000", "9109-9100", "a", "1-2-3", "-5"])
def test_parse_ports_rejects(spec: str):
    with pytest.raises(ValueError):
        parse_ports(spec)


@pytest.mark.parametrize("port", [22, 5432, 6379, 8000, 9099, 9110])
def test_port_outside_allowlist(port: int):
    policy = AddressPolicy(parse_ports("6101,9100-9109"))
    with pytest.raises(AddressNotAllowed, match="PRINTER_ALLOWED_PORTS"):
        policy.check_port(port)


@pytest.mark.parametrize("port", [6101, 9100, 9109])
def test_port_in_allowlist(port: int):
    AddressPolicy(parse_ports("6101,9100-9109")).check_port(port)


@pytest.mark.parametrize("address", LOOPBACK)
def test_loopback_needs_opt_in(address: str):
    with pytest.raises(AddressNotAllowed, match="PRINTER_ALLOW_LOOPBACK"):
        AddressPolicy(PORTS).check_ip(address)
    AddressPolicy(PORTS, allow_loopback=True).check_ip(address)


@pytest.mark.parametrize("address", SPECIAL)
def test_special_addresses_are_always_refused(address: str):
    for allow_loopback in (False, True):
        with pytest.raises(AddressNotAllowed):
            AddressPolicy(PORTS, allow_loopback=allow_loopback).check_ip(address)


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "192.168.1.20", "172.18.0.3", "100.64.0.1", "8.8.8.8", "fd00::5"]
)
def test_lan_and_public_addresses_are_allowed(address: str):
    AddressPolicy(PORTS).check_ip(address)


@pytest.mark.parametrize("host", ["localhost", "127.1", "2130706433", "::ffff:127.0.0.1"])
async def test_resolve_checks_resolved_addresses(host: str):
    with pytest.raises(AddressNotAllowed, match="loopback"):
        await AddressPolicy(PORTS).resolve(host, 9100)


async def test_resolve_returns_addresses_to_connect_to():
    assert await AddressPolicy(PORTS).resolve("10.0.0.5", 9100) == ["10.0.0.5"]
    resolved = await AddressPolicy(PORTS, allow_loopback=True).resolve("localhost", 9100)
    assert "127.0.0.1" in resolved


async def test_resolve_checks_the_port_before_looking_up_the_name():
    with pytest.raises(AddressNotAllowed, match="Port 5432"):
        await AddressPolicy(PORTS).resolve("printer.invalid", 5432)
