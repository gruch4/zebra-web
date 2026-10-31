import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Code,
  Drawer,
  Group,
  NumberInput,
  Pagination,
  Progress,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconChevronDown,
  IconChevronRight,
  IconDeviceFloppy,
  IconPrinter,
  IconSearch,
} from '@tabler/icons-react'
import { Fragment, useState } from 'react'

import { apiBlob } from '../api/client'
import {
  BATCH_JOBS_PAGE_SIZE,
  useBatchJobs,
  useHistory,
  usePrinters,
  useReprint,
  useSaveJobAsLabel,
} from '../api/hooks'
import type { Batch, PrintJob } from '../api/types'
import { PreviewPanel } from '../components/PreviewPanel'
import { useSelectedPrinter } from '../components/printerContext'
import { usePngPreview } from '../components/usePngPreview'
import { errorMessage, formatDateTime } from '../utils/format'

const PAGE_SIZE = 50

const SOURCE_LABELS: Record<string, string> = {
  raw: 'ZPL editor',
  designer: 'Designer',
  archive: 'Archive',
  reprint: 'Reprint',
  template: 'Template',
  batch: 'Mass print',
  api: 'API',
}

const BATCH_COLORS: Record<string, string> = {
  queued: 'gray',
  running: 'blue',
  done: 'green',
  failed: 'red',
  cancelled: 'orange',
}

export function JobStatusBadge({ job }: { job: PrintJob }) {
  return (
    <Badge color={job.status === 'sent' ? 'green' : 'red'} variant="light">
      {job.status}
    </Badge>
  )
}

