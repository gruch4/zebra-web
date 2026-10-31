"""Designer model (JSON) and its translation to ZPL."""

import base64
import binascii
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from PIL import Image
from pydantic import BaseModel, Field, model_validator

from app.render.barcodes import code128_field
from app.render.fonts import resolve_font
from app.zpl.graphics import MAX_GRAPHIC_BYTES, Bitmap, encode_gfa, split_bitmap
from app.zpl.templating import VAR_RE, extract_variables, substitute

Rotation = Literal[0, 90, 180, 270]
_ROTATION = {0: "N", 90: "R", 180: "I", 270: "B"}


def _clamped(data: Any, limits: Mapping[str, tuple[int, int]]) -> Any:
    """Bring numbers into the range the printer accepts.

    Designs saved before these limits were enforced may hold smaller or larger values; they
    are moved to the nearest value the printer takes instead of failing to load.
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    for name, (low, high) in limits.items():
        value = data.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            data[name] = min(high, max(low, value))
    return data


class _Element(BaseModel):
    id: str
    name: str = ""
    x: int = Field(0, ge=0)
    y: int = Field(0, ge=0)
    rotation: Rotation = 0


class TextElement(_Element):
    type: Literal["text"] = "text"
    text: str = "Text"
    font: str = Field("0", pattern=r"^[0-9A-Z]$")
    font_height: int = Field(30, ge=1, le=32000)
    font_width: int = Field(0, ge=0, le=32000)
    block_width: int | None = Field(None, ge=1, le=32000)
    block_lines: int = Field(1, ge=1, le=9999)
    line_spacing: int = Field(0, ge=-9999, le=9999)
    align: Literal["L", "C", "R", "J"] = "L"
    reverse: bool = False

    @model_validator(mode="before")
    @classmethod
    def _scalable_size(cls, data: Any) -> Any:
        # ^A: scalable fonts take a height and width of 10 to 32000 dots (p.12).
        if not isinstance(data, dict) or data.get("font", "0") != "0":
            return data
        data = _clamped(data, {"font_height": (10, 32000)})
        width = data.get("font_width")
        if isinstance(width, int | float) and 0 < width < 10:
            data["font_width"] = 10
        return data


class BarcodeElement(_Element):
    type: Literal["barcode"] = "barcode"
    symbology: Literal["code128", "code39", "ean13", "ean8", "upca", "itf"] = "code128"
    data: str = "123456"
    height: int = Field(80, ge=1, le=32000)
    module_width: int = Field(2, ge=1, le=10)
    ratio: float = Field(3.0, ge=2.0, le=3.0)
    show_text: bool = True
    text_above: bool = False
    check_digit: bool = False


class QrCodeElement(_Element):
    type: Literal["qrcode"] = "qrcode"
    rotation: Literal[0] = 0  # ^BQ has a fixed orientation
    data: str = "https://example.com"
    magnification: int = Field(4, ge=1, le=10)
    error_correction: Literal["L", "M", "Q", "H"] = "M"

    @model_validator(mode="before")
    @classmethod
    def _fixed_orientation(cls, data: Any) -> Any:
        return {**data, "rotation": 0} if isinstance(data, dict) else data


class DataMatrixElement(_Element):
    type: Literal["datamatrix"] = "datamatrix"
    data: str = "DATA"
    module_size: int = Field(6, ge=1, le=100)


class Pdf417Element(_Element):
    type: Literal["pdf417"] = "pdf417"
    data: str = "PDF417"
    module_width: int = Field(2, ge=2, le=10)  # ^BY with PDF417: 2 to 10 (p.34)
    row_height: int = Field(6, ge=1, le=255)  # in dots (T10), whatever the module width
    security: int = Field(2, ge=0, le=8)
    columns: int = Field(4, ge=1, le=30)

    @model_validator(mode="before")
    @classmethod
    def _module_width(cls, data: Any) -> Any:
        return _clamped(data, {"module_width": (2, 10)})


class BoxElement(_Element):
    type: Literal["box"] = "box"
    width: int = Field(200, ge=1, le=32000)
    height: int = Field(100, ge=1, le=32000)
    thickness: int = Field(3, ge=1, le=32000)
    color: Literal["B", "W"] = "B"
    rounding: int = Field(0, ge=0, le=8)


class LineElement(_Element):
    type: Literal["line"] = "line"
    width: int = Field(200, ge=1, le=32000)
    height: int = Field(3, ge=1, le=32000)
    thickness: int = Field(3, ge=1, le=32000)
    diagonal: Literal["none", "down", "up"] = "none"
    color: Literal["B", "W"] = "B"

    @model_validator(mode="before")
    @classmethod
    def _diagonal_size(cls, data: Any) -> Any:
        # ^GD takes a width and height of at least 3 dots (p.158).
        if isinstance(data, dict) and data.get("diagonal", "none") != "none":
            return _clamped(data, {"width": (3, 32000), "height": (3, 32000)})
        return data


class EllipseElement(_Element):
    type: Literal["ellipse"] = "ellipse"
    # ^GE: width and height 3 to 4095, thickness 2 to 4095 (p.159)
    width: int = Field(100, ge=3, le=4095)
    height: int = Field(100, ge=3, le=4095)
    thickness: int = Field(3, ge=2, le=4095)
    color: Literal["B", "W"] = "B"

    @model_validator(mode="before")
    @classmethod
    def _size(cls, data: Any) -> Any:
        return _clamped(data, {"width": (3, 4095), "height": (3, 4095), "thickness": (2, 4095)})


class ImageElement(_Element):
    type: Literal["image"] = "image"
    width: int = Field(ge=1, le=32000)
    height: int = Field(ge=1, le=32000)
    bytes_per_row: int = Field(ge=1)
    data: str = Field(description="Base64 of the packed 1-bit bitmap (1 = black)")

    @model_validator(mode="after")
    def _check_bitmap(self) -> ImageElement:
        if self.bytes_per_row * 8 < self.width:
            raise ValueError("bytes_per_row is too small for the image width")
        if self.bytes_per_row * self.height > MAX_GRAPHIC_BYTES:
            raise ValueError(f"image data is larger than {MAX_GRAPHIC_BYTES} bytes")
        try:
            raw = base64.b64decode(self.data, validate=True)
        except binascii.Error as exc:
            raise ValueError("image data is not valid base64") from exc
        if len(raw) != self.bytes_per_row * self.height:
            raise ValueError("image data size does not match bytes_per_row x height")
        return self


Element = Annotated[
    TextElement
    | BarcodeElement
    | QrCodeElement
    | DataMatrixElement
    | Pdf417Element
    | BoxElement
    | LineElement
    | EllipseElement
    | ImageElement,
    Field(discriminator="type"),
]


class Design(BaseModel):
    width_mm: float = Field(100, gt=0, le=1000)
    height_mm: float = Field(50, gt=0, le=4000)
    dpi: int = Field(203, ge=100, le=600)
    elements: list[Element] = Field(default_factory=list)

    @property
    def width_dots(self) -> int:
        return mm_to_dots(self.width_mm, self.dpi)

    @property
    def height_dots(self) -> int:
        return mm_to_dots(self.height_mm, self.dpi)


def dots_per_mm(dpi: int) -> int:
    """Printheads have 6, 8, 12 or 24 dots per mm; "300 dpi" is really 12 dots/mm (304.8 dpi)."""
    return max(1, round(dpi / 25.4))


def mm_to_dots(mm: float, dpi: int) -> int:
    return round(mm * dots_per_mm(dpi))


def design_texts(design: Design) -> list[str]:
    """All template-capable strings in the design."""
    texts = []
    for element in design.elements:
        if isinstance(element, TextElement):
            texts.append(element.text)
        elif hasattr(element, "data") and not isinstance(element, ImageElement):
            texts.append(element.data)
    return texts


def design_variables(design: Design) -> list[str]:
    return extract_variables(*design_texts(design))


def _escape_field_hex(text: str) -> str:
    return text.replace("_", "_5F").replace("^", "_5E").replace("~", "_7E")


def _field_data(value: str, *, template: bool = False) -> str:
    """Return `^FD...` with `^FH` escaping when the value contains control characters.

    In a template the `{{name}}` placeholders are kept as they are, so they still match when
    it is filled in (`substitute_zpl` escapes the values it puts into a ^FH field).
    """
    if "^" not in value and "~" not in value:
        return f"^FD{value}"
    escaped, end = [], 0
    for match in VAR_RE.finditer(value) if template else ():
        escaped += [_escape_field_hex(value[end : match.start()]), match.group(0)]
        end = match.end()
    escaped.append(_escape_field_hex(value[end:]))
    return f"^FH_^FD{''.join(escaped)}"


_DATAMATRIX_ESCAPE = "`"
# A QR code prints 2 dots less than the ^BY height below ^FO, and that height stays set from
# earlier bar codes and labels (docs/print-tests T11, T17): QR codes name the smallest one,
# 10 dots, and start that much higher.
_QR_BAR_HEIGHT = 10
_QR_OFFSET = _QR_BAR_HEIGHT - 2


def _yn(flag: bool) -> str:
    return "Y" if flag else "N"


def _escape_block(text: str) -> str:
    """^FB field data: a backslash starts an escape, and \\& is the line break (p.138)."""
    return text.replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\&")


def _code128_data(value: str) -> str:
    """Code 128 data with explicit subsets, so the printer encodes exactly what is previewed.

    Placeholders of a template cannot be encoded yet; their literal text is only escaped.
    """
    if not VAR_RE.search(value):
        return code128_field(value)
    return value.replace(">", ">0")


def _qr_data(error_correction: str, value: str) -> str:
    """^BQ field data. Automatic input cannot carry bytes 80-9F and E0-FF (p.84), which UTF-8
    uses for every non-ASCII character, so such data goes in manual byte mode."""
    if value.isascii() or VAR_RE.search(value):
        return f"{error_correction}A,{value}"
    return f"{error_correction}M,B{len(value.encode()):04d}{value}"


def _rotate_bitmap(element: ImageElement) -> Bitmap:
    bitmap = Bitmap(
        element.width, element.height, element.bytes_per_row, base64.b64decode(element.data)
    )
    if element.rotation == 0:
        return bitmap
    transpose = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }[element.rotation]
    return Bitmap.from_mask(bitmap.to_mask().transpose(transpose))


def _text_lines(element: TextElement, text: str, o: str, dpi: int, template: bool) -> str:
    """Text with line breaks but no text block: one field per line, stacked like ^FB lines.

    ZPL drops CR/LF in field data, so the lines would otherwise run together.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    font_width = element.font_width or None
    cell = resolve_font(element.font, element.font_height, font_width, dots_per_mm(dpi))
    step = cell.cell_height + element.line_spacing
    width = element.font_width or ""
    fields = []
    last = len(lines) - 1
    for index, line in enumerate(lines):
        # Following lines go "down" in the text's own direction, like a rotated block.
        dx, dy = {
            "N": (0, index * step),
            "R": ((last - index) * step, 0),
            "I": (0, (last - index) * step),
            "B": (index * step, 0),
        }[o]
        parts = [
            f"^FO{element.x + dx},{element.y + dy}",
            f"^A{element.font}{o},{element.font_height},{width}",
        ]
        if element.reverse:
            parts.append("^FR")
        parts.append(_field_data(line, template=template))
        fields.append("".join(parts) + "^FS")
    return "".join(fields)


