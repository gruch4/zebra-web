import pytest
from PIL import Image

from app.render import barcodes
from app.render.lexer import decode_field_hex, tokenize
from app.render.renderer import RenderCache, RenderError, render_zpl
from app.zpl.graphics import Bitmap, encode_gfa
from tests.conftest import png_image


def render(zpl: str, **kwargs) -> Image.Image:
    return png_image(render_zpl(zpl, **kwargs).png)


def black(img: Image.Image, x: int, y: int) -> bool:
    return img.getpixel((x, y)) == 0


def ink_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    return img.point(lambda v: 255 - v).getbbox()


def test_tokenize():
    commands = tokenize("^XA\r\n^A0N,30,20^FDa,b^FS~HS^xz")
    assert [(c.prefix, c.code, c.params) for c in commands] == [
        ("^", "XA", ""),
        ("^", "A", "0N,30,20"),
        ("^", "FD", "a,b"),
        ("^", "FS", ""),
        ("~", "HS", ""),
        ("^", "XZ", ""),
    ]


def test_decode_field_hex():
    assert decode_field_hex("_41_5E_c5_82", "_", encoding="utf-8") == "A^ł"
    assert decode_field_hex("a_zz", "_") == "a_zz"


def test_label_size_from_pw_ll_and_defaults():
    result = render_zpl("^XA^PW300^LL200^XZ")
    assert (result.width, result.height) == (300, 200)
    default = render_zpl("^XA^XZ", dpi=203)
    assert (default.width, default.height) == (812, 1218)
    sized = render_zpl("^XA^XZ", width=100, height=50)
    assert (sized.width, sized.height) == (100, 50)


def test_filled_box_and_label_home():
    img = render("^XA^PW100^LL100^LH10,10^FO5,5^GB20,20,20^FS^XZ")
    assert black(img, 20, 20)
    assert not black(img, 12, 12)
    assert ink_bbox(img) == (15, 15, 35, 35)


def test_box_outline_has_white_center():
    img = render("^XA^PW100^LL100^FO0,0^GB50,50,3^FS^XZ")
    assert black(img, 1, 25)
    assert not black(img, 25, 25)


def test_white_box_and_reverse_field():
    img = render(
        "^XA^PW100^LL100^FO0,0^GB60,60,60^FS^FO10,10^GB10,10,10,W^FS^FO40,40^FR^GB40,40,40^FS^XZ"
    )
    assert not black(img, 15, 15)  # white box
    assert not black(img, 50, 50)  # reversed overlap turns white
    assert black(img, 70, 70)  # reversed on white paper turns black


def test_print_orientation_inverted():
    img = render("^XA^PW100^LL100^POI^FO0,0^GB10,10,10^FS^XZ")
    assert ink_bbox(img) == (90, 90, 100, 100)


def test_text_renders_and_rotates():
    normal = ink_bbox(render("^XA^PW400^LL200^FO10,10^A0N,50,50^FDHello^FS^XZ"))
    assert normal is not None
    # Font 0 capitals reach a dot or two above the origin, as printed (T04).
    assert normal[0] >= 10 and normal[1] >= 8 and normal[3] <= 60
    rotated = ink_bbox(render("^XA^PW400^LL400^FO10,10^A0R,50,50^FDHello^FS^XZ"))
    assert rotated is not None
    width, height = rotated[2] - rotated[0], rotated[3] - rotated[1]
    assert height > width  # text runs downwards


def test_field_typeset_uses_baseline():
    bbox = ink_bbox(render("^XA^PW400^LL200^FT10,100^A0N,50,50^FDHHH^FS^XZ"))
    assert bbox is not None
    assert bbox[3] <= 101 and bbox[1] >= 50


def test_field_block_justifies_all_but_the_last_line():
    words = "a quick fox jumps over the lazy dog and keeps going"
    zpl = "^XA^PW500^LL300^FO0,0^A0N,30,30^FB400,3,0,{}^FD" + words + "^FS^XZ"
    justified, left = render(zpl.format("J")), render(zpl.format("L"))
    first_line = (0, 0, 500, 30)
    # Glyph side bearings and the rasterizer leave a few dots between the ink and the block
    # edge; left-aligned, the first line ends about 30 dots earlier.
    justified_end = ink_bbox(justified.crop(first_line))[2]
    assert 394 <= justified_end <= 400
    assert ink_bbox(left.crop(first_line))[2] < justified_end - 20
    # The last line stays left-aligned.
    last = ink_bbox(justified.crop((0, 30, 500, 90)))
    assert last == ink_bbox(left.crop((0, 30, 500, 90)))


def test_field_block_overflow_prints_over_the_last_line():
    words = " ".join(["aaa bbb ccc ddd"] * 4)
    result = render_zpl(f"^XA^PW500^LL300^FO0,0^A0N,30,30^FB200,2,0,L^FD{words}^FS^XZ")
    bbox = ink_bbox(png_image(result.png))
    assert bbox is not None and bbox[3] <= 60 and bbox[2] <= 200
    assert any("allows 2" in w for w in result.warnings)


def test_field_block_hyphenates_words_wider_than_the_block():
    img = render("^XA^PW500^LL300^FO0,0^A0N,30,30^FB150,4,0,L^FDSUPERCALIFRAGILISTIC^FS^XZ")
    bbox = ink_bbox(img)
    assert bbox is not None and bbox[2] <= 150 and bbox[3] > 30


def test_field_block_escapes():
    block = "^XA^CI{}^PW600^LL200^FO0,0^A0N,30,30^FB500,3,0,L^FD{}^FS^XZ"
    plain = "^XA^CI{}^PW600^LL200^FO0,0^A0N,30,30^FD{}^FS^XZ"
    # \& breaks the line.
    assert ink_bbox(render(block.format(13, r"a\&b")))[3] > 40
    # \\ is a backslash, which ^CI0 prints as a cent sign.
    assert render(block.format(13, r"C:\\x")) == render(plain.format(13, r"C:\x"))
    assert render(block.format(0, r"C:\\x")) == render(plain.format(28, "C:¢x"))
    # A backslash before a letter is a soft hyphen, not printed unless the line breaks there.
    assert render(block.format(13, r"ne\wline")) == render(plain.format(13, "newline"))


def test_backslash_and_line_break_outside_a_field_block():
    zpl = "^XA^CI{}^PW400^LL60^FO0,0^A0N,30,30^FD{}^FS^XZ"
    # \& only means a line break inside ^FB.
    assert render(zpl.format(13, r"a\&b")) != render(zpl.format(13, "a b"))
    # The resident fonts print 5C as a cent sign except with ^CI13 (p.114, p.342).
    assert render(zpl.format(0, "\\")) == render(zpl.format(28, "¢"))


def test_field_typeset_block_uses_the_last_possible_line():
    one_line = ink_bbox(render("^XA^PW400^LL300^FT0,200^A0N,30,30^FDHHH^FS^XZ"))
    block = ink_bbox(render("^XA^PW400^LL300^FT0,200^A0N,30,30^FB300,3,0,L^FDHHH^FS^XZ"))
    assert one_line and block and block[3] == one_line[3] - 60


