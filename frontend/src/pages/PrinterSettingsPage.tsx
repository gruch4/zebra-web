import {
  Accordion,
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconDeviceFloppy,
  IconRefresh,
} from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import {
  useLabelSettingsGroups,
  usePrinterActions,
  usePrinterSettings,
  usePrinterStatus,
  usePrinters,
  useRawSettings,
  useRefreshPrinterSettings,
  useRunAction,
  useUpdateLabelSettings,
  useWriteSettings,
} from '../api/hooks'
import type { Printer, PrinterSetting, SettingSource } from '../api/types'
import { errorMessage } from '../utils/format'
import {
  type SettingsForm,
  changedSettings,
  describeChoices,
  displayLimits,
  formatDeviceInfo,
  fromDisplay,
  isLengthField,
  settingsToForm,
  speedOptions,
  toDisplay,
  validateDisplay,
} from '../utils/printerSettings'
import { dotsToMm } from '../utils/units'

const DESTRUCTIVE = new Set(['factory_defaults', 'reset', 'cancel_all'])

const SELECTS: Record<string, { value: string; label: string }[]> = {
  media_tracking: [
    { value: 'gap', label: 'Gap / notch (labels)' },
    { value: 'mark', label: 'Black mark' },
    { value: 'continuous', label: 'Continuous' },
    { value: 'variable', label: 'Continuous, variable length' },
  ],
  print_method: [
    { value: 'transfer', label: 'Thermal transfer (ribbon)' },
    { value: 'direct', label: 'Direct thermal' },
  ],
  print_mode: [
    { value: 'tear', label: 'Tear off' },
    { value: 'peel', label: 'Peel off' },
    { value: 'rewind', label: 'Rewind' },
    { value: 'cutter', label: 'Cutter' },
    { value: 'delayed_cut', label: 'Delayed cut' },
    { value: 'applicator', label: 'Applicator' },
    { value: 'kiosk', label: 'Kiosk' },
  ],
  orientation: [
    { value: 'normal', label: 'Normal' },
    { value: 'inverted', label: 'Inverted (180°)' },
  ],
}

function StatusCard({ printerId, dpi }: { printerId: number; dpi: number }) {
  const { data, isLoading } = usePrinterStatus(printerId, 5000)
  if (isLoading || !data) return <Loader size="sm" />
  if (!data.online) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={16} />} title="Printer offline">
        {data.error}
      </Alert>
    )
  }
  const details = data.details ?? {}
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Badge color={data.ready ? 'green' : 'orange'} size="lg">
          {data.ready ? 'Ready' : 'Not ready'}
        </Badge>
        {data.problems.map((problem) => (
          <Badge key={problem} color="orange" variant="light">
            {problem}
          </Badge>
        ))}
      </Group>
      <Text size="sm">
        Media: {details.thermal_transfer ? 'thermal transfer' : 'direct thermal'} · mode{' '}
        {String(details.print_mode ?? '?')} · label length{' '}
        {typeof details.label_length === 'number'
          ? `${dotsToMm(details.label_length, dpi)} mm`
          : '?'}{' '}
        · formats in buffer {String(details.formats_in_buffer ?? 0)}
      </Text>
    </Stack>
  )
}

function SettingInput({
  setting,
  form,
  setForm,
  errors,
  dpi,
}: {
  setting: PrinterSetting
  form: SettingsForm
  setForm: (form: SettingsForm) => void
  errors: Record<string, string>
  dpi: number
}) {
  const key = setting.name as keyof SettingsForm
  const value = form[key]
  const choices = describeChoices(key, setting.choices, dpi)
  const description = [
    choices ? `Allowed: ${choices}` : null,
    setting.value == null ? 'Not reported by this printer' : null,
  ]
    .filter(Boolean)
    .join(' · ')
  if (key === 'speed') {
    return (
      <Select
        label={`${setting.label} (mm/s)`}
        description={description}
        data={speedOptions(setting.choices)}
        value={value == null ? null : String(value)}
        onChange={(v) => setForm({ ...form, speed: v == null ? null : Number(v) })}
      />
    )
  }
  if (SELECTS[key]) {
    return (
      <Select
        label={setting.label}
        description={description}
        data={SELECTS[key]}
        value={(value as string | null) ?? null}
        onChange={(v) => setForm({ ...form, [key]: v })}
      />
    )
  }
  const length = isLengthField(key)
  const limits = displayLimits(key, dpi)
  return (
    <NumberInput
      label={length ? `${setting.label} (mm)` : setting.label}
      description={description}
      min={limits?.min}
      max={limits?.max}
      allowDecimal={length}
      decimalScale={length ? 2 : 0}
      step={length ? 0.5 : 1}
      value={(value as number | null) ?? ''}
      error={errors[key]}
      onChange={(v) => setForm({ ...form, [key]: v === '' ? null : Number(v) })}
    />
  )
}

