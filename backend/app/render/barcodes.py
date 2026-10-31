"""Barcode symbol generation as module patterns/matrices."""

import math
import re
from dataclasses import dataclass, field

import segno
from barcode import codabar, codex, ean, itf, upc
from barcode.charsets.code128 import CODES as _CODE128_PATTERNS
from barcode.charsets.code128 import STOP as _CODE128_STOP
from barcode.errors import BarcodeError as _LibBarcodeError
from pdf417gen import encode as pdf417_encode
from ppf.datamatrix import DataMatrix


class BarcodeError(ValueError):
    pass


@dataclass(slots=True)
class LinearCode:
    pattern: str  # "1" = bar module, "0" = space module (fixed-ratio symbologies)
    text: str  # human readable interpretation line
    # Variable-ratio symbologies: bars and spaces alternating from a bar, "n" narrow, "w" wide.
    elements: str = ""
    warnings: list[str] = field(default_factory=list)

    def runs(self, module_width: int, ratio: float) -> list[tuple[bool, int]]:
        """(is_bar, width in dots) of each bar and space."""
        if self.elements:
            wide = wide_dots(module_width, ratio)
            return [
                (i % 2 == 0, module_width if e == "n" else wide)
                for i, e in enumerate(self.elements)
            ]
        return [
            (m.group()[0] == "1", len(m.group()) * module_width)
            for m in re.finditer(r"1+|0+", self.pattern)
        ]


def wide_dots(module_width: int, ratio: float) -> int:
    """Width of a wide element: the printer only prints whole dots.

    ^BY Table 11 (ZPL II Programming Guide p.104) lists the ratios actually printed; truncating
    module width x ratio to whole dots reproduces it.
    """
    return max(module_width, math.floor(module_width * ratio + 1e-9))


# ASCII digits only: \d and str.isdigit() also match digits of other scripts.
_DIGITS = re.compile(r"[^0-9]")


def _elements(pattern: str) -> str:
    """Narrow/wide elements of a pattern built with narrow = 1 and wide = 3 modules."""
    return "".join("n" if len(m.group()) == 1 else "w" for m in re.finditer(r"1+|0+", pattern))


def _mod10(digits: str) -> str:
    """Mod 10 check digit of UPC/EAN and Interleaved 2 of 5 (weights 3, 1, ... from the right)."""
    total = sum(int(d) * (1 if i % 2 else 3) for i, d in enumerate(reversed(digits)))
    return str(-total % 10)


def _fixed_length(data: str, length: int, name: str, warnings: list[str]) -> str:
    """Digits of a fixed-length symbology, padded or truncated like the printer does.

    The printer pads on the left with zeros and truncates longer data to `length` digits; a
    13th EAN-13 digit is taken to be a typed check digit, which the printer recalculates.
    """
    digits = _DIGITS.sub("", data)
    if not digits:
        raise BarcodeError(f"{name} needs digits")
    if len(digits) < length:
        warnings.append(f"{name} data is padded to {length} digits with leading zeros")
        return digits.rjust(length, "0")
    if len(digits) > length:
        kept, extra = digits[:length], digits[length:]
        if len(extra) == 1 and extra != _mod10(kept):
            warnings.append(
                f"{name} check digit {extra} is wrong; the printer prints {_mod10(kept)}"
            )
        elif len(extra) > 1:
            warnings.append(f"{name} uses only the first {length} digits")
        return kept
    return digits


# ---- Code 128 --------------------------------------------------------------------------------

_START = {"A": 103, "B": 104, "C": 105}
_CODE_C, _CODE_B, _CODE_A, _FNC1 = 99, 100, 101, 102
# ZPL invocation codes (^BC, Table 6 p.49): ">" and a character insert a code value directly.
_INVOCATION = {
    "<": 62, "0": 30, "=": 94, "1": 95, "2": 96, "3": 97, "4": 98, "5": 99, "6": 100,
    "7": 101, "8": 102, "9": 103, ":": 104, ";": 105,
}  # fmt: skip
_INVOCATION_OF = {value: f">{char}" for char, value in _INVOCATION.items()}
# Code values that switch subsets, by current subset.
_SWITCH = {
    "A": {_CODE_C: "C", _CODE_B: "B"},
    "B": {_CODE_C: "C", _CODE_A: "A"},
    "C": {_CODE_B: "B", _CODE_A: "A"},
}