def test_field_typeset_without_coordinates_continues_after_the_last_field():
    joined = render("^XA^PW400^LL100^FT10,50^A0N,30,30^FDAB^FS^FT^A0N,30,30^FDCD^FS^XZ")
    whole = render("^XA^PW400^LL100^FT10,50^A0N,30,30^FDABCD^FS^XZ")
    a, b = ink_bbox(joined), ink_bbox(whole)
    assert a and b and abs(a[2] - b[2]) <= 3


def test_font_command_without_a_name_uses_the_default_font():
    assert render("^XA^PW200^LL50^CFD^FO0,0^A,36,20^FDAB^FS^XZ") == render(
        "^XA^PW200^LL50^FO0,0^ADN,36,20^FDAB^FS^XZ"
    )


def test_graphic_symbols():
    result = render_zpl("^XA^PW300^LL100^FO0,0^GSN,40,40^FDABCDE^FS^XZ")
    assert result.warnings == []
    assert ink_bbox(png_image(result.png)) is not None


def test_uppercase_only_fonts_and_code_page_850_warnings():
    lower = render_zpl("^XA^PW300^LL50^FO0,0^ABN,22,14^FDabc^FS^XZ")
    assert lower.png == render_zpl("^XA^PW300^LL50^FO0,0^ABN,22,14^FDABC^FS^XZ").png
    assert any("no lowercase" in w for w in lower.warnings)
    # Characters outside code page 850 print blank in the bitmap fonts.
    polish = render_zpl("^XA^CI28^PW300^LL50^FO0,0^ADN,18,10^FDżółw^FS^XZ")
    assert any("has no ł ż; they print blank" in w for w in polish.warnings)
    assert polish.png == render_zpl("^XA^CI28^PW300^LL50^FO0,0^ADN,18,10^FD ó w^FS^XZ").png
    assert render_zpl("^XA^CI28^PW300^LL50^FO0,0^A0N,30,30^FDżółw^FS^XZ").warnings == []
    # OCR-A (H) has ASCII only; OCR-B (E) prints ó (docs/print-tests T05).
    ocr_a = render_zpl("^XA^CI28^PW300^LL50^FO0,0^AHN,21,13^FDAó^FS^XZ")
    assert ocr_a.png == render_zpl("^XA^CI28^PW300^LL50^FO0,0^AHN,21,13^FDA ^FS^XZ").png
    ocr_b = render_zpl("^XA^CI28^PW300^LL50^FO0,0^AEN,28,15^FDAó^FS^XZ")
    assert ocr_b.warnings == []
    assert ocr_b.png != render_zpl("^XA^CI28^PW300^LL50^FO0,0^AEN,28,15^FDA ^FS^XZ").png


def test_right_justified_fields():
    # ^FOx,y,z and ^FTx,y,z with z = 1 (firmware x.14+): the field ends at the origin.
    left = ink_bbox(render("^XA^PW400^LL100^FO300,10^A0N,30,30^FDRIGHT^FS^XZ"))
    right = ink_bbox(render("^XA^PW400^LL100^FO300,10,1^A0N,30,30^FDRIGHT^FS^XZ"))
    assert left and right and right[2] <= 300 < left[2]
    typeset = ink_bbox(render("^XA^PW400^LL100^FT300,40,1^A0N,30,30^FDRIGHT^FS^XZ"))
    assert typeset and typeset[2] <= 300
    # ^FW sets the default justification.
    assert render("^XA^PW400^LL100^FWN,1^FO300,10^A0N,30,30^FDRIGHT^FS^XZ") == render(
        "^XA^PW400^LL100^FO300,10,1^A0N,30,30^FDRIGHT^FS^XZ"
    )


def test_text_block_clips_instead_of_overprinting():
    words = " ".join(["aaa bbb ccc ddd"] * 4)
    result = render_zpl(f"^XA^PW500^LL300^FO0,0^A0N,30,30^TBN,200,60^FD{words}^FS^XZ")
    bbox = ink_bbox(png_image(result.png))
    assert bbox is not None and bbox[2] <= 200 and bbox[3] <= 60
    assert result.fields == [(0, 0, 200, 60)]
    assert any("cut off" in w for w in result.warnings)
    # Rotated with the block's orientation.
    rotated = render_zpl("^XA^PW500^LL300^FO0,0^A0N,30,30^TBR,200,60^FDaaa^FS^XZ")
    assert rotated.fields == [(0, 0, 60, 200)]


def test_placed_field_boxes():
    result = render_zpl("^XA^PW400^LL400^FO10,20^GB50,30,2^FS^FO100,100^A0R,40,40^FDAB^FS^XZ")
    assert result.fields[0] == (10, 20, 50, 30)
    x, y, width, height = result.fields[1]
    assert (x, y, width) == (100, 100, 40) and height > 20  # the cell is rotated


def test_field_block_wraps_and_centers():
    img = render("^XA^PW400^LL300^FO0,0^A0N,30,30^FB200,3,0,C^FDone two three four five^FS^XZ")
    bbox = ink_bbox(img)
    assert bbox is not None
    assert bbox[2] <= 200
    assert bbox[3] > 40  # more than one line


def test_code128_width_matches_modules():
    code = barcodes.linear("code128", "ABC")
    img = render("^XA^PW800^LL200^FO0,0^BY3^BCN,50,N^FDABC^FS^XZ")
    bbox = ink_bbox(img)
    assert bbox is not None
    assert bbox[2] == len(code.pattern.rstrip("0")) * 3
    assert bbox[3] == 50


def test_code128_interpretation_line_adds_height():
    without = ink_bbox(render("^XA^PW800^LL200^FO0,0^BCN,50,N^FD123^FS^XZ"))
    with_text = ink_bbox(render("^XA^PW800^LL200^FO0,0^BCN,50,Y^FD123^FS^XZ"))
    assert without and with_text and with_text[3] > without[3]


def test_qr_magnification():
    bbox = ink_bbox(render("^XA^PW400^LL400^FO0,0^BQN,2,4^FDMA,hi^FS^XZ"))
    assert bbox is not None
    assert bbox[2] - bbox[0] == 21 * 4


@pytest.mark.parametrize(
    ("data", "text", "values"),
    [
        ("A>0B", "A>B", [104, 33, 30, 34]),
        ("A><B", "A^B", [104, 33, 62, 34]),
        ("A>=B", "A~B", [104, 33, 94, 34]),
        # Start B, switch to C (>5); the lone last digit goes back to B.
        (">:AB>5123", "AB123", [104, 33, 34, 99, 12, 100, 19]),
        (">;1234>6A", "1234A", [105, 12, 34, 100, 33]),
        (">9A>7", "A", [103, 33, 101]),
    ],
)
def test_code128_invocation_codes(data: str, text: str, values: list[int]):
    code = barcodes.code128(data)
    assert (code.text, code.values) == (text, values)


