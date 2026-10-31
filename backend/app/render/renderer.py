"""Local ZPL renderer producing PNG previews (1 pixel = 1 printer dot)."""

import hashlib
import io
import math
import re
import string
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageOps

from app.render import barcodes
from app.render.fonts import ZebraFont, bitmap_metrics, resolve_font
from app.render.lexer import Command, decode_field_hex, tokenize
from app.render.limits import MAX_FIELD_DOTS, MAX_HEIGHT, MAX_WIDTH, check_size, new_mask
from app.zpl.graphics import MAX_GRAPHIC_BYTES, Bitmap, GraphicError, decode_graphic_data
from app.zpl.templating import field_hex_indicator

# ~DG graphics and ^IS images kept for later formats, in bytes.
MAX_STORED_BYTES = 2 * MAX_FIELD_DOTS
# Total length of the formats expanded by ^XF recalls, across the whole data.
MAX_RECALLED_COMMANDS = 1_000_000
DEFAULT_WIDTH_IN = 4
DEFAULT_HEIGHT_IN = 6

# Commands that only affect the physical printer and do not change the image.
IGNORED = {
    "CC", "CD", "CT", "CW", "FA", "HH", "HM", "HS", "HI", "HQ", "HW", "ID", "IS", "JA", "JB", "JC",
    "JD", "JE", "JG", "JH", "JI", "JJ", "JL", "JN", "JO", "JR", "JS", "JT", "JU", "JW", "JZ", "KD",
    "KL", "KN", "KP", "LT", "MA", "MC", "MD", "MF", "MI", "ML", "MM", "MN", "MP", "MT", "MW", "NC",
    "NI", "NS", "NT", "PA", "PF", "PH", "PP", "PQ", "PR", "PS", "PW", "LL", "SC", "SD", "SL", "SO",
    "SP", "SQ", "SR", "SS", "ST", "SX", "SZ", "TA", "TO", "WC", "WD", "WL", "XA", "XZ", "XB", "XS",
    "ZZ",
}  # fmt: skip

# ^CI character sets: 27 = Zebra code page 1252, 28-30 = Unicode; the default and the
# remaining international sets are based on code page 850.
_ENCODINGS = {"27": "cp1252", "28": "utf-8", "29": "utf-16-be", "30": "utf-16-le"}
# ^CI0-12 replace some ASCII positions in the resident fonts (International Character Sets,
# p.114); only ^CI13 prints a backslash, the power-up ^CI0 prints a cent sign.
_NATIONAL = {
    0: "\\¢",
    1: "[⅓\\¢]⅔{¼|½}¾",
    2: "#£\\¢",
    3: "#ƒ@§\\Ĳ|ĳ",
    4: "[Æ\\Ø]Å{æ|ø}å",
    5: "#Ü@É[Ä\\Ö]Å^Ü`é{ä|ö}å~ü",
    6: "@§[Ä\\Ö]Ü{ä|ö}ü~ß",
    7: "#£@à\\ç{é}ù~è",
    8: "@à[â\\ç]ê^î`ô{é|ù}è~û",
    9: "#£@§\\ç]é`ù{à|ò}è~ì",
    10: "@§[¡\\Ñ]¿|ñ}ç",
    11: "#£@É[Ä\\Ö]Ü`ä{ë|ï}ö~ü",
    12: "\\¥",
}
_NATIONAL_TABLES = {
    charset: str.maketrans(dict(zip(pairs[::2], pairs[1::2], strict=True)))
    for charset, pairs in _NATIONAL.items()
}
# Resident bitmap fonts without lowercase letters (Vol. 2 Table 10): B prints them as
# capitals, H (OCR-A) leaves them blank (docs/print-tests T05).
_UPPERCASE_FONTS = {"B"}
_NO_LOWERCASE_FONTS = {"H"}
_CAPITALS = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)
_NO_LOWERCASE = str.maketrans(string.ascii_lowercase, " " * len(string.ascii_lowercase))
# OCR-A (H) has ASCII characters only; the other bitmap fonts have code page 850 and € (T05:
# E prints ó, A, B and D print €).
_ASCII_FONTS = {"H"}
# The OCR fonts (E = OCR-B, H = OCR-A) print a backslash; the other resident fonts, font 0
# included, print ¢ in its place with Unicode (^CI28) too (p.342, T05 and T06).
_OCR_FONTS = {"E", "H"}
# Field data escapes inside ^FB: \& line break, \\ backslash, \x soft hyphen.
_SOFT_HYPHEN = "\x00"
# ^GS symbols (p.162): registered, copyright, trademark, UL and CSA marks.
_SYMBOLS = {"A": "®", "B": "©", "C": "™", "D": "UL", "E": "CSA"}
# EAN and UPC human readable layout (T09): modules of the longer guard bars, the digit groups
# (the modules they are centred under and their slice of the text), and whether the first and
# the last digit stand outside the bars.
_EAN_GUARD_EXTENSION_MM = 1.5
_EAN_LAYOUT: dict[
    str, tuple[list[tuple[int, int]], list[tuple[tuple[int, int], tuple[int, int]]], bool, bool]
] = {
    "ean13": ([(0, 3), (45, 50), (92, 95)], [((3, 45), (1, 7)), ((50, 92), (7, 13))], True, False),
    "ean8": ([(0, 3), (31, 36), (64, 67)], [((3, 31), (0, 4)), ((36, 64), (4, 8))], False, False),
    "upca": ([(0, 10), (45, 50), (85, 95)], [((10, 45), (1, 6)), ((50, 85), (6, 11))], True, True),
}

BARCODE_NAMES = {
    "B1": "Code 11", "B4": "Code 49", "B5": "Planet Code", "B9": "UPC-E", "BA": "Code 93",
    "BB": "CODABLOCK", "BD": "MaxiCode", "BF": "MicroPDF417", "BI": "Industrial 2 of 5",
    "BJ": "Standard 2 of 5", "BL": "LOGMARS", "BM": "MSI", "BO": "Aztec", "BP": "Plessey",
    "BR": "GS1 DataBar", "BS": "UPC/EAN extension", "BT": "TLC39", "BZ": "POSTNET",
}  # fmt: skip

_TRANSPOSE = {
    "R": Image.Transpose.ROTATE_270,
    "I": Image.Transpose.ROTATE_180,
    "B": Image.Transpose.ROTATE_90,
}

# ^BQ field data: error correction (H, Q, M, L) and input mode (A or M), then a comma; in
# manual mode the data starts with its character mode (B takes a 4-digit byte count).
_QR_HEADER = re.compile(r"([HQML])([AM]),", re.IGNORECASE)
_QR_CHARACTER_MODE = re.compile(r"[NAK]|B[0-9]{4}", re.IGNORECASE)
# PDF417 field data escapes: \& line break, \\ backslash (p.34).
_PDF417_ESCAPE = re.compile(r"\\(.)", re.DOTALL)


class RenderError(ValueError):
    pass


def _trim_headroom(img: Image.Image, headroom: int) -> tuple[Image.Image, int]:
    """Drop the empty rows of the `headroom` on top of a rendered line or block; returns the
    image and how many rows above the cell it keeps."""
    box = img.getbbox()
    above = 0 if box is None else max(0, headroom - box[1])
    return img.crop((0, headroom - above, img.width, img.height)), above


