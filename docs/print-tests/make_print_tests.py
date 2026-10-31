"""Write the printer fidelity test labels (T01-T17) as .zpl files next to this script.

Each label checks one way the preview and a real Zebra printer can differ; README.md says what
to measure. The labels are 100 x 50 mm at 203 dpi (8 dots/mm) unless noted; run
`python3 make_print_tests.py` after changing them.
"""

from pathlib import Path

HERE = Path(__file__).parent
HEADER = "^XA^CI28^PW800^LL400^LH0,0^LRN^PMN\n"


def corner(x: int, y: int) -> str:
    """An L-shaped bracket whose inner corner is exactly at (x, y): the field origin."""
    return f"^FO{x - 14},{y - 2}^GB12,2,2^FS^FO{x - 2},{y - 14}^GB2,12,2^FS\n"


def label(comment: str, *fields: str) -> str:
    return HEADER + f"^FX {comment}\n" + "".join(fields) + "^XZ\n"


def ruler(dpmm: int) -> str:
    """80 mm and 40 mm rulers with ticks every 5 mm."""
    width, height = 100 * dpmm, 50 * dpmm
    x0 = y0 = 5 * dpmm
    lines = [
        f"^XA^CI28^PW{width}^LL{height}^LH0,0^LRN^PMN\n",
        "^FX T01: horizontal ruler 0-80 mm, vertical ruler 0-40 mm, ticks every 5 mm\n",
        f"^FO{x0},{y0}^GB{80 * dpmm + 2},2,2^FS\n",
    ]
    for i in range(17):
        x = x0 + i * 5 * dpmm
        tick = 4 * dpmm if i % 2 == 0 else 2 * dpmm
        line = f"^FO{x},{y0}^GB2,{tick},2^FS"
        if i % 2 == 0:
            line += f"^FO{x + 4},{y0 + tick + 4}^A0N,{3 * dpmm},{3 * dpmm}^FD{i * 5}^FS"
        lines.append(line + "\n")
    for i in range(9):
        tick = 4 * dpmm if i % 2 == 0 else 2 * dpmm
        lines.append(f"^FO{x0},{y0 + i * 5 * dpmm}^GB{tick},2,2^FS\n")
    lines += [
        f"^FO{x0},{y0}^GB2,{40 * dpmm + 2},2^FS\n",
        f"^FO{30 * dpmm},{25 * dpmm}^A0N,{4 * dpmm},{4 * dpmm}^FDT01 {dpmm} dots/mm^FS\n",
        f"^FO{30 * dpmm},{32 * dpmm}^A0N,{3 * dpmm},{3 * dpmm}^FD80 mm = {80 * dpmm} dots^FS\n",
        "^XZ\n",
    ]
    return "".join(lines)


def graphic_field_strips() -> str:
    """A 800 x 1200 dot ^GF of 120,000 bytes, more than ^GF's 99,999 (100 x 150 mm label).

    One character per row: "!" fills the row with black, "," with white. A black band every
    100 rows, and the last 100 rows black: they are missing if the printer stops at 99,999.
    """
    rows = "".join("!" if (row % 100 < 8 or row >= 1100) else "," for row in range(1200))
    return (
        "^XA^CI28^PW800^LL1200^LH0,0^LRN^PMN\n"
        "^FX T14 ^GF over 99999 bytes (needs 100x150 mm label)\n"
        f"^FO0,0^GFA,120000,120000,100,{rows}^FS\n"
        "^FO420,30^A0N,30,30^FDbands every 100 rows^FS\n"
        "^FO420,1000^A0N,30,30^FDbottom band = rows 1100-1199^FS\n^XZ\n"
    )


POLISH = "Zażółć gęślą jaźń"