@pytest.mark.parametrize(
    ("zpl", "modules"),
    [
        # Mode N without a start code is subset B (p.49): 6 data characters.
        ("^BCN,50,N,N,N^FD123456", 101),
        ("^BCN,50,N,N,N^FD>;123456", 68),
        ("^BCN,50,N,N,N,A^FD123456", 68),  # automatic mode packs the digits in subset C
        ("^BCN,50,N,N,N^FDABC123456", 134),
        ("^BCN,50,N,N,N,A^FDABC123456", 112),
        ("^BCN,50,N,N,Y^FD>;123456", 68),  # mode N leaves out the UCC Mod 10 digit (T02d)
        ("^BCN,50,N,N,Y,A^FD123456", 90),  # Mod 10 digit 5, then back to subset B
    ],
)
def test_code128_width_follows_the_printer_subsets(zpl: str, modules: int):
    bbox = ink_bbox(render(f"^XA^PW1000^LL100^FO0,0^BY2{zpl}^FS^XZ"))
    assert bbox is not None and bbox[2] - bbox[0] == modules * 2


def test_code128_check_digit_is_shown_in_the_interpretation_line():
    assert barcodes.code128("123456", mode="A", ucc_check=True).text == "1234565"
    assert barcodes.code128("AB", mode="A", ucc_check=True).warnings
    # In mode N the printer ignores the flag (T02d).
    plain = barcodes.code128(">;123456", ucc_check=True)
    assert plain.text == "123456" and plain.warnings


@pytest.mark.parametrize(
    ("zpl", "width"),
    [
        # ^BY Table 11: the wide element is a whole number of dots (2 x 2.5 = 5, 3 x 2.4 = 7).
        ("^BY2,2.5^B3N,N,50,N,N^FDABC123", 230),
        ("^BY2,3.0^B3N,N,50,N,N^FDABC123", 254),
        ("^BY2,2.5^B2N,50,N,N,N^FD12345678", 145),
        ("^BY2,3.0^B2N,50,N,N,N^FD12345678", 162),
        ("^BY3,2.4^B3N,N,50,N,N^FDAB12", 249),
    ],
)
def test_wide_to_narrow_ratio_in_whole_dots(zpl: str, width: int):
    bbox = ink_bbox(render(f"^XA^PW800^LL100^FO0,0{zpl}^FS^XZ"))
    assert bbox is not None and bbox[2] - bbox[0] == width


def test_wide_dots_follow_table_11():
    assert [barcodes.wide_dots(w, 2.2) for w in range(1, 11)] == [
        2, 4, 6, 8, 11, 13, 15, 17, 19, 22,
    ]  # fmt: skip
    assert barcodes.wide_dots(9, 2.4) == 21


@pytest.mark.parametrize(
    ("command", "data", "text"),
    [
        ("BE", "12345", "0000000123457"),  # padded on the left with zeros
        ("BE", "4006381333931", "4006381333931"),  # a typed check digit is recalculated
        ("B8", "1234", "00012348"),
        ("BU", "123", "000000001236"),
    ],
)
def test_ean_and_upc_are_padded_like_the_printer(command: str, data: str, text: str):
    symbology = {"BE": "ean13", "B8": "ean8", "BU": "upca"}[command]
    assert barcodes.linear(symbology, data).text == text
    result = render_zpl(f"^XA^PW400^LL120^FO0,0^{command}N,50,Y,N^FD{data}^FS^XZ")
    assert ink_bbox(png_image(result.png)) is not None
    assert all("needs" not in w for w in result.warnings)


def test_ean_wrong_check_digit_warns():
    result = render_zpl("^XA^PW400^LL120^FO0,0^BEN,50^FD4006381333930^FS^XZ")
    assert any("check digit 0 is wrong" in w for w in result.warnings)


def test_interpretation_line_is_centred_under_the_bars():
    # In the default font the text is centred on the bars; in an ^A font it starts at their
    # left edge (T02a and T02f).
    img = render("^XA^PW600^LL200^FO100,0^BY2^BCN,40,Y,N,N^FD>;123456^FS^XZ")
    bars = ink_bbox(img.crop((0, 0, 600, 40)))
    text = ink_bbox(img.crop((0, 45, 600, 200)))
    assert bars and text
    assert abs((bars[0] + bars[2]) / 2 - (text[0] + text[2]) / 2) <= 2
    img = render("^XA^PW600^LL200^FO100,0^BY2^BCN,40,Y,N,N^A0N,30,30^FD>;123456^FS^XZ")
    text = ink_bbox(img.crop((0, 45, 600, 200)))
    assert text and 100 <= text[0] <= 104


def test_pdf417_row_height_is_in_dots():
    # The guide multiplies h by the module width; the printer does not (T10).
    rows = len(barcodes.pdf417_rows("PDF417 TEST", columns=4, security=2))
    for zpl, row_height in (("^BY2^B7N,6,2,4", 6), ("^BY3^B7N,4,2,4", 4)):
        bbox = ink_bbox(render(f"^XA^PW800^LL400^FO0,0{zpl},,N^FDPDF417 TEST^FS^XZ"))
        assert bbox is not None and bbox[3] - bbox[1] == rows * row_height
    # Without a row height the ^BY height is shared by the rows.
    bbox = ink_bbox(render("^XA^PW800^LL400^FO0,0^BY2,3,120^B7N,,2,4,,N^FDPDF417 TEST^FS^XZ"))
    assert bbox is not None and bbox[3] - bbox[1] == rows * round(120 / rows)


def test_qr_automatic_input_with_utf8_warns_and_byte_mode_does_not():
    auto = render_zpl("^XA^CI28^PW300^LL300^FO0,0^BQN,2,4^FDQA,Zażółć^FS^XZ")
    assert any("automatic input" in w for w in auto.warnings)
    manual = render_zpl("^XA^CI28^PW300^LL300^FO0,0^BQN,2,4^FDQM,B0010Zażółć^FS^XZ")
    assert manual.warnings == []
    short = render_zpl("^XA^CI28^PW300^LL300^FO0,0^BQN,2,4^FDQM,B0006Zażółć^FS^XZ")
    assert any("count 6" in w for w in short.warnings)


def test_datamatrix_escape_sequences():
    doubled = render("^XA^PW200^LL200^FO0,0^BXN,4,200^FH\\^FDA\\7E\\7EB^FS^XZ")
    literal = Image.new("L", (200, 200), 255)
    matrix = barcodes.datamatrix_matrix("A~B")
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if cell:
                literal.paste(0, (c * 4, r * 4, c * 4 + 4, r * 4 + 4))
    assert doubled.tobytes() == literal.convert("1").convert("L").tobytes()
    # With another escape character, ~ is an ordinary character.
    other = render("^XA^PW200^LL200^FO0,0^BXN,4,200,0,0,6,#^FH\\^FDA\\7EB^FS^XZ")
    assert other.tobytes() == doubled.tobytes()


def test_itf_check_digit():
    assert barcodes._mod10("400638133393") == "1"  # EAN-13 4006381333931
    assert barcodes.linear("itf", "123456", check_digit=True).text == "01234565"
    assert barcodes.linear("itf", "123456").text == "123456"
    plain = render_zpl("^XA^PW600^LL100^FO0,0^B2N,50,Y,N,N^FD123456^FS^XZ")
    checked = render_zpl("^XA^PW600^LL100^FO0,0^B2N,50,Y,N,Y^FD123456^FS^XZ")
    assert checked.png != plain.png
    assert checked.warnings == []