// Control commands use the tilde prefix; the rest are format commands.
const TILDE_COMMANDS = new Set(['SD', 'TA', 'JS'])

function LabelSettingsCard({ printer }: { printer: Printer }) {
  const { data: groups = [] } = useLabelSettingsGroups()
  const update = useUpdateLabelSettings(printer.id)
  return (
    <Card withBorder mt="md">
      <Title order={4}>Printer settings inside labels</Title>
      <Text size="sm" c="dimmed" mb="sm">
        Labels from design software often contain printer settings. Choose which ones are taken from
        the label and which this printer replaces with its own settings. Commands that change the
        printer permanently (^JUS) or calibrate or reset it are never sent.
      </Text>
      <Stack gap="sm">
        {groups.map((group) => (
          <Group key={group.group} justify="space-between" wrap="nowrap">
            <div>
              <Text size="sm" fw={500}>
                {group.title}
              </Text>
              <Text size="xs" c="dimmed" ff="monospace">
                {group.commands
                  .map((code) => `${TILDE_COMMANDS.has(code) ? '~' : '^'}${code}`)
                  .join(' ')}
              </Text>
            </div>
            <SegmentedControl
              size="xs"
              aria-label={group.title}
              data={[
                { value: 'label', label: 'From label' },
                { value: 'printer', label: 'From printer' },
              ]}
              value={printer.label_settings[group.group] ?? group.default}
              onChange={async (value) => {
                try {
                  await update.mutateAsync({ [group.group]: value as SettingSource })
                } catch (error) {
                  notifications.show({
                    color: 'red',
                    title: 'Saving failed',
                    message: errorMessage(error),
                  })
                }
              }}
            />
          </Group>
        ))}
      </Stack>
    </Card>
  )
}

function RawSettings({ printerId, enabled }: { printerId: number; enabled: boolean }) {
  const { data = [], isLoading, error } = useRawSettings(printerId, enabled)
  const [search, setSearch] = useState('')
  const rows = useMemo(
    () =>
      data.filter((row) =>
        `${row.key} ${row.value}`.toLowerCase().includes(search.trim().toLowerCase()),
      ),
    [data, search],
  )
  if (isLoading) return <Loader size="sm" />
  if (error) return <Alert color="red">{errorMessage(error)}</Alert>
  return (
    <Stack>
      <TextInput
        placeholder="Search settings…"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      <Table.ScrollContainer minWidth={600} maxHeight={500}>
        <Table striped stickyHeader>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Key</Table.Th>
              <Table.Th>Value</Table.Th>
              <Table.Th>Choices</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.key}>
                <Table.Td ff="monospace">{row.key}</Table.Td>
                <Table.Td>{row.value}</Table.Td>
                <Table.Td c="dimmed">{row.choices}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}

