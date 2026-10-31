import { useDebouncedValue } from '@mantine/hooks'
import type Konva from 'konva'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Ellipse,
  Group,
  Image as KonvaImage,
  Layer,
  Line,
  Rect,
  Stage,
  Text,
  Transformer,
} from 'react-konva'

import { mmToDots } from '../utils/units'
import {
  RENDERED_TYPES,
  drawnRotated,
  isDiagonal,
  normalizeElement,
  printedDiagonal,
  rotatedSize,
  rotationTransform,
  shapeSize,
} from './elements'
import type { DesignerAction } from './store'
import type { Design, DesignElement, ImageElement } from './types'
import { useElementPreview } from './useElementPreview'

const RESIZABLE = new Set(['box', 'line', 'ellipse'])
const SELECTION_COLOR = '#228be6'

function useHtmlImage(src: string | null | undefined): HTMLImageElement | undefined {
  const [loaded, setLoaded] = useState<{ src: string; image: HTMLImageElement }>()
  useEffect(() => {
    if (!src) return
    const img = new window.Image()
    img.onload = () => setLoaded({ src, image: img })
    img.src = src
  }, [src])
  return src && loaded?.src === src ? loaded.image : undefined
}

function bitmapCanvas(element: ImageElement): HTMLCanvasElement | undefined {
  try {
    const bytes = Uint8Array.from(atob(element.data), (c) => c.charCodeAt(0))
    const canvas = document.createElement('canvas')
    canvas.width = element.width
    canvas.height = element.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined
    const pixels = ctx.createImageData(element.width, element.height)
    for (let y = 0; y < element.height; y++) {
      for (let x = 0; x < element.width; x++) {
        const bit = (bytes[y * element.bytes_per_row + (x >> 3)] >> (7 - (x & 7))) & 1
        const i = (y * element.width + x) * 4
        pixels.data[i + 3] = bit ? 255 : 0 // black ink, transparent paper
      }
    }
    ctx.putImageData(pixels, 0, 0)
    return canvas
  } catch {
    return undefined
  }
}

/** The same image with white ink, for reverse (^FR) fields drawn with "difference". */
function whiteInk(image: HTMLImageElement | undefined): HTMLCanvasElement | undefined {
  if (!image) return undefined
  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.drawImage(image, 0, 0)
  ctx.globalCompositeOperation = 'source-in'
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  return canvas
}

/**
 * The content of an element, drawn from (0, 0): unrotated for shapes and images (the canvas
 * rotates them), as printed for rendered elements and diagonal lines (see `drawnRotated`).
 */