TESTS = {
    "T01_ruler_203dpi": ruler(8),
    "T01_ruler_300dpi": ruler(12),
    "T02_code128": label(
        "T02 Code 128 subsets, check digit, interpretation line font",
        corner(40, 20), "^FO40,20^BY2^BCN,50,Y,N,N^FD123456^FS\n",
        corner(40, 115), "^FO40,115^BY2^BCN,50,Y,N,N,A^FD123456^FS\n",
        corner(40, 210), "^FO40,210^BY2^BCN,50,Y,N,N^FD>;123456^FS\n",
        corner(40, 305), "^FO40,305^BY2^BCN,50,Y,N,Y^FD>;123456^FS\n",
        corner(420, 20), "^FO420,20^BY2^BCN,50,Y,N,N^FDAB>0CD^FS\n",
        corner(420, 115), "^FO420,115^A0N,30,30^BY2^BCN,50,Y,N,N^FD>;123456^FS\n",
        corner(420, 210), "^FO420,210^ADN,36,20^BY2^BCN,50,Y,N,N^FD>;123456^FS\n",
        corner(420, 305), "^FO420,305^BY2^BCN,50,Y,N,N^FDABC123456^FS\n",
    ),
    "T03_rotation": label(
        "T03 field origin of rotated fields (bracket corner = ^FO)",
        corner(40, 40), "^FO40,40^A0N,40,40^FDBATCH 01^FS\n",
        corner(40, 140), "^FO40,140^A0I,40,40^FDBATCH 01^FS\n",
        corner(260, 40), "^FO260,40^A0R,40,40^FDBATCH 01^FS\n",
        corner(340, 40), "^FO340,40^A0B,40,40^FDBATCH 01^FS\n",
        corner(440, 40), "^FO440,40^BY2^BCR,80,Y,N,N^FD>;123456^FS\n",
        corner(600, 40), "^FO600,40^A0R,30,30^FB300,1,0,C^FDCENTER^FS\n",
        corner(700, 40), "^FO700,40^A0R,30,30^FB300,3,0,L^FDONE LINE^FS\n",
        corner(40, 250), "^FO40,250^A0N,40,40^FDgjpqy^FS\n",
        corner(260, 250), "^FO260,250^A0I,40,40^FDgjpqy^FS\n",
    ),
    "T04_font0_width": label(
        "T04 font 0 width when w is omitted; minimum height",
        corner(40, 20), "^FO40,20^A0N,50^FDHHHHHHHHHH^FS\n",
        corner(40, 90), "^FO40,90^A0N,50,50^FDHHHHHHHHHH^FS\n",
        corner(40, 160), "^FO40,160^A0N,50,40^FDHHHHHHHHHH^FS\n",
        corner(40, 230), "^FO40,230^A0N,40,40^FDThe quick brown fox 0123^FS\n",
        corner(40, 310), "^FO40,310^A0N,8,8^FDtiny 8 dots^FS\n",
        corner(300, 310), "^FO300,310^A0N,10,10^FDtiny 10 dots^FS\n",
    ),
    "T05_fonts_chars": label(
        "T05 bitmap fonts, lowercase, backslash, non-ASCII",
        "^FO20,10^AAN,18,10^FDA: AaGgy 09 \\ ó ą ł €^FS\n",
        "^FO20,40^ABN,22,14^FDB: AaGgy 09 \\ ó ą ł €^FS\n",
        "^FO20,72^ADN,18,10^FDD: AaGgy 09 \\ ó ą ł €^FS\n",
        "^FO20,100^AEN,28,15^FDE: AaGgy 09 \\ ó ą^FS\n",
        "^FO20,138^AFN,26,13^FDF: AaGgy 09 \\ ó ą^FS\n",
        "^FO20,174^AHN,21,13^FDH: AaGgy 09 \\ ó ą^FS\n",
        "^FO20,210^A0N,34,34^FH^FD0: AaGgy \\ ó ą ł ż € _7E _5E^FS\n",
        "^FO20,260^ADN,52^FDD52^FS^FO200,260^ADN,54^FDD54^FS\n",
        f"^FO420,260^A0N,30,30^FD{POLISH}^FS\n",
        # Link-OS printers have the Unicode Swiss 721 font; a missing font prints in font A.
        "^FO20,325^A@N,28,28,E:TT0003M_.FNT^FDE FNT: Zażółć €^FS\n",
        "^FO420,325^A@N,28,28,E:TT0003M_.TTF^FDE TTF: Zażółć €^FS\n",
        "^FO20,362^A@N,28,28,Z:TT0003M_.FNT^FDZ FNT: Zażółć €^FS\n",
    ),
    "T06_field_block": label(
        "T06 ^FB justify, overflow, long word, escapes, newline, ^FT",
        "^FO20,20^GB360,96,1^FS^FO20,20^A0N,24,24^FB360,4,0,J^FDThe quick brown fox jumps "
        "over the lazy dog and keeps running far far away^FS\n",
        "^FO420,20^GB360,48,1^FS^FO420,20^A0N,24,24^FB360,2,0,L^FDOne two three four five "
        "six seven eight nine ten eleven twelve thirteen fourteen fifteen^FS\n",
        "^FO20,150^GB200,72,1^FS^FO20,150^A0N,24,24^FB200,3,0,L"
        "^FDSUPERCALIFRAGILISTICEXPIALIDOCIOUS end^FS\n",
        "^FO420,150^GB360,96,1^FS^FO420,150^A0N,24,24^FB360,4,0,L"
        "^FDLine one\\&Line two C:\\\\temp\\\\x\\&Path C:\\new\\lot^FS\n",
        corner(20, 290), "^FO20,290^A0N,24,24^FDLine A\nLine B^FS\n",
        corner(420, 380),
        "^FT420,380^GB360,1,1^FS^FT420,380^A0N,24,24^FB360,3,0,L^FDFT block, one line^FS\n",
    ),
    "T07_reverse": label(
        "T07 ^FR over a black box, white box",
        "^FO40,40^GB300,100,100^FS\n",
        "^FO20,60^A0N,60,60^FR^FDREVERSE TEXT^FS\n",
        "^FO420,40^GB300,100,100^FS^FO440,60^GB100,60,60,W^FS\n",
        "^FO40,200^GB200,120,120^FS^FO60,220^BY2^FR^BCN,60,N,N,N^FD>;123456^FS\n",
    ),
    "T08_ratio": label(
        "T08 wide:narrow ratio in whole dots",
        corner(40, 20), "^FO40,20^BY2,2.5^B3N,N,50,Y,N^FDABC123^FS\n",
        corner(40, 115), "^FO40,115^BY2,3.0^B3N,N,50,Y,N^FDABC123^FS\n",
        corner(40, 210), "^FO40,210^BY2,2.5^B2N,50,Y,N,N^FD12345678^FS\n",
        corner(40, 305), "^FO40,305^BY2,3.0^B2N,50,Y,N,N^FD12345678^FS\n",
        corner(420, 20), "^FO420,20^BY3,2.4^B3N,N,50,Y,N^FDAB12^FS\n",
        corner(410, 115), "^FO410,115^BY9,2.4^B3N,N,40,N,N^FDA^FS\n",
    ),
    "T09_ean_upc": label(
        "T09 EAN/UPC padding, truncation, human-readable layout",
        corner(60, 20), "^FO60,20^BY2^BEN,50,Y,N^FD12345^FS\n",
        corner(60, 120), "^FO60,120^BY2^BEN,50,Y,N^FD4006381333931^FS\n",
        corner(60, 220), "^FO60,220^BY2^BUN,50,Y,N,Y^FD123^FS\n",
        corner(460, 20), "^FO460,20^BY2^B8N,50,Y,N^FD1234^FS\n",
        corner(460, 120), "^FO460,120^BY3^BEN,50,Y,N^FD590123412345^FS\n",
    ),
    "T10_pdf417": label(
        "T10 PDF417 row height h in dots (the guide: h x module width)",
        corner(40, 20), "^FO40,20^BY2^B7N,6,2,4,,N^FDPDF417 TEST^FS\n",
        corner(420, 20), "^FO420,20^BY3^B7N,4,2,4,,N^FDPDF417 TEST^FS\n",
        corner(40, 220), "^FO40,220^BY2,3,120^B7N,,2,4,,N^FDPDF417 TEST^FS\n",
        corner(420, 220), "^FO420,220^BY2^B7N,6,2,4,,N^FDA\\&B \\\\ C:\\new^FS\n",
    ),
    "T11_qr_datamatrix": label(
        "T11 QR/Data Matrix data encoding and placement (scan each)",
        corner(40, 30), "^FO40,30^BQN,2,4^FDQA,https://example.com^FS\n",
        corner(230, 30), f"^FO230,30^BQN,2,4^FDQA,{POLISH}^FS\n",
        corner(420, 30), f"^FO420,30^BQN,2,4^FDQM,B{len(POLISH.encode()):04d}{POLISH}^FS\n",
        corner(610, 30), f"^FO610,30^BQN,2,4^FDQM,B{len(POLISH):04d}{POLISH}^FS\n",
        corner(40, 250), "^FO40,250^BXN,6,200^FDSKU_1 A^FS\n",
        corner(230, 250), "^FO230,250^BXN,6,200^FH\\^FDA\\7EB^FS\n",
        corner(420, 250), "^FO420,250^BXN,6,200^FH\\^FDA\\7E\\7EB^FS\n",
        corner(610, 250), "^FO610,250^BXN,6,200,0,0,6,#^FH\\^FDSKU_1 A\\7EB^FS\n",
    ),
    "T12_shapes": label(
        "T12 shape limits and ^GD geometry",
        corner(40, 40), "^FO40,40^GB2,100,6^FS\n",
        "^FO100,40^GB200,100,2^FS^FO100,40^GD200,100,6,,L^FS\n",
        "^FO340,40^GB200,100,2^FS^FO340,40^GD200,100,20,,R^FS\n",
        corner(580, 40), "^FO580,40^GE200,100,1^FS\n",
        "^FO40,200^GB200,120,6,B,8^FS\n",
        corner(300, 200), "^FO300,200^GE2,100,2^FS\n",
        corner(400, 200), "^FO400,200^GD2,100,4^FS\n",
        "^FO500,200^GB240,1,1^FS^FO500,320^GB240,1,1^FS^FO500,200^GD240,120,30,,L^FS\n",
    ),
    "T13_sticky_state": (
        "^XA^LRY^PMY^FWR^XZ\n"
        "^XA^CI28^PW800^LL400^LH0,0\n^FX T13 label 1: no resets\n"
        "^FO40,40^A0N,40,40^FDSTICKY 1: NO RESET^FS^FO40,120^GB300,80,80^FS"
        "^FO60,135^A0N,50,50^FDOVER BOX^FS\n^XZ\n"
        "^XA^CI28^PW800^LL400^LH0,0^LRN^PMN\n^FX T13 label 2: with ^LRN^PMN\n"
        "^FO40,40^A0N,40,40^FDSTICKY 2: WITH RESET^FS^FO40,120^GB300,80,80^FS"
        "^FO60,135^A0N,50,50^FDOVER BOX^FS\n^XZ\n"
        "^XA^LRN^PMN^FWN^XZ\n"
    ),
    "T14_gf_99999_100x150": graphic_field_strips(),
    # Prints the printer's own labels listing the fonts and other files on E: and Z:.
    "T15_font_directory": (
        "^XA^FX T15 directory of E: (fonts, graphics)^WDE:*.*^XZ\n"
        "^XA^FX T15 directory of Z: (resident fonts)^WDZ:*.*^XZ\n"
    ),
    "T16_newer_firmware": label(
        "T16 firmware x.14+: right justification (^FO/^FT/^FW z) and ^TB text blocks",
        "^FO400,20^GB1,170,1^FS\n",
        corner(400, 30), "^FO400,30,1^A0N,30,30^FDRIGHT FO^FS\n",
        corner(400, 100), "^FT400,100,1^A0N,30,30^FDRIGHT FT^FS\n",
        corner(400, 140), "^FWN,1^FO400,140^A0N,30,30^FDRIGHT FW^FS^FWN,0\n",
        "^FO440,20^GB300,100,1^FS^FO440,20^A0N,30,30^TBN,300,100^FDThis text block is three "
        "lines high, so the rest of this long sentence does not print on the label at all^FS\n",
        "^FO40,220^GB90,160,1^FS^FO40,220^A0N,30,30^TBR,160,90^FDA rotated text block "
        "whose last words are cut off at the end^FS\n",
        "^FO200,220^GB300,60,1^FS^FO200,220^A0N,30,30^FB300,2,0,L^FDThe same in a field block "
        "prints the extra lines over its last line instead^FS\n",
    ),
    # Checks the rules the preview took from single measurements of the first print run.
    "T17_follow_ups": label(
        "T17 ^TB line spacing, QR offset, ellipse thickness, bar code text side, EAN guards",
        # ^TB lines 1.25 h apart (T16, h=30): 4 lines expected at h=20, 2 at h=50.
        "^FO20,20^GB250,100,1^FS^FO20,20^A0N,20,20^TBN,250,100^FDAt twenty dots high this "
        "block holds four lines of text, so the rest of this rather long sentence about line "
        "spacing does not print on the label^FS\n",
        "^FO290,20^GB200,130,1^FS^FO290,20^A0N,50,50^TBN,200,130^FDFifty dots: two "
        "lines only^FS\n",
        # QR codes print the ^BY height below ^FO (T11): 10 and 60 dots expected.
        corner(520, 30), "^FO520,30^BY2,3,10^BQN,2,3^FDQA,T17 A^FS\n",
        corner(650, 30), "^FO650,30^BY2,3,60^BQN,2,3^FDQA,T17 B^FS\n",
        # ^GE thickness 1 to 4 (t=1 printed about 3 dots in T12).
        "^FO20,180^GE80,50,1^FS^FO110,180^GE80,50,2^FS"
        "^FO200,180^GE80,50,3^FS^FO290,180^GE80,50,4^FS\n",
        # Text of an inverted bar code above its bars and outside ^FO, like ^BCR (T03)?
        corner(40, 310), "^FO40,310^BY2^BCI,40,Y,N,N^FD>;1234^FS\n",
        # Text above the bars: does it stand above ^FO?
        corner(250, 310), "^FO250,310^BY2^BCN,40,Y,Y,N^FD>;1234^FS\n",
        # Guard bars reached 12-13 dots below the others at h=50 (T09): the same at h=100?
        corner(480, 200), "^FO480,200^BY2^BEN,100,Y,N^FD590123412345^FS\n",
    ),
}  # fmt: skip


def main() -> None:
    for name, zpl in TESTS.items():
        (HERE / f"{name}.zpl").write_text(zpl, encoding="utf-8")
        print(f"{name}.zpl")


if __name__ == "__main__":
    main()
