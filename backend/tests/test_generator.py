import base64
import io
from datetime import datetime

import pytest
from PIL import Image, ImageOps
from pydantic import ValidationError

from app.render.lexer import tokenize
from app.render.renderer import render_zpl
from app.zpl.generator import (
    BarcodeElement,
    BoxElement,
    DataMatrixElement,
    Design,
    EllipseElement,
    ImageElement,
    LineElement,
    Pdf417Element,
    QrCodeElement,
    TextElement,
    design_variables,
    element_to_zpl,
    generate_zpl,
)
from app.zpl.templating import substitute_zpl


def zpl_of(element) -> str:
    return element_to_zpl(element, lambda text: text)


def test_text_element():
    element = TextElement(id="t", x=10, y=20, text="Hello", font_height=40, font_width=30)
    assert zpl_of(element) == "^FO10,20^A0N,40,30^FDHello^FS"


def test_text_block_rotation_reverse_and_escaping():
    element = TextElement(
        id="t",
        text="a^b_c",
        rotation=90,
        block_width=300,
        block_lines=2,
        align="C",
        reverse=True,
    )
    assert zpl_of(element) == "^FO0,0^A0R,30,^FB300,2,0,C,0^FR^FH_^FDa_5Eb_5Fc^FS"


def test_text_block_escapes_backslashes_and_line_breaks():
    element = TextElement(id="t", text="C:\\new\nline", block_width=300, block_lines=2)
    assert zpl_of(element).endswith("^FDC:\\\\new\\&line^FS")


def test_text_with_line_breaks_but_no_block_prints_one_field_per_line():
    element = TextElement(id="t", x=10, y=20, text="one\ntwo", font_height=30)
    assert zpl_of(element) == "^FO10,20^A0N,30,^FDone^FS^FO10,50^A0N,30,^FDtwo^FS"
    # Rotated 90 degrees the following line is to the left, as in a rotated text block.
    rotated = TextElement(id="t", x=10, y=20, text="one\ntwo", font_height=30, rotation=90)
    assert zpl_of(rotated) == "^FO40,20^A0R,30,^FDone^FS^FO10,20^A0R,30,^FDtwo^FS"
    # Bitmap fonts step by their magnified cell height (font D is 18 dots: 30 prints at 36).
    bitmap = TextElement(id="t", text="a\nb", font="D", font_height=30)
    assert "^FO0,36^" in zpl_of(bitmap)


@pytest.mark.parametrize(
    ("symbology", "expected"),
    [
        ("code128", "^BCN,80,Y,N,N"),
        ("code39", "^B3N,N,80,Y,N"),
        ("ean13", "^BEN,80,Y,N"),
        ("ean8", "^B8N,80,Y,N"),
        ("upca", "^BUN,80,Y,N,Y"),
        ("itf", "^B2N,80,Y,N,N"),
    ],
)
def test_barcode_symbologies(symbology, expected):
    element = BarcodeElement(id="b", x=1, y=2, symbology=symbology, data="123")
    data = ">:123" if symbology == "code128" else "123"
    assert zpl_of(element) == f"^FO1,2^BY2,3.0,80{expected}^FD{data}^FS"


@pytest.mark.parametrize(
    ("data", "field"),
    [
        # The printer would use subset B for all of these without explicit codes (p.49).
        ("123456", ">;123456"),
        ("ABC123456", ">:ABC>5123456"),
        ("12345", ">:1>52345"),
        ("A>B", ">:A>0B"),
        ("SKU-{{n}}", "SKU-{{n}}"),  # placeholders are encoded once they are filled in
        ("a>{{n}}", "a>0{{n}}"),
    ],
)
def test_code128_data_has_explicit_subsets(data, field):
    assert zpl_of(BarcodeElement(id="b", data=data)).endswith(f"^FD{field}^FS")


def test_code128_previews_exactly_as_encoded():
    zpl = "^XA" + zpl_of(BarcodeElement(id="b", data="123456", show_text=False)) + "^XZ"
    bbox = Image.open(io.BytesIO(render_zpl(zpl).png)).convert("L")
    width = ImageOps.invert(bbox).getbbox()
    # start C, 3 pairs, check, stop = 68 modules of 2 dots
    assert width is not None and width[2] - width[0] == 136


def test_two_dimensional_codes():
    assert zpl_of(QrCodeElement(id="q", data="x", magnification=5, error_correction="H")) == (
        "^FO0,0^BY2,3,10^BQN,2,5^FDHA,x^FS"
    )
    assert zpl_of(DataMatrixElement(id="d", data="x", module_size=4)) == (
        "^FO0,0^BXN,4,200,0,0,6,`^FDx^FS"
    )
    assert zpl_of(Pdf417Element(id="p", data="x")) == "^FO0,0^BY2^B7N,6,2,4,,N^FDx^FS"


