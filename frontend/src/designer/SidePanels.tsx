import {
  ActionIcon,
  Button,
  Card,
  Checkbox,
  Group,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import {
  IconArrowDown,
  IconArrowUp,
  IconCopy,
  IconPlus,
  IconTrash,
  IconVariablePlus,
} from '@tabler/icons-react'
import { useState } from 'react'

import type { VariableDef, VariableType } from '../api/types'
import { ELEMENT_LABELS, insertVariable, newId } from './elements'
import type { DesignerAction } from './store'
import type { DesignElement } from './types'

function summary(element: DesignElement): string {
  if (element.name) return element.name
  if (element.type === 'text') return element.text
  if ('data' in element && element.type !== 'image') return element.data
  return ''
}

export function LayersPanel({
  elements,
  selectedId,
  dispatch,
}: {
  elements: DesignElement[]
  selectedId: string | null
  dispatch: (action: DesignerAction) => void
}) {
  if (elements.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No elements yet. Add one from the toolbox.
      </Text>
    )
  }
  return (
    <ScrollArea.Autosize mah={420}>
      <Stack gap={4}>
        {[...elements].reverse().map((element) => (
          <Card
            key={element.id}
            withBorder
            p={6}
            bg={element.id === selectedId ? 'var(--mantine-color-blue-light)' : undefined}
          >
            <Group justify="space-between" wrap="nowrap" gap={4}>
              <UnstyledButton
                style={{ flex: 1, minWidth: 0 }}
                onClick={() => dispatch({ type: 'select', id: element.id })}
              >
                <Text size="sm" fw={500}>
                  {ELEMENT_LABELS[element.type]}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {summary(element) || `${element.x}, ${element.y}`}
                </Text>
              </UnstyledButton>
              <Group gap={0} wrap="nowrap">
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  aria-label="Bring forward"
                  onClick={() => dispatch({ type: 'reorder', id: element.id, direction: 'up' })}
                >
                  <IconArrowUp size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  aria-label="Send backward"
                  onClick={() => dispatch({ type: 'reorder', id: element.id, direction: 'down' })}
                >
                  <IconArrowDown size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  aria-label="Duplicate"
                  onClick={() => dispatch({ type: 'duplicate', id: element.id, newId: newId() })}
                >
                  <IconCopy size={14} />
                </ActionIcon>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  aria-label="Delete"
                  onClick={() => dispatch({ type: 'remove', id: element.id })}
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            </Group>
          </Card>
        ))}
      </Stack>
    </ScrollArea.Autosize>
  )
}

export function VariablesPanel({
  variables,
  onChange,
  selected,
  dispatch,
}: {
  variables: VariableDef[]
  onChange: (variables: VariableDef[]) => void
  selected: DesignElement | undefined
  dispatch: (action: DesignerAction) => void
}) {
  const [newName, setNewName] = useState('')
  const validName = /^[A-Za-z_][A-Za-z0-9_.-]*$/.test(newName)

  function insert(name: string) {
    if (!selected) return
    const patch = insertVariable(selected, name)
    if (patch) dispatch({ type: 'update', id: selected.id, patch })
  }

  function update(name: string, patch: Partial<VariableDef>) {
    onChange(variables.map((v) => (v.name === name ? { ...v, ...patch } : v)))
  }

  const canInsert = !!selected && insertVariable(selected, 'name') !== null

  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">
        Variables are placeholders like {'{{name}}'} in text or barcode data. Their values are asked
        for when printing from a template.
      </Text>
      <Group gap="xs" align="flex-end" wrap="nowrap">
        <TextInput
          size="xs"
          label="New variable"
          placeholder="product_name"
          value={newName}
          error={newName && !validName ? 'Letters, digits, _ . -' : undefined}
          onChange={(e) => setNewName(e.currentTarget.value.trim())}
          style={{ flex: 1 }}
        />
        <Tooltip
          label={canInsert ? 'Insert into the selected element' : 'Select a text or code element'}
        >
          <Button
            size="xs"
            leftSection={<IconPlus size={14} />}
            disabled={!validName || !canInsert}
            onClick={() => {
              insert(newName)
              setNewName('')
            }}
          >
            Insert
          </Button>
        </Tooltip>
      </Group>
      {variables.length === 0 && (
        <Text size="sm" c="dimmed">
          This design has no variables.
        </Text>
      )}
      {variables.map((variable) => (
        <Card key={variable.name} withBorder p="xs">
          <Group justify="space-between" mb={4}>
            <Text size="sm" ff="monospace" fw={600}>{`{{${variable.name}}}`}</Text>
            <Tooltip label="Insert into the selected element">
              <ActionIcon
                size="sm"
                variant="subtle"
                disabled={!canInsert}
                aria-label={`Insert ${variable.name}`}
                onClick={() => insert(variable.name)}
              >
                <IconVariablePlus size={14} />
              </ActionIcon>
            </Tooltip>
          </Group>
          <Stack gap={4}>
            <TextInput
              size="xs"
              placeholder="Label shown in the form"
              value={variable.label}
              onChange={(e) => update(variable.name, { label: e.currentTarget.value })}
            />
            <Group gap={4} grow>
              <TextInput
                size="xs"
                placeholder="Default value"
                value={variable.default}
                onChange={(e) => update(variable.name, { default: e.currentTarget.value })}
              />
              <Select
                size="xs"
                data={['text', 'number', 'date']}
                value={variable.type}
                onChange={(v) => v && update(variable.name, { type: v as VariableType })}
                aria-label="Type"
              />
            </Group>
            <Checkbox
              size="xs"
              label="Required"
              checked={variable.required}
              onChange={(e) => update(variable.name, { required: e.currentTarget.checked })}
            />
          </Stack>
        </Card>
      ))}
    </Stack>
  )
}