@pytest.mark.parametrize(
    ("data", "expected"),
    [("MM,B0005hello", "MA,hello"), ("HM,N123", "HA,123"), ("qa,x", "QA,x")],
)
def test_qr_header(data: str, expected: str):
    def qr(value: str):
        return render_zpl(f"^XA^PW300^LL300^FO0,0^BQN,2,3^FD{value}^FS^XZ")

    assert qr(data).png == qr(expected).png
    assert qr(data).warnings == []


def test_qr_without_header_encodes_all_data():
    result = render_zpl("^XA^PW300^LL300^FO0,0^BQN,2,3^FDHi, world^FS^XZ")
    assert result.png == render_zpl("^XA^PW300^LL300^FO0,0^BQN,2,3^FDMA,Hi, world^FS^XZ").png
    assert result.warnings == [
        "^BQ at 0,0 has no error correction and input mode (e.g. QA,) before its data, "
        "so the preview encodes all of it"
    ]


def test_qr_with_only_a_header_prints_nothing():
    result = render_zpl("^XA^PW300^LL300^FO10,10^BQN,2,3^FDMA,^FS^XZ")
    assert ink_bbox(png_image(result.png)) is None
    assert result.warnings == ["^BQ at 10,10 has no data, so nothing is printed"]


def test_serialization_field_keeps_the_starting_value():
    result = render_zpl("^XA^PW300^LL100^FO0,0^A0N,30^FD00001^SFddddd,1^FS^XZ")
    assert result.png == render_zpl("^XA^PW300^LL100^FO0,0^A0N,30^FD00001^FS^XZ").png
    assert result.warnings == ["^SF serialization is previewed as the starting value"]


def test_ean13_invalid_data_warns():
    result = render_zpl("^XA^FO0,0^BEN,50^FDabc^FS^XZ")
    assert any("EAN-13" in w for w in result.warnings)


def test_graphic_field_and_download_graphic():
    mask = Image.new("L", (16, 4), 0)
    mask.paste(255, (0, 0, 8, 4))
    bitmap = Bitmap.from_mask(mask)
    gfa = encode_gfa(bitmap)
    img = render(f"^XA^PW50^LL50^FO10,10{gfa}^FS^XZ")
    assert ink_bbox(img) == (10, 10, 18, 14)

    hex_data = bitmap.data.hex().upper()
    dg = f"~DGR:LOGO.GRF,{len(bitmap.data)},2,{hex_data}"
    img = render(f"{dg}^XA^PW50^LL50^FO0,0^XGR:LOGO.GRF,2,2^FS^XZ")
    assert ink_bbox(img) == (0, 0, 16, 8)


def test_unknown_command_and_missing_graphic_warnings():
    result = render_zpl("^XA^QQ1^FO0,0^XGR:NOPE.GRF^FS^PQ2^XZ")
    assert "Unsupported command ^QQ ignored" in result.warnings
    assert any("NOPE.GRF" in w for w in result.warnings)
    assert not any("^PQ" in w for w in result.warnings)


def test_multiple_formats_and_index():
    zpl = "^XA^PW10^LL10^XZ^XA^PW20^LL20^XZ"
    assert render_zpl(zpl).label_count == 2
    assert render_zpl(zpl, index=1).width == 20
    with pytest.raises(RenderError):
        render_zpl(zpl, index=2)
    with pytest.raises(RenderError):
        render_zpl(zpl, index=-1)


def test_no_format_warns():
    result = render_zpl("hello")
    assert result.label_count == 0
    assert result.warnings


def test_render_cache_returns_same_result():
    cache = RenderCache(size=1)
    first = cache.render("^XA^XZ", dpi=203, width=None, height=None, index=0)
    assert cache.render("^XA^XZ", dpi=203, width=None, height=None, index=0) is first
    cache.render("^XA^PW5^XZ", dpi=203, width=None, height=None, index=0)
    assert cache.render("^XA^XZ", dpi=203, width=None, height=None, index=0) is not first


def test_requested_size_is_capped_even_without_a_format():
    from app.render.renderer import MAX_HEIGHT, MAX_WIDTH

    result = render_zpl("", dpi=600, width=23622, height=94488)
    assert (result.width, result.height) == (MAX_WIDTH, MAX_HEIGHT)
    assert any("clipped" in w for w in result.warnings)


def test_broken_last_field_without_fs_is_a_warning():
    result = render_zpl("^XA^PW50^LL50^FO10,10^GFA,4,4,1,:Z64:AAAA^XZ")
    assert any("Invalid Z64" in w for w in result.warnings)
    with_fs = render_zpl("^XA^PW50^LL50^FO10,10^GFA,4,4,1,:Z64:AAAA^FS^XZ")
    assert any("Invalid Z64" in w for w in with_fs.warnings)


def test_render_cache_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor

    cache = RenderCache(size=2)

    def work(i: int) -> int:
        return cache.render(f"^XA^PW{10 + i % 7}^LL10^XZ", dpi=203, width=None, height=None).width

    with ThreadPoolExecutor(8) as pool:
        widths = list(pool.map(work, range(400)))
    assert widths == [10 + i % 7 for i in range(400)]
    assert len(cache._items) <= 2


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_control_character_commands():
    caret = tokenize("~CC$$XA$FO10,10$FDa$FS$XZ")
    assert [c.code for c in caret] == ["CC", "XA", "FO", "FD", "FS", "XZ"]
    assert all(c.prefix == "^" for c in caret[1:])
    tilde = tokenize("^CT#^XA#HS^XZ")
    assert [(c.prefix, c.code) for c in tilde] == [
        ("^", "CT"),
        ("^", "XA"),
        ("~", "HS"),
        ("^", "XZ"),
    ]
    delimited = render("^CD;^XA^PW50^LL50^FO10;20^GB5;5;5^FS^XZ")
    assert ink_bbox(delimited) == (10, 20, 15, 25)


def test_stray_text_before_the_first_format_is_ignored():
    commands = tokenize("CT~~CD,~CC^~CT~\n^XA^FDx^FS^XZ")
    assert [c.code for c in commands] == ["CD", "CC", "CT", "XA", "FD", "FS", "XZ"]


def test_setup_formats_are_not_labels_but_their_settings_apply():
    zpl = "^XA^LH50,0^JUS^XZ^XA^PW200^LL50^FO0,0^GB10,10,10^FS^XZ"
    result = render_zpl(zpl)
    assert result.label_count == 1
    assert ink_bbox(png_image(result.png)) == (50, 0, 60, 10)


