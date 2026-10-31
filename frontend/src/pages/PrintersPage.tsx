import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import { IconEdit, IconPlugConnected, IconPlus, IconSettings, IconTrash } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { useDeletePrinter, usePrinters, useSavePrinter, useTestConnection } from '../api/hooks'
import type { Printer, PrinterInput } from '../api/types'
import { PrinterStatusBadge } from '../components/PrinterStatusBadge'
import { errorMessage } from '../utils/format'

const EMPTY: PrinterInput = { name: '', host: '', port: 9100, dpi: 203, is_default: false }

function PrinterModal({
  printer,
  opened,
  onClose,
}: {
  printer: Printer | null
  opened: boolean
  onClose: () => void
}) {
  return (
    <Modal opened={opened} onClose={onClose} title={printer ? 'Edit printer' : 'Add printer'}>
      {opened && <PrinterForm printer={printer} onClose={onClose} />}
    </Modal>
  )
}

function PrinterForm({ printer, onClose }: { printer: Printer | null; onClose: () => void }) {
  const save = useSavePrinter()
  const test = useTestConnection()
  const [form, setForm] = useState<PrinterInput>(() => (printer ? { ...printer } : EMPTY))

  async function runTest() {
    const result = await test.mutateAsync({ host: form.host, port: form.port })
    if (result.ok) {
      setForm((current) => ({
        ...current,
        dpi: result.dpi ?? current.dpi,
        model: result.model,
        firmware: result.firmware,
        name: current.name || result.model || current.name,
      }))
    }
  }

  async function submit() {
    try {
      await save.mutateAsync({ ...form, id: printer?.id })
      notifications.show({ color: 'green', message: `Saved printer ${form.name}` })
      onClose()
    } catch (error) {
      notifications.show({ color: 'red', title: 'Saving failed', message: errorMessage(error) })
    }
  }

  const valid = form.name.trim() && form.host.trim() && form.port > 0

  return (
    <Stack>
      <TextInput
        label="Name"
        required
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
      />
      <Group grow align="flex-start">
        <TextInput
          label="Host / IP address"
          required
          placeholder="192.168.1.50"
          value={form.host}
          onChange={(e) => setForm({ ...form, host: e.currentTarget.value.trim() })}
        />
        <NumberInput
          label="Port"
          min={1}
          max={65535}
          value={form.port}
          onChange={(v) => setForm({ ...form, port: Number(v) || 9100 })}
        />
      </Group>
      <Select
        label="Resolution"
        data={[
          { value: '203', label: '203 dpi (8 dots/mm)' },
          { value: '300', label: '300 dpi (12 dots/mm)' },
          { value: '600', label: '600 dpi (24 dots/mm)' },
        ]}
        value={String(form.dpi)}
        onChange={(v) => setForm({ ...form, dpi: Number(v ?? 203) })}
      />
      <Checkbox
        label="Default printer"
        checked={form.is_default}
        onChange={(e) => setForm({ ...form, is_default: e.currentTarget.checked })}
      />
      {test.data && (
        <Alert color={test.data.ok ? 'green' : 'red'}>
          {test.data.ok
            ? `Connected: ${test.data.model} (${test.data.firmware}), ${test.data.dpi} dpi`
            : test.data.error}
        </Alert>
      )}
      <Group justify="space-between">
        <Button
          variant="default"
          leftSection={<IconPlugConnected size={16} />}
          onClick={runTest}
          loading={test.isPending}
          disabled={!form.host}
        >
          Test connection
        </Button>
        <Button onClick={submit} loading={save.isPending} disabled={!valid}>
          Save
        </Button>
      </Group>
    </Stack>
  )
}

export function PrintersPage() {
  const { data: printers = [], isLoading } = usePrinters()
  const remove = useDeletePrinter()
  const [editing, setEditing] = useState<Printer | null>(null)
  const [opened, setOpened] = useState(false)

  function confirmDelete(printer: Printer) {
    modals.openConfirmModal({
      title: `Delete ${printer.name}?`,
      children: (
        <Text size="sm">Print history is kept, but it will no longer link to this printer.</Text>
      ),
      labels: { confirm: 'Delete', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () => remove.mutate(printer.id),
    })
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Printers</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setEditing(null)
            setOpened(true)
          }}
        >
          Add printer
        </Button>
      </Group>
      <Card withBorder p={0}>
        <Table.ScrollContainer minWidth={700}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Address</Table.Th>
                <Table.Th>Resolution</Table.Th>
                <Table.Th>Model</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {printers.map((printer) => (
                <Table.Tr key={printer.id}>
                  <Table.Td>
                    <Group gap="xs">
                      <Text component={Link} to={`/printers/${printer.id}`} fw={500}>
                        {printer.name}
                      </Text>
                      {printer.is_default && <Badge size="xs">Default</Badge>}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {printer.host}:{printer.port}
                  </Table.Td>
                  <Table.Td>{printer.dpi} dpi</Table.Td>
                  <Table.Td>{printer.model ?? '—'}</Table.Td>
                  <Table.Td>
                    <PrinterStatusBadge printerId={printer.id} />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Tooltip label="Settings & calibration">
                        <ActionIcon
                          variant="subtle"
                          component={Link}
                          to={`/printers/${printer.id}`}
                          aria-label="Settings"
                        >
                          <IconSettings size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <ActionIcon
                        variant="subtle"
                        aria-label="Edit"
                        onClick={() => {
                          setEditing(printer)
                          setOpened(true)
                        }}
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label="Delete"
                        onClick={() => confirmDelete(printer)}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {!isLoading && printers.length === 0 && (
          <Text c="dimmed" ta="center" p="lg">
            No printers yet. Add your Zebra by its IP address (raw port 9100).
          </Text>
        )}
      </Card>
      <PrinterModal printer={editing} opened={opened} onClose={() => setOpened(false)} />
    </Stack>
  )
}