@dataclass(slots=True)
class RenderResult:
    png: bytes
    width: int
    height: int
    label_count: int
    warnings: list[str]
    # Box (x, y, width, height) of every field placed on the label, rotated as printed.
    fields: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass(slots=True)
class _Field:
    x: int = 0
    y: int = 0
    typeset: bool = False  # ^FT instead of ^FO
    has_origin: bool = False
    font: tuple[str, str | None, int | None, int | None] | None = None  # name, orient, h, w
    block: tuple[int, int, int, str, int] | None = None  # width, lines, spacing, justify, indent
    text_block: tuple[str | None, int, int] | None = None  # ^TB orientation, width, height
    justify: int | None = None  # ^FO/^FT z (x.14+): 0 left, 1 right, 2 auto
    symbol: tuple[str | None, int | None, int | None] | None = None  # ^GS orient, h, w
    reverse: bool = False
    parameter: tuple[str, int] | None = None  # ^FP direction (H/V/R) and character gap
    hex_indicator: str | None = None
    barcode: Command | None = None
    graphic: Command | None = None
    data: str | None = None


@dataclass(slots=True)
class _Mask:
    image: Image.Image  # 'L', ink = 255
    anchor: tuple[int, int] = (0, 0)  # point used by ^FT, in unrotated mask coordinates
    white: bool = False
    # Parts of the image outside the field itself (left, top, right, bottom), e.g. barcode
    # text wider than the bars: ^FO places the field, not the whole image, at the origin.
    overhang: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class _State:
    width: int
    height: int
    dpmm: int
    home: tuple[int, int] = (0, 0)
    shift: int = 0
    reverse_all: bool = False
    invert: bool = False
    orientation: str = "N"
    justification: int = 0  # ^FW z (x.14+)
    default_font: tuple[str, int | None, int | None] = ("A", None, None)
    bar_width: int = 2
    bar_ratio: float = 3.0
    bar_height: int = 10
    encoding: str = "cp850"
    charset: int = 0  # ^CI number, for the national character sets
    mirror: bool = False
    next_typeset: tuple[int, int] = (0, 0)  # where ^FT without coordinates continues
    field: _Field = field(default_factory=_Field)


def _in_code_page_850(ch: str) -> bool:
    try:
        ch.encode("cp850")
    except UnicodeEncodeError:
        return False
    return True


def _block_paragraphs(text: str) -> list[str]:
    """Split ^FB field data at \\& and resolve \\\\ (backslash) and \\x (soft hyphen)."""
    paragraphs: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(text):
        ch, following = text[i], text[i + 1 : i + 2]
        if ch == "\\" and following == "&":
            paragraphs.append("".join(current))
            current = []
            i += 2
        elif ch == "\\" and following == "\\":
            current.append("\\")
            i += 2
        elif ch == "\\" and following.isalnum():
            # A soft hyphen: a possible break point, printed as "-" only where the line breaks.
            current.append(_SOFT_HYPHEN)
            i += 1
        else:
            current.append(ch)
            i += 1
    paragraphs.append("".join(current))
    return paragraphs


def _int(value: str | None, default: int) -> int:
    try:
        return int(float(value)) if value not in (None, "") else default
    except ValueError, OverflowError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _arg(args: list[str], index: int) -> str | None:
    return args[index] if index < len(args) and args[index] != "" else None


def _object_name(value: str, extension: str) -> str:
    name = value.split(",", 1)[0].split(":", 1)[-1].strip().upper()
    return name if "." in name else f"{name}{extension}"