function JobDrawer({ job, onClose }: { job: PrintJob | null; onClose: () => void }) {
  const { printer } = useSelectedPrinter()
  const reprint = useReprint()
  const saveAsLabel = useSaveJobAsLabel()
  const [copies, setCopies] = useState<number | ''>('')
  const preview = usePngPreview(
    ['job', job?.id],
    () => apiBlob(`/api/jobs/${job?.id}/preview.png`),
    job !== null,
  )

  async function handleReprint() {
    if (!job) return
    try {
      const result = await reprint.mutateAsync({
        id: job.id,
        copies: copies || undefined,
        printer_id: printer?.id,
      })
      notifications.show({
        color: result.status === 'sent' ? 'green' : 'red',
        message: result.status === 'sent' ? `Reprinted on ${result.printer_name}` : result.error,
      })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Reprint failed', message: errorMessage(error) })
    }
  }

  async function handleSave() {
    if (!job) return
    try {
      const label = await saveAsLabel.mutateAsync({ id: job.id })
      notifications.show({ color: 'green', message: `Saved as “${label.name}”` })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Saving failed', message: errorMessage(error) })
    }
  }

  return (
    <Drawer
      opened={job !== null}
      onClose={onClose}
      position="right"
      size="lg"
      title={job ? `Print job #${job.id}` : ''}
    >
      {job && (
        <Stack>
          <Group gap="xs">
            <JobStatusBadge job={job} />
            <Badge variant="outline">{SOURCE_LABELS[job.source] ?? job.source}</Badge>
            <Text size="sm" c="dimmed">
              {formatDateTime(job.created_at)} · {job.printer_name} ({job.printer_host}) ·{' '}
              {job.copies} cop{job.copies === 1 ? 'y' : 'ies'}
            </Text>
          </Group>
          {job.error && (
            <Text c="red" size="sm">
              {job.error}
            </Text>
          )}
          <PreviewPanel
            preview={preview.data}
            loading={preview.isFetching}
            error={preview.error}
            maxHeight={360}
          />
          {Object.keys(job.variables).length > 0 && (
            <Table withTableBorder>
              <Table.Tbody>
                {Object.entries(job.variables).map(([key, value]) => (
                  <Table.Tr key={key}>
                    <Table.Td ff="monospace">{key}</Table.Td>
                    <Table.Td>{value}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          <Group align="flex-end">
            <NumberInput
              label="Copies"
              placeholder={String(job.copies)}
              min={1}
              max={1000}
              w={110}
              value={copies}
              onChange={(v) => setCopies(v === '' ? '' : Number(v))}
            />
            <Button
              leftSection={<IconPrinter size={16} />}
              onClick={handleReprint}
              loading={reprint.isPending}
              disabled={!printer}
            >
              Reprint{printer ? ` on ${printer.name}` : ''}
            </Button>
            <Button
              variant="default"
              leftSection={<IconDeviceFloppy size={16} />}
              onClick={handleSave}
              loading={saveAsLabel.isPending}
            >
              Save as label
            </Button>
          </Group>
          <Text fw={600}>ZPL sent</Text>
          <ScrollArea h={260}>
            <Code block>{job.zpl}</Code>
          </ScrollArea>
        </Stack>
      )}
    </Drawer>
  )
}

function JobRow({ job, onOpen, nested }: { job: PrintJob; onOpen: () => void; nested?: boolean }) {
  return (
    <Table.Tr onClick={onOpen} style={{ cursor: 'pointer' }}>
      <Table.Td pl={nested ? 40 : undefined}>
        {nested ? `Row ${(job.batch_row ?? 0) + 1}` : formatDateTime(job.created_at)}
      </Table.Td>
      <Table.Td>{job.label_name ?? <Text c="dimmed">—</Text>}</Table.Td>
      <Table.Td>{job.printer_name}</Table.Td>
      <Table.Td>
        <Badge variant="outline" size="sm">
          {SOURCE_LABELS[job.source] ?? job.source}
        </Badge>
      </Table.Td>
      <Table.Td>{job.copies}</Table.Td>
      <Table.Td>
        <JobStatusBadge job={job} />
      </Table.Td>
      <Table.Td>{job.created_by}</Table.Td>
    </Table.Tr>
  )
}

function BatchRows({ batch, onOpenJob }: { batch: Batch; onOpenJob: (job: PrintJob) => void }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const { data } = useBatchJobs(open ? batch.id : null, page)
  const done = batch.sent + batch.failed
  return (
    <Fragment>
      <Table.Tr onClick={() => setOpen(!open)} style={{ cursor: 'pointer' }}>
        <Table.Td>
          <Group gap={4} wrap="nowrap">
            <ActionIcon size="xs" variant="subtle" aria-label={open ? 'Collapse' : 'Expand'}>
              {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            </ActionIcon>
            {formatDateTime(batch.created_at)}
          </Group>
        </Table.Td>
        <Table.Td>
          <Text size="sm">{batch.label_name}</Text>
          <Text size="xs" c="dimmed">
            {batch.data_filename || 'pasted data'}
          </Text>
        </Table.Td>
        <Table.Td>{batch.printer_name}</Table.Td>
        <Table.Td>
          <Badge variant="outline" size="sm">
            Mass print
          </Badge>
        </Table.Td>
        <Table.Td>
          <Stack gap={2} miw={90}>
            <Text size="xs">
              {batch.sent}/{batch.total}
              {batch.failed ? ` · ${batch.failed} failed` : ''}
            </Text>
            <Progress size="xs" value={(done / Math.max(1, batch.total)) * 100} />
          </Stack>
        </Table.Td>
        <Table.Td>
          <Badge color={BATCH_COLORS[batch.status]} variant="light">
            {batch.status}
          </Badge>
        </Table.Td>
        <Table.Td>{batch.created_by}</Table.Td>
      </Table.Tr>
      {open &&
        data?.items.map((job) => (
          <JobRow key={job.id} job={job} nested onOpen={() => onOpenJob(job)} />
        ))}
      {open && data && data.total > BATCH_JOBS_PAGE_SIZE && (
        <Table.Tr>
          <Table.Td colSpan={7} pl={40}>
            <Group gap="sm">
              <Pagination
                size="xs"
                total={Math.ceil(data.total / BATCH_JOBS_PAGE_SIZE)}
                value={page}
                onChange={setPage}
                aria-label={`Pages of batch ${batch.id}`}
              />
              <Text size="xs" c="dimmed">
                {data.total} rows
              </Text>
            </Group>
          </Table.Td>
        </Table.Tr>
      )}
      {open && batch.error && (
        <Table.Tr>
          <Table.Td colSpan={7} pl={40}>
            <Text c="red" size="sm">
              {batch.error}
            </Text>
          </Table.Td>
        </Table.Tr>
      )}
    </Fragment>
  )
}

export function HistoryPage() {
  const { data: printers = [] } = usePrinters()
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const [status, setStatus] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [printerId, setPrinterId] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [openJob, setOpenJob] = useState<PrintJob | null>(null)
  const { data, isLoading } = useHistory({
    q,
    status,
    source,
    printer_id: printerId ? Number(printerId) : null,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })

  return (
    <Stack>
      <Title order={2}>Print history</Title>
      <Group>
        <TextInput
          placeholder="Search label or ZPL"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            setSearch(e.currentTarget.value)
            setPage(1)
          }}
          w={260}
        />
        <Select
          placeholder="Any status"
          data={[
            { value: 'sent', label: 'Sent' },
            { value: 'failed', label: 'Failed' },
          ]}
          value={status}
          onChange={(v) => {
            setStatus(v)
            setPage(1)
          }}
          clearable
          w={150}
        />
        <Select
          placeholder="Any source"
          data={Object.entries(SOURCE_LABELS).map(([value, label]) => ({ value, label }))}
          value={source}
          onChange={(v) => {
            setSource(v)
            setPage(1)
          }}
          clearable
          w={170}
        />
        <Select
          placeholder="Any printer"
          data={printers.map((p) => ({ value: String(p.id), label: p.name }))}
          value={printerId}
          onChange={(v) => {
            setPrinterId(v)
            setPage(1)
          }}
          clearable
          w={180}
        />
      </Group>
      <Card withBorder p={0}>
        <Table.ScrollContainer minWidth={800}>
          <Table highlightOnHover verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Time</Table.Th>
                <Table.Th>Label</Table.Th>
                <Table.Th>Printer</Table.Th>
                <Table.Th>Source</Table.Th>
                <Table.Th>Copies</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>User</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.items.map((item) =>
                item.kind === 'batch' && item.batch ? (
                  <BatchRows key={`b${item.batch.id}`} batch={item.batch} onOpenJob={setOpenJob} />
                ) : item.job ? (
                  <JobRow
                    key={`j${item.job.id}`}
                    job={item.job}
                    onOpen={() => setOpenJob(item.job)}
                  />
                ) : null,
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {!isLoading && data?.items.length === 0 && (
          <Text c="dimmed" ta="center" p="lg">
            Nothing printed yet.
          </Text>
        )}
      </Card>
      {data && data.total > PAGE_SIZE && (
        <Group justify="center">
          <Pagination total={Math.ceil(data.total / PAGE_SIZE)} value={page} onChange={setPage} />
        </Group>
      )}
      <JobDrawer job={openJob} onClose={() => setOpenJob(null)} />
    </Stack>
  )
}