@dataclass(slots=True)
class Code128:
    values: list[int]  # start code, data and switch codes (no check character or stop)
    text: str
    warnings: list[str] = field(default_factory=list)

    @property
    def pattern(self) -> str:
        check = (self.values[0] + sum(i * v for i, v in enumerate(self.values[1:], 1))) % 103
        # The stop character ends with a 2-module termination bar.
        symbols = "".join(_CODE128_PATTERNS[v] for v in [*self.values, check])
        return symbols + _CODE128_STOP + "11"


def _char_value(ch: str, subset: str) -> int | None:
    code = ord(ch)
    if subset == "A":
        if 32 <= code < 96:
            return code - 32
        return code + 64 if code < 32 else None
    if subset == "B":
        return code - 32 if 32 <= code < 128 else None
    return None


def _decode_zpl_code128(data: str) -> Code128:
    """Code values of ^BC mode N field data, as the printer reads it.

    Subset B is used unless the data starts with a start code (>9, >: or >;); invocation codes
    switch subsets or insert special characters.
    """
    warnings: list[str] = []
    values: list[int] = []
    text: list[str] = []
    subset = "B"
    i = 0
    if data[:1] == ">" and data[1:2] in "9:;" and len(data) > 1:
        subset = {"9": "A", ":": "B", ";": "C"}[data[1]]
        i = 2
    values.append(_START[subset])
    while i < len(data):
        ch = data[i]
        if ch == ">" and data[i + 1 : i + 2] in _INVOCATION and i + 1 < len(data):
            value = _INVOCATION[data[i + 1]]
            i += 2
            if value >= 103:
                warnings.append("Code 128 start codes are only valid at the start of the data")
                continue
            values.append(value)
            if value in _SWITCH[subset]:
                subset = _SWITCH[subset][value]
            elif subset == "C" and value < 100:
                text.append(f"{value:02d}")
            elif subset != "C" and value < 96:
                text.append(chr(value + 32) if subset == "B" or value < 64 else chr(value - 64))
            continue
        if subset == "C":
            pair = data[i : i + 2]
            if len(pair) == 2 and pair.isascii() and pair.isdigit():
                values.append(int(pair))
                text.append(pair)
                i += 2
                continue
            # A lone digit or other character: continue in subset B.
            values.append(_CODE_B)
            subset = "B"
            continue
        value = _char_value(ch, subset)
        if value is None:
            raise BarcodeError(f"Code 128 cannot encode {ch!r}")
        values.append(value)
        text.append(ch)
        i += 1
    return Code128(values, "".join(text), warnings)


def _subset_of(ch: str) -> str | None:
    """The subset a character needs: A for control characters, B for lowercase letters and
    the characters after them; None when both have it."""
    code = ord(ch)
    return "A" if code < 32 else "B" if code >= 96 else None


def _segments(text: str) -> list[tuple[str, str]]:
    """Split text into (subset, chunk) the way ^BC automatic mode does.

    "A string of four or more numeric digits causes an automatic shift to Subset C" (p.48);
    an odd run keeps its first digit in the preceding subset. Other characters stay in the
    current subset A or B while it has them.
    """
    parts: list[tuple[str | None, str]] = []
    for match in re.finditer(r"[0-9]{4,}|[0-9]{1,3}|[^0-9]+", text):
        chunk = match.group()
        if len(chunk) >= 4 and chunk[0] in "0123456789":
            if len(chunk) % 2:
                parts.append((None, chunk[0]))
                chunk = chunk[1:]
            parts.append(("C", chunk))
        else:
            parts += [(_subset_of(ch), ch) for ch in chunk]
    merged: list[tuple[str, str]] = []
    current: str | None = None
    for index, (subset, chunk) in enumerate(parts):
        if subset is None:
            # Either A or B: keep the current one, or take the one needed next.
            following = next((s for s, _ in parts[index + 1 :] if s is not None), None)
            subset = current if current in ("A", "B") else following if following == "A" else "B"
        if merged and merged[-1][0] == subset and subset != "C":
            merged[-1] = (subset, merged[-1][1] + chunk)
        else:
            merged.append((subset, chunk))
        current = subset
    return merged or [("B", "")]


def code128_field(text: str) -> str:
    """^BC mode N field data with explicit subsets, e.g. ">;123456>6AB".

    The printer then has no subset to choose, so it prints exactly what the preview shows.
    """
    out: list[str] = []
    current = None
    for subset, chunk in _segments(text):
        if current is None:
            out.append({"A": ">9", "B": ">:", "C": ">;"}[subset])
        else:
            switch = next(v for v, s in _SWITCH[current].items() if s == subset)
            out.append(_INVOCATION_OF[switch])
        current = subset
        # ">" is the invocation prefix, so a literal one is written as ">0".
        out.append(chunk if subset == "C" else chunk.replace(">", ">0"))
    return "".join(out)


