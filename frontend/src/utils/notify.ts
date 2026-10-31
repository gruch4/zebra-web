import { notifications } from '@mantine/notifications'

import type { PrintJob } from '../api/types'
import { errorMessage } from './format'

/** Show the outcome of a print request; returns true when the job was sent. */
export async function notifyPrint(request: Promise<PrintJob>): Promise<boolean> {
  try {
    const job = await request
    if (job.status === 'sent') {
      notifications.show({ color: 'green', message: `Sent to ${job.printer_name}` })
      return true
    }
    notifications.show({ color: 'red', title: 'Printing failed', message: job.error })
  } catch (error) {
    notifications.show({ color: 'red', title: 'Printing failed', message: errorMessage(error) })
  }
  return false
}
