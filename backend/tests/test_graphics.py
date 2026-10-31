import base64
import time
import tracemalloc
import zlib

import pytest
from PIL import Image, ImageDraw

from app.zpl.graphics import (
    MAX_GRAPHIC_BYTES,
    Bitmap,
    GraphicError,
    _compress_row,
    _encode_count,
    decode_graphic_data,
    encode_gfa,
    image_to_bitmap,
)


def sample_bitmap() -> Bitmap:
    img = Image.new("L", (20, 10), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle((2, 2, 12, 7), fill=255)
    draw.point((19, 9), fill=255)
    return Bitmap.from_mask(img)


def test_encode_count():
    assert _encode_count(1) == "G"
    assert _encode_count(19) == "Y"
    assert _encode_count(20) == "g"
    assert _encode_count(45) == "hK"
    assert _encode_count(401) == "zG"


def test_compress_row():
    assert _compress_row("000000") == ","
    assert _compress_row("FFFF00") == "JF,"
    assert _compress_row("0F0F") == "0F0F"


def test_gfa_roundtrip_compressed_and_plain():
    bitmap = sample_bitmap()
    for compress in (True, False):
        command = encode_gfa(bitmap, compress=compress)
        _, total, _, bpr, data = command.split(",", 4)
        decoded = decode_graphic_data(data, total=int(total), bytes_per_row=int(bpr))
        assert decoded == bitmap.data


def test_decode_repeat_previous_row_and_fill_ones():
    # Row 1: "FF" then rest ones, row 2 repeats row 1.
    data = decode_graphic_data("F0!:", total=4, bytes_per_row=2)
    assert data == bytes.fromhex("F0FFF0FF")


def test_decode_z64():
    raw = bytes(range(16))
    payload = base64.b64encode(zlib.compress(raw)).decode()
    assert decode_graphic_data(f":Z64:{payload}:1234", total=16, bytes_per_row=2) == raw


def test_image_to_bitmap_threshold_resize_and_alpha():
    img = Image.new("RGBA", (40, 20), (255, 255, 255, 0))
    ImageDraw.Draw(img).rectangle((0, 0, 19, 19), fill=(0, 0, 0, 255))
    bitmap = image_to_bitmap(img, width=20)
    assert (bitmap.width, bitmap.height, bitmap.bytes_per_row) == (20, 10, 3)
    mask = bitmap.to_mask()
    assert mask.getpixel((2, 2)) == 255  # black ink on the left half
    assert mask.getpixel((18, 5)) == 0  # transparent area becomes white paper


def test_image_to_bitmap_invert_and_dither():
    img = Image.new("L", (8, 8), 128)
    dithered = image_to_bitmap(img, dither=True).to_mask()
    assert 0 < sum(1 for p in dithered.get_flattened_data() if p) < 64
    inverted = image_to_bitmap(Image.new("L", (8, 8), 255), invert=True).to_mask()
    assert all(p == 255 for p in inverted.get_flattened_data())


def test_comma_needs_one_explicit_zero_for_odd_trailing_zeros():
    # Guide: "If the HEX string ends in an odd number of zeros, one zero and a single comma".
    assert _compress_row("F000") == "F0,"
    assert _compress_row("FFF0") == "IF0"  # I = 3 repeats
    bitmap = Bitmap(16, 1, 2, bytes.fromhex("F000"))
    _, total, _, bpr, data = encode_gfa(bitmap).split(",", 4)
    assert decode_graphic_data(data, total=int(total), bytes_per_row=int(bpr)) == bitmap.data


def test_guide_compression_examples():
    assert decode_graphic_data("M6", total=4, bytes_per_row=4)[:3] == bytes.fromhex("666666")
    assert decode_graphic_data("hB", total=20, bytes_per_row=20) == bytes.fromhex("BB" * 20)
    # "MvB or vMB sends 327 hexadecimal B's"
    for data in ("MvB", "vMB"):
        assert (
            decode_graphic_data(data, total=164, bytes_per_row=164)
            .hex()
            .upper()
            .startswith("B" * 327)
        )


def test_z64_accepts_gzip_wrapped_data():
    import gzip

    raw = bytes(range(32))
    payload = base64.b64encode(gzip.compress(raw)).decode()
    assert decode_graphic_data(f":Z64:{payload}:0000", total=32, bytes_per_row=4) == raw


@pytest.mark.parametrize("data", ["FF", ":Z64:eJwDAAAAAAE="])
@pytest.mark.parametrize(
    ("total", "bpr"), [(MAX_GRAPHIC_BYTES + 1, 1), (0, 1), (10, 0), (10, -1), (10, 11)]
)
def test_decode_rejects_sizes_outside_the_limits(data: str, total: int, bpr: int):
    with pytest.raises(GraphicError):
        decode_graphic_data(data, total=total, bytes_per_row=bpr)


@pytest.mark.parametrize(
    "data",
    ["z" * 5000 + "0", "z" * 1_000_000 + "F", "," * 1_000_000, ":" * 1_000_000, "!" * 1_000_000],
)
def test_decode_stops_once_the_declared_size_is_filled(data: str):
    start = time.perf_counter()
    decoded = decode_graphic_data(data, total=4, bytes_per_row=2)
    assert len(decoded) == 4
    assert time.perf_counter() - start < 1


def test_long_repeat_counts_span_rows_up_to_the_declared_size():
    assert decode_graphic_data("z" * 100 + "F", total=6, bytes_per_row=2) == b"\xff" * 6


def test_z64_inflates_only_the_declared_size():
    payload = base64.b64encode(zlib.compress(bytes(20_000_000), 9)).decode()
    tracemalloc.start()
    try:
        decoded = decode_graphic_data(f":Z64:{payload}", total=16, bytes_per_row=2)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert decoded == bytes(16)
    assert peak < 1_000_000


def test_image_to_bitmap_flattens_palette_transparency_onto_white():
    img = Image.new("P", (8, 8), 0)
    img.putpalette([0, 0, 0, 255, 255, 255])
    img.info["transparency"] = 0  # black index is transparent
    img.paste(1, (0, 0, 4, 8))
    assert all(p == 0 for p in image_to_bitmap(img).to_mask().get_flattened_data())
    img.info.pop("transparency")
    mask = image_to_bitmap(img).to_mask()
    assert mask.getpixel((1, 1)) == 0 and mask.getpixel((6, 1)) == 255