export function PrinterSettingsPage() {
  const printerId = Number(useParams().id)
  const { data: printers = [] } = usePrinters()
  const printer = printers.find((p) => p.id === printerId)
  const settings = usePrinterSettings(printerId)
  const { data: actions = [] } = usePrinterActions()
  const write = useWriteSettings(printerId)
  const refresh = useRefreshPrinterSettings(printerId)
  const runAction = useRunAction(printerId)
  const [rawOpen, setRawOpen] = useState<string | null>(null)

  const dpi = printer?.dpi ?? 203
  // `initial` is in printer units (dots); the form shows lengths in millimetres.
  const initial = useMemo(
    () => (settings.data ? settingsToForm(settings.data.settings) : null),
    [settings.data],
  )
  const initialDisplay = useMemo(() => (initial ? toDisplay(initial, dpi) : null), [initial, dpi])
  const [edits, setEdits] = useState<Partial<SettingsForm>>({})
  const form = initialDisplay ? { ...initialDisplay, ...edits } : null
  const setForm = (next: SettingsForm) =>
    setEdits(
      Object.fromEntries(
        Object.entries(next).filter(
          ([key, value]) => value !== initialDisplay?.[key as keyof SettingsForm],
        ),
      ),
    )

  const errors = form ? validateDisplay(form, dpi) : {}
  const changes = form && initial ? changedSettings(initial, fromDisplay(form, dpi)) : {}
  const dirty = Object.keys(changes).length > 0

  async function save() {
    if (Object.keys(errors).length > 0) return
    try {
      await write.mutateAsync(changes)
      setEdits({})
      notifications.show({ color: 'green', message: 'Settings saved to the printer' })
    } catch (error) {
      notifications.show({ color: 'red', title: 'Saving failed', message: errorMessage(error) })
    }
  }

  function trigger(action: string, description: string) {
    const run = async () => {
      try {
        await runAction.mutateAsync(action)
        notifications.show({ color: 'green', message: `${description}: sent` })
      } catch (error) {
        notifications.show({ color: 'red', title: description, message: errorMessage(error) })
      }
    }
    if (!DESTRUCTIVE.has(action)) return void run()
    modals.openConfirmModal({
      title: description,
      children: <Text size="sm">Are you sure? This affects the printer immediately.</Text>,
      labels: { confirm: 'Continue', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: run,
    })
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Anchor component={Link} to="/printers" aria-label="Back to printers">
            <IconArrowLeft size={20} />
          </Anchor>
          <Title order={2}>{printer?.name ?? 'Printer'}</Title>
          {printer && (
            <Text c="dimmed">
              {printer.host}:{printer.port} · {printer.dpi} dpi
            </Text>
          )}
        </Group>
      </Group>
      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder>
            <Group justify="space-between" mb="sm">
              <Group gap="xs">
                <Title order={4}>Settings</Title>
                <Tooltip label="Read the settings from the printer again">
                  <ActionIcon
                    variant="subtle"
                    aria-label="Refresh settings"
                    loading={refresh.isPending}
                    onClick={() => refresh.mutate()}
                  >
                    <IconRefresh size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
              <Button
                leftSection={<IconDeviceFloppy size={16} />}
                onClick={save}
                disabled={!dirty || Object.keys(errors).length > 0}
                loading={write.isPending}
              >
                Save to printer
              </Button>
            </Group>
            {settings.isLoading && (
              <Group gap="xs">
                <Loader size="sm" />
                <Text size="sm" c="dimmed">
                  Reading the settings from the printer, this can take a few seconds…
                </Text>
              </Group>
            )}
            {settings.error && (
              <Alert color="red" title="Cannot read settings">
                {errorMessage(settings.error)}
              </Alert>
            )}
            {settings.data && form && (
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                {settings.data.settings.map((setting) => (
                  <SettingInput
                    key={setting.name}
                    setting={setting}
                    form={form}
                    setForm={setForm}
                    errors={errors}
                    dpi={dpi}
                  />
                ))}
              </SimpleGrid>
            )}
            <Text size="xs" c="dimmed" mt="md">
              Changes are applied with ZPL commands and stored permanently with ^JUS.
            </Text>
          </Card>
          {printer && <LabelSettingsCard printer={printer} />}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack>
            <Card withBorder>
              <Title order={4} mb="sm">
                Status
              </Title>
              <StatusCard printerId={printerId} dpi={dpi} />
            </Card>
            <Card withBorder>
              <Title order={4} mb="sm">
                Calibration & actions
              </Title>
              <SimpleGrid cols={2}>
                {actions.map(({ action, description }) => (
                  <Button
                    key={action}
                    variant={DESTRUCTIVE.has(action) ? 'light' : 'default'}
                    color={DESTRUCTIVE.has(action) ? 'red' : undefined}
                    onClick={() => trigger(action, description)}
                    styles={{ label: { whiteSpace: 'normal', textAlign: 'center' } }}
                    h="auto"
                    py={8}
                  >
                    {description}
                  </Button>
                ))}
              </SimpleGrid>
            </Card>
            {settings.data && (
              <Card withBorder>
                <Title order={4} mb="sm">
                  Device
                </Title>
                <Table>
                  <Table.Tbody>
                    {Object.entries(settings.data.info).map(([key, value]) => (
                      <Table.Tr key={key}>
                        <Table.Td c="dimmed">{key.replace(/_/g, ' ')}</Table.Td>
                        <Table.Td>{formatDeviceInfo(key, value)}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Card>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
      <Accordion variant="contained" value={rawOpen} onChange={setRawOpen}>
        <Accordion.Item value="raw">
          <Accordion.Control>All printer settings (SGD)</Accordion.Control>
          <Accordion.Panel>
            <RawSettings printerId={printerId} enabled={rawOpen === 'raw'} />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  )
}
