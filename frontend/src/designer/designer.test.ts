import { describe, expect, it } from 'vitest'

import {
  bitmapFontHeight,
  createElement,
  designTexts,
  drawnRotated,
  emptyDesign,
  insertVariable,
  normalizeDesign,
  printedDiagonal,
  rescaleDesign,
  rotatedSize,
  rotationTransform,
  shapeSize,
} from './elements'
import { designerReducer, initialState } from './store'
import type {
  BarcodeElement,
  BoxElement,
  EllipseElement,
  ImageElement,
  LineElement,
  Pdf417Element,
  TextElement,
} from './types'

function text(id: string, x = 0, y = 0): TextElement {
  return { ...(createElement('text', 203) as TextElement), id, x, y }
}

describe('designer store', () => {
  it('adds, selects, updates and removes elements', () => {
    let state = initialState(emptyDesign())
    state = designerReducer(state, { type: 'add', element: text('a') })
    expect(state.selectedId).toBe('a')
    state = designerReducer(state, { type: 'update', id: 'a', patch: { x: -5, y: 12.6 } })
    expect(state.design.elements[0]).toMatchObject({ x: 0, y: 13 })
    state = designerReducer(state, { type: 'remove', id: 'a' })
    expect(state.design.elements).toHaveLength(0)
    expect(state.selectedId).toBeNull()
  })

  it('supports undo and redo', () => {
    let state = initialState(emptyDesign())
    state = designerReducer(state, { type: 'add', element: text('a') })
    state = designerReducer(state, { type: 'update', id: 'a', patch: { x: 50 } })
    state = designerReducer(state, { type: 'undo' })
    expect(state.design.elements[0].x).toBe(0)
    state = designerReducer(state, { type: 'undo' })
    expect(state.design.elements).toHaveLength(0)
    state = designerReducer(state, { type: 'redo' })
    state = designerReducer(state, { type: 'redo' })
    expect(state.design.elements[0].x).toBe(50)
    // A new change clears the redo stack.
    state = designerReducer(state, { type: 'undo' })
    state = designerReducer(state, { type: 'update', id: 'a', patch: { y: 5 } })
    expect(state.future).toHaveLength(0)
  })

  it('coalesces consecutive edits of the same field into one undo step', () => {
    let state = initialState(emptyDesign())
    state = designerReducer(state, { type: 'add', element: text('a') })
    for (const value of ['H', 'He', 'Hel']) {
      state = designerReducer(state, {
        type: 'update',
        id: 'a',
        patch: { text: value },
        coalesce: 'text',
      })
    }
    expect(state.past).toHaveLength(2)
    state = designerReducer(state, { type: 'undo' })
    expect((state.design.elements[0] as TextElement).text).toBe('Text')
  })

  it('duplicates, reorders, nudges and changes the label size', () => {
    let state = initialState(emptyDesign())
    state = designerReducer(state, { type: 'add', element: text('a', 10, 10) })
    state = designerReducer(state, { type: 'duplicate', id: 'a', newId: 'b' })
    expect(state.design.elements.map((e) => [e.id, e.x])).toEqual([
      ['a', 10],
      ['b', 20],
    ])
    state = designerReducer(state, { type: 'reorder', id: 'a', direction: 'up' })
    expect(state.design.elements.map((e) => e.id)).toEqual(['b', 'a'])
    state = designerReducer(state, { type: 'nudge', id: 'a', dx: -20, dy: 5 })
    expect(state.design.elements[1]).toMatchObject({ x: 0, y: 15 })
    state = designerReducer(state, { type: 'setLabel', patch: { width_mm: 60 } })
    expect(state.design.width_mm).toBe(60)
  })
})