class _Renderer:
    def __init__(self, dpi: int, width: int | None, height: int | None) -> None:
        self.dpi = dpi
        self.dpmm = max(1, round(dpi / 25.4))
        self.warnings: list[str] = []
        self.default_width, self.default_height = self.clamp_size(
            width or DEFAULT_WIDTH_IN * dpi, height or DEFAULT_HEIGHT_IN * dpi
        )
        self.graphics: dict[str, Bitmap] = {}
        self.images: dict[str, Image.Image] = {}  # label formats saved with ^IS
        self.stored_sizes: dict[tuple[str, str], int] = {}
        self.stored_total = 0
        self.placed: list[tuple[int, int, int, int]] = []

    def clamp_size(self, width: int, height: int) -> tuple[int, int]:
        if width > MAX_WIDTH or height > MAX_HEIGHT:
            self.warn(f"Label size clipped to {MAX_WIDTH}x{MAX_HEIGHT} dots")
        return max(1, min(width, MAX_WIDTH)), max(1, min(height, MAX_HEIGHT))

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def reserve(self, kind: str, name: str, size: int) -> bool:
        """Account for a stored ~DG graphic or ^IS image; False when over the memory budget."""
        key = (kind, name)
        total = self.stored_total - self.stored_sizes.get(key, 0) + size
        if total > MAX_STORED_BYTES:
            self.warn(f"{name} is not stored: too many stored graphics and images")
            return False
        self.stored_sizes[key] = size
        self.stored_total = total
        return True

    # ---- formats -------------------------------------------------------------------------

    def split_formats(self, commands: list[Command]) -> list[list[Command]]:
        formats: list[list[Command]] = []
        current: list[Command] | None = None
        for command in commands:
            if command.prefix == "~" and command.code == "DG":
                self.download_graphic(command)
            elif command.code == "XA":
                current = []
            elif command.code == "XZ":
                if current is not None:
                    formats.append(current)
                current = None
            elif current is not None:
                current.append(command)
        if current:
            self.warn("Missing ^XZ at the end of the label")
            formats.append(current)
        return formats

    def download_graphic(self, command: Command) -> None:
        args = command.args(3)
        if len(args) < 4:
            self.warn("Invalid ~DG command")
            return
        name = _object_name(args[0], ".GRF")
        total, bpr = _int(args[1], 0), _int(args[2], 0)
        try:
            data = decode_graphic_data(args[3], total=total, bytes_per_row=bpr)
            if self.reserve("DG", name, len(data)):
                self.graphics[name] = Bitmap(bpr * 8, total // bpr, bpr, data)
        except (GraphicError, ZeroDivisionError, ValueError) as exc:
            self.warn(f"Invalid ~DG graphic {name}: {exc}")

    def render(self, commands: list[Command]) -> Image.Image:
        """Render a format as printed: composed, then mirrored (^PM) and inverted (^PO)."""
        image = self.compose(commands)
        if self.state.mirror:
            image = ImageOps.mirror(image)
        if self.state.invert:
            image = image.transpose(Image.Transpose.ROTATE_180)
        return image

    def compose(self, commands: list[Command]) -> Image.Image:
        """Draw all fields of a format; orientation is applied by `render`."""
        width, height = self.default_width, self.default_height
        for command in commands:
            if command.code == "PW":
                width = _int(command.args()[0], width)
            elif command.code == "LL":
                height = _int(command.args()[0], height)
        width, height = self.clamp_size(width, height)
        self.canvas = Image.new("L", (width, height), 255)
        self.state = _State(width, height, self.dpmm, bar_height=10)
        self.placed = []
        for command in commands:
            try:
                self.execute(command)
            except Exception as exc:
                self.warn(f"{command.name}: {exc}")
                self.state.field = _Field()
        try:
            self.finish_field()
        except Exception as exc:
            self.warn(f"Last field: {exc}")
        return self.canvas

    # ---- commands ------------------------------------------------------------------------

    def execute(self, command: Command) -> None:
        state, f = self.state, self.state.field
        code = command.code
        args = command.args()
        match code:
            case "FO" | "FT":
                if f.has_origin and (f.data is not None or f.graphic):
                    self.finish_field()
                    f = self.state.field
                # ^FT without a coordinate continues after the last typeset field (p.150).
                default = state.next_typeset if code == "FT" else (0, 0)
                f.x, f.y = _int(_arg(args, 0), default[0]), _int(_arg(args, 1), default[1])
                # Justification (firmware x.14 and later, e.g. ZebraDesigner 3's right-aligned
                # fields): 0 left, 1 right, 2 automatic (left for left-to-right scripts).
                f.justify = _int(_arg(args, 2), 0) if _arg(args, 2) else None
                f.typeset = code == "FT"
                f.has_origin = True
            case "FS":
                self.finish_field()
            case "FD" | "FV":
                f.data = command.params
            case "FH":
                f.hex_indicator = field_hex_indicator(command.params)
            case "FP":
                direction = (_arg(args, 0) or "H").upper()[:1]
                gap = max(0, min(9999, _int(_arg(args, 1), 0)))
                f.parameter = (direction if direction in "HVR" else "H", gap)
            case "FR":
                f.reverse = True
            case "FB":
                f.block = (
                    _int(_arg(args, 0), 0),
                    max(1, min(9999, _int(_arg(args, 1), 1))),
                    max(-9999, min(9999, _int(_arg(args, 2), 0))),
                    (_arg(args, 3) or "L").upper()[:1],
                    max(0, min(9999, _int(_arg(args, 4), 0))),
                )
            case "FW":
                state.orientation = (_arg(args, 0) or state.orientation).upper()[:1]
                if _arg(args, 1):
                    state.justification = _int(_arg(args, 1), 0)
            case "TB":
                # ^TBa,b,c (firmware x.16 and later): a text block that clips instead of
                # overprinting.
                orient = (_arg(args, 0) or "").upper()[:1] or None
                f.text_block = (
                    orient,
                    max(1, _int(_arg(args, 1), 1)),
                    max(1, _int(_arg(args, 2), 1)),
                )
            case "A":
                spec = args[0] if args else ""
                # Without a font name the ^CF font is used (p.12).
                name = spec[:1] or state.default_font[0]
                orient = spec[1:2].upper() or None
                f.font = (
                    name,
                    orient,
                    _int(_arg(args, 1), 0) or None,
                    _int(_arg(args, 2), 0) or None,
                )
            case "CF":
                name, h, w = state.default_font
                state.default_font = (
                    (_arg(args, 0) or name)[:1],
                    _int(_arg(args, 1), 0) or h,
                    _int(_arg(args, 2), 0) or w,
                )
            case "CI":
                state.charset = _int(_arg(args, 0), 0)
                state.encoding = _ENCODINGS.get(str(state.charset), "cp850")
            case "GS":
                orient = (_arg(args, 0) or "").upper()[:1] or None
                f.symbol = (orient, _int(_arg(args, 1), 0) or None, _int(_arg(args, 2), 0) or None)
            case "PM":
                state.mirror = (_arg(args, 0) or "N").upper() == "Y"
            case "JM":
                if (_arg(args, 0) or "A").upper() == "B":
                    self.warn("^JMB (half dot density) is not shown in the preview")
            case "MU":
                if (_arg(args, 0) or "D").upper() != "D":
                    self.warn("^MU units other than dots are not supported in the preview")
            case "IL":
                name = _object_name(args[0] if args else "", ".GRF")
                image = self.images.get(name)
                if image is None:
                    self.warn(
                        f"Image {name} not found (it must be saved with ^IS in the same data)"
                    )
                else:
                    self.canvas.paste(image, (0, 0))
            case "LH":
                state.home = (_int(_arg(args, 0), 0), _int(_arg(args, 1), 0))
            case "LS":
                state.shift = _int(_arg(args, 0), 0)
            case "LR":
                state.reverse_all = (_arg(args, 0) or "N").upper() == "Y"
            case "PO":
                state.invert = (_arg(args, 0) or "N").upper() == "I"
            case "BY":
                state.bar_width = max(1, min(10, _int(_arg(args, 0), state.bar_width)))
                state.bar_ratio = max(2.0, min(3.0, _float(_arg(args, 1), state.bar_ratio)))
                state.bar_height = _int(_arg(args, 2), state.bar_height)
            case _ if code[0] == "B" and code != "BY":
                f.barcode = command
            case "GB" | "GC" | "GE" | "GD" | "GF" | "XG" | "IM":
                f.graphic = command
            case "FX":
                pass
            case "SN":
                f.data = command.args()[0] if command.params else ""
                self.warn(f"{command.name} serialization is previewed as the starting value")
            case "SF":
                # ^SF takes a mask and an increment; the starting value is the field's ^FD.
                self.warn(f"{command.name} serialization is previewed as the starting value")
            case _ if code in IGNORED:
                pass
            case _:
                self.warn(f"Unsupported command {command.name} ignored")

    # ---- fields --------------------------------------------------------------------------

    def field_text(self, f: _Field) -> str:
        data = f.data or ""
        encoding = self.state.encoding
        if f.hex_indicator:
            data = decode_field_hex(data, f.hex_indicator, encoding=encoding)
        elif not data.isascii() and encoding != "utf-8":
            # Text is sent as UTF-8; without ^CI28 the printer reads those bytes differently.
            data = data.encode("utf-8").decode(encoding, "replace")
        if not (f.data or "").isascii() and encoding != "utf-8":
            self.warn(
                f"Field at {f.x},{f.y} contains non-ASCII characters but ^CI28 (UTF-8) is not "
                "active, so they print as shown"
            )
        return data

    def printable(self, text: str, font_name: str, f: _Field) -> str:
        """Text as the resident font prints it: characters the font lacks are blank, national
        characters (^CI0-12) replace some ASCII ones, and some fonts have capitals only."""
        name = font_name.upper()
        resident = bitmap_metrics(name) is not None
        if resident:
            ascii_only = name in _ASCII_FONTS
            missing = sorted(
                {
                    ch
                    for ch in text
                    if not (" " <= ch <= "~" if ascii_only else _in_code_page_850(ch) or ch == "€")
                }
            )
            if missing:
                repertoire = "ASCII" if ascii_only else "code page 850"
                self.warn(
                    f"Font {name} at {f.x},{f.y} has no {' '.join(missing)}; they print blank "
                    f"(it has {repertoire} characters only)"
                )
                text = "".join(" " if ch in missing else ch for ch in text)
        table = _NATIONAL_TABLES.get(self.state.charset) if self.state.encoding == "cp850" else None
        if table:
            text = text.translate(table)
        elif (
            self.state.encoding.startswith("utf")
            and (resident or name == "0")
            and name not in _OCR_FONTS
            and "\\" in text
        ):
            self.warn(f"Font {name} at {f.x},{f.y} prints a backslash as ¢")
            text = text.replace("\\", "¢")
        if name in _UPPERCASE_FONTS and text != text.translate(_CAPITALS):
            self.warn(
                f"Font {name} at {f.x},{f.y} has no lowercase letters; they are shown as capitals"
            )
            text = text.translate(_CAPITALS)
        if name in _NO_LOWERCASE_FONTS and text != text.translate(_NO_LOWERCASE):
            self.warn(f"Font {name} at {f.x},{f.y} has no lowercase letters; they print blank")
            text = text.translate(_NO_LOWERCASE)
        return text

    def finish_field(self) -> None:
        f = self.state.field
        self.state.field = _Field()
        if not f.has_origin and f.data is None and f.graphic is None:
            return
        try:
            if f.graphic is not None:
                mask = self.graphic_mask(f.graphic)
                orientation = "N"
            elif f.barcode is not None and f.data is not None:
                data = self.field_text(f)
                if not data.strip():
                    self.warn(f"{f.barcode.name} at {f.x},{f.y} has no data, so nothing is printed")
                    return
                mask, orientation = self.barcode_mask(f.barcode, data, f)
            elif f.symbol is not None and f.data is not None:
                mask, orientation = self.symbol_mask(f)
            elif f.data is not None:
                mask, orientation = self.text_mask(f)
            else:
                return
        except barcodes.BarcodeError as exc:
            self.warn(f"Barcode at {f.x},{f.y}: {exc}")
            return
        except (GraphicError, ValueError) as exc:
            self.warn(f"Field at {f.x},{f.y}: {exc}")
            return
        if mask is None:
            return
        self.place(mask, orientation, f)

    def place(self, mask: _Mask, orientation: str, f: _Field) -> None:
        image = mask.image
        ax, ay = mask.anchor
        left, top, right, bottom = mask.overhang
        w, h = image.size
        if orientation in _TRANSPOSE:
            image = image.transpose(_TRANSPOSE[orientation])
            ax, ay = {"R": (h - ay, ax), "I": (w - ax, h - ay), "B": (ay, w - ax)}[orientation]
            # The margins turn with the image (clockwise for R).
            left, top = {"R": (bottom, left), "I": (right, bottom), "B": (top, right)}[orientation]
        x = self.state.home[0] + f.x - self.state.shift
        y = self.state.home[1] + f.y
        if not f.typeset:
            x, y = x - left, y - top
        justify = f.justify if f.justify is not None else self.state.justification
        if justify == 1:
            if orientation == "N":
                # Right justification: the field ends at the origin.
                x -= w
            else:
                self.warn(
                    f"Right justification of the rotated field at {f.x},{f.y} is previewed as "
                    "left justification"
                )
        if f.typeset:
            x, y = x - ax, y - ay
            # The next ^FT without coordinates continues after this field.
            step = {"R": (0, w), "I": (-w, 0), "B": (0, -w)}.get(orientation, (w, 0))
            self.state.next_typeset = (f.x + step[0], f.y + step[1])
        self.placed.append((x, y, image.width, image.height))
        reverse = f.reverse or self.state.reverse_all
        box = (x, y, x + image.width, y + image.height)
        if reverse:
            region = self.canvas.crop(box)
            region.paste(ImageChops.invert(region), (0, 0), image)
            self.canvas.paste(region, box)
        else:
            self.canvas.paste(255 if mask.white else 0, box, image)

    def font_spec(self, f: _Field) -> tuple[str, str | None, int | None, int | None]:
        default_name, default_h, default_w = self.state.default_font
        if f.font:
            name, orient, h, w = f.font
        else:
            name, orient, h, w = default_name, None, None, None
        if h is None and w is None:
            # "If neither is defined, the ^CF height and width are used."
            h, w = default_h, default_w
        return name, orient, h, w

    def font_for(self, f: _Field) -> tuple[ZebraFont, str]:
        name, orient, h, w = self.font_spec(f)
        return resolve_font(name, h, w, self.dpmm), (orient or self.state.orientation)

    def text_mask(self, f: _Field) -> tuple[_Mask | None, str]:
        font, orientation = self.font_for(f)
        name = self.font_spec(f)[0]
        text = self.field_text(f)
        if f.block:
            return self.block_mask(text, font, name, f), orientation
        if f.text_block:
            return self.text_block_mask(text, font, name, f), f.text_block[0] or orientation
        text = self.printable(text, name, f)
        if not text:
            return None, orientation
        if f.parameter and (f.parameter[0] != "H" or f.parameter[1]):
            return self.spaced_text(text, font, *f.parameter), orientation
        img, above = _trim_headroom(font.render_line(text, above=True), font.headroom)
        return _Mask(img, (0, above + font.baseline), overhang=(0, above, 0, 0)), orientation

    def block_mask(self, text: str, font: ZebraFont, name: str, f: _Field) -> _Mask | None:
        """^FB: word wrap, justification, hanging indent and overprinted extra lines."""
        assert f.block is not None
        width, max_lines, spacing, justify, indent = f.block
        font_width = font.char_width or round(font.cell_height * font.scale_x)
        if width < font_width:
            self.warn(
                f"Text block at {f.x},{f.y} is narrower than the font, so the text does not print"
            )
            return None
        lines = [
            (self.printable(line, name, f), end)
            for line, end in self.wrap(text, font, width, indent)
        ]
        if len(lines) > max_lines:
            self.warn(
                f"Text block at {f.x},{f.y} needs {len(lines)} lines but allows {max_lines}; "
                "the extra lines print over the last one"
            )
        line_h = max(1, font.cell_height + spacing)
        shown = min(len(lines), max_lines)
        # Lines are drawn with the rows above their cell, so accents on the first line can
        # rise above the block like on a single line.
        headroom = font.headroom
        img = new_mask(width, headroom + (shown - 1) * line_h + font.cell_height)
        for index, (line, ends_paragraph) in enumerate(lines):
            row = min(index, max_lines - 1)
            offset = indent if index else 0
            room = width - offset
            words = line.split(" ")
            if justify == "J" and not ends_paragraph and len(words) > 1:
                images = [font.render_line(word, above=True) for word in words]
                gap = (room - sum(i.width for i in images)) / (len(images) - 1)
                x = float(offset)
                for word_img in images:
                    img.paste(word_img, (round(x), row * line_h), word_img)
                    x += word_img.width + gap
                continue
            line_img = font.render_line(line, above=True)
            if justify == "C":
                offset += (room - line_img.width) // 2
            elif justify == "R":
                offset += room - line_img.width
            img.paste(line_img, (offset, row * line_h), line_img)
        img, above = _trim_headroom(img, headroom)
        # The printer keeps room for every line of the block, also those left empty: a
        # rotated block with fewer lines prints its first line on the far side (T03, R:
        # two lines to the right of ^FO). The empty lines are a negative bottom margin.
        unused = (max_lines - shown) * line_h
        # ^FT uses the baseline of the last possible line of the block (p.138).
        return _Mask(
            img,
            (0, above + (max_lines - 1) * line_h + font.baseline),
            overhang=(0, above, 0, -unused),
        )

    def text_block_mask(self, text: str, font: ZebraFont, name: str, f: _Field) -> _Mask:
        """^TB: word wrap within width x height; lines whose baseline is outside the block are
        not printed, and the block cuts off what reaches below it (T16)."""
        assert f.text_block is not None
        _, width, height = f.text_block
        lines = self.wrap(text, font, width, escapes=False, hyphenate=False)
        img = new_mask(width, height)
        # Font 0 lines are 1.25 times its height apart (38 dots at h=30), not h as in ^FB.
        pitch = font.cell_height if font.advance is not None else round(font.cell_height * 5 / 4)
        for row, (line, _) in enumerate(lines):
            top = row * pitch
            if top + font.baseline > height:
                self.warn(f"Text block at {f.x},{f.y}: text beyond the block height is cut off")
                break
            line_img = font.render_line(self.printable(line, name, f))
            img.paste(line_img, (0, top), line_img)
        return _Mask(img, (0, font.baseline))

    def symbol_mask(self, f: _Field) -> tuple[_Mask | None, str]:
        """^GS: registered, copyright and trademark signs and the UL and CSA marks."""
        assert f.symbol is not None
        orient, h, w = f.symbol
        if h is None and w is None:
            h, w = self.state.default_font[1:]
        symbols = [_SYMBOLS[ch] for ch in self.field_text(f).upper() if ch in _SYMBOLS]
        if not symbols:
            return None, orient or self.state.orientation
        font = resolve_font("0", h or w or 24, w or h, self.dpmm)
        parts = []
        for symbol in symbols:
            glyph = font.render_line(symbol)
            if len(symbol) > 1:  # UL and CSA are circled marks
                ring = new_mask(glyph.width + 8, font.cell_height)
                ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), outline=255)
                ring.paste(glyph, (4, 0), glyph)
                glyph = ring
            parts.append(glyph)
        img = new_mask(sum(p.width for p in parts), font.cell_height)
        x = 0
        for part in parts:
            img.paste(part, (x, 0), part)
            x += part.width
        return _Mask(img, (0, font.baseline)), orient or self.state.orientation

    @staticmethod
    def spaced_text(text: str, font: ZebraFont, direction: str, gap: int) -> _Mask:
        """^FP: characters with extra spacing, stacked vertically (V) or right-to-left (R)."""
        # Size the result before rendering any glyph (render_line is exactly cell_height tall).
        widths = [max(1, font.line_width(ch)) for ch in text]
        if direction == "V":
            width = max(widths)
            img = new_mask(width, font.cell_height * len(text) + gap * (len(text) - 1))
            y = 0
            for ch in text:
                glyph = font.render_line(ch)
                img.paste(glyph, ((width - glyph.width) // 2, y), glyph)
                y += glyph.height + gap
            return _Mask(img, (0, font.baseline))
        if direction == "R":
            text, widths = text[::-1], widths[::-1]
        # The gap is in addition to the font's own spacing (bitmap fonts have a fixed advance).
        steps = [(font.advance or w) + gap for w in widths]
        img = new_mask(max(1, sum(steps[:-1]) + widths[-1]), font.cell_height)
        x = 0
        for ch, step in zip(text, steps, strict=True):
            glyph = font.render_line(ch)
            img.paste(glyph, (x, 0), glyph)
            x += step
        return _Mask(img, (0, font.baseline))

    @staticmethod
    def wrap(
        text: str,
        font: ZebraFont,
        width: int,
        indent: int = 0,
        *,
        escapes: bool = True,
        hyphenate: bool = True,
    ) -> list[tuple[str, bool]]:
        """Break ^FB text into (line, ends_paragraph) like the printer (p.137-138).

        Lines break at spaces and at \\&; a word wider than the block is split at a soft hyphen
        (\\ before a letter or digit) or else at the block edge, with a hyphen. Without
        `escapes` the text is taken literally, without `hyphenate` long words are cut (^TB).
        """
        mark = "-" if hyphenate else ""

        def measure(value: str) -> int:
            return font.line_width(value.replace(_SOFT_HYPHEN, ""))

        def split(word: str, room: int) -> tuple[str, str] | None:
            """Longest head of the word that fits in `room` with a hyphen, preferring soft
            hyphens; None if not even one character fits."""
            soft = [i for i, ch in enumerate(word) if ch == _SOFT_HYPHEN]
            for i in reversed(soft):
                if measure(word[:i] + mark) <= room:
                    return word[:i], word[i + 1 :]
            visible = [i for i, ch in enumerate(word) if ch != _SOFT_HYPHEN]
            for count in range(len(visible) - 1, 0, -1):
                cut = visible[count]
                if measure(word[:cut] + mark) <= room:
                    return word[:cut], word[cut:]
            return None

        lines: list[tuple[str, bool]] = []

        def room() -> int:
            return width - (indent if lines else 0)

        for paragraph in _block_paragraphs(text) if escapes else [text]:
            current = ""
            for word in paragraph.split(" "):
                candidate = f"{current} {word}" if current else word
                if measure(candidate) <= room():
                    current = candidate
                    continue
                if current:
                    # Fill the line with the head of the word when a soft hyphen allows it.
                    head = None
                    if _SOFT_HYPHEN in word:
                        head = split(word, room() - measure(current + " "))
                    if head and word[len(head[0]) : len(head[0]) + 1] == _SOFT_HYPHEN:
                        lines.append((f"{current} {head[0]}-", False))
                        word = head[1]
                    else:
                        lines.append((current, False))
                    current = ""
                while measure(word) > room():
                    parts = split(word, room())
                    if parts is None:
                        break
                    lines.append((parts[0] + mark, False))
                    word = parts[1]
                current = word
            lines.append((current, True))
        return [(line.replace(_SOFT_HYPHEN, ""), end) for line, end in lines]

    # ---- barcodes ------------------------------------------------------------------------

    def interpretation_font(self, module_width: int, f: _Field) -> ZebraFont:
        """Interpretation line font: the field's ^A font if it has one (p.47), else font A
        magnified by the module width (T03, T08: ^BY2 prints it twice, ^BY3 three times the
        5 x 9 matrix)."""
        if f.font:
            return self.font_for(f)[0]
        return resolve_font("A", 9 * module_width, 5 * module_width, self.dpmm)

    def linear_mask(
        self,
        code: barcodes.LinearCode,
        height: int,
        show_text: bool,
        text_above: bool,
        f: _Field,
        symbology: str = "",
    ) -> _Mask:
        for warning in code.warnings:
            self.warn(f"Barcode at {f.x},{f.y}: {warning}")
        mw = self.state.bar_width
        runs = code.runs(mw, self.state.bar_ratio)
        bars = new_mask(max(1, sum(width for _, width in runs)), max(1, height))
        draw = ImageDraw.Draw(bars)
        x = 0
        for is_bar, width in runs:
            if is_bar:
                draw.rectangle((x, 0, x + width - 1, height), fill=255)
            x += width
        if not show_text:
            return _Mask(bars, (0, bars.height))
        if symbology in _EAN_LAYOUT and not text_above:
            return self.ean_mask(code, bars, symbology, f)
        label = self.interpretation_font(mw, f).render_line(code.text)
        # Text above the bars stands further off them than text below (T17: 8 dots at ^BY2).
        gap = mw * 4 if text_above else mw * 2
        # In the default font the text is centred on the bars, even when it is the wider of
        # the two; in an ^A font it starts at their left edge (T02f/g).
        shift = 0 if f.font else (bars.width - label.width) // 2
        bars_x = max(0, -shift)
        label_x = bars_x + shift
        total_w = max(bars_x + bars.width, label_x + label.width)
        right = total_w - bars_x - bars.width
        text_h = gap + label.height
        img = new_mask(total_w, bars.height + text_h)
        # The bars are the field and the text is outside it, so ^FO places the bars: text
        # above starts above the origin (T17), and a rotated bar code has its text beyond the
        # bars (T03, ^BCR: text left of the origin).
        if text_above:
            img.paste(label, (label_x, 0))
            img.paste(bars, (bars_x, text_h))
            return _Mask(img, (bars_x, img.height), overhang=(bars_x, text_h, right, 0))
        img.paste(bars, (bars_x, 0))
        img.paste(label, (label_x, bars.height + gap))
        return _Mask(img, (bars_x, bars.height), overhang=(bars_x, 0, right, text_h))

    def ean_mask(
        self, code: barcodes.LinearCode, bars: Image.Image, symbology: str, f: _Field
    ) -> _Mask:
        """EAN and UPC with their usual human readable layout (T09): longer guard bars, the
        digits in two groups at the centre guard, and the first (and the last UPC-A) digit
        outside."""
        mw = self.state.bar_width
        guards, groups, first, last = _EAN_LAYOUT[symbology]
        font = self.interpretation_font(mw, f)
        gap = mw
        # The guard bars reach 12 (at most 13) dots below the others at 8 dots/mm, at ^BY2 and
        # ^BY3 and bar heights 50 and 100 (T09, T17).
        extension = round(_EAN_GUARD_EXTENSION_MM * self.dpmm)
        first_img = font.render_line(code.text[0]) if first else None
        last_img = font.render_line(code.text[-1]) if last else None
        # The first digit ends 4 modules before the bars (9 modules before them it starts in
        # font A), the last UPC-A digit starts 2 modules after them.
        left = 4 * mw + first_img.width if first_img else 0
        right = 2 * mw + last_img.width if last_img else 0
        height = bars.height + max(extension, gap + font.cell_height)
        img = new_mask(left + bars.width + right, height)
        img.paste(bars, (left, 0))
        draw = ImageDraw.Draw(img)
        for start, end in guards:
            for module in range(start, end):
                if code.pattern[module] == "1":
                    x = left + module * mw
                    draw.rectangle(
                        (x, bars.height, x + mw - 1, bars.height + extension - 1), fill=255
                    )
        top = bars.height + gap
        # The digits keep to the centre guard: the left group ends just before it and the
        # right group starts just after it (T09, T17).
        (left_span, left_text), (right_span, right_text) = groups
        group = font.render_line(code.text[slice(*left_text)])
        img.paste(group, (left + left_span[1] * mw - 1 - group.width, top), group)
        group = font.render_line(code.text[slice(*right_text)])
        img.paste(group, (left + right_span[0] * mw + 1, top), group)
        if first_img:
            img.paste(first_img, (0, top), first_img)
        if last_img:
            img.paste(last_img, (left + bars.width + 2 * mw, top), last_img)
        return _Mask(img, (left, bars.height), overhang=(left, 0, right, img.height - bars.height))

    @staticmethod
    def matrix_mask(matrix: list[list[int]], module: int) -> _Mask:
        rows, cols = len(matrix), len(matrix[0]) if matrix else 0
        check_size(cols * module, rows * module)
        img = new_mask(cols, rows)
        img.putdata([255 if cell else 0 for row in matrix for cell in row])
        img = img.resize((cols * module, rows * module), Image.Resampling.NEAREST)
        return _Mask(img, (0, img.height))

    def field_bytes(self, text: str) -> bytes:
        """Field data as the bytes the printer receives in the active ^CI encoding."""
        try:
            return text.encode(self.state.encoding)
        except UnicodeEncodeError:
            return text.encode("utf-8")

    def barcode_mask(self, command: Command, data: str, f: _Field) -> tuple[_Mask | None, str]:
        args = command.args()
        state = self.state
        orientation = (_arg(args, 0) or state.orientation).upper()[:1]

        def yes(index: int, default: str) -> bool:
            return (_arg(args, index) or default).upper() == "Y"

        def linear(symbology: str, height: int, text: int, above: int, **kwargs) -> _Mask:
            symbol = barcodes.linear(symbology, data, **kwargs)
            return self.linear_mask(symbol, height, yes(text, "Y"), yes(above, "N"), f, symbology)

        code = command.code
        if code == "BC":
            height = _int(_arg(args, 1), state.bar_height)
            mode = (_arg(args, 5) or "N").upper()[:1]
            return linear("code128", height, 2, 3, check_digit=yes(4, "N"), mode=mode), orientation
        if code == "B3":
            height = _int(_arg(args, 2), state.bar_height)
            return linear("code39", height, 3, 4, check_digit=yes(1, "N")), orientation
        if code in ("BE", "B8", "BU"):
            symbology = {"BE": "ean13", "B8": "ean8", "BU": "upca"}[code]
            height = _int(_arg(args, 1), state.bar_height)
            return linear(symbology, height, 2, 3), orientation
        if code == "B2":
            height = _int(_arg(args, 1), state.bar_height)
            return linear("itf", height, 2, 3, check_digit=yes(4, "N")), orientation
        if code == "BQ":
            default_magnification = {6: 1, 8: 2, 12: 3, 24: 6}.get(self.dpmm, 2)
            magnification = max(1, min(10, _int(_arg(args, 2), default_magnification)))
            error, payload = "M", data
            header = _QR_HEADER.match(data)
            if header:
                error, payload = header.group(1).upper(), data[header.end() :]
                if header.group(2).upper() == "M":
                    mode = _QR_CHARACTER_MODE.match(payload)
                    if mode and mode.group().upper().startswith("B"):
                        # Byte mode: Bnnnn gives the number of data bytes that follow.
                        count = int(mode.group()[1:])
                        raw = self.field_bytes(payload[mode.end() :])
                        if count != len(raw):
                            self.warn(
                                f"{command.name} at {f.x},{f.y}: byte mode count {count} does "
                                f"not match the {len(raw)} bytes of data"
                            )
                        payload = raw[:count]
                    else:
                        payload = payload[mode.end() :] if mode else payload
                elif any(0x80 <= b <= 0x9F or b >= 0xE0 for b in self.field_bytes(payload)):
                    self.warn(
                        f"{command.name} at {f.x},{f.y}: automatic input cannot carry these "
                        "characters on older firmware (bytes 80-9F and E0-FF, p.84; V84.20 "
                        "encodes them); manual byte mode (e.g. QM,B0012...) works on all"
                    )
            else:
                self.warn(
                    f"{command.name} at {f.x},{f.y} has no error correction and input mode "
                    "(e.g. QA,) before its data, so the preview encodes all of it"
                )
            if not payload.strip():
                self.warn(f"{command.name} at {f.x},{f.y} has no data, so nothing is printed")
                return None, "N"
            matrix = barcodes.qr_matrix(payload, error)
            mask = self.matrix_mask(matrix, magnification)
            # The symbol prints 2 dots less than the ^BY height (default 10) below ^FO, and ^BY
            # stays set from earlier labels (T11 printed 118 dots low after T10's ^BY2,3,120;
            # T17: 8 and 58 for 10 and 60).
            mask.overhang = (0, -max(0, state.bar_height - 2), 0, 0)
            return mask, "N"
        if code == "BX":
            module = max(1, _int(_arg(args, 1), max(1, self.dpmm // 2)))
            escape = (_arg(args, 6) or "~")[:1]
            text = self.datamatrix_data(data, escape, f) if _arg(args, 2) == "200" else data
            return self.matrix_mask(barcodes.datamatrix_matrix(text), module), orientation
        if code == "B7":
            mw = state.bar_width
            security = max(0, min(8, _int(_arg(args, 2), 2)))
            columns = max(1, min(30, _int(_arg(args, 3), 4)))
            # \& is a line break and \\ a backslash in PDF417 field data (p.34); before any
            # other character the backslash is dropped (T10: C:\new reads "C:new"). One pass
            # from the left, so an escaped backslash before "&" stays a backslash.
            text = _PDF417_ESCAPE.sub(lambda m: "\r\n" if m.group(1) == "&" else m.group(1), data)
            rows = barcodes.pdf417_rows(text, columns=columns, security=security)
            # h is the row height in dots: the guide multiplies it by the module width (p.31),
            # the printer does not (T10: ^BY2 h6 and ^BY3 h4 print 6 and 4 dot rows). Without
            # it ^BY's height is shared by the rows.
            h = _int(_arg(args, 1), 0)
            row_height = h if h > 0 else max(1, round(state.bar_height / len(rows)))
            width = max(len(row) for row in rows)
            img = new_mask(width * mw, len(rows) * row_height)
            draw = ImageDraw.Draw(img)
            for r, row in enumerate(rows):
                for c, module in enumerate(row):
                    if module == "1":
                        draw.rectangle(
                            (c * mw, r * row_height, c * mw + mw - 1, (r + 1) * row_height - 1),
                            fill=255,
                        )
            return _Mask(img, (0, img.height)), orientation
        if code == "BK":
            # ^BKo,e,h,f,g,k,l: k/l are the start and stop characters (A-D).
            height = _int(_arg(args, 2), state.bar_height)
            start = (_arg(args, 5) or "A").upper()[:1]
            stop = (_arg(args, 6) or "A").upper()[:1]
            symbol = barcodes.linear("codabar", f"{start}{data}{stop}")
            return self.linear_mask(symbol, height, yes(3, "Y"), yes(4, "N"), f), orientation
        name = BARCODE_NAMES.get(code, "this bar code")
        raise barcodes.BarcodeError(f"{command.name} ({name}) is not drawn in the preview")

    def datamatrix_data(self, data: str, escape: str, f: _Field) -> str:
        """Resolve ^BX quality 200 escape sequences (p.102): a doubled escape character is
        the character itself, ~X a control character, ~dNNN a byte; FNC, structured append
        and code page sequences cannot be previewed and are dropped."""
        out: list[str] = []
        i = 0
        while i < len(data):
            ch = data[i]
            if ch != escape or i + 1 >= len(data):
                out.append(ch)
                i += 1
                continue
            following = data[i + 1]
            if following == escape:
                out.append(escape)
                i += 2
            elif following == "d" and re.fullmatch(r"[0-9]{3}", data[i + 2 : i + 5]):
                out.append(chr(min(255, int(data[i + 2 : i + 5]))))
                i += 5
            elif "@" <= following <= "_":
                out.append(chr(ord(following) - 64))
                i += 2
            else:
                skip = {"1": 2, "2": 11, "3": 2, "5": 5}.get(following, 2)
                self.warn(
                    f"^BX at {f.x},{f.y}: escape sequence {data[i : i + skip]} is not shown in "
                    "the preview"
                )
                i += skip
        return "".join(out)

    # ---- graphics ------------------------------------------------------------------------

    def graphic_mask(self, command: Command) -> _Mask | None:
        code = command.code
        if code == "GF":
            return self.field_graphic(command)
        if code in ("XG", "IM"):
            args = command.args()
            name = _object_name(args[0] if args else "", ".GRF")
            bitmap = self.graphics.get(name)
            if bitmap is None:
                self.warn(f"Graphic {name} not found (it must be downloaded in the same data)")
                return None
            check_size(bitmap.bytes_per_row * 8, bitmap.height)
            img = bitmap.to_mask()
            if code == "XG":
                mx = max(1, min(10, _int(_arg(args, 1), 1)))
                my = max(1, min(10, _int(_arg(args, 2), 1)))
                if mx > 1 or my > 1:
                    check_size(img.width * mx, img.height * my)
                    img = img.resize((img.width * mx, img.height * my), Image.Resampling.NEAREST)
            return _Mask(img, (0, img.height))
        args = command.args()
        color_index = {"GB": 3, "GC": 2, "GE": 3, "GD": 3}[code]
        white = (_arg(args, color_index) or "B").upper() == "W"
        if code == "GC":
            d = max(1, _int(_arg(args, 0), 3))
            t = max(1, _int(_arg(args, 1), 1))
            img = self.ellipse(d, d, t)
        elif code == "GE":
            # "larger values are replaced with 4095" (p.159)
            t = max(1, min(4095, _int(_arg(args, 2), 1)))
            w = min(4095, _int(_arg(args, 0), t))
            h = min(4095, _int(_arg(args, 1), t))
            if w < 3 or h < 3:
                # Below the 3-dot minimum (p.159) the printer prints nothing (T12: ^GE2,100,2).
                self.warn(f"{command.name}{w},{h}: ellipses under 3 dots wide or high do not print")
                return None
            # The border prints one dot thicker, inwards, than given, and at least 3 dots
            # (T12, T17: t = 1, 2, 3, 4 print 3, 3, 4, 5 dots).
            img = self.ellipse(w, h, max(2, t) + 1)
        elif code == "GD":
            t = max(1, _int(_arg(args, 2), 1))
            w, h = max(1, _int(_arg(args, 0), t)), max(1, _int(_arg(args, 1), t))
            lean = (_arg(args, 4) or "R").upper()
            img = new_mask(w + t, h)
            if lean in ("R", "/"):
                points = [(0, h), (t, h), (w + t, 0), (w, 0)]
            else:
                points = [(0, 0), (t, 0), (w + t, h), (w, h)]
            ImageDraw.Draw(img).polygon(points, fill=255)
        else:  # GB
            t = max(1, _int(_arg(args, 2), 1))
            w, h = max(t, _int(_arg(args, 0), t)), max(t, _int(_arg(args, 1), t))
            rounding = max(0, min(8, _int(_arg(args, 4), 0)))
            img = new_mask(w, h)
            draw = ImageDraw.Draw(img)
            if rounding:
                radius = math.floor(min(w, h) * rounding / 16)
                draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
                if t * 2 < min(w, h):
                    draw.rounded_rectangle(
                        (t, t, w - 1 - t, h - 1 - t), radius=max(0, radius - t), fill=0
                    )
            else:
                draw.rectangle((0, 0, w - 1, h - 1), fill=255)
                if t * 2 < min(w, h):
                    draw.rectangle((t, t, w - 1 - t, h - 1 - t), fill=0)
        return _Mask(img, (0, img.height), white)

    @staticmethod
    def ellipse(w: int, h: int, t: int) -> Image.Image:
        img = new_mask(w, h)
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, w - 1, h - 1), fill=255)
        if t * 2 < min(w, h):
            draw.ellipse((t, t, w - 1 - t, h - 1 - t), fill=0)
        return img

    def field_graphic(self, command: Command) -> _Mask | None:
        args = command.args(4)
        if len(args) < 5:
            self.warn("Invalid ^GF command")
            return None
        fmt = (args[0] or "A").upper()
        if fmt not in ("A", "B"):
            self.warn(f"^GF format {fmt} is not supported in previews (use ASCII hex)")
            return None
        total, bpr = _int(args[2], _int(args[1], 0)), _int(args[3], 0)
        if total <= 0 or bpr <= 0:
            self.warn("Invalid ^GF size")
            return None
        if fmt == "B":
            if not total <= MAX_GRAPHIC_BYTES:
                raise GraphicError(f"Graphic size must be between 1 and {MAX_GRAPHIC_BYTES} bytes")
            # Binary data: one byte per character, kept as sent (not stripped).
            raw = command.params.split(command.delimiter, 4)[4]
            data = raw.encode("latin-1", "replace")[:total].ljust(total, b"\0")
        else:
            data = decode_graphic_data(args[4], total=total, bytes_per_row=bpr)
        check_size(bpr * 8, total // bpr)
        bitmap = Bitmap(bpr * 8, total // bpr, bpr, data)
        img = bitmap.to_mask()
        return _Mask(img, (0, img.height))


# Commands whose effect carries over to the following label formats.
PERSISTENT = {"PW", "LL", "LH", "LS", "PO", "PM", "LR", "CI", "FW", "CF", "BY"}
# Commands that put something on the label; formats without any only configure the printer.
PRINTING = {"FD", "FV", "SN", "GB", "GC", "GE", "GD", "GF", "XG", "IM", "IL"}


_FIELD_NUMBER = re.compile(r"\s*([0-9]+)")


def _field_number(command: Command) -> str | None:
    """`^FN1` and the prompt form `^FN1"Name"` both refer to field 1."""
    match = _FIELD_NUMBER.match(command.params)
    return match.group(1) if match else None


def _recall_format(
    commands: list[Command], stored: dict[str, list[Command]], warn, limit: int
) -> list[Command]:
    """Expand ^XF: merge the caller's ^FNn data fields into the stored format's ^FNn fields.

    Everything the caller puts between ^FNn and ^FS (e.g. ^FH and ^FD) replaces the stored
    ^FNn command. Recalls that would make the format longer than `limit` are left out.
    """
    values: dict[str, list[Command]] = {}
    caller: list[Command] = []
    number: str | None = None
    for command in commands:
        if command.code == "FN":
            number = _field_number(command)
            if number is not None:
                values[number] = []
        elif number is not None and command.code == "FS":
            number = None
        elif number is not None:
            values[number].append(command)
        else:
            caller.append(command)
    expanded: list[Command] = []
    for command in caller:
        if command.code != "XF":
            expanded.append(command)
            continue
        name = _object_name(command.params, ".ZPL")
        body = stored.get(name)
        if body is None:
            warn(f"Stored format {name} not found (it must be sent with ^DF in the same data)")
            continue
        if len(expanded) + len(body) > limit:
            warn(f"Stored format {name} is recalled too often; the extra recalls are not shown")
            continue
        for stored_command in body:
            if stored_command.code == "FN":
                expanded.extend(values.get(_field_number(stored_command) or "", []))
            elif stored_command.code != "FA":
                expanded.append(stored_command)
    return expanded


def render_zpl(
    zpl: str,
    *,
    dpi: int = 203,
    width: int | None = None,
    height: int | None = None,
    index: int = 0,
) -> RenderResult:
    """Render one label (`index`) of the ZPL to a PNG image.

    Formats that only change settings (e.g. the setup block ZebraDesigner puts first) or that
    store a format (^DF) or an image without printing it (^IS...,N) are not counted as labels,
    but their persistent settings such as ^PW or ^LH still apply.
    """
    renderer = _Renderer(dpi, width, height)
    formats = renderer.split_formats(tokenize(zpl))
    stored: dict[str, list[Command]] = {}
    # Persistent commands seen so far, shared by all labels; each label records how many of
    # them precede it (copying the list per label would be quadratic).
    prelude: list[Command] = []
    labels: list[tuple[int, list[Command]]] = []
    every_format: list[tuple[int, list[Command]]] = []
    recalled = 0
    for fmt in formats:
        define = next((i for i, c in enumerate(fmt) if c.code == "DF"), None)
        if define is not None:
            stored[_object_name(fmt[define].params, ".ZPL")] = fmt[define + 1 :]
            continue
        if any(c.code == "XF" for c in fmt):
            fmt = _recall_format(fmt, stored, renderer.warn, MAX_RECALLED_COMMANDS - recalled)
            recalled += len(fmt)
        every_format.append((len(prelude), fmt))
        save = next((c for c in fmt if c.code == "IS"), None)
        printed = any(c.code in PRINTING for c in fmt)
        if save is not None:
            # ^IS stores the label as formatted; ^PM/^PO apply when it is printed later.
            image = renderer.compose(prelude + fmt).copy()
            name = _object_name(save.params, ".GRF")
            if renderer.reserve("IS", name, image.width * image.height):
                renderer.images[name] = image
            printed = printed and (_arg(save.args(), 1) or "Y").upper() != "N"
        if printed:
            labels.append((len(prelude), fmt))
        prelude.extend(c for c in fmt if c.code in PERSISTENT)
    if not labels:
        # Nothing prints: show the (empty) formats so their size is still visible.
        labels = every_format or ([(len(prelude), [])] if formats else [])
    if not formats:
        renderer.warn("No label format (^XA ... ^XZ) found")
        image = Image.new("L", (renderer.default_width, renderer.default_height), 255)
    else:
        if not 0 <= index < len(labels):
            raise RenderError(f"Label index {index} out of range (found {len(labels)})")
        preceding, fmt = labels[index]
        image = renderer.render(prelude[:preceding] + fmt)
    buf = io.BytesIO()
    image.convert("1").save(buf, "PNG", optimize=True)
    return RenderResult(
        buf.getvalue(),
        image.width,
        image.height,
        len(labels),
        renderer.warnings,
        renderer.placed if formats else [],
    )


class RenderCache:
    """Small in-process LRU cache of rendered previews."""

    def __init__(self, size: int = 256) -> None:
        self.size = size
        self._items: OrderedDict[str, RenderResult] = OrderedDict()
        # Previews are rendered from several threadpool workers at once.
        self._lock = threading.Lock()

    def render(self, zpl: str, **kwargs: int | None) -> RenderResult:
        key = hashlib.sha256(f"{zpl}|{sorted(kwargs.items())}".encode()).hexdigest()
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return cached
        # Render outside the lock; a concurrent duplicate render is harmless.
        result = render_zpl(zpl, **kwargs)  # type: ignore[arg-type]
        with self._lock:
            self._items[key] = result
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return result


render_cache = RenderCache()
