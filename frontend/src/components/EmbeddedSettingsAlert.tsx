import { Alert, Anchor, Badge, Button, Checkbox, Group, Stack, Text, Tooltip } from '@mantine/core'
import { IconAdjustments } from '@tabler/icons-react'
import { Link } from 'react-router'

import type { EmbeddedSetting, PrinterSettingsInZpl } from '../api/types'

interface EmbeddedSettingsAlertProps {
  settings: PrinterSettingsInZpl
  printerId: number | null | undefined
  keepAll: boolean
  onKeepAllChange: (keep: boolean) => void
  onRemoveReplaced: () => void
}

function SettingBadges({ items, replaced }: { items: EmbeddedSetting[]; replaced?: boolean }) {
  return (
    <Group gap={6}>
      {items.map((setting, i) => (
        <Tooltip key={`${setting.command}-${i}`} label={setting.description}>
          <Badge
            variant="outline"
            color={replaced ? 'yellow' : 'gray'}
            tt="none"
            ff="monospace"
            td={replaced ? 'line-through' : undefined}
          >
            {setting.command}
          </Badge>
        </Tooltip>
      ))}
    </Group>
  )
}

/** Which printer settings embedded in the ZPL are used and which the printer replaces. */
export function EmbeddedSettingsAlert({
  settings,
  printerId,
  keepAll,
  onKeepAllChange,
  onRemoveReplaced,
}: EmbeddedSettingsAlertProps) {
  const { kept, removed } = settings
  if (kept.length === 0 && removed.length === 0) return null
  return (
    <Alert
      color={removed.length > 0 && !keepAll ? 'yellow' : 'blue'}
      icon={<IconAdjustments size={16} />}
      title="Printer settings in this ZPL"
    >
      <Stack gap="xs">
        {kept.length > 0 && (
          <div>
            <Text size="sm" mb={4}>
              Used from the label:
            </Text>
            <SettingBadges items={kept} />
          </div>
        )}
        {removed.length > 0 && (
          <div>
            <Text size="sm" mb={4}>
              {keepAll
                ? 'Also sent (you chose to send all settings unchanged):'
                : 'Replaced by the printer’s own settings:'}
            </Text>
            <SettingBadges items={removed} replaced={!keepAll} />
          </div>
        )}
        <Text size="xs" c="dimmed">
          {printerId != null ? (
            <Anchor component={Link} to={`/printers/${printerId}`} size="xs">
              Choose which settings come from the label
            </Anchor>
          ) : (
            'Which settings come from the label is configured per printer.'
          )}
        </Text>
        {removed.length > 0 && (
          <Group justify="space-between">
            <Checkbox
              size="xs"
              label="Send all settings unchanged"
              checked={keepAll}
              onChange={(e) => onKeepAllChange(e.currentTarget.checked)}
            />
            <Button size="xs" variant="light" color="yellow" onClick={onRemoveReplaced}>
              Remove replaced settings from editor
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  )
}
