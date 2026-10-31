import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  CopyButton,
  Grid,
  Group,
  Modal,
  NumberInput,
  ScrollArea,
  Select,
  Slider,
  Stack,
  Switch,
  Tabs,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { useDebouncedValue, useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconArrowBackUp,
  IconArrowForwardUp,
  IconBarcode,
  IconCircle,
  IconDeviceFloppy,
  IconLetterT,
  IconLine,
  IconPhoto,
  IconPrinter,
  IconQrcode,
  IconSquare,
  IconTable,
} from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { api, apiBlob } from '../api/client'
import { useLabel, usePrint, usePrinterSettings, useSaveLabel } from '../api/hooks'
import type { GraphicResult, Printer, VariableDef } from '../api/types'
import { PreviewPanel } from '../components/PreviewPanel'
import { useSelectedPrinter } from '../components/printerContext'
import { SaveLabelModal, type LabelDetails } from '../components/SaveLabelModal'
import { usePngPreview } from '../components/usePngPreview'
import { PrintForm } from '../components/PrintForm'
import { notifyPrint } from '../utils/notify'
import { DesignCanvas } from '../designer/DesignCanvas'
import { createElement, designTexts, emptyDesign, newId } from '../designer/elements'
import { ImageImportModal } from '../designer/ImageImportModal'
import { PropertiesPanel } from '../designer/PropertiesPanel'
import { LayersPanel, VariablesPanel } from '../designer/SidePanels'
import { useDesigner } from '../designer/store'
import type { Design, ElementType } from '../designer/types'
import { errorMessage } from '../utils/format'
import { extractVariables, initialValues, mergeVariables } from '../utils/templating'
import { dotsToMm, mmToDots } from '../utils/units'

const TOOLS: { type: Exclude<ElementType, 'image'>; label: string; icon: typeof IconLetterT }[] = [
  { type: 'text', label: 'Text', icon: IconLetterT },
  { type: 'barcode', label: 'Barcode', icon: IconBarcode },
  { type: 'qrcode', label: 'QR code', icon: IconQrcode },
  { type: 'datamatrix', label: 'Data Matrix', icon: IconTable },
  { type: 'pdf417', label: 'PDF417', icon: IconBarcode },
  { type: 'box', label: 'Box', icon: IconSquare },
  { type: 'line', label: 'Line', icon: IconLine },
  { type: 'ellipse', label: 'Ellipse', icon: IconCircle },
]

/** Firmware before x.14 has no ^CI28 (UTF-8), which designs use for non-ASCII text. */
function lacksUtf8(firmware: string | null): boolean {
  const version = /V?\d+\.(\d+)/i.exec(firmware ?? '')
  return version != null && Number(version[1]) < 14
}

/** Differences between the design and the selected printer that change the printout. */
function PrinterMismatch({ design, printer }: { design: Design; printer: Printer }) {
  const settings = usePrinterSettings(printer.id, printer.dpi === design.dpi)
  const printWidth = Number(
    settings.data?.settings.find((setting) => setting.name === 'print_width')?.value,
  )
  const widthDots = mmToDots(design.width_mm, design.dpi)
  const warnings: string[] = []
  if (printer.dpi !== design.dpi) {
    warnings.push(
      `This design is for ${design.dpi} dpi but ${printer.name} prints at ${printer.dpi} dpi: ` +
        'everything would print at a different size, so printing is refused. Change the ' +
        'resolution (the design is rescaled to keep its size) or select another printer.',
    )
  } else if (printWidth > 0 && widthDots > printWidth) {
    warnings.push(
      `The label is ${design.width_mm} mm wide but ${printer.name} prints at most ` +
        `${dotsToMm(printWidth, printer.dpi)} mm; the rest is cut off.`,
    )
  }
  if (lacksUtf8(printer.firmware) && designTexts(design).some((text) => /[^ -~\s]/.test(text))) {
    warnings.push(
      `${printer.name} runs firmware ${printer.firmware}, which predates UTF-8 (^CI28, ` +
        'firmware x.14): non-ASCII characters will not print as shown.',
    )
  }
  if (!warnings.length) return null
  return (
    <Alert color="orange" p="xs">
      <Stack gap={4}>
        {warnings.map((warning) => (
          <Text key={warning} size="sm">
            {warning}
          </Text>
        ))}
      </Stack>
    </Alert>
  )
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}

