import {
  Badge,
  Button,
  Card,
  Grid,
  Group,
  NumberInput,
  Select,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { useDebouncedValue, useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconDeviceFloppy, IconPrinter, IconTrash } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { api, apiBlob } from '../api/client'
import { useDraft, useLabel, usePrint, usePrinterSettingsInZpl, useSaveLabel } from '../api/hooks'
import type { PrinterSettingsInZpl, VariableDef } from '../api/types'
import { EmbeddedSettingsAlert } from '../components/EmbeddedSettingsAlert'
import { PreviewPanel } from '../components/PreviewPanel'
import { useAutosaveDraft } from '../components/useAutosaveDraft'
import { useSelectedPrinter } from '../components/printerContext'
import { SaveLabelModal } from '../components/SaveLabelModal'
import { usePngPreview } from '../components/usePngPreview'
import { VariableFields } from '../components/VariableFields'
import { ZplEditor } from '../components/ZplEditor'
import { errorMessage } from '../utils/format'
import {
  extractVariables,
  initialValues,
  mergeVariables,
  variableErrors,
} from '../utils/templating'

export const SAMPLE_ZPL = `^XA
^CI28
^FO40,40^A0N,50,50^FDHello from Zebra Web^FS
^FO40,110^BY2^BCN,80,Y,N,N^FD123456789^FS
^FO40,240^GB500,3,3^FS
^XZ
`

const DRAFT_NAME = 'print-zpl'

interface PrintDraft {
  zpl: string
  width_mm: number | ''
  height_mm: number | ''
  values: Record<string, string>
  copies: number
  keep_printer_settings: boolean
}

/** Typed values, falling back to defaults like printing does; variables without either are
 * left out, so the preview shows them as written. */
function previewValues(
  values: Record<string, string>,
  definitions: VariableDef[],
): Record<string, string> {
  const defaults = initialValues(definitions)
  return Object.fromEntries(
    definitions
      .map(({ name }) => [name, values[name] || defaults[name]])
      .filter(([, value]) => value),
  )
}

export function PrintPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const labelId = searchParams.get('label') ? Number(searchParams.get('label')) : null
  const { data: label } = useLabel(labelId)
  const { printer } = useSelectedPrinter()
  const print = usePrint()
  const saveLabel = useSaveLabel()
  const [saveOpened, saveModal] = useDisclosure()

  const [zpl, setZpl] = useState(labelId === null ? '' : SAMPLE_ZPL)
  const [values, setValues] = useState<Record<string, string>>({})
  const [copies, setCopies] = useState(1)
  const [widthMm, setWidthMm] = useState<number | ''>('')
  const [heightMm, setHeightMm] = useState<number | ''>('')
  const [index, setIndex] = useState(0)
  const [submitted, setSubmitted] = useState(false)
  const [keepSettings, setKeepSettings] = useState(false)

  // Load the label into the editor when it arrives (state adjusted during render).
  const [loadedLabel, setLoadedLabel] = useState<typeof label>(undefined)
  if (label && label !== loadedLabel) {
    setLoadedLabel(label)
    setZpl(label.zpl)
    setWidthMm(label.width_mm ?? '')
    setHeightMm(label.height_mm ?? '')
    setIndex(0)
  }

  // The last ZPL pasted here is kept for the current user, on the server, so the page looks
  // the same when they come back (not while editing an archived label, which is stored
  // with the label).
  const useDraftHere = labelId === null
  const draft = useDraft<PrintDraft>(DRAFT_NAME, useDraftHere)
  const [restored, setRestored] = useState(false)
  if (!restored && useDraftHere && (draft.isSuccess || draft.isError)) {
    setRestored(true)
    const saved = draft.data?.data
    setZpl(typeof saved?.zpl === 'string' ? saved.zpl : SAMPLE_ZPL)
    setWidthMm(saved?.width_mm ?? '')
    setHeightMm(saved?.height_mm ?? '')
    setValues(saved?.values ?? {})
    setCopies(saved?.copies ?? 1)
    setKeepSettings(saved?.keep_printer_settings ?? false)
  }
  const autosave = useAutosaveDraft<PrintDraft>(
    DRAFT_NAME,
    restored
      ? {
          zpl,
          width_mm: widthMm,
          height_mm: heightMm,
          values,
          copies,
          keep_printer_settings: keepSettings,
        }
      : null,
    { enabled: useDraftHere },
  )

  const definitions = useMemo(
    () => mergeVariables(extractVariables(zpl), label?.variables ?? []),
    [zpl, label],
  )
  const dpi = printer?.dpi ?? label?.dpi ?? 203
  const [debouncedZpl] = useDebouncedValue(zpl, 400)
  const { data: embedded } = usePrinterSettingsInZpl(debouncedZpl, printer?.id)
  // The server fills in the values like printing does (escaping them in ^FH fields).
  const filled = useMemo(
    () => ({ zpl, variables: previewValues(values, definitions) }),
    [zpl, values, definitions],
  )
  const [previewed] = useDebouncedValue(filled, 400)
  const preview = usePngPreview(
    ['render', previewed, dpi, widthMm, heightMm, index, keepSettings, printer?.id],
    () =>
      apiBlob('/api/render', {
        json: {
          zpl: previewed.zpl,
          variables: previewed.variables,
          dpi,
          width_mm: widthMm || null,
          height_mm: heightMm || null,
          index,
          // Preview what is printed: the printer replaces some embedded settings.
          strip_printer_settings: !keepSettings,
          printer_id: printer?.id ?? null,
        },
      }),
    previewed.zpl.trim() !== '',
  )
  const labelCount = preview.data?.labelCount ?? 1

  // Clean the ZPL that is in the editor now (the analysis above may lag behind typing) and
  // leave anything typed while the request runs untouched.
  async function removeReplacedSettings() {
    const current = zpl
    try {
      const cleaned = await api<PrinterSettingsInZpl>('/api/zpl/printer-settings', {
        json: { zpl: current, printer_id: printer?.id ?? null },
      })
      setZpl((latest) => (latest === current ? cleaned.zpl : latest))
      setKeepSettings(false)
    } catch (error) {
      notifications.show({
        color: 'red',
        title: 'Could not clean the ZPL',
        message: errorMessage(error),
      })
    }
  }

  async function handlePrint() {
    setSubmitted(true)
    if (Object.keys(variableErrors(definitions, values)).length > 0) return
    try {
      const job = await print.mutateAsync({
        zpl,
        printer_id: printer?.id,
        variables: values,
        definitions,
        copies,
        source: 'raw',
        keep_printer_settings: keepSettings,
      })
      if (job.status === 'sent') {
        notifications.show({ color: 'green', message: `Sent to ${job.printer_name}` })
      } else {
        notifications.show({ color: 'red', title: 'Printing failed', message: job.error })
      }
    } catch (error) {
      notifications.show({ color: 'red', title: 'Printing failed', message: errorMessage(error) })
    }
  }

  async function handleSave(details?: { name: string; description: string; tags: string[] }) {
    try {
      const body = {
        zpl,
        width_mm: widthMm || null,
        height_mm: heightMm || null,
        dpi,
        variables: definitions,
      }
      if (label && !details) {
        await saveLabel.mutateAsync({ id: label.id, body })
        notifications.show({ color: 'green', message: `Updated "${label.name}"` })
        return
      }
      const created = await saveLabel.mutateAsync({
        body: { ...body, ...details!, kind: 'zpl' },
      })
      saveModal.close()
      notifications.show({ color: 'green', message: `Saved "${created.name}" to the archive` })
      navigate(`/?label=${created.id}`, { replace: true })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Saving failed', message: errorMessage(error) })
    }
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={2}>Print ZPL</Title>
          {label && <Badge variant="light">Editing “{label.name}”</Badge>}
        </Group>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconTrash size={16} />}
            onClick={() => {
              setZpl('')
              setValues({})
              if (labelId) navigate('/', { replace: true })
            }}
          >
            Clear
          </Button>
          {label && (
            <Button
              variant="default"
              leftSection={<IconDeviceFloppy size={16} />}
              loading={saveLabel.isPending}
              onClick={() => handleSave()}
            >
              Save changes
            </Button>
          )}
          <Button
            variant="default"
            leftSection={<IconDeviceFloppy size={16} />}
            onClick={saveModal.open}
            disabled={!zpl.trim()}
          >
            {label ? 'Save as new' : 'Save to archive'}
          </Button>
        </Group>
      </Group>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <Stack>
            <Card withBorder p={0}>
              <ZplEditor value={zpl} onChange={setZpl} />
            </Card>
            {labelId === null && (
              <Text size="xs" c="dimmed" mt={-8} data-testid="draft-status">
                {autosave.saving
                  ? 'Saving…'
                  : autosave.savedAt
                    ? `Saved for you at ${new Date(autosave.savedAt).toLocaleTimeString()}`
                    : 'Your last ZPL is kept here, also on other devices'}
              </Text>
            )}
            {embedded && zpl.trim() && (
              <EmbeddedSettingsAlert
                settings={embedded}
                printerId={printer?.id}
                keepAll={keepSettings}
                onKeepAllChange={setKeepSettings}
                onRemoveReplaced={removeReplacedSettings}
              />
            )}
            {definitions.length > 0 && (
              <Card withBorder>
                <Text fw={600} mb="xs">
                  Template variables
                </Text>
                <VariableFields
                  definitions={definitions}
                  values={values}
                  onChange={setValues}
                  showErrors={submitted}
                  showBuiltins
                />
              </Card>
            )}
            <Group align="flex-end">
              <NumberInput
                label="Copies"
                min={1}
                max={1000}
                w={120}
                value={copies}
                onChange={(value) => setCopies(Number(value) || 1)}
              />
              <Button
                leftSection={<IconPrinter size={16} />}
                onClick={handlePrint}
                loading={print.isPending}
                disabled={!printer || !zpl.trim()}
              >
                Print{printer ? ` on ${printer.name}` : ''}
              </Button>
              {!printer && (
                <Text size="sm" c="dimmed">
                  Add a printer first.
                </Text>
              )}
            </Group>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 6 }}>
          <Card withBorder>
            <Group mb="sm" align="flex-end">
              <NumberInput
                label="Width (mm)"
                placeholder="from ^PW"
                w={120}
                min={1}
                value={widthMm}
                onChange={(v) => setWidthMm(v === '' ? '' : Number(v))}
              />
              <NumberInput
                label="Height (mm)"
                placeholder="from ^LL"
                w={120}
                min={1}
                value={heightMm}
                onChange={(v) => setHeightMm(v === '' ? '' : Number(v))}
              />
              {labelCount > 1 && (
                <Select
                  label="Label"
                  w={120}
                  data={Array.from({ length: labelCount }, (_, i) => ({
                    value: String(i),
                    label: `${i + 1} of ${labelCount}`,
                  }))}
                  value={String(index)}
                  onChange={(v) => setIndex(Number(v ?? 0))}
                />
              )}
              <Text size="xs" c="dimmed">
                {dpi} dpi
              </Text>
            </Group>
            <PreviewPanel
              preview={zpl.trim() ? preview.data : undefined}
              loading={preview.isFetching}
              error={preview.error}
              emptyText="Paste ZPL on the left to see a preview"
            />
          </Card>
        </Grid.Col>
      </Grid>
      <SaveLabelModal
        opened={saveOpened}
        onClose={saveModal.close}
        onSave={(details) => handleSave(details)}
        loading={saveLabel.isPending}
        initial={label ? { name: `${label.name} (copy)`, tags: label.tags } : undefined}
      />
    </Stack>
  )
}