def test_field_parameter_spacing_and_direction():
    plain = ink_bbox(render("^XA^PW600^LL200^FO0,0^AAN,27,15^FDABCD^FS^XZ"))
    spaced = ink_bbox(render("^XA^PW600^LL200^FO0,0^FPH,10^AAN,27,15^FDABCD^FS^XZ"))
    assert plain and spaced
    widening = (spaced[2] - spaced[0]) - (plain[2] - plain[0])
    assert abs(widening - 30) <= 2  # 3 gaps of 10 dots (± glyph bearings)
    vertical = ink_bbox(render("^XA^PW600^LL400^FO0,0^FPV^AAN,27,15^FDABCD^FS^XZ"))
    assert vertical and vertical[3] - vertical[1] > 4 * 20
    # ^FP only applies to its own field
    after = render_zpl("^XA^PW600^LL200^FO0,0^FPH,10^FDAB^FS^FO0,100^FDAB^FS^XZ")
    assert after.warnings == []


def test_empty_barcode_data_prints_nothing():
    result = render_zpl("^XA^PW200^LL200^FO10,10^BQN,2,3^FD^FS^XZ")
    assert ink_bbox(png_image(result.png)) is None
    assert result.warnings == ["^BQ at 10,10 has no data, so nothing is printed"]


def test_zebradesigner_label():
    result = render_zpl((FIXTURES / "zebradesigner_asn.zpl").read_text())
    assert (result.width, result.height, result.label_count) == (799, 320, 1)
    assert result.warnings == ["^BQ at 615,243 has no data, so nothing is printed"]
    image = png_image(result.png)
    assert image.getpixel((5, 300)) == 0  # reversed bar at the bottom


# ---- checks against the ZPL II Programming Guide, Vol. 2 ----------------------------------


def test_rs_and_dle_replace_caret_and_tilde():
    commands = tokenize("\x1eXA\x1eFDa\x10HS\x1eXZ")
    assert [(c.prefix, c.code) for c in commands] == [
        ("^", "XA"),
        ("^", "FD"),
        ("~", "HS"),
        ("^", "XZ"),
    ]


def test_bitmap_font_metrics_follow_the_font_matrix():
    from app.render.fonts import resolve_font

    font_a = resolve_font("A", None, None)
    assert (font_a.cell_height, font_a.char_width, font_a.advance) == (9, 5, 6)  # gap 1
    assert font_a.baseline == 7
    assert font_a.line_width("ABCD") == 4 * 6 - 1
    # ^AD,52 gives the same size as ^AD,54 (whole multiples of the 18x10 matrix)
    assert resolve_font("D", 52, None).cell_height == resolve_font("D", 54, None).cell_height == 54
    # only the height given: width magnified by the same factor
    assert resolve_font("D", 36, None).char_width == 20
    # OCR fonts change with the printhead resolution
    assert (resolve_font("E", None, None, dpmm=12).cell_height,) == (42,)
    assert resolve_font("H", None, None, dpmm=6).char_width == 11


def test_scalable_font_defaults_and_baseline():
    from app.render.fonts import resolve_font

    default = resolve_font("0", None, None)
    assert default.cell_height == 15  # "0 Default: 15 x 12"
    assert resolve_font("0", 80, 80).baseline == 60  # 3/4 down the cell


def test_cf_size_applies_to_fonts_selected_without_size():
    # "If neither is defined, the ^CF height and width are used."
    with_cf = ink_bbox(render("^XA^PW600^LL300^CFA,90^FO0,0^AD^FDHH^FS^XZ"))
    without = ink_bbox(render("^XA^PW600^LL300^FO0,0^AD^FDHH^FS^XZ"))
    assert with_cf and without
    assert with_cf[3] - with_cf[1] > 2 * (without[3] - without[1])


def test_default_code_page_and_ci27_for_hex_escapes():
    from app.render.lexer import decode_field_hex

    assert decode_field_hex("_82", "_") == "é"  # code page 850
    assert decode_field_hex("_E9", "_", encoding="cp1252") == "é"


def test_non_ascii_text_without_utf8_warns():
    result = render_zpl("^XA^PW300^LL60^FO0,0^A0N,30,30^FDżółw^FS^XZ")
    assert any("^CI28" in w for w in result.warnings)
    assert render_zpl("^XA^CI28^PW300^LL60^FO0,0^A0N,30,30^FDżółw^FS^XZ").warnings == []


def test_print_mirror_image():
    img = render("^XA^PW100^LL20^PMY^FO0,0^GB10,10,10^FS^XZ")
    assert ink_bbox(img) == (90, 0, 100, 10)


def test_stored_format_is_merged_with_field_numbers():
    zpl = (
        "^XA^DFFORMAT^FS^LH30,30^BY2,3,100"
        "^FO120,100^CFD^FN1^FA9^FS^FO120,160^B3^FN2^FA6^FS^XZ"
        "^XA^XFFORMAT^FS^FN1^FDLABEL ONE^FS^FN2^FDAAA001^FS^XZ"
    )
    result = render_zpl(zpl, width=600, height=400)
    assert result.label_count == 1  # ^DF stores the format, it does not print
    assert result.warnings == []
    bbox = ink_bbox(png_image(result.png))
    assert bbox is not None and bbox[0] >= 150 and bbox[1] >= 130  # inside the stored layout
    missing = render_zpl("^XA^XFNOPE^FS^FN1^FDx^FS^XZ")
    assert any("NOPE.ZPL" in w for w in missing.warnings)


def test_image_save_and_load():
    zpl = "^XA^FO10,10^GB20,20,20^FS^ISR:SAVED.GRF,N^XZ^XA^ILR:SAVED.GRF^FO50,10^GB10,10,10^FS^XZ"
    result = render_zpl(zpl, width=100, height=50)
    assert result.label_count == 1  # ^IS...,N does not print
    img = png_image(result.png)
    assert black(img, 15, 15) and black(img, 55, 15)


def test_unsupported_bar_codes_are_not_drawn_as_text():
    result = render_zpl("^XA^PW300^LL100^FO10,10^BAN,50^FD123^FS^XZ")
    assert ink_bbox(png_image(result.png)) is None
    assert result.warnings == ["Barcode at 10,10: ^BA (Code 93) is not drawn in the preview"]


def test_codabar():
    result = render_zpl("^XA^PW400^LL100^FO10,10^BKN,N,50,N^FD12345^FS^XZ")
    assert result.warnings == []
    assert ink_bbox(png_image(result.png)) is not None


def test_jm_and_mu_warn():
    assert render_zpl("^XA^JMB^XZ").warnings == [
        "^JMB (half dot density) is not shown in the preview"
    ]
    assert render_zpl("^XA^MUM^XZ").warnings == [
        "^MU units other than dots are not supported in the preview"
    ]


# ---- review fixes -------------------------------------------------------------------------


def test_saved_image_is_not_oriented_twice():
    # ^POI carries over; the recalled image must be rotated once, together with the label.
    zpl = "^XA^POI^FO0,0^GB10,10,10^FS^ISR:IMG.GRF,N^XZ^XA^ILR:IMG.GRF^FO20,0^GB5,5,5^FS^XZ"
    img = png_image(render_zpl(zpl, width=100, height=50).png)
    assert black(img, 95, 45)  # recalled box: top-left corner rotated to bottom-right
    assert black(img, 77, 47)  # new box at 20,0 rotated the same way
    assert not black(img, 5, 5)