describe('element helpers', () => {
  it('scales defaults with resolution', () => {
    const low = createElement('text', 203) as TextElement
    const high = createElement('text', 300) as TextElement
    expect(high.font_height).toBeGreaterThan(low.font_height)
  })

  it('places rotated content inside its bounding box like ^FO', () => {
    expect(rotationTransform(0, 100, 20)).toEqual({ x: 0, y: 0, rotation: 0 })
    expect(rotationTransform(90, 100, 20)).toEqual({ x: 20, y: 0, rotation: 90 })
    expect(rotationTransform(180, 100, 20)).toEqual({ x: 100, y: 20, rotation: 180 })
    expect(rotationTransform(270, 100, 20)).toEqual({ x: 0, y: 100, rotation: 270 })
    expect(rotatedSize(90, 100, 20)).toEqual({ width: 20, height: 100 })
  })

  it('draws shapes the size the printer does', () => {
    // ^GB is never thinner than its border.
    const box = { ...(createElement('box', 203) as BoxElement), width: 2, thickness: 6 }
    expect(shapeSize(box)).toEqual({ width: 6, height: 100 })
    // ^GD: a quarter turn swaps width and height and turns "\" into "/".
    const line = {
      ...(createElement('line', 203) as LineElement),
      width: 100,
      height: 60,
      diagonal: 'down' as const,
    }
    expect(printedDiagonal(line)).toEqual({ width: 100, height: 60, lean: 'L' })
    expect(printedDiagonal({ ...line, rotation: 90 })).toEqual({
      width: 60,
      height: 100,
      lean: 'R',
    })
    expect(printedDiagonal({ ...line, rotation: 180 })).toEqual({
      width: 100,
      height: 60,
      lean: 'L',
    })
    // Rendered elements and diagonal lines come rotated as printed.
    expect(drawnRotated(text('a'))).toBe(true)
    expect(drawnRotated(line)).toBe(true)
    expect(drawnRotated(box)).toBe(false)
  })

  it('shows the height bitmap fonts print at', () => {
    expect(bitmapFontHeight('D', 52, 203)).toBe(54) // ^AD,52 prints like ^AD,54
    expect(bitmapFontHeight('A', 5000, 203)).toBe(90) // at most 10 times
    expect(bitmapFontHeight('E', 28, 300)).toBe(42) // OCR-B is 42 dots high at 12 dots/mm
    expect(bitmapFontHeight('0', 30, 203)).toBeNull()
  })

  it('brings values from older designs into the printer limits', () => {
    const ellipse = { ...(createElement('ellipse', 203) as EllipseElement), thickness: 1 }
    const pdf417 = { ...(createElement('pdf417', 203) as Pdf417Element), module_width: 1 }
    const tiny = { ...text('t'), font_height: 5, font_width: 3 }
    const design = normalizeDesign({ ...emptyDesign(), elements: [ellipse, pdf417, tiny] })
    expect(design.elements[0]).toMatchObject({ thickness: 2 })
    expect(design.elements[1]).toMatchObject({ module_width: 2 })
    expect(design.elements[2]).toMatchObject({ font_height: 10, font_width: 10 })
  })

  it('rescales a design to keep its size at another resolution', () => {
    const box = { ...(createElement('box', 203) as BoxElement), x: 80, y: 40, width: 200 }
    const barcode = { ...(createElement('barcode', 203) as BarcodeElement), module_width: 2 }
    // 2 x 2 dots, black top-left
    const image: ImageElement = {
      id: 'i',
      type: 'image',
      x: 8,
      y: 8,
      rotation: 0,
      width: 2,
      height: 2,
      bytes_per_row: 1,
      data: btoa(String.fromCharCode(0x80, 0x00)),
    }
    const pdf417 = createElement('pdf417', 203) as Pdf417Element
    const design = { ...emptyDesign(203), elements: [box, barcode, image, pdf417] }
    // 8 dots/mm at 203 dpi, 12 at 300: everything grows by 1.5.
    const scaled = rescaleDesign(design, 300)
    expect(scaled.dpi).toBe(300)
    expect(scaled.elements[0]).toMatchObject({ x: 120, y: 60, width: 300 })
    expect(scaled.elements[1]).toMatchObject({ module_width: 3 })
    expect(scaled.elements[2]).toMatchObject({ x: 12, y: 12, width: 3, height: 3 })
    const bytes = atob((scaled.elements[2] as ImageElement).data)
    // The black corner pixel covers 2 x 2 of the 3 x 3 dots.
    expect([...bytes].map((c) => c.charCodeAt(0))).toEqual([0xc0, 0xc0, 0x00])
    // PDF417 rows are in dots, so they grow too (6 -> 9).
    expect(scaled.elements[3]).toMatchObject({ module_width: 3, row_height: 9 })
    // Changing the resolution in the designer rescales the design.
    let state = initialState(design)
    state = designerReducer(state, { type: 'setLabel', patch: { dpi: 300 } })
    expect(state.design.elements[0]).toMatchObject({ x: 120, width: 300 })
  })

  it('inserts variables into text and data fields', () => {
    expect(insertVariable(text('a'), 'name')).toEqual({ text: 'Text {{name}}' })
    expect(insertVariable(createElement('qrcode', 203), 'url')).toEqual({
      data: 'https://example.com{{url}}',
    })
    expect(insertVariable(createElement('box', 203), 'x')).toBeNull()
    const design = { ...emptyDesign(), elements: [text('a'), createElement('box', 203)] }
    expect(designTexts(design)).toEqual(['Text'])
  })
})
