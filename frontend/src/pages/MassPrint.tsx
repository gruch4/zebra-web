import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Grid,
  Group,
  Menu,
  Pagination,
  Progress,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { notifications } from '@mantine/notifications'
import {
  IconAlertTriangle,
  IconDownload,
  IconFileUpload,
  IconPlayerStop,
  IconPrinter,
  IconRefresh,
} from '@tabler/icons-react'
import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api/client'
import { useBatch } from '../api/hooks'
import type { Batch, DryRunResult, ParseResult, VariableDef } from '../api/types'
import { PreviewPanel } from '../components/PreviewPanel'
import { useSelectedPrinter } from '../components/printerContext'
import { useTemplatePreview } from '../components/useTemplatePreview'
import { buildRows } from '../utils/batch'
import { downloadText } from '../utils/download'
import { errorMessage } from '../utils/format'

const ROWS_PER_PAGE = 100
const ACCEPT = [
  'text/csv',
  'text/tab-separated-values',
  'text/plain',
  'application/json',
  'application/yaml',
  'application/x-yaml',
  'text/yaml',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.csv',
  '.tsv',
  '.json',
  '.yaml',
  '.yml',
  '.xlsx',
]

interface MassPrintProps {
  labelId: number
  labelName: string
  definitions: VariableDef[]
}

function BatchProgress({ batchId, onRetry }: { batchId: number; onRetry: (batch: Batch) => void }) {
  const { data: batch } = useBatch(batchId)
  const cancel = useMutation({
    mutationFn: () => api<Batch>(`/api/batches/${batchId}/cancel`, { method: 'POST' }),
  })
  if (!batch) return null
  const running = batch.status === 'queued' || batch.status === 'running'
  const done = batch.sent + batch.failed
  const colors: Record<string, string> = {
    done: 'green',
    failed: 'red',
    cancelled: 'orange',
    running: 'blue',
    queued: 'gray',
  }
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>Batch #{batch.id}</Text>
          <Badge color={colors[batch.status]}>{batch.status}</Badge>
        </Group>
        <Group gap="xs">
          {running && (
            <Button
              size="xs"
              color="orange"
              variant="light"
              leftSection={<IconPlayerStop size={14} />}
              loading={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Cancel
            </Button>
          )}
          {!running && batch.sent < batch.total && (
            <Button
              size="xs"
              variant="light"
              leftSection={<IconRefresh size={14} />}
              onClick={() => onRetry(batch)}
            >
              Retry unprinted rows
            </Button>
          )}
        </Group>
      </Group>
      <Progress.Root size="lg">
        <Progress.Section value={(batch.sent / Math.max(1, batch.total)) * 100} color="green" />
        <Progress.Section value={(batch.failed / Math.max(1, batch.total)) * 100} color="red" />
      </Progress.Root>
      <Text size="sm" mt="xs">
        {batch.sent} of {batch.total} labels sent{batch.failed ? `, ${batch.failed} failed` : ''}
        {running && done < batch.total ? '…' : ''}
      </Text>
      {batch.error && (
        <Text size="sm" c="red" mt={4}>
          {batch.error}
        </Text>
      )}
    </Card>
  )
}