export function DesignerPage() {
  const navigate = useNavigate()
  const params = useParams()
  const labelId = params.labelId ? Number(params.labelId) : null
  const { data: label } = useLabel(labelId)
  const { printer } = useSelectedPrinter()
  const [state, dispatch] = useDesigner(emptyDesign(printer?.dpi ?? 203))
  const { design, selectedId } = state
  const selected = design.elements.find((el) => el.id === selectedId)
  const [variableMeta, setVariableMeta] = useState<VariableDef[]>([])
  const [zoom, setZoom] = useState(1)
  const [showGrid, setShowGrid] = useState(true)
  const [tab, setTab] = useState<string | null>('canvas')
  const [sideTab, setSideTab] = useState<string | null>('properties')
  const [saveOpened, saveModal] = useDisclosure()
  const [imageOpened, imageModal] = useDisclosure()
  const [printOpened, printModal] = useDisclosure()
  const saveLabel = useSaveLabel()
  const canvasBox = useRef<HTMLDivElement>(null)
  const loadedId = useRef<number | null>(null)

  useEffect(() => {
    if (label?.design && loadedId.current !== label.id) {
      loadedId.current = label.id
      dispatch({ type: 'load', design: label.design })
      setVariableMeta(label.variables)
    }
  }, [label, dispatch])

  useEffect(() => {
    if (labelId === null && loadedId.current !== null) {
      loadedId.current = null
      dispatch({ type: 'load', design: emptyDesign(printer?.dpi ?? 203) })
      setVariableMeta([])
    }
  }, [labelId, printer, dispatch])

  const widthDots = mmToDots(design.width_mm, design.dpi)

  // Fit the label into the available width when the size changes.
  useEffect(() => {
    const available = (canvasBox.current?.clientWidth ?? 800) - 32
    setZoom(Math.max(0.2, Math.min(3, Math.floor((available / widthDots) * 20) / 20)))
  }, [widthDots])

  const variables = useMemo(
    () => mergeVariables(extractVariables(...designTexts(design)), variableMeta),
    [design, variableMeta],
  )

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (isTyping(event.target)) return
      const mod = event.metaKey || event.ctrlKey
      if (mod && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        dispatch({ type: event.shiftKey ? 'redo' : 'undo' })
      } else if (mod && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        dispatch({ type: 'redo' })
      } else if (selectedId && mod && event.key.toLowerCase() === 'd') {
        event.preventDefault()
        dispatch({ type: 'duplicate', id: selectedId, newId: newId() })
      } else if (selectedId && (event.key === 'Delete' || event.key === 'Backspace')) {
        event.preventDefault()
        dispatch({ type: 'remove', id: selectedId })
      } else if (selectedId && event.key.startsWith('Arrow')) {
        event.preventDefault()
        const step = event.shiftKey ? 10 : 1
        const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0
        const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0
        dispatch({ type: 'nudge', id: selectedId, dx, dy })
      } else if (event.key === 'Escape') {
        dispatch({ type: 'select', id: null })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, dispatch])

  const [debouncedDesign] = useDebouncedValue(design, 400)
  const generated = useQuery({
    queryKey: ['designer-zpl', debouncedDesign],
    queryFn: () =>
      api<{ zpl: string; variables: string[] }>('/api/designer/zpl', { json: debouncedDesign }),
    placeholderData: keepPreviousData,
  })
  // The server fills in the defaults like printing does; variables without one stay visible.
  const defaults = useMemo(
    () => Object.fromEntries(Object.entries(initialValues(variables)).filter(([, v]) => v)),
    [variables],
  )
  // The preview is generated with the defaults like a print, so data is encoded as printed.
  const previewZpl = useQuery({
    queryKey: ['designer-preview-zpl', debouncedDesign, defaults],
    queryFn: () =>
      api<{ zpl: string }>('/api/designer/preview-zpl', {
        json: { design: debouncedDesign, values: defaults },
      }),
    enabled: tab === 'preview',
    placeholderData: keepPreviousData,
  })
  const rendered = usePngPreview(
    ['designer-render', previewZpl.data?.zpl, design.dpi],
    () => apiBlob('/api/render', { json: { zpl: previewZpl.data?.zpl ?? '', dpi: design.dpi } }),
    tab === 'preview' && !!previewZpl.data,
  )

  function addElement(type: Exclude<ElementType, 'image'>) {
    const offset = (design.elements.length % 10) * 10
    dispatch({
      type: 'add',
      element: createElement(type, design.dpi, { x: 20 + offset, y: 20 + offset }),
    })
    setSideTab('properties')
  }

  function addImage(graphic: GraphicResult) {
    dispatch({
      type: 'add',
      element: {
        id: newId(),
        type: 'image',
        x: 20,
        y: 20,
        rotation: 0,
        width: graphic.width,
        height: graphic.height,
        bytes_per_row: graphic.bytes_per_row,
        data: graphic.data,
      },
    })
  }

  async function save(details?: LabelDetails) {
    try {
      if (labelId && !details) {
        await saveLabel.mutateAsync({ id: labelId, body: { design, variables } })
        notifications.show({ color: 'green', message: `Saved "${label?.name}"` })
        return
      }
      const created = await saveLabel.mutateAsync({
        body: { ...details!, kind: 'design', design, variables },
      })
      saveModal.close()
      notifications.show({ color: 'green', message: `Saved "${created.name}" to the archive` })
      loadedId.current = created.id
      navigate(`/designer/${created.id}`, { replace: true })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Saving failed', message: errorMessage(error) })
    }
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={2}>Label designer</Title>
          {label && <Badge variant="light">{label.name}</Badge>}
        </Group>
        <Group gap="xs">
          <Tooltip label="Undo (Ctrl+Z)">
            <ActionIcon
              variant="default"
              size="lg"
              aria-label="Undo"
              disabled={state.past.length === 0}
              onClick={() => dispatch({ type: 'undo' })}
            >
              <IconArrowBackUp size={18} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label="Redo (Ctrl+Shift+Z)">
            <ActionIcon
              variant="default"
              size="lg"
              aria-label="Redo"
              disabled={state.future.length === 0}
              onClick={() => dispatch({ type: 'redo' })}
            >
              <IconArrowForwardUp size={18} />
            </ActionIcon>
          </Tooltip>
          {labelId && (
            <Button
              variant="default"
              leftSection={<IconDeviceFloppy size={16} />}
              loading={saveLabel.isPending}
              onClick={() => save()}
            >
              Save
            </Button>
          )}
          <Button
            variant="default"
            leftSection={<IconDeviceFloppy size={16} />}
            onClick={saveModal.open}
          >
            {labelId ? 'Save as new' : 'Save to archive'}
          </Button>
          <Button
            leftSection={<IconPrinter size={16} />}
            onClick={printModal.open}
            disabled={!printer}
          >
            Print
          </Button>
        </Group>
      </Group>

      <Card withBorder p="xs">
        <Group gap="md" align="flex-end">
          <NumberInput
            label="Width (mm)"
            size="xs"
            w={100}
            min={5}
            max={1000}
            decimalScale={1}
            value={design.width_mm}
            onChange={(v) =>
              v !== '' && dispatch({ type: 'setLabel', patch: { width_mm: Number(v) } })
            }
          />
          <NumberInput
            label="Height (mm)"
            size="xs"
            w={100}
            min={5}
            max={4000}
            decimalScale={1}
            value={design.height_mm}
            onChange={(v) =>
              v !== '' && dispatch({ type: 'setLabel', patch: { height_mm: Number(v) } })
            }
          />
          <Select
            label="Resolution"
            size="xs"
            w={110}
            data={['203', '300', '600'].map((v) => ({ value: v, label: `${v} dpi` }))}
            value={String(design.dpi)}
            onChange={(v) => v && dispatch({ type: 'setLabel', patch: { dpi: Number(v) } })}
          />
          <Stack gap={2} w={160}>
            <Text size="xs" fw={500}>
              Zoom {Math.round(zoom * 100)}%
            </Text>
            <Slider
              size="sm"
              min={0.2}
              max={4}
              step={0.05}
              value={zoom}
              onChange={setZoom}
              label={null}
            />
          </Stack>
          <Switch
            size="xs"
            label="Grid & snap (1 mm)"
            checked={showGrid}
            onChange={(e) => setShowGrid(e.currentTarget.checked)}
          />
          <Text size="xs" c="dimmed">
            {widthDots} × {mmToDots(design.height_mm, design.dpi)} dots
          </Text>
        </Group>
      </Card>

      {printer && <PrinterMismatch design={design} printer={printer} />}

      <Grid>
        <Grid.Col span={{ base: 12, md: 'content' }}>
          <Card withBorder p="xs">
            <Stack gap={4}>
              {TOOLS.map(({ type, label: toolLabel, icon: Icon }) => (
                <Button
                  key={type}
                  variant="subtle"
                  size="xs"
                  justify="flex-start"
                  leftSection={<Icon size={16} />}
                  onClick={() => addElement(type)}
                >
                  {toolLabel}
                </Button>
              ))}
              <Button
                variant="subtle"
                size="xs"
                justify="flex-start"
                leftSection={<IconPhoto size={16} />}
                onClick={imageModal.open}
              >
                Image / logo
              </Button>
            </Stack>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 'auto' }} miw={0}>
          <Tabs value={tab} onChange={setTab}>
            <Tabs.List mb="xs">
              <Tabs.Tab value="canvas">Canvas</Tabs.Tab>
              <Tabs.Tab value="zpl">Generated ZPL</Tabs.Tab>
              <Tabs.Tab value="preview">Rendered preview</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="canvas">
              <ScrollArea
                ref={canvasBox}
                p="md"
                bg="var(--mantine-color-gray-light)"
                style={{ borderRadius: 8 }}
                h={560}
              >
                <DesignCanvas
                  design={design}
                  values={defaults}
                  selectedId={selectedId}
                  zoom={zoom}
                  gridDots={mmToDots(1, design.dpi)}
                  showGrid={showGrid}
                  dispatch={dispatch}
                />
              </ScrollArea>
              <Text size="xs" c="dimmed" mt={4}>
                Drag to move · arrows nudge (Shift = 10 dots) · Delete removes · Ctrl+D duplicates
              </Text>
            </Tabs.Panel>
            <Tabs.Panel value="zpl">
              <Card withBorder>
                <Group justify="flex-end" mb="xs" gap="xs">
                  <CopyButton value={generated.data?.zpl ?? ''}>
                    {({ copied, copy }) => (
                      <Button size="xs" variant="default" onClick={copy}>
                        {copied ? 'Copied' : 'Copy'}
                      </Button>
                    )}
                  </CopyButton>
                </Group>
                <ScrollArea h={500}>
                  <Code block>{generated.data?.zpl ?? ''}</Code>
                </ScrollArea>
              </Card>
            </Tabs.Panel>
            <Tabs.Panel value="preview">
              <Card withBorder>
                <Text size="xs" c="dimmed" mb="xs">
                  Rendered from the generated ZPL by the local renderer (variables use their
                  defaults).
                </Text>
                <PreviewPanel
                  preview={rendered.data}
                  loading={rendered.isFetching}
                  error={rendered.error}
                />
              </Card>
            </Tabs.Panel>
          </Tabs>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Card withBorder p="xs">
            <Tabs value={sideTab} onChange={setSideTab}>
              <Tabs.List grow mb="xs">
                <Tabs.Tab value="properties">Properties</Tabs.Tab>
                <Tabs.Tab value="layers">Layers</Tabs.Tab>
                <Tabs.Tab value="variables">
                  Variables{variables.length ? ` (${variables.length})` : ''}
                </Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="properties">
                {selected ? (
                  <PropertiesPanel
                    element={selected}
                    dpi={design.dpi}
                    values={defaults}
                    dispatch={dispatch}
                  />
                ) : (
                  <Text size="sm" c="dimmed">
                    Select an element on the canvas.
                  </Text>
                )}
              </Tabs.Panel>
              <Tabs.Panel value="layers">
                <LayersPanel
                  elements={design.elements}
                  selectedId={selectedId}
                  dispatch={dispatch}
                />
              </Tabs.Panel>
              <Tabs.Panel value="variables">
                <VariablesPanel
                  variables={variables}
                  onChange={setVariableMeta}
                  selected={selected}
                  dispatch={dispatch}
                />
              </Tabs.Panel>
            </Tabs>
          </Card>
        </Grid.Col>
      </Grid>

      <SaveLabelModal
        opened={saveOpened}
        onClose={saveModal.close}
        onSave={save}
        loading={saveLabel.isPending}
        initial={label ? { name: `${label.name} (copy)`, tags: label.tags } : undefined}
      />
      <ImageImportModal
        opened={imageOpened}
        onClose={imageModal.close}
        onAdd={addImage}
        dpi={design.dpi}
        maxWidth={widthDots}
      />
      <PrintDesignModal
        opened={printOpened}
        onClose={printModal.close}
        design={design}
        variables={variables}
      />
    </Stack>
  )
}

function PrintDesignModal({
  opened,
  onClose,
  design,
  variables,
}: {
  opened: boolean
  onClose: () => void
  design: Design
  variables: VariableDef[]
}) {
  const { printer } = useSelectedPrinter()
  const print = usePrint()
  return (
    <Modal opened={opened} onClose={onClose} title="Print design">
      {opened && (
        <PrintForm
          definitions={variables}
          loading={print.isPending}
          onPrint={async (values, copies) => {
            const sent = await notifyPrint(
              print.mutateAsync({
                design,
                variables: values,
                definitions: variables,
                copies,
                printer_id: printer?.id,
                source: 'designer',
              }),
            )
            if (sent) onClose()
          }}
        />
      )}
    </Modal>
  )
}