function ElementContent({
  element,
  dpi,
  values,
  onSize,
}: {
  element: DesignElement
  dpi: number
  values: Record<string, string>
  onSize: (size: { width: number; height: number }) => void
}) {
  const rendered = RENDERED_TYPES.includes(element.type)
  const [debounced] = useDebouncedValue(element, 200)
  const preview = useElementPreview(debounced, dpi, rendered, values)
  const previewImage = useHtmlImage(rendered ? preview.data?.image : null)
  const reverse = element.type === 'text' && element.reverse
  const reverseImage = useMemo(
    () => (reverse ? whiteInk(previewImage) : undefined),
    [reverse, previewImage],
  )
  const bitmap = useMemo(
    () => (element.type === 'image' ? bitmapCanvas(element) : undefined),
    [element],
  )

  const size = useMemo(() => {
    if (isDiagonal(element)) {
      const line = printedDiagonal(element)
      return { width: line.width + element.thickness, height: line.height }
    }
    const known = shapeSize(element)
    if (known) return known
    const data = preview.data
    if (data?.image) {
      // The field box of the printer, which includes the ink.
      return {
        width: Math.max(data.field_width, data.offset_x + data.width),
        height: Math.max(data.field_height, data.offset_y + data.height),
      }
    }
    return { width: 160, height: 40 }
  }, [element, preview.data])

  useEffect(() => onSize(size), [size, onSize])

  const ink = (color: 'B' | 'W') => (color === 'W' ? '#ffffff' : '#000000')

  switch (element.type) {
    case 'box': {
      const { width: w, height: h } = size
      const t = element.thickness
      const radius = (element.rounding * Math.min(w, h)) / 16
      const filled = t * 2 >= Math.min(w, h)
      return filled ? (
        <Rect width={w} height={h} fill={ink(element.color)} cornerRadius={radius} />
      ) : (
        <Rect
          x={t / 2}
          y={t / 2}
          width={w - t}
          height={h - t}
          stroke={ink(element.color)}
          strokeWidth={t}
          cornerRadius={Math.max(0, radius - t / 2)}
        />
      )
    }
    case 'line': {
      if (element.diagonal === 'none')
        return <Rect width={element.width} height={element.height} fill={ink(element.color)} />
      // Drawn as printed, like the renderer draws ^GD.
      const { width: w, height: h, lean } = printedDiagonal(element)
      const t = element.thickness
      const points = lean === 'R' ? [0, h, t, h, w + t, 0, w, 0] : [0, 0, t, 0, w + t, h, w, h]
      return <Line points={points} closed fill={ink(element.color)} />
    }
    case 'ellipse': {
      const { width: w, height: h, thickness: t } = element
      const filled = t * 2 >= Math.min(w, h)
      return filled ? (
        <Ellipse x={w / 2} y={h / 2} radiusX={w / 2} radiusY={h / 2} fill={ink(element.color)} />
      ) : (
        <Ellipse
          x={w / 2}
          y={h / 2}
          radiusX={(w - t) / 2}
          radiusY={(h - t) / 2}
          stroke={ink(element.color)}
          strokeWidth={t}
        />
      )
    }
    case 'image':
      return bitmap ? (
        <KonvaImage image={bitmap} width={element.width} height={element.height} />
      ) : (
        <Rect width={element.width} height={element.height} stroke="#fa5252" dash={[6, 4]} />
      )
    default:
      if (previewImage && preview.data?.image) {
        // A reverse field inverts what is underneath (^FR), so white ink is "differenced".
        return (
          <KonvaImage
            image={reverseImage ?? previewImage}
            globalCompositeOperation={reverseImage ? 'difference' : 'source-over'}
            x={preview.data.offset_x}
            y={preview.data.offset_y}
            width={preview.data.width}
            height={preview.data.height}
          />
        )
      }
      return (
        <Group>
          <Rect width={size.width} height={size.height} stroke="#868e96" dash={[6, 4]} />
          <Text
            text={'data' in element ? element.data : element.type === 'text' ? element.text : ''}
            fontSize={Math.min(24, size.height - 8)}
            x={4}
            y={4}
            fill="#868e96"
          />
        </Group>
      )
  }
}

function CanvasElement({
  element,
  dpi,
  values,
  zoom,
  selected,
  grid,
  dispatch,
  registerNode,
}: {
  element: DesignElement
  dpi: number
  values: Record<string, string>
  zoom: number
  selected: boolean
  grid: number | null
  dispatch: (action: DesignerAction) => void
  registerNode: (id: string, node: Konva.Group | null) => void
}) {
  const [size, setSize] = useState({ width: 1, height: 1 })
  // Rendered elements and diagonal lines arrive rotated; the rest is rotated here.
  const rotation = drawnRotated(element) ? 0 : element.rotation
  const transform = rotationTransform(rotation, size.width, size.height)
  const bounds = rotatedSize(rotation, size.width, size.height)
  const snap = (value: number) => (grid ? Math.round(value / grid) * grid : Math.round(value))

  return (
    <Group
      ref={(node) => registerNode(element.id, node)}
      x={element.x}
      y={element.y}
      draggable
      onMouseDown={(e) => {
        e.cancelBubble = true
        dispatch({ type: 'select', id: element.id })
      }}
      onTap={() => dispatch({ type: 'select', id: element.id })}
      onDragEnd={(e) => {
        const node = e.target
        const x = Math.max(0, snap(node.x()))
        const y = Math.max(0, snap(node.y()))
        node.position({ x, y })
        dispatch({ type: 'update', id: element.id, patch: { x, y } })
      }}
      onTransformEnd={(e) => {
        const node = e.target
        let visualW = Math.max(1, Math.round(bounds.width * node.scaleX()))
        const visualH = Math.max(1, Math.round(bounds.height * node.scaleY()))
        node.scale({ x: 1, y: 1 })
        // A diagonal line is drawn as printed: thickness dots wider than its width.
        if (isDiagonal(element)) visualW = Math.max(3, visualW - element.thickness)
        const swap = element.rotation === 90 || element.rotation === 270
        // Keep the size within what the printer accepts (e.g. ^GE 3-4095, ^GD at least 3).
        const resized = normalizeElement({
          ...element,
          width: swap ? visualH : visualW,
          height: swap ? visualW : visualH,
        } as DesignElement) as Extract<DesignElement, { width: number }>
        dispatch({
          type: 'update',
          id: element.id,
          patch: {
            x: node.x(),
            y: node.y(),
            width: resized.width,
            height: resized.height,
          } as Partial<DesignElement>,
        })
      }}
    >
      {/* Transparent hit area so thin shapes and text are easy to grab. */}
      <Rect width={bounds.width} height={bounds.height} fill="rgba(0,0,0,0)" />
      <Group x={transform.x} y={transform.y} rotation={transform.rotation}>
        <ElementContent element={element} dpi={dpi} values={values} onSize={setSize} />
      </Group>
      {selected && (
        <Rect
          width={bounds.width}
          height={bounds.height}
          stroke={SELECTION_COLOR}
          strokeWidth={1 / zoom}
          dash={[4 / zoom, 3 / zoom]}
          listening={false}
        />
      )}
    </Group>
  )
}