def code128(data: str, *, mode: str = "N", ucc_check: bool = False) -> Code128:
    """Code 128 as ^BC prints it: mode N (field data with invocation codes) or A (automatic).

    Modes U and D (UCC/EAN) are drawn approximately.
    """
    mode = (mode or "N").upper()
    warnings: list[str] = []
    if mode in ("U", "D"):
        warnings.append(f"^BC mode {mode} (UCC/EAN) is previewed approximately")
        text = re.sub(r"[()\s]", "", data)
        if mode == "U":
            text = _DIGITS.sub("", text)[:19].ljust(19, "0")
            text += _mod10(text)
        source = code128_field(text)
    elif mode == "A":
        source = code128_field(data)
    else:
        source = data
    encoded = _decode_zpl_code128(source)
    if ucc_check and mode == "N":
        # Without a UCC mode the printer leaves the Mod 10 digit out (T02d prints 123456).
        warnings.append("The printer ignores the ^BC UCC check digit in mode N")
    elif ucc_check:
        digits = _DIGITS.sub("", encoded.text)
        if digits and digits == encoded.text:
            # The Mod 10 digit is added to the data, in whichever subset the data ends in.
            encoded = _decode_zpl_code128(source + _mod10(digits))
        else:
            warnings.append("The ^BC UCC check digit applies to numeric data only")
    if mode in ("U", "D"):
        encoded.values.insert(1, _FNC1)
        encoded.text = data
    encoded.warnings += warnings
    return encoded


# ---- linear symbologies ------------------------------------------------------------------------


def linear(
    symbology: str,
    data: str,
    *,
    check_digit: bool = False,
    mode: str = "N",
) -> LinearCode:
    warnings: list[str] = []
    try:
        match symbology:
            case "code128":
                code = code128(data, mode=mode, ucc_check=check_digit)
                return LinearCode(code.pattern, code.text, warnings=code.warnings)
            case "code39":
                c39 = codex.Code39(data.upper(), add_checksum=check_digit)
                pattern = c39.build()[0]
                return LinearCode(pattern, f"*{c39.get_fullcode()}*", _elements(pattern))
            case "ean13":
                code = ean.EAN13(_fixed_length(data, 12, "EAN-13", warnings))
                return LinearCode(code.build()[0], code.get_fullcode(), warnings=warnings)
            case "ean8":
                code = ean.EAN8(_fixed_length(data, 7, "EAN-8", warnings))
                return LinearCode(code.build()[0], code.get_fullcode(), warnings=warnings)
            case "upca":
                code = upc.UPCA(_fixed_length(data, 11, "UPC-A", warnings))
                return LinearCode(code.build()[0], code.get_fullcode(), warnings=warnings)
            case "codabar":
                pattern = codabar.CODABAR(data, narrow=1, wide=3).build()[0]
                return LinearCode(pattern, data[1:-1], _elements(pattern))
            case "itf":
                digits = _DIGITS.sub("", data)
                if not digits:
                    raise BarcodeError("Interleaved 2 of 5 needs digits")
                if check_digit:
                    digits += _mod10(digits)
                if len(digits) % 2:
                    digits = "0" + digits
                pattern = itf.ITF(digits, narrow=1, wide=3).build()[0]
                return LinearCode(pattern, digits, _elements(pattern))
    except _LibBarcodeError as exc:
        raise BarcodeError(str(exc)) from exc
    raise BarcodeError(f"Unsupported barcode {symbology}")


def qr_matrix(data: str | bytes, error: str = "M") -> list[list[int]]:
    try:
        qr = segno.make_qr(data, error=error.lower(), boost_error=False)
    except (segno.DataOverflowError, ValueError) as exc:
        raise BarcodeError(str(exc)) from exc
    return [list(row) for row in qr.matrix]


def datamatrix_matrix(data: str) -> list[list[int]]:
    try:
        return [list(row) for row in DataMatrix(data).matrix]
    except Exception as exc:
        raise BarcodeError(f"Cannot encode Data Matrix: {exc}") from exc


def pdf417_rows(data: str, *, columns: int = 4, security: int = 2) -> list[str]:
    """Return one module pattern string per PDF417 row."""
    try:
        codes = pdf417_encode(data, columns=max(1, min(columns, 30)), security_level=security)
    except Exception as exc:
        raise BarcodeError(f"Cannot encode PDF417: {exc}") from exc
    return ["".join(format(value, "b") for value in row) for row in codes]
