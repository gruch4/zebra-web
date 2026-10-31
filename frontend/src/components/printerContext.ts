import { createContext, useContext } from 'react'

import type { Printer } from '../api/types'

export interface PrinterContextValue {
  printers: Printer[]
  printer: Printer | null
  setPrinterId: (id: number | null) => void
}

export const PrinterContext = createContext<PrinterContextValue>({
  printers: [],
  printer: null,
  setPrinterId: () => undefined,
})

export function useSelectedPrinter(): PrinterContextValue {
  return useContext(PrinterContext)
}