interface DesignCanvasProps {
  design: Design
  /** Values for the canvas previews, e.g. the variables' defaults. */
  values?: Record<string, string>
  selectedId: string | null
  zoom: number
  gridDots: number | null
  showGrid: boolean
  dispatch: (action: DesignerAction) => void
}

const NO_VALUES: Record<string, string> = {}

export function DesignCanvas({
  design,
  values = NO_VALUES,
  selectedId,
  zoom,
  gridDots,
  showGrid,
  dispatch,
}: DesignCanvasProps) {
  const width = mmToDots(design.width_mm, design.dpi)
  const height = mmToDots(design.height_mm, design.dpi)
  const nodes = useRef(new Map<string, Konva.Group>())
  const transformer = useRef<Konva.Transformer>(null)
  const selected = design.elements.find((el) => el.id === selectedId)

  useEffect(() => {
    const tr = transformer.current
    if (!tr) return
    const node = selected && RESIZABLE.has(selected.type) ? nodes.current.get(selected.id) : null
    tr.nodes(node ? [node] : [])
    tr.getLayer()?.batchDraw()
  }, [selected])

  const gridLines = useMemo(() => {
    if (!showGrid || !gridDots) return []
    const lines: number[][] = []
    for (let x = gridDots; x < width; x += gridDots) lines.push([x, 0, x, height])
    for (let y = gridDots; y < height; y += gridDots) lines.push([0, y, width, y])
    return lines
  }, [showGrid, gridDots, width, height])

  return (
    <Stage
      width={width * zoom}
      height={height * zoom}
      scaleX={zoom}
      scaleY={zoom}
      onMouseDown={(e) => {
        if (e.target === e.target.getStage() || e.target.name() === 'paper') {
          dispatch({ type: 'select', id: null })
        }
      }}
      style={{ boxShadow: '0 1px 6px rgba(0,0,0,.25)', background: '#fff' }}
    >
      <Layer>
        <Rect name="paper" width={width} height={height} fill="#ffffff" />
        {gridLines.map((points, i) => (
          <Line key={i} points={points} stroke="#e9ecef" strokeWidth={1 / zoom} listening={false} />
        ))}
        {design.elements.map((element) => (
          <CanvasElement
            key={element.id}
            element={element}
            dpi={design.dpi}
            values={values}
            zoom={zoom}
            selected={element.id === selectedId}
            grid={showGrid ? gridDots : null}
            dispatch={dispatch}
            registerNode={(id, node) => {
              if (node) nodes.current.set(id, node)
              else nodes.current.delete(id)
            }}
          />
        ))}
        <Transformer
          ref={transformer}
          rotateEnabled={false}
          keepRatio={false}
          ignoreStroke
          borderStroke={SELECTION_COLOR}
          anchorStroke={SELECTION_COLOR}
          anchorSize={8}
          boundBoxFunc={(oldBox, newBox) =>
            newBox.width < 2 || newBox.height < 2 ? oldBox : newBox
          }
        />
      </Layer>
    </Stage>
  )
}
