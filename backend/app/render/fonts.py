"""Approximations of Zebra's built-in fonts using bundled TrueType fonts.

Metrics follow the ZPL II Programming Guide (Vol. 2, "Fonts and Bar Codes"): bitmap fonts have
a fixed cell, an intercharacter gap and a baseline; scalable fonts put the baseline 3/4 down
the cell.
"""

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.render.limits import check_size, new_mask

FONT_DIR = Path(__file__).parent / "fonts"
SCALABLE_FONT = FONT_DIR / "RobotoCondensed-Variable.ttf"
MONO_FONT = FONT_DIR / "DejaVuSansMono-Bold.ttf"


@dataclass(frozen=True, slots=True)
class BitmapMetrics:
    height: int
    width: int
    gap: int  # intercharacter gap in dots
    baseline: int  # dots from the top of the cell


# 8 dots/mm (203 dpi) matrices, Table 10 and the font matrices of the guide.
BITMAP_FONTS: dict[str, BitmapMetrics] = {
    "A": BitmapMetrics(9, 5, 1, 7),
    "B": BitmapMetrics(11, 7, 2, 11),
    "C": BitmapMetrics(18, 10, 2, 14),
    "D": BitmapMetrics(18, 10, 2, 14),
    "E": BitmapMetrics(28, 15, 5, 23),
    "F": BitmapMetrics(26, 13, 3, 21),
    "G": BitmapMetrics(60, 40, 8, 48),
    "H": BitmapMetrics(21, 13, 6, 21),
    "P": BitmapMetrics(20, 18, 0, 15),
    "Q": BitmapMetrics(28, 24, 0, 21),
    "R": BitmapMetrics(35, 31, 0, 26),
    "S": BitmapMetrics(40, 35, 0, 30),
    "T": BitmapMetrics(48, 42, 0, 36),
    "U": BitmapMetrics(59, 53, 0, 44),
    "V": BitmapMetrics(80, 71, 0, 60),
}

# The OCR fonts E and H use different matrices on other printheads.
_RESOLUTION_OVERRIDES: dict[int, dict[str, tuple[int, int]]] = {
    6: {"E": (21, 10), "H": (17, 11)},
    12: {"E": (42, 20), "H": (34, 22)},
    24: {"E": (42, 20), "H": (34, 22)},
}

# Font 0 size when neither ^A nor ^CF give one.
SCALABLE_DEFAULT = (15, 12)
SCALABLE_MIN = 10
# The printer's font 0 capitals are about 6% taller than the bundled font's at the same em,
# its widths the same (docs/print-tests T03-T05 at 300 dpi): glyphs are drawn this much
# taller, and measured at the em.
SCALABLE_STRETCH = 1.06


def bitmap_metrics(name: str, dpmm: int = 8) -> BitmapMetrics | None:
    metrics = BITMAP_FONTS.get(name)
    if metrics is None:
        return None
    override = _RESOLUTION_OVERRIDES.get(dpmm, {}).get(name)
    if override:
        height, width = override
        scale = height / metrics.height
        return BitmapMetrics(
            height, width, round(metrics.gap * scale), round(metrics.baseline * scale)
        )
    return metrics


