import {
  Alert,
  Checkbox,
  Group,
  List,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import type { ReactNode } from 'react'

import { dotsToMm } from '../utils/units'
import { ELEMENT_LABELS, RENDERED_TYPES, bitmapFontHeight } from './elements'
import type { DesignerAction } from './store'
import type { DesignElement, Rotation, Symbology } from './types'
import { useElementPreview } from './useElementPreview'

interface PanelProps {
  element: DesignElement
  dpi: number
  /** Variable values the canvas previews use. */
  values?: Record<string, string>
  dispatch: (action: DesignerAction) => void
}

// The ^BY wide-to-narrow ratio only changes variable-ratio symbologies.
const VARIABLE_RATIO: Symbology[] = ['code39', 'itf']
// Code 128 has none: the printer ignores ^BC's UCC check digit in the mode designs use
// (docs/print-tests T02d).
const CHECK_DIGITS: Partial<Record<Symbology, string>> = {
  code39: 'Mod-43 check digit',
  itf: 'Mod-10 check digit',
}

/** Warnings of the element's preview (the same request the canvas makes). */
function PreviewWarnings({ element, dpi, values }: Omit<PanelProps, 'dispatch'>) {
  const [debounced] = useDebouncedValue(element, 200)
  const preview = useElementPreview(debounced, dpi, RENDERED_TYPES.includes(element.type), values)
  const warnings = preview.data?.warnings ?? []
  if (!warnings.length) return null
  return (
    <Alert color="yellow" p="xs" title="Printer differences">
      <List size="xs" spacing={2}>
        {warnings.map((warning) => (
          <List.Item key={warning}>{warning}</List.Item>
        ))}
      </List>
    </Alert>
  )
}

const FONTS = [
  { value: '0', label: '0 – scalable' },
  ...['A', 'B', 'D', 'E', 'F', 'G', 'H'].map((f) => ({ value: f, label: `${f} – bitmap` })),
]

export function PropertiesPanel({ element, dpi, values, dispatch }: PanelProps) {
  function set(patch: Record<string, unknown>, coalesce?: string) {
    dispatch({
      type: 'update',
      id: element.id,
      patch: patch as Partial<DesignElement>,
      coalesce,
    })
  }

  function num(
    label: string,
    field: string,
    value: number,
    opts: {
      min?: number
      max?: number
      step?: number
      decimal?: boolean
      mm?: boolean
      description?: string
      error?: string
    } = {},
  ): ReactNode {
    return (
      <NumberInput
        key={field}
        label={label}
        size="xs"
        min={opts.min ?? 0}
        max={opts.max}
        step={opts.step}
        allowDecimal={opts.decimal ?? false}
        description={opts.description ?? (opts.mm ? `${dotsToMm(value, dpi)} mm` : undefined)}
        error={opts.error}
        value={value}
        onChange={(v) => v !== '' && set({ [field]: Number(v) }, field)}
      />
    )
  }

  function bool(label: string, field: string, value: boolean): ReactNode {
    return (
      <Checkbox
        key={field}
        size="xs"
        label={label}
        checked={value}
        onChange={(e) => set({ [field]: e.currentTarget.checked })}
      />
    )
  }

  function data(value: string, multiline = false): ReactNode {
    const Input = multiline ? Textarea : TextInput
    return (
      <Input
        label={multiline ? 'Text' : 'Data'}
        size="xs"
        autosize={multiline || undefined}
        minRows={multiline ? 2 : undefined}
        description="Use {{name}} for template variables"
        value={value}
        onChange={(e) =>
          set({ [multiline ? 'text' : 'data']: e.currentTarget.value }, multiline ? 'text' : 'data')
        }
      />
    )
  }

  const color = 'color' in element && (
    <Select
      label="Color"
      size="xs"
      data={[
        { value: 'B', label: 'Black' },
        { value: 'W', label: 'White' },
      ]}
      value={element.color}
      onChange={(v) => v && set({ color: v })}
    />
  )

  let specific: ReactNode = null
  switch (element.type) {
    case 'text': {
      // Scalable font 0 takes 10 to 32000 dots (^A, p.12); bitmap fonts print whole multiples.
      const scalable = element.font === '0'
      const printed = bitmapFontHeight(element.font, element.font_height, dpi)
      specific = (
        <>
          {data(element.text, true)}
          <SimpleGrid cols={2}>
            <Select
              label="Font"
              size="xs"
              data={FONTS}
              value={element.font}
              onChange={(v) =>
                v &&
                set({
                  font: v,
                  ...(v === '0' && { font_height: Math.max(10, element.font_height) }),
                  ...(v === '0' &&
                    element.font_width > 0 && { font_width: Math.max(10, element.font_width) }),
                })
              }
            />
            {num('Height (dots)', 'font_height', element.font_height, {
              min: scalable ? 10 : 1,
              description:
                printed != null && printed !== element.font_height
                  ? `prints at ${printed} dots`
                  : undefined,
            })}
            {num('Width (0 = auto)', 'font_width', element.font_width, {
              error:
                scalable && element.font_width > 0 && element.font_width < 10
                  ? 'At least 10 dots'
                  : undefined,
            })}
          </SimpleGrid>
          <Checkbox
            size="xs"
            label="Text block (wrap within a width)"
            checked={element.block_width != null}
            onChange={(e) => set({ block_width: e.currentTarget.checked ? 300 : null })}
          />
          {element.block_width != null && (
            <SimpleGrid cols={2}>
              {num('Block width', 'block_width', element.block_width, { min: 1, mm: true })}
              {num('Max lines', 'block_lines', element.block_lines, { min: 1 })}
              {num('Line spacing', 'line_spacing', element.line_spacing, { min: -999 })}
              <Select
                label="Alignment"
                size="xs"
                data={[
                  { value: 'L', label: 'Left' },
                  { value: 'C', label: 'Center' },
                  { value: 'R', label: 'Right' },
                  { value: 'J', label: 'Justified' },
                ]}
                value={element.align}
                onChange={(v) => v && set({ align: v })}
              />
            </SimpleGrid>
          )}
          {bool('Reverse (inverts what is underneath)', 'reverse', element.reverse)}
        </>
      )
      break
    }
    case 'barcode':
      specific = (
        <>
          <Select
            label="Symbology"
            size="xs"
            data={[
              { value: 'code128', label: 'Code 128' },
              { value: 'code39', label: 'Code 39' },
              { value: 'ean13', label: 'EAN-13' },
              { value: 'ean8', label: 'EAN-8' },
              { value: 'upca', label: 'UPC-A' },
              { value: 'itf', label: 'Interleaved 2 of 5' },
            ]}
            value={element.symbology}
            onChange={(v) => v && set({ symbology: v })}
          />
          {data(element.data)}
          <SimpleGrid cols={3}>
            {num('Height', 'height', element.height, { min: 1, mm: true })}
            {num('Module width', 'module_width', element.module_width, { min: 1, max: 10 })}
            {VARIABLE_RATIO.includes(element.symbology) &&
              num('Ratio', 'ratio', element.ratio, { min: 2, max: 3, step: 0.1, decimal: true })}
          </SimpleGrid>
          <Group>
            {bool('Human-readable text', 'show_text', element.show_text)}
            {bool('Text above', 'text_above', element.text_above)}
            {CHECK_DIGITS[element.symbology] &&
              bool(CHECK_DIGITS[element.symbology]!, 'check_digit', element.check_digit)}
          </Group>
        </>
      )
      break
    case 'qrcode':
      specific = (
        <>
          {data(element.data)}
          <SimpleGrid cols={2}>
            {num('Magnification', 'magnification', element.magnification, { min: 1, max: 10 })}
            <Select
              label="Error correction"
              size="xs"
              data={['L', 'M', 'Q', 'H']}
              value={element.error_correction}
              onChange={(v) => v && set({ error_correction: v })}
            />
          </SimpleGrid>
        </>
      )
      break
    case 'datamatrix':
      specific = (
        <>
          {data(element.data)}
          {num('Module size (dots)', 'module_size', element.module_size, { min: 1 })}
        </>
      )
      break
    case 'pdf417':
      specific = (
        <>
          {data(element.data)}
          <SimpleGrid cols={2}>
            {num('Module width', 'module_width', element.module_width, { min: 2, max: 10 })}
            {num('Row height (dots)', 'row_height', element.row_height, { min: 1, max: 255 })}
            {num('Security level', 'security', element.security, { max: 8 })}
            {num('Columns', 'columns', element.columns, { min: 1, max: 30 })}
          </SimpleGrid>
        </>
      )
      break
    case 'box':
      specific = (
        <SimpleGrid cols={2}>
          {num('Width', 'width', element.width, { min: 1, mm: true })}
          {num('Height', 'height', element.height, { min: 1, mm: true })}
          {num('Thickness', 'thickness', element.thickness, { min: 1 })}
          {num('Rounding (0–8)', 'rounding', element.rounding, { max: 8 })}
          {color}
        </SimpleGrid>
      )
      break
    case 'line': {
      // ^GD needs a box of at least 3 x 3 dots (p.158).
      const minimum = element.diagonal === 'none' ? 1 : 3
      specific = (
        <SimpleGrid cols={2}>
          {num('Width', 'width', element.width, { min: minimum, mm: true })}
          {num('Height', 'height', element.height, { min: minimum, mm: true })}
          {num('Thickness', 'thickness', element.thickness, { min: 1 })}
          <Select
            label="Direction"
            size="xs"
            data={[
              { value: 'none', label: 'Horizontal / vertical' },
              { value: 'down', label: 'Diagonal ↘' },
              { value: 'up', label: 'Diagonal ↗' },
            ]}
            value={element.diagonal}
            onChange={(v) =>
              v &&
              set({
                diagonal: v,
                ...(v !== 'none' && {
                  width: Math.max(3, element.width),
                  height: Math.max(3, element.height),
                }),
              })
            }
          />
          {color}
        </SimpleGrid>
      )
      break
    }
    case 'ellipse':
      // ^GE: width and height 3 to 4095 dots, thickness 2 to 4095 (p.159)
      specific = (
        <SimpleGrid cols={2}>
          {num('Width', 'width', element.width, { min: 3, max: 4095, mm: true })}
          {num('Height', 'height', element.height, { min: 3, max: 4095, mm: true })}
          {num('Thickness', 'thickness', element.thickness, { min: 2, max: 4095 })}
          {color}
        </SimpleGrid>
      )
      break
    case 'image':
      specific = (
        <Text size="sm" c="dimmed">
          {element.width} × {element.height} dots ({dotsToMm(element.width, dpi)} ×{' '}
          {dotsToMm(element.height, dpi)} mm)
        </Text>
      )
      break
  }

  return (
    <Stack gap="xs">
      <Text fw={600}>{ELEMENT_LABELS[element.type]}</Text>
      <TextInput
        label="Name"
        size="xs"
        placeholder="(optional)"
        value={element.name ?? ''}
        onChange={(e) => set({ name: e.currentTarget.value }, 'name')}
      />
      <SimpleGrid cols={2}>
        {num('X (dots)', 'x', element.x, { mm: true })}
        {num('Y (dots)', 'y', element.y, { mm: true })}
      </SimpleGrid>
      {element.type !== 'qrcode' && (
        <div>
          <Text size="xs" fw={500} mb={2}>
            Rotation
          </Text>
          <SegmentedControl
            size="xs"
            fullWidth
            data={['0', '90', '180', '270'].map((v) => ({ value: v, label: `${v}°` }))}
            value={String(element.rotation)}
            onChange={(v) => set({ rotation: Number(v) as Rotation })}
          />
        </div>
      )}
      {specific}
      <PreviewWarnings element={element} dpi={dpi} values={values} />
    </Stack>
  )
}