def test_two_dimensional_data_escaping():
    # QR automatic input cannot carry UTF-8 bytes (p.84): non-ASCII data uses byte mode.
    assert zpl_of(QrCodeElement(id="q", data="Zażółć")).endswith("^FDMM,B0010Zażółć^FS")
    # Data Matrix: the escape character is named and doubled where it is literal (p.102).
    # ~ is ZPL's control prefix, so the escape character is a backtick; ~ is then ordinary.
    assert zpl_of(DataMatrixElement(id="d", data="A~B_1`")).endswith(
        "^BXN,6,200,0,0,6,`^FH_^FDA_7EB_5F1``^FS"
    )
    tokens = tokenize(zpl_of(DataMatrixElement(id="d", data="x")))
    assert tokens[1].args()[6] == "`"
    # PDF417 field data: \& is a line break and \\ a backslash (p.34).
    assert zpl_of(Pdf417Element(id="p", data="C:\\x\nB")).endswith("^FDC:\\\\x\\&B^FS")


def test_two_dimensional_data_previews_as_entered():
    for element in (
        QrCodeElement(id="q", data="Zażółć gęślą"),
        DataMatrixElement(id="d", data="A~B`C"),
    ):
        result = render_zpl("^XA^CI28" + zpl_of(element) + "^XZ")
        assert result.warnings == []


def test_shapes():
    assert zpl_of(BoxElement(id="b", width=100, height=50, thickness=2, rounding=3)) == (
        "^FO0,0^GB100,50,2,B,3^FS"
    )
    assert zpl_of(BoxElement(id="b", width=100, height=50, rotation=90)) == (
        "^FO0,0^GB50,100,3,B,0^FS"
    )
    assert zpl_of(LineElement(id="l", width=100, height=3, thickness=3)) == (
        "^FO0,0^GB100,3,3,B,0^FS"
    )
    assert zpl_of(LineElement(id="l", width=100, height=60, diagonal="up")) == (
        "^FO0,0^GD100,60,3,B,R^FS"
    )
    # A quarter turn makes "/" a "\" (and the other way round); half a turn keeps it.
    assert zpl_of(LineElement(id="l", width=100, height=60, diagonal="up", rotation=90)) == (
        "^FO0,0^GD60,100,3,B,L^FS"
    )
    assert zpl_of(LineElement(id="l", width=100, height=60, diagonal="down", rotation=270)) == (
        "^FO0,0^GD60,100,3,B,R^FS"
    )
    assert zpl_of(LineElement(id="l", width=100, height=60, diagonal="up", rotation=180)) == (
        "^FO0,0^GD100,60,3,B,R^FS"
    )
    assert zpl_of(EllipseElement(id="e", width=80, height=40, color="W")) == (
        "^FO0,0^GE80,40,3,W^FS"
    )


def test_image_element_rotation():
    data = base64.b64encode(bytes([0b11110000, 0, 0, 0])).decode()  # 8x4, top-left 4 dots
    element = ImageElement(id="i", width=8, height=4, bytes_per_row=1, data=data, rotation=90)
    zpl = zpl_of(element)
    assert zpl.startswith("^FO0,0^GFA,8,8,1,")  # rotated: 4 wide (1 byte/row), 8 high


def test_generate_zpl_with_and_without_values():
    design = Design(
        width_mm=50,
        height_mm=25,
        dpi=203,
        elements=[
            TextElement(id="t", text="Name: {{name}} {{date}}"),
            BarcodeElement(id="b", data="{{sku}}"),
        ],
    )
    assert design_variables(design) == ["name", "sku"]
    template = generate_zpl(design)
    assert template.startswith("^XA\n^CI28\n^PW400\n^LL200\n^LH0,0\n^LRN^PMN\n")
    assert "{{name}}" in template
    filled = generate_zpl(design, {"name": "A_B", "sku": "42"}, now=datetime(2026, 1, 2))
    assert "^FDName: A_B 2026-01-02^FS" in filled
    assert "^FD>:42^FS" in filled
    assert filled.endswith("^XZ\n")


def test_template_keeps_placeholders_in_escaped_fields():
    # A field with ^ or ~ is escaped with ^FH_, but its placeholders must still match their
    # variables when the template is filled in, which escapes the values instead.
    design = Design(elements=[TextElement(id="t", text="A ~ {{unit_price}}")])
    template = generate_zpl(design)
    assert "^FH_^FDA _7E {{unit_price}}^FS" in template
    filled = substitute_zpl(template, {"unit_price": "1_000"})
    assert "^FH_^FDA _7E 1_5F000^FS" in filled
    assert filled == generate_zpl(design, {"unit_price": "1_000"})
    # Outside a template (e.g. an element preview) a placeholder is shown as it is written.
    assert zpl_of(TextElement(id="t", text="~{{a_b}}")) == "^FO0,0^A0N,30,^FH_^FD_7E{{a_5Fb}}^FS"