@lru_cache(maxsize=256)
def _truetype(path: Path, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    if path == SCALABLE_FONT:
        font.set_variation_by_name("Bold")
    return font


@lru_cache(maxsize=4)
def _ascent_ratio(path: Path) -> float:
    """Font ascent as a fraction of its em size."""
    return _truetype(path, 100).getmetrics()[0] / 100


# Em size bitmap font glyphs are drawn at before they are scaled down into their matrix.
_GLYPH_SIZE = 200


@lru_cache(maxsize=2048)
def _bitmap_glyph(path: Path, width: int, height: int, baseline: int, ch: str) -> Image.Image:
    """One glyph filling its matrix like the resident bitmap fonts (T05): capitals from the
    top of the cell down to the baseline, the advance across the character width. Accented
    capitals rise above the cell, so what is above the baseline is squeezed into it."""
    font = _truetype(path, _GLYPH_SIZE)
    cap = -font.getbbox("H", anchor="ls")[1]
    ascent, _ = font.getmetrics()
    scale = baseline / cap  # dots per drawing pixel
    below = math.ceil((height - baseline) / scale)
    advance = max(1, round(font.getlength(ch)))
    img = Image.new("L", (advance, ascent + below), 0)
    ImageDraw.Draw(img).text((0, ascent), ch, fill=255, font=font, anchor="ls")
    # The printer's capitals fill the matrix width; the bundled font keeps side bearings.
    img = img.crop((round(advance * 0.05), 0, round(advance * 0.95), img.height))
    ink = img.getbbox()
    top = ascent - cap if ink is None else min(ascent - cap, ink[1])
    glyph = Image.new("L", (width, height), 0)
    upper = img.crop((0, top, img.width, ascent)).resize((width, baseline), Image.Resampling.BOX)
    glyph.paste(upper, (0, 0))
    if height > baseline:
        lower = img.crop((0, ascent, img.width, img.height))
        glyph.paste(lower.resize((width, height - baseline), Image.Resampling.BOX), (0, baseline))
    return glyph


@dataclass(frozen=True, slots=True)
class ZebraFont:
    """A font resolved for a given cell height/width."""

    path: Path
    cell_height: int
    baseline: int
    char_width: int | None  # glyph cell width (bitmap fonts)
    advance: int | None  # glyph cell + intercharacter gap (bitmap fonts)
    scale_x: float  # horizontal stretch for scalable fonts

    @property
    def font(self) -> ImageFont.FreeTypeFont:
        if self.path == SCALABLE_FONT:
            # Font 0's em is the ^A height: capitals run from the field origin down to the
            # baseline 3/4 down the cell (measured on a ZD420d, docs/print-tests T04).
            return _truetype(self.path, max(1, self.cell_height))
        # Size the TrueType font so its ascent ends at the Zebra baseline.
        size = max(1, round(self.baseline / _ascent_ratio(self.path)))
        return _truetype(self.path, size)

    @property
    def drawing_font(self) -> ImageFont.FreeTypeFont:
        """The font glyphs are drawn with: font 0 taller than its em (SCALABLE_STRETCH)."""
        if self.path == SCALABLE_FONT:
            return _truetype(self.path, max(1, round(self.cell_height * SCALABLE_STRETCH)))
        return self.font

    @property
    def headroom(self) -> int:
        """Rows above the cell that tall glyphs (accented capitals) of font 0 can reach."""
        if self.path != SCALABLE_FONT:
            return 0
        return max(0, self.drawing_font.getmetrics()[0] - self.baseline)

    def line_width(self, text: str) -> int:
        if self.advance is not None and self.char_width is not None:
            return max(0, self.advance * len(text) - (self.advance - self.char_width))
        return round(self.font.getlength(text) * self.scale_x)

    def _draw(self, text: str) -> Image.Image:
        """The text at its drawing size; render_line scales it to the measured width."""
        font = self.drawing_font
        top = self.headroom
        # Checked separately from the final size: a narrow ^A width squeezes a wide drawing.
        # FreeType's fixed point wraps around for very long lines, so getlength alone could
        # report a small width; the per-character sum cannot overflow.
        rough = sum(font.getlength(ch) * n for ch, n in Counter(text).items())
        check_size(round(rough) + 2, top + self.cell_height)
        natural = max(1, round(font.getlength(text)))
        img = new_mask(natural + 2, top + self.cell_height)
        if text:
            ImageDraw.Draw(img).text(
                (0, top + self.baseline), text, fill=255, font=font, anchor="ls"
            )
        return img

    def render_line(self, text: str, *, above: bool = False) -> Image.Image:
        """Render one line as an 'L' mask (ink = 255) of exactly cell height; with `above`,
        the `headroom` rows above the cell are kept on top of it."""
        target = max(1, self.line_width(text))
        top = self.headroom
        check_size(target, top + self.cell_height)
        if self.advance is not None and self.char_width is not None:
            img = new_mask(target, self.cell_height)
            for index, ch in enumerate(text):
                if ch.isspace():
                    continue
                glyph = _bitmap_glyph(
                    self.path, self.char_width, self.cell_height, self.baseline, ch
                )
                img.paste(glyph, (index * self.advance, 0), glyph)
        else:
            img = self._draw(text)
            if target != img.width:
                img = img.resize((target, top + self.cell_height), Image.Resampling.BILINEAR)
        if not above and top:
            img = img.crop((0, top, img.width, img.height))
        return img.point(lambda v: 255 if v >= 128 else 0)


def _magnification(size: int, base: int) -> int:
    return max(1, min(10, math.floor(size / base + 0.5)))


def resolve_font(name: str, height: int | None, width: int | None, dpmm: int = 8) -> ZebraFont:
    name = (name or "0").upper()
    metrics = bitmap_metrics(name, dpmm)
    if metrics is not None:
        # Bitmap fonts only grow in whole multiples of their matrix ("^AD,52" == "^AD,54"),
        # up to ten times; the nearest multiple, halves rounded up (the designer does the same).
        mag_h = _magnification(height, metrics.height) if height else None
        mag_w = _magnification(width, metrics.width) if width else None
        mag_h = mag_h or mag_w or 1
        mag_w = mag_w or mag_h
        return ZebraFont(
            MONO_FONT,
            metrics.height * mag_h,
            metrics.baseline * mag_h,
            metrics.width * mag_w,
            (metrics.width + metrics.gap) * mag_w,
            1.0,
        )
    # Font 0 and any downloaded/unknown font use the scalable font.
    if height is None and width is None:
        height, width = SCALABLE_DEFAULT
    # Smaller sizes print at 10 dots, the minimum of ^A (T04: "^A0N,8,8" prints like 10,10).
    h = max(SCALABLE_MIN, height or width or SCALABLE_DEFAULT[0])
    w = max(SCALABLE_MIN, width or h)
    return ZebraFont(SCALABLE_FONT, h, round(h * 3 / 4), None, None, w / h)
