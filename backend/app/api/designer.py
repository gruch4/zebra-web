import base64
import io
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.api.deps import SettingsDep
from app.render.renderer import render_cache
from app.schemas import GraphicOut
from app.zpl.generator import Design, Element, design_variables, element_to_zpl, generate_zpl
from app.zpl.graphics import encode_gfa, image_to_bitmap
from app.zpl.templating import substitute

router = APIRouter(tags=["designer"])

MAX_GRAPHIC_DOTS = 2400
PREVIEW_CANVAS_DOTS = 2400
# Elements are previewed this far from the edges: barcode text can stick out before ^FO.
PREVIEW_MARGIN = 200
# Uploaded images are decoded at full size before scaling, so their pixel count is capped.
MAX_SOURCE_PIXELS = 25_000_000


class DesignZplOut(BaseModel):
    zpl: str
    variables: list[str]


@router.post("/designer/zpl", response_model=DesignZplOut)
async def design_to_zpl(design: Design):
    return DesignZplOut(zpl=generate_zpl(design), variables=design_variables(design))


class DesignPreviewRequest(BaseModel):
    design: Design
    values: dict[str, str] = {}


@router.post("/designer/preview-zpl", response_model=DesignZplOut)
async def design_preview_zpl(body: DesignPreviewRequest):
    """ZPL as printed with the given values (e.g. variable defaults); placeholders without a
    value are kept. Unlike filling in the template, this encodes the data like printing."""
    zpl = generate_zpl(body.design, body.values)
    return DesignZplOut(zpl=zpl, variables=design_variables(body.design))


class ElementPreviewRequest(BaseModel):
    element: Element
    dpi: int = Field(203, ge=100, le=600)
    values: dict[str, str] = {}


class ElementPreviewOut(BaseModel):
    image: str | None  # transparent PNG data URL, None when nothing is drawn
    width: int
    height: int
    offset_x: int
    offset_y: int
    # The field as the printer places it at ^FO, which can be larger than the ink.
    field_width: int
    field_height: int
    warnings: list[str]


@router.post("/designer/element-preview", response_model=ElementPreviewOut)
def element_preview(body: ElementPreviewRequest):
    """Render one element at the origin, rotated as printed, cropped to its ink."""
    margin = PREVIEW_MARGIN
    element = body.element.model_copy(update={"x": margin, "y": margin})
    zpl = (
        "^XA^CI28"
        + element_to_zpl(element, lambda text: substitute(text, body.values), dpi=body.dpi)
        + "^XZ"
    )
    size = PREVIEW_CANVAS_DOTS + margin
    result = render_cache.render(zpl, dpi=body.dpi, width=size, height=size, index=0)
    # The union of the placed fields (multi-line text places one field per line), measured
    # from the element's origin.
    field_width = max((x + w - margin for x, _, w, _ in result.fields), default=0)
    field_height = max((y + h - margin for _, y, _, h in result.fields), default=0)
    image = Image.open(io.BytesIO(result.png)).convert("L")
    ink = ImageOps.invert(image)
    bbox = ink.getbbox()
    if bbox is None:
        return ElementPreviewOut(
            image=None,
            width=0,
            height=0,
            offset_x=0,
            offset_y=0,
            field_width=field_width,
            field_height=field_height,
            warnings=result.warnings,
        )
    alpha = ink.crop(bbox)
    rgba = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    rgba.putalpha(alpha)
    buf = io.BytesIO()
    rgba.save(buf, "PNG", optimize=True)
    return ElementPreviewOut(
        image="data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        width=alpha.width,
        height=alpha.height,
        offset_x=bbox[0] - margin,
        offset_y=bbox[1] - margin,
        field_width=field_width,
        field_height=field_height,
        warnings=result.warnings,
    )


@router.post("/graphics/convert", response_model=GraphicOut)
def convert_graphic(
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    width: Annotated[int | None, Form(ge=1, le=MAX_GRAPHIC_DOTS)] = None,
    height: Annotated[int | None, Form(ge=1, le=MAX_GRAPHIC_DOTS)] = None,
    threshold: Annotated[int, Form(ge=1, le=254)] = 128,
    dither: Annotated[bool, Form()] = False,
    invert: Annotated[bool, Form()] = False,
):
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image is too large")
    try:
        image = Image.open(io.BytesIO(content))  # reads only the header
        if image.width * image.height > MAX_SOURCE_PIXELS:
            raise Image.DecompressionBombError(f"{image.width}x{image.height} pixels")
        image.load()
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Image has too many pixels (at most {MAX_SOURCE_PIXELS // 1_000_000} megapixels)",
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Unsupported image file"
        ) from exc
    if not width and not height and max(image.size) > MAX_GRAPHIC_DOTS:
        if image.width >= image.height:
            width = MAX_GRAPHIC_DOTS
        else:
            height = MAX_GRAPHIC_DOTS
    bitmap = image_to_bitmap(
        image, width=width, height=height, threshold=threshold, dither=dither, invert=invert
    )
    return GraphicOut(
        width=bitmap.width,
        height=bitmap.height,
        bytes_per_row=bitmap.bytes_per_row,
        data=base64.b64encode(bitmap.data).decode(),
        zpl=encode_gfa(bitmap),
        preview="data:image/png;base64," + base64.b64encode(bitmap.to_png()).decode(),
    )
