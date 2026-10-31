import { dotsPerMm } from '../utils/units'
import type {
  Design,
  DesignElement,
  ElementType,
  ImageElement,
  LineElement,
  Rotation,
} from './types'

export const ELEMENT_LABELS: Record<ElementType, string> = {
  text: 'Text',
  barcode: 'Barcode',
  qrcode: 'QR code',
  datamatrix: 'Data Matrix',
  pdf417: 'PDF417',
  box: 'Box',
  line: 'Line',
  ellipse: 'Ellipse',
  image: 'Image',
}

/** Elements whose canvas appearance is rendered by the backend. */
export const RENDERED_TYPES: ElementType[] = ['text', 'barcode', 'qrcode', 'datamatrix', 'pdf417']

let counter = 0

export function newId(): string {
  counter += 1
  return `el-${Date.now().toString(36)}-${counter}`
}

/** Create an element with sensible defaults scaled to the printer resolution. */
export function createElement(
  type: Exclude<ElementType, 'image'>,
  dpi: number,
  position = { x: 20, y: 20 },
): DesignElement {
  const k = dpi / 203
  const s = (value: number) => Math.max(1, Math.round(value * k))
  const base = { id: newId(), x: position.x, y: position.y, rotation: 0 as Rotation }
  switch (type) {
    case 'text':
      return {
        ...base,
        type,
        text: 'Text',
        font: '0',
        font_height: s(30),
        font_width: 0,
        block_width: null,
        block_lines: 1,
        line_spacing: 0,
        align: 'L',
        reverse: false,
      }
    case 'barcode':
      return {
        ...base,
        type,
        symbology: 'code128',
        data: '123456',
        height: s(80),
        module_width: Math.max(1, Math.round(2 * k)),
        ratio: 3,
        show_text: true,
        text_above: false,
        check_digit: false,
      }
    case 'qrcode':
      return {
        ...base,
        type,
        data: 'https://example.com',
        magnification: s(4),
        error_correction: 'M',
      }
    case 'datamatrix':
      return { ...base, type, data: 'DATA', module_size: s(6) }
    case 'pdf417':
      return {
        ...base,
        type,
        data: 'PDF417',
        module_width: s(2),
        row_height: s(6),
        security: 2,
        columns: 4,
      }
    case 'box':
      return {
        ...base,
        type,
        width: s(200),
        height: s(100),
        thickness: s(3),
        color: 'B',
        rounding: 0,
      }
    case 'line':
      return {
        ...base,
        type,
        width: s(200),
        height: s(3),
        thickness: s(3),
        diagonal: 'none',
        color: 'B',
      }
    case 'ellipse':
      return { ...base, type, width: s(100), height: s(100), thickness: s(3), color: 'B' }
  }
}

export function emptyDesign(dpi = 203): Design {
  return { width_mm: 100, height_mm: 50, dpi, elements: [] }
}

/** Template-capable strings of the design (text and barcode data). */
export function designTexts(design: Design): string[] {
  return design.elements.flatMap((element) => {
    if (element.type === 'text') return [element.text]
    if (element.type === 'image') return []
    if ('data' in element) return [element.data]
    return []
  })
}

/**
 * Size of an element's content before rotation, if it is known without rendering.
 * A ^GB box is never thinner than its border (p.155).
 */
export function shapeSize(element: DesignElement): { width: number; height: number } | null {
  switch (element.type) {
    case 'box':
      return {
        width: Math.max(element.width, element.thickness),
        height: Math.max(element.height, element.thickness),
      }
    case 'line':
    case 'ellipse':
    case 'image':
      return { width: element.width, height: element.height }
    default:
      return null
  }
}

/** Whether the canvas draws the element as printed, already rotated (no Konva rotation). */
export function drawnRotated(element: DesignElement): boolean {
  return RENDERED_TYPES.includes(element.type) || isDiagonal(element)
}

export function isDiagonal(element: DesignElement): element is LineElement {
  return element.type === 'line' && element.diagonal !== 'none'
}

/**
 * A diagonal line as the generator writes it (^GDw,h,t,c,o): a quarter turn swaps the width
 * and height and turns "\" into "/". The printer draws it thickness dots wider than w.
 */
export function printedDiagonal(element: LineElement): {
  width: number
  height: number
  lean: 'L' | 'R'
} {
  const quarter = element.rotation === 90 || element.rotation === 270
  const down = (element.diagonal === 'down') !== quarter
  return {
    width: quarter ? element.height : element.width,
    height: quarter ? element.width : element.height,
    lean: down ? 'L' : 'R',
  }
}

/**
 * Offset and rotation for content of size w×h so that its rotated bounding box starts at
 * the group's origin, matching ZPL where ^FO is the top-left corner of the rotated field.
 */
export function rotationTransform(
  rotation: Rotation,
  width: number,
  height: number,
): { x: number; y: number; rotation: number } {
  switch (rotation) {
    case 90:
      return { x: height, y: 0, rotation: 90 }
    case 180:
      return { x: width, y: height, rotation: 180 }
    case 270:
      return { x: 0, y: width, rotation: 270 }
    default:
      return { x: 0, y: 0, rotation: 0 }
  }
}

export function rotatedSize(rotation: Rotation, width: number, height: number) {
  return rotation === 90 || rotation === 270 ? { width: height, height: width } : { width, height }
}