def test_recall_accepts_prompt_form_and_keeps_field_commands():
    zpl = '^XA^DFLBL^FS^FO10,10^A0N,40,40^FN1"Product name"^FS^XZ^XA^XFLBL^FS^FN1^FH^FD_41_42^FS^XZ'
    with_hex = render_zpl(zpl, width=200, height=60)
    plain = render_zpl("^XA^FO10,10^A0N,40,40^FDAB^FS^XZ", width=200, height=60)
    assert with_hex.warnings == []
    assert with_hex.png == plain.png  # "_41_42" decoded to "AB" because ^FH was kept


@pytest.mark.parametrize(
    ("zpl", "printed"),
    [
        # Both printed like this on a real printer: whitespace after ^FH is not the indicator.
        ("^XA^FO20,20^FH\n^FDa_41 b^FS^XZ", "aA b"),
        ("^XA^FO20,20^FH ^FDa_41 41^FS^XZ", "aA 41"),
    ],
)
def test_whitespace_after_field_hex_keeps_the_default_indicator(zpl: str, printed: str):
    result = render_zpl(zpl)
    assert result.png == render_zpl(f"^XA^FO20,20^FD{printed}^FS^XZ").png


def test_persistent_settings_still_merge_across_formats():
    # ^CF with partial parameters builds on the previous ^CF from an earlier format.
    merged = render_zpl("^XA^CF0^XZ^XA^PW300^LL100^CF,60^FO0,0^FDH^FS^XZ")
    direct = render_zpl("^XA^PW300^LL100^CF0,60^FO0,0^FDH^FS^XZ")
    assert merged.png == direct.png


def test_only_stored_formats_render_blank():
    result = render_zpl("^XA^DFX^FS^FO0,0^FN1^FS^XZ")
    assert result.label_count == 1


@pytest.mark.parametrize(
    ("field", "warning"),
    [
        ("^GFA,1000000000,1000000000,1000,,", "Graphic size must be"),
        ("^GFA,6000000,6000000,6000000,,", "too large to preview"),
        ("^GB99999,99999,1", "too large to preview"),
        ("^GC99999,1", "too large to preview"),
        ("^GD99999,99999,1", "too large to preview"),
        ("^A0N,50000,50000^FDHello", "too large to preview"),
        ("^A0N,16000,1^FD" + "W" * 200, "too large to preview"),
        ("^A0N,16000,1^FD" + "W" * 5000, "too large to preview"),  # FreeType width wraps
        ("^A0N,30,30^FB50000,1000,50000^FDHello", "too large to preview"),
        ("^A0N,30,30^FPV,50000^FDHello", "too large to preview"),
        ("^A0N,30,30^FPH,9999^FD" + "x" * 1000, "too large to preview"),
        ("^BCN,500000^FD123", "too large to preview"),
        ("^BXN,5000^FDABC", "too large to preview"),
        ("^B7N,50000^FDABC", "too large to preview"),
    ],
)
def test_oversized_fields_are_skipped_with_a_warning(field: str, warning: str):
    result = render_zpl(f"^XA^PW100^LL100^FO0,0{field}^FS^XZ")
    assert any(warning in w for w in result.warnings), result.warnings
    assert ink_bbox(png_image(result.png)) is None


def test_ellipse_size_is_capped_at_4095():
    # "larger values are replaced with 4095" (p.159)
    result = render_zpl("^XA^PW3000^LL5000^FO0,0^GE99999,99999,1^FS^XZ")
    assert ink_bbox(png_image(result.png)) == (0, 0, 3000, 4095)


def test_graphic_magnification_and_bitmap_fonts_are_capped_at_ten():
    dg = "~DGR:DOT.GRF,1,1,80"  # a single dot
    huge = render(f"{dg}^XA^PW100^LL100^FO0,0^XGR:DOT.GRF,10000,10000^FS^XZ")
    assert ink_bbox(huge) == (0, 0, 10, 10)
    text = render_zpl("^XA^PW200^LL200^FO0,0^AAN,5000,5000^FDA^FS^XZ")
    assert text.warnings == []
    assert ink_bbox(png_image(text.png))[3] <= 90  # font A is 9 dots tall


@pytest.mark.parametrize("value", ["inf", "9" * 400])
def test_numbers_too_large_for_an_int_fall_back_to_defaults(value: str):
    result = render_zpl(f"~DGR:X.GRF,{value},1,FF^XA^PW{value}^LL100^FO0,0^GB{value},10,10^FS^XZ")
    assert (result.width, result.height) == (812, 100)


def test_stored_graphics_and_images_share_a_memory_budget(monkeypatch: pytest.MonkeyPatch):
    from app.render import renderer

    monkeypatch.setattr(renderer, "MAX_STORED_BYTES", 2500)
    graphics = "".join(f"~DGR:G{i}.GRF,1000,10,," for i in range(3))
    zpl = f"{graphics}^XA^PW40^LL40^FO0,0^GB10,10,10^FS^ISR:SAVED.GRF,N^XZ"
    result = render_zpl(zpl + "^XA^FO0,0^XGR:G1.GRF^FS^XZ")
    assert "G2.GRF is not stored: too many stored graphics and images" in result.warnings
    assert "SAVED.GRF is not stored: too many stored graphics and images" in result.warnings
    assert not any("G1.GRF" in w for w in result.warnings)
    # Downloading a graphic again under the same name replaces it instead of adding to it.
    again = "".join("~DGR:G0.GRF,1000,10,," for _ in range(5))
    assert render_zpl(again + "^XA^XZ").warnings == []


def test_format_recalls_have_a_total_budget(monkeypatch: pytest.MonkeyPatch):
    from app.render import renderer

    monkeypatch.setattr(renderer, "MAX_RECALLED_COMMANDS", 70)  # two recalls
    stored = "^XA^DFR:BIG.ZPL^FS" + "^FO0,0^GB5,5,5^FS" * 10 + "^XZ"
    result = render_zpl(stored + "^XA^XFR:BIG.ZPL^FS^XFR:BIG.ZPL^FS^XFR:BIG.ZPL^FS^XZ")
    assert any("BIG.ZPL is recalled too often" in w for w in result.warnings)
    calls = render_zpl(stored + "^XA^XFR:BIG.ZPL^FS^XZ" * 3)
    assert calls.label_count == 2  # the third recall exceeds the budget and prints nothing


def test_shift_in_ends_a_field():
    assert [c.code for c in tokenize("^XA^FDa\x0f^XZ")] == ["XA", "FD", "FS", "XZ"]
    assert render("^XA^PW100^LL50^FO0,0^GB10,10,10\x0f^FO20,0^GB10,10,10\x0f^XZ") == render(
        "^XA^PW100^LL50^FO0,0^GB10,10,10^FS^FO20,0^GB10,10,10^FS^XZ"
    )


def test_binary_graphic_data_may_contain_control_prefixes():
    # Two rows of 1 byte: "^" (0x5E) and "~" (0x7E) are image bytes, not commands.
    zpl = "^XA^PW16^LL4^FO0,0^GFB,2,2,1,^~^FS^XZ"
    assert [c.code for c in tokenize(zpl)] == ["XA", "PW", "LL", "FO", "GF", "FS", "XZ"]
    img = render(zpl)
    assert [black(img, x, 0) for x in range(8)] == [c == "1" for c in f"{0x5E:08b}"]
    assert [black(img, x, 1) for x in range(8)] == [c == "1" for c in f"{0x7E:08b}"]


