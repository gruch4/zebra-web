"""Monochrome bitmap helpers: image conversion and ^GF encoding/decoding."""

import base64
import binascii
import io
import re
import zlib
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.render.limits import MAX_FIELD_DOTS

# Largest ^GF/~DG graphic: its mask (8 dots per byte) must fit within one field's budget.
MAX_GRAPHIC_BYTES = MAX_FIELD_DOTS // 8

# ^GF byte counts are 1 to 99999 and larger values are clamped (p.160).
MAX_GF_BYTES = 99_999

# ZPL "alternative compression scheme" repeat counts.
_LOW = {chr(ord("G") + i): i + 1 for i in range(19)}  # G..Y = 1..19
_HIGH = {chr(ord("g") + i): (i + 1) * 20 for i in range(20)}  # g..z = 20..400


class GraphicError(ValueError):
    pass


@dataclass(slots=True)
class Bitmap:
    """Packed 1-bit bitmap, 1 = black dot, rows padded to whole bytes."""

    width: int
    height: int
    bytes_per_row: int
    data: bytes

    def to_image(self) -> Image.Image:
        """Return an 'L' image where ink is 0 (black) and background 255."""
        img = Image.frombytes("1", (self.bytes_per_row * 8, self.height), self.data)
        img = ImageOps.invert(img.convert("L"))
        return img.crop((0, 0, self.width, self.height))

    def to_mask(self) -> Image.Image:
        """Return an 'L' mask where ink is 255."""
        img = Image.frombytes("1", (self.bytes_per_row * 8, self.height), self.data).convert("L")
        return img.crop((0, 0, self.width, self.height))

    def to_png(self) -> bytes:
        buf = io.BytesIO()
        self.to_image().save(buf, "PNG")
        return buf.getvalue()

    @classmethod
    def from_mask(cls, mask: Image.Image) -> Bitmap:
        mask = mask.convert("L").point(lambda v: 255 if v >= 128 else 0).convert("1")
        bpr = (mask.width + 7) // 8
        padded = Image.new("1", (bpr * 8, mask.height), 0)
        padded.paste(mask, (0, 0))
        return cls(mask.width, mask.height, bpr, padded.tobytes())


def image_to_bitmap(
    image: Image.Image,
    *,
    width: int | None = None,
    height: int | None = None,
    threshold: int = 128,
    dither: bool = False,
    invert: bool = False,
) -> Bitmap:
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        # Flatten onto white in grayscale: same result as compositing in RGBA, less memory.
        image = image.convert("LA")
        gray = Image.new("L", image.size, 255)
        gray.paste(image.getchannel("L"), (0, 0), image.getchannel("A"))
    else:
        gray = image.convert("L")
    if width or height:
        w = width or round(gray.width * height / gray.height)  # type: ignore[operator]
        h = height or round(gray.height * width / gray.width)  # type: ignore[operator]
        gray = gray.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)
    if invert:
        gray = ImageOps.invert(gray)
    if dither:
        mono = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        ink = ImageOps.invert(mono.convert("L"))
    else:
        ink = gray.point(lambda v: 255 if v < threshold else 0)
    return Bitmap.from_mask(ink)


