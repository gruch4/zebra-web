"""Size limits that keep the memory used by a preview bounded."""

from PIL import Image

MAX_WIDTH = 3000
MAX_HEIGHT = 16000
# Largest image a single field may allocate (48 MB as an 'L' image): anything bigger cannot fit
# on the largest label in any orientation.
MAX_FIELD_DOTS = MAX_WIDTH * MAX_HEIGHT


class TooLargeError(ValueError):
    pass


def check_size(width: int, height: int) -> None:
    if max(width, height) > MAX_HEIGHT or width * height > MAX_FIELD_DOTS:
        raise TooLargeError(f"{width}x{height} dots is too large to preview")


def new_mask(width: int, height: int) -> Image.Image:
    """Return an empty 'L' mask (ink = 255), refusing sizes that cannot appear on a label."""
    check_size(width, height)
    return Image.new("L", (width, height), 0)
