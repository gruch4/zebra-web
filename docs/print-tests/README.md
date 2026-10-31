# Printer fidelity tests

These labels check whether the app's preview (the local renderer, which the designer canvas also
uses) matches what a real Zebra printer prints. Each one covers a place where the ZPL II
Programming Guide (x.10–x.13 firmware, part no. 45541L-004; page numbers as printed in the guide)
leaves something open, or where the app had to change to match the printer. Zebra publishes the
current guide at [docs.zebra.com](https://docs.zebra.com/us/en/printers/software/zpl-pg.html).

`make_print_tests.py` writes the `.zpl` files; edit it rather than the files themselves.
`backend/tests/test_print_tests.py` checks that every file renders.

## Target printer: ZD420d, firmware V84.20.23Z

The labels are meant for this printer: Link-OS 6.4 with the x.20 ZPL engine. The two manuals
cover firmware x.10–x.13, so some behaviour differs from them:

- `^CI28` (UTF-8), which every design uses, needs x.14 or later. This printer has it. The
  designer warns when a printer's firmware is older.
- The bitmap fonts A–H have the code page 850 characters and € (H, OCR-A: ASCII only). Others
  (ą ć ę ł ń ś ź ż) print blank, and so does the preview. Font B prints lowercase letters as
  capitals, font H leaves them blank. Font 0 (`Z:0.TTF`) has the Polish letters and €, so
  designs do not need the Unicode Swiss 721 font (`E:TT0003M_.TTF`, which this unit also has).
- With `^CI28` a backslash prints as ¢ in every resident font except the OCR fonts E and H
  (p.342); font 0 included.
- Data Matrix keeps `~` as its default escape character (T11: DM1 encodes `_1` literally).
  Designs name their own (a backtick) explicitly anyway.
- Link-OS accepts `^GF` data over 99,999 bytes (T14). Designs split large images into strips
  anyway, so they also print on older firmware.
- `^BY` stays set from one label to the next, and a QR code prints 2 dots less than the `^BY`
  height (10 by default) below its `^FO`: T11 printed 118 dots low after T10's `^BY2,3,120`,
  T17 8 and 58 dots after `^BY…,10` and `^BY…,60`. Designs name `^BY2,3,10` before each QR
  code and start it 8 dots higher.
- QR automatic input (`QA,`) carries UTF-8 text on this firmware (T11 QR2 scans as Polish
  text), although the guide says it cannot (p.84). Designs use byte mode anyway.
- `^BC`'s UCC check digit flag does nothing in mode N (T02d prints 123456), so the designer
  no longer offers it for Code 128.
- In PDF417 data a backslash before a character other than `&` or `\` is dropped (T10d:
  `C:\new` reads "C:new").
- `^FO`/`^FT`/`^FW` take a justification parameter, and `^TB` text blocks exist. Both are
  previewed now and checked by T16.
- `^MT` (print method) now comes from the printer by default rather than from the label: a
  thermal transfer `^MTT` in imported ZPL would stop a printer without ribbon with "Ribbon out".

## How to run them

1. Use 100 × 50 mm die-cut labels on a 203 dpi printer. T14 needs 100 × 150 mm labels. T01 has
   a 300 dpi version. The other tests also work at 300 dpi but print smaller (they are in dots),
   so compare them with a 300 dpi preview.
2. Print T15 first if you are unsure which fonts the printer has: it prints the printer's own
   directory of E: and Z:.
3. Send each file from the app's **Print** page (raw ZPL) and look at its preview at 100%, or
   send it directly: `nc <printer-ip> 9100 < T02_code128.zpl`.
4. Print **T13 last**: it turns on reverse and mirror printing to show that they stick, and
   ends by turning them off again. `^BY` sticks too: T11's QR codes print the `^BY` height of
   the label before it below their brackets.
5. Measure with a steel ruler (8 dots = 1 mm at 203 dpi) and scan the codes with a phone.
   Write the result in the *Printed* column, and add photos if something differs.

On most labels an L-shaped bracket marks the field origin: its inner corner is exactly at the
`^FO` x,y.

## Results

First run: ZD420d V84.20.23Z on 100 × 150 mm labels, scanned at 150 dpi and compared with the
preview in dots (±3 dots). T02 and the 300 dpi T01 were not printed.

Second run: the same printer and labels, T01–T17, scanned at 300 dpi and aligned per label on
the brackets (±1 dot; the scanner's feed changed the vertical scale by up to 2% between labels),
and every code decoded from the scan. The previews have since been changed to match; *Preview*
is what the app shows now.

The *Preview* column is what the app shows (and so expects the printer to print). Where the
guide does not say what the printer does, the *Open question* column says what to look for.
Widths are of the bars only, without the human-readable text.

| Test | What | Preview | Open question | Printed |
|------|------|---------|---------------|---------|
| T01 | Rulers: 0–80 mm across, 0–40 mm down | 80 mm = 640 dots at 203 dpi, 960 dots at 300 dpi (12 dots/mm) | Is a "300 dpi" head 12 dots/mm? | 640 dots exactly at 203 dpi; 300 dpi not printed yet |
| T02a | `^BCN…^FD123456`: no start code, so subset B (p.49) | 202 dots = 25.3 mm | | 202 dots |
| T02b | Same data in automatic mode `,A` | 136 dots = 17.0 mm | | 136 dots |
| T02c | `>;123456`: explicit subset C, as the designer now writes it | 136 dots = 17.0 mm | | 136 dots |
| T02d | `>;123456` with UCC check digit (e=Y) | 136 dots, text 123456: mode N ignores e | Does mode A add the digit? | 136 dots, scans 123456: no Mod 10 digit |
| T02e | `AB>0CD`: a literal `>` | 180 dots, text "AB>CD" | | As previewed |
| T02f/g | `^A0` or `^AD` before `^BC` | Text in that font, starting at the bars' left edge | | That font, left-aligned (the default font A text is centred). Without `^A`: font A magnified by the module width |
| T02h | `ABC123456` in mode N | 268 dots = 33.5 mm | | 268 dots |
| T03 | Gap from bracket to ink for text at N/I/R/B, a rotated barcode and two rotated ^FB blocks | Field box at ^FO; a rotated bar code's text outside it; a block keeps room for all its lines | | Text as previewed. `^BCR`: bars at ^FO, text left of it. The 3-line `^FB` prints its one line two lines to the right of the bracket (x ≈ 766) |
| T04 | Width of H×10: `^A0N,50` / `,50,50` / `,50,40`; height of H; fox line; 8 vs 10 dots | 302 / 302 / 242 dots, H 36 dots, fox 408 dots; 8 prints like 10 | | 302 / 302 / 235, H ≈ 37: w left out = h, font 0's em is h (the preview was 24% small). 8 prints like 10 |
| T05 | Fonts A–H and 0: lowercase in B and H, `\`, ó, ą ł ż € | B in capitals, H lowercase blank; characters a font lacks blank (H: ASCII only); `\` as ¢ except in E and H | | B capitals (ó stays), H lowercase blank. `\` prints ¢ in A, B, D, F, 0 and `\` in E, H. € prints in A, B, D; E prints ó. Font 0 prints ą ę ł ż € |
| T05 bottom | Swiss 721 as `E:TT0003M_.FNT`, `E:TT0003M_.TTF`, `Z:TT0003M_.FNT` | Approximated with the preview font | | Both E: names print Swiss 721 (regular weight, wider than the preview) with Polish letters and €. `Z:TT0003M_.FNT` is missing: font A magnified to 28 × 28, ż ł ć blank |
| T06a | ^FB justified | Lines spread to the 45 mm box, last line left | | As previewed |
| T06b | More text than 2 lines | Extra lines printed over line 2 | | As previewed |
| T06c | Word wider than a 25 mm block | Split with a hyphen at the edge | | SUPERCALIFRAGILI- / STICEXPIALIDOCIO- / US end, as previewed |
| T06d | `\&`, `\\`, `\n` | Line breaks, one backslash printed as ¢, `\n` as a soft hyphen | | As previewed: "C:¢temp¢x", "C:newlot" |
| T06e | Line break in the data without ^FB | "Line ALine B" | | As previewed |
| T06f | ^FT with a 3-line ^FB | Text 2 lines (48 dots = 6 mm) above the guide line (p.138) | | As previewed |
| T07 | ^FR over a black box, white box, reversed barcode | White on black, black on white | | As previewed |
| T08 | Code 39 r2.5 / r3.0, ITF r2.5 / r3.0, Code 39 `^BY3,2.4`, Code 39 `^BY9,2.4` | 230 / 254 / 145 / 162 / 249 / 369 dots | | 229 / 253 / 144 / 160 / 247 / 367: truncated like Table 11 (369, not 378). Text in font A × module width |
| T09a | EAN-13 `12345` | 0000000123457 (padded with zeros) | | As previewed |
| T09b | EAN-13 with 13 digits | 4006381333931 (first 12 kept) | | As previewed |
| T09c/d | UPC-A `123`, EAN-8 `1234` | 000000001236 / 00012348 | | As previewed |
| T09e | EAN-13 human-readable layout | First digit left of the bars, the digit groups against the centre guard, guard bars 12 dots longer | Which font at ^BY3 (25 dots high, 20 apart)? | First digit 9 modules left of the bars (UPC-A: last digit right of them), each group against the centre guard, guards 12–13 dots longer. At ^BY2 the digits are font A × 2; at ^BY3 larger than font A × 3 |
| T10a–c | PDF417 height: `^BY2` h6, `^BY3` h4, no h with `^BY` height 120 | 24 / 16 / 120 dots (4 rows) | | ≈ 24 / 16 / 120: rows are h dots, not h × module width as in the guide |
| T10d | Scan `A\&B \\ C:\new` | "A", line break, "B \ C:new" (6 rows) | | Scans the same; 5 rows (the printer packs it tighter) |
| T11 QR | Scan QR1–4 | QR1 URL; QR2 Polish text (flagged for older firmware); QR3 the same; QR4 the first 17 bytes | | All scan as previewed, 118 dots below the bracket (the `^BY` height from T10, less 2). The printer picks other mask patterns (2, 7, 7, 6) |
| T11 DM | Scan DM1–4 | DM1 `SKU_1 A`; DM2 `~B` taken as an escape; DM3 `A~B`; DM4 (escape #) `SKU_1 A~B` | | Scan as previewed: `_` is not an escape |
| T12 | Box w2 t6; diagonals inside boxes; ellipse t1; rounding 8; ellipse and diagonal 2 dots wide; thick shallow diagonal | Box 6 dots wide; diagonals thickness dots wider than the box; the t1 ellipse 3 dots; the 2-dot ellipse not printed | | As previewed; ^GD runs t dots past the box. `^GE2,100,2` prints nothing; `^GE…,1` prints 3 dots |
| T13 | Label 1 mirrored and reversed; label 2 normal | ^LR and ^PM stick (p.219, p.241); designs now send `^LRN^PMN` | | As previewed |
| T14 | Black band at the bottom (rows 1100–1199) | Shown | | Printed: Link-OS takes more than 99,999 bytes |
| T15 | The printer's directory labels for E: and Z: | Not previewed | | E: `TT0003M_.TTF`. Z: `0.TTF` (font 0), A, B, D, E6–E24, F, G, GS, H6–H24, P–V; no `TT0003M_` |
| T16 | Right justification with `^FO`/`^FT`/`^FW` z = 1; `^TB` text blocks (straight and rotated) next to an `^FB` | The three RIGHT texts end at the vertical line; `^TB` lines 1.25 h apart, printed while their baseline fits (3 and 2) | | As previewed: 38-dot line pitch at h = 30, descenders cut at the block |
| T17 | `^TB` at h 20 and 50; QR after `^BY…,10` and `^BY…,60`; `^GE` t1–t4; `^BCI` and text-above Code 128; EAN-13 h100 | 4 and 2 lines; QR 8 and 58 dots low; ellipses 3, 3, 4, 5 dots; text of both bar codes outside ^FO, above the bars; guards 12 dots longer | Is the text-above gap (8 dots at ^BY2) 4 modules at other widths? | 4 and 2 lines, 25 and 62 dots apart; QR 8 and 58; ellipses 3, 3, 4, 5 dots (inwards); bars at ^FO with the text above; guards 12 dots longer |

The white streaks at x ≈ 404 and 591–593 dots in every black area are dead printhead dots:
they are in both runs, at the same place on the label, although the second scan was fed the
other way round.

Font 0 is previewed with Roboto Condensed. Its capitals are drawn 6% taller to match, and whole
lines come within 2–4% of the printer's (lowercase prints a little wider, spaces wider still), so
a line that only just fits can wrap differently (T06b's overprinted line).

When a printed result differs from the preview, fix the renderer to match the printer and add a
regression test in `backend/tests/test_renderer.py`.