export function MassPrint({ labelId, labelName, definitions }: MassPrintProps) {
  const { printer } = useSelectedPrinter()
  const [inputMode, setInputMode] = useState('file')
  const [pasted, setPasted] = useState('')
  const [pastedFormat, setPastedFormat] = useState<string | null>(null)
  const [filename, setFilename] = useState('')
  const [parsed, setParsed] = useState<ParseResult | null>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [constants, setConstants] = useState<Record<string, string>>({})
  const [copiesColumn, setCopiesColumn] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [page, setPage] = useState(1)
  const [previewRow, setPreviewRow] = useState<number | null>(null)
  const [batchId, setBatchId] = useState<number | null>(null)

  const parse = useMutation({
    mutationFn: (input: { file?: File; text?: string; format?: string | null }) => {
      const form = new FormData()
      form.append('label_id', String(labelId))
      if (input.file) form.append('file', input.file)
      if (input.text) form.append('text', input.text)
      if (input.format) form.append('format', input.format)
      return api<ParseResult>('/api/batches/parse', { form })
    },
    onSuccess: (result) => {
      setParsed(result)
      setMapping(result.mapping)
      setConstants({})
      setCopiesColumn(result.copies_column)
      setSelected(new Set(result.preview.filter((r) => r.errors.length === 0).map((r) => r.index)))
      setPage(1)
      setPreviewRow(null)
      setBatchId(null)
    },
    onError: (error) =>
      notifications.show({ color: 'red', title: 'Cannot read data', message: errorMessage(error) }),
  })

  const rows = useMemo(
    () => (parsed ? buildRows(parsed.rows, definitions, mapping, constants, copiesColumn) : []),
    [parsed, definitions, mapping, constants, copiesColumn],
  )
  const validSelected = rows.filter((r) => selected.has(r.index) && r.errors.length === 0)
  const totalCopies = validSelected.reduce((sum, r) => sum + r.copies, 0)

  const batchBody = () => ({
    label_id: labelId,
    printer_id: printer?.id,
    rows: parsed?.rows ?? [],
    mapping,
    constants,
    copies_column: copiesColumn,
    selected: validSelected.map((r) => r.index),
    data_filename: filename,
  })

  const start = useMutation({
    mutationFn: () => api<Batch>('/api/batches', { json: batchBody() }),
    onSuccess: (batch) => setBatchId(batch.id),
    onError: (error) =>
      notifications.show({
        color: 'red',
        title: 'Cannot start printing',
        message: errorMessage(error),
      }),
  })
  const dryRun = useMutation({
    mutationFn: () => api<DryRunResult>('/api/batches/dry-run', { json: batchBody() }),
    onSuccess: (result) => downloadText(result.zpl, `${labelName}-${result.count}-labels.zpl`),
    onError: (error) =>
      notifications.show({ color: 'red', title: 'Dry run failed', message: errorMessage(error) }),
  })
  const retry = useMutation({
    mutationFn: (batch: Batch) =>
      api<Batch>(`/api/batches/${batch.id}/retry-failed`, { method: 'POST' }),
    onSuccess: (batch) => setBatchId(batch.id),
    onError: (error) =>
      notifications.show({ color: 'red', title: 'Retry failed', message: errorMessage(error) }),
  })

  const previewValues = previewRow !== null ? (rows[previewRow]?.values ?? {}) : {}
  const preview = useTemplatePreview(labelId, previewValues, previewRow !== null)

  const columnOptions = (parsed?.columns ?? []).map((c) => ({ value: c, label: c }))
  const pageRows = rows.slice((page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE)

  function toggle(index: number, checked: boolean) {
    const next = new Set(selected)
    if (checked) next.add(index)
    else next.delete(index)
    setSelected(next)
  }

  return (
    <Stack>
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <SegmentedControl
            value={inputMode}
            onChange={setInputMode}
            data={[
              { value: 'file', label: 'Upload file' },
              { value: 'paste', label: 'Paste data' },
            ]}
          />
          <Menu>
            <Menu.Target>
              <Button size="xs" variant="subtle" leftSection={<IconDownload size={14} />}>
                Download sample file
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              {['csv', 'xlsx', 'json', 'yaml'].map((fmt) => (
                <Menu.Item
                  key={fmt}
                  component="a"
                  href={`/api/labels/${labelId}/sample-data.${fmt}`}
                >
                  {fmt.toUpperCase()}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        </Group>
        {inputMode === 'file' ? (
          <Dropzone
            onDrop={(files) => {
              setFilename(files[0].name)
              parse.mutate({ file: files[0] })
            }}
            accept={ACCEPT}
            maxFiles={1}
            maxSize={5 * 1024 * 1024}
            loading={parse.isPending}
          >
            <Group justify="center" gap="md" mih={110} style={{ pointerEvents: 'none' }}>
              <IconFileUpload size={40} stroke={1.5} />
              <div>
                <Text size="lg">Drop a data file here or click to select</Text>
                <Text size="sm" c="dimmed">
                  CSV, TSV, JSON, YAML or Excel (.xlsx) · first row / keys are column names · an
                  optional “copies” column sets copies per row
                </Text>
              </div>
            </Group>
          </Dropzone>
        ) : (
          <Stack>
            <Textarea
              label="Data"
              description="CSV/TSV with a header row, a JSON array of objects, or a YAML list"
              autosize
              minRows={5}
              maxRows={14}
              styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
              value={pasted}
              onChange={(e) => setPasted(e.currentTarget.value)}
            />
            <Group>
              <Select
                placeholder="Detect format"
                data={['csv', 'tsv', 'json', 'yaml']}
                value={pastedFormat}
                onChange={setPastedFormat}
                clearable
                w={160}
              />
              <Button
                onClick={() => {
                  setFilename('')
                  parse.mutate({ text: pasted, format: pastedFormat })
                }}
                loading={parse.isPending}
                disabled={!pasted.trim()}
              >
                Load data
              </Button>
            </Group>
          </Stack>
        )}
      </Card>

      {parsed && (
        <>
          <Card withBorder>
            <Text fw={600} mb="xs">
              Map columns to variables
            </Text>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Variable</Table.Th>
                  <Table.Th>Column</Table.Th>
                  <Table.Th>…or the same value for all rows</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {definitions.map((definition) => (
                  <Table.Tr key={definition.name}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {definition.label || definition.name}
                      </Text>
                      <Text size="xs" c="dimmed" ff="monospace">{`{{${definition.name}}}`}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Select
                        aria-label={`Column for ${definition.name}`}
                        size="xs"
                        placeholder="— none —"
                        data={columnOptions}
                        value={mapping[definition.name] ?? null}
                        onChange={(v) => setMapping({ ...mapping, [definition.name]: v })}
                        clearable
                      />
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label={`Constant for ${definition.name}`}
                        size="xs"
                        placeholder={definition.default || ''}
                        value={constants[definition.name] ?? ''}
                        onChange={(e) =>
                          setConstants({ ...constants, [definition.name]: e.currentTarget.value })
                        }
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
                <Table.Tr>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      Copies per row
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      aria-label="Copies column"
                      size="xs"
                      placeholder="1 copy each"
                      data={columnOptions}
                      value={copiesColumn}
                      onChange={setCopiesColumn}
                      clearable
                    />
                  </Table.Td>
                  <Table.Td />
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Card>

          <Grid>
            <Grid.Col span={{ base: 12, lg: 8 }}>
              <Card withBorder p={0}>
                <Group justify="space-between" p="sm">
                  <Text size="sm">
                    {rows.length} rows ({parsed.format.toUpperCase()}
                    {filename ? `, ${filename}` : ''})
                  </Text>
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() =>
                        setSelected(
                          new Set(rows.filter((r) => r.errors.length === 0).map((r) => r.index)),
                        )
                      }
                    >
                      Select all valid
                    </Button>
                    <Button size="xs" variant="subtle" onClick={() => setSelected(new Set())}>
                      Clear selection
                    </Button>
                  </Group>
                </Group>
                <Table.ScrollContainer minWidth={500} maxHeight={460}>
                  <Table stickyHeader highlightOnHover verticalSpacing={4}>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th w={40} />
                        <Table.Th w={50}>#</Table.Th>
                        {parsed.columns.map((column) => (
                          <Table.Th key={column}>{column}</Table.Th>
                        ))}
                        <Table.Th>Problems</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {pageRows.map((row) => {
                        const invalid = row.errors.length > 0
                        return (
                          <Table.Tr
                            key={row.index}
                            data-testid={`row-${row.index}`}
                            bg={
                              invalid
                                ? 'var(--mantine-color-red-light)'
                                : previewRow === row.index
                                  ? 'var(--mantine-color-blue-light)'
                                  : undefined
                            }
                            style={{ cursor: 'pointer' }}
                            onClick={() => setPreviewRow(row.index)}
                          >
                            <Table.Td onClick={(e) => e.stopPropagation()}>
                              <Checkbox
                                aria-label={`Select row ${row.index + 1}`}
                                size="xs"
                                checked={selected.has(row.index)}
                                disabled={invalid}
                                onChange={(e) => toggle(row.index, e.currentTarget.checked)}
                              />
                            </Table.Td>
                            <Table.Td>{row.index + 1}</Table.Td>
                            {parsed.columns.map((column) => (
                              <Table.Td key={column}>{parsed.rows[row.index][column]}</Table.Td>
                            ))}
                            <Table.Td>
                              {invalid && (
                                <Tooltip label={row.errors.join('; ')} multiline w={300}>
                                  <Text size="xs" c="red" truncate maw={220}>
                                    {row.errors.join('; ')}
                                  </Text>
                                </Tooltip>
                              )}
                            </Table.Td>
                          </Table.Tr>
                        )
                      })}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
                {rows.length > ROWS_PER_PAGE && (
                  <Group justify="center" p="xs">
                    <Pagination
                      size="sm"
                      total={Math.ceil(rows.length / ROWS_PER_PAGE)}
                      value={page}
                      onChange={setPage}
                    />
                  </Group>
                )}
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 4 }}>
              <Card withBorder>
                <Text size="xs" c="dimmed" mb="xs">
                  {previewRow !== null
                    ? `Preview of row ${previewRow + 1}`
                    : 'Click a row to preview it'}
                </Text>
                {previewRow !== null && (
                  <PreviewPanel
                    preview={preview.data}
                    loading={preview.isFetching}
                    error={preview.error}
                    maxHeight={320}
                  />
                )}
              </Card>
            </Grid.Col>
          </Grid>

          <Card withBorder>
            <Group justify="space-between">
              <Stack gap={2}>
                <Text fw={600} data-testid="batch-summary">
                  {validSelected.length} label{validSelected.length === 1 ? '' : 's'} selected
                  {totalCopies !== validSelected.length ? ` (${totalCopies} copies)` : ''}
                </Text>
                {rows.some((r) => r.errors.length > 0) && (
                  <Text size="sm" c="red">
                    <IconAlertTriangle size={14} style={{ verticalAlign: 'middle' }} />{' '}
                    {rows.filter((r) => r.errors.length > 0).length} row(s) with errors will be
                    skipped
                  </Text>
                )}
              </Stack>
              <Group gap="xs">
                <Button
                  variant="default"
                  leftSection={<IconDownload size={16} />}
                  onClick={() => dryRun.mutate()}
                  loading={dryRun.isPending}
                  disabled={validSelected.length === 0}
                >
                  Dry run (.zpl)
                </Button>
                <Button
                  leftSection={<IconPrinter size={16} />}
                  onClick={() => start.mutate()}
                  loading={start.isPending}
                  disabled={validSelected.length === 0 || !printer}
                >
                  Print {validSelected.length} label{validSelected.length === 1 ? '' : 's'}
                  {printer ? ` on ${printer.name}` : ''}
                </Button>
              </Group>
            </Group>
          </Card>
        </>
      )}

      {batchId !== null && <BatchProgress batchId={batchId} onRetry={(b) => retry.mutate(b)} />}
      {batchId !== null && (
        <Alert variant="light">
          Every printed row is recorded in{' '}
          <Anchor href="/history" size="sm">
            Print history
          </Anchor>
          .
        </Alert>
      )}
    </Stack>
  )
}
