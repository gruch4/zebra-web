import { useLocalStorage } from '@mantine/hooks'
import { type ReactNode, useMemo } from 'react'

import { usePrinters } from '../api/hooks'
import { PrinterContext } from './printerContext'

export function PrinterProvider({ children }: { children: ReactNode }) {
  const { data: printers = [] } = usePrinters()
  const [selectedId, setSelectedId] = useLocalStorage<number | null>({
    key: 'zebra-web:printer',
    defaultValue: null,
  })
  const value = useMemo(() => {
    const printer =
      printers.find((p) => p.id === selectedId) ??
      printers.find((p) => p.is_default) ??
      printers[0] ??
      null
    return { printers, printer, setPrinterId: setSelectedId }
  }, [printers, selectedId, setSelectedId])
  return <PrinterContext.Provider value={value}>{children}</PrinterContext.Provider>
}