def element_to_zpl(
    element: Element, render: _Text, *, template: bool = False, dpi: int = 203
) -> str:
    """ZPL of one element; with `template` its placeholders are kept for filling in."""
    o = _ROTATION[element.rotation]
    origin = f"^FO{element.x},{element.y}"
    match element:
        case TextElement():
            text = render(element.text)
            if not element.block_width and "\n" in text:
                return _text_lines(element, text, o, dpi, template)
            width = element.font_width or ""
            parts = [origin, f"^A{element.font}{o},{element.font_height},{width}"]
            if element.block_width:
                parts.append(
                    f"^FB{element.block_width},{element.block_lines},"
                    f"{element.line_spacing},{element.align},0"
                )
                text = _escape_block(text)
            if element.reverse:
                parts.append("^FR")
            parts.append(_field_data(text, template=template))
        case BarcodeElement():
            interp = _yn(element.show_text)
            above = _yn(element.text_above)
            ratio = f"{element.ratio:.1f}"
            data = render(element.data)
            parts = [origin, f"^BY{element.module_width},{ratio},{element.height}"]
            # EAN and UPC have no check digit option: the printer always adds it.
            symbology = {
                "code128": f"^BC{o},{element.height},{interp},{above},{_yn(element.check_digit)}",
                "code39": f"^B3{o},{_yn(element.check_digit)},{element.height},{interp},{above}",
                "ean13": f"^BE{o},{element.height},{interp},{above}",
                "ean8": f"^B8{o},{element.height},{interp},{above}",
                "upca": f"^BU{o},{element.height},{interp},{above},Y",
                "itf": f"^B2{o},{element.height},{interp},{above},{_yn(element.check_digit)}",
            }[element.symbology]
            if element.symbology == "code128":
                data = _code128_data(data)
            parts += [symbology, _field_data(data, template=template)]
        case QrCodeElement():
            data = render(element.data)
            parts = [
                f"^FO{element.x},{max(0, element.y - _QR_OFFSET)}",
                f"^BY2,3,{_QR_BAR_HEIGHT}",
                f"^BQN,2,{element.magnification}",
            ]
            parts.append(_field_data(_qr_data(element.error_correction, data), template=template))
        case DataMatrixElement():
            # Quality 200 data uses an escape character (~, or _ on some firmware), so one is
            # named explicitly and doubled where it is meant literally (p.102). It is not ~:
            # that is ZPL's control command prefix and cannot be a parameter.
            data = render(element.data).replace(_DATAMATRIX_ESCAPE, _DATAMATRIX_ESCAPE * 2)
            parts = [
                origin,
                f"^BX{o},{element.module_size},200,0,0,6,{_DATAMATRIX_ESCAPE}",
                _field_data(data, template=template),
            ]
        case Pdf417Element():
            parts = [
                origin,
                f"^BY{element.module_width}",
                f"^B7{o},{element.row_height},{element.security},{element.columns},,N",
                _field_data(_escape_block(render(element.data)), template=template),
            ]
        case BoxElement():
            w, h = element.width, element.height
            if element.rotation in (90, 270):
                w, h = h, w
            gb = f"^GB{w},{h},{element.thickness},{element.color},{element.rounding}"
            parts = [origin, gb]
        case LineElement():
            w, h = element.width, element.height
            lean = "L" if element.diagonal == "down" else "R"
            if element.rotation in (90, 270):
                w, h = h, w
                lean = "R" if lean == "L" else "L"  # a quarter turn makes "\" a "/"
            if element.diagonal == "none":
                parts = [origin, f"^GB{w},{h},{min(element.thickness, w, h)},{element.color},0"]
            else:
                parts = [origin, f"^GD{w},{h},{element.thickness},{element.color},{lean}"]
        case EllipseElement():
            w, h = element.width, element.height
            if element.rotation in (90, 270):
                w, h = h, w
            parts = [origin, f"^GE{w},{h},{element.thickness},{element.color}"]
        case ImageElement():
            # ^GF byte counts stop at 99,999 (p.160): larger images go in horizontal strips.
            strips = split_bitmap(_rotate_bitmap(element))
            return "".join(
                f"^FO{element.x},{element.y + offset}{encode_gfa(strip)}^FS"
                for offset, strip in strips
            )
    return "".join(parts) + "^FS"


class _Text:
    def __init__(self, values: Mapping[str, str] | None, now: datetime | None) -> None:
        self.values = values
        self.now = now

    def __call__(self, text: str) -> str:
        if self.values is None:
            return text
        return substitute(text, self.values, now=self.now)


def generate_zpl(
    design: Design,
    values: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Generate ZPL. With `values=None` placeholders are kept as `{{name}}`."""
    render = _Text(values, now)
    lines = [
        "^XA",
        "^CI28",
        f"^PW{design.width_dots}",
        f"^LL{design.height_dots}",
        "^LH0,0",
        # Reverse and mirror printing stay on in the printer after a job that set them.
        "^LRN^PMN",
    ]
    template = values is None
    lines += [
        element_to_zpl(element, render, template=template, dpi=design.dpi)
        for element in design.elements
    ]
    lines.append("^XZ")
    return "\n".join(lines) + "\n"
