import {
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Grid,
  Group,
  NumberInput,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import { useLocalStorage } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconArrowLeft, IconFileSpreadsheet, IconPrinter, IconForms } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { useLabel, useLabelVariables, usePrint } from '../api/hooks'
import type { VariableDef } from '../api/types'
import { PreviewPanel } from '../components/PreviewPanel'
import { useSelectedPrinter } from '../components/printerContext'
import { useTemplatePreview } from '../components/useTemplatePreview'
import { VariableFields } from '../components/VariableFields'
import { errorMessage } from '../utils/format'
import { initialValues, variableErrors } from '../utils/templating'
import { MassPrint } from './MassPrint'

function SinglePrint({ labelId, definitions }: { labelId: number; definitions: VariableDef[] }) {
  const { printer } = useSelectedPrinter()
  const print = usePrint()
  const [remember, setRemember] = useLocalStorage({
    key: 'zebra-web:remember-template-values',
    defaultValue: true,
  })
  const [stored, setStored] = useLocalStorage<Record<string, string>>({
    key: `zebra-web:template:${labelId}`,
    defaultValue: {},
  })
  const [values, setValues] = useState<Record<string, string>>(() => ({
    ...initialValues(definitions),
    ...(remember ? stored : {}),
  }))
  const [copies, setCopies] = useState(1)
  const [submitted, setSubmitted] = useState(false)
  const preview = useTemplatePreview(labelId, values)

  useEffect(() => {
    if (remember) setStored(values)
  }, [values, remember, setStored])

  async function submit() {
    setSubmitted(true)
    if (Object.keys(variableErrors(definitions, values)).length > 0) return
    try {
      const job = await print.mutateAsync({
        label_id: labelId,
        variables: values,
        copies,
        printer_id: printer?.id,
        source: 'template',
      })
      if (job.status === 'sent') {
        notifications.show({ color: 'green', message: `Printed on ${job.printer_name}` })
      } else {
        notifications.show({ color: 'red', title: 'Printing failed', message: job.error })
      }
    } catch (error) {
      notifications.show({ color: 'red', title: 'Printing failed', message: errorMessage(error) })
    }
  }

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Card withBorder>
          <Stack>
            <VariableFields
              definitions={definitions}
              values={values}
              onChange={setValues}
              showErrors={submitted}
              showBuiltins
            />
            <Group align="flex-end">
              <NumberInput
                label="Copies"
                min={1}
                max={1000}
                w={110}
                value={copies}
                onChange={(v) => setCopies(Number(v) || 1)}
              />
              <Button
                leftSection={<IconPrinter size={16} />}
                onClick={submit}
                loading={print.isPending}
                disabled={!printer}
              >
                Print{printer ? ` on ${printer.name}` : ''}
              </Button>
            </Group>
            <Group justify="space-between">
              <Checkbox
                size="xs"
                label="Remember last values"
                checked={remember}
                onChange={(e) => setRemember(e.currentTarget.checked)}
              />
              <Button
                size="xs"
                variant="subtle"
                onClick={() => {
                  setValues(initialValues(definitions))
                  setSubmitted(false)
                }}
              >
                Reset to defaults
              </Button>
            </Group>
          </Stack>
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 7 }}>
        <Card withBorder>
          <Text size="xs" c="dimmed" mb="xs">
            Live preview
          </Text>
          <PreviewPanel preview={preview.data} loading={preview.isFetching} error={preview.error} />
        </Card>
      </Grid.Col>
    </Grid>
  )
}

export function TemplatePrintPage() {
  const labelId = Number(useParams().labelId)
  const { data: label } = useLabel(labelId)
  const { data: definitions, isLoading } = useLabelVariables(labelId)
  const [tab, setTab] = useState<string | null>('single')

  return (
    <Stack>
      <Group gap="xs">
        <Anchor component={Link} to="/templates" aria-label="Back to templates">
          <IconArrowLeft size={20} />
        </Anchor>
        <Title order={2}>{label?.name ?? 'Template'}</Title>
        {label && (
          <Badge variant="light">
            {label.kind === 'design' ? 'Design' : 'ZPL'}
            {label.width_mm && label.height_mm
              ? ` · ${label.width_mm} × ${label.height_mm} mm`
              : ''}
          </Badge>
        )}
      </Group>
      {!isLoading && definitions && definitions.length === 0 && (
        <Text c="dimmed">This label has no variables, so there is nothing to fill in.</Text>
      )}
      {definitions && definitions.length > 0 && (
        <Tabs value={tab} onChange={setTab} keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="single" leftSection={<IconForms size={16} />}>
              Single label
            </Tabs.Tab>
            <Tabs.Tab value="mass" leftSection={<IconFileSpreadsheet size={16} />}>
              Mass print from data file
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="single">
            <SinglePrint labelId={labelId} definitions={definitions} />
          </Tabs.Panel>
          <Tabs.Panel value="mass">
            <MassPrint
              labelId={labelId}
              labelName={label?.name ?? 'labels'}
              definitions={definitions}
            />
          </Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  )
}