def test_design_validation():
    with pytest.raises(ValidationError):
        Design.model_validate({"elements": [{"type": "unknown", "id": "x"}]})


@pytest.mark.parametrize(
    ("element", "fields", "expected"),
    [
        # ^A scalable fonts: 10 to 32000 dots; bitmap fonts may be smaller.
        (TextElement, {"font_height": 9}, {"font_height": 10}),
        (TextElement, {"font_width": 5}, {"font_width": 10}),
        (TextElement, {"font": "A", "font_height": 9}, {"font_height": 9}),
        # ^GE: 3 to 4095, thickness at least 2
        (EllipseElement, {"width": 5000, "thickness": 1}, {"width": 4095, "thickness": 2}),
        # ^GD: at least 3; a straight line may be thinner
        (LineElement, {"diagonal": "up", "height": 2}, {"height": 3}),
        (LineElement, {"height": 2}, {"height": 2}),
        (Pdf417Element, {"module_width": 1}, {"module_width": 2}),  # ^BY for PDF417: 2 to 10
        (QrCodeElement, {"rotation": 90}, {"rotation": 0}),  # ^BQ has a fixed orientation
    ],
)
def test_values_outside_the_printer_limits_are_clamped(element, fields, expected):
    """Designs saved before the limits were enforced still load (and print)."""
    loaded = element.model_validate({"id": "x", **fields})
    assert loaded.model_dump(include=set(expected)) == expected


def test_saved_design_with_old_values_still_generates():
    design = Design.model_validate(
        {
            "elements": [
                {"type": "ellipse", "id": "e", "thickness": 1},
                {"type": "pdf417", "id": "p", "module_width": 1},
                {"type": "qrcode", "id": "q", "rotation": 180},
            ]
        }
    )
    zpl = generate_zpl(design)
    assert "^GE100,100,2,B" in zpl and "^BY2^B7" in zpl


def test_large_images_are_split_into_graphic_field_strips():
    # 800 x 1200 dots is 120,000 bytes, more than ^GF's 99,999 (p.160).
    data = base64.b64encode(bytes(100 * 1200)).decode()
    element = ImageElement(id="i", x=5, y=7, width=800, height=1200, bytes_per_row=100, data=data)
    zpl = zpl_of(element)
    assert zpl.startswith("^FO5,7^GFA,99900,99900,100,")
    assert "^FO5,1006^GFA,20100,20100,100," in zpl


def test_generated_template_resets_reverse_and_mirror_printing():
    assert "^LRN^PMN" in generate_zpl(Design())


def test_generated_design_renders_without_warnings():
    design = Design(
        width_mm=60,
        height_mm=40,
        elements=[
            TextElement(id="t", x=10, y=10, text="Zażółć"),
            BarcodeElement(id="b", x=10, y=60, data="12345"),
            QrCodeElement(id="q", x=300, y=10),
            DataMatrixElement(id="d", x=300, y=200),
            Pdf417Element(id="p", x=10, y=200),
            BoxElement(id="x", x=0, y=0, width=470, height=310),
            LineElement(id="l", x=0, y=150, width=470),
            EllipseElement(id="e", x=200, y=200, width=60, height=40),
        ],
    )
    result = render_zpl(generate_zpl(design), dpi=203)
    assert result.warnings == []
    assert (result.width, result.height) == (design.width_dots, design.height_dots)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"data": "not base64!"}, "base64"),
        ({"data": base64.b64encode(b"x").decode()}, "size"),
        ({"width": 20}, "bytes_per_row"),
    ],
)
def test_image_element_validation(extra, message):
    fields = {"id": "i", "width": 8, "height": 2, "bytes_per_row": 1} | {
        "data": base64.b64encode(b"\xff\x00").decode()
    }
    with pytest.raises(ValidationError, match=message):
        ImageElement(**(fields | extra))


def test_qr_code_prints_where_it_is_designed():
    # The printer puts a QR code 2 dots less than the ^BY height below ^FO, whatever an
    # earlier bar code or label left ^BY at (docs/print-tests T11, T17), so the code names
    # ^BY and starts higher.
    qr = QrCodeElement(id="q", x=40, y=30)
    assert zpl_of(qr).startswith("^FO40,22^BY2,3,10^BQN")
    after_barcode = Design(
        elements=[BarcodeElement(id="b", x=0, y=200, data="12345", height=120), qr]
    )
    img = ImageOps.invert(
        Image.open(io.BytesIO(render_zpl(generate_zpl(after_barcode)).png)).convert("L")
    )
    bbox = img.crop((40, 0, 200, 190)).getbbox()
    assert bbox is not None and bbox[1] == 30