@pytest.mark.parametrize(
    "zpl",
    [
        "^XA^GFB,²,1,1,x^FS^XZ",
        "^XA^FO0,0^BCN,50^FD>;1²^FS^XZ",
        "^XA^FO0,0^BXN,4,200^FDa~d²²²b^FS^XZ",
        "^XA^FO0,0^BQN,2,4^FDQM,B²²²²ab^FS^XZ",
        "^XA^FO0,0^BEN,50^FD12345²^FS^XZ",
    ],
)
def test_digits_of_other_scripts_do_not_break_the_preview(zpl: str):
    render_zpl(zpl)  # no exception


def test_bitmap_font_halves_round_up_like_the_designer():
    from app.render.fonts import resolve_font

    # 45 / 18 = 2.5: font D prints 3 times its matrix (frontend bitmapFontHeight agrees).
    assert resolve_font("D", 45, None).cell_height == 54


@pytest.mark.parametrize("orientation", ["N", "R", "I", "B"])
def test_barcode_bars_stay_at_the_origin_when_the_text_is_wider(orientation: str):
    # Module width 1 and a large interpretation font: the text is wider than the bars.
    wide = f"^XA^PW600^LL600^FO200,200^BY1^BC{orientation},40,Y,N,N^A0N,60,60^FD>;1111^FS^XZ"
    bars_only = f"^XA^PW600^LL600^FO200,200^BY1^BC{orientation},40,N,N,N^FD>;1111^FS^XZ"
    with_text, bars = ink_bbox(render(wide)), ink_bbox(render(bars_only))
    assert with_text and bars
    # The bars are where they are without the text; the text in an ^A font starts where the
    # bars start and sticks out past their other end (T02f/g).
    assert with_text[:2] <= bars[:2] and with_text[2:] >= bars[2:]
    if orientation in ("N", "I"):
        assert bars[0] == 200
        assert (with_text[2] > bars[2]) if orientation == "N" else (with_text[0] < 200)
    else:
        assert bars[1] == 200
        assert (with_text[3] > bars[3]) if orientation == "R" else (with_text[1] < 200)


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("x\ty", ">:x>7\t>6y"),  # lowercase needs B, tab needs A
        ("\tAB", ">9\tAB"),  # A holds capitals too
        ("ab12345678", ">:ab>512345678"),
    ],
)
def test_code128_switches_subsets_per_character(text: str, field: str):
    assert barcodes.code128_field(text) == field
    code = barcodes.code128(field)
    assert code.text == text and not code.warnings


def test_pdf417_escaped_backslash_before_ampersand_stays_a_backslash():
    # a\&b as entered is sent as a\\&b: a backslash, then "&", no line break.
    escaped = render(r"^XA^PW600^LL300^FO0,0^BY2^B7N,6,2,4,,N^FDa\\&b^FS^XZ")
    plain = Image.new("L", escaped.size, 255)
    rows = barcodes.pdf417_rows("a\\&b", columns=4, security=2)
    for r, row in enumerate(rows):
        for c, module in enumerate(row):
            if module == "1":
                plain.paste(0, (c * 2, r * 6, c * 2 + 2, r * 6 + 6))
    assert escaped.tobytes() == plain.convert("1").convert("L").tobytes()


# Measured on a ZD420d (V84.20.23Z) printout of docs/print-tests, compared in dots.


def test_font0_em_is_the_height():
    # T04: ten H at ^A0N,50 print 302 dots wide, capitals from the origin to 3/4 down.
    for zpl in ("^A0N,50", "^A0N,50,50"):
        bbox = ink_bbox(render(f"^XA^PW800^LL200^FO40,20{zpl}^FDHHHHHHHHHH^FS^XZ"))
        assert bbox is not None
        assert 299 <= bbox[2] - bbox[0] <= 305
        assert 20 <= bbox[1] <= 23 and bbox[3] == 20 + 38  # baseline 3/4 of 50, rounded
    narrow = ink_bbox(render("^XA^PW800^LL200^FO40,20^A0N,50,40^FDHHHHHHHHHH^FS^XZ"))
    assert narrow is not None and 235 <= narrow[2] - narrow[0] <= 245


def test_font0_sizes_below_10_print_at_10():
    small = render("^XA^PW300^LL50^FO10,10^A0N,8,8^FDtiny^FS^XZ")
    assert small == render("^XA^PW300^LL50^FO10,10^A0N,10,10^FDtiny^FS^XZ")


def test_font0_accents_on_capitals_rise_above_the_origin():
    bbox = ink_bbox(render("^XA^CI28^PW300^LL100^FO10,40^A0N,40,40^FDŻÓŁ^FS^XZ"))
    assert bbox is not None and bbox[1] < 40
    # Without such glyphs the field still starts at the origin.
    plain = render_zpl("^XA^CI28^PW300^LL100^FO10,40^A0N,40,40^FDZOL^FS^XZ")
    assert plain.fields[0][1] == 40


def test_backslash_prints_as_cent_except_in_the_ocr_fonts():
    # T05/T06d: ^CI28 keeps the resident fonts' ¢ in place of the backslash; E and H print it.
    for font in ("^A0N,30,30", "^AAN,18,10", "^ADN,18,10"):
        cent = render_zpl(f"^XA^CI28^PW300^LL50^FO0,0{font}^FDa\\b^FS^XZ")
        assert any("backslash as ¢" in w for w in cent.warnings)
        assert cent.png == render_zpl(f"^XA^CI28^PW300^LL50^FO0,0{font}^FDa¢b^FS^XZ").png
    ocr = render_zpl("^XA^CI28^PW300^LL50^FO0,0^AEN,28,15^FDa\\b^FS^XZ")
    assert ocr.warnings == []
    assert ocr.png != render_zpl("^XA^CI28^PW300^LL50^FO0,0^AEN,28,15^FDa¢b^FS^XZ").png


def test_bitmap_fonts_have_the_euro_and_h_has_no_lowercase():
    euro = render_zpl("^XA^CI28^PW300^LL50^FO0,0^AAN,18,10^FD€^FS^XZ")
    assert euro.warnings == [] and ink_bbox(png_image(euro.png)) is not None
    lower = render_zpl("^XA^PW300^LL50^FO0,0^AHN,21,13^FDag^FS^XZ")
    assert ink_bbox(png_image(lower.png)) is None
    assert any("print blank" in w for w in lower.warnings)


def test_interpretation_line_is_font_a_times_the_module_width():
    # T08: font A cells 12 dots apart at ^BY2 and 18 at ^BY3, capitals 7 x 2 and 7 x 3 high.
    for mw, advance, cap in ((2, 12, 14), (3, 18, 21)):
        img = render(f"^XA^PW800^LL200^FO40,20^BY{mw}^BCN,50,Y,N,N^FDHHHHHH^FS^XZ")
        text = ink_bbox(img.crop((0, 71, 800, 200)))
        assert text is not None
        # Six cells of 5 x mw dots, less the glyphs' side bearings.
        assert 6 * advance - 4 * mw <= text[2] - text[0] <= 6 * advance - mw
        assert text[3] - text[1] == cap