def _encode_count(count: int) -> str:
    out = []
    while count > 400:
        out.append("z")
        count -= 400
    if count >= 20:
        out.append(chr(ord("g") + count // 20 - 1))
        count %= 20
    if count:
        out.append(chr(ord("G") + count - 1))
    return "".join(out)


def _compress_row(hex_row: str) -> str:
    stripped = hex_row.rstrip("0")
    if not stripped:
        return ","
    if len(stripped) % 2:
        # "," fills whole bytes: an odd number of trailing zeros needs one explicit zero.
        stripped += "0"
    trailing = len(hex_row) - len(stripped)
    out = []
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        j = i
        while j < len(stripped) and stripped[j] == ch:
            j += 1
        run = j - i
        out.append((_encode_count(run) if run > 1 else "") + ch)
        i = j
    result = "".join(out)
    if trailing:
        result += ","
    return result


def split_bitmap(bitmap: Bitmap, limit: int = MAX_GF_BYTES) -> list[tuple[int, Bitmap]]:
    """Horizontal strips of at most `limit` bytes each, with their offsets from the top."""
    rows = max(1, limit // bitmap.bytes_per_row)
    size = rows * bitmap.bytes_per_row
    return [
        (
            top,
            Bitmap(
                bitmap.width,
                min(rows, bitmap.height - top),
                bitmap.bytes_per_row,
                bitmap.data[top * bitmap.bytes_per_row : top * bitmap.bytes_per_row + size],
            ),
        )
        for top in range(0, bitmap.height, rows)
    ]


def encode_gfa(bitmap: Bitmap, *, compress: bool = True) -> str:
    """Return a complete `^GFA,...` command for the bitmap."""
    total = len(bitmap.data)
    bpr = bitmap.bytes_per_row
    hex_data = bitmap.data.hex().upper()
    rows = [hex_data[i : i + bpr * 2] for i in range(0, len(hex_data), bpr * 2)]
    if compress:
        parts = []
        previous = None
        for row in rows:
            parts.append(":" if row == previous else _compress_row(row))
            previous = row
        body = "".join(parts)
    else:
        body = hex_data
    return f"^GFA,{total},{total},{bpr},{body}"


def _decode_compressed_hex(data: str, bytes_per_row: int, total: int) -> bytes:
    row_chars = bytes_per_row * 2
    # Rows past the declared size are dropped, so stop as soon as they are all decoded.
    max_rows = -(-total // bytes_per_row)
    rows: list[str] = []
    current: list[str] = []  # chunks of the row being decoded
    filled = 0
    count = 0

    def flush(fill: str) -> None:
        nonlocal filled
        rows.append("".join(current).ljust(row_chars, fill))
        current.clear()
        filled = 0

    for ch in data:
        if len(rows) >= max_rows:
            break
        if ch in _LOW:
            count += _LOW[ch]
        elif ch in _HIGH:
            count += _HIGH[ch]
        elif ch in "0123456789ABCDEFabcdef":
            repeat = count or 1
            while repeat and len(rows) < max_rows:
                n = min(repeat, row_chars - filled)
                current.append(ch.upper() * n)
                filled += n
                repeat -= n
                if filled == row_chars:
                    flush("0")
            count = 0
        elif ch == ",":
            flush("0")
        elif ch == "!":
            flush("F")
        elif ch == ":":
            if current:
                flush("0")
            rows.append(rows[-1] if rows else "0" * row_chars)
        # anything else (whitespace, stray characters) is ignored
    if current:
        flush("0")
    hex_data = "".join(rows)[: total * 2].ljust(total * 2, "0")
    return binascii.unhexlify(hex_data)


_B64_RE = re.compile(r"^:(Z64|B64):([^:]+)(?::([0-9A-Fa-f]+))?$")


def decode_graphic_data(data: str, *, total: int, bytes_per_row: int) -> bytes:
    """Decode ^GF/~DG ASCII data (hex, compressed hex, :Z64: or :B64:)."""
    if not 0 < total <= MAX_GRAPHIC_BYTES:
        raise GraphicError(f"Graphic size must be between 1 and {MAX_GRAPHIC_BYTES} bytes")
    if not 0 < bytes_per_row <= total:
        raise GraphicError("Bytes per row must be between 1 and the graphic size")
    data = data.strip()
    match = _B64_RE.match(data)
    if match:
        kind, payload, _crc = match.groups()
        try:
            raw = base64.b64decode(payload)
            if kind == "Z64":
                # LZ77 data may come zlib- or gzip-wrapped; wbits=47 accepts both. Inflate
                # only the declared size so a small payload cannot expand without limit.
                raw = zlib.decompressobj(wbits=47).decompress(raw, total)
        except (binascii.Error, zlib.error) as exc:
            raise GraphicError(f"Invalid {kind} graphic data") from exc
        return raw[:total].ljust(total, b"\x00")
    return _decode_compressed_hex(re.sub(r"\s", "", data), bytes_per_row, total)
