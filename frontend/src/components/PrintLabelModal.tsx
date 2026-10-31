import { Center, Loader, Modal } from '@mantine/core'

import { useLabelVariables, usePrint } from '../api/hooks'
import type { LabelSummary } from '../api/types'
import { useSelectedPrinter } from './printerContext'
import { notifyPrint } from '../utils/notify'
import { PrintForm } from './PrintForm'

interface PrintLabelModalProps {
  label: LabelSummary | null
  onClose: () => void
}

export function PrintLabelModal({ label, onClose }: PrintLabelModalProps) {
  const { printer } = useSelectedPrinter()
  const { data: definitions } = useLabelVariables(label?.id)
  const print = usePrint()

  return (
    <Modal opened={label !== null} onClose={onClose} title={`Print “${label?.name ?? ''}”`}>
      {label && definitions ? (
        <PrintForm
          key={label.id}
          definitions={definitions}
          loading={print.isPending}
          onPrint={async (variables, copies) => {
            const sent = await notifyPrint(
              print.mutateAsync({ label_id: label.id, printer_id: printer?.id, variables, copies }),
            )
            if (sent) onClose()
          }}
        />
      ) : (
        <Center p="md">
          <Loader size="sm" />
        </Center>
      )}
    </Modal>
  )
}
