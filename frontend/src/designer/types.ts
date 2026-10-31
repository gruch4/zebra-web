export type Rotation = 0 | 90 | 180 | 270

interface BaseElement {
  id: string
  name?: string
  x: number
  y: number
  rotation: Rotation
}

export interface TextElement extends BaseElement {
  type: 'text'
  text: string
  font: string
  font_height: number
  font_width: number
  block_width: number | null
  block_lines: number
  line_spacing: number
  align: 'L' | 'C' | 'R' | 'J'
  reverse: boolean
}

export type Symbology = 'code128' | 'code39' | 'ean13' | 'ean8' | 'upca' | 'itf'

export interface BarcodeElement extends BaseElement {
  type: 'barcode'
  symbology: Symbology
  data: string
  height: number
  module_width: number
  ratio: number
  show_text: boolean
  text_above: boolean
  check_digit: boolean
}

export interface QrCodeElement extends BaseElement {
  type: 'qrcode'
  data: string
  magnification: number
  error_correction: 'L' | 'M' | 'Q' | 'H'
}

export interface DataMatrixElement extends BaseElement {
  type: 'datamatrix'
  data: string
  module_size: number
}

export interface Pdf417Element extends BaseElement {
  type: 'pdf417'
  data: string
  module_width: number
  row_height: number
  security: number
  columns: number
}

export type LineColor = 'B' | 'W'

export interface BoxElement extends BaseElement {
  type: 'box'
  width: number
  height: number
  thickness: number
  color: LineColor
  rounding: number
}

export interface LineElement extends BaseElement {
  type: 'line'
  width: number
  height: number
  thickness: number
  diagonal: 'none' | 'down' | 'up'
  color: LineColor
}

export interface EllipseElement extends BaseElement {
  type: 'ellipse'
  width: number
  height: number
  thickness: number
  color: LineColor
}

export interface ImageElement extends BaseElement {
  type: 'image'
  width: number
  height: number
  bytes_per_row: number
  data: string
}

export type DesignElement =
  | TextElement
  | BarcodeElement
  | QrCodeElement
  | DataMatrixElement
  | Pdf417Element
  | BoxElement
  | LineElement
  | EllipseElement
  | ImageElement

export type ElementType = DesignElement['type']

export interface Design {
  width_mm: number
  height_mm: number
  dpi: number
  elements: DesignElement[]
}
