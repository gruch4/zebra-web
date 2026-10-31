"""Tokenizer for ZPL II command streams."""

import re
from dataclasses import dataclass


@dataclass(slots=True)
class Command:
    prefix: str  # "^" (format command) or "~" (control command), whatever chars the data uses
    code: str  # upper-case command code, e.g. "FO", "A", "GF"
    params: str
    delimiter: str = ","
    start: int = 0  # span of the command in the source text
    end: int = 0

    @property
    def name(self) -> str:
        return f"{self.prefix}{self.code}"

    def args(self, maxsplit: int = -1) -> list[str]:
        return [part.strip() for part in self.params.split(self.delimiter, maxsplit)]


RS, DLE = "\x1e", "\x10"
# SI (Control-O) can be sent instead of ^FS (p.149).
SI = "\x0f"

# Commands that change the control characters; their parameter is exactly one character.
_CHANGE_CARET, _CHANGE_TILDE, _CHANGE_DELIMITER = "CC", "CT", "CD"


def _binary_end(zpl: str, start: int, code: str, delimiter: str) -> int | None:
    """End of a ^GF or ~DY command whose data is binary.

    "All control prefixes are ignored until the total number of bytes needed for the graphic
    format is sent" (p.135, p.160), so the data may contain ^ and ~ bytes.
    """
    fields = 4 if code == "GF" else 5  # ^GFa,b,c,d,data and ~DYd:f,b,x,t,w,data
    commas, i = [], start
    while len(commas) < fields:
        i = zpl.find(delimiter, i)
        if i < 0:
            return None
        commas.append(i)
        i += 1
    params = zpl[start : commas[-1]].split(delimiter)
    if code == "GF":
        binary, count = params[0].strip().upper() in ("B", "C"), params[1]
    else:
        binary, count = params[1].strip().upper() in ("B", "C"), params[3]
    # ASCII digits only: str.isdigit() accepts characters like "²" that int() rejects.
    if not binary or not re.fullmatch(r"[0-9]+", count.strip()):
        return None
    return min(len(zpl), commas[-1] + 1 + int(count))


def tokenize(zpl: str) -> list[Command]:
    """Split ZPL into commands, honouring ^CC/~CC, ^CT/~CT and ^CD/~CD."""
    commands: list[Command] = []
    caret, tilde, delimiter = "^", "~", ","
    n = len(zpl)
    i = 0
    while i < n:
        ch = zpl[i]
        if ch == SI:
            commands.append(Command("^", "FS", "", delimiter, i, i + 1))
            i += 1
            continue
        # RS (0x1E) may replace the caret and DLE (0x10) the tilde.
        if ch not in (caret, tilde, RS, DLE):
            i += 1
            continue
        prefix = "^" if ch in (caret, RS) else "~"
        if prefix == "^" and zpl[i + 1 : i + 2].upper() == "A" and i + 2 < n:
            # ^A takes the font name as its first parameter character (e.g. ^A0N,30,30).
            code, start = "A", i + 2
        else:
            code, start = zpl[i + 1 : i + 3].upper(), i + 3
            if len(code) < 2 or not code.isalnum():
                # Not a command (e.g. stray text before the first ^XA); keep scanning.
                i += 1
                continue
        if code in (_CHANGE_CARET, _CHANGE_TILDE, _CHANGE_DELIMITER):
            value = zpl[start : start + 1]
            if value and not value.isspace():
                if code == _CHANGE_CARET:
                    caret = value
                elif code == _CHANGE_TILDE:
                    tilde = value
                else:
                    delimiter = value
            commands.append(Command(prefix, code, value, delimiter, i, start + 1))
            i = start + 1
            continue
        binary_end = (
            _binary_end(zpl, start, code, delimiter)
            if (code, prefix) in (("GF", "^"), ("DY", "~"))
            else None
        )
        j = binary_end or start
        while j < n and zpl[j] not in (caret, tilde, RS, DLE, SI):
            j += 1
        if binary_end:
            params = zpl[start:binary_end]  # binary data may contain CR and LF bytes
        else:
            params = zpl[start:j].replace("\r", "").replace("\n", "")
        commands.append(Command(prefix, code, params, delimiter, i, j))
        i = j
    return commands


def decode_field_hex(data: str, indicator: str, *, encoding: str = "cp850") -> str:
    """Decode ^FH escapes like `_41` into characters of the active ^CI encoding.

    Literal characters are sent to the printer as UTF-8, escapes as raw bytes; the printer
    then reads all bytes in its current encoding.
    """
    out = bytearray()
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == indicator and _is_hex(data[i + 1 : i + 3]):
            out.append(int(data[i + 1 : i + 3], 16))
            i += 3
            continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode(encoding, "replace")


def _is_hex(value: str) -> bool:
    return len(value) == 2 and all(c in "0123456789abcdefABCDEF" for c in value)