def test_rotated_bar_code_text_is_outside_the_field_origin():
    # T03: ^BCR puts the bars at ^FO and the interpretation line left of it.
    img = render("^XA^PW800^LL400^FO440,40^BY2^BCR,80,Y,N,N^FD>;123456^FS^XZ")
    bars = ink_bbox(img.crop((440, 0, 800, 400)))
    text = ink_bbox(img.crop((0, 0, 440, 400)))
    assert bars is not None and bars[0] == 0 and bars[2] == 80
    assert text is not None and text[0] >= 420 and text[2] <= 440


def test_rotated_field_block_keeps_room_for_all_its_lines():
    # T03: a 3-line block at R with one line prints it two lines (60 dots) right of ^FO.
    bbox = ink_bbox(render("^XA^PW800^LL400^FO700,40^A0R,30,30^FB300,3,0,L^FDONE LINE^FS^XZ"))
    assert bbox is not None and bbox[0] >= 765 and bbox[2] <= 792
    # Inverted, the line goes to the bottom of the block; at N and B nothing moves.
    inverted = ink_bbox(render("^XA^PW800^LL400^FO40,40^A0I,30,30^FB300,3,0,L^FDONE^FS^XZ"))
    assert inverted is not None and inverted[1] >= 100
    normal = ink_bbox(render("^XA^PW800^LL400^FO40,40^A0N,30,30^FB300,3,0,L^FDONE^FS^XZ"))
    assert normal is not None and normal[1] < 50


def test_text_block_line_pitch_and_which_lines_print():
    # T16: lines 38 dots apart at h=30; a line prints while its baseline is in the block.
    text = "This text block is three lines high, so the rest of this long sentence does not print"
    img = render(f"^XA^PW800^LL400^FO0,0^A0N,30,30^TBN,300,100^FD{text}^FS^XZ")
    rows = [y for y in range(130) if ink_bbox(img.crop((0, y, 300, y + 1)))]
    tops = [y for y in rows if y - 1 not in rows]
    assert tops == [0, 38, 76]
    assert max(rows) < 100  # descenders of the last line are cut off at the block
    rotated = render(
        "^XA^PW800^LL400^FO40,220^A0N,30,30^TBR,160,90"
        "^FDA rotated text block whose last words are cut off at the end^FS^XZ"
    )
    cols = [x for x in range(40, 140) if ink_bbox(rotated.crop((x, 220, x + 1, 380)))]
    assert min(cols) >= 60  # two lines, the third (left) does not fit


def test_qr_offset_is_the_bar_code_height():
    # T11, T17: a QR code prints 2 dots less than the ^BY height (default 10) below ^FO,
    # also when an earlier label set it.
    qr = "^XA^PW300^LL300^FO0,0^BQN,2,4^FDQA,x^FS^XZ"
    default = ink_bbox(render(qr))
    after = ink_bbox(render("^XA^BY2,3,60^XZ" + qr))
    assert default is not None and default[1] == 8
    assert after is not None and after[1] == 58
    # Data Matrix is not moved.
    dm = ink_bbox(render("^XA^PW300^LL300^BY2,3,60^FO0,0^BXN,4,200^FDx^FS^XZ"))
    assert dm is not None and dm[1] == 0


def test_ellipse_under_3_dots_does_not_print():
    # T12: ^GE2,100,2 prints nothing.
    result = render_zpl("^XA^PW200^LL200^FO10,10^GE2,100,2^FS^XZ")
    assert ink_bbox(png_image(result.png)) is None
    assert any("do not print" in w for w in result.warnings)


def test_ean_and_upc_human_readable_layout():
    # T09: the first digit 9 modules left of the bars, guard bars 12 dots longer.
    img = render("^XA^PW800^LL400^FO60,20^BY2^BEN,50,Y,N^FD12345^FS^XZ")
    bbox = ink_bbox(img)
    assert bbox is not None and 60 - 18 <= bbox[0] <= 60 - 16
    guard = ink_bbox(img.crop((60, 0, 62, 400)))
    data = ink_bbox(img.crop((66, 0, 150, 70)))
    assert guard is not None and guard[3] == 20 + 50 + 12
    assert data is not None and data[3] == 20 + 50
    # UPC-A has its last digit right of the bars too.
    upc = ink_bbox(render("^XA^PW800^LL400^FO60,20^BY2^BUN,50,Y,N,Y^FD123^FS^XZ"))
    assert upc is not None and upc[2] > 60 + 190


def test_bar_code_text_above_stands_above_the_origin():
    # T17: with the text above, the bars are still at ^FO and the text above it.
    img = render("^XA^PW600^LL400^FO250,310^BY2^BCN,40,Y,Y,N^FD>;1234^FS^XZ")
    bars = ink_bbox(img.crop((0, 310, 600, 400)))
    text = ink_bbox(img.crop((0, 0, 600, 310)))
    assert bars is not None and bars[1] == 0 and bars[3] == 40
    assert text is not None and text[1] >= 280 and text[3] <= 302


def test_ellipse_border_prints_one_dot_thicker():
    # T12, T17: t = 1, 2, 3, 4 print 3, 3, 4, 5 dots, inwards from the outer size.
    for t, printed in ((1, 3), (2, 3), (3, 4), (4, 5)):
        img = render(f"^XA^PW200^LL100^FO20,20^GE80,50,{t}^FS^XZ")
        top = [y for y in range(10, 50) if black(img, 60, y)]
        assert top == list(range(20, 20 + printed))
        assert ink_bbox(img) == (20, 20, 100, 70)


def test_pdf417_drops_a_backslash_before_other_characters():
    # T10d: C:\new is encoded as "C:new".
    escaped = render(r"^XA^PW600^LL300^FO0,0^BY2^B7N,6,2,4,,N^FDC:\new^FS^XZ")
    plain = render("^XA^PW600^LL300^FO0,0^BY2^B7N,6,2,4,,N^FDC:new^FS^XZ")
    assert escaped == plain


def test_ean_digit_groups_keep_to_the_centre_guard():
    # T09 at ^BY2: the left digits end just before the centre guard (x 150), the right ones
    # start just after it (x 160).
    img = render("^XA^PW800^LL400^FO60,20^BY2^BEN,50,Y,N^FD12345^FS^XZ")
    digits = img.crop((0, 74, 800, 88))
    left = ink_bbox(digits.crop((62, 0, 150, 14)))
    right = ink_bbox(digits.crop((160, 0, 244, 14)))
    assert left is not None and 62 + left[2] >= 147
    assert right is not None and right[0] <= 4


def test_font0_capitals_are_taller_than_the_em_suggests():
    # T04: the H of ^A0N,50 prints 38 dots high (the bundled font's capitals: 36).
    bbox = ink_bbox(render("^XA^PW400^LL100^FO10,20^A0N,50,50^FDH^FS^XZ"))
    assert bbox is not None and 37 <= bbox[3] - bbox[1] <= 39