// Bitmap font matrices at 8 dots/mm (height in dots) and the OCR fonts on other printheads.
const BITMAP_HEIGHTS: Record<string, number> = {
  A: 9,
  B: 11,
  C: 18,
  D: 18,
  E: 28,
  F: 26,
  G: 60,
  H: 21,
}
const BITMAP_OVERRIDES: Record<number, Record<string, number>> = {
  6: { E: 21, H: 17 },
  12: { E: 42, H: 34 },
  24: { E: 42, H: 34 },
}

/**
 * Height a bitmap font prints at: a whole multiple (1-10) of its matrix, the nearest to the
 * requested height (^AD,52 prints 54 dots high). Null for scalable fonts.
 */
export function bitmapFontHeight(font: string, height: number, dpi: number): number | null {
  const base = BITMAP_OVERRIDES[dotsPerMm(dpi)]?.[font] ?? BITMAP_HEIGHTS[font]
  if (!base) return null
  return base * Math.max(1, Math.min(10, Math.round(height / base)))
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/**
 * Bring an element's values into the range the printer accepts, like the backend does for
 * designs saved before these limits were enforced (^A, ^GD, ^GE, ^BY for PDF417, ^BQ).
 */
export function normalizeElement(element: DesignElement): DesignElement {
  switch (element.type) {
    case 'text':
      if (element.font !== '0') return element
      return {
        ...element,
        font_height: Math.max(10, element.font_height),
        font_width: element.font_width > 0 ? Math.max(10, element.font_width) : 0,
      }
    case 'qrcode':
      return { ...element, rotation: 0 }
    case 'pdf417':
      return { ...element, module_width: clamp(element.module_width, 2, 10) }
    case 'line':
      if (element.diagonal === 'none') return element
      return { ...element, width: Math.max(3, element.width), height: Math.max(3, element.height) }
    case 'ellipse':
      return {
        ...element,
        width: clamp(element.width, 3, 4095),
        height: clamp(element.height, 3, 4095),
        thickness: clamp(element.thickness, 2, 4095),
      }
    default:
      return element
  }
}

export function normalizeDesign(design: Design): Design {
  return { ...design, elements: design.elements.map(normalizeElement) }
}

/** A 1-bit image resized with nearest-neighbour sampling (packed rows, 1 = black). */
function scaleBitmap(element: ImageElement, factor: number): ImageElement {
  const width = Math.max(1, Math.round(element.width * factor))
  const height = Math.max(1, Math.round(element.height * factor))
  const bytesPerRow = Math.ceil(width / 8)
  const source = Uint8Array.from(atob(element.data), (c) => c.charCodeAt(0))
  const target = new Uint8Array(bytesPerRow * height)
  for (let y = 0; y < height; y++) {
    const sy = Math.min(element.height - 1, Math.floor(y / factor))
    for (let x = 0; x < width; x++) {
      const sx = Math.min(element.width - 1, Math.floor(x / factor))
      if ((source[sy * element.bytes_per_row + (sx >> 3)] >> (7 - (sx & 7))) & 1) {
        target[y * bytesPerRow + (x >> 3)] |= 0x80 >> (x & 7)
      }
    }
  }
  let binary = ''
  for (const byte of target) binary += String.fromCharCode(byte)
  return { ...element, width, height, bytes_per_row: bytesPerRow, data: btoa(binary) }
}

/**
 * The design at another resolution. Elements are laid out in printer dots, so positions and
 * sizes are scaled by the ratio of dots per mm to print at the same physical size; module
 * widths are whole dots, so barcodes change size slightly.
 */
export function rescaleDesign(design: Design, dpi: number): Design {
  const factor = dotsPerMm(dpi) / dotsPerMm(design.dpi)
  if (factor === 1) return { ...design, dpi }
  const s = (value: number, min = 1) => Math.max(min, Math.round(value * factor))
  const elements = design.elements.map((element): DesignElement => {
    const position = { x: Math.round(element.x * factor), y: Math.round(element.y * factor) }
    switch (element.type) {
      case 'text':
        return {
          ...element,
          ...position,
          font_height: s(element.font_height),
          font_width: element.font_width ? s(element.font_width) : 0,
          block_width: element.block_width == null ? null : s(element.block_width),
          line_spacing: Math.round(element.line_spacing * factor),
        }
      case 'barcode':
        return {
          ...element,
          ...position,
          height: s(element.height),
          module_width: clamp(s(element.module_width), 1, 10),
        }
      case 'qrcode':
        return { ...element, ...position, magnification: clamp(s(element.magnification), 1, 10) }
      case 'datamatrix':
        return { ...element, ...position, module_size: clamp(s(element.module_size), 1, 100) }
      case 'pdf417':
        return {
          ...element,
          ...position,
          module_width: clamp(s(element.module_width), 2, 10),
          // Rows are row_height dots high (the printer does not multiply it by the module).
          row_height: clamp(s(element.row_height), 1, 255),
        }
      case 'box':
      case 'line':
      case 'ellipse':
        return {
          ...element,
          ...position,
          width: s(element.width),
          height: s(element.height),
          thickness: s(element.thickness),
        }
      case 'image':
        return { ...scaleBitmap(element, factor), ...position }
    }
  })
  return normalizeDesign({ ...design, dpi, elements })
}

export function insertVariable(
  element: DesignElement,
  name: string,
): Partial<DesignElement> | null {
  const token = `{{${name}}}`
  if (element.type === 'text') return { text: element.text ? `${element.text} ${token}` : token }
  if (element.type === 'image') return null
  if ('data' in element) return { data: element.data ? `${element.data}${token}` : token }
  return null
}
