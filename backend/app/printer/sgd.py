"""Parsing of Set-Get-Do (SGD) responses."""

import re
from dataclasses import dataclass

_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*:\s*(.*?)\s*(?:,\s*Choices:\s*(.*))?$")


@dataclass(slots=True)
class SgdValue:
    value: str
    choices: str | None = None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse_allcv(raw: bytes | str) -> dict[str, SgdValue]:
    """Parse the output of `! U1 getvar "allcv"`.

    Each line looks like `ezpl.print_width : 832 , Choices: 2 to 832`.
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    # The whole answer is one quoted string; values on its lines can be quoted, too.
    if text.startswith('"'):
        text = text[1:].removesuffix('"')
    result: dict[str, SgdValue] = {}
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value, choices = match.groups()
        result[key] = SgdValue(_unquote(value), choices.strip() if choices else None)
    return result


def parse_getvar(raw: bytes | str) -> str:
    """Parse a single `! U1 getvar` response, which is a quoted string."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    return _unquote(text.strip())
