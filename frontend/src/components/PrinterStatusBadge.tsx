import { Badge, Tooltip } from '@mantine/core'

import { usePrinterStatus } from '../api/hooks'

export function PrinterStatusBadge({ printerId }: { printerId: number | null | undefined }) {
  const { data, isLoading } = usePrinterStatus(printerId)
  if (printerId == null) return null
  if (isLoading || !data) {
    return (
      <Badge color="gray" variant="light">
        Checking…
      </Badge>
    )
  }
  if (!data.online) {
    return (
      <Tooltip label={data.error ?? 'Printer unreachable'}>
        <Badge color="red" variant="filled">
          Offline
        </Badge>
      </Tooltip>
    )
  }
  if (!data.ready) {
    return (
      <Tooltip label={data.problems.join(', ')}>
        <Badge color="orange" variant="filled">
          {data.problems[0] ?? 'Not ready'}
        </Badge>
      </Tooltip>
    )
  }
  return (
    <Badge color="green" variant="filled">
      Ready
    </Badge>
  )
}
