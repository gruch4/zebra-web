import { Badge, Group, SimpleGrid, Text, TextInput } from '@mantine/core'

import type { VariableDef } from '../api/types'
import { variableErrors } from '../utils/templating'

interface VariableFieldsProps {
  definitions: VariableDef[]
  values: Record<string, string>
  onChange: (values: Record<string, string>) => void
  showErrors?: boolean
  showBuiltins?: boolean
}

export function VariableFields({
  definitions,
  values,
  onChange,
  showErrors = false,
  showBuiltins = false,
}: VariableFieldsProps) {
  const errors = variableErrors(definitions, values)
  return (
    <>
      <SimpleGrid cols={{ base: 1, sm: definitions.length > 3 ? 2 : 1 }}>
        {definitions.map((definition) => {
          const value = values[definition.name] ?? ''
          const error = errors[definition.name]
          const visibleError = error && (showErrors || (value !== '' && error !== 'is required'))
          return (
            <TextInput
              key={definition.name}
              label={definition.label || definition.name}
              description={
                definition.help || (definition.label ? `{{${definition.name}}}` : undefined)
              }
              placeholder={definition.default || undefined}
              withAsterisk={definition.required && !definition.default}
              type={definition.type === 'date' ? 'date' : 'text'}
              inputMode={definition.type === 'number' ? 'decimal' : undefined}
              value={value}
              error={visibleError ? `${definition.label || definition.name} ${error}` : undefined}
              onChange={(event) =>
                onChange({ ...values, [definition.name]: event.currentTarget.value })
              }
            />
          )
        })}
      </SimpleGrid>
      {showBuiltins && (
        <Group gap={6} mt="sm">
          <Text size="xs" c="dimmed">
            Filled automatically:
          </Text>
          {['date', 'time', 'datetime', 'year'].map((name) => (
            <Badge key={name} size="xs" variant="light" color="gray">{`{{${name}}}`}</Badge>
          ))}
        </Group>
      )}
    </>
  )
}
