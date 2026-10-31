import { Button, Group, NumberInput, Stack, Text } from '@mantine/core'
import { useState } from 'react'

import type { VariableDef } from '../api/types'
import { initialValues, variableErrors } from '../utils/templating'
import { useSelectedPrinter } from './printerContext'
import { VariableFields } from './VariableFields'

interface PrintFormProps {
  definitions: VariableDef[]
  loading: boolean
  onPrint: (values: Record<string, string>, copies: number) => void
}

/** Variable values + copies; state is initialised from the definitions when mounted. */
export function PrintForm({ definitions, loading, onPrint }: PrintFormProps) {
  const { printer } = useSelectedPrinter()
  const [values, setValues] = useState(() => initialValues(definitions))
  const [copies, setCopies] = useState(1)
  const [submitted, setSubmitted] = useState(false)

  function submit() {
    setSubmitted(true)
    if (Object.keys(variableErrors(definitions, values)).length === 0) onPrint(values, copies)
  }

  return (
    <Stack>
      {definitions.length > 0 ? (
        <VariableFields
          definitions={definitions}
          values={values}
          onChange={setValues}
          showErrors={submitted}
        />
      ) : (
        <Text size="sm" c="dimmed">
          This label has no template variables.
        </Text>
      )}
      <NumberInput
        label="Copies"
        min={1}
        max={1000}
        value={copies}
        onChange={(value) => setCopies(Number(value) || 1)}
      />
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Printer: {printer?.name ?? 'none configured'}
        </Text>
        <Button onClick={submit} loading={loading} disabled={!printer}>
          Print
        </Button>
      </Group>
    </Stack>
  )
}
